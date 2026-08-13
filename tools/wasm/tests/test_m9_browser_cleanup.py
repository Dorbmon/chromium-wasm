#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for M9 browser process-group cleanup."""

from __future__ import annotations

from collections import deque
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

from tools.wasm.m0_common import M0Error
from tools.wasm import m9_browser_cleanup as cleanup


class _BrokenTextStream:
    def __iter__(self) -> _BrokenTextStream:
        return self

    def __next__(self) -> str:
        raise RuntimeError("reader broke")

    def close(self) -> None:
        return


class _BoundedReadTextStream(io.StringIO):
    """Text stream that proves the reader never asks for an unbounded read."""

    def __init__(self, value: str, maximum_read_chars: int):
        super().__init__(value)
        self.maximum_read_chars = maximum_read_chars
        self.read_sizes: list[int] = []

    def __iter__(self) -> _BoundedReadTextStream:
        raise AssertionError("BrowserStderrReader must use fixed-size read framing")

    def read(self, size: int = -1) -> str:
        self.read_sizes.append(size)
        if size < 0 or size > self.maximum_read_chars:
            raise AssertionError(f"unexpected unbounded read size: {size}")
        return super().read(size)


class _DrainFailureTextStream:
    """Overflow once, then make the cleanup-only drain itself fail."""

    def __init__(self):
        self._reads = 0

    def read(self, size: int = -1) -> str:
        self._reads += 1
        if self._reads == 1:
            return "xxxx"
        raise RuntimeError("drain read failed")

    def close(self) -> None:
        return


@unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
class M9BrowserCleanupTest(unittest.TestCase):
    def _start(self, source: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-c", source],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )

    def _reader(self, process: subprocess.Popen[str]) -> cleanup.BrowserStderrReader:
        self.assertIsNotNone(process.stderr)
        return cleanup.BrowserStderrReader(
            process.stderr,  # type: ignore[arg-type]
            deque(),
            name="m9-browser-cleanup-test-reader",
        )

    def _output_readers(
        self, process: subprocess.Popen[str]
    ) -> tuple[cleanup.BrowserStderrReader, cleanup.BrowserStderrReader]:
        self.assertIsNotNone(process.stdout)
        self.assertIsNotNone(process.stderr)
        return (
            cleanup.BrowserStderrReader(
                process.stdout,  # type: ignore[arg-type]
                deque(),
                name="m9-process-cleanup-test-stdout",
            ),
            cleanup.BrowserStderrReader(
                process.stderr,  # type: ignore[arg-type]
                deque(),
                name="m9-process-cleanup-test-stderr",
            ),
        )

    def test_clean_eof_and_absent_group_are_required_for_success(self) -> None:
        process = self._start("import sys; sys.stderr.write('diagnostic\\n')")
        reader = self._reader(process)
        reader.start()

        cleanup.stop_browser_group(process, reader)

        self.assertTrue(reader.reached_eof)
        self.assertFalse(reader.is_alive())
        self.assertIsNotNone(process.returncode)

    def test_same_group_descendant_cannot_be_reported_as_clean_success(self) -> None:
        # The leader exits immediately while a same-session child keeps the
        # inherited stderr FD open and ignores the cooperative signal.  The
        # cleanup must escalate to the whole retained group, then reject that
        # force-killed outcome.
        process = self._start(
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)']); "
            "time.sleep(0.2); sys.stderr.write('leader exiting\\n')"
        )
        reader = self._reader(process)
        reader.start()
        process.wait(timeout=2)
        with mock.patch.object(cleanup, "COOPERATIVE_STOP_SECONDS", 0.1), mock.patch.object(
            cleanup, "FORCED_STOP_SECONDS", 1.0
        ):
            with self.assertRaisesRegex(M0Error, "required SIGKILL"):
                cleanup.stop_browser_group(process, reader)

        self.assertFalse(reader.is_alive())

    def test_multi_pipe_group_rejects_a_reaped_term_ignoring_descendant(self) -> None:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, subprocess, sys, time; "
                "subprocess.Popen([sys.executable, '-c', "
                "'import signal, time; signal.signal(signal.SIGTERM, "
                "signal.SIG_IGN); time.sleep(30)'], stdin=subprocess.DEVNULL, "
                "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                "time.sleep(0.2); sys.stdout.write('leader exiting\\n'); "
                "sys.stdout.flush()",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout_reader, stderr_reader = self._output_readers(process)
        stdout_reader.start()
        stderr_reader.start()
        try:
            process.wait(timeout=2)
            with mock.patch.object(cleanup, "COOPERATIVE_STOP_SECONDS", 0.1), mock.patch.object(
                cleanup, "FORCED_STOP_SECONDS", 1.0
            ):
                with self.assertRaisesRegex(M0Error, "required SIGKILL"):
                    cleanup.stop_process_group(
                        process,
                        (stdout_reader, stderr_reader),
                        description="test relay",
                    )
            self.assertFalse(stdout_reader.is_alive())
            self.assertFalse(stderr_reader.is_alive())
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.pid, 0)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_abort_multi_pipe_group_closes_streams_without_reader_owners(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.assertIsNotNone(process.stdout)
        self.assertIsNotNone(process.stderr)
        stdout = process.stdout
        stderr = process.stderr
        try:
            cleanup.abort_process_group(
                process,
                (),
                description="test relay",
                unowned_streams=(stdout, stderr),  # type: ignore[arg-type]
            )
            self.assertTrue(stdout.closed)
            self.assertTrue(stderr.closed)
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.pid, 0)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_abort_browser_group_closes_a_pre_reader_stderr_pipe(self) -> None:
        process = self._start("import time; time.sleep(30)")
        self.assertIsNotNone(process.stderr)
        stderr = process.stderr
        try:
            cleanup.abort_browser_group(
                process,
                unowned_streams=(stderr,),  # type: ignore[arg-type]
            )
            self.assertTrue(stderr.closed)
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.pid, 0)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_probe_failure_after_sigterm_still_attempts_sigkill(self) -> None:
        browser = mock.Mock()
        browser.pid = 123
        browser.poll.return_value = 0
        reader = mock.Mock()
        reader.started = True
        reader.is_alive.return_value = False
        reader.error = None
        reader.reached_eof = True

        with (
            mock.patch.object(cleanup, "_signal_browser_group") as signal_group,
            mock.patch.object(
                cleanup,
                "_browser_group_exists",
                side_effect=[M0Error("group probe failed"), False],
            ),
            self.assertRaisesRegex(M0Error, "cannot verify M9 browser cleanup"),
        ):
            cleanup.stop_browser_group(browser, reader)

        self.assertEqual(
            [
                mock.call(browser, signal.SIGTERM),
                mock.call(browser, signal.SIGKILL),
            ],
            signal_group.call_args_list,
        )
        reader.close_after_reader_stops.assert_called_once_with()

    def test_live_reader_is_not_closed_when_forced_cleanup_is_incomplete(self) -> None:
        browser = mock.Mock()
        reader = mock.Mock()
        reader.started = True
        reader.is_alive.return_value = True
        reader.error = None
        reader.reached_eof = False

        with (
            mock.patch.object(cleanup, "_signal_browser_group"),
            mock.patch.object(
                cleanup,
                "_wait_for_browser_cleanup",
                side_effect=[(False, None), (False, None)],
            ),
            self.assertRaisesRegex(
                M0Error,
                "M9 browser process group or stderr reader did not stop",
            ),
        ):
            cleanup.stop_browser_group(browser, reader)

        reader.close_after_reader_stops.assert_not_called()
        reader.close_unstarted_pipe.assert_not_called()

    def test_abort_unstarted_reader_kills_the_retained_group(self) -> None:
        process = self._start(
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "time.sleep(30)"
        )
        reader = self._reader(process)
        try:
            with mock.patch.object(cleanup, "COOPERATIVE_STOP_SECONDS", 0.1), mock.patch.object(
                cleanup, "FORCED_STOP_SECONDS", 1.0
            ):
                cleanup.abort_browser_group(process, reader)
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.pid, 0)
        finally:
            # The method under test is expected to have closed this stream;
            # tolerate an already-dead process while keeping failure cleanup
            # bounded if the assertion itself fails.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_abort_rejects_a_started_reader_exception(self) -> None:
        process = self._start("import time; time.sleep(30)")
        reader = cleanup.BrowserStderrReader(
            _BrokenTextStream(),  # type: ignore[arg-type]
            deque(),
            name="m9-browser-cleanup-broken-reader",
        )
        reader.start()
        deadline = time.monotonic() + 2
        while reader.is_alive() and time.monotonic() < deadline:
            reader.join(timeout=0.05)
        try:
            with self.assertRaisesRegex(M0Error, "cannot verify M9 browser abort cleanup"):
                cleanup.abort_browser_group(process, reader)
        finally:
            if process.stderr is not None:
                process.stderr.close()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_stopped_reader_without_eof_is_not_clean(self) -> None:
        reader = cleanup.BrowserStderrReader(
            io.StringIO(), deque(), name="m9-browser-cleanup-no-eof"
        )
        self.assertEqual(
            "M9 browser stderr reader stopped before EOF",
            str(cleanup._reader_failure(reader)),
        )

    def test_reader_callbacks_preserve_line_and_eof_evidence(self) -> None:
        lines: list[str] = []
        eof: list[bool] = []
        reader = cleanup.BrowserStderrReader(
            io.StringIO("first\nsecond\n"),
            deque(),
            name="m9-browser-cleanup-callbacks",
            on_line=lines.append,
            on_eof=lambda: eof.append(True),
        )
        reader.start()
        reader.join(timeout=1)

        self.assertFalse(reader.is_alive())
        self.assertTrue(reader.reached_eof)
        self.assertIsNone(reader.error)
        self.assertEqual(["first", "second"], lines)
        self.assertEqual([True], eof)

    def test_reader_fixed_size_framing_preserves_lines_and_eof(self) -> None:
        lines: list[str] = []
        eof: list[bool] = []
        destination: deque[str] = deque()
        stream = _BoundedReadTextStream("first\nsecond\nlast", 3)
        reader = cleanup.BrowserStderrReader(
            stream,
            destination,
            name="m9-browser-cleanup-fixed-size-framing",
            on_line=lines.append,
            on_eof=lambda: eof.append(True),
        )

        with mock.patch.object(cleanup, "STDERR_READ_CHUNK_CHARS", 3):
            reader.start()
            reader.join(timeout=1)

        self.assertFalse(reader.is_alive())
        self.assertTrue(reader.reached_eof)
        self.assertIsNone(reader.error)
        self.assertEqual(["first", "second", "last"], list(destination))
        self.assertEqual(["first", "second", "last"], lines)
        self.assertEqual([True], eof)
        self.assertGreater(len(stream.read_sizes), 1)
        self.assertEqual([3] * len(stream.read_sizes), stream.read_sizes)

    def test_reader_rejects_one_mebibyte_unterminated_record_and_drains(self) -> None:
        lines: list[str] = []
        eof: list[bool] = []
        destination: deque[str] = deque()
        reader = cleanup.BrowserStderrReader(
            io.StringIO("x" * (1024 * 1024)),
            destination,
            name="m9-browser-cleanup-unterminated-mebibyte",
            on_line=lines.append,
            on_eof=lambda: eof.append(True),
        )

        reader.start()
        reader.join(timeout=3)

        self.assertFalse(reader.is_alive())
        self.assertFalse(reader.reached_eof)
        self.assertIsInstance(reader.error, M0Error)
        self.assertIn("record exceeds", str(reader.error))
        self.assertEqual([], list(destination))
        self.assertEqual([], lines)
        self.assertEqual([], eof)

    def test_reader_preserves_record_limit_error_when_drain_fails(self) -> None:
        reader = cleanup.BrowserStderrReader(
            _DrainFailureTextStream(),  # type: ignore[arg-type]
            deque(),
            name="m9-browser-cleanup-record-limit-sticky-error",
        )

        with (
            mock.patch.object(cleanup, "STDERR_READ_CHUNK_CHARS", 4),
            mock.patch.object(cleanup, "MAX_STDERR_RECORD_CHARS", 3),
        ):
            reader.start()
            reader.join(timeout=1)

        self.assertFalse(reader.is_alive())
        self.assertFalse(reader.reached_eof)
        self.assertIsInstance(reader.error, M0Error)
        self.assertIn("record exceeds", str(reader.error))

    def test_stop_reaps_subprocess_but_rejects_oversized_stderr_record(self) -> None:
        process = self._start(
            "import sys; sys.stderr.write('x' * (1024 * 1024)); sys.stderr.flush()"
        )
        reader = self._reader(process)
        reader.start()
        try:
            process.wait(timeout=5)
            reader.join(timeout=5)
            with self.assertRaisesRegex(M0Error, "stderr reader failed.*record exceeds"):
                cleanup.stop_browser_group(process, reader)
            self.assertFalse(reader.is_alive())
            self.assertIsNotNone(process.returncode)
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.pid, 0)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_reader_line_callback_failure_is_not_clean_eof_evidence(self) -> None:
        reader = cleanup.BrowserStderrReader(
            io.StringIO("line\n"),
            deque(),
            name="m9-browser-cleanup-line-callback-failure",
            on_line=lambda _line: (_ for _ in ()).throw(
                RuntimeError("line callback failed")
            ),
        )
        reader.start()
        reader.join(timeout=1)

        self.assertFalse(reader.is_alive())
        self.assertFalse(reader.reached_eof)
        self.assertIsInstance(reader.error, RuntimeError)
        self.assertIn("line callback failed", str(cleanup._reader_failure(reader)))

    def test_reader_callback_failure_is_not_clean_eof_evidence(self) -> None:
        reader = cleanup.BrowserStderrReader(
            io.StringIO("line\n"),
            deque(),
            name="m9-browser-cleanup-callback-failure",
            on_eof=lambda: (_ for _ in ()).throw(RuntimeError("eof callback failed")),
        )
        reader.start()
        reader.join(timeout=1)

        self.assertFalse(reader.is_alive())
        self.assertFalse(reader.reached_eof)
        self.assertIsInstance(reader.error, RuntimeError)
        self.assertIn("eof callback failed", str(cleanup._reader_failure(reader)))


if __name__ == "__main__":
    unittest.main()

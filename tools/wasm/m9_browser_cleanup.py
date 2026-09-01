#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Fail-closed cleanup for the M9 browser-backed observation runners.

The generic browser smoke helper predates the M9 runners and deliberately has
a smaller contract.  These runners need stronger completion evidence: a
reaped browser leader is not sufficient while a descendant can retain its
stderr pipe or stay in the browser's dedicated process group.
"""

from __future__ import annotations

from collections import deque
import os
import queue
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Sequence, TextIO

if __package__:
    from .m0_common import M0Error
else:
    from m0_common import M0Error


COOPERATIVE_STOP_SECONDS = 3.0
FORCED_STOP_SECONDS = 3.0
POLL_SECONDS = 0.05
# Browser output is decoded through ``text=True``, so this cap is expressed in
# decoded characters rather than source bytes.  It bounds one retained record
# even if a browser or child writes without a newline.
MAX_STDERR_RECORD_CHARS = 64 * 1024


class RelayReadinessLatch:
    """Retain one relay readiness line without applying producer backpressure.

    Relay stdout is otherwise retained in a bounded diagnostic deque, but its
    readiness protocol needs just one terminal observation: the first
    nonempty line, or EOF if no such line arrived.  A ``queue.Queue`` lets an
    unbounded relay stdout stream accumulate readiness candidates while the
    consumer is busy elsewhere.  This latch keeps only the first outcome and
    wakes waiters through an ``Event``.  Its ``get`` method deliberately
    raises ``queue.Empty`` on timeout so existing runner wait loops retain
    their timeout behavior.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._outcome: str | None = None
        self._resolved = False

    def put(self, line: str | None) -> None:
        """Publish one relay stdout observation without waiting for a consumer.

        Empty records are ignored.  ``None`` is reserved for EOF, making it
        distinct from an empty text record.  Once a readiness line or EOF has
        resolved the latch, later output cannot replace that evidence.
        """

        if line is not None and not isinstance(line, str):
            raise TypeError("relay readiness observation must be text or None")
        if line == "":
            return
        with self._lock:
            if self._resolved:
                return
            self._outcome = line
            self._resolved = True
            self._event.set()

    def get(
        self, block: bool = True, timeout: float | None = None
    ) -> str | None:
        """Return the retained outcome or raise ``queue.Empty`` like Queue.get."""

        if timeout is not None and timeout < 0:
            raise ValueError("'timeout' must be a non-negative number")
        if not block and timeout is not None:
            raise ValueError("can't specify timeout for non-blocking get")
        if block:
            if not self._event.wait(timeout):
                raise queue.Empty
        elif not self._event.is_set():
            raise queue.Empty
        with self._lock:
            if not self._resolved:
                # ``Event`` is set while holding this lock, so this can only
                # occur if a future implementation changes that ordering.
                raise queue.Empty
            return self._outcome


class BrowserStderrReader:
    """Drain a browser stderr pipe while retaining EOF and error evidence."""

    def __init__(
        self,
        stream: TextIO,
        destination: deque[str],
        *,
        name: str,
        thread_factory: Callable[..., Any] = threading.Thread,
        on_line: Callable[[str], None] | None = None,
        on_eof: Callable[[], None] | None = None,
        transform_record: Callable[[str], str] | None = None,
    ):
        self._stream = stream
        self._destination = destination
        self._on_line = on_line
        self._on_eof = on_eof
        self._transform_record = transform_record
        self._error: BaseException | None = None
        self._reached_eof = False
        self._started = False
        # Let callers inject their local Thread constructor.  This keeps the
        # four runners' established startup-failure coverage useful without
        # making the helper's cleanup policy depend on their implementation.
        self.thread = thread_factory(target=self._drain, name=name, daemon=True)

    def start(self) -> None:
        self.thread.start()
        self._started = True

    @property
    def started(self) -> bool:
        """Whether ``Thread.start`` returned normally for this reader."""

        return self._started

    @property
    def reached_eof(self) -> bool:
        return self._reached_eof

    @property
    def error(self) -> BaseException | None:
        return self._error

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self.thread.join(timeout=timeout)

    def close_after_reader_stops(self) -> None:
        """Close only after the buffered reader cannot be blocked in read()."""

        if self.is_alive():
            raise M0Error("M9 browser stderr reader did not stop before pipe close")
        try:
            self._stream.close()
        except OSError:
            # The browser can close the read end first.  EOF is the relevant
            # success evidence, and a redundant local close need not obscure it.
            pass

    def close_unstarted_pipe(self) -> None:
        """Close a pipe whose reader never started.

        A failed ``Thread.start`` leaves no concurrent read to unblock, so
        this is safe.  Callers must never use it after a reader has started.
        """

        if self._started:
            raise M0Error("cannot close an M9 browser stderr pipe before its reader stops")
        try:
            self._stream.close()
        except OSError:
            pass

    def _drain(self) -> None:
        try:
            while True:
                # ``TextIOWrapper.read(n)`` waits for all ``n`` characters or
                # EOF.  Relay readiness records are much smaller than the
                # record cap and their process deliberately stays alive, so a
                # fixed-size ``read`` would hold a valid newline-delimited
                # readiness record until shutdown.  ``readline(limit)``
                # wakes as soon as that newline arrives while still bounding
                # one decoded record in memory.
                record = self._stream.readline(MAX_STDERR_RECORD_CHARS + 1)
                if not record:
                    break
                payload = record[:-1] if record.endswith("\n") else record
                if len(payload) > MAX_STDERR_RECORD_CHARS:
                    self._record_limit_error()
                    self._drain_after_record_limit()
                    return
                self._emit_record(payload)
        except BaseException as exc:
            if self._error is None:
                self._error = exc
            return

        self._reached_eof = True
        if self._on_eof is not None:
            try:
                self._on_eof()
            except BaseException as exc:
                self._error = exc
                self._reached_eof = False

    def _emit_record(self, record: str) -> None:
        text = record.rstrip()
        if self._transform_record is not None:
            text = self._transform_record(text)
        if not isinstance(text, str):
            raise TypeError("browser stderr record transform must return text")
        self._destination.append(text)
        if self._on_line is not None:
            self._on_line(text)

    def _record_limit_error(self) -> None:
        # Keep this first error even if a later pipe read fails while draining.
        self._error = M0Error(
            "M9 browser stderr record exceeds "
            f"{MAX_STDERR_RECORD_CHARS} decoded characters"
        )

    def _drain_after_record_limit(self) -> None:
        """Discard bounded chunks until EOF after an oversized record.

        A reader error must not leave a writer blocked on its inherited pipe.
        Do not emit further records or EOF evidence after the limit violation:
        callers must be unable to mistake this cleanup-only drain for a clean
        browser completion.
        """

        while self._stream.readline(MAX_STDERR_RECORD_CHARS + 1):
            pass


def _browser_group_exists(browser: subprocess.Popen[str]) -> bool:
    """Return whether the dedicated browser group remains, failing closed."""

    try:
        os.killpg(browser.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        raise M0Error(
            "cannot verify M9 browser process-group absence after leader exit"
        ) from exc


def _signal_browser_group(
    browser: subprocess.Popen[str], signal_number: int
) -> None:
    """Signal the dedicated browser group even when its leader is reaped."""

    try:
        os.killpg(browser.pid, signal_number)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise M0Error("cannot signal M9 browser process group during cleanup") from exc


def _reader_failure(reader: BrowserStderrReader) -> M0Error | None:
    if reader.error is not None:
        return M0Error(f"M9 browser stderr reader failed: {reader.error}")
    if not reader.is_alive() and not reader.reached_eof:
        return M0Error("M9 browser stderr reader stopped before EOF")
    return None


def _wait_for_browser_cleanup(
    browser: subprocess.Popen[str],
    reader: BrowserStderrReader | None,
    timeout: float,
) -> tuple[bool, BaseException | None]:
    """Wait for leader, reader EOF, and process-group absence together."""

    deadline = time.monotonic() + timeout
    while True:
        # Keep checking the group even after the leader exits: browser child
        # processes can outlive the leader and can retain no stderr pipe.
        try:
            group_exists = _browser_group_exists(browser)
        except BaseException as exc:
            # Do not abandon the escalation path merely because the first
            # signal-zero probe failed.  The caller still attempts SIGKILL
            # against the retained session/process-group identifier.
            return False, exc
        reader_stopped = reader is None or not reader.is_alive()
        if browser.poll() is not None and reader_stopped and not group_exists:
            return True, None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, None
        if reader is not None and reader.is_alive():
            reader.join(timeout=min(POLL_SECONDS, remaining))
        else:
            time.sleep(min(POLL_SECONDS, remaining))


def _close_reader_after_cleanup(reader: BrowserStderrReader | None) -> BaseException | None:
    """Close a stopped reader pipe without hiding an earlier failure."""

    if reader is None or reader.is_alive():
        return None
    try:
        if reader.started:
            reader.close_after_reader_stops()
        else:
            reader.close_unstarted_pipe()
    except BaseException as exc:
        return exc
    return None


def _signal_or_record(
    browser: subprocess.Popen[str], signal_number: int
) -> BaseException | None:
    try:
        _signal_browser_group(browser, signal_number)
    except BaseException as exc:
        return exc
    return None


def stop_browser_group(
    browser: subprocess.Popen[str], reader: BrowserStderrReader
) -> None:
    """Stop one M9 browser group and prove its stderr path has completed.

    A forced kill is failure-only.  SIGKILL may prevent Chrome's ordinary
    cleanup from running, so a caller must never turn it into an M9 success.
    """

    if not reader.started:
        raise M0Error("M9 browser stderr reader was never started")

    first_problem = _signal_or_record(browser, signal.SIGTERM)
    cooperative_complete = False
    if first_problem is None:
        cooperative_complete, first_problem = _wait_for_browser_cleanup(
            browser, reader, COOPERATIVE_STOP_SECONDS
        )
    if cooperative_complete:
        close_problem = _close_reader_after_cleanup(reader)
        reader_problem = _reader_failure(reader)
        if first_problem is not None:
            raise M0Error("cannot verify M9 browser cleanup") from first_problem
        if close_problem is not None:
            raise M0Error("could not close stopped M9 browser stderr pipe") from close_problem
        if reader_problem is not None:
            raise reader_problem
        return

    # A failed probe is itself a non-success outcome, but it must not prevent
    # the emergency group kill from running.  A reaped leader is insufficient:
    # Chrome descendants can retain the group and stderr FD.
    kill_problem = _signal_or_record(browser, signal.SIGKILL)
    forced_complete, forced_wait_problem = _wait_for_browser_cleanup(
        browser, reader, FORCED_STOP_SECONDS
    )
    close_problem = _close_reader_after_cleanup(reader)
    reader_problem = _reader_failure(reader)
    root_problem = first_problem or kill_problem or forced_wait_problem or reader_problem
    if not forced_complete:
        raise M0Error(
            "M9 browser process group or stderr reader did not stop after "
            "SIGTERM and SIGKILL"
        ) from root_problem
    if close_problem is not None:
        raise M0Error("could not close stopped M9 browser stderr pipe") from close_problem
    if root_problem is not None:
        raise M0Error("cannot verify M9 browser cleanup") from root_problem
    raise M0Error(
        "M9 browser cleanup required SIGKILL; normal browser shutdown cannot "
        "be proven"
    )


def wait_for_browser_group_exit(
    browser: subprocess.Popen[str],
    reader: BrowserStderrReader,
    timeout: float,
    *,
    description: str,
    expected_returncode: int = 0,
) -> None:
    """Verify an independently requested graceful browser exit.

    Some witnesses must ask Chrome itself to close (for example through CDP)
    rather than signal its process group.  This helper deliberately sends no
    signal: it accepts success only after the already-requested shutdown
    reaps the leader, closes stderr cleanly, and removes every member of the
    dedicated browser process group.  Callers retain the failure-path choice
    of ``abort_browser_group`` if this evidence cannot be obtained.
    """

    if not reader.started:
        raise M0Error(f"{description} browser stderr reader was never started")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        raise M0Error(f"{description} browser exit timeout is invalid")
    if not isinstance(expected_returncode, int) or isinstance(
        expected_returncode, bool
    ):
        raise M0Error(f"{description} expected browser exit status is invalid")

    complete, wait_problem = _wait_for_browser_cleanup(browser, reader, timeout)
    if not complete:
        raise M0Error(
            f"{description} browser did not exit with a closed stderr pipe "
            "and no remaining process group"
        ) from wait_problem
    close_problem = _close_reader_after_cleanup(reader)
    reader_problem = _reader_failure(reader)
    if close_problem is not None:
        raise M0Error(
            f"could not close stopped {description} browser stderr pipe"
        ) from close_problem
    if reader_problem is not None:
        raise reader_problem
    if browser.returncode != expected_returncode:
        raise M0Error(f"{description} browser exit status is invalid")


def abort_browser_group(
    browser: subprocess.Popen[str],
    reader: BrowserStderrReader | None = None,
    *,
    unowned_streams: Sequence[TextIO] = (),
) -> None:
    """Best-effort failure-path cleanup for a browser lacking clean evidence.

    This helper is intentionally unsuitable for a success path.  It exists
    for failures before a stderr reader starts, where killing only the leader
    can leave Chrome descendants in the session.  It still requires the
    process group to disappear if it returns normally. ``unowned_streams``
    covers a raw pipe when reader construction itself failed.
    """

    # An unstarted reader has no concurrent read, so it cannot be part of the
    # wait condition.  A started reader must reach a terminal state just like
    # the ordinary success-path reader; otherwise a descendant may still own
    # the pipe even after the browser leader has gone away.
    wait_reader = reader if reader is not None and reader.started else None
    first_problem = _signal_or_record(browser, signal.SIGTERM)
    cooperative_complete = False
    if first_problem is None:
        cooperative_complete, first_problem = _wait_for_browser_cleanup(
            browser, wait_reader, COOPERATIVE_STOP_SECONDS
        )
    if not cooperative_complete:
        kill_problem = _signal_or_record(browser, signal.SIGKILL)
        forced_complete, forced_wait_problem = _wait_for_browser_cleanup(
            browser, wait_reader, FORCED_STOP_SECONDS
        )
    else:
        kill_problem = None
        forced_complete = True
        forced_wait_problem = None

    close_problem = _close_reader_after_cleanup(reader)
    raw_close_problem = _close_unowned_streams_after_cleanup(unowned_streams)
    reader_problem = _reader_failure(wait_reader) if wait_reader is not None else None
    root_problem = (
        first_problem or kill_problem or forced_wait_problem or reader_problem
    )
    if not forced_complete:
        raise M0Error(
            "M9 browser abort cleanup could not stop the process group"
        ) from root_problem
    if close_problem is not None:
        raise M0Error("could not close M9 browser stderr pipe during abort") from close_problem
    if raw_close_problem is not None:
        raise M0Error("could not close unowned M9 browser stderr pipe during abort") from raw_close_problem
    if root_problem is not None:
        raise M0Error("cannot verify M9 browser abort cleanup") from root_problem


def _process_group_exists(
    process: subprocess.Popen[str], *, description: str
) -> bool:
    """Return whether a runner-owned process group remains, failing closed."""

    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        raise M0Error(
            f"cannot verify {description} process-group absence after leader exit"
        ) from exc


def _signal_process_group(
    process: subprocess.Popen[str], signal_number: int, *, description: str
) -> None:
    """Signal a dedicated group even after its leader has exited."""

    try:
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise M0Error(
            f"cannot signal {description} process group during cleanup"
        ) from exc


def _process_reader_failure(
    reader: BrowserStderrReader, *, description: str
) -> M0Error | None:
    if reader.error is not None:
        return M0Error(f"{description} output reader failed: {reader.error}")
    if not reader.is_alive() and not reader.reached_eof:
        return M0Error(f"{description} output reader stopped before EOF")
    return None


def _process_readers_failure(
    readers: Sequence[BrowserStderrReader], *, description: str
) -> M0Error | None:
    for reader in readers:
        failure = _process_reader_failure(reader, description=description)
        if failure is not None:
            return failure
    return None


def _wait_for_process_group_cleanup(
    process: subprocess.Popen[str],
    readers: Sequence[BrowserStderrReader],
    timeout: float,
    *,
    description: str,
) -> tuple[bool, BaseException | None]:
    """Wait for the leader, all output readers, and its group to finish."""

    deadline = time.monotonic() + timeout
    while True:
        try:
            group_exists = _process_group_exists(process, description=description)
        except BaseException as exc:
            # A failed signal-zero probe cannot suppress the emergency group
            # kill. The caller still treats this as a failed observation.
            return False, exc
        if (
            process.poll() is not None
            and not any(reader.is_alive() for reader in readers)
            and not group_exists
        ):
            return True, None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, None
        live_readers = [reader for reader in readers if reader.is_alive()]
        if live_readers:
            for reader in live_readers:
                reader.join(timeout=min(POLL_SECONDS, remaining))
        else:
            time.sleep(min(POLL_SECONDS, remaining))


def _close_process_readers_after_cleanup(
    readers: Sequence[BrowserStderrReader],
) -> BaseException | None:
    """Close only output pipes whose readers have reached a terminal state."""

    close_problem: BaseException | None = None
    for reader in readers:
        if reader.is_alive():
            continue
        try:
            if reader.started:
                reader.close_after_reader_stops()
            else:
                reader.close_unstarted_pipe()
        except BaseException as exc:
            if close_problem is None:
                close_problem = exc
    return close_problem


def _close_unowned_streams_after_cleanup(
    streams: Sequence[TextIO],
) -> BaseException | None:
    """Close raw pipes that failed before a reader could take ownership.

    Callers may pass a stream here only when no ``BrowserStderrReader`` was
    constructed for it. There is no concurrent reader in that ownership state,
    so closing its parent descriptor cannot race a reader.
    """

    close_problem: BaseException | None = None
    for stream in streams:
        try:
            stream.close()
        except OSError:
            # A child can close the read end before this failure-path cleanup
            # reaches it.  This has the same harmless semantics as closing a
            # stopped BrowserStderrReader's stream above.
            pass
        except BaseException as exc:
            if close_problem is None:
                close_problem = exc
    return close_problem


def _signal_process_group_or_record(
    process: subprocess.Popen[str],
    signal_number: int,
    *,
    description: str,
) -> BaseException | None:
    try:
        _signal_process_group(process, signal_number, description=description)
    except BaseException as exc:
        return exc
    return None


def stop_process_group(
    process: subprocess.Popen[str],
    readers: Sequence[BrowserStderrReader],
    *,
    description: str,
) -> None:
    """Stop one runner-owned process group with complete output evidence.

    This is for child harnesses that own a process with more than one pipe,
    such as a WISP relay.  A reaped leader alone is insufficient: a descendant
    can retain either pipe or remain in the dedicated process group.  SIGKILL
    remains failure-only because it cannot prove normal process shutdown.
    """

    readers = tuple(readers)
    if not readers or not all(reader.started for reader in readers):
        raise M0Error(f"{description} output reader was never started")

    first_problem = _signal_process_group_or_record(
        process, signal.SIGTERM, description=description
    )
    cooperative_complete = False
    if first_problem is None:
        cooperative_complete, first_problem = _wait_for_process_group_cleanup(
            process,
            readers,
            COOPERATIVE_STOP_SECONDS,
            description=description,
        )
    if cooperative_complete:
        close_problem = _close_process_readers_after_cleanup(readers)
        reader_problem = _process_readers_failure(readers, description=description)
        if first_problem is not None:
            raise M0Error(f"cannot verify {description} cleanup") from first_problem
        if close_problem is not None:
            raise M0Error(f"could not close stopped {description} output pipe") from close_problem
        if reader_problem is not None:
            raise reader_problem
        return

    kill_problem = _signal_process_group_or_record(
        process, signal.SIGKILL, description=description
    )
    forced_complete, forced_wait_problem = _wait_for_process_group_cleanup(
        process,
        readers,
        FORCED_STOP_SECONDS,
        description=description,
    )
    close_problem = _close_process_readers_after_cleanup(readers)
    reader_problem = _process_readers_failure(readers, description=description)
    root_problem = first_problem or kill_problem or forced_wait_problem or reader_problem
    if not forced_complete:
        raise M0Error(
            f"{description} process group or output readers did not stop after "
            "SIGTERM and SIGKILL"
        ) from root_problem
    if close_problem is not None:
        raise M0Error(f"could not close stopped {description} output pipe") from close_problem
    if root_problem is not None:
        raise M0Error(f"cannot verify {description} cleanup") from root_problem
    raise M0Error(
        f"{description} cleanup required SIGKILL; normal process shutdown "
        "cannot be proven"
    )


def abort_process_group(
    process: subprocess.Popen[str],
    readers: Sequence[BrowserStderrReader],
    *,
    description: str,
    unowned_streams: Sequence[TextIO] = (),
) -> None:
    """Complete failure-path cleanup for a runner-owned multi-pipe process.

    Unlike ``stop_process_group``, emergency SIGKILL is permitted here because
    the caller already has an operational failure.  It still proves group
    absence and a terminal state for each reader that actually started. Raw
    streams are accepted only for failures before reader construction.
    """

    readers = tuple(readers)
    started_readers = tuple(reader for reader in readers if reader.started)
    first_problem = _signal_process_group_or_record(
        process, signal.SIGTERM, description=description
    )
    cooperative_complete = False
    if first_problem is None:
        cooperative_complete, first_problem = _wait_for_process_group_cleanup(
            process,
            started_readers,
            COOPERATIVE_STOP_SECONDS,
            description=description,
        )
    if cooperative_complete:
        kill_problem = None
        forced_complete = True
        forced_wait_problem = None
    else:
        kill_problem = _signal_process_group_or_record(
            process, signal.SIGKILL, description=description
        )
        forced_complete, forced_wait_problem = _wait_for_process_group_cleanup(
            process,
            started_readers,
            FORCED_STOP_SECONDS,
            description=description,
        )

    close_problem = _close_process_readers_after_cleanup(readers)
    raw_close_problem = _close_unowned_streams_after_cleanup(unowned_streams)
    reader_problem = _process_readers_failure(
        started_readers, description=description
    )
    root_problem = (
        first_problem or kill_problem or forced_wait_problem or reader_problem
    )
    if not forced_complete:
        raise M0Error(
            f"{description} abort cleanup could not stop the process group"
        ) from root_problem
    if close_problem is not None:
        raise M0Error(f"could not close {description} output pipe during abort") from close_problem
    if raw_close_problem is not None:
        raise M0Error(
            f"could not close unowned {description} output pipe during abort"
        ) from raw_close_problem
    if root_problem is not None:
        raise M0Error(f"cannot verify {description} abort cleanup") from root_problem

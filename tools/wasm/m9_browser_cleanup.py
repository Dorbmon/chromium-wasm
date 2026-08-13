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
import signal
import subprocess
import threading
import time
from typing import Any, Callable, TextIO

if __package__:
    from .m0_common import M0Error
else:
    from m0_common import M0Error


COOPERATIVE_STOP_SECONDS = 3.0
FORCED_STOP_SECONDS = 3.0
POLL_SECONDS = 0.05


class BrowserStderrReader:
    """Drain a browser stderr pipe while retaining EOF and error evidence."""

    def __init__(
        self,
        stream: TextIO,
        destination: deque[str],
        *,
        name: str,
        thread_factory: Callable[..., Any] = threading.Thread,
    ):
        self._stream = stream
        self._destination = destination
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
            for line in self._stream:
                self._destination.append(line.rstrip())
        except BaseException as exc:
            self._error = exc
        else:
            self._reached_eof = True


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


def abort_browser_group(
    browser: subprocess.Popen[str], reader: BrowserStderrReader | None = None
) -> None:
    """Best-effort failure-path cleanup for a browser lacking clean evidence.

    This helper is intentionally unsuitable for a success path.  It exists
    for failures before a stderr reader starts, where killing only the leader
    can leave Chrome descendants in the session.  It still requires the
    process group to disappear if it returns normally.
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
    if root_problem is not None:
        raise M0Error("cannot verify M9 browser abort cleanup") from root_problem

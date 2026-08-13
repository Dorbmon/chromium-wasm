#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Bounded server-shutdown calls for the M9 observation runners.

``BaseServer.shutdown`` waits for ``serve_forever`` to enter and leave its
loop.  Calling it directly can block indefinitely when a just-started daemon
thread has not entered that loop.  M9 runners must fail rather than hang or
claim a completed observation in that state.
"""

from __future__ import annotations

from http.server import ThreadingHTTPServer
import threading
import time
from typing import Any, Callable

if __package__:
    from .m0_common import M0Error
else:
    from m0_common import M0Error


def shutdown_server_bounded(
    server: Any,
    *,
    timeout: float,
    description: str,
    thread_factory: Callable[..., Any] = threading.Thread,
) -> None:
    """Call ``server.shutdown`` without permitting an unbounded wait.

    Callers must still close the server socket and join the serving thread in
    their ``finally`` block.  A timed-out helper thread is daemon-only and is
    failure evidence, never cleanup success evidence.
    """

    if timeout <= 0:
        raise ValueError("M9 server shutdown timeout must be positive")

    errors: list[BaseException] = []

    def invoke_shutdown() -> None:
        try:
            server.shutdown()
        except BaseException as exc:
            errors.append(exc)

    worker = thread_factory(
        target=invoke_shutdown,
        name="chromium-wasm-m9-server-shutdown",
        daemon=True,
    )
    try:
        worker.start()
    except BaseException as exc:
        raise M0Error(f"{description} shutdown helper did not start") from exc
    try:
        worker.join(timeout=timeout)
    except BaseException as exc:
        raise M0Error(f"{description} shutdown helper could not be joined") from exc
    if worker.is_alive():
        raise M0Error(f"{description} shutdown did not return before its deadline")
    if errors:
        raise M0Error(f"{description} shutdown failed") from errors[0]


class M9TrackingThreadingHTTPServer(ThreadingHTTPServer):
    """A ``ThreadingHTTPServer`` that proves daemon handlers have exited.

    ``ThreadingMixIn`` deliberately excludes daemon request threads from its
    private ``_threads`` collection, so ``server_close`` cannot establish
    that an in-flight response has finished.  M9 server lifetimes use daemon
    handlers to avoid an unbounded close, but must separately retain and join
    them before an observation can report success.
    """

    daemon_threads = True
    _HANDLER_POLL_SECONDS = 0.05

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._m9_handler_lock = threading.Lock()
        self._m9_handler_threads: set[threading.Thread] = set()
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        """Start and retain every daemon request handler for later draining."""

        handler_thread: threading.Thread | None = None
        try:
            handler_thread = threading.Thread(
                target=self.process_request_thread,
                args=(request, client_address),
                name="chromium-wasm-m9-http-handler",
                daemon=self.daemon_threads,
            )
            with self._m9_handler_lock:
                self._m9_handler_threads.add(handler_thread)
            handler_thread.start()
        except BaseException:
            if handler_thread is not None:
                with self._m9_handler_lock:
                    self._m9_handler_threads.discard(handler_thread)
            # No worker owns this accepted request after Thread.start fails.
            # Preserve that primary startup failure, while still releasing the
            # server-side socket best-effort so a client cannot linger.
            try:
                self.shutdown_request(request)
            except BaseException:
                pass
            raise

    def _discard_stopped_handlers_locked(self) -> None:
        """Drop only Thread objects already observed in their terminal state."""

        for handler in tuple(self._m9_handler_threads):
            if not handler.is_alive():
                self._m9_handler_threads.discard(handler)

    def join_request_handlers(self, *, timeout: float, description: str) -> None:
        """Boundedly require every previously accepted handler to finish.

        Call this only after ``shutdown``, ``server_close``, and the serving
        thread's bounded join.  At that point no new handler can be accepted,
        so an active tracked thread is evidence of an incomplete server
        lifetime rather than a race with a new request.
        """

        if timeout <= 0:
            raise ValueError("M9 request-handler timeout must be positive")
        deadline = time.monotonic() + timeout
        while True:
            with self._m9_handler_lock:
                handlers = tuple(self._m9_handler_threads)
            if not handlers:
                return
            for handler in handlers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise M0Error(f"{description} request handlers did not stop")
                handler.join(timeout=min(self._HANDLER_POLL_SECONDS, remaining))
            # A handler target can return just before its Thread object flips
            # to non-alive. Retain every reference until this observer sees
            # the terminal Thread state, rather than removing it from the
            # handler target's ``finally`` block.
            with self._m9_handler_lock:
                self._discard_stopped_handlers_locked()

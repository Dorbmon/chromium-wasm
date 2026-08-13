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

import threading
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

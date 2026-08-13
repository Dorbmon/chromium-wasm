#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for bounded M9 HTTP-server shutdown calls."""

from __future__ import annotations

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from tools.wasm.m0_common import M0Error
from tools.wasm import m9_server_cleanup as cleanup


class _BlockingServer:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def shutdown(self) -> None:
        self.entered.set()
        self.release.wait()
        self.finished.set()


class _QuietRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


class _PreServeShutdownServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        self.shutdown_entered = threading.Event()
        self.shutdown_returned = threading.Event()
        super().__init__(("127.0.0.1", 0), _QuietRequestHandler)

    def shutdown(self) -> None:
        self.shutdown_entered.set()
        try:
            super().shutdown()
        finally:
            self.shutdown_returned.set()


class M9ServerCleanupTest(unittest.TestCase):
    def test_normal_shutdown_returns(self) -> None:
        server = mock.Mock()

        cleanup.shutdown_server_bounded(
            server, timeout=1, description="test M9 server"
        )

        server.shutdown.assert_called_once_with()

    def test_blocking_shutdown_is_bounded_and_fails_closed(self) -> None:
        server = _BlockingServer()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(M0Error, "did not return before its deadline"):
                cleanup.shutdown_server_bounded(
                    server, timeout=0.05, description="test M9 server"
                )
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(server.entered.is_set())
            self.assertFalse(server.finished.is_set())
        finally:
            server.release.set()
        self.assertTrue(server.finished.wait(1))

    def test_pre_serve_forever_base_server_shutdown_is_bounded(self) -> None:
        """Exercise the actual BaseServer shutdown wait before serve_forever."""

        try:
            server = _PreServeShutdownServer()
        except PermissionError:
            self.skipTest("test sandbox does not permit loopback socket binding")

        serving_thread = threading.Thread(target=server.serve_forever, daemon=True)
        try:
            with self.assertRaisesRegex(M0Error, "did not return before its deadline"):
                cleanup.shutdown_server_bounded(
                    server, timeout=0.05, description="test M9 server"
                )
            self.assertTrue(server.shutdown_entered.is_set())
            self.assertFalse(server.shutdown_returned.is_set())

            serving_thread.start()
            self.assertTrue(server.shutdown_returned.wait(1))
            serving_thread.join(1)
            self.assertFalse(serving_thread.is_alive())
        finally:
            if serving_thread.ident is None:
                serving_thread.start()
            serving_thread.join(1)
            server.server_close()

    def test_shutdown_helper_start_failure_fails_closed(self) -> None:
        worker = mock.Mock()
        worker.start.side_effect = RuntimeError("thread start failed")
        factory = mock.Mock(return_value=worker)

        with self.assertRaisesRegex(M0Error, "shutdown helper did not start"):
            cleanup.shutdown_server_bounded(
                mock.Mock(),
                timeout=1,
                description="test M9 server",
                thread_factory=factory,
            )

        worker.join.assert_not_called()

    def test_shutdown_exception_is_not_silently_accepted(self) -> None:
        server = mock.Mock()
        server.shutdown.side_effect = RuntimeError("shutdown failed")

        with self.assertRaisesRegex(M0Error, "shutdown failed"):
            cleanup.shutdown_server_bounded(
                server, timeout=1, description="test M9 server"
            )


if __name__ == "__main__":
    unittest.main()

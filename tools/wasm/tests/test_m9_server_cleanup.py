#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for bounded M9 HTTP-server shutdown calls."""

from __future__ import annotations

import socket
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


class _PartialResponseHandler(BaseHTTPRequestHandler):
    """Leave a real loopback response incomplete until the test releases it."""

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"a")
        self.wfile.flush()
        self.server.partial_response_started.set()  # type: ignore[attr-defined]
        self.server.release_partial_response.wait()  # type: ignore[attr-defined]
        self.wfile.write(b"b")


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

    def test_handler_start_failure_closes_the_accepted_request(self) -> None:
        try:
            server = cleanup.M9TrackingThreadingHTTPServer(
                ("127.0.0.1", 0), _QuietRequestHandler
            )
        except PermissionError:
            self.skipTest("test sandbox does not permit loopback socket binding")
        request = object()
        handler_thread = mock.Mock()
        handler_thread.start.side_effect = RuntimeError("handler start failed")
        try:
            with (
                mock.patch.object(
                    cleanup.threading, "Thread", return_value=handler_thread
                ),
                mock.patch.object(server, "shutdown_request") as shutdown_request,
                self.assertRaisesRegex(RuntimeError, "handler start failed"),
            ):
                server.process_request(request, ("127.0.0.1", 12345))

            shutdown_request.assert_called_once_with(request)
            server.join_request_handlers(timeout=0.1, description="test M9 server")
        finally:
            server.server_close()

    def test_partial_loopback_handler_prevents_clean_teardown(self) -> None:
        """A partial live response cannot outlast a successful M9 server."""

        try:
            server = cleanup.M9TrackingThreadingHTTPServer(
                ("127.0.0.1", 0), _PartialResponseHandler
            )
        except PermissionError:
            self.skipTest("test sandbox does not permit loopback socket binding")
        server.partial_response_started = threading.Event()  # type: ignore[attr-defined]
        server.release_partial_response = threading.Event()  # type: ignore[attr-defined]
        serving_thread = threading.Thread(target=server.serve_forever, daemon=True)
        client: socket.socket | None = None
        serving_started = False
        try:
            serving_thread.start()
            serving_started = True
            client = socket.create_connection(server.server_address, timeout=1)
            client.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            self.assertTrue(server.partial_response_started.wait(1))  # type: ignore[attr-defined]

            cleanup.shutdown_server_bounded(
                server, timeout=1, description="test M9 server"
            )
            server.server_close()
            serving_thread.join(timeout=1)
            self.assertFalse(serving_thread.is_alive())
            with self.assertRaisesRegex(M0Error, "request handlers did not stop"):
                server.join_request_handlers(timeout=0.05, description="test M9 server")
        finally:
            if serving_started and serving_thread.is_alive():
                try:
                    cleanup.shutdown_server_bounded(
                        server, timeout=1, description="test M9 server"
                    )
                except M0Error:
                    pass
            server.server_close()
            if serving_started:
                serving_thread.join(timeout=1)
            server.release_partial_response.set()  # type: ignore[attr-defined]
            try:
                server.join_request_handlers(timeout=1, description="test M9 server")
            finally:
                if client is not None:
                    client.close()


if __name__ == "__main__":
    unittest.main()

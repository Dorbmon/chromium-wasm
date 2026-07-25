#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class M3NetTcpSourceContractTest(unittest.TestCase):
    def test_wasm_tcp_socket_is_selected_without_posix(self) -> None:
        build = source("net/BUILD.gn")
        selector = source("net/socket/tcp_socket.h")
        client = source("net/socket/tcp_client_socket.h")

        self.assertIn('"socket/tcp_socket_wasm.cc"', build)
        self.assertIn('"socket/tcp_socket_wasm.h"', build)
        self.assertIn(
            '#elif BUILDFLAG(IS_WASM)\n'
            '#include "net/socket/tcp_socket_wasm.h"',
            selector,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "typedef TCPSocketWasm TCPSocket;",
            selector,
        )
        self.assertIn('#include "net/base/network_handle.h"', client)

    def test_wasm_tcp_operations_fail_explicitly(self) -> None:
        header = source("net/socket/tcp_socket_wasm.h")
        implementation = source("net/socket/tcp_socket_wasm.cc")

        self.assertIn("class NET_EXPORT TCPSocketWasm", header)
        self.assertIn(
            '#error "tcp_socket_wasm.cc must only be built for WebAssembly"',
            implementation,
        )
        self.assertGreaterEqual(
            implementation.count("return ERR_NOT_IMPLEMENTED;"), 18
        )
        self.assertGreaterEqual(implementation.count("return false;"), 4)
        self.assertEqual(
            implementation.count("return kInvalidSocket;"), 2
        )
        self.assertEqual(implementation.count("NOTIMPLEMENTED_LOG_ONCE();"), 2)
        self.assertNotIn("CreatePlatformSocket", implementation)
        self.assertNotIn("::socket(", implementation)
        self.assertNotIn("#include <sys/socket.h>", implementation)

    def test_wasm_tcp_preserves_failure_diagnostics(self) -> None:
        implementation = source("net/socket/tcp_socket_wasm.cc")

        self.assertIn("NetLogSourceType::SOCKET", implementation)
        self.assertIn("NetLogEventType::SOCKET_ALIVE", implementation)
        self.assertIn("NetLogEventType::TCP_CONNECT", implementation)
        self.assertIn("EndEventWithNetErrorCode", implementation)
        self.assertIn("NetLogEventType::TCP_CONNECT,\n", implementation)
        self.assertIn(
            "EndLoggingMultipleConnectAttempts(ERR_ABORTED)", implementation
        )


if __name__ == "__main__":
    unittest.main()

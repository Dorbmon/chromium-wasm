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


class M5NetTcpSourceContractTest(unittest.TestCase):
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

    def test_wasm_tcp_uses_the_bounded_wisp_client_transport(self) -> None:
        header = source("net/socket/tcp_socket_wasm.h")
        implementation = source("net/socket/tcp_socket_wasm.cc")
        transport_header = source("net/socket/wisp_transport_wasm.h")
        transport_implementation = source("net/socket/wisp_transport_wasm.cc")
        bridge = source("net/socket/wisp_host_bridge_wasm.js")

        self.assertIn("class NET_EXPORT TCPSocketWasm", header)
        self.assertIn(
            '#error "tcp_socket_wasm.cc must only be built for WebAssembly"',
            implementation,
        )
        self.assertIn('"net/socket/wisp_transport_wasm.h"', implementation)
        self.assertIn("OpenWasmWispStream", implementation)
        self.assertIn("ReadWasmWispStream", implementation)
        self.assertIn("WriteWasmWispStream", implementation)
        self.assertIn("GetWasmWispStreamAvailableBytes", implementation)
        self.assertIn("base::OneShotTimer", header)
        self.assertIn("SEQUENCE_CHECKER", header)
        self.assertIn("base::WeakPtrFactory", header)
        self.assertIn("return ERR_IO_PENDING;", implementation)
        self.assertGreaterEqual(
            implementation.count("return ERR_NOT_IMPLEMENTED;"), 10
        )
        self.assertGreaterEqual(implementation.count("return false;"), 3)
        self.assertEqual(implementation.count("return kInvalidSocket;"), 2)

        self.assertIn("enum class WasmWispStreamState", transport_header)
        self.assertIn("chromium_wasm_wisp_stream_open", transport_implementation)
        self.assertIn("chromium_wasm_wisp_stream_read", transport_implementation)
        self.assertIn("chromium_wasm_wisp_stream_write", transport_implementation)
        self.assertIn("chromium_wasm_wisp_stream_available", transport_implementation)
        self.assertIn("chromium_wasm_wisp_stream_close", transport_implementation)
        self.assertIn("chromium_wasm_wisp_stream_open__proxy: 'sync'", bridge)
        self.assertIn("chromium_wasm_wisp_stream_read__proxy: 'sync'", bridge)
        self.assertIn("chromium_wasm_wisp_stream_write__proxy: 'sync'", bridge)
        self.assertNotIn("CreatePlatformSocket", implementation)
        self.assertNotIn("::socket(", implementation)
        self.assertNotIn("#include <sys/socket.h>", implementation)
        self.assertNotIn("fetch(", bridge)

    def test_wasm_tcp_preserves_failure_diagnostics_and_keeps_udp_disabled(
        self,
    ) -> None:
        implementation = source("net/socket/tcp_socket_wasm.cc")
        udp_implementation = source("net/socket/udp_socket_wasm.cc")

        self.assertIn("NetLogSourceType::SOCKET", implementation)
        self.assertIn("NetLogEventType::SOCKET_ALIVE", implementation)
        self.assertIn("NetLogEventType::TCP_CONNECT", implementation)
        self.assertIn("NetLogEventType::TCP_CONNECT_ATTEMPT", implementation)
        self.assertIn("NetLogEventType::SOCKET_READ_ERROR", implementation)
        self.assertIn("NetLogEventType::SOCKET_WRITE_ERROR", implementation)
        self.assertIn("NetLogEventType::SOCKET_BYTES_RECEIVED", implementation)
        self.assertIn("NetLogEventType::SOCKET_BYTES_SENT", implementation)
        self.assertIn("EndEventWithNetErrorCode", implementation)
        self.assertIn("NetLogEventType::TCP_CONNECT,\n", implementation)
        self.assertIn(
            "EndLoggingMultipleConnectAttempts(ERR_ABORTED)", implementation
        )
        destructor = implementation.split("TCPSocketWasm::~TCPSocketWasm() {", 1)[
            1
        ].split("int TCPSocketWasm::Open", 1)[0]
        self.assertLess(
            destructor.index("Close();"),
            destructor.index("EndLoggingMultipleConnectAttempts(ERR_ABORTED)"),
        )
        self.assertGreaterEqual(
            udp_implementation.count("return ERR_NOT_IMPLEMENTED;"), 20
        )
        self.assertNotIn("Wisp", udp_implementation)

    def test_net_target_links_the_wisp_bridge_only_for_wasm(self) -> None:
        build = source("net/BUILD.gn")

        self.assertIn('config("wisp_wasm_host_bridge")', build)
        self.assertIn("--js-library=", build)
        self.assertIn('"socket/wisp_host_bridge_wasm.js"', build)
        self.assertIn('"socket/wisp_transport_wasm.cc"', build)
        self.assertIn('"socket/wisp_transport_wasm.h"', build)
        self.assertIn('all_dependent_configs = [ ":wisp_wasm_host_bridge" ]', build)


if __name__ == "__main__":
    unittest.main()

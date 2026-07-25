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


class M3NetUdpSourceContractTest(unittest.TestCase):
    def test_wasm_udp_socket_is_selected_without_posix(self) -> None:
        build = source("net/BUILD.gn")
        selector = source("net/socket/udp_socket.h")

        self.assertIn('"socket/udp_socket_wasm.cc"', build)
        self.assertIn('"socket/udp_socket_wasm.h"', build)
        self.assertIn(
            '#elif BUILDFLAG(IS_WASM)\n'
            '#include "net/socket/udp_socket_wasm.h"',
            selector,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "typedef UDPSocketWasm UDPSocket;",
            selector,
        )

    def test_wasm_udp_operations_fail_explicitly(self) -> None:
        header = source("net/socket/udp_socket_wasm.h")
        implementation = source("net/socket/udp_socket_wasm.cc")

        self.assertIn("class NET_EXPORT UDPSocketWasm", header)
        self.assertIn(
            '#error "udp_socket_wasm.cc must only be built for WebAssembly"',
            implementation,
        )
        self.assertGreaterEqual(
            implementation.count("return ERR_NOT_IMPLEMENTED;"), 20
        )
        self.assertEqual(implementation.count("NOTIMPLEMENTED_LOG_ONCE();"), 2)
        self.assertNotIn("CreatePlatformSocket", implementation)
        self.assertNotIn("::socket(", implementation)
        self.assertNotIn("#include <sys/socket.h>", implementation)

    def test_sockaddr_storage_uses_only_emscripten_abi_types(self) -> None:
        header = source("net/base/sockaddr_storage.h")
        wasm_branch = header.split(
            "#elif BUILDFLAG(IS_WASM)\n", maxsplit=1
        )[1].split("#elif", maxsplit=1)[0]

        self.assertIn("#include <sys/socket.h>", wasm_branch)


if __name__ == "__main__":
    unittest.main()

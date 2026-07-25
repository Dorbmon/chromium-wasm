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


class M3NetSocketSourceContractTest(unittest.TestCase):
    def test_addrinfo_uses_emscripten_socket_abi_headers(self) -> None:
        header = source("net/base/sys_addrinfo.h")
        wasm_branch = header.split(
            "#elif BUILDFLAG(IS_WASM)\n", maxsplit=1
        )[1].split("#elif", maxsplit=1)[0]

        self.assertIn("#include <netdb.h>", wasm_branch)
        self.assertIn("#include <netinet/in.h>", wasm_branch)
        self.assertIn("#include <sys/socket.h>", wasm_branch)

    def test_ip_endpoint_uses_emscripten_interface_abi_header(self) -> None:
        endpoint = source("net/base/ip_endpoint.cc")
        wasm_branch = endpoint.split(
            "#elif BUILDFLAG(IS_WASM)\n", maxsplit=1
        )[1].split("#elif", maxsplit=1)[0]

        self.assertIn("#include <net/if.h>", wasm_branch)

    def test_socket_descriptor_is_only_an_invalid_wasm_sentinel(self) -> None:
        descriptor_header = source("net/socket/socket_descriptor.h")
        wasm_header_branch = descriptor_header.split(
            "#elif BUILDFLAG(IS_WASM)\n", maxsplit=1
        )[1].split("#elif", maxsplit=1)[0]
        descriptor_implementation = source("net/socket/socket_descriptor.cc")
        wasm_implementation_branch = descriptor_implementation.rsplit(
            "#elif BUILDFLAG(IS_WASM)\n", maxsplit=1
        )[1].split("#elif", maxsplit=1)[0]

        self.assertIn("typedef int SocketDescriptor;", wasm_header_branch)
        self.assertIn(
            "const SocketDescriptor kInvalidSocket = -1;",
            wasm_header_branch,
        )
        self.assertIn("errno = ENOSYS;", wasm_implementation_branch)
        self.assertIn("return kInvalidSocket;", wasm_implementation_branch)
        self.assertNotIn("::socket(", wasm_implementation_branch)


if __name__ == "__main__":
    unittest.main()

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

    def test_transferable_socket_only_roundtrips_the_invalid_sentinel(
        self,
    ) -> None:
        header = source(
            "services/network/public/cpp/transferable_socket.h"
        )
        implementation = source(
            "services/network/public/cpp/transferable_socket.cc"
        )
        traits = source(
            "services/network/public/cpp/"
            "transferable_socket_mojom_traits.cc"
        )
        unit_test = source(
            "services/network/public/cpp/transferable_socket_unittest.cc"
        )

        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  // M3 has no native socket transport.",
            header,
        )
        self.assertIn(
            "CHECK_EQ(socket, net::kInvalidSocket)\n"
            '      << "Native socket transfer is unsupported on '
            'WebAssembly";',
            implementation,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  return net::kInvalidSocket;",
            implementation,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "// Wasm has no native-handle constructor.\n"
            "#elif !BUILDFLAG(IS_WIN)",
            implementation,
        )
        self.assertIn(
            "// M3 can serialize only the empty handle representing "
            "kInvalidSocket.\n"
            "  return mojo::PlatformHandle();",
            traits,
        )
        self.assertIn(
            "if (socket.type() != mojo::PlatformHandle::Type::kNone)\n"
            "    return false;",
            traits,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "TEST_F(TransferableSocketTest, MojoTraits)",
            unit_test,
        )
        self.assertIn(
            "TEST_F(TransferableSocketTest, InvalidSocketMojoTraits)",
            unit_test,
        )
        self.assertIn(
            "TEST_F(TransferableSocketTest, EmptyMojoTraits)",
            unit_test,
        )


if __name__ == "__main__":
    unittest.main()

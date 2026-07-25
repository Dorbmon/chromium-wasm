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


class M3NetSocketOptionsSourceContractTest(unittest.TestCase):
    def test_wasm_selects_an_explicit_socket_options_provider(self) -> None:
        build = source("net/BUILD.gn")
        wasm_block = build.split("if (is_wasm) {", maxsplit=1)[1].split(
            "\n  }", maxsplit=1
        )[0]

        self.assertIn(
            'sources -= [ "socket/socket_options.cc" ]', wasm_block
        )
        self.assertIn('"socket/socket_options_wasm.cc"', wasm_block)

    def test_wasm_socket_options_fail_explicitly_without_native_calls(
        self,
    ) -> None:
        implementation = source("net/socket/socket_options_wasm.cc")

        self.assertIn(
            '#error "socket_options_wasm.cc must only be built for '
            'WebAssembly"',
            implementation,
        )
        self.assertEqual(
            implementation.count("return ERR_NOT_IMPLEMENTED;"), 5
        )
        self.assertNotIn("setsockopt", implementation)
        self.assertNotIn("ioctl", implementation)
        self.assertNotIn("#include <sys/socket.h>", implementation)
        self.assertNotIn("#include <netinet/", implementation)


if __name__ == "__main__":
    unittest.main()

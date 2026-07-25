#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


class M3IpcSourceContractTest(unittest.TestCase):
    def test_shared_memory_ipc_fails_explicitly_without_platform_handles(
        self,
    ) -> None:
        source = (ROOT_DIR / "ipc/param_traits_utils.cc").read_text(
            encoding="utf-8"
        )
        write = source.split(
            "void ParamTraits<base::subtle::PlatformSharedMemoryRegion>::Write",
            1,
        )[1].split(
            "bool ParamTraits<base::subtle::PlatformSharedMemoryRegion>::Read",
            1,
        )[0]
        read = source.split(
            "bool ParamTraits<base::subtle::PlatformSharedMemoryRegion>::Read",
            1,
        )[1].split(
            "void ParamTraits<base::subtle::PlatformSharedMemoryRegion::Mode>",
            1,
        )[0]

        for body in (write, read):
            with self.subTest(body=body[:24]):
                self.assertIn("#if BUILDFLAG(IS_WASM)", body)
        self.assertIn(
            'CHECK(false) << "IPC shared memory transport is unsupported on '
            'Wasm";',
            write,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return false;\n#else",
            read,
        )


if __name__ == "__main__":
    unittest.main()

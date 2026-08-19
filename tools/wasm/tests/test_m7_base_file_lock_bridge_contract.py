#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the Wasm base::File whole-file lock bridge."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M7BaseFileLockBridgeContractTest(unittest.TestCase):
    def test_wasm_bridge_uses_nonblocking_whole_file_posix_locks(self) -> None:
        bridge = source("base/files/file_wasm.cc")

        for token in (
            "#include <fcntl.h>",
            "short FcntlFlockType(File::LockMode mode)",
            "return F_RDLCK;",
            "return F_WRLCK;",
            "struct flock lock = {};",
            "lock.l_whence = SEEK_SET;",
            "lock.l_start = 0;",
            "lock.l_len = 0;  // Lock the entire file.",
            "HANDLE_EINTR(fcntl(file, F_SETLK, &lock))",
            "return File::GetLastFileError();",
            "return File::FILE_OK;",
            "return CallFcntlFlock(file_.get(), F_UNLCK);",
        ):
            with self.subTest(token=token):
                self.assertIn(token, bridge)

        for method, trace in (("Lock", "Lock"), ("Unlock", "Unlock")):
            with self.subTest(method=method):
                method_body = re.search(
                    rf"File::Error File::{method}.*?\n\}}", bridge, re.DOTALL
                )
                self.assertIsNotNone(method_body)
                body = method_body.group(0)
                self.assertIn(f'SCOPED_FILE_TRACE("{trace}");', body)
                self.assertNotIn("DCHECK(IsValid());", body)

        self.assertNotIn("FILE_ERROR_INVALID_OPERATION", bridge)

    def test_default_wasm_backend_is_an_explicit_lock_failure(self) -> None:
        smoke = source("tools/wasm/m1_base_smoke.cc")
        harness = source("tools/wasm/serve.py")

        for token in (
            "file_lock_shared_enotsup",
            "file_lock_exclusive_enotsup",
            "file_unlock_enotsup",
            "file_lock=unsupported_backend",
            "base::File::FILE_ERROR_FAILED",
            "errno == ENOTSUP",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

        self.assertNotIn("file_lock=invalid_operation", smoke)
        self.assertNotIn("file_lock_not_explicitly_unsupported", smoke)
        self.assertNotIn("FILE_ERROR_INVALID_OPERATION", smoke)
        self.assertIn('"file_lock": "unsupported_backend"', harness)


if __name__ == "__main__":
    unittest.main()

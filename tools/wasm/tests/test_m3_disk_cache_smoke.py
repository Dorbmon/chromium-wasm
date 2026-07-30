#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import serve


PREFIX = "CHROMIUM_WASM_M3_DISK_CACHE"
RESULT = (
    f"{PREFIX}:RESULT filesystem=memfs move=ok delete_open_reuse=ok "
    "default_backend=simple write_read=ok reopen=ok "
    "blockfile=unsupported_async"
)


def valid_stdout() -> str:
    return "\n".join(
        (
            f"{PREFIX}:RUNTIME_START",
            f"{PREFIX}:PHASE name=filesystem_helpers status=ok",
            f"{PREFIX}:PHASE name=simple_cache_round_trip status=ok",
            f"{PREFIX}:PHASE name=blockfile_failure_contract status=ok",
            f"{PREFIX}:RUNTIME_END",
            RESULT,
            f"{PREFIX}:PASS",
        )
    )


class M3DiskCacheSmokeTest(unittest.TestCase):
    def test_smoke_case_uses_the_content_profile(self) -> None:
        case = serve.smoke_case("disk_cache")

        self.assertEqual(case.module_name, "m3_disk_cache_smoke.js")
        self.assertEqual(case.sentinel_prefix, PREFIX)
        self.assertEqual(case.gn_args_key, "m3_content_gn_args")

    def test_accepts_exact_runtime_contract(self) -> None:
        serve.validate_case_stdout("disk_cache", valid_stdout())

    def test_rejects_missing_result_field(self) -> None:
        stdout = valid_stdout().replace(" reopen=ok", "")

        with self.assertRaisesRegex(M0Error, r"missing=\['reopen'\]"):
            serve.validate_case_stdout("disk_cache", stdout)

    def test_rejects_blockfile_false_success(self) -> None:
        stdout = valid_stdout().replace(
            "blockfile=unsupported_async", "blockfile=simple"
        )

        with self.assertRaisesRegex(M0Error, r"mismatched=\['blockfile'\]"):
            serve.validate_case_stdout("disk_cache", stdout)

    def test_rejects_unproven_delete_reuse(self) -> None:
        stdout = valid_stdout().replace(
            "delete_open_reuse=ok", "delete_reuse=ok"
        )

        with self.assertRaisesRegex(
            M0Error, r"missing=\['delete_open_reuse'\]"
        ):
            serve.validate_case_stdout("disk_cache", stdout)

    def test_rejects_result_before_runtime_end(self) -> None:
        lines = valid_stdout().splitlines()
        result = lines.pop(5)
        lines.insert(3, result)

        with self.assertRaisesRegex(M0Error, "markers are out of order"):
            serve.validate_case_stdout("disk_cache", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_DIR.parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import serve


PREFIX = "CHROMIUM_WASM_M3_PA_ROOT"
RESULT_LINE = (
    f"{PREFIX}:RESULT "
    + " ".join(
        f"{key}={value}" for key, value in serve.PA_ROOT_RESULT_VALUES.items()
    )
)
METRICS = {
    "committed_before_reclaim": "983040",
    "committed_after_reclaim": "0",
    "threads": "4",
    "iterations_per_thread": "128",
    "contention_allocations": "512",
    "roots": "3",
}
METRICS_LINE = (
    f"{PREFIX}:METRICS "
    + " ".join(f"{key}={value}" for key, value in METRICS.items())
)
PHASE_LINES = tuple(
    f"{PREFIX}:PHASE name={name} status=ok"
    for name in serve.PA_ROOT_PHASE_NAMES
)


def valid_stdout() -> str:
    return "\n".join(
        (
            f"{PREFIX}:RUNTIME_START",
            *PHASE_LINES,
            f"{PREFIX}:RUNTIME_END",
            METRICS_LINE,
            RESULT_LINE,
            f"{PREFIX}:PASS",
        )
    )


class PartitionAllocRootValidatorTest(unittest.TestCase):
    def test_accepts_exact_contract(self) -> None:
        serve.validate_case_stdout("pa_roots", valid_stdout())

    def test_rejects_reordered_phase(self) -> None:
        lines = valid_stdout().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        with self.assertRaisesRegex(M0Error, "phase sequence"):
            serve.validate_case_stdout("pa_roots", "\n".join(lines))

    def test_rejects_duplicate_phase(self) -> None:
        stdout = valid_stdout().replace(
            PHASE_LINES[0], f"{PHASE_LINES[0]}\n{PHASE_LINES[0]}", 1
        )
        with self.assertRaisesRegex(M0Error, "phase sequence"):
            serve.validate_case_stdout("pa_roots", stdout)

    def test_rejects_result_field_drift(self) -> None:
        stdout = valid_stdout().replace(
            "direct_map=ok", "direct_map=wrong", 1
        )
        with self.assertRaisesRegex(M0Error, "mismatched"):
            serve.validate_case_stdout("pa_roots", stdout)

    def test_rejects_extra_result_field(self) -> None:
        stdout = valid_stdout().replace(
            RESULT_LINE, f"{RESULT_LINE} surprise=1", 1
        )
        with self.assertRaisesRegex(M0Error, "unexpected"):
            serve.validate_case_stdout("pa_roots", stdout)

    def test_rejects_nondecimal_metric(self) -> None:
        stdout = valid_stdout().replace(
            "committed_before_reclaim=983040",
            "committed_before_reclaim=960KiB",
            1,
        )
        with self.assertRaisesRegex(M0Error, "decimal integers"):
            serve.validate_case_stdout("pa_roots", stdout)

    def test_rejects_unaligned_committed_metric(self) -> None:
        stdout = valid_stdout().replace(
            "committed_before_reclaim=983040",
            "committed_before_reclaim=983041",
            1,
        )
        with self.assertRaisesRegex(M0Error, "reclaim accounting"):
            serve.validate_case_stdout("pa_roots", stdout)

    def test_rejects_missing_reclamation(self) -> None:
        stdout = valid_stdout().replace(
            "committed_after_reclaim=0",
            "committed_after_reclaim=983040",
            1,
        )
        with self.assertRaisesRegex(M0Error, "reclaim accounting"):
            serve.validate_case_stdout("pa_roots", stdout)

    def test_rejects_execution_count_drift(self) -> None:
        stdout = valid_stdout().replace(
            "contention_allocations=512",
            "contention_allocations=511",
            1,
        )
        with self.assertRaisesRegex(M0Error, "execution counts"):
            serve.validate_case_stdout("pa_roots", stdout)


class PartitionAllocRootSourceContractTest(unittest.TestCase):
    def test_target_uses_public_partition_alloc_group(self) -> None:
        build = (TOOLS_DIR / "BUILD.gn").read_text(encoding="utf-8")
        self.assertIn('executable("m3_partition_alloc_root_smoke")', build)
        self.assertIn(
            "if (!use_partition_alloc) {\n"
            '    executable("m3_partition_alloc_page_smoke")',
            build,
        )
        self.assertIn(
            '"//base/allocator/partition_allocator/src/partition_alloc"',
            build,
        )
        source = (TOOLS_DIR / "m3_partition_alloc_root_smoke.cc").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("partition_alloc/internal/", source)
        self.assertIn(
            "BucketIndexLookup::kMinBucketSize",
            source,
        )

    def test_m3_profile_enables_production_partition_alloc(self) -> None:
        manifest = json.loads(
            (TOOLS_DIR / "toolchain_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        arguments = manifest["m3_content_gn_args"]
        self.assertIn("use_partition_alloc = true", arguments)
        self.assertIn("use_allocator_shim = false", arguments)
        self.assertIn("use_partition_alloc_as_malloc = false", arguments)
        self.assertIn("enable_backup_ref_ptr_support = false", arguments)
        self.assertEqual(serve.PA_ROOT_RESULT_VALUES["production_pa"], "on")

    def test_wasm_thread_cache_is_enabled(self) -> None:
        config = REPO_ROOT / (
            "base/allocator/partition_allocator/src/partition_alloc/"
            "partition_alloc_config.h"
        )
        self.assertIn(
            "PA_BUILDFLAG(IS_POSIX) || PA_BUILDFLAG(IS_WASM)",
            config.read_text(encoding="utf-8"),
        )

    def test_wasm_callers_use_logical_page_transitions(self) -> None:
        allocator = REPO_ROOT / (
            "base/allocator/partition_allocator/src/partition_alloc"
        )
        address_pool = (allocator / "address_pool_manager.cc").read_text(
            encoding="utf-8"
        )
        bucket = (allocator / "partition_bucket.cc").read_text(
            encoding="utf-8"
        )
        root = (allocator / "partition_root.cc").read_text(encoding="utf-8")
        self.assertIn("kReservationPermissions", address_pool)
        self.assertIn("PageRecommitDisposition()", bucket)
        self.assertIn("DirectMapResizeDisposition()", root)


if __name__ == "__main__":
    unittest.main()

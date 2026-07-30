#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_DIR.parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import serve


PREFIX = "CHROMIUM_WASM_M3_PA_PAGE"
RESULT_LINE = (
    f"{PREFIX}:RESULT "
    + " ".join(
        f"{key}={value}" for key, value in serve.PA_PAGE_RESULT_VALUES.items()
    )
)
METRICS = {
    "startup_heap_bytes": "67108864",
    "pre_growth_heap_bytes": "71303168",
    "grown_heap_bytes": "159383552",
    "final_heap_bytes": "159383552",
    "max_heap_bytes": "2147483648",
    "initial_mapped_bytes": "0",
    "growth_request_bytes": "71368704",
    "mapped_during_growth_bytes": "71368704",
    "final_mapped_bytes": "0",
}
METRICS_LINE = (
    f"{PREFIX}:METRICS "
    + " ".join(f"{key}={value}" for key, value in METRICS.items())
)
PHASE_LINES = tuple(
    f"{PREFIX}:PHASE name={name} status=ok"
    for name in serve.PA_PAGE_PHASE_NAMES
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


class PartitionAllocPageValidatorTest(unittest.TestCase):
    def test_accepts_exact_contract(self) -> None:
        serve.validate_case_stdout("pa_pages", valid_stdout())

    def test_rejects_reordered_phase(self) -> None:
        lines = valid_stdout().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        with self.assertRaisesRegex(M0Error, "phase sequence"):
            serve.validate_case_stdout("pa_pages", "\n".join(lines))

    def test_rejects_duplicate_phase(self) -> None:
        stdout = valid_stdout().replace(
            PHASE_LINES[0], f"{PHASE_LINES[0]}\n{PHASE_LINES[0]}", 1
        )
        with self.assertRaisesRegex(M0Error, "phase sequence"):
            serve.validate_case_stdout("pa_pages", stdout)

    def test_rejects_result_field_drift(self) -> None:
        stdout = valid_stdout().replace(
            "granularity_64k=ok", "granularity_64k=wrong", 1
        )
        with self.assertRaisesRegex(M0Error, "mismatched"):
            serve.validate_case_stdout("pa_pages", stdout)

    def test_rejects_extra_result_field(self) -> None:
        stdout = valid_stdout().replace(
            RESULT_LINE, f"{RESULT_LINE} surprise=1", 1
        )
        with self.assertRaisesRegex(M0Error, "unexpected"):
            serve.validate_case_stdout("pa_pages", stdout)

    def test_rejects_nondecimal_metric(self) -> None:
        stdout = valid_stdout().replace(
            "startup_heap_bytes=67108864",
            "startup_heap_bytes=64MiB",
            1,
        )
        with self.assertRaisesRegex(M0Error, "decimal integers"):
            serve.validate_case_stdout("pa_pages", stdout)

    def test_rejects_unaligned_heap_metric(self) -> None:
        stdout = valid_stdout().replace(
            "pre_growth_heap_bytes=71303168",
            "pre_growth_heap_bytes=71303169",
            1,
        )
        with self.assertRaisesRegex(M0Error, "page-aligned"):
            serve.validate_case_stdout("pa_pages", stdout)

    def test_rejects_missing_growth(self) -> None:
        stdout = valid_stdout().replace(
            "grown_heap_bytes=159383552",
            "grown_heap_bytes=71303168",
            1,
        ).replace(
            "final_heap_bytes=159383552",
            "final_heap_bytes=71303168",
            1,
        )
        with self.assertRaisesRegex(M0Error, "heap growth"):
            serve.validate_case_stdout("pa_pages", stdout)

    def test_rejects_mapped_accounting_drift(self) -> None:
        stdout = valid_stdout().replace(
            "mapped_during_growth_bytes=71368704",
            "mapped_during_growth_bytes=65536",
            1,
        )
        with self.assertRaisesRegex(M0Error, "mapped/growth accounting"):
            serve.validate_case_stdout("pa_pages", stdout)


class PartitionAllocPageSourceContractTest(unittest.TestCase):
    def test_target_uses_public_partition_alloc_group(self) -> None:
        build = (TOOLS_DIR / "BUILD.gn").read_text(encoding="utf-8")
        self.assertIn('executable("m3_partition_alloc_page_smoke")', build)
        self.assertIn(
            '"//base/allocator/partition_allocator/src/partition_alloc"',
            build,
        )
        self.assertNotIn(
            "page_allocator_internals_wasm.h",
            (TOOLS_DIR / "m3_partition_alloc_page_smoke.cc").read_text(
                encoding="utf-8"
            ),
        )

    def test_wasm_backend_is_selected_before_posix(self) -> None:
        allocator = REPO_ROOT / (
            "base/allocator/partition_allocator/src/partition_alloc"
        )
        source = (allocator / "page_allocator.cc").read_text(encoding="utf-8")
        wasm = source.index("#if PA_BUILDFLAG(IS_WASM)")
        posix = source.index("#elif PA_BUILDFLAG(IS_POSIX)", wasm)
        self.assertLess(wasm, posix)
        build = (allocator / "BUILD.gn").read_text(encoding="utf-8")
        self.assertIn("page_allocator_internals_wasm.cc", build)


if __name__ == "__main__":
    unittest.main()

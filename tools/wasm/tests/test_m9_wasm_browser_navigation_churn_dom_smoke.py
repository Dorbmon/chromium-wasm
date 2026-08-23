#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M9 native data: navigation-churn smoke."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error, REPO_ROOT
import run_m9_wasm_browser_navigation_churn_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e"}
ARTIFACT_IDENTITY = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "loader": {"bytes": 10, "sha256": "a" * 64},
    "module_name": "chrome_wasm",
    "wasm": {"bytes": 20, "sha256": "b" * 64},
}
CAPTURE_HARNESS_IDENTITY = {
    "host_html": {"bytes": 11, "sha256": "c" * 64},
    "host_js": {"bytes": 12, "sha256": "d" * 64},
    "runner_source": {"bytes": 13, "sha256": "e" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}


def validate(result: dict[str, object]) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
    )


def wasm_heap_buffer_capacity(
    stages: list[dict[str, object]], capacities: list[int] | None = None
) -> dict[str, object]:
    if capacities is None:
        capacities = [
            smoke.WASM_PAGE_SIZE_BYTES
        ] * smoke.WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT
    if len(capacities) != smoke.WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT:
        raise ValueError("Wasm capacity sample count is invalid")
    samples: list[dict[str, object]] = [
        {
            "bufferKind": "SharedArrayBuffer",
            "capacityBytes": capacities[0],
            "frameId": None,
            "heapU8Exported": True,
            "observation": "runtime_initialized",
            "stage": None,
        }
    ]
    for index, stage in enumerate(stages, start=1):
        samples.append(
            {
                "bufferKind": "SharedArrayBuffer",
                "capacityBytes": capacities[index],
                "frameId": stage["backingStoreCopyFrameId"],
                "heapU8Exported": True,
                "observation": "stage_backing_store_copy",
                "stage": index,
            }
        )
    samples.append(
        {
            "bufferKind": "SharedArrayBuffer",
            "capacityBytes": capacities[-1],
            "frameId": None,
            "heapU8Exported": True,
            "observation": "runtime_exit",
            "stage": None,
        }
    )
    return {
        "definition": smoke.WASM_HEAP_BUFFER_CAPACITY_DEFINITION,
        "grew": max(capacities) > capacities[0],
        "highWaterBytes": max(capacities),
        "nondecreasing": all(
            later >= earlier for earlier, later in zip(capacities, capacities[1:])
        ),
        "sampleCount": smoke.WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT,
        "samples": samples,
    }


def native_memory_snapshot(
    stages: list[dict[str, object]],
    capacities: list[int] | None = None,
    *,
    maximum_bytes: int = 2_147_483_648,
    mappings: list[int] | None = None,
) -> dict[str, object]:
    if capacities is None:
        capacities = [smoke.WASM_PAGE_SIZE_BYTES] * smoke.NATIVE_MEMORY_SAMPLE_COUNT
    if len(capacities) != smoke.NATIVE_MEMORY_SAMPLE_COUNT:
        raise ValueError("native memory sample count is invalid")
    if mappings is None:
        mappings = [0] * smoke.NATIVE_MEMORY_SAMPLE_COUNT
    if len(mappings) != smoke.NATIVE_MEMORY_SAMPLE_COUNT:
        raise ValueError("native memory mapping sample count is invalid")

    def sample(
        observation: str, stage: int | None, frame_id: int | None, index: int
    ) -> dict[str, object]:
        return {
            "frameId": frame_id,
            "observation": observation,
            "pageAllocatorTotalMappedBytes": mappings[index],
            "stage": stage,
            "wasmLinearMemoryCapacityBytes": capacities[index],
            "wasmLinearMemoryHeadroomBytes": maximum_bytes - capacities[index],
            "wasmLinearMemoryMaximumBytes": maximum_bytes,
        }

    samples: list[dict[str, object]] = [
        sample("runtime_initialized", None, None, 0)
    ]
    for index, stage in enumerate(stages, start=1):
        samples.append(
            sample(
                "stage_backing_store_copy",
                index,
                stage["backingStoreCopyFrameId"],
                index,
            )
        )
    return {
        "definition": smoke.NATIVE_MEMORY_SNAPSHOT_DEFINITION,
        "nondecreasingLinearCapacity": all(
            later >= earlier for earlier, later in zip(capacities, capacities[1:])
        ),
        "sampleCount": smoke.NATIVE_MEMORY_SAMPLE_COUNT,
        "samples": samples,
    }


def successful_result(
    *, stage_one_history_entries: int = 1, stage_one_history_index: int = 0
) -> dict[str, object]:
    if (
        stage_one_history_entries < 1
        or stage_one_history_index < 0
        or stage_one_history_index >= stage_one_history_entries
    ):
        raise ValueError("stage-one history baseline is invalid")
    stages: list[dict[str, object]] = []
    stderr: list[str] = [
        f"{smoke.READY_MARKER} cycles={smoke.CYCLE_COUNT} "
        f"navigations={smoke.STAGE_COUNT}"
    ]
    # Stage one captures an intentionally unspecified post-navigation
    # baseline. Content may retain or replace startup about:blank; only stages
    # two through six must append one entry/current index from that baseline.
    prior_entries = stage_one_history_entries
    prior_index = stage_one_history_index
    for ordinal in range(1, smoke.STAGE_COUNT + 1):
        info = smoke.stage_info(ordinal)
        is_first_stage = ordinal == 1
        history_entries = prior_entries if is_first_stage else prior_entries + 1
        history_index = prior_index if is_first_stage else prior_index + 1
        stage = {
            **info,
            "historyEntries": history_entries,
            "historyIndex": history_index,
            "historyBaselineEntries": prior_entries,
            "historyBaselineIndex": prior_index,
            "historyAppendVerified": not is_first_stage,
            "forwardHistory": False,
            "backHistory": not is_first_stage,
            "historyExact": True,
            "titleExact": True,
            "rfhLive": True,
            "fvp": True,
            "navigationMarkerFrameId": ordinal,
            "backingStoreCopyFrameId": ordinal + 1,
            "presentationQueued": True,
            "presentedObserved": True,
        }
        stages.append(stage)
        stderr.extend((smoke._navigated_marker(stage), smoke._presented_marker(stage)))
        prior_entries = history_entries
        prior_index = history_index
    stderr.extend(
        (
            f"{smoke.PASS_MARKER} cycles={smoke.CYCLE_COUNT} "
            f"navigations={smoke.STAGE_COUNT}",
            smoke.LIFECYCLE_PASS_MARKER,
        )
    )
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m9GateComplete": False,
        "limitations": list(smoke.LIMITATIONS),
        "artifact": ARTIFACT_IDENTITY,
        "capture_harness": CAPTURE_HARNESS_IDENTITY,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": VERSIONS,
        "frameReports": [
            {
                "id": frame_id,
                "width": 640,
                "height": 480,
                "timestampMs": float(frame_id),
            }
            for frame_id in range(1, smoke.STAGE_COUNT + 2)
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "navigationChurn": {
            "cycleCount": smoke.CYCLE_COUNT,
            "navigationsPerCycle": smoke.NAVIGATIONS_PER_CYCLE,
            "stageCount": smoke.STAGE_COUNT,
            "frameTransitionPolicy": smoke.FRAME_TRANSITION_POLICY,
            "readyObserved": True,
            "passObserved": True,
            "lifecyclePassObserved": True,
            "stages": stages,
        },
        "wasmHeapBufferCapacity": wasm_heap_buffer_capacity(stages),
        "nativeMemorySnapshot": native_memory_snapshot(stages),
        "stdout": [],
        "stderr": stderr,
        "failedChecks": [],
        "error": None,
    }


class M9WasmBrowserNavigationChurnDomSmokeTest(unittest.TestCase):
    def test_accepts_fixed_three_cycle_native_history_evidence(self) -> None:
        validate(successful_result())

    def test_accepts_stage_one_post_navigation_history_baseline(self) -> None:
        # Do not encode an initial NavigationController count/index: either
        # retaining or replacing startup about:blank may lead to this valid
        # post-stage-one baseline before stages two through six append.
        validate(
            successful_result(stage_one_history_entries=2, stage_one_history_index=1)
        )

    def test_accepts_wasm_capacity_growth_as_observation(self) -> None:
        result = successful_result()
        capacities = [
            smoke.WASM_PAGE_SIZE_BYTES,
            smoke.WASM_PAGE_SIZE_BYTES,
            2 * smoke.WASM_PAGE_SIZE_BYTES,
            2 * smoke.WASM_PAGE_SIZE_BYTES,
            3 * smoke.WASM_PAGE_SIZE_BYTES,
            3 * smoke.WASM_PAGE_SIZE_BYTES,
            3 * smoke.WASM_PAGE_SIZE_BYTES,
            4 * smoke.WASM_PAGE_SIZE_BYTES,
        ]
        result["wasmHeapBufferCapacity"] = wasm_heap_buffer_capacity(
            result["navigationChurn"]["stages"], capacities
        )
        validate(result)

    def test_accepts_independent_native_capacity_and_nonmonotonic_mappings(
        self,
    ) -> None:
        result = successful_result()
        page = smoke.WASM_PAGE_SIZE_BYTES
        # Native and HEAPU8 observations are separately refreshed. The native
        # capacity may therefore differ from the retained HEAPU8 evidence;
        # PageAllocator's logical mappings may independently rise and fall.
        result["nativeMemorySnapshot"] = native_memory_snapshot(
            result["navigationChurn"]["stages"],
            [2 * page, 2 * page, 3 * page, 3 * page, 4 * page, 4 * page, 4 * page],
            mappings=[4 * page, page, 8 * page, 0, 3 * page, page, 0],
        )
        validate(result)

    def test_rejects_native_memory_headroom_below_safety_floor(self) -> None:
        result = successful_result()
        sample = result["nativeMemorySnapshot"]["samples"][0]
        sample["wasmLinearMemoryMaximumBytes"] = (
            smoke.MINIMUM_WASM_LINEAR_MEMORY_HEADROOM_BYTES
        )
        sample["wasmLinearMemoryHeadroomBytes"] = (
            smoke.MINIMUM_WASM_LINEAR_MEMORY_HEADROOM_BYTES
            - sample["wasmLinearMemoryCapacityBytes"]
        )

        with self.assertRaisesRegex(M0Error, "required 1 GiB safety floor"):
            validate(result)

    def test_rejects_invalid_native_memory_evidence(self) -> None:
        page = smoke.WASM_PAGE_SIZE_BYTES
        unsafe_aligned = ((smoke.MAX_SAFE_INTEGER // page) + 1) * page

        mutations = (
            (
                lambda result: result["nativeMemorySnapshot"].pop("definition"),
                "native memory snapshot schema is invalid",
            ),
            (
                lambda result: result["nativeMemorySnapshot"].__setitem__(
                    "unexpected", True
                ),
                "native memory snapshot schema is invalid",
            ),
            (
                lambda result: result["nativeMemorySnapshot"].__setitem__(
                    "sampleCount", True
                ),
                "native memory sample count is invalid",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"].pop(),
                "does not have seven samples",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "unexpected", True
                ),
                "native memory sample 0 schema is invalid",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].pop(
                    "wasmLinearMemoryMaximumBytes"
                ),
                "native memory sample 0 schema is invalid",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "pageAllocatorTotalMappedBytes", True
                ),
                "safe nonnegative Wasm-page multiple",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "pageAllocatorTotalMappedBytes", 1.5
                ),
                "safe nonnegative Wasm-page multiple",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "pageAllocatorTotalMappedBytes", unsafe_aligned
                ),
                "safe nonnegative Wasm-page multiple",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "pageAllocatorTotalMappedBytes", 1
                ),
                "safe nonnegative Wasm-page multiple",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "pageAllocatorTotalMappedBytes", -page
                ),
                "safe nonnegative Wasm-page multiple",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "wasmLinearMemoryHeadroomBytes", -page
                ),
                "safe nonnegative Wasm-page multiple",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "wasmLinearMemoryCapacityBytes", 0
                ),
                "capacity is below one page",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].update(
                    wasmLinearMemoryMaximumBytes=0,
                    wasmLinearMemoryHeadroomBytes=0,
                ),
                "maximum is below capacity",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "wasmLinearMemoryHeadroomBytes",
                    result["nativeMemorySnapshot"]["samples"][0][
                        "wasmLinearMemoryHeadroomBytes"
                    ]
                    + page,
                ),
                "headroom is inconsistent",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][1].__setitem__(
                    "frameId",
                    result["navigationChurn"]["stages"][1]["backingStoreCopyFrameId"],
                ),
                "stage/frame copy observation",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][1].__setitem__(
                    "stage", True
                ),
                "stage/frame copy observation",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][0].__setitem__(
                    "stage", 0
                ),
                "is not runtime initialization",
            ),
            (
                lambda result: result["nativeMemorySnapshot"].__setitem__(
                    "nondecreasingLinearCapacity", 1
                ),
                "linear-capacity monotonic flag is invalid",
            ),
            (
                lambda result: result.__setitem__(
                    "nativeMemorySnapshot",
                    native_memory_snapshot(
                        result["navigationChurn"]["stages"],
                        [page, 2 * page, page, 2 * page, 2 * page, 2 * page, 2 * page],
                    ),
                ),
                "linear capacity regressed",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_required_native_memory_exports_are_checked_before_browser_launch(
        self,
    ) -> None:
        exports = (
            'Module["_chromium_wasm_browser_host_navigation_churn_presented"]',
            'Module["ccall"]',
            'Module["_chromium_wasm_browser_host_memory_linear_capacity_bytes"]',
            'Module["_chromium_wasm_browser_host_memory_linear_maximum_bytes"]',
            'Module["_chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes"]',
        )
        loader = "\n".join(exports).encode("utf-8")
        smoke.verify_required_exports(loader)
        for export in exports:
            with self.subTest(export=export):
                with self.assertRaisesRegex(M0Error, "lacks required export"):
                    smoke.verify_required_exports(loader.replace(export.encode(), b""))

    def test_main_rejects_missing_native_export_before_browser_launch(self) -> None:
        server = mock.Mock()
        server.artifacts = {
            "chrome_wasm.js": b"\n".join(
                (
                    b'Module["_chromium_wasm_browser_host_navigation_churn_presented"]',
                    b'Module["ccall"]',
                    b'Module["_chromium_wasm_browser_host_memory_linear_capacity_bytes"]',
                    b'Module["_chromium_wasm_browser_host_memory_linear_maximum_bytes"]',
                )
            )
        }
        stderr = io.StringIO()
        with (
            mock.patch.object(smoke, "check_boundary"),
            mock.patch.object(smoke, "create_server", return_value=server),
            mock.patch.object(smoke, "artifact_identity", return_value={}),
            mock.patch.object(smoke, "capture_harness_identity", return_value={}),
            mock.patch.object(smoke, "load_manifest") as load_manifest,
            mock.patch.object(smoke, "find_browser") as find_browser,
            mock.patch.object(smoke.subprocess, "Popen") as popen,
            mock.patch.object(
                smoke,
                "write_failure_diagnostics",
                return_value=Path("/tmp/m9-navigation-churn-diagnostics.json"),
            ),
            mock.patch.object(sys, "argv", ["navigation-churn-runner"]),
            mock.patch.object(smoke.sys, "stderr", stderr),
        ):
            self.assertEqual(1, smoke.main())

        self.assertIn("lacks required export", stderr.getvalue())
        load_manifest.assert_not_called()
        find_browser.assert_not_called()
        popen.assert_not_called()
        server.server_close.assert_called_once_with()
        server.join_request_handlers.assert_called_once_with(
            timeout=1, description="M9 navigation-churn server"
        )

    def test_rejects_invalid_wasm_capacity_evidence(self) -> None:
        def with_capacities(capacities: list[int]) -> dict[str, object]:
            result = successful_result()
            result["wasmHeapBufferCapacity"] = wasm_heap_buffer_capacity(
                result["navigationChurn"]["stages"], capacities
            )
            return result

        mutations = (
            (
                lambda result: result["wasmHeapBufferCapacity"].__setitem__(
                    "unexpected", True
                ),
                "schema is invalid",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"].__setitem__(
                    "sampleCount", smoke.WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT - 1
                ),
                "sample count is invalid",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"].__setitem__(
                    "sampleCount", float(smoke.WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT)
                ),
                "sample count is invalid",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"].pop(),
                "does not have eight samples",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][0].__setitem__(
                    "unexpected", True
                ),
                "sample 0 schema is invalid",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][0].__setitem__(
                    "capacityBytes", float(smoke.WASM_PAGE_SIZE_BYTES)
                ),
                "positive safe Wasm-page multiple",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][0].__setitem__(
                    "capacityBytes", True
                ),
                "positive safe Wasm-page multiple",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][0].__setitem__(
                    "capacityBytes", smoke.WASM_PAGE_SIZE_BYTES - 1
                ),
                "positive safe Wasm-page multiple",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][1].__setitem__(
                    "bufferKind", "ArrayBuffer"
                ),
                "is not shared",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][1].__setitem__(
                    "heapU8Exported", 1
                ),
                "lacks Uint8Array evidence",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][3].__setitem__(
                    "frameId", 99
                ),
                "stage/frame copy observation",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"]["samples"][0].__setitem__(
                    "stage", 0
                ),
                "is not terminal",
            ),
            (
                lambda result: result.__setitem__(
                    "wasmHeapBufferCapacity",
                    wasm_heap_buffer_capacity(
                        result["navigationChurn"]["stages"],
                        [
                            smoke.WASM_PAGE_SIZE_BYTES,
                            2 * smoke.WASM_PAGE_SIZE_BYTES,
                            smoke.WASM_PAGE_SIZE_BYTES,
                            2 * smoke.WASM_PAGE_SIZE_BYTES,
                            2 * smoke.WASM_PAGE_SIZE_BYTES,
                            2 * smoke.WASM_PAGE_SIZE_BYTES,
                            2 * smoke.WASM_PAGE_SIZE_BYTES,
                            2 * smoke.WASM_PAGE_SIZE_BYTES,
                        ],
                    ),
                ),
                "not nondecreasing",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"].__setitem__(
                    "highWaterBytes", 2 * smoke.WASM_PAGE_SIZE_BYTES
                ),
                "high water is invalid",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"].__setitem__(
                    "grew", True
                ),
                "growth flag is invalid",
            ),
            (
                lambda result: result["wasmHeapBufferCapacity"].__setitem__(
                    "nondecreasing", 1
                ),
                "nondecreasing flag is invalid",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_rejects_history_title_rfh_fvp_or_copy_evidence_failures(self) -> None:
        mutations = (
            (
                lambda result: result["navigationChurn"]["stages"][1].__setitem__(
                    "historyBaselineEntries", 99
                ),
                "did not append from prior history",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][0].__setitem__(
                    "titleExact", False
                ),
                "titleExact is not true",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][3].__setitem__(
                    "rfhLive", False
                ),
                "rfhLive is not true",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][4].__setitem__(
                    "fvp", False
                ),
                "fvp is not true",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][0].__setitem__(
                    "historyAppendVerified", True
                ),
                "stage one did not capture",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][2].__setitem__(
                    "forwardHistory", True
                ),
                "forwardHistory is not false",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][1].__setitem__(
                    "backHistory", False
                ),
                "backHistory is not true",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][0].__setitem__(
                    "backingStoreCopyFrameId", 1
                ),
                "ordered Canvas2D copy evidence",
            ),
            (
                lambda result: result.__setitem__("limitations", []),
                "limitations",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_requires_an_exact_zero_native_process_exit_report(self) -> None:
        mutations = (
            (lambda result: result.pop("processExitCode"), "missing"),
            (
                lambda result: result.__setitem__("processExitCode", True),
                "boolean",
            ),
            (
                lambda result: result.__setitem__("processExitCode", 1),
                "nonzero",
            ),
        )
        for mutate, description in mutations:
            with self.subTest(description=description):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, "processExitCode mismatch"):
                    validate(result)

    def test_rejects_numeric_boolean_aliases_and_marker_reorder(self) -> None:
        mutations = (
            (
                lambda result: result["navigationChurn"].__setitem__(
                    "cycleCount", 3.0
                ),
                "fixed evidence metadata",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][0].__setitem__(
                    "historyEntries", True
                ),
                "historyEntries is invalid",
            ),
            (
                lambda result: result["navigationChurn"]["stages"][0].__setitem__(
                    "presentationQueued", 1
                ),
                "presentationQueued is not true",
            ),
            (
                lambda result: result.__setitem__(
                    "stderr", result["stderr"][:1] + [result["stderr"][2], result["stderr"][1]] + result["stderr"][3:]
                ),
                "invalid order",
            ),
            (
                lambda result: result["stderr"].append(
                    "Some "
                    + " ".join(smoke.DISCARDABLE_MEMORY_MANAGER_LEAK_MARKERS)
                ),
                "live discardable-memory Mojo receiver",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_result_rejects_substituted_product_module(self) -> None:
        result = copy.deepcopy(successful_result())
        result["artifact"]["module_name"] = "alternate_wasm"  # type: ignore[index]
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            validate(result)

    def test_parser_rejects_duplicate_keys_and_wrong_scope(self) -> None:
        result = successful_result()
        payload = json.dumps(result, separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(payload), result)
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,'
                b'"case":"browser_same_instance_navigation_churn_m9"}'
            )
        )
        result["scope"] = "wrong"
        self.assertIsNone(smoke.parse_result_payload(json.dumps(result).encode()))

    def test_server_captures_immutable_artifact_and_harness_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            loader = b'export default function chromeWasm() {}\n'
            wasm = b"\x00asm\x01\x00\x00\x00"
            html = b"<html>navigation churn</html>"
            host_js = b"export const navigationChurn = true;\n"
            runner_source = b"# navigation churn runner source\n"
            (out_dir / "chrome_wasm.js").write_bytes(loader)
            (out_dir / "chrome_wasm.wasm").write_bytes(wasm)
            (host_dir / "chrome_wasm_browser_navigation_churn_smoke.html").write_bytes(html)
            (
                host_dir / "chrome_wasm_browser_navigation_churn_smoke_host.js"
            ).write_bytes(host_js)
            runner_path = root / "runner.py"
            runner_path.write_bytes(runner_source)
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                "test-token",
                queue.Queue(maxsize=1),
                module_name="chrome_wasm",
                host_dir=host_dir,
                runner_source_path=runner_path,
            )
            try:
                (out_dir / "chrome_wasm.js").write_bytes(b"tampered")
                (out_dir / "chrome_wasm.wasm").write_bytes(b"tampered")
                (
                    host_dir / "chrome_wasm_browser_navigation_churn_smoke.html"
                ).write_bytes(b"tampered")
                runner_path.write_bytes(b"tampered")
                self.assertEqual(loader, server.artifacts["chrome_wasm.js"])
                self.assertEqual(wasm, server.artifacts["chrome_wasm.wasm"])
                self.assertEqual(html, server.host_html)
                self.assertEqual(runner_source, server.runner_source)
                artifact = smoke.artifact_identity(server, module_name="chrome_wasm")
                harness = smoke.capture_harness_identity(server)
                self.assertEqual("unverified", artifact["artifact_source_provenance"])
                self.assertEqual(
                    hashlib.sha256(loader).hexdigest(), artifact["loader"]["sha256"]
                )
                self.assertEqual(
                    hashlib.sha256(host_js).hexdigest(), harness["host_js"]["sha256"]
                )
            finally:
                server.server_close()

    def test_rejects_each_unsafe_input_before_server_construction(self) -> None:
        if not hasattr(os, "mkfifo") or not hasattr(os, "symlink"):
            self.skipTest("host lacks FIFO or symbolic-link support")
        protected_paths = (
            Path("out/chrome_wasm.js"),
            Path("out/chrome_wasm.wasm"),
            Path("host/chrome_wasm_browser_navigation_churn_smoke.html"),
            Path("host/chrome_wasm_browser_navigation_churn_smoke_host.js"),
            Path("runner.py"),
        )
        for unsafe_kind in ("fifo", "symlink"):
            for protected_path in protected_paths:
                with self.subTest(
                    unsafe_kind=unsafe_kind, protected_path=protected_path
                ), tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    for path in protected_paths:
                        input_path = root / path
                        input_path.parent.mkdir(parents=True, exist_ok=True)
                        input_path.write_bytes(b"trusted input")
                    unsafe_path = root / protected_path
                    unsafe_path.unlink()
                    if unsafe_kind == "fifo":
                        os.mkfifo(unsafe_path)
                    else:
                        replacement = root / "untrusted-replacement"
                        replacement.write_bytes(b"untrusted replacement")
                        unsafe_path.symlink_to(replacement)
                    with mock.patch.object(
                        smoke, "NavigationChurnSmokeServer"
                    ) as server_constructor:
                        with self.assertRaises(M0Error):
                            smoke.create_server(
                                "127.0.0.1",
                                0,
                                root / "out",
                                "test-token",
                                queue.Queue(maxsize=1),
                                module_name="chrome_wasm",
                                host_dir=root / "host",
                                runner_source_path=root / "runner.py",
                            )
                    server_constructor.assert_not_called()

    def test_rejects_alternate_product_module_at_server_url_and_identity_boundaries(
        self,
    ) -> None:
        alternate_module = "alternate_wasm"
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.create_server(
                "127.0.0.1",
                0,
                Path("/missing-navigation-churn-output"),
                "test-token",
                queue.Queue(maxsize=1),
                module_name=alternate_module,
            )

        server = mock.Mock()
        server.module_name = smoke.PRODUCT_MODULE_NAME
        server.server_address = ("127.0.0.1", 12345)
        server.artifacts = {
            "chrome_wasm.js": b"loader",
            "chrome_wasm.wasm": b"wasm",
        }
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.smoke_url(
                server,
                "test-token",
                VERSIONS,
                artifact=ARTIFACT_IDENTITY,
                capture_harness=CAPTURE_HARNESS_IDENTITY,
                module_name=alternate_module,
                timeout_seconds=15.0,
            )
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.artifact_identity(server, module_name=alternate_module)

        server.module_name = alternate_module
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.smoke_url(
                server,
                "test-token",
                VERSIONS,
                artifact=ARTIFACT_IDENTITY,
                capture_harness=CAPTURE_HARNESS_IDENTITY,
                module_name=smoke.PRODUCT_MODULE_NAME,
                timeout_seconds=15.0,
            )
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            smoke.artifact_identity(server, module_name=smoke.PRODUCT_MODULE_NAME)

    def test_main_rejects_alternate_module_before_server_or_browser(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(smoke, "check_boundary") as check_boundary,
            mock.patch.object(smoke, "create_server") as create_server,
            mock.patch.object(smoke, "find_browser") as find_browser,
            mock.patch.object(
                smoke.sys,
                "argv",
                ["navigation-churn-runner", "--module-name", "alternate_wasm"],
            ),
            mock.patch.object(smoke.sys, "stderr", stderr),
            self.assertRaisesRegex(SystemExit, "^2$"),
        ):
            smoke.main()

        self.assertIn("--module-name must be chrome_wasm", stderr.getvalue())
        check_boundary.assert_not_called()
        create_server.assert_not_called()
        find_browser.assert_not_called()

    def _run_host_query(self, query: str) -> dict[str, object]:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        host = (
            REPO_ROOT
            / "tools/wasm/host/chrome_wasm_browser_navigation_churn_smoke_host.js"
        )
        script = f"""
globalThis.location = {{
  origin: "http://127.0.0.1",
  pathname: "/__m9_browser_navigation_churn__/",
  search: {json.dumps(query)},
}};
let fetchCalls = 0;
globalThis.fetch = () => {{
  fetchCalls += 1;
  throw new Error("unexpected navigation-churn loader fetch");
}};
const host = await import({json.dumps(host.as_uri())});
let error = null;
try {{
  await host.runChromeWasmBrowserNavigationChurnSmokeFromQuery();
}} catch (value) {{
  error = String(value);
}}
process.stdout.write(JSON.stringify({{error, fetchCalls}}));
"""
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        return json.loads(completed.stdout)

    def test_native_memory_ccalls_are_exact_and_fail_closed(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        host = (
            REPO_ROOT
            / "tools/wasm/host/chrome_wasm_browser_navigation_churn_smoke_host.js"
        )
        script = f"""
const {{nativeMemorySample}} = await import({json.dumps(host.as_uri())});
const page = 64 * 1024;
const names = {{
  mapped: "chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes",
  capacity: "chromium_wasm_browser_host_memory_linear_capacity_bytes",
  maximum: "chromium_wasm_browser_host_memory_linear_maximum_bytes",
}};
const values = {{
  [names.mapped]: 2 * page,
  [names.capacity]: 4 * page,
  [names.maximum]: 8 * page,
}};
const calls = [];
const valid = nativeMemorySample({{ccall(name, returnType, argTypes, args) {{
  calls.push([name, returnType, argTypes, args]);
  if (!Object.hasOwn(values, name)) throw new Error("missing export");
  return values[name];
}}}}, "runtime_initialized", null, null);
function failure(module) {{
  try {{
    nativeMemorySample(module, "stage_backing_store_copy", 1, 2);
  }} catch (error) {{
    return String(error);
  }}
  return "accepted";
}}
const missing = failure({{ccall(name) {{
  if (name === names.maximum) throw new Error("missing export");
  return values[name];
}}}});
const throwing = failure({{ccall(name) {{
  if (name === names.mapped) throw new Error("export trapped");
  return values[name];
}}}});
const noCcall = failure({{}});
process.stdout.write(JSON.stringify({{calls, valid, missing, throwing, noCcall, names}}));
"""
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        observed = json.loads(completed.stdout)
        self.assertEqual(
            [
                [
                    observed["names"]["mapped"],
                    "number",
                    [],
                    [],
                ],
                [
                    observed["names"]["capacity"],
                    "number",
                    [],
                    [],
                ],
                [
                    observed["names"]["maximum"],
                    "number",
                    [],
                    [],
                ],
            ],
            observed["calls"],
        )
        self.assertEqual(4 * 64 * 1024, observed["valid"]["wasmLinearMemoryCapacityBytes"])
        self.assertEqual(4 * 64 * 1024, observed["valid"]["wasmLinearMemoryHeadroomBytes"])
        self.assertIn(observed["names"]["maximum"], observed["missing"])
        self.assertIn("failed", observed["missing"])
        self.assertIn(observed["names"]["mapped"], observed["throwing"])
        self.assertIn("failed", observed["throwing"])
        self.assertIn("requires Module.ccall", observed["noCcall"])

    def test_alternate_module_query_is_rejected_before_loader_fetch(self) -> None:
        observed = self._run_host_query("?token=test-token&module=alternate_wasm")
        self.assertIn(
            "must select the chrome_wasm product module", observed["error"]
        )
        self.assertEqual(0, observed["fetchCalls"])

    def test_main_closes_an_unstarted_server_without_shutdown(self) -> None:
        server = mock.Mock()
        server.artifacts = {"chrome_wasm.js": b"loader"}
        server.shutdown.side_effect = AssertionError(
            "an unstarted server must not be shut down"
        )
        server_thread = mock.Mock()
        server_thread.start.side_effect = RuntimeError("server thread start failed")

        with (
            mock.patch.object(smoke, "check_boundary"),
            mock.patch.object(smoke, "create_server", return_value=server),
            mock.patch.object(smoke, "artifact_identity", return_value={}),
            mock.patch.object(smoke, "capture_harness_identity", return_value={}),
            mock.patch.object(smoke, "verify_required_exports"),
            mock.patch.object(smoke, "load_manifest", return_value={}),
            mock.patch.object(smoke, "toolchain_manifest_versions", return_value={}),
            mock.patch.object(smoke.threading, "Thread", return_value=server_thread),
            mock.patch.object(
                smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ) as find_browser,
            mock.patch.object(smoke.subprocess, "Popen") as popen,
            mock.patch.object(sys, "argv", ["navigation-churn-runner"]),
            self.assertRaisesRegex(RuntimeError, "server thread start failed"),
        ):
            smoke.main()

        server.shutdown.assert_not_called()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_not_called()
        find_browser.assert_called_once_with(None)
        popen.assert_not_called()

    def test_main_preserves_unstarted_stderr_reader_failure_and_cleans_up(self) -> None:
        server = mock.Mock()
        server.artifacts = {"chrome_wasm.js": b"loader"}
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = True
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-navigation-churn-profile"
        stderr_thread = mock.Mock()
        stderr_thread.start.side_effect = RuntimeError("stderr reader start failed")
        stderr_thread.join.side_effect = RuntimeError(
            "cannot join thread before it is started"
        )

        with (
            mock.patch.object(smoke, "check_boundary"),
            mock.patch.object(smoke, "create_server", return_value=server),
            mock.patch.object(smoke, "artifact_identity", return_value={}),
            mock.patch.object(smoke, "capture_harness_identity", return_value={}),
            mock.patch.object(smoke, "verify_required_exports"),
            mock.patch.object(smoke, "load_manifest", return_value={}),
            mock.patch.object(smoke, "toolchain_manifest_versions", return_value={}),
            mock.patch.object(
                smoke.threading,
                "Thread",
                side_effect=[server_thread, stderr_thread],
            ),
            mock.patch.object(
                smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                smoke,
                "smoke_url",
                return_value=(
                    "http://127.0.0.1:12345/__m9_browser_navigation_churn__/"
                ),
            ),
            mock.patch.object(
                smoke.tempfile, "TemporaryDirectory", return_value=profile
            ),
            mock.patch.object(
                smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(smoke.subprocess, "Popen", return_value=browser),
            mock.patch.object(smoke, "abort_browser_group") as abort_browser_group,
            mock.patch.object(sys, "argv", ["navigation-churn-runner"]),
            self.assertRaisesRegex(RuntimeError, "stderr reader start failed"),
        ):
            smoke.main()

        server_thread.start.assert_called_once_with()
        abort_browser_group.assert_called_once_with(browser, mock.ANY)
        stderr_thread.join.assert_not_called()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=1)
        server_thread.is_alive.assert_called_once_with()
        profile.cleanup.assert_called_once_with()

    def test_main_rejects_browser_cleanup_without_success_markers(self) -> None:
        server = mock.Mock()
        server.artifacts = {"chrome_wasm.js": b"loader"}
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = True
        stderr_thread = mock.Mock()
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-navigation-churn-profile"
        stdout = io.StringIO()

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(smoke, "check_boundary"))
            stack.enter_context(
                mock.patch.object(smoke, "create_server", return_value=server)
            )
            stack.enter_context(
                mock.patch.object(smoke, "artifact_identity", return_value={})
            )
            stack.enter_context(
                mock.patch.object(smoke, "capture_harness_identity", return_value={})
            )
            stack.enter_context(mock.patch.object(smoke, "verify_required_exports"))
            stack.enter_context(mock.patch.object(smoke, "load_manifest", return_value={}))
            stack.enter_context(
                mock.patch.object(smoke, "toolchain_manifest_versions", return_value={})
            )
            stack.enter_context(
                mock.patch.object(
                    smoke.threading,
                    "Thread",
                    side_effect=[server_thread, stderr_thread],
                )
            )
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "find_browser",
                    return_value=(Path("/fake/browser"), "test-browser"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "smoke_url",
                    return_value=(
                        "http://127.0.0.1:12345/__m9_browser_navigation_churn__/"
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    smoke.tempfile, "TemporaryDirectory", return_value=profile
                )
            )
            stack.enter_context(
                mock.patch.object(
                    smoke,
                    "browser_command",
                    return_value=["/fake/browser", "profile", "url"],
                )
            )
            stack.enter_context(
                mock.patch.object(smoke.subprocess, "Popen", return_value=browser)
            )
            stack.enter_context(mock.patch.object(smoke, "wait_for_result", return_value={}))
            stack.enter_context(mock.patch.object(smoke, "validate_result"))
            stop_browser_group = stack.enter_context(
                mock.patch.object(
                    smoke,
                    "stop_browser_group",
                    side_effect=M0Error("browser group cleanup failed"),
                )
            )
            stack.enter_context(
                mock.patch.object(sys, "argv", ["navigation-churn-runner"])
            )
            stack.enter_context(mock.patch.object(smoke.sys, "stdout", stdout))

            with self.assertRaisesRegex(
                M0Error, "browser group cleanup failed"
            ):
                smoke.main()

        self.assertNotIn(f"{smoke.SENTINEL}:BROWSER_RESULT", stdout.getvalue())
        self.assertNotIn(f"{smoke.SENTINEL}:PASS", stdout.getvalue())
        stop_browser_group.assert_called_once_with(browser, mock.ANY)
        server_thread.start.assert_called_once_with()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=1)
        server_thread.is_alive.assert_called_once_with()

    def test_native_host_and_runner_keep_the_bounded_scope_explicit(self) -> None:
        entrypoint = source("chrome/app/chrome_main_wasm.cc")
        native = source("chrome/browser/wasm/wasm_browser_navigation_churn_smoke.cc")
        native_header = source(
            "chrome/browser/wasm/wasm_browser_navigation_churn_smoke.h"
        )
        bridge = source(
            "chrome/browser/wasm/wasm_browser_host_navigation_churn_smoke.cc"
        )
        host = source(
            "tools/wasm/host/chrome_wasm_browser_navigation_churn_smoke_host.js"
        )
        runner = source("tools/wasm/run_m9_wasm_browser_navigation_churn_dom_smoke.py")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        build = source("chrome/browser/wasm/BUILD.gn")
        self.assertIn("chromium_wasm_report_process_exit(exit_code)", entrypoint)
        self.assertIn("host rejected process-exit report", entrypoint)
        self.assertIn("fputs(", entrypoint)
        self.assertIn("return exit_code == 0 ? 1 : exit_code;", entrypoint)
        self.assertLess(
            entrypoint.index("const int exit_code ="),
            entrypoint.index("chromium_wasm_report_process_exit(exit_code)"),
        )
        for marker in (
            "constexpr int kCycleCount = 3;",
            "constexpr int kNavigationsPerCycle = 2;",
            "data:text/html",
            "CompletedFirstVisuallyNonEmptyPaint",
            "GetPrimaryMainFrame",
            "IsRenderFrameLive",
            "GetEntryCount",
            "GetCurrentEntryIndex",
            "GetEntryAtIndex",
            "CanGoBack",
            "TitleWasSet",
            "history_baseline_captured_",
            "history_baseline_entry_count_",
            "history_baseline_entry_index_",
            "current_stage_history_entry_count_",
            "SchedulePaint()",
            "ClearWasmBrowserHostNavigationChurnSmokeVerificationForTesting",
            "CHROMIUM_WASM_M9_NAVIGATION_CHURN:PRESENTED",
        ):
            with self.subTest(native=marker):
                self.assertIn(marker, native)
        for forbidden in ("Wisp", "WebWorker", "javascript:", "raw_ptr<content::WebContents>"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, native)
        self.assertIn("base::WeakPtr<content::WebContents>", native_header)
        self.assertIn("base::WeakPtrFactory<WasmBrowserNavigationChurnSmoke>", native_header)
        self.assertIn("base::OnceClosure request_shutdown_", native_header)
        self.assertIn("PostOrderlyShutdown", native_header)
        self.assertNotIn("GetEntryCount(), 0", native)
        self.assertNotIn("GetCurrentEntryIndex(), -1", native)
        self.assertIn("base::SingleThreadTaskRunner::GetCurrentDefault", native)
        self.assertIn("std::move(request_shutdown_)", native)
        self.assertIn("weak_ptr_factory_.GetWeakPtr()", native)
        self.assertIn("weak_ptr_factory_.InvalidateWeakPtrs()", native)
        for marker in (
            "expected_stage_ = 1",
            "dispatch_pending_",
            "generation_",
            "chromium_wasm_browser_host_navigation_churn_presented",
        ):
            with self.subTest(bridge=marker):
                self.assertIn(marker, bridge)
        for marker in (
            'const PRODUCT_MODULE_NAME = "chrome_wasm";',
            "parseNavigatedMarker",
            "historyExact",
            "historyBaselineEntries",
            "historyAppendVerified",
            "forwardHistory",
            "backHistory",
            "titleExact",
            "rfhLive",
            "fvp",
            "backingStoreCopyFrameId",
            "wasmHeapBufferCapacitySample",
            "Module.HEAPU8.buffer.byteLength capacity is not allocations",
            "WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT",
            "NATIVE_MEMORY_SAMPLE_COUNT",
            "NATIVE_MEMORY_SNAPSHOT_DEFINITION",
            "nativeMemorySample",
            "nativeMemorySnapshot",
            "chromium_wasm_browser_host_memory_linear_capacity_bytes",
            "chromium_wasm_browser_host_memory_linear_maximum_bytes",
            "chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes",
            "stage_backing_store_copy",
            "wasmHeapBufferCapacity",
            "const observedStage = churn.stages[stage - 1]",
            "artifact_source_provenance",
            "immutable-in-memory-server-snapshot",
            "artifact identity must select the chrome_wasm product module",
            "query must select the chrome_wasm product module",
            "artifacts/${PRODUCT_MODULE_NAME}.js",
            "processExitPromise",
            "processExitCode === null",
            "bridge process exit did not report zero",
            "does not establish raster, compositor,",
        ):
            with self.subTest(host=marker):
                self.assertIn(marker, host)
        self.assertIn("const buffer = heap.buffer;", host)
        self.assertIn("never\n  // retains a buffer or view", host)
        self.assertNotIn("Page.navigate", host)
        self.assertIn("not RSS, committed memory, allocation, residency, leak,", host)
        self.assertIn("out-of-memory, or drain evidence", host)
        report_runtime_exit = host[
            host.index("  #reportRuntimeExit(code) {") : host.index(
                "  #reportProcessExit(value) {"
            )
        ]
        self.assertNotIn("#recordNativeMemory", report_runtime_exit)
        set_module = host[
            host.index("  #setModule(module) {") : host.index("  #stageSnapshot(stage) {")
        ]
        self.assertIn("!this.#recordNativeMemory(\"runtime_initialized\", null, null)", set_module)
        self.assertLess(
            set_module.index("!this.#recordNativeMemory"),
            set_module.index("this.#runtimeInitialized = true"),
        )
        self.assertIn("cannot satisfy the pass\n      // contract", set_module)
        for marker in (
            'HOST_ROOT = "/__m9_browser_navigation_churn__"',
            '"Cross-Origin-Opener-Policy", "same-origin"',
            '"Cross-Origin-Embedder-Policy", "require-corp"',
            '"application/wasm"',
            "verify_required_exports",
            "_validate_wasm_heap_buffer_capacity",
            "WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT",
            "_validate_native_memory_snapshot",
            "NATIVE_MEMORY_SAMPLE_COUNT",
            "NATIVE_MEMORY_SNAPSHOT_DEFINITION",
            "MINIMUM_WASM_LINEAR_MEMORY_HEADROOM_BYTES",
            "nativeMemorySnapshot",
            "_chromium_wasm_browser_host_memory_linear_capacity_bytes",
            "_chromium_wasm_browser_host_memory_linear_maximum_bytes",
            "_chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes",
            "MAX_SAFE_INTEGER",
            "stage/frame copy observation",
            "immutable-in-memory-server-snapshot",
            "wait_for_normal_close_result",
            'PRODUCT_MODULE_NAME = "chrome_wasm"',
            "_require_product_module_name",
            "--module-name must be chrome_wasm",
        ):
            with self.subTest(runner=marker):
                self.assertIn(marker, runner)
        self.assertIn("not RSS, committed memory, allocation, residency, leak,", runner)
        self.assertIn("out-of-memory, or drain evidence", runner)
        self.assertNotIn("ccall(", runner)
        self.assertIn("wasm-browser-host-navigation-churn-smoke", main_parts)
        self.assertIn("BeginNavigationChurnShutdown", lifecycle)
        self.assertIn("weak_ptr_factory_.GetWeakPtr()", lifecycle)
        self.assertIn(
            'source_set("wasm_browser_navigation_churn_smoke")', build
        )
        self.assertIn(
            'source_set("wasm_browser_host_navigation_churn_smoke")', build
        )

    def test_host_javascript_parses_with_node_when_available(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        host = (
            TOOLS_DIR.parents[1]
            / "tools/wasm/host/chrome_wasm_browser_navigation_churn_smoke_host.js"
        )
        completed = subprocess.run(
            [node, "--check", str(host)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "Node rejected navigation-churn host asset:\n"
            + completed.stdout
            + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()

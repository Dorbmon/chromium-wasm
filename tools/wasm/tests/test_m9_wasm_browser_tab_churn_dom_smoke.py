#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the fixed same-instance Chrome Wasm tab-churn smoke."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error, REPO_ROOT
import run_m9_wasm_browser_tab_churn_dom_smoke as smoke
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
    "pointer_input_js": {"bytes": 13, "sha256": "e" * 64},
    "runner_source": {"bytes": 14, "sha256": "f" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}


def validate(
    result: dict[str, object], *, pointer_abi_rejection_seed: bool = False
) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
        expected_pointer_abi_rejection_seed=pointer_abi_rejection_seed,
    )


def pointer_record(
    event_type: str,
    x: int,
    y: int,
    *,
    buttons: int,
) -> dict[str, object]:
    return {
        "type": event_type,
        "trusted": True,
        "cancelable": True,
        "pointerType": "mouse",
        "primary": True,
        "button": 0,
        "buttons": buttons,
        "accepted": True,
        "defaultPrevented": True,
        "x": x,
        "y": y,
        "reason": None,
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


def pointer_abi_rejections(enabled: bool = False) -> dict[str, object]:
    return {
        "protocol": smoke.POINTER_ABI_REJECTIONS_PROTOCOL,
        "phase": (
            smoke.POINTER_ABI_REJECTIONS_PRE_ADAPTER_PHASE
            if enabled
            else smoke.POINTER_ABI_REJECTIONS_DISABLED_PHASE
        ),
        "cases": (
            [
                {
                    "arguments": list(arguments),
                    "expectedResult": 0,
                    "name": name,
                    "operation": operation,
                    "result": 0,
                }
                for name, operation, arguments in smoke.POINTER_ABI_REJECTION_CASES
            ]
            if enabled
            else []
        ),
    }


def successful_result(
    *, pointer_abi_rejection_seed: bool = False
) -> dict[str, object]:
    stages: list[dict[str, object]] = []
    pointer_records: list[dict[str, object]] = []
    stderr: list[str] = []
    for ordinal in range(1, smoke.STAGE_COUNT + 1):
        info = smoke.stage_info(ordinal)
        target = {
            "x": 20 + ordinal,
            "y": 30 + ordinal,
            "clientX": 20.5 + ordinal,
            "clientY": 30.5 + ordinal,
        }
        stages.append(
            {
                **info,
                "target": target,
                "readyFrameId": ordinal,
                "checkQueued": True,
                "verified": True,
                "verifiedFrameId": ordinal,
                "backingStoreCopyFrameId": ordinal + 1,
                "backingStoreCopyQueued": True,
                "passObserved": ordinal == smoke.STAGE_COUNT,
            }
        )
        pointer_records.extend(
            (
                pointer_record("down", target["x"], target["y"], buttons=1),
                pointer_record("up", target["x"], target["y"], buttons=0),
            )
        )
        stderr.extend(
            (
                f"{smoke.READY_MARKER} cycle={info['cycle']} "
                f"stage={ordinal} action={info['action']} "
                f"x={target['x']} y={target['y']}",
                f"{smoke.VERIFIED_MARKER} cycle={info['cycle']} "
                f"stage={ordinal} action={info['action']}",
            )
        )
    stderr.extend(
        (
            f"{smoke.PASS_MARKER} cycles={smoke.CYCLE_COUNT}",
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
        "artifact": ARTIFACT_IDENTITY,
        "capture_harness": CAPTURE_HARNESS_IDENTITY,
        "frameReports": [
            {
                "id": frame_id,
                "width": 640,
                "height": 480,
                "timestampMs": float(frame_id),
            }
            for frame_id in range(1, (smoke.STAGE_COUNT * 2) + 1)
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "ozoneFocusReports": [{"keyboardTargetPresent": True, "active": True}],
        "ozoneCursorReports": [],
        "tabChurn": {
            "cycleCount": smoke.CYCLE_COUNT,
            "frameTransitionPolicy": smoke.FRAME_TRANSITION_POLICY,
            "stageCount": smoke.STAGE_COUNT,
            "stages": stages,
            "pointerRecords": pointer_records,
        },
        "pointerAbiRejections": pointer_abi_rejections(
            pointer_abi_rejection_seed
        ),
        "nativeMemorySnapshot": native_memory_snapshot(stages),
        "stdout": [],
        "stderr": stderr,
        "failedChecks": [],
        "error": None,
    }


class M9WasmBrowserTabChurnDomSmokeTest(unittest.TestCase):
    def test_fixed_three_cycle_scope_and_host_contract_are_explicit(self) -> None:
        entrypoint = source("chrome/app/chrome_main_wasm.cc")
        host = source("tools/wasm/host/chrome_wasm_browser_tab_churn_smoke_host.js")
        runner = source("tools/wasm/run_m9_wasm_browser_tab_churn_dom_smoke.py")
        cxx = source("chrome/browser/wasm/wasm_browser_tab_churn_smoke.cc")
        cxx_header = source("chrome/browser/wasm/wasm_browser_tab_churn_smoke.h")
        verifier = source(
            "chrome/browser/wasm/wasm_browser_host_tab_churn_smoke.cc"
        )
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        build = source("chrome/browser/wasm/BUILD.gn")

        for expected in (
            'const PRODUCT_MODULE_NAME = "chrome_wasm";',
            'const CYCLE_COUNT = 3;',
            '"new-tab", "select-first", "select-second", "close-second"',
            "chromium_wasm_browser_host_tab_churn_check",
            "chromium_wasm_browser_host_tab_churn_presented",
            "awaiting-initial-backing-store-copy",
            "awaiting-trusted-dom-action",
            "setTimeout(() =>",
            "passObserved",
            "backingStoreCopyFrameId",
            "backingStoreCopyQueued",
            "FRAME_TRANSITION_POLICY",
            "backing-store-copy-and-native-memory-observation-only",
            "NATIVE_MEMORY_SAMPLE_COUNT",
            "NATIVE_MEMORY_SNAPSHOT_DEFINITION",
            "nativeMemorySample",
            "nativeMemorySnapshot",
            "validateNativeMemorySnapshot",
            "POINTER_ABI_REJECTIONS_PROTOCOL",
            "POINTER_ABI_REJECTION_CASES",
            "runPointerAbiRejections",
            "pointerAbiRejections",
            "pointerAbiRejectionSeed",
            "after-native-ready-before-trusted-dom-adapter-attach",
            "valid-coordinate-release-without-press",
            "result_one_would_mean_only_queue_and_state_admission",
            "chromium_wasm_browser_host_memory_linear_capacity_bytes",
            "chromium_wasm_browser_host_memory_linear_maximum_bytes",
            "chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes",
            "stage_backing_store_copy",
            "does_not_exercise_navigation_or_page_javascript",
            "does_not_exercise_page_webassembly",
            "does_not_exercise_wisp_or_network_reconnect",
            "does_not_prove_opfs_persistence_or_recovery",
            "does_not_measure_or_exhaust_the_pthread_pool",
            "does_not_prove_raster_compositor_display_or_vsync_presentation",
            "artifact_source_provenance",
            "immutable-in-memory-server-snapshot",
            "artifact identity must select the chrome_wasm product module",
            "query must select the chrome_wasm product module",
            "artifacts/${PRODUCT_MODULE_NAME}.js",
            "report.protocol !== HOST_PROTOCOL",
            "processExitPromise",
            "processExitCode === null",
            "bridge process exit did not report zero",
            "do not establish raster, compositor, display, vsync, RSS, committed memory",
            "not RSS, committed memory, allocation, residency, leak,",
            "out-of-memory, or drain evidence",
        ):
            with self.subTest(host=expected):
                self.assertIn(expected, host)
        for expected in (
            "client.dispatch_primary_click",
            "__chromiumWasmM9TabChurnState",
            "--wasm-browser-host-tab-churn-smoke",
            "fixed-three-cycle-same-instance-tab-churn-with-later-",
            'PRODUCT_MODULE_NAME = "chrome_wasm"',
            "_require_product_module_name",
            "--module-name must be chrome_wasm",
            "ARTIFACT_SOURCE_PROVENANCE = \"unverified\"",
            "artifact_identity",
            "capture_harness_identity",
            "toolchain_manifest_versions",
            "backingStoreCopyFrameId",
            "verify_required_exports",
            "_validate_native_memory_snapshot",
            "NATIVE_MEMORY_SAMPLE_COUNT",
            "NATIVE_MEMORY_SNAPSHOT_DEFINITION",
            "MINIMUM_WASM_LINEAR_MEMORY_HEADROOM_BYTES",
            "nativeMemorySnapshot",
            "POINTER_ABI_REJECTIONS_PROTOCOL",
            "POINTER_ABI_REJECTION_CASES",
            "_validate_pointer_abi_rejections",
            "pointerAbiRejections",
            "--pointer-abi-rejection-seed",
            "pointerAbiRejectionSeed",
            "_chromium_wasm_browser_host_memory_linear_capacity_bytes",
            "_chromium_wasm_browser_host_memory_linear_maximum_bytes",
            "_chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes",
            "MAX_SAFE_INTEGER",
            "stage/frame copy observation",
        ):
            with self.subTest(runner=expected):
                self.assertIn(expected, runner)
        self.assertIn("not RSS, committed memory, allocation, residency, leak,", runner)
        self.assertIn("out-of-memory, or drain evidence", runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("Runtime.evaluate", runner)
        report_runtime_exit = host[
            host.index("  #reportRuntimeExit(code) {") : host.index(
                "  #reportProcessExit(value) {"
            )
        ]
        self.assertNotIn("#recordNativeMemory", report_runtime_exit)
        set_module = host[
            host.index("  #setModule(module) {") : host.index("  #result(status, error) {")
        ]
        self.assertIn(
            "!this.#recordNativeMemory(\"runtime_initialized\", null, null)",
            set_module,
        )
        self.assertLess(
            set_module.index("!this.#recordNativeMemory"),
            set_module.index("this.#runtimeInitialized = true"),
        )
        self.assertIn("cannot satisfy pass", set_module)
        self.assertNotIn("runPointerAbiRejections(", set_module)
        self.assertNotIn("new ChromiumWasmTrustedPointerInput", set_module)
        initial_copy_attach = host[
            host.index(
                "  #attachPointerInputAfterInitialBackingStoreCopy() {"
            ) : host.index(
                "  #recordOutput(value) {"
            )
        ]
        self.assertLess(
            initial_copy_attach.index("runPointerAbiRejections("),
            initial_copy_attach.index("new ChromiumWasmTrustedPointerInput"),
        )
        initial_activation = host[
            host.index(
                "  #activateInitialStageAfterFirstBackingStoreCopy() {"
            ) : host.index(
                "  #attachPointerInputAfterInitialBackingStoreCopy() {"
            )
        ]
        self.assertIn("!this.#module", initial_activation)
        self.assertIn("this.#frameReports.at(0)", initial_activation)
        self.assertLess(
            initial_activation.index("active.readyFrameId = firstFrame.id"),
            initial_activation.index(
                "this.#attachPointerInputAfterInitialBackingStoreCopy()"
            ),
        )
        report_frame = host[
            host.index("  #reportFrame(value) {") : host.index(
                "  #reportReadiness(value) {"
            )
        ]
        self.assertLess(
            report_frame.index("appendBounded(this.#frameReports"),
            report_frame.index("#activateInitialStageAfterFirstBackingStoreCopy"),
        )
        record_output = host[
            host.index("  #recordOutput(value) {") : host.index("  #setModule(module) {")
        ]
        self.assertLess(
            record_output.index("this.#stages.push({"),
            record_output.index("if (initialStage)"),
        )
        self.assertLess(
            record_output.index("if (initialStage)"),
            record_output.index("this.#activateInitialStageAfterFirstBackingStoreCopy();"),
        )
        self.assertLess(
            set_module.index("this.#module = module;"),
            set_module.index("this.#activateInitialStageAfterFirstBackingStoreCopy();"),
        )
        self.assertLess(
            set_module.index("this.#activateInitialStageAfterFirstBackingStoreCopy();"),
            set_module.index("this.#updateState();"),
        )
        queue_verifier = host[
            host.index("  #queueVerifier(") : host.index("  #maybeQueueCheck() {")
        ]
        self.assertLess(
            queue_verifier.index("#recordNativeMemory"),
            queue_verifier.index("this.#module.ccall(name"),
        )
        backing_store_copy = host[
            host.index("  #maybeQueueBackingStoreCopy() {") : host.index(
                "  #recordPointer(record) {"
            )
        ]
        self.assertIn("stage_backing_store_copy", queue_verifier)
        self.assertIn("true);", backing_store_copy)
        self.assertIn("chromium_wasm_report_process_exit(exit_code)", entrypoint)
        self.assertIn("host rejected process-exit report", entrypoint)
        self.assertIn("fputs(", entrypoint)
        self.assertIn("return exit_code == 0 ? 1 : exit_code;", entrypoint)
        self.assertLess(
            entrypoint.index("const int exit_code ="),
            entrypoint.index("chromium_wasm_report_process_exit(exit_code)"),
        )
        for expected in (
            "constexpr int kCycleCount = 3;",
            "constexpr int kActionsPerCycle = 4;",
            "tab_strip_model->count() != 2",
            "tab_strip_model->count() != 1",
            "SchedulePaint()",
            "ClearWasmBrowserHostTabChurnSmokeVerificationForTesting",
            "CHROMIUM_WASM_M9_TAB_CHURN:PASS",
            "GetWeakPtr()",
            "second_contents_.reset()",
            "VerifyBackingStoreCopy",
            "does not prove raster, compositor,",
        ):
            with self.subTest(cxx=expected):
                self.assertIn(expected, cxx)
        for forbidden in (
            "NavigationController",
            "LoadURL",
            "Wisp",
            "WebWorker",
            "raw_ptr<content::WebContents>",
            "VerifyPresentation",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, cxx)
        self.assertIn("base::WeakPtr<content::WebContents>", cxx_header)
        self.assertNotIn("raw_ptr<content::WebContents>", cxx_header)
        for expected in (
            "expected_stage_ = 1",
            "dispatch_pending_",
            "generation_",
            "HostTabChurnExpectedCallback::kBackingStoreCopy",
            "chromium_wasm_browser_host_tab_churn_check",
            "chromium_wasm_browser_host_tab_churn_presented",
        ):
            with self.subTest(verifier=expected):
                self.assertIn(expected, verifier)
        self.assertIn("wasm-browser-host-tab-churn-smoke", main_parts)
        self.assertIn('source_set("wasm_browser_tab_churn_smoke")', build)
        self.assertIn('source_set("wasm_browser_host_tab_churn_smoke")', build)

    def test_single_process_renderer_releases_before_profile_teardown(self) -> None:
        profile = source("chrome/browser/wasm/wasm_profile.cc")
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        shutdown = profile[
            profile.index("void WasmProfile::Shutdown()") : profile.index(
                "void WasmProfile::BeginPrefsShutdownFence"
            )
        ]
        finish_shutdown = main_parts[
            main_parts.index(
                "void WasmBrowserMainParts::FinishShutdown()"
            ) : main_parts.index(
                "void WasmBrowserMainParts::ShutdownFoundation()"
            )
        ]

        self.assertIn(
            '#include "content/public/browser/render_process_host.h"', profile
        )
        self.assertIn("CHECK(!browser_lifecycle_);", finish_shutdown)
        self.assertIn("CHECK(!browser_window_lifecycle_);", finish_shutdown)
        self.assertIn("MaybeSendDestroyedNotification();", shutdown)
        self.assertIn(
            "content::RenderProcessHost::run_renderer_in_process()", shutdown
        )
        self.assertIn(
            "content::RenderProcessHost::ShutDownInProcessRenderer()", shutdown
        )
        self.assertIn(
            "DependencyManager::PerformInterlockedTwoPhaseShutdown", shutdown
        )
        self.assertIn("ShutdownStoragePartitions();", shutdown)
        self.assertLess(
            shutdown.index("MaybeSendDestroyedNotification();"),
            shutdown.index(
                "content::RenderProcessHost::ShutDownInProcessRenderer()"
            ),
        )
        self.assertLess(
            shutdown.index(
                "content::RenderProcessHost::ShutDownInProcessRenderer()"
            ),
            shutdown.index("DependencyManager::PerformInterlockedTwoPhaseShutdown"),
        )
        self.assertLess(
            shutdown.index(
                "content::RenderProcessHost::ShutDownInProcessRenderer()"
            ),
            shutdown.index("ShutdownStoragePartitions();"),
        )
        self.assertLess(
            finish_shutdown.index("profile_->Shutdown();"),
            finish_shutdown.index("profile_.reset();"),
        )

    def test_accepts_complete_three_cycle_evidence(self) -> None:
        result = successful_result()
        validate(result)

    def test_accepts_exact_opt_in_pointer_abi_rejection_evidence(self) -> None:
        result = successful_result(pointer_abi_rejection_seed=True)
        validate(result, pointer_abi_rejection_seed=True)
        with self.assertRaisesRegex(
            M0Error, "pointer ABI rejection phase is invalid"
        ):
            validate(result)

    def test_rejects_invalid_pointer_abi_rejection_evidence(self) -> None:
        mutations = (
            (
                lambda result: result["pointerAbiRejections"].pop("protocol"),
                "pointer ABI rejection evidence schema is invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"].__setitem__(
                    "unexpected", True
                ),
                "pointer ABI rejection evidence schema is invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"].__setitem__(
                    "protocol", True
                ),
                "pointer ABI rejection protocol is invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"].__setitem__(
                    "phase", smoke.POINTER_ABI_REJECTIONS_DISABLED_PHASE
                ),
                "pointer ABI rejection phase is invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"]["cases"].pop(),
                "pointer ABI rejection case count is invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"]["cases"][0].pop(
                    "result"
                ),
                "pointer ABI rejection case 0 schema is invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"]["cases"][0].__setitem__(
                    "arguments", [True, 0, 0, 0]
                ),
                "pointer ABI rejection case 0 arguments are invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"]["cases"][0].__setitem__(
                    "operation", "pointer-exit"
                ),
                "pointer ABI rejection case 0 descriptor is invalid",
            ),
            (
                lambda result: result["pointerAbiRejections"]["cases"][0].__setitem__(
                    "expectedResult", True
                ),
                "pointer ABI rejection case 0 expectedResult did not reject exactly",
            ),
            (
                lambda result: result["pointerAbiRejections"]["cases"][0].__setitem__(
                    "result", True
                ),
                "pointer ABI rejection case 0 result did not reject exactly",
            ),
            (
                lambda result: result["pointerAbiRejections"]["cases"].reverse(),
                "pointer ABI rejection case 0 arguments are invalid",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = successful_result(pointer_abi_rejection_seed=True)
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result, pointer_abi_rejection_seed=True)

    def test_rejects_pointer_abi_rejection_seed_cases_when_disabled(self) -> None:
        result = successful_result()
        result["pointerAbiRejections"]["cases"] = [  # type: ignore[index]
            {
                "arguments": [],
                "expectedResult": 0,
                "name": "exit-without-unpressed-hover",
                "operation": "pointer-exit",
                "result": 0,
            }
        ]
        with self.assertRaisesRegex(
            M0Error, "pointer ABI rejection case count is invalid"
        ):
            validate(result)

    def test_accepts_independent_native_capacity_and_nonmonotonic_mappings(
        self,
    ) -> None:
        result = successful_result()
        page = smoke.WASM_PAGE_SIZE_BYTES
        # Native observations are independent from the retained HEAPU8 pointer
        # bridge. PageAllocator's logical mappings can independently rise and
        # fall, so this is intentionally not a leak or monotonicity assertion.
        result["nativeMemorySnapshot"] = native_memory_snapshot(
            result["tabChurn"]["stages"],  # type: ignore[index]
            [
                2 * page,
                2 * page,
                3 * page,
                3 * page,
                4 * page,
                4 * page,
                4 * page,
                5 * page,
                5 * page,
                5 * page,
                6 * page,
                6 * page,
                6 * page,
            ],
            mappings=[
                4 * page,
                page,
                8 * page,
                0,
                3 * page,
                page,
                0,
                7 * page,
                2 * page,
                0,
                9 * page,
                page,
                0,
            ],
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
                "does not have thirteen samples",
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
                    result["tabChurn"]["stages"][1]["backingStoreCopyFrameId"],
                ),
                "stage/frame copy observation",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][1].__setitem__(
                    "frameId", True
                ),
                "stage/frame copy observation",
            ),
            (
                lambda result: result["nativeMemorySnapshot"]["samples"][1].__setitem__(
                    "observation", "runtime_initialized"
                ),
                "observation is invalid",
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
                        result["tabChurn"]["stages"],  # type: ignore[index]
                        [
                            page,
                            2 * page,
                            page,
                            2 * page,
                            2 * page,
                            2 * page,
                            2 * page,
                            2 * page,
                            2 * page,
                            2 * page,
                            2 * page,
                            2 * page,
                            2 * page,
                        ],
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
            'Module["_chromium_wasm_browser_host_pointer"]',
            'Module["_chromium_wasm_browser_host_pointer_exit"]',
            'Module["_chromium_wasm_browser_host_tab_churn_check"]',
            'Module["_chromium_wasm_browser_host_tab_churn_presented"]',
            'Module["_malloc"]',
            'Module["_free"]',
            'Module["ccall"]',
            'Module["HEAPU8"]',
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
                    b'Module["_chromium_wasm_browser_host_pointer"]',
                    b'Module["_chromium_wasm_browser_host_pointer_exit"]',
                    b'Module["_chromium_wasm_browser_host_tab_churn_check"]',
                    b'Module["_chromium_wasm_browser_host_tab_churn_presented"]',
                    b'Module["_malloc"]',
                    b'Module["_free"]',
                    b'Module["ccall"]',
                    b'Module["HEAPU8"]',
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
                return_value=Path("/tmp/m9-tab-churn-diagnostics.json"),
            ),
            mock.patch.object(sys, "argv", ["tab-churn-runner"]),
            mock.patch.object(smoke.sys, "stderr", stderr),
        ):
            self.assertEqual(1, smoke.main())

        self.assertIn("lacks required export", stderr.getvalue())
        load_manifest.assert_not_called()
        find_browser.assert_not_called()
        popen.assert_not_called()
        server.server_close.assert_called_once_with()
        server.join_request_handlers.assert_called_once_with(
            timeout=1, description="M9 tab-churn server"
        )

    def test_rejects_missing_final_marker_bad_copy_evidence_and_trusted_click(self) -> None:
        mutations = (
            (
                lambda result: result["tabChurn"]["stages"][-1].__setitem__(
                    "passObserved", False
                ),
                "pass observation",
            ),
            (
                lambda result: result["tabChurn"]["stages"][4].__setitem__(
                    "backingStoreCopyFrameId", 5
                ),
                "ordered Canvas2D copy evidence",
            ),
            (
                lambda result: result["tabChurn"]["pointerRecords"][0].__setitem__(
                    "trusted", False
                ),
                "pointer down trusted",
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

    def test_rejects_numeric_boolean_aliases_in_exact_tab_churn_evidence(self) -> None:
        mutations = (
            (
                lambda result: result["tabChurn"]["stages"][2].__setitem__(
                    "cycle", 1.0
                ),
                "cycle is invalid",
            ),
            (
                lambda result: result["tabChurn"]["stages"][0].__setitem__(
                    "stage", True
                ),
                "stage is invalid",
            ),
            (
                lambda result: result["tabChurn"].__setitem__("cycleCount", 3.0),
                "cycle or stage count",
            ),
            (
                lambda result: result["tabChurn"]["pointerRecords"][0].__setitem__(
                    "button", False
                ),
                "pointer down button",
            ),
            (
                lambda result: result["tabChurn"]["pointerRecords"][0].__setitem__(
                    "buttons", True
                ),
                "pointer down buttons",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_rejects_impossible_or_reordered_backing_store_copy_frames(self) -> None:
        mutations = (
            (
                lambda result: result["tabChurn"]["stages"][0].__setitem__(
                    "readyFrameId", 999
                ),
                "readyFrameId is invalid",
            ),
            (
                lambda result: result["tabChurn"]["stages"][0].__setitem__(
                    "verifiedFrameId", 999
                ),
                "verifiedFrameId is invalid",
            ),
            (
                lambda result: result["tabChurn"]["stages"][0].__setitem__(
                    "backingStoreCopyFrameId", 999
                ),
                "backingStoreCopyFrameId is invalid",
            ),
            (
                lambda result: result["tabChurn"]["stages"][0].update(
                    {"readyFrameId": 2, "verifiedFrameId": 1}
                ),
                "ordered Canvas2D copy evidence",
            ),
            (
                lambda result: result["frameReports"][1].__setitem__("id", 1),
                "not monotonic",
            ),
            (
                lambda result: result["tabChurn"]["stages"][0].__setitem__(
                    "backingStoreCopyFrameId", 20
                ),
                "cross-stage copy chronology",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    validate(result)

    def test_rejects_reordered_ready_verified_pass_and_lifecycle_markers(self) -> None:
        result = successful_result()
        ready = [line for line in result["stderr"] if line.startswith(smoke.READY_MARKER)]
        verified = [
            line for line in result["stderr"] if line.startswith(smoke.VERIFIED_MARKER)
        ]
        result["stderr"] = ready + verified + [
            f"{smoke.PASS_MARKER} cycles={smoke.CYCLE_COUNT}",
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "temporal order"):
            validate(result)

        result = successful_result()
        result["stderr"][-2:] = [
            smoke.LIFECYCLE_PASS_MARKER,
            f"{smoke.PASS_MARKER} cycles={smoke.CYCLE_COUNT}",
        ]
        with self.assertRaisesRegex(M0Error, "final PASS/lifecycle marker order"):
            validate(result)

    def test_rejects_artifact_or_harness_identity_mismatch(self) -> None:
        for mutate, expression in (
            (
                lambda result: result["artifact"].__setitem__(
                    "artifact_source_provenance", "checkout"
                ),
                "source provenance",
            ),
            (
                lambda result: result["artifact"]["loader"].__setitem__(
                    "sha256", "0" * 64
                ),
                "artifact identity disagrees",
            ),
            (
                lambda result: result["capture_harness"].__setitem__(
                    "version_provenance", "artifact-commit"
                ),
                "version provenance",
            ),
        ):
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

    def test_marker_parser_rejects_duplicate_or_wrong_scope_results(self) -> None:
        result = successful_result()
        encoded = json.dumps(result, separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(encoded), result)
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,"case":"browser_same_instance_tab_churn_m9"}'
            )
        )
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":true,"case":"browser_same_instance_tab_churn_m9"}'
            )
        )
        wrong_scope = copy.deepcopy(result)
        wrong_scope["scope"] = "navigation"
        self.assertIsNone(
            smoke.parse_result_payload(
                json.dumps(wrong_scope, separators=(",", ":")).encode()
            )
        )

    def test_pointer_abi_rejection_seed_url_is_opt_in_and_bounded(self) -> None:
        server = mock.Mock()
        server.module_name = smoke.PRODUCT_MODULE_NAME
        server.server_address = ("127.0.0.1", 12345)
        default_url = smoke.smoke_url(
            server,
            "test-token",
            VERSIONS,
            artifact=ARTIFACT_IDENTITY,
            capture_harness=CAPTURE_HARNESS_IDENTITY,
            module_name=smoke.PRODUCT_MODULE_NAME,
            timeout_seconds=15.0,
        )
        seeded_url = smoke.smoke_url(
            server,
            "test-token",
            VERSIONS,
            artifact=ARTIFACT_IDENTITY,
            capture_harness=CAPTURE_HARNESS_IDENTITY,
            module_name=smoke.PRODUCT_MODULE_NAME,
            timeout_seconds=15.0,
            pointer_abi_rejection_seed=True,
        )
        self.assertNotIn("pointerAbiRejectionSeed", default_url)
        self.assertIn("pointerAbiRejectionSeed=1", seeded_url)
        with self.assertRaisesRegex(
            M0Error, "pointer ABI rejection seed flag is invalid"
        ):
            smoke.smoke_url(
                server,
                "test-token",
                VERSIONS,
                artifact=ARTIFACT_IDENTITY,
                capture_harness=CAPTURE_HARNESS_IDENTITY,
                module_name=smoke.PRODUCT_MODULE_NAME,
                timeout_seconds=15.0,
                pointer_abi_rejection_seed=1,  # type: ignore[arg-type]
            )

    def test_server_captures_immutable_artifact_and_harness_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            loader = b"export default function chromeWasm() {}\n"
            wasm = b"\x00asm\x01\x00\x00\x00"
            html = b"<html>tab churn</html>"
            host_js = b"export const tabChurn = true;\n"
            pointer_js = b"export const pointer = true;\n"
            runner_source = b"# tab churn runner source\n"
            (out_dir / "chrome_wasm.js").write_bytes(loader)
            (out_dir / "chrome_wasm.wasm").write_bytes(wasm)
            (host_dir / "chrome_wasm_browser_tab_churn_smoke.html").write_bytes(html)
            (
                host_dir / "chrome_wasm_browser_tab_churn_smoke_host.js"
            ).write_bytes(host_js)
            (host_dir / "chrome_wasm_pointer_input.js").write_bytes(pointer_js)
            runner_path = root / "runner.py"
            runner_path.write_bytes(runner_source)
            result_queue = queue.Queue(maxsize=1)
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                "test-token",
                result_queue,
                module_name="chrome_wasm",
                host_dir=host_dir,
                runner_source_path=runner_path,
            )
            try:
                (out_dir / "chrome_wasm.js").write_bytes(b"tampered")
                (out_dir / "chrome_wasm.wasm").write_bytes(b"tampered")
                (host_dir / "chrome_wasm_browser_tab_churn_smoke.html").write_bytes(
                    b"tampered"
                )
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
                    hashlib.sha256(wasm).hexdigest(), artifact["wasm"]["sha256"]
                )
                self.assertEqual(
                    hashlib.sha256(host_js).hexdigest(), harness["host_js"]["sha256"]
                )
                self.assertEqual(
                    hashlib.sha256(runner_source).hexdigest(),
                    harness["runner_source"]["sha256"],
                )
            finally:
                server.server_close()

    def test_rejects_each_unsafe_input_before_server_construction(self) -> None:
        if not hasattr(os, "mkfifo") or not hasattr(os, "symlink"):
            self.skipTest("host lacks FIFO or symbolic-link support")
        protected_paths = (
            Path("out/chrome_wasm.js"),
            Path("out/chrome_wasm.wasm"),
            Path("host/chrome_wasm_browser_tab_churn_smoke.html"),
            Path("host/chrome_wasm_browser_tab_churn_smoke_host.js"),
            Path("host/chrome_wasm_pointer_input.js"),
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
                        smoke, "TabChurnSmokeServer"
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
                Path("/missing-tab-churn-output"),
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
                ["tab-churn-runner", "--module-name", "alternate_wasm"],
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
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_browser_tab_churn_smoke_host.js"
        script = f"""
globalThis.location = {{
  origin: "http://127.0.0.1",
  pathname: "/__m9_browser_tab_churn__/",
  search: {json.dumps(query)},
}};
let fetchCalls = 0;
globalThis.fetch = () => {{
  fetchCalls += 1;
  throw new Error("unexpected tab-churn loader fetch");
}};
const host = await import({json.dumps(host.as_uri())});
let error = null;
try {{
  await host.runChromeWasmBrowserTabChurnSmokeFromQuery();
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
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_browser_tab_churn_smoke_host.js"
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
        self.assertEqual(
            4 * 64 * 1024, observed["valid"]["wasmLinearMemoryCapacityBytes"]
        )
        self.assertEqual(
            4 * 64 * 1024, observed["valid"]["wasmLinearMemoryHeadroomBytes"]
        )
        self.assertIn(observed["names"]["maximum"], observed["missing"])
        self.assertIn("failed", observed["missing"])
        self.assertIn(observed["names"]["mapped"], observed["throwing"])
        self.assertIn("failed", observed["throwing"])
        self.assertIn("requires Module.ccall", observed["noCcall"])

    def test_pointer_abi_rejection_seed_ccalls_are_exact_and_fail_closed(
        self,
    ) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_browser_tab_churn_smoke_host.js"
        script = f"""
const {{runPointerAbiRejections, validatePointerAbiRejections}} = await import(
    {json.dumps(host.as_uri())});
const calls = [];
const enabled = runPointerAbiRejections({{ccall(name, returnType, argTypes, args) {{
  calls.push([name, returnType, argTypes, args]);
  return 0;
}}}}, true);
const disabled = runPointerAbiRejections(null, false);
function failure(module, enabled = true) {{
  try {{
    runPointerAbiRejections(module, enabled);
  }} catch (error) {{
    return String(error);
  }}
  return "accepted";
}}
const nonzero = failure({{ccall: () => 1}});
const boolean = failure({{ccall: () => true}});
const missing = failure({{}});
const badFlag = failure(null, 1);
function validation(evidence) {{
  const failures = [];
  validatePointerAbiRejections(
      {{pointerAbiRejections: evidence}},
      (condition, message) => {{ if (!condition) failures.push(message); }});
  return failures;
}}
const badEvidence = structuredClone(enabled);
badEvidence.cases[0].result = true;
process.stdout.write(JSON.stringify({{
  calls, enabled, disabled, nonzero, boolean, missing, badFlag,
  enabledValidation: validation(enabled),
  disabledValidation: validation(disabled),
  badValidation: validation(badEvidence),
}}));
"""
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        observed = json.loads(completed.stdout)
        self.assertEqual(
            smoke.POINTER_ABI_REJECTIONS_PROTOCOL, observed["enabled"]["protocol"]
        )
        self.assertEqual(
            smoke.POINTER_ABI_REJECTIONS_PRE_ADAPTER_PHASE,
            observed["enabled"]["phase"],
        )
        self.assertEqual(
            smoke.POINTER_ABI_REJECTIONS_DISABLED_PHASE,
            observed["disabled"]["phase"],
        )
        self.assertEqual([], observed["disabled"]["cases"])
        self.assertEqual(
            [
                {
                    "arguments": list(arguments),
                    "expectedResult": 0,
                    "name": name,
                    "operation": operation,
                    "result": 0,
                }
                for name, operation, arguments in smoke.POINTER_ABI_REJECTION_CASES
            ],
            observed["enabled"]["cases"],
        )
        self.assertEqual(
            [
                [
                    (
                        "chromium_wasm_browser_host_pointer"
                        if operation == "pointer"
                        else "chromium_wasm_browser_host_pointer_exit"
                    ),
                    "number",
                    ["number", "number", "number", "number"]
                    if operation == "pointer"
                    else [],
                    list(arguments),
                ]
                for _, operation, arguments in smoke.POINTER_ABI_REJECTION_CASES
            ],
            observed["calls"],
        )
        self.assertIn("returned 1, expected 0", observed["nonzero"])
        self.assertIn("invalid result", observed["boolean"])
        self.assertIn("require Module.ccall", observed["missing"])
        self.assertIn("seed flag is invalid", observed["badFlag"])
        self.assertEqual([], observed["enabledValidation"])
        self.assertEqual([], observed["disabledValidation"])
        self.assertTrue(
            any("did not reject exactly" in message for message in observed["badValidation"])
        )

    def test_alternate_module_query_is_rejected_before_loader_fetch(self) -> None:
        observed = self._run_host_query("?token=test-token&module=alternate_wasm")
        self.assertIn(
            "must select the chrome_wasm product module", observed["error"]
        )
        self.assertEqual(0, observed["fetchCalls"])

    def test_invalid_pointer_abi_rejection_seed_query_is_rejected_before_fetch(
        self,
    ) -> None:
        observed = self._run_host_query(
            "?token=test-token&module=chrome_wasm&pointerAbiRejectionSeed=0"
        )
        self.assertIn("pointer ABI rejection seed is invalid", observed["error"])
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
            mock.patch.object(sys, "argv", ["tab-churn-runner"]),
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
        profile.name = "/tmp/m9-tab-churn-profile"
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
                return_value="http://127.0.0.1:12345/__m9_browser_tab_churn__/",
            ),
            mock.patch.object(
                smoke.tempfile, "TemporaryDirectory", return_value=profile
            ),
            mock.patch.object(smoke, "unused_loopback_port", return_value=12346),
            mock.patch.object(
                smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(smoke.subprocess, "Popen", return_value=browser),
            mock.patch.object(smoke, "abort_browser_group") as abort_browser_group,
            mock.patch.object(sys, "argv", ["tab-churn-runner"]),
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
        profile.name = "/tmp/m9-tab-churn-profile"
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
                        "http://127.0.0.1:12345/__m9_browser_tab_churn__/"
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    smoke.tempfile, "TemporaryDirectory", return_value=profile
                )
            )
            stack.enter_context(
                mock.patch.object(smoke, "unused_loopback_port", return_value=12346)
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
            stack.enter_context(
                mock.patch.object(smoke, "wait_for_page_client", return_value=mock.Mock())
            )
            stack.enter_context(mock.patch.object(smoke, "wait_for_stage", return_value={}))
            stack.enter_context(mock.patch.object(smoke, "click_target"))
            stack.enter_context(mock.patch.object(smoke, "wait_for_result", return_value={}))
            stack.enter_context(mock.patch.object(smoke, "validate_result"))
            stop_browser_group = stack.enter_context(
                mock.patch.object(
                    smoke,
                    "stop_browser_group",
                    side_effect=M0Error("browser group cleanup failed"),
                )
            )
            stack.enter_context(mock.patch.object(sys, "argv", ["tab-churn-runner"]))
            stack.enter_context(mock.patch.object(smoke.sys, "stdout", stdout))

            with self.assertRaisesRegex(M0Error, "browser group cleanup failed"):
                smoke.main()

        self.assertNotIn(f"{smoke.SENTINEL}:BROWSER_RESULT", stdout.getvalue())
        self.assertNotIn(f"{smoke.SENTINEL}:PASS", stdout.getvalue())
        stop_browser_group.assert_called_once_with(browser, mock.ANY)
        server_thread.start.assert_called_once_with()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=1)
        server_thread.is_alive.assert_called_once_with()

    def test_stage_info_is_exactly_three_cycles_of_four_actions(self) -> None:
        self.assertEqual(smoke.STAGE_COUNT, 12)
        self.assertEqual(
            [smoke.stage_info(index)["action"] for index in range(1, 5)],
            list(smoke.ACTIONS),
        )
        self.assertEqual(smoke.stage_info(9), {"cycle": 3, "stage": 9, "action": "new-tab"})
        for invalid in (0, 13, True, 1.0):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(M0Error, "out of range"):
                    smoke.stage_info(invalid)


if __name__ == "__main__":
    unittest.main()

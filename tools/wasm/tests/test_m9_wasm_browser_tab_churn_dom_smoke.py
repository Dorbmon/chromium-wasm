#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the fixed same-instance Chrome Wasm tab-churn smoke."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
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


def validate(result: dict[str, object]) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
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


def successful_result() -> dict[str, object]:
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
        "stdout": [],
        "stderr": stderr,
        "failedChecks": [],
        "error": None,
    }


class M9WasmBrowserTabChurnDomSmokeTest(unittest.TestCase):
    def test_fixed_three_cycle_scope_and_host_contract_are_explicit(self) -> None:
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
            'const CYCLE_COUNT = 3;',
            '"new-tab", "select-first", "select-second", "close-second"',
            "chromium_wasm_browser_host_tab_churn_check",
            "chromium_wasm_browser_host_tab_churn_presented",
            "awaiting-trusted-dom-action",
            "setTimeout(() =>",
            "passObserved",
            "backingStoreCopyFrameId",
            "backingStoreCopyQueued",
            "FRAME_TRANSITION_POLICY",
            "does_not_exercise_navigation_or_page_javascript",
            "does_not_exercise_page_webassembly",
            "does_not_exercise_wisp_or_network_reconnect",
            "does_not_prove_opfs_persistence_or_recovery",
            "does_not_measure_or_exhaust_the_pthread_pool",
            "does_not_prove_raster_compositor_display_or_vsync_presentation",
            "artifact_source_provenance",
            "immutable-in-memory-server-snapshot",
            "not establish raster, compositor, display, or vsync presentation",
        ):
            with self.subTest(host=expected):
                self.assertIn(expected, host)
        for expected in (
            "client.dispatch_primary_click",
            "__chromiumWasmM9TabChurnState",
            "--wasm-browser-host-tab-churn-smoke",
            "fixed-three-cycle-same-instance-tab-churn-with-later-",
            "ARTIFACT_SOURCE_PROVENANCE = \"unverified\"",
            "artifact_identity",
            "capture_harness_identity",
            "toolchain_manifest_versions",
            "backingStoreCopyFrameId",
        ):
            with self.subTest(runner=expected):
                self.assertIn(expected, runner)
        self.assertNotIn("ccall(", runner)
        self.assertNotIn("Runtime.evaluate", runner)
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

    def test_accepts_complete_three_cycle_evidence(self) -> None:
        result = successful_result()
        validate(result)

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

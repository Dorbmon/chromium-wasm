#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M9 native data: navigation-churn smoke."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
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
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
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

    def test_native_host_and_runner_keep_the_bounded_scope_explicit(self) -> None:
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
            "const observedStage = churn.stages[stage - 1]",
            "artifact_source_provenance",
            "immutable-in-memory-server-snapshot",
            "does not establish raster, compositor,",
        ):
            with self.subTest(host=marker):
                self.assertIn(marker, host)
        self.assertNotIn("Page.navigate", host)
        for marker in (
            'HOST_ROOT = "/__m9_browser_navigation_churn__"',
            '"Cross-Origin-Opener-Policy", "same-origin"',
            '"Cross-Origin-Embedder-Policy", "require-corp"',
            '"application/wasm"',
            "verify_required_exports",
            "immutable-in-memory-server-snapshot",
            "wait_for_normal_close_result",
        ):
            with self.subTest(runner=marker):
                self.assertIn(marker, runner)
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

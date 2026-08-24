#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 Chromium AX snapshot semantic mirror."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_wasm_browser_accessibility_snapshot_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}


def successful_result() -> dict[str, object]:
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
        "m8GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "readyObserved": True,
        "navigatedObserved": True,
        "snapshotDelivered": True,
        "passObserved": True,
        "lifecyclePassObserved": True,
        "semanticMirror": {
            "heading": smoke.EXPECTED_HEADING,
            "text": smoke.EXPECTED_TEXT,
            "roleMask": smoke.EXPECTED_ROLE_MASK,
            "controlName": smoke.EXPECTED_CONTROL_NAME,
            "controlPressed": True,
            "controlBounds": smoke.EXPECTED_CONTROL_BOUNDS,
            "controlGeometryMatchesCanvas": True,
            "connected": True,
            "passive": True,
        },
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": VERSIONS,
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "stdout": [],
        "stderr": [
            smoke.READY_MARKER,
            smoke.NAVIGATED_MARKER,
            smoke.DELIVERED_MARKER,
            smoke.PASS_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8WasmBrowserAccessibilitySnapshotDomSmokeTest(unittest.TestCase):
    def test_accepts_one_fixed_passive_semantic_mirror(self) -> None:
        smoke.validate_result(successful_result(), expected_versions=VERSIONS)

    def test_rejects_changed_semantics_bounds_interactivity_or_marker_order(self) -> None:
        mutations = (
            (
                lambda result: result["semanticMirror"].__setitem__(
                    "heading", "host-injected"
                ),
                "semantic mirror does not match",
            ),
            (
                lambda result: result["semanticMirror"].__setitem__(
                    "roleMask", 0
                ),
                "semantic mirror does not match",
            ),
            (
                lambda result: result["semanticMirror"]["controlBounds"].__setitem__(
                    "left", 0
                ),
                "semantic mirror does not match",
            ),
            (
                lambda result: result["semanticMirror"].__setitem__(
                    "controlGeometryMatchesCanvas", False
                ),
                "semantic mirror does not match",
            ),
            (
                lambda result: result["semanticMirror"].__setitem__(
                    "passive", False
                ),
                "semantic mirror does not match",
            ),
            (
                lambda result: result.__setitem__(
                    "stderr",
                    [
                        smoke.READY_MARKER,
                        smoke.DELIVERED_MARKER,
                        smoke.NAVIGATED_MARKER,
                        smoke.PASS_MARKER,
                        smoke.LIFECYCLE_PASS_MARKER,
                    ],
                ),
                "not ordered",
            ),
        )
        for mutate, expression in mutations:
            with self.subTest(expression=expression):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaisesRegex(M0Error, expression):
                    smoke.validate_result(result, expected_versions=VERSIONS)

    def test_parser_rejects_duplicate_keys_and_wrong_scope(self) -> None:
        result = successful_result()
        payload = json.dumps(result, separators=(",", ":")).encode()
        self.assertEqual(smoke.parse_result_payload(payload), result)
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,'
                b'"case":"browser_accessibility_snapshot_m8",'
                b'"scope":"fixed-webcontents-ax-snapshot-passive-semantic-dom"}'
            )
        )
        result["scope"] = "wrong"
        self.assertIsNone(smoke.parse_result_payload(json.dumps(result).encode()))

    def test_native_snapshot_is_one_shot_and_rejects_arbitrary_page_export(self) -> None:
        native = source(
            "chrome/browser/wasm/wasm_browser_accessibility_snapshot_smoke.cc"
        )
        native_header = source(
            "chrome/browser/wasm/wasm_browser_accessibility_snapshot_smoke.h"
        )
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        for marker in (
            "RequestAXTreeSnapshot",
            "ui::kAXModeComplete",
            "kSameOriginDirectDescendants",
            "kMaximumSnapshotNodes = 32",
            "kSnapshotTimeout = base::Seconds(5)",
            "kRootWebArea",
            "kMain",
            "kHeading",
            "kStaticText",
            "kToggleButton",
            "kExpectedHeading",
            "kExpectedStaticText",
            "kExpectedControlName",
            "kExpectedControlLeft = 64",
            "kExpectedControlTop = 128",
            "kExpectedControlWidth = 192",
            "kExpectedControlHeight = 48",
            "IsButtonPressed",
            "IsExpectedControlBounds",
            "heading_name.data()",
            "static_text_name.data()",
            "control_name.data()",
            "rounded_coordinate(control_bounds.x())",
            "chromium_wasm_report_accessibility_snapshot",
            "weak_ptr_factory_.GetWeakPtr()",
            "weak_ptr_factory_.InvalidateWeakPtrs()",
            "if (completed_)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, native)
        for forbidden in (
            "PerformAction",
            "SetAccessibilityFocus",
            "AddObserver",
            "RequestAXTreeSnapshotWithinBrowserProcess",
            "base::Unretained(this)",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, native)

        # A renderer snapshot can reply after browser shutdown has started.
        # Keep the weak factory last (so it invalidates first during member
        # destruction), invalidate pending replies before completion can begin
        # teardown, and move the one-shot callback out before running it.
        self.assertLess(
            native_header.index("CompletionCallback completion_callback_;"),
            native_header.index("base::WeakPtrFactory<"),
        )
        self.assertLess(
            native.index("weak_ptr_factory_.InvalidateWeakPtrs();"),
            native.index(
                "CompletionCallback completion_callback = "
                "std::move(completion_callback_);"
            ),
        )
        self.assertLess(
            native.index(
                "CompletionCallback completion_callback = "
                "std::move(completion_callback_);"
            ),
            native.index("std::move(completion_callback).Run(success);"),
        )

        bridge_section = bridge[
            bridge.index("chromium_wasm_report_accessibility_snapshot__deps") : bridge.index(
                "chromium_wasm_report_navigation__deps"
            )
        ]
        for marker in (
            "__proxy: 'sync'",
            "expectedHeading = 'Chromium Wasm AX snapshot'",
            "expectedText = 'Static semantic text.'",
            "expectedControlName = 'Chromium Wasm AX control'",
            "expectedRoleMask = 0xf",
            "expectedControlBounds = Object.freeze({",
            "const controlBounds = Object.freeze({",
            "maximumTextBytes = 64",
            "end > HEAPU8.length",
            "bridge.reportAccessibilitySnapshot",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge_section)
        for forbidden in ("PerformAction", "ccall(", "Page.navigate"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, bridge_section)

    def test_host_creates_passive_semantic_dom_outside_canvas(self) -> None:
        html = source(
            "tools/wasm/host/chrome_wasm_browser_accessibility_snapshot_smoke.html"
        )
        host = source(
            "tools/wasm/host/chrome_wasm_browser_accessibility_snapshot_smoke_host.js"
        )
        self.assertIn('id="accessibility-mirror"', html)
        self.assertIn('id="browser-surface"', html)
        self.assertIn("pointer-events: none", html)
        for marker in (
            "reportAccessibilitySnapshot(report)",
            "function exactJsonEqual(left, right)",
            'document.createElement("section")',
            'document.createElement("h1")',
            'document.createElement("p")',
            'document.createElement("button")',
            'control.tabIndex = -1',
            'aria-pressed", "true"',
            "controlGeometryMatchesCanvas",
            "EXPECTED_CONTROL_BOUNDS",
            "canvasContentLeft",
            "canvasContentTop",
            "controlBoundsAreWithinCanvas",
            "section.parentElement === this.#mirrorRoot",
            "!this.#canvas.contains(section)",
            "report.source !== \"fixed-webcontents-ax-snapshot\"",
            "roleMask !== EXPECTED_ROLE_MASK",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        for forbidden in ("ccall(", "addEventListener(\"click\""):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_runner_requires_isolation_mime_and_ordered_lifecycle_close(self) -> None:
        runner = source(
            "tools/wasm/run_m8_wasm_browser_accessibility_snapshot_dom_smoke.py"
        )
        for marker in (
            'HOST_ROOT = "/__m8_browser_accessibility_snapshot__"',
            '"Cross-Origin-Opener-Policy", "same-origin"',
            '"Cross-Origin-Embedder-Policy", "require-corp"',
            '"application/wasm"',
            "_require_unique_ordered_markers",
            "_validate_semantic_mirror",
            "runtime_arguments=[SWITCH]",
            "wait_for_normal_close_result",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertNotIn("ccall(", runner)

    def test_host_javascript_parses_with_node_when_available(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        host = (
            TOOLS_DIR.parents[1]
            / "tools/wasm/host/chrome_wasm_browser_accessibility_snapshot_smoke_host.js"
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
            "Node rejected accessibility snapshot host asset:\n"
            + completed.stdout
            + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()

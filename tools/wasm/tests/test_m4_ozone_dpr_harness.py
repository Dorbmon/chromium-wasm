#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the bounded M4 1x/2x DPR smoke."""

from __future__ import annotations

import copy
import io
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import run_m4_ozone_smoke


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}

TARGET_CSS_X = 285
TARGET_CSS_Y = 229
TARGET_BACKING_X = TARGET_CSS_X * 2
TARGET_BACKING_Y = TARGET_CSS_Y * 2


def frame(frame_id: int, device_scale_factor: int) -> dict[str, object]:
    return {
        "id": frame_id,
        "timestampMs": 1000 + frame_id,
        "width": 800 * device_scale_factor,
        "height": 600 * device_scale_factor,
    }


def geometry(device_scale_factor: int) -> dict[str, object]:
    return {
        "innerWidth": 800,
        "innerHeight": 600,
        "documentClientWidth": 800,
        "documentClientHeight": 600,
        "screenWidth": 800,
        "screenHeight": 600,
        "screenAvailWidth": 800,
        "screenAvailHeight": 600,
        "devicePixelRatio": device_scale_factor,
        "twoDppx": device_scale_factor == 2,
    }


def canvas(device_scale_factor: int) -> dict[str, object]:
    return {
        "clientWidth": 800,
        "clientHeight": 600,
        "width": 800 * device_scale_factor,
        "height": 600 * device_scale_factor,
        "styleWidth": "800px",
        "styleHeight": "600px",
    }


def resize_call(device_scale_factor: int) -> dict[str, object]:
    return {
        "ok": True,
        "width": 800,
        "height": 600,
        "devicePixelRatio": device_scale_factor,
        "physicalWidth": 800 * device_scale_factor,
        "physicalHeight": 600 * device_scale_factor,
    }


def page_probe(device_scale_factor: int) -> dict[str, object]:
    return {
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-pointer-v2",
        "fontReady": True,
        "ready": True,
        "activationCount": 1,
        "clickTrusted": True,
        "clickDefaultPrevented": False,
        "navigationFrameLoadCount": 2,
        "navigationFrameLastLoadTrusted": True,
        "navigationFrameLoadCountBeforeActivation": 1,
        "resultText": "ACTIVATED",
        "targetCenterX": TARGET_CSS_X,
        "targetCenterY": TARGET_CSS_Y,
        "timerTicks": 3,
        "displayGeometry": geometry(device_scale_factor),
        "pointerMoveTrace": [
            {
                "type": "pointermove",
                "trusted": True,
                "targetId": "m4-link",
                "clientX": TARGET_CSS_X,
                "clientY": TARGET_CSS_Y,
            }
        ],
    }


def pointer_input() -> dict[str, object]:
    return {
        "enabled": True,
        "receivedCount": 3,
        "trustedCount": 3,
        "queuedCount": 3,
        "lastQueued": {
            "type": "up",
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
            "sequence": 3,
            "x": TARGET_BACKING_X,
            "y": TARGET_BACKING_Y,
            "frameIdBefore": 11,
        },
    }


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    initial_call = resize_call(1)
    scaled_call = resize_call(2)
    restored_call = resize_call(1)
    initial_frame = frame(10, 1)
    scaled_frame = frame(11, 2)
    input_frame = frame(12, 2)
    restored_frame = frame(13, 1)
    pointer = pointer_input()
    final_probe = page_probe(1)
    input_probe = page_probe(2)
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_dpr_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": VERSIONS,
        "readiness": {
            "baseReady": True,
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "pageReady": True,
            "fatalErrors": [],
            "heartbeat": {
                "anchor": "data-navigation-committed",
                "elapsedMs": 1200,
            },
            "frame": copy.deepcopy(restored_frame),
            "pageProbe": final_probe,
        },
        "resizeCalls": [initial_call, scaled_call, restored_call],
        "dprProof": {
            "initial": {
                "resize": copy.deepcopy(initial_call),
                "frame": initial_frame,
                "geometry": geometry(1),
                "canvas": canvas(1),
            },
            "scaled": {
                "resize": copy.deepcopy(scaled_call),
                "frame": scaled_frame,
                "geometry": geometry(2),
                "canvas": canvas(2),
                "targetCssX": TARGET_CSS_X,
                "targetCssY": TARGET_CSS_Y,
                "targetBackingX": TARGET_BACKING_X,
                "targetBackingY": TARGET_BACKING_Y,
            },
            "input": {
                "pointer": copy.deepcopy(pointer),
                "frame": input_frame,
                "pageProbe": input_probe,
            },
            "restored": {
                "resize": copy.deepcopy(restored_call),
                "frame": restored_frame,
                "geometry": geometry(1),
                "canvas": canvas(1),
            },
        },
        "pointerInput": copy.deepcopy(pointer),
        "shutdown": {
            "ok": True,
            "accepted": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "logs": {
            "host": [
                "resize:800x600@1",
                "resize:800x600@2",
                "m4:pointer:listeners-attached",
                "resize:800x600@1",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, VERSIONS


class M4DprResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_dpr_result(
                result, expected_versions=versions
            )
        )

    def proof(self, result: dict[str, object]) -> dict[str, object]:
        proof = result["dprProof"]
        assert isinstance(proof, dict)
        return proof

    def pointer(self, result: dict[str, object]) -> dict[str, object]:
        pointer = self.proof(result)["input"]
        assert isinstance(pointer, dict)
        value = pointer["pointer"]
        assert isinstance(value, dict)
        return value

    def test_complete_one_to_two_to_one_dpr_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_scaled_backing_store_must_be_twice_the_logical_canvas(self) -> None:
        result, versions = passing_result()
        scaled = self.proof(result)["scaled"]
        assert isinstance(scaled, dict)
        backing = scaled["canvas"]
        assert isinstance(backing, dict)
        backing["width"] = 800

        with self.assertRaisesRegex(M0Error, "scaled canvas width mismatch"):
            self.assert_valid(result, versions)

    def test_host_pointer_must_remain_in_physical_backing_pixels(self) -> None:
        result, versions = passing_result()
        for value in (self.pointer(result), result["pointerInput"]):
            assert isinstance(value, dict)
            last_queued = value["lastQueued"]
            assert isinstance(last_queued, dict)
            last_queued["x"] = TARGET_CSS_X

        with self.assertRaisesRegex(M0Error, "physical backing pixels"):
            self.assert_valid(result, versions)

    def test_blink_pointer_trace_must_return_to_css_coordinates(self) -> None:
        result, versions = passing_result()
        pointer = self.proof(result)["input"]
        assert isinstance(pointer, dict)
        input_probe = pointer["pageProbe"]
        assert isinstance(input_probe, dict)
        trace = input_probe["pointerMoveTrace"]
        assert isinstance(trace, list)
        record = trace[0]
        assert isinstance(record, dict)
        record["clientX"] = TARGET_BACKING_X

        with self.assertRaisesRegex(M0Error, "Blink CSS target"):
            self.assert_valid(result, versions)

    def test_native_link_navigation_must_survive_scaled_and_restored_dpr(
        self,
    ) -> None:
        result, versions = passing_result()
        proof = self.proof(result)
        input_proof = proof["input"]
        assert isinstance(input_proof, dict)
        input_page_probe = input_proof["pageProbe"]
        assert isinstance(input_page_probe, dict)
        input_page_probe["clickDefaultPrevented"] = True

        with self.assertRaisesRegex(
            M0Error, "input page probe clickDefaultPrevented mismatch"
        ):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        final_page_probe = readiness["pageProbe"]
        assert isinstance(final_page_probe, dict)
        final_page_probe["navigationFrameLoadCountBeforeActivation"] = 2

        with self.assertRaisesRegex(
            M0Error, "final page probe navigation target did not load exactly once"
        ):
            self.assert_valid(result, versions)

    def test_scaled_frame_must_use_the_physical_backing_dimensions(self) -> None:
        result, versions = passing_result()
        scaled = self.proof(result)["scaled"]
        assert isinstance(scaled, dict)
        scaled_frame = scaled["frame"]
        assert isinstance(scaled_frame, dict)
        scaled_frame["height"] = 600

        with self.assertRaisesRegex(M0Error, "scaled proof frame height"):
            self.assert_valid(result, versions)


class M4DprUrlTest(unittest.TestCase):
    def test_dpr_url_uses_the_dedicated_case_and_pointer_fixture(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 31415)

        url = m3_content_server.m4_dpr_smoke_url(
            Server(),
            "dpr-token",
            VERSIONS,
            module_name="dpr_shell",
            timeout_seconds=12.5,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:31415")
        self.assertEqual(parsed.path, "/__m3__/")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "case": ["ozone_dpr_m4"],
                "chromium": ["chromium-revision"],
                "emscripten": ["emscripten-revision"],
                "fixture": ["/__m3__/m4-fixture.html"],
                "font": ["/__m3__/Ahem.woff2"],
                "module": ["/__m3__/artifacts/dpr_shell.js"],
                "port": ["port-revision"],
                "token": ["dpr-token"],
                "timeout_ms": ["12500"],
                "v8": ["v8-revision"],
            },
        )


class M4DprRunnerTest(unittest.TestCase):
    def test_dpr_input_selects_its_dedicated_runner_case(self) -> None:
        failure = M0Error("stop before browser startup")
        context = {"test": "dpr"}
        stderr = io.StringIO()

        with (
            mock.patch.object(
                sys, "argv", ["run_m4_ozone_smoke.py", "--input=dpr"]
            ),
            mock.patch.object(
                run_m4_ozone_smoke, "load_manifest", return_value={}
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "checked_output",
                return_value="port-revision",
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "manifest_versions",
                return_value=VERSIONS,
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "print_context",
                return_value=context,
            ) as print_context,
            mock.patch.object(
                run_m4_ozone_smoke, "find_browser", side_effect=failure
            ),
            mock.patch.object(
                run_m4_ozone_smoke,
                "write_failure_diagnostics",
                return_value=Path("diagnostics.json"),
            ) as diagnostics,
            mock.patch.object(sys, "stderr", stderr),
        ):
            self.assertEqual(run_m4_ozone_smoke.main(), 1)

        self.assertEqual(
            print_context.call_args.kwargs["case"],
            m3_content_server.M4_DPR_CASE,
        )
        self.assertIn(
            "800x600@2", print_context.call_args.kwargs["input_driver"]
        )
        self.assertIn(
            "physical backing pixels",
            print_context.call_args.kwargs["input_driver"],
        )
        self.assertEqual(
            diagnostics.call_args.kwargs["case"],
            m3_content_server.M4_DPR_CASE,
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused unit tests for the M4 trusted-wheel host harness."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import m4_cdp


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    versions = {
        "chromium": "chromium-revision",
        "v8": "v8-revision",
        "emscripten": "emscripten-revision",
        "port": "port-revision",
    }
    wheel_input = {
        "enabled": True,
        "receivedCount": 1,
        "trustedCount": 1,
        "queuedCount": 1,
        "lastQueued": {
            "type": "wheel",
            "trusted": True,
            "queued": True,
            "canvasFocused": True,
            "defaultPrevented": True,
            "deltaMode": 0,
            "domDeltaX": 0,
            "domDeltaY": 160,
            "deltaX": 0,
            "deltaY": 160,
            "sequence": 1,
            "x": 285,
            "y": 229,
            "frameIdBefore": 6,
        },
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_wheel_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": versions,
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
            "frame": {
                "id": 7,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": {
                "fontReady": True,
                "protocol": 1,
                "fixture": "chromium-wasm-m4-ozone-wheel-v1",
                "ready": True,
                "targetCenterX": 285,
                "targetCenterY": 229,
                "timerTicks": 3,
                "wheelEvents": {
                    "count": 1,
                    "trusted": True,
                    "deltaMode": 0,
                    "deltaX": 0,
                    "deltaY": 160,
                },
                "innerScrollTop": 160,
                "innerScrollLeft": 0,
                "outerScrollLeft": 0,
                "outerScrollTop": 0,
                "documentScrollTop": 0,
            },
            "wheelInput": wheel_input,
        },
        "wheelInput": wheel_input,
        "shutdown": {
            "ok": True,
            "accepted": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "logs": {
            "host": [
                "m4:wheel:listeners-attached",
                "m4:wheel:queued",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M4WheelResultValidationTest(unittest.TestCase):
    def test_complete_queued_wheel_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assertIsNone(
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )
        )

    def test_untrusted_inner_wheel_event_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        wheel_events = page_probe["wheelEvents"]
        assert isinstance(wheel_events, dict)
        wheel_events["trusted"] = False

        with self.assertRaisesRegex(M0Error, "wheel event was not trusted"):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )

    def test_untrusted_queued_wheel_is_rejected(self) -> None:
        result, versions = passing_result()
        wheel_input = result["wheelInput"]
        assert isinstance(wheel_input, dict)
        last_queued = wheel_input["lastQueued"]
        assert isinstance(last_queued, dict)
        last_queued["trusted"] = False

        with self.assertRaisesRegex(
            M0Error, "queued wheel trusted mismatch"
        ):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )

    def test_missing_default_prevention_is_rejected(self) -> None:
        result, versions = passing_result()
        wheel_input = result["wheelInput"]
        assert isinstance(wheel_input, dict)
        last_queued = wheel_input["lastQueued"]
        assert isinstance(last_queued, dict)
        last_queued["defaultPrevented"] = False

        with self.assertRaisesRegex(
            M0Error, "queued wheel defaultPrevented mismatch"
        ):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )

    def test_no_inner_scroll_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["innerScrollTop"] = 0

        with self.assertRaisesRegex(
            M0Error, "inner scroll top must be at least 1"
        ):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )

    def test_outer_scroll_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["outerScrollTop"] = 1

        with self.assertRaisesRegex(
            M0Error, "outerScrollTop changed unexpectedly"
        ):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )

    def test_queued_wheel_target_mismatch_is_rejected(self) -> None:
        result, versions = passing_result()
        wheel_input = result["wheelInput"]
        assert isinstance(wheel_input, dict)
        last_queued = wheel_input["lastQueued"]
        assert isinstance(last_queued, dict)
        last_queued["x"] = 284

        with self.assertRaisesRegex(
            M0Error, "wheel x does not match the fixture target"
        ):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )

    def test_no_later_compositor_frame_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        frame = readiness["frame"]
        assert isinstance(frame, dict)
        frame["id"] = 6

        with self.assertRaisesRegex(
            M0Error, "no compositor frame after wheel input"
        ):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )

    def test_mismatched_readiness_wheel_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["wheelInput"] = copy.deepcopy(result["wheelInput"])
        readiness_wheel = readiness["wheelInput"]
        assert isinstance(readiness_wheel, dict)
        readiness_wheel["queuedCount"] = 0

        with self.assertRaisesRegex(
            M0Error, "wheel evidence differs from readiness evidence"
        ):
            m3_content_server.validate_m4_wheel_result(
                result, expected_versions=versions
            )


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4WheelDevToolsClientTest(unittest.TestCase):
    def test_mouse_wheel_uses_one_trusted_mouse_input_message(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_mouse_wheel(12.5, 34.75, 0, 160)

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseWheel",
                        "x": 12.5,
                        "y": 34.75,
                        "deltaX": 0,
                        "deltaY": 160,
                        "pointerType": "mouse",
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()

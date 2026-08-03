#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the M4 1x resize and reflow smoke."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}


def frame(frame_id: int, width: int, height: int) -> dict[str, object]:
    return {
        "id": frame_id,
        "timestampMs": 1000 + frame_id,
        "width": width,
        "height": height,
    }


def geometry(width: int, height: int) -> dict[str, object]:
    grid_width = width - 64
    narrow = width == 640
    first_width = grid_width if narrow else (grid_width - 16) // 2
    first = {
        "left": 32,
        "top": 80,
        "width": first_width,
        "height": 120,
    }
    second = {
        "left": 32 if narrow else 32 + first_width + 16,
        "top": 216 if narrow else 80,
        "width": first_width,
        "height": 120,
    }
    return {
        "innerWidth": width,
        "innerHeight": height,
        "documentClientWidth": width,
        "documentClientHeight": height,
        "screenWidth": width,
        "screenHeight": height,
        "screenAvailWidth": width,
        "screenAvailHeight": height,
        "devicePixelRatio": 1,
        "narrowMedia": narrow,
        "layoutMode": "narrow" if narrow else "wide",
        "gridColumns": 1 if narrow else 2,
        "gridWidth": grid_width,
        "firstCard": first,
        "secondCard": second,
    }


def resize_event(sequence: int, geometry_value: dict[str, object]) -> dict[str, object]:
    return {
        "sequence": sequence,
        "type": "resize",
        "trusted": True,
        "geometry": copy.deepcopy(geometry_value),
    }


def passing_result() -> tuple[dict[str, object], dict[str, str]]:
    initial_geometry = geometry(800, 600)
    narrow_geometry = geometry(640, 480)
    restored_geometry = geometry(800, 600)
    initial_frame = frame(10, 800, 600)
    narrow_frame = frame(11, 640, 480)
    restored_frame = frame(12, 800, 600)
    initial_resize = {
        "ok": True,
        "width": 800,
        "height": 600,
        "devicePixelRatio": 1,
    }
    narrow_resize = {
        "ok": True,
        "width": 640,
        "height": 480,
        "devicePixelRatio": 1,
    }
    restored_resize = {
        "ok": True,
        "width": 800,
        "height": 600,
        "devicePixelRatio": 1,
    }
    events = [
        resize_event(1, narrow_geometry),
        resize_event(2, restored_geometry),
    ]
    page_probe: dict[str, object] = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-resize-v1",
        "ready": True,
        "resizeCaptureArmed": True,
        "timerTicks": 3,
        "currentGeometry": copy.deepcopy(restored_geometry),
        "resizeEvents": copy.deepcopy(events),
    }
    resize_proof = {
        "initial": {
            "resize": copy.deepcopy(initial_resize),
            "frame": copy.deepcopy(initial_frame),
            "geometry": copy.deepcopy(initial_geometry),
        },
        "narrow": {
            "resize": copy.deepcopy(narrow_resize),
            "frame": copy.deepcopy(narrow_frame),
            "geometry": copy.deepcopy(narrow_geometry),
            "event": copy.deepcopy(events[0]),
        },
        "restored": {
            "resize": copy.deepcopy(restored_resize),
            "frame": copy.deepcopy(restored_frame),
            "geometry": copy.deepcopy(restored_geometry),
            "event": copy.deepcopy(events[1]),
        },
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_resize_m4",
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
            "pageProbe": page_probe,
        },
        "resizeProof": resize_proof,
        "resizeEvents": events,
        "resizeCalls": [initial_resize, narrow_resize, restored_resize],
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
                "resize:640x480@1",
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


class M4ResizeResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_resize_result(
                result, expected_versions=versions
            )
        )

    def proof(self, result: dict[str, object]) -> dict[str, object]:
        proof = result["resizeProof"]
        assert isinstance(proof, dict)
        return proof

    def geometry(
        self, result: dict[str, object], stage: str
    ) -> dict[str, object]:
        snapshot = self.proof(result)[stage]
        assert isinstance(snapshot, dict)
        value = snapshot["geometry"]
        assert isinstance(value, dict)
        return value

    def frame(self, result: dict[str, object], stage: str) -> dict[str, object]:
        snapshot = self.proof(result)[stage]
        assert isinstance(snapshot, dict)
        value = snapshot["frame"]
        assert isinstance(value, dict)
        return value

    def test_complete_1x_resize_and_reflow_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_narrow_snapshot_must_update_all_viewport_and_screen_dimensions(
        self,
    ) -> None:
        for field in (
            "innerWidth",
            "documentClientWidth",
            "screenWidth",
            "screenAvailWidth",
        ):
            with self.subTest(field=field):
                result, versions = passing_result()
                self.geometry(result, "narrow")[field] = 800
                with self.assertRaises(M0Error):
                    self.assert_valid(result, versions)

    def test_resize_events_must_be_trusted_and_match_the_snapshots(self) -> None:
        result, versions = passing_result()
        events = result["resizeEvents"]
        assert isinstance(events, list)
        event = events[0]
        assert isinstance(event, dict)
        event["trusted"] = False
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        events = result["resizeEvents"]
        assert isinstance(events, list)
        event = events[1]
        assert isinstance(event, dict)
        event_geometry = event["geometry"]
        assert isinstance(event_geometry, dict)
        event_geometry["screenHeight"] = 480
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_narrow_layout_must_reflow_to_one_column(self) -> None:
        result, versions = passing_result()
        narrow = self.geometry(result, "narrow")
        narrow["gridColumns"] = 2
        narrow["layoutMode"] = "wide"
        narrow["narrowMedia"] = False
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        narrow = self.geometry(result, "narrow")
        second = narrow["secondCard"]
        assert isinstance(second, dict)
        second["top"] = 80
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_frames_must_be_exact_sizes_and_strictly_increasing(self) -> None:
        result, versions = passing_result()
        self.frame(result, "narrow")["width"] = 800
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

        result, versions = passing_result()
        self.frame(result, "restored")["id"] = 11
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_resize_calls_remain_explicitly_1x(self) -> None:
        result, versions = passing_result()
        calls = result["resizeCalls"]
        assert isinstance(calls, list)
        call = calls[0]
        assert isinstance(call, dict)
        call["devicePixelRatio"] = 2
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_final_readiness_must_match_the_restored_snapshot(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        current = page_probe["currentGeometry"]
        assert isinstance(current, dict)
        current["innerWidth"] = 640
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)

    def test_clean_shutdown_is_required(self) -> None:
        result, versions = passing_result()
        shutdown = result["shutdown"]
        assert isinstance(shutdown, dict)
        shutdown["runtimeExitCode"] = 1
        with self.assertRaises(M0Error):
            self.assert_valid(result, versions)


class M4ResizeUrlTest(unittest.TestCase):
    def test_resize_url_uses_the_dedicated_case_and_fixture(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 31415)

        url = m3_content_server.m4_resize_smoke_url(
            Server(),
            "resize-token",
            VERSIONS,
            module_name="resize_shell",
            timeout_seconds=12.5,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:31415")
        self.assertEqual(parsed.path, "/__m3__/")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "case": ["ozone_resize_m4"],
                "chromium": ["chromium-revision"],
                "emscripten": ["emscripten-revision"],
                "fixture": ["/__m3__/m4-resize-fixture.html"],
                "font": ["/__m3__/Ahem.woff2"],
                "module": ["/__m3__/artifacts/resize_shell.js"],
                "port": ["port-revision"],
                "token": ["resize-token"],
                "timeout_ms": ["12500"],
                "v8": ["v8-revision"],
            },
        )


if __name__ == "__main__":
    unittest.main()

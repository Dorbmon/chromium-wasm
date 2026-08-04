#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Executable unit coverage for the bounded M4 context-menu harness pieces."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import m3_content_server
from m4_cdp import DevToolsClient


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}


class ServerStub:
    server_address = ("127.0.0.1", 34123)


class RecordingDevToolsClient(DevToolsClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4ContextMenuHarnessTest(unittest.TestCase):
    def test_context_menu_url_binds_the_dedicated_fixture_and_case(self) -> None:
        url = m3_content_server.m4_context_menu_smoke_url(
            ServerStub(),  # type: ignore[arg-type]
            "context-token",
            VERSIONS,
            module_name="context_shell_test",
            timeout_seconds=12.5,
        )
        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:34123")
        query = parse_qs(parsed.query)
        self.assertEqual(
            query,
            {
                "case": ["ozone_context_menu_m4"],
                "chromium": [VERSIONS["chromium"]],
                "emscripten": [VERSIONS["emscripten"]],
                "fixture": ["/__m3__/m4-context-menu-fixture.html"],
                "font": ["/__m3__/Ahem.woff2"],
                "module": ["/__m3__/artifacts/context_shell_test.js"],
                "port": [VERSIONS["port"]],
                "token": ["context-token"],
                "timeout_ms": ["12500"],
                "v8": [VERSIONS["v8"]],
            },
        )
        self.assertEqual(
            m3_content_server.M4_CONTEXT_MENU_FIXTURE.name,
            "m4_ozone_context_menu_page.html",
        )

    def test_secondary_click_driver_uses_only_physical_mouse_phases(self) -> None:
        client = RecordingDevToolsClient()

        client.dispatch_secondary_click(125.5, 248.25)

        self.assertEqual(
            [method for method, _ in client.calls],
            ["Input.dispatchMouseEvent"] * 3,
        )
        parameters = [params for _, params in client.calls]
        self.assertEqual(
            parameters,
            [
                {
                    "x": 125.5,
                    "y": 248.25,
                    "pointerType": "mouse",
                    "type": "mouseMoved",
                },
                {
                    "x": 125.5,
                    "y": 248.25,
                    "pointerType": "mouse",
                    "type": "mousePressed",
                    "button": "right",
                    "clickCount": 1,
                },
                {
                    "x": 125.5,
                    "y": 248.25,
                    "pointerType": "mouse",
                    "type": "mouseReleased",
                    "button": "right",
                    "clickCount": 1,
                },
            ],
        )

    def test_copy_click_and_ctrl_v_use_physical_devtools_events(self) -> None:
        client = RecordingDevToolsClient()

        client.dispatch_primary_click(37.25, 71.5)
        client.dispatch_ctrl_v()

        self.assertEqual(
            [method for method, _ in client.calls],
            ["Input.dispatchMouseEvent"] * 3
            + ["Input.dispatchKeyEvent"] * 4,
        )
        self.assertEqual(
            [params for _, params in client.calls],
            [
                {
                    "x": 37.25,
                    "y": 71.5,
                    "pointerType": "mouse",
                    "type": "mouseMoved",
                },
                {
                    "x": 37.25,
                    "y": 71.5,
                    "pointerType": "mouse",
                    "type": "mousePressed",
                    "button": "left",
                    "clickCount": 1,
                },
                {
                    "x": 37.25,
                    "y": 71.5,
                    "pointerType": "mouse",
                    "type": "mouseReleased",
                    "button": "left",
                    "clickCount": 1,
                },
                {
                    "code": "ControlLeft",
                    "key": "Control",
                    "windowsVirtualKeyCode": 17,
                    "modifiers": 2,
                    "type": "rawKeyDown",
                },
                {
                    "code": "KeyV",
                    "key": "v",
                    "windowsVirtualKeyCode": 86,
                    "modifiers": 2,
                    "type": "rawKeyDown",
                },
                {
                    "code": "KeyV",
                    "key": "v",
                    "windowsVirtualKeyCode": 86,
                    "modifiers": 2,
                    "type": "keyUp",
                },
                {
                    "code": "ControlLeft",
                    "key": "Control",
                    "windowsVirtualKeyCode": 17,
                    "modifiers": 0,
                    "type": "keyUp",
                },
            ],
        )
        for _, params in client.calls:
            self.assertNotIn("text", params or {})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the M4 outer IME proxy preedit contract."""

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
    pointer_input = {
        "enabled": True,
        "receivedCount": 2,
        "trustedCount": 2,
        "queuedCount": 2,
        "lastQueued": {
            "type": "up",
            "trusted": True,
            "queued": True,
            "sequence": 2,
            "frameIdBefore": 6,
        },
    }
    focus_input = {
        "enabled": True,
        "hostWindowActive": True,
        "receivedCount": 2,
        "trustedCount": 2,
        "queuedCount": 1,
        "lastQueuedFocusLoss": None,
    }
    confirmed_transaction = {
        "sessionId": 1,
        "sequence": 3,
        "opcode": "set-composition",
        "text": {"utf16Length": 2, "utf8Bytes": 4, "codePointCount": 1},
        "rangeStart": 0,
        "rangeEnd": 2,
        "selection": {"start": 2, "end": 2},
    }
    ime_proxy_input = {
        "enabled": True,
        "present": True,
        "focused": True,
        "hostWindowActive": True,
        "sessionId": 1,
        "receivedCount": 4,
        "trustedCount": 4,
        "acceptedCount": 4,
        "focusCount": 1,
        "blurCount": 0,
        "compositionStartCount": 1,
        "compositionUpdateCount": 1,
        "compositionEndCount": 0,
        "beforeinputCount": 1,
        "inputCount": 1,
        "compositionActive": True,
        "pendingTransaction": False,
        "activationPending": False,
        "nativeTextInputReady": True,
        "lastConfirmedTransaction": confirmed_transaction,
        "failure": None,
        "proxyText": {
            "utf16Length": 2,
            "utf8Bytes": 4,
            "codePointCount": 1,
            "selection": {"start": 2, "end": 2},
        },
    }
    page_probe = {
        "fontReady": True,
        "protocol": 1,
        "fixture": "chromium-wasm-m4-ozone-ime-bridge-v1",
        "ready": True,
        "targetCenterX": 388,
        "targetCenterY": 215,
        "timerTicks": 3,
        "activeElementId": "editable-target",
        "activationCount": 1,
        "clickTrusted": True,
        "focusCount": 1,
        "focusTrusted": True,
        "value": "",
        "selectionStart": 0,
        "selectionEnd": 0,
        "resultText": "WAITING FOR PREEDIT BRIDGE",
        "textInputEvents": {
            "beforeinputCount": 0,
            "inputCount": 0,
            "compositionstartCount": 0,
            "compositionupdateCount": 0,
            "compositionendCount": 0,
        },
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_ime_bridge_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": False,
        "proxyFocused": True,
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
                "id": 8,
                "timestampMs": 1180,
                "width": 800,
                "height": 600,
            },
            "pageProbe": page_probe,
            "ozoneFocusState": {
                "sequence": 2,
                "keyboardTargetPresent": True,
                "active": True,
            },
            "ozoneTextInputState": {
                "sequence": 4,
                "focusedClientPresent": True,
                "editable": True,
                "canComposeInline": True,
            },
            "pointerInput": pointer_input,
            "focusInput": focus_input,
            "imeProxyInput": ime_proxy_input,
        },
        "pointerInput": pointer_input,
        "focusInput": focus_input,
        "imeProxyInput": ime_proxy_input,
        "shutdown": {
            "ok": True,
            "accepted": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "logs": {
            "host": [
                "m4:pointer:listeners-attached",
                "m4:focus:listeners-attached",
                "m4:ime-proxy:listeners-attached",
                "m4:ime-proxy:pointer-arm-awaiting-native-editable",
                "ozone:text-input:client-present:editable:inline",
                "m4:focus:canvas-blur:expected-proxy-transfer",
                "m4:ime-proxy:native-editable-focus",
                "m4:ime-proxy:compositionstart:accepted",
                "m4:ime-proxy:compositionupdate:accepted",
                "m4:ime-proxy:beforeinput:accepted-no-native-dispatch",
                "m4:ime-proxy:input:confirmed-no-native-dispatch",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M4ImeBridgeResultValidationTest(unittest.TestCase):
    def assert_valid(
        self, result: dict[str, object], versions: dict[str, str]
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_ime_bridge_result(
                result, expected_versions=versions
            )
        )

    def test_complete_proxy_preedit_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_inner_blink_edit_is_rejected_before_native_bridge_exists(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_events = page_probe["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["inputCount"] = 1

        with self.assertRaisesRegex(M0Error, "must not mutate inner Blink"):
            self.assert_valid(result, versions)

    def test_missing_native_editable_acknowledgement_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        ozone_text_input = readiness["ozoneTextInputState"]
        assert isinstance(ozone_text_input, dict)
        ozone_text_input["editable"] = False

        with self.assertRaisesRegex(
            M0Error, "native text-input acknowledgement editable"
        ):
            self.assert_valid(result, versions)

    def test_native_keyboard_target_loss_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        ozone_focus = readiness["ozoneFocusState"]
        assert isinstance(ozone_focus, dict)
        ozone_focus["keyboardTargetPresent"] = False

        with self.assertRaisesRegex(M0Error, "lost Ozone's keyboard target"):
            self.assert_valid(result, versions)

    def test_bad_utf16_range_is_rejected(self) -> None:
        result, versions = passing_result()
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        transaction = proxy["lastConfirmedTransaction"]
        assert isinstance(transaction, dict)
        transaction["rangeEnd"] = 1

        with self.assertRaisesRegex(M0Error, "transaction rangeEnd mismatch"):
            self.assert_valid(result, versions)

    def test_latched_proxy_failure_is_rejected(self) -> None:
        result, versions = passing_result()
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["failure"] = "UNTRUSTED_DOM_EVENT"

        with self.assertRaisesRegex(M0Error, "proxy failure mismatch"):
            self.assert_valid(result, versions)

    def test_mismatched_readiness_proxy_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["imeProxyInput"] = copy.deepcopy(result["imeProxyInput"])
        readiness_proxy = readiness["imeProxyInput"]
        assert isinstance(readiness_proxy, dict)
        readiness_proxy["acceptedCount"] = 3

        with self.assertRaisesRegex(M0Error, "proxy evidence differs"):
            self.assert_valid(result, versions)


class RecordingDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((method, params))
        return {}


class M4ImeBridgeDevToolsClientTest(unittest.TestCase):
    def test_preedit_uses_ime_set_composition_without_insert_text(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_ime_preedit()

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.imeSetComposition",
                    {
                        "text": "🙂",
                        "selectionStart": 2,
                        "selectionEnd": 2,
                        "replacementStart": 0,
                        "replacementEnd": 0,
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()

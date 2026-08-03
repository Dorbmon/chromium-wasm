#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused validation tests for the M4 native Ozone IME bridge contract."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import m4_cdp


EXPECTED_TEXT_SUMMARY = {
    "utf16Length": 2,
    "utf8Bytes": 4,
    "codePointCount": 1,
}
EMPTY_TEXT_SUMMARY = {
    "utf16Length": 0,
    "utf8Bytes": 0,
    "codePointCount": 0,
}


def text_trace_record(
    event_type: str,
    *,
    data: dict[str, int] | None,
    data_matches_expected: bool,
    value: dict[str, int],
    selection_start: int,
    selection_end: int,
    trusted: bool,
) -> dict[str, object]:
    is_text_input = event_type in ("beforeinput", "input")
    return {
        "type": event_type,
        "data": copy.deepcopy(data),
        "dataMatchesExpected": data_matches_expected,
        "trusted": trusted,
        "inputType": "insertCompositionText" if is_text_input else None,
        "isComposing": is_text_input,
        "value": copy.deepcopy(value),
        "selectionStart": selection_start,
        "selectionEnd": selection_end,
    }


def passing_result(
    terminal_mode: str = "commit",
) -> tuple[dict[str, object], dict[str, str]]:
    if terminal_mode not in ("commit", "cancel"):
        raise ValueError(f"unsupported terminal mode: {terminal_mode!r}")
    is_cancellation = terminal_mode == "cancel"
    terminal_text_summary = (
        EMPTY_TEXT_SUMMARY if is_cancellation else EXPECTED_TEXT_SUMMARY
    )
    terminal_selection = 0 if is_cancellation else 2
    terminal_event_count = 2
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
        "sequence": 3 if is_cancellation else 6,
        "opcode": "set-composition",
        "text": copy.deepcopy(EXPECTED_TEXT_SUMMARY),
        "rangeStart": 0,
        "rangeEnd": 2,
        "selection": {"start": 2, "end": 2},
    }
    last_native_delivery = {
        "action": 3 if is_cancellation else 2,
        "actionName": (
            "clear-composition" if is_cancellation else "confirm-composition"
        ),
        "sessionId": 1,
        "sequence": 7 if is_cancellation else 8,
        "queued": True,
        "deliveryAccepted": True,
        "text": None,
        "selection": {"start": 0, "end": 0},
    }
    ime_proxy_input = {
        "enabled": True,
        "present": True,
        "focused": True,
        "hostWindowActive": True,
        "sessionId": 1,
        "receivedCount": 8,
        "trustedCount": 7,
        "acceptedCount": 7 if is_cancellation else 8,
        "derivedTerminalCount": 0 if is_cancellation else 1,
        "observedClearTerminalCount": 1 if is_cancellation else 0,
        "focusCount": 1,
        "blurCount": 0,
        "compositionStartCount": 1,
        "compositionUpdateCount": 2,
        "compositionEndCount": 1,
        "beforeinputCount": 2,
        "inputCount": 2,
        "compositionActive": False,
        "terminalCancellationPending": False,
        "pendingTransaction": False,
        "activationPending": False,
        "nativeTextInputReady": True,
        "nativeQueuedCount": 2 if is_cancellation else 3,
        "nativeSetDeliveryCount": 1 if is_cancellation else 2,
        "nativeConfirmDeliveryCount": 0 if is_cancellation else 1,
        "nativeClearDeliveryCount": 1 if is_cancellation else 0,
        "nativePendingDelivery": False,
        "nativeCompositionActive": False,
        "nativeTerminalAction": None,
        "lastNativeDelivery": last_native_delivery,
        "lastConfirmedTransaction": confirmed_transaction,
        "failure": None,
        "proxyText": {
            **terminal_text_summary,
            "selection": {
                "start": terminal_selection,
                "end": terminal_selection,
            },
        },
    }
    text_trace = [
        text_trace_record(
            "compositionstart",
            data=EMPTY_TEXT_SUMMARY,
            data_matches_expected=False,
            value=EMPTY_TEXT_SUMMARY,
            selection_start=0,
            selection_end=0,
            trusted=True,
        ),
        text_trace_record(
            "compositionupdate",
            data=EXPECTED_TEXT_SUMMARY,
            data_matches_expected=True,
            value=EMPTY_TEXT_SUMMARY,
            selection_start=0,
            selection_end=0,
            trusted=True,
        ),
        text_trace_record(
            "beforeinput",
            data=EXPECTED_TEXT_SUMMARY,
            data_matches_expected=True,
            value=EMPTY_TEXT_SUMMARY,
            selection_start=0,
            selection_end=0,
            trusted=True,
        ),
        text_trace_record(
            "input",
            data=EXPECTED_TEXT_SUMMARY,
            data_matches_expected=True,
            value=EXPECTED_TEXT_SUMMARY,
            selection_start=2,
            selection_end=2,
            trusted=True,
        ),
    ]
    if is_cancellation:
        text_trace.extend(
            (
                text_trace_record(
                    "compositionupdate",
                    data=EMPTY_TEXT_SUMMARY,
                    data_matches_expected=False,
                    value=EXPECTED_TEXT_SUMMARY,
                    selection_start=0,
                    selection_end=2,
                    trusted=True,
                ),
                text_trace_record(
                    "beforeinput",
                    data=EMPTY_TEXT_SUMMARY,
                    data_matches_expected=False,
                    value=EXPECTED_TEXT_SUMMARY,
                    selection_start=0,
                    selection_end=2,
                    trusted=True,
                ),
                text_trace_record(
                    "input",
                    data=None,
                    data_matches_expected=False,
                    value=EMPTY_TEXT_SUMMARY,
                    selection_start=0,
                    selection_end=0,
                    trusted=True,
                ),
                text_trace_record(
                    "compositionend",
                    data=EMPTY_TEXT_SUMMARY,
                    data_matches_expected=False,
                    value=EMPTY_TEXT_SUMMARY,
                    selection_start=0,
                    selection_end=0,
                    trusted=False,
                ),
            )
        )
    else:
        text_trace.extend(
            (
                text_trace_record(
                    "compositionupdate",
                    data=EXPECTED_TEXT_SUMMARY,
                    data_matches_expected=True,
                    value=EXPECTED_TEXT_SUMMARY,
                    selection_start=0,
                    selection_end=2,
                    trusted=True,
                ),
                text_trace_record(
                    "beforeinput",
                    data=EXPECTED_TEXT_SUMMARY,
                    data_matches_expected=True,
                    value=EXPECTED_TEXT_SUMMARY,
                    selection_start=0,
                    selection_end=2,
                    trusted=True,
                ),
                text_trace_record(
                    "input",
                    data=EXPECTED_TEXT_SUMMARY,
                    data_matches_expected=True,
                    value=EXPECTED_TEXT_SUMMARY,
                    selection_start=2,
                    selection_end=2,
                    trusted=True,
                ),
                text_trace_record(
                    "compositionend",
                    data=EXPECTED_TEXT_SUMMARY,
                    data_matches_expected=True,
                    value=EXPECTED_TEXT_SUMMARY,
                    selection_start=2,
                    selection_end=2,
                    trusted=False,
                ),
            )
        )
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
        "value": copy.deepcopy(terminal_text_summary),
        "valueMatchesExpected": not is_cancellation,
        "selectionStart": terminal_selection,
        "selectionEnd": terminal_selection,
        "resultText": (
            "INNER EDITOR COMPOSITION ENDED"
            if is_cancellation
            else "INNER EDITOR COMMITTED"
        ),
        "textInputEvents": {
            "beforeinputCount": terminal_event_count,
            "inputCount": terminal_event_count,
            "compositionstartCount": 1,
            "compositionupdateCount": terminal_event_count,
            "compositionendCount": 1,
        },
        "textInputTrace": text_trace,
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "ozone_ime_bridge_m4",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": False,
        "proxyFocused": True,
        "terminalMode": terminal_mode,
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
                "m4:ime-proxy:beforeinput:native-set-queued",
                "ozone:text-input-delivery:set-composition:accepted",
                "m4:ime-proxy:input:confirmed-native-set",
                *(
                    [
                        "m4:ime-proxy:compositionupdate:cancellation-pending",
                        "m4:ime-proxy:beforeinput:cancellation-pending",
                        "m4:ime-proxy:input:native-clear-queued",
                        "ozone:text-input-delivery:clear-composition:accepted",
                        "m4:ime-proxy:compositionend:clear-observed",
                    ]
                    if is_cancellation
                    else [
                        "m4:ime-proxy:compositionend:native-confirm-queued",
                        "ozone:text-input-delivery:confirm-composition:accepted",
                    ]
                ),
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
        self,
        result: dict[str, object],
        versions: dict[str, str],
        *,
        terminal_mode: str = "commit",
    ) -> None:
        self.assertIsNone(
            m3_content_server.validate_m4_ime_bridge_result(
                result,
                expected_versions=versions,
                terminal_mode=terminal_mode,
            )
        )

    def test_complete_native_composition_commit_contract_is_accepted(self) -> None:
        result, versions = passing_result()

        self.assert_valid(result, versions)

    def test_complete_native_composition_cancel_contract_is_accepted(self) -> None:
        result, versions = passing_result("cancel")

        self.assert_valid(result, versions, terminal_mode="cancel")

    def test_terminal_mode_must_match_the_requested_contract(self) -> None:
        result, versions = passing_result("cancel")

        with self.assertRaisesRegex(M0Error, "terminalMode"):
            self.assert_valid(result, versions)

    def test_missing_inner_blink_input_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_events = page_probe["textInputEvents"]
        assert isinstance(text_events, dict)
        text_events["inputCount"] = 0

        with self.assertRaisesRegex(M0Error, "inner inputCount"):
            self.assert_valid(result, versions)

    def test_wrong_inner_blink_value_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["valueMatchesExpected"] = False

        with self.assertRaisesRegex(M0Error, "valueMatchesExpected"):
            self.assert_valid(result, versions)

    def test_bad_inner_composition_trace_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        composition_end = text_trace[-1]
        assert isinstance(composition_end, dict)
        composition_end["dataMatchesExpected"] = False

        with self.assertRaisesRegex(M0Error, "text trace record 7"):
            self.assert_valid(result, versions)

    def test_inner_trace_binds_trusted_sources_to_untrusted_terminal(self) -> None:
        for terminal_mode in ("commit", "cancel"):
            for index, trusted in ((0, False), (7, True)):
                with self.subTest(
                    terminal_mode=terminal_mode, index=index, trusted=trusted
                ):
                    result, versions = passing_result(terminal_mode)
                    readiness = result["readiness"]
                    assert isinstance(readiness, dict)
                    page_probe = readiness["pageProbe"]
                    assert isinstance(page_probe, dict)
                    text_trace = page_probe["textInputTrace"]
                    assert isinstance(text_trace, list)
                    record = text_trace[index]
                    assert isinstance(record, dict)
                    record["trusted"] = trusted

                    with self.assertRaisesRegex(
                        M0Error, f"text trace record {index}"
                    ):
                        self.assert_valid(
                            result, versions, terminal_mode=terminal_mode
                        )

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

    def test_unaccepted_native_confirmation_is_rejected(self) -> None:
        result, versions = passing_result()
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["nativeConfirmDeliveryCount"] = 0
        delivery = proxy["lastNativeDelivery"]
        assert isinstance(delivery, dict)
        delivery["deliveryAccepted"] = False

        with self.assertRaisesRegex(M0Error, "nativeConfirmDeliveryCount"):
            self.assert_valid(result, versions)

    def test_commit_terminal_delivery_binds_to_composition_end_sequence(
        self,
    ) -> None:
        result, versions = passing_result()
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        delivery = proxy["lastNativeDelivery"]
        assert isinstance(delivery, dict)
        delivery["sequence"] = 7

        with self.assertRaisesRegex(M0Error, "last native delivery sequence"):
            self.assert_valid(result, versions)

    def test_pending_native_delivery_is_rejected(self) -> None:
        result, versions = passing_result()
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["nativePendingDelivery"] = True

        with self.assertRaisesRegex(M0Error, "nativePendingDelivery"):
            self.assert_valid(result, versions)

    def test_derived_terminal_count_must_be_exactly_one(self) -> None:
        result, versions = passing_result()
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["derivedTerminalCount"] = 2

        with self.assertRaisesRegex(M0Error, "derivedTerminalCount"):
            self.assert_valid(result, versions)

    def test_cancel_requires_observed_clear_terminal_record(self) -> None:
        result, versions = passing_result("cancel")
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["observedClearTerminalCount"] = 0

        with self.assertRaisesRegex(M0Error, "observedClearTerminalCount"):
            self.assert_valid(result, versions, terminal_mode="cancel")

    def test_cancel_requires_clear_native_delivery(self) -> None:
        result, versions = passing_result("cancel")
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["nativeClearDeliveryCount"] = 0

        with self.assertRaisesRegex(M0Error, "nativeClearDeliveryCount"):
            self.assert_valid(result, versions, terminal_mode="cancel")

    def test_cancel_terminal_delivery_binds_to_empty_input_sequence(
        self,
    ) -> None:
        result, versions = passing_result("cancel")
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        delivery = proxy["lastNativeDelivery"]
        assert isinstance(delivery, dict)
        delivery["sequence"] = 4

        with self.assertRaisesRegex(M0Error, "last native delivery sequence"):
            self.assert_valid(result, versions, terminal_mode="cancel")

    def test_cancel_disallows_a_derived_terminal_record(self) -> None:
        result, versions = passing_result("cancel")
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["derivedTerminalCount"] = 1

        with self.assertRaisesRegex(M0Error, "derivedTerminalCount"):
            self.assert_valid(result, versions, terminal_mode="cancel")

    def test_cancel_requires_empty_inner_editor_value(self) -> None:
        result, versions = passing_result("cancel")
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["value"] = copy.deepcopy(EXPECTED_TEXT_SUMMARY)

        with self.assertRaisesRegex(M0Error, "inner value summary"):
            self.assert_valid(result, versions, terminal_mode="cancel")

    def test_cancel_requires_the_empty_update_before_clear(self) -> None:
        result, versions = passing_result("cancel")
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        cancellation_update = text_trace[4]
        assert isinstance(cancellation_update, dict)
        cancellation_update["data"] = copy.deepcopy(EXPECTED_TEXT_SUMMARY)

        with self.assertRaisesRegex(M0Error, "text trace record 4"):
            self.assert_valid(result, versions, terminal_mode="cancel")

    def test_cancel_requires_null_clear_input_data(self) -> None:
        result, versions = passing_result("cancel")
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        text_trace = page_probe["textInputTrace"]
        assert isinstance(text_trace, list)
        cancellation_input = text_trace[6]
        assert isinstance(cancellation_input, dict)
        cancellation_input["data"] = copy.deepcopy(EMPTY_TEXT_SUMMARY)

        with self.assertRaisesRegex(M0Error, "text trace record 6"):
            self.assert_valid(result, versions, terminal_mode="cancel")

    def test_latched_proxy_failure_is_rejected(self) -> None:
        result, versions = passing_result()
        proxy = result["imeProxyInput"]
        assert isinstance(proxy, dict)
        proxy["failure"] = "NATIVE_TEXT_INPUT_DELIVERY_REJECTED"

        with self.assertRaisesRegex(M0Error, "proxy failure mismatch"):
            self.assert_valid(result, versions)

    def test_mismatched_readiness_proxy_evidence_is_rejected(self) -> None:
        result, versions = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["imeProxyInput"] = copy.deepcopy(result["imeProxyInput"])
        readiness_proxy = readiness["imeProxyInput"]
        assert isinstance(readiness_proxy, dict)
        readiness_proxy["acceptedCount"] = 7

        with self.assertRaisesRegex(M0Error, "proxy evidence differs"):
            self.assert_valid(result, versions)


class M4ImeBridgeSmokeUrlTest(unittest.TestCase):
    def test_terminal_mode_is_forwarded_to_the_host_query(self) -> None:
        server = SimpleNamespace(server_address=("127.0.0.1", 9222))
        versions = {
            "chromium": "chromium-revision",
            "v8": "v8-revision",
            "emscripten": "emscripten-revision",
            "port": "port-revision",
        }

        url = m3_content_server.m4_ime_bridge_smoke_url(
            server,  # type: ignore[arg-type]
            "token",
            versions,
            terminal_mode="cancel",
        )

        self.assertEqual(
            parse_qs(urlsplit(url).query).get("ime_terminal"), ["cancel"]
        )

    def test_invalid_terminal_mode_is_rejected(self) -> None:
        server = SimpleNamespace(server_address=("127.0.0.1", 9222))
        versions = {
            "chromium": "chromium-revision",
            "v8": "v8-revision",
            "emscripten": "emscripten-revision",
            "port": "port-revision",
        }

        with self.assertRaisesRegex(M0Error, "terminal mode"):
            m3_content_server.m4_ime_bridge_smoke_url(
                server,  # type: ignore[arg-type]
                "token",
                versions,
                terminal_mode="invalid",
            )


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

    def test_commit_uses_insert_text_after_the_outer_preedit(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_ime_commit()

        self.assertEqual(
            recording.calls,
            [("Input.insertText", {"text": "🙂"})],
        )

    def test_cancel_uses_an_empty_ime_set_composition(self) -> None:
        recording = RecordingDevToolsClient()
        client = object.__new__(m4_cdp.DevToolsClient)
        client.call = recording.call  # type: ignore[method-assign]

        client.dispatch_ime_cancel()

        self.assertEqual(
            recording.calls,
            [
                (
                    "Input.imeSetComposition",
                    {
                        "text": "",
                        "selectionStart": 0,
                        "selectionEnd": 0,
                        "replacementStart": 0,
                        "replacementEnd": 0,
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()

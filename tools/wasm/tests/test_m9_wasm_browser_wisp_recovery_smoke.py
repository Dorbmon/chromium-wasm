#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the same-instance M9 Chrome WISP recovery lane."""

from __future__ import annotations

import base64
from collections import deque
import contextlib
import copy
import io
import math
from pathlib import Path
import queue
import socket
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m4_cdp
import run_m9_wasm_browser_wisp_recovery_smoke as smoke


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def make_png(width: int = 1, height: int = 1) -> bytes:
    row = b"\x00" + bytes((24, 32, 48, 255)) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(row * height, level=9))
        + png_chunk(b"IEND", b"")
    )


SCREENSHOT_BASE64 = base64.b64encode(make_png()).decode("ascii")


def input_records() -> dict[str, object]:
    return {
        "readyObserved": True,
        "ctrlLComplete": True,
        "proxyFocusedAfterCtrlL": True,
        "nativeTextAdmissionCount": 1,
        "nativeTextDeliveryCount": 1,
        "nativeTextDeliverySequences": [1],
        "textDeliveryAccepted": True,
        "enterComplete": True,
        "attached": True,
        "deliveryAccepted": True,
        "deliveryRejected": False,
        "pendingDeliveryCount": 0,
        "pendingTextUtf8Bytes": 0,
        "tombstonedDeliveryCount": 0,
        "proxyTextEmpty": True,
        "rejectedRecords": [],
        "cleanupRecords": [],
        "ctrlLRecords": [
            {
                "type": event_type,
                "code": code,
                "trusted": True,
                "cancelable": True,
                "canvasFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            }
            for event_type, code in (
                ("keydown", "ControlLeft"),
                ("keydown", "KeyL"),
                ("keyup", "KeyL"),
                ("keyup", "ControlLeft"),
            )
        ],
        "beforeInputRecords": [
            {
                "inputType": "insertText",
                "dataOmitted": True,
                "dataUtf16Units": len(smoke.ADDRESS_TEXT),
                "trusted": True,
                "cancelable": True,
                "isComposing": False,
                "proxyFocused": True,
                "queued": True,
                "defaultPrevented": True,
                "dataUtf8Bytes": len(smoke.ADDRESS_TEXT.encode("utf-8")),
                "sequence": 1,
                "nativeDispatched": True,
                "nativeAccepted": True,
            }
        ],
        "browserTextDeliveryReports": [
            {"action": 4, "sessionId": 0, "sequence": 1, "accepted": True}
        ],
        "enterRecords": [
            {
                "type": event_type,
                "code": "Enter",
                "key": "Enter",
                "trusted": True,
                "cancelable": True,
                "proxyFocused": True,
                "accepted": True,
                "defaultPrevented": True,
            }
            for event_type in ("keydown", "keyup")
        ],
    }


def passing_result() -> dict[str, object]:
    markers = [
        smoke.READY_MARKER,
        smoke.NAVIGATED_MARKER,
        smoke.NATIVE_DISCONNECT_MARKER,
        smoke.H2_RECOVERED_MARKER,
        smoke.SAME_INSTANCE_MARKER,
        smoke.PASS_MARKER,
    ]
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m9GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "m9WispRecovery": {
            "wispConfigured": True,
            "runtimeArgumentsConfigured": True,
            "configurationPrecededFactory": True,
            "readyMarkerObserved": True,
            "navigatedMarkerObserved": True,
            "nativeDisconnectMarkerObserved": True,
            "h2RecoveredMarkerObserved": True,
            "sameInstanceMarkerObserved": True,
            "passMarkerObserved": True,
            "frameIdAtH2Recovered": 1,
            "h2RecoveredObservationSequence": 10,
            "sameInstanceObservationSequence": 12,
            "recoveryFrameObserved": True,
            "recoveryFrameId": 2,
        },
        "frameReports": [
            {"id": 1, "width": 1, "height": 1, "timestampMs": 1},
            {"id": 2, "width": 1, "height": 1, "timestampMs": 2},
        ],
        "readiness": {
            "shellReady": True,
            "surfaceReady": True,
            "firstVisuallyNonEmptyPaint": True,
        },
        "readinessReports": [
            {
                "shellReady": True,
                "surfaceReady": True,
                "firstVisuallyNonEmptyPaint": True,
            }
        ],
        "ozoneFocusReports": [{"keyboardTargetPresent": True, "active": True}],
        "ozoneTextInputStates": [
            {
                "focusedClientPresent": True,
                "editable": True,
                "canComposeInline": True,
            }
        ],
        "hostInput": input_records(),
        "recoveryScreenshot": {
            "id": 2,
            "width": 1,
            "height": 1,
            "observationSequence": 11,
            "mimeType": "image/png",
            "dataBase64": SCREENSHOT_BASE64,
        },
        "canvasBackingStore": {"width": 1, "height": 1},
        "stdout": markers,
        "stderr": [],
        "failedChecks": [],
        "error": None,
    }


def event(name: str, **fields: object) -> dict[str, object]:
    return {"event": name, **fields}


def passing_relay_status() -> dict[str, object]:
    transcript = [
        event(
            "fixture-ready",
            cspConnectSrcTargetPort=10001,
            h1Port=10002,
            h2Port=10003,
            plaintextHttpControlPort=10004,
            tlsFailurePort=10005,
        ),
        event("wisp-connected"),
        event("wisp-ready"),
        event("connect-requested", streamId=1, destination="a.test:443"),
        event("connect-open", streamId=1, destination="a.test:443"),
        event("h2-m9-wisp-recovery"),
        event("h2-m9-wisp-recovery-script"),
        event("connect-requested", streamId=2, destination="a.test:443"),
        event("connect-open", streamId=2, destination="a.test:443"),
        event("h2-reconnect-stream-start"),
        event("h2-reconnect-stream-first-chunk"),
        event("h2-reconnect-first-chunk-ack"),
        event("h2-reconnect-disconnect-requested"),
        event("h2-reconnect-carrier-close"),
        event("wisp-disconnected"),
        event("h2-reconnect-wisp-disconnected"),
        event("wisp-transport-closed"),
        event("wisp-connected"),
        event("wisp-ready"),
        event("connect-requested", streamId=3, destination="a.test:443"),
        event("connect-open", streamId=3, destination="a.test:443"),
        event("h2-reconnect-recovery"),
        event("connect-requested", streamId=4, destination="a.test:443"),
        event("connect-open", streamId=4, destination="a.test:443"),
        # Deliberately later than recovery: this is the permitted old H2
        # teardown race the validator must not mistake for a replay.
        event("h2-reconnect-stream-disconnected"),
        event("h2-m9-wisp-recovery-complete"),
        event("stream-client-close", streamId=3),
        event("stream-client-close", streamId=4),
    ]
    for sequence, entry in enumerate(transcript, start=1):
        entry["sequence"] = sequence
    status: dict[str, object] = dict(
        smoke.M9_RELAY_PRE_CLEANUP_NUMERIC_EXPECTATIONS
    )
    status.update(smoke.M9_RELAY_PRE_CLEANUP_PHASE_EXPECTATIONS)
    status.update(smoke.M9_RELAY_PRE_CLEANUP_BOOLEAN_EXPECTATIONS)
    status.update({
        "fixture": smoke.RELAY_FIXTURE,
        "protocol": 1,
        "ready": True,
        "m9WispRecoveryRequests": 1,
        "m9WispRecoveryCompleteRequests": 1,
        "m9WispRecoveryScriptRequests": 1,
        "m6UiRequests": 0,
        "reconnectStreamRequests": 1,
        "reconnectFirstChunks": 1,
        "reconnectFirstChunkAcks": 1,
        "reconnectDisconnectRequests": 1,
        "reconnectRecoveryRequests": 1,
        "reconnectSessionMismatches": 0,
        "reconnectUnexpectedCloses": 0,
        "reconnectUnexpectedRetries": 0,
        "rejectedDestinations": 0,
        "relayErrors": 0,
        "wispSessions": 2,
        "activeWispSessions": 1,
        "activeWispTransports": 1,
        "wispTransportClosures": 1,
        "wispTransportCloseTimeouts": 0,
        "localGateway443StreamsOpened": 4,
        "localGateway443Requests": 0,
        "reconnectPhase": "recovered",
        "h2Requests": {"protocol": "h2", "count": 6},
        "requestedDestinations": [
            {"hostname": "a.test", "port": 443},
            {"hostname": "a.test", "port": 443},
            {"hostname": "a.test", "port": 443},
            {"hostname": "a.test", "port": 443},
        ],
        "transcript": transcript,
    })
    return status


class M9ResultContractTest(unittest.TestCase):
    def test_passing_result_binds_exact_native_and_host_evidence(self) -> None:
        smoke.validate_result(passing_result(), expected_versions=VERSIONS)

    def test_duplicate_native_marker_is_rejected(self) -> None:
        result = passing_result()
        result["stdout"] = [
            *result["stdout"],  # type: ignore[list-item]
            smoke.PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "native marker"):
            smoke.validate_result(result, expected_versions=VERSIONS)

    def test_native_marker_in_stderr_is_rejected(self) -> None:
        result = passing_result()
        result["stderr"] = [smoke.PASS_MARKER]
        with self.assertRaisesRegex(M0Error, "native marker"):
            smoke.validate_result(result, expected_versions=VERSIONS)

    def test_action_four_delivery_must_be_exact(self) -> None:
        result = passing_result()
        result["hostInput"]["browserTextDeliveryReports"][0]["action"] = 3  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "action-4"):
            smoke.validate_result(result, expected_versions=VERSIONS)

    def test_recovery_screenshot_must_precede_same_instance_marker(self) -> None:
        result = passing_result()
        result["recoveryScreenshot"]["observationSequence"] = 12  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "first presentation"):
            smoke.validate_result(result, expected_versions=VERSIONS)

    def test_retained_textarea_value_is_rejected(self) -> None:
        result = passing_result()
        result["hostInput"]["textareaValue"] = smoke.ADDRESS_TEXT  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "textarea"):
            smoke.validate_result(result, expected_versions=VERSIONS)

    def test_bool_alias_for_native_text_count_is_rejected(self) -> None:
        result = passing_result()
        result["hostInput"]["nativeTextAdmissionCount"] = True  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "nativeTextAdmissionCount"):
            smoke.validate_result(result, expected_versions=VERSIONS)

    def test_integer_alias_for_host_boolean_is_rejected(self) -> None:
        result = passing_result()
        result["hostInput"]["readyObserved"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "readyObserved"):
            smoke.validate_result(result, expected_versions=VERSIONS)


class M9RelayContractTest(unittest.TestCase):
    def test_valid_async_old_stream_teardown_is_accepted(self) -> None:
        smoke.validate_m9_relay_status(passing_relay_status())

    def test_old_transport_close_cannot_predate_old_wisp_disconnect(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        old_transport_close = next(
            entry for entry in transcript if entry["event"] == "wisp-transport-closed"
        )
        transcript.remove(old_transport_close)
        transcript.insert(1, old_transport_close)
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(M0Error, "transport closed before relay disconnect"):
            smoke.validate_m9_relay_status(status)

    def test_old_transport_close_can_follow_fresh_recovery(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        old_transport_close = next(
            entry for entry in transcript if entry["event"] == "wisp-transport-closed"
        )
        transcript.remove(old_transport_close)
        completion = next(
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "h2-m9-wisp-recovery-complete"
        )
        transcript.insert(completion + 1, old_transport_close)
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        smoke.validate_m9_relay_status(status)

    def test_pre_cleanup_wait_accepts_only_old_transport_close_gap(self) -> None:
        pending = passing_relay_status()
        pending["activeWispTransports"] = 2
        pending["wispTransportClosures"] = 0
        transcript = pending["transcript"]
        assert isinstance(transcript, list)
        transcript[:] = [
            entry for entry in transcript if entry["event"] != "wisp-transport-closed"
        ]
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        self.assertFalse(smoke._validate_m9_relay_pre_cleanup_progress(pending))

        with mock.patch.object(
            smoke,
            "fetch_relay_status",
            side_effect=[pending, passing_relay_status()],
        ), mock.patch.object(smoke.time, "sleep"):
            observed = smoke.wait_for_m9_relay_pre_cleanup_status(
                "http://127.0.0.1:40123/status", timeout_seconds=1.0
            )
        self.assertEqual(observed, passing_relay_status())

    def test_stream_ids_can_repeat_across_wisp_carriers(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        requested = [
            entry for entry in transcript if entry["event"] == "connect-requested"
        ]
        opened = [entry for entry in transcript if entry["event"] == "connect-open"]
        for entry, stream_id in zip(requested, (1, 2, 1, 2)):
            entry["streamId"] = stream_id
        for entry, stream_id in zip(opened, (1, 2, 1, 2)):
            entry["streamId"] = stream_id
        client_closes = [
            entry for entry in transcript if entry["event"] == "stream-client-close"
        ]
        client_closes[0]["streamId"] = 1
        client_closes[1]["streamId"] = 2
        smoke.validate_m9_relay_status(status)

    def test_client_closes_must_match_post_recovery_stream_ids(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        client_close = next(
            entry for entry in transcript if entry["event"] == "stream-client-close"
        )
        client_close["streamId"] = 9
        with self.assertRaisesRegex(M0Error, "client closes"):
            smoke.validate_m9_relay_status(status)

    def test_unexpected_cleanup_record_is_rejected(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        transcript.append(event("unexpected-cleanup-record"))
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(M0Error, "unexpected event"):
            smoke.validate_m9_relay_status(status)

    def test_status_field_injection_is_rejected(self) -> None:
        status = passing_relay_status()
        status["unexpectedCleanupRecord"] = {"accepted": True}
        with self.assertRaisesRegex(M0Error, "field set"):
            smoke.validate_m9_relay_status(status)

    def test_transcript_field_injection_is_rejected(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        transcript[1]["unexpected"] = True
        with self.assertRaisesRegex(M0Error, "field shape"):
            smoke.validate_m9_relay_status(status)

    def test_second_ready_must_follow_wisp_disconnect(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        first_ready = next(
            index for index, entry in enumerate(transcript) if entry["event"] == "wisp-ready"
        )
        second_ready = next(
            index
            for index, entry in enumerate(transcript[first_ready + 1 :], first_ready + 1)
            if entry["event"] == "wisp-ready"
        )
        disconnect = next(
            index for index, entry in enumerate(transcript) if entry["event"] == "wisp-disconnected"
        )
        transcript[second_ready], transcript[disconnect] = (
            transcript[disconnect],
            transcript[second_ready],
        )
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(
            M0Error,
            "carrier lifecycle|transition ordering|transport closed before relay disconnect",
        ):
            smoke.validate_m9_relay_status(status)

    def test_exact_m9_document_count_is_required(self) -> None:
        status = passing_relay_status()
        status["m9WispRecoveryRequests"] = 2
        with self.assertRaisesRegex(M0Error, "m9WispRecoveryRequests"):
            smoke.validate_m9_relay_status(status)

    def test_exact_m9_external_script_count_is_required(self) -> None:
        status = passing_relay_status()
        status["m9WispRecoveryScriptRequests"] = 2
        with self.assertRaisesRegex(M0Error, "m9WispRecoveryScriptRequests"):
            smoke.validate_m9_relay_status(status)

    def test_external_script_must_precede_reconnect_stream(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        script = next(
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "h2-m9-wisp-recovery-script"
        )
        reconnect = next(
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "h2-reconnect-stream-start"
        )
        transcript[script], transcript[reconnect] = (
            transcript[reconnect],
            transcript[script],
        )
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(M0Error, "setup ordering"):
            smoke.validate_m9_relay_status(status)

    def test_second_connect_request_cannot_predate_carrier_close(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        second_request = [
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "connect-requested"
        ][1]
        transcript[0], transcript[second_request] = (
            transcript[second_request],
            transcript[0],
        )
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(M0Error, "carrier lifecycle|pairing"):
            smoke.validate_m9_relay_status(status)

    def test_recovery_connect_cannot_predate_second_wisp_ready(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        recovery_connect = [
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "connect-requested"
        ][2]
        second_ready = [
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "wisp-ready"
        ][1]
        transcript[recovery_connect], transcript[second_ready] = (
            transcript[second_ready],
            transcript[recovery_connect],
        )
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(M0Error, "transition ordering|carrier lifecycle"):
            smoke.validate_m9_relay_status(status)

    def test_completion_cannot_precede_its_recovered_session_stream(self) -> None:
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        completion = next(
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "h2-m9-wisp-recovery-complete"
        )
        completion_connect = [
            index
            for index, entry in enumerate(transcript)
            if entry["event"] == "connect-requested"
        ][3]
        transcript[completion], transcript[completion_connect] = (
            transcript[completion_connect],
            transcript[completion],
        )
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(M0Error, "carrier lifecycle|pairing"):
            smoke.validate_m9_relay_status(status)

    def test_bool_protocol_alias_is_rejected(self) -> None:
        status = passing_relay_status()
        status["protocol"] = True
        with self.assertRaisesRegex(M0Error, "expected ready fixture"):
            smoke.validate_m9_relay_status(status)

    def test_terminal_quiescence_requires_relay_and_transport_closure(self) -> None:
        pre_cleanup = passing_relay_status()
        quiescent = copy.deepcopy(pre_cleanup)
        quiescent["activeWispSessions"] = 0
        quiescent["activeWispTransports"] = 0
        quiescent["wispTransportClosures"] = 2
        transcript = quiescent["transcript"]
        assert isinstance(transcript, list)
        transcript.extend(
            (event("wisp-disconnected"), event("wisp-transport-closed"))
        )
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        smoke.validate_m9_relay_quiescence(
            quiescent, pre_cleanup_status=pre_cleanup
        )

    def test_terminal_quiescence_rejects_partial_transport_cleanup(self) -> None:
        pre_cleanup = passing_relay_status()
        pending = copy.deepcopy(pre_cleanup)
        pending["activeWispSessions"] = 0
        transcript = pending["transcript"]
        assert isinstance(transcript, list)
        transcript.append(event("wisp-disconnected"))
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        with self.assertRaisesRegex(M0Error, "still in progress"):
            smoke.validate_m9_relay_quiescence(
                pending, pre_cleanup_status=pre_cleanup
            )

    def test_terminal_quiescence_rejects_status_injection(self) -> None:
        pre_cleanup = passing_relay_status()
        quiescent = copy.deepcopy(pre_cleanup)
        quiescent["activeWispSessions"] = 0
        quiescent["activeWispTransports"] = 0
        quiescent["wispTransportClosures"] = 2
        transcript = quiescent["transcript"]
        assert isinstance(transcript, list)
        transcript.extend(
            (event("wisp-disconnected"), event("wisp-transport-closed"))
        )
        for sequence, entry in enumerate(transcript, start=1):
            entry["sequence"] = sequence
        quiescent["unexpectedCleanupRecord"] = {"accepted": True}
        with self.assertRaisesRegex(M0Error, "field set"):
            smoke.validate_m9_relay_quiescence(
                quiescent, pre_cleanup_status=pre_cleanup
            )

    def test_wait_for_terminal_quiescence_accepts_only_known_progress(self) -> None:
        pre_cleanup = passing_relay_status()
        pending = copy.deepcopy(pre_cleanup)
        pending["activeWispSessions"] = 0
        pending_transcript = pending["transcript"]
        assert isinstance(pending_transcript, list)
        pending_transcript.append(event("wisp-disconnected"))
        for sequence, entry in enumerate(pending_transcript, start=1):
            entry["sequence"] = sequence

        quiescent = copy.deepcopy(pending)
        quiescent["activeWispTransports"] = 0
        quiescent["wispTransportClosures"] = 2
        quiescent_transcript = quiescent["transcript"]
        assert isinstance(quiescent_transcript, list)
        quiescent_transcript.append(event("wisp-transport-closed"))
        for sequence, entry in enumerate(quiescent_transcript, start=1):
            entry["sequence"] = sequence

        with mock.patch.object(
            smoke,
            "fetch_relay_status",
            side_effect=[copy.deepcopy(pre_cleanup), pending, quiescent],
        ), mock.patch.object(smoke.time, "sleep"):
            observed = smoke.wait_for_m9_relay_quiescence(
                "http://127.0.0.1:40123/status",
                pre_cleanup_status=pre_cleanup,
                timeout_seconds=1.0,
            )
        self.assertEqual(observed, quiescent)


class M9SnapshotAndSourceContractTest(unittest.TestCase):
    def test_host_snapshot_is_immutable_resource_set(self) -> None:
        snapshots = smoke.snapshot_m9_host_resources()
        identity = smoke.m9_host_delivery_identity(snapshots)
        self.assertEqual(set(identity), {"host_html", "host_js", "trusted_text_input_js"})
        tampered = dict(snapshots)
        tampered["unexpected.js"] = b"x"
        with self.assertRaisesRegex(M0Error, "resource set"):
            smoke.validate_m9_host_snapshots(tampered)

    def test_runner_stays_on_outer_observation_and_physical_input_boundary(self) -> None:
        runner = (TOOLS_DIR / "run_m9_wasm_browser_wisp_recovery_smoke.py").read_text(
            encoding="utf-8"
        )
        host = (
            TOOLS_DIR
            / "host"
            / "chrome_wasm_browser_m9_wisp_recovery_smoke_host.js"
        ).read_text(encoding="utf-8")
        for contents in (runner, host):
            self.assertNotIn("Page" + ".navigate", contents)
            self.assertNotIn("Runtime" + ".evaluate", contents)
            self.assertNotIn("client.evaluate", contents)
        self.assertIn("Input.insertText", runner)
        self.assertIn("dispatch_control_shortcut", runner)
        self.assertIn("Runtime.enable", runner)
        pre_cleanup_transport = runner.index(
            'stage = "wait_for_pre_cleanup_transport"'
        )
        self.assertLess(
            pre_cleanup_transport,
            runner.index('stage = "cleanup_before_pass"'),
        )
        self.assertLess(
            runner.index('stage = "cleanup_before_pass"'),
            runner.index(f'print(f"{{SENTINEL}}:PASS"'),
        )
        quiescence = runner.index('stage = "wait_for_relay_quiescence"')
        self.assertLess(
            runner.index('stage = "cleanup_before_pass"'), quiescence
        )
        self.assertLess(
            quiescence, runner.index("stop_process_group(", quiescence)
        )
        self.assertLess(
            runner.index('stage = "recheck_source_identities"'),
            runner.index(f'print(f"{{SENTINEL}}:PASS"'),
        )

    def test_network_enable_is_armed_before_input_and_fixture_gates_recovery(self) -> None:
        """Keep the no-race handoff between native enablement and Fetch.

        The recorder dispatches its fixed Network.enable command before the
        sole physical Ctrl+L/Enter navigation. A blank WebContents answers it
        only after that typed navigation supplies a renderer, so the C++ smoke
        waits for its response after initial FVP. The initial document has no
        inline executable code under the relay's default script-src 'self'
        policy: its one immutable same-origin script waits two renderer frames
        before invoking the reconnect Fetch. This source contract is paired
        with the real M9 smoke and prevents a future edit from silently
        bypassing either half of the bounded handoff.
        """

        smoke_source = (
            TOOLS_DIR.parent.parent
            / "chrome"
            / "browser"
            / "wasm"
            / "wasm_browser_smoke.cc"
        ).read_text(encoding="utf-8")
        fixture_source = (TOOLS_DIR / "m5_wisp_test_server.js").read_text(
            encoding="utf-8"
        )

        start = smoke_source.index("network_recorder.Start(")
        typed_navigation_wait = smoke_source.index(
            "navigation_observer.WaitForNavigationAndFirstVisuallyNonEmptyPaint(",
            start,
        )
        enable_wait = smoke_source.index(
            "network_recorder.WaitForNetworkEnable();", start
        )
        self.assertLess(start, typed_navigation_wait)
        self.assertLess(typed_navigation_wait, enable_wait)

        page = fixture_source.split("function m9WispRecoveryPage() {", 1)[1].split(
            "\nfunction m9WispRecoveryScript()", 1
        )[0]
        script = fixture_source.split("function m9WispRecoveryScript() {", 1)[1].split(
            "\nfunction m9WispRecoveryCompletePage()", 1
        )[0]
        self.assertIn(
            '<script src="/m5/m9-wisp-recovery-script.js" defer></script>',
            page,
        )
        self.assertNotIn("<script>\n", page)
        self.assertIn(
            'const M9_WISP_RECOVERY_SCRIPT_PATH = "/m5/m9-wisp-recovery-script.js";',
            fixture_source,
        )
        first_fetch = script.index("const partial = await fetch(reconnectStreamUrl")
        nested_frame_gate = script.index(
            "requestAnimationFrame(() => {\n"
            "    requestAnimationFrame(() => {\n"
            "      run().catch(() => failure());"
        )
        self.assertLess(first_fetch, nested_frame_gate)
        self.assertEqual(script.count("run().catch(() => failure());"), 1)
        self.assertIn(
            "browser-side fixed Network.enable recorder is armed before trusted\n"
            "  // address-bar input",
            script,
        )
        self.assertIn(
            '"content-type": "text/javascript; charset=utf-8"',
            fixture_source,
        )
        self.assertIn("h2-m9-wisp-recovery-script", fixture_source)

        record_finished = smoke_source.split(
            "void RecordFinished(const base::DictValue& params) {", 1
        )[1].split("\n  void RecordFailed", 1)[0]
        self.assertLess(
            record_finished.index("recovery_loading_finished_ = true;"),
            record_finished.index("Detach();"),
        )
        self.assertEqual(record_finished.split("Detach();", 1)[1].strip(), "}")
        validate_evidence = smoke_source.split(
            "void ValidateRecoveryEvidence() const {", 1
        )[1].split("\n  void Detach()", 1)[0]
        self.assertIn("CHECK(recovery_loading_finished_);", validate_evidence)
        self.assertIn("CHECK(!agent_host_);", validate_evidence)
        self.assertIn("CHECK(!web_contents_);", validate_evidence)
        self.assertLess(
            smoke_source.index("network_recorder.WaitForNetworkEnable();", start),
            smoke_source.index("completion_observer.WaitForCompletion();", start),
        )

    def test_completion_observer_waits_through_provisional_navigation_title(self) -> None:
        smoke_source = (
            TOOLS_DIR.parent.parent
            / "chrome"
            / "browser"
            / "wasm"
            / "wasm_browser_smoke.cc"
        ).read_text(encoding="utf-8")
        observer = smoke_source.split(
            "class M9WispRecoveryCompletionObserver final", 1
        )[1].split("\nvoid SendKeyPress", 1)[0]
        did_finish = observer.split("void DidFinishNavigation(", 1)[1].split(
            "\n  void DidStopLoading", 1
        )[0]
        title_was_set = observer.split("void TitleWasSet", 1)[1].split(
            "\n  void OnTimeout", 1
        )[0]
        title_check = observer.split(
            "void ObserveCurrentCompletionTitleIfPresent() {", 1
        )[1].split("\n  void QuitWait", 1)[0]
        self.assertIn("ObserveCurrentCompletionTitleIfPresent();", did_finish)
        self.assertIn("CHECK_EQ(web_contents(), expected_web_contents_);", did_finish)
        self.assertIn("ObserveCurrentCompletionTitleIfPresent();", title_was_set)
        self.assertIn("if (title != kM9WispRecoveryCompleteTitle) {", title_check)
        self.assertIn("return;", title_check)
        self.assertNotIn("CHECK_EQ(title, kM9WispRecoveryCompleteTitle)", title_check)
        self.assertIn("CHECK(completion_title_observed_);", observer)
        self.assertIn("!completion_title_observed_", observer)

    def test_ready_schema_bool_alias_is_rejected(self) -> None:
        line = (
            '{"schema_version":true,"httpsUrl":"https://a.test:43211/m5/",'
            '"transcriptUrl":"http://127.0.0.1:43210/status",'
            '"wispEndpoint":"ws://127.0.0.1:43210/wisp/"}'
        )
        with self.assertRaisesRegex(M0Error, "metadata"):
            smoke.parse_relay_ready_line(line)


class M9MainCleanupBoundaryTest(unittest.TestCase):
    """Exercise the terminal cleanup boundary with fully controlled children."""

    def _run_with_preexited_leader(
        self, *, leader: str, returncode: int
    ) -> tuple[
        int,
        str,
        str,
        mock.Mock,
        mock.Mock,
        mock.Mock,
        mock.Mock,
        mock.Mock,
        mock.Mock,
        mock.Mock,
        list[str],
    ]:
        self.assertIn(leader, ("browser", "relay"))

        events: list[str] = []
        relay = mock.Mock()
        relay.pid = 222
        relay.stdout = io.StringIO()
        relay.stderr = io.StringIO()
        relay.returncode = None
        def relay_poll() -> int | None:
            events.append("relay_poll")
            return relay.returncode

        relay.poll.side_effect = relay_poll

        browser = mock.Mock()
        browser.pid = 111
        browser.stderr = io.StringIO()
        browser.returncode = None
        def browser_poll() -> int | None:
            events.append("browser_poll")
            return browser.returncode

        browser.poll.side_effect = browser_poll

        relay_stdout_reader = mock.Mock()
        relay_stderr_reader = mock.Mock()
        browser_stderr_reader = mock.Mock()
        profile = mock.Mock()
        profile.name = "/tmp/m9-wisp-recovery-test-profile"
        server = mock.Mock()
        server_thread = mock.Mock()
        client = mock.Mock()

        def close_client() -> None:
            events.append("client_close")
            if leader == "browser":
                browser.returncode = returncode

        client.close.side_effect = close_client
        stop_browser = mock.Mock(side_effect=lambda *_args, **_kwargs: events.append("stop_browser"))
        stop_relay = mock.Mock(side_effect=lambda *_args, **_kwargs: events.append("stop_relay"))
        abort_browser = mock.Mock(side_effect=lambda *_args, **_kwargs: events.append("abort_browser"))
        abort_relay = mock.Mock(side_effect=lambda *_args, **_kwargs: events.append("abort_relay"))
        cleanup_server = mock.Mock(return_value=None)
        stdout = io.StringIO()
        stderr = io.StringIO()
        stopped_observation = mock.Mock()
        stopped_observation.si_code = smoke.os.CLD_STOPPED
        stopped_observation.si_status = smoke.signal.SIGSTOP

        def finish_relay_quiescence(
            *_args: object, **_kwargs: object
        ) -> dict[str, object]:
            events.append("relay_quiescence")
            if leader == "relay":
                relay.returncode = returncode
            return passing_relay_status()

        with tempfile.TemporaryDirectory() as diagnostics_directory:
            relay_ready = smoke.RelayReady(
                wisp_endpoint="ws://127.0.0.1:40124/wisp/",
                transcript_url="http://127.0.0.1:40124/status",
            )
            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(
                        sys,
                        "argv",
                        [
                            "run_m9_wasm_browser_wisp_recovery_smoke.py",
                            "--browser",
                            "/tmp/fake-browser",
                            "--diagnostics-dir",
                            diagnostics_directory,
                            "--timeout",
                            "5",
                        ],
                    )
                )
                stack.enter_context(
                    mock.patch.object(smoke, "snapshot_wisp_artifacts", return_value={})
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke, "verify_optional_wisp_data_private_key_pem_artifact"
                    )
                )
                stack.enter_context(
                    mock.patch.object(smoke, "snapshot_m9_host_resources", return_value={})
                )
                stack.enter_context(
                    mock.patch.object(smoke, "snapshot_wisp_relay_closure", return_value={})
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke, "artifact_delivery_identity", return_value={"artifact": "id"}
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke, "m9_host_delivery_identity", return_value={"host": "id"}
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke, "wisp_relay_closure_identity", return_value={"relay": "id"}
                    )
                )
                stack.enter_context(mock.patch.object(smoke, "load_manifest", return_value={}))
                stack.enter_context(
                    mock.patch.object(smoke, "checked_output", return_value="test-commit")
                )
                stack.enter_context(
                    mock.patch.object(smoke, "manifest_versions", return_value=VERSIONS)
                )
                stack.enter_context(
                    mock.patch.object(smoke, "print_context", return_value={"test": True})
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke,
                        "find_browser",
                        return_value=(Path("/tmp/fake-browser"), "test"),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke, "find_node", return_value=Path("/tmp/fake-node")
                    )
                )
                stack.enter_context(mock.patch.object(smoke, "create_server", return_value=server))
                stack.enter_context(
                    mock.patch.object(smoke.threading, "Thread", return_value=server_thread)
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke, "m5_host_origin", return_value="http://127.0.0.1:40123"
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke,
                        "materialized_wisp_relay_closure_from_snapshot",
                        return_value=contextlib.nullcontext(Path("/tmp/fake-relay.js")),
                    )
                )
                stack.enter_context(
                    mock.patch.object(smoke, "relay_command", return_value=["fake-relay"])
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke.subprocess, "Popen", side_effect=(relay, browser)
                    )
                )
                stack.enter_context(mock.patch.object(smoke.os, "kill"))
                stack.enter_context(
                    mock.patch.object(smoke.os, "waitid", return_value=stopped_observation)
                )
                stack.enter_context(
                    mock.patch.object(
                        smoke,
                        "BrowserStderrReader",
                        side_effect=(
                            relay_stdout_reader,
                            relay_stderr_reader,
                            browser_stderr_reader,
                        ),
                    )
                )
                stack.enter_context(
                    mock.patch.object(smoke, "wait_for_relay_ready", return_value=relay_ready)
                )
                stack.enter_context(
                    mock.patch.object(smoke, "smoke_url", return_value="http://127.0.0.1:40123/")
                )
                stack.enter_context(
                    mock.patch.object(smoke, "unused_loopback_port", return_value=40125)
                )
                stack.enter_context(
                    mock.patch.object(smoke, "browser_command", return_value=["fake-browser"])
                )
                stack.enter_context(
                    mock.patch.object(smoke, "wait_for_page_client", return_value=client)
                )
                stack.enter_context(mock.patch.object(smoke, "wait_for_console_marker"))
                stack.enter_context(mock.patch.object(smoke, "dispatch_unmodified_enter"))
                stack.enter_context(
                    mock.patch.object(smoke, "wait_for_result", return_value=passing_result())
                )
                stack.enter_context(mock.patch.object(smoke, "validate_result"))
                stack.enter_context(
                    mock.patch.object(
                        smoke,
                        "wait_for_m9_relay_pre_cleanup_status",
                        return_value=passing_relay_status(),
                    )
                )
                stack.enter_context(mock.patch.object(smoke, "validate_m9_relay_status"))
                stack.enter_context(
                    mock.patch.object(
                        smoke,
                        "wait_for_m9_relay_quiescence",
                        side_effect=finish_relay_quiescence,
                    )
                )
                stack.enter_context(mock.patch.object(smoke, "stop_browser_group", stop_browser))
                stack.enter_context(mock.patch.object(smoke, "stop_process_group", stop_relay))
                stack.enter_context(mock.patch.object(smoke, "abort_browser_group", abort_browser))
                stack.enter_context(mock.patch.object(smoke, "abort_process_group", abort_relay))
                stack.enter_context(mock.patch.object(smoke, "cleanup_server", cleanup_server))
                stack.enter_context(
                    mock.patch.object(
                        smoke.tempfile, "TemporaryDirectory", return_value=profile
                    )
                )
                stack.enter_context(contextlib.redirect_stdout(stdout))
                stack.enter_context(contextlib.redirect_stderr(stderr))
                exit_code = smoke.main()

        return (
            exit_code,
            stdout.getvalue(),
            stderr.getvalue(),
            stop_browser,
            stop_relay,
            abort_browser,
            abort_relay,
            cleanup_server,
            profile,
            client,
            events,
        )

    def _assert_no_terminal_success_records(self, stdout: str, stderr: str) -> None:
        combined = stdout + stderr
        for record in (
            ":ARTIFACT_DELIVERY ",
            ":BROWSER_RESULT ",
            ":RELAY_STATUS ",
            ":RELAY_QUIESCENT_STATUS ",
            ":PASS",
        ):
            with self.subTest(record=record):
                self.assertNotIn(f"{smoke.SENTINEL}{record}", combined)

    def test_main_rejects_clean_and_nonzero_preexited_browser_before_pass(self) -> None:
        for returncode in (0, 23):
            with self.subTest(returncode=returncode):
                (
                    exit_code,
                    stdout,
                    stderr,
                    stop_browser,
                    stop_relay,
                    abort_browser,
                    abort_relay,
                    cleanup_server,
                    profile,
                    client,
                    events,
                ) = self._run_with_preexited_leader(
                    leader="browser", returncode=returncode
                )

                self.assertEqual(exit_code, 1)
                self.assertIn(
                    "M9 host browser exited before clean-stop "
                    f"(status {returncode})",
                    stderr,
                )
                self._assert_no_terminal_success_records(stdout, stderr)
                stop_browser.assert_not_called()
                stop_relay.assert_not_called()
                abort_browser.assert_called_once()
                abort_relay.assert_called_once()
                cleanup_server.assert_called_once()
                profile.cleanup.assert_called_once_with()
                client.close.assert_called_once_with()
                self.assertLess(events.index("client_close"), events.index("browser_poll"))
                self.assertLess(events.index("browser_poll"), events.index("abort_browser"))

    def test_main_rejects_clean_and_nonzero_preexited_relay_before_pass(self) -> None:
        for returncode in (0, 29):
            with self.subTest(returncode=returncode):
                (
                    exit_code,
                    stdout,
                    stderr,
                    stop_browser,
                    stop_relay,
                    abort_browser,
                    abort_relay,
                    cleanup_server,
                    profile,
                    client,
                    events,
                ) = self._run_with_preexited_leader(
                    leader="relay", returncode=returncode
                )

                self.assertEqual(exit_code, 1)
                self.assertIn(
                    "M9 WISP relay exited before clean-stop "
                    f"(status {returncode})",
                    stderr,
                )
                self._assert_no_terminal_success_records(stdout, stderr)
                stop_browser.assert_called_once()
                stop_relay.assert_not_called()
                abort_browser.assert_not_called()
                abort_relay.assert_called_once()
                cleanup_server.assert_called_once()
                profile.cleanup.assert_called_once_with()
                client.close.assert_called_once_with()
                self.assertLess(events.index("relay_quiescence"), events.index("relay_poll"))
                self.assertLess(events.index("relay_poll"), events.index("abort_relay"))

    def test_verified_leader_stop_requires_a_kernel_stopped_witness(self) -> None:
        process = mock.Mock()
        process.pid = 31337
        process.poll.return_value = None
        stopped = mock.Mock()
        stopped.si_code = smoke.os.CLD_STOPPED
        stopped.si_status = smoke.signal.SIGSTOP

        with (
            mock.patch.object(smoke.os, "kill") as kill,
            mock.patch.object(smoke.os, "waitid", return_value=stopped) as waitid,
        ):
            smoke._require_live_leader_for_clean_stop(
                process, description="test leader"
            )

        self.assertEqual(
            kill.call_args_list,
            [
                mock.call(process.pid, smoke.signal.SIGSTOP),
                mock.call(process.pid, smoke.signal.SIGTERM),
                mock.call(process.pid, smoke.signal.SIGCONT),
            ],
        )
        waitid.assert_called_once_with(
            smoke.os.P_PID,
            process.pid,
            smoke.os.WEXITED | smoke.os.WSTOPPED | smoke.os.WNOHANG | smoke.os.WNOWAIT,
        )

    def test_verified_leader_stop_rejects_exit_after_poll_before_stop_witness(self) -> None:
        process = mock.Mock()
        process.pid = 31338
        process.poll.return_value = None
        exited = mock.Mock()
        exited.si_code = smoke.os.CLD_EXITED
        exited.si_status = 23

        with (
            mock.patch.object(smoke.os, "kill") as kill,
            mock.patch.object(smoke.os, "waitid", return_value=exited),
            self.assertRaisesRegex(M0Error, "exited before clean-stop"),
        ):
            smoke._require_live_leader_for_clean_stop(
                process, description="test leader"
            )

        self.assertEqual(
            kill.call_args_list,
            [
                mock.call(process.pid, smoke.signal.SIGSTOP),
                mock.call(process.pid, smoke.signal.SIGCONT),
            ],
        )


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def event_client() -> m4_cdp.DevToolsClient:
    client = object.__new__(m4_cdp.DevToolsClient)
    client._connection = FakeConnection()  # type: ignore[attr-defined]
    client._pending_events = deque()  # type: ignore[attr-defined]
    return client


class M4NextEventFramingTest(unittest.TestCase):
    def test_queued_event_is_delivered_without_select(self) -> None:
        client = event_client()
        queued = {"method": "Runtime.consoleAPICalled", "params": {}}
        client._pending_events.append(queued)  # type: ignore[attr-defined]
        with mock.patch.object(m4_cdp.select, "select") as select:
            self.assertEqual(client.next_event(0), queued)
        select.assert_not_called()

    def test_nonfinite_and_bool_idle_timeout_are_rejected(self) -> None:
        client = event_client()
        for timeout in (True, math.nan, math.inf, -math.inf, -1):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(
                M0Error, "idle readiness timeout"
            ):
                client.next_event(timeout)

    def test_queued_event_does_not_bypass_idle_timeout_validation(self) -> None:
        client = event_client()
        client._pending_events.append({"method": "Runtime.consoleAPICalled"})  # type: ignore[attr-defined]
        for timeout in (True, math.nan, -1):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(
                M0Error, "idle readiness timeout"
            ):
                client.next_event(timeout)
        self.assertEqual(len(client._pending_events), 1)  # type: ignore[attr-defined]

    def test_idle_timeout_returns_none_without_receiving(self) -> None:
        client = event_client()
        client._receive = mock.Mock()  # type: ignore[method-assign]
        with mock.patch.object(m4_cdp.select, "select", return_value=([], [], [])):
            self.assertIsNone(client.next_event(0.01))
        client._receive.assert_not_called()  # type: ignore[attr-defined]

    def test_readiness_then_complete_frame_returns_event(self) -> None:
        client = event_client()
        received = {"method": "Runtime.consoleAPICalled", "params": {"args": []}}
        client._receive = mock.Mock(return_value=received)  # type: ignore[method-assign]
        with mock.patch.object(
            m4_cdp.select, "select", return_value=([client._connection], [], [])
        ):
            self.assertEqual(client.next_event(0.01), received)
        client._receive.assert_called_once()  # type: ignore[attr-defined]

    def test_event_arriving_while_call_waits_is_queued(self) -> None:
        client = event_client()
        client._next_id = 0  # type: ignore[attr-defined]
        client._send_text = mock.Mock()  # type: ignore[method-assign]
        event = {"method": "Runtime.consoleAPICalled", "params": {}}
        client._receive = mock.Mock(  # type: ignore[method-assign]
            side_effect=[event, {"id": 1, "result": {}}]
        )
        self.assertEqual(client.call("Runtime.enable"), {})
        self.assertEqual(client.next_event(0), event)

    def test_command_response_is_rejected_while_waiting_for_event(self) -> None:
        client = event_client()
        client._receive = mock.Mock(return_value={"id": 1, "result": {}})  # type: ignore[method-assign]
        with mock.patch.object(
            m4_cdp.select, "select", return_value=([client._connection], [], [])
        ), self.assertRaisesRegex(M0Error, "command response"):
            client.next_event(0.01)

    def test_queue_overflow_is_rejected(self) -> None:
        client = event_client()
        client._pending_events.extend(  # type: ignore[attr-defined]
            {"method": "Runtime.consoleAPICalled"}
            for _ in range(m4_cdp.MAX_PENDING_EVENTS)
        )
        with self.assertRaisesRegex(M0Error, "bounded limit"):
            client._queue_event({"method": "Runtime.consoleAPICalled"})

    def test_partial_frame_timeout_closes_connection_and_is_terminal(self) -> None:
        client = event_client()
        client._receive = mock.Mock(side_effect=socket.timeout())  # type: ignore[method-assign]
        with mock.patch.object(
            m4_cdp.select, "select", return_value=([client._connection], [], [])
        ), self.assertRaisesRegex(M0Error, "frame did not complete"):
            client.next_event(0.01)
        self.assertTrue(client._connection.closed)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()

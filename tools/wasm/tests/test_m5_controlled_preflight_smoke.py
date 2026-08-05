#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the loopback-only M5 preflight runner."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import run_m5_controlled_preflight_smoke as controlled_smoke
import run_m5_wisp_smoke


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}


class FakeServer:
    server_address = ("127.0.0.1", 38123)


def relay_ready() -> run_m5_wisp_smoke.RelayReady:
    return run_m5_wisp_smoke.parse_relay_ready_line(
        json.dumps(
            {
                "schema_version": 1,
                "wispEndpoint": "ws://127.0.0.1:40123/wisp/",
                "httpsUrl": "https://a.test:4443/m5/",
                "redirectUrl": "https://a.test:4443/m5/redirect-cookie",
                "plaintextHttpControlUrl": (
                    "http://a.test:4446/m5/plaintext-control"
                ),
                "mixedContentTargetUrl": (
                    "http://a.test:4446/m5/mixed-content-target"
                ),
                "http1Url": "https://a.test:4444/m5/cors-resource",
                "tlsFailureUrl": "https://a.test:4445/m5/tls-name-mismatch",
                "transcriptUrl": "http://127.0.0.1:40123/status",
            }
        )
    )


def passing_result() -> dict[str, object]:
    devtools = controlled_smoke.expected_controlled_preflight_devtools_network()
    return {
        "protocol": 1,
        "case": "wisp_controlled_preflight_m5",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": copy.deepcopy(VERSIONS),
        "initialFrame": {"id": 1, "width": 800, "height": 600},
        "controlledPreflightFrame": {"id": 2, "width": 800, "height": 600},
        "navigationResult": {"ok": True, "scheme": "https"},
        "controlledPreflightDevtoolsNetworkEnabled": {
            "protocol": 1,
            "state": "enabled",
            "networkEnabled": True,
            "events": [],
        },
        "readiness": {
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "fatalErrors": [],
            "navigation": {
                "committed": True,
                "scheme": "https",
                "responseCode": 200,
                "connectionProtocol": "h2",
            },
            "controlledPreflightDevtoolsNetwork": devtools,
            "heartbeat": {
                "anchor": "m5-controlled-preflight-navigation-committed",
                "timerDelta": 2,
                "animationFrameDelta": 2,
                "maxTimerGapMs": 25,
            },
        },
        "logs": {
            "host": [
                "initialize:wisp-configured",
                "m5:controlled-preflight-devtools-network:enabled",
                "navigation:requested:m5-controlled-preflight",
                "navigation:committed:m5-controlled-preflight",
                "m5:controlled-preflight-devtools-network:complete",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "shutdown": {
            "ok": True,
            "accepted": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "failedChecks": [],
        "error": None,
    }


def passing_relay_status() -> dict[str, object]:
    return {
        "fixture": "chromium-wasm-m5-network-v1",
        "protocol": 1,
        "ready": True,
        "wispSessions": 1,
        "rejectedDestinations": 1,
        "localGatewayBlockedPortAttempts": 1,
        "localGateway443StreamsOpened": 1,
        "localGateway443Requests": 1,
        "udpPackets": 0,
        "relayErrors": 0,
        "h2Requests": {"protocol": "h2", "count": 1},
        "requestedDestinations": [{"hostname": "a.test", "port": 443}],
        "transcript": [
            {"sequence": 1, "event": "wisp-connected"},
            {"sequence": 2, "event": "wisp-ready"},
            {"sequence": 3, "event": "local-gateway-444-blocked"},
            {
                "sequence": 4,
                "event": "connect-requested",
                "destination": "a.test:443",
            },
            {
                "sequence": 5,
                "event": "connect-open",
                "destination": "a.test:443",
            },
            {"sequence": 6, "event": "local-gateway-443-request"},
        ],
    }


class M5ControlledPreflightSmokeTest(unittest.TestCase):
    def test_smoke_url_has_only_transport_and_metadata_inputs(self) -> None:
        url = controlled_smoke.controlled_preflight_smoke_url(
            FakeServer(), "result-token", VERSIONS, relay_ready=relay_ready()
        )
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(
            query["case"], [m3_content_server.M5_CONTROLLED_PREFLIGHT_CASE]
        )
        self.assertEqual(
            query["module"], [
                "/__m3__/artifacts/"
                "content_shell_wasm_m5_controlled_preflight_test.js"
            ],
        )
        self.assertEqual(query["wisp_endpoint"], ["ws://127.0.0.1:40123/wisp/"])
        for forbidden in (
            "m5_url",
            "httpsUrl",
            "m5_public_url",
            "redirect_url",
            "m5_plaintext_http_control_url",
        ):
            self.assertNotIn(forbidden, query)

    def test_passing_result_is_accepted(self) -> None:
        controlled_smoke.validate_controlled_preflight_result(
            passing_result(), expected_versions=VERSIONS
        )

    def test_result_rejects_urls_and_mutated_native_evidence(self) -> None:
        invalid_url = passing_result()
        invalid_url["error"] = "https://leaked.invalid/"
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_result(
                invalid_url, expected_versions=VERSIONS
            )

        invalid_protocol = passing_result()
        invalid_protocol["readiness"]["controlledPreflightDevtoolsNetwork"][
            "responseProtocol"
        ] = "http/1.1"
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_result(
                invalid_protocol, expected_versions=VERSIONS
            )

        invalid_events = passing_result()
        invalid_events["readiness"]["controlledPreflightDevtoolsNetwork"][
            "events"
        ].pop()
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_result(
                invalid_events, expected_versions=VERSIONS
            )

    def test_passing_relay_transcript_is_accepted(self) -> None:
        controlled_smoke.validate_controlled_preflight_relay_transcript(
            passing_relay_status()
        )

    def test_relay_rejects_denial_after_document_or_a_second_destination(self) -> None:
        wrong_order = passing_relay_status()
        wrong_order["transcript"][2], wrong_order["transcript"][5] = (
            wrong_order["transcript"][5],
            wrong_order["transcript"][2],
        )
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_relay_transcript(
                wrong_order
            )

        extra_destination = passing_relay_status()
        extra_destination["requestedDestinations"].append(
            {"hostname": "a.test", "port": 444}
        )
        with self.assertRaises(M0Error):
            controlled_smoke.validate_controlled_preflight_relay_transcript(
                extra_destination
            )

    def test_harness_admits_the_controlled_preflight_result_case(self) -> None:
        self.assertIn(
            m3_content_server.M5_CONTROLLED_PREFLIGHT_CASE,
            m3_content_server.M3_RESULT_CASES,
        )


if __name__ == "__main__":
    unittest.main()

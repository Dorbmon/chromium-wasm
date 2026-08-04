#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the controlled M5 WISP browser runner."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import run_m5_wisp_smoke


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}
RELAY_READY_LINE = json.dumps(
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


class FakeServer:
    server_address = ("127.0.0.1", 38123)


def passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": "wisp_network_m5",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": copy.deepcopy(VERSIONS),
        "initialFrame": {
            "id": 1,
            "width": 800,
            "height": 600,
            "timestampMs": 1,
        },
        "plaintextHttpControlNavigationResult": {
            "ok": True,
            "scheme": "http",
            "hostname": "a.test",
        },
        "navigationResult": {
            "ok": True,
            "scheme": "https",
            "hostname": "a.test",
        },
        "tlsFailureNavigationResult": {
            "ok": True,
            "scheme": "https",
            "hostname": "a.test",
        },
        "plaintextHttpControlReadiness": {
            "baseReady": True,
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "pageReady": True,
            "fatalErrors": [],
            "navigation": {"committed": True, "scheme": "http"},
            "heartbeat": {
                "anchor": "m5-plaintext-http-control-navigation-committed",
                "elapsedMs": 10,
            },
            "pageProbe": {
                "protocol": 1,
                "fixture": "chromium-wasm-m5-network-v1",
                "ready": True,
                "phase": "plaintext-http-control",
                "plaintextHttpControlDocument": True,
                "plaintextHttpControlProof": True,
            },
        },
        "readiness": {
            "baseReady": True,
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "pageReady": True,
            "fatalErrors": [],
            "navigation": {"committed": True, "scheme": "https"},
            "heartbeat": {
                "anchor": "m5-https-navigation-committed",
                "elapsedMs": 10,
            },
            "pageProbe": {
                "protocol": 1,
                "fixture": "chromium-wasm-m5-network-v1",
                "ready": True,
                "h2Fetch": True,
                "h2Protocol": "h2",
                "corsFetch": True,
                "webSocketEcho": True,
                "altSvcH3Advertised": True,
                "redirected": True,
                "cacheStored": True,
                "cacheRevalidated": True,
                "cancelStreamStarted": True,
                "cancelStreamReceivedFirstChunk": True,
                "cancelStreamAborted": True,
                "cancelStreamErrorName": "AbortError",
                "cancelStreamProof": True,
                "slowStreamStarted": True,
                "slowStreamFirstStage": True,
                "slowStreamSecondStage": True,
                "slowStreamThirdStage": True,
                "slowStreamComplete": True,
                "slowStreamProof": True,
                "slowStreamConsumerPauseStarted": True,
                "slowStreamConsumerBurstRead": True,
                "slowStreamConsumerResume": True,
                "slowStreamElapsedMs": 200,
                "slowStreamFirstToSecondStageDelayMs": 100,
                "slowStreamSecondToThirdStageDelayMs": 100,
                "slowStreamConsumerPauseElapsedMs": 100,
                "slowStreamConsumerPauseTimerTicks": 4,
                "slowStreamTimerTicksWhileWaiting": 8,
                "largeDownloadStarted": True,
                "largeDownloadContentDisposition": True,
                "largeDownloadComplete": True,
                "largeDownloadBytes": 512 * 1024,
                "largeDownloadReaderChunks": 32,
                "cspConnectSrcBlocked": True,
                "phase": "https-fixture",
                "activeMixedContentBlocked": True,
                "activeMixedContentTargetUrl": (
                    "http://a.test:4446/m5/mixed-content-target"
                ),
                "activeMixedContentErrorName": "TypeError",
                "activeMixedContentCspAllowed": True,
                "nonce": "fixed-test-nonce",
            },
        },
        "slowStreamHeartbeat": {
            "anchor": "m5-https-navigation-committed",
            "elapsedMs": 200,
            "timerDelta": 8,
            "animationFrameDelta": 4,
            "maxTimerGapMs": 50,
        },
        "logs": {
            "host": [
                "initialize:wisp-configured",
                "navigation:requested:m5-plaintext-http-control",
                "navigation:committed:m5-plaintext-http-control",
                "navigation:requested:m5-https",
                "navigation:requested:m5-https-tls-failure",
                "navigation:failed:m5-https:-200",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "tlsFailureReadiness": {
            "navigationCommitted": False,
            "fatalErrors": [],
            "navigation": {
                "committed": False,
                "scheme": "https",
                "netError": -200,
            },
            "heartbeat": {
                "anchor": "m5-https-navigation-tls-rejected",
                "elapsedMs": 10,
            },
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
        "activeWispSessions": 0,
        "wispSessions": 1,
        "rejectedDestinations": 0,
        "udpPackets": 0,
        "relayErrors": 0,
        "corsRequests": 1,
        "webSocketEchoes": 1,
        "redirectRequests": 1,
        "redirectCookieValidations": 1,
        "cacheStore200s": 1,
        "cacheConditionalRequests": 1,
        "cacheNotModified304s": 1,
        "cacheUnexpectedRequests": 0,
        "cancelStreamCancelResets": 1,
        "cancelStreamFirstChunks": 1,
        "cancelStreamPhase": "cancel-observed",
        "cancelStreamProofs": 1,
        "cancelStreamProofSessionMismatches": 0,
        "cancelStreamProofTimeouts": 0,
        "cancelStreamRequests": 1,
        "cancelStreamUnexpectedResets": 0,
        "largeDownloadPhase": "complete",
        "largeDownloadBackpressureEvents": 32,
        "largeDownloadBytes": 512 * 1024,
        "largeDownloadChunks": 32,
        "largeDownloadCompletions": 1,
        "largeDownloadRequests": 1,
        "largeDownloadUnexpectedCloses": 0,
        "slowStreamPhase": "complete",
        "slowStreamRequests": 1,
        "slowStreamFirstStages": 1,
        "slowStreamSecondStages": 1,
        "slowStreamThirdStages": 1,
        "slowStreamCompletedStreams": 1,
        "slowStreamConsumerBurstBytes": 64 * 1024,
        "slowStreamConsumerBurstWrites": 1,
        "slowStreamConsumerPauseReadyRequests": 1,
        "slowStreamConsumerResumes": 1,
        "slowStreamFirstStageAcks": 1,
        "slowStreamSecondStageAcks": 1,
        "slowStreamProofs": 1,
        "slowStreamSessionMismatches": 0,
        "slowStreamStageAckTimeouts": 0,
        "slowStreamUnexpectedCloses": 0,
        "slowStreamStageDelayMs": 100,
        "slowStreamStageDelaySchedules": 2,
        "cspConnectSrcProofs": 1,
        "cspConnectSrcTargetTcpConnections": 0,
        "cspConnectSrcTargetRequests": 0,
        "plaintextHttpControlPhase": "post-control",
        "plaintextHttpControlTcpConnections": 1,
        "plaintextHttpControlRequests": 1,
        "plaintextHttpControlProofs": 1,
        "mixedContentTargetPostControlWispConnects": 0,
        "mixedContentTargetPostControlTcpConnections": 0,
        "mixedContentTargetPostControlRequests": 0,
        "mixedContentProofs": 1,
        "tlsMismatchTcpConnections": 1,
        "tlsMismatchHttpStreams": 0,
        "h2Requests": {"count": 2, "protocol": "h2"},
        "requestedDestinations": [
            {"hostname": "a.test", "port": 4446},
            {"hostname": "a.test", "port": 4443},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4445},
        ],
        "transcript": [
            {"sequence": 1, "event": "wisp-ready"},
            {"sequence": 2, "event": "connect-open"},
            {"sequence": 3, "event": "plaintext-http-control-tcp-connect"},
            {"sequence": 4, "event": "h1-plaintext-http-control"},
            {"sequence": 5, "event": "h1-plaintext-http-control-proof"},
            {
                "sequence": 6,
                "event": "plaintext-http-control-phase-complete",
            },
            {"sequence": 7, "event": "h2-redirect"},
            {"sequence": 8, "event": "h2-redirect-cookie"},
            {"sequence": 9, "event": "h2-page"},
            {"sequence": 10, "event": "h2-page-cookie"},
            {"sequence": 11, "event": "h2-resource"},
            {"sequence": 12, "event": "h2-cache-store-200"},
            {"sequence": 13, "event": "h2-cache-revalidate-304"},
            {"sequence": 14, "event": "h2-csp-connect-src-proof"},
            {"sequence": 15, "event": "h2-mixed-content-proof"},
            {"sequence": 16, "event": "h2-cancel-stream-start"},
            {
                "sequence": 17,
                "event": "h2-cancel-stream-cancel-reset",
                "rstCode": 8,
            },
            {"sequence": 18, "event": "h2-cancel-stream-proof"},
            {"sequence": 19, "event": "h2-slow-stream-start"},
            {"sequence": 20, "event": "h2-slow-stream-first-stage"},
            {
                "sequence": 21,
                "event": "h2-slow-stream-first-stage-ack",
            },
            {"sequence": 22, "event": "h2-slow-stream-second-stage"},
            {
                "sequence": 23,
                "event": "h2-slow-stream-consumer-pause-ready",
            },
            {
                "sequence": 24,
                "event": "h2-slow-stream-consumer-burst",
                "bytes": 64 * 1024,
                "backpressured": True,
            },
            {
                "sequence": 25,
                "event": "h2-slow-stream-consumer-resume",
            },
            {
                "sequence": 26,
                "event": "h2-slow-stream-second-stage-ack",
            },
            {"sequence": 27, "event": "h2-slow-stream-third-stage"},
            {"sequence": 28, "event": "h2-slow-stream-complete"},
            {"sequence": 29, "event": "h2-slow-stream-proof"},
            {"sequence": 30, "event": "h2-large-download-start"},
            {"sequence": 31, "event": "h2-large-download-complete"},
            {"sequence": 32, "event": "h1-cors"},
            {"sequence": 33, "event": "h1-wss-echo"},
            {"sequence": 34, "event": "tls-failure-tcp-connect"},
        ],
    }


def parsed_relay_ready() -> run_m5_wisp_smoke.RelayReady:
    return run_m5_wisp_smoke.parse_relay_ready_line(RELAY_READY_LINE)


def validate_passing_result(result: dict[str, object]) -> None:
    run_m5_wisp_smoke.validate_m5_result(
        result,
        expected_versions=VERSIONS,
        relay_ready=parsed_relay_ready(),
    )


class RelayReadinessTest(unittest.TestCase):
    def test_parses_fixed_loopback_readiness(self) -> None:
        ready = parsed_relay_ready()

        self.assertEqual(ready.wisp_endpoint, "ws://127.0.0.1:40123/wisp/")
        self.assertEqual(ready.https_url, "https://a.test:4443/m5/")
        self.assertEqual(
            ready.redirect_url, "https://a.test:4443/m5/redirect-cookie"
        )
        self.assertEqual(
            ready.plaintext_http_control_url,
            "http://a.test:4446/m5/plaintext-control",
        )
        self.assertEqual(
            ready.mixed_content_target_url,
            "http://a.test:4446/m5/mixed-content-target",
        )
        self.assertEqual(ready.http1_url, "https://a.test:4444/m5/cors-resource")
        self.assertEqual(
            ready.tls_failure_url,
            "https://a.test:4445/m5/tls-name-mismatch",
        )
        self.assertEqual(ready.transcript_url, "http://127.0.0.1:40123/status")

    def test_rejects_nonloopback_or_credentialed_wisp_endpoint(self) -> None:
        for endpoint in (
            "ws://example.test:40123/wisp/",
            "ws://user@127.0.0.1:40123/wisp/",
            "ws://127.0.0.1:40123/wisp/?token=secret",
            "ws://127.0.0.1:40123/wisp",
        ):
            with self.subTest(endpoint=endpoint):
                readiness = json.loads(RELAY_READY_LINE)
                readiness["wispEndpoint"] = endpoint
                with self.assertRaisesRegex(M0Error, "wispEndpoint"):
                    run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(readiness))

    def test_rejects_nonexact_or_query_bearing_https_fixture_url(self) -> None:
        for https_url in (
            "https://example.test:4443/m5/network",
            "http://a.test:4443/m5/network",
            "https://a.test:4443/not-m5",
            "https://a.test:4443/m5/network",
            "https://a.test:4443/m5/network?secret=1",
            "https://a.test:4443/m5/#",
            "https://@a.test:4443/m5/",
        ):
            with self.subTest(https_url=https_url):
                readiness = json.loads(RELAY_READY_LINE)
                readiness["httpsUrl"] = https_url
                with self.assertRaisesRegex(M0Error, "httpsUrl"):
                    run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(readiness))

    def test_m5_query_is_tokenized_and_carries_only_validated_values(self) -> None:
        ready = parsed_relay_ready()
        url = run_m5_wisp_smoke.m5_smoke_url(
            FakeServer(),
            "result-token",
            VERSIONS,
            relay_ready=ready,
            timeout_seconds=121.25,
        )
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, strict_parsing=True)

        self.assertEqual(parsed.path, "/__m3__/")
        self.assertEqual(query["case"], ["wisp_network_m5"])
        self.assertEqual(
            query["module"], ["/__m3__/artifacts/content_shell_wasm_m5_test.js"]
        )
        self.assertEqual(query["token"], ["result-token"])
        self.assertEqual(query["timeout_ms"], ["121250"])
        self.assertEqual(query["wisp_endpoint"], [ready.wisp_endpoint])
        self.assertEqual(query["m5_url"], [ready.redirect_url])
        self.assertEqual(
            query["m5_plaintext_http_control_url"],
            [ready.plaintext_http_control_url],
        )
        self.assertNotIn("m5_mixed_content_target_url", query)
        self.assertEqual(
            query["m5_tls_failure_url"], [ready.tls_failure_url]
        )

    def test_rejects_nonlocal_or_unscoped_transcript_url(self) -> None:
        for transcript_url in (
            "https://127.0.0.1:40123/status",
            "http://example.test:40123/status",
            "http://127.0.0.1:40123/not-status",
            "http://127.0.0.1:40123/status?token=secret",
        ):
            with self.subTest(transcript_url=transcript_url):
                readiness = json.loads(RELAY_READY_LINE)
                readiness["transcriptUrl"] = transcript_url
                with self.assertRaisesRegex(M0Error, "transcriptUrl"):
                    run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(readiness))

    def test_rejects_tls_failure_url_on_a_normal_fixture_port(self) -> None:
        ready = json.loads(RELAY_READY_LINE)
        ready["tlsFailureUrl"] = "https://a.test:4443/m5/tls-name-mismatch"

        with self.assertRaisesRegex(M0Error, "distinct fixture port"):
            run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(ready))

    def test_rejects_redirect_url_outside_the_h2_fixture_listener(self) -> None:
        ready = json.loads(RELAY_READY_LINE)
        ready["redirectUrl"] = "https://a.test:4444/m5/redirect-cookie"

        with self.assertRaisesRegex(M0Error, "H2 fixture port"):
            run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(ready))

    def test_rejects_nonexact_named_https_fixture_paths(self) -> None:
        for field, value in (
            ("redirectUrl", "https://a.test:4443/m5/not-redirect-cookie"),
            ("http1Url", "https://a.test:4444/m5/not-cors-resource"),
            (
                "tlsFailureUrl",
                "https://a.test:4445/m5/not-tls-name-mismatch",
            ),
        ):
            with self.subTest(field=field, value=value):
                readiness = json.loads(RELAY_READY_LINE)
                readiness[field] = value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.parse_relay_ready_line(
                        json.dumps(readiness)
                    )

    def test_rejects_nonexact_plaintext_control_or_mixed_target_url(self) -> None:
        for field, value in (
            (
                "plaintextHttpControlUrl",
                "https://a.test:4446/m5/plaintext-control",
            ),
            (
                "plaintextHttpControlUrl",
                "http://example.test:4446/m5/plaintext-control",
            ),
            (
                "plaintextHttpControlUrl",
                "http://a.test:4446/m5/plaintext-control/extra",
            ),
            (
                "plaintextHttpControlUrl",
                "http://a.test:4446/m5/plaintext-control?query=1",
            ),
            (
                "plaintextHttpControlUrl",
                "http://@a.test:4446/m5/plaintext-control",
            ),
            (
                "plaintextHttpControlUrl",
                "http://a.test:4446/m5/plaintext-control?",
            ),
            (
                "mixedContentTargetUrl",
                "https://a.test:4446/m5/mixed-content-target",
            ),
            (
                "mixedContentTargetUrl",
                "http://example.test:4446/m5/mixed-content-target",
            ),
            (
                "mixedContentTargetUrl",
                "http://a.test:4446/m5/plaintext-control",
            ),
            (
                "mixedContentTargetUrl",
                "http://a.test:4446/m5/mixed-content-target?query=1",
            ),
            (
                "mixedContentTargetUrl",
                "http://a.test:4446/m5/mixed-content-target#",
            ),
        ):
            with self.subTest(field=field, value=value):
                readiness = json.loads(RELAY_READY_LINE)
                readiness[field] = value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.parse_relay_ready_line(
                        json.dumps(readiness)
                    )

        readiness = json.loads(RELAY_READY_LINE)
        readiness["mixedContentTargetUrl"] = (
            "http://a.test:4447/m5/mixed-content-target"
        )
        with self.assertRaisesRegex(M0Error, "plaintext control port"):
            run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(readiness))

        readiness = json.loads(RELAY_READY_LINE)
        readiness["plaintextHttpControlUrl"] = (
            "http://a.test:4443/m5/plaintext-control"
        )
        readiness["mixedContentTargetUrl"] = (
            "http://a.test:4443/m5/mixed-content-target"
        )
        with self.assertRaisesRegex(M0Error, "distinct fixture port"):
            run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(readiness))

    def test_m5_query_revalidates_plaintext_control_and_port_layout(self) -> None:
        ready = parsed_relay_ready()
        invalid_control = replace(
            ready,
            plaintext_http_control_url="http://a.test:4446/m5/not-plaintext-control",
        )
        with self.assertRaisesRegex(M0Error, "plaintextHttpControlUrl"):
            run_m5_wisp_smoke.m5_smoke_url(
                FakeServer(), "result-token", VERSIONS, relay_ready=invalid_control
            )

        invalid_target = replace(
            ready,
            mixed_content_target_url="http://a.test:4447/m5/mixed-content-target",
        )
        with self.assertRaisesRegex(M0Error, "plaintext control port"):
            run_m5_wisp_smoke.m5_smoke_url(
                FakeServer(), "result-token", VERSIONS, relay_ready=invalid_target
            )

        colliding_control = replace(
            ready,
            plaintext_http_control_url="http://a.test:4443/m5/plaintext-control",
            mixed_content_target_url="http://a.test:4443/m5/mixed-content-target",
        )
        with self.assertRaisesRegex(M0Error, "distinct fixture port"):
            run_m5_wisp_smoke.m5_smoke_url(
                FakeServer(), "result-token", VERSIONS, relay_ready=colliding_control
            )

        invalid_tls_path = replace(
            ready,
            tls_failure_url="https://a.test:4445/m5/not-tls-name-mismatch",
        )
        with self.assertRaisesRegex(M0Error, "tlsFailureUrl"):
            run_m5_wisp_smoke.m5_smoke_url(
                FakeServer(), "result-token", VERSIONS, relay_ready=invalid_tls_path
            )


class M5ResultValidationTest(unittest.TestCase):
    def test_accepts_complete_chromium_network_evidence(self) -> None:
        validate_passing_result(passing_result())

    def test_rejects_missing_page_network_evidence(self) -> None:
        for field in (
            "h2Fetch",
            "corsFetch",
            "webSocketEcho",
            "redirected",
            "cacheStored",
            "cacheRevalidated",
            "cancelStreamStarted",
            "cancelStreamReceivedFirstChunk",
            "cancelStreamAborted",
            "cancelStreamProof",
            "slowStreamStarted",
            "slowStreamFirstStage",
            "slowStreamSecondStage",
            "slowStreamThirdStage",
            "slowStreamComplete",
            "slowStreamProof",
            "slowStreamConsumerPauseStarted",
            "slowStreamConsumerBurstRead",
            "slowStreamConsumerResume",
            "largeDownloadStarted",
            "largeDownloadContentDisposition",
            "largeDownloadComplete",
            "cspConnectSrcBlocked",
            "activeMixedContentBlocked",
            "activeMixedContentCspAllowed",
        ):
            with self.subTest(field=field):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe[field] = False
                with self.assertRaisesRegex(M0Error, field):
                    validate_passing_result(result)

    def test_rejects_invalid_slow_stream_page_timing_evidence(self) -> None:
        for field, invalid_value in (
            ("slowStreamElapsedMs", -1),
            ("slowStreamElapsedMs", 0),
            ("slowStreamElapsedMs", 74),
            ("slowStreamElapsedMs", True),
            ("slowStreamElapsedMs", None),
            ("slowStreamFirstToSecondStageDelayMs", -1),
            ("slowStreamFirstToSecondStageDelayMs", 0),
            ("slowStreamFirstToSecondStageDelayMs", 74),
            ("slowStreamFirstToSecondStageDelayMs", True),
            ("slowStreamSecondToThirdStageDelayMs", -1),
            ("slowStreamSecondToThirdStageDelayMs", 0),
            ("slowStreamSecondToThirdStageDelayMs", 74),
            ("slowStreamSecondToThirdStageDelayMs", True),
            ("slowStreamConsumerPauseElapsedMs", -1),
            ("slowStreamConsumerPauseElapsedMs", 0),
            ("slowStreamConsumerPauseElapsedMs", 74),
            ("slowStreamConsumerPauseElapsedMs", True),
            ("slowStreamConsumerPauseTimerTicks", -1),
            ("slowStreamConsumerPauseTimerTicks", 0),
            ("slowStreamConsumerPauseTimerTicks", 1),
            ("slowStreamConsumerPauseTimerTicks", True),
            ("slowStreamTimerTicksWhileWaiting", -1),
            ("slowStreamTimerTicksWhileWaiting", 0),
            ("slowStreamTimerTicksWhileWaiting", 1),
            ("slowStreamTimerTicksWhileWaiting", True),
            ("slowStreamTimerTicksWhileWaiting", None),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe[field] = invalid_value
                with self.assertRaisesRegex(M0Error, field):
                    validate_passing_result(result)

    def test_rejects_invalid_slow_stream_host_heartbeat(self) -> None:
        for field, invalid_value in (
            ("anchor", "m5-plaintext-http-control-navigation-committed"),
            ("elapsedMs", 74),
            ("elapsedMs", float("nan")),
            ("timerDelta", 1),
            ("timerDelta", True),
            ("animationFrameDelta", 1),
            ("animationFrameDelta", True),
            ("maxTimerGapMs", -1),
            ("maxTimerGapMs", 251),
            ("maxTimerGapMs", True),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                result = passing_result()
                heartbeat = result["slowStreamHeartbeat"]
                assert isinstance(heartbeat, dict)
                heartbeat[field] = invalid_value
                with self.assertRaisesRegex(M0Error, "slow-stream host heartbeat"):
                    validate_passing_result(result)

    def test_rejects_invalid_large_download_page_evidence(self) -> None:
        for field, invalid_value in (
            ("largeDownloadBytes", 0),
            ("largeDownloadBytes", 512 * 1024 - 1),
            ("largeDownloadBytes", 512 * 1024 + 1),
            ("largeDownloadBytes", True),
            ("largeDownloadReaderChunks", 0),
            ("largeDownloadReaderChunks", -1),
            ("largeDownloadReaderChunks", True),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe[field] = invalid_value
                with self.assertRaisesRegex(M0Error, field):
                    validate_passing_result(result)

    def test_rejects_invalid_cancel_stream_page_evidence(self) -> None:
        for invalid_value in ("", "TypeError", None):
            with self.subTest(
                field="cancelStreamErrorName", invalid_value=invalid_value
            ):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe["cancelStreamErrorName"] = invalid_value
                with self.assertRaisesRegex(M0Error, "cancelStreamErrorName"):
                    validate_passing_result(result)

    def test_rejects_invalid_plaintext_control_evidence(self) -> None:
        result = passing_result()
        navigation_result = result["plaintextHttpControlNavigationResult"]
        assert isinstance(navigation_result, dict)
        navigation_result["scheme"] = "https"
        with self.assertRaisesRegex(
            M0Error, "plaintext HTTP control navigation result"
        ):
            validate_passing_result(result)

        result = passing_result()
        control_readiness = result["plaintextHttpControlReadiness"]
        assert isinstance(control_readiness, dict)
        control_readiness["navigation"] = {"committed": True, "scheme": "https"}
        with self.assertRaisesRegex(M0Error, "HTTP navigation"):
            validate_passing_result(result)

        for field, invalid_value in (
            ("phase", "https-fixture"),
            ("plaintextHttpControlDocument", False),
            ("plaintextHttpControlProof", False),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                result = passing_result()
                control_readiness = result["plaintextHttpControlReadiness"]
                assert isinstance(control_readiness, dict)
                page_probe = control_readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe[field] = invalid_value
                with self.assertRaisesRegex(M0Error, field):
                    validate_passing_result(result)

        result = passing_result()
        control_readiness = result["plaintextHttpControlReadiness"]
        assert isinstance(control_readiness, dict)
        control_readiness["heartbeat"] = {"anchor": "m5-https-navigation-committed"}
        with self.assertRaisesRegex(M0Error, "control heartbeat"):
            validate_passing_result(result)

    def test_allows_control_before_a_new_visually_nonempty_paint(self) -> None:
        # The initial shell frame is already proven before the HTTP control
        # navigation. Content is not required to emit a second FVN paint for
        # that intermediate document, so transport proof must not depend on
        # this observer callback.
        result = passing_result()
        control_readiness = result["plaintextHttpControlReadiness"]
        assert isinstance(control_readiness, dict)
        control_readiness["baseReady"] = False
        control_readiness["firstVisuallyNonEmptyPaint"] = False
        validate_passing_result(result)

    def test_rejects_invalid_mixed_content_proof_or_host_phase_order(self) -> None:
        for field, invalid_value in (
            ("phase", "plaintext-http-control"),
            ("activeMixedContentErrorName", "SecurityError"),
            (
                "activeMixedContentTargetUrl",
                "http://a.test:4446/m5/not-the-mixed-content-target",
            ),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe[field] = invalid_value
                with self.assertRaisesRegex(M0Error, field):
                    validate_passing_result(result)

        result = passing_result()
        logs = result["logs"]
        assert isinstance(logs, dict)
        host_logs = logs["host"]
        assert isinstance(host_logs, list)
        host_logs.remove("navigation:requested:m5-plaintext-http-control")
        with self.assertRaisesRegex(
            M0Error, "navigation:requested:m5-plaintext-http-control"
        ):
            validate_passing_result(result)

        for marker in (
            "navigation:requested:m5-plaintext-http-control",
            "navigation:committed:m5-plaintext-http-control",
            "navigation:requested:m5-https",
            "navigation:requested:m5-https-tls-failure",
            "navigation:failed:m5-https:-200",
            "shutdown:complete",
        ):
            with self.subTest(duplicate_marker=marker):
                result = passing_result()
                logs = result["logs"]
                assert isinstance(logs, dict)
                host_logs = logs["host"]
                assert isinstance(host_logs, list)
                host_logs.append(marker)
                with self.assertRaisesRegex(M0Error, marker):
                    validate_passing_result(result)

        result = passing_result()
        logs = result["logs"]
        assert isinstance(logs, dict)
        host_logs = logs["host"]
        assert isinstance(host_logs, list)
        requested_index = host_logs.index(
            "navigation:requested:m5-plaintext-http-control"
        )
        https_index = host_logs.index("navigation:requested:m5-https")
        host_logs[requested_index], host_logs[https_index] = (
            host_logs[https_index],
            host_logs[requested_index],
        )
        with self.assertRaisesRegex(M0Error, "M5 phase order"):
            validate_passing_result(result)

    def test_rejects_data_navigation_or_unclean_shutdown(self) -> None:
        result = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["navigation"] = {"committed": True, "scheme": "data"}
        with self.assertRaisesRegex(M0Error, "HTTPS"):
            validate_passing_result(result)

    def test_rejects_unexpected_native_tls_failure(self) -> None:
        result = passing_result()
        tls_failure_readiness = result["tlsFailureReadiness"]
        assert isinstance(tls_failure_readiness, dict)
        navigation = tls_failure_readiness["navigation"]
        assert isinstance(navigation, dict)
        navigation["committed"] = True
        with self.assertRaisesRegex(M0Error, "TLS-failure navigation committed"):
            validate_passing_result(result)

        result = passing_result()
        tls_failure_readiness = result["tlsFailureReadiness"]
        assert isinstance(tls_failure_readiness, dict)
        navigation = tls_failure_readiness["navigation"]
        assert isinstance(navigation, dict)
        navigation["netError"] = -201
        with self.assertRaisesRegex(M0Error, "TLS-failure navigation netError"):
            validate_passing_result(result)

        result = passing_result()
        shutdown = result["shutdown"]
        assert isinstance(shutdown, dict)
        shutdown["runtimeExitCode"] = 1
        with self.assertRaisesRegex(M0Error, "runtimeExitCode"):
            validate_passing_result(result)


class M5RelayTranscriptValidationTest(unittest.TestCase):
    def test_accepts_the_bounded_inner_network_transcript(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        run_m5_wisp_smoke.validate_relay_transcript(
            passing_relay_status(), relay_ready=relay_ready
        )

    def test_rejects_unexpected_destination_and_udp(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        status = passing_relay_status()
        destinations = status["requestedDestinations"]
        assert isinstance(destinations, list)
        destinations[0] = {"hostname": "example.test", "port": 4443}
        with self.assertRaisesRegex(M0Error, "non-fixture WISP hostname"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        status["udpPackets"] = 1
        with self.assertRaisesRegex(M0Error, "UDP"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

    def test_rejects_missing_tls_mismatch_or_an_http_stream(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        status = passing_relay_status()
        status["tlsMismatchTcpConnections"] = 0
        with self.assertRaisesRegex(M0Error, "TLS-mismatch TCP"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        status["tlsMismatchHttpStreams"] = 1
        with self.assertRaisesRegex(M0Error, "HTTP stream after TLS mismatch"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        destinations = status["requestedDestinations"]
        assert isinstance(destinations, list)
        destinations[-1] = {"hostname": "a.test", "port": 4444}
        with self.assertRaisesRegex(M0Error, "all fixed M5 destination streams"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

    def test_rejects_missing_redirect_counter_or_transcript_event(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        status = passing_relay_status()
        status["redirectRequests"] = 0
        with self.assertRaisesRegex(M0Error, "redirect request"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        status["redirectCookieValidations"] = 0
        with self.assertRaisesRegex(M0Error, "redirect cookie"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for event_name in (
            "h2-redirect",
            "h2-redirect-cookie",
            "h2-page-cookie",
        ):
            with self.subTest(event_name=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                status["transcript"] = [
                    entry
                    for entry in transcript
                    if entry.get("event") != event_name
                ]
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        redirect_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "h2-redirect-cookie"
        )
        page_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "h2-page-cookie"
        )
        transcript[redirect_index], transcript[page_index] = (
            transcript[page_index],
            transcript[redirect_index],
        )
        with self.assertRaisesRegex(M0Error, "before redirect cookie"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

    def test_rejects_invalid_cache_revalidation_evidence(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        for field, actual_value in (
            ("cacheStore200s", 0),
            ("cacheStore200s", 2),
            ("cacheConditionalRequests", 0),
            ("cacheConditionalRequests", 2),
            ("cacheNotModified304s", 0),
            ("cacheNotModified304s", 2),
            ("cacheUnexpectedRequests", 1),
        ):
            with self.subTest(field=field, actual_value=actual_value):
                status = passing_relay_status()
                status[field] = actual_value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-cache-store-200",
            "h2-cache-revalidate-304",
        ):
            with self.subTest(event_name=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                status["transcript"] = [
                    entry
                    for entry in transcript
                    if entry.get("event") != event_name
                ]
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        store_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "h2-cache-store-200"
        )
        revalidation_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "h2-cache-revalidate-304"
        )
        transcript[store_index], transcript[revalidation_index] = (
            transcript[revalidation_index],
            transcript[store_index],
        )
        with self.assertRaisesRegex(M0Error, "before storing"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

    def test_rejects_invalid_plaintext_control_and_mixed_content_evidence(
        self,
    ) -> None:
        relay_ready = parsed_relay_ready()

        status = passing_relay_status()
        status["plaintextHttpControlPhase"] = "control"
        with self.assertRaisesRegex(M0Error, "plaintext HTTP control phase"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for field, actual_value, error in (
            (
                "plaintextHttpControlTcpConnections",
                0,
                "plaintext HTTP control TCP",
            ),
            ("plaintextHttpControlRequests", 0, "plaintextHttpControlRequests"),
            ("plaintextHttpControlRequests", 2, "plaintextHttpControlRequests"),
            ("plaintextHttpControlProofs", 0, "plaintextHttpControlProofs"),
            ("plaintextHttpControlProofs", 2, "plaintextHttpControlProofs"),
            (
                "mixedContentTargetPostControlWispConnects",
                1,
                "mixedContentTargetPostControlWispConnects",
            ),
            (
                "mixedContentTargetPostControlTcpConnections",
                1,
                "mixedContentTargetPostControlTcpConnections",
            ),
            (
                "mixedContentTargetPostControlRequests",
                1,
                "mixedContentTargetPostControlRequests",
            ),
            ("mixedContentProofs", 0, "mixedContentProofs"),
            ("mixedContentProofs", 2, "mixedContentProofs"),
        ):
            with self.subTest(field=field, actual_value=actual_value):
                status = passing_relay_status()
                status[field] = actual_value
                with self.assertRaisesRegex(M0Error, error):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "plaintext-http-control-tcp-connect",
            "h1-plaintext-http-control",
            "h1-plaintext-http-control-proof",
            "plaintext-http-control-phase-complete",
            "h2-mixed-content-proof",
        ):
            with self.subTest(missing_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                status["transcript"] = [
                    entry
                    for entry in transcript
                    if entry.get("event") != event_name
                ]
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h1-plaintext-http-control",
            "h1-plaintext-http-control-proof",
            "plaintext-http-control-phase-complete",
            "h2-mixed-content-proof",
        ):
            with self.subTest(duplicate_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {"sequence": len(transcript) + 1, "event": event_name}
                )
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for first_event, second_event, error in (
            (
                "h1-plaintext-http-control-proof",
                "plaintext-http-control-phase-complete",
                "plaintext HTTP control did not complete before HTTPS navigation",
            ),
            (
                "h2-csp-connect-src-proof",
                "h2-mixed-content-proof",
                "cancellation proof events are not between active mixed-content "
                "proof and CORS",
            ),
            (
                "h2-mixed-content-proof",
                "h1-cors",
                "cancellation proof events are not between active mixed-content "
                "proof and CORS",
            ),
        ):
            with self.subTest(first_event=first_event, second_event=second_event):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                first_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == first_event
                )
                second_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == second_event
                )
                transcript[first_index], transcript[second_index] = (
                    transcript[second_index],
                    transcript[first_index],
                )
                with self.assertRaisesRegex(M0Error, error):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "mixed-content-target-post-control-wisp-connect",
            "mixed-content-target-post-control-tcp-connect",
            "h1-mixed-content-target-post-control-request",
        ):
            with self.subTest(forbidden_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {"sequence": len(transcript) + 1, "event": event_name}
                )
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

    def test_rejects_invalid_cancel_stream_evidence(self) -> None:
        relay_ready = parsed_relay_ready()

        status = passing_relay_status()
        status["cancelStreamPhase"] = "streaming"
        with self.assertRaisesRegex(M0Error, "cancel stream phase"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for field, actual_value in (
            ("cancelStreamRequests", 0),
            ("cancelStreamRequests", 2),
            ("cancelStreamFirstChunks", 0),
            ("cancelStreamFirstChunks", 2),
            ("cancelStreamCancelResets", 0),
            ("cancelStreamCancelResets", 2),
            ("cancelStreamProofs", 0),
            ("cancelStreamProofs", 2),
            ("cancelStreamProofSessionMismatches", 1),
            ("cancelStreamProofTimeouts", 1),
            ("cancelStreamUnexpectedResets", 1),
        ):
            with self.subTest(field=field, actual_value=actual_value):
                status = passing_relay_status()
                status[field] = actual_value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for invalid_rst_code in (None, 0, 7, "8"):
            with self.subTest(invalid_rst_code=invalid_rst_code):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                reset_entry = next(
                    entry
                    for entry in transcript
                    if entry.get("event") == "h2-cancel-stream-cancel-reset"
                )
                reset_entry["rstCode"] = invalid_rst_code
                with self.assertRaisesRegex(M0Error, "NGHTTP2_CANCEL"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-cancel-stream-start",
            "h2-cancel-stream-cancel-reset",
            "h2-cancel-stream-proof",
        ):
            with self.subTest(missing_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                status["transcript"] = [
                    entry
                    for entry in transcript
                    if entry.get("event") != event_name
                ]
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-cancel-stream-start",
            "h2-cancel-stream-cancel-reset",
            "h2-cancel-stream-proof",
        ):
            with self.subTest(duplicate_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {"sequence": len(transcript) + 1, "event": event_name}
                )
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for first_event, second_event in (
            ("h2-mixed-content-proof", "h2-cancel-stream-start"),
            ("h2-cancel-stream-start", "h2-cancel-stream-cancel-reset"),
            ("h2-cancel-stream-cancel-reset", "h2-cancel-stream-proof"),
            ("h2-cancel-stream-proof", "h1-cors"),
        ):
            with self.subTest(first_event=first_event, second_event=second_event):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                first_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == first_event
                )
                second_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == second_event
                )
                transcript[first_index], transcript[second_index] = (
                    transcript[second_index],
                    transcript[first_index],
                )
                with self.assertRaisesRegex(
                    M0Error,
                    "cancellation proof events are not between active mixed-content "
                    "proof and CORS",
                ):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-cancel-stream-rejected",
            "h2-cancel-stream-unexpected-reset",
            "h2-cancel-stream-proof-rejected",
            "h2-cancel-stream-proof-session-mismatch",
            "h2-cancel-stream-proof-timeout",
        ):
            with self.subTest(forbidden_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {"sequence": len(transcript) + 1, "event": event_name}
                )
                with self.assertRaisesRegex(
                    M0Error, "cancellation failure event"
                ):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

    def test_rejects_invalid_slow_stream_evidence(self) -> None:
        relay_ready = parsed_relay_ready()

        status = passing_relay_status()
        status["slowStreamPhase"] = "second-stage"
        with self.assertRaisesRegex(M0Error, "slow stream phase"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for field, actual_value in (
            ("slowStreamRequests", 0),
            ("slowStreamRequests", 2),
            ("slowStreamFirstStages", 0),
            ("slowStreamFirstStages", 2),
            ("slowStreamSecondStages", 0),
            ("slowStreamSecondStages", 2),
            ("slowStreamThirdStages", 0),
            ("slowStreamThirdStages", 2),
            ("slowStreamCompletedStreams", 0),
            ("slowStreamCompletedStreams", 2),
            ("slowStreamConsumerBurstBytes", 0),
            ("slowStreamConsumerBurstBytes", 64 * 1024 - 1),
            ("slowStreamConsumerBurstBytes", 64 * 1024 + 1),
            ("slowStreamConsumerBurstWrites", 0),
            ("slowStreamConsumerBurstWrites", 2),
            ("slowStreamConsumerPauseReadyRequests", 0),
            ("slowStreamConsumerPauseReadyRequests", 2),
            ("slowStreamConsumerResumes", 0),
            ("slowStreamConsumerResumes", 2),
            ("slowStreamFirstStageAcks", 0),
            ("slowStreamFirstStageAcks", 2),
            ("slowStreamSecondStageAcks", 0),
            ("slowStreamSecondStageAcks", 2),
            ("slowStreamProofs", 0),
            ("slowStreamProofs", 2),
            ("slowStreamSessionMismatches", 1),
            ("slowStreamStageAckTimeouts", 1),
            ("slowStreamUnexpectedCloses", 1),
            ("slowStreamStageDelaySchedules", 0),
            ("slowStreamStageDelaySchedules", 3),
            ("slowStreamStageDelayMs", 74),
            ("slowStreamStageDelayMs", True),
        ):
            with self.subTest(field=field, actual_value=actual_value):
                status = passing_relay_status()
                status[field] = actual_value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for invalid_bytes in (None, 0, 64 * 1024 - 1, 64 * 1024 + 1, "65536"):
            with self.subTest(invalid_bytes=invalid_bytes):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                burst_entry = next(
                    entry
                    for entry in transcript
                    if entry.get("event") == "h2-slow-stream-consumer-burst"
                )
                burst_entry["bytes"] = invalid_bytes
                with self.assertRaisesRegex(M0Error, "bounded payload size"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for invalid_backpressure in (None, False, "true"):
            with self.subTest(invalid_backpressure=invalid_backpressure):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                burst_entry = next(
                    entry
                    for entry in transcript
                    if entry.get("event") == "h2-slow-stream-consumer-burst"
                )
                burst_entry["backpressured"] = invalid_backpressure
                with self.assertRaisesRegex(M0Error, "H2 write backpressure"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-slow-stream-start",
            "h2-slow-stream-first-stage",
            "h2-slow-stream-first-stage-ack",
            "h2-slow-stream-second-stage",
            "h2-slow-stream-consumer-pause-ready",
            "h2-slow-stream-consumer-burst",
            "h2-slow-stream-consumer-resume",
            "h2-slow-stream-second-stage-ack",
            "h2-slow-stream-third-stage",
            "h2-slow-stream-complete",
            "h2-slow-stream-proof",
        ):
            with self.subTest(missing_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                status["transcript"] = [
                    entry
                    for entry in transcript
                    if entry.get("event") != event_name
                ]
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-slow-stream-start",
            "h2-slow-stream-first-stage",
            "h2-slow-stream-first-stage-ack",
            "h2-slow-stream-second-stage",
            "h2-slow-stream-consumer-pause-ready",
            "h2-slow-stream-consumer-burst",
            "h2-slow-stream-consumer-resume",
            "h2-slow-stream-second-stage-ack",
            "h2-slow-stream-third-stage",
            "h2-slow-stream-complete",
            "h2-slow-stream-proof",
        ):
            with self.subTest(duplicate_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {"sequence": len(transcript) + 1, "event": event_name}
                )
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for first_event, second_event in (
            ("h2-cancel-stream-proof", "h2-slow-stream-start"),
            ("h2-slow-stream-start", "h2-slow-stream-first-stage"),
            ("h2-slow-stream-first-stage", "h2-slow-stream-first-stage-ack"),
            (
                "h2-slow-stream-first-stage-ack",
                "h2-slow-stream-second-stage",
            ),
            (
                "h2-slow-stream-second-stage",
                "h2-slow-stream-consumer-pause-ready",
            ),
            (
                "h2-slow-stream-consumer-pause-ready",
                "h2-slow-stream-consumer-burst",
            ),
            (
                "h2-slow-stream-consumer-burst",
                "h2-slow-stream-consumer-resume",
            ),
            (
                "h2-slow-stream-consumer-resume",
                "h2-slow-stream-second-stage-ack",
            ),
            (
                "h2-slow-stream-second-stage-ack",
                "h2-slow-stream-third-stage",
            ),
            ("h2-slow-stream-third-stage", "h2-slow-stream-complete"),
            ("h2-slow-stream-complete", "h2-slow-stream-proof"),
        ):
            with self.subTest(first_event=first_event, second_event=second_event):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                first_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == first_event
                )
                second_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == second_event
                )
                transcript[first_index], transcript[second_index] = (
                    transcript[second_index],
                    transcript[first_index],
                )
                with self.assertRaisesRegex(
                    M0Error,
                    "slow stream stage events are not between cancellation proof "
                    "and CORS",
                ):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-slow-stream-rejected",
            "h2-slow-stream-unexpected-close",
            "h2-slow-stream-stage-ack-rejected",
            "h2-slow-stream-stage-ack-session-mismatch",
            "h2-slow-stream-stage-ack-timeout",
            "h2-slow-stream-consumer-pause-ready-rejected",
            "h2-slow-stream-consumer-pause-ready-session-mismatch",
            "h2-slow-stream-consumer-resume-rejected",
            "h2-slow-stream-consumer-resume-session-mismatch",
            "h2-slow-stream-proof-rejected",
            "h2-slow-stream-proof-session-mismatch",
            "h2-slow-stream-proof-timeout",
        ):
            with self.subTest(forbidden_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {"sequence": len(transcript) + 1, "event": event_name}
                )
                with self.assertRaisesRegex(
                    M0Error, "slow-stream failure event"
                ):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

    def test_rejects_invalid_large_download_evidence(self) -> None:
        relay_ready = parsed_relay_ready()

        status = passing_relay_status()
        status["largeDownloadPhase"] = "streaming"
        with self.assertRaisesRegex(M0Error, "large download phase"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for field, actual_value in (
            ("largeDownloadBytes", 0),
            ("largeDownloadBytes", 512 * 1024 - 1),
            ("largeDownloadBytes", 512 * 1024 + 1),
            ("largeDownloadChunks", 0),
            ("largeDownloadChunks", 31),
            ("largeDownloadChunks", 33),
            ("largeDownloadCompletions", 0),
            ("largeDownloadCompletions", 2),
            ("largeDownloadRequests", 0),
            ("largeDownloadRequests", 2),
            ("largeDownloadUnexpectedCloses", 1),
            ("largeDownloadBackpressureEvents", 0),
            ("largeDownloadBackpressureEvents", 33),
        ):
            with self.subTest(field=field, actual_value=actual_value):
                status = passing_relay_status()
                status[field] = actual_value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-large-download-start",
            "h2-large-download-complete",
        ):
            with self.subTest(missing_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                status["transcript"] = [
                    entry
                    for entry in transcript
                    if entry.get("event") != event_name
                ]
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for first_event, second_event in (
            ("h2-slow-stream-proof", "h2-large-download-start"),
            ("h2-large-download-start", "h2-large-download-complete"),
            ("h2-large-download-complete", "h1-cors"),
        ):
            with self.subTest(first_event=first_event, second_event=second_event):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                first_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == first_event
                )
                second_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == second_event
                )
                transcript[first_index], transcript[second_index] = (
                    transcript[second_index],
                    transcript[first_index],
                )
                with self.assertRaisesRegex(M0Error, "large download events"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-large-download-rejected",
            "h2-large-download-unexpected-close",
        ):
            with self.subTest(forbidden_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {"sequence": len(transcript) + 1, "event": event_name}
                )
                with self.assertRaisesRegex(M0Error, "large-download failure"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

    def test_rejects_invalid_csp_connect_src_evidence(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        for field, actual_value in (
            ("cspConnectSrcProofs", 0),
            ("cspConnectSrcProofs", 2),
            ("cspConnectSrcTargetTcpConnections", 1),
            ("cspConnectSrcTargetRequests", 1),
        ):
            with self.subTest(field=field, actual_value=actual_value):
                status = passing_relay_status()
                status[field] = actual_value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        status["transcript"] = [
            entry
            for entry in transcript
            if entry.get("event") != "h2-csp-connect-src-proof"
        ]
        with self.assertRaisesRegex(M0Error, "h2-csp-connect-src-proof"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        transcript.append(
            {
                "sequence": len(transcript) + 1,
                "event": "h2-csp-connect-src-proof",
            }
        )
        with self.assertRaisesRegex(M0Error, "h2-csp-connect-src-proof"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for first_event, second_event in (
            ("h2-cache-revalidate-304", "h2-csp-connect-src-proof"),
            ("h2-csp-connect-src-proof", "h1-cors"),
        ):
            with self.subTest(
                first_event=first_event, second_event=second_event
            ):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                first_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == first_event
                )
                second_index = next(
                    index
                    for index, entry in enumerate(transcript)
                    if entry.get("event") == second_event
                )
                transcript[first_index], transcript[second_index] = (
                    transcript[second_index],
                    transcript[first_index],
                )
                with self.assertRaisesRegex(
                    M0Error, "between cache revalidation and CORS"
                ):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "csp-connect-src-target-tcp-connect",
            "h1-csp-connect-src-target-request",
        ):
            with self.subTest(event_name=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {
                        "sequence": len(transcript) + 1,
                        "event": event_name,
                    }
                )
                with self.assertRaisesRegex(M0Error, event_name):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )


class M5ResultEndpointTest(unittest.TestCase):
    def test_m3_host_allows_only_the_new_m5_result_case(self) -> None:
        self.assertIn(
            m3_content_server.M5_WISP_CASE,
            m3_content_server.M3_RESULT_CASES,
        )
        self.assertTrue(
            m3_content_server.is_supported_result_case("wisp_network_m5")
        )
        self.assertFalse(
            m3_content_server.is_supported_result_case("untrusted_case")
        )


class M5ArtifactTrustBoundaryTest(unittest.TestCase):
    def test_rejects_only_actual_private_key_pem_headers(self) -> None:
        module_name = "content_shell_wasm_m5_test"
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            artifact = out_dir / f"{module_name}.wasm"
            artifact.write_bytes(
                b"generic parser token: PRIVATE KEY; certificate DER follows"
            )
            run_m5_wisp_smoke.verify_no_private_key_pem_artifacts(
                out_dir, module_name
            )

            artifact.write_bytes(
                b"prefix\n-----BEGIN EC PRIVATE KEY-----\nsuffix"
            )
            with self.assertRaisesRegex(M0Error, "private-key header"):
                run_m5_wisp_smoke.verify_no_private_key_pem_artifacts(
                    out_dir, module_name
                )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the controlled M5 WISP browser runner."""

from __future__ import annotations

import contextlib
import copy
from dataclasses import replace
import hashlib
import http.client
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from unittest import mock
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
        "devtoolsNetworkEnabled": {
            "protocol": 1,
            "state": "enabled",
            "networkEnabled": True,
            "events": [],
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
            "devtoolsNetwork": {
                "protocol": 1,
                "state": "complete",
                "networkEnabled": True,
                "redirectRequest": True,
                "redirectIntermediateRequest": True,
                "redirectHopCount": 2,
                "finalRequest": True,
                "responseReceived": True,
                "loadingFinished": True,
                "requestIdCorrelated": True,
                "responseStatus": 200,
                "responseProtocol": "h2",
                "localGatewayBlockedRequest": True,
                "localGatewayBlockedLoadingFailed": True,
                "localGatewayBlockedRequestIdCorrelated": True,
                "localGatewayBlockedByAdministrator": True,
                "reconnectRequest": True,
                "reconnectLoadingFailed": True,
                "reconnectRequestIdCorrelated": True,
                "reconnectInternetDisconnected": True,
                "events": [
                    "Network.requestWillBeSent:redirect",
                    "Network.requestWillBeSent:redirect-intermediate",
                    "Network.requestWillBeSent:final",
                    "Network.responseReceived:final",
                    "Network.loadingFinished:final",
                    "Network.requestWillBeSent:reconnect",
                    "Network.loadingFailed:reconnect",
                ],
            },
            "m5Download": {
                "protocol": 1,
                "state": "complete",
                "singleDownload": True,
                "navigationSource": True,
                "responseStatusMatched": True,
                "contentDispositionMatched": True,
                "mimeTypeMatched": True,
                "allDataSaved": True,
                "targetPathDetermined": True,
                "targetDirectoryMatched": True,
                "interruptReasonNone": True,
                "totalBytes": 512 * 1024,
                "receivedBytes": 512 * 1024,
                "filePatternVerified": True,
            },
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
                "corsDeniedRequestStarted": True,
                "corsDeniedResponseBlocked": True,
                "corsFetch": True,
                "webSocketEcho": True,
                "altSvcH3Advertised": True,
                "redirectHopCount": 2,
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
                "multiplexRequestsStarted": True,
                "multiplexH2Response": True,
                "multiplexH1Response": True,
                "multiplexComplete": True,
                "largeDownloadNavigationRequested": True,
                "largeDownloadNativeComplete": True,
                "reconnectStreamStarted": True,
                "reconnectFirstChunkReceived": True,
                "reconnectFirstChunkAck": True,
                "reconnectDisconnectRequested": True,
                "reconnectStreamFailed": True,
                "reconnectStreamErrorName": "TypeError",
                "reconnectRecovered": True,
                "reconnectRecoveryProtocol": "h2",
                "cspConnectSrcBlocked": True,
                "phase": "https-fixture",
                "activeMixedContentBlocked": True,
                "activeMixedContentTargetUrl": (
                    "http://a.test:4446/m5/mixed-content-target"
                ),
                "activeMixedContentErrorName": "TypeError",
                "activeMixedContentCspAllowed": True,
                "localGatewayMappedRequestStarted": True,
                "localGatewayMappedResponse": True,
                "localGatewayBlockedRequestStarted": True,
                "localGatewayBlocked": True,
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
                "m5:devtools-network:enabled",
                "navigation:requested:m5-plaintext-http-control",
                "navigation:committed:m5-plaintext-http-control",
                "navigation:requested:m5-https",
                "m5:download-manager:complete",
                "m5:devtools-network:complete",
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
        "activeWispSessions": 1,
        "wispSessions": 2,
        "rejectedDestinations": 1,
        "localGateway443StreamsOpened": 1,
        "localGateway443Requests": 1,
        "localGatewayBlockedPortAttempts": 1,
        "udpPackets": 0,
        "relayErrors": 0,
        "corsDeniedRequests": 1,
        "corsRequests": 1,
        "webSocketEchoes": 1,
        "redirectRequests": 1,
        "redirectIntermediateRequests": 1,
        "redirectIntermediateCookieValidations": 1,
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
        "multiplexPhase": "complete",
        "multiplexBarrierReleases": 1,
        "multiplexBarrierTimeouts": 0,
        "multiplexBothStreamsOpen": True,
        "multiplexCorrelationFailures": 0,
        "multiplexDistinctWispStreamCount": 2,
        "multiplexH1Requests": 1,
        "multiplexH2Requests": 1,
        "multiplexResponses": 2,
        "multiplexSharedCarrier": True,
        "multiplexUnexpectedCloses": 0,
        "reconnectPhase": "recovered",
        "reconnectDisconnectRequests": 1,
        "reconnectFirstChunkAcks": 1,
        "reconnectFirstChunks": 1,
        "reconnectRecoveryRequests": 1,
        "reconnectSessionMismatches": 0,
        "reconnectStreamRequests": 1,
        "reconnectUnexpectedCloses": 0,
        "reconnectUnexpectedRetries": 0,
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
            {"hostname": "a.test", "port": 443},
            {"hostname": "a.test", "port": 4443},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4445},
        ],
        "transcript": [
            {"sequence": 1, "event": "wisp-connected"},
            {"sequence": 2, "event": "wisp-ready"},
            {"sequence": 3, "event": "connect-open"},
            {"sequence": 4, "event": "plaintext-http-control-tcp-connect"},
            {"sequence": 5, "event": "h1-plaintext-http-control"},
            {"sequence": 6, "event": "h1-plaintext-http-control-proof"},
            {
                "sequence": 7,
                "event": "plaintext-http-control-phase-complete",
            },
            {"sequence": 8, "event": "h2-redirect"},
            {"sequence": 9, "event": "h2-redirect-cookie"},
            {"sequence": 10, "event": "h2-redirect-intermediate"},
            {"sequence": 11, "event": "h2-redirect-intermediate-cookie"},
            {"sequence": 12, "event": "h2-page"},
            {"sequence": 13, "event": "h2-page-cookie"},
            {"sequence": 14, "event": "h2-resource"},
            {"sequence": 15, "event": "local-gateway-443-request"},
            {"sequence": 16, "event": "local-gateway-444-blocked"},
            {"sequence": 17, "event": "h2-cache-store-200"},
            {"sequence": 18, "event": "h2-cache-revalidate-304"},
            {"sequence": 19, "event": "h2-csp-connect-src-proof"},
            {"sequence": 20, "event": "h2-mixed-content-proof"},
            {"sequence": 21, "event": "h2-cancel-stream-start"},
            {
                "sequence": 22,
                "event": "h2-cancel-stream-cancel-reset",
                "rstCode": 8,
            },
            {"sequence": 23, "event": "h2-cancel-stream-proof"},
            {"sequence": 24, "event": "h2-slow-stream-start"},
            {"sequence": 25, "event": "h2-slow-stream-first-stage"},
            {
                "sequence": 26,
                "event": "h2-slow-stream-first-stage-ack",
            },
            {"sequence": 27, "event": "h2-slow-stream-second-stage"},
            {
                "sequence": 28,
                "event": "h2-slow-stream-consumer-pause-ready",
            },
            {
                "sequence": 29,
                "event": "h2-slow-stream-consumer-burst",
                "bytes": 64 * 1024,
                "backpressured": True,
            },
            {
                "sequence": 30,
                "event": "h2-slow-stream-consumer-resume",
            },
            {
                "sequence": 31,
                "event": "h2-slow-stream-second-stage-ack",
            },
            {"sequence": 32, "event": "h2-slow-stream-third-stage"},
            {"sequence": 33, "event": "h2-slow-stream-complete"},
            {"sequence": 34, "event": "h2-slow-stream-proof"},
            {"sequence": 35, "event": "h2-multiplex-pending"},
            {"sequence": 36, "event": "h1-multiplex-pending"},
            {"sequence": 37, "event": "wisp-multiplex-two-streams-live"},
            {"sequence": 38, "event": "h2-multiplex-complete"},
            {"sequence": 39, "event": "h1-multiplex-complete"},
            {"sequence": 40, "event": "h2-large-download-start"},
            {"sequence": 41, "event": "h2-large-download-complete"},
            {"sequence": 42, "event": "h2-reconnect-stream-start"},
            {"sequence": 43, "event": "h2-reconnect-stream-first-chunk"},
            {"sequence": 44, "event": "h2-reconnect-first-chunk-ack"},
            {"sequence": 45, "event": "h2-reconnect-disconnect-requested"},
            {"sequence": 46, "event": "h2-reconnect-carrier-close"},
            {"sequence": 47, "event": "wisp-disconnected"},
            {"sequence": 48, "event": "h2-reconnect-stream-disconnected"},
            {"sequence": 49, "event": "h2-reconnect-wisp-disconnected"},
            {"sequence": 50, "event": "wisp-connected"},
            {"sequence": 51, "event": "wisp-ready"},
            {
                "sequence": 52,
                "event": "connect-open",
                "destination": "a.test:4443",
            },
            {"sequence": 53, "event": "h2-reconnect-recovery"},
            {"sequence": 54, "event": "h1-cors-denied"},
            {"sequence": 55, "event": "h1-cors"},
            {"sequence": 56, "event": "h1-wss-echo"},
            {"sequence": 57, "event": "tls-failure-tcp-connect"},
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

    def test_rejects_incomplete_or_unredacted_devtools_network_evidence(
        self,
    ) -> None:
        for field, invalid_value in (
            ("state", "enabled"),
            ("networkEnabled", False),
            ("redirectRequest", False),
            ("redirectIntermediateRequest", False),
            ("redirectHopCount", 1),
            ("finalRequest", False),
            ("responseReceived", False),
            ("loadingFinished", False),
            ("requestIdCorrelated", False),
            ("responseStatus", 302),
            ("responseProtocol", "http/1.1"),
            ("localGatewayBlockedRequest", False),
            ("localGatewayBlockedLoadingFailed", False),
            ("localGatewayBlockedRequestIdCorrelated", False),
            ("localGatewayBlockedByAdministrator", False),
            ("reconnectRequest", False),
            ("reconnectLoadingFailed", False),
            ("reconnectRequestIdCorrelated", False),
            ("reconnectInternetDisconnected", False),
            ("events", ["Network.requestWillBeSent:final"]),
            ("url", "https://a.test:4443/m5/"),
            ("requestId", "1.2"),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                devtools_network = readiness["devtoolsNetwork"]
                assert isinstance(devtools_network, dict)
                devtools_network[field] = invalid_value
                with self.assertRaisesRegex(M0Error, "DevTools Network"):
                    validate_passing_result(result)

        result = passing_result()
        result["devtoolsNetworkEnabled"] = {
            "protocol": 1,
            "state": "complete",
            "networkEnabled": True,
            "events": [],
        }
        with self.assertRaisesRegex(M0Error, "Network.enable"):
            validate_passing_result(result)

    def test_rejects_incomplete_or_unredacted_download_manager_evidence(
        self,
    ) -> None:
        for field, invalid_value in (
            ("state", "enabled"),
            ("singleDownload", False),
            ("navigationSource", False),
            ("responseStatusMatched", False),
            ("contentDispositionMatched", False),
            ("mimeTypeMatched", False),
            ("allDataSaved", False),
            ("targetPathDetermined", False),
            ("targetDirectoryMatched", False),
            ("interruptReasonNone", False),
            ("totalBytes", 0),
            ("receivedBytes", 0),
            ("filePatternVerified", False),
            ("url", "https://a.test:4443/m5/large-download"),
            ("path", "/profile/wasm-m5-download-manager/file"),
            ("guid", "not-a-guid"),
            ("headers", {"content-disposition": "attachment"}),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                download = readiness["m5Download"]
                assert isinstance(download, dict)
                download[field] = invalid_value
                with self.assertRaisesRegex(M0Error, "DownloadManager"):
                    validate_passing_result(result)

    def test_rejects_missing_page_network_evidence(self) -> None:
        for field in (
            "h2Fetch",
            "corsDeniedRequestStarted",
            "corsDeniedResponseBlocked",
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
            "multiplexRequestsStarted",
            "multiplexH2Response",
            "multiplexH1Response",
            "multiplexComplete",
            "largeDownloadNavigationRequested",
            "largeDownloadNativeComplete",
            "reconnectStreamStarted",
            "reconnectFirstChunkReceived",
            "reconnectFirstChunkAck",
            "reconnectDisconnectRequested",
            "reconnectStreamFailed",
            "reconnectRecovered",
            "cspConnectSrcBlocked",
            "activeMixedContentBlocked",
            "activeMixedContentCspAllowed",
            "localGatewayMappedRequestStarted",
            "localGatewayMappedResponse",
            "localGatewayBlockedRequestStarted",
            "localGatewayBlocked",
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

    def test_rejects_an_incorrect_redirect_hop_count(self) -> None:
        result = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        page_probe = readiness["pageProbe"]
        assert isinstance(page_probe, dict)
        page_probe["redirectHopCount"] = 1
        with self.assertRaisesRegex(M0Error, "redirectHopCount"):
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

    def test_rejects_invalid_reconnect_page_evidence(self) -> None:
        for invalid_value in ("", "AbortError", None, False):
            with self.subTest(
                field="reconnectStreamErrorName", invalid_value=invalid_value
            ):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe["reconnectStreamErrorName"] = invalid_value
                with self.assertRaisesRegex(
                    M0Error, "reconnectStreamErrorName"
                ):
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
        # The peer teardown marker and the asynchronous H2 stream close can
        # arrive in either order after the RFC 6455 carrier close.
        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        stream_closed_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "h2-reconnect-stream-disconnected"
        )
        relay_closed_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "h2-reconnect-wisp-disconnected"
        )
        transcript[stream_closed_index], transcript[relay_closed_index] = (
            transcript[relay_closed_index],
            transcript[stream_closed_index],
        )
        run_m5_wisp_smoke.validate_relay_transcript(
            status, relay_ready=relay_ready
        )

    def test_rejects_incomplete_or_unredacted_multiplex_evidence(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        for field, invalid_value in (
            ("multiplexPhase", "awaiting-streams"),
            ("multiplexBarrierReleases", 0),
            ("multiplexBarrierTimeouts", 1),
            ("multiplexBothStreamsOpen", False),
            ("multiplexCorrelationFailures", 1),
            ("multiplexDistinctWispStreamCount", 1),
            ("multiplexH1Requests", 0),
            ("multiplexH2Requests", 0),
            ("multiplexResponses", 1),
            ("multiplexSharedCarrier", False),
            ("multiplexUnexpectedCloses", 1),
            ("multiplexResponses", True),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                status = passing_relay_status()
                status[field] = invalid_value
                with self.assertRaisesRegex(M0Error, "multiplex"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        live_entry = next(
            entry
            for entry in transcript
            if entry.get("event") == "wisp-multiplex-two-streams-live"
        )
        live_entry["carrierId"] = 1
        with self.assertRaisesRegex(M0Error, "non-redacted"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

    def test_rejects_missing_or_misordered_multiplex_transcript(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        for event_name in (
            "h2-multiplex-pending",
            "h1-multiplex-pending",
            "wisp-multiplex-two-streams-live",
            "h2-multiplex-complete",
            "h1-multiplex-complete",
        ):
            with self.subTest(missing_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript[:] = [
                    entry for entry in transcript if entry.get("event") != event_name
                ]
                with self.assertRaisesRegex(M0Error, "missing|exactly one"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        live_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "wisp-multiplex-two-streams-live"
        )
        completion_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "h2-multiplex-complete"
        )
        transcript[live_index], transcript[completion_index] = (
            transcript[completion_index],
            transcript[live_index],
        )
        with self.assertRaisesRegex(M0Error, "multiplex proof"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

    def test_rejects_incomplete_or_unredacted_local_gateway_evidence(
        self,
    ) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        for field, invalid_value in (
            ("localGateway443StreamsOpened", 0),
            ("localGateway443StreamsOpened", 2),
            ("localGateway443Requests", 0),
            ("localGateway443Requests", 2),
            ("localGatewayBlockedPortAttempts", 0),
            ("localGatewayBlockedPortAttempts", 2),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                status = passing_relay_status()
                status[field] = invalid_value
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for rejected_destinations in (0, 2):
            with self.subTest(rejected_destinations=rejected_destinations):
                status = passing_relay_status()
                status["rejectedDestinations"] = rejected_destinations
                with self.assertRaisesRegex(
                    M0Error, "controlled local gateway port"
                ):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        destinations = status["requestedDestinations"]
        assert isinstance(destinations, list)
        destinations[:] = [
            destination
            for destination in destinations
            if destination.get("port") != 443
        ]
        with self.assertRaisesRegex(M0Error, "mapped local gateway 443 stream"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        destinations = status["requestedDestinations"]
        assert isinstance(destinations, list)
        destinations.append({"hostname": "a.test", "port": 444})
        with self.assertRaisesRegex(M0Error, "blocked local gateway port"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for event_name in (
            "local-gateway-443-request",
            "local-gateway-444-blocked",
        ):
            with self.subTest(missing_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript[:] = [
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
        transcript.append(
            {"sequence": 55, "event": "local-gateway-443-request"}
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        mapping_entry = next(
            entry
            for entry in transcript
            if entry.get("event") == "local-gateway-443-request"
        )
        mapping_entry["destination"] = "a.test:443"
        with self.assertRaisesRegex(M0Error, "non-redacted"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        mapping_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "local-gateway-443-request"
        )
        blocked_index = next(
            index
            for index, entry in enumerate(transcript)
            if entry.get("event") == "local-gateway-444-blocked"
        )
        transcript[mapping_index], transcript[blocked_index] = (
            transcript[blocked_index],
            transcript[mapping_index],
        )
        with self.assertRaisesRegex(M0Error, "mapping proof"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
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

        for field in (
            "redirectIntermediateRequests",
            "redirectIntermediateCookieValidations",
        ):
            with self.subTest(field=field):
                status = passing_relay_status()
                status[field] = 0
                with self.assertRaisesRegex(M0Error, "redirect|intermediate"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in (
            "h2-redirect",
            "h2-redirect-cookie",
            "h2-redirect-intermediate",
            "h2-redirect-intermediate-cookie",
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
            if entry.get("event") == "h2-redirect-intermediate-cookie"
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
        with self.assertRaisesRegex(M0Error, "two-hop redirect chain"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

    def test_rejects_invalid_cors_denial_evidence(self) -> None:
        relay_ready = run_m5_wisp_smoke.parse_relay_ready_line(
            RELAY_READY_LINE
        )
        for field, invalid_value, error in (
            ("corsDeniedRequests", 0, "rejected CORS request"),
            ("corsDeniedRequests", 2, "rejected CORS request"),
            ("corsRequests", 0, "allowed CORS request"),
            ("corsRequests", 2, "allowed CORS request"),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                status = passing_relay_status()
                status[field] = invalid_value
                with self.assertRaisesRegex(M0Error, error):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        for event_name in ("h1-cors-denied", "h1-cors"):
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

        for first_event, second_event in (
            ("h1-cors-denied", "h1-cors"),
            ("h1-cors", "h1-wss-echo"),
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
                    M0Error, "denied then allowed CORS before WebSocket"
                ):
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
                "h1-cors-denied",
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
            ("h2-cancel-stream-proof", "h1-cors-denied"),
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
            ("h2-large-download-complete", "h1-cors-denied"),
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
                    M0Error, "multiplex proof|large download events"
                ):
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

    def test_rejects_invalid_reconnect_evidence(self) -> None:
        relay_ready = parsed_relay_ready()

        status = passing_relay_status()
        status["reconnectPhase"] = "disconnected"
        with self.assertRaisesRegex(M0Error, "reconnect phase"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for field, actual_value, error in (
            ("activeWispSessions", 0, "recovered WISP session"),
            ("activeWispSessions", 2, "recovered WISP session"),
            ("wispSessions", 1, "fresh reconnect"),
            ("wispSessions", 3, "fresh reconnect"),
            ("reconnectDisconnectRequests", 0, "reconnectDisconnectRequests"),
            ("reconnectDisconnectRequests", 2, "reconnectDisconnectRequests"),
            ("reconnectFirstChunkAcks", 0, "reconnectFirstChunkAcks"),
            ("reconnectFirstChunkAcks", 2, "reconnectFirstChunkAcks"),
            ("reconnectFirstChunks", 0, "reconnectFirstChunks"),
            ("reconnectFirstChunks", 2, "reconnectFirstChunks"),
            ("reconnectRecoveryRequests", 0, "reconnectRecoveryRequests"),
            ("reconnectRecoveryRequests", 2, "reconnectRecoveryRequests"),
            ("reconnectSessionMismatches", 1, "reconnectSessionMismatches"),
            ("reconnectStreamRequests", 0, "reconnectStreamRequests"),
            ("reconnectStreamRequests", 2, "reconnectStreamRequests"),
            ("reconnectUnexpectedCloses", 1, "reconnectUnexpectedCloses"),
            ("reconnectUnexpectedRetries", 1, "reconnectUnexpectedRetries"),
        ):
            with self.subTest(field=field, actual_value=actual_value):
                status = passing_relay_status()
                status[field] = actual_value
                with self.assertRaisesRegex(M0Error, error):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        destinations = status["requestedDestinations"]
        assert isinstance(destinations, list)
        destinations.pop(1)
        with self.assertRaisesRegex(
            M0Error, "all fixed M5 destination streams"
        ):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for event_name in (
            "h2-reconnect-stream-start",
            "h2-reconnect-stream-first-chunk",
            "h2-reconnect-first-chunk-ack",
            "h2-reconnect-disconnect-requested",
            "h2-reconnect-carrier-close",
            "h2-reconnect-stream-disconnected",
            "h2-reconnect-wisp-disconnected",
            "h2-reconnect-recovery",
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
            "h2-reconnect-stream-start",
            "h2-reconnect-stream-first-chunk",
            "h2-reconnect-first-chunk-ack",
            "h2-reconnect-disconnect-requested",
            "h2-reconnect-carrier-close",
            "h2-reconnect-stream-disconnected",
            "h2-reconnect-wisp-disconnected",
            "h2-reconnect-recovery",
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
                "h2-reconnect-carrier-close",
                "wisp-disconnected",
                "relay reconnect events",
            ),
            (
                "h2-reconnect-carrier-close",
                "h2-reconnect-stream-disconnected",
                "relay reconnect events",
            ),
            (
                "h2-reconnect-wisp-disconnected",
                "h2-reconnect-recovery",
                "relay reconnect events",
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

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        transcript[:] = [
            entry
            for entry in transcript
            if not (
                entry.get("event") == "connect-open"
                and entry.get("destination") == "a.test:4443"
            )
        ]
        with self.assertRaisesRegex(M0Error, "fresh TCP stream"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        recovery_connect = next(
            entry
            for entry in transcript
            if entry.get("event") == "connect-open"
            and entry.get("destination") == "a.test:4443"
        )
        recovery_connect["destination"] = "a.test:4444"
        with self.assertRaisesRegex(M0Error, "original H2 destination"):
            run_m5_wisp_smoke.validate_relay_transcript(
                status, relay_ready=relay_ready
            )

        for event_name in (
            "h2-reconnect-stream-rejected",
            "h2-reconnect-stream-unexpected-close",
            "h2-reconnect-first-chunk-ack-rejected",
            "h2-reconnect-first-chunk-ack-session-mismatch",
            "h2-reconnect-relay-selection-failed",
            "h2-reconnect-recovery-rejected",
            "h2-reconnect-recovery-session-mismatch",
            "h2-reconnect-recovery-timeout",
            "h2-reconnect-recovery-unexpected-close",
        ):
            with self.subTest(forbidden_event=event_name):
                status = passing_relay_status()
                transcript = status["transcript"]
                assert isinstance(transcript, list)
                transcript.append(
                    {
                        "sequence": len(transcript) + 1,
                        "event": event_name,
                    }
                )
                with self.assertRaisesRegex(M0Error, "reconnect failure"):
                    run_m5_wisp_smoke.validate_relay_transcript(
                        status, relay_ready=relay_ready
                    )

        status = passing_relay_status()
        transcript = status["transcript"]
        assert isinstance(transcript, list)
        transcript.append(
            {
                "sequence": len(transcript) + 1,
                "event": "h2-reconnect-global-close",
            }
        )
        with self.assertRaisesRegex(M0Error, "WISP global close"):
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
            ("h2-csp-connect-src-proof", "h1-cors-denied"),
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

    def test_snapshot_rechecks_captured_bytes_for_private_key_headers(self) -> None:
        module_name = "content_shell_wasm_m5_test"
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            (out_dir / f"{module_name}.js").write_bytes(b"loader")
            (out_dir / f"{module_name}.wasm").write_bytes(
                b"\x00asm\n-----BEGIN EC PRIVATE KEY-----\n"
            )

            with self.assertRaisesRegex(M0Error, "private-key header"):
                run_m5_wisp_smoke.snapshot_wisp_artifacts(out_dir, module_name)

    def test_static_host_snapshot_rechecks_served_host_bytes_for_private_key_headers(
        self,
    ) -> None:
        with self.assertRaisesRegex(M0Error, "private-key header"):
            run_m5_wisp_smoke.validate_wisp_static_host_snapshots(
                {
                    "/": b"<html>host</html>",
                    "/__m3__/": b"<html>host</html>",
                    "/__m3__/content_shell_host.js": (
                        b"// -----BEGIN PRIVATE KEY-----"
                    ),
                }
            )

    def test_server_serves_captured_artifacts_after_disk_mutation(self) -> None:
        module_name = "content_shell_wasm_m5_test"
        original_loader = b"original M5 loader"
        original_wasm = b"\x00asm-original-M5"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / "out"
            out_dir.mkdir()
            (out_dir / f"{module_name}.js").write_bytes(original_loader)
            (out_dir / f"{module_name}.wasm").write_bytes(original_wasm)
            snapshots = run_m5_wisp_smoke.snapshot_wisp_artifacts(
                out_dir, module_name
            )
            delivery = run_m5_wisp_smoke.artifact_delivery_identity(
                snapshots, module_name
            )
            font = root / "Ahem.woff2"
            font.write_bytes(b"test font")
            with mock.patch.object(m3_content_server, "M3_AHEM_FONT", font):
                server = m3_content_server.create_m3_server(
                    "127.0.0.1",
                    0,
                    out_dir,
                    "m5-token",
                    queue.Queue(maxsize=1),
                    module_name=module_name,
                    artifact_snapshots=snapshots,
                    server_factory=run_m5_wisp_smoke.M5WispServer,
                )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                (out_dir / f"{module_name}.js").write_bytes(b"mutated loader")
                (out_dir / f"{module_name}.wasm").write_bytes(b"mutated wasm")
                host, port = server.server_address[:2]
                for suffix, expected in (
                    (".js", original_loader),
                    (".wasm", original_wasm),
                ):
                    with self.subTest(suffix=suffix):
                        connection = http.client.HTTPConnection(host, port, timeout=5)
                        try:
                            connection.request(
                                "GET", f"/__m3__/artifacts/{module_name}{suffix}"
                            )
                            response = connection.getresponse()
                            self.assertEqual(http.client.OK, response.status)
                            self.assertEqual(expected, response.read())
                        finally:
                            connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(
                hashlib.sha256(original_loader).hexdigest(),
                delivery["loader"]["sha256"],
            )
            self.assertEqual(
                run_m5_wisp_smoke.ARTIFACT_SOURCE_PROVENANCE,
                delivery["artifact_source_provenance"],
            )

    def test_server_serves_captured_static_host_after_disk_mutation(self) -> None:
        module_name = "content_shell_wasm_m5_test"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            (out_dir / f"{module_name}.js").write_bytes(b"loader")
            (out_dir / f"{module_name}.wasm").write_bytes(b"\x00asm")
            original_html = b"<script type=module>original M5 host</script>"
            original_js = b"export const m5Host = 'original';"
            (host_dir / "content_shell.html").write_bytes(original_html)
            (host_dir / "content_shell_host.js").write_bytes(original_js)
            artifact_snapshots = run_m5_wisp_smoke.snapshot_wisp_artifacts(
                out_dir, module_name
            )
            static_snapshots = run_m5_wisp_smoke.snapshot_wisp_static_host_resources(
                host_dir
            )
            delivery = run_m5_wisp_smoke.artifact_delivery_identity(
                artifact_snapshots, module_name
            )
            delivery.update(
                run_m5_wisp_smoke.wisp_static_host_delivery_identity(
                    static_snapshots
                )
            )
            server = m3_content_server.create_m3_server(
                "127.0.0.1",
                0,
                out_dir,
                "m5-token",
                queue.Queue(maxsize=1),
                module_name=module_name,
                artifact_snapshots=artifact_snapshots,
                static_snapshots=static_snapshots,
                require_ahem_font=False,
                server_factory=run_m5_wisp_smoke.M5WispServer,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                (host_dir / "content_shell.html").write_bytes(b"mutated HTML")
                (host_dir / "content_shell_host.js").write_bytes(b"mutated JS")
                host, port = server.server_address[:2]
                for path, expected in (
                    ("/", original_html),
                    ("/__m3__/", original_html),
                    ("/__m3__/content_shell_host.js", original_js),
                ):
                    with self.subTest(path=path):
                        connection = http.client.HTTPConnection(host, port, timeout=5)
                        try:
                            connection.request("GET", path)
                            response = connection.getresponse()
                            self.assertEqual(http.client.OK, response.status)
                            self.assertEqual(expected, response.read())
                        finally:
                            connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(
                hashlib.sha256(original_html).hexdigest(),
                delivery["host_html"]["sha256"],
            )
            self.assertEqual(
                hashlib.sha256(original_js).hexdigest(),
                delivery["host_js"]["sha256"],
            )


class M5RunnerCleanupTest(unittest.TestCase):
    """Exercise terminal-evidence ordering without launching Chrome or Node."""

    def _run_main_with_cleanup_fakes(
        self,
        *,
        browser_cleanup_error: BaseException | None = None,
        operational_error: BaseException | None = None,
        abort_browser_error: BaseException | None = None,
        abort_relay_error: BaseException | None = None,
        server_cleanup_error: BaseException | None = None,
        profile_cleanup_error: BaseException | None = None,
    ) -> tuple[int, str, str, dict[str, mock.Mock]]:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 8123)
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        relay = mock.Mock()
        relay.stdout = object()
        relay.stderr = object()
        browser = mock.Mock()
        browser.stderr = object()
        relay_stdout_reader = mock.Mock()
        relay_stderr_reader = mock.Mock()
        browser_stderr_reader = mock.Mock()
        profile = mock.Mock()
        profile.name = "/fake-profile"
        profile.cleanup.side_effect = profile_cleanup_error
        artifact_snapshots = {
            "content_shell_wasm_m5_test.js": b"fake M5 loader",
            "content_shell_wasm_m5_test.wasm": b"\x00asm fake M5",
        }
        relay_ready = run_m5_wisp_smoke.RelayReady(
            wisp_endpoint="ws://127.0.0.1:40123/wisp/",
            https_url="https://a.test:4443/m5/",
            redirect_url="https://a.test:4443/m5/redirect-cookie",
            plaintext_http_control_url=(
                "http://a.test:4446/m5/plaintext-control"
            ),
            mixed_content_target_url=(
                "http://a.test:4446/m5/mixed-content-target"
            ),
            http1_url="https://a.test:4444/m5/cors-resource",
            tls_failure_url="https://a.test:4445/m5/tls-name-mismatch",
            transcript_url="http://127.0.0.1:40123/status",
        )
        stop_browser = mock.Mock(side_effect=browser_cleanup_error)
        stop_relay = mock.Mock()
        cleanup_server = mock.Mock(return_value=server_cleanup_error)
        abort_browser = mock.Mock(side_effect=abort_browser_error)
        abort_relay = mock.Mock(side_effect=abort_relay_error)
        wait_for_result = mock.Mock()
        if operational_error is None:
            wait_for_result.return_value = {}
        else:
            wait_for_result.side_effect = operational_error
        dependencies = {
            "server": server,
            "server_thread": server_thread,
            "relay": relay,
            "browser": browser,
            "relay_stdout_reader": relay_stdout_reader,
            "relay_stderr_reader": relay_stderr_reader,
            "browser_stderr_reader": browser_stderr_reader,
            "profile": profile,
            "stop_browser": stop_browser,
            "stop_relay": stop_relay,
            "cleanup_server": cleanup_server,
            "abort_browser": abort_browser,
            "abort_relay": abort_relay,
            "artifact_snapshots": artifact_snapshots,
            "wait_for_result": wait_for_result,
        }
        patches = (
            mock.patch.object(run_m5_wisp_smoke, "load_manifest", return_value={}),
            mock.patch.object(run_m5_wisp_smoke, "checked_output", return_value="head"),
            mock.patch.object(
                run_m5_wisp_smoke, "manifest_versions", return_value=VERSIONS
            ),
            mock.patch.object(run_m5_wisp_smoke, "print_context", return_value={}),
            mock.patch.object(
                run_m5_wisp_smoke,
                "find_browser",
                return_value=(Path("/fake-browser"), "test-browser"),
            ),
            mock.patch.object(
                run_m5_wisp_smoke, "find_node", return_value=Path("/fake-node")
            ),
            mock.patch.object(run_m5_wisp_smoke, "verify_no_private_key_pem_artifacts"),
            mock.patch.object(
                run_m5_wisp_smoke,
                "snapshot_wisp_artifacts",
                return_value=artifact_snapshots,
            ),
            mock.patch.object(
                run_m5_wisp_smoke, "create_m3_server", return_value=server
            ),
            mock.patch.object(
                run_m5_wisp_smoke.threading,
                "Thread",
                return_value=server_thread,
            ),
            mock.patch.object(run_m5_wisp_smoke, "relay_command", return_value=["relay"]),
            mock.patch.object(
                run_m5_wisp_smoke, "m5_host_origin", return_value="http://host.test"
            ),
            mock.patch.object(
                run_m5_wisp_smoke, "m5_smoke_url", return_value="http://host.test/m5"
            ),
            mock.patch.object(
                run_m5_wisp_smoke, "m5_browser_command", return_value=["browser"]
            ),
            mock.patch.object(
                run_m5_wisp_smoke.subprocess,
                "Popen",
                side_effect=[relay, browser],
            ),
            mock.patch.object(
                run_m5_wisp_smoke,
                "BrowserStderrReader",
                side_effect=(
                    relay_stdout_reader,
                    relay_stderr_reader,
                    browser_stderr_reader,
                ),
            ),
            mock.patch.object(
                run_m5_wisp_smoke,
                "wait_for_relay_ready",
                return_value=relay_ready,
            ),
            mock.patch.object(
                run_m5_wisp_smoke.tempfile,
                "TemporaryDirectory",
                return_value=profile,
            ),
            mock.patch.object(run_m5_wisp_smoke, "wait_for_result", wait_for_result),
            mock.patch.object(run_m5_wisp_smoke, "validate_m5_result"),
            mock.patch.object(
                run_m5_wisp_smoke, "fetch_relay_transcript", return_value={}
            ),
            mock.patch.object(run_m5_wisp_smoke, "validate_relay_transcript"),
            mock.patch.object(run_m5_wisp_smoke, "stop_browser_group", stop_browser),
            mock.patch.object(run_m5_wisp_smoke, "stop_process_group", stop_relay),
            mock.patch.object(run_m5_wisp_smoke, "_cleanup_m5_server", cleanup_server),
            mock.patch.object(run_m5_wisp_smoke, "abort_browser_group", abort_browser),
            mock.patch.object(run_m5_wisp_smoke, "abort_process_group", abort_relay),
            mock.patch.object(
                run_m5_wisp_smoke,
                "write_failure_diagnostics",
                return_value=Path("/diagnostic"),
            ),
            mock.patch.object(sys, "argv", ["m5-wisp-runner"]),
        )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stdout = stack.enter_context(
                mock.patch("sys.stdout", new_callable=io.StringIO)
            )
            stderr = stack.enter_context(
                mock.patch("sys.stderr", new_callable=io.StringIO)
            )
            result = run_m5_wisp_smoke.main()
        return result, stdout.getvalue(), stderr.getvalue(), dependencies

    def test_main_suppresses_terminal_markers_when_cleanup_before_pass_fails(
        self,
    ) -> None:
        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes(
            browser_cleanup_error=M0Error("browser cleanup failed")
        )

        self.assertEqual(1, result)
        self.assertIn("FAIL reason=browser cleanup failed", stderr)
        for marker in (
            "ARTIFACT_DELIVERY",
            "BROWSER_RESULT",
            "RELAY_TRANSCRIPT",
            "PASS",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(
                    f"{run_m5_wisp_smoke.SENTINEL}:{marker}", stdout + stderr
                )
        dependencies["stop_browser"].assert_called_once_with(
            dependencies["browser"], dependencies["browser_stderr_reader"]
        )
        dependencies["stop_relay"].assert_not_called()
        dependencies["abort_browser"].assert_called_once_with(
            dependencies["browser"],
            dependencies["browser_stderr_reader"],
            unowned_streams=(),
        )
        dependencies["abort_relay"].assert_called_once_with(
            dependencies["relay"],
            (
                dependencies["relay_stdout_reader"],
                dependencies["relay_stderr_reader"],
            ),
            description="M5 WISP relay",
            unowned_streams=(),
        )
        dependencies["cleanup_server"].assert_called_once()
        dependencies["profile"].cleanup.assert_called_once_with()

    def test_main_preserves_operational_failure_while_attempting_all_cleanup(
        self,
    ) -> None:
        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes(
            operational_error=M0Error("original operational failure"),
            abort_browser_error=M0Error("abort browser cleanup failed"),
            abort_relay_error=M0Error("abort relay cleanup failed"),
            server_cleanup_error=M0Error("server cleanup failed"),
            profile_cleanup_error=M0Error("profile cleanup failed"),
        )

        self.assertEqual(1, result)
        self.assertIn("FAIL reason=original operational failure", stderr)
        for message in (
            "abort browser cleanup failed",
            "abort relay cleanup failed",
            "server cleanup failed",
            "profile cleanup failed",
        ):
            with self.subTest(message=message):
                self.assertNotIn(message, stderr)
        for marker in (
            "ARTIFACT_DELIVERY",
            "BROWSER_RESULT",
            "RELAY_TRANSCRIPT",
            "PASS",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(
                    f"{run_m5_wisp_smoke.SENTINEL}:{marker}", stdout + stderr
                )
        dependencies["stop_browser"].assert_not_called()
        dependencies["stop_relay"].assert_not_called()
        dependencies["abort_browser"].assert_called_once()
        dependencies["abort_relay"].assert_called_once()
        dependencies["cleanup_server"].assert_called_once()
        dependencies["profile"].cleanup.assert_called_once_with()

    def test_main_emits_snapshot_delivery_only_after_successful_cleanup(self) -> None:
        result, stdout, stderr, dependencies = self._run_main_with_cleanup_fakes()

        self.assertEqual(0, result)
        self.assertEqual("", stderr)
        delivery_prefix = f"{run_m5_wisp_smoke.SENTINEL}:ARTIFACT_DELIVERY "
        browser_prefix = f"{run_m5_wisp_smoke.SENTINEL}:BROWSER_RESULT "
        relay_prefix = f"{run_m5_wisp_smoke.SENTINEL}:RELAY_TRANSCRIPT "
        self.assertLess(stdout.index(delivery_prefix), stdout.index(browser_prefix))
        self.assertLess(stdout.index(browser_prefix), stdout.index(relay_prefix))
        delivery = json.loads(
            next(
                line[len(delivery_prefix) :]
                for line in stdout.splitlines()
                if line.startswith(delivery_prefix)
            )
        )
        self.assertEqual(
            run_m5_wisp_smoke.ARTIFACT_SOURCE_PROVENANCE,
            delivery["artifact_source_provenance"],
        )
        self.assertEqual(
            hashlib.sha256(
                dependencies["artifact_snapshots"][
                    "content_shell_wasm_m5_test.wasm"
                ]
            ).hexdigest(),
            delivery["wasm"]["sha256"],
        )

    def test_server_cleanup_uses_bounded_shutdown_and_handler_drain(self) -> None:
        server = mock.Mock()
        thread = mock.Mock()
        thread.is_alive.return_value = False

        with mock.patch.object(run_m5_wisp_smoke, "shutdown_server_bounded") as shutdown:
            error = run_m5_wisp_smoke._cleanup_m5_server(
                server=server,
                server_thread=thread,
                server_thread_started=True,
            )

        self.assertIsNone(error)
        shutdown.assert_called_once_with(
            server,
            timeout=run_m5_wisp_smoke.CLEANUP_TIMEOUT_SECONDS,
            description="M5 host server",
        )
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(
            timeout=run_m5_wisp_smoke.CLEANUP_TIMEOUT_SECONDS
        )
        server.join_request_handlers.assert_called_once_with(
            timeout=run_m5_wisp_smoke.CLEANUP_TIMEOUT_SECONDS,
            description="M5 host server",
        )


if __name__ == "__main__":
    unittest.main()

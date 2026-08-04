#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the controlled M5 WISP browser runner."""

from __future__ import annotations

import copy
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
                "nonce": "fixed-test-nonce",
            },
        },
        "logs": {
            "host": [
                "initialize:wisp-configured",
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
        "tlsMismatchTcpConnections": 1,
        "tlsMismatchHttpStreams": 0,
        "h2Requests": {"count": 2, "protocol": "h2"},
        "requestedDestinations": [
            {"hostname": "a.test", "port": 4443},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4444},
            {"hostname": "a.test", "port": 4445},
        ],
        "transcript": [
            {"sequence": 1, "event": "wisp-ready"},
            {"sequence": 2, "event": "connect-open"},
            {"sequence": 3, "event": "h2-page"},
            {"sequence": 4, "event": "h2-resource"},
            {"sequence": 5, "event": "h1-cors"},
            {"sequence": 6, "event": "h1-wss-echo"},
            {"sequence": 7, "event": "tls-failure-tcp-connect"},
        ],
    }


class RelayReadinessTest(unittest.TestCase):
    def test_parses_fixed_loopback_readiness(self) -> None:
        ready = run_m5_wisp_smoke.parse_relay_ready_line(RELAY_READY_LINE)

        self.assertEqual(ready.wisp_endpoint, "ws://127.0.0.1:40123/wisp/")
        self.assertEqual(ready.https_url, "https://a.test:4443/m5/")
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
                line = json.dumps(
                    {
                        "wispEndpoint": endpoint,
                        "httpsUrl": "https://a.test:4443/m5/network",
                        "http1Url": "https://a.test:4444/m5/cors-resource",
                        "tlsFailureUrl": (
                            "https://a.test:4445/m5/tls-name-mismatch"
                        ),
                        "transcriptUrl": "http://127.0.0.1:40123/status",
                    }
                )
                with self.assertRaisesRegex(M0Error, "wispEndpoint"):
                    run_m5_wisp_smoke.parse_relay_ready_line(line)

    def test_rejects_arbitrary_or_query_bearing_navigation_url(self) -> None:
        for https_url in (
            "https://example.test:4443/m5/network",
            "http://a.test:4443/m5/network",
            "https://a.test:4443/not-m5",
            "https://a.test:4443/m5/network?secret=1",
        ):
            with self.subTest(https_url=https_url):
                line = json.dumps(
                    {
                        "wispEndpoint": "ws://127.0.0.1:40123/wisp/",
                        "httpsUrl": https_url,
                        "http1Url": "https://a.test:4444/m5/cors-resource",
                        "tlsFailureUrl": (
                            "https://a.test:4445/m5/tls-name-mismatch"
                        ),
                        "transcriptUrl": "http://127.0.0.1:40123/status",
                    }
                )
                with self.assertRaisesRegex(M0Error, "httpsUrl"):
                    run_m5_wisp_smoke.parse_relay_ready_line(line)

    def test_m5_query_is_tokenized_and_carries_only_validated_values(self) -> None:
        ready = run_m5_wisp_smoke.parse_relay_ready_line(RELAY_READY_LINE)
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
        self.assertEqual(query["m5_url"], [ready.https_url])
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
                line = json.dumps(
                    {
                        "wispEndpoint": "ws://127.0.0.1:40123/wisp/",
                        "httpsUrl": "https://a.test:4443/m5/network",
                        "http1Url": "https://a.test:4444/m5/cors-resource",
                        "tlsFailureUrl": (
                            "https://a.test:4445/m5/tls-name-mismatch"
                        ),
                        "transcriptUrl": transcript_url,
                    }
                )
                with self.assertRaisesRegex(M0Error, "transcriptUrl"):
                    run_m5_wisp_smoke.parse_relay_ready_line(line)

    def test_rejects_tls_failure_url_on_a_normal_fixture_port(self) -> None:
        ready = json.loads(RELAY_READY_LINE)
        ready["tlsFailureUrl"] = "https://a.test:4443/m5/tls-name-mismatch"

        with self.assertRaisesRegex(M0Error, "distinct fixture port"):
            run_m5_wisp_smoke.parse_relay_ready_line(json.dumps(ready))


class M5ResultValidationTest(unittest.TestCase):
    def test_accepts_complete_chromium_network_evidence(self) -> None:
        run_m5_wisp_smoke.validate_m5_result(
            passing_result(), expected_versions=VERSIONS
        )

    def test_rejects_missing_http2_or_websocket_evidence(self) -> None:
        for field in ("h2Fetch", "corsFetch", "webSocketEcho"):
            with self.subTest(field=field):
                result = passing_result()
                readiness = result["readiness"]
                assert isinstance(readiness, dict)
                page_probe = readiness["pageProbe"]
                assert isinstance(page_probe, dict)
                page_probe[field] = False
                with self.assertRaisesRegex(M0Error, field):
                    run_m5_wisp_smoke.validate_m5_result(
                        result, expected_versions=VERSIONS
                    )

    def test_rejects_data_navigation_or_unclean_shutdown(self) -> None:
        result = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        readiness["navigation"] = {"committed": True, "scheme": "data"}
        with self.assertRaisesRegex(M0Error, "HTTPS"):
            run_m5_wisp_smoke.validate_m5_result(
                result, expected_versions=VERSIONS
            )

    def test_rejects_unexpected_native_tls_failure(self) -> None:
        result = passing_result()
        tls_failure_readiness = result["tlsFailureReadiness"]
        assert isinstance(tls_failure_readiness, dict)
        navigation = tls_failure_readiness["navigation"]
        assert isinstance(navigation, dict)
        navigation["committed"] = True
        with self.assertRaisesRegex(M0Error, "TLS-failure navigation committed"):
            run_m5_wisp_smoke.validate_m5_result(
                result, expected_versions=VERSIONS
            )

        result = passing_result()
        tls_failure_readiness = result["tlsFailureReadiness"]
        assert isinstance(tls_failure_readiness, dict)
        navigation = tls_failure_readiness["navigation"]
        assert isinstance(navigation, dict)
        navigation["netError"] = -201
        with self.assertRaisesRegex(M0Error, "TLS-failure navigation netError"):
            run_m5_wisp_smoke.validate_m5_result(
                result, expected_versions=VERSIONS
            )

        result = passing_result()
        shutdown = result["shutdown"]
        assert isinstance(shutdown, dict)
        shutdown["runtimeExitCode"] = 1
        with self.assertRaisesRegex(M0Error, "runtimeExitCode"):
            run_m5_wisp_smoke.validate_m5_result(
                result, expected_versions=VERSIONS
            )


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

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the opt-in external/public M5 WISP smoke lane."""

from __future__ import annotations

import copy
from collections import deque
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, quote, quote_plus, urlsplit


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import run_m5_public_https_smoke as public_smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}
PUBLIC_ENDPOINT = "wss://relay.public.example.com/wisp/"
PUBLIC_PROBE_URL = "https://probe.public.example.com/static/public-v1"


class FakeServer:
    server_address = ("127.0.0.1", 38123)


def passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": "wisp_public_https_m5",
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
        "publicFrame": {
            "id": 2,
            "width": 800,
            "height": 600,
            "timestampMs": 2,
        },
        "navigationResult": {"ok": True, "scheme": "https"},
        "publicDevtoolsNetworkEnabled": {
            "protocol": 1,
            "state": "enabled",
            "networkEnabled": True,
            "events": [],
        },
        "readiness": {
            "firstVisuallyNonEmptyPaint": True,
            "fatalErrors": [],
            "navigation": {
                "committed": True,
                "scheme": "https",
                "responseCode": 200,
                "connectionProtocol": "h2",
            },
            "publicDevtoolsNetwork": {
                "protocol": 1,
                "state": "complete",
                "networkEnabled": True,
                "documentRequest": True,
                "responseReceived": True,
                "loadingFinished": True,
                "requestIdCorrelated": True,
                "responseStatus": 200,
                "responseProtocol": "h2",
                "wispWebSocketOpened": True,
                "wispHandshakeReady": True,
                "wispConfirmedStream": True,
                "wispDestinationMatched": True,
                "events": [
                    "Network.requestWillBeSent:document",
                    "Network.responseReceived:document",
                    "Network.loadingFinished:document",
                ],
            },
            "heartbeat": {
                "anchor": "m5-public-https-navigation-committed",
                "timerDelta": 2,
                "animationFrameDelta": 2,
                "maxTimerGapMs": 25,
            },
        },
        "logs": {
            "host": [
                "initialize:wisp-configured",
                "m5:public-devtools-network:enabled",
                "navigation:requested:m5-public-https",
                "navigation:committed:m5-public-https",
                "m5:public-devtools-network:complete",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "shutdown": {
            "ok": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "failedChecks": [],
        "error": None,
    }


class PublicInputValidationTest(unittest.TestCase):
    def test_external_wisp_endpoint_requires_public_wss_without_credentials(
        self,
    ) -> None:
        self.assertEqual(
            public_smoke.validate_public_wisp_endpoint(PUBLIC_ENDPOINT),
            PUBLIC_ENDPOINT,
        )
        self.assertEqual(
            public_smoke.validate_public_wisp_endpoint(
                "wss://Relay.Public.Example.Com:443/wisp/"
            ),
            PUBLIC_ENDPOINT,
        )
        for endpoint in (
            "ws://relay.public.example.com/wisp/",
            "wss://localhost/wisp/",
            "wss://127.0.0.1/wisp/",
            "wss://127.1/wisp/",
            "wss://0177.0.0.1/wisp/",
            "wss://0x7f.0x0.0x0.0x1/wisp/",
            "wss://[::1]/wisp/",
            "wss://[malformed/wisp/",
            "wss://relay.test/wisp/",
            "wss://relay.local/wisp/",
            "wss://relay.public.example.com/wisp",
            "wss://user@relay.public.example.com/wisp/",
            "wss://relay.public.example.com/wisp/?token=forbidden",
            "wss://relay.public.example.com/wisp/#fragment",
            "wss://relay.public.example.com:invalid/wisp/",
            "wss://relay.public.example.com/wisp/\x00",
            "wss://relay.public.example.com/wisp/\ud800",
            "wss://relay.public.example.com/wisp/ with-space",
            "wss://relay.public.example.com/wisp/%00",
            "wss://relay.public.example.com/wisp/%20",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(M0Error):
                    public_smoke.validate_public_wisp_endpoint(endpoint)

    def test_public_probe_requires_https_on_port_443_without_userinfo(
        self,
    ) -> None:
        self.assertEqual(
            public_smoke.validate_public_probe_url(PUBLIC_PROBE_URL),
            PUBLIC_PROBE_URL,
        )
        self.assertEqual(
            public_smoke.validate_public_probe_url(
                "https://probe.public.example.com:443/static/public-v1"
            ),
            "https://probe.public.example.com/static/public-v1",
        )
        for probe_url in (
            "http://probe.public.example.com/static/public-v1",
            "https://localhost/static/public-v1",
            "https://127.0.0.1/static/public-v1",
            "https://127.1/static/public-v1",
            "https://0177.0.0.1/static/public-v1",
            "https://0x7f.0x0.0x0.0x1/static/public-v1",
            "https://[::1]/static/public-v1",
            "https://[malformed/static/public-v1",
            "https://probe.test/static/public-v1",
            "https://probe.local/static/public-v1",
            "https://user@probe.public.example.com/static/public-v1",
            "https://probe.public.example.com/static/public-v1?cache=1",
            "https://probe.public.example.com/static/public-v1#fragment",
            "https://probe.public.example.com:444/static/public-v1",
            "https://probe.public.example.com:invalid/static/public-v1",
            "https://probe.public.example.com/static/../public-v1",
            "https://probe.public.example.com/static/%2e%2e/public-v1",
            "https://probe.public.example.com/static/public-v1\x00",
            "https://probe.public.example.com/static/public-v1\ud800",
            "https://probe.public.example.com/static/public v1",
            "https://probe.public.example.com/static/public%00v1",
            "https://probe.public.example.com/static/public%20v1",
        ):
            with self.subTest(probe_url=probe_url):
                with self.assertRaises(M0Error):
                    public_smoke.validate_public_probe_url(probe_url)

    def test_public_host_policy_rejects_literals_and_local_only_names(self) -> None:
        for hostname in (
            "",
            "localhost",
            "service.localhost",
            "service.local",
            "probe.test",
            "probe.example",
            "probe.invalid",
            "hiddenservice.onion",
            "home.arpa",
            "gateway.home.arpa",
            "public.example.com.",
            "127.0.0.1",
            "127.1",
            "0177.0.0.1",
            "0x7f.0x0.0x0.0x1",
            "::1",
            "single-label",
            "bad_label.public.example.com",
        ):
            with self.subTest(hostname=hostname):
                self.assertFalse(public_smoke._is_public_dns_hostname(hostname))


class PublicSmokeRunnerContractTest(unittest.TestCase):
    def assert_public_result_rejected(self, result: dict[str, object]) -> None:
        with self.assertRaises(M0Error):
            public_smoke.validate_public_result(
                result,
                expected_versions=VERSIONS,
                expected_status=200,
                expected_protocol="h2",
                public_wisp_endpoint=PUBLIC_ENDPOINT,
                public_probe_url=PUBLIC_PROBE_URL,
            )

    def test_smoke_url_carries_runtime_only_inputs_to_the_local_host(self) -> None:
        url = public_smoke.public_smoke_url(
            FakeServer(),
            "result-token",
            VERSIONS,
            public_wisp_endpoint=PUBLIC_ENDPOINT,
            public_probe_url=PUBLIC_PROBE_URL,
            expected_status=200,
            expected_protocol="h2",
            timeout_seconds=121.5,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, 38123)
        query = parse_qs(parsed.query)
        self.assertEqual(query["case"], [m3_content_server.M5_PUBLIC_HTTPS_CASE])
        self.assertEqual(query["module"], [
            "/__m3__/artifacts/content_shell_wasm_m5_public_test.js"
        ])
        self.assertEqual(query["wisp_endpoint"], [PUBLIC_ENDPOINT])
        self.assertEqual(query["m5_public_url"], [PUBLIC_PROBE_URL])
        self.assertEqual(query["m5_public_status"], ["200"])
        self.assertEqual(query["m5_public_protocol"], ["h2"])
        self.assertEqual(query["timeout_ms"], ["121500"])

    def test_public_result_requires_redacted_h2_navigation_evidence(self) -> None:
        result = passing_result()
        public_smoke.validate_public_result(
            result,
            expected_versions=VERSIONS,
            expected_status=200,
            expected_protocol="h2",
            public_wisp_endpoint=PUBLIC_ENDPOINT,
            public_probe_url=PUBLIC_PROBE_URL,
        )

        invalid_protocol = passing_result()
        invalid_protocol["readiness"]["navigation"]["connectionProtocol"] = "h3"  # type: ignore[index]
        self.assert_public_result_rejected(invalid_protocol)

        stale_frame = passing_result()
        stale_frame["publicFrame"]["id"] = 1  # type: ignore[index]
        self.assert_public_result_rejected(stale_frame)

        leaked_endpoint = passing_result()
        leaked_endpoint["logs"]["stderr"].append(PUBLIC_ENDPOINT)  # type: ignore[index]
        self.assert_public_result_rejected(leaked_endpoint)

        escaped_probe = passing_result()
        escaped_probe["logs"]["stdout"].append(quote(PUBLIC_PROBE_URL, safe=""))  # type: ignore[index]
        self.assert_public_result_rejected(escaped_probe)

        for leaked_value in (
            "//probe.public.example.com/static/public-v1",
            quote(quote(PUBLIC_PROBE_URL, safe=""), safe=""),
        ):
            with self.subTest(leaked_value=leaked_value):
                invalid = passing_result()
                invalid["logs"]["stdout"].append(leaked_value)  # type: ignore[index]
                self.assert_public_result_rejected(invalid)

    def test_public_result_rejects_type_coerced_control_fields(self) -> None:
        mutations = (
            (("protocol",), True),
            (("initialFrame", "width"), 800.0),
            (("publicFrame", "height"), 600.0),
            (("navigationResult", "ok"), 1),
            (("publicDevtoolsNetworkEnabled", "protocol"), True),
            (("publicDevtoolsNetworkEnabled", "networkEnabled"), 1),
            (("readiness", "navigation", "committed"), 1),
            (("readiness", "navigation", "responseCode"), 200.0),
            (("shutdown", "exitCode"), False),
            (("shutdown", "runtimeExitCode"), False),
            (("readiness", "fatalErrors"), ()),
            (("failedChecks",), ()),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                invalid = passing_result()
                target: dict[str, object] = invalid
                for field in path[:-1]:
                    target = target[field]  # type: ignore[assignment]
                target[path[-1]] = value
                self.assert_public_result_rejected(invalid)

    def test_public_result_requires_complete_cdp_and_wisp_evidence(self) -> None:
        invalid_values = {
            "networkEnabled": False,
            "documentRequest": False,
            "responseReceived": False,
            "loadingFinished": False,
            "requestIdCorrelated": False,
            "responseStatus": 201,
            "responseProtocol": "http/1.1",
            "wispWebSocketOpened": False,
            "wispHandshakeReady": False,
            "wispConfirmedStream": False,
            "wispDestinationMatched": False,
            "events": ["Network.requestWillBeSent:document"],
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                invalid = passing_result()
                trace = invalid["readiness"]["publicDevtoolsNetwork"]  # type: ignore[index]
                trace[field] = value  # type: ignore[index]
                self.assert_public_result_rejected(invalid)

        type_confusions = (
            ("protocol", True),
            ("responseStatus", True),
            ("networkEnabled", 1),
            ("documentRequest", 1),
            ("state", 1),
            ("responseProtocol", 1),
            ("events", ["Network.requestWillBeSent:document", 1]),
        )
        for field, value in type_confusions:
            with self.subTest(type_confusion=field):
                invalid = passing_result()
                trace = invalid["readiness"]["publicDevtoolsNetwork"]  # type: ignore[index]
                trace[field] = value  # type: ignore[index]
                self.assert_public_result_rejected(invalid)

        for field, value in (
            ("state", "complete"),
            ("networkEnabled", False),
            ("events", ["Network.enable"]),
            ("url", PUBLIC_PROBE_URL),
            ("requestId", "leaked-request-id"),
        ):
            with self.subTest(enable_field=field):
                invalid = passing_result()
                enabled = invalid["publicDevtoolsNetworkEnabled"]
                enabled[field] = value  # type: ignore[index]
                self.assert_public_result_rejected(invalid)

        for field, value in (
            ("url", PUBLIC_PROBE_URL),
            ("requestId", "leaked-request-id"),
            ("headers", {"x-test": "forbidden"}),
        ):
            with self.subTest(trace_field=field):
                invalid = passing_result()
                trace = invalid["readiness"]["publicDevtoolsNetwork"]  # type: ignore[index]
                trace[field] = value  # type: ignore[index]
                self.assert_public_result_rejected(invalid)

    def test_public_cdp_evidence_summary_is_fixed_and_redacted(self) -> None:
        evidence = public_smoke.public_devtools_network_evidence(
            passing_result(), expected_status=200, expected_protocol="h2"
        )
        self.assertEqual(
            evidence,
            public_smoke.expected_public_devtools_network_evidence(
                expected_status=200, expected_protocol="h2"
            ),
        )
        serialized = json.dumps(evidence, sort_keys=True)
        self.assertIsNone(public_smoke.URL_LIKE_VALUE_PATTERN.search(serialized))
        with self.assertRaises(M0Error):
            public_smoke.expected_public_devtools_network_evidence(
                expected_status=True, expected_protocol="h2"
            )

    def test_public_provenance_is_fixed_and_type_sensitive(self) -> None:
        provenance = public_smoke.public_provenance(VERSIONS)
        self.assertEqual(
            provenance,
            {
                "protocol": public_smoke.PUBLIC_PROVENANCE_PROTOCOL,
                "versions": VERSIONS,
            },
        )
        self.assertEqual(
            public_smoke.validate_public_provenance(
                provenance, expected_versions=VERSIONS
            ),
            provenance,
        )

        stale_versions = {**VERSIONS, "port": "stale-port-revision"}
        invalid_provenance = (
            ("missing_field", {"protocol": 1}),
            (
                "extra_field",
                {**provenance, "unexpected": "not allowed"},
            ),
            (
                "boolean_protocol",
                {**provenance, "protocol": True},
            ),
            (
                "float_protocol",
                {**provenance, "protocol": 1.0},
            ),
            (
                "missing_version",
                {
                    "protocol": 1,
                    "versions": {
                        key: value
                        for key, value in VERSIONS.items()
                        if key != "port"
                    },
                },
            ),
            (
                "extra_version",
                {
                    "protocol": 1,
                    "versions": {**VERSIONS, "unexpected": "not allowed"},
                },
            ),
            (
                "empty_version",
                {"protocol": 1, "versions": {**VERSIONS, "port": ""}},
            ),
            (
                "boolean_version",
                {"protocol": 1, "versions": {**VERSIONS, "port": True}},
            ),
            ("stale_versions", {"protocol": 1, "versions": stale_versions}),
        )
        for name, value in invalid_provenance:
            with self.subTest(name=name):
                with self.assertRaises(M0Error):
                    public_smoke.validate_public_provenance(
                        value, expected_versions=VERSIONS
                    )

        with self.assertRaises(M0Error):
            public_smoke.public_provenance({**VERSIONS, "port": True})

    def test_failure_diagnostics_redact_runtime_only_inputs(self) -> None:
        endpoint_query_value = (
            "wss://Relay.Public.Example.Com:443/wisp/"
        )
        probe_query_value = (
            "https://Probe.Public.Example.Com:443/static/public-v1"
        )
        scheme_relative_probe = "//probe.public.example.com/static/public-v1"
        endpoint_hostname = "relay.public.example.com"
        endpoint_authority = "relay.public.example.com:443"
        probe_hostname = "probe.public.example.com"
        probe_authority = "probe.public.example.com:443"
        double_escaped_endpoint = quote(quote(PUBLIC_ENDPOINT, safe=""), safe="")
        double_escaped_probe = quote(quote(PUBLIC_PROBE_URL, safe=""), safe="")
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic_path = public_smoke.write_failure_diagnostics(
                Path(temporary),
                stage="validate_runtime_contract",
                error=M0Error(f"configured probe failed: {PUBLIC_PROBE_URL}"),
                context={
                    "endpoint": endpoint_query_value,
                    "escaped_probe": quote_plus(PUBLIC_PROBE_URL),
                    "scheme_relative_probe": scheme_relative_probe,
                    "double_escaped_endpoint": double_escaped_endpoint,
                    "endpoint_hostname": endpoint_hostname,
                    endpoint_authority: "configured endpoint authority as a key",
                    PUBLIC_PROBE_URL: "configured probe appears as a key",
                },
                browser_path=None,
                browser_version=None,
                browser=None,
                browser_stderr=deque([
                    f"endpoint={quote(PUBLIC_ENDPOINT, safe='')}"
                ]),
                result={
                    "error": f"probe={PUBLIC_PROBE_URL}",
                    "endpoint": PUBLIC_ENDPOINT,
                    "scheme_relative_probe": scheme_relative_probe,
                    "double_escaped_probe": double_escaped_probe,
                    "probe_hostname": probe_hostname,
                    probe_authority: "configured probe authority as a key",
                    PUBLIC_ENDPOINT: "configured endpoint appears as a key",
                },
                public_wisp_endpoint=endpoint_query_value,
                public_probe_url=probe_query_value,
            )
            serialized = diagnostic_path.read_text(encoding="utf-8")
            for secret in (
                PUBLIC_ENDPOINT,
                PUBLIC_PROBE_URL,
                endpoint_query_value,
                probe_query_value,
                quote(PUBLIC_ENDPOINT, safe=""),
                quote(PUBLIC_PROBE_URL, safe=""),
                quote_plus(PUBLIC_ENDPOINT),
                quote_plus(PUBLIC_PROBE_URL),
                scheme_relative_probe,
                double_escaped_endpoint,
                double_escaped_probe,
                endpoint_hostname,
                endpoint_authority,
                probe_hostname,
                probe_authority,
            ):
                with self.subTest(secret=secret):
                    self.assertNotIn(secret, serialized)
            self.assertIn("<redacted>", serialized)
            self.assertIsNone(
                public_smoke.URL_LIKE_VALUE_PATTERN.search(serialized)
            )

    def test_public_case_is_an_explicit_result_server_case(self) -> None:
        self.assertIn(
            m3_content_server.M5_PUBLIC_HTTPS_CASE,
            m3_content_server.M3_RESULT_CASES,
        )
        self.assertTrue(
            m3_content_server.is_supported_result_case(
                m3_content_server.M5_PUBLIC_HTTPS_CASE
            )
        )


class PublicHttpsSourceContractTest(unittest.TestCase):
    def test_public_host_redacts_configured_hostname_and_authority_forms(self) -> None:
        node = shutil.which("node")
        if node is None:
            pinned_node = (
                Path(__file__).resolve().parents[3]
                / "third_party/emsdk/node/22.16.0_64bit/bin/node"
            )
            node = str(pinned_node) if pinned_node.is_file() else None
        if node is None:
            self.skipTest("Node is unavailable")

        host = (
            Path(__file__).resolve().parents[1] / "host/content_shell_host.js"
        )
        script = r"""
import fs from "node:fs";

const assert = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};
const source = fs.readFileSync(__HOST_PATH__, "utf8");
const start = source.indexOf("function m5PublicRedactionVariants(values) {");
const end = source.indexOf("\nexport class ChromiumWasmM3Host", start);
assert(start >= 0 && end > start, "public redaction helpers were not found");
const helpers = new Function(source.slice(start, end) +
    "\nreturn {m5PublicRedactionVariants, redactM5PublicRuntimeValue};")();
const endpoint = "wss://relay.public.example.com/wisp/";
const probe = "https://probe.public.example.com/static/public-v1";
const redacted = helpers.redactM5PublicRuntimeValue({
  "relay.public.example.com:443": "probe.public.example.com",
  nested: ["relay.public.example.com", "probe.public.example.com:443"],
}, helpers.m5PublicRedactionVariants([endpoint, probe]));
const serialized = JSON.stringify(redacted);
for (const secret of [
  "relay.public.example.com",
  "relay.public.example.com:443",
  "probe.public.example.com",
  "probe.public.example.com:443",
]) {
  assert(!serialized.includes(secret), "host result leaked " + secret);
}
assert(serialized.includes("<redacted-url>"),
    "host result did not replace sensitive authority forms");
console.log("M5_PUBLIC_HOST_REDACTION:PASS");
""".replace("__HOST_PATH__", json.dumps(str(host)))
        completed = subprocess.run(
            [node, "--input-type=module", "--eval", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("M5_PUBLIC_HOST_REDACTION:PASS", completed.stdout)

    def test_public_target_is_test_only_and_never_uses_the_controlled_root(self) -> None:
        build = source("content/shell/BUILD.gn")
        target = build.split(
            'executable("content_shell_wasm_m5_public_test") {', 1
        )[1].split("\n  }\n} else {", 1)[0]
        main = source("content/shell/app/shell_main.cc")

        self.assertIn("testonly = true", target)
        self.assertIn('CONTENT_SHELL_WASM_M5_PUBLIC_TEST=1', target)
        self.assertNotIn("wasm_m5_test_trust", target)
        self.assertNotIn("generate_wasm_m5_test_root_cert", target)
        self.assertNotIn('"//net"', target)
        normal_target = build.split(
            'executable("content_shell_wasm") {', 1
        )[1].split(
            '\n  # This target exists solely for the controlled M5', 1
        )[0]
        controlled_target = build.split(
            'executable("content_shell_wasm_m5_test") {', 1
        )[1].split(
            '\n  # This executable is intentionally distinct', 1
        )[0]
        self.assertNotIn("CONTENT_SHELL_WASM_M5_PUBLIC_TEST", normal_target)
        self.assertNotIn(
            "CONTENT_SHELL_WASM_M5_PUBLIC_TEST", controlled_target
        )
        public_mode = main.split(
            "#elif defined(CONTENT_SHELL_WASM_M5_PUBLIC_TEST)", 1
        )[1].split("#endif", 1)[0]
        self.assertIn(
            "EnableWasmM5PublicNetworkTestModeForTesting();", public_mode
        )
        self.assertNotIn("InstallWasmM5TestTrustRoot", public_mode)

    def test_native_public_loader_has_a_bounded_exact_https_boundary(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        predicate = api.split(
            "bool IsM5PublicHttpsUrl(const GURL& candidate_url) {", 1
        )[1].split("\n}\n\nbool IsObservedWasmHostUrl", 1)[0]
        loader = api.split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_public_url(",
            1,
        )[1].split(
            "\n}\n\nEMSCRIPTEN_KEEPALIVE int chromium_wasm_host_text_input",
            1,
        )[0]
        finish = api.split(
            "void DidFinishNavigation(NavigationHandle* navigation_handle) override {",
            1,
        )[1].split(
            "void DocumentOnLoadCompletedInPrimaryMainFrame() override", 1
        )[0]

        self.assertIn("kMaximumM5PublicUrlBytes = 2048", api)
        self.assertIn("IsWasmM5PublicNetworkTestModeEnabled()", predicate)
        self.assertIn("SchemeIs(url::kHttpsScheme)", predicate)
        self.assertIn("EffectiveIntPort() == 443", predicate)
        self.assertIn("!candidate_url.has_username()", predicate)
        self.assertIn("!candidate_url.has_query()", predicate)
        self.assertIn("!candidate_url.HostIsIPAddress()", predicate)
        self.assertIn("IsM5PublicDnsHostname(host)", predicate)
        self.assertIn("strnlen(public_url", loader)
        self.assertIn("IsM5PublicHttpsUrl(url)", loader)
        self.assertIn("GetResponseHeaders()", finish)
        self.assertIn("GetConnectionInfo()", finish)
        self.assertIn("HttpConnectionInfoToString", finish)
        self.assertIn("IsErrorPage()", finish)
        self.assertIn(
            "m5_public_navigation_handle_ == navigation_handle", finish
        )
        self.assertNotIn(
            "m5_public_navigation_handle_ == navigation_handle ||",
            finish,
        )
        self.assertIn(
            "navigation_url.spec().size() > kMaximumM5PublicUrlBytes",
            finish,
        )

    def test_public_host_reports_keep_the_url_out_of_results(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        runner = source("tools/wasm/run_m5_public_https_smoke.py")

        policy = host.split("function normalizeM5PublicHTTPSURL(value) {", 1)[
            1
        ].split("\nexport class ChromiumWasmM3Host", 1)[0]
        report = host.split("_reportM5PublicNavigation(value) {", 1)[1].split(
            "\n  _reportM5PublicNavigationError", 1
        )[0]
        stored_navigation = report.split("this.#navigation = {", 1)[1].split(
            "\n      };", 1
        )[0]

        self.assertIn("isM5PublicHostname(parsed.hostname)", policy)
        self.assertIn('parsed.protocol !== "https:"', policy)
        self.assertIn("parsed.port", policy)
        self.assertIn("parsed.username", policy)
        self.assertIn("parsed.search", policy)
        self.assertIn("reportM5PublicNavigation(report)", host)
        self.assertIn("reportM5PublicNavigationError(report)", host)
        self.assertIn("m5PublicRedactionVariants", host)
        self.assertIn("redactM5PublicRuntimeValue", host)
        self.assertIn("parsed.hostname", host)
        self.assertIn("redactM5PublicRuntimeValue(key, variants)", host)
        self.assertIn("publicFrame", host)
        self.assertIn("M5_PUBLIC_HTTPS_FIXTURE", host)
        self.assertIn("m5PublicNavigationFinished", host)
        self.assertIn("readiness.frame.id > initialFrame.id", host)
        self.assertIn("await postResult(token, redactedResult)", host)
        self.assertIn("chromium_wasm_report_m5_public_navigation", bridge)
        self.assertIn("connectionProtocol", stored_navigation)
        self.assertNotIn("url:", stored_navigation)
        self.assertIn("--public-wisp-endpoint", runner)
        self.assertIn("--public-probe-url", runner)
        self.assertGreaterEqual(runner.count("required=True"), 4)
        self.assertIn('"<redacted>"', runner)
        self.assertNotIn("m5_wisp_test_server", runner)

    def test_public_cdp_trace_requires_the_atomic_wisp_completion_proof(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        host = source("tools/wasm/host/content_shell_host.js")
        host_bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        transport_header = source("net/socket/wisp_transport_wasm.h")
        transport = source("net/socket/wisp_transport_wasm.cc")
        wisp_bridge = source("net/socket/wisp_host_bridge_wasm.js")
        runner = source("tools/wasm/run_m5_public_https_smoke.py")

        recorder = api.split(
            "class M5PublicDevToolsNetworkRecorder final : "
            "public DevToolsAgentHostClient {",
            1,
        )[1].split("\nvoid ReportTextInputDelivery", 1)[0]
        public_report = host.split(
            "_reportM5PublicDevToolsNetwork(value) {", 1
        )[1].split("\n  _reportM5PageProbe", 1)[0]
        public_smoke = host.split(
            "async function runM5PublicHttpsSmokeFromQuery() {", 1
        )[1].split("\nexport async function runContentShellSmokeFromQuery", 1)[0]

        for marker in (
            "DevToolsAgentHost::GetOrCreateFor(web_contents)",
            'R"({"id":1,"method":"Network.enable"})"',
            "IsM5PublicHttpsUrl(request_url)",
            "Network.requestWillBeSent:document",
            "Network.responseReceived:document",
            "Network.loadingFinished:document",
            "expected_document_url.host(), static_cast<uint16_t>(port)",
            "request_url != expected_document_url_",
            "GetWasmWispTransportDiagnostics()",
            "kWasmWispDiagnosticAllRequired",
            "wispDestinationMatched",
            "chromium_wasm_report_m5_public_devtools_network",
        ):
            with self.subTest(recorder_marker=marker):
                self.assertIn(marker, recorder)
        self.assertIn(
            "diagnostics->completion_flags != "
            "net::kWasmWispDiagnosticAllRequired",
            recorder,
        )
        for forbidden in (
            'report.Set("url"',
            'report.Set("requestId"',
            'report.Set("headers"',
            'report.Set("cookies"',
            "request_url.spec()",
        ):
            with self.subTest(recorder_forbidden=forbidden):
                self.assertNotIn(forbidden, recorder)

        self.assertIn(
            "chromium_wasm_report_m5_public_devtools_network__proxy: 'sync'",
            host_bridge,
        )
        self.assertIn("reportM5PublicDevToolsNetwork(report)", host)
        self.assertIn("isM5PublicDevToolsNetworkEnabled", host)
        self.assertIn("hasM5PublicDevToolsNetworkLog", host)
        self.assertIn("m5:public-devtools-network:enabled", public_report)
        self.assertIn("m5:public-devtools-network:complete", public_report)
        self.assertIn("publicDevtoolsNetworkEnabled", public_smoke)
        self.assertLess(
            public_smoke.index("isM5PublicDevToolsNetworkEnabled("),
            public_smoke.index("loadM5PublicHTTPSURL(testURL)"),
        )
        self.assertIn("hasM5PublicDevToolsNetworkLog", public_smoke)

        for marker in (
            "kWasmWispDiagnosticWebSocketOpened = 1 << 0",
            "kWasmWispDiagnosticHandshakeReady = 1 << 1",
            "kWasmWispDiagnosticStreamConfirmed = 1 << 2",
            "BeginWasmWispTransportDiagnostics(std::string_view hostname,",
            "GetWasmWispTransportDiagnostics()",
            "chromium_wasm_wisp_diagnostics_completion_flags()",
            "chromium_wasm_wisp_diagnostics_begin_evidence_window(\n    const char* hostname,",
            "IsValidDiagnosticFlags",
            "diagnosticsCompletionFlags()",
            "beginDiagnosticsEvidenceWindow(hostnamePointer, hostnameLength, port)",
            "diagnosticEvidenceEpoch: this.diagnosticEvidenceEpoch",
            "this.diagnosticEvidenceWindowEpoch = this.diagnosticEvidenceEpoch",
            "diagnosticEvidenceWindowTarget",
            "stream.hostname.toLowerCase() === target.hostname",
            "stream.port === target.port",
            "this.diagnosticEvidenceWindowConfirmed = true",
            "this.webSocketOpenCount += 1",
            "this.readyConnectionCount += 1",
            "this.confirmedStreamCount += 1",
        ):
            with self.subTest(wisp_marker=marker):
                self.assertIn(
                    marker,
                    transport_header + transport + wisp_bridge,
                )
        public_loader = api.split(
            "void LoadM5PublicUrlOnUiThread(GURL url) {", 1
        )[1].split("\n}\n\nvoid DeactivateHostWindowOnUiThread", 1)[0]
        self.assertLess(
            public_loader.index("BeginWispEvidenceWindow(\n          url)"),
            public_loader.index("LoadUrlOnUiThread(std::move(url))"),
        )
        self.assertIn(
            "public HTTPS DevTools Network log does not contain the bounded ",
            runner,
        )
        self.assertIn("Chromium CDP and WISP completion trace", runner)
        self.assertIn("PUBLIC_DEVTOOLS_NETWORK_EVENTS", runner)
        self.assertIn("expected_public_devtools_network_evidence", runner)
        self.assertIn("PUBLIC_PROVENANCE_PROTOCOL", runner)
        self.assertIn("validate_public_provenance", runner)
        self.assertIn('f"{SENTINEL}:PROVENANCE "', runner)
        self.assertIn('f"{SENTINEL}:EVIDENCE "', runner)
        self.assertIn("_is_safe_public_url_string", runner)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded M5 network host-test lanes."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M5WispNetworkHostContractTest(unittest.TestCase):
    def test_m5_url_is_a_fixed_https_fixture_not_a_general_navigation_api(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        start = host.index("function normalizeM5NetworkTestURL(value)")
        end = host.index("\nexport class ChromiumWasmM3Host", start)
        url_policy = host[start:end]

        self.assertIn('M5_NETWORK_TEST_HOSTNAME = "a.test"', host)
        self.assertIn('M5_NETWORK_TEST_PATH_PREFIX = "/m5/"', host)
        self.assertIn('parsed.protocol !== "https:"', url_policy)
        self.assertIn(
            "parsed.hostname !== M5_NETWORK_TEST_HOSTNAME", url_policy
        )
        self.assertIn("!parsed.port", url_policy)
        self.assertIn("parsed.username || parsed.password", url_policy)
        self.assertIn("parsed.search || parsed.hash", url_policy)
        self.assertIn(
            "parsed.pathname.startsWith(M5_NETWORK_TEST_PATH_PREFIX)",
            url_policy,
        )

    def test_plaintext_control_is_one_exact_http_fixture_url(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        start = host.index("function normalizeM5PlaintextHttpControlURL(value)")
        end = host.index("\nexport class ChromiumWasmM3Host", start)
        url_policy = host[start:end]

        self.assertIn(
            'M5_PLAINTEXT_HTTP_CONTROL_PATH = "/m5/plaintext-control"', host
        )
        self.assertIn('parsed.protocol !== "http:"', url_policy)
        self.assertIn(
            "parsed.hostname !== M5_NETWORK_TEST_HOSTNAME", url_policy
        )
        self.assertIn("!parsed.port", url_policy)
        self.assertIn("parsed.username || parsed.password", url_policy)
        self.assertIn("parsed.search || parsed.hash", url_policy)
        self.assertIn(
            "parsed.pathname !== M5_PLAINTEXT_HTTP_CONTROL_PATH", url_policy
        )
        self.assertNotIn("startsWith(M5_NETWORK_TEST_PATH_PREFIX)", url_policy)

    def test_data_navigation_stays_separate_from_the_test_only_m5_loader(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        data_loader = host.split("  async loadURL(url) {", 1)[1].split(
            "\n  async loadM5PlaintextHttpControlURL(url) {", 1
        )[0]
        plaintext_loader = host.split(
            "  async loadM5PlaintextHttpControlURL(url) {", 1
        )[1].split("\n  async loadM5NetworkURL(url) {", 1)[0]
        m5_loader = host.split("  async loadM5NetworkURL(url) {", 1)[1].split(
            "\n  async injectInput(event)", 1
        )[0]
        post_m5_loader = host.split("  #postM5TestNavigation(", 1)[1].split(
            "\n  #restoreM5TestNavigation", 1
        )[0]

        self.assertIn('parsed.protocol !== "data:"', data_loader)
        self.assertIn('"chromium_wasm_host_load_url"', data_loader)
        self.assertNotIn("chromium_wasm_host_load_m5_url", data_loader)
        self.assertNotIn("plaintext_http_control", data_loader)

        self.assertIn("normalizeM5PlaintextHttpControlURL(url)", plaintext_loader)
        self.assertIn("M5 plaintext HTTP control must be the first navigation", plaintext_loader)
        self.assertIn(
            '"chromium_wasm_host_load_m5_plaintext_http_control_url"',
            plaintext_loader,
        )
        self.assertIn('scheme: "http"', plaintext_loader)

        self.assertIn("this.#wispConfigured", m5_loader)
        self.assertIn("normalizeM5NetworkTestURL(url)", m5_loader)
        self.assertIn(
            "M5 HTTPS navigation requires a committed plaintext HTTP control",
            m5_loader,
        )
        self.assertIn("M5 TLS rejection navigation requires an initial HTTPS fixture", m5_loader)
        self.assertIn("M5_NAVIGATION_PHASE.PLAINTEXT_HTTP_CONTROL", m5_loader)
        self.assertIn("M5_NAVIGATION_PHASE.HTTPS_FIXTURE", m5_loader)
        self.assertIn('exportName: "chromium_wasm_host_load_m5_url"', m5_loader)
        self.assertIn(
            "this.#m5NetworkTestActive = true;", post_m5_loader
        )
        self.assertIn("this.#m5NetworkPhase = phase;", post_m5_loader)
        self.assertIn("this.#pageProbe = {};", post_m5_loader)

    def test_m5_reports_and_smoke_proof_are_separate_from_data_reports(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        m5_smoke = host.split(
            "async function runM5WispNetworkSmokeFromQuery() {", 1
        )[1].split("\nexport async function runContentShellSmokeFromQuery()", 1)[0]

        self.assertIn("reportM5Navigation(report)", host)
        self.assertIn("reportM5NavigationError(report)", host)
        self.assertIn("reportM5Download(report)", host)
        self.assertIn("reportM5PageProbe(report)", host)
        self.assertIn("reportM5PlaintextHttpControlNavigation(report)", host)
        self.assertIn("reportM5PlaintextHttpControlNavigationError(report)", host)
        self.assertIn("reportM5PlaintextHttpControlPageProbe(report)", host)
        self.assertIn("_reportM5Navigation(value)", host)
        self.assertIn("_reportM5NavigationError(value)", host)
        self.assertIn("_reportM5Download(value)", host)
        self.assertIn("_reportM5PageProbe(value)", host)
        self.assertIn("_reportM5PlaintextHttpControlNavigation(value)", host)
        self.assertIn("_reportM5PlaintextHttpControlNavigationError(value)", host)
        self.assertIn("_reportM5PlaintextHttpControlPageProbe(value)", host)
        self.assertIn("M5_TLS_NAME_MISMATCH_NET_ERROR = -200", host)
        self.assertIn('report.scheme !== "https"', host)
        self.assertIn(
            "report.netError !== M5_TLS_NAME_MISMATCH_NET_ERROR", host
        )
        self.assertIn("!isM5NetworkPageProbeIdentity(report)", host)
        self.assertIn(
            "!isM5PlaintextHttpControlPageProbeIdentity(report)", host
        )
        self.assertIn("m5:ignored-stale:https-page-probe", host)
        self.assertIn(
            "m5:ignored-stale:plaintext-http-control-page-probe", host
        )
        self.assertIn("hasM5NetworkPageProbe(readiness.pageProbe)", host)
        self.assertIn("runM5WispNetworkSmokeFromQuery", host)
        self.assertIn("let slowStreamHeartbeat = null;", m5_smoke)
        self.assertIn("let slowStreamHeartbeatStart = null;", m5_smoke)
        self.assertIn('"m5_plaintext_http_control_url"', host)
        self.assertIn('parameters.get("m5_tls_failure_url")', host)
        self.assertIn("plaintextHttpControlReadiness.navigation?.scheme === \"http\"", host)
        self.assertIn("tlsFailureReadiness.navigation?.netError", host)
        self.assertIn("if (selectedCase === M5_NETWORK_CASE)", host)
        for marker in (
            "pageProbe?.h2Fetch === true",
            'pageProbe?.h2Protocol === "h2"',
            "pageProbe?.redirected === true",
            "pageProbe?.cacheStored === true",
            "pageProbe?.cacheRevalidated === true",
            "pageProbe?.cspConnectSrcBlocked === true",
            "pageProbe?.activeMixedContentBlocked === true",
            "pageProbe?.activeMixedContentTargetUrl",
            "pageProbe?.activeMixedContentErrorName === \"TypeError\"",
            "pageProbe?.activeMixedContentCspAllowed === true",
            "pageProbe?.localGatewayMappedRequestStarted === true",
            "pageProbe?.localGatewayMappedResponse === true",
            "pageProbe?.localGatewayBlockedRequestStarted === true",
            "pageProbe?.localGatewayBlocked === true",
            "pageProbe?.cancelStreamStarted === true",
            "pageProbe?.cancelStreamReceivedFirstChunk === true",
            "pageProbe?.cancelStreamAborted === true",
            "pageProbe?.cancelStreamErrorName === \"AbortError\"",
            "pageProbe?.cancelStreamProof === true",
            "pageProbe?.slowStreamStarted === true",
            "pageProbe?.slowStreamFirstStage === true",
            "pageProbe?.slowStreamSecondStage === true",
            "pageProbe?.slowStreamThirdStage === true",
            "pageProbe?.slowStreamComplete === true",
            "pageProbe?.slowStreamProof === true",
            "pageProbe?.slowStreamConsumerPauseStarted === true",
            "pageProbe?.slowStreamConsumerBurstRead === true",
            "pageProbe?.slowStreamConsumerResume === true",
            "Number.isSafeInteger(pageProbe?.slowStreamElapsedMs)",
            "Number.isSafeInteger(pageProbe?.slowStreamFirstToSecondStageDelayMs)",
            "Number.isSafeInteger(pageProbe?.slowStreamSecondToThirdStageDelayMs)",
            "Number.isSafeInteger(pageProbe?.slowStreamConsumerPauseElapsedMs)",
            "Number.isSafeInteger(pageProbe?.slowStreamConsumerPauseTimerTicks)",
            "Number.isSafeInteger(pageProbe?.slowStreamTimerTicksWhileWaiting)",
            "pageProbe?.slowStreamElapsedMs >= M5_SLOW_STREAM_MIN_ELAPSED_MS",
            "pageProbe?.slowStreamFirstToSecondStageDelayMs >=",
            "pageProbe?.slowStreamSecondToThirdStageDelayMs >=",
            "pageProbe?.slowStreamConsumerPauseElapsedMs >=",
            "pageProbe?.slowStreamConsumerPauseTimerTicks >=",
            "pageProbe?.slowStreamTimerTicksWhileWaiting >=",
            "snapshotM5SlowStreamHostHeartbeat",
            "makeM5SlowStreamHostHeartbeat",
            "hasM5SlowStreamHostHeartbeat(slowStreamHeartbeat)",
            "pageProbe?.multiplexRequestsStarted === true",
            "pageProbe?.multiplexH2Response === true",
            "pageProbe?.multiplexH1Response === true",
            "pageProbe?.multiplexComplete === true",
            "pageProbe?.largeDownloadNavigationRequested === true",
            "pageProbe?.largeDownloadNativeComplete === true",
            "hasM5DownloadManagerLog(readiness.m5Download)",
            "pageProbe?.reconnectStreamStarted === true",
            "pageProbe?.reconnectFirstChunkReceived === true",
            "pageProbe?.reconnectFirstChunkAck === true",
            "pageProbe?.reconnectDisconnectRequested === true",
            "pageProbe?.reconnectStreamFailed === true",
            'pageProbe?.reconnectStreamErrorName === "TypeError"',
            "pageProbe?.reconnectRecovered === true",
            'pageProbe?.reconnectRecoveryProtocol === "h2"',
            "pageProbe?.corsFetch === true",
            "pageProbe?.webSocketEcho === true",
            "pageProbe?.altSvcH3Advertised === true",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

    def test_m5_local_gateway_page_probe_fields_are_controlled_only(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        controlled_smoke = host.split(
            "async function runM5WispNetworkSmokeFromQuery() {", 1
        )[1].split("\nasync function runM5PublicHttpsSmokeFromQuery()", 1)[0]
        public_smoke = host.split(
            "async function runM5PublicHttpsSmokeFromQuery() {", 1
        )[1].split("\nexport async function runContentShellSmokeFromQuery()", 1)[0]

        for field in (
            "localGatewayMappedRequestStarted",
            "localGatewayMappedResponse",
            "localGatewayBlockedRequestStarted",
            "localGatewayBlocked",
        ):
            with self.subTest(field=field):
                self.assertIn(
                    f'typeof pageProbe?.{field} === "boolean"', host
                )
                self.assertIn(f"pageProbe?.{field} === true", host)
                self.assertIn(f"pageProbe.{field} === true", controlled_smoke)
                self.assertNotIn(field, public_smoke)

    def test_m5_devtools_network_trace_is_in_process_bounded_and_required(
        self,
    ) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        host_api = source("content/shell/browser/wasm_host_api.cc")
        runner = source("tools/wasm/run_m5_wisp_smoke.py")
        m5_smoke = host.split(
            "async function runM5WispNetworkSmokeFromQuery() {", 1
        )[1].split("\nasync function runM5PublicHttpsSmokeFromQuery()", 1)[0]
        recorder = host_api.split(
            "class M5DevToolsNetworkRecorder final : public DevToolsAgentHostClient {",
            1,
        )[1].split("\nvoid ReportTextInputDelivery", 1)[0]

        self.assertIn('#include "content/public/browser/devtools_agent_host.h"', host_api)
        self.assertIn("DevToolsAgentHost::GetOrCreateFor(web_contents)", recorder)
        self.assertIn("if (IsWasmM5NetworkTestModeEnabled())", host_api)
        self.assertIn('R"({"id":1,"method":"Network.enable"})"', recorder)
        for event in (
            "Network.requestWillBeSent",
            "Network.responseReceived",
            "Network.loadingFinished",
            "Network.loadingFailed",
        ):
            with self.subTest(event=event):
                self.assertIn(event, recorder)
        self.assertIn("request_id != request_id_", recorder)
        self.assertIn("kM5NetworkRedirectPath", recorder)
        self.assertIn("kM5NetworkDocumentPath", recorder)
        self.assertIn("kM5NetworkReconnectStreamPath", recorder)
        self.assertIn("kM5NetworkReconnectFailure", recorder)
        self.assertIn("RecordFailed", recorder)
        self.assertIn("reconnectInternetDisconnected", recorder)
        self.assertIn("responseStatus", recorder)
        self.assertIn("responseProtocol", recorder)
        self.assertNotIn('report.Set("url"', recorder)
        self.assertNotIn('report.Set("requestId"', recorder)
        self.assertNotIn('report.Set("headers"', recorder)
        self.assertNotIn('report.Set("cookies"', recorder)
        self.assertNotIn('report.Set("errorText"', recorder)

        self.assertIn("chromium_wasm_report_m5_devtools_network__proxy: 'sync'", bridge)
        self.assertIn("bridge.reportM5DevToolsNetwork", bridge)
        self.assertIn("reportM5DevToolsNetwork(report)", host)
        self.assertIn("_reportM5DevToolsNetwork(value)", host)
        self.assertIn("isM5DevToolsNetworkEnabled", host)
        self.assertIn("hasM5DevToolsNetworkLog", host)
        self.assertIn("m5:devtools-network:enabled", host)
        self.assertIn("m5:devtools-network:complete", host)
        self.assertIn("m5:download-manager:complete", host)
        self.assertLess(
            m5_smoke.index("M5 DevTools Network.enable did not complete"),
            m5_smoke.index("loadM5PlaintextHttpControlURL"),
        )
        self.assertIn("hasM5DevToolsNetworkLog(readiness.devtoolsNetwork)", m5_smoke)

        self.assertIn("M5_DEVTOOLS_NETWORK_EVENT_ORDER", runner)
        self.assertIn("M5 DevTools Network enable", runner)
        self.assertIn("M5 DevTools Network log", runner)
        self.assertIn("m5:devtools-network:enabled", runner)
        self.assertIn("m5:devtools-network:complete", runner)
        self.assertIn("M5 DownloadManager log", runner)
        self.assertIn("m5:download-manager:complete", runner)

    def test_m5_attachment_download_uses_download_manager_not_fetch(self) -> None:
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        fixture = source("tools/wasm/m5_wisp_test_server.js")
        host = source("tools/wasm/host/content_shell_host.js")
        host_api = source("content/shell/browser/wasm_host_api.cc")
        runner = source("tools/wasm/run_m5_wisp_smoke.py")
        recorder = host_api.split(
            "class M5DownloadRecorder final : public DownloadManager::Observer,",
            1,
        )[1].split("\nvoid ReportTextInputDelivery", 1)[0]
        m5_loader = host_api.split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_url(", 1
        )[1].split(
            "EMSCRIPTEN_KEEPALIVE int "
            "chromium_wasm_host_load_m5_plaintext_http_control_url(",
            1,
        )[0]

        self.assertIn('document.createElement("iframe")', fixture)
        self.assertIn("frame.src = largeDownloadURL", fixture)
        self.assertIn("largeDownloadNavigationRequested", fixture)
        self.assertIn("largeDownloadNativeComplete", fixture)
        self.assertIn("__chromiumWasmM5NativeDownloadComplete", fixture)
        self.assertNotIn("fetch(largeDownloadURL", fixture)
        self.assertNotIn("verifyLargeDownload", fixture)

        for marker in (
            "DownloadManager::Observer",
            "download::DownloadItem::Observer",
            "SetDownloadBehaviorForTesting",
            "DownloadSource::NAVIGATION",
            "GetOriginalUrl",
            "GetTargetFilePath",
            "GetTotalBytes",
            "GetReceivedBytes",
            "AllDataSaved",
            "DOWNLOAD_INTERRUPT_REASON_NONE",
            "PostTaskAndReplyWithResult",
            "HasExpectedM5DownloadFileContents",
            "OnDownloadDestroyed",
            "OnDownloadDropped",
            "ManagerGoingDown",
            "ArmForFixtureUrl",
            "DeprecatedGetOriginAsURL",
            "expected_fixture_origin_",
            "chromium_wasm_report_m5_download",
            "__chromiumWasmM5NativeDownloadComplete",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, recorder)
        self.assertIn("ReadAtCurrentPosAndCheck", host_api)
        self.assertNotIn("GetSuggestedFilename", recorder)
        for raw_field in ("url", "path", "guid", "headers", "error"):
            with self.subTest(raw_field=raw_field):
                self.assertNotIn(f'report.Set("{raw_field}"', recorder)

        self.assertIn("LoadM5NetworkUrlOnUiThread", m5_loader)

        self.assertIn(
            "chromium_wasm_report_m5_download__proxy: 'sync'", bridge
        )
        self.assertIn("bridge.reportM5Download", bridge)
        self.assertIn("reportM5Download(report)", host)
        self.assertIn("_reportM5Download(value)", host)
        self.assertIn("hasM5DownloadManagerLog", host)
        self.assertIn("M5_DOWNLOAD_REPORT_KEYS", host)
        self.assertIn(
            "M5 page completion requires native DownloadManager evidence", host
        )
        self.assertIn("hasM5DownloadManagerLog(this.#m5Download)", host)
        self.assertIn("hasM5DownloadManagerLog(readiness.m5Download)", host)
        self.assertIn("M5 DownloadManager log", runner)
        self.assertIn("filePatternVerified", runner)
        self.assertIn("m5:download-manager:complete", runner)

    def test_emscripten_bridge_cannot_relabel_m5_as_data_navigation(self) -> None:
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        m5_navigation = bridge.split(
            "chromium_wasm_report_m5_navigation: () => {", 1
        )[1].split("\n  },", 1)[0]
        m5_probe = bridge.split(
            "chromium_wasm_report_m5_page_probe: (probe) => {", 1
        )[1].split("\n  },", 1)[0]
        m5_failure = bridge.split(
            "chromium_wasm_report_m5_navigation_error: (netError) => {", 1
        )[1].split("\n  },", 1)[0]
        plaintext_navigation = bridge.split(
            "chromium_wasm_report_m5_plaintext_http_control_navigation: () => {",
            1,
        )[1].split("\n  },", 1)[0]
        plaintext_probe = bridge.split(
            "chromium_wasm_report_m5_plaintext_http_control_page_probe: (probe) => {",
            1,
        )[1].split("\n  },", 1)[0]

        self.assertIn("bridge.reportM5Navigation", m5_navigation)
        self.assertIn("scheme: 'https'", m5_navigation)
        self.assertNotIn("reportNavigation", m5_navigation)
        self.assertIn("bridge.reportM5NavigationError", m5_failure)
        self.assertIn("committed: false", m5_failure)
        self.assertIn("netError", m5_failure)
        self.assertNotIn("reportNavigation", m5_failure)
        self.assertIn("bridge.reportM5PageProbe", m5_probe)
        self.assertNotIn("reportPageProbe", m5_probe)
        self.assertIn(
            "bridge.reportM5PlaintextHttpControlNavigation",
            plaintext_navigation,
        )
        self.assertIn("scheme: 'http'", plaintext_navigation)
        self.assertNotIn("reportNavigation", plaintext_navigation)
        self.assertIn(
            "bridge.reportM5PlaintextHttpControlPageProbe", plaintext_probe
        )
        self.assertNotIn("reportPageProbe", plaintext_probe)

    def test_m5_tls_name_mismatch_is_reported_before_commit_filtering(self) -> None:
        host_api = source("content/shell/browser/wasm_host_api.cc")
        failure_path = host_api.split(
            "void DidFinishNavigation(NavigationHandle* navigation_handle) override {",
            1,
        )[1].split("if (!navigation_handle->HasCommitted())", 1)[0]

        self.assertIn('#include "net/base/net_errors.h"', host_api)
        self.assertIn("chromium_wasm_report_m5_navigation_error", host_api)
        self.assertIn("navigation_handle->GetNetErrorCode()", failure_path)
        self.assertIn("net_error != net::OK", failure_path)
        self.assertIn("IsM5NetworkTestUrl(navigation_url)", failure_path)

    def test_native_plaintext_control_is_exact_and_separate_from_https(self) -> None:
        host_api = source("content/shell/browser/wasm_host_api.cc")
        predicate = host_api.split(
            "bool IsM5PlaintextHttpControlUrl(const GURL& candidate_url) {", 1
        )[1].split("\n}\n\nbool IsObservedWasmHostUrl", 1)[0]
        loader = host_api.split(
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_plaintext_http_control_url(",
            1,
        )[1].split("\n}\n\nEMSCRIPTEN_KEEPALIVE int chromium_wasm_host_text_input", 1)[0]

        self.assertIn('kM5PlaintextHttpControlPath =', host_api)
        self.assertIn('"/m5/plaintext-control"', host_api)
        self.assertIn("candidate_url.SchemeIs(url::kHttpScheme)", predicate)
        self.assertIn("candidate_url.host() == kM5NetworkTestHostname", predicate)
        self.assertIn("candidate_url.has_port()", predicate)
        self.assertIn("!candidate_url.has_username()", predicate)
        self.assertIn("!candidate_url.has_query()", predicate)
        self.assertIn("candidate_url.path() == kM5PlaintextHttpControlPath", predicate)
        self.assertIn("IsM5PlaintextHttpControlUrl(url)", loader)
        self.assertNotIn("IsM5NetworkTestUrl(url)", loader)

    def test_plaintext_control_fixture_uses_the_native_probe_symbol(self) -> None:
        host_api = source("content/shell/browser/wasm_host_api.cc")
        server = source("tools/wasm/m5_wisp_test_server.js")

        self.assertIn(
            "window.__chromiumWasmM5PlaintextHttpControlProbe ?", host_api
        )
        self.assertIn(
            "window.__chromiumWasmM5PlaintextHttpControlProbe = () => "
            "JSON.stringify({",
            server,
        )


if __name__ == "__main__":
    unittest.main()

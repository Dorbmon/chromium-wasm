#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the bounded host-origin storage estimate diagnostic."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M7WasmBrowserHostStorageEstimateContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state_header = source(
            "chrome/browser/wasm/wasm_browser_host_storage_estimate.h"
        )
        self.state = source("chrome/browser/wasm/wasm_browser_host_storage_estimate.cc")
        self.smoke = source(
            "chrome/browser/wasm/wasm_browser_host_storage_estimate_smoke.cc"
        )
        self.bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        self.adapter = source("tools/wasm/host/chrome_wasm_storage_estimate.js")
        self.normal_host = source("tools/wasm/host/chrome_wasm_host.js")
        self.smoke_host = source(
            "tools/wasm/host/chrome_wasm_browser_host_storage_estimate_smoke_host.js"
        )
        self.settings_header = source("chrome/browser/wasm/wasm_settings_ui.h")
        self.settings = source("chrome/browser/wasm/wasm_settings_ui.cc")
        self.lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        self.main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        self.build = source("chrome/browser/wasm/BUILD.gn")
        self.normal_runner = source("tools/wasm/run_chrome_wasm_smoke.py")
        self.runner = source(
            "tools/wasm/run_m7_wasm_browser_host_storage_estimate_dom_smoke.py"
        )

    def test_scope_is_a_read_only_outer_origin_estimate_not_profile_quota(self) -> None:
        normalized_header = " ".join(self.state_header.replace("//", "").split())
        normalized_settings = " ".join(self.settings.split())
        for marker in (
            "navigator.storage.estimate()",
            "outer origin",
            "not Chromium Wasm profile usage",
            "OPFS reservation",
            "persistence grant",
            "enforcement quota",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, normalized_header)
        for marker in (
            "outer-origin aggregate estimate",
            "not Chromium Wasm profile quota",
            "does not request persistent storage",
            "profile usage, an OPFS reservation",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, normalized_settings)
        for forbidden in (
            "requestPersistent",
            "getDirectory",
            "createSyncAccessHandle",
            "showDirectoryPicker",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.adapter)

    def test_scalar_completion_requires_exact_safe_bytes_and_a_coherent_quota(self) -> None:
        completion = section(
            self.state,
            "bool ValidateHostStorageEstimateCompletion(",
            "class WasmBrowserHostStorageEstimateState",
        )
        for marker in (
            "kMaximumExactHostStorageBytes = (UINT64_C(1) << 53) - 1",
            "std::isfinite(value)",
            "std::floor(value) != value",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.state)
        for marker in (
            "return *usage <= *quota;",
            "case kHostStorageEstimateUnavailable:",
            "case kHostStorageEstimateError:",
            "if (usage_bytes != 0 || quota_bytes != 0)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, completion)
        self.assertIn(
            "chromium_wasm_browser_host_storage_estimate_complete", self.state
        )
        self.assertIn("EMSCRIPTEN_KEEPALIVE", self.state)

    def test_cpp_state_reserves_one_terminal_post_and_teardown_makes_late_results_inert(self) -> None:
        post = section(
            self.state,
            "  bool PostCompletion(",
            " private:",
        )
        for marker in (
            "completion_posted_",
            "completion_terminal_",
            "snapshot_->state() !=\n            WasmBrowserHostStorageEstimateSnapshot::State::kPending",
            "generation != generation_",
            "completion_posted_ = true;",
            "completion_posted_ = false;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, post)
        unavailable = section(
            self.state,
            "  void SetUnavailableOnUiThread",
            "  void DispatchCompletionOnUiThread",
        )
        self.assertIn("completion_terminal_ = true;", unavailable)
        dispatch = section(
            self.state,
            "  void DispatchCompletionOnUiThread",
            "  mutable base::Lock lock_",
        )
        self.assertIn("completion_terminal_ = true;", dispatch)
        shutdown = section(
            self.state,
            "  void ShutdownOnUiThread()",
            "  scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot> Snapshot",
        )
        for marker in (
            "++generation_",
            "accepting_completions_ = false;",
            "completion_terminal_ = true;",
            "task_runner_ = nullptr;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, shutdown)

    def test_sync_import_only_admits_and_adapter_defers_one_terminal_callback(self) -> None:
        bridge = section(
            self.bridge,
            "chromium_wasm_request_outer_origin_storage_estimate__deps",
            "chromium_wasm_report_navigation__deps",
        )
        for marker in (
            "__proxy: 'sync'",
            "Number.isSafeInteger(generation)",
            "bridge.requestOuterOriginStorageEstimate",
            "protocol: ChromiumWasmHostBridge.version",
            "generation,",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge)
        self.assertNotIn("navigator.storage", bridge)

        request = section(
            self.adapter,
            "  request(value) {",
            "  dispose()",
        )
        for marker in (
            "this.#acceptedGenerations.has(value.generation)",
            "this.#acceptedGenerations.add(value.generation);",
            "this.#pendingGenerations.add(value.generation);",
            "Promise.resolve()",
            ".then(() => this.#collectEstimate())",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, request)
        delivery = self.adapter[self.adapter.index("  #deliver(generation, result) {") :]
        self.assertIn("!this.#pendingGenerations.delete(generation)", delivery)
        self.assertIn(
            '"chromium_wasm_browser_host_storage_estimate_complete"', delivery
        )
        self.assertIn("status: result.outcome", delivery)
        self.assertNotIn("String(_error)", self.adapter)

    def test_adapter_keeps_available_unavailable_and_error_distinct(self) -> None:
        for marker in (
            "const OUTCOME_AVAILABLE = 1;",
            "const OUTCOME_UNAVAILABLE = 2;",
            "const OUTCOME_ERROR = 3;",
            "usageBytes > quotaBytes",
            'status: result.outcome === OUTCOME_AVAILABLE ? "available" :',
            'result.outcome === OUTCOME_UNAVAILABLE ? "unavailable" : "error"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.adapter)

    def test_settings_root_is_strict_and_datasource_has_a_captured_snapshot(self) -> None:
        root = section(
            self.settings,
            "bool IsWasmSettingsRootURL",
            "std::string BytesForWasmSettings",
        )
        for marker in (
            "url.SchemeIs(content::kChromeUIScheme)",
            "url.host() == kWasmSettingsHost",
            "url.path() == \"/\" || url.path().empty()",
            "!url.has_username()",
            "!url.has_password()",
            "!url.has_port()",
            "!url.has_query()",
            "!url.has_ref()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, root)
        data_source = section(
            self.settings,
            "class WasmSettingsDataSource final",
            "}  // namespace\n\nWasmSettingsUI::WasmSettingsUI",
        )
        self.assertIn("storage_estimate_snapshot_", data_source)
        self.assertIn("BuildWasmSettingsBootstrapHtml(*storage_estimate_snapshot_)", data_source)
        self.assertNotIn("GetWasmBrowserHostStorageEstimateSnapshot()", data_source)
        self.assertIn("GetStorageEstimateSnapshotForTesting", self.settings_header)
        self.assertIn("State::kPending", self.settings)
        self.assertIn("State::kAvailable", self.settings)
        self.assertIn("State::kUnavailable", self.settings)
        self.assertIn("State::kError", self.settings)

    def test_dedicated_smoke_owns_only_fixed_ordinals_and_native_settings_proof(self) -> None:
        for marker in (
            "chromium_wasm_browser_host_storage_estimate_check",
            "chromium_wasm_browser_host_storage_estimate_presented",
            "stage == 1",
            "stage == 2",
            "dispatch_pending_",
            "expected_callback_",
            "DisableAfterFailedCallback",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.smoke)
        for forbidden in ("LoadURL", "OpenURL", "NavigationController", "SetText("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.smoke)
        lifecycle = section(
            self.lifecycle,
            "bool WasmBrowserLifecycle::VerifyHostStorageEstimateSmokeCheck",
            "void WasmBrowserLifecycle::OnHostStorageEstimateSettingsNavigationObserved",
        )
        for marker in (
            "GetWasmBrowserHostStorageEstimateSnapshot()",
            "State::kAvailable",
            "snapshot->usage_bytes() > snapshot->quota_bytes()",
            "kHostStorageEstimateSettingsUrl",
            "LoadURLWithParams(params)",
            "ui::PAGE_TRANSITION_GENERATED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, lifecycle)
        self.assertLess(
            lifecycle.index("host_storage_estimate_check_verified_ = true;"),
            lifecycle.index("LoadURLWithParams(params)"),
        )
        observed = section(
            self.lifecycle,
            "void WasmBrowserLifecycle::OnHostStorageEstimateSettingsNavigationObserved",
            "bool WasmBrowserLifecycle::OnHostStorageEstimateSmokePresented",
        )
        for marker in (
            "GetAs<WasmSettingsUI>()",
            "GetStorageEstimateSnapshotForTesting()",
            "controller_snapshot->generation() != host_storage_estimate_generation_",
            "controller_snapshot->usage_bytes() != host_storage_estimate_usage_bytes_",
            "controller_snapshot->quota_bytes() != host_storage_estimate_quota_bytes_",
            "browser_view.SchedulePaint();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, observed)

    def test_smoke_and_normal_host_routes_reuse_the_adapter_without_broadening_production(self) -> None:
        for host in (self.normal_host, self.smoke_host):
            self.assertIn(
                'import {ChromiumWasmOuterOriginStorageEstimate} from "./chrome_wasm_storage_estimate.js";',
                host,
            )
            self.assertIn("requestOuterOriginStorageEstimate(report)", host)
            self.assertIn("new ChromiumWasmOuterOriginStorageEstimate", host)
        self.assertIn("this.#storageEstimate?.dispose();", self.normal_host)
        self.assertIn("this.#storageEstimate?.dispose();", self.smoke_host)
        self.assertIn("setTimeout(() => {", self.smoke_host)
        self.assertIn("frameIdAfterNavigation", self.smoke_host)
        self.assertNotIn("NavigationController", self.smoke_host)
        self.assertNotIn("LoadURL", self.smoke_host)
        self.assertIn('"chrome_wasm_storage_estimate.js"', self.normal_runner)

    def test_build_selects_direct_dependencies_and_dedicated_switch(self) -> None:
        target = section(
            self.build,
            'source_set("wasm_browser_host_storage_estimate")',
            '# The host-origin capacity smoke',
        )
        for marker in (
            '"wasm_browser_host_storage_estimate.cc"',
            '":wasm_browser_lifecycle"',
            '":wasm_browser_main_parts"',
            '":wasm_settings_ui"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, target)
        self.assertIn('source_set("wasm_browser_host_storage_estimate_smoke")', self.build)
        for marker in (
            '"wasm-browser-host-storage-estimate-smoke"',
            "InitializeWasmBrowserHostStorageEstimate()",
            "ShutdownWasmBrowserHostStorageEstimate()",
            "StartHostStorageEstimateSmoke()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.main_parts)
        for marker in (
            "HOST_ROOT = \"/__m7_browser_host_storage_estimate__\"",
            "chrome_wasm_storage_estimate.js",
            "verify_explicit_smoke_exports",
            "chromium_wasm_browser_host_storage_estimate_complete",
            "chromium_wasm_browser_host_storage_estimate_check",
            "chromium_wasm_browser_host_storage_estimate_presented",
            "runtime_arguments=[SWITCH]",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.runner)


if __name__ == "__main__":
    unittest.main()

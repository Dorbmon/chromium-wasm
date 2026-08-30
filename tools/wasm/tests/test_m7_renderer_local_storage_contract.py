#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the narrow M7 renderer-owned LocalStorage witness."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


_BASE_FLAG = "enable_chromium_wasm_m7_default_partition_local_storage_test"
_BASE_MACRO = "CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST"


def _body_after_marker(text: str, marker: str) -> str:
    start = text.index(marker)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing brace for {marker}")


class M7RendererLocalStorageContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wasm_args = source("build/config/wasm.gni")
        self.gni = source("chrome/browser/wasm/wasm_profile_local_storage_smoke.gni")
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        self.content_client = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )
        self.dom_storage = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.cc"
        )
        self.dom_storage_support = source(
            "content/browser/dom_storage/wasm_dom_storage_test_support.cc"
        )
        self.smoke = source("chrome/browser/wasm/wasm_profile_local_storage_smoke.cc")
        self.ui = source(
            "chrome/browser/wasm/wasm_profile_renderer_local_storage_ui.cc"
        )

    def test_renderer_route_is_source_selected_into_the_existing_m7_artifact(
        self,
    ) -> None:
        args = _body_after_marker(self.wasm_args, "declare_args()")
        self.assertIn(f"{_BASE_FLAG} = false", args)
        default_guard = _body_after_marker(
            self.wasm_args, "if (current_toolchain == default_toolchain)"
        )
        self.assertIn(f"!{_BASE_FLAG} ||", default_guard)

        gni_gate = _body_after_marker(self.gni, f"if ({_BASE_FLAG})")
        self.assertIn(
            '"wasm-chrome-m7-default-partition-local-storage"', gni_gate
        )

        executable = _body_after_marker(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        selected = _body_after_marker(executable, f"if ({_BASE_FLAG})")
        self.assertIn(
            'output_name = "chrome_wasm_m7_default_partition_local_storage_test"',
            selected,
        )
        self.assertIn(f'"{_BASE_MACRO}=1"', selected)

        smoke_target = _body_after_marker(
            self.wasm_build, 'source_set("wasm_profile_local_storage_smoke")'
        )
        for expected in (
            '"wasm_profile_local_storage_smoke.cc"',
            '"wasm_profile_renderer_local_storage_ui.cc"',
            '"wasm_profile_renderer_local_storage_ui.h"',
            f'"{_BASE_MACRO}=1"',
            '":wasm_profile_ordered_drain_lifecycle"',
            '"//content/public/common"',
            'public_deps = [ "//content/public/browser" ]',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, smoke_target)
        self.assertNotIn('":wasm_profile"', smoke_target)

        self.assertIn(
            f"#if defined({_BASE_MACRO})", self.main_parts
        )
        self.assertIn(
            "EnsureWasmProfileRendererLocalStorageWebUIConfigRegistered();",
            self.main_parts,
        )

    def test_existing_m7_isolation_and_normal_partition_policy_remain_intact(
        self,
    ) -> None:
        for incompatible in (
            "enable_chromium_wasm_m7_profile_preferences_test",
            "enable_chromium_wasm_m7_profile_database_test",
        ):
            with self.subTest(incompatible=incompatible):
                self.assertIn(
                    _BASE_FLAG + " &&\n          " + incompatible,
                    self.chrome_build,
                )
        profile = source("chrome/browser/wasm/wasm_profile.cc")
        default_partition = _body_after_marker(
            profile,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn("return true;", default_partition)
        self.assertNotIn(_BASE_MACRO, default_partition)

    def test_webui_uses_an_external_renderer_script_only(self) -> None:
        self.assertIn('<script src="m7_local_storage_renderer.js"></script>', self.ui)
        self.assertIn('"text/javascript"', self.ui)
        self.assertIn("globalThis.localStorage.setItem(tokenKey, token);", self.ui)
        self.assertIn("globalThis.localStorage.getItem(tokenKey) === token", self.ui)
        self.assertIn(
            'const fenceValueA = "m7-renderer-local-storage-close-fence-value-a";',
            self.ui,
        )
        self.assertIn(
            'const fenceValueB = "m7-renderer-local-storage-close-fence-value-b";',
            self.ui,
        )
        self.assertIn(
            "const previousFenceValue = globalThis.localStorage.getItem(fenceKey);",
            self.ui,
        )
        self.assertIn(
            "previousFenceValue === fenceValueA ?\n"
            "          fenceValueB : fenceValueA",
            self.ui,
        )
        self.assertIn(
            "globalThis.localStorage.setItem(fenceKey, nextFenceValue);", self.ui
        )
        self.assertNotIn(
            "globalThis.localStorage.setItem(fenceKey, token);", self.ui
        )
        self.assertIn('mode === "renderer-write"', self.ui)
        self.assertIn('mode === "renderer-verify"', self.ui)
        self.assertIn("m7-local-storage-renderer-write-ok", self.ui)
        self.assertIn("m7-local-storage-renderer-verify-ok", self.ui)
        html = self.ui.split("constexpr char kRendererLocalStorageHtml", 1)[1].split(
            ")HTML\"", 1
        )[0]
        self.assertNotIn("<script>", html)

        root = _body_after_marker(
            self.ui, "bool IsWasmProfileRendererLocalStorageRootURL("
        )
        for expected in (
            "mode=renderer-write&token=",
            "mode=renderer-verify&token=",
            "url.has_username()",
            "url.has_password()",
            "url.has_port()",
            "url.has_ref()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, root)
        script = _body_after_marker(
            self.ui, "bool IsWasmProfileRendererLocalStorageScriptURL("
        )
        for expected in (
            'url.path() == "/m7_local_storage_renderer.js"',
            "!url.has_query()",
            "!url.has_ref()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, script)

    def test_renderer_storage_key_and_partition_are_observed_from_real_rfh(self) -> None:
        start = _body_after_marker(self.smoke, "bool StartRenderer(")
        for expected in (
            "content::WebContents::Create(create_params)",
            "Observe(renderer_web_contents_.get());",
            "renderer_operation_timeout_.Start(",
            "LoadURLWithParams(load_params)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, start)
        self.assertIn('"chrome://m7-local-storage/"', self.smoke)

        boundary = _body_after_marker(
            self.smoke, "bool ValidateRendererStorageBoundary()"
        )
        for expected in (
            "renderer_browser_context_->GetDefaultStoragePartition()",
            "renderer_web_contents_->GetBrowserContext()\n"
            "                ->GetDefaultStoragePartition()",
            "renderer_web_contents_->GetPrimaryMainFrame()",
            "render_frame_host->IsRenderFrameLive()",
            "render_frame_host->GetLastCommittedURL()",
            "render_frame_host->GetStorageKey()",
            "blink::StorageKey::CreateFirstParty(",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, boundary)
        self.assertNotIn("renderer_profile_", boundary)
        self.assertNotIn("WasmProfile", boundary)

    def test_navigation_is_commit_gated_and_bounded(self) -> None:
        title = _body_after_marker(self.smoke, "void TitleWasSet(")
        self.assertIn("entry->GetURL() != renderer_page_url_", title)
        self.assertIn("MaybeCompleteRendererPage();", title)
        navigation = _body_after_marker(self.smoke, "void DidFinishNavigation(")
        for expected in (
            "navigation_handle->GetURL() != renderer_page_url_",
            "!navigation_handle->HasCommitted()",
            "navigation_handle->IsErrorPage()",
            "renderer_primary_commit_seen_ = true;",
            "MaybeCompleteRendererPage();",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, navigation)
        complete = _body_after_marker(self.smoke, "void MaybeCompleteRendererPage()")
        self.assertNotIn("renderer_operation_timeout_.Stop();", complete)
        timeout = _body_after_marker(self.smoke, "void OnRendererOperationTimeout()")
        self.assertIn("ReportFailure", timeout)

        state_start = self.smoke.index(
            "class WasmProfileLocalStorageLifetimeParticipant::State"
        )
        failure = _body_after_marker(
            self.smoke[state_start:], "void ReportFailure("
        )
        self.assertIn(
            "close_receipt_lifetime_.FailBeforeExactCloseReceipt(", failure
        )
        self.assertIn("CleanupProfileBoundResources", failure)
        self.assertNotIn("PostTask(", failure)
        self.assertNotIn("profile_io_hold_->Complete", failure)

        retry = _body_after_marker(
            self.smoke, "static bool IsRetryableRendererPrepareResult("
        )
        for expected in (
            "kStorageNotFound",
            "kStorageAreaNotBound",
            "kDatabaseNotReady",
            "kSnapshotConnectionNotReady",
            "kSnapshotNotCommitted",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, retry)

    def test_renderer_owner_is_destroyed_before_existing_close_fence_arm(self) -> None:
        close = _body_after_marker(
            self.smoke, "void DestroyRendererWebContentsThenArmCloseFence()"
        )
        detach = close.index("Observe(nullptr);")
        destroy = close.index("renderer_web_contents_.reset();")
        reset_connections = close.index(
            "content::ResetWasmLocalStorageConnectionsForTest("
        )
        arm = close.index("test_api_->ArmCommitCloseFence(")
        self.assertLess(detach, destroy)
        self.assertLess(destroy, reset_connections)
        self.assertLess(reset_connections, arm)
        self.assertNotIn(
            "content::RenderProcessHost::ShutDownInProcessRenderer()", close
        )
        self.assertLess(destroy, arm)
        self.assertNotIn("renderer_operation_timeout_.Stop();", close)

        reset = _body_after_marker(
            self.dom_storage,
            "bool DOMStorageContextWrapper::\n"
            "    ResetLocalStorageConnectionsForWasmProfileTest()",
        )
        self.assertIn(
            "!partition_ || local_storage_rebind_sealed_for_wasm_profile_test_",
            reset,
        )
        self.assertIn("partition_->ResetLocalStorageConnections();", reset)
        support = _body_after_marker(
            self.dom_storage_support,
            "bool ResetWasmLocalStorageConnectionsForTest(",
        )
        self.assertIn(
            "return wrapper->ResetLocalStorageConnectionsForWasmProfileTest();",
            support,
        )
        prepared = _body_after_marker(
            self.smoke, "void OnRendererCloseFencePrepared("
        )
        self.assertIn("renderer_operation_timeout_.IsRunning()", prepared)
        self.assertIn("WaitForCloseFence", self.smoke)

    def test_content_client_allows_only_exact_test_document_and_script(self) -> None:
        self.assertIn(f"#if defined({_BASE_MACRO})", self.content_client)
        helper = _body_after_marker(
            self.content_client, "bool IsWasmM7RendererLocalStorageURL("
        )
        for expected in (
            "kWasmM7RendererLocalStorageHost",
            "mode=renderer-write&token=",
            "mode=renderer-verify&token=",
            'url.path() == "/m7_local_storage_renderer.js"',
            "!url.has_query()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, helper)
        handled = _body_after_marker(
            self.content_client, "bool WasmContentBrowserClient::IsHandledURL("
        )
        self.assertIn("IsWasmM7RendererLocalStorageURL(url)", handled)


if __name__ == "__main__":
    unittest.main()

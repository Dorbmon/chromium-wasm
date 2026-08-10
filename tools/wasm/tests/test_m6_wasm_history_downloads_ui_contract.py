#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded Wasm History and Downloads bootstrap WebUIs."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _source_set_body(build_file: str, target: str) -> str:
    match = re.search(rf'\bsource_set\("{re.escape(target)}"\)', build_file)
    if not match:
        raise AssertionError(f"missing source set {target!r}")
    opening_brace = build_file.find("{", match.end())
    if opening_brace < 0:
        raise AssertionError(f"missing opening brace for {target!r}")
    depth = 0
    for index in range(opening_brace, len(build_file)):
        if build_file[index] == "{":
            depth += 1
        elif build_file[index] == "}":
            depth -= 1
            if depth == 0:
                return build_file[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {target!r}")


class M6WasmHistoryDownloadsUIContractTest(unittest.TestCase):
    def test_targets_do_not_select_desktop_history_or_downloads_graphs(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        history = _source_set_body(build, "wasm_history_ui")
        downloads = _source_set_body(build, "wasm_downloads_ui")
        journal = _source_set_body(build, "wasm_session_navigation_journal")

        for required in (
            '"wasm_history_ui.h"',
            '"wasm_history_ui.cc"',
            '":wasm_profile",',
            '":wasm_session_navigation_journal",',
            '"//content/public/browser"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, history)
        for required in (
            '"wasm_downloads_ui.h"',
            '"wasm_downloads_ui.cc"',
            '"//content/public/browser"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, downloads)
        for required in (
            '"wasm_session_navigation_journal.h"',
            '"wasm_session_navigation_observer.h"',
            '":wasm_session_tab_helper",',
            '"//content/public/browser"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, journal)

        for target in (history, downloads, journal):
            for forbidden in (
                "//chrome/browser/ui/webui/history",
                "//chrome/browser/ui/webui/downloads",
                "//components/history",
                "//chrome/browser/download",
                "//components/sync",
                "//components/bookmarks",
                "//components/webui/history",
                "//components/webui/downloads",
            ):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, target)

    def test_profile_owned_journal_is_bounded_redacted_and_disarmed(self) -> None:
        profile_h = source("chrome/browser/wasm/wasm_profile.h")
        profile = source("chrome/browser/wasm/wasm_profile.cc")
        journal_h = source("chrome/browser/wasm/wasm_session_navigation_journal.h")
        journal = source("chrome/browser/wasm/wasm_session_navigation_journal.cc")
        observer = source("chrome/browser/wasm/wasm_session_navigation_observer.cc")
        session_helper = source("chrome/browser/wasm/wasm_session_tab_helper.cc")
        tab_model = source("chrome/browser/ui/tabs/tab_model.cc")

        for required in (
            "std::unique_ptr<WasmSessionNavigationJournal> session_navigation_journal_",
            "GetSessionNavigationJournalWeakPtr",
        ):
            with self.subTest(required=required):
                self.assertIn(required, profile_h)
        shutdown = "session_navigation_journal_->Shutdown();"
        self.assertIn(shutdown, profile)
        self.assertLess(profile.index(shutdown), profile.index("MaybeSendDestroyedNotification"))

        for required in (
            "kMaximumEntries = 64",
            "kMaximumDisplayUrlBytes = 2048",
            "url.SchemeIsHTTPOrHTTPS()",
            "replacements.ClearUsername();",
            "replacements.ClearPassword();",
            "replacements.ClearQuery();",
            "replacements.ClearRef();",
            "InvalidateWeakPtrsAndDoom();",
            "while (entries_.size() > kMaximumEntries)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, journal_h + journal)
        self.assertNotIn('return "data:', journal)

        for required in (
            "IsInPrimaryMainFrame()",
            "HasCommitted()",
            "IsSameDocument()",
            "IsErrorPage()",
            "IsDownload()",
            "void WasmSessionNavigationObserver::WebContentsDestroyed()",
            "journal_.reset();",
            "Observe(nullptr);",
        ):
            with self.subTest(required=required):
                self.assertIn(required, observer)
        self.assertNotIn("delete this", observer)

        attach = "WasmSessionNavigationObserver::CreateForWebContents("
        self.assertIn(attach, session_helper)
        self.assertLess(session_helper.index(attach), session_helper.index("SessionTabHelper::CreateForWebContents"))
        self.assertIn("PrepareWasmTabWebContents(contents.get());", tab_model)

    def test_history_uses_immutable_ui_snapshot_and_escapes_html(self) -> None:
        header = source("chrome/browser/wasm/wasm_history_ui.h")
        implementation = source("chrome/browser/wasm/wasm_history_ui.cc")

        for required in (
            "class WasmHistoryUI final : public content::WebUIController",
            "content::DefaultWebUIConfig<WasmHistoryUI>",
            "EnsureWasmHistoryWebUIConfigRegistered",
            "not desktop HistoryUI or HistoryService",
        ):
            with self.subTest(required=required):
                self.assertIn(required, header)
        for required in (
            'constexpr char kWasmHistoryHost[] = "history";',
            "bool IsWasmHistoryRootURL",
            "!url.has_username()",
            "!url.has_password()",
            "!url.has_port()",
            "!url.has_query()",
            "!url.has_ref()",
            "base::EscapeForHTML(entry.display_url)",
            "Volatile M6 session journal",
            "not backed by\n      Chrome HistoryService",
            "std::vector<WasmSessionNavigationJournal::Entry> snapshot;",
            "snapshot = journal->GetSnapshot();",
            "std::make_unique<WasmHistoryDataSource>(std::move(snapshot))",
            "bool AllowCaching() override { return false; }",
            "std::move(callback).Run(nullptr);",
        ):
            with self.subTest(required=required):
                self.assertIn(required, implementation)
        start_request = implementation.index("void StartDataRequest")
        source_ctor = implementation.index("WasmHistoryUI::WasmHistoryUI")
        self.assertNotIn("GetSnapshot()", implementation[start_request:source_ctor])
        for forbidden in (
            "history::HistoryService",
            "AddMessageHandler",
            "WebUIDataSource",
            "javascript",
            "location.assign",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_downloads_is_a_static_unavailable_root_without_fake_actions(self) -> None:
        header = source("chrome/browser/wasm/wasm_downloads_ui.h")
        implementation = source("chrome/browser/wasm/wasm_downloads_ui.cc")

        for required in (
            "class WasmDownloadsUI final : public content::WebUIController",
            "content::DefaultWebUIConfig<WasmDownloadsUI>",
            "EnsureWasmDownloadsWebUIConfigRegistered",
            "a synthetic download row",
        ):
            with self.subTest(required=required):
                self.assertIn(required, header)
        for required in (
            'constexpr char kWasmDownloadsHost[] = "downloads";',
            "bool IsWasmDownloadsRootURL",
            "Unavailable until M7 OPFS/export",
            "no\n      <code>DownloadManagerDelegate</code>",
            "There are no download records, controls, synthetic completion states",
            "bool AllowCaching() override { return false; }",
            "std::move(callback).Run(nullptr);",
        ):
            with self.subTest(required=required):
                self.assertIn(required, implementation)
        for forbidden in (
            "content::DownloadManager",
            "AddMessageHandler",
            "WebUIDataSource",
            "javascript",
            "<button",
            "<form",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_registration_and_routes_stay_exact_and_wasm_owned(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        client = source("chrome/browser/wasm/wasm_content_browser_client.cc")
        controls = source("chrome/browser/wasm/wasm_top_controls_view.cc")
        menu_h = source("chrome/browser/wasm/wasm_browser_menu.h")
        menu = source("chrome/browser/wasm/wasm_browser_menu.cc")

        profile_creation = "profile_ = std::make_unique<WasmProfile>(profile_path);"
        for registration in (
            "chrome::EnsureWasmHistoryWebUIConfigRegistered();",
            "chrome::EnsureWasmDownloadsWebUIConfigRegistered();",
        ):
            with self.subTest(registration=registration):
                self.assertIn(registration, main_parts)
                self.assertLess(main_parts.index(registration), main_parts.index(profile_creation))
        self.assertIn("mutually exclusive with RegisterChromeWebUIConfigs()", main_parts)
        self.assertNotIn("RegisterChromeWebUIConfigs();", main_parts)

        for required in (
            'constexpr char kWasmHistoryHost[] = "history";',
            'constexpr char kWasmDownloadsHost[] = "downloads";',
            "bool IsWasmRootChromeUrl",
            "IsWasmRootChromeUrl(url, kWasmHistoryHost)",
            "IsWasmRootChromeUrl(url, kWasmDownloadsHost)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, client)
        for required in (
            'constexpr char kWasmHistoryURL[] = "chrome://history/";',
            'constexpr char kWasmDownloadsURL[] = "chrome://downloads/";',
            "target_url == GURL(kWasmHistoryURL)",
            "target_url == GURL(kWasmDownloadsURL)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, controls)
        for required in (
            "history_button_for_testing",
            "downloads_button_for_testing",
            "ShowHistory",
            "ShowDownloads",
        ):
            with self.subTest(required=required):
                self.assertIn(required, menu_h + menu)
        for required in (
            'u"History"',
            'u"Downloads"',
            'constexpr char kWasmHistoryURL[] = "chrome://history/";',
            'constexpr char kWasmDownloadsURL[] = "chrome://downloads/";',
            "params.transition_type = ui::PAGE_TRANSITION_GENERATED;",
            "params.has_user_gesture = true;",
        ):
            with self.subTest(required=required):
                self.assertIn(required, menu)

    def test_host_runtime_proof_is_test_gated_and_observes_real_routes(self) -> None:
        build = source("chrome/browser/wasm/BUILD.gn")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        lifecycle_h = source("chrome/browser/wasm/wasm_browser_lifecycle.h")
        verifier = source(
            "chrome/browser/wasm/wasm_browser_host_history_downloads_smoke.cc"
        )
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        chrome_main = source("chrome/app/chrome_main_wasm.cc")

        verifier_target = _source_set_body(
            build, "wasm_browser_host_history_downloads_smoke"
        )
        lifecycle_target = _source_set_body(build, "wasm_browser_lifecycle")
        for required in (
            '"wasm_browser_host_history_downloads_smoke.h"',
            '"wasm_browser_host_history_downloads_smoke.cc"',
            '":wasm_browser_host_history_downloads_smoke",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, verifier_target + lifecycle_target)

        for required in (
            "StartHostHistoryDownloadsSmoke",
            "VerifyHostHistoryDownloadsSmokeCheck",
            "OnHostHistoryDownloadsSmokePresented",
            "WasmBrowserHostHistoryDownloadsNavigationObserver",
            "ExpectedNavigation::kTypedUser",
            "ExpectedNavigation::kGeneratedUser",
            "https://a.test/m5/m6-ui#wasm_journal=1",
            "kHostHistoryDownloadsRedactedJournalUrl",
            "history_ui->entry_count_for_testing() != 2u",
            "profile_->GetDownloadManagerDelegate() != nullptr",
            "history_button_for_testing",
            "downloads_button_for_testing",
            "ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting",
        ):
            with self.subTest(required=required):
                self.assertIn(required, lifecycle + lifecycle_h)
        self.assertGreaterEqual(
            lifecycle.count("ClearWasmBrowserHostHistoryDownloadsSmokeVerificationForTesting"),
            3,
        )
        start = lifecycle.index("void WasmBrowserLifecycle::StartHostHistoryDownloadsSmoke")
        second_navigation = lifecycle.index(
            "void WasmBrowserLifecycle::OnHostHistoryDownloadsSecondNavigationObserved"
        )
        history_navigation = lifecycle.index(
            "void WasmBrowserLifecycle::OnHostHistoryDownloadsHistoryNavigationObserved"
        )
        self.assertLess(
            lifecycle.index("host_history_downloads_first_navigation_observer_ =", start),
            lifecycle.index("kHostHistoryDownloadsReadyMarker", start),
        )
        self.assertLess(
            lifecycle.index(
                "host_history_downloads_history_navigation_observer_ =",
                second_navigation,
            ),
            lifecycle.index(
                "kHostHistoryDownloadsSecondNavigatedMarker", second_navigation
            ),
        )
        self.assertLess(
            lifecycle.index(
                "host_history_downloads_downloads_navigation_observer_ =",
                history_navigation,
            ),
            lifecycle.index(
                "kHostHistoryDownloadsHistoryNavigatedMarker", history_navigation
            ),
        )

        for required in (
            "kHistoryMenuOpenCheck",
            "kHistoryMenuClosedCheck",
            "kDownloadsMenuOpenCheck",
            "kDownloadsMenuClosedCheck",
            "stage == 6",
            "base::Unretained(this)",
            "DisableAfterFailedCallback",
        ):
            with self.subTest(required=required):
                self.assertIn(required, verifier)
        self.assertNotIn("NavigationController", verifier)
        self.assertNotIn("BrowserView", verifier)

        self.assertIn("kWasmBrowserHostHistoryDownloadsSmokeSwitch", main_parts)
        self.assertIn("IsWasmM6ControlledHttpsTestModeEnabled", main_parts)
        self.assertIn("StartHostHistoryDownloadsSmoke", main_parts)
        self.assertIn("kWasmBrowserHostHistoryDownloadsSmokeSwitch", chrome_main)
        self.assertIn("#if defined(CHROME_WASM_M6_CONTROLLED_HTTPS_TEST)", chrome_main)
        self.assertIn("InstallWasmM6TestTrustRoot", chrome_main)


if __name__ == "__main__":
    unittest.main()

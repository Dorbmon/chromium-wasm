#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the Bookmark/Cookie/History/LocalStorage aggregate."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


_FLAG = (
    "enable_chromium_wasm_m7_profile_"
    "bookmark_cookie_history_local_storage_test"
)
_MACRO = (
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST"
)
_CONFIG = "wasm_profile_m7_bookmark_cookie_history_local_storage_smoke_config"
_BRIDGE_CONFIG = "wasm_m7_profile_bookmark_cookie_history_local_storage_test"
_OUTPUT = "chrome_wasm_m7_profile_bookmark_cookie_history_local_storage_test"
_OUT_DIR = "wasm-chrome-m7-profile-bookmark-cookie-history-local-storage"
_OTHER_MACROS = (
    "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST",
    "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST",
    "CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST",
)


def _body_after_marker(text: str, marker: str) -> str:
    start = text.index(marker)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing brace for {marker}")


def _prefix_before(text: str, marker: str | int, length: int = 1200) -> str:
    position = marker if isinstance(marker, int) else text.index(marker)
    return text[max(0, position - length) : position]


class M7ProfileBookmarkCookieHistoryLocalStorageContractTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.wasm_args = source("build/config/wasm.gni")
        self.aggregate_gni = source(
            "chrome/browser/wasm/"
            "wasm_profile_bookmark_cookie_history_local_storage_smoke.gni"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.main_parts_header = source(
            "chrome/browser/wasm/wasm_browser_main_parts.h"
        )
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.profile_storage = source(
            "chrome/browser/wasm/wasm_profile_storage.cc"
        )
        self.profile_storage_header = source(
            "chrome/browser/wasm/wasm_profile_storage.h"
        )
        self.preferences_smoke = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.cc"
        )
        self.bookmark_smoke = source(
            "chrome/browser/wasm/wasm_profile_bookmark_smoke.cc"
        )
        self.bookmark_smoke_header = source(
            "chrome/browser/wasm/wasm_profile_bookmark_smoke.h"
        )
        self.cookie_smoke = source(
            "chrome/browser/wasm/wasm_profile_cookie_smoke.cc"
        )
        self.history_smoke = source(
            "chrome/browser/wasm/wasm_profile_history_smoke.cc"
        )
        self.local_storage_smoke = source(
            "chrome/browser/wasm/wasm_profile_local_storage_smoke.cc"
        )
        self.content_client = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )
        self.dom_storage = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.cc"
        )
        self.dom_storage_header = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.h"
        )
        self.dom_storage_test_support = source(
            "content/public/browser/wasm_dom_storage_test_support.h"
        )
        self.local_storage_impl = source(
            "components/services/storage/dom_storage/local_storage_impl.cc"
        )
        self.local_storage_impl_header = source(
            "components/services/storage/dom_storage/local_storage_impl.h"
        )
        self.storage_service = source(
            "components/services/storage/storage_service_impl.cc"
        )
        self.storage_service_header = source(
            "components/services/storage/storage_service_impl.h"
        )
        self.content_build = source("content/browser/BUILD.gn")
        self.content_public_build = source("content/public/browser/BUILD.gn")
        self.storage_build = source("components/services/storage/BUILD.gn")
        self.storage_mojom_build = source(
            "components/services/storage/public/mojom/BUILD.gn"
        )

    def test_fresh_artifact_selects_only_the_four_store_witnesses(self) -> None:
        args = _body_after_marker(self.wasm_args, "declare_args()")
        self.assertRegex(args, rf"{re.escape(_FLAG)}\s*=\s*false")
        self.assertRegex(
            self.wasm_args,
            rf"assert\(\s*!{re.escape(_FLAG)}\s*\|\|",
        )

        aggregate_gate = _body_after_marker(
            self.aggregate_gni, f"if ({_FLAG})"
        )
        for excluded_flag in (
            "enable_chromium_wasm_m7_profile_preferences_test",
            "enable_chromium_wasm_m7_profile_database_test",
            "enable_chromium_wasm_m7_default_partition_local_storage_test",
            "enable_chromium_wasm_m7_profile_cookie_local_storage_test",
            "enable_chromium_wasm_m7_profile_cookie_history_local_storage_test",
            "enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic",
        ):
            with self.subTest(excluded_flag=excluded_flag):
                self.assertIn(f"!{excluded_flag}", aggregate_gate)
        self.assertIn(f'"{_OUT_DIR}"', aggregate_gate)

        executable = _body_after_marker(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        selected = _body_after_marker(executable, f"if ({_FLAG})")
        self.assertIn(f'"{_OUTPUT}"', selected)
        self.assertIn(f'"{_MACRO}=1"', selected)
        for other_macro in _OTHER_MACROS:
            with self.subTest(other_macro=other_macro):
                self.assertNotIn(other_macro, selected)

        deps_start = executable.index("deps = [")
        deps_tail = executable[executable.index(f"if ({_FLAG})", deps_start) :]
        deps_gate = _body_after_marker(deps_tail, f"if ({_FLAG})")
        for helper in (
            "wasm_profile_preferences_smoke",
            "wasm_profile_bookmark_smoke",
            "wasm_profile_cookie_smoke",
            "wasm_profile_history_smoke",
            "wasm_profile_local_storage_smoke",
        ):
            with self.subTest(helper=helper):
                self.assertIn(helper, deps_gate)
        self.assertNotIn("wasm_profile_database_smoke", deps_gate)

        profile_target = _body_after_marker(
            self.wasm_build, 'source_set("wasm_profile")'
        )
        profile_gate = _body_after_marker(profile_target, f"if ({_FLAG})")
        self.assertIn(f'":{_CONFIG}"', profile_gate)
        self.assertIn("public_configs", profile_gate)
        for helper in (
            '":wasm_profile_preferences_smoke"',
            '":wasm_profile_bookmark_smoke"',
            '":wasm_profile_cookie_smoke"',
            '":wasm_profile_history_smoke"',
            '":wasm_profile_local_storage_smoke"',
        ):
            with self.subTest(profile_helper=helper):
                self.assertIn(helper, profile_gate)
        self.assertNotIn("wasm_profile_database_smoke", profile_gate)

    def test_phase_pair_and_exact_owner_set_are_admitted_before_mount(self) -> None:
        phase_start = self.chrome_main.index("const bool phases_match =")
        mount = self.chrome_main.index(
            "chrome::InitializeWasmProfilePreferencesStorage()"
        )
        content_main = self.chrome_main.index(
            "content::ContentMain(std::move(params))"
        )
        self.assertLess(phase_start, mount)
        self.assertLess(mount, content_main)
        validation = self.chrome_main[phase_start:mount]

        for phase in (
            "WasmProfilePreferencesSmokeMode::kWrite",
            "WasmProfilePreferencesSmokeMode::kVerifyAndWrite",
            "WasmProfilePreferencesSmokeMode::kVerifyB",
            "kRendererWrite",
            "kRendererVerify",
        ):
            with self.subTest(phase=phase):
                self.assertIn(phase, validation)
        phase_expression = validation.split(
            "const bool phases_match =", 1
        )[1].split("aggregate_smoke_enabled =", 1)[0]
        expected_pairs = (
            ("kWrite", "kRendererWrite"),
            ("kVerifyAndWrite", "kRendererVerify"),
            ("kVerifyB", "kRendererVerify"),
        )
        for preferences_phase, local_storage_phase in expected_pairs:
            with self.subTest(
                preferences_phase=preferences_phase,
                local_storage_phase=local_storage_phase,
            ):
                self.assertRegex(
                    phase_expression,
                    re.compile(
                        r"\(preferences_mode\s*==\s*"
                        r"chrome::WasmProfilePreferencesSmokeMode::"
                        + preferences_phase
                        + r"\s*&&\s*local_storage_mode\s*==\s*"
                        r"chrome::WasmProfileLocalStorageSmokeInput::Mode::\s*"
                        + local_storage_phase
                        + r"\)",
                    ),
                )
        self.assertEqual(
            len(re.findall(r"\(preferences_mode\s*==", phase_expression)), 3
        )
        self.assertEqual(
            len(re.findall(r"local_storage_mode\s*==", phase_expression)), 3
        )
        verify_b = phase_expression.index(
            "WasmProfilePreferencesSmokeMode::kVerifyB"
        )
        verify_b_guard = phase_expression.rfind(
            f"#if defined({_MACRO})", 0, verify_b
        )
        self.assertGreaterEqual(verify_b_guard, 0)
        self.assertLess(verify_b, phase_expression.index("#endif", verify_b))
        for owner in (
            "IsWasmProfilePreferencesBrowserSmokeEnabled()",
            "IsWasmProfilePreferencesBookmarkSmokeEnabled()",
            "IsWasmProfilePreferencesCookieSmokeEnabled()",
            "IsWasmProfilePreferencesHistorySmokeEnabled()",
            "IsWasmProfileRendererLocalStorageSmokeEnabled()",
        ):
            with self.subTest(owner=owner):
                self.assertIn(owner, validation)
        self.assertIn(_MACRO, validation)
        bookmark_positive = validation.index(
            "chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled()"
        )
        bookmark_negative = validation.index(
            "!chrome::IsWasmProfilePreferencesBookmarkSmokeEnabled()"
        )
        bookmark_macro = validation.rfind(_MACRO, 0, bookmark_positive)
        self.assertGreaterEqual(bookmark_macro, 0)
        self.assertLess(bookmark_macro, bookmark_positive)
        self.assertLess(bookmark_positive, bookmark_negative)
        self.assertIn("if (!aggregate_smoke_enabled)", validation)
        self.assertNotIn("IsWasmProfileDatabaseSmokeEnabled", validation)

    def test_runtime_orders_browser_bookmark_cookie_history_then_local_storage(
        self,
    ) -> None:
        startup = _body_after_marker(
            self.main_parts, "int WasmBrowserMainParts::PreMainMessageLoopRun()"
        )
        browser = startup.index("RunWasmBrowserSmoke(profile_.get())")
        bookmark_start = startup.index(
            "StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown();"
        )
        self.assertLess(browser, bookmark_start)
        self.assertIn(_MACRO, _prefix_before(startup, bookmark_start, 1800))

        start_bookmark = _body_after_marker(
            self.main_parts,
            "StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown() {",
        )
        take_input = start_bookmark.index(
            "TakeWasmProfilePreferencesBookmarkSmokeInput()"
        )
        acquire = start_bookmark.index(
            "TryAcquireWasmProfileStorageProfileIO()"
        )
        start_owner = start_bookmark.index("profile_->StartBookmarkSmoke(")
        self.assertLess(take_input, acquire)
        self.assertLess(acquire, start_owner)

        bookmark_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileBookmarkSmokeComplete(",
        )
        bookmark_receipt = bookmark_complete.index(
            "profile_->DidBookmarkSmokeSucceed()"
        )
        cookie_start = bookmark_complete.index(
            "StartWasmProfileCookieSmokeOrHistoryOrShutdown();"
        )
        self.assertLess(bookmark_receipt, cookie_start)

        cookie_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileCookieSmokeComplete(",
        )
        cookie_receipt = cookie_complete.index("DidCookieSmokeSucceed()")
        history_start = cookie_complete.index(
            "StartWasmProfileHistorySmokeOrShutdown();"
        )
        self.assertLess(cookie_receipt, history_start)
        self.assertIn(_MACRO, cookie_complete)

        history_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileHistorySmokeComplete(",
        )
        history_receipt = history_complete.index("DidHistorySmokeSucceed()")
        local_storage_start = history_complete.index(
            "StartWasmProfileRendererLocalStorageSmokeOrShutdown();"
        )
        self.assertLess(history_receipt, local_storage_start)
        self.assertIn(_MACRO, history_complete)

        local_storage_complete = _body_after_marker(
            self.main_parts,
            "void WasmBrowserMainParts::\n"
            "    OnWasmProfileRendererLocalStorageSmokeComplete(bool success)",
        )
        local_storage_receipt = local_storage_complete.index(
            "DidLocalStorageSmokeSucceed()"
        )
        shutdown = local_storage_complete.index("RequestShutdown();")
        self.assertLess(local_storage_receipt, shutdown)

    def test_bookmark_model_waits_for_write_close_and_delayed_completion(
        self,
    ) -> None:
        start = _body_after_marker(
            self.bookmark_smoke,
            "bool Start(base::OnceCallback<void(bool success)> completion)",
        )
        model_create = start.index("std::make_unique<bookmarks::BookmarkModel>")
        model_load = start.index("model_->Load(profile_path_)")
        load_receipt = start.index(
            "bookmarks::ScheduleCallbackOnBookmarkModelLoad("
        )
        self.assertLess(model_create, model_load)
        self.assertLess(model_load, load_receipt)
        for fail_closed_feature in (
            "bookmarks::kEncryptBookmarks",
            "bookmarks::ShouldWriteBookmarksToSecondaryFileOnDisk()",
            "bookmarks::ShouldUseEncryptedBookmarksAsPrimarySource()",
            "switches::kSyncEnableBookmarksInTransportMode",
        ):
            with self.subTest(feature=fail_closed_feature):
                self.assertIn(fail_closed_feature, start)

        flush = _body_after_marker(self.bookmark_smoke, "void FlushAndClose(")
        self.assertIn(
            "model_->FlushLocalOrSyncablePendingWriteForTesting(", flush
        )
        flushed = _body_after_marker(self.bookmark_smoke, "void OnWriteFlushed(")
        emit = flushed.index("EmitDigestMarker(marker, digest)")
        close = flushed.index("CloseAndFinish(operation_succeeded)")
        self.assertLess(emit, close)

        close_and_finish = _body_after_marker(
            self.bookmark_smoke, "void CloseAndFinish(bool operation_succeeded)"
        )
        destroy_model = close_and_finish.index("model_.reset()")
        complete_after_close = close_and_finish.index(
            "CompleteAfterModelClose(operation_succeeded)"
        )
        self.assertLess(destroy_model, complete_after_close)

        delayed = _body_after_marker(
            self.bookmark_smoke,
            "void CompleteAfterModelClose(bool operation_succeeded)",
        )
        self.assertIn("completion_delivery_pending_ = true", delayed)
        self.assertIn("PostTask(", delayed)
        self.assertIn("&State::DeliverCompletion", delayed)

        deliver = _body_after_marker(
            self.bookmark_smoke, "void DeliverCompletion()"
        )
        retire_io = deliver.index("profile_io_hold_->Complete(")
        notify_owner = deliver.index("std::move(completion).Run(succeeded)")
        self.assertLess(retire_io, notify_owner)
        self.assertNotIn("BOOKMARK_BACKEND_CLOSED", self.bookmark_smoke)

        cancel = _body_after_marker(self.bookmark_smoke, "void Cancel()")
        self.assertIn("if (flush_pending_)", cancel)
        self.assertIn("if (!model_->loaded())", cancel)
        self.assertIn("FailAndClose();", cancel)
        quarantine = _body_after_marker(
            self.bookmark_smoke,
            "bool WasmProfileBookmarkLifetimeParticipant::"
            "QuarantineForFailureShutdown()",
        )
        self.assertLess(quarantine.index("state_->Cancel()"),
                        quarantine.index("quarantined_states"))
        self.assertIn(
            "std::vector<std::unique_ptr<State>>", quarantine
        )
        self.assertIn("admission active", self.bookmark_smoke_header)

    def test_cookie_history_and_local_storage_require_exact_close_receipts(
        self,
    ) -> None:
        cookie_close = _body_after_marker(
            self.cookie_smoke, "void BeginBackendClose()"
        )
        self.assertIn("CloseCookieStoreForTesting", cookie_close)
        self.assertIn("&State::OnBackendClosed", cookie_close)
        cookie_closed = _body_after_marker(
            self.cookie_smoke, "void OnBackendClosed(bool success)"
        )
        self.assertLess(
            cookie_closed.index("close_receipt_received_ = true"),
            cookie_closed.index("ScheduleCompletion(operation_succeeded)"),
        )

        history_close = _body_after_marker(self.history_smoke, "void Close()")
        receipt = history_close.index("SetOnBackendDestroyTask(")
        shutdown = history_close.index("history_service_->Shutdown()")
        release = history_close.index("history_service_.reset()")
        self.assertLess(receipt, shutdown)
        self.assertLess(shutdown, release)
        history_complete = _body_after_marker(
            self.history_smoke,
            "void CompleteAfterBackendClose(bool operation_succeeded)",
        )
        self.assertLess(
            history_complete.index("profile_io_hold_->Complete("),
            history_complete.index("std::move(completion_).Run(succeeded_)"),
        )

        local_close = _body_after_marker(
            self.local_storage_smoke,
            "void OnCloseFenceReady("
            "storage::mojom::WasmLocalStorageTestResult result)",
        )
        self.assertLess(
            local_close.index('EmitDigestMarker("DB_CLOSE_OK")'),
            local_close.index("CompleteAfterExactCloseReceipt("),
        )

    def test_shutdown_gates_and_quarantines_all_four_participants(self) -> None:
        maybe_shutdown = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::MaybeStartShutdown()"
        )
        finish_shutdown = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        foundation = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        destructor = _body_after_marker(
            self.profile, "WasmProfile::~WasmProfile()"
        )

        for body in (maybe_shutdown, finish_shutdown):
            bookmark = body.index("HasActiveBookmarkSmoke()")
            cookie = body.index("HasActiveCookieSmoke()")
            history = body.index("HasActiveHistorySmoke()")
            local_storage = body.index("HasActiveLocalStorageSmoke()")
            self.assertLess(bookmark, cookie)
            self.assertLess(cookie, history)
            self.assertLess(history, local_storage)
            self.assertIn(_MACRO, _prefix_before(body, "HasActiveBookmarkSmoke()"))

        for body in (foundation, destructor):
            for quarantine in (
                "QuarantineBookmarkSmokeForFailureShutdown()",
                "QuarantineCookieSmokeForFailureShutdown()",
                "QuarantineHistorySmokeForFailureShutdown()",
                "QuarantineLocalStorageSmokeForFailureShutdown()",
            ):
                with self.subTest(quarantine=quarantine):
                    self.assertIn(quarantine, body)
            self.assertIn(
                _MACRO,
                _prefix_before(
                    body, "QuarantineBookmarkSmokeForFailureShutdown()"
                ),
            )

        for owner in (
            "bookmark_lifetime_participant_",
            "cookie_lifetime_participant_",
            "history_lifetime_participant_",
            "local_storage_lifetime_participant_",
        ):
            with self.subTest(owner=owner):
                self.assertIn(owner, self.profile_header)

    def test_one_v4_drain_fans_out_one_result_to_both_protocols(self) -> None:
        drain_body = _body_after_marker(
            self.chrome_main,
            "if (chrome::NeedsWasmProfileStorageBackendDrain())",
        )
        self.assertEqual(
            drain_body.count(
                "WasmProfileStorageDrainResult drain_result =\n"
                "        chrome::DrainAndReleaseWasmProfileStorageBackend();"
            ),
            1,
        )
        for notification in (
            "NotifyWasmProfilePreferencesSmokeBackendDrain",
            "NotifyWasmProfileLocalStorageSmokeBackendDrain",
        ):
            with self.subTest(notification=notification):
                self.assertIn(
                    f"chrome::{notification}(\n"
                    "        drain_result.Succeeded());",
                    drain_body,
                )
        missing_drain = _body_after_marker(
            self.chrome_main, "} else if (aggregate_smoke_enabled)"
        )
        self.assertIn(
            "NotifyWasmProfilePreferencesSmokeBackendDrain(false)",
            missing_drain,
        )
        self.assertIn(
            "NotifyWasmProfileLocalStorageSmokeBackendDrain(false)",
            missing_drain,
        )

    def test_default_partition_stays_in_memory_and_paths_remain_narrow(
        self,
    ) -> None:
        default_partition = _body_after_marker(
            self.profile,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn("return true;", default_partition)
        self.assertNotIn("return false;", default_partition)
        self.assertNotIn("#if", default_partition)
        self.assertNotIn(_MACRO, default_partition)

        bookmark_owner = _body_after_marker(
            self.profile, "bool WasmProfile::StartBookmarkSmoke("
        )
        self.assertIn("profile_path_", bookmark_owner)
        self.assertIn("WasmProfileBookmarkLifetimeParticipant", bookmark_owner)

        network_params = _body_after_marker(
            self.content_client,
            "void WasmContentBrowserClient::ConfigureNetworkContextParams(",
        )
        for cookie_path in (
            "IsWasmProfilePreferencesCookieSmokeEnabled()",
            "profile_path.AppendASCII(kWasmNetworkDataDirectory)",
            'base::FilePath(FILE_PATH_LITERAL("Cookies"))',
            "http_cache_enabled = false",
        ):
            with self.subTest(cookie_path=cookie_path):
                self.assertIn(cookie_path, network_params)
        self.assertIn(_MACRO, self.content_client)

        self.assertIn(
            "history::HistoryDatabaseParamsForPath(\n"
            "            profile_path_, version_info::Channel::UNKNOWN)",
            self.history_smoke,
        )
        local_storage_path = _body_after_marker(
            self.dom_storage,
            "std::optional<base::FilePath> GetLocalStoragePath(",
        )
        self.assertIn("partition->GetConfig().is_default()", local_storage_path)
        self.assertIn("browser_context->GetPath()", local_storage_path)
        self.assertIn(_MACRO, self.dom_storage)
        self.assertIn(
            "ProfileStorageMount::kDefaultProfile",
            _body_after_marker(
                self.profile_storage,
                "bool InitializeWasmProfilePreferencesStorage()",
            ),
        )

    def test_macro_layout_and_bridge_source_selection_are_closed(self) -> None:
        for build_file in (
            self.chrome_build,
            self.wasm_build,
            self.content_build,
            self.content_public_build,
            self.storage_build,
        ):
            with self.subTest(build_file=build_file[:48]):
                self.assertIn(_FLAG, build_file)
                self.assertIn(_MACRO, build_file)
        self.assertIn(_FLAG, self.storage_mojom_build)

        for implementation in (
            self.chrome_main,
            self.main_parts,
            self.main_parts_header,
            self.profile,
            self.profile_header,
            self.profile_storage,
            self.profile_storage_header,
            self.content_client,
            self.dom_storage,
            self.dom_storage_header,
            self.dom_storage_test_support,
            self.local_storage_impl,
            self.local_storage_impl_header,
            self.storage_service,
            self.storage_service_header,
        ):
            with self.subTest(implementation=implementation[:48]):
                self.assertIn(_MACRO, implementation)

        profile_config = _body_after_marker(
            self.wasm_build, f'config("{_CONFIG}")'
        )
        self.assertIn(f'"{_MACRO}=1"', profile_config)

        bookmark_target_start = self.wasm_build.index(
            'source_set("wasm_profile_bookmark_smoke")'
        )
        bookmark_gate = self.wasm_build[
            self.wasm_build.rfind("if (", 0, bookmark_target_start) :
            bookmark_target_start
        ]
        self.assertIn(_FLAG, bookmark_gate)

        content_target = _body_after_marker(
            self.content_build, 'source_set("browser")'
        )
        content_gate = _body_after_marker(content_target, f"if ({_FLAG})")
        self.assertIn(f'"{_MACRO}=1"', content_gate)
        self.assertIn(
            '"dom_storage/wasm_dom_storage_test_support.cc",', content_target
        )
        self.assertIn(
            '"//components/services/storage/public/mojom:'
            'wasm_local_storage_test_api",',
            content_target,
        )

        storage_target = _body_after_marker(
            self.storage_build, 'source_set("storage")'
        )
        storage_gate = _body_after_marker(storage_target, f"if ({_FLAG})")
        self.assertIn(f'":{_BRIDGE_CONFIG}"', storage_gate)
        self.assertIn("public_configs", storage_gate)
        self.assertIn(
            '"//components/services/storage/public/mojom:'
            'wasm_local_storage_test_api",',
            storage_target,
        )
        self.assertNotIn("wasm_profile_database_smoke", content_gate)
        self.assertNotIn("wasm_profile_database_smoke", storage_gate)


if __name__ == "__main__":
    unittest.main()

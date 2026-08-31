#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the M7 Preferences acceptance helper and probes."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
    """Returns one balanced C++ function body without relying on line layout."""

    start = text.index(signature)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing brace for {signature}")


def _bracket_body_after(text: str, marker: str) -> str:
    """Returns one balanced GN list body after |marker|."""

    start = text.index(marker)
    opening = text.index("[", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing bracket for {marker}")


_M7_PREFERENCES_MACROS = (
    "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST",
    "CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST",
)


_NORMAL_CHROME_MAIN_M7_EXCLUSION_GUARD = """#if !defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) && \\
    !defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST) && \\
    !defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) && \\
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) && \\
    !defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \\
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) && \\
    !defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)"""


def _is_in_m7_preferences_macro_block(text: str, position: int) -> bool:
    """Returns whether |position| is under a positive M7 prefs capability."""

    active_stack: list[bool] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if offset <= position < offset + len(line):
            return any(active_stack)

        directive = line.lstrip()
        grants_capability = any(
            f"defined({macro})" in directive
            and f"!defined({macro})" not in directive
            for macro in _M7_PREFERENCES_MACROS
        )
        if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
            active_stack.append(grants_capability)
        elif re.match(r"#\s*elif\b", directive):
            if active_stack:
                active_stack[-1] = grants_capability
        elif re.match(r"#\s*else\b", directive):
            if active_stack:
                active_stack[-1] = False
        elif re.match(r"#\s*endif\b", directive):
            if active_stack:
                active_stack.pop()
        offset += len(line)
    return False


def _assert_only_in_m7_blocks(
    testcase: unittest.TestCase, text: str, token: str
) -> None:
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(
                _is_in_m7_preferences_macro_block(text, position),
                f"{token} is not M7-config-gated",
            )


class M7ProfilePreferencesSmokeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.header = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.h"
        )
        self.smoke = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.cc"
        )
        self.history = source("chrome/browser/wasm/wasm_profile_history_smoke.cc")
        self.history_header = source(
            "chrome/browser/wasm/wasm_profile_history_smoke.h"
        )
        self.history_lifetime_unittest = source(
            "chrome/browser/wasm/wasm_profile_history_lifetime_participant_unittest.cc"
        )
        self.bookmark = source("chrome/browser/wasm/wasm_profile_bookmark_smoke.cc")
        self.bookmark_header = source(
            "chrome/browser/wasm/wasm_profile_bookmark_smoke.h"
        )
        self.bookmark_model = source(
            "components/bookmarks/browser/bookmark_model.cc"
        )
        self.bookmark_model_header = source(
            "components/bookmarks/browser/bookmark_model.h"
        )
        self.bookmark_storage = source(
            "components/bookmarks/browser/bookmark_storage.cc"
        )
        self.bookmark_storage_header = source(
            "components/bookmarks/browser/bookmark_storage.h"
        )
        self.bookmark_lifetime_unittest = source(
            "chrome/browser/wasm/wasm_profile_bookmark_lifetime_participant_unittest.cc"
        )
        self.cookie = source("chrome/browser/wasm/wasm_profile_cookie_smoke.cc")
        self.cookie_header = source(
            "chrome/browser/wasm/wasm_profile_cookie_smoke.h"
        )
        self.cookie_lifetime_unittest = source(
            "chrome/browser/wasm/wasm_profile_cookie_lifetime_participant_unittest.cc"
        )
        self.content_client = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )
        self.sqlite_backend = source(
            "net/extras/sqlite/sqlite_persistent_store_backend_base.cc"
        )
        self.sqlite_backend_header = source(
            "net/extras/sqlite/sqlite_persistent_store_backend_base.h"
        )
        self.sqlite_cookie_store = source(
            "net/extras/sqlite/sqlite_persistent_cookie_store.cc"
        )
        self.sqlite_cookie_store_header = source(
            "net/extras/sqlite/sqlite_persistent_cookie_store.h"
        )
        self.session_cookie_store = source(
            "services/network/session_cleanup_cookie_store.cc"
        )
        self.session_cookie_store_header = source(
            "services/network/session_cleanup_cookie_store.h"
        )
        self.cookie_manager = source("services/network/cookie_manager.cc")
        self.cookie_manager_header = source("services/network/cookie_manager.h")
        self.cookie_manager_mojom = source(
            "services/network/public/mojom/cookie_manager.mojom"
        )
        self.test_cookie_manager = source(
            "services/network/test/test_cookie_manager.h"
        )
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.profile_storage = source(
            "chrome/browser/wasm/wasm_profile_storage.cc"
        )
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_build = source("chrome/browser/wasm/BUILD.gn")
        self.m7_gni = source(
            "chrome/browser/wasm/wasm_profile_preferences_smoke.gni"
        )

    def test_strict_private_argument_and_digest_protocol(self) -> None:
        for token in (
            'constexpr char kSmokeSwitch[] = "wasm-profile-preferences-smoke";',
            'constexpr char kTokenASwitch[] = "wasm-profile-preferences-token-a";',
            'constexpr char kTokenBSwitch[] = "wasm-profile-preferences-token-b";',
            '"wasm-profile-preferences-browser-smoke"',
            '"wasm-profile-preferences-history-smoke"',
            '"wasm-profile-preferences-cookie-smoke"',
            '"wasm-profile-preferences-bookmark-smoke"',
            'constexpr char kWriteMode[] = "write";',
            'constexpr char kVerifyAndWriteMode[] = "verify-and-write";',
            'constexpr char kVerifyBMode[] = "verify-b";',
            "constexpr size_t kOpaqueTokenLength = 64;",
            "value.size() != kOpaqueTokenLength",
            "character >= '0' && character <= '9'",
            "character >= 'a' && character <= 'f'",
            '#include "crypto/hash.h"',
            "crypto::hash::Sha256(token)",
            "base::HexEncodeLower",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        self.assertNotIn('#include "crypto/sha2.h"', self.smoke)
        self.assertNotIn("SHA256HashString", self.smoke)
        self.assertIn(
            "--wasm-profile-preferences-smoke=verify-and-write", self.header
        )
        self.assertIn("--wasm-profile-preferences-smoke=verify-b", self.header)
        self.assertIn("--wasm-profile-preferences-bookmark-smoke", self.header)
        self.assertIn("token_b_ == token_a_", self.smoke)
        self.assertIn("token B must differ from token A", self.header)
        self.assertIn("if (has_token_a || !has_token_b)", self.smoke)
        self.assertIn("where |digest| is exactly 64 lowercase hexadecimal", self.header)
        self.assertIn(
            "arguments, capability, storage, profile, browser, cookie,",
            self.header,
        )

    def test_markers_are_stderr_only_digest_or_fixed_failure_output(self) -> None:
        for token in (
            'constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_PREFS:";',
            'EmitMarker("READY")',
            'EmitDigestMarker("READ_A_OK", token_a_digest_)',
            'EmitDigestMarker("READ_B_OK", token_b_digest_)',
            'EmitDigestMarker("WRITE_ACCEPTED", token_b_digest_)',
            'EmitDigestMarker("WRITE_ACCEPTED", token_a_digest_)',
            'EmitMarker("BROWSER_SMOKE_CLOSED")',
            'EmitMarker("HISTORY_BACKEND_CLOSED")',
            'EmitDigestMarker("FENCE_OK", expected_fence_digest_)',
            'EmitMarker("LEASE_RELEASED")',
            'std::fprintf(stderr, "%sFAIL stage=%s\\n", kMarkerPrefix,',
            'std::fprintf(stderr, "%s%s sha256=%s\\n", kMarkerPrefix, marker,',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.smoke)

        for token in (
            "token_a_.c_str()",
            "token_b_.c_str()",
            "kSmokePref.c_str()",
            "std::cout",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, self.smoke)

        emit_marker = _body_after_signature(
            self.smoke, "void EmitMarker(const char* marker)"
        )
        emit_digest_marker = _body_after_signature(
            self.smoke,
            "void EmitDigestMarker(const char* marker, const std::string& digest)",
        )
        self.assertNotIn("token_", emit_marker)
        self.assertNotIn("token_", emit_digest_marker)
        self.assertIn("digest.c_str()", emit_digest_marker)

        report_failure = _body_after_signature(
            self.smoke,
            "void ReportFailure(WasmProfilePreferencesSmokeFailureStage stage)",
        )
        self.assertLess(
            report_failure.index("ClearRawTokens();"),
            report_failure.index("std::fprintf(stderr"),
        )
        self.assertEqual(self.smoke.count("std::fprintf(stderr"), 3)
        for output_body in (emit_marker, emit_digest_marker, report_failure):
            for sensitive in (
                "kTokenASwitch",
                "kTokenBSwitch",
                "token_a_",
                "token_b_",
                "kSmokePref",
            ):
                with self.subTest(sensitive=sensitive):
                    self.assertNotIn(sensitive, output_body)
        clear_raw_tokens = _body_after_signature(self.smoke, "void ClearRawTokens()")
        self.assertIn("token_a_.clear();", clear_raw_tokens)
        self.assertIn("token_b_.clear();", clear_raw_tokens)

    def test_profile_action_writes_a_then_reads_a_writes_b_then_reads_b(self) -> None:
        start = _body_after_signature(self.smoke, "bool Start(PrefService* prefs)")
        ready = start.index('EmitMarker("READY");')
        verify = start.index("if (mode_ == SmokeMode::kVerifyAndWrite)")
        verify_b = start.index("else if (mode_ == SmokeMode::kVerifyB)")
        read = start.index("prefs->GetString(kSmokePref) != token_a_")
        read_marker = start.index('EmitDigestMarker("READ_A_OK", token_a_digest_);')
        write_b = start.index("prefs->SetString(kSmokePref, token_b_);")
        write_b_marker = start.index(
            'EmitDigestMarker("WRITE_ACCEPTED", token_b_digest_);'
        )
        write_a = start.index("prefs->SetString(kSmokePref, token_a_);")
        write_a_marker = start.index(
            'EmitDigestMarker("WRITE_ACCEPTED", token_a_digest_);'
        )
        read_b = start.index("prefs->GetString(kSmokePref) != token_b_")
        read_b_marker = start.index('EmitDigestMarker("READ_B_OK", token_b_digest_);')
        clear = start.index("ClearRawTokens();")

        self.assertLess(ready, verify)
        self.assertLess(verify, read)
        self.assertLess(read, read_marker)
        self.assertLess(read_marker, write_b)
        self.assertLess(write_b, write_b_marker)
        self.assertLess(write_a, write_a_marker)
        self.assertLess(write_b_marker, clear)
        self.assertLess(write_a_marker, clear)
        self.assertLess(verify_b, read_b)
        self.assertLess(read_b, read_b_marker)
        self.assertLess(read_b_marker, clear)
        self.assertNotIn("FENCE_OK", start)

        storage_lifecycle = _body_after_signature(
            self.smoke, "void NotifyStorageLifecycle(bool success)"
        )
        browser = _body_after_signature(
            self.smoke, "void NotifyBrowserSmokeResult(bool success)"
        )
        fence = _body_after_signature(
            self.smoke, "void NotifyFenceResult(bool success)"
        )
        backend_drain = _body_after_signature(
            self.smoke, "void NotifyBackendDrain(bool success)"
        )
        self.assertIn("if (fence_succeeded_)", fence)
        self.assertIn(
            "!success || !fence_succeeded_ || storage_lifecycle_succeeded_",
            storage_lifecycle,
        )
        self.assertIn("storage_lifecycle_succeeded_ = true;", storage_lifecycle)
        self.assertIn("storage_lifecycle_succeeded_", storage_lifecycle)
        self.assertIn("!storage_lifecycle_succeeded_", backend_drain)
        self.assertIn("if (lease_released_)", backend_drain)
        self.assertIn("browser_smoke_required_", browser)
        self.assertIn("browser_smoke_completed_ = true;", browser)
        self.assertIn('EmitMarker("BROWSER_SMOKE_CLOSED")', browser)
        self.assertIn(
            "browser_smoke_required_ && !browser_smoke_completed_", fence
        )
        history = _body_after_signature(
            self.smoke, "void NotifyHistorySmokeResult(bool success)"
        )
        self.assertIn("history_smoke_required_", history)
        self.assertIn("!browser_smoke_completed_", history)
        self.assertIn("history_smoke_completed_ = true;", history)
        self.assertIn('EmitMarker("HISTORY_BACKEND_CLOSED")', history)
        self.assertIn(
            "history_smoke_required_ && !history_smoke_completed_", fence
        )
        bookmark = _body_after_signature(
            self.smoke, "void NotifyBookmarkSmokeResult(bool success)"
        )
        self.assertIn("bookmark_smoke_required_", bookmark)
        self.assertIn("!browser_smoke_completed_", bookmark)
        self.assertIn("!bookmark_smoke_input_taken_", bookmark)
        self.assertIn("bookmark_smoke_completed_ = true;", bookmark)
        self.assertIn('EmitMarker("BOOKMARK_MODEL_CLOSED")', bookmark)
        self.assertIn(
            "bookmark_smoke_required_ && !bookmark_smoke_completed_", fence
        )
        cookie = _body_after_signature(
            self.smoke, "void NotifyCookieSmokeResult(bool success)"
        )
        self.assertIn("cookie_smoke_required_", cookie)
        self.assertIn("!browser_smoke_completed_", cookie)
        self.assertIn(
            "bookmark_smoke_required_ && !bookmark_smoke_completed_", cookie
        )
        self.assertIn("cookie_smoke_completed_ = true;", cookie)
        self.assertIn(
            "cookie_smoke_required_ && !cookie_smoke_completed_", fence
        )

    def test_history_service_probe_is_profile_owned_and_blocks_early_handoff(self) -> None:
        for token in (
            '#include "components/history/core/browser/history_service.h"',
            "std::make_unique<history::HistoryService>(",
            "history::HistoryDatabaseParamsForPath(",
            "history::SOURCE_BROWSED",
            "history_service_->AddPage(",
            "history_service_->SetPageTitle(",
            "history_service_->FlushForTest(",
            "history_service_->QueryURLAndVisits(",
            "history_service_->SetOnBackendDestroyTask(",
            "history_service_->Shutdown();",
            "history_service_.reset();",
            '"HISTORY_A_WRITE_ACCEPTED"',
            '"HISTORY_A_READ_OK"',
            '"HISTORY_B_WRITE_ACCEPTED"',
            '"HISTORY_B_READ_OK"',
            '"HISTORY_QUERY_VALIDATION_FAILED"',
            '"HISTORY_QUERY_NOT_FOUND"',
            '"HISTORY_QUERY_URL_MISMATCH"',
            '"HISTORY_QUERY_TITLE_MISMATCH"',
            '"HISTORY_QUERY_NO_VISITS"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.history)

        for forbidden in (
            "HistoryServiceFactory::",
            "ChromeHistoryClient",
            "BookmarkModelFactory",
            "StoragePartition::",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.history)

        self.assertIn(
            "class WasmProfileHistoryLifetimeParticipant", self.history_header
        )
        self.assertIn(
            "WasmProfileOrderedDrainLifecycle::ProfileIOHold", self.history_header
        )
        self.assertIn(
            "std::unique_ptr<chrome::WasmProfileHistoryLifetimeParticipant>",
            self.profile_header,
        )
        self.assertIn("bool StartHistorySmoke(", self.profile_header)
        self.assertIn("bool HasActiveHistorySmoke() const;", self.profile_header)
        self.assertIn("void CancelHistorySmokeForShutdown();", self.profile_header)
        self.assertIn(
            "void QuarantineHistorySmokeForFailureShutdown();",
            self.profile_header,
        )
        self.assertIn("bool QuarantineForFailureShutdown();", self.history_header)

        close = _body_after_signature(self.history, "void Close()")
        backend_destroy = _body_after_signature(
            self.history, "void OnBackendDestroyed()"
        )
        terminal = _body_after_signature(
            self.history,
            "void CompleteAfterBackendClose(bool operation_succeeded)",
        )
        self.assertLess(
            close.index("SetOnBackendDestroyTask"), close.index("Shutdown();")
        )
        self.assertLess(
            close.index("Shutdown();"), close.index("history_service_.reset();")
        )
        self.assertIn("CompleteAfterBackendClose", backend_destroy)
        self.assertLess(
            terminal.index("profile_io_hold_->Complete("),
            terminal.index("completed_ = true;"),
        )
        self.assertLess(
            terminal.index("completed_ = true;"),
            terminal.index("std::move(completion_).Run(succeeded_);"),
        )
        self.assertIn("task_tracker_.TryCancelAll();", self.history)
        state_start = _body_after_signature(
            self.history, "bool Start(base::OnceCallback<void(bool success)> completion)"
        )
        duplicate_start = state_start.index("if (started_ || completed_)")
        invalid_start = state_start.index("if (!profile_io_hold_ || !completion)")
        self.assertLess(duplicate_start, invalid_start)
        self.assertNotIn(
            "CompleteAfterBackendClose", state_start[duplicate_start:invalid_start]
        )
        self.assertIn("CompleteAfterBackendClose", state_start[invalid_start:])
        cancel_state = _body_after_signature(self.history, "void Cancel()")
        self.assertLess(
            cancel_state.index("if (closing_)"),
            cancel_state.index("if (!history_service_)"),
        )
        self.assertIn("return;", cancel_state[cancel_state.index("if (closing_)") :])
        self.assertIn("base::WeakPtrFactory<State> weak_ptr_factory_{this};", self.history)
        self.assertNotIn("base::Unretained(this)", self.history)

        participant_destructor = _body_after_signature(
            self.history,
            "WasmProfileHistoryLifetimeParticipant::~WasmProfileHistoryLifetimeParticipant()",
        )
        self.assertIn("QuarantineForFailureShutdown();", participant_destructor)
        quarantine = _body_after_signature(
            self.history,
            "bool WasmProfileHistoryLifetimeParticipant::QuarantineForFailureShutdown()",
        )
        self.assertIn("state_->Cancel();", quarantine)
        self.assertIn(
            "base::NoDestructor<std::vector<std::unique_ptr<State>>>", quarantine
        )
        self.assertIn("quarantined_states->push_back(std::move(state_));", quarantine)
        self.assertLess(
            quarantine.index("state_->Cancel();"),
            quarantine.index("quarantined_states->push_back"),
        )
        self.assertNotIn("CompleteAfterBackendClose(", quarantine)
        self.assertIn("~State() override = default;", self.history)

        verify = _body_after_signature(self.history, "void Verify(GURL url,")
        callback = verify.index("auto on_query =")
        query = verify.index("history_service_->QueryURLAndVisits(")
        self.assertLess(callback, query)
        self.assertIn("weak_ptr_factory_.GetWeakPtr()", verify)
        self.assertIn("std::move(on_query)", verify)

        profile_start = _body_after_signature(
            self.profile, "bool WasmProfile::StartHistorySmoke("
        )
        self.assertIn(
            "std::make_unique<chrome::WasmProfileHistoryLifetimeParticipant>",
            profile_start,
        )
        self.assertIn("std::move(profile_io_hold)", profile_start)
        self.assertIn("history_lifetime_participant_->Start", profile_start)
        self.assertIn("ProfileIOCompletion::kFailed", profile_start)

        destructor = _body_after_signature(
            self.profile, "WasmProfile::~WasmProfile()"
        )
        self.assertLess(
            destructor.index("QuarantineHistorySmokeForFailureShutdown();"),
            destructor.index("prefs_lifetime_profile_io_participant_->Cancel();"),
        )

        start_history = _body_after_signature(
            self.main_parts,
            "void WasmBrowserMainParts::StartWasmProfileHistorySmokeOrShutdown()",
        )
        self.assertIn("chrome::TryAcquireWasmProfileStorageProfileIO()", start_history)
        self.assertIn("profile_->StartHistorySmoke(", start_history)
        self.assertIn("std::move(*profile_io_hold)", start_history)
        self.assertNotIn("std::shared_ptr<std::optional", start_history)
        self.assertNotIn("->Complete(", start_history)

        completion = _body_after_signature(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileHistorySmokeComplete(bool success)",
        )
        self.assertIn(
            "success && profile_ && profile_->DidHistorySmokeSucceed()",
            completion,
        )
        self.assertIn(
            "NotifyWasmProfilePreferencesHistorySmokeResult(history_succeeded)",
            completion,
        )
        self.assertIn("if (shutdown_requested_)", completion)
        self.assertIn("MaybeStartShutdown();", completion)
        self.assertIn("RequestShutdown();", completion)

        maybe_shutdown = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::MaybeStartShutdown()"
        )
        history_guard = maybe_shutdown.index("profile_->HasActiveHistorySmoke()")
        finish_call = maybe_shutdown.index("FinishShutdown();")
        self.assertLess(history_guard, finish_call)
        self.assertIn("profile_->CancelHistorySmokeForShutdown();", maybe_shutdown)

        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        self.assertIn("profile_->HasActiveHistorySmoke()", finish)
        self.assertIn("profile_->CancelHistorySmokeForShutdown();", finish)
        self.assertLess(
            finish.index("profile_->HasActiveHistorySmoke()"),
            finish.index("profile_->Shutdown();"),
        )

        foundation = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        self.assertIn("profile_->QuarantineHistorySmokeForFailureShutdown();", foundation)
        self.assertLess(
            foundation.index("profile_->QuarantineHistorySmokeForFailureShutdown();"),
            foundation.index("profile_->Shutdown();"),
        )

        storage_drain = _body_after_signature(
            self.profile_storage,
            "WasmProfileStorageDrainResult DrainAndReleaseBackend()",
        )
        waiting = storage_drain.index("kWaitingForRegisteredProfileIO")
        refused_return = storage_drain.index("return result;", waiting)
        transaction = storage_drain.index("backend_drain_attempted_ = true;")
        waiting_body = storage_drain[waiting:refused_return]
        self.assertIn("result.error = -EBUSY;", waiting_body)
        self.assertIn("result.refused_for_outstanding_profile_io = true;", waiting_body)
        # The fallback quarantine leaves its hold live. ChromeMain must see
        # this refusal before selecting either backend operation, including
        # fail-closed retirement.
        self.assertLess(waiting, refused_return)
        self.assertLess(refused_return, transaction)

        # Exercise the production HistoryService shutdown path rather than
        # treating the source ordering as the only evidence. Before its actual
        # HistoryBackend destroy receipt, cancellation must leave the explicit
        # admission live and make both outer backend operations unavailable.
        self.assertIn(
            'test("wasm_profile_history_lifetime_participant_unittests")',
            self.wasm_build,
        )
        for token in (
            "base::test::TaskEnvironment task_environment;",
            "EnableWasmProfilePreferencesSmokeTestMode()",
            "std::make_unique<WasmProfileHistoryLifetimeParticipant>",
            "EXPECT_FALSE(participant->Start(base::BindOnce([](bool) {})));",
            "participant->Cancel();",
            "participant.reset();",
            "backend_destroyed_loop.Run();",
            "Lifecycle::Status::kWaitingForRegisteredProfileIO",
            "Lifecycle::Status::kRegisteredProfileIONotClean",
            "ClaimPostContentDrain().has_value()",
            "ClaimPostContentFailureRetirement().has_value()",
            "result.profile_io.failed_operations, 1u",
            "result.profile_io.abandoned_operations, 0u",
        ):
            with self.subTest(runtime_token=token):
                self.assertIn(token, self.history_lifetime_unittest)

        cancel = _body_after_signature(
            self.history_lifetime_unittest,
            "FoundationFallbackQuarantineRetainsProfileIOUntilBackendDestroyReceipt)",
        )
        cancel_call = cancel.index("participant->Cancel();")
        quarantine_call = cancel.index("participant->QuarantineForFailureShutdown()")
        owner_reset = cancel.index("participant.reset();")
        backend_receipt = cancel.index("backend_destroyed_loop.Run();")
        self.assertLess(cancel_call, backend_receipt)
        self.assertLess(cancel_call, quarantine_call)
        self.assertLess(quarantine_call, backend_receipt)
        self.assertLess(quarantine_call, owner_reset)
        self.assertLess(owner_reset, backend_receipt)
        pre_receipt = cancel[cancel_call:quarantine_call]
        self.assertIn("EXPECT_TRUE(participant->IsActive());", pre_receipt)
        self.assertIn("EXPECT_FALSE(completion_called);", pre_receipt)
        self.assertIn("kWaitingForRegisteredProfileIO", pre_receipt)
        self.assertEqual(pre_receipt.count("ClaimPostContentDrain().has_value()"), 1)
        self.assertEqual(
            pre_receipt.count("ClaimPostContentFailureRetirement().has_value()"),
            1,
        )
        quarantine = cancel[quarantine_call:backend_receipt]
        self.assertIn("EXPECT_FALSE(participant->IsActive());", quarantine)
        self.assertIn("EXPECT_FALSE(completion_called);", quarantine)
        self.assertIn("kWaitingForRegisteredProfileIO", quarantine)
        self.assertEqual(quarantine.count("ClaimPostContentDrain().has_value()"), 2)
        self.assertEqual(
            quarantine.count("ClaimPostContentFailureRetirement().has_value()"),
            2,
        )

    def test_bookmark_model_probe_is_direct_and_closed_before_cookie_handoff(self) -> None:
        for token in (
            '#include "components/bookmarks/browser/bookmark_model.h"',
            "std::make_unique<bookmarks::BookmarkModel>(",
            "model_->Load(profile_path_);",
            "bookmarks::ScheduleCallbackOnBookmarkModelLoad(",
            "model_->GetNodesByURL(url)",
            "model_->AddNewURL(",
            "model_->Remove(",
            "FlushLocalOrSyncablePendingWriteForTesting(",
            "model_.reset();",
            '"BOOKMARK_A_WRITE_FLUSHED"',
            '"BOOKMARK_A_READ_OK"',
            '"BOOKMARK_B_WRITE_FLUSHED"',
            '"BOOKMARK_B_READ_OK"',
            '"BOOKMARK_CLEANUP_FLUSHED"',
            "bookmarks::kEncryptBookmarks",
            "bookmarks::ShouldWriteBookmarksToSecondaryFileOnDisk()",
            "bookmarks::ShouldUseEncryptedBookmarksAsPrimarySource()",
            "switches::kSyncEnableBookmarksInTransportMode",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.bookmark)

        for forbidden in (
            "BookmarkModelFactory",
            "ChromeBookmarkClient",
            "BookmarkMergedSurfaceService",
            "GetBookmarkModel()",
            "input_.token_a.c_str()",
            "input_.token_b.c_str()",
            "GetWasmProfileBookmarkSmokeState",
            "WasmProfileBookmarkSmokeState",
            "DidWasmProfileBookmarkSmokeSucceed",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.bookmark)

        close = _body_after_signature(
            self.bookmark, "void CloseAndFinish(bool operation_succeeded)"
        )
        self.assertLess(
            close.index("model_.reset();"),
            close.index("CompleteAfterModelClose(operation_succeeded);"),
        )
        on_write_flushed = _body_after_signature(
            self.bookmark, "void OnWriteFlushed("
        )
        self.assertLess(on_write_flushed.index("EmitMarker(marker);"),
                        on_write_flushed.index("CloseAndFinish("))
        self.assertLess(
            on_write_flushed.index("EmitDigestMarker(marker, digest);"),
            on_write_flushed.index("CloseAndFinish("),
        )
        self.assertIn("ImportantFileWriter result", self.bookmark_header)

        terminal = _body_after_signature(
            self.bookmark,
            "void CompleteAfterModelClose(bool operation_succeeded)",
        )
        self.assertIn("completion_delivery_pending_ = true;", terminal)
        self.assertIn(
            "pending_operation_succeeded_ = operation_succeeded;", terminal
        )
        self.assertIn(
            "CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask(",
            terminal,
        )
        self.assertIn("&State::DeliverCompletion", terminal)
        self.assertNotIn("profile_io_hold_->Complete(", terminal)
        self.assertLess(
            terminal.index("completion_delivery_pending_ = true;"),
            terminal.index(
                "CHECK(base::SequencedTaskRunner::GetCurrentDefault()->PostTask("
            ),
        )

        delivery = _body_after_signature(
            self.bookmark,
            "void DeliverCompletion()",
        )
        self.assertLess(
            delivery.index("profile_io_hold_->Complete("),
            delivery.index("completed_ = true;"),
        )
        self.assertLess(
            delivery.index("completed_ = true;"),
            delivery.index("std::move(completion).Run(succeeded);"),
        )
        self.assertIn("Do not access any member after", delivery)
        cancel = _body_after_signature(self.bookmark, "void Cancel()")
        self.assertLess(
            cancel.index("completed_ || completion_delivery_pending_"),
            cancel.index("failed_ = true;"),
        )

        self.assertIn(
            "class WasmProfileBookmarkLifetimeParticipant",
            self.bookmark_header,
        )
        self.assertIn(
            "WasmProfileOrderedDrainLifecycle::ProfileIOHold",
            self.bookmark_header,
        )
        self.assertIn("bool QuarantineForFailureShutdown();", self.bookmark_header)
        participant_destructor = _body_after_signature(
            self.bookmark,
            "~WasmProfileBookmarkLifetimeParticipant()",
        )
        self.assertIn("QuarantineForFailureShutdown();", participant_destructor)
        quarantine = _body_after_signature(
            self.bookmark,
            "bool WasmProfileBookmarkLifetimeParticipant::QuarantineForFailureShutdown()",
        )
        self.assertIn("state_->Cancel();", quarantine)
        self.assertIn(
            "base::NoDestructor<std::vector<std::unique_ptr<State>>>",
            quarantine,
        )
        self.assertIn("quarantined_states->push_back(std::move(state_));", quarantine)
        self.assertNotIn("CompleteAfterModelClose(", quarantine)

        self.assertIn(
            "std::unique_ptr<chrome::WasmProfileBookmarkLifetimeParticipant>",
            self.profile_header,
        )
        self.assertIn("bool StartBookmarkSmoke(", self.profile_header)
        self.assertIn("bool HasActiveBookmarkSmoke() const;", self.profile_header)
        self.assertIn("void CancelBookmarkSmokeForShutdown();", self.profile_header)
        self.assertIn(
            "void QuarantineBookmarkSmokeForFailureShutdown();",
            self.profile_header,
        )
        profile_start = _body_after_signature(
            self.profile, "bool WasmProfile::StartBookmarkSmoke("
        )
        self.assertIn(
            "std::make_unique<chrome::WasmProfileBookmarkLifetimeParticipant>",
            profile_start,
        )
        self.assertIn("std::move(profile_io_hold)", profile_start)
        self.assertIn("bookmark_lifetime_participant_->Start", profile_start)

        profile_destructor = _body_after_signature(
            self.profile, "WasmProfile::~WasmProfile()"
        )
        self.assertIn(
            "QuarantineBookmarkSmokeForFailureShutdown();",
            profile_destructor,
        )

        self.assertIn(
            "bool FlushLocalOrSyncablePendingWriteForTesting(",
            self.bookmark_model_header,
        )
        self.assertIn(
            "return local_or_syncable_store_->FlushPendingWriteForTesting(",
            self.bookmark_model,
        )
        self.assertIn(
            "bool FlushPendingWriteForTesting(", self.bookmark_storage_header
        )
        flush = _body_after_signature(
            self.bookmark_storage,
            "bool BookmarkStorage::FlushPendingWriteForTesting(",
        )
        self.assertIn("writer_.RegisterOnNextWriteCallbacks", flush)
        self.assertIn("writer_.DoScheduledWrite();", flush)

        start_bookmark = _body_after_signature(
            self.main_parts,
            "StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown() {",
        )
        self.assertIn("TakeWasmProfilePreferencesBookmarkSmokeInput", start_bookmark)
        self.assertIn("TryAcquireWasmProfileStorageProfileIO", start_bookmark)
        self.assertIn("profile_->StartBookmarkSmoke(", start_bookmark)
        self.assertIn("std::move(*profile_io_hold)", start_bookmark)
        self.assertNotIn("std::shared_ptr<std::optional", start_bookmark)
        self.assertNotIn("->Complete(", start_bookmark)

        bookmark_completion = _body_after_signature(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileBookmarkSmokeComplete(",
        )
        self.assertIn(
            "profile_->DidBookmarkSmokeSucceed()",
            bookmark_completion,
        )
        self.assertIn(
            "NotifyWasmProfilePreferencesBookmarkSmokeResult(bookmark_succeeded)",
            bookmark_completion,
        )
        self.assertIn("if (shutdown_requested_)", bookmark_completion)
        self.assertIn("MaybeStartShutdown();", bookmark_completion)
        self.assertIn(
            "StartWasmProfileCookieSmokeOrHistoryOrShutdown();",
            bookmark_completion,
        )

        maybe_shutdown = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::MaybeStartShutdown()"
        )
        self.assertLess(
            maybe_shutdown.index("profile_->HasActiveBookmarkSmoke()"),
            maybe_shutdown.index("FinishShutdown();"),
        )
        self.assertIn("profile_->CancelBookmarkSmokeForShutdown();", maybe_shutdown)

        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        self.assertLess(
            finish.index("profile_->HasActiveBookmarkSmoke()"),
            finish.index("profile_->Shutdown();"),
        )
        self.assertIn("profile_->CancelBookmarkSmokeForShutdown();", finish)
        bookmark_guard = finish.index(
            "IsWasmProfilePreferencesBookmarkSmokeEnabled()"
        )
        storage_handoff = finish.index("NotifyWasmProfileStorageProfileShutdown();")
        self.assertLess(storage_handoff, bookmark_guard)

        foundation = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        self.assertLess(
            foundation.index("profile_->QuarantineBookmarkSmokeForFailureShutdown();"),
            foundation.index("profile_->Shutdown();"),
        )

        self.assertIn(
            'test("wasm_profile_bookmark_lifetime_participant_unittests")',
            self.wasm_build,
        )
        for token in (
            "std::make_unique<WasmProfileBookmarkLifetimeParticipant>",
            "WasmProfileBookmarkImportantFileWriterTest",
            "FailingDataSerializer serializer;",
            "FailingBackgroundDataSerializer serializer;",
            "writer.RegisterOnNextWriteCallbacks(",
            "EXPECT_FALSE(before_write_called);",
            "EXPECT_FALSE(write_succeeded);",
            "active_during_delayed_completion",
            "delayed_participant->IsActive()",
            "delayed_participant->Cancel();",
            "base::ThreadPoolInstance::Get()->FlushForTesting();",
            "base::ScopedThreadPoolExecutionFence write_fence;",
            "base::RunLoop().RunUntilIdle();",
            "successful_loop.Run();",
            "successful_participant->DidSucceed()",
            "cancelled_participant->Cancel();",
            "cancelled_participant->QuarantineForFailureShutdown()",
            "cancelled_participant.reset();",
            "cancelled_loop.Run();",
            "Lifecycle::Status::kWaitingForRegisteredProfileIO",
            "Lifecycle::Status::kRegisteredProfileIONotClean",
            "ClaimPostContentDrain().has_value()",
            "ClaimPostContentFailureRetirement().has_value()",
            "cancelled_result.profile_io.failed_operations, 1u",
            "cancelled_result.profile_io.abandoned_operations, 0u",
        ):
            with self.subTest(runtime_token=token):
                self.assertIn(token, self.bookmark_lifetime_unittest)

    def test_cookie_manager_probe_closes_its_sqlite_backend_before_handoff(self) -> None:
        for token in (
            "GetCookieList(",
            "SetCanonicalCookie(",
            "DeleteCanonicalCookie(",
            "FlushCookieStore(",
            "CloseCookieStoreForTesting(",
            "net::CanonicalCookie::Create(",
            '"COOKIE_A_WRITE_FLUSHED"',
            '"COOKIE_A_READ_OK"',
            '"COOKIE_B_WRITE_FLUSHED"',
            '"COOKIE_B_READ_OK"',
            "COOKIE_BACKEND_CLOSED",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.cookie)

        for sensitive in (
            "input_.token_a.c_str()",
            "input_.token_b.c_str()",
            "expected_value.c_str()",
            "kCookieUrl);",
        ):
            with self.subTest(sensitive=sensitive):
                self.assertNotIn(sensitive, self.cookie)

        for token in (
            "GetDefaultStoragePartition()",
            "GetCookieManagerForBrowserProcess()",
            "CloneInterface(",
        ):
            with self.subTest(profile_cookie_boundary=token):
                self.assertIn(token, self.profile)

        close = _body_after_signature(self.cookie, "void BeginBackendClose()")
        closed = _body_after_signature(
            self.cookie, "void OnBackendClosed(bool success)"
        )
        self.assertIn("CloseCookieStoreForTesting", close)
        self.assertIn("success && probe_succeeded_ && !failed_", closed)
        self.assertIn("if (operation_succeeded)", closed)
        self.assertIn('"%sCOOKIE_BACKEND_CLOSED\\n"', closed)
        self.assertLess(
            closed.index("COOKIE_BACKEND_CLOSED"),
            closed.index("ScheduleCompletion(operation_succeeded)"),
        )
        self.assertIn("DeleteAndFlush(*expected_cookie);", self.cookie)

        for forbidden in (
            "raw_ptr<WasmProfile>",
            "GetWasmProfileCookieSmokeState",
            "WasmProfileCookieSmokeState",
            "StartWasmProfileCookieSmoke(",
            "DidWasmProfileCookieSmokeSucceed",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.cookie)

        self.assertIn(
            "class WasmProfileCookieLifetimeParticipant", self.cookie_header
        )
        self.assertIn(
            "WasmProfileOrderedDrainLifecycle::ProfileIOHold",
            self.cookie_header,
        )
        self.assertIn("bool QuarantineForFailureShutdown();", self.cookie_header)
        participant_destructor = _body_after_signature(
            self.cookie, "~WasmProfileCookieLifetimeParticipant()"
        )
        self.assertIn("QuarantineForFailureShutdown();", participant_destructor)
        quarantine = _body_after_signature(
            self.cookie,
            "bool WasmProfileCookieLifetimeParticipant::QuarantineForFailureShutdown()",
        )
        self.assertIn("state_->Cancel();", quarantine)
        self.assertIn(
            "base::NoDestructor<std::vector<std::unique_ptr<State>>>",
            quarantine,
        )
        self.assertIn(
            "quarantined_states->push_back(std::move(state_));", quarantine
        )

        disconnect = _body_after_signature(
            self.cookie, "void OnCookieManagerDisconnected()"
        )
        self.assertIn("leave the admission non-terminal", disconnect)
        self.assertNotIn("ScheduleCompletion", disconnect)
        self.assertNotIn("profile_io_hold_->Complete", disconnect)

        delivery = _body_after_signature(self.cookie, "void DeliverCompletion()")
        self.assertLess(
            delivery.index("profile_io_hold_->Complete("),
            delivery.index("completed_ = true;"),
        )
        self.assertLess(
            delivery.index("completed_ = true;"),
            delivery.index("std::move(completion).Run(succeeded);"),
        )

        self.assertIn(
            "std::unique_ptr<chrome::WasmProfileCookieLifetimeParticipant>",
            self.profile_header,
        )
        self.assertIn("bool StartCookieSmoke(", self.profile_header)
        self.assertIn("bool HasActiveCookieSmoke() const;", self.profile_header)
        self.assertIn(
            "void CancelCookieSmokeForShutdown();", self.profile_header
        )
        self.assertIn(
            "void QuarantineCookieSmokeForFailureShutdown();",
            self.profile_header,
        )
        profile_start = _body_after_signature(
            self.profile, "bool WasmProfile::StartCookieSmoke("
        )
        self.assertIn("CloneInterface(", profile_start)
        self.assertIn(
            "std::make_unique<chrome::WasmProfileCookieLifetimeParticipant>",
            profile_start,
        )
        self.assertIn("std::move(profile_io_hold)", profile_start)
        self.assertIn("cookie_lifetime_participant_->Start", profile_start)
        profile_destructor = _body_after_signature(
            self.profile, "WasmProfile::~WasmProfile()"
        )
        self.assertIn(
            "QuarantineCookieSmokeForFailureShutdown();", profile_destructor
        )

        # Normal Wasm Chrome remains deliberately volatile. This source-selected
        # artifact configures only the default in-memory partition's cookie file.
        self.assertIn(
            "IsWasmProfilePreferencesCookieSmokeEnabled()", self.content_client
        )
        self.assertIn("!in_memory || !relative_partition_path.empty()", self.content_client)
        self.assertIn("profile_path.AppendASCII(kWasmNetworkDataDirectory)", self.content_client)
        self.assertIn('FILE_PATH_LITERAL("Cookies")', self.content_client)
        self.assertIn("enable_encrypted_cookies = false;", self.content_client)
        self.assertIn("http_cache_enabled = false;", self.content_client)
        self.assertIn("restore_old_session_cookies = false;", self.content_client)
        self.assertIn("persist_session_cookies = false;", self.content_client)
        profile_policy = _body_after_signature(
            self.profile, "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()"
        )
        self.assertIn("return true;", profile_policy)

        # The close acknowledgement crosses the real cookie stack and is
        # delivered only after the SQLite database is reset on its background
        # runner. A false result is explicit for an in-memory/test stub path.
        self.assertIn("void Close(base::OnceClosure callback);", self.sqlite_backend_header)
        self.assertIn("CloseAndNotifyInBackground", self.sqlite_backend_header)
        backend_close = _body_after_signature(
            self.sqlite_backend,
            "void SQLitePersistentStoreBackendBase::Close(base::OnceClosure callback)",
        )
        self.assertIn("CloseAndNotifyInBackground", backend_close)
        backend_notify = _body_after_signature(
            self.sqlite_backend,
            "void SQLitePersistentStoreBackendBase::CloseAndNotifyInBackground(",
        )
        self.assertLess(backend_notify.index("DoCloseInBackground();"), backend_notify.index("PostClientTask"))
        self.assertIn("CloseForTesting(base::OnceClosure callback)", self.sqlite_cookie_store_header)
        self.assertIn("backend_->Close(std::move(callback));", self.sqlite_cookie_store)
        self.assertIn("ClosePersistentStoreForTesting", self.session_cookie_store_header)
        self.assertIn("persistent_store_->CloseForTesting", self.session_cookie_store)
        self.assertIn("CloseCookieStoreForTesting() => (bool success);", self.cookie_manager_mojom)
        self.assertIn(
            "[AllowedContext=sandbox.mojom.Context.kBrowser]", self.cookie_manager_mojom
        )
        self.assertIn("CloseCookieStoreForTestingCallback callback", self.cookie_manager_header)
        self.assertIn("ClosePersistentStoreForTesting", self.cookie_manager)
        self.assertIn("std::move(callback).Run(false);", self.test_cookie_manager)

        start_cookie = _body_after_signature(
            self.main_parts,
            "void WasmBrowserMainParts::StartWasmProfileCookieSmokeOrHistoryOrShutdown()",
        )
        self.assertIn("TakeWasmProfilePreferencesCookieSmokeInput", start_cookie)
        self.assertIn("TryAcquireWasmProfileStorageProfileIO", start_cookie)
        self.assertLess(
            start_cookie.index("TakeWasmProfilePreferencesCookieSmokeInput"),
            start_cookie.index("TryAcquireWasmProfileStorageProfileIO"),
        )
        self.assertIn("profile_->StartCookieSmoke(", start_cookie)
        self.assertIn("std::move(*profile_io_hold)", start_cookie)
        self.assertNotIn("std::shared_ptr<std::optional", start_cookie)
        self.assertNotIn("->Complete(", start_cookie)

        cookie_completion = _body_after_signature(
            self.main_parts,
            "void WasmBrowserMainParts::OnWasmProfileCookieSmokeComplete(",
        )
        self.assertIn(
            "NotifyWasmProfilePreferencesCookieSmokeResult(cookie_succeeded)",
            cookie_completion,
        )
        self.assertIn("if (shutdown_requested_)", cookie_completion)
        self.assertIn("MaybeStartShutdown();", cookie_completion)
        self.assertIn(
            "StartWasmProfileHistorySmokeOrShutdown();", cookie_completion
        )

        maybe_shutdown = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::MaybeStartShutdown()"
        )
        self.assertLess(
            maybe_shutdown.index("profile_->HasActiveCookieSmoke()"),
            maybe_shutdown.index("FinishShutdown();"),
        )
        self.assertIn("profile_->CancelCookieSmokeForShutdown();", maybe_shutdown)

        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        self.assertLess(
            finish.index("profile_->HasActiveCookieSmoke()"),
            finish.index("profile_->Shutdown();"),
        )
        self.assertIn("profile_->CancelCookieSmokeForShutdown();", finish)
        cookie_guard = finish.index("IsWasmProfilePreferencesCookieSmokeEnabled()")
        storage_handoff = finish.index("NotifyWasmProfileStorageProfileShutdown();")
        # The CookieManager completion above is terminal before shutdown. Its
        # result must reach the outer failure-retirement seam before the smoke
        # receipt selects a clean or failed lifecycle marker.
        self.assertLess(storage_handoff, cookie_guard)

        foundation = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        self.assertLess(
            foundation.index(
                "profile_->QuarantineCookieSmokeForFailureShutdown();"
            ),
            foundation.index("profile_->Shutdown();"),
        )

        self.assertIn(
            'test("wasm_profile_cookie_lifetime_participant_unittests")',
            self.wasm_build,
        )
        for token in (
            "std::make_unique<WasmProfileCookieLifetimeParticipant>",
            "ControllableCookieManager",
            "successful_cookie_manager.ReplyFlush();",
            "successful_cookie_manager.ReplyClose(/*success=*/true);",
            "successful_participant->IsActive()",
            "rejected_close_cookie_manager.ReplyClose(/*success=*/false);",
            "rejected_close_result.profile_io.failed_operations, 1u",
            "rejected_close_result.profile_io.abandoned_operations, 0u",
            "cancelled_participant->Cancel();",
            "cancelled_participant->QuarantineForFailureShutdown()",
            "cancelled_participant.reset();",
            "disconnected_cookie_manager.reset();",
            "Lifecycle::Status::kWaitingForRegisteredProfileIO",
            "Lifecycle::Status::kRegisteredProfileIONotClean",
            "ClaimPostContentDrain().has_value()",
            "ClaimPostContentFailureRetirement()",
            "cancelled_result.profile_io.failed_operations, 1u",
            "cancelled_result.profile_io.abandoned_operations, 0u",
        ):
            with self.subTest(runtime_token=token):
                self.assertIn(token, self.cookie_lifetime_unittest)

    def test_test_pref_is_capability_gated_before_prefservice_construction(self) -> None:
        register = _body_after_signature(
            self.smoke,
            "void RegisterWasmProfilePreferencesSmokePref(",
        )
        self.assertIn("if (!IsWasmProfilePreferencesSmokeEnabled())", register)
        self.assertIn("registry->RegisterStringPref(kSmokePref, std::string());", register)
        registered = self.profile.index(
            "chrome::RegisterWasmProfilePreferencesSmokePref(pref_registry_.get());"
        )
        pref_service = self.profile.index("PrefServiceFactory pref_service_factory;")
        self.assertLess(registered, pref_service)
        _assert_only_in_m7_blocks(
            self,
            self.profile,
            "chrome::RegisterWasmProfilePreferencesSmokePref",
        )
        self.assertIn(
            '#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck',
            self.profile,
        )

    def test_profile_branch_and_lifecycle_markers_follow_experimental_storage_boundaries(
        self,
    ) -> None:
        admitted = self.main_parts.index(
            "chrome::NotifyWasmProfileStorageProfileCreated()"
        )
        smoke_branch = self.main_parts.index(
            "if (chrome::IsWasmProfilePreferencesSmokeEnabled())"
        )
        host_input = self.main_parts.index(
            "chrome::InitializeWasmBrowserHostInput()"
        )
        browser_manager = self.main_parts.index(
            "BrowserManagerServiceFactory::GetForProfile(profile_.get())"
        )
        self.assertLess(admitted, smoke_branch)
        self.assertLess(smoke_branch, host_input)
        self.assertLess(smoke_branch, browser_manager)

        branch = self.main_parts[smoke_branch:host_input]
        self.assertIn(
            "chrome::StartWasmProfilePreferencesSmoke(profile_->GetPrefs())",
            branch,
        )
        self.assertIn(
            "chrome::IsWasmProfilePreferencesBrowserSmokeEnabled()", branch
        )
        self.assertIn("RequestShutdown();", branch)

        browser_branch_start = self.main_parts.index(
            "if (chrome::IsWasmProfilePreferencesBrowserSmokeEnabled())",
            browser_manager,
        )
        browser_branch_end = self.main_parts.index("#endif", browser_branch_start)
        browser_branch = self.main_parts[browser_branch_start:browser_branch_end]
        browser_run = browser_branch.index("chrome::RunWasmBrowserSmoke(profile_.get())")
        browser_failure = browser_branch.index(
            "chrome::NotifyWasmProfilePreferencesBrowserSmokeResult(false);"
        )
        browser_complete = browser_branch.index(
            "chrome::NotifyWasmProfilePreferencesBrowserSmokeResult(true);"
        )
        browser_bookmark_or_cookie_or_history = browser_branch.index(
            "StartWasmProfileBookmarkSmokeOrCookieOrHistoryOrShutdown();"
        )
        self.assertLess(browser_run, browser_failure)
        self.assertLess(browser_failure, browser_complete)
        self.assertLess(browser_complete, browser_bookmark_or_cookie_or_history)

        finish = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        fence_begin = finish.index("profile_->BeginPrefsShutdownFence")
        fence_marker = finish.index(
            "chrome::NotifyWasmProfilePreferencesSmokeFenceResult(success);"
        )
        fence_reentry = finish.index("main_parts->FinishShutdown();")
        profile_reset = finish.index("profile_.reset();")
        storage_notify = finish.index(
            "chrome::NotifyWasmProfileStorageProfileShutdown();"
        )
        lifecycle_marker = finish.index(
            "chrome::NotifyWasmProfilePreferencesSmokeStorageLifecycle(",
            storage_notify,
        )
        self.assertLess(fence_begin, fence_marker)
        self.assertLess(fence_marker, fence_reentry)
        self.assertLess(fence_reentry, profile_reset)
        self.assertLess(profile_reset, storage_notify)
        self.assertLess(storage_notify, lifecycle_marker)

        content_main = self.chrome_main.index("content::ContentMain(std::move(params))")
        drain = self.chrome_main.index(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()"
        )
        drain_marker = self.chrome_main.index(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain("
        )
        process_exit = self.chrome_main.index(
            "chromium_wasm_report_process_exit(exit_code)"
        )
        self.assertLess(content_main, drain)
        self.assertLess(drain, drain_marker)
        self.assertLess(drain_marker, process_exit)
        self.assertIn(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(\n"
            "        drain_result.Succeeded());",
            self.chrome_main,
        )

    def test_content_normal_exit_is_not_a_content_failure(self) -> None:
        normal_result = _body_after_signature(
            self.chrome_main, "bool IsNormalChromeMainResult(int result)"
        )
        self.assertIn(
            "return result == content::RESULT_CODE_NORMAL_EXIT ||\n"
            "         IsNormalResultCode(static_cast<ResultCode>(result));",
            normal_result,
        )

        content_failure = _body_after_signature(
            self.chrome_main,
            "if (preferences_smoke_enabled &&\n"
            "      !IsNormalChromeMainResult(result))",
        )
        self.assertIn(
            "if (preferences_smoke_enabled &&\n"
            "      !IsNormalChromeMainResult(result))",
            self.chrome_main,
        )
        self.assertIn(
            "WasmProfilePreferencesSmokeFailureStage::kContent", content_failure
        )

        # The database acceptance target shares ChromeMain and has independent
        # normal-result checks. Verify the three decisions that affect the
        # Preferences target instead of constraining a file-wide occurrence
        # count owned by unrelated acceptance helpers.
        shared_drain_failure = _body_after_signature(
            self.chrome_main, "if (!drain_result.Succeeded())"
        )
        shared_drain_normal_result = _body_after_signature(
            shared_drain_failure, "if (IsNormalChromeMainResult(result))"
        )
        self.assertIn(
            "result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;",
            shared_drain_normal_result,
        )

        preferences_missing_drain = _body_after_signature(
            self.chrome_main, "} else if (preferences_smoke_enabled)"
        )
        self.assertIn(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain(false);",
            preferences_missing_drain,
        )
        preferences_missing_drain_normal_result = _body_after_signature(
            preferences_missing_drain, "if (IsNormalChromeMainResult(result))"
        )
        self.assertIn(
            "result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;",
            preferences_missing_drain_normal_result,
        )

        # Keep the final process-exit bridge responsible for preserving
        # non-normal ContentMain values after either Preferences drain path.
        final_exit = self.chrome_main[self.chrome_main.index("const int exit_code =") :]
        self.assertIn(
            "const int exit_code = IsNormalChromeMainResult(result)\n"
            "                            ? content::RESULT_CODE_NORMAL_EXIT\n"
            "                            : result;",
            final_exit,
        )

    def test_dedicated_gn_configuration_is_the_only_capability_grant(self) -> None:
        for token in (
            "enable_chromium_wasm_m7_profile_preferences_test = false",
            "is_wasm && enable_chromium_wasm_chrome",
            '"wasm-chrome-m7-profile-preferences"',
            "M7 Preferences acceptance must use "
            "out/wasm-chrome-m7-profile-preferences",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.m7_gni)

        for build_file in (self.chrome_build, self.wasm_build):
            self.assertIn(
                'import("//chrome/browser/wasm/wasm_profile_preferences_smoke.gni")',
                build_file,
            )

        target = _body_after_signature(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        direct_deps = _bracket_body_after(target, "deps = [")
        self.assertNotIn("wasm_profile_preferences_smoke", direct_deps)
        self.assertNotIn('executable("chrome_wasm_m7_profile_preferences_test")', self.chrome_build)
        for token in (
            "if (enable_chromium_wasm_m7_profile_preferences_test)",
            'output_name = "chrome_wasm_m7_profile_preferences_test"',
            'defines = [ "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST=1" ]',
            'deps += [ "//chrome/browser/wasm:wasm_profile_preferences_smoke" ]',
        ):
            with self.subTest(token=token):
                self.assertIn(token, target)
        for forbidden in (
            "wasm_m6_test_trust",
            "wasm_m6_controlled_https_test_mode",
            "CHROME_WASM_M6_CONTROLLED_HTTPS_TEST",
            "generate_wasm_m6_test_root_cert",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        profile_layout_config = _body_after_signature(
            self.wasm_build,
            'config("wasm_profile_m7_preferences_smoke_config")',
        )
        self.assertIn(
            'defines = [ "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST=1" ]',
            profile_layout_config,
        )

        for source_set in ("wasm_profile", "wasm_browser_main_parts"):
            target = _body_after_signature(
                self.wasm_build, f'source_set("{source_set}")'
            )
            direct_deps = _bracket_body_after(target, "deps = [")
            self.assertNotIn("wasm_profile_preferences_smoke", direct_deps)
            self.assertIn(
                "if (enable_chromium_wasm_m7_profile_preferences_test)", target
            )
            if source_set == "wasm_profile":
                self.assertIn(
                    'public_configs = [ ":wasm_profile_m7_preferences_smoke_config" ]',
                    target,
                )
                self.assertIn('":wasm_profile_bookmark_smoke",', target)
                self.assertIn('":wasm_profile_preferences_smoke",', target)
                self.assertIn('":wasm_profile_history_smoke",', target)
            else:
                self.assertIn(
                    'defines = [ "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST=1" ]',
                    target,
                )
                self.assertIn('":wasm_profile_bookmark_smoke",', target)
                self.assertIn('":wasm_profile_preferences_smoke",', target)
                preferences_gate = _body_after_signature(
                    target,
                    "if (enable_chromium_wasm_m7_profile_preferences_test)",
                )
                self.assertNotIn(
                    '":wasm_profile_history_smoke",', preferences_gate
                )

        helper_gate = (
            "if (enable_chromium_wasm_m7_profile_preferences_test ||\n"
            "    enable_chromium_wasm_m7_profile_cookie_local_storage_test ||\n"
            "    enable_chromium_wasm_m7_profile_cookie_history_local_storage_test ||\n"
            "    enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test ||\n"
            "    enable_chromium_wasm_m7_profile_bookmark_cookie_history_database_local_storage_test) {\n"
            '  source_set("wasm_profile_preferences_smoke")'
        )
        helper_start = self.wasm_build.index(helper_gate)
        self.assertGreater(helper_start, 0)
        self.assertIn("//crypto", self.wasm_build[helper_start:])

    def test_primary_configuration_has_no_helper_or_m7_switch_handling(self) -> None:
        # The helper is physically absent from the default GN graph. Shared
        # source files retain the M7 code only inside target-specific macro
        # blocks, whose includes are narrowly nogncheck-marked because GN does
        # not evaluate target-specific preprocessing during include checks.
        for text in (self.profile, self.main_parts, self.chrome_main):
            self.assertIn(
                '#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck',
                text,
            )

        for text, token in (
            (
                self.profile,
                "chrome::RegisterWasmProfilePreferencesSmokePref",
            ),
            (self.main_parts, "chrome::IsWasmProfilePreferencesSmokeEnabled"),
            (self.main_parts, "chrome::StartWasmProfilePreferencesSmoke"),
            (self.main_parts, "chrome::NotifyWasmProfilePreferencesSmoke"),
            (self.chrome_main, "chrome::HasWasmProfilePreferencesSmokeArguments"),
            (self.chrome_main, "chrome::EnableWasmProfilePreferencesSmokeTestMode"),
            (self.chrome_main, "chrome::ReportWasmProfilePreferencesSmokeFailure"),
            (self.chrome_main, "chrome::NotifyWasmProfilePreferencesSmoke"),
        ):
            _assert_only_in_m7_blocks(self, text, token)

        self.assertNotIn(
            "WasmProfilePreferencesSmokeFailureStage::kCapability",
            self.chrome_main,
        )
        self.assertEqual(
            self.chrome_main.count(_NORMAL_CHROME_MAIN_M7_EXCLUSION_GUARD),
            3,
        )


if __name__ == "__main__":
    unittest.main()

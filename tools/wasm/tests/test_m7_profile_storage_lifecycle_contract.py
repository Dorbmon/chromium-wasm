#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the experimental M7 OPFS profile-storage lifecycle."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _matching_closing_brace(
    text: str, opening_brace: int, description: str
) -> int:
    """Returns the matching C++ closing brace for a known opening brace."""

    if opening_brace < 0:
        raise AssertionError(f"missing opening brace for {description}")

    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError(f"missing closing brace for {description}")


_M7_STORAGE_MACROS = (
    "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST",
    "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST",
)
_M7_STORAGE_GN_FLAGS = (
    "enable_chromium_wasm_m7_profile_preferences_test",
    "enable_chromium_wasm_m7_profile_database_test",
)


def _is_in_m7_storage_macro_block(text: str, position: int) -> bool:
    """Returns whether |position| is under either M7 storage capability."""

    active_stack: list[bool] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if offset <= position < offset + len(line):
            return any(active_stack)

        directive = line.lstrip()
        is_storage_directive = any(
            macro in directive for macro in _M7_STORAGE_MACROS
        )
        if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
            active_stack.append(is_storage_directive)
        elif re.match(r"#\s*elif\b", directive):
            if active_stack:
                active_stack[-1] = is_storage_directive
        elif re.match(r"#\s*else\b", directive):
            if active_stack:
                active_stack[-1] = False
        elif re.match(r"#\s*endif\b", directive):
            if active_stack:
                active_stack.pop()
        offset += len(line)
    return False


def _assert_only_in_m7_storage_blocks(
    testcase: unittest.TestCase, text: str, token: str
) -> None:
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(
                _is_in_m7_storage_macro_block(text, position),
                f"{token} is not M7-storage-config-gated",
            )


def _body_after_signature(text: str, signature: str) -> str:
    """Returns one balanced body without relying on line layout."""

    start = text.index(signature)
    opening_brace = text.index("{", start)
    return text[
        opening_brace + 1 : _matching_closing_brace(
            text, opening_brace, signature
        )
    ]


def _m7_storage_gn_blocks(text: str) -> list[tuple[int, int]]:
    """Returns GN ``if`` bodies that explicitly grant an M7 capability."""

    blocks = []
    for match in re.finditer(r"if\s*\((.*?)\)\s*\{", text, re.DOTALL):
        if not any(flag in match.group(1) for flag in _M7_STORAGE_GN_FLAGS):
            continue
        opening_brace = match.end() - 1
        closing_brace = _matching_closing_brace(
            text, opening_brace, "M7 storage GN capability"
        )
        blocks.append((opening_brace, closing_brace))
    return blocks


def _assert_only_in_m7_storage_gn_blocks(
    testcase: unittest.TestCase, text: str, token: str
) -> None:
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    blocks = _m7_storage_gn_blocks(text)
    testcase.assertTrue(blocks, "missing M7 storage GN capability block")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(
                any(start < position < end for start, end in blocks),
                f"{token} is not M7-storage-config-gated",
            )


class M7ProfileStorageLifecycleContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.storage_header = source(
            "chrome/browser/wasm/wasm_profile_storage.h"
        )
        self.storage_result_header = source(
            "chrome/browser/wasm/wasm_profile_storage_drain_result.h"
        )
        self.storage = source("chrome/browser/wasm/wasm_profile_storage.cc")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_browser_build = source("chrome/browser/wasm/BUILD.gn")

    def test_runtime_storage_consumers_are_m7_config_gated(self) -> None:
        for text, tokens in (
            (
                self.chrome_main,
                (
                    '#include "chrome/browser/wasm/wasm_profile_storage.h"',
                    "chrome::InitializeWasmProfileStorage()",
                    "chrome::InitializeWasmProfilePreferencesStorage()",
                    "chrome::NeedsWasmProfileStorageBackendDrain()",
                    "chrome::DrainAndReleaseWasmProfileStorageBackend()",
                ),
            ),
            (
                self.main_parts,
                (
                    '#include "chrome/browser/wasm/wasm_profile_storage.h"',
                    "chrome::IsWasmProfileStorageMounted()",
                    "chrome::NotifyWasmProfileStorageProfileCreated()",
                    "chrome::NotifyWasmProfileStorageProfileShutdown()",
                    "chrome::TryAcquireWasmProfileStorageProfileIO()",
                ),
            ),
        ):
            for token in tokens:
                _assert_only_in_m7_storage_blocks(self, text, token)

    def test_preferences_storage_keeps_profile_parent_volatile_and_scopes_lease(
        self,
    ) -> None:
        for token in (
            '#include <emscripten/threading.h>',
            '#include <emscripten/wasmfs.h>',
            '#include <emscripten/wasmfs_opfs_profile_drain.h>',
            'constexpr char kWasmFsRootPath[] = "/";',
            'constexpr char kProfileRootPath[] = "/profile";',
            'constexpr char kProfileDefaultPath[] = "/profile/Default";',
            'constexpr char kProfileLeaseName[] = "chromium-wasm-profile-v1";',
            "wasmfs_create_opfs_backend_with_profile_lease(kProfileLeaseName)",
            "bool InitializeWasmProfilePreferencesStorage()",
            "ProfileStorageMount::kDefaultProfile",
            "emscripten_is_main_browser_thread()",
            "emscripten_is_main_runtime_thread()",
            "initialization_error_ = -EAGAIN;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)

        self.assertNotIn("wasmfs_create_opfs_backend()", self.storage)
        self.assertNotIn("wasmfs_unmount(", self.storage)
        self.assertNotIn("wasmfs_terminal_drain(", self.storage)

        prepare_parent = _body_after_signature(
            self.storage,
            "static int PrepareVolatileProfileRoot(backend_t* profile_root_backend)",
        )
        for token in (
            "wasmfs_get_backend_by_path(kWasmFsRootPath)",
            "wasmfs_create_directory(\n        kProfileRootPath, /*mode=*/0700, wasmfs_root_backend)",
            "create_profile_root_result != -EEXIST",
            "wasmfs_get_backend_by_path(kProfileRootPath)",
            "parent_backend != wasmfs_root_backend",
            "it is never a fallback\n    // to an unknown existing mount.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, prepare_parent)

        mount_identity = _body_after_signature(
            self.storage,
            "static bool HasExpectedDefaultProfileMountIdentity(",
        )
        for token in (
            "wasmfs_get_backend_by_path(kProfileDefaultPath)",
            "parent_backend == profile_root_backend",
            "parent_backend != leased_backend",
            "default_backend == leased_backend",
        ):
            with self.subTest(token=token):
                self.assertIn(token, mount_identity)

        self.assertIn(
            "#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)\n"
            "// Mounts the Preferences acceptance probe's leased OPFS backend only at",
            self.storage_header,
        )
        self.assertIn(
            "bool InitializeWasmProfilePreferencesStorage();", self.storage_header
        )

        self.assertIn(
            "#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)\n"
            "    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {\n"
            "#else\n"
            "    } else if (!chrome::InitializeWasmProfileStorage()) {\n"
            "#endif",
            self.chrome_main,
        )

    def test_mount_failure_defers_an_already_acquired_lease_until_post_scope(
        self,
    ) -> None:
        mount_failure = self.storage.index("if (mount_result != 0)")
        backend_identity_failure = self.storage.index(
            "if (!has_expected_mount_identity)"
        )
        initialize_start = self.storage.index(
            "  bool Initialize(ProfileStorageMount mount) {"
        )
        initialize = self.storage[
            initialize_start : self.storage.index("  bool IsMounted() {")
        ]
        self.assertIn("backend_ = backend;", initialize)
        self.assertNotIn("DrainBackend(backend);", initialize)
        self.assertLess(
            initialize.index("backend_ = backend;"),
            mount_failure - initialize_start,
        )
        self.assertLess(
            initialize.index("backend_ = backend;"),
            backend_identity_failure - initialize_start,
        )
        self.assertIn("bool NeedsWasmProfileStorageBackendDrain()", self.storage)
        self.assertIn("backend_ != nullptr", self.storage)
        self.assertIn("backend_drain_attempted_", self.storage)

    def test_scoped_backend_drain_requires_complete_cleanup_and_reports_every_counter(
        self,
    ) -> None:
        for token in (
            "WasmProfileStorageDrainResult DrainAndReleaseWasmProfileStorageBackend()",
            "wasmfs_opfs_profile_drain_result wasmfs_result{};",
            "wasmfs_drain_opfs_profile_backend(backend, &wasmfs_result)",
            "result.detached_descriptors = wasmfs_result.detached_descriptors;",
            "result.data_file_states = wasmfs_result.data_file_states;",
            "result.libc_flush_failed = wasmfs_result.libc_flush_failed;",
            "result.data_flush_failures = wasmfs_result.data_flush_failures;",
            "result.data_close_failures = wasmfs_result.data_close_failures;",
            "result.prior_close_failures = wasmfs_result.prior_close_failures;",
            "result.lease_release_failures = wasmfs_result.lease_release_failures;",
            "result.backend_retire_failures = wasmfs_result.backend_retire_failures;",
            "result.backend_sealed = wasmfs_result.backend_sealed != 0;",
            "result.lease_released = wasmfs_result.lease_released != 0;",
            "result.backend_retired = wasmfs_result.backend_retired != 0;",
            "result.error = -EIO;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)

        self.assertNotIn("wasmfs_terminal_drain(", self.storage)
        self.assertIn(
            "uint32_t backend_retire_failures = 0;", self.storage_result_header
        )
        self.assertIn("bool backend_retired = false;", self.storage_result_header)
        for token in (
            "bool Succeeded() const {",
            "return error == 0 && libc_flush_failed == 0 &&",
            "backend_retire_failures == 0",
            "backend_sealed && lease_released && backend_retired;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage_result_header)
        self.assertNotIn(
            "bool WasmProfileStorageDrainResult::Succeeded() const", self.storage
        )
        self.assertIn(
            '#include "chrome/browser/wasm/wasm_profile_storage_drain_result.h"',
            self.storage_header,
        )
        for forbidden in (
            "wasmfs_",
            "<emscripten/",
            '"/profile"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.storage_result_header)
        self.assertLess(
            self.storage_result_header.index(
                "uint32_t lease_release_failures = 0;"
            ),
            self.storage_result_header.index(
                "uint32_t backend_retire_failures = 0;"
            ),
        )
        self.assertLess(
            self.storage_result_header.index("bool lease_released = false;"),
            self.storage_result_header.index("bool backend_retired = false;"),
        )
        self.assertIn("result.backend_retire_failures != 0", self.storage)
        self.assertIn("!result.backend_retired", self.storage)
        self.assertIn("result.error = -EBUSY;", self.storage)
        for token in (
            "std::make_unique<WasmProfileOrderedDrainLifecycle>()",
            "TryAcquireProfileIO()",
            "profile_io_lifecycle_->TryAcquireProfileIO()",
            "profile_io_lifecycle_->BeginQuiesce()",
            "profile_io_observation_->ClaimPostContentDrain()",
            "profile_io_drain_permit->GetProfileIOQuiesceResult()",
            "profile_io_quiesce_result->admitted_operations == 0",
            "!profile_io_quiesce_result->Succeeded()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)
        self.assertIn(
            "WasmProfileOrderedDrainLifecycle::Status::\n"
            "                          kWaitingForRegisteredProfileIO",
            self.storage,
        )
        self.assertIn(
            "if (emscripten_is_main_browser_thread() ||\n"
            "          emscripten_is_main_runtime_thread()) {\n"
            "        WasmProfileStorageDrainResult result;\n"
            "        result.error = -EAGAIN;",
            self.storage,
        )
        self.assertLess(
            self.storage.index("backend_drain_attempted_ = true;"),
            self.storage.index(
                "WasmProfileStorageDrainResult result = DrainBackend(backend);"
            ),
        )
        self.assertIn(
            "backend_drain_result_ = result;\n"
            "    state_ = backend_drain_result_.Succeeded() ? State::kDrained\n"
            "                                               : State::kDrainFailed;\n"
            "    return backend_drain_result_;",
            self.storage,
        )

    def test_known_test_profile_operations_must_quiesce_before_backend_drain(
        self,
    ) -> None:
        storage_created = _body_after_signature(
            self.storage, "bool NotifyProfileCreated()"
        )
        self.assertLess(
            storage_created.index(
                "std::make_unique<WasmProfileOrderedDrainLifecycle>()"
            ),
            storage_created.index("profile_created_ = true;"),
        )

        storage_shutdown = _body_after_signature(
            self.storage, "bool NotifyProfileShutdown()"
        )
        self.assertIn("if (profile_created_)", storage_shutdown)
        self.assertIn("profile_io_lifecycle_->BeginQuiesce()", storage_shutdown)
        self.assertLess(
            storage_shutdown.index("profile_io_lifecycle_->BeginQuiesce()"),
            storage_shutdown.index("profile_shutdown_ = true;"),
        )

        storage_drain = _body_after_signature(
            self.storage, "WasmProfileStorageDrainResult DrainAndReleaseBackend()"
        )
        self.assertLess(
            storage_drain.index("profile_io_observation_->ClaimPostContentDrain()"),
            storage_drain.index("backend_drain_attempted_ = true;"),
        )
        self.assertLess(
            storage_drain.index("emscripten_is_main_browser_thread()"),
            storage_drain.index("profile_io_observation_->ClaimPostContentDrain()"),
        )
        self.assertLess(
            storage_drain.index("profile_io_drain_permit"),
            storage_drain.index("WasmProfileStorageDrainResult result = DrainBackend(backend);"),
        )

        profile = source("chrome/browser/wasm/wasm_profile.cc")
        prefs_fence = _body_after_signature(
            profile, "bool WasmProfile::StartPrefsShutdownFence("
        )
        for token in (
            "chrome::TryAcquireWasmProfileStorageProfileIO()",
            "CompletePersistentPrefsWithProfileStorageHold",
            "std::move(*profile_io_hold)",
            "base::BindPostTask",
        ):
            with self.subTest(token=token):
                self.assertIn(token, prefs_fence)
        self.assertLess(
            prefs_fence.index("chrome::TryAcquireWasmProfileStorageProfileIO()"),
            prefs_fence.index("prefs_->CommitPendingWrite("),
        )

        database_admission = self.main_parts.index(
            "auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();"
        )
        database_start = self.main_parts.index(
            "chrome::StartWasmProfileDatabaseSmoke("
        )
        database_complete = self.main_parts.index(
            "profile_io_hold->Complete("
        )
        database_shutdown = self.main_parts.index("main_parts->RequestShutdown();")
        self.assertLess(database_admission, database_start)
        self.assertLess(database_start, database_complete)
        self.assertLess(database_complete, database_shutdown)

    def test_experimental_chrome_main_orders_mount_before_content_and_drain_after_teardown(
        self,
    ) -> None:
        initialize = self.chrome_main.index(
            "chrome::InitializeWasmProfilePreferencesStorage()"
        )
        content_main = self.chrome_main.index("content::ContentMain(std::move(params))")
        needs_drain = self.chrome_main.index(
            "chrome::NeedsWasmProfileStorageBackendDrain()"
        )
        drain = self.chrome_main.index(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()"
        )

        self.assertLess(initialize, content_main)
        self.assertIn("WasmChromeMainDelegate chrome_main_delegate;", self.chrome_main)
        self.assertIn(
            "content::ContentMainParams params(&chrome_main_delegate);",
            self.chrome_main,
        )
        self.assertLess(content_main, needs_drain)
        self.assertLess(needs_drain, drain)
        drain_marker = self.chrome_main.index(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain("
        )
        process_exit = self.chrome_main.index(
            "chromium_wasm_report_process_exit(exit_code)"
        )
        self.assertLess(drain, drain_marker)
        self.assertLess(drain_marker, process_exit)
        for token in (
            "CHROME_RESULT_CODE_UNSUPPORTED_PARAM",
            "drain_result.Succeeded()",
            "chromium_wasm_report_process_exit(exit_code)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.chrome_main)

        # The scoped operation preserves global stderr and the normal exit
        # tail. Failed-mount lease cleanup still runs after the delegate scope.
        self.assertNotIn("wasmfs_terminal_drain(", self.chrome_main)
        self.assertIn("#include <stdio.h>", self.chrome_main)
        self.assertIn("host rejected process-exit report", self.chrome_main)
        self.assertIn("fputs(", self.chrome_main)
        self.assertIn("return exit_code == 0 ? 1 : exit_code;", self.chrome_main)
        self.assertIn(
            "Its scoped cleanup\n      // runs after this delegate scope",
            self.chrome_main,
        )
        self.assertNotIn(
            "A failed scoped drain retains its lease.", self.chrome_main
        )
        self.assertIn(
            "Before acknowledged Web Locks release, a drain failure has no safe\n"
            "      // handoff. A post-release worker-retirement failure has already released\n"
            "      // its lease and cannot be retried.",
            self.chrome_main,
        )
        self.assertLess(
            self.chrome_main.index("chromium_wasm_report_process_exit(exit_code)"),
            self.chrome_main.index("fputs(\"CHROMIUM_WASM: host rejected"),
        )

    def test_dedicated_artifacts_reject_unowned_profile_startup_before_mount(
        self,
    ) -> None:
        preferences_capability = _body_after_signature(
            self.chrome_main,
            "if (!preferences_smoke_requested || !preferences_smoke_enabled)",
        )
        database_capability = _body_after_signature(
            self.chrome_main,
            "if (!database_smoke_requested || !database_smoke_enabled)",
        )
        for capability in (preferences_capability, database_capability):
            self.assertIn(
                "result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;", capability
            )

        preferences_capability_start = self.chrome_main.index(
            "if (!preferences_smoke_requested || !preferences_smoke_enabled)"
        )
        database_capability_start = self.chrome_main.index(
            "if (!database_smoke_requested || !database_smoke_enabled)"
        )
        preferences_mount = self.chrome_main.index(
            "chrome::InitializeWasmProfilePreferencesStorage()"
        )
        database_mount = self.chrome_main.index(
            "chrome::InitializeWasmProfileStorage()"
        )
        self.assertLess(preferences_capability_start, preferences_mount)
        self.assertLess(database_capability_start, database_mount)

    def test_experimental_main_parts_admits_and_completes_profile_lifecycle_before_drain(
        self,
    ) -> None:
        mounted = self.main_parts.index("chrome::IsWasmProfileStorageMounted()")
        user_data = self.main_parts.index(
            "base::PathService::Get(chrome::DIR_USER_DATA, &user_data_directory)"
        )
        profile = self.main_parts.index(
            "profile_ = std::make_unique<WasmProfile>(profile_path);"
        )
        admitted = self.main_parts.index(
            "chrome::NotifyWasmProfileStorageProfileCreated()"
        )
        shutdown = self.main_parts.index("profile_->Shutdown();")
        complete = self.main_parts.index(
            "chrome::NotifyWasmProfileStorageProfileShutdown()"
        )

        self.assertLess(mounted, user_data)
        self.assertLess(profile, admitted)
        self.assertLess(shutdown, complete)
        self.assertNotIn("wasmfs_terminal_drain", self.main_parts)
        self.assertNotIn("wasmfs_unmount", self.main_parts)

    def test_only_experimental_m7_selects_wasmfs_and_storage(self) -> None:
        chrome_wasm = _body_after_signature(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        chrome_https_test = _body_after_signature(
            self.chrome_build, 'executable("chrome_wasm_m6_https_test")'
        )
        main_parts = _body_after_signature(
            self.wasm_browser_build, 'source_set("wasm_browser_main_parts")'
        )

        for token in (
            'config("chrome_wasm_profile_storage")',
            'ldflags = [ "-sWASMFS=1" ]',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.chrome_build)

        for token in (
            '":chrome_wasm_profile_storage"',
            '"//chrome/browser/wasm:wasm_profile_storage"',
        ):
            with self.subTest(token=token):
                _assert_only_in_m7_storage_gn_blocks(self, chrome_wasm, token)
        _assert_only_in_m7_storage_gn_blocks(
            self, main_parts, '":wasm_profile_storage"'
        )
        for token in (
            '":chrome_wasm_profile_storage"',
            '"//chrome/browser/wasm:wasm_profile_storage"',
            '":wasm_profile_storage"',
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, chrome_https_test)

        for token in (
            'source_set("wasm_profile_storage")',
            'public = [ "wasm_profile_storage.h" ]',
            'sources = [ "wasm_profile_storage.cc" ]',
            '":wasm_profile_ordered_drain_lifecycle",',
            '":wasm_profile_storage_drain_result",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.wasm_browser_build)

        storage_source_set = _body_after_signature(
            self.wasm_browser_build, 'source_set("wasm_profile_storage")'
        )
        self.assertIn(
            "if (enable_chromium_wasm_m7_profile_preferences_test)",
            storage_source_set,
        )
        self.assertIn(
            'defines = [ "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST=1" ]',
            storage_source_set,
        )

        result_source_set_start = self.wasm_browser_build.index(
            'source_set("wasm_profile_storage_drain_result")'
        )
        result_source_set_opening_brace = self.wasm_browser_build.index(
            "{", result_source_set_start
        )
        result_source_set_end = _matching_closing_brace(
            self.wasm_browser_build,
            result_source_set_opening_brace,
            "wasm_profile_storage_drain_result",
        )
        result_source_set = self.wasm_browser_build[
            result_source_set_opening_brace + 1 : result_source_set_end
        ]
        self.assertIn(
            'public = [ "wasm_profile_storage_drain_result.h" ]',
            result_source_set,
        )
        for forbidden in ("wasmfs", "emscripten", "deps"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, result_source_set)

        result_test_start = self.wasm_browser_build.index(
            'test("wasm_profile_storage_drain_result_unittests")'
        )
        result_test_opening_brace = self.wasm_browser_build.index(
            "{", result_test_start
        )
        result_test_end = _matching_closing_brace(
            self.wasm_browser_build,
            result_test_opening_brace,
            "wasm_profile_storage_drain_result_unittests",
        )
        result_test = self.wasm_browser_build[
            result_test_opening_brace + 1 : result_test_end
        ]
        for token in (
            'sources = [ "wasm_profile_storage_drain_result_unittest.cc" ]',
            '":wasm_profile_storage_drain_result",',
            '"//base/test:run_all_unittests",',
            '"//testing/gtest",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, result_test)
        for forbidden in (
            '":wasm_profile_storage",',
            "wasmfs",
            "emscripten",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, result_test)


if __name__ == "__main__":
    unittest.main()

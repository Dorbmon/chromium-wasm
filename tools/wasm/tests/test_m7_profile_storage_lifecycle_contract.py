#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for Chrome's leased-OPFS profile storage lifecycle."""

from __future__ import annotations

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


class M7ProfileStorageLifecycleContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.storage_header = source(
            "chrome/browser/wasm/wasm_profile_storage.h"
        )
        self.storage = source("chrome/browser/wasm/wasm_profile_storage.cc")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_browser_build = source("chrome/browser/wasm/BUILD.gn")

    def test_storage_mounts_only_the_leased_backend_at_the_profile_root(self) -> None:
        for token in (
            '#include <emscripten/threading.h>',
            '#include <emscripten/wasmfs.h>',
            '#include <emscripten/wasmfs_opfs_profile_drain.h>',
            'constexpr char kProfileMountPath[] = "/profile";',
            'constexpr char kProfileLeaseName[] = "chromium-wasm-profile-v1";',
            "wasmfs_create_opfs_backend_with_profile_lease(kProfileLeaseName)",
            "wasmfs_create_directory(kProfileMountPath, /*mode=*/0700, backend)",
            "wasmfs_get_backend_by_path(kProfileMountPath) != backend",
            "emscripten_is_main_browser_thread()",
            "emscripten_is_main_runtime_thread()",
            "initialization_error_ = -EAGAIN;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)

        self.assertNotIn("wasmfs_create_opfs_backend()", self.storage)
        self.assertNotIn("wasmfs_unmount(", self.storage)
        self.assertNotIn("wasmfs_terminal_drain(", self.storage)

    def test_mount_failure_defers_an_already_acquired_lease_until_post_scope(
        self,
    ) -> None:
        mount_failure = self.storage.index("if (mount_result != 0)")
        backend_identity_failure = self.storage.index(
            "wasmfs_get_backend_by_path(kProfileMountPath) != backend"
        )
        initialize = self.storage[
            self.storage.index("  bool Initialize() {") : self.storage.index(
                "  bool IsMounted() {"
            )
        ]
        self.assertIn("backend_ = backend;", initialize)
        self.assertNotIn("DrainBackend(backend);", initialize)
        self.assertLess(
            initialize.index("backend_ = backend;"),
            mount_failure - self.storage.index("  bool Initialize() {"),
        )
        self.assertLess(
            initialize.index("backend_ = backend;"),
            backend_identity_failure - self.storage.index("  bool Initialize() {"),
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
            "return error == 0 && libc_flush_failed == 0 &&",
            "backend_retire_failures == 0",
            "backend_sealed && lease_released && backend_retired;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)

        self.assertNotIn("wasmfs_terminal_drain(", self.storage)
        self.assertIn("uint32_t backend_retire_failures = 0;", self.storage_header)
        self.assertIn("bool backend_retired = false;", self.storage_header)
        self.assertLess(
            self.storage_header.index("uint32_t lease_release_failures = 0;"),
            self.storage_header.index("uint32_t backend_retire_failures = 0;"),
        )
        self.assertLess(
            self.storage_header.index("bool lease_released = false;"),
            self.storage_header.index("bool backend_retired = false;"),
        )
        self.assertIn("result.backend_retire_failures != 0", self.storage)
        self.assertIn("!result.backend_retired", self.storage)
        self.assertIn("result.error = -EBUSY;", self.storage)
        self.assertIn("profile_created_ && !profile_shutdown_", self.storage)
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

    def test_chrome_main_orders_mount_before_content_and_drain_after_teardown(
        self,
    ) -> None:
        initialize = self.chrome_main.index(
            "chrome::InitializeWasmProfileStorage()"
        )
        content_main = self.chrome_main.index("content::ContentMain(std::move(params))")
        delegate_scope_start = self.chrome_main.index(
            "{\n    WasmChromeMainDelegate chrome_main_delegate;"
        )
        delegate_scope_end = _matching_closing_brace(
            self.chrome_main,
            delegate_scope_start,
            "ChromeMain ContentMain delegate scope",
        )
        delegate_scope = self.chrome_main[
            delegate_scope_start + 1 : delegate_scope_end
        ]
        needs_drain = self.chrome_main.index(
            "chrome::NeedsWasmProfileStorageBackendDrain()"
        )
        drain = self.chrome_main.index(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()"
        )

        self.assertLess(initialize, content_main)
        self.assertIn(
            "WasmChromeMainDelegate chrome_main_delegate;", delegate_scope
        )
        self.assertIn(
            "content::ContentMainParams params(&chrome_main_delegate);",
            delegate_scope,
        )
        self.assertIn("content::ContentMain(std::move(params))", delegate_scope)
        self.assertLess(content_main, delegate_scope_end)
        self.assertNotIn(
            "chrome::NeedsWasmProfileStorageBackendDrain()", delegate_scope
        )
        self.assertNotIn(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()", delegate_scope
        )
        self.assertLess(delegate_scope_end, needs_drain)
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

    def test_main_parts_admits_and_completes_profile_lifecycle_before_drain(
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

    def test_chrome_build_owns_wasmfs_and_storage_source_selection(self) -> None:
        for token in (
            'config("chrome_wasm_profile_storage")',
            'ldflags = [ "-sWASMFS=1" ]',
            '":chrome_wasm_profile_storage",',
            '"//chrome/browser/wasm:wasm_profile_storage",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.chrome_build)

        for token in (
            'source_set("wasm_profile_storage")',
            'public = [ "wasm_profile_storage.h" ]',
            'sources = [ "wasm_profile_storage.cc" ]',
            '":wasm_profile_storage",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.wasm_browser_build)


if __name__ == "__main__":
    unittest.main()

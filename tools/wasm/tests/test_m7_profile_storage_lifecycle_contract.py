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
    "CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST",
    "CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST",
    "CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE",
    "CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE",
    "CHROME_WASM_M7_LOCAL_STORAGE_CLOSE_FENCE_TEST",
)
_M7_STORAGE_GN_FLAGS = (
    "enable_chromium_wasm_m7_profile_preferences_test",
    "enable_chromium_wasm_m7_profile_database_test",
    "enable_chromium_wasm_m7_default_partition_local_storage_test",
    "enable_chromium_wasm_m7_profile_cookie_local_storage_test",
    "enable_chromium_wasm_m7_profile_cookie_history_local_storage_test",
    "enable_chromium_wasm_m7_profile_bookmark_cookie_history_local_storage_test",
    "enable_chromium_wasm_m7_profile_bookmark_cookie_history_database_"
    "local_storage_test",
    "enable_chromium_wasm_m7_profile_indexed_db_test",
    "enable_chromium_wasm_m7_persistent_default_partition_policy_probe",
    "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe",
)


def _is_in_m7_storage_macro_block(text: str, position: int) -> bool:
    """Returns whether |position| is under an M7 storage capability."""

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


def _positive_macro_branch_blocks(text: str, macro: str) -> list[tuple[int, int]]:
    """Returns the true branches of exact ``#if defined(MACRO)`` guards."""

    blocks = []
    frames: list[dict[str, int | bool]] = []
    directive_re = re.compile(r"#\s*(if|ifdef|ifndef|elif|else|endif)\b")
    exact_positive_re = re.compile(
        rf"#\s*if\s+defined\({re.escape(macro)}\)\s*(?://.*)?$"
    )
    offset = 0
    for line in text.splitlines(keepends=True):
        directive = line.lstrip()
        match = directive_re.match(directive)
        if match:
            kind = match.group(1)
            if kind in ("if", "ifdef", "ifndef"):
                frames.append(
                    {
                        "exact_positive": bool(exact_positive_re.match(directive)),
                        "true_branch_active": bool(
                            exact_positive_re.match(directive)
                        ),
                        "branch_start": offset + len(line),
                    }
                )
            elif kind in ("elif", "else") and frames:
                frame = frames[-1]
                if frame["exact_positive"] and frame["true_branch_active"]:
                    blocks.append((int(frame["branch_start"]), offset))
                frame["true_branch_active"] = False
            elif kind == "endif" and frames:
                frame = frames.pop()
                if frame["exact_positive"] and frame["true_branch_active"]:
                    blocks.append((int(frame["branch_start"]), offset))
        offset += len(line)
    return blocks


def _assert_only_in_exact_positive_macro_blocks(
    testcase: unittest.TestCase, text: str, token: str, macro: str
) -> None:
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    blocks = _positive_macro_branch_blocks(text, macro)
    testcase.assertTrue(blocks, f"missing exact positive guard for {macro}")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(
                any(start <= position < end for start, end in blocks),
                f"{token} is not inside #if defined({macro})",
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


def _preprocessor_branch_after(text: str, signature: str) -> str:
    """Returns one raw preprocessor branch after its unique condition.

    ChromeMain's mutually exclusive M7 branches share a closing brace with
    later source-selected mount branches. Raw C++ brace matching cannot model
    that preprocessor structure, so use the next branch directive as the
    boundary instead.
    """

    start = text.index(signature)
    nested_preprocessor_depth = 0
    offset = start
    for line in text[start:].splitlines(keepends=True):
        directive = line.lstrip()
        if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
            nested_preprocessor_depth += 1
        elif re.match(r"#\s*endif\b", directive):
            if nested_preprocessor_depth == 0:
                return text[start:offset]
            nested_preprocessor_depth -= 1
        elif (
            re.match(r"#\s*(elif|else)\b", directive)
            and nested_preprocessor_depth == 0
        ):
            return text[start:offset]
        offset += len(line)
    raise AssertionError(
        f"missing preprocessor branch boundary for {signature}"
    )


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
        self.content_browser_client = source(
            "chrome/browser/wasm/wasm_content_browser_client.cc"
        )
        self.cookie_manager_mojom = source(
            "services/network/public/mojom/cookie_manager.mojom"
        )
        self.cookie_manager = source("services/network/cookie_manager.cc")
        self.session_cleanup_cookie_store = source(
            "services/network/session_cleanup_cookie_store.cc"
        )
        self.sqlite_persistent_cookie_store = source(
            "net/extras/sqlite/sqlite_persistent_cookie_store.cc"
        )
        self.sqlite_persistent_cookie_store_unit = source(
            "net/extras/sqlite/sqlite_persistent_cookie_store_unittest.cc"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_browser_build = source("chrome/browser/wasm/BUILD.gn")
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.policy_probe = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_policy_probe.cc"
        )
        self.policy_probe_header = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_policy_probe.h"
        )
        self.policy_probe_unit = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_policy_probe_unittest.cc"
        )
        self.policy_probe_gni = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_policy_probe.gni"
        )
        self.shutdown_probe = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_shutdown_probe.cc"
        )
        self.shutdown_probe_header = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_shutdown_probe.h"
        )
        self.shutdown_probe_unit = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_shutdown_probe_unittest.cc"
        )
        self.shutdown_probe_gni = source(
            "chrome/browser/wasm/"
            "wasm_profile_persistent_default_partition_shutdown_probe.gni"
        )
        self.local_storage_smoke = source(
            "chrome/browser/wasm/wasm_profile_local_storage_smoke.cc"
        )
        self.local_storage_smoke_header = source(
            "chrome/browser/wasm/wasm_profile_local_storage_smoke.h"
        )
        self.indexed_db_smoke = source(
            "chrome/browser/wasm/wasm_profile_indexed_db_smoke.cc"
        )
        self.indexed_db_smoke_header = source(
            "chrome/browser/wasm/wasm_profile_indexed_db_smoke.h"
        )
        self.indexed_db_ui = source(
            "chrome/browser/wasm/wasm_profile_renderer_indexed_db_ui.cc"
        )
        self.renderer_indexed_db_runner = source(
            "tools/wasm/run_m7_chrome_renderer_indexed_db_outer_reload_dom_smoke.py"
        )
        self.renderer_indexed_db_host = source(
            "tools/wasm/host/chrome_wasm_renderer_indexed_db_outer_reload_smoke.js"
        )
        self.cache_storage_cache = source(
            "content/browser/cache_storage/cache_storage_cache.h"
        )
        self.cache_storage_cache_source = source(
            "content/browser/cache_storage/cache_storage_cache.cc"
        )
        self.cache_storage_manager = source(
            "content/browser/cache_storage/cache_storage_manager.cc"
        )
        self.cache_storage_manager_header = source(
            "content/browser/cache_storage/cache_storage_manager.h"
        )
        self.cache_storage_context = source(
            "content/browser/cache_storage/cache_storage_context_impl.cc"
        )
        self.cache_storage_control_wrapper = source(
            "content/browser/cache_storage/cache_storage_control_wrapper.cc"
        )
        self.cache_storage_control_wrapper_header = source(
            "content/browser/cache_storage/cache_storage_control_wrapper.h"
        )
        self.indexed_db_context = source(
            "content/browser/indexed_db/indexed_db_context_impl.cc"
        )
        self.indexed_db_context_header = source(
            "content/browser/indexed_db/indexed_db_context_impl.h"
        )
        self.indexed_db_build = source("content/browser/indexed_db/BUILD.gn")
        self.indexed_db_context_unit = source(
            "content/browser/indexed_db/indexed_db_context_unittest.cc"
        )
        self.indexed_db_control_wrapper = source(
            "content/browser/indexed_db/indexed_db_control_wrapper.cc"
        )
        self.indexed_db_control_wrapper_header = source(
            "content/browser/indexed_db/indexed_db_control_wrapper.h"
        )
        self.indexed_db_control_wrapper_unit = source(
            "content/browser/indexed_db/"
            "indexed_db_control_wrapper_unittest.cc"
        )
        self.indexed_db_bucket_context = source(
            "content/browser/indexed_db/instance/bucket_context.cc"
        )
        self.indexed_db_bucket_context_header = source(
            "content/browser/indexed_db/instance/bucket_context.h"
        )
        self.indexed_db_bucket_context_shutdown_receipt_unit = source(
            "content/browser/indexed_db/instance/"
            "bucket_context_shutdown_receipt_unittest.cc"
        )
        self.storage_partition_impl_source = source(
            "content/browser/storage_partition_impl.cc"
        )
        self.storage_partition_impl_header = source(
            "content/browser/storage_partition_impl.h"
        )
        self.dom_storage_test_support_header = source(
            "content/public/browser/wasm_dom_storage_test_support.h"
        )
        self.wasm_gni = source("build/config/wasm.gni")
        self.browser_context_header = source(
            "content/public/browser/browser_context.h"
        )
        self.browser_context = source("content/browser/browser_context.cc")
        self.browser_context_impl = source(
            "content/browser/browser_context_impl.h"
        )
        self.browser_context_impl_source = source(
            "content/browser/browser_context_impl.cc"
        )
        self.content_browser_build = source("content/browser/BUILD.gn")
        self.content_public_browser_build = source(
            "content/public/browser/BUILD.gn"
        )
        self.content_test_build = source("content/test/BUILD.gn")
        self.shutdown_notification_public_header = source(
            "content/public/browser/"
            "wasm_storage_partition_shutdown_test_support.h"
        )
        self.shutdown_notification_support = source(
            "content/browser/wasm_storage_partition_shutdown_test_support.cc"
        )
        self.storage_partition_map_unit = source(
            "content/browser/storage_partition_impl_map_unittest.cc"
        )

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
                    "chrome::BeginWasmProfileStorageProfileConstruction()",
                    "chrome::AbortWasmProfileStorageProfileConstructionFailClosed()",
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
            "wasmfs_create_opfs_profile_log_v4_filesystem_backend(kProfileLeaseName)",
            "bool InitializeWasmProfilePreferencesStorage()",
            "ProfileStorageMount::kDefaultProfile",
            "emscripten_is_main_browser_thread()",
            "emscripten_is_main_runtime_thread()",
            "initialization_error_ = -EAGAIN;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)

        self.assertNotIn("wasmfs_create_opfs_backend()", self.storage)
        self.assertNotIn(
            "wasmfs_create_opfs_backend_with_profile_lease(", self.storage
        )
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
            "if (!parent_backend || parent_backend != wasmfs_root_backend)",
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
            "#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) || \\\n"
            "    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)\n"
            "// Mounts one dedicated Default-profile acceptance's leased V4 OPFS backend",
            self.storage_header,
        )
        self.assertIn(
            "bool InitializeWasmProfilePreferencesStorage();", self.storage_header
        )

        self.assertIn(
            "#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \\\n"
            "    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)\n"
            "    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {\n"
            "#elif defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)\n"
            "    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {\n"
            "#elif defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)\n"
            "    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {\n"
            "#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)\n"
            "    } else if (!chrome::InitializeWasmProfilePreferencesStorage()) {\n"
            "#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)\n"
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
            "return error == 0 && !refused_for_outstanding_profile_io &&",
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
            "profile_io_observation_->ClaimPostContentFailureRetirement()",
            "profile_io_drain_permit->GetProfileIOQuiesceResult()",
            "profile_io_quiesce_result->admitted_operations == 0",
            "const bool clean_profile_io = profile_io_drain_permit.has_value();",
            "profile_io_quiesce_result->Succeeded() != clean_profile_io",
            "wasmfs_fail_closed_opfs_profile_backend(backend, &wasmfs_result)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)
        self.assertIn("kWaitingForRegisteredProfileIO", self.storage)
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
                "const bool fail_closed_retirement =\n"
                "        force_fail_closed || profile_io_failure_retirement_permit.has_value();"
            ),
        )
        self.assertIn(
            "backend_drain_result_ = result;\n"
            "    state_ = backend_drain_result_.Succeeded() ? State::kDrained\n"
            "                                               : State::kDrainFailed;\n"
            "    return backend_drain_result_;",
            self.storage,
        )

    def test_foundation_fallback_never_converts_an_uncertified_epoch_to_handoff(
        self,
    ) -> None:
        for token in (
            "enum class ProfileShutdownDisposition",
            "kCleanHandoff",
            "kFailClosed",
            "bool NotifyProfileShutdown(ProfileShutdownDisposition disposition)",
            "bool NotifyWasmProfileStorageProfileShutdownFailClosed()",
            "force_fail_closed_",
            "if (!force_fail_closed_ &&\n"
            "            profile_io_quiesce_result->admitted_operations == 0)",
            "const bool fail_closed_retirement =\n"
            "        force_fail_closed || profile_io_failure_retirement_permit.has_value();",
            "fail_closed_retirement\n"
            "            ? FailClosedRetireBackend(backend)\n"
            "            : DrainBackend(backend);",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage)

        foundation = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        profile_shutdown = foundation.index("profile_->Shutdown();")
        fail_closed_reset = foundation.index(
            "ResetProfileThenFailCloseM7ProfileStorage(profile_);"
        )
        self.assertLess(profile_shutdown, fail_closed_reset)
        self.assertIn("clean handoff from a merely terminal", foundation)

        helper = _body_after_signature(
            self.main_parts,
            "void ResetProfileThenFailCloseM7ProfileStorage(",
        )
        profile_reset = helper.index("profile.reset();")
        fail_closed_notify = helper.index(
            "chrome::NotifyWasmProfileStorageProfileShutdownFailClosed()"
        )
        self.assertLess(profile_reset, fail_closed_notify)

    def test_nonclean_profile_io_uses_failure_retirement_not_clean_handoff(
        self,
    ) -> None:
        storage_drain = _body_after_signature(
            self.storage, "WasmProfileStorageDrainResult DrainAndReleaseBackend()"
        )
        for token in (
            "WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit",
            "Status::\n              kRegisteredProfileIONotClean:",
            "profile_io_observation_->ClaimPostContentFailureRetirement()",
            "profile_io_failure_retirement_permit\n                      ->GetProfileIOQuiesceResult()",
            "const bool clean_profile_io = profile_io_drain_permit.has_value();",
            "profile_io_quiesce_result->Succeeded() != clean_profile_io",
            "const bool fail_closed_retirement =\n"
            "        force_fail_closed || profile_io_failure_retirement_permit.has_value();",
            "fail_closed_retirement\n"
            "            ? FailClosedRetireBackend(backend)\n"
            "            : DrainBackend(backend);",
        ):
            with self.subTest(token=token):
                self.assertIn(token, storage_drain)

        clean_claim = storage_drain.index(
            "profile_io_observation_->ClaimPostContentDrain()"
        )
        failure_claim = storage_drain.index(
            "profile_io_observation_->ClaimPostContentFailureRetirement()"
        )
        quiesce_validation = storage_drain.index(
            "profile_io_quiesce_result->Succeeded() != clean_profile_io"
        )
        attempt = storage_drain.index("backend_drain_attempted_ = true;")
        dispatch = storage_drain.index("? FailClosedRetireBackend(backend)")
        self.assertLess(clean_claim, quiesce_validation)
        self.assertLess(failure_claim, quiesce_validation)
        self.assertLess(quiesce_validation, attempt)
        self.assertLess(attempt, dispatch)

        normal_drain = _body_after_signature(
            self.storage,
            "static WasmProfileStorageDrainResult DrainBackend(backend_t backend)",
        )
        self.assertIn(
            "wasmfs_drain_opfs_profile_backend(backend, &wasmfs_result)",
            normal_drain,
        )
        self.assertNotIn("wasmfs_fail_closed_opfs_profile_backend", normal_drain)

        failure_retirement = _body_after_signature(
            self.storage,
            "static WasmProfileStorageDrainResult FailClosedRetireBackend(",
        )
        self.assertIn(
            "wasmfs_fail_closed_opfs_profile_backend(backend, &wasmfs_result)",
            failure_retirement,
        )
        self.assertNotIn("wasmfs_drain_opfs_profile_backend", failure_retirement)

    def test_known_test_profile_operations_must_quiesce_before_backend_drain(
        self,
    ) -> None:
        for declaration in (
            "BeginWasmProfileStorageProfileConstruction()",
            "AbortWasmProfileStorageProfileConstructionFailClosed()",
        ):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, self.storage_header)

        construction_start = _body_after_signature(
            self.storage,
            "BeginProfileConstruction()",
        )
        for token in (
            "std::make_unique<WasmProfileOrderedDrainLifecycle>()",
            "profile_construction_started_ = true;",
            "profile_io_lifecycle_->TryAcquireProfileIO()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, construction_start)
        self.assertLess(
            construction_start.index(
                "std::make_unique<WasmProfileOrderedDrainLifecycle>()"
            ),
            construction_start.index("profile_construction_started_ = true;"),
        )
        self.assertLess(
            construction_start.index("profile_construction_started_ = true;"),
            construction_start.index("profile_io_lifecycle_->TryAcquireProfileIO()"),
        )

        storage_created = _body_after_signature(
            self.storage, "bool NotifyProfileCreated()"
        )
        self.assertIn("!profile_construction_started_", storage_created)
        self.assertIn("!profile_io_lifecycle_", storage_created)
        self.assertIn("profile_created_ = true;", storage_created)
        self.assertNotIn(
            "std::make_unique<WasmProfileOrderedDrainLifecycle>()", storage_created
        )

        construction_abort = _body_after_signature(
            self.storage, "bool AbortProfileConstructionFailClosed()"
        )
        for token in (
            "force_fail_closed_ = true;",
            "profile_construction_started_",
            "profile_io_lifecycle_->BeginQuiesce()",
            "profile_shutdown_ = true;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, construction_abort)
        self.assertNotIn("kCleanHandoff", construction_abort)
        self.assertNotIn("NotifyProfileCreated", construction_abort)
        self.assertNotIn("NotifyProfileShutdown", construction_abort)
        self.assertLess(
            construction_abort.index("profile_io_lifecycle_->BeginQuiesce()"),
            construction_abort.index("profile_shutdown_ = true;"),
        )

        storage_shutdown = _body_after_signature(
            self.storage,
            "bool NotifyProfileShutdown(ProfileShutdownDisposition disposition)",
        )
        self.assertIn("!profile_created_", storage_shutdown)
        self.assertIn("if (profile_construction_started_)", storage_shutdown)
        self.assertIn("profile_io_lifecycle_->BeginQuiesce()", storage_shutdown)
        self.assertLess(
            storage_shutdown.index("profile_io_lifecycle_->BeginQuiesce()"),
            storage_shutdown.index("profile_shutdown_ = true;"),
        )

        storage_drain = _body_after_signature(
            self.storage, "WasmProfileStorageDrainResult DrainAndReleaseBackend()"
        )
        self.assertIn(
            "state_ == State::kMounted && profile_construction_started_",
            storage_drain,
        )
        self.assertIn(
            "state_ == State::kMounted && !profile_created_", storage_drain
        )
        no_created_start = storage_drain.index(
            "if (state_ == State::kMounted && !profile_created_)"
        )
        no_created = storage_drain[
            no_created_start : storage_drain.index(
                "if (state_ == State::kMounted && profile_construction_started_)",
                no_created_start,
            )
        ]
        self.assertIn("force_fail_closed_ = true;", no_created)
        self.assertNotIn("DrainBackend", no_created)
        self.assertNotIn("ClaimPostContentDrain", no_created)
        self.assertNotIn("State::kMountFailed", no_created)
        self.assertLess(
            storage_drain.index("state_ == State::kMounted && !profile_created_"),
            storage_drain.index(
                "state_ == State::kMounted && profile_construction_started_"
            ),
        )
        self.assertLess(
            storage_drain.index("force_fail_closed_ = true;"),
            storage_drain.index("backend_drain_attempted_ = true;"),
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
            storage_drain.index(
                "const bool fail_closed_retirement =\n"
                "        force_fail_closed || profile_io_failure_retirement_permit.has_value();"
            ),
        )
        self.assertLess(
            storage_drain.index(
                "profile_io_observation_->ClaimPostContentFailureRetirement()"
            ),
            storage_drain.index("? FailClosedRetireBackend(backend)"),
        )
        self.assertLess(
            storage_drain.index("force_fail_closed ||"),
            storage_drain.index("? FailClosedRetireBackend(backend)"),
        )
        self.assertIn(
            "const bool fail_closed_retirement =\n"
            "        force_fail_closed || profile_io_failure_retirement_permit.has_value();",
            storage_drain,
        )
        self.assertIn(
            "fail_closed_retirement\n"
            "            ? FailClosedRetireBackend(backend)\n"
            "            : DrainBackend(backend);",
            storage_drain,
        )

        profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.assertNotIn("StartPrefsLifetimeProfileIOAdmission", profile)
        pre_main = _body_after_signature(
            self.main_parts, "int WasmBrowserMainParts::PreMainMessageLoopRun()"
        )
        for token in (
            "chrome::BeginWasmProfileStorageProfileConstruction()",
            "WasmProfilePersistentPrefsLifetimeParticipant",
            "std::move(*preconstruction_profile_io_hold)",
            "profile_ = std::make_unique<WasmProfile>(",
            "chrome::NotifyWasmProfileStorageProfileCreated()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, pre_main)
        self.assertLess(
            pre_main.index(
                "chrome::BeginWasmProfileStorageProfileConstruction()"
            ),
            pre_main.index(
                "WasmProfilePersistentPrefsLifetimeParticipant"
            ),
        )
        self.assertLess(
            pre_main.index("WasmProfilePersistentPrefsLifetimeParticipant"),
            pre_main.index("profile_ = std::make_unique<WasmProfile>("),
        )
        self.assertLess(
            pre_main.index("profile_ = std::make_unique<WasmProfile>("),
            pre_main.index("chrome::NotifyWasmProfileStorageProfileCreated()"),
        )

        prefs_fence = _body_after_signature(
            profile, "bool WasmProfile::StartPrefsShutdownFence("
        )
        self.assertIn("base::BindPostTask", prefs_fence)
        self.assertIn("prefs_->CommitPendingWrite(", prefs_fence)
        self.assertIn(
            "CHECK(prefs_lifetime_profile_io_participant_)", prefs_fence
        )
        self.assertIn(
            "prefs_lifetime_profile_io_participant_->IsPending()", prefs_fence
        )
        self.assertLess(
            prefs_fence.index("prefs_lifetime_profile_io_participant_->IsPending()"),
            prefs_fence.index("prefs_->CommitPendingWrite("),
        )
        self.assertNotIn(
            "chrome::TryAcquireWasmProfileStorageProfileIO()", prefs_fence
        )

        prefs_completion = _body_after_signature(
            profile, "void WasmProfile::OnPrefsShutdownFenceComplete("
        )
        self.assertIn("CompleteAfterStrictFence(", prefs_completion)
        self.assertLess(
            prefs_completion.index("CompleteAfterStrictFence("),
            prefs_completion.index("prefs_shutdown_fence_state_ = success"),
        )

        database_branch_start = pre_main.index(
            "if (chrome::IsWasmProfileDatabaseSmokeEnabled())"
        )
        database_branch_end = pre_main.index(
            "#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)",
            database_branch_start,
        )
        database_branch = pre_main[database_branch_start:database_branch_end]
        database_admission = database_branch.index(
            "auto profile_io_hold = chrome::TryAcquireWasmProfileStorageProfileIO();"
        )
        database_start = database_branch.index("profile_->StartDatabaseSmoke(")
        database_transfer = database_branch.index("std::move(*profile_io_hold)")
        database_shutdown = database_branch.index(
            "RequestShutdown();", database_start
        )
        self.assertLess(database_admission, database_start)
        self.assertLess(database_start, database_transfer)
        self.assertLess(database_transfer, database_shutdown)
        self.assertNotIn("profile_io_hold->Complete(", database_branch)
        self.assertNotIn("StartWasmProfileDatabaseSmoke", database_branch)

        database_profile_start = _body_after_signature(
            profile, "bool WasmProfile::StartDatabaseSmoke("
        )
        self.assertIn(
            "std::make_unique<chrome::WasmProfileDatabaseLifetimeParticipant>",
            database_profile_start,
        )
        self.assertIn("std::move(profile_io_hold)", database_profile_start)
        self.assertIn(
            "database_lifetime_participant_->Start", database_profile_start
        )

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

    def test_failure_retirement_receipt_is_exact_and_never_a_handoff(self) -> None:
        for token in (
            "#include <cerrno>",
            "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED",
            "bool IsWasmM7ProfileFailureRetirement(",
            "result.error == -ESHUTDOWN",
            "result.libc_flush_failed == 0",
            "result.data_flush_failures == 0",
            "result.data_close_failures == 0",
            "result.prior_close_failures == 0",
            "result.lease_release_failures == 0",
            "result.backend_retire_failures == 0",
            "result.backend_sealed",
            "!result.lease_released",
            "!result.backend_retired",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.chrome_main)

        marker = self.chrome_main.index(
            "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED"
        )
        marker_emit = self.chrome_main.index(
            "if (IsWasmM7ProfileFailureRetirement(drain_result))"
        )
        backend_drain = self.chrome_main.index(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()"
        )
        backend_receipt = self.chrome_main.index(
            "chrome::NotifyWasmProfilePreferencesSmokeBackendDrain("
        )
        process_exit = self.chrome_main.index(
            "chromium_wasm_report_process_exit(exit_code)"
        )
        self.assertLess(marker, marker_emit)
        self.assertLess(backend_drain, marker_emit)
        self.assertLess(marker_emit, backend_receipt)
        self.assertLess(marker_emit, process_exit)
        _assert_only_in_m7_storage_blocks(
            self,
            self.chrome_main,
            "IsWasmM7ProfileFailureRetirement",
        )

    def test_dedicated_artifacts_reject_unowned_profile_startup_before_mount(
        self,
    ) -> None:
        preferences_capability = _preprocessor_branch_after(
            self.chrome_main,
            "if (!preferences_smoke_requested || !preferences_smoke_enabled)",
        )
        database_capability = _preprocessor_branch_after(
            self.chrome_main,
            "if (!database_smoke_requested || !database_smoke_enabled)",
        )
        local_storage_capability = _preprocessor_branch_after(
            self.chrome_main,
            "if (!local_storage_smoke_requested || !local_storage_smoke_enabled)",
        )
        indexed_db_capability = _preprocessor_branch_after(
            self.chrome_main,
            "if (!indexed_db_smoke_requested || !indexed_db_smoke_enabled)",
        )
        for capability in (
            preferences_capability,
            database_capability,
            local_storage_capability,
            indexed_db_capability,
        ):
            self.assertIn(
                "result = CHROME_RESULT_CODE_UNSUPPORTED_PARAM;", capability
            )

        preferences_capability_start = self.chrome_main.index(
            "if (!preferences_smoke_requested || !preferences_smoke_enabled)"
        )
        database_capability_start = self.chrome_main.index(
            "if (!database_smoke_requested || !database_smoke_enabled)"
        )
        local_storage_capability_start = self.chrome_main.index(
            "if (!local_storage_smoke_requested || !local_storage_smoke_enabled)"
        )
        indexed_db_capability_start = self.chrome_main.index(
            "if (!indexed_db_smoke_requested || !indexed_db_smoke_enabled)"
        )
        preferences_mount = self.chrome_main.index(
            "chrome::InitializeWasmProfilePreferencesStorage()"
        )
        database_mount = self.chrome_main.index(
            "chrome::InitializeWasmProfileStorage()"
        )
        self.assertLess(preferences_capability_start, preferences_mount)
        self.assertLess(database_capability_start, database_mount)
        self.assertLess(local_storage_capability_start, preferences_mount)
        self.assertLess(indexed_db_capability_start, preferences_mount)

    def test_experimental_main_parts_admits_and_completes_profile_lifecycle_before_drain(
        self,
    ) -> None:
        mounted = self.main_parts.index("chrome::IsWasmProfileStorageMounted()")
        user_data = self.main_parts.index(
            "base::PathService::Get(chrome::DIR_USER_DATA, &user_data_directory)"
        )
        construction_start = self.main_parts.index(
            "chrome::BeginWasmProfileStorageProfileConstruction()"
        )
        profile = self.main_parts.index(
            "profile_ = std::make_unique<WasmProfile>(\n"
            "      profile_path, std::move(prefs_lifetime_profile_io_participant));"
        )
        admitted = self.main_parts.index(
            "chrome::NotifyWasmProfileStorageProfileCreated()"
        )
        shutdown = self.main_parts.index("profile_->Shutdown();")
        complete = self.main_parts.index(
            "chrome::NotifyWasmProfileStorageProfileShutdown()"
        )

        self.assertLess(mounted, construction_start)
        self.assertLess(construction_start, user_data)
        self.assertLess(construction_start, profile)
        self.assertLess(profile, admitted)
        self.assertLess(shutdown, complete)
        self.assertNotIn("wasmfs_terminal_drain", self.main_parts)
        self.assertNotIn("wasmfs_unmount", self.main_parts)

    def test_persistent_default_partition_policy_probe_isolated_and_fail_closed(
        self,
    ) -> None:
        for token in (
            "enable_chromium_wasm_m7_persistent_default_partition_policy_probe = false",
            "M7 persistent-default-partition policy probe requires Wasm Chrome",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.wasm_gni)

        for token in (
            "wasm-chrome-m7-persistent-default-partition-policy-probe",
            "enable_chromium_wasm_m7_persistent_default_partition_policy_probe",
            "enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.policy_probe_gni)

        for token in (
            "CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE=1",
            'source_set("wasm_profile_persistent_default_partition_policy_probe")',
            'test("wasm_profile_persistent_default_partition_policy_probe_unittests")',
            '"//content/test:wasm_browser_task_environment_test_support",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.wasm_browser_build)

        probe_run = _body_after_signature(
            self.policy_probe,
            "  bool Run(content::BrowserContext* browser_context,",
        )
        for token in (
            "policy_query_count_ != 0",
            "policy_query_armed_ = true;",
            "content::StoragePartitionConfig::CreateDefault(browser_context)",
            "policy_query_armed_ = false;",
            "policy_query_count_ != 1",
            "DEFAULT_CONFIG_DEFAULT_NOT_IN_MEMORY",
        ):
            with self.subTest(token=token):
                self.assertIn(token, probe_run)
        self.assertLess(
            probe_run.index("policy_query_armed_ = true;"),
            probe_run.index(
                "content::StoragePartitionConfig::CreateDefault(browser_context)"
            ),
        )
        self.assertLess(
            probe_run.index(
                "content::StoragePartitionConfig::CreateDefault(browser_context)"
            ),
            probe_run.index("policy_query_armed_ = false;"),
        )
        self.assertNotIn("GetDefaultStoragePartition(", self.policy_probe)
        self.assertNotIn("GetStoragePartition(", self.policy_probe)

        policy_record = _body_after_signature(
            self.policy_probe, "  void RecordPolicyQuery()"
        )
        for token in (
            "++policy_query_count_;",
            "!policy_query_armed_ || policy_query_count_ != 1",
            "kPolicyQuery",
        ):
            with self.subTest(token=token):
                self.assertIn(token, policy_record)
        self.assertIn(
            "void RecordWasmPersistentDefaultPartitionPolicyProbePolicyQuery();",
            self.policy_probe_header,
        )

        profile_policy = _body_after_signature(
            self.profile,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn(
            "chrome::RecordWasmPersistentDefaultPartitionPolicyProbePolicyQuery();",
            profile_policy,
        )
        self.assertIn("return false;", profile_policy)

        self.assertIn(
            "content::StoragePartitionConfig::CreateDefault(&browser_context)",
            self.policy_probe_unit,
        )
        self.assertIn(
            "EXPECT_EQ(1, browser_context.policy_query_count());",
            self.policy_probe_unit,
        )
        self.assertNotIn(
            "GetDefaultStoragePartition(", self.policy_probe_unit
        )

        pre_main = _body_after_signature(
            self.main_parts, "int WasmBrowserMainParts::PreMainMessageLoopRun()"
        )
        profile_created = pre_main.index(
            "chrome::NotifyWasmProfileStorageProfileCreated()"
        )
        policy_branch = pre_main.index(
            "#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE)",
            profile_created,
        )
        host_input = pre_main.index("chrome::InitializeWasmBrowserHostInput()")
        self.assertLess(profile_created, policy_branch)
        self.assertLess(policy_branch, host_input)
        policy_branch_text = pre_main[policy_branch:host_input]
        self.assertIn(
            "chrome::RunWasmPersistentDefaultPartitionPolicyProbe(",
            policy_branch_text,
        )
        self.assertIn("RequestShutdown();", policy_branch_text)
        self.assertNotIn("GetDefaultStoragePartition(", policy_branch_text)
        ordinary_pre_main_remainder = (
            "#if !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \\\n"
            "    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)\n"
            "#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)"
        )
        self.assertIn(ordinary_pre_main_remainder, pre_main)
        self.assertLess(
            policy_branch,
            pre_main.index(ordinary_pre_main_remainder),
        )
        self.assertIn("#endif  // !policy-probe && !structural-shutdown-probe", pre_main)
        pre_profile_browser_setup = pre_main[
            pre_main.index(
                "// The policy-only and structural-shutdown artifacts own their exact first"
            ) : pre_main.index("// BrowserThread::IO and ThreadPool are live")
        ]
        self.assertIn(
            "#if !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY_PROBE) && \\\n"
            "    !defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)",
            pre_profile_browser_setup,
        )
        self.assertIn(
            "EnsureWasmBrowserKeyedServiceFactoriesBuilt();",
            pre_profile_browser_setup,
        )
        self.assertIn(
            "chrome::EnsureWasmVersionWebUIConfigRegistered();",
            pre_profile_browser_setup,
        )
        self.assertIn(
            "#endif  // !policy-probe && !structural-shutdown-probe",
            pre_profile_browser_setup,
        )

        finish_shutdown = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        profile_reset = finish_shutdown.index("profile_.reset();")
        policy_clean_check = finish_shutdown.index(
            "chrome::CanWasmPersistentDefaultPartitionPolicyProbeUseCleanShutdown()"
        )
        profile_shutdown_choice = finish_shutdown.index(
            "policy_probe_can_clean_shutdown\n"
            "            ? chrome::NotifyWasmProfileStorageProfileShutdown()"
        )
        self.assertLess(profile_reset, policy_clean_check)
        self.assertLess(policy_clean_check, profile_shutdown_choice)
        self.assertIn(
            "policy_probe_can_clean_shutdown\n"
            "            ? chrome::NotifyWasmProfileStorageProfileShutdown()\n"
            "            : chrome::NotifyWasmProfileStorageProfileShutdownFailClosed();",
            finish_shutdown,
        )
        self.assertIn(
            "chrome::NotifyWasmPersistentDefaultPartitionPolicyProbeStorageLifecycle(\n"
            "        smoke_allows_storage_lifecycle);",
            finish_shutdown,
        )

        for token in (
            "persistent_default_partition_policy_probe_requested",
            "persistent_default_partition_policy_probe_enabled",
            "chrome::NotifyWasmPersistentDefaultPartitionPolicyProbeBackendDrain(\n"
            "        drain_result.Succeeded());",
            "chrome::DidWasmPersistentDefaultPartitionPolicyProbeComplete()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.chrome_main)

    def test_result_bearing_indexed_db_close_is_source_selected(self) -> None:
        shutdown_macro = (
            "CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE"
        )
        shutdown_flag = (
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe"
        )
        wrapper_test_source = '"indexed_db_control_wrapper_unittest.cc"'

        self.assertIn('import("//build/config/wasm.gni")', self.indexed_db_build)
        probe_config = _body_after_signature(
            self.indexed_db_build,
            'config("wasm_m7_persistent_default_partition_shutdown_probe")',
        )
        self.assertIn(f'"{shutdown_macro}=1",', probe_config)

        indexed_db_target = _body_after_signature(
            self.indexed_db_build, 'source_set("indexed_db")'
        )
        indexed_db_selector_start = indexed_db_target.index(
            f"if ({shutdown_flag}) {{"
        )
        indexed_db_selector_opening_brace = indexed_db_target.index(
            "{", indexed_db_selector_start
        )
        indexed_db_selector_end = _matching_closing_brace(
            indexed_db_target,
            indexed_db_selector_opening_brace,
            "IndexedDB result-close source selector",
        )
        indexed_db_selector = indexed_db_target[
            indexed_db_selector_opening_brace + 1 : indexed_db_selector_end
        ]
        for token in (
            '":wasm_m7_persistent_default_partition_shutdown_probe"',
            "configs += [",
            "public_configs",
        ):
            with self.subTest(indexed_db_selector_token=token):
                self.assertIn(token, indexed_db_selector)

        unit_tests_target = _body_after_signature(
            self.indexed_db_build, 'source_set("unit_tests")'
        )
        unit_tests_selector_start = unit_tests_target.index(
            f"if ({shutdown_flag}) {{"
        )
        unit_tests_selector_opening_brace = unit_tests_target.index(
            "{", unit_tests_selector_start
        )
        unit_tests_selector_end = _matching_closing_brace(
            unit_tests_target,
            unit_tests_selector_opening_brace,
            "IndexedDB result-close unit-test selector",
        )
        unit_tests_selector = unit_tests_target[
            unit_tests_selector_opening_brace + 1 : unit_tests_selector_end
        ]
        for token in (
            '":wasm_m7_persistent_default_partition_shutdown_probe"',
            "configs += [",
            f"sources += [ {wrapper_test_source} ]",
        ):
            with self.subTest(indexed_db_unit_selector_token=token):
                self.assertIn(token, unit_tests_selector)
        self.assertEqual(1, self.indexed_db_build.count(wrapper_test_source))

        dedicated_test = _body_after_signature(
            self.wasm_browser_build,
            'test("wasm_profile_persistent_default_partition_shutdown_probe_unittests")',
        )
        for token in (
            '"../../../content/browser/indexed_db/indexed_db_control_wrapper_unittest.cc",',
            '"//content/browser/indexed_db:wasm_m7_persistent_default_partition_shutdown_receipt_unittests",',
            '":wasm_profile_m7_persistent_default_partition_shutdown_probe_config",',
        ):
            with self.subTest(dedicated_test_token=token):
                self.assertIn(token, dedicated_test)
        dedicated_test_position = self.wasm_browser_build.index(
            'test("wasm_profile_persistent_default_partition_shutdown_probe_unittests")'
        )
        dedicated_selector_start = self.wasm_browser_build.rfind(
            f"if ({shutdown_flag}) {{", 0, dedicated_test_position
        )
        self.assertNotEqual(-1, dedicated_selector_start)
        dedicated_selector_opening_brace = self.wasm_browser_build.index(
            "{", dedicated_selector_start
        )
        dedicated_selector_end = _matching_closing_brace(
            self.wasm_browser_build,
            dedicated_selector_opening_brace,
            "dedicated IndexedDB result-close test selector",
        )
        self.assertLess(dedicated_selector_opening_brace, dedicated_test_position)
        self.assertLess(dedicated_test_position, dedicated_selector_end)

        receipt_test_target = _body_after_signature(
            self.indexed_db_build,
            'source_set("wasm_m7_persistent_default_partition_shutdown_receipt_unittests")',
        )
        for token in (
            '"instance/bucket_context_shutdown_receipt_unittest.cc"',
            '":wasm_m7_persistent_default_partition_shutdown_probe"',
            '":indexed_db"',
        ):
            with self.subTest(receipt_test_target_token=token):
                self.assertIn(token, receipt_test_target)

        for text, token in (
            (self.indexed_db_context_header, "static bool ShutdownAndReply("),
            (self.indexed_db_control_wrapper_header, "bool ShutdownAndReply("),
            (
                self.indexed_db_bucket_context_header,
                "void SealForContextShutdown(base::OnceClosure on_destroyed);",
            ),
            (
                self.indexed_db_bucket_context_header,
                "base::OnceClosure on_destroyed_after_destruction;",
            ),
            (self.indexed_db_context, "class IndexedDBShutdownAndReplyState"),
            (
                self.indexed_db_context,
                "bool IndexedDBContextImpl::ShutdownAndReply(",
            ),
            (
                self.indexed_db_control_wrapper,
                "bool IndexedDBControlWrapper::ShutdownAndReply(",
            ),
            (
                self.indexed_db_bucket_context,
                "void BucketContext::SealForContextShutdown(",
            ),
            (
                self.storage_partition_impl_header,
                "bool ShutdownIndexedDBForWasmTest(base::OnceClosure completion);",
            ),
            (
                self.storage_partition_impl_source,
                "bool StoragePartitionImpl::ShutdownIndexedDBForWasmTest(",
            ),
            (
                self.indexed_db_context_unit,
                "ShutdownAndReplySealsFactoryIngress",
            ),
            (
                self.indexed_db_bucket_context_shutdown_receipt_unit,
                "SealForContextShutdownWithholdsAckWhenFinalPostRejected",
            ),
            (
                self.indexed_db_control_wrapper_unit,
                "PolicyNotificationAfterResultCloseDoesNotUseClosedControl",
            ),
        ):
            _assert_only_in_exact_positive_macro_blocks(
                self, text, token, shutdown_macro
            )

        ordinary_destruction_callback = (
            "  if (delegate_.on_destroyed) {\n"
            "    std::move(delegate_.on_destroyed).Run();\n"
            "  }"
        )
        ordinary_callback_position = self.indexed_db_bucket_context.index(
            ordinary_destruction_callback
        )
        self.assertFalse(
            any(
                start <= ordinary_callback_position < end
                for start, end in _positive_macro_branch_blocks(
                    self.indexed_db_bucket_context, shutdown_macro
                )
            )
        )

    def test_persistent_default_partition_shutdown_probe_seals_creation_and_fail_closes(
        self,
    ) -> None:
        for token in (
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe = false",
            "M7 persistent-default-partition shutdown probe requires Wasm Chrome",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.wasm_gni)

        for token in (
            "wasm-chrome-m7-persistent-default-partition-shutdown-probe",
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe",
            "enable_chromium_wasm_m7_persistent_default_partition_policy_probe",
            "M7 persistent-default-partition shutdown probe requires its own fresh",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.shutdown_probe_gni)

        for token in (
            "CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE=1",
            "CHROME_WASM_M7_LOCAL_STORAGE_CLOSE_FENCE_TEST=1",
            'source_set("wasm_profile_persistent_default_partition_shutdown_probe")',
            '":wasm_profile_local_storage_smoke",',
            'test("wasm_profile_persistent_default_partition_shutdown_probe_unittests")',
            '":wasm_profile_persistent_default_partition_shutdown_probe",',
            '"../../../content/browser/indexed_db/indexed_db_control_wrapper_unittest.cc",',
            '"//content/browser/indexed_db",',
            '"//storage/browser:test_support",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.wasm_browser_build)

        # The shutdown artifact borrows only the browser-side close fence. Its
        # target does not compile the legacy renderer/WebUI source closure.
        local_storage_target_position = self.wasm_browser_build.index(
            'source_set("wasm_profile_local_storage_smoke")'
        )
        local_storage_outer_selector_start = self.wasm_browser_build.rfind(
            "if (enable_chromium_wasm_m7_default_partition_local_storage_test ||",
            0,
            local_storage_target_position,
        )
        self.assertNotEqual(-1, local_storage_outer_selector_start)
        local_storage_outer_selector = self.wasm_browser_build[
            local_storage_outer_selector_start : self.wasm_browser_build.index(
                "{", local_storage_outer_selector_start
            )
        ]
        self.assertIn(
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe",
            local_storage_outer_selector,
        )
        local_storage_target = _body_after_signature(
            self.wasm_browser_build,
            'source_set("wasm_profile_local_storage_smoke")',
        )
        self.assertIn(
            'sources = [ "wasm_profile_local_storage_smoke.cc" ]',
            local_storage_target,
        )
        self.assertIn(
            '":wasm_profile_m7_persistent_default_partition_shutdown_probe_config",',
            local_storage_target,
        )
        renderer_selector_start = local_storage_target.index(
            "    if (enable_chromium_wasm_m7_default_partition_local_storage_test ||"
        )
        renderer_selector_opening_brace = local_storage_target.index(
            "{", renderer_selector_start
        )
        renderer_selector_end = _matching_closing_brace(
            local_storage_target,
            renderer_selector_opening_brace,
            "legacy LocalStorage renderer source selector",
        )
        renderer_selector = local_storage_target[
            renderer_selector_start : renderer_selector_end + 1
        ]
        self.assertIn("wasm_profile_renderer_local_storage_ui.cc", renderer_selector)
        self.assertNotIn(
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe",
            renderer_selector,
        )
        self.assertLess(
            local_storage_target.index(
                'sources = [ "wasm_profile_local_storage_smoke.cc" ]'
            ),
            renderer_selector_start,
        )
        self.assertIn(
            "defined(CHROME_WASM_M7_LOCAL_STORAGE_CLOSE_FENCE_TEST)",
            self.dom_storage_test_support_header,
        )
        self.assertNotIn(
            "#define CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST",
            self.dom_storage_test_support_header,
        )

        shutdown_run = _body_after_signature(
            self.shutdown_probe,
            "  bool Run(content::BrowserContext* browser_context,",
        )
        for token in (
            "profile_io_hold_.emplace(std::move(profile_io_hold));",
            "browser_context->GetLoadedStoragePartitionCount() != 0u",
            "browser_context_ = browser_context;",
            "browser_context->GetDefaultStoragePartition();",
            "policy_query_phase_ = PolicyQueryPhase::kDefaultPartition;",
            "policy_query_phase_ = PolicyQueryPhase::kNone;",
            "policy_query_count_ != 1",
            "config->is_default()",
            "config->in_memory()",
            "partition->GetPath() == browser_context->GetPath()",
            "IsCapturedDefaultPartitionStillSoleLoaded()",
            'EmitMarker("DEFAULT_PARTITION_CREATED");',
        ):
            with self.subTest(token=token):
                self.assertIn(token, shutdown_run)
        self.assertLess(
            shutdown_run.index(
                "policy_query_phase_ = PolicyQueryPhase::kDefaultPartition;"
            ),
            shutdown_run.index("browser_context->GetDefaultStoragePartition();"),
        )
        self.assertLess(
            shutdown_run.index("browser_context->GetDefaultStoragePartition();"),
            shutdown_run.index("policy_query_phase_ = PolicyQueryPhase::kNone;"),
        )
        self.assertGreaterEqual(
            self.shutdown_probe.count("GetStoragePartition("), 2
        )
        self.assertNotIn("Flush(", self.shutdown_probe)

        # Run() owns the only fail-closed initial default-partition policy
        # query. Later SiteInfo/frame-host config derivations are permitted,
        # while renderer identity is proved by the committed RFH plus no-create
        # lookup of the captured partition.
        record_policy_query = _body_after_signature(
            self.shutdown_probe,
            "  void RecordPolicyQuery(content::BrowserContext* browser_context)",
        )
        for token in (
            "is_initial_default_partition_query",
            "browser_context != browser_context_",
            "(!is_initial_default_partition_query && !partition_created_)",
        ):
            with self.subTest(policy_query_token=token):
                self.assertIn(token, record_policy_query)
        self.assertNotIn("PolicyQueryPhase::kRenderer", self.shutdown_probe)
        self.assertNotIn("ObserveIndexedDBWebContentsTeardown", self.shutdown_probe)
        self.assertNotIn("CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_DEBUG", self.shutdown_probe)
        for token in (
            "content::StoragePartition* storage_partition,",
            "calling BrowserContext::GetDefaultStoragePartition().",
        ):
            with self.subTest(local_storage_header_token=token):
                self.assertIn(token, self.local_storage_smoke_header)
        for token in (
            "input.emit_protocol_markers = false;",
            "crypto::RandBytesAsArray<32>()",
            "PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK",
            "kLocalStorageOperationTimeout",
            "local_storage_participant_->QuarantineForFailureShutdown()",
        ):
            with self.subTest(local_storage_token=token):
                self.assertIn(token, self.shutdown_probe)
        local_storage_start = _body_after_signature(
            self.local_storage_smoke,
            "  bool Start(base::OnceCallback<void(bool)> completion)",
        )
        supplied_partition_start = local_storage_start.index(
            "if (storage_partition) {"
        )
        supplied_partition_opening_brace = local_storage_start.index(
            "{", supplied_partition_start
        )
        supplied_partition_end = _matching_closing_brace(
            local_storage_start,
            supplied_partition_opening_brace,
            "supplied LocalStorage StoragePartition validation",
        )
        supplied_partition_branch = local_storage_start[
            supplied_partition_start : supplied_partition_end + 1
        ]
        for token in (
            "const content::StoragePartitionConfig& config =",
            "!config.is_default() || config.in_memory()",
            "storage_partition->GetPath() != profile_path_",
        ):
            with self.subTest(supplied_partition_token=token):
                self.assertIn(token, supplied_partition_branch)
        self.assertNotIn("GetDefaultStoragePartition(", supplied_partition_branch)
        self.assertLess(
            supplied_partition_end,
            local_storage_start.index(
                "storage_partition = browser_context_->GetDefaultStoragePartition();"
            ),
        )

        local_storage_receipt_start = _body_after_signature(
            self.shutdown_probe, "  void StartLocalStorageReceipt()"
        )
        for token in (
            "TryAcquireWasmProfileStorageProfileIO()",
            "std::make_unique<WasmProfileLocalStorageLifetimeParticipant>(",
            "browser_context_, partition_, partition_->GetPath()",
            "local_storage_operation_timeout_.Start(",
            "OnLocalStorageOperationTimeout",
            "OnLocalStorageReceiptClosed",
        ):
            with self.subTest(local_storage_receipt_token=token):
                self.assertIn(token, local_storage_receipt_start)
        local_storage_closed = _body_after_signature(
            self.shutdown_probe, "  void OnLocalStorageReceiptClosed(bool success)"
        )
        for token in (
            "local_storage_participant_->DidSucceed()",
            "local_storage_on_disk_commit_and_close_acknowledged_ = true;",
            'EmitMarker("PERSISTENT_LOCAL_STORAGE_ON_DISK_'
            'MAP_UPDATE_AND_CLOSE_OK");',
            "StartIndexedDBReceipt();",
        ):
            with self.subTest(local_storage_closed_token=token):
                self.assertIn(token, local_storage_closed)
        self.assertLess(
            local_storage_closed.index(
                'EmitMarker("PERSISTENT_LOCAL_STORAGE_ON_DISK_'
                'MAP_UPDATE_AND_CLOSE_OK");'
            ),
            local_storage_closed.index("StartIndexedDBReceipt();"),
        )
        local_storage_failure = _body_after_signature(
            self.shutdown_probe, "  void FailLocalStorageReceipt("
        )
        for token in (
            "local_storage_operation_timeout_.Stop();",
            "local_storage_participant_->Cancel();",
            "local_storage_participant_->QuarantineForFailureShutdown();",
            "ScheduleSelectedOwnerReceiptsCompletion(/*success=*/false);",
        ):
            with self.subTest(local_storage_failure_token=token):
                self.assertIn(token, local_storage_failure)

        for token in (
            "content::SiteInstance::Create(browser_context_)",
            "RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK",
            "PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK",
            "PERSISTENT_CACHE_API_RENDERER_WRITE_AND_READBACK_OK",
            "PERSISTENT_CACHE_API_SELECTED_BACKEND_CLOSE_AND_INDEX_REPLACED_OK",
            "PERSISTENT_INDEXED_DB_CONTEXT_CLOSED",
            "WasmProfileIndexedDBLifetimeParticipant",
            "kIndexedDBOperationTimeout",
            "kIndexedDBContextShutdownTimeout",
            "indexed_db_participant_->QuarantineForFailureShutdown()",
            "indexed_db_context_shutdown_profile_io_hold_",
            "ShutdownWasmStoragePartitionIndexedDBForTest(",
            "TakeRendererConfigForSite(",
            "renderer_default_partition_config_",
            "renderer_indexed_db_page_url_",
            "GetStoragePartition(\n               *renderer_default_partition_config_, /*can_create=*/false)",
        ):
            with self.subTest(indexed_db_shutdown_token=token):
                self.assertIn(token, self.shutdown_probe)
        self.assertNotIn(
            "content::SiteInstance::CreateForURL(", self.shutdown_probe
        )
        for token in (
            "content::StoragePartition* expected_default_storage_partition",
            "scoped_refptr<content::SiteInstance> renderer_site_instance",
            "create_params.site_instance = renderer_site_instance_",
            "actual_partition != expected_default_storage_partition_",
        ):
            with self.subTest(indexed_db_participant_token=token):
                self.assertIn(token, self.indexed_db_smoke)
        self.assertIn("emit_protocol_markers = true", self.indexed_db_smoke_header)
        for text, token in (
            (self.shutdown_probe, "input.require_cache_api_write_readback = true;"),
            (
                self.indexed_db_smoke,
                "DidRendererCacheAPIWriteAndReadbackSucceed()",
            ),
            (
                self.indexed_db_smoke,
                "DidRendererCacheAPIBackendCloseAndIndexReplacementSucceed()",
            ),
            (
                self.indexed_db_smoke,
                "StartRendererCacheAPIBackendCloseAndIndexReplacement();",
            ),
            (self.indexed_db_smoke_header, "Cache Storage close, flush, durability"),
            (self.indexed_db_ui, "https://m7-cache-api-write-readback.test/"),
            (self.indexed_db_ui, "globalThis.caches.open(cacheName)"),
            (self.indexed_db_ui, "await cache.put(request, new Response(token))"),
            (self.indexed_db_ui, "response = await cache.match(request)"),
            (self.indexed_db_ui, "&cache-api=write-readback"),
            (
                self.content_browser_client,
                "kCacheAPIWriteReadbackSuffix",
            ),
            (self.indexed_db_smoke, 'kCacheAPISwitch[] = "wasm-profile-indexed-db-cache-api"'),
            (self.indexed_db_smoke, 'kRendererCacheAPIPersistenceName[] ='),
            (self.indexed_db_smoke, 'input_.require_cache_api_persistence = has_cache_api;'),
            (self.indexed_db_smoke, '"&cache-api=persistence"'),
            (self.indexed_db_smoke, 'CACHE_API_REOPEN_READ_A_OK'),
            (self.indexed_db_smoke, 'CACHE_API_WRITE_B_OK'),
            (self.indexed_db_smoke, 'CACHE_API_REOPEN_READ_B_OK'),
            (self.indexed_db_ui, 'cacheApiPersistenceName = "m7-renderer-cache-api-persistence-v1"'),
            (self.indexed_db_ui, '"m7-indexed-db-renderer-write-cache-api-persistence-ok"'),
            (self.indexed_db_ui, '"m7-indexed-db-renderer-verify-a-write-b-cache-api-persistence-ok"'),
            (self.indexed_db_ui, '"m7-indexed-db-renderer-verify-b-cache-api-persistence-ok"'),
            (self.renderer_indexed_db_runner, '"--cache-api-persistence"'),
            (self.renderer_indexed_db_runner, '"cacheApiPersistence": self.cache_api_persistence'),
            (self.renderer_indexed_db_host, '"cacheApiPersistence"'),
            (self.renderer_indexed_db_host, 'CACHE_API_BACKEND_CLOSED_AND_INDEX_REPLACED'),
            (self.renderer_indexed_db_host, 'cacheApiPersistence: cacheApi === "1"'),
            (self.cache_storage_cache, "CHROME_WASM_M7_CACHE_STORAGE_CLOSE_RECEIPT_TEST"),
            (self.cache_storage_cache_source, "CHROME_WASM_M7_CACHE_STORAGE_CLOSE_RECEIPT_TEST"),
            (self.cache_storage_manager, "CloseLiveDefaultCacheAndWriteIndexForWasmTest"),
            (self.cache_storage_manager_header, "CloseLiveDefaultCacheAndWriteIndexForWasmTest"),
            (self.cache_storage_context, "CloseLiveDefaultCacheAndWriteIndexForWasmTest"),
            (self.cache_storage_control_wrapper, "CloseLiveDefaultCacheAndWriteIndexForWasmTest"),
            (self.cache_storage_control_wrapper_header, "CloseLiveDefaultCacheAndWriteIndexForWasmTest"),
            # The CacheStorage receipt implementation define is deliberately
            # private to content/browser; the public config only carries the
            # profile-indexed-db class-layout define.
            (self.content_browser_build, "CHROME_WASM_M7_CACHE_STORAGE_CLOSE_RECEIPT_TEST=1"),
            (self.content_test_build, "CHROME_WASM_M7_CACHE_STORAGE_CLOSE_RECEIPT_TEST=1"),
        ):
            with self.subTest(cache_api_token=token):
                self.assertIn(token, text)
        self.assertIn(
            "m7-indexed-db-renderer-write-cache-api-write-readback-ok",
            self.indexed_db_ui,
        )
        outer_indexed_db_timeout = re.search(
            r"constexpr base::TimeDelta kIndexedDBOperationTimeout = "
            r"base::Seconds\((\d+)\);",
            self.shutdown_probe,
        )
        renderer_cache_api_timeout = re.search(
            r"constexpr base::TimeDelta "
            r"kRendererCacheAPIWriteReadbackOperationTimeout =\n"
            r"    base::Seconds\((\d+)\);",
            self.indexed_db_smoke,
        )
        self.assertIsNotNone(outer_indexed_db_timeout)
        self.assertIsNotNone(renderer_cache_api_timeout)
        self.assertGreaterEqual(
            int(outer_indexed_db_timeout.group(1)),
            int(renderer_cache_api_timeout.group(1)) + 5,
        )
        indexed_db_context_close_start = _body_after_signature(
            self.shutdown_probe, "  void StartIndexedDBContextShutdownReceipt()"
        )
        for token in (
            "TryAcquireWasmProfileStorageProfileIO()",
            "indexed_db_context_shutdown_profile_io_hold_.emplace(",
            "indexed_db_context_shutdown_started_ = true;",
            "content::ShutdownWasmStoragePartitionIndexedDBForTest(",
            "OnIndexedDBContextShutdownClosed",
            "OnIndexedDBContextShutdownTimeout",
        ):
            with self.subTest(indexed_db_context_close_token=token):
                self.assertIn(token, indexed_db_context_close_start)
        self.assertLess(
            indexed_db_context_close_start.index(
                "indexed_db_context_shutdown_started_ = true;"
            ),
            indexed_db_context_close_start.index(
                "content::ShutdownWasmStoragePartitionIndexedDBForTest("
            ),
        )
        self.assertIn(
            "if (!indexed_db_context_shutdown_acknowledged_ && !failure_reported_)",
            indexed_db_context_close_start,
        )
        indexed_db_context_closed = _body_after_signature(
            self.shutdown_probe, "  void OnIndexedDBContextShutdownClosed()"
        )
        for token in (
            "ProfileIOCompletion::\n                kSucceeded",
            "indexed_db_context_shutdown_acknowledged_ = true;",
            'EmitMarker("PERSISTENT_INDEXED_DB_CONTEXT_CLOSED");',
            "StartCookieReceipt();",
        ):
            with self.subTest(indexed_db_context_closed_token=token):
                self.assertIn(token, indexed_db_context_closed)
        self.assertLess(
            indexed_db_context_closed.index(
                'EmitMarker("PERSISTENT_INDEXED_DB_CONTEXT_CLOSED");'
            ),
            indexed_db_context_closed.index("StartCookieReceipt();"),
        )
        self.assertLess(
            self.shutdown_probe.index(
                'EmitMarker("PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK");'
            ),
            self.shutdown_probe.index(
                'EmitMarker("PERSISTENT_CACHE_API_RENDERER_WRITE_AND_READBACK_OK");'
            ),
        )
        self.assertLess(
            self.shutdown_probe.index(
                'EmitMarker("PERSISTENT_CACHE_API_RENDERER_WRITE_AND_READBACK_OK");'
            ),
            self.shutdown_probe.index(
                'EmitMarker(\n'
                '        "PERSISTENT_CACHE_API_SELECTED_BACKEND_CLOSE_AND_INDEX_REPLACED_OK");'
            ),
        )
        self.assertLess(
            self.shutdown_probe.index(
                'EmitMarker(\n'
                '        "PERSISTENT_CACHE_API_SELECTED_BACKEND_CLOSE_AND_INDEX_REPLACED_OK");'
            ),
            self.shutdown_probe.index(
                'EmitMarker("PERSISTENT_INDEXED_DB_CONTEXT_CLOSED");'
            ),
        )
        self.assertLess(
            self.shutdown_probe.index(
                'EmitMarker("PERSISTENT_INDEXED_DB_CONTEXT_CLOSED");'
            ),
            self.shutdown_probe.index(
                'EmitMarker("PERSISTENT_COOKIE_WRITE_ACCEPTED");'
            ),
        )
        start_cookie_receipt = _body_after_signature(
            self.shutdown_probe, "  void StartCookieReceipt()"
        )
        self.assertIn(
            "!indexed_db_context_shutdown_acknowledged_", start_cookie_receipt
        )
        self.assertIn(
            "bool indexed_db_context_shutdown_acknowledged,",
            self.shutdown_probe_header,
        )
        self.assertIn(
            "bool cache_api_renderer_write_and_readback_acknowledged,",
            self.shutdown_probe_header,
        )
        self.assertIn(
            "bool cache_api_selected_backend_close_and_index_replacement_acknowledged);",
            self.shutdown_probe_header,
        )
        for token in (
            "bool IndexedDBContextImpl::ShutdownAndReply(",
            "shutdown_in_progress_ = true;",
            "control_receivers_.Clear();",
            "test_receivers_.Clear();",
            "quota_client_receiver_.reset();",
            "InitializeFromFilesIfNeeded(base::BindOnce(",
            "ContinueShutdownAndReplyAfterInitialization",
            "IndexedDBContextOnTaskRunner",
            "base::OnTaskRunnerDeleter",
            "HoldUntilFinished",
            "detached_bucket_context_generations_",
            "OnDetachedBucketContextDestroyed",
            "destruction_barrier",
            "seal_barrier",
            "BucketContext::SealForContextShutdown",
            "FinishShutdownAndReply",
        ):
            with self.subTest(indexed_db_context_impl_token=token):
                self.assertIn(token, self.indexed_db_context)
        self.assertIn(
            "Returns false without consuming |context|", self.indexed_db_context_header
        )
        bind_pipes = _body_after_signature(
            self.indexed_db_context,
            "void IndexedDBContextImpl::BindPipesOnIDBSequence(",
        )
        self.assertIn("if (shutdown_in_progress_)", bind_pipes)
        delete_bucket_data = _body_after_signature(
            self.indexed_db_context,
            "void IndexedDBContextImpl::DeleteBucketData(",
        )
        self.assertIn("blink::mojom::QuotaStatusCode::kErrorAbort", delete_bucket_data)
        self.assertIn("if (shutdown_in_progress_)", delete_bucket_data)
        public_force_close = _body_after_signature(
            self.indexed_db_context,
            "void IndexedDBContextImpl::ForceClose(storage::BucketId bucket_id,",
        )
        self.assertIn("if (shutdown_in_progress_)", public_force_close)
        wrapper_close = _body_after_signature(
            self.indexed_db_control_wrapper,
            "bool IndexedDBControlWrapper::ShutdownAndReply(",
        )
        for token in (
            "storage_policy_observer_.reset();",
            "indexed_db_control_.reset();",
        ):
            with self.subTest(indexed_db_wrapper_close_token=token):
                self.assertIn(token, wrapper_close)
        for signature in (
            "void IndexedDBControlWrapper::BindIndexedDB(",
            "void IndexedDBControlWrapper::OnSpecialStoragePolicyUpdated(",
        ):
            self.assertIn(
                "if (!context_)",
                _body_after_signature(self.indexed_db_control_wrapper, signature),
            )
        for token in (
            "PolicyNotificationAfterResultCloseDoesNotUseClosedControl",
            "ShutdownAndReply(base::BindPostTask",
            "HasObserverForTesting",
            "InitializeMojoCoreForWasmTests",
            "BindNewPipeAndPassRemote",
            "AddSessionOnly",
            "NotifyPolicyChanged",
        ):
            with self.subTest(indexed_db_wrapper_unit_token=token):
                self.assertIn(token, self.indexed_db_control_wrapper_unit)
        for token in (
            "BucketContext::InsertTeardownStepForTesting",
            "BucketContext::InsertDestructionStepForTesting",
            "BucketContext::InsertFinalDestructionStepForTesting",
            "EXPECT_TRUE(teardown_step_ran->load());",
            "EXPECT_TRUE(destruction_step_ran->load());",
            "EXPECT_TRUE(final_destruction_step_ran->load());",
            "ShutdownAndReplySealsFactoryIngress",
            "ShutdownAndReplyWaitsForAlreadyDetachedBucketDestruction",
            "ShutdownAndReplySealsQueuedDestructionBeforePurge",
            "ShutdownAndReplyDoesNotConsumeOnRejectedPost",
            "factory.set_disconnect_handler",
        ):
            with self.subTest(indexed_db_context_unit_token=token):
                self.assertIn(token, self.indexed_db_context_unit)
        for token in (
            "SealForContextShutdownWithholdsAckWhenFinalPostRejected",
            "RejectNextPostTaskRunner",
            "RejectNextPost",
            "rejected_post_count",
        ):
            with self.subTest(indexed_db_bucket_context_unit_token=token):
                self.assertIn(
                    token, self.indexed_db_bucket_context_shutdown_receipt_unit
                )
        for token in (
            "void SealForContextShutdown(base::OnceClosure on_destroyed);",
            "bool context_shutdown_in_progress_ = false;",
            "InsertDestructionStepForTesting",
            "InsertFinalDestructionStepForTesting",
            "on_destroyed_after_destruction",
        ):
            with self.subTest(indexed_db_bucket_context_header_token=token):
                self.assertIn(token, self.indexed_db_bucket_context_header)
        sealed_bucket = _body_after_signature(
            self.indexed_db_bucket_context,
            "void BucketContext::SealForContextShutdown(",
        )
        for token in (
            "context_shutdown_in_progress_ = true;",
            "delegate().on_ready_for_destruction.Reset();",
            "receivers_.Clear();",
            "DoForceClose(/*doom=*/false, \"Context shutdown\");",
            "delegate().on_destroyed_after_destruction",
        ):
            with self.subTest(sealed_bucket_token=token):
                self.assertIn(token, sealed_bucket)
        for signature in (
            "void BucketContext::AddReceiver(",
            "void BucketContext::GetDatabaseInfo(",
            "void BucketContext::Open(",
            "void BucketContext::DeleteDatabase(",
        ):
            with self.subTest(bucket_entrypoint=signature):
                self.assertIn(
                    "if (context_shutdown_in_progress_)",
                    _body_after_signature(self.indexed_db_bucket_context, signature),
                )
        for token in (
            "bool StoragePartitionImpl::ShutdownIndexedDBForWasmTest(",
            "if (!indexed_db_control_wrapper_)",
            "Mojo disconnect",
        ):
            with self.subTest(storage_partition_close_token=token):
                self.assertIn(token, self.storage_partition_impl_source)
        for token in (
            "partition_->GetCookieManagerForBrowserProcess();",
            "cookie_manager->CloneInterface(",
            'EmitMarker("PERSISTENT_COOKIE_WRITE_ACCEPTED");',
            "FlushCookieStore(",
            'EmitMarker("PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED");',
            "VerifyPersistentCookieStoreReadbackForTesting(",
            "OnCookieStoreReadback",
            'EmitMarker("PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK");',
            "CloseCookieStoreForTesting(",
            'EmitMarker("PERSISTENT_COOKIE_STORE_CLOSED");',
            "SEQUENCE_CHECKER(cookie_sequence_checker_);",
            "DCHECK_CALLED_ON_VALID_SEQUENCE(cookie_sequence_checker_);",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.shutdown_probe)
        # The Chrome-side probe must not open its own SQLite handle.  The
        # selected NetworkContext owns the database and its sequence/crypto
        # state, so the probe can only ask CookieManager for this test seam.
        for token in (
            "base::ThreadPool",
            "sql::Database",
            "HasPersistentCookieDatabaseRecord",
            "OnCookieDatabaseReadback",
            "PERSISTENT_COOKIE_DATABASE_READBACK_OK",
        ):
            with self.subTest(unsafe_probe_token=token):
                self.assertNotIn(token, self.shutdown_probe)
        cookie_set_body = _body_after_signature(
            self.shutdown_probe,
            "  void OnCookieSet(net::CookieAccessResult access_result)",
        )
        cookie_flushed_body = _body_after_signature(
            self.shutdown_probe, "  void OnCookieFlushed()"
        )
        cookie_closed_body = _body_after_signature(
            self.shutdown_probe, "  void OnCookieStoreClosed(bool success)"
        )
        cookie_readback_body = _body_after_signature(
            self.shutdown_probe, "  void OnCookieStoreReadback(bool success)"
        )
        self.assertLess(
            cookie_set_body.index('EmitMarker("PERSISTENT_COOKIE_WRITE_ACCEPTED");'),
            cookie_set_body.index("FlushCookieStore("),
        )
        self.assertLess(
            cookie_flushed_body.index(
                'EmitMarker("PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED");'
            ),
            cookie_flushed_body.index(
                "VerifyPersistentCookieStoreReadbackForTesting("
            ),
        )
        self.assertNotIn("CloseCookieStoreForTesting(", cookie_flushed_body)
        self.assertLess(
            cookie_readback_body.index(
                'EmitMarker("PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK");'
            ),
            cookie_readback_body.index("CloseCookieStoreForTesting("),
        )
        self.assertNotIn("CompleteCookiePhase(", cookie_readback_body)
        self.assertLess(
            cookie_closed_body.index('EmitMarker("PERSISTENT_COOKIE_STORE_CLOSED");'),
            cookie_closed_body.index("CompleteCookiePhase(/*success=*/true);"),
        )
        self.assertIn("ConsumeCookieOperationReply()", cookie_closed_body)

        # The readback is intentionally owned by the Network service.  The
        # Mojo entry point rejects nonpersistent CookieManagers, the session
        # wrapper rejects absent/closed persistent stores, and the SQLite
        # store reads its already-open backend on that backend's own sequence.
        for token in (
            "VerifyPersistentCookieStoreReadbackForTesting(",
            "persistent SQLite backend",
            "FlushCookieStore()",
            "CloseCookieStoreForTesting()",
        ):
            with self.subTest(cookie_manager_mojom_token=token):
                self.assertIn(token, self.cookie_manager_mojom)

        cookie_manager_readback = _body_after_signature(
            self.cookie_manager,
            "void CookieManager::VerifyPersistentCookieStoreReadbackForTesting(",
        )
        for token in (
            "if (!session_cleanup_cookie_store_)",
            "std::move(callback).Run(false);",
            "session_cleanup_cookie_store_->VerifyPersistentCookieStoreReadbackForTesting(",
        ):
            with self.subTest(cookie_manager_readback_token=token):
                self.assertIn(token, cookie_manager_readback)

        session_cleanup_readback = _body_after_signature(
            self.session_cleanup_cookie_store,
            "void SessionCleanupCookieStore::VerifyPersistentCookieStoreReadbackForTesting(",
        )
        for token in (
            "!persistent_store_",
            "persistent_store_closed_for_testing_",
            "!expected_cookie.IsPersistent()",
            "std::move(callback).Run(false);",
            "persistent_store_->VerifyCookiePersistedForTesting(",
        ):
            with self.subTest(session_cleanup_readback_token=token):
                self.assertIn(token, session_cleanup_readback)

        sqlite_store_readback = _body_after_signature(
            self.sqlite_persistent_cookie_store,
            "void SQLitePersistentCookieStore::VerifyCookiePersistedForTesting(",
        )
        self.assertIn(
            "backend_->VerifyCookiePersistedForTesting(", sqlite_store_readback
        )
        sqlite_backend_readback = _body_after_signature(
            self.sqlite_persistent_cookie_store,
            "void SQLitePersistentCookieStore::Backend::VerifyCookiePersistedForTesting(",
        )
        for token in (
            "background_task_runner()->PostTask(",
            "VerifyCookiePersistedInBackground",
        ):
            with self.subTest(sqlite_backend_readback_token=token):
                self.assertIn(token, sqlite_backend_readback)
        sqlite_background_readback = _body_after_signature(
            self.sqlite_persistent_cookie_store,
            "void SQLitePersistentCookieStore::Backend::VerifyCookiePersistedInBackground(",
        )
        for token in (
            "db()",
            "MakeCookiesFromSQLStatement(",
            "MatchesPersistentCookieReadback(",
            "PostClientTask(",
        ):
            with self.subTest(sqlite_background_readback_token=token):
                self.assertIn(token, sqlite_background_readback)
        self.assertIn(
            "VerifyCookiePersistedForTestingReadsCommittedRow",
            self.sqlite_persistent_cookie_store_unit,
        )

        self.assertIn(
            "IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(",
            self.shutdown_probe_unit,
        )
        self.assertIn(
            "IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(",
            self.shutdown_probe_header,
        )
        self.assertIn(
            "RequiresAllThreeSelectedOwnerCloseReceiptsAndCacheAPIOperation",
            self.shutdown_probe_unit,
        )
        selected_owner_predicate = _body_after_signature(
            self.shutdown_probe,
            "bool IsWasmPersistentDefaultPartitionSelectedOwnerReceiptWitness(",
        )
        for token in (
            "local_storage_receipt_started",
            "local_storage_on_disk_commit_and_close_acknowledged",
            "renderer_default_partition_config_reuse_witness",
            "indexed_db_renderer_write_and_close_acknowledged",
            "cache_api_renderer_write_and_readback_acknowledged",
            "cache_api_selected_backend_close_and_index_replacement_acknowledged",
            "IsWasmPersistentDefaultPartitionCookieStoreReceiptWitness(",
        ):
            with self.subTest(selected_owner_predicate_token=token):
                self.assertIn(token, selected_owner_predicate)

        for token in (
            "SealStoragePartitionCreationForShutdown();",
            "IsStoragePartitionCreationSealedForShutdown()",
            "content::StoragePartitionConfig::Create(",
            '"wasmshutdownprobe", "late-partition"',
            "GetStoragePartition(late_partition_config,",
            "/*can_create=*/true",
            "browser_context->GetLoadedStoragePartitionCount() != 1u",
            'EmitMarker("PARTITION_CREATION_SEALED");',
            'EmitMarker("LATE_PARTITION_CREATION_REJECTED");',
            "HasStoragePartitionMap()",
            "IsWasmPersistentDefaultPartitionMapDropped(",
            'EmitMarker("PARTITION_MAP_DROPPED");',
            "return !has_partition_map && loaded_partition_count == 0u;",
            "CanUseFailureRetirement() const",
            'EmitMarker("FAIL_CLOSED_RETIREMENT");',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.shutdown_probe)
        self.assertLess(
            self.shutdown_probe.index('EmitMarker("PARTITION_CREATION_SEALED");'),
            self.shutdown_probe.index(
                "content::StoragePartitionConfig::Create("
            ),
        )
        self.assertLess(
            self.shutdown_probe.index(
                "content::StoragePartitionConfig::Create("
            ),
            self.shutdown_probe.index(
                'EmitMarker("LATE_PARTITION_CREATION_REJECTED");'
            ),
        )
        self.assertLess(
            self.shutdown_probe.index(
                'EmitMarker("LATE_PARTITION_CREATION_REJECTED");'
            ),
            self.shutdown_probe.index('EmitMarker("PARTITION_MAP_DROPPED");'),
        )

        # The subsequent structural gates require all three selected owner
        # receipts, not merely the Cookies SQLite receipt.
        for signature in (
            "  void NotifyCreationSealed(content::BrowserContext* browser_context)",
            "  void NotifyMapDropped(content::BrowserContext* browser_context)",
            "  void NotifyPartitionDestroyNotification()",
            "  bool CanUseFailureRetirement() const",
        ):
            with self.subTest(selected_owner_gate=signature):
                self.assertIn(
                    "HasSelectedOwnerReceiptWitness()",
                    _body_after_signature(self.shutdown_probe, signature),
                )

        for token in (
            "ArmWasmStoragePartitionShutdownNotificationForTest(",
            "NotifyPartitionDestroyNotification",
            "IsWasmPersistentDefaultPartitionShutdownNotificationWitness(",
            "DidWasmStoragePartitionShutdownNotificationForTest()",
            'EmitMarker("PARTITION_DESTROY_NOTIFICATION_DISPATCHED");',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.shutdown_probe)
        self.assertLess(
            shutdown_run.index(
                "ArmWasmStoragePartitionShutdownNotificationForTest("
            ),
            shutdown_run.index('EmitMarker("DEFAULT_PARTITION_CREATED");'),
        )
        map_drop_body = _body_after_signature(
            self.shutdown_probe,
            "  void NotifyMapDropped(content::BrowserContext* browser_context)",
        )
        self.assertIn(
            "IsWasmPersistentDefaultPartitionShutdownNotificationWitness(",
            map_drop_body,
        )
        notification_body = _body_after_signature(
            self.shutdown_probe,
            "  void NotifyPartitionDestroyNotification()",
        )
        self.assertIn(
            "content::DidWasmStoragePartitionShutdownNotificationForTest()",
            notification_body,
        )
        self.assertIn(
            'EmitMarker("PARTITION_DESTROY_NOTIFICATION_DISPATCHED");',
            notification_body,
        )
        self.assertIn(
            "RequiresTheExactNotificationBeforeMapDrop", self.shutdown_probe_unit
        )
        self.assertIn(
            "IsWasmPersistentDefaultPartitionShutdownNotificationWitness(",
            self.shutdown_probe_unit,
        )

        for token in (
            "CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE=1",
            "CHROME_WASM_M7_LOCAL_STORAGE_CLOSE_FENCE_TEST=1",
            "wasm_storage_partition_shutdown_test_support.cc",
            "wasm_storage_partition_shutdown_test_support.h",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.content_browser_build)
        for token in (
            'config("wasm_m7_persistent_default_partition_shutdown_probe")',
            "wasm_storage_partition_shutdown_test_support.h",
            "public_configs = []",
            "public_configs += [",
            '":wasm_m7_persistent_default_partition_shutdown_probe",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.content_public_browser_build)
        for token in (
            "ArmWasmStoragePartitionShutdownNotificationForTest(",
            "DidWasmStoragePartitionShutdownNotificationForTest();",
            "CancelWasmStoragePartitionShutdownNotificationForTest();",
            "ShutdownWasmStoragePartitionIndexedDBForTest(",
            "StoragePartitionImpl::OnBrowserContextWillBeDestroyed()",
            "not an asynchronous service",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.shutdown_notification_public_header)
        for token in (
            "raw_ptr<StoragePartition> expected_partition_",
            "DCHECK_CURRENTLY_ON(BrowserThread::UI);",
            "partition != expected_partition_",
            "notification_returned_ = true;",
            "std::move(on_notification_returned_).Run();",
            "void Cancel()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.shutdown_notification_support)
        self.assertLess(
            self.shutdown_notification_support.index(
                "notification_returned_ = true;"
            ),
            self.shutdown_notification_support.index(
                "std::move(on_notification_returned_).Run();"
            ),
        )
        report_failure_body = _body_after_signature(
            self.shutdown_probe,
            "  void ReportFailure(\n"
            "      WasmPersistentDefaultPartitionShutdownProbeFailureStage stage)",
        )
        self.assertIn(
            "CancelWasmStoragePartitionShutdownNotificationForTest();",
            report_failure_body,
        )
        for token in (
            "local_storage_participant_->Cancel();",
            "local_storage_participant_->QuarantineForFailureShutdown();",
            "local_storage_operation_timeout_.Stop();",
            "indexed_db_participant_->Cancel();",
            "indexed_db_participant_->QuarantineForFailureShutdown();",
            "indexed_db_operation_timeout_.Stop();",
            "ClearProfileBoundPointers();",
        ):
            with self.subTest(report_failure_local_storage_token=token):
                self.assertIn(token, report_failure_body)
        selected_owner_handoff = _body_after_signature(
            self.shutdown_probe,
            "  void ScheduleSelectedOwnerReceiptsCompletion(bool success)",
        )
        for token in (
            "ClearProfileBoundPointers();",
            "DeliverSelectedOwnerReceiptsCompletion",
            "PostTask(",
        ):
            with self.subTest(selected_owner_handoff_token=token):
                self.assertIn(token, selected_owner_handoff)
        clear_profile_bound_pointers = _body_after_signature(
            self.shutdown_probe, "  void ClearProfileBoundPointers()"
        )
        self.assertIn("partition_ = nullptr;", clear_profile_bound_pointers)
        self.assertIn("browser_context_ = nullptr;", clear_profile_bound_pointers)
        self.assertLess(
            selected_owner_handoff.index("ClearProfileBoundPointers();"),
            selected_owner_handoff.index("PostTask("),
        )

        content_notification = _body_after_signature(
            self.browser_context_impl_source,
            "void NotifyContextWillBeDestroyed(StoragePartition* partition)",
        )
        self.assertIn(
            "->OnBrowserContextWillBeDestroyed();", content_notification
        )
        self.assertIn(
            "internal::NotifyWasmStoragePartitionShutdownNotificationReturnedForTest(",
            content_notification,
        )
        self.assertLess(
            content_notification.index("->OnBrowserContextWillBeDestroyed();"),
            content_notification.index(
                "internal::NotifyWasmStoragePartitionShutdownNotificationReturnedForTest("
            ),
        )

        for token in (
            "bool HasStoragePartitionMap();",
            "void SealStoragePartitionCreationForShutdown();",
            "bool IsStoragePartitionCreationSealedForShutdown();",
            "This does not change explicit map-maintenance APIs.",
            "callers must not continue to require the default partition.",
            "has sealed creation and released the partition map, this can return",
            "nullptr.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.browser_context_header)
        self.assertIn(
            "remains only an instantaneous map-drop observation.",
            self.shutdown_probe_header,
        )
        for token in (
            "DCHECK_CURRENTLY_ON(BrowserThread::UI);",
            "if (impl()->IsStoragePartitionCreationSealedForShutdown())",
            "impl()->storage_partition_map()",
            "/*can_create=*/false",
            "bool BrowserContext::HasStoragePartitionMap()",
            "void BrowserContext::SealStoragePartitionCreationForShutdown()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.browser_context)
        for signature in (
            "StoragePartition* BrowserContext::GetStoragePartition(\n"
            "    const StoragePartitionConfig& storage_partition_config,",
            "bool BrowserContext::HasStoragePartitionMap()",
            "void BrowserContext::SealStoragePartitionCreationForShutdown()",
            "bool BrowserContext::IsStoragePartitionCreationSealedForShutdown()",
        ):
            with self.subTest(signature=signature):
                self.assertIn(
                    "DCHECK_CURRENTLY_ON(BrowserThread::UI);",
                    _body_after_signature(self.browser_context, signature),
                )
        self.assertIn(
            "bool storage_partition_creation_sealed_for_shutdown_ = false;",
            self.browser_context_impl,
        )

        for token in (
            "BrowserContextStoragePartitionCreationSeal",
            "SealStoragePartitionCreationForShutdown();",
            "GetStoragePartition(default_config,",
            "/*can_create=*/true",
            '"late-partition"',
            "GetLoadedStoragePartitionCount()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.storage_partition_map_unit)

        profile_policy = _body_after_signature(
            self.profile,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn(
            "RecordWasmPersistentDefaultPartitionShutdownProbePolicyQuery(this);",
            profile_policy,
        )
        self.assertIn("return false;", profile_policy)

        # The shutdown artifact's non-memory default partition has no implicit
        # Cookies path. This distinct client branch must configure exactly its
        # Default/Network/Cookies SQLite file and stay source-selected.
        for token in (
            "CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE",
            "!context || in_memory || !relative_partition_path.empty()",
            "network_context_params->file_paths",
            "profile_path.AppendASCII(kWasmNetworkDataDirectory)",
            'base::FilePath(FILE_PATH_LITERAL("Cookies"))',
            "enable_encrypted_cookies = false",
            "persist_session_cookies = false",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.content_browser_client)
        shutdown_probe_target = _body_after_signature(
            self.wasm_browser_build,
            'source_set("wasm_profile_persistent_default_partition_shutdown_probe")',
        )
        self.assertNotIn('"//sql",', shutdown_probe_target)
        content_browser_client_target = _body_after_signature(
            self.wasm_browser_build, 'source_set("wasm_content_browser_client")'
        )
        for token in (
            '":wasm_profile_m7_persistent_default_partition_shutdown_probe_config",',
            '"//services/network/public/mojom",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, content_browser_client_target)

        pre_main = _body_after_signature(
            self.main_parts, "int WasmBrowserMainParts::PreMainMessageLoopRun()"
        )
        shutdown_branch = pre_main.index(
            "#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)"
        )
        self.assertIn(
            "RunWasmPersistentDefaultPartitionShutdownProbe(",
            pre_main[shutdown_branch:],
        )
        self.assertIn(
            "OnWasmPersistentDefaultPartitionShutdownProbeSelectedOwnerReceiptsClosed",
            pre_main[shutdown_branch:],
        )
        selected_owner_close_callback = _body_after_signature(
            self.main_parts,
            "void WasmBrowserMainParts::\n"
            "    OnWasmPersistentDefaultPartitionShutdownProbe"
            "SelectedOwnerReceiptsClosed(",
        )
        self.assertIn("RequestShutdown();", selected_owner_close_callback)

        finish_shutdown = _body_after_signature(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        creation_sealed = finish_shutdown.index(
            "NotifyWasmPersistentDefaultPartitionShutdownProbeCreationSealed("
        )
        profile_shutdown = finish_shutdown.index("profile_->Shutdown();")
        map_dropped = finish_shutdown.index(
            "NotifyWasmPersistentDefaultPartitionShutdownProbeMapDropped("
        )
        prefs_fence = finish_shutdown.index(
            "NotifyWasmPersistentDefaultPartitionShutdownProbePrefsFenceResult("
        )
        self.assertLess(creation_sealed, profile_shutdown)
        self.assertLess(profile_shutdown, map_dropped)
        self.assertLess(map_dropped, prefs_fence)
        shutdown_retirement_start = finish_shutdown.index(
            "#elif defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)"
        )
        shutdown_retirement = finish_shutdown[
            shutdown_retirement_start : finish_shutdown.index(
                "#else", shutdown_retirement_start
            )
        ]
        self.assertIn(
            "NotifyWasmProfileStorageProfileShutdownFailClosed()",
            shutdown_retirement,
        )
        self.assertNotIn(
            "NotifyWasmProfileStorageProfileShutdown()",
            shutdown_retirement,
        )

        for token in (
            "persistent_default_partition_shutdown_probe_requested",
            "persistent_default_partition_shutdown_probe_enabled",
            "NotifyWasmPersistentDefaultPartitionShutdownProbeFailureRetirement(\n"
            "        IsWasmM7ProfileFailureRetirement(drain_result));",
            "DidWasmPersistentDefaultPartitionShutdownProbeComplete()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.chrome_main)
        self.assertIn(
            "wasm-persistent-default-partition-shutdown-probe",
            self.shutdown_probe,
        )
        self.assertLess(
            self.chrome_main.index(
                "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED"
            ),
            self.chrome_main.index(
                "NotifyWasmPersistentDefaultPartitionShutdownProbeFailureRetirement("
            ),
        )

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

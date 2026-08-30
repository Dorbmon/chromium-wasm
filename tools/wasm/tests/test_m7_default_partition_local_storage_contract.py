#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the isolated M7 default-partition LocalStorage test."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


_FLAG = "enable_chromium_wasm_m7_default_partition_local_storage_test"
_MACRO = "CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST"


def _body_after_marker(text: str, marker: str) -> str:
    """Returns one balanced C++ or GN body beginning after ``marker``."""

    start = text.index(marker)
    opening_brace = text.index("{", start)
    depth = 0
    index = opening_brace
    while index < len(text):
        character = text[index]
        if character == "#":
            newline = text.find("\n", index + 1)
            index = len(text) if newline < 0 else newline + 1
            continue
        if character == "/" and index + 1 < len(text):
            if text[index + 1] == "/":
                newline = text.find("\n", index + 2)
                index = len(text) if newline < 0 else newline + 1
                continue
            if text[index + 1] == "*":
                comment_end = text.find("*/", index + 2)
                if comment_end < 0:
                    raise AssertionError(f"missing comment terminator after {marker}")
                index = comment_end + 2
                continue
        if character in ('"', "'"):
            quote = character
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                elif text[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1 : index]
        index += 1
    raise AssertionError(f"missing closing brace for {marker}")


def _positions(text: str, token: str) -> list[int]:
    positions = []
    start = 0
    while True:
        position = text.find(token, start)
        if position < 0:
            return positions
        positions.append(position)
        start = position + len(token)


class M7DefaultPartitionLocalStorageContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wasm_args = source("build/config/wasm.gni")
        self.local_storage_gni = source(
            "chrome/browser/wasm/wasm_profile_local_storage_smoke.gni"
        )
        self.shutdown_fence_diagnostic_gni = source(
            "chrome/browser/wasm/wasm_profile_shutdown_fence_failure_diagnostic.gni"
        )
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_browser_build = source("chrome/browser/wasm/BUILD.gn")
        self.content_browser_build = source("content/browser/BUILD.gn")
        self.storage_build = source("components/services/storage/BUILD.gn")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.wasm_profile_header = source(
            "chrome/browser/wasm/wasm_profile.h"
        )
        self.wasm_profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.local_storage_smoke_header = source(
            "chrome/browser/wasm/wasm_profile_local_storage_smoke.h"
        )
        self.dom_storage = source(
            "content/browser/dom_storage/dom_storage_context_wrapper.cc"
        )
        self.local_storage_smoke = source(
            "chrome/browser/wasm/wasm_profile_local_storage_smoke.cc"
        )
        self.close_receipt_lifetime_header = source(
            "chrome/browser/wasm/"
            "wasm_profile_local_storage_close_receipt_lifetime.h"
        )
        self.close_receipt_lifetime = source(
            "chrome/browser/wasm/"
            "wasm_profile_local_storage_close_receipt_lifetime.cc"
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
        self.local_storage_test_api = source(
            "components/services/storage/public/mojom/wasm_local_storage_test_api.mojom"
        )
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")

    def test_dedicated_gn_flag_and_artifact_are_isolated(self) -> None:
        args = _body_after_marker(self.wasm_args, "declare_args()")
        self.assertIn(f"{_FLAG} = false", args)
        default_toolchain_guard = _body_after_marker(
            self.wasm_args, "if (current_toolchain == default_toolchain)"
        )
        self.assertIn(
            f"assert(!{_FLAG} ||", default_toolchain_guard
        )
        self.assertIn("is_wasm && enable_chromium_wasm_chrome", default_toolchain_guard)

        artifact_gate = _body_after_marker(
            self.local_storage_gni, f"if ({_FLAG})"
        )
        self.assertIn('get_path_info(root_out_dir, "name")', artifact_gate)
        self.assertIn(
            '"wasm-chrome-m7-default-partition-local-storage"', artifact_gate
        )

        self.assertIn(
            "!(enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic &&\n"
            "      enable_chromium_wasm_m7_default_partition_local_storage_test)",
            self.shutdown_fence_diagnostic_gni,
        )

        chrome_wasm = _body_after_marker(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        selected_artifact = _body_after_marker(chrome_wasm, f"if ({_FLAG})")
        for expected in (
            'output_name = "chrome_wasm_m7_default_partition_local_storage_test"',
            f'defines = [ "{_MACRO}=1" ]',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, selected_artifact)

        selected_smoke = _body_after_marker(
            self.wasm_browser_build,
            'source_set("wasm_profile_local_storage_smoke")',
        )
        for expected in (
            '"wasm_profile_local_storage_smoke.cc"',
            '"wasm_profile_renderer_local_storage_ui.cc"',
            '":wasm_profile_local_storage_close_receipt_lifetime",',
            f'defines = [ "{_MACRO}=1" ]',
            '"//components/services/storage/public/mojom:wasm_local_storage_test_api",',
            'public_deps = [ "//content/public/browser" ]',
            '"//third_party/blink/public/mojom:mojom_platform",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, selected_smoke)

        profile_layout_config = _body_after_marker(
            self.wasm_browser_build,
            'config("wasm_profile_m7_local_storage_smoke_config")',
        )
        self.assertIn(f'defines = [ "{_MACRO}=1" ]', profile_layout_config)
        profile_target = _body_after_marker(
            self.wasm_browser_build, 'source_set("wasm_profile")'
        )
        profile_gate = _body_after_marker(profile_target, f"if ({_FLAG})")
        self.assertIn(
            'public_configs = [ ":wasm_profile_m7_local_storage_smoke_config" ]',
            profile_gate,
        )
        self.assertIn(
            'deps += [ ":wasm_profile_local_storage_smoke" ]', profile_gate
        )
        self.assertNotIn('":wasm_profile"', selected_smoke)
        self.assertNotIn('"wasm_profile.cc"', selected_smoke)

        close_receipt_target = _body_after_marker(
            self.wasm_browser_build,
            'source_set("wasm_profile_local_storage_close_receipt_lifetime")',
        )
        for expected in (
            'public = [ "wasm_profile_local_storage_close_receipt_lifetime.h" ]',
            'sources = [ "wasm_profile_local_storage_close_receipt_lifetime.cc" ]',
            'public_deps = [ ":wasm_profile_ordered_drain_lifecycle" ]',
            'deps = [ "//base" ]',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, close_receipt_target)
        for forbidden in (
            "//chrome/browser/profiles",
            "//content",
            "//mojo",
            "//components/services/storage",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, close_receipt_target)
        self.assertEqual(close_receipt_target.count('"//'), 1)

        close_receipt_test = _body_after_marker(
            self.wasm_browser_build,
            'test("wasm_profile_local_storage_close_receipt_lifetime_unittests")',
        )
        for expected in (
            '"wasm_profile_local_storage_close_receipt_lifetime_unittest.cc",',
            '":wasm_profile_local_storage_close_receipt_lifetime",',
            '":wasm_profile_ordered_drain_lifecycle",',
            '"//base/test:run_all_unittests",',
            '"//base/test:test_support",',
            '"//testing/gtest",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, close_receipt_test)

        smoke_target_start = self.wasm_browser_build.index(
            'source_set("wasm_profile_local_storage_smoke")'
        )
        smoke_gate_start = self.wasm_browser_build.rfind(
            f"if ({_FLAG})", 0, smoke_target_start
        )
        self.assertGreaterEqual(smoke_gate_start, 0)
        smoke_gate = _body_after_marker(
            self.wasm_browser_build[smoke_gate_start:], f"if ({_FLAG})"
        )
        self.assertIn(
            'source_set("wasm_profile_local_storage_smoke")', smoke_gate
        )

        content_browser = _body_after_marker(
            self.content_browser_build, 'source_set("browser")'
        )
        content_gate = _body_after_marker(content_browser, f"if ({_FLAG})")
        for expected in (
            f'defines += [ "{_MACRO}=1" ]',
            '"dom_storage/wasm_dom_storage_test_support.cc",',
            '"//components/services/storage/public/mojom:wasm_local_storage_test_api",',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, content_gate)

        storage_target = _body_after_marker(
            self.storage_build, 'source_set("storage")'
        )
        storage_gate = _body_after_marker(storage_target, f"if ({_FLAG})")
        self.assertIn("public_deps += [", storage_gate)
        self.assertIn(
            '"//components/services/storage/public/mojom:'
            'wasm_local_storage_test_api",',
            storage_gate,
        )

    def test_normal_wasm_default_partition_remains_in_memory(self) -> None:
        default_policy = _body_after_marker(
            self.wasm_profile,
            "bool WasmProfile::ShouldUseInMemoryDefaultStoragePartition()",
        )
        self.assertIn("return true;", default_policy)
        self.assertNotIn(_MACRO, default_policy)

        local_path = _body_after_marker(
            self.dom_storage,
            "std::optional<base::FilePath> GetLocalStoragePath(",
        )
        test_path_branch = local_path.split(f"#if defined({_MACRO})", 1)[1]
        normal_wasm_path_branch = test_path_branch.split("#else", 1)[1]
        self.assertIn("static_cast<void>(partition);", normal_wasm_path_branch)
        self.assertIn("return std::nullopt;", normal_wasm_path_branch)

        session_path = _body_after_marker(
            self.dom_storage,
            "std::optional<base::FilePath> GetSessionStoragePath(",
        )
        self.assertIn("#if BUILDFLAG(IS_WASM)", session_path)
        self.assertIn("return std::nullopt;", session_path)
        self.assertNotIn(_MACRO, session_path)

    def test_selected_local_storage_uses_real_mojo_storage_area_not_javascript(
        self,
    ) -> None:
        start = _body_after_marker(
            self.local_storage_smoke,
            "bool Start(base::OnceCallback<void(bool)> completion)",
        )
        for expected in (
            "browser_context_->GetDefaultStoragePartition()",
            "storage_partition->GetDOMStorageContext()",
            "content::BindWasmLocalStorageTestApi(",
            "storage_partition->GetLocalStorageControl()",
            "local_storage_control->BindStorageArea(",
            "storage_area_.BindNewPipeAndPassReceiver()",
            "test_api_.BindNewPipeAndPassReceiver()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, start)

        put = _body_after_marker(
            self.local_storage_smoke, "void PutTokenForWrite()"
        )
        read = _body_after_marker(
            self.local_storage_smoke, "void ReadTokenForVerify()"
        )
        self.assertIn("storage_area_->Put(", put)
        self.assertIn("storage_area_->GetAll(", read)
        for body in (start, put, read):
            for forbidden in ("EM_JS", "EM_ASM", "emscripten::", "ccall"):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, body)

    def test_profile_owns_local_storage_state_and_consumes_input_before_io(
        self,
    ) -> None:
        participant = _body_after_marker(
            self.local_storage_smoke_header,
            "class WasmProfileLocalStorageLifetimeParticipant",
        )
        for expected in (
            "content::BrowserContext* browser_context",
            "WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold",
            "bool Start(base::OnceCallback<void(bool success)> completion);",
            "void Cancel();",
            "bool QuarantineForFailureShutdown();",
            "bool IsActive() const;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, participant)
        self.assertNotIn("WasmProfile*", participant)
        self.assertNotIn("wasm_profile.h", self.local_storage_smoke_header)
        self.assertNotIn("wasm_profile.h", self.local_storage_smoke)
        self.assertIn(
            "raw_ptr<content::BrowserContext> browser_context_ = nullptr;",
            self.local_storage_smoke,
        )
        self.assertIn(
            "WasmProfileLocalStorageCloseReceiptLifetime "
            "close_receipt_lifetime_;",
            self.local_storage_smoke,
        )
        self.assertNotIn("raw_ptr<WasmProfile>", self.local_storage_smoke)
        self.assertIn(
            "std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>\n"
            "      profile_io_hold_;",
            self.close_receipt_lifetime_header,
        )

        protocol = _body_after_marker(
            self.local_storage_smoke,
            "class WasmProfileLocalStorageProtocolState",
        )
        for profile_bound_state in (
            "raw_ptr",
            "BrowserContext",
            "ProfileIOHold",
            "WebContents",
            "mojo::Remote",
            "profile_path",
        ):
            with self.subTest(profile_bound_state=profile_bound_state):
                self.assertNotIn(profile_bound_state, protocol)

        self.assertIn(
            "std::unique_ptr<chrome::WasmProfileLocalStorageLifetimeParticipant>\n"
            "      local_storage_lifetime_participant_;",
            self.wasm_profile_header,
        )
        profile_start = _body_after_marker(
            self.wasm_profile, "bool WasmProfile::StartLocalStorageSmoke("
        )
        self.assertIn(
            "local_storage_lifetime_participant_ = std::make_unique<",
            profile_start,
        )
        self.assertIn("this, profile_path_", profile_start)
        self.assertIn(
            "local_storage_lifetime_participant_->Start(std::move(completion))",
            profile_start,
        )

        protocol_take = _body_after_marker(
            self.local_storage_smoke,
            "std::optional<WasmProfileLocalStorageSmokeInput> TakeInput()",
        )
        self.assertIn("input_taken_", protocol_take)
        self.assertIn("input_taken_ = true;", protocol_take)
        self.assertIn("result.token = std::move(input_.token);", protocol_take)
        self.assertIn("result.token_digest = input_.token_digest;", protocol_take)
        self.assertNotIn("std::move(input_.token_digest)", protocol_take)

        startup = _body_after_marker(
            self.main_parts, "int WasmBrowserMainParts::PreMainMessageLoopRun()"
        )
        take = startup.index("chrome::TakeWasmProfileLocalStorageSmokeInput()")
        acquire = startup.index("chrome::TryAcquireWasmProfileStorageProfileIO()", take)
        transfer = startup.index("profile_->StartLocalStorageSmoke(", acquire)
        self.assertLess(take, acquire)
        self.assertLess(acquire, transfer)
        self.assertIn("std::move(*local_storage_input)", startup[transfer:])
        self.assertIn("std::move(*profile_io_hold)", startup[transfer:])

    def test_close_result_is_deferred_and_pre_receipt_failure_is_quarantined(
        self,
    ) -> None:
        close_ready = _body_after_marker(
            self.local_storage_smoke, "void OnCloseFenceReady("
        )
        close_receipt = close_ready.index("close_succeeded_ = true;")
        complete = close_ready.index(
            "close_receipt_lifetime_.CompleteAfterExactCloseReceipt("
        )
        self.assertLess(close_receipt, complete)
        self.assertIn('EmitDigestMarker("DB_CLOSE_OK")', close_ready)
        self.assertIn("CleanupProfileBoundResources", close_ready[complete:])

        complete_after_receipt = _body_after_marker(
            self.close_receipt_lifetime,
            "CompleteAfterExactCloseReceipt(base::OnceClosure cleanup)",
        )
        mark_receipt = complete_after_receipt.index(
            "exact_close_receipt_received_ = true;"
        )
        cleanup = complete_after_receipt.index("std::move(cleanup).Run();")
        post = complete_after_receipt.index("PostTask(")
        deliver = complete_after_receipt.index("DeliverCloseReceipt", post)
        self.assertLess(mark_receipt, cleanup)
        self.assertLess(cleanup, post)
        self.assertLess(post, deliver)

        cleanup_resources = _body_after_marker(
            self.local_storage_smoke, "void CleanupProfileBoundResources()"
        )
        for cleared_owner in (
            "weak_ptr_factory_.InvalidateWeakPtrs();",
            "Observe(nullptr);",
            "renderer_web_contents_.reset();",
            "storage_area_.reset();",
            "test_api_.reset();",
            "dom_storage_context_ = nullptr;",
            "browser_context_ = nullptr;",
            "profile_path_.clear();",
            "ClearRawToken();",
        ):
            with self.subTest(cleared_owner=cleared_owner):
                self.assertIn(cleared_owner, cleanup_resources)
        self.assertNotIn("PostTask(", cleanup_resources)
        self.assertNotIn("profile_io_hold_", cleanup_resources)

        deliver_receipt = _body_after_marker(
            self.close_receipt_lifetime,
            "void WasmProfileLocalStorageCloseReceiptLifetime::"
            "DeliverCloseReceipt()",
        )
        complete_hold = deliver_receipt.index("profile_io_hold_->Complete(")
        reset_hold = deliver_receipt.index("profile_io_hold_.reset();")
        deliver_owner = deliver_receipt.index(
            "std::move(completion).Run(succeeded);"
        )
        self.assertLess(complete_hold, reset_hold)
        self.assertLess(reset_hold, deliver_owner)
        self.assertIn("!cancel_requested_", deliver_receipt)

        state_start = self.local_storage_smoke.index(
            "class WasmProfileLocalStorageLifetimeParticipant::State"
        )
        state_source = self.local_storage_smoke[state_start:]
        failure = _body_after_marker(state_source, "void ReportFailure(")
        for expected in (
            "ClearRawToken();",
            "close_receipt_lifetime_.FailBeforeExactCloseReceipt(",
            "CleanupProfileBoundResources",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, failure)
        self.assertNotIn("profile_io_hold_->Complete", failure)
        self.assertNotIn("ProfileIOCompletion::", failure)

        fail_before_receipt = _body_after_marker(
            self.close_receipt_lifetime,
            "FailBeforeExactCloseReceipt(base::OnceClosure cleanup)",
        )
        fail_cleanup = fail_before_receipt.index("std::move(cleanup).Run();")
        fail_post = fail_before_receipt.index("PostTask(")
        quarantine_delivery = fail_before_receipt.index(
            "DeliverQuarantineRequest", fail_post
        )
        self.assertLess(fail_cleanup, fail_post)
        self.assertLess(fail_post, quarantine_delivery)
        self.assertIn("cancel_requested_ = true;", fail_before_receipt)
        self.assertNotIn("profile_io_hold_->Complete", fail_before_receipt)
        self.assertNotIn("profile_io_hold_.reset", fail_before_receipt)
        self.assertNotIn("ProfileIOCompletion::", fail_before_receipt)

        controller_quarantine = _body_after_marker(
            self.close_receipt_lifetime,
            "DeliverQuarantineRequest()",
        )
        copy_owner_callback = controller_quarantine.index(
            "base::OnceClosure quarantine_callback ="
        )
        copy_completion_callback = controller_quarantine.index(
            "base::OnceCallback<void(bool)> completion ="
        )
        owner_callback = controller_quarantine.index(
            "std::move(quarantine_callback).Run();"
        )
        completion_callback = controller_quarantine.index(
            "std::move(completion).Run(false);"
        )
        self.assertLess(copy_owner_callback, owner_callback)
        self.assertLess(copy_completion_callback, owner_callback)
        self.assertLess(owner_callback, completion_callback)
        self.assertNotIn("profile_io_hold_->Complete", controller_quarantine)
        self.assertNotIn("profile_io_hold_.reset", controller_quarantine)
        self.assertNotIn("ProfileIOCompletion::", controller_quarantine)

        quarantine = _body_after_marker(
            self.local_storage_smoke,
            "bool WasmProfileLocalStorageLifetimeParticipant::\n"
            "    QuarantineForFailureShutdown()",
        )
        retain = quarantine.index("RetainQuarantinedState(std::move(state_));")
        outstanding = quarantine.index("state_->HasOutstandingAdmission()")
        prepare = quarantine.index("state_->PrepareForOwnerQuarantine()")
        self.assertLess(outstanding, prepare)
        self.assertLess(prepare, retain)
        self.assertNotIn("profile_io_hold_->Complete", quarantine)
        self.assertNotIn("profile_io_hold_.reset", quarantine)
        self.assertNotIn("ProfileIOCompletion::", quarantine)
        owner_quarantine = _body_after_marker(
            self.local_storage_smoke,
            "OnOperationRequiresQuarantine()",
        )
        self.assertIn(
            "RetainQuarantinedState(std::move(state_));", owner_quarantine
        )
        retained_state = _body_after_marker(
            self.local_storage_smoke,
            "void WasmProfileLocalStorageLifetimeParticipant::RetainQuarantinedState(",
        )
        self.assertIn("base::NoDestructor", retained_state)
        self.assertIn(
            "quarantined_states->push_back(std::move(state));", retained_state
        )

    def test_active_operation_gates_every_profile_teardown_path(self) -> None:
        maybe_shutdown = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::MaybeStartShutdown()"
        )
        finish_shutdown = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::FinishShutdown()"
        )
        for body in (maybe_shutdown, finish_shutdown):
            with self.subTest(path="profile teardown gate"):
                active = body.index("profile_->HasActiveLocalStorageSmoke()")
                cancel = body.index("profile_->CancelLocalStorageSmokeForShutdown()")
                early_return = body.index("return;", cancel)
                self.assertLess(active, cancel)
                self.assertLess(cancel, early_return)

        foundation = _body_after_marker(
            self.main_parts, "void WasmBrowserMainParts::ShutdownFoundation()"
        )
        foundation_active = foundation.index(
            "profile_->HasActiveLocalStorageSmoke()"
        )
        foundation_quarantine = foundation.index(
            "profile_->QuarantineLocalStorageSmokeForFailureShutdown()"
        )
        profile_shutdown = foundation.index("profile_->Shutdown();")
        self.assertLess(foundation_active, foundation_quarantine)
        self.assertLess(foundation_quarantine, profile_shutdown)

        destructor = _body_after_marker(
            self.wasm_profile, "WasmProfile::~WasmProfile()"
        )
        owner = destructor.index("if (local_storage_lifetime_participant_)")
        quarantine_owner = destructor.index(
            "QuarantineLocalStorageSmokeForFailureShutdown()"
        )
        shutdown = destructor.index("\n  Shutdown();")
        self.assertLess(owner, quarantine_owner)
        self.assertLess(quarantine_owner, shutdown)

    def test_snapshot_requires_every_area_one_exact_on_disk_committed_map_update(
        self,
    ) -> None:
        snapshot = _body_after_marker(
            self.local_storage_impl,
            "void LocalStorageImpl::RequestImmediateCommitSnapshot(",
        )
        for expected in (
            "storage_keys.reserve(areas_.size());",
            "for (const auto& area : areas_)",
            "snapshot->Initialize(std::move(storage_keys), backing_store);",
            "for (size_t index = 0; index < snapshot->size(); ++index)",
            "RequestImmediateCommitSnapshot(",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, snapshot)

        classify = _body_after_marker(
            self.storage_service,
            "WasmLocalStorageTestResult ClassifyWasmLocalStorageSnapshot(",
        )
        for expected in (
            "snapshot.scope_outcome != ScopeOutcome::kAllAreasReported",
            "snapshot.backing_store != BackingStore::kOnDisk",
            "snapshot.area_results.size() != 1u",
            "const auto& area = snapshot.area_results.front();",
            "area.storage_key != storage_key",
            "area.result.outcome != AreaOutcome::kCommittedMapUpdate",
            "!area.result.status.ok()",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, classify)

    def test_owner_erase_precedes_same_database_runner_fifo_close_receipt(
        self,
    ) -> None:
        prepare = _body_after_marker(
            self.storage_service,
            "void StorageServiceImpl::PrepareCommitCloseFence(",
        )
        for expected in (
            "DomStorageDatabase::GetPath(StorageType::kLocalStorage, profile_path)",
            "GetTaskRunnerForDb(database_path)",
            "std::move(database_task_runner)",
            "storage->RequestImmediateCommitSnapshot(",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, prepare)

        start_close_fence = _body_after_marker(
            self.storage_service,
            "void StorageServiceImpl::MaybeStartWasmLocalStorageCloseFence()",
        )
        storage_removed = start_close_fence.index("if (!fence.storage_removed)")
        post_fifo_noop = start_close_fence.index(
            "fence.database_task_runner->PostTaskAndReply("
        )
        self.assertLess(storage_removed, post_fifo_noop)
        self.assertIn("base::DoNothing()", start_close_fence)
        self.assertIn(
            "OnWasmLocalStorageCloseFenceNoOpComplete", start_close_fence
        )

        remove_owner = _body_after_marker(
            self.storage_service,
            "void StorageServiceImpl::ShutDownAndRemoveLocalStorage(",
        )
        erase_owner = remove_owner.index("local_storages_.erase(it);")
        mark_removed = remove_owner.index(
            "wasm_local_storage_close_fence_->storage_removed = true;"
        )
        start_fifo_close_receipt = remove_owner.index(
            "MaybeStartWasmLocalStorageCloseFence();"
        )
        self.assertLess(erase_owner, mark_removed)
        self.assertLess(mark_removed, start_fifo_close_receipt)

    def test_area_unbind_arm_precedes_control_seal_and_close_receipt(self) -> None:
        prepare_close = _body_after_marker(
            self.local_storage_smoke,
            "void PrepareCloseFence()",
        )
        self.assertIn("!storage_area_", prepare_close)
        self.assertIn("test_api_->PrepareCommitCloseFence(", prepare_close)

        close_prepared = _body_after_marker(
            self.local_storage_smoke,
            "void OnCloseFencePrepared(",
        )
        release = close_prepared.index("ReleaseAreaThenArmCloseFence();")
        self.assertGreaterEqual(release, 0)

        release_area = _body_after_marker(
            self.local_storage_smoke,
            "void ReleaseAreaThenArmCloseFence()",
        )
        reset_area = release_area.index("storage_area_.reset();")
        arm = release_area.index("test_api_->ArmCommitCloseFence(")
        self.assertLess(reset_area, arm)

        close_armed = _body_after_marker(
            self.local_storage_smoke,
            "void OnCloseFenceArmed(",
        )
        seal = close_armed.index("content::SealWasmLocalStorageForTest(")
        wait = close_armed.index("test_api_->WaitForCloseFence(")
        self.assertLess(seal, wait)

        seal_control = _body_after_marker(
            self.dom_storage,
            "bool DOMStorageContextWrapper::SealLocalStorageForWasmProfileTest()",
        )
        set_seal = seal_control.index(
            "local_storage_rebind_sealed_for_wasm_profile_test_ = true;"
        )
        reset_control = seal_control.index("local_storage_control_.reset();")
        self.assertLess(set_seal, reset_control)

        disconnected = _body_after_marker(
            self.dom_storage,
            "void DOMStorageContextWrapper::OnLocalStorageDisconnected()",
        )
        prevent_rebind = disconnected.index(
            "if (local_storage_rebind_sealed_for_wasm_profile_test_)"
        )
        rebind = disconnected.index("MaybeBindLocalStorageControl();")
        self.assertLess(prevent_rebind, rebind)
        self.assertIn("return;", disconnected[prevent_rebind:rebind])

    def test_arm_waits_for_exact_instance_last_area_notification(self) -> None:
        arm = _body_after_marker(
            self.storage_service,
            "void StorageServiceImpl::ArmCommitCloseFence(",
        )
        for expected in (
            "fence.arm_callback = std::move(callback);",
            "Phase::kWaitingForAreaRelease",
            "RunWhenNoStorageAreasBoundForTesting(",
            "OnWasmLocalStorageCloseFenceAreasUnbound",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, arm)
        self.assertNotIn("kStorageAreasStillBound", arm)
        self.assertNotIn("CompleteWasmLocalStorageArmFence(\n        std::move(callback)", arm)

        on_unbound = _body_after_marker(
            self.storage_service,
            "void StorageServiceImpl::OnWasmLocalStorageCloseFenceAreasUnbound(",
        )
        for expected in (
            "generation_it->second != fence.generation",
            "storage_it->second->GetStoragePartitionDirectory()",
            "storage->HasBoundStorageAreasForTesting()",
            "storage->RunWhenNoStorageAreasBoundForTesting(",
            "Phase::kArmedForClose",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, on_unbound)

        holder = _body_after_marker(
            self.local_storage_impl,
            "void OnNoBindings() override",
        )
        self.assertIn("context_->OnStorageAreaNoBindingsForTesting();", holder)
        bind_holder = _body_after_marker(
            self.local_storage_impl,
            "void Bind(mojo::PendingReceiver<blink::mojom::StorageArea> receiver)",
        )
        self.assertIn("context_->OnStorageAreaBoundForTesting();", bind_holder)
        self.assertIn(
            "void RunWhenNoStorageAreasBoundForTesting(base::OnceClosure callback);",
            self.local_storage_impl_header,
        )
        self.assertIn("ArmCommitCloseFence()", self.local_storage_test_api)
        self.assertNotIn("kStorageAreasStillBound", self.local_storage_test_api)

    def test_v4_drain_happens_after_content_main_and_close_lifecycle(self) -> None:
        chrome_main_start = self.chrome_main.index(
            'extern "C" int ChromeMain(int argc, const char** argv)'
        )
        drain = self.chrome_main.index(
            "chrome::DrainAndReleaseWasmProfileStorageBackend()", chrome_main_start
        )
        content_main_calls = _positions(
            self.chrome_main, "content::ContentMain(std::move(params))"
        )
        content_main_calls = [
            call
            for call in content_main_calls
            if chrome_main_start < call < drain
        ]
        self.assertTrue(content_main_calls)
        for content_main in content_main_calls:
            with self.subTest(content_main=content_main):
                self.assertLess(content_main, drain)

        post_drain_end = self.chrome_main.index(
            "const int exit_code = IsNormalChromeMainResult(result)", drain
        )
        post_drain = self.chrome_main[drain:post_drain_end]
        self.assertNotIn("content::ContentMain(std::move(params))", post_drain)
        notify_drain = self.chrome_main.index(
            "chrome::NotifyWasmProfileLocalStorageSmokeBackendDrain(", drain
        )
        self.assertLess(drain, notify_drain)


if __name__ == "__main__":
    unittest.main()

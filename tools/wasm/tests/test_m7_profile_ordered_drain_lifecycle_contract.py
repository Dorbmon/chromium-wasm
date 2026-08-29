#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the narrowly integrated M7 profile-drain control plane."""

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _body_after_signature(text: str, signature: str) -> str:
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


class M7ProfileOrderedDrainLifecycleContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.header = source(
            "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.h"
        )
        self.implementation = source(
            "chrome/browser/wasm/wasm_profile_ordered_drain_lifecycle.cc"
        )
        self.build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_build = source("chrome/BUILD.gn")
        self.chrome_main = source("chrome/app/chrome_main_wasm.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )

    def test_target_is_base_only_and_only_m7_storage_consumes_it(self) -> None:
        target = _body_after_signature(
            self.build, 'source_set("wasm_profile_ordered_drain_lifecycle")'
        )
        self.assertIn('public = [ "wasm_profile_ordered_drain_lifecycle.h" ]', target)
        self.assertIn('sources = [ "wasm_profile_ordered_drain_lifecycle.cc" ]', target)
        self.assertIn('deps = [ "//base" ]', target)
        for forbidden in (
            "wasm_profile_storage",
            "wasmfs",
            "emscripten",
            "//sql",
            "//third_party/leveldatabase",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        storage_target = _body_after_signature(
            self.build, 'source_set("wasm_profile_storage")'
        )
        self.assertIn('":wasm_profile_ordered_drain_lifecycle",', storage_target)
        self.assertIn(
            "TryAcquireWasmProfileStorageProfileIO", self.main_parts
        )
        self.assertIn(
            "WasmProfileOrderedDrainLifecycle::ProfileIOHold", self.main_parts
        )

        profile_target = _body_after_signature(
            self.build, 'source_set("wasm_profile")'
        )
        self.assertIn('":wasm_profile_storage"', profile_target)
        self.assertIn(
            '"CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST=1"', profile_target
        )

        chrome_target = _body_after_signature(
            self.chrome_build, 'executable("chrome_wasm")'
        )
        self.assertNotIn('":wasm_profile_ordered_drain_lifecycle",', chrome_target)

    def test_epoch_never_selects_or_invokes_the_profile_storage_backend(self) -> None:
        for forbidden in (
            "WasmProfileStorageDrainResult",
            "InitializeWasmProfileStorage",
            "DrainAndReleaseWasmProfileStorageBackend",
            "NeedsWasmProfileStorageBackendDrain",
            "wasmfs_",
            "<emscripten/",
            '"/profile"',
            "SequencedTaskRunner",
            "PostTask",
            "OnceCallback",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.header)
                self.assertNotIn(forbidden, self.implementation)

        self.assertIn(
            "class Observation : public base::RefCountedThreadSafe<Observation>",
            self.header,
        )
        self.assertIn("mutable base::Lock lock_;", self.header)
        self.assertNotIn("RefCountedDeleteOnSequence", self.header)
        self.assertNotIn("RefCountedDeleteOnSequence", self.implementation)

    def test_lifetime_outcomes_gate_one_neutral_post_content_permit(self) -> None:
        for token in (
            "uint64_t admitted_operations_ GUARDED_BY(lock_) = 0;",
            "uint64_t active_holds_ GUARDED_BY(lock_) = 0;",
            "uint64_t outstanding_at_begin_ GUARDED_BY(lock_) = 0;",
            "uint64_t succeeded_operations_ GUARDED_BY(lock_) = 0;",
            "uint64_t failed_operations_ GUARDED_BY(lock_) = 0;",
            "uint64_t abandoned_operations_ GUARDED_BY(lock_) = 0;",
            "outstanding_at_begin_ = active_holds_;",
            "++succeeded_operations_;",
            "++failed_operations_;",
            "++abandoned_operations_;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.header + self.implementation)

        quiesce = _body_after_signature(
            self.implementation, "BuildProfileIOQuiesceResultLocked() const"
        )
        self.assertLess(
            quiesce.index("abandoned_operations_ != 0"),
            quiesce.index("failed_operations_ != 0"),
        )
        self.assertLess(
            quiesce.index("failed_operations_ != 0"),
            quiesce.index("succeeded_operations_, admitted_operations_"),
        )

        claim = _body_after_signature(
            self.implementation, "Observation::ClaimPostContentDrain()"
        )
        self.assertIn(
            "if (status_ != Status::kReadyForPostContentDrain)", claim
        )
        self.assertIn("Status::kReadyForPostContentDrain", claim)
        self.assertIn("CHECK(profile_io.Succeeded());", claim)
        self.assertIn("Status::kPostContentDrainPermitClaimed", claim)

        retire = _body_after_signature(
            self.implementation, "RetirePostContentDrainPermit()"
        )
        self.assertIn("Status::kPostContentDrainPermitClaimed", retire)
        self.assertIn("Status::kPostContentDrainPermitRetired", retire)
        self.assertNotIn("kPostContentDrainPermitConsumed", self.header)
        self.assertNotIn("ConsumeForPostContentDrain", self.header)
        self.assertIn(
            "Retirement deliberately does not distinguish a", self.header
        )
        self.assertIn(
            "neither case can be mistaken for a clean release", self.header
        )

        reset = _body_after_signature(
            self.implementation, "PostContentDrainPermit::Reset()"
        )
        self.assertIn("observation->RetirePostContentDrainPermit();", reset)

    def test_nonclean_epoch_issues_one_fail_closed_retirement_permit(self) -> None:
        for token in (
            "class PostContentFailureRetirementPermit",
            "ClaimPostContentFailureRetirement()",
            "kRegisteredProfileIONotClean",
            "kPostContentFailureRetirementPermitClaimed",
            "kPostContentFailureRetirementPermitRetired",
            "RetirePostContentFailureRetirementPermit()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.header + self.implementation)

        claim = _body_after_signature(
            self.implementation,
            "Observation::\n    ClaimPostContentFailureRetirement()",
        )
        for token in (
            "if (status_ != Status::kRegisteredProfileIONotClean)",
            "CHECK(!profile_io.Succeeded());",
            "CHECK_NE(profile_io.status, ProfileIOQuiesceStatus::kWaiting);",
            "Status::kPostContentFailureRetirementPermitClaimed",
        ):
            with self.subTest(token=token):
                self.assertIn(token, claim)

        retire = _body_after_signature(
            self.implementation, "RetirePostContentFailureRetirementPermit()"
        )
        self.assertIn(
            "Status::kPostContentFailureRetirementPermitClaimed", retire
        )
        self.assertIn(
            "Status::kPostContentFailureRetirementPermitRetired", retire
        )

        reset = _body_after_signature(
            self.implementation, "PostContentFailureRetirementPermit::\n    Reset()"
        )
        self.assertIn(
            "observation->RetirePostContentFailureRetirementPermit();", reset
        )


if __name__ == "__main__":
    unittest.main()

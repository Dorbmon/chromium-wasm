#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the unlinked Wasm SessionTabHelper prerequisite."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def _source_set_body(build_file: str, target: str) -> str:
    match = re.search(
        rf'\bsource_set\s*\(\s*"{re.escape(target)}"\s*\)', build_file
    )
    if not match:
        raise AssertionError(f"could not find source set {target!r}")

    opening_brace = build_file.find("{", match.end())
    if opening_brace == -1:
        raise AssertionError(f"source set {target!r} has no opening brace")

    depth = 0
    for index in range(opening_brace, len(build_file)):
        if build_file[index] == "{":
            depth += 1
        elif build_file[index] == "}":
            depth -= 1
            if depth == 0:
                return build_file[opening_brace + 1 : index]
    raise AssertionError(f"source set {target!r} has no closing brace")


class M6WasmSessionTabHelperContractTest(unittest.TestCase):
    def test_uses_the_real_helper_with_a_transient_empty_delegate(self) -> None:
        header = source("chrome/browser/wasm/wasm_session_tab_helper.h")
        implementation = source(
            "chrome/browser/wasm/wasm_session_tab_helper.cc"
        )

        self.assertIn(
            "void EnsureWasmSessionTabHelper(content::WebContents* web_contents);",
            header,
        )
        self.assertIn(
            "SessionID GetWasmSessionTabId(content::WebContents* web_contents);",
            header,
        )
        self.assertIn(
            '#include "components/sessions/content/session_tab_helper.h"',
            implementation,
        )
        self.assertIn("CHECK(web_contents);", implementation)
        self.assertIn(
            "sessions::SessionTabHelper::FromWebContents(web_contents)",
            implementation,
        )
        self.assertIn(
            "sessions::SessionTabHelper::CreateForWebContents(", implementation
        )
        self.assertIn(
            "sessions::SessionTabHelper::DelegateLookup()", implementation
        )
        self.assertIn(
            "SessionTabHelper allocates its real per-session ID", implementation
        )
        self.assertIn("no persistence delegate", implementation)
        self.assertIn("SessionID GetWasmSessionTabId", implementation)
        self.assertIn(
            "EnsureWasmSessionTabHelper must run before querying the tab ID",
            implementation,
        )

        # Creating a duplicate WebContentsUserData object is invalid. The
        # explicit presence check makes this prerequisite safe to call at each
        # tab-core construction seam.
        lookup_index = implementation.index(
            "sessions::SessionTabHelper::FromWebContents(web_contents)"
        )
        create_index = implementation.index(
            "sessions::SessionTabHelper::CreateForWebContents("
        )
        self.assertLess(lookup_index, create_index)

    def test_does_not_select_session_persistence_or_browser_ui(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_session_tab_helper.cc"
        )

        for forbidden in (
            "CreateSessionServiceTabHelper",
            "SessionService",
            "AppSessionService",
            "SessionServiceFactory",
            "Profile",
            "Browser",
            "TabModel",
            "TabStripModel",
            "base::Bind",
            "SessionTabHelperDelegate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_target_is_narrow_and_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_session_tab_helper")

        for entry in (
            '"wasm_session_tab_helper.h"',
            '"wasm_session_tab_helper.cc"',
            '"//components/sessions/content/content_record_password_state.cc",',
            '"//components/sessions/content/content_serialized_navigation_builder.cc",',
            '"//components/sessions/content/content_serialized_navigation_driver.cc",',
            '"//components/sessions/content/navigation_task_id.cc",',
            '"//components/sessions/content/session_tab_helper.cc",',
            '"//components/sessions/core/serialized_navigation_entry.cc",',
            '"//components/sessions/core/serialized_user_agent_override.cc",',
            '"//base",',
            '"//components/sessions:session_id",',
            '"//content/public/browser",',
            '"//content/public/common",',
            '"//services/network/public/cpp",',
            '"//services/network/public/mojom",',
            '"//third_party/blink/public/common",',
            '"//ui/base",',
            '"//url",',
        ):
            with self.subTest(entry=entry):
                self.assertIn(entry, target)

        for forbidden in (
            '"//components/sessions",',
            '"//chrome/browser/sessions",',
            '"//chrome/browser/ui:ui",',
            '"//chrome/browser/ui/tabs:tab_strip",',
            '"//chrome/browser/ui/browser_window",',
            ":wasm_tab_bootstrap_delegate",
            ":wasm_tab_features",
            ":wasm_browser_window_features",
            ":wasm_browser_main_parts",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        # The real tab core and its bounded process-local smoke are the only
        # owners of this helper. Browser main parts reaches it only through
        # that explicit smoke owner, not a browser-window lifecycle.
        self.assertEqual(2, wasm_build.count('":wasm_session_tab_helper",'))
        self.assertIn(
            '":wasm_session_tab_helper",',
            _source_set_body(wasm_build, "wasm_tab_core"),
        )
        self.assertIn(
            '":wasm_session_tab_helper",',
            _source_set_body(wasm_build, "wasm_tab_core_smoke"),
        )
        self.assertNotIn(":wasm_session_tab_helper", source("chrome/BUILD.gn"))


if __name__ == "__main__":
    unittest.main()

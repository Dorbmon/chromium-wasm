#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the object-only Wasm TabStripModelDelegate prerequisite."""

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


class M6TabBootstrapDelegateContractTest(unittest.TestCase):
    def test_delegate_is_real_bwi_backed_and_source_selected(self) -> None:
        header = source("chrome/browser/wasm/wasm_tab_bootstrap_delegate.h")
        implementation = source(
            "chrome/browser/wasm/wasm_tab_bootstrap_delegate.cc"
        )

        self.assertIn(
            '#include "chrome/browser/ui/tabs/tab_strip_model_delegate.h"',
            header,
        )
        self.assertIn(
            "class WasmTabBootstrapDelegate : public TabStripModelDelegate",
            header,
        )
        self.assertIn(
            "const raw_ptr<BrowserWindowInterface> browser_window_interface_;",
            header,
        )
        self.assertIn("CHECK(browser_window_interface_);", implementation)
        self.assertIn(
            "BrowserWindowInterface::TYPE_NORMAL", implementation
        )
        self.assertRegex(
            implementation,
            r"BrowserWindowInterface\*\s*"
            r"WasmTabBootstrapDelegate::GetBrowserWindowInterface\(\) \{\s*"
            r"return browser_window_interface_;",
        )

    def test_delegate_does_not_choose_webcontents_helper_policy(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_tab_bootstrap_delegate.cc"
        )

        self.assertIn("CHECK(contents);", implementation)
        self.assertIn("after TabModel construction", implementation)
        self.assertIn("future Wasm TabModel owns", implementation)
        self.assertIn("pre-construction helper policy", implementation)

        # SessionTabHelper must be attached before TabModel construction by a
        # later Wasm core seam. The unlinked delegate must not choose the base
        # security helper either: Chrome's helper cannot replace it later.
        self.assertNotIn("SessionTabHelper::", implementation)
        self.assertNotIn(
            '#include "components/sessions/content/session_tab_helper.h"',
            implementation,
        )
        self.assertNotIn("components/sessions/content", implementation)
        self.assertNotIn("SecurityStateTabHelper::", implementation)
        self.assertNotIn(
            '#include "components/security_state/content/security_state_tab_helper.h"',
            implementation,
        )

    def test_unsupported_operations_fail_or_report_explicitly(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_tab_bootstrap_delegate.cc"
        )

        self.assertIn(
            "[[noreturn]] void UnsupportedTabBootstrapOperation", implementation
        )
        self.assertIn("CHECK(false)", implementation)

        for operation in (
            "tab creation",
            "window creation",
            "split duplication",
            "moving tabs between windows",
            "moving tabs to a new window",
            "tab close unload handling",
            "Read Later",
            "copying tab URLs",
            "Glic",
        ):
            with self.subTest(operation=operation):
                self.assertIn(
                    f'UnsupportedTabBootstrapOperation("{operation}")',
                    implementation,
                )

        explicit_results = (
            "return 0;  // Explicitly no move or tear-off actions.",
            "return false;  // Explicitly unsupported.",
            "return nullptr;  // Explicit unsupported result.",
            "return std::nullopt;  // Explicitly no tab-restore persistence.",
            "return false;  // Explicitly unsupported until the browser "
            "command lifecycle.",
        )
        for result in explicit_results:
            with self.subTest(result=result):
                self.assertIn(result, implementation)

        self.assertNotIn("std::move(close_callback).Run()", implementation)
        self.assertNotIn("std::move(callback).Run()", implementation)

        # The one selected core/view smoke reaches the strict immediate-close
        # path only after TabStripModel has rejected pending unload work. The
        # delegate must never manufacture an asynchronous close success.
        no_unload = re.search(
            r"bool WasmTabBootstrapDelegate::ShouldRunUnloadListenerBeforeClosing\(\s*"
            r"content::WebContents\* contents\) \{(?P<body>.*?)\n\}",
            implementation,
            re.DOTALL,
        )
        self.assertIsNotNone(no_unload)
        body = no_unload.group("body")
        self.assertIn("CHECK(contents);", body)
        self.assertIn(
            "CHECK(!contents->NeedToFireBeforeUnloadOrUnloadEvents())", body
        )
        self.assertIn("return false;", body)
        self.assertNotIn("RunUnloadListenerBeforeClosing(contents)", body)

    def test_target_is_narrow_and_selected_only_by_core_smoke_targets(
        self,
    ) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_tab_bootstrap_delegate")

        for entry in (
            '"wasm_tab_bootstrap_delegate.cc"',
            '"wasm_tab_bootstrap_delegate.h"',
            '"../ui/tabs/tab_strip_model_delegate.h"',
            '"//chrome/browser/ui/browser_window",',
            '"//components/sessions:session_id",',
            '"//components/split_tabs",',
            '"//components/tab_groups",',
            '"//components/tabs:public",',
        ):
            with self.subTest(entry=entry):
                self.assertIn(entry, target)

        for forbidden in (
            '"//chrome/browser/ui/tabs:tab_strip",',
            '"//chrome/browser/ui/tabs:tab_strip_impl",',
            '"//chrome/browser/ui:ui",',
            '"//components/sessions",',
            '"//components/security_state/content",',
            '"//content/public/browser",',
            ":wasm_browser_window_features",
            ":wasm_browser_main_parts",
            ":wasm_browser_command_controller",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertEqual(1, wasm_build.count('":wasm_tab_bootstrap_delegate",'))
        self.assertIn(
            '":wasm_tab_bootstrap_delegate",',
            _source_set_body(wasm_build, "wasm_browser_window_core"),
        )
        self.assertNotIn(
            '":wasm_tab_bootstrap_delegate",',
            _source_set_body(wasm_build, "wasm_browser_main_parts"),
        )
        self.assertNotIn(
            ":wasm_tab_bootstrap_delegate", source("chrome/BUILD.gn")
        )


if __name__ == "__main__":
    unittest.main()

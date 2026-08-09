#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the source-selected Wasm navigation command controller."""

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


class M6BrowserCommandControllerContractTest(unittest.TestCase):
    def test_wasm_header_uses_the_narrow_browser_window_contract(self) -> None:
        header = source("chrome/browser/ui/browser_command_controller.h")

        self.assertIn(
            "// The desktop UI target owns these dependencies. GN checks header includes",
            header,
        )
        for desktop_only_include in (
            "chrome/browser/ui/side_panel/side_panel_enums.h",
            "chrome/browser/ui/tabs/tab_strip_model_observer.h",
            "chrome/browser/ui/webui/side_panel/customize_chrome/"
            "customize_chrome_section.h",
            "components/prefs/pref_change_registrar.h",
            "components/prefs/pref_member.h",
            "components/sessions/core/tab_restore_service_observer.h",
            "content/public/browser/web_contents_observer.h",
            "ui/actions/actions.h",
        ):
            with self.subTest(desktop_only_include=desktop_only_include):
                self.assertIn(
                    f'#include "{desktop_only_include}"  // nogncheck', header
                )

        self.assertIn('#if BUILDFLAG(IS_WASM)\nclass BrowserCommandController : public CommandUpdater {', header)
        self.assertIn("const raw_ptr<BrowserWindowInterface> browser_window_interface_;", header)
        self.assertIn("base::CallbackListSubscription active_tab_changed_subscription_;", header)
        self.assertIn("std::unique_ptr<ActiveContentsObserver> active_contents_observer_;", header)
        self.assertIn("void ObserveActiveContents();", header)
        self.assertIn(
            "void ActiveTabChanged(BrowserWindowInterface* browser_window_interface);",
            header,
        )
        self.assertIn("void ActiveContentsDestroyed();", header)
        self.assertIn("void ClearNavigationCommands();", header)
        self.assertIn("void UpdateNavigationCommands();", header)
        self.assertIn("content::WebContents* GetActiveContents() const;", header)

        wasm_class = re.search(
            r"#if BUILDFLAG\(IS_WASM\)\n"
            r"class BrowserCommandController : public CommandUpdater \{"
            r"(?P<body>.*?)#else\n"
            r"class BrowserCommandController",
            header,
            re.DOTALL,
        )
        self.assertIsNotNone(wasm_class)
        wasm_header = wasm_class.group("body")
        for forbidden in (
            "TabStripModelObserver",
            "TabRestoreServiceObserver",
            "PrefChangeRegistrar",
            "actions::ActionItem",
            "base::WeakPtrFactory",
            "const raw_ptr<Browser> browser_",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, wasm_header)

    def test_navigation_actions_are_real_and_other_commands_are_absent(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_browser_command_controller.cc"
        )

        self.assertIn("bool IsWasmNavigationCommand(int command_id)", implementation)
        for command in (
            "IDC_BACK",
            "IDC_FORWARD",
            "IDC_RELOAD",
            "IDC_RELOAD_BYPASSING_CACHE",
            "IDC_STOP",
        ):
            with self.subTest(command=command):
                self.assertIn(f"case {command}:", implementation)

        self.assertIn("browser_window_interface_->RegisterActiveTabDidChange(", implementation)
        self.assertIn("std::make_unique<ActiveContentsObserver>", implementation)
        self.assertIn("content::NavigationController& navigation_controller", implementation)
        self.assertIn("navigation_controller.GoBack();", implementation)
        self.assertIn("navigation_controller.GoForward();", implementation)
        self.assertIn("content::ReloadType::NORMAL", implementation)
        self.assertIn("content::ReloadType::BYPASSING_CACHE", implementation)
        self.assertIn("web_contents->Stop();", implementation)
        self.assertIn("disposition != WindowOpenDisposition::CURRENT_TAB", implementation)
        self.assertIn("return false;", implementation)
        self.assertIn(
            "if (!web_contents || web_contents->IsBeingDestroyed()) {\n"
            "    return false;\n"
            "  }",
            implementation,
        )
        self.assertIn("command_updater_.UpdateCommandEnabled(IDC_STOP, false);", implementation)
        self.assertIn("web_contents->IsLoading()", implementation)
        self.assertIn("web_contents->GetController().CanGoBack()", implementation)
        self.assertIn("web_contents->GetController().CanGoForward()", implementation)
        self.assertIn("if (!SupportsCommand(id)) {\n    return false;", implementation)
        self.assertIn("controller_->ActiveContentsDestroyed();", implementation)
        self.assertIn("active_contents_destroyed_ = true;", implementation)
        self.assertIn(
            "void BrowserCommandController::ActiveTabChanged(\n"
            "    BrowserWindowInterface* browser_window_interface)",
            implementation,
        )
        self.assertIn(
            "CHECK_EQ(browser_window_interface, browser_window_interface_);",
            implementation,
        )
        self.assertIn("void BrowserCommandController::ClearNavigationCommands()", implementation)

        update_match = re.search(
            r"void BrowserCommandController::UpdateNavigationCommands\(\) \{"
            r"(?P<body>.*?)\n\}",
            implementation,
            re.DOTALL,
        )
        self.assertIsNotNone(update_match)
        update_body = update_match.group("body")
        self.assertIn(
            "if (!web_contents || web_contents->IsBeingDestroyed()) {\n"
            "    // NavigationController may no longer be safe to query during WebContents\n"
            "    // teardown. The observer's WebContentsDestroyed() callback will retain\n"
            "    // this disabled state until BrowserWindowInterface selects a replacement.\n"
            "    ClearNavigationCommands();\n"
            "    return;\n"
            "  }",
            update_body,
        )
        self.assertLess(
            update_body.index("web_contents->IsBeingDestroyed()"),
            update_body.index("web_contents->GetController()"),
        )

        destroyed_match = re.search(
            r"void WebContentsDestroyed\(\) override \{(?P<body>.*?)\n  \}",
            implementation,
            re.DOTALL,
        )
        self.assertIsNotNone(destroyed_match)
        self.assertNotIn("UpdateNavigationCommands", destroyed_match.group("body"))

        # These APIs have no definitions: trying to use a profile/menu or side
        # panel command is a link-time feature-boundary failure, not a null
        # implementation that could make Chrome UI look functional.
        self.assertNotRegex(
            implementation,
            r"void BrowserCommandController::ShowCustomizeChromeSidePanel\s*\(",
        )
        self.assertNotRegex(
            implementation,
            r"BrowserCommandController::UpdateSharedCommandsForIncognitoAvailability\s*\(",
        )

        for forbidden in (
            "Browser::",
            "browser_commands",
            "BrowserWindowFeatures",
            "BrowserActions",
            "ActionManager",
            "NewTab",
            "ExtensionRegistry",
            "TabRestoreService",
            "SidePanelController",
            "ThemeService",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_source_selection_is_narrow_and_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(wasm_build, "wasm_browser_command_controller")

        public_deps_match = re.search(
            r"public_deps = \[(?P<body>.*?)\n  \]", target, re.DOTALL
        )
        self.assertIsNotNone(public_deps_match)
        public_deps = public_deps_match.group("body")
        self.assertIn('"//chrome/common:buildflags",', public_deps)
        self.assertNotIn('"//chrome/browser/ui/browser_window",', public_deps)

        deps_match = re.search(
            r"^  deps = \[(?P<body>.*?)\n  \]", target, re.DOTALL | re.MULTILINE
        )
        self.assertIsNotNone(deps_match)
        self.assertIn(
            '"//chrome/browser/ui/browser_window",', deps_match.group("body")
        )

        for required in (
            '"../command_observer.h"',
            '"../command_updater.h"',
            '"../command_updater_delegate.h"',
            '"../command_updater_impl.h"',
            '"../ui/browser_command_controller.h"',
            '"../command_updater_impl.cc"',
            '"wasm_browser_command_controller.cc"',
            '"//base",',
            '"//chrome/app:command_ids",',
            '"//chrome/common:buildflags",',
            '"//chrome/browser/ui/browser_window"',
            '"//components/tabs:public",',
            '"//content/public/browser",',
            '"//ui/base",',
        ):
            with self.subTest(required=required):
                self.assertIn(required, target)

        for forbidden in (
            "//chrome/browser/ui/tabs:tab_strip",
            "//chrome/browser:command_updater_impl",
            "//chrome/browser:primitives",
            "//chrome/browser/ui:ui",
            "//chrome/browser/ui/browser_window/internal",
            "//chrome/browser/ui/browser_commands",
            "//chrome/browser/history",
            "//extensions",
            "//chrome/browser/profiles",
            "//chrome/browser/ui/side_panel",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        self.assertNotIn(":wasm_browser_command_controller", source("chrome/BUILD.gn"))
        self.assertNotIn(
            ":wasm_browser_command_controller",
            _source_set_body(wasm_build, "wasm_browser_main_parts"),
        )
        # BrowserWindowFeatures is the sole owner and constructs the
        # controller before BrowserView. The bounded Views consumers depend on
        # its public API only to reflect/execute selected active-tab navigation;
        # neither adds a Browser core or browser-main lifecycle edge.
        self.assertIn(
            ":wasm_browser_command_controller",
            _source_set_body(wasm_build, "wasm_browser_window_features"),
        )
        self.assertIn(
            ":wasm_browser_command_controller",
            _source_set_body(wasm_build, "wasm_browser_window_view_smoke"),
        )
        self.assertIn(
            ":wasm_browser_command_controller",
            _source_set_body(wasm_build, "wasm_top_controls"),
        )
        self.assertIn(
            ":wasm_browser_command_controller",
            _source_set_body(wasm_build, "wasm_browser_menu"),
        )
        self.assertEqual(
            4, wasm_build.count('\":wasm_browser_command_controller\",')
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the M6 source-selected BrowserManager lifecycle."""

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


class M6BrowserManagerContractTest(unittest.TestCase):
    def test_manager_is_source_selected_without_desktop_browser_aggregates(
        self,
    ) -> None:
        target = _source_set_body(
            source("chrome/browser/wasm/BUILD.gn"), "wasm_browser_manager"
        )

        for filename in (
            "wasm_browser_manager_service.cc",
            "wasm_browser_manager_service_factory.cc",
            "wasm_profile_browser_collection.cc",
        ):
            with self.subTest(filename=filename):
                self.assertIn(f'"{filename}"', target)

        for dependency in (
            '":wasm_browser_collection",',
            '"//chrome/browser/profiles:profile",',
            '"//chrome/browser/ui/browser_window",',
            '"//components/keyed_service/content",',
            '"//components/keyed_service/core",',
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, target)

        for forbidden in (
            "//chrome/browser/ui:ui",
            "//chrome/browser/history",
            "//chrome/browser/bookmarks",
            "//chrome/browser/lifetime",
            "//chrome/browser/printing",
            "//chrome/browser/ui/browser_window/internal",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

    def test_manager_owns_browser_window_interface_not_browser_concrete_type(
        self,
    ) -> None:
        header = source("chrome/browser/ui/browser_manager_service.h")
        wasm_service = source(
            "chrome/browser/wasm/wasm_browser_manager_service.cc"
        )

        self.assertIn(
            "std::unique_ptr<BrowserWindowInterface> browser", header
        )
        self.assertIn(
            "void DeleteBrowser(BrowserWindowInterface* browser);", header
        )
        self.assertNotIn("std::unique_ptr<Browser> browser", header)
        self.assertNotIn("DeleteBrowser(Browser* browser)", header)
        self.assertNotIn('"chrome/browser/ui/browser.h"', wasm_service)
        self.assertIn("CHECK(!profile_->IsOffTheRecord())", wasm_service)

    def test_factory_is_registered_before_profile_becomes_live(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        factory = source(
            "chrome/browser/wasm/wasm_browser_manager_service_factory.cc"
        )

        ensure = "EnsureWasmBrowserKeyedServiceFactoriesBuilt();"
        create_profile = "profile_ = std::make_unique<WasmProfile>(profile_path);"
        get_service = (
            "CHECK(BrowserManagerServiceFactory::GetForProfile(profile_.get()));"
        )
        self.assertIn(ensure, main_parts)
        self.assertIn(create_profile, main_parts)
        self.assertIn(get_service, main_parts)
        self.assertLess(main_parts.index(ensure), main_parts.index(create_profile))
        self.assertLess(
            main_parts.index(create_profile), main_parts.index(get_service)
        )
        self.assertIn("BrowserManagerServiceFactory::GetInstance();", factory)
        self.assertNotIn(
            '#include "chrome/browser/history/history_service_factory.h"',
            factory,
        )
        self.assertNotIn("DependsOn(HistoryServiceFactory", factory)
        self.assertIn("history", factory.lower())

    def test_profile_registers_then_creates_keyed_services_in_lifecycle_order(
        self,
    ) -> None:
        profile = source("chrome/browser/wasm/wasm_profile.cc")

        ordered_steps = (
            "Profile::RegisterProfilePrefs(pref_registry_.get());",
            "RegisterIntegerPref(prefs::kDevToolsAvailability",
            "SimpleDependencyManager::GetInstance()->RegisterProfilePrefsForServices",
            "BrowserContextDependencyManager::GetInstance()\n      ->RegisterProfilePrefsForServices",
            "PrefServiceFactory pref_service_factory;",
            "SimpleKeyMap::GetInstance()->Associate(this, key_.get());",
            "SimpleDependencyManager::GetInstance()->CreateServices(key_.get());",
            "BrowserContextDependencyManager::GetInstance()->CreateBrowserContextServices(\n      this);",
            "NotifyProfileInitializationComplete();",
        )
        positions = []
        for step in ordered_steps:
            with self.subTest(step=step):
                self.assertIn(step, profile)
                positions.append(profile.index(step))
        self.assertEqual(positions, sorted(positions))

        self.assertIn("PerformInterlockedTwoPhaseShutdown", profile)
        self.assertLess(
            profile.index("PerformInterlockedTwoPhaseShutdown"),
            profile.index("SimpleKeyMap::GetInstance()->Dissociate(this);"),
        )

    def test_manager_keeps_desktop_shutdown_and_workspace_paths_out(self) -> None:
        wasm_service = source(
            "chrome/browser/wasm/wasm_browser_manager_service.cc"
        )
        collection = source(
            "chrome/browser/wasm/wasm_profile_browser_collection.cc"
        )

        for forbidden in (
            "ProfileDestroyer",
            "background_printing",
            "chrome::OnAppExiting",
            "HistoryService",
            '"chrome/browser/ui/browser.h"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, wasm_service)
        self.assertIn("one Ozone surface", collection)
        self.assertNotIn('"chrome/browser/ui/browser.h"', collection)


if __name__ == "__main__":
    unittest.main()

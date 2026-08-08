#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded Wasm Chrome security-state helper."""

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


class M6ChromeSecurityStateContractTest(unittest.TestCase):
    def test_wasm_header_preserves_elevated_identity_without_ui_observers(
        self,
    ) -> None:
        header = source("chrome/browser/ssl/chrome_security_state_tab_helper.h")

        self.assertIn('#include "build/build_config.h"', header)
        self.assertIn(
            "class ChromeSecurityStateTabHelper : public SecurityStateTabHelper",
            header,
        )
        self.assertIn("#if !BUILDFLAG(IS_WASM)\n"
                      "                                     , public content::WebContentsObserver",
                      header)
        self.assertIn("#if !BUILDFLAG(IS_WASM)\n"
                      "  std::unique_ptr<security_state::VisibleSecurityState>",
                      header)
        self.assertIn("static void CreateForWebContents", header)

    def test_wasm_implementation_uses_the_chrome_userdata_key(self) -> None:
        implementation = source(
            "chrome/browser/wasm/wasm_chrome_security_state_tab_helper.cc"
        )

        for expected in (
            '#include "chrome/browser/ssl/chrome_security_state_tab_helper.h"',
            "#if !BUILDFLAG(IS_WASM)",
            "SecurityStateTabHelper* helper = FromWebContents(contents);",
            "contents->SetUserData(UserDataKey(), base::WrapUnique(helper));",
            "CHECK(helper->uses_embedder_information())",
            "SecurityStateTabHelper(web_contents, UsesEmbedderInformation(true))",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, implementation)

        for forbidden in (
            "QwacWebContentsObserver",
            "SafetyTipWebContentsObserver",
            "HttpsOnlyModeTabHelper",
            "MaybeShowKnownInterceptionDisclosureDialog",
            "GetVisibleSecurityState()",
            "GetMaliciousContentStatus()",
            "DidStartNavigation(",
            "PrimaryPageChanged(",
            "PrefService",
            "return nullptr",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_target_is_narrow_and_unwired(self) -> None:
        wasm_build = source("chrome/browser/wasm/BUILD.gn")
        target = _source_set_body(
            wasm_build, "wasm_chrome_security_state_tab_helper"
        )

        for expected in (
            '"wasm_chrome_security_state_tab_helper.cc"',
            '"../ssl/chrome_security_state_tab_helper.h"',
            '"//components/security_state/content"',
            '"//content/public/browser"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, target)

        for forbidden in (
            '"//chrome/browser/ssl:impl"',
            '"//chrome/browser/net"',
            '"//chrome/browser/lookalikes"',
            '"//chrome/browser/safe_browsing"',
            '"//components/security_interstitials"',
            '"//chrome/browser/ui:ui"',
            ":wasm_tab_features",
            ":wasm_browser_window_features",
            ":wasm_browser_main_parts",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, target)

        # The tab core and its bounded process-local smoke are the only
        # owners of the elevated helper. Browser main parts reaches it only
        # through that explicit smoke owner, not a browser-window lifecycle.
        self.assertEqual(
            2, wasm_build.count('":wasm_chrome_security_state_tab_helper",')
        )
        self.assertIn(
            '":wasm_chrome_security_state_tab_helper",',
            _source_set_body(wasm_build, "wasm_tab_core"),
        )
        self.assertIn(
            '":wasm_chrome_security_state_tab_helper",',
            _source_set_body(wasm_build, "wasm_tab_core_smoke"),
        )
        self.assertNotIn(
            ":wasm_chrome_security_state_tab_helper", source("chrome/BUILD.gn")
        )


if __name__ == "__main__":
    unittest.main()

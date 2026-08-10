#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded physical Ozone accelerator-key slice."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M6OzoneAcceleratorKeysContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")

    def test_preserves_the_m4_allowlist_and_adds_only_selected_accelerators(
        self,
    ) -> None:
        m4_allowlist = section(
            self.event_source,
            "bool IsSupportedM4DomCode(DomCode dom_code)",
            "bool IsSupportedWasmAcceleratorDomCode",
        )
        self.assertEqual(
            re.findall(r"DomCode::([A-Z_]+)", m4_allowlist),
            [
                "ARROW_DOWN",
                "US_A",
                "US_B",
                "BACKSPACE",
                "CONTROL_LEFT",
                "US_C",
                "US_V",
            ],
        )

        accelerator_allowlist = section(
            self.event_source,
            "bool IsSupportedWasmAcceleratorDomCode(DomCode dom_code)",
            "bool IsM4RepeatableDomCode",
        )
        self.assertEqual(
            re.findall(r"DomCode::([A-Z_]+)", accelerator_allowlist),
            [
                "SHIFT_LEFT",
                "ALT_LEFT",
                "US_L",
                "US_R",
                "ARROW_LEFT",
                "ARROW_RIGHT",
                "TAB",
                "ENTER",
            ],
        )

    def test_tracks_modifier_state_and_rejects_unapproved_chords(self) -> None:
        injector = section(
            self.event_source,
            "  void InjectKeyEvent(DomCode physical_key",
            " private:",
        )
        chord_policy = section(
            self.event_source,
            "  bool IsAcceleratorChordSatisfied(DomCode physical_key) const",
            "  raw_ptr<WasmPlatformEventSource> event_source_",
        )

        for marker in (
            "DomCode::SHIFT_LEFT",
            "DomCode::ALT_LEFT",
            "DomCode::US_L",
            "DomCode::US_R",
            "DomCode::ARROW_LEFT",
            "DomCode::ARROW_RIGHT",
            "DomCode::TAB",
            "DomCode::ENTER",
            "shift_left_",
            "alt_left_",
            "key_l_",
            "key_r_",
            "arrow_left_",
            "arrow_right_",
            "tab_",
            "enter_",
            "if (down && !IsAcceleratorChordSatisfied(physical_key))",
            "*key_down == down",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, injector)

        # Duplicate input is rejected before a new action key may be admitted,
        # while keyup bypasses the chord admission check so a valid held key can
        # always be released after its modifier is released first.
        self.assertLess(
            injector.index("if (*key_down == down)"),
            injector.index("if (down && !IsAcceleratorChordSatisfied(physical_key))"),
        )

        self.assertRegex(
            chord_policy,
            r"case DomCode::US_L:\s*"
            r"return control_left_ && !shift_left_ && !alt_left_;",
        )
        self.assertRegex(
            chord_policy,
            r"case DomCode::US_R:\s*return control_left_ && !alt_left_;",
        )
        self.assertRegex(
            chord_policy,
            r"case DomCode::ARROW_LEFT:\s*case DomCode::ARROW_RIGHT:\s*"
            r"return alt_left_ && !control_left_ && !shift_left_;",
        )
        self.assertRegex(
            chord_policy,
            r"case DomCode::TAB:\s*return control_left_ && !alt_left_;",
        )
        self.assertRegex(
            chord_policy,
            r"case DomCode::ENTER:\s*"
            r"return !control_left_ && !shift_left_ && !alt_left_;",
        )

    def test_modifier_flags_and_repeat_policy_remain_physical_and_bounded(
        self,
    ) -> None:
        injector = section(
            self.event_source,
            "  void InjectKeyEvent(DomCode physical_key",
            " private:",
        )
        modifier_flags = injector
        repeatable = section(
            self.event_source,
            "bool IsM4RepeatableDomCode(DomCode dom_code)",
            "raw_ptr<WasmPlatformEventSource>& GetWasmPlatformEventSource",
        )

        for marker in (
            "control_left_ || physical_key == DomCode::CONTROL_LEFT",
            "shift_left_ || physical_key == DomCode::SHIFT_LEFT",
            "alt_left_ || physical_key == DomCode::ALT_LEFT",
            "EF_CONTROL_DOWN",
            "EF_SHIFT_DOWN",
            "EF_ALT_DOWN",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, modifier_flags)

        self.assertIn("IsM4RepeatableDomCode(physical_key)", injector)
        self.assertIn("modifier_flags_for_key(physical_key) |", injector)
        self.assertIn("EF_IS_REPEAT", injector)
        self.assertEqual(
            re.findall(r"DomCode::([A-Z_]+)", repeatable),
            ["ARROW_DOWN", "BACKSPACE"],
        )

    def test_event_dispatch_accepts_the_same_bounded_union(self) -> None:
        dispatch = section(
            self.event_source,
            "bool WasmPlatformEventSource::DispatchKeyEvent",
            "std::unique_ptr<SystemInputInjector> "
            "CreateWasmSystemInputInjector",
        )

        self.assertIn("IsSupportedM4DomCode(physical_key)", dispatch)
        self.assertIn("IsSupportedWasmAcceleratorDomCode(physical_key)", dispatch)
        self.assertIn("KeyboardLayoutEngineManager::GetKeyboardLayoutEngine", dispatch)
        self.assertIn("layout_engine->Lookup", dispatch)
        self.assertNotIn("EMSCRIPTEN_KEEPALIVE", self.event_source)


if __name__ == "__main__":
    unittest.main()

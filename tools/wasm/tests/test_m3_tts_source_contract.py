#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3TtsSourceContractTest(unittest.TestCase):
    def test_wasm_selects_its_explicitly_unsupported_tts_platform(
        self,
    ) -> None:
        build = source("content/browser/BUILD.gn")
        wasm_selection = build.split(
            'if (is_wasm) {\n    sources += [\n'
            '      "child_process_launcher_helper_wasm.cc",',
            1,
        )[1].split("  } else if (is_fuchsia)", 1)[0]

        self.assertIn('"speech/tts_wasm.cc",', wasm_selection)
        self.assertNotIn("tts_linux.cc", wasm_selection)
        self.assertNotIn("tts_fuchsia.cc", wasm_selection)

    def test_wasm_tts_never_reports_fake_platform_success(self) -> None:
        implementation = source("content/browser/speech/tts_wasm.cc")

        self.assertIn(
            "class TtsPlatformImplWasm final : public TtsPlatformImpl",
            implementation,
        )
        self.assertIn(
            "bool PlatformImplSupported() override { return false; }",
            implementation,
        )
        self.assertIn(
            "bool PlatformImplInitialized() override { return false; }",
            implementation,
        )
        self.assertIn(
            "std::move(did_start_speaking_callback).Run(false);",
            implementation,
        )
        self.assertIn(
            "bool StopSpeaking() override { return false; }",
            implementation,
        )
        self.assertIn(
            "bool IsSpeaking() override { return false; }",
            implementation,
        )
        self.assertIn(
            "void GetVoices(std::vector<VoiceData>* out_voices) override {\n"
            "    // The unavailable platform contributes no voices to the "
            "caller's list.\n"
            "  }",
            implementation,
        )
        self.assertIn("void Pause() override {}", implementation)
        self.assertIn("void Resume() override {}", implementation)
        self.assertNotIn("return true;", implementation)


if __name__ == "__main__":
    unittest.main()

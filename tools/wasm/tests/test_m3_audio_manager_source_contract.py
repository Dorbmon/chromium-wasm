#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3AudioManagerSourceContractTest(unittest.TestCase):
    def test_wasm_selects_dedicated_audio_manager_and_test(self) -> None:
        build = source("media/audio/BUILD.gn")
        wasm_audio = build.split(
            'if (is_wasm) {\n'
            '    sources += [ "audio_manager_wasm.cc" ]',
            1,
        )[1].split("  if (is_apple)", 1)[0]
        wasm_tests = build.split(
            'if (is_wasm) {\n'
            '    sources += [ "audio_manager_wasm_unittest.cc" ]',
            1,
        )[1].split("  configs +=", 1)[0]

        self.assertIn("if (!is_wasm)", wasm_audio)
        self.assertIn("if (!is_wasm)", wasm_tests)
        self.assertNotIn("audio_manager_linux.cc", wasm_audio)
        self.assertNotIn("fake_audio_manager.cc", wasm_audio)

    def test_wasm_reports_unavailable_audio_without_fake_streams(self) -> None:
        implementation = source("media/audio/audio_manager_wasm.cc")

        self.assertIn(
            "class AudioManagerWasm final : public AudioManagerBase",
            implementation,
        )
        self.assertIn(
            "bool HasAudioOutputDevices() override {\n"
            "    CHECK(GetTaskRunner()->BelongsToCurrentThread());\n"
            "    return false;\n"
            "  }",
            implementation,
        )
        self.assertIn(
            "bool HasAudioInputDevices() override {\n"
            "    CHECK(GetTaskRunner()->BelongsToCurrentThread());\n"
            "    return false;\n"
            "  }",
            implementation,
        )
        self.assertEqual(
            implementation.count(
                "return AudioParameters::UnavailableDeviceParams();"
            ),
            2,
        )
        self.assertEqual(implementation.count("return nullptr;"), 7)
        self.assertNotIn("FakeAudio", implementation)


if __name__ == "__main__":
    unittest.main()

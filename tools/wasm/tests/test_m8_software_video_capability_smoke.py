#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8.3 software-video capability witness."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_software_video_capability_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


def valid_stdout() -> str:
    return "\n".join(
        (
            *smoke.EXPECTED_MARKERS,
            f'{smoke.PREFIX}:NODE_EXIT {{"exitCode":0}}',
        )
    )


class M8SoftwareVideoCapabilityResultTest(unittest.TestCase):
    def test_accepts_exact_disabled_software_video_witness(self) -> None:
        smoke.validate_streams(valid_stdout(), "")

    def test_rejects_out_of_order_or_relaxed_capability_result(self) -> None:
        lines = valid_stdout().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        with self.assertRaisesRegex(M0Error, "out of order"):
            smoke.validate_streams("\n".join(lines), "")

        relaxed = valid_stdout().replace("vp8=not_supported", "vp8=supported")
        with self.assertRaisesRegex(M0Error, "exactly one"):
            smoke.validate_streams(relaxed, "")

        enabled = valid_stdout().replace(
            "software_decoder_buildflags status=disabled",
            "software_decoder_buildflags status=enabled",
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            smoke.validate_streams(enabled, "")

    def test_rejects_native_failure_or_missing_zero_exit(self) -> None:
        with self.assertRaisesRegex(M0Error, "failure marker"):
            smoke.validate_streams(valid_stdout(), f"{smoke.PREFIX}:FAIL stage=x")
        with self.assertRaisesRegex(M0Error, "exactly one zero native exit"):
            smoke.validate_streams(
                valid_stdout().replace('"exitCode":0', '"exitCode":1'), ""
            )

    def test_resolve_module_requires_fixed_js_and_wasm_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            module = out_dir / smoke.MODULE_NAME
            module.write_text("export default async () => {};", encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "sidecar"):
                smoke.resolve_module(out_dir)
            module.with_suffix(".wasm").write_bytes(b"\\0asm")
            self.assertEqual(smoke.resolve_module(out_dir), module.resolve())


class M8SoftwareVideoCapabilitySourceContractTest(unittest.TestCase):
    def test_target_is_wasm_only_and_uses_media_capability_api(self) -> None:
        build = source("media/base/BUILD.gn")
        native = source("media/base/wasm_software_video_capability_smoke.cc")
        runner = source("tools/wasm/run_m8_software_video_capability_smoke.py")

        self.assertIn('if (is_wasm) {', build)
        self.assertIn('visibility += [ ":wasm_software_video_capability_smoke" ]', build)
        self.assertIn('executable("wasm_software_video_capability_smoke")', build)
        self.assertIn('sources = [ "wasm_software_video_capability_smoke.cc" ]', build)
        self.assertIn('"//media:media_buildflags",', build)
        self.assertIn('#if !BUILDFLAG(IS_WASM)', native)
        self.assertIn('#if BUILDFLAG(IS_POSIX)', native)
        self.assertIn("media::IsSupportedMediaFormat", native)
        self.assertIn("media::IsDecoderBuiltInVideoCodec", native)
        for flag in (
            "ENABLE_LIBVPX",
            "ENABLE_FFMPEG_VIDEO_DECODERS",
            "ENABLE_AV1_DECODER",
        ):
            self.assertIn(flag, native)
        self.assertIn("browser_playback=not_proven", native)
        self.assertIn("webcodecs=not_proven", native)
        self.assertIn("software_decoder_unexpectedly_enabled", native)
        self.assertIn("m8GateComplete\": False", runner)
        self.assertIn("compiled-media-mime-capability-only", runner)

    def test_target_does_not_claim_or_construct_playback(self) -> None:
        native = source("media/base/wasm_software_video_capability_smoke.cc")
        for forbidden in (
            '#include "content/public/browser/web_contents.h"',
            '#include "media/base/video_decoder.h"',
            '#include "media/renderers/audio_renderer_impl.h"',
            '#include "third_party/blink/renderer/modules/webcodecs/',
            '#include "third_party/blink/renderer/core/html/media/html_video_element.h"',
        ):
            self.assertNotIn(forbidden, native)


if __name__ == "__main__":
    unittest.main()

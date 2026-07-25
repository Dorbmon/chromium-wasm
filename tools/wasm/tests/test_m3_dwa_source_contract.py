#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class M3DwaSourceContractTest(unittest.TestCase):
    def test_wasm_keeps_recording_without_selecting_upload_services(
        self,
    ) -> None:
        dwa_build = source("components/metrics/dwa/BUILD.gn")
        builders = source(
            "tools/metrics/private_metrics/"
            "gen_private_metrics_builders.gni"
        )
        private_metrics_build = source(
            "components/metrics/private_metrics/BUILD.gn"
        )
        content_browser = source("content/browser/BUILD.gn")
        privacy_sandbox = source("components/privacy_sandbox/BUILD.gn")

        wasm_builder_base = dwa_build.split(
            "if (is_wasm) {", 1
        )[1].split("private_metrics_builders", 1)[0]
        self.assertIn(
            'source_set("dwa_entry_builder_base")',
            wasm_builder_base,
        )
        self.assertIn(
            '"dwa_entry_builder_base.cc"',
            wasm_builder_base,
        )
        self.assertIn(
            "//components/metrics/private_metrics:dwa_recorder",
            wasm_builder_base,
        )

        recorder_target = private_metrics_build.split(
            'component("dwa_recorder") {', 1
        )[1].split('component("private_metrics_recorders") {', 1)[0]
        self.assertIn(
            '"//components/metrics/dwa/dwa_recorder.cc"',
            recorder_target,
        )

        builder_wasm_deps = builders.split(
            'if (is_wasm && invoker.type == "dwa") {', 1
        )[1].split("} else {", 1)[0]
        self.assertIn(
            "//components/metrics/dwa:dwa_entry_builder_base",
            builder_wasm_deps,
        )

        content_browser_target = content_browser.split(
            'source_set("browser") {', 1
        )[1].split("if (is_android) {", 1)[0]
        content_wasm_deps = content_browser_target.split(
            "# Content records DWA events during M3", 1
        )[1].split("} else {", 1)[0]
        self.assertIn(
            "//components/metrics/private_metrics:dwa_recorder",
            content_wasm_deps,
        )

        privacy_sandbox_target = privacy_sandbox.split(
            'source_set("privacy_sandbox") {', 1
        )[1].split('source_set("test_support") {', 1)[0]
        privacy_sandbox_wasm_deps = privacy_sandbox_target.split(
            "if (is_wasm) {", 1
        )[1].split("} else {", 1)[0]
        self.assertIn(
            "//components/metrics/private_metrics:dwa_recorder",
            privacy_sandbox_wasm_deps,
        )

        selected_wasm_paths = "\n".join(
            (
                wasm_builder_base,
                recorder_target,
                builder_wasm_deps,
                content_wasm_deps,
                privacy_sandbox_wasm_deps,
            )
        )
        for excluded_upload_path in (
            "data_upload_config_downloader",
            "dwa_service",
            "private_metrics_reporting_service",
            "federated_compute",
            "third_party/oak",
            "_wasm.cc",
        ):
            with self.subTest(excluded_upload_path=excluded_upload_path):
                self.assertNotIn(
                    excluded_upload_path,
                    selected_wasm_paths,
                )

        full_private_metrics_target = private_metrics_build.split(
            'static_library("private_metrics") {', 1
        )[1].split('source_set("unit_tests") {', 1)[0]
        for real_upload_path in (
            "data_upload_config_downloader.cc",
            "dwa_service.cc",
            "private_metrics_reporting_service.cc",
            "//third_party/federated_compute",
            "//third_party/oak:oak_proto",
        ):
            with self.subTest(real_upload_path=real_upload_path):
                self.assertIn(
                    real_upload_path,
                    full_private_metrics_target,
                )

        full_target = '"//components/metrics/private_metrics"'
        self.assertNotIn(full_target, builder_wasm_deps)
        self.assertNotIn(full_target, content_wasm_deps)
        self.assertNotIn(full_target, privacy_sandbox_wasm_deps)
        self.assertEqual(builders.count(full_target), 1)
        self.assertEqual(content_browser_target.count(full_target), 1)
        self.assertEqual(privacy_sandbox_target.count(full_target), 1)


if __name__ == "__main__":
    unittest.main()

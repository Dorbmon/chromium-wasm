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


def braced_block(contents: str, marker: str) -> str:
    marker_index = contents.index(marker)
    open_brace = contents.index("{", marker_index + len(marker))
    depth = 0
    for index in range(open_brace, len(contents)):
        if contents[index] == "{":
            depth += 1
        elif contents[index] == "}":
            depth -= 1
            if depth == 0:
                return contents[open_brace + 1 : index]
    raise AssertionError(f"unterminated block after {marker}")


class M3LanguageDetectionContractTest(unittest.TestCase):
    def test_core_model_is_unavailable_without_tflite(self) -> None:
        build = source("components/language_detection/core/BUILD.gn")
        header = source(
            "components/language_detection/core/language_detection_model.h"
        )
        implementation = source(
            "components/language_detection/core/"
            "language_detection_model_wasm.cc"
        )

        core = braced_block(build, 'component("core")')
        wasm_sources = braced_block(core, "if (is_wasm)")
        native_deps = braced_block(core, "if (!is_wasm)")
        self.assertIn('"language_detection_model_wasm.cc"', wasm_sources)
        self.assertNotIn('"language_detection_model.cc"', wasm_sources)
        self.assertIn('"language_detection_model.cc"', core)
        self.assertIn("//third_party/tflite", native_deps)
        self.assertIn("//third_party/tflite_support", native_deps)
        self.assertNotIn(
            "//third_party/tflite",
            core.replace(native_deps, ""),
        )
        self.assertNotIn("third_party/tflite", header)

        availability = braced_block(
            implementation,
            "bool LanguageDetectionModel::IsAvailable() const",
        )
        model_size = braced_block(
            implementation,
            "int64_t LanguageDetectionModel::GetModelSize() const",
        )
        version = braced_block(
            implementation,
            "std::string LanguageDetectionModel::GetModelVersion() const",
        )
        self.assertIn("return false;", availability)
        self.assertNotIn("return true;", availability)
        self.assertIn("return 0;", model_size)
        self.assertIn('return "unsupported-wasm";', version)
        for method in (
            "LanguageDetectionModel::Predict(",
            "LanguageDetectionModel::PredictWithScan(",
            "LanguageDetectionModel::DetectTopLanguage(",
            "LanguageDetectionModel::PredictTopLanguageWithSamples(",
        ):
            with self.subTest(method=method):
                self.assertIn(
                    "CHECK(IsAvailable())",
                    braced_block(implementation, method),
                )

        blocking_update = braced_block(
            implementation,
            "void LanguageDetectionModel::UpdateWithFile(",
        )
        self.assertIn("model_file.Close();", blocking_update)
        self.assertIn("NotifyModelLoaded();", blocking_update)

    def test_browser_driver_reports_definitive_unavailability(self) -> None:
        service_build = source(
            "components/language_detection/core/browser/BUILD.gn"
        )
        driver = source(
            "components/language_detection/content/browser/"
            "content_language_detection_driver.cc"
        )

        wasm_service = braced_block(service_build, "if (is_wasm)")
        self.assertIn('"language_detection_model_service.cc"', wasm_service)
        self.assertIn(
            "//components/optimization_guide/core", wasm_service
        )
        self.assertIn(
            "//components/optimization_guide/proto", wasm_service
        )

        get_model = braced_block(
            driver,
            "void ContentLanguageDetectionDriver::"
            "GetLanguageDetectionModel(",
        )
        wasm_get_model = get_model.split(
            "#if BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn(
            "std::move(callback).Run(base::File());", wasm_get_model
        )
        self.assertNotIn(
            "GetLanguageDetectionModelFile", wasm_get_model
        )

        get_status = braced_block(
            driver,
            "void ContentLanguageDetectionDriver::"
            "GetLanguageDetectionModelStatus(",
        )
        wasm_get_status = get_status.split(
            "#if BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn(
            "LanguageDetectionModelStatus::kNotAvailable", wasm_get_status
        )
        self.assertNotIn(
            "LanguageDetectionModelStatus::kAfterDownload", wasm_get_status
        )

    def test_translate_reports_no_model_run_or_cld3_version(self) -> None:
        build = source(
            "components/translate/core/language_detection/BUILD.gn"
        )
        util = source(
            "components/translate/core/language_detection/"
            "language_detection_util.cc"
        )
        agent = source(
            "components/translate/content/renderer/translate_agent.cc"
        )

        target = braced_block(build, 'static_library("language_detection")')
        native_deps = braced_block(target, "if (!is_wasm)")
        self.assertIn("//third_party/cld_3", native_deps)
        self.assertIn("//third_party/tflite", native_deps)
        self.assertNotIn(
            "//third_party/cld_3",
            target.replace(native_deps, ""),
        )
        self.assertNotIn(
            "//third_party/tflite",
            target.replace(native_deps, ""),
        )

        determine_text = braced_block(
            util, "std::string DetermineTextLanguage("
        )
        wasm_util = determine_text.split(
            "#if BUILDFLAG(IS_WASM)", 1
        )[1].split("#else", 1)[0]
        self.assertIn("*is_model_reliable = false;", wasm_util)
        self.assertIn("model_reliability_score = 0.0f;", wasm_util)
        self.assertIn(
            "return language_detection::kUnknownLanguageCode;", wasm_util
        )

        wasm_report = agent.split(
            "#if BUILDFLAG(IS_WASM)\n"
            "    // The M3 port does not ship either language-detection model.",
            1,
        )[1].split("#else", 1)[0]
        native_report = agent.split(
            "#if BUILDFLAG(IS_WASM)\n"
            "    // The M3 port does not ship either language-detection model.",
            1,
        )[1].split("#else", 1)[1].split("#endif", 1)[0]
        self.assertIn("DeterminePageLanguageNoModel(", wasm_report)
        self.assertIn(
            "LanguageVerificationType::kModelNotAvailable", wasm_report
        )
        self.assertIn(
            "details.has_run_lang_detection = false;", wasm_report
        )
        self.assertNotIn("kCLDModelVersion", wasm_report)
        self.assertIn("kCLDModelVersion", native_report)
        self.assertIn(
            "details.has_run_lang_detection = true;", native_report
        )

    def test_accessibility_detection_is_disabled_without_cld3(self) -> None:
        build = source("ui/accessibility/BUILD.gn")
        implementation = source(
            "ui/accessibility/ax_language_detection.cc"
        )

        target = braced_block(build, 'component("accessibility_internal")')
        native_deps = braced_block(target, "if (!is_wasm)")
        self.assertIn("//third_party/cld_3", native_deps)
        self.assertNotIn(
            "//third_party/cld_3",
            target.replace(native_deps, ""),
        )
        for method in (
            "bool AXLanguageDetectionManager::"
            "IsStaticLanguageDetectionEnabled()",
            "bool AXLanguageDetectionManager::"
            "IsDynamicLanguageDetectionEnabled()",
        ):
            with self.subTest(method=method):
                wasm_branch = braced_block(
                    implementation, method
                ).split("#if BUILDFLAG(IS_WASM)", 1)[1].split(
                    "#else", 1
                )[0]
                self.assertIn("return false;", wasm_branch)

        annotation = braced_block(
            implementation,
            "AXLanguageDetectionManager::"
            "GetLanguageAnnotationForStringAttribute(",
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return language_annotation;",
            annotation,
        )

    def test_optimization_guide_core_does_not_export_inference(self) -> None:
        build = source("components/optimization_guide/core/BUILD.gn")
        core = braced_block(build, 'static_library("core")')
        native_inference = braced_block(core, "if (!is_wasm)")
        inference = "//components/optimization_guide/core/inference"

        self.assertIn(inference, native_inference)
        self.assertNotIn(inference, core.replace(native_inference, ""))


if __name__ == "__main__":
    unittest.main()

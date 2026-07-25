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


class M3MlFeatureBoundaryContractTest(unittest.TestCase):
    def test_optimization_guide_inference_is_native_only(self) -> None:
        build = source("components/optimization_guide/core/BUILD.gn")
        core = braced_block(build, 'static_library("core")')
        native_deps = braced_block(core, "if (!is_wasm)")
        inference = "//components/optimization_guide/core/inference"

        self.assertIn(inference, native_deps)
        self.assertNotIn(inference, core.replace(native_deps, ""))

    def test_autofill_reports_an_unavailable_model_without_tflite(self) -> None:
        build = source("components/autofill/core/browser/BUILD.gn")
        header = source(
            "components/autofill/core/browser/ml_model/"
            "field_classification_model_handler.h"
        )
        implementation = source(
            "components/autofill/core/browser/ml_model/"
            "field_classification_model_handler_wasm.cc"
        )

        target = braced_block(build, 'static_library("browser")')
        wasm_sources = braced_block(target, "if (is_wasm)")
        native_deps = braced_block(target, "if (!is_wasm)")
        self.assertIn(
            '"ml_model/field_classification_model_handler_wasm.cc"',
            wasm_sources,
        )
        for source_name in (
            "field_classification_model_executor.cc",
            "field_classification_model_executor.h",
            "field_classification_model_handler.cc",
        ):
            with self.subTest(source_name=source_name):
                self.assertIn(f'"ml_model/{source_name}"', wasm_sources)
        for dependency in (
            "//third_party/tflite",
            "//third_party/tflite_support",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, native_deps)
                self.assertNotIn(
                    dependency,
                    target.replace(native_deps, ""),
                )

        wasm_class = header.split(
            "#else\nclass FieldClassificationModelHandler "
            ": public KeyedService {",
            1,
        )[1].split("#endif", 1)[0]
        self.assertNotIn("ModelHandler", wasm_class)
        self.assertIn(
            "bool ModelAvailable() const { return false; }",
            header,
        )
        single_form = braced_block(
            implementation,
            "FieldClassificationModelHandler::"
            "GetModelPredictionsForForm(",
        )
        multiple_forms = braced_block(
            implementation,
            "FieldClassificationModelHandler::"
            "GetModelPredictionsForForms(",
        )
        self.assertIn("ModelPredictions(", single_form)
        self.assertIn("{}, {}", single_form)
        self.assertIn("std::move(callback).Run({});", multiple_forms)

    def test_browsing_topics_omits_the_bert_implementation(self) -> None:
        build = source("components/browsing_topics/BUILD.gn")
        interface = source("components/browsing_topics/annotator.h")

        target = braced_block(build, 'source_set("browsing_topics")')
        wasm_sources = braced_block(target, "if (is_wasm)")
        self.assertIn('"annotator_impl.cc"', wasm_sources)
        self.assertIn('"annotator_impl.h"', wasm_sources)
        self.assertIn(
            "components/optimization_guide/core/delivery/model_info.h",
            interface,
        )
        self.assertNotIn(
            "components/optimization_guide/core/inference",
            interface,
        )

    def test_omnibox_services_never_synthesize_predictions(self) -> None:
        build = source("components/omnibox/browser/BUILD.gn")
        scoring_service = source(
            "components/omnibox/browser/"
            "autocomplete_scoring_model_service.cc"
        )
        tail_header = source(
            "components/omnibox/browser/on_device_tail_model_executor.h"
        )
        tail_implementation = source(
            "components/omnibox/browser/"
            "on_device_tail_model_executor_wasm.cc"
        )

        target = braced_block(build, 'static_library("browser")')
        wasm_sources = braced_block(target, "if (is_wasm)")
        native_deps = braced_block(target, "if (!is_wasm)")
        self.assertIn(
            '"on_device_tail_model_executor_wasm.cc"', wasm_sources
        )
        for source_name in (
            "autocomplete_scoring_model_executor.cc",
            "autocomplete_scoring_model_executor.h",
            "autocomplete_scoring_model_handler.cc",
            "autocomplete_scoring_model_handler.h",
            "on_device_tail_model_executor.cc",
        ):
            with self.subTest(source_name=source_name):
                self.assertIn(f'"{source_name}"', wasm_sources)
        for dependency in (
            "//third_party/tflite",
            "//third_party/tflite_support",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, native_deps)
                self.assertNotIn(
                    dependency,
                    target.replace(native_deps, ""),
                )

        get_version = braced_block(
            scoring_service,
            "int AutocompleteScoringModelService::GetModelVersion() const",
        )
        batch_score = braced_block(
            scoring_service,
            "AutocompleteScoringModelService::"
            "BatchScoreAutocompleteUrlMatchesSync(",
        )
        availability = braced_block(
            scoring_service,
            "bool AutocompleteScoringModelService::"
            "UrlScoringModelAvailable()",
        )
        self.assertIn("return -1;", get_version)
        self.assertIn("return {};", batch_score)
        self.assertIn("return false;", availability)
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n    return false;",
            braced_block(tail_header, "bool IsReady() const"),
        )
        for init_signature in (
            "bool OnDeviceTailModelExecutor::Init()",
            "bool OnDeviceTailModelExecutor::Init(\n"
            "    const base::FilePath&",
        ):
            with self.subTest(init_signature=init_signature):
                self.assertIn(
                    "return false;",
                    braced_block(tail_implementation, init_signature),
                )
        generate = braced_block(
            tail_implementation,
            "OnDeviceTailModelExecutor::GenerateSuggestionsForPrefix(",
        )
        self.assertIn("return {};", generate)

    def test_page_annotations_return_explicit_unavailability(self) -> None:
        build = source("components/page_content_annotations/core/BUILD.gn")
        model_manager = source(
            "components/page_content_annotations/core/"
            "page_content_annotations_model_manager_wasm.cc"
        )
        classifier = source(
            "components/page_content_annotations/core/"
            "on_device_category_classifier_wasm.cc"
        )

        target = braced_block(build, 'static_library("core")')
        wasm_sources = braced_block(target, "if (is_wasm)")
        native_deps = braced_block(target, "if (!is_wasm)")
        unit_tests = braced_block(build, 'source_set("unit_tests")')
        for source_name in (
            "category_classifier_model_executor.cc",
            "category_classifier_model_handler.cc",
            "page_visibility_model_executor.cc",
            "page_visibility_model_handler.cc",
            "page_visibility_op_resolver.cc",
        ):
            with self.subTest(source_name=source_name):
                self.assertIn(f'"{source_name}"', wasm_sources)
        self.assertIn(
            '"on_device_category_classifier_wasm.cc"', wasm_sources
        )
        self.assertIn(
            '"page_content_annotations_model_manager_wasm.cc"',
            wasm_sources,
        )
        self.assertIn(
            "//third_party/tensorflow_models:tflite_custom_ops",
            native_deps,
        )
        self.assertNotIn(
            "//third_party/tensorflow_models:tflite_custom_ops",
            target.replace(native_deps, ""),
        )
        native_manager_test = braced_block(
            unit_tests, "if (!is_chromeos && !is_wasm)"
        )
        self.assertIn(
            '"page_content_annotations_model_manager_unittest.cc"',
            native_manager_test,
        )

        annotate = braced_block(
            model_manager,
            "PageContentAnnotationsModelManager::Annotate(",
        )
        model_info = braced_block(
            model_manager,
            "PageContentAnnotationsModelManager::GetModelInfoForType(",
        )
        availability = braced_block(
            model_manager,
            "PageContentAnnotationsModelManager::"
            "RequestAndNotifyWhenModelAvailable(",
        )
        self.assertIn("CreateEmptyBatchAnnotationResults(inputs)", annotate)
        self.assertIn("return std::nullopt;", model_info)
        self.assertIn("std::move(callback).Run(false);", availability)
        self.assertNotIn("OnCategoriesClassified", classifier)

    def test_segmentation_returns_no_model_or_result(self) -> None:
        build = source("components/segmentation_platform/internal/BUILD.gn")
        header = source(
            "components/segmentation_platform/internal/execution/"
            "optimization_guide/"
            "optimization_guide_segmentation_model_provider.h"
        )
        implementation = source(
            "components/segmentation_platform/internal/execution/"
            "optimization_guide/"
            "optimization_guide_segmentation_model_provider_wasm.cc"
        )

        target = braced_block(
            build,
            'static_library("optimization_guide_segmentation_handler")',
        )
        wasm_sources = braced_block(target, "if (is_wasm)")
        native_sources = braced_block(target, "} else")
        self.assertIn(
            '"execution/optimization_guide/'
            'optimization_guide_segmentation_model_provider_wasm.cc"',
            wasm_sources,
        )
        self.assertNotIn(
            "optimization_guide_segmentation_model_handler.cc",
            wasm_sources,
        )
        self.assertIn(
            "optimization_guide_segmentation_model_handler.cc",
            native_sources,
        )
        self.assertNotIn(
            "components/optimization_guide/core/inference", header
        )

        execute = braced_block(
            implementation,
            "OptimizationGuideSegmentationModelProvider::"
            "ExecuteModelWithInput(",
        )
        availability = braced_block(
            implementation,
            "bool OptimizationGuideSegmentationModelProvider::"
            "ModelAvailable()",
        )
        self.assertIn("std::nullopt", execute)
        self.assertIn("return false;", availability)


if __name__ == "__main__":
    unittest.main()

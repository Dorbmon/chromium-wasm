// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/autofill/core/browser/ml_model/field_classification_model_handler.h"

#include <utility>

#include "components/autofill/core/browser/heuristic_source.h"

namespace autofill {

namespace {

HeuristicSource HeuristicSourceForTarget(
    optimization_guide::proto::OptimizationTarget target) {
  return target == optimization_guide::proto::OptimizationTarget::
                       OPTIMIZATION_TARGET_PASSWORD_MANAGER_FORM_CLASSIFICATION
             ? HeuristicSource::kPasswordManagerMachineLearning
             : HeuristicSource::kAutofillMachineLearning;
}

}  // namespace

FieldClassificationModelHandler::FieldClassificationModelHandler(
    optimization_guide::OptimizationGuideModelProvider*,
    optimization_guide::proto::OptimizationTarget optimization_target,
    MlLogRouter*)
    : optimization_target_(optimization_target) {}

FieldClassificationModelHandler::~FieldClassificationModelHandler() = default;

void FieldClassificationModelHandler::GetModelPredictionsForForm(
    FormData,
    const GeoIpCountryCode&,
    bool,
    base::OnceCallback<void(ModelPredictions)> callback) {
  std::move(callback).Run(ModelPredictions(
      HeuristicSourceForTarget(optimization_target_), {}, {}));
}

void FieldClassificationModelHandler::GetModelPredictionsForForms(
    std::vector<FormData>,
    const GeoIpCountryCode&,
    bool,
    base::OnceCallback<void(std::vector<ModelPredictions>)> callback) {
  std::move(callback).Run({});
}

bool FieldClassificationModelHandler::ShouldApplySmallFormRules() const {
  return false;
}

base::CallbackListSubscription
FieldClassificationModelHandler::RegisterModelChangeCallback(
    ModelChangeCallbackList::CallbackType callback) {
  return model_change_callback_list_.Add(std::move(callback));
}

}  // namespace autofill

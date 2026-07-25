// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/page_content_annotations/core/page_content_annotations_model_manager.h"

#include <utility>

namespace page_content_annotations {

PageContentAnnotationsModelManager::PageContentAnnotationsModelManager(
    optimization_guide::OptimizationGuideModelProvider*) {}

PageContentAnnotationsModelManager::~PageContentAnnotationsModelManager() =
    default;

void PageContentAnnotationsModelManager::Annotate(
    BatchAnnotationCallback callback,
    const std::vector<std::string>& inputs,
    AnnotationType) {
  std::move(callback).Run(CreateEmptyBatchAnnotationResults(inputs));
}

std::optional<optimization_guide::ModelInfo>
PageContentAnnotationsModelManager::GetModelInfoForType(AnnotationType) const {
  return std::nullopt;
}

void PageContentAnnotationsModelManager::RequestAndNotifyWhenModelAvailable(
    AnnotationType,
    base::OnceCallback<void(bool)> callback) {
  std::move(callback).Run(false);
}

}  // namespace page_content_annotations

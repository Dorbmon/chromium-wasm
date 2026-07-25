// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/segmentation_platform/internal/execution/optimization_guide/optimization_guide_segmentation_model_provider.h"

#include <optional>
#include <utility>

#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"

namespace segmentation_platform {

OptimizationGuideSegmentationModelProvider::
    OptimizationGuideSegmentationModelProvider(
        optimization_guide::OptimizationGuideModelProvider* model_provider,
        scoped_refptr<base::SequencedTaskRunner> background_task_runner,
        proto::SegmentId segment_id)
    : ModelProvider(segment_id) {
  static_cast<void>(model_provider);
  static_cast<void>(background_task_runner);
}

OptimizationGuideSegmentationModelProvider::
    ~OptimizationGuideSegmentationModelProvider() = default;

void OptimizationGuideSegmentationModelProvider::InitAndFetchModel(
    const ModelUpdatedCallback&) {
  // M3 has no local model runtime, so no model update can be published.
}

void OptimizationGuideSegmentationModelProvider::ExecuteModelWithInput(
    const ModelProvider::Request&,
    ExecutionCallback callback) {
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(std::move(callback), std::nullopt));
}

bool OptimizationGuideSegmentationModelProvider::ModelAvailable() {
  return false;
}

}  // namespace segmentation_platform

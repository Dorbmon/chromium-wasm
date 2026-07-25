// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/page_content_annotations/core/on_device_category_classifier.h"

namespace page_content_annotations {

OnDeviceCategoryClassifier::OnDeviceCategoryClassifier(
    optimization_guide::OptimizationGuideModelProvider*,
    passage_embeddings::EmbedderMetadataProvider*) {}

OnDeviceCategoryClassifier::~OnDeviceCategoryClassifier() = default;

void OnDeviceCategoryClassifier::AddObserver(Observer* observer) {
  observers_.AddObserver(observer);
}

void OnDeviceCategoryClassifier::RemoveObserver(Observer* observer) {
  observers_.RemoveObserver(observer);
}

void OnDeviceCategoryClassifier::OnPageEmbeddingAvailable(
    const GURL&,
    ukm::SourceId,
    std::optional<passage_embeddings::Embedding>,
    std::vector<passage_embeddings::Embedding>) {}

void OnDeviceCategoryClassifier::EmbedderMetadataUpdated(
    passage_embeddings::EmbedderMetadata) {}

}  // namespace page_content_annotations

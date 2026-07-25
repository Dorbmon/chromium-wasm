// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/language_detection/core/language_detection_model.h"

#include <algorithm>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/task_traits.h"
#include "base/task/thread_pool.h"
#include "components/language_detection/core/constants.h"

namespace language_detection {

namespace {

Prediction UnsupportedPrediction() {
  return Prediction(kUnknownLanguageCode, 0.0f);
}

}  // namespace

Prediction TopPrediction(const std::vector<Prediction>& predictions) {
  auto prediction = std::max_element(predictions.begin(), predictions.end());
  CHECK(prediction != predictions.end());
  return *prediction;
}

LanguageDetectionModel::LanguageDetectionModel() = default;

LanguageDetectionModel::~LanguageDetectionModel() = default;

std::vector<Prediction> LanguageDetectionModel::Predict(
    std::u16string_view contents) const {
  static_cast<void>(contents);
  CHECK(IsAvailable()) << "language detection is unsupported on Wasm";
  return {UnsupportedPrediction()};
}

std::vector<Prediction> LanguageDetectionModel::PredictWithScan(
    std::u16string_view contents) const {
  static_cast<void>(contents);
  CHECK(IsAvailable()) << "language detection is unsupported on Wasm";
  return {UnsupportedPrediction()};
}

Prediction LanguageDetectionModel::DetectTopLanguage(
    std::u16string_view sampled_str) const {
  static_cast<void>(sampled_str);
  CHECK(IsAvailable()) << "language detection is unsupported on Wasm";
  return UnsupportedPrediction();
}

Prediction LanguageDetectionModel::PredictTopLanguageWithSamples(
    std::u16string_view contents) const {
  static_cast<void>(contents);
  CHECK(IsAvailable()) << "language detection is unsupported on Wasm";
  return UnsupportedPrediction();
}

void LanguageDetectionModel::UpdateWithFile(base::File model_file) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  model_file.Close();
  model_file_size_ = 0;
  NotifyModelLoaded();
}

void LanguageDetectionModel::UpdateWithFileAsync(
    base::File model_file,
    base::OnceClosure callback) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  base::ThreadPool::PostTaskAndReply(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::BEST_EFFORT},
      base::BindOnce(
          [](base::File model_file) { model_file.Close(); },
          std::move(model_file)),
      base::BindOnce(&LanguageDetectionModel::CompleteUnsupportedModelLoad,
                     weak_factory_.GetWeakPtr(), std::move(callback)));
}

void LanguageDetectionModel::CompleteUnsupportedModelLoad(
    base::OnceClosure callback) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  model_file_size_ = 0;
  NotifyModelLoaded();
  std::move(callback).Run();
}

bool LanguageDetectionModel::IsAvailable() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return false;
}

int64_t LanguageDetectionModel::GetModelSize() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return 0;
}

void LanguageDetectionModel::AddOnModelLoadedCallback(
    ModelLoadedCallback callback) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (loaded_ || model_loaded_callbacks_.size() >=
                     kMaxPendingCallbacksCount) {
    std::move(callback).Run(*this);
    return;
  }
  model_loaded_callbacks_.emplace_back(std::move(callback));
}

std::string LanguageDetectionModel::GetModelVersion() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return "unsupported-wasm";
}

void LanguageDetectionModel::NotifyModelLoaded() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  for (auto&& callback : model_loaded_callbacks_) {
    base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(
            [](ModelLoadedCallback callback,
               base::WeakPtr<LanguageDetectionModel> model) {
              if (model) {
                std::move(callback).Run(*model);
              }
            },
            std::move(callback), weak_factory_.GetWeakPtr()));
  }
  loaded_ = true;
  model_loaded_callbacks_.clear();
}

}  // namespace language_detection

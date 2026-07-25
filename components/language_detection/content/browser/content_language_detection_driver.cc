// Copyright 2024 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/language_detection/content/browser/content_language_detection_driver.h"

#include <memory>

#include "build/build_config.h"
#include "components/language_detection/core/browser/language_detection_model_provider.h"

namespace language_detection {

ContentLanguageDetectionDriver::ContentLanguageDetectionDriver(
    LanguageDetectionModelProvider* language_detection_model_provider)
    : language_detection_model_provider_(language_detection_model_provider) {}

ContentLanguageDetectionDriver::~ContentLanguageDetectionDriver() = default;

void ContentLanguageDetectionDriver::AddReceiver(
    mojo::PendingReceiver<mojom::ContentLanguageDetectionDriver> receiver) {
  receivers_.Add(this, std::move(receiver));
}

void ContentLanguageDetectionDriver::GetLanguageDetectionModel(
    GetLanguageDetectionModelCallback callback) {
#if BUILDFLAG(IS_WASM)
  // No model runtime is present in the M3 port. Complete the request
  // immediately instead of leaving it pending for a model that cannot arrive.
  std::move(callback).Run(base::File());
  return;
#else
  if (!language_detection_model_provider_) {
    std::move(callback).Run(base::File());
    return;
  }

  language_detection_model_provider_->GetLanguageDetectionModelFile(
      std::move(callback));
#endif
}

void ContentLanguageDetectionDriver::GetLanguageDetectionModelStatus(
    GetLanguageDetectionModelStatusCallback callback) {
#if BUILDFLAG(IS_WASM)
  std::move(callback).Run(mojom::LanguageDetectionModelStatus::kNotAvailable);
  return;
#else
  if (!language_detection_model_provider_) {
    // TODO (crbug.com/383022111): Pass the model availability based on the
    // real-time status of the model (if the model is unloaded).
    std::move(callback).Run(mojom::LanguageDetectionModelStatus::kNotAvailable);
    return;
  }
  if (language_detection_model_provider_->HasValidModelFile()) {
    std::move(callback).Run(mojom::LanguageDetectionModelStatus::kReadily);
    return;
  }
  std::move(callback).Run(mojom::LanguageDetectionModelStatus::kAfterDownload);
#endif
}

}  // namespace language_detection

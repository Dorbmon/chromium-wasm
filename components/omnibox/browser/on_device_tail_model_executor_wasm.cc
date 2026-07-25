// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "components/omnibox/browser/on_device_tail_model_executor.h"

#include <utility>

OnDeviceTailModelExecutor::ModelInput::ModelInput() = default;

OnDeviceTailModelExecutor::ModelInput::ModelInput(
    std::string prefix,
    std::string previous_query,
    size_t max_num_suggestions)
    : prefix(std::move(prefix)),
      previous_query(std::move(previous_query)),
      max_num_suggestions(max_num_suggestions) {}

OnDeviceTailModelExecutor::OnDeviceTailModelExecutor() = default;

OnDeviceTailModelExecutor::~OnDeviceTailModelExecutor() = default;

bool OnDeviceTailModelExecutor::Init() {
  executor_last_called_time_ = base::TimeTicks::Now();
  return false;
}

bool OnDeviceTailModelExecutor::Init(
    const base::FilePath&,
    const base::flat_set<base::FilePath>&,
    const ModelMetadata&) {
  executor_last_called_time_ = base::TimeTicks::Now();
  return false;
}

void OnDeviceTailModelExecutor::Reset() {}

std::vector<OnDeviceTailModelExecutor::Prediction>
OnDeviceTailModelExecutor::GenerateSuggestionsForPrefix(const ModelInput&) {
  executor_last_called_time_ = base::TimeTicks::Now();
  return {};
}

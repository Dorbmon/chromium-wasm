// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/process/process_iterator.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "process_iterator_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

ProcessIterator::ProcessIterator(const ProcessFilter* filter)
    : filter_(filter) {}

ProcessIterator::~ProcessIterator() = default;

bool ProcessIterator::CheckForNextProcess() {
  // The Wasm port has no OS process namespace to enumerate. In particular,
  // exposing the single in-process browser as a killable child would be
  // incorrect.
  return false;
}

bool NamedProcessIterator::IncludeEntry() {
  return false;
}

}  // namespace base

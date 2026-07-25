// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/threading/platform_thread_metrics.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "platform_thread_metrics_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

// static
std::unique_ptr<PlatformThreadMetrics>
PlatformThreadMetrics::CreateForCurrentThread() {
  return std::unique_ptr<PlatformThreadMetrics>(new PlatformThreadMetrics());
}

std::optional<TimeDelta> PlatformThreadMetrics::GetCumulativeCPUUsage() {
  // Browsers do not expose per-worker CPU time.
  return std::nullopt;
}

}  // namespace base

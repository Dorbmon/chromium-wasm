// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/profiler/module_cache.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "module_cache_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

// static
std::unique_ptr<const ModuleCache::Module> ModuleCache::CreateModuleForAddress(
    uintptr_t address) {
  // Native module metadata is not exposed to a WebAssembly application.
  return nullptr;
}

}  // namespace base

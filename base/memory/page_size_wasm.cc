// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/memory/page_size.h"

#include <emscripten/heap.h>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "page_size_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

size_t GetPageSize() {
  static_assert(WASM_PAGE_SIZE == 65536);
  return WASM_PAGE_SIZE;
}

}  // namespace base

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_GFX_GPU_FENCE_HANDLE_WASM_H_
#define UI_GFX_GPU_FENCE_HANDLE_WASM_H_

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "gpu_fence_handle_wasm.h is only for WebAssembly"
#endif

namespace gfx {

// Software-only Wasm does not support native GPU fences. This move-only token
// preserves the GpuFenceHandle type boundary while making it impossible to
// construct a handle that claims to provide synchronization.
class ScopedWasmGpuFence {
 public:
  ScopedWasmGpuFence() = default;
  ScopedWasmGpuFence(ScopedWasmGpuFence&&) = default;
  ScopedWasmGpuFence& operator=(ScopedWasmGpuFence&&) = default;
  ~ScopedWasmGpuFence() = default;

  ScopedWasmGpuFence(const ScopedWasmGpuFence&) = delete;
  ScopedWasmGpuFence& operator=(const ScopedWasmGpuFence&) = delete;

  bool is_valid() const { return false; }
};

}  // namespace gfx

#endif  // UI_GFX_GPU_FENCE_HANDLE_WASM_H_

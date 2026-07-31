// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/renderer/renderer_main_platform_delegate.h"

#include "base/logging.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "renderer_main_platform_delegate_wasm.cc is only for WebAssembly"
#endif

namespace content {

RendererMainPlatformDelegate::RendererMainPlatformDelegate(
    const MainFunctionParams& parameters) {}

RendererMainPlatformDelegate::~RendererMainPlatformDelegate() = default;

void RendererMainPlatformDelegate::PlatformInitialize() {}

void RendererMainPlatformDelegate::PlatformUninitialize() {}

bool RendererMainPlatformDelegate::EnableSandbox() {
  LOG(ERROR) << "Renderer process sandboxing is unsupported on WebAssembly.";
  return false;
}

}  // namespace content

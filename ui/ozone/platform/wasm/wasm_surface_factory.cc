// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_surface_factory.h"

#include "base/check.h"
#include "base/logging.h"
#include "ui/gfx/native_pixmap.h"
#include "ui/ozone/platform/wasm/wasm_surface_ozone_canvas.h"

namespace ui {

WasmSurfaceFactory::WasmSurfaceFactory()
    : canvas_active_(std::make_shared<std::atomic_bool>(false)) {}

WasmSurfaceFactory::~WasmSurfaceFactory() = default;

std::vector<gl::GLImplementationParts>
WasmSurfaceFactory::GetAllowedGLImplementations() {
  return {};
}

GLOzone* WasmSurfaceFactory::GetGLOzone(
    const gl::GLImplementationParts& implementation) {
  return nullptr;
}

std::unique_ptr<SurfaceOzoneCanvas>
WasmSurfaceFactory::CreateCanvasForWidget(gfx::AcceleratedWidget widget) {
  CHECK_NE(widget, gfx::kNullAcceleratedWidget);
  CHECK(!canvas_active_->exchange(true, std::memory_order_acq_rel))
      << "ozone_wasm M3 supports one live compositor surface";
  return std::make_unique<WasmSurfaceOzoneCanvas>(canvas_active_);
}

scoped_refptr<gfx::NativePixmap> WasmSurfaceFactory::CreateNativePixmap(
    gfx::AcceleratedWidget widget,
    gpu::VulkanDeviceQueue* device_queue,
    gfx::Size size,
    viz::SharedImageFormat format,
    gfx::BufferUsage usage,
    std::optional<gfx::Size> framebuffer_size) {
  LOG(ERROR) << "Native pixmaps are unsupported by ozone_wasm software mode";
  return nullptr;
}

}  // namespace ui

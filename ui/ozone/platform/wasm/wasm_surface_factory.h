// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_SURFACE_FACTORY_H_
#define UI_OZONE_PLATFORM_WASM_WASM_SURFACE_FACTORY_H_

#include <atomic>
#include <memory>

#include "ui/ozone/public/surface_factory_ozone.h"

namespace ui {

class WasmSurfaceFactory final : public SurfaceFactoryOzone {
 public:
  WasmSurfaceFactory();

  WasmSurfaceFactory(const WasmSurfaceFactory&) = delete;
  WasmSurfaceFactory& operator=(const WasmSurfaceFactory&) = delete;

  ~WasmSurfaceFactory() override;

  // SurfaceFactoryOzone:
  std::vector<gl::GLImplementationParts> GetAllowedGLImplementations() override;
  GLOzone* GetGLOzone(
      const gl::GLImplementationParts& implementation) override;
  std::unique_ptr<SurfaceOzoneCanvas> CreateCanvasForWidget(
      gfx::AcceleratedWidget widget) override;
  scoped_refptr<gfx::NativePixmap> CreateNativePixmap(
      gfx::AcceleratedWidget widget,
      gpu::VulkanDeviceQueue* device_queue,
      gfx::Size size,
      viz::SharedImageFormat format,
      gfx::BufferUsage usage,
      std::optional<gfx::Size> framebuffer_size) override;

 private:
  // M3 has one host canvas and therefore permits only one live compositor
  // surface. The shared flag remains valid if teardown destroys the platform
  // factory before the surface.
  std::shared_ptr<std::atomic_bool> canvas_active_;
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_SURFACE_FACTORY_H_

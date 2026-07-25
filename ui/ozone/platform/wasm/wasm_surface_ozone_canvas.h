// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_SURFACE_OZONE_CANVAS_H_
#define UI_OZONE_PLATFORM_WASM_WASM_SURFACE_OZONE_CANVAS_H_

#include <stdint.h>

#include <atomic>
#include <memory>
#include <vector>

#include "third_party/skia/include/core/SkRefCnt.h"
#include "ui/gfx/geometry/size.h"
#include "ui/ozone/public/surface_ozone_canvas.h"

class SkSurface;

namespace ui {

// Owns the software compositor framebuffer and presents stable RGBA copies to
// the browser main thread through the versioned host bridge.
class WasmSurfaceOzoneCanvas final : public SurfaceOzoneCanvas {
 public:
  explicit WasmSurfaceOzoneCanvas(
      std::shared_ptr<std::atomic_bool> canvas_active);

  WasmSurfaceOzoneCanvas(const WasmSurfaceOzoneCanvas&) = delete;
  WasmSurfaceOzoneCanvas& operator=(const WasmSurfaceOzoneCanvas&) = delete;

  ~WasmSurfaceOzoneCanvas() override;

  // SurfaceOzoneCanvas:
  SkCanvas* GetCanvas() override;
  void ResizeCanvas(const gfx::Size& viewport_size, float scale) override;
  void PresentCanvas(const gfx::Rect& damage) override;
  std::unique_ptr<gfx::VSyncProvider> CreateVSyncProvider() override;

 private:
  gfx::Size viewport_size_;
  sk_sp<SkSurface> surface_;
  std::vector<uint8_t> rgba_pixels_;
  std::shared_ptr<std::atomic_bool> canvas_active_;
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_SURFACE_OZONE_CANVAS_H_

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_surface_ozone_canvas.h"

#include <stddef.h>

#include <atomic>
#include <utility>

#include "base/check.h"
#include "base/numerics/checked_math.h"
#include "base/time/time.h"
#include "skia/ext/legacy_display_globals.h"
#include "third_party/skia/include/core/SkCanvas.h"
#include "third_party/skia/include/core/SkImageInfo.h"
#include "third_party/skia/include/core/SkSurface.h"
#include "third_party/skia/include/core/SkSurfaceProps.h"
#include "ui/gfx/geometry/rect.h"

namespace ui {

namespace {

constexpr uint32_t kHostBridgeVersion = 1;
constexpr int kMaximumCanvasDimension = 16384;
constexpr size_t kMaximumCanvasStorageBytes = 128 * 1024 * 1024;
std::atomic<uint64_t> g_next_frame_id{1};

extern "C" int chromium_wasm_present_frame(uint32_t bridge_version,
                                           const uint8_t* pixels,
                                           int width,
                                           int height,
                                           int stride,
                                           double frame_id,
                                           double timestamp_ms);
extern "C" int chromium_wasm_report_fatal(const char* message);

base::CheckedNumeric<size_t> CanvasByteSize(const gfx::Size& size) {
  base::CheckedNumeric<size_t> bytes(size.width());
  bytes *= size.height();
  bytes *= 4;
  return bytes;
}

}  // namespace

WasmSurfaceOzoneCanvas::WasmSurfaceOzoneCanvas(
    std::shared_ptr<std::atomic_bool> canvas_active)
    : canvas_active_(std::move(canvas_active)) {
  CHECK(canvas_active_);
  CHECK(canvas_active_->load(std::memory_order_acquire));
}

WasmSurfaceOzoneCanvas::~WasmSurfaceOzoneCanvas() {
  CHECK(canvas_active_->exchange(false, std::memory_order_acq_rel));
}

SkCanvas* WasmSurfaceOzoneCanvas::GetCanvas() {
  CHECK(surface_) << "ResizeCanvas must create a surface before drawing";
  return surface_->getCanvas();
}

void WasmSurfaceOzoneCanvas::ResizeCanvas(const gfx::Size& viewport_size,
                                          float scale) {
  CHECK_EQ(scale, 1.0f) << "M3 supports one fixed-density display";
  CHECK(!viewport_size.IsEmpty());
  CHECK_LE(viewport_size.width(), kMaximumCanvasDimension);
  CHECK_LE(viewport_size.height(), kMaximumCanvasDimension);

  base::CheckedNumeric<size_t> byte_size = CanvasByteSize(viewport_size);
  CHECK(byte_size.IsValid());
  base::CheckedNumeric<size_t> storage_size = byte_size;
  storage_size *= 2;
  CHECK(storage_size.IsValid());
  const size_t storage_bytes = storage_size.ValueOrDie<size_t>();
  CHECK_LE(storage_bytes, kMaximumCanvasStorageBytes);

  if (surface_ && viewport_size_ == viewport_size) {
    return;
  }

  // Release both old buffers before allocating either replacement so a resize
  // cannot transiently double the aggregate backing-store budget.
  surface_.reset();
  std::vector<uint8_t>().swap(rgba_pixels_);

  SkSurfaceProps props = skia::LegacyDisplayGlobals::GetSkSurfaceProps();
  surface_ = SkSurfaces::Raster(
      SkImageInfo::Make(viewport_size.width(), viewport_size.height(),
                        kRGBA_8888_SkColorType, kPremul_SkAlphaType),
      &props);
  CHECK(surface_);

  viewport_size_ = viewport_size;
  rgba_pixels_.resize(byte_size.ValueOrDie());
}

void WasmSurfaceOzoneCanvas::PresentCanvas(const gfx::Rect& damage) {
  CHECK(surface_);
  CHECK(gfx::Rect(viewport_size_).Contains(damage));

  base::CheckedNumeric<size_t> checked_stride(viewport_size_.width());
  checked_stride *= 4;
  CHECK(checked_stride.IsValid());
  const size_t stride = checked_stride.ValueOrDie();

  const SkImageInfo host_image_info =
      SkImageInfo::Make(viewport_size_.width(), viewport_size_.height(),
                        kRGBA_8888_SkColorType, kUnpremul_SkAlphaType);
  CHECK(surface_->readPixels(host_image_info, rgba_pixels_.data(), stride, 0,
                             0));

  const uint64_t frame_id =
      g_next_frame_id.fetch_add(1, std::memory_order_relaxed);
  const double timestamp_ms =
      base::TimeTicks::Now().since_origin().InMillisecondsF();
  const int result = chromium_wasm_present_frame(
      kHostBridgeVersion, rgba_pixels_.data(), viewport_size_.width(),
      viewport_size_.height(), static_cast<int>(stride),
      static_cast<double>(frame_id), timestamp_ms);
  if (result != 1) {
    chromium_wasm_report_fatal(
        "host canvas rejected an ozone_wasm compositor frame");
  }
  CHECK_EQ(result, 1) << "The host canvas rejected compositor frame "
                      << frame_id;
}

std::unique_ptr<gfx::VSyncProvider>
WasmSurfaceOzoneCanvas::CreateVSyncProvider() {
  return nullptr;
}

}  // namespace ui

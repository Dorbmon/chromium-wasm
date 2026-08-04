// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_WINDOW_MANAGER_H_
#define UI_OZONE_PLATFORM_WASM_WASM_WINDOW_MANAGER_H_

#include <vector>

#include "base/containers/id_map.h"
#include "base/memory/raw_ptr.h"
#include "base/threading/thread_checker.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/gfx/native_ui_types.h"

namespace ui {

class WasmWindow;

class WasmWindowManager {
 public:
  WasmWindowManager();

  WasmWindowManager(const WasmWindowManager&) = delete;
  WasmWindowManager& operator=(const WasmWindowManager&) = delete;

  ~WasmWindowManager();

  gfx::AcceleratedWidget AddWindow(WasmWindow* window);
  void RemoveWindow(gfx::AcceleratedWidget widget, WasmWindow* window);
  WasmWindow* GetWindow(gfx::AcceleratedWidget widget);
  gfx::AcceleratedWidget GetAcceleratedWidgetAtScreenPoint(
      const gfx::Point& point_in_dip);
  WasmWindow* GetWindowAtScreenPointInPixels(
      const gfx::Point& point_in_pixels);

  // The Ozone event source receives host-canvas physical pixels, while the
  // PlatformScreen API exposes screen positions in DIPs. Keep the one bounded
  // display scale alongside pixel-bound hit testing so every conversion uses
  // the same value during a resize notification.
  void SetDeviceScaleFactor(float device_scale_factor);
  // The host delivers pointer coordinates in physical pixels. Store the latest
  // accepted coordinate as DIPs so a scale transition preserves the same
  // logical hover for PlatformScreen until the next host record arrives.
  void SetCursorScreenPointInPixels(const gfx::Point& point_in_pixels);
  // Marks the host cursor as outside the sole Wasm logical display. The
  // screen point must remain outside all roots until the next accepted host
  // pointer record, so Aura cannot synthesize a stale in-canvas hover move.
  void SetCursorOutsideDisplay();
  gfx::Point GetCursorScreenPoint() const;
  gfx::Point GetCursorScreenPointInPixels() const;

  void SetPointerFocusedWindow(WasmWindow* window);
  WasmWindow* GetPointerFocusedWindow();
  // Returns the last non-captured pointer target and clears it before an exit
  // event can synchronously reenter Aura and destroy platform state.
  WasmWindow* TakePointerFocusedWindow();
  void SetKeyboardFocusedWindow(WasmWindow* window);
  WasmWindow* GetKeyboardFocusedWindow();
  bool IsKeyboardFocusedWidget(gfx::AcceleratedWidget widget);
  void SetPointerCapture(WasmWindow* window);
  void ReleasePointerCapture(WasmWindow* window);
  bool HasPointerCapture(WasmWindow* window);
  WasmWindow* GetPointerTarget(const gfx::Point& point);

 private:
  std::vector<raw_ptr<WasmWindow>> stacking_order_;
  base::IDMap<WasmWindow*> windows_;
  raw_ptr<WasmWindow> pointer_focused_window_ = nullptr;
  raw_ptr<WasmWindow> keyboard_focused_window_ = nullptr;
  raw_ptr<WasmWindow> pointer_capture_window_ = nullptr;
  gfx::PointF cursor_screen_point_in_dip_;
  float device_scale_factor_ = 1.0f;
  base::ThreadChecker thread_checker_;
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_WINDOW_MANAGER_H_

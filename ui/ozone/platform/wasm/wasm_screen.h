// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_SCREEN_H_
#define UI_OZONE_PLATFORM_WASM_WASM_SCREEN_H_

#include "base/memory/raw_ptr.h"
#include "ui/display/display_list.h"
#include "ui/ozone/public/platform_screen.h"

namespace ui {

class WasmWindowManager;

// The M3 host exposes one fixed-density canvas-backed display. Dynamic display
// configuration and host input arrive with the M4 Ozone gate.
class WasmScreen final : public PlatformScreen {
 public:
  explicit WasmScreen(WasmWindowManager* window_manager);

  WasmScreen(const WasmScreen&) = delete;
  WasmScreen& operator=(const WasmScreen&) = delete;

  ~WasmScreen() override;

  // PlatformScreen:
  const std::vector<display::Display>& GetAllDisplays() const override;
  display::Display GetPrimaryDisplay() const override;
  display::Display GetDisplayForAcceleratedWidget(
      gfx::AcceleratedWidget widget) const override;
  gfx::Point GetCursorScreenPoint() const override;
  gfx::AcceleratedWidget GetAcceleratedWidgetAtScreenPoint(
      const gfx::Point& point) const override;
  display::Display GetDisplayNearestPoint(
      const gfx::Point& point) const override;
  display::Display GetDisplayMatching(
      const gfx::Rect& match_rect) const override;
  bool IsScreenSaverActive() const override;
  base::TimeDelta CalculateIdleTime() const override;
  void AddObserver(display::DisplayObserver* observer) override;
  void RemoveObserver(display::DisplayObserver* observer) override;
  bool IsHeadless() const override;

 private:
  raw_ptr<WasmWindowManager> window_manager_;
  display::DisplayList display_list_;
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_SCREEN_H_

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_screen.h"

#include "base/check.h"
#include "base/notimplemented.h"
#include "base/time/time.h"
#include "ui/display/display.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/ozone/platform/wasm/wasm_window.h"
#include "ui/ozone/platform/wasm/wasm_window_manager.h"

namespace ui {

namespace {

constexpr int64_t kWasmDisplayId = 1;
constexpr gfx::Size kWasmDisplaySize(800, 600);

}  // namespace

WasmScreen::WasmScreen(WasmWindowManager* window_manager)
    : window_manager_(window_manager) {
  CHECK(window_manager_);

  display::Display display(kWasmDisplayId);
  display.SetScaleAndBounds(1.0f, gfx::Rect(kWasmDisplaySize));
  display.set_work_area(display.bounds());
  display_list_.AddDisplay(display, display::DisplayList::Type::PRIMARY);
}

WasmScreen::~WasmScreen() = default;

const std::vector<display::Display>& WasmScreen::GetAllDisplays() const {
  return display_list_.displays();
}

display::Display WasmScreen::GetPrimaryDisplay() const {
  const auto primary = display_list_.GetPrimaryDisplayIterator();
  CHECK(primary != display_list_.displays().end());
  return *primary;
}

display::Display WasmScreen::GetDisplayForAcceleratedWidget(
    gfx::AcceleratedWidget widget) const {
  if (WasmWindow* window = window_manager_->GetWindow(widget)) {
    return GetDisplayMatching(window->GetBoundsInPixels());
  }
  return GetPrimaryDisplay();
}

gfx::Point WasmScreen::GetCursorScreenPoint() const {
  NOTIMPLEMENTED_LOG_ONCE()
      << "Host cursor position is unsupported until the M4 input gate";
  return gfx::Point();
}

gfx::AcceleratedWidget WasmScreen::GetAcceleratedWidgetAtScreenPoint(
    const gfx::Point& point) const {
  return window_manager_->GetAcceleratedWidgetAtScreenPoint(point);
}

display::Display WasmScreen::GetDisplayNearestPoint(
    const gfx::Point& point) const {
  return GetPrimaryDisplay();
}

display::Display WasmScreen::GetDisplayMatching(
    const gfx::Rect& match_rect) const {
  return GetPrimaryDisplay();
}

bool WasmScreen::IsScreenSaverActive() const {
  return false;
}

base::TimeDelta WasmScreen::CalculateIdleTime() const {
  // With no M3 host input source, the canvas is treated as continuously active.
  return base::Seconds(0);
}

void WasmScreen::AddObserver(display::DisplayObserver* observer) {
  display_list_.AddObserver(observer);
}

void WasmScreen::RemoveObserver(display::DisplayObserver* observer) {
  display_list_.RemoveObserver(observer);
}

bool WasmScreen::IsHeadless() const {
  return false;
}

}  // namespace ui

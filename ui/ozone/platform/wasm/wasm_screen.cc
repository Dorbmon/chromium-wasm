// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_screen.h"

#include "base/check.h"
#include "base/time/time.h"
#include "ui/display/display.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"
#include "ui/ozone/platform/wasm/wasm_window.h"
#include "ui/ozone/platform/wasm/wasm_window_manager.h"

namespace ui {

namespace {

constexpr int64_t kWasmDisplayId = 1;
constexpr gfx::Size kWasmDisplaySize(800, 600);

}  // namespace

WasmScreen* WasmScreen::instance_ = nullptr;

WasmScreen::WasmScreen(WasmWindowManager* window_manager)
    : window_manager_(window_manager) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  CHECK(window_manager_);
  CHECK(!instance_);

  display::Display display(kWasmDisplayId);
  display.SetScaleAndBounds(1.0f, gfx::Rect(kWasmDisplaySize));
  display.set_work_area(display.bounds());
  display_list_.AddDisplay(display, display::DisplayList::Type::PRIMARY);
  instance_ = this;
}

WasmScreen::~WasmScreen() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  CHECK_EQ(instance_, this);
  instance_ = nullptr;
}

// static
bool WasmScreen::UpdatePrimaryDisplayForHostResize(
    const gfx::Size& size,
    float device_scale_factor) {
  WasmScreen* const screen = instance_;
  if (!screen) {
    return false;
  }

  DCHECK_CALLED_ON_VALID_SEQUENCE(screen->sequence_checker_);
  CHECK(!size.IsEmpty());
  CHECK(device_scale_factor == 1.0f || device_scale_factor == 2.0f);
  // PlatformScreen exposes DIPs. Update the manager before observers can
  // synchronously query cursor or widget-at-point state during this display
  // transaction.
  screen->window_manager_->SetDeviceScaleFactor(device_scale_factor);
  display::Display display = screen->GetPrimaryDisplay();
  display.SetScaleAndBounds(device_scale_factor, gfx::Rect(size));
  display.set_work_area(display.bounds());
  screen->display_list_.UpdateDisplay(display,
                                      display::DisplayList::Type::PRIMARY);
  return true;
}

const std::vector<display::Display>& WasmScreen::GetAllDisplays() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return display_list_.displays();
}

display::Display WasmScreen::GetPrimaryDisplay() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  const auto primary = display_list_.GetPrimaryDisplayIterator();
  CHECK(primary != display_list_.displays().end());
  return *primary;
}

display::Display WasmScreen::GetDisplayForAcceleratedWidget(
    gfx::AcceleratedWidget widget) const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (WasmWindow* window = window_manager_->GetWindow(widget)) {
    return GetDisplayMatching(window->GetBoundsInPixels());
  }
  return GetPrimaryDisplay();
}

gfx::Point WasmScreen::GetCursorScreenPoint() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return window_manager_->GetCursorScreenPoint();
}

gfx::AcceleratedWidget WasmScreen::GetAcceleratedWidgetAtScreenPoint(
    const gfx::Point& point) const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return window_manager_->GetAcceleratedWidgetAtScreenPoint(point);
}

display::Display WasmScreen::GetDisplayNearestPoint(
    const gfx::Point& point) const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return GetPrimaryDisplay();
}

display::Display WasmScreen::GetDisplayMatching(
    const gfx::Rect& match_rect) const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return GetPrimaryDisplay();
}

bool WasmScreen::IsScreenSaverActive() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return false;
}

base::TimeDelta WasmScreen::CalculateIdleTime() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  // With no M3 host input source, the canvas is treated as continuously active.
  return base::Seconds(0);
}

void WasmScreen::AddObserver(display::DisplayObserver* observer) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  display_list_.AddObserver(observer);
}

void WasmScreen::RemoveObserver(display::DisplayObserver* observer) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  display_list_.RemoveObserver(observer);
}

bool WasmScreen::IsHeadless() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return false;
}

}  // namespace ui

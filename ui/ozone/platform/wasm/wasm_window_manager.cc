// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_window_manager.h"

#include <algorithm>

#include "base/check.h"
#include "ui/gfx/geometry/point_conversions.h"
#include "ui/ozone/platform/wasm/wasm_window.h"

namespace ui {

WasmWindowManager::WasmWindowManager() = default;

WasmWindowManager::~WasmWindowManager() {
  DCHECK(thread_checker_.CalledOnValidThread());
}

gfx::AcceleratedWidget WasmWindowManager::AddWindow(WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  const gfx::AcceleratedWidget widget = windows_.Add(window);
  stacking_order_.push_back(window);
  return widget;
}

void WasmWindowManager::RemoveWindow(gfx::AcceleratedWidget widget,
                                     WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  DCHECK_EQ(window, windows_.Lookup(widget));
  auto stacking_window =
      std::find(stacking_order_.begin(), stacking_order_.end(), window);
  DCHECK(stacking_window != stacking_order_.end());
  stacking_order_.erase(stacking_window);
  // WasmWindow releases capture before removal. Keep this defensive clear for
  // partially constructed windows, whose delegates cannot be notified safely.
  if (pointer_capture_window_ == window) {
    pointer_capture_window_ = nullptr;
  }
  if (pointer_focused_window_ == window) {
    pointer_focused_window_ = nullptr;
  }
  if (keyboard_focused_window_ == window) {
    keyboard_focused_window_ = nullptr;
  }
  windows_.Remove(widget);
}

WasmWindow* WasmWindowManager::GetWindow(gfx::AcceleratedWidget widget) {
  DCHECK(thread_checker_.CalledOnValidThread());
  return windows_.Lookup(widget);
}

WasmWindow* WasmWindowManager::GetWindowAtScreenPointInPixels(
    const gfx::Point& point_in_pixels) {
  DCHECK(thread_checker_.CalledOnValidThread());
  for (auto it = stacking_order_.rbegin(); it != stacking_order_.rend();
       ++it) {
    WasmWindow* window = *it;
    if (window->IsVisible() &&
        window->GetBoundsInPixels().Contains(point_in_pixels)) {
      return window;
    }
  }
  return nullptr;
}

gfx::AcceleratedWidget WasmWindowManager::GetAcceleratedWidgetAtScreenPoint(
    const gfx::Point& point_in_dip) {
  DCHECK(thread_checker_.CalledOnValidThread());
  const gfx::Point point_in_pixels = gfx::ToFlooredPoint(
      gfx::ScalePoint(gfx::PointF(point_in_dip), device_scale_factor_));
  WasmWindow* window = GetWindowAtScreenPointInPixels(point_in_pixels);
  return window ? window->widget() : gfx::kNullAcceleratedWidget;
}

void WasmWindowManager::SetDeviceScaleFactor(float device_scale_factor) {
  DCHECK(thread_checker_.CalledOnValidThread());
  CHECK(device_scale_factor == 1.0f || device_scale_factor == 2.0f);
  // Store the cursor in DIPs so a DPR transition preserves a stationary hover
  // until the host delivers its next physical-coordinate pointer record.
  device_scale_factor_ = device_scale_factor;
}

void WasmWindowManager::SetCursorScreenPointInPixels(
    const gfx::Point& point_in_pixels) {
  DCHECK(thread_checker_.CalledOnValidThread());
  if (point_in_pixels.x() < 0 || point_in_pixels.y() < 0) {
    cursor_screen_point_in_dip_ = gfx::PointF(point_in_pixels);
    return;
  }
  cursor_screen_point_in_dip_ =
      gfx::ScalePoint(gfx::PointF(point_in_pixels),
                      1.0f / device_scale_factor_);
}

void WasmWindowManager::SetCursorOutsideDisplay() {
  DCHECK(thread_checker_.CalledOnValidThread());
  // WasmScreen exposes one display with an origin of (0, 0). DOM
  // `pointerleave` has no in-display coordinate, so use a point outside that
  // display rather than retaining the last valid host point. Aura consults
  // PlatformScreen before synthesizing hover moves after layout changes.
  cursor_screen_point_in_dip_ = gfx::PointF(-1, -1);
}

gfx::Point WasmWindowManager::GetCursorScreenPoint() const {
  DCHECK(thread_checker_.CalledOnValidThread());
  return gfx::ToFlooredPoint(cursor_screen_point_in_dip_);
}

gfx::Point WasmWindowManager::GetCursorScreenPointInPixels() const {
  DCHECK(thread_checker_.CalledOnValidThread());
  // Preserve the outside-display sentinel rather than rescaling it.
  if (cursor_screen_point_in_dip_.x() < 0 ||
      cursor_screen_point_in_dip_.y() < 0) {
    return gfx::ToFlooredPoint(cursor_screen_point_in_dip_);
  }
  return gfx::ToFlooredPoint(
      gfx::ScalePoint(cursor_screen_point_in_dip_, device_scale_factor_));
}

void WasmWindowManager::SetPointerFocusedWindow(WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  DCHECK(!window || windows_.Lookup(window->widget()) == window);
  pointer_focused_window_ = window;
}

WasmWindow* WasmWindowManager::GetPointerFocusedWindow() {
  DCHECK(thread_checker_.CalledOnValidThread());
  return pointer_focused_window_;
}

WasmWindow* WasmWindowManager::TakePointerFocusedWindow() {
  DCHECK(thread_checker_.CalledOnValidThread());
  WasmWindow* pointer_focused_window = pointer_focused_window_;
  pointer_focused_window_ = nullptr;
  return pointer_focused_window;
}

void WasmWindowManager::SetKeyboardFocusedWindow(WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  DCHECK(!window || windows_.Lookup(window->widget()) == window);
  keyboard_focused_window_ = window;
}

WasmWindow* WasmWindowManager::GetKeyboardFocusedWindow() {
  DCHECK(thread_checker_.CalledOnValidThread());
  return keyboard_focused_window_;
}

bool WasmWindowManager::IsKeyboardFocusedWidget(
    gfx::AcceleratedWidget widget) {
  DCHECK(thread_checker_.CalledOnValidThread());
  WasmWindow* window = GetKeyboardFocusedWindow();
  return window && window->widget() == widget && window->IsVisible();
}

void WasmWindowManager::SetPointerCapture(WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  CHECK(window);
  DCHECK_EQ(window, windows_.Lookup(window->widget()));
  if (pointer_capture_window_ == window) {
    return;
  }
  WasmWindow* old_capture = pointer_capture_window_;
  pointer_capture_window_ = window;
  if (old_capture) {
    old_capture->OnPointerCaptureLost();
  }
}

void WasmWindowManager::ReleasePointerCapture(WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  if (pointer_capture_window_ == window) {
    pointer_capture_window_ = nullptr;
  }
}

bool WasmWindowManager::HasPointerCapture(WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  return pointer_capture_window_ == window;
}

WasmWindow* WasmWindowManager::GetPointerTarget(const gfx::Point& point) {
  DCHECK(thread_checker_.CalledOnValidThread());
  if (pointer_capture_window_) {
    return pointer_capture_window_;
  }
  WasmWindow* window = GetWindowAtScreenPointInPixels(point);
  SetPointerFocusedWindow(window);
  return window;
}

}  // namespace ui

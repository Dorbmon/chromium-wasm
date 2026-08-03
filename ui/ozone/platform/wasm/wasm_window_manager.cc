// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_window_manager.h"

#include <algorithm>

#include "base/check.h"
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

WasmWindow* WasmWindowManager::GetWindowAtScreenPoint(
    const gfx::Point& point) {
  DCHECK(thread_checker_.CalledOnValidThread());
  for (auto it = stacking_order_.rbegin(); it != stacking_order_.rend();
       ++it) {
    WasmWindow* window = *it;
    if (window->IsVisible() && window->GetBoundsInPixels().Contains(point)) {
      return window;
    }
  }
  return nullptr;
}

gfx::AcceleratedWidget
WasmWindowManager::GetAcceleratedWidgetAtScreenPoint(
    const gfx::Point& point) {
  WasmWindow* window = GetWindowAtScreenPoint(point);
  return window ? window->widget() : gfx::kNullAcceleratedWidget;
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
  WasmWindow* window = GetWindowAtScreenPoint(point);
  SetPointerFocusedWindow(window);
  return window;
}

}  // namespace ui

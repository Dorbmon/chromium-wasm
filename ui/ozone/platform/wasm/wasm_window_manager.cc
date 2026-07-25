// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_window_manager.h"

#include "base/check.h"
#include "ui/ozone/platform/wasm/wasm_window.h"

namespace ui {

WasmWindowManager::WasmWindowManager() = default;

WasmWindowManager::~WasmWindowManager() {
  DCHECK(thread_checker_.CalledOnValidThread());
}

gfx::AcceleratedWidget WasmWindowManager::AddWindow(WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  return windows_.Add(window);
}

void WasmWindowManager::RemoveWindow(gfx::AcceleratedWidget widget,
                                     WasmWindow* window) {
  DCHECK(thread_checker_.CalledOnValidThread());
  DCHECK_EQ(window, windows_.Lookup(widget));
  windows_.Remove(widget);
}

WasmWindow* WasmWindowManager::GetWindow(gfx::AcceleratedWidget widget) {
  DCHECK(thread_checker_.CalledOnValidThread());
  return windows_.Lookup(widget);
}

gfx::AcceleratedWidget
WasmWindowManager::GetAcceleratedWidgetAtScreenPoint(
    const gfx::Point& point) {
  DCHECK(thread_checker_.CalledOnValidThread());
  for (base::IDMap<WasmWindow*>::const_iterator it(&windows_); !it.IsAtEnd();
       it.Advance()) {
    const WasmWindow* window = it.GetCurrentValue();
    if (window->IsVisible() && window->GetBoundsInPixels().Contains(point)) {
      return window->widget();
    }
  }
  return gfx::kNullAcceleratedWidget;
}

}  // namespace ui

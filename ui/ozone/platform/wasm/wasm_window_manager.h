// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_WINDOW_MANAGER_H_
#define UI_OZONE_PLATFORM_WASM_WASM_WINDOW_MANAGER_H_

#include "base/containers/id_map.h"
#include "base/threading/thread_checker.h"
#include "ui/gfx/geometry/point.h"
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
      const gfx::Point& point);

 private:
  base::IDMap<WasmWindow*> windows_;
  base::ThreadChecker thread_checker_;
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_WINDOW_MANAGER_H_

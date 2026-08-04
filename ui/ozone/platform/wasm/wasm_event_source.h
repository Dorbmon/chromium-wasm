// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_EVENT_SOURCE_H_
#define UI_OZONE_PLATFORM_WASM_WASM_EVENT_SOURCE_H_

#include <memory>

#include "base/memory/raw_ptr.h"
#include "base/threading/thread_checker.h"
#include "base/time/time.h"
#include "ui/events/event_constants.h"
#include "ui/events/keycodes/dom/dom_code.h"
#include "ui/events/platform/platform_event_source.h"
#include "ui/events/types/event_type.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/gfx/geometry/vector2d.h"

namespace ui {

class SystemInputInjector;
class WasmWindowManager;

// Translates host input records into normal Ozone native events. Records are
// delivered on Chromium's UI sequence; the JavaScript main thread only queues
// them through the Content host bridge.
class WasmPlatformEventSource final : public PlatformEventSource {
 public:
  explicit WasmPlatformEventSource(WasmWindowManager* window_manager);

  WasmPlatformEventSource(const WasmPlatformEventSource&) = delete;
  WasmPlatformEventSource& operator=(const WasmPlatformEventSource&) = delete;

  ~WasmPlatformEventSource() override;

  bool DispatchMouseEvent(EventType type,
                          const gfx::PointF& screen_location,
                          EventFlags flags,
                          EventFlags changed_button_flags,
                          int source_device_id);

  bool DispatchMouseWheelEvent(const gfx::PointF& screen_location,
                               const gfx::Vector2d& offset,
                               EventFlags flags,
                               int source_device_id);

  bool DispatchKeyEvent(EventType type,
                        DomCode physical_key,
                        EventFlags flags,
                        int source_device_id);

 private:
  base::TimeTicks NextMouseEventTime();

  raw_ptr<WasmWindowManager> window_manager_;
  base::ThreadChecker thread_checker_;
  base::TimeTicks last_mouse_event_time_;
};

std::unique_ptr<SystemInputInjector> CreateWasmSystemInputInjector(
    WasmPlatformEventSource* event_source);

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_EVENT_SOURCE_H_

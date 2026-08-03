// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_event_source.h"

#include <cmath>
#include <utility>

#include "base/check.h"
#include "base/notimplemented.h"
#include "ui/events/event.h"
#include "ui/events/event_utils.h"
#include "ui/events/platform/platform_event_dispatcher.h"
#include "ui/ozone/public/system_input_injector.h"
#include "ui/gfx/geometry/point.h"
#include "ui/ozone/platform/wasm/wasm_window.h"
#include "ui/ozone/platform/wasm/wasm_window_manager.h"

namespace ui {

namespace {

bool IsSupportedMouseButton(EventFlags button) {
  return button == EF_LEFT_MOUSE_BUTTON || button == EF_MIDDLE_MOUSE_BUTTON ||
         button == EF_RIGHT_MOUSE_BUTTON;
}

class WasmSystemInputInjector final : public SystemInputInjector {
 public:
  explicit WasmSystemInputInjector(WasmPlatformEventSource* event_source)
      : event_source_(event_source) {
    CHECK(event_source_);
  }

  WasmSystemInputInjector(const WasmSystemInputInjector&) = delete;
  WasmSystemInputInjector& operator=(const WasmSystemInputInjector&) =
      delete;

  ~WasmSystemInputInjector() override = default;

  void SetDeviceId(int device_id) override { device_id_ = device_id; }

  void MoveCursorTo(const gfx::PointF& location) override {
    location_ = location;
    event_source_->DispatchMouseEvent(EventType::kMouseMoved, location_,
                                      button_flags_, EF_NONE, device_id_);
  }

  void InjectMouseButton(EventFlags button, bool down) override {
    if (!IsSupportedMouseButton(button)) {
      NOTIMPLEMENTED_LOG_ONCE()
          << "ozone_wasm only supports primary, middle, and secondary mouse "
             "buttons";
      return;
    }
    if (down) {
      if (button_flags_ & button) {
        return;
      }
      button_flags_ |= button;
      event_source_->DispatchMouseEvent(EventType::kMousePressed, location_,
                                        button_flags_, button, device_id_);
      return;
    }

    if (!(button_flags_ & button)) {
      return;
    }
    // Chromium mouse-release events retain the changed button in `flags` for
    // dispatch, then clear it from the source state.
    event_source_->DispatchMouseEvent(EventType::kMouseReleased, location_,
                                      button_flags_, button, device_id_);
    button_flags_ &= ~button;
  }

  void InjectMouseWheel(int delta_x, int delta_y) override {
    NOTIMPLEMENTED_LOG_ONCE()
        << "ozone_wasm wheel injection is not implemented by the first M4 "
           "pointer slice";
  }

  void InjectKeyEvent(DomCode physical_key,
                      bool down,
                      bool suppress_auto_repeat) override {
    NOTIMPLEMENTED_LOG_ONCE()
        << "ozone_wasm keyboard injection is not implemented by the first M4 "
           "pointer slice";
  }

 private:
  raw_ptr<WasmPlatformEventSource> event_source_;
  gfx::PointF location_;
  EventFlags button_flags_ = EF_NONE;
  int device_id_ = ED_UNKNOWN_DEVICE;
};

}  // namespace

WasmPlatformEventSource::WasmPlatformEventSource(
    WasmWindowManager* window_manager)
    : window_manager_(window_manager) {
  CHECK(window_manager_);
}

WasmPlatformEventSource::~WasmPlatformEventSource() {
  DCHECK(thread_checker_.CalledOnValidThread());
}

bool WasmPlatformEventSource::DispatchMouseEvent(
    EventType type,
    const gfx::PointF& screen_location,
    EventFlags flags,
    EventFlags changed_button_flags,
    int source_device_id) {
  DCHECK(thread_checker_.CalledOnValidThread());
  if (PlatformEventSource::ShouldIgnoreNativePlatformEvents() ||
      !std::isfinite(screen_location.x()) ||
      !std::isfinite(screen_location.y())) {
    return false;
  }

  const gfx::Point root_location = gfx::ToFlooredPoint(screen_location);
  WasmWindow* target = window_manager_->GetPointerTarget(root_location);
  if (!target) {
    return false;
  }

  gfx::Point location = root_location;
  location.Offset(-target->GetBoundsInPixels().x(),
                  -target->GetBoundsInPixels().y());
  MouseEvent event(type, location, root_location, EventTimeForNow(), flags,
                   changed_button_flags);
  event.set_source_device_id(source_device_id);
  Event::DispatcherApi(&event).set_target(target);
  PlatformEventSource::DispatchEvent(&event);
  return true;
}

std::unique_ptr<SystemInputInjector> CreateWasmSystemInputInjector(
    WasmPlatformEventSource* event_source) {
  return std::make_unique<WasmSystemInputInjector>(event_source);
}

}  // namespace ui

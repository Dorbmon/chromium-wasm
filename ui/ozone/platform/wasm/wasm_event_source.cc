// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_event_source.h"

#include <cmath>
#include <utility>

#include "base/check.h"
#include "base/no_destructor.h"
#include "base/notimplemented.h"
#include "ui/events/event.h"
#include "ui/events/event_utils.h"
#include "ui/events/keycodes/dom/dom_code.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/events/ozone/layout/keyboard_layout_engine.h"
#include "ui/events/ozone/layout/keyboard_layout_engine_manager.h"
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

bool IsSupportedM4DomCode(DomCode dom_code) {
  return dom_code == DomCode::ARROW_DOWN || dom_code == DomCode::US_A ||
         dom_code == DomCode::BACKSPACE ||
         dom_code == DomCode::CONTROL_LEFT || dom_code == DomCode::US_C ||
         dom_code == DomCode::US_V;
}

raw_ptr<WasmPlatformEventSource>& GetWasmPlatformEventSource() {
  static base::NoDestructor<raw_ptr<WasmPlatformEventSource>> event_source;
  return *event_source;
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
    if (delta_x == 0 && delta_y == 0) {
      return;
    }
    event_source_->DispatchMouseWheelEvent(
        location_, gfx::Vector2d(delta_x, delta_y),
        button_flags_ | EF_PRECISION_SCROLLING_DELTA, device_id_);
  }

  void InjectKeyEvent(DomCode physical_key,
                      bool down,
                      bool suppress_auto_repeat) override {
    // The host accepts explicit trusted DOM keydown/keyup records. A
    // duplicate ArrowDown keydown with auto-repeat suppression disabled is
    // one already-observed DOM repeat, not a request to start a platform
    // repeat timer. The bounded printable slice maps through the Ozone
    // keyboard layout engine below. Backspace plus Ctrl+C/Ctrl+V do not make
    // this generic keyboard or host-synthesized text input to Blink.
    if (!IsSupportedM4DomCode(physical_key)) {
      NOTIMPLEMENTED_LOG_ONCE()
          << "ozone_wasm M4 raw-key input supports ArrowDown, KeyA, "
             "Backspace, and Ctrl+C/Ctrl+V only";
      return;
    }
    bool* key_down = &backspace_;
    if (physical_key == DomCode::ARROW_DOWN) {
      key_down = &arrow_down_;
    } else if (physical_key == DomCode::US_A) {
      key_down = &key_a_;
    } else if (physical_key == DomCode::CONTROL_LEFT) {
      key_down = &control_left_;
    } else if (physical_key == DomCode::US_C) {
      key_down = &key_c_;
    } else if (physical_key == DomCode::US_V) {
      key_down = &key_v_;
    } else {
      DCHECK_EQ(physical_key, DomCode::BACKSPACE);
    }
    if (*key_down == down) {
      if (down && !suppress_auto_repeat &&
          physical_key == DomCode::ARROW_DOWN) {
        event_source_->DispatchKeyEvent(EventType::kKeyPressed, physical_key,
                                        EF_IS_REPEAT, device_id_);
      }
      return;
    }
    if (down &&
        (physical_key == DomCode::US_C || physical_key == DomCode::US_V) &&
        !control_left_) {
      NOTIMPLEMENTED_LOG_ONCE()
          << "ozone_wasm only accepts KeyC and KeyV while ControlLeft is "
             "held";
      return;
    }
    // Keep Control in the flag state of its own press/release and every
    // bounded chord key. That is the normal Ozone modifier representation;
    // SystemInputInjector deliberately accepts physical keys only.
    const EventFlags flags =
        (control_left_ || physical_key == DomCode::CONTROL_LEFT)
            ? EF_CONTROL_DOWN
            : EF_NONE;
    *key_down = down;
    event_source_->DispatchKeyEvent(
        down ? EventType::kKeyPressed : EventType::kKeyReleased,
        physical_key, flags, device_id_);
  }

 private:
  raw_ptr<WasmPlatformEventSource> event_source_;
  gfx::PointF location_;
  EventFlags button_flags_ = EF_NONE;
  int device_id_ = ED_UNKNOWN_DEVICE;
  bool arrow_down_ = false;
  bool key_a_ = false;
  bool backspace_ = false;
  bool control_left_ = false;
  bool key_c_ = false;
  bool key_v_ = false;
};

}  // namespace

WasmPlatformEventSource::WasmPlatformEventSource(
    WasmWindowManager* window_manager)
    : window_manager_(window_manager) {
  CHECK(window_manager_);
  CHECK(!GetWasmPlatformEventSource());
  GetWasmPlatformEventSource() = this;
}

WasmPlatformEventSource::~WasmPlatformEventSource() {
  DCHECK(thread_checker_.CalledOnValidThread());
  CHECK_EQ(GetWasmPlatformEventSource(), this);
  GetWasmPlatformEventSource() = nullptr;
}

base::TimeTicks WasmPlatformEventSource::NextMouseEventTime() {
  DCHECK(thread_checker_.CalledOnValidThread());

  // A tooltip update returns asynchronously from Blink, so its timestamp is
  // also its correlation token at the browser endpoint. Emscripten's clock is
  // monotonic but may return the same tick for adjacent host records. Reserve
  // one microsecond for each accepted mouse event so no two records can share
  // that token.
  const base::TimeTicks now = EventTimeForNow();
  if (now <= last_mouse_event_time_) {
    last_mouse_event_time_ =
        last_mouse_event_time_ + base::Microseconds(1);
  } else {
    last_mouse_event_time_ = now;
  }
  return last_mouse_event_time_;
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
  // Keep PlatformScreen's cursor state in sync with every accepted host
  // pointer record, including records outside a Wasm window or during capture.
  // Aura consults this state while dispatching normal mouse and drag events.
  window_manager_->SetCursorScreenPointInPixels(root_location);
  WasmWindow* target = window_manager_->GetPointerTarget(root_location);
  if (!target) {
    return false;
  }

  if (type != EventType::kMouseExited) {
    last_mouse_source_device_id_ = source_device_id;
    has_last_mouse_event_ = true;
  }

  if (type == EventType::kMousePressed &&
      (changed_button_flags & EF_LEFT_MOUSE_BUTTON)) {
    // Pointer hover follows hit testing, but keyboard focus follows activation.
    target->Activate();
  }

  gfx::Point location = root_location;
  location.Offset(-target->GetBoundsInPixels().x(),
                  -target->GetBoundsInPixels().y());
  MouseEvent event(type, location, root_location, NextMouseEventTime(), flags,
                   changed_button_flags);
  event.set_source_device_id(source_device_id);
  Event::DispatcherApi(&event).set_target(target);
  PlatformEventSource::DispatchEvent(&event);
  return true;
}

bool WasmPlatformEventSource::DispatchMouseExitEvent() {
  DCHECK(thread_checker_.CalledOnValidThread());
  if (PlatformEventSource::ShouldIgnoreNativePlatformEvents() ||
      !has_last_mouse_event_) {
    return false;
  }

  // Clear the manager state before dispatch. Mouse exit processing can
  // synchronously reenter Aura and destroy the target window.
  WasmWindow* target = window_manager_->TakePointerFocusedWindow();
  const gfx::Point root_location =
      window_manager_->GetCursorScreenPointInPixels();
  window_manager_->SetCursorOutsideDisplay();
  has_last_mouse_event_ = false;
  if (!target || !target->IsVisible()) {
    return false;
  }

  gfx::Point location = root_location;
  location.Offset(-target->GetBoundsInPixels().x(),
                  -target->GetBoundsInPixels().y());
  MouseEvent event(EventType::kMouseExited, location, root_location,
                   NextMouseEventTime(), EF_NONE, EF_NONE);
  event.set_source_device_id(last_mouse_source_device_id_);
  Event::DispatcherApi(&event).set_target(target);
  PlatformEventSource::DispatchEvent(&event);
  return true;
}

bool WasmPlatformEventSource::DispatchMouseWheelEvent(
    const gfx::PointF& screen_location,
    const gfx::Vector2d& offset,
    EventFlags flags,
    int source_device_id) {
  DCHECK(thread_checker_.CalledOnValidThread());
  if (PlatformEventSource::ShouldIgnoreNativePlatformEvents() ||
      !std::isfinite(screen_location.x()) ||
      !std::isfinite(screen_location.y()) ||
      (offset.x() == 0 && offset.y() == 0)) {
    return false;
  }

  const gfx::Point root_location = gfx::ToFlooredPoint(screen_location);
  window_manager_->SetCursorScreenPointInPixels(root_location);
  WasmWindow* target = window_manager_->GetPointerTarget(root_location);
  if (!target) {
    return false;
  }

  gfx::Point location = root_location;
  location.Offset(-target->GetBoundsInPixels().x(),
                  -target->GetBoundsInPixels().y());
  MouseWheelEvent event(offset, location, root_location, EventTimeForNow(),
                        flags, EF_NONE);
  event.set_source_device_id(source_device_id);
  Event::DispatcherApi(&event).set_target(target);
  PlatformEventSource::DispatchEvent(&event);
  return true;
}

bool WasmPlatformEventSource::DispatchKeyEvent(EventType type,
                                               DomCode physical_key,
                                               EventFlags flags,
                                               int source_device_id) {
  DCHECK(thread_checker_.CalledOnValidThread());
  if (PlatformEventSource::ShouldIgnoreNativePlatformEvents() ||
      (type != EventType::kKeyPressed && type != EventType::kKeyReleased) ||
      !IsSupportedM4DomCode(physical_key)) {
    return false;
  }

  WasmWindow* target = window_manager_->GetKeyboardFocusedWindow();
  if (!target || !target->IsVisible()) {
    return false;
  }

  DomKey dom_key;
  KeyboardCode key_code;
  KeyboardLayoutEngine* layout_engine =
      KeyboardLayoutEngineManager::GetKeyboardLayoutEngine();
  if (!layout_engine ||
      !layout_engine->Lookup(physical_key, flags, &dom_key, &key_code)) {
    return false;
  }

  KeyEvent event(type, key_code, physical_key, flags, dom_key,
                 EventTimeForNow());
  event.set_source_device_id(source_device_id);
  Event::DispatcherApi(&event).set_target(target);
  PlatformEventSource::DispatchEvent(&event);
  return true;
}

std::unique_ptr<SystemInputInjector> CreateWasmSystemInputInjector(
    WasmPlatformEventSource* event_source) {
  return std::make_unique<WasmSystemInputInjector>(event_source);
}

bool DispatchWasmMouseExit() {
  WasmPlatformEventSource* event_source = GetWasmPlatformEventSource();
  return event_source && event_source->DispatchMouseExitEvent();
}

}  // namespace ui

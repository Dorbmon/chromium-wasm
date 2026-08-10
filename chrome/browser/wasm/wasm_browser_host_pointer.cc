// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_pointer.h"

#include <cstdint>
#include <memory>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "emscripten/emscripten.h"
#include "ui/events/event_constants.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/ozone/platform/wasm/wasm_event_source.h"
#include "ui/ozone/public/ozone_platform.h"
#include "ui/ozone/public/system_input_injector.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_host_pointer.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

// The host frame protocol permits a 16,384-pixel backing dimension, whose last
// valid zero-based pixel coordinate is 16,383. This keeps malformed C ABI
// arguments from reaching gfx/Aura while allowing the single Wasm display to
// grow or resize independently of this bridge.
constexpr int kMaximumHostPointerCoordinate = 16383;

enum class WasmBrowserHostPointerType {
  kMove = 0,
  kDown = 1,
  kUp = 2,
};

bool ParseWasmBrowserHostPointerType(int value,
                                     WasmBrowserHostPointerType* type) {
  CHECK(type);
  switch (value) {
    case static_cast<int>(WasmBrowserHostPointerType::kMove):
      *type = WasmBrowserHostPointerType::kMove;
      return true;
    case static_cast<int>(WasmBrowserHostPointerType::kDown):
      *type = WasmBrowserHostPointerType::kDown;
      return true;
    case static_cast<int>(WasmBrowserHostPointerType::kUp):
      *type = WasmBrowserHostPointerType::kUp;
      return true;
  }
  return false;
}

bool ParseWasmBrowserHostMouseButton(int value, ui::EventFlags* button) {
  CHECK(button);
  switch (value) {
    case 0:
      *button = ui::EF_LEFT_MOUSE_BUTTON;
      return true;
    case 1:
      *button = ui::EF_MIDDLE_MOUSE_BUTTON;
      return true;
    case 2:
      *button = ui::EF_RIGHT_MOUSE_BUTTON;
      return true;
  }
  return false;
}

class WasmBrowserHostPointerState {
 public:
  WasmBrowserHostPointerState() = default;
  WasmBrowserHostPointerState(const WasmBrowserHostPointerState&) = delete;
  WasmBrowserHostPointerState& operator=(const WasmBrowserHostPointerState&) =
      delete;
  ~WasmBrowserHostPointerState() = default;

  bool InitializeOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    CHECK(!input_injector_);

    std::unique_ptr<ui::SystemInputInjector> input_injector =
        ui::OzonePlatform::GetInstance()->CreateSystemInputInjector();
    if (!input_injector) {
      return false;
    }

    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    if (!task_runner) {
      return false;
    }

    {
      base::AutoLock lock(lock_);
      CHECK(!accepting_host_pointer_);
      CHECK(!task_runner_);
      ++generation_;
      accepting_host_pointer_ = true;
      task_runner_ = std::move(task_runner);
      pressed_buttons_ = ui::EF_NONE;
      has_unpressed_hover_target_ = false;
    }
    input_injector_ = std::move(input_injector);
    return true;
  }

  void ShutdownOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    {
      base::AutoLock lock(lock_);
      ++generation_;
      accepting_host_pointer_ = false;
      task_runner_ = nullptr;
      pressed_buttons_ = ui::EF_NONE;
      has_unpressed_hover_target_ = false;
    }
    input_injector_.reset();
  }

  bool PostPointer(WasmBrowserHostPointerType type,
                   const gfx::Point& location,
                   ui::EventFlags button) {
    base::AutoLock lock(lock_);
    if (!accepting_host_pointer_ || !task_runner_ ||
        !IsTransitionAllowedLocked(type, button)) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostPointerState::DispatchPointerOnUiThread,
                base::Unretained(this), type, location, button, generation))) {
      return false;
    }
    UpdatePressedButtonsLocked(type, button);
    UpdateHoverTargetLocked(type);
    return true;
  }

  bool PostMouseExit() {
    base::AutoLock lock(lock_);
    // A host exit represents only a prior accepted in-canvas unpressed hover.
    // It intentionally has no coordinate and cannot turn a captured drag
    // into a mouse exit. The shared trusted-DOM adapter independently enforces
    // the matching primary, no-capture PointerEvent state.
    if (!accepting_host_pointer_ || !task_runner_ ||
        pressed_buttons_ != ui::EF_NONE || !has_unpressed_hover_target_) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostPointerState::DispatchMouseExitOnUiThread,
                base::Unretained(this), generation))) {
      return false;
    }
    has_unpressed_hover_target_ = false;
    return true;
  }

 private:
  bool IsTransitionAllowedLocked(WasmBrowserHostPointerType type,
                                 ui::EventFlags button) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (type == WasmBrowserHostPointerType::kMove) {
      return true;
    }

    const bool button_is_pressed = (pressed_buttons_ & button) != 0;
    return type == WasmBrowserHostPointerType::kDown ? !button_is_pressed
                                                      : button_is_pressed;
  }

  void UpdatePressedButtonsLocked(WasmBrowserHostPointerType type,
                                  ui::EventFlags button)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (type == WasmBrowserHostPointerType::kDown) {
      pressed_buttons_ |= button;
    } else if (type == WasmBrowserHostPointerType::kUp) {
      pressed_buttons_ &= ~button;
    }
  }

  void UpdateHoverTargetLocked(WasmBrowserHostPointerType type)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (type) {
      case WasmBrowserHostPointerType::kDown:
        has_unpressed_hover_target_ = false;
        return;
      case WasmBrowserHostPointerType::kMove:
      case WasmBrowserHostPointerType::kUp:
        // A queued move or release identifies a valid canvas location at
        // which the Wasm Ozone event source may retain a hover target. Do not
        // claim that state while any injected button remains down.
        has_unpressed_hover_target_ = pressed_buttons_ == ui::EF_NONE;
        return;
    }
    NOTREACHED();
  }

  bool IsCurrentGeneration(uint64_t generation) const {
    base::AutoLock lock(lock_);
    return accepting_host_pointer_ && generation == generation_;
  }

  void DispatchPointerOnUiThread(WasmBrowserHostPointerType type,
                                 const gfx::Point& location,
                                 ui::EventFlags button,
                                 uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    if (!IsCurrentGeneration(generation) || !input_injector_) {
      return;
    }

    // SystemInputInjector accepts physical display pixels. The trusted DOM
    // adapter maps the canvas's CSS point to its backing store before this C
    // ABI is called, so no browser UI coordinate conversion leaks into JS.
    input_injector_->MoveCursorTo(gfx::PointF(location));
    switch (type) {
      case WasmBrowserHostPointerType::kMove:
        return;
      case WasmBrowserHostPointerType::kDown:
        input_injector_->InjectMouseButton(button, /*down=*/true);
        return;
      case WasmBrowserHostPointerType::kUp:
        input_injector_->InjectMouseButton(button, /*down=*/false);
        return;
    }
    NOTREACHED();
  }

  void DispatchMouseExitOnUiThread(uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    if (!IsCurrentGeneration(generation)) {
      return;
    }

    // This must stay an Ozone-Wasm boundary call rather than a synthetic
    // out-of-display move: the platform event source retains the last valid
    // target and clears it before Aura reentrancy. A disappeared target is a
    // harmless no-op after a valid host exit was queued.
    ui::DispatchWasmMouseExit();
  }

  mutable base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_
      GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_host_pointer_ GUARDED_BY(lock_) = false;
  ui::EventFlags pressed_buttons_ GUARDED_BY(lock_) = ui::EF_NONE;
  bool has_unpressed_hover_target_ GUARDED_BY(lock_) = false;
  std::unique_ptr<ui::SystemInputInjector> input_injector_;
};

WasmBrowserHostPointerState& GetWasmBrowserHostPointerState() {
  static base::NoDestructor<WasmBrowserHostPointerState> state;
  return *state;
}

}  // namespace

bool InitializeWasmBrowserHostPointer() {
  return GetWasmBrowserHostPointerState().InitializeOnUiThread();
}

void ShutdownWasmBrowserHostPointer() {
  GetWasmBrowserHostPointerState().ShutdownOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer(int type,
                                                            int x,
                                                            int y,
                                                            int button) {
  if (x < 0 || x > kMaximumHostPointerCoordinate || y < 0 ||
      y > kMaximumHostPointerCoordinate) {
    return 0;
  }

  WasmBrowserHostPointerType pointer_type;
  ui::EventFlags mouse_button;
  if (!ParseWasmBrowserHostPointerType(type, &pointer_type) ||
      !ParseWasmBrowserHostMouseButton(button, &mouse_button)) {
    return 0;
  }

  return GetWasmBrowserHostPointerState().PostPointer(
             pointer_type, gfx::Point(x, y), mouse_button)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_pointer_exit() {
  return GetWasmBrowserHostPointerState().PostMouseExit() ? 1 : 0;
}

}  // extern "C"

}  // namespace chrome

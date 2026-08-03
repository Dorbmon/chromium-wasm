// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_WINDOW_H_
#define UI_OZONE_PLATFORM_WASM_WASM_WINDOW_H_

#include <optional>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "ui/events/event_target.h"
#include "ui/events/platform/platform_event_dispatcher.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/native_ui_types.h"
#include "ui/platform_window/platform_window.h"

namespace ui {

class WasmWindowManager;

// M3 supplies the minimum single-canvas window lifecycle Aura needs. M4 adds
// host-pointer dispatch while keyboard, IME, and cursor integration remain off.
class WasmWindow final : public PlatformWindow,
                         public PlatformEventDispatcher,
                         public EventTarget {
 public:
  WasmWindow(PlatformWindowDelegate* delegate,
             WasmWindowManager* manager,
             const gfx::Rect& bounds);

  WasmWindow(const WasmWindow&) = delete;
  WasmWindow& operator=(const WasmWindow&) = delete;

  ~WasmWindow() override;

  // PlatformWindow:
  void Show(bool inactive) override;
  void Hide() override;
  void Close() override;
  bool IsVisible() const override;
  void PrepareForShutdown() override;
  void SetBoundsInPixels(const gfx::Rect& bounds) override;
  gfx::Rect GetBoundsInPixels() const override;
  void SetBoundsInDIP(const gfx::Rect& bounds) override;
  gfx::Rect GetBoundsInDIP() const override;
  void SetTitle(const std::u16string& title) override;
  void SetCapture() override;
  void ReleaseCapture() override;
  bool HasCapture() const override;
  void SetFullscreen(bool fullscreen, int64_t target_display_id) override;
  void Maximize() override;
  void Minimize() override;
  void Restore() override;
  PlatformWindowState GetPlatformWindowState() const override;
  void Activate() override;
  void Deactivate() override;
  void SetUseNativeFrame(bool use_native_frame) override;
  bool ShouldUseNativeFrame() const override;
  void SetCursor(scoped_refptr<PlatformCursor> cursor) override;
  void MoveCursorTo(const gfx::Point& location) override;
  void ConfineCursorToBounds(const gfx::Rect& bounds) override;
  void SetRestoredBoundsInDIP(const gfx::Rect& bounds) override;
  gfx::Rect GetRestoredBoundsInDIP() const override;
  void SetWindowIcons(const gfx::ImageSkia& window_icon,
                      const gfx::ImageSkia& app_icon) override;
  void SizeConstraintsChanged() override;

  // PlatformEventDispatcher:
  bool CanDispatchEvent(const PlatformEvent& event) override;
  uint32_t DispatchEvent(const PlatformEvent& event) override;

  // EventTarget:
  void OnPointerCaptureLost();

  bool CanAcceptEvent(const Event& event) override;
  EventTarget* GetParentTarget() override;
  std::unique_ptr<EventTargetIterator> GetChildIterator() const override;
  EventTargeter* GetEventTargeter() override;

  gfx::AcceleratedWidget widget() const { return widget_; }

 private:
  enum class ActivationState {
    kUnknown,
    kActive,
    kInactive,
  };

  void ZoomWindowBounds();
  void RestoreWindowBounds();
  void UpdateBounds(const gfx::Rect& bounds);
  void UpdateWindowState(PlatformWindowState new_window_state);
  uint32_t DispatchEventToDelegate(const PlatformEvent& event);

  raw_ptr<PlatformWindowDelegate> delegate_;
  raw_ptr<WasmWindowManager> manager_;
  gfx::Rect bounds_;
  gfx::AcceleratedWidget widget_ = gfx::kNullAcceleratedWidget;
  bool visible_ = false;
  std::optional<gfx::Rect> restored_bounds_;
  PlatformWindowState window_state_ = PlatformWindowState::kUnknown;
  ActivationState activation_state_ = ActivationState::kUnknown;
  base::WeakPtrFactory<WasmWindow> weak_ptr_factory_{this};
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_WINDOW_H_

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_window.h"

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/notimplemented.h"
#include "ui/base/cursor/platform_cursor.h"
#include "ui/display/screen.h"
#include "ui/display/types/display_constants.h"
#include "ui/events/event.h"
#include "ui/events/ozone/events_ozone.h"
#include "ui/events/platform/platform_event_source.h"
#include "ui/ozone/platform/wasm/wasm_window_manager.h"
#include "ui/platform_window/platform_window_delegate.h"

namespace ui {

WasmWindow::WasmWindow(PlatformWindowDelegate* delegate,
                       WasmWindowManager* manager,
                       const gfx::Rect& bounds)
    : delegate_(delegate), manager_(manager), bounds_(bounds) {
  CHECK(delegate_);
  CHECK(manager_);
  CHECK(!bounds_.IsEmpty());
  widget_ = manager_->AddWindow(this);
  CHECK(PlatformEventSource::GetInstance());
  PlatformEventSource::GetInstance()->AddPlatformEventDispatcher(this);
  delegate_->OnAcceleratedWidgetAvailable(widget_);
}

WasmWindow::~WasmWindow() {
  ReleaseCapture();
  if (PlatformEventSource::GetInstance()) {
    PlatformEventSource::GetInstance()->RemovePlatformEventDispatcher(this);
  }
  manager_->RemoveWindow(widget_, this);
}

void WasmWindow::Show(bool inactive) {
  visible_ = true;
  if (!inactive) {
    Activate();
  }
}

void WasmWindow::Hide() {
  visible_ = false;
  if (manager_->GetKeyboardFocusedWindow() == this) {
    manager_->SetKeyboardFocusedWindow(nullptr);
  }
  ReleaseCapture();
}

void WasmWindow::Close() {
  delegate_->OnClosed();
}

bool WasmWindow::IsVisible() const {
  return visible_;
}

void WasmWindow::PrepareForShutdown() {}

void WasmWindow::SetBoundsInPixels(const gfx::Rect& bounds) {
  CHECK(!bounds.IsEmpty());
  UpdateBounds(bounds);
}

gfx::Rect WasmWindow::GetBoundsInPixels() const {
  return bounds_;
}

void WasmWindow::SetBoundsInDIP(const gfx::Rect& bounds) {
  SetBoundsInPixels(delegate_->ConvertRectToPixels(bounds));
}

gfx::Rect WasmWindow::GetBoundsInDIP() const {
  return delegate_->ConvertRectToDIP(bounds_);
}

void WasmWindow::SetTitle(const std::u16string& title) {
  NOTIMPLEMENTED_LOG_ONCE()
      << "ozone_wasm M3 has no host-native title surface";
}

void WasmWindow::OnPointerCaptureLost() {
  delegate_->OnLostCapture();
}

void WasmWindow::SetCapture() {
  manager_->SetPointerCapture(this);
}

void WasmWindow::ReleaseCapture() {
  manager_->ReleasePointerCapture(this);
}

bool WasmWindow::HasCapture() const {
  return manager_->HasPointerCapture(const_cast<WasmWindow*>(this));
}

void WasmWindow::SetFullscreen(bool fullscreen, int64_t target_display_id) {
  DCHECK_EQ(target_display_id, display::kInvalidDisplayId);
  if (!delegate_->CanFullscreen()) {
    return;
  }

  base::WeakPtr<WasmWindow> weak_ptr = weak_ptr_factory_.GetWeakPtr();
  if (fullscreen) {
    if (window_state_ != PlatformWindowState::kMaximized &&
        window_state_ != PlatformWindowState::kFullScreen) {
      restored_bounds_ = bounds_;
    }
    ZoomWindowBounds();
    if (weak_ptr) {
      UpdateWindowState(PlatformWindowState::kFullScreen);
    }
    return;
  }

  if (window_state_ != PlatformWindowState::kFullScreen) {
    return;
  }
  RestoreWindowBounds();
  if (weak_ptr) {
    UpdateWindowState(PlatformWindowState::kNormal);
  }
}

void WasmWindow::Maximize() {
  if (!delegate_->CanMaximize() ||
      window_state_ == PlatformWindowState::kMaximized ||
      window_state_ == PlatformWindowState::kFullScreen) {
    return;
  }

  restored_bounds_ = bounds_;
  base::WeakPtr<WasmWindow> weak_ptr = weak_ptr_factory_.GetWeakPtr();
  ZoomWindowBounds();
  if (weak_ptr) {
    UpdateWindowState(PlatformWindowState::kMaximized);
  }
}

void WasmWindow::Minimize() {
  if (window_state_ == PlatformWindowState::kMinimized) {
    return;
  }

  base::WeakPtr<WasmWindow> weak_ptr = weak_ptr_factory_.GetWeakPtr();
  if (window_state_ == PlatformWindowState::kMaximized ||
      window_state_ == PlatformWindowState::kFullScreen) {
    RestoreWindowBounds();
    if (!weak_ptr) {
      return;
    }
  }
  UpdateWindowState(PlatformWindowState::kMinimized);
  if (weak_ptr) {
    Deactivate();
  }
}

void WasmWindow::Restore() {
  if (window_state_ == PlatformWindowState::kNormal) {
    return;
  }

  base::WeakPtr<WasmWindow> weak_ptr = weak_ptr_factory_.GetWeakPtr();
  RestoreWindowBounds();
  if (weak_ptr) {
    UpdateWindowState(PlatformWindowState::kNormal);
  }
}

PlatformWindowState WasmWindow::GetPlatformWindowState() const {
  return window_state_;
}

void WasmWindow::Activate() {
  manager_->SetKeyboardFocusedWindow(this);
  if (activation_state_ == ActivationState::kActive) {
    return;
  }
  activation_state_ = ActivationState::kActive;
  delegate_->OnActivationChanged(true);
}

void WasmWindow::Deactivate() {
  if (activation_state_ == ActivationState::kInactive) {
    return;
  }
  if (manager_->GetKeyboardFocusedWindow() == this) {
    manager_->SetKeyboardFocusedWindow(nullptr);
  }
  activation_state_ = ActivationState::kInactive;
  delegate_->OnActivationChanged(false);
}

void WasmWindow::SetUseNativeFrame(bool use_native_frame) {
  if (use_native_frame) {
    NOTIMPLEMENTED_LOG_ONCE()
        << "ozone_wasm provides no host-native window frame";
  }
}

bool WasmWindow::ShouldUseNativeFrame() const {
  return false;
}

void WasmWindow::SetCursor(scoped_refptr<PlatformCursor> cursor) {
  NOTIMPLEMENTED_LOG_ONCE()
      << "Host cursor updates are unsupported by the M4 pointer slice";
}

void WasmWindow::MoveCursorTo(const gfx::Point& location) {
  NOTIMPLEMENTED_LOG_ONCE()
      << "Host cursor movement is unsupported by the M4 pointer slice";
}

void WasmWindow::ConfineCursorToBounds(const gfx::Rect& bounds) {
  NOTIMPLEMENTED_LOG_ONCE()
      << "Host cursor confinement is unsupported by the M4 pointer slice";
}

void WasmWindow::SetRestoredBoundsInDIP(const gfx::Rect& bounds) {
  restored_bounds_ = delegate_->ConvertRectToPixels(bounds);
}

gfx::Rect WasmWindow::GetRestoredBoundsInDIP() const {
  return delegate_->ConvertRectToDIP(restored_bounds_.value_or(bounds_));
}

void WasmWindow::SetWindowIcons(const gfx::ImageSkia& window_icon,
                                const gfx::ImageSkia& app_icon) {
  NOTIMPLEMENTED_LOG_ONCE()
      << "ozone_wasm M3 has no host-native window icon surface";
}

void WasmWindow::SizeConstraintsChanged() {}

bool WasmWindow::CanDispatchEvent(const PlatformEvent& event) {
  return event && CanAcceptEvent(*event);
}

uint32_t WasmWindow::DispatchEvent(const PlatformEvent& event) {
  return event ? DispatchEventToDelegate(event) : POST_DISPATCH_NONE;
}

bool WasmWindow::CanAcceptEvent(const Event& event) {
  return event.target() == this;
}

EventTarget* WasmWindow::GetParentTarget() {
  return nullptr;
}

std::unique_ptr<EventTargetIterator> WasmWindow::GetChildIterator() const {
  return nullptr;
}

EventTargeter* WasmWindow::GetEventTargeter() {
  return nullptr;
}

uint32_t WasmWindow::DispatchEventToDelegate(const PlatformEvent& event) {
  const EventResult result = DispatchEventFromNativeUiEvent(
      event, base::BindOnce(&PlatformWindowDelegate::DispatchEvent,
                            base::Unretained(delegate_)));
  if (result == ER_UNHANDLED) {
    return POST_DISPATCH_NONE;
  }
  return (result & ER_SKIPPED) ? POST_DISPATCH_PERFORM_DEFAULT
                               : POST_DISPATCH_STOP_PROPAGATION;
}

void WasmWindow::ZoomWindowBounds() {
  const gfx::Rect display_bounds =
      display::Screen::Get()->GetDisplayMatching(bounds_).work_area();
  UpdateBounds(delegate_->ConvertRectToPixels(display_bounds));
}

void WasmWindow::RestoreWindowBounds() {
  if (!restored_bounds_) {
    return;
  }
  const gfx::Rect restored_bounds = *restored_bounds_;
  restored_bounds_.reset();
  UpdateBounds(restored_bounds);
}

void WasmWindow::UpdateBounds(const gfx::Rect& bounds) {
  const bool origin_changed = bounds_.origin() != bounds.origin();
  bounds_ = bounds;
  delegate_->OnBoundsChanged({origin_changed});
}

void WasmWindow::UpdateWindowState(PlatformWindowState new_window_state) {
  DCHECK_NE(window_state_, new_window_state);
  const PlatformWindowState old_window_state = window_state_;
  window_state_ = new_window_state;
  delegate_->OnWindowStateChanged(old_window_state, new_window_state);
}

}  // namespace ui

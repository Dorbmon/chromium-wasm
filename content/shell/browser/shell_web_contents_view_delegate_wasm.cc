// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <algorithm>
#include <memory>
#include <optional>

#include "base/memory/raw_ptr.h"
#include "content/public/browser/context_menu_params.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_view_delegate.h"
#include "content/shell/common/shell_switches.h"
#include "third_party/blink/public/common/context_menu_data/edit_flags.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/aura/client/window_types.h"
#include "ui/aura/window.h"
#include "ui/aura/window_delegate.h"
#include "ui/base/cursor/cursor.h"
#include "ui/base/hit_test.h"
#include "ui/compositor/paint_recorder.h"
#include "ui/events/event.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"

namespace content {
namespace {

// The entire enabled Copy row is deliberately a single opaque color. Besides
// making this small first menu implementation visually unambiguous, this gives
// the Wasm browser smoke test a stable on-canvas signal that is independent of
// text rasterization and the underlying page.
constexpr SkColor kEnabledCopyRowColor = 0xff0057b8;
constexpr SkColor kDisabledCopyRowColor = 0xff5f6368;
constexpr SkColor kCopyTextColor = SK_ColorWHITE;
constexpr int kMenuWidth = 160;
constexpr int kMenuHeight = 40;
constexpr int kCopyTextInset = 16;
constexpr int kCopyGlyphScale = 3;
constexpr int kCopyGlyphWidth = 3;
constexpr int kCopyGlyphHeight = 5;
constexpr int kCopyGlyphSpacing = 2;

// A small pixel Copy label deliberately avoids ui::FontList. The early Wasm
// platform has no native default UI font, and asking PlatformFontSkia to build
// one can produce an invalid zero-width font before Chrome resource font setup
// exists. These fixed glyphs keep the command visibly labelled without taking
// a second, unrelated native font dependency into this transient surface.
constexpr char kCopyGlyphs[] =
    "111100100100111"  // C
    "111101101101111"  // O
    "110101110100100"  // P
    "101101010010010"; // Y

void PaintCopyLabel(gfx::Canvas* canvas, const gfx::Size& menu_size) {
  constexpr int kGlyphCount = 4;
  constexpr int kGlyphPixels = kCopyGlyphWidth * kCopyGlyphHeight;
  constexpr int kGlyphDisplayWidth = kCopyGlyphWidth * kCopyGlyphScale;
  constexpr int kGlyphDisplayHeight = kCopyGlyphHeight * kCopyGlyphScale;
  constexpr int kLabelWidth =
      kGlyphCount * kGlyphDisplayWidth +
      (kGlyphCount - 1) * kCopyGlyphSpacing;

  const int origin_x = std::clamp(
      kCopyTextInset, 0, std::max(0, menu_size.width() - kLabelWidth));
  const int origin_y =
      std::max(0, (menu_size.height() - kGlyphDisplayHeight) / 2);
  for (int glyph = 0; glyph < kGlyphCount; ++glyph) {
    for (int row = 0; row < kCopyGlyphHeight; ++row) {
      for (int column = 0; column < kCopyGlyphWidth; ++column) {
        const int pixel =
            glyph * kGlyphPixels + row * kCopyGlyphWidth + column;
        if (kCopyGlyphs[pixel] != '1') {
          continue;
        }
        canvas->FillRect(
            gfx::Rect(origin_x + glyph * (kGlyphDisplayWidth +
                                          kCopyGlyphSpacing) +
                          column * kCopyGlyphScale,
                      origin_y + row * kCopyGlyphScale, kCopyGlyphScale,
                      kCopyGlyphScale),
            kCopyTextColor);
      }
    }
  }
}

class WasmContextMenuOverlay final : public aura::WindowDelegate {
 public:
  WasmContextMenuOverlay(WebContents* web_contents,
                         const ContextMenuParams& params)
      : web_contents_(web_contents),
        params_(params),
        copy_enabled_(params.edit_flags &
                      blink::ContextMenuDataEditFlags::kCanCopy) {}

  WasmContextMenuOverlay(const WasmContextMenuOverlay&) = delete;
  WasmContextMenuOverlay& operator=(const WasmContextMenuOverlay&) = delete;

  ~WasmContextMenuOverlay() override {
    Dismiss();
  }

  bool Show() {
    DCHECK(!showing_);

    aura::Window* web_contents_window = web_contents_->GetNativeView();
    aura::Window* root_window =
        web_contents_window ? web_contents_window->GetRootWindow() : nullptr;
    if (!root_window || root_window->bounds().IsEmpty()) {
      return false;
    }

    const gfx::Rect root_bounds(root_window->bounds().size());
    const gfx::Size menu_size(
        std::min(kMenuWidth, root_bounds.width()),
        std::min(kMenuHeight, root_bounds.height()));
    if (menu_size.IsEmpty()) {
      return false;
    }

    gfx::Point menu_origin(params_.x, params_.y);
    aura::Window::ConvertPointToTarget(web_contents_window, root_window,
                                       &menu_origin);
    menu_origin.set_x(std::clamp(menu_origin.x(), root_bounds.x(),
                                 root_bounds.right() - menu_size.width()));
    menu_origin.set_y(std::clamp(menu_origin.y(), root_bounds.y(),
                                 root_bounds.bottom() - menu_size.height()));
    menu_size_ = menu_size;
    const gfx::Rect menu_bounds(menu_origin, menu_size);

    window_ = std::make_unique<aura::Window>(
        this, aura::client::WINDOW_TYPE_MENU);
    // The view delegate owns the menu. The root only supplies its compositor
    // and must not delete this object while the delegate is still alive.
    window_->set_owned_by_parent(false);
    window_->SetName("WasmContextMenuOverlay");
    window_->Init(ui::LAYER_TEXTURED);
    root_window->AddChild(window_.get());
    // ShellPlatformDataAura's root FillLayout assigns a newly added child the
    // root size before this call. Keep the original local bounds rather than
    // the delegate's OnBoundsChanged() cache, which that layout callback has
    // already updated.
    window_->SetBounds(menu_bounds);
    root_window->StackChildAtTop(window_.get());
    window_->Show();

    showing_ = true;
    web_contents_->SetShowingContextMenu(true);
    window_->SetCapture();
    return true;
  }

  void Dismiss() {
    if (!showing_) {
      return;
    }

    // Mark the state before releasing capture: Aura synchronously calls
    // OnCaptureLost() as part of that operation.
    showing_ = false;
    if (window_ && window_->HasCapture()) {
      window_->ReleaseCapture();
    }
    if (window_) {
      window_->Hide();
    }
    NotifyContextMenuClosed();
  }

  bool is_showing() const { return showing_; }

 private:
  void NotifyContextMenuClosed() {
    web_contents_->SetShowingContextMenu(false);
    web_contents_->NotifyContextMenuClosed(params_.link_followed,
                                            params_.impression);
  }

  // aura::WindowDelegate:
  gfx::Size GetMinimumSize() const override { return gfx::Size(); }

  std::optional<gfx::Size> GetMaximumSize() const override {
    return std::nullopt;
  }

  void OnBoundsChanged(const gfx::Rect& old_bounds,
                       const gfx::Rect& new_bounds) override {
    menu_size_ = new_bounds.size();
  }

  gfx::NativeCursor GetCursor(const gfx::Point& point) override {
    return gfx::NativeCursor{};
  }

  int GetNonClientComponent(const gfx::Point& point) const override {
    return HTCLIENT;
  }

  bool ShouldDescendIntoChildForEventHandling(
      aura::Window* child,
      const gfx::Point& location) override {
    return true;
  }

  bool CanFocus() override {
    // Keep Blink's focused renderer widget focused so Copy targets the
    // selection that produced this menu.
    return false;
  }

  void OnCaptureLost() override { Dismiss(); }

  void OnMouseEvent(ui::MouseEvent* event) override {
    if (!showing_) {
      return;
    }

    event->SetHandled();
    if (event->type() != ui::EventType::kMouseReleased) {
      return;
    }

    const bool copy_clicked =
        copy_enabled_ &&
        gfx::Rect(menu_size_).Contains(event->location()) &&
        (event->changed_button_flags() & ui::EF_LEFT_MOUSE_BUTTON);
    if (copy_clicked) {
      web_contents_->Copy();
    }
    Dismiss();
  }

  void OnPaint(const ui::PaintContext& context) override {
    ui::PaintRecorder recorder(context, menu_size_);
    recorder.canvas()->DrawColor(copy_enabled_ ? kEnabledCopyRowColor
                                               : kDisabledCopyRowColor);
    PaintCopyLabel(recorder.canvas(), menu_size_);
  }

  void OnDeviceScaleFactorChanged(float old_device_scale_factor,
                                  float new_device_scale_factor) override {}

  void OnWindowDestroying(aura::Window* window) override {
    if (showing_) {
      showing_ = false;
      NotifyContextMenuClosed();
    }
  }

  void OnWindowDestroyed(aura::Window* window) override {}

  void OnWindowTargetVisibilityChanged(bool visible) override {
    if (!visible) {
      Dismiss();
    }
  }

  bool HasHitTestMask() const override { return false; }

  void GetHitTestMask(SkPath* mask) const override {}

  raw_ptr<WebContents> web_contents_;
  const ContextMenuParams params_;
  std::unique_ptr<aura::Window> window_;
  gfx::Size menu_size_;
  const bool copy_enabled_;
  bool showing_ = false;
};

class ShellWebContentsViewDelegateWasm final
    : public WebContentsViewDelegate {
 public:
  explicit ShellWebContentsViewDelegateWasm(WebContents* web_contents)
      : web_contents_(web_contents) {}

  ShellWebContentsViewDelegateWasm(
      const ShellWebContentsViewDelegateWasm&) = delete;
  ShellWebContentsViewDelegateWasm& operator=(
      const ShellWebContentsViewDelegateWasm&) = delete;

  ~ShellWebContentsViewDelegateWasm() override { DismissContextMenu(); }

  void ShowContextMenu(RenderFrameHost&,
                       const ContextMenuParams& params) override {
    if (switches::IsRunWebTestsSwitchPresent()) {
      return;
    }

    DismissContextMenu();
    auto context_menu =
        std::make_unique<WasmContextMenuOverlay>(web_contents_, params);
    if (context_menu->Show()) {
      context_menu_ = std::move(context_menu);
    }
  }

  void DismissContextMenu() override {
    if (context_menu_) {
      context_menu_->Dismiss();
    }
  }

  bool IsContextMenuShowingForTesting() override {
    return context_menu_ && context_menu_->is_showing();
  }

 private:
  raw_ptr<WebContents> web_contents_;
  std::unique_ptr<WasmContextMenuOverlay> context_menu_;
};

}  // namespace

std::unique_ptr<WebContentsViewDelegate> CreateShellWebContentsViewDelegate(
    WebContents* web_contents) {
  return std::make_unique<ShellWebContentsViewDelegateWasm>(web_contents);
}

}  // namespace content

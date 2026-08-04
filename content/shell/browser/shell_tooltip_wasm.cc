// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/shell/browser/shell_tooltip_wasm.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/scoped_observation.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "ui/aura/client/window_types.h"
#include "ui/aura/env.h"
#include "ui/aura/window.h"
#include "ui/aura/window_delegate.h"
#include "ui/aura/window_observer.h"
#include "ui/base/hit_test.h"
#include "ui/base/cursor/cursor.h"
#include "ui/compositor/layer_type.h"
#include "ui/compositor/paint_recorder.h"
#include "ui/events/event.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"
#include "ui/wm/public/tooltip_client.h"
#include "third_party/skia/include/core/SkColor.h"

namespace content {
namespace {

constexpr auto kTooltipHoverDelay = base::Milliseconds(500);
constexpr SkColor kTooltipBackgroundColor = 0xff202124;
constexpr SkColor kTooltipBorderColor = 0xff5f6368;
constexpr SkColor kTooltipTextColor = SK_ColorWHITE;
constexpr int kTooltipMaximumWidth = 260;
constexpr int kTooltipHorizontalInset = 8;
constexpr int kTooltipVerticalInset = 7;
constexpr int kTooltipCursorOffsetX = 12;
constexpr int kTooltipCursorOffsetY = 18;
constexpr int kTooltipGlyphWidth = 3;
constexpr int kTooltipGlyphHeight = 5;
constexpr int kTooltipGlyphScale = 2;
constexpr int kTooltipGlyphSpacing = 2;

constexpr std::string_view kUnknownGlyph = "111001010000010";
constexpr std::string_view kAGlyph = "010101111101101";
constexpr std::string_view kIGlyph = "111010010010111";
constexpr std::string_view kLGlyph = "100100100100111";
constexpr std::string_view kMGlyph = "101111111101101";
constexpr std::string_view kOGlyph = "111101101101111";
constexpr std::string_view kPGlyph = "110101110100100";
constexpr std::string_view kSGlyph = "111100111001111";
constexpr std::string_view kTGlyph = "111010010010010";
constexpr std::string_view kWGlyph = "101101101111101";

std::string_view GlyphForCharacter(char16_t character) {
  if (character >= u'a' && character <= u'z') {
    character = character - u'a' + u'A';
  }

  switch (character) {
    case u' ':
      return {};
    case u'A':
      return kAGlyph;
    case u'I':
      return kIGlyph;
    case u'L':
      return kLGlyph;
    case u'M':
      return kMGlyph;
    case u'O':
      return kOGlyph;
    case u'P':
      return kPGlyph;
    case u'S':
      return kSGlyph;
    case u'T':
      return kTGlyph;
    case u'W':
      return kWGlyph;
    default:
      return kUnknownGlyph;
  }
}

int GlyphDisplayWidth() {
  return kTooltipGlyphWidth * kTooltipGlyphScale;
}

int GlyphDisplayHeight() {
  return kTooltipGlyphHeight * kTooltipGlyphScale;
}

int MaximumGlyphCount() {
  return std::max(
      1, (kTooltipMaximumWidth - 2 * kTooltipHorizontalInset +
              kTooltipGlyphSpacing) /
             (GlyphDisplayWidth() + kTooltipGlyphSpacing));
}

int GlyphCountForText(const std::u16string& text) {
  return std::min(static_cast<int>(text.size()), MaximumGlyphCount());
}

gfx::Size TooltipSizeForText(const std::u16string& text) {
  const int glyph_count = GlyphCountForText(text);
  const int text_width = glyph_count * GlyphDisplayWidth() +
                         (glyph_count - 1) * kTooltipGlyphSpacing;
  return gfx::Size(text_width + 2 * kTooltipHorizontalInset,
                   GlyphDisplayHeight() + 2 * kTooltipVerticalInset);
}

void PaintTooltipLabel(gfx::Canvas* canvas,
                       const gfx::Size& tooltip_size,
                       const std::u16string& text) {
  const int glyph_count = GlyphCountForText(text);
  const int label_width = glyph_count * GlyphDisplayWidth() +
                          (glyph_count - 1) * kTooltipGlyphSpacing;
  const int origin_x =
      std::clamp(kTooltipHorizontalInset, 0,
                 std::max(0, tooltip_size.width() - label_width));
  const int origin_y = std::max(
      0, (tooltip_size.height() - GlyphDisplayHeight()) / 2);

  for (int glyph = 0; glyph < glyph_count; ++glyph) {
    const std::string_view glyph_pixels = GlyphForCharacter(text[glyph]);
    if (glyph_pixels.empty()) {
      continue;
    }
    for (int row = 0; row < kTooltipGlyphHeight; ++row) {
      for (int column = 0; column < kTooltipGlyphWidth; ++column) {
        const int pixel = row * kTooltipGlyphWidth + column;
        if (glyph_pixels[pixel] != '1') {
          continue;
        }
        canvas->FillRect(
            gfx::Rect(origin_x + glyph * (GlyphDisplayWidth() +
                                           kTooltipGlyphSpacing) +
                          column * kTooltipGlyphScale,
                      origin_y + row * kTooltipGlyphScale,
                      kTooltipGlyphScale, kTooltipGlyphScale),
            kTooltipTextColor);
      }
    }
  }
}

}  // namespace

class WasmTooltipController final : public wm::TooltipClient,
                                    public aura::WindowDelegate,
                                    public aura::WindowObserver {
 public:
  explicit WasmTooltipController(aura::Window* root_window)
      : root_window_(root_window) {
    CHECK(root_window_);
    CHECK_EQ(root_window_->GetRootWindow(), root_window_);
    wm::SetTooltipClient(root_window_, this);
    root_window_->AddPreTargetHandler(this);
  }

  WasmTooltipController(const WasmTooltipController&) = delete;
  WasmTooltipController& operator=(const WasmTooltipController&) = delete;

  ~WasmTooltipController() override {
    hover_timer_.Stop();
    hide_timer_.Stop();
    observed_window_observation_.Reset();
    root_window_->RemovePreTargetHandler(this);
    if (wm::GetTooltipClient(root_window_) == this) {
      wm::SetTooltipClient(root_window_, nullptr);
    }
    HideTooltipWindow();
    tooltip_window_.reset();
  }

 private:
  // wm::TooltipClient:
  int GetMaxWidth(const gfx::Point&) const override {
    return kTooltipMaximumWidth;
  }

  void UpdateTooltip(aura::Window* target) override {
    // RenderWidgetHostViewAura calls this after it updates its normal Aura
    // tooltip property. Its content Aura window is not necessarily the same
    // Aura target seen by the root's pre-target mouse handler, so correlate at
    // the shared root rather than dropping the normal Blink callback. Do not
    // revive an older renderer callback after the pointer has moved to a
    // different Aura target.
    if (!target || target != observed_window_ ||
        target->GetRootWindow() != root_window_) {
      return;
    }
    ScheduleTooltipFromWindow(target);
  }

  void UpdateTooltipFromKeyboard(const gfx::Rect&,
                                 aura::Window*) override {
    // Keyboard-triggered tooltips need a real focus-anchor and typography
    // policy. Keep that path explicitly absent rather than pretending a
    // pointer-relative overlay is a keyboard tooltip.
    HideAndCancelTooltip();
  }

  bool IsTooltipSetFromKeyboard(aura::Window*) override { return false; }

  void SetHideTooltipTimeout(aura::Window* target,
                             base::TimeDelta timeout) override {
    if (target == observed_window_) {
      hide_timeout_ = timeout;
    }
  }

  void SetTooltipsEnabled(bool enable) override {
    if (tooltips_enabled_ == enable) {
      return;
    }
    tooltips_enabled_ = enable;
    if (!tooltips_enabled_) {
      HideAndCancelTooltip();
    }
  }

  // ui::EventHandler:
  void OnKeyEvent(ui::KeyEvent*) override { HideAndCancelTooltip(); }

  void OnMouseEvent(ui::MouseEvent* event) override {
    switch (event->type()) {
      case ui::EventType::kMouseMoved: {
        if (event->IsSynthesized()) {
          return;
        }
        if (aura::Env::GetInstance()->IsMouseButtonDown()) {
          HideAndCancelTooltip();
          UpdateObservedWindow(nullptr);
          return;
        }
        aura::Window* const target =
            static_cast<aura::Window*>(event->target());
        if (tooltips_enabled_ && allow_mouse_tooltips_ &&
            has_last_mouse_location_ && target == observed_window_ &&
            event->root_location() == last_mouse_location_) {
          // Blink coalesces tooltip decisions for an unchanged cursor point.
          // Preserve a pending hover timer or visible overlay because the
          // duplicate move will not necessarily send another tooltip callback.
          return;
        }
        HideTooltipWindow();
        tooltip_text_.clear();
        last_mouse_location_ = event->root_location();
        has_last_mouse_location_ = true;
        allow_mouse_tooltips_ = true;
        UpdateObservedWindow(target);
        // Do not infer the title from the whole renderer Aura window after a
        // move. The normal RenderWidgetHostViewAura::UpdateTooltip callback
        // supplies the current Blink title and starts the bounded timer.
        return;
      }
      case ui::EventType::kMouseDragged:
        HideAndCancelTooltip();
        UpdateObservedWindow(nullptr);
        return;
      case ui::EventType::kMouseCaptureChanged:
        HideAndCancelTooltip();
        UpdateObservedWindow(nullptr);
        return;
      case ui::EventType::kMouseExited:
      case ui::EventType::kMousePressed:
      case ui::EventType::kMouseReleased:
      case ui::EventType::kMousewheel:
        HideAndCancelTooltip();
        if (event->type() == ui::EventType::kMouseExited) {
          UpdateObservedWindow(nullptr);
        }
        return;
      default:
        return;
    }
  }

  void OnScrollEvent(ui::ScrollEvent*) override {
    HideAndCancelTooltip();
  }

  void OnTouchEvent(ui::TouchEvent*) override { HideAndCancelTooltip(); }

  void OnGestureEvent(ui::GestureEvent*) override {
    HideAndCancelTooltip();
  }

  void OnCancelMode(ui::CancelModeEvent*) override {
    HideAndCancelTooltip();
  }

  std::string_view GetLogContext() const override {
    return "WasmTooltipController";
  }

  // aura::WindowObserver and aura::WindowDelegate:
  void OnWindowDestroying(aura::Window* window) override {
    if (window == observed_window_) {
      observed_window_observation_.Reset();
      observed_window_ = nullptr;
      HideAndCancelTooltip();
    }
    if (window == tooltip_window_.get())
      hover_timer_.Stop();
  }

  void OnWindowDestroyed(aura::Window*) override {}

  gfx::Size GetMinimumSize() const override { return gfx::Size(); }

  std::optional<gfx::Size> GetMaximumSize() const override {
    return std::nullopt;
  }

  void OnBoundsChanged(const gfx::Rect&,
                       const gfx::Rect& new_bounds) override {
    tooltip_size_ = new_bounds.size();
  }

  gfx::NativeCursor GetCursor(const gfx::Point&) override {
    return gfx::NativeCursor{};
  }

  int GetNonClientComponent(const gfx::Point&) const override {
    return HTCLIENT;
  }

  bool ShouldDescendIntoChildForEventHandling(
      aura::Window*,
      const gfx::Point&) override {
    return false;
  }

  bool CanFocus() override { return false; }

  void OnCaptureLost() override { HideAndCancelTooltip(); }

  void OnPaint(const ui::PaintContext& context) override {
    ui::PaintRecorder recorder(context, tooltip_size_);
    recorder.canvas()->DrawColor(kTooltipBackgroundColor);
    recorder.canvas()->FillRect(
        gfx::Rect(tooltip_size_.width(), 1), kTooltipBorderColor);
    recorder.canvas()->FillRect(
        gfx::Rect(0, std::max(0, tooltip_size_.height() - 1),
                  tooltip_size_.width(), 1),
        kTooltipBorderColor);
    recorder.canvas()->FillRect(
        gfx::Rect(0, 0, 1, tooltip_size_.height()), kTooltipBorderColor);
    recorder.canvas()->FillRect(
        gfx::Rect(std::max(0, tooltip_size_.width() - 1), 0, 1,
                  tooltip_size_.height()),
        kTooltipBorderColor);
    PaintTooltipLabel(recorder.canvas(), tooltip_size_, tooltip_text_);
  }

  void OnDeviceScaleFactorChanged(float, float) override {}

  void OnWindowTargetVisibilityChanged(bool visible) override {
    if (!visible)
      hover_timer_.Stop();
  }

  bool HasHitTestMask() const override { return false; }

  void GetHitTestMask(SkPath*) const override {}

  void UpdateObservedWindow(aura::Window* target) {
    if (target == observed_window_) {
      return;
    }
    observed_window_observation_.Reset();
    observed_window_ = target;
    if (observed_window_) {
      observed_window_observation_.Observe(observed_window_);
    }
  }

  void ScheduleTooltipFromWindow(aura::Window* target) {
    HideTooltipWindow();
    tooltip_text_.clear();
    if (!tooltips_enabled_ || !allow_mouse_tooltips_ || !target ||
        target != observed_window_ ||
        target->GetRootWindow() != root_window_ ||
        !has_last_mouse_location_) {
      return;
    }

    tooltip_text_ = wm::GetTooltipText(target);
    if (tooltip_text_.empty()) {
      return;
    }

    hover_timer_.Start(
        FROM_HERE, kTooltipHoverDelay,
        base::BindOnce(&WasmTooltipController::ShowTooltip,
                       weak_ptr_factory_.GetWeakPtr()));
  }

  void ShowTooltip() {
    if (!tooltips_enabled_ || !observed_window_ || tooltip_text_.empty() ||
        !has_last_mouse_location_ || root_window_->bounds().IsEmpty()) {
      return;
    }
    // The title update crosses the renderer/browser boundary. Confirm that
    // the current observed Aura window still advertises the text that armed
    // this timer before painting, so a later clear cannot revive stale text.
    if (wm::GetTooltipText(observed_window_) != tooltip_text_) {
      HideTooltipWindow();
      tooltip_text_.clear();
      return;
    }
    if (aura::Env::GetInstance()->IsMouseButtonDown()) {
      HideAndCancelTooltip();
      return;
    }

    const gfx::Rect root_bounds(root_window_->bounds().size());
    const gfx::Size preferred_size = TooltipSizeForText(tooltip_text_);
    const gfx::Size tooltip_size(
        std::min(preferred_size.width(), root_bounds.width()),
        std::min(preferred_size.height(), root_bounds.height()));
    if (tooltip_size.IsEmpty()) {
      return;
    }
    gfx::Point tooltip_origin(last_mouse_location_.x() + kTooltipCursorOffsetX,
                              last_mouse_location_.y() + kTooltipCursorOffsetY);
    tooltip_origin.set_x(
        std::clamp(tooltip_origin.x(), root_bounds.x(),
                   root_bounds.right() - tooltip_size.width()));
    tooltip_origin.set_y(
        std::clamp(tooltip_origin.y(), root_bounds.y(),
                   root_bounds.bottom() - tooltip_size.height()));

    EnsureTooltipWindow();
    tooltip_size_ = tooltip_size;
    // Root FillLayout assigns every newly-added child the root bounds. Set the
    // intended local overlay bounds only after AddChild() has run.
    tooltip_window_->SetBounds(gfx::Rect(tooltip_origin, tooltip_size));
    root_window_->StackChildAtTop(tooltip_window_.get());
    tooltip_window_->Show();

    if (hide_timeout_.is_positive()) {
      hide_timer_.Start(
          FROM_HERE, hide_timeout_,
          base::BindOnce(&WasmTooltipController::HideTooltipWindow,
                         weak_ptr_factory_.GetWeakPtr()));
    }
  }

  void EnsureTooltipWindow() {
    if (tooltip_window_) {
      return;
    }

    tooltip_window_ = std::make_unique<aura::Window>(
        this, aura::client::WINDOW_TYPE_TOOLTIP);
    // This controller owns the transient child. The root only contributes its
    // compositor and must never delete a live controller-owned overlay.
    tooltip_window_->set_owned_by_parent(false);
    tooltip_window_->SetName("WasmTooltipOverlay");
    tooltip_window_->Init(ui::LAYER_TEXTURED);
    tooltip_window_->SetEventTargetingPolicy(aura::EventTargetingPolicy::kNone);
    root_window_->AddChild(tooltip_window_.get());
  }

  void HideTooltipWindow() {
    hover_timer_.Stop();
    hide_timer_.Stop();
    if (tooltip_window_) {
      tooltip_window_->Hide();
    }
  }

  void HideAndCancelTooltip() {
    HideTooltipWindow();
    tooltip_text_.clear();
    hide_timeout_ = base::TimeDelta();
    allow_mouse_tooltips_ = false;
  }

  raw_ptr<aura::Window> root_window_;
  raw_ptr<aura::Window> observed_window_ = nullptr;
  base::ScopedObservation<aura::Window, aura::WindowObserver>
      observed_window_observation_{this};
  std::unique_ptr<aura::Window> tooltip_window_;
  base::OneShotTimer hover_timer_;
  base::OneShotTimer hide_timer_;
  gfx::Point last_mouse_location_;
  gfx::Size tooltip_size_;
  std::u16string tooltip_text_;
  base::TimeDelta hide_timeout_;
  bool has_last_mouse_location_ = false;
  bool tooltips_enabled_ = true;
  bool allow_mouse_tooltips_ = true;
  base::WeakPtrFactory<WasmTooltipController> weak_ptr_factory_{this};
};

void WasmTooltipControllerDeleter::operator()(
    WasmTooltipController* controller) const {
  delete controller;
}

WasmTooltipControllerPtr CreateWasmTooltipController(
    aura::Window* root_window) {
  return WasmTooltipControllerPtr(new WasmTooltipController(root_window));
}

}  // namespace content

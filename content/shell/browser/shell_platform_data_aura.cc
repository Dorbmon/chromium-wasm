// Copyright 2014 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/shell/browser/shell_platform_data_aura.h"

#include <memory>

#include "base/memory/raw_ptr.h"
#include "base/observer_list.h"
#include "base/scoped_observation.h"
#include "build/build_config.h"
#include "ui/aura/client/cursor_shape_client.h"
#include "ui/aura/client/default_capture_client.h"
#include "ui/aura/env.h"
#include "ui/aura/layout_manager.h"
#if BUILDFLAG(IS_WASM)
#include "ui/aura/client/focus_change_observer.h"
#include "ui/aura/client/focus_client.h"
#include "ui/aura/client/window_parenting_client.h"
#include "ui/aura/window_observer.h"
#else
#include "ui/aura/test/test_focus_client.h"  // nogncheck
#include "ui/aura/test/test_window_parenting_client.h"  // nogncheck
#endif
#include "ui/aura/window.h"
#include "ui/platform_window/platform_window_init_properties.h"
#include "ui/wm/core/cursor_loader.h"
#include "ui/wm/core/default_activation_client.h"

#if BUILDFLAG(IS_OZONE)
#include "ui/aura/screen_ozone.h"
#endif

namespace content {

namespace {

class FillLayout : public aura::LayoutManager {
 public:
  explicit FillLayout(aura::Window* root)
      : root_(root), has_bounds_(!root->bounds().IsEmpty()) {}

  FillLayout(const FillLayout&) = delete;
  FillLayout& operator=(const FillLayout&) = delete;

  ~FillLayout() override {}

 private:
  // aura::LayoutManager:
  void OnWindowResized() override {
    // If window bounds were not set previously then resize all children to
    // match the size of the parent.
    if (!has_bounds_) {
      has_bounds_ = true;
      for (aura::Window* child : root_->children())
        SetChildBoundsDirect(child, gfx::Rect(root_->bounds().size()));
    }
  }

  void OnWindowAddedToLayout(aura::Window* child) override {
    child->SetBounds(root_->bounds());
  }

  void OnWillRemoveWindowFromLayout(aura::Window* child) override {}

  void OnWindowRemovedFromLayout(aura::Window* child) override {}

  void OnChildWindowVisibilityChanged(aura::Window* child,
                                      bool visible) override {}

  void SetChildBounds(aura::Window* child,
                      const gfx::Rect& requested_bounds) override {
    SetChildBoundsDirect(child, requested_bounds);
  }

  raw_ptr<aura::Window> root_;
  bool has_bounds_;
};

#if BUILDFLAG(IS_WASM)
class ShellFocusClient : public aura::client::FocusClient,
                         public aura::WindowObserver {
 public:
  explicit ShellFocusClient(aura::Window* root_window)
      : root_window_(root_window) {
    CHECK(root_window_);
    aura::client::SetFocusClient(root_window_, this);
  }

  ShellFocusClient(const ShellFocusClient&) = delete;
  ShellFocusClient& operator=(const ShellFocusClient&) = delete;

  ~ShellFocusClient() override {
    observation_.Reset();
    aura::client::SetFocusClient(root_window_, nullptr);
  }

  void AddObserver(aura::client::FocusChangeObserver* observer) override {
    focus_observers_.AddObserver(observer);
  }

  void RemoveObserver(aura::client::FocusChangeObserver* observer) override {
    focus_observers_.RemoveObserver(observer);
  }

  void FocusWindow(aura::Window* window) override {
    if (window && !window->CanFocus()) {
      return;
    }

    observation_.Reset();
    aura::Window* old_focused_window = focused_window_;
    focused_window_ = window;
    if (focused_window_) {
      observation_.Observe(focused_window_);
    }

    focus_observers_.Notify(
        &aura::client::FocusChangeObserver::OnWindowFocused, focused_window_,
        old_focused_window);
    if (auto* observer =
            aura::client::GetFocusChangeObserver(old_focused_window)) {
      observer->OnWindowFocused(focused_window_, old_focused_window);
    }
    if (auto* observer =
            aura::client::GetFocusChangeObserver(focused_window_)) {
      observer->OnWindowFocused(focused_window_, old_focused_window);
    }
  }

  void ResetFocusWithinActiveWindow(aura::Window* window) override {
    if (!window->Contains(focused_window_)) {
      FocusWindow(window);
    }
  }

  aura::Window* GetFocusedWindow() override { return focused_window_; }

  void OnWindowDestroying(aura::Window* window) override {
    CHECK_EQ(window, focused_window_);
    FocusWindow(nullptr);
  }

 private:
  raw_ptr<aura::Window> root_window_;
  raw_ptr<aura::Window> focused_window_ = nullptr;
  base::ScopedObservation<aura::Window, aura::WindowObserver> observation_{
      this};
  base::ObserverList<aura::client::FocusChangeObserver> focus_observers_;
};

class ShellWindowParentingClient
    : public aura::client::WindowParentingClient {
 public:
  explicit ShellWindowParentingClient(aura::Window* root_window)
      : root_window_(root_window) {
    CHECK(root_window_);
    aura::client::SetWindowParentingClient(root_window_, this);
  }

  ShellWindowParentingClient(const ShellWindowParentingClient&) = delete;
  ShellWindowParentingClient& operator=(const ShellWindowParentingClient&) =
      delete;

  ~ShellWindowParentingClient() override {
    aura::client::SetWindowParentingClient(root_window_, nullptr);
  }

  aura::Window* GetDefaultParent(aura::Window* window,
                                 const gfx::Rect& bounds,
                                 int64_t display_id) override {
    return root_window_;
  }

 private:
  raw_ptr<aura::Window> root_window_;
};
#endif

}

ShellPlatformDataAura::ShellPlatformDataAura(const gfx::Size& initial_size) {
  CHECK(aura::Env::GetInstance());

#if BUILDFLAG(IS_OZONE)
  // Setup global display::Screen singleton.
  if (!display::Screen::HasScreen()) {
    screen_ = std::make_unique<aura::ScreenOzone>();
  }
#endif  // BUILDFLAG(IS_OZONE)

  ui::PlatformWindowInitProperties properties;
  properties.bounds = gfx::Rect(initial_size);

  host_ = aura::WindowTreeHost::Create(std::move(properties));
  host_->InitHost();
  host_->window()->Show();
  host_->window()->SetLayoutManager(
      std::make_unique<FillLayout>(host_->window()));

#if BUILDFLAG(IS_WASM)
  focus_client_ = std::make_unique<ShellFocusClient>(host_->window());
#else
  focus_client_ =
      std::make_unique<aura::test::TestFocusClient>(host_->window());
#endif

  new wm::DefaultActivationClient(host_->window());
  capture_client_ =
      std::make_unique<aura::client::DefaultCaptureClient>(host_->window());
#if BUILDFLAG(IS_WASM)
  window_parenting_client_ =
      std::make_unique<ShellWindowParentingClient>(host_->window());
#else
  window_parenting_client_ =
      std::make_unique<aura::test::TestWindowParentingClient>(host_->window());
#endif

  // TODO(https://crbug.com/1336055): this is needed for
  // mouse_cursor_overlay_controller_browsertest.cc on cast_shell_linux as
  // currently, when is_castos = true, the views toolkit isn't used.
  cursor_shape_client_ = std::make_unique<wm::CursorLoader>();
  aura::client::SetCursorShapeClient(cursor_shape_client_.get());
}

ShellPlatformDataAura::~ShellPlatformDataAura() {
  aura::client::SetCursorShapeClient(nullptr);
}

void ShellPlatformDataAura::ShowWindow() {
  host_->Show();
}

void ShellPlatformDataAura::ResizeWindow(const gfx::Size& size) {
  host_->SetBoundsInPixels(gfx::Rect(size));
}

}  // namespace content

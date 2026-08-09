// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_menu.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/memory/weak_ptr.h"
#include "build/build_config.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/ui/browser_command_controller.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/events/event.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/size.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/layout/box_layout.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_menu.cc must only be built for WebAssembly"
#endif

namespace {

constexpr int kWasmBrowserMenuHeight = 72;
constexpr char kWasmVersionURL[] = "chrome://version/";
constexpr char kWasmSettingsURL[] = "chrome://settings/";

}  // namespace

WasmBrowserMenuView::WasmBrowserMenuView(
    BrowserWindowInterface* browser_window_interface,
    chrome::BrowserCommandController* browser_command_controller)
    : browser_window_interface_(browser_window_interface),
      browser_command_controller_(browser_command_controller) {
  CHECK(browser_window_interface_);
  CHECK(browser_command_controller_);

  SetPreferredSize(gfx::Size(0, kWasmBrowserMenuHeight));
  auto layout = std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal, gfx::Insets::VH(6, 8), 4);
  SetLayoutManager(std::move(layout));

  reload_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmBrowserMenuView::Reload,
                          base::Unretained(this)),
      u"Reload"));
  about_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmBrowserMenuView::ShowVersion,
                          base::Unretained(this)),
      u"About Chromium Wasm"));
  settings_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmBrowserMenuView::ShowSettings,
                          base::Unretained(this)),
      u"Settings"));

  // This menu is a collapsible child of the primary BrowserView, not another
  // Ozone Widget. Hidden Views do not participate in BoxLayout, so the active
  // WebView retains its full content area until a user opens the menu.
  SetVisible(false);

  browser_command_controller_->AddCommandObserver(IDC_RELOAD, this);
  UpdateEnabledState();

  // Commands target one selected tab. Do not leave a visible panel attached
  // to an old tab when a user switches the bounded tab strip underneath it:
  // command enablement can change during that transition. Closing the panel
  // is both conventional menu behavior and avoids a stale reload command.
  active_tab_changed_subscription_ =
      browser_window_interface_->RegisterActiveTabDidChange(base::BindRepeating(
          &WasmBrowserMenuView::ActiveTabChanged, base::Unretained(this)));
}

WasmBrowserMenuView::~WasmBrowserMenuView() {
  active_tab_changed_subscription_ = base::CallbackListSubscription();
  browser_command_controller_->RemoveCommandObserver(this);
}

void WasmBrowserMenuView::Toggle() {
  SetVisible(!GetVisible());
  if (GetVisible()) {
    UpdateEnabledState();
  }
  InvalidateLayout();
  SchedulePaint();
}

void WasmBrowserMenuView::Close() {
  if (!GetVisible()) {
    return;
  }
  SetVisible(false);
  InvalidateLayout();
  SchedulePaint();
}

void WasmBrowserMenuView::ActiveTabChanged(
    BrowserWindowInterface* browser_window_interface) {
  CHECK_EQ(browser_window_interface, browser_window_interface_);
  Close();
}

void WasmBrowserMenuView::EnabledStateChangedForCommand(int command_id,
                                                         bool enabled) {
  CHECK_EQ(command_id, IDC_RELOAD);
  CHECK(reload_button_);
  reload_button_->SetEnabled(enabled);
}

void WasmBrowserMenuView::UpdateEnabledState() {
  CHECK(reload_button_);
  CHECK(about_button_);
  CHECK(settings_button_);
  reload_button_->SetEnabled(
      browser_command_controller_->IsCommandEnabled(IDC_RELOAD));

  tabs::TabInterface* const active_tab =
      browser_window_interface_->GetActiveTabInterface();
  content::WebContents* const contents =
      active_tab ? active_tab->GetContents() : nullptr;
  const bool has_live_contents = contents && !contents->IsBeingDestroyed();
  about_button_->SetEnabled(has_live_contents);
  settings_button_->SetEnabled(has_live_contents);
}

void WasmBrowserMenuView::Reload(const ui::Event& event) {
  CHECK(reload_button_);
  // A completed navigation can disable Reload after the View has accepted an
  // input event. Recheck the real controller rather than turning that normal
  // race into a user-triggered CHECK failure.
  UpdateEnabledState();
  if (reload_button_->GetEnabled() &&
      browser_command_controller_->ExecuteCommand(IDC_RELOAD,
                                                   event.time_stamp())) {
    Close();
  }
}

void WasmBrowserMenuView::ShowVersion(const ui::Event& event) {
  CHECK(about_button_);
  UpdateEnabledState();
  if (!about_button_->GetEnabled() || !NavigateTo(kWasmVersionURL, event)) {
    Close();
  }
}

void WasmBrowserMenuView::ShowSettings(const ui::Event& event) {
  CHECK(settings_button_);
  UpdateEnabledState();
  if (!settings_button_->GetEnabled() ||
      !NavigateTo(kWasmSettingsURL, event)) {
    Close();
  }
}

bool WasmBrowserMenuView::NavigateTo(const char* url, const ui::Event& event) {
  CHECK(url);

  tabs::TabInterface* const active_tab =
      browser_window_interface_->GetActiveTabInterface();
  if (!active_tab) {
    return false;
  }
  content::WebContents* const contents = active_tab->GetContents();
  if (!contents || contents->IsBeingDestroyed()) {
    return false;
  }

  content::NavigationController::LoadURLParams params{GURL(url)};
  params.transition_type = ui::PAGE_TRANSITION_GENERATED;
  params.has_user_gesture = true;
  params.input_start = event.time_stamp();
  base::WeakPtr<content::NavigationHandle> navigation_handle =
      contents->GetController().LoadURLWithParams(params);
  if (!navigation_handle) {
    return false;
  }
  Close();
  return true;
}

BEGIN_METADATA(WasmBrowserMenuView)
END_METADATA

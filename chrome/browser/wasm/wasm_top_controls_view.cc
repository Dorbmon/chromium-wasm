// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_top_controls_view.h"

#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/utf_string_conversions.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/ui/browser_command_controller.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/tab_ui_helper.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/events/event.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/size.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/layout/box_layout.h"
#include "url/gurl.h"
#include "url/url_constants.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_top_controls_view.cc must only be built for WebAssembly"
#endif

namespace {

constexpr int kWasmTopControlsHeight = 40;

bool IsWasmTopControlsUrl(const GURL& target_url) {
  return target_url.is_valid() &&
         (target_url.SchemeIsHTTPOrHTTPS() ||
          target_url.SchemeIs(url::kDataScheme) ||
          target_url == GURL(url::kAboutBlankURL));
}

}  // namespace

WasmTopControlsView::WasmTopControlsView(
    BrowserWindowInterface* browser_window_interface,
    chrome::BrowserCommandController* browser_command_controller)
    : browser_window_interface_(browser_window_interface),
      browser_command_controller_(browser_command_controller) {
  CHECK(browser_window_interface_);
  CHECK(browser_command_controller_);

  SetPreferredSize(gfx::Size(0, kWasmTopControlsHeight));
  auto layout = std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal, gfx::Insets::VH(6, 8), 4);
  views::BoxLayout* const layout_ptr = layout.get();
  SetLayoutManager(std::move(layout));

  back_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmTopControlsView::ExecuteNavigationCommand,
                          base::Unretained(this), IDC_BACK),
      u"Back"));
  forward_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmTopControlsView::ExecuteNavigationCommand,
                          base::Unretained(this), IDC_FORWARD),
      u"Forward"));
  reload_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmTopControlsView::ExecuteNavigationCommand,
                          base::Unretained(this), IDC_RELOAD),
      u"Reload"));
  stop_button_ = AddChildView(std::make_unique<views::LabelButton>(
      base::BindRepeating(&WasmTopControlsView::ExecuteNavigationCommand,
                          base::Unretained(this), IDC_STOP),
      u"Stop"));

  address_field_ = AddChildView(std::make_unique<views::Textfield>());
  address_field_->SetController(this);
  address_field_->SetPlaceholderText(u"Enter URL");
  address_field_->SetDefaultWidthInChars(32);
  address_field_->SetMinimumWidthInChars(24);
  layout_ptr->SetFlexForView(address_field_, 1, /*use_min_size=*/true);
  address_field_observation_.Observe(address_field_);

  browser_command_controller_->AddCommandObserver(IDC_BACK, this);
  browser_command_controller_->AddCommandObserver(IDC_FORWARD, this);
  browser_command_controller_->AddCommandObserver(IDC_RELOAD, this);
  browser_command_controller_->AddCommandObserver(IDC_STOP, this);
  UpdateNavigationButton(IDC_BACK);
  UpdateNavigationButton(IDC_FORWARD);
  UpdateNavigationButton(IDC_RELOAD);
  UpdateNavigationButton(IDC_STOP);

  active_tab_changed_subscription_ =
      browser_window_interface_->RegisterActiveTabDidChange(base::BindRepeating(
          &WasmTopControlsView::ActiveTabChanged, base::Unretained(this)));
  BindActiveTab();
}

WasmTopControlsView::~WasmTopControlsView() {
  address_field_observation_.Reset();
  ClearActiveTab();
  active_tab_changed_subscription_ = base::CallbackListSubscription();
  browser_command_controller_->RemoveCommandObserver(this);
}

void WasmTopControlsView::OnActiveWebContentsDetached(
    content::WebContents* contents) {
  if (!contents || !active_tab_ || active_tab_->GetContents() != contents) {
    return;
  }

  ClearActiveTab();
  if (address_field_ && !address_field_->HasFocus()) {
    address_field_->SetText(u"about:blank");
    address_field_->SetInvalid(false);
  }
}

void WasmTopControlsView::ActiveTabChanged(
    BrowserWindowInterface* browser_window_interface) {
  CHECK_EQ(browser_window_interface, browser_window_interface_);
  BindActiveTab();
}

void WasmTopControlsView::BindActiveTab() {
  ClearActiveTab();
  active_tab_ = browser_window_interface_->GetActiveTabInterface();
  if (active_tab_) {
    TabUIHelper* const tab_ui_helper = TabUIHelper::From(active_tab_);
    CHECK(tab_ui_helper);
    tab_ui_change_subscription_ = tab_ui_helper->AddTabUIChangeCallback(
        base::BindRepeating(&WasmTopControlsView::RefreshFromActiveTab,
                            base::Unretained(this)));
  }

  // Address text belongs to the previously selected tab. Do not let a focused
  // field carry that text into a newly selected tab, where Return would
  // otherwise navigate an unexpected WebContents. The view is usually not
  // attached during its first BindActiveTab(), so this is only observable for
  // a real selection transition.
  if (address_field_ && address_field_->HasFocus()) {
    CHECK(address_field_->GetFocusManager());
    address_field_->GetFocusManager()->ClearFocus();
  }
  RefreshFromActiveTab();
}

void WasmTopControlsView::ClearActiveTab() {
  tab_ui_change_subscription_ = base::CallbackListSubscription();
  active_tab_ = nullptr;
}

void WasmTopControlsView::RefreshFromActiveTab() {
  if (!address_field_ || address_field_->HasFocus()) {
    return;
  }

  if (!active_tab_) {
    address_field_->SetText(u"about:blank");
    address_field_->SetInvalid(false);
    return;
  }

  TabUIHelper* const tab_ui_helper = TabUIHelper::From(active_tab_);
  CHECK(tab_ui_helper);
  address_field_->SetText(
      base::UTF8ToUTF16(tab_ui_helper->GetVisibleURL().spec()));
  address_field_->SetInvalid(false);
}

void WasmTopControlsView::UpdateNavigationButton(int command_id) {
  const bool enabled = browser_command_controller_->IsCommandEnabled(command_id);
  EnabledStateChangedForCommand(command_id, enabled);
}

void WasmTopControlsView::ExecuteNavigationCommand(int command_id,
                                                    const ui::Event& event) {
  static_cast<void>(event);
  CHECK(command_id == IDC_BACK || command_id == IDC_FORWARD ||
        command_id == IDC_RELOAD || command_id == IDC_STOP);
  if (address_field_->HasFocus()) {
    CHECK(address_field_->GetFocusManager());
    address_field_->GetFocusManager()->ClearFocus();
  }
  static_cast<void>(browser_command_controller_->ExecuteCommand(
      command_id, base::TimeTicks::Now()));
}

bool WasmTopControlsView::NavigateAddressText() {
  CHECK(address_field_);
  const GURL target_url(base::UTF16ToUTF8(address_field_->GetText()));
  if (!IsWasmTopControlsUrl(target_url)) {
    address_field_->SetInvalid(true);
    return false;
  }

  tabs::TabInterface* const active_tab =
      browser_window_interface_->GetActiveTabInterface();
  content::WebContents* const web_contents =
      active_tab ? active_tab->GetContents() : nullptr;
  if (!web_contents || web_contents->IsBeingDestroyed()) {
    address_field_->SetInvalid(true);
    return false;
  }

  content::NavigationController::LoadURLParams params(target_url);
  params.transition_type = ui::PAGE_TRANSITION_TYPED;
  params.has_user_gesture = true;
  params.input_start = base::TimeTicks::Now();
  base::WeakPtr<content::NavigationHandle> navigation_handle =
      web_contents->GetController().LoadURLWithParams(params);
  if (!navigation_handle) {
    address_field_->SetInvalid(true);
    return false;
  }

  address_field_->SetInvalid(false);
  if (address_field_->HasFocus()) {
    CHECK(address_field_->GetFocusManager());
    address_field_->GetFocusManager()->ClearFocus();
  }
  return true;
}

bool WasmTopControlsView::HandleKeyEvent(
    views::Textfield* sender,
    const ui::KeyEvent& key_event) {
  if (sender != address_field_ ||
      key_event.type() != ui::EventType::kKeyPressed ||
      key_event.key_code() != ui::VKEY_RETURN) {
    return false;
  }

  NavigateAddressText();
  return true;
}

void WasmTopControlsView::EnabledStateChangedForCommand(int command_id,
                                                         bool enabled) {
  views::LabelButton* button = nullptr;
  switch (command_id) {
    case IDC_BACK:
      button = back_button_;
      break;
    case IDC_FORWARD:
      button = forward_button_;
      break;
    case IDC_RELOAD:
      button = reload_button_;
      break;
    case IDC_STOP:
      button = stop_button_;
      break;
    default:
      return;
  }
  CHECK(button);
  button->SetEnabled(enabled);
}

void WasmTopControlsView::OnViewFocused(views::View* observed_view) {
  CHECK_EQ(observed_view, address_field_);
}

void WasmTopControlsView::OnViewBlurred(views::View* observed_view) {
  CHECK_EQ(observed_view, address_field_);
  RefreshFromActiveTab();
}

BEGIN_METADATA(WasmTopControlsView)
END_METADATA

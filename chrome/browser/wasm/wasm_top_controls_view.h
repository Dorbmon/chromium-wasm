// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_TOP_CONTROLS_VIEW_H_
#define CHROME_BROWSER_WASM_WASM_TOP_CONTROLS_VIEW_H_

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "base/scoped_observation.h"
#include "chrome/browser/command_observer.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/controls/textfield/textfield_controller.h"
#include "ui/views/view.h"
#include "ui/views/view_observer.h"

class BrowserWindowInterface;

namespace chrome {
class BrowserCommandController;
}  // namespace chrome

namespace content {
class WebContents;
}  // namespace content

namespace tabs {
class TabInterface;
}  // namespace tabs

namespace ui {
class Event;
class KeyEvent;
}  // namespace ui

namespace views {
class LabelButton;
class Textfield;
}  // namespace views

// The bounded Wasm top-controls strip supplies only direct active-tab
// navigation. It intentionally is not a Toolbar, LocationBar, or omnibox:
// command state comes from the selected BrowserCommandController and typed
// input is restricted to direct URLs plus the one source-selected VersionUI;
// it does not select desktop search, history, keyword, or the broad Chrome
// WebUI registry.
class WasmTopControlsView final : public views::View,
                                  public views::TextfieldController,
                                  public CommandObserver,
                                  public views::ViewObserver {
  METADATA_HEADER(WasmTopControlsView, views::View)

 public:
  WasmTopControlsView(
      BrowserWindowInterface* browser_window_interface,
      chrome::BrowserCommandController* browser_command_controller);
  WasmTopControlsView(const WasmTopControlsView&) = delete;
  WasmTopControlsView& operator=(const WasmTopControlsView&) = delete;
  ~WasmTopControlsView() override;

  // BrowserView calls this before the TabModel destroys a selected tab's
  // TabFeatures. It clears the TabUIHelper callback while its owner is still
  // valid; the following active-tab notification binds a replacement, if any.
  void OnActiveWebContentsDetached(content::WebContents* contents);

  // These narrow accessors support the switch-gated Wasm smoke. They expose
  // Views event entry points, not a second navigation or command API.
  views::Textfield* address_field_for_testing() const {
    return address_field_;
  }
  views::LabelButton* back_button_for_testing() const {
    return back_button_;
  }
  views::LabelButton* forward_button_for_testing() const {
    return forward_button_;
  }
  views::LabelButton* reload_button_for_testing() const {
    return reload_button_;
  }
  views::LabelButton* stop_button_for_testing() const {
    return stop_button_;
  }

 private:
  void ActiveTabChanged(BrowserWindowInterface* browser_window_interface);
  void BindActiveTab();
  void ClearActiveTab();
  void RefreshFromActiveTab();
  void UpdateNavigationButton(int command_id);
  void ExecuteNavigationCommand(int command_id, const ui::Event& event);
  bool NavigateAddressText();

  // views::TextfieldController:
  bool HandleKeyEvent(views::Textfield* sender,
                      const ui::KeyEvent& key_event) override;

  // CommandObserver:
  void EnabledStateChangedForCommand(int command_id, bool enabled) override;

  // views::ViewObserver:
  void OnViewFocused(views::View* observed_view) override;
  void OnViewBlurred(views::View* observed_view) override;

  const raw_ptr<BrowserWindowInterface> browser_window_interface_;
  const raw_ptr<chrome::BrowserCommandController>
      browser_command_controller_;
  raw_ptr<tabs::TabInterface> active_tab_ = nullptr;
  raw_ptr<views::Textfield> address_field_ = nullptr;
  raw_ptr<views::LabelButton> back_button_ = nullptr;
  raw_ptr<views::LabelButton> forward_button_ = nullptr;
  raw_ptr<views::LabelButton> reload_button_ = nullptr;
  raw_ptr<views::LabelButton> stop_button_ = nullptr;
  base::CallbackListSubscription active_tab_changed_subscription_;
  base::CallbackListSubscription tab_ui_change_subscription_;
  base::ScopedObservation<views::View, views::ViewObserver>
      address_field_observation_{this};
};

#endif  // CHROME_BROWSER_WASM_WASM_TOP_CONTROLS_VIEW_H_

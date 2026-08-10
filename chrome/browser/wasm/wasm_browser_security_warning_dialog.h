// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_SECURITY_WARNING_DIALOG_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_SECURITY_WARNING_DIALOG_H_

#include <memory>

#include "base/memory/raw_ptr.h"
#include "components/web_modal/web_contents_modal_dialog_manager_delegate.h"
#include "ui/views/widget/widget.h"

class Browser;
class TabStripModelChange;

namespace content {
class WebContents;
}  // namespace content

namespace tabs {
class TabInterface;
}  // namespace tabs

namespace views {
class DialogDelegate;
class View;
}  // namespace views

namespace chrome {

// Browser-owned implementation of the WebContents-modal dialog-manager
// delegate for the initial Wasm Chrome window.  It is deliberately shared by
// every live tab in the bounded model: WebContents replacement can otherwise
// leave a per-tab raw delegate behind while the TabInterface survives.
//
// The only dialog currently admitted through this owner is an explicit,
// user-triggered security warning.  It uses the canonical constrained-window
// Views path and remains a kChild Widget in the BrowserWidget Aura tree.
class WasmBrowserSecurityWarningDialog final
    : public web_modal::WebContentsModalDialogManagerDelegate {
 public:
  explicit WasmBrowserSecurityWarningDialog(Browser* browser);
  WasmBrowserSecurityWarningDialog(const WasmBrowserSecurityWarningDialog&) =
      delete;
  WasmBrowserSecurityWarningDialog& operator=(
      const WasmBrowserSecurityWarningDialog&) = delete;
  ~WasmBrowserSecurityWarningDialog() override;

  // Opens the real kChild Views warning for the active tab.  This is called
  // only from the BrowserView menu's ordinary LabelButton callback; it has no
  // host-ABI entry point.
  bool Show();

  // Model lifetime hooks are called by Browser while the relevant WebContents
  // is still model-owned.  They make manager ownership robust across tab
  // insertion, replacement/discard, and removal.
  void OnTabStripModelChanged(const TabStripModelChange& change);
  void OnTabWillBeRemoved(content::WebContents* web_contents);

  // Browser close must drain these synchronously before TabStripModel begins
  // CloseAllTabs(), which requires no active constrained dialog or blocked
  // tab state.
  void CloseAllDialogsForBrowserClose();

  // Narrow test-only inspection used by the switch-gated trusted-DOM smoke.
  // These are Views objects already owned by the Browser/dialog manager; they
  // deliberately expose no control or navigation capability to JavaScript.
  views::Widget* dialog_widget_for_testing() const {
    return dialog_widget_.get();
  }
  views::View* dismiss_button_for_testing() const;
  content::WebContents* dialog_web_contents_for_testing() const {
    return dialog_web_contents_;
  }
  int blocked_state_change_count_for_testing() const {
    return blocked_state_change_count_;
  }

 private:
  void AttachToWebContents(content::WebContents* web_contents);
  void DetachFromWebContents(content::WebContents* web_contents);
  void CloseDialogsForWebContents(content::WebContents* web_contents);
  void OnDialogWidgetClosed(views::Widget::ClosedReason reason);

  // web_modal::WebContentsModalDialogManagerDelegate:
  void SetWebContentsBlocked(content::WebContents* web_contents,
                             bool blocked) override;
  web_modal::WebContentsModalDialogHost* GetWebContentsModalDialogHost(
      content::WebContents* web_contents) override;
  bool IsWebContentsVisible(content::WebContents* web_contents) override;

  const raw_ptr<Browser> browser_;
  raw_ptr<content::WebContents> dialog_web_contents_ = nullptr;
  // A TabInterface survives a discard/replacement while its WebContents does
  // not. Remember the tab that we blocked so an old manager's synchronous
  // unblock callback can clear the right model entry after replacement.
  raw_ptr<content::WebContents> blocked_web_contents_ = nullptr;
  raw_ptr<tabs::TabInterface> blocked_tab_ = nullptr;
  std::unique_ptr<views::DialogDelegate> dialog_delegate_;
  std::unique_ptr<views::Widget> dialog_widget_;
  int blocked_state_change_count_ = 0;
  bool closing_all_dialogs_ = false;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_SECURITY_WARNING_DIALOG_H_

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_security_warning_dialog.h"

#include <memory>
#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "build/build_config.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "components/constrained_window/constrained_window_views.h"
#include "components/tabs/public/tab_interface.h"
#include "components/web_modal/web_contents_modal_dialog_manager.h"
#include "components/web_modal/web_contents_modal_dialog_manager_delegate.h"
#include "content/public/browser/web_contents.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/base/hit_test.h"
#include "ui/base/mojom/dialog_button.mojom.h"
#include "ui/base/mojom/ui_base_types.mojom-shared.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/gfx/geometry/size.h"
#include "ui/gfx/text_constants.h"
#include "ui/views/background.h"
#include "ui/views/controls/label.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"
#include "ui/views/window/dialog_delegate.h"
#include "ui/views/window/frame_view.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_security_warning_dialog.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr gfx::Size kSecurityWarningDialogContentsSize(360, 128);

// The Ozone-Wasm platform has one BrowserWidget Aura tree rather than a
// desktop child-window implementation.  Keep the generic Views client area
// fully painted inside that child Widget while the constrained-window manager
// owns modality, positioning, and close notification.
class WasmSecurityWarningFrameView final : public views::FrameView {
 public:
  WasmSecurityWarningFrameView() = default;
  WasmSecurityWarningFrameView(const WasmSecurityWarningFrameView&) = delete;
  WasmSecurityWarningFrameView& operator=(
      const WasmSecurityWarningFrameView&) = delete;
  ~WasmSecurityWarningFrameView() override = default;

  gfx::Rect GetBoundsForClientView() const override {
    return GetLocalBounds();
  }

  gfx::Rect GetWindowBoundsForClientBounds(
      const gfx::Rect& client_bounds) const override {
    return client_bounds;
  }

  int NonClientHitTest(const gfx::Point& point) override {
    return GetLocalBounds().Contains(point) ? HTCLIENT : HTNOWHERE;
  }
};

// Real content for the product warning.  The standard DialogClientView owns
// and paints its Dismiss MdTextButton; this delegate only supplies the child
// modal policy and a deliberately small, in-canvas explanation of the Wasm
// single-process security boundary.
class WasmSecurityWarningDialogDelegate final : public views::DialogDelegate {
 public:
  WasmSecurityWarningDialogDelegate() {
    SetModalType(ui::mojom::ModalType::kChild);
    SetOwnershipOfNewWidget(views::Widget::InitParams::CLIENT_OWNS_WIDGET);
    SetTitle(u"Security warning");
    SetButtons(static_cast<int>(ui::mojom::DialogButton::kOk));
    SetButtonLabel(ui::mojom::DialogButton::kOk, u"Dismiss");
    SetShowCloseButton(false);
    SetShowTitle(false);
    set_use_custom_frame(false);
    set_fixed_width(kSecurityWarningDialogContentsSize.width());

    auto contents = std::make_unique<views::View>();
    contents->SetPreferredSize(kSecurityWarningDialogContentsSize);
    contents->SetBackground(views::CreateSolidBackground(SK_ColorWHITE));
    contents->SetLayoutManager(std::make_unique<views::BoxLayout>(
        views::BoxLayout::Orientation::kVertical, gfx::Insets::VH(12, 16), 8));

    auto title = std::make_unique<views::Label>(u"Security warning");
    title->SetHorizontalAlignment(gfx::ALIGN_LEFT);
    contents->AddChildView(std::move(title));

    auto message = std::make_unique<views::Label>(
        u"Chromium Wasm runs browser and page code in one process. "
        u"Do not use this build for sensitive data.");
    message->SetHorizontalAlignment(gfx::ALIGN_LEFT);
    message->SetMultiLine(true);
    message->SetMaxLines(3);
    contents->AddChildView(std::move(message));

    SetContentsView(std::move(contents));
  }

  WasmSecurityWarningDialogDelegate(
      const WasmSecurityWarningDialogDelegate&) = delete;
  WasmSecurityWarningDialogDelegate& operator=(
      const WasmSecurityWarningDialogDelegate&) = delete;
  ~WasmSecurityWarningDialogDelegate() override = default;

  std::unique_ptr<views::FrameView> CreateFrameView(
      views::Widget* /*widget*/) override {
    return std::make_unique<WasmSecurityWarningFrameView>();
  }
};

web_modal::WebContentsModalDialogManager* GetDialogManager(
    content::WebContents* web_contents) {
  CHECK(web_contents);
  web_modal::WebContentsModalDialogManager* const manager =
      web_modal::WebContentsModalDialogManager::FromWebContents(web_contents);
  CHECK(manager);
  return manager;
}

}  // namespace

WasmBrowserSecurityWarningDialog::WasmBrowserSecurityWarningDialog(
    Browser* browser)
    : browser_(browser) {
  CHECK(browser_);
}

WasmBrowserSecurityWarningDialog::~WasmBrowserSecurityWarningDialog() {
  CloseAllDialogsForBrowserClose();
  CHECK(!dialog_widget_);
  CHECK(!dialog_delegate_);
  dialog_web_contents_ = nullptr;
  blocked_web_contents_ = nullptr;
  blocked_tab_ = nullptr;
}

bool WasmBrowserSecurityWarningDialog::Show() {
  CHECK(browser_);
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  if (!tab_strip_model || tab_strip_model->empty() || dialog_widget_ ||
      dialog_delegate_) {
    return false;
  }

  content::WebContents* const web_contents =
      tab_strip_model->GetActiveWebContents();
  if (!web_contents || web_contents->IsBeingDestroyed()) {
    return false;
  }
  const int tab_index = tab_strip_model->GetIndexOfWebContents(web_contents);
  if (tab_index == TabStripModel::kNoTab ||
      tab_strip_model->IsTabBlocked(tab_index)) {
    return false;
  }

  BrowserView& browser_view = browser_->GetBrowserView();
  if (!browser_view.IsVisible() ||
      browser_view.GetActiveWebContents() != web_contents) {
    return false;
  }

  web_modal::WebContentsModalDialogManager* const manager =
      GetDialogManager(web_contents);
  if (manager->IsDialogActive()) {
    return false;
  }
  AttachToWebContents(web_contents);
  CHECK_EQ(manager->delegate(), this);

  dialog_delegate_ = std::make_unique<WasmSecurityWarningDialogDelegate>();
  dialog_web_contents_ = web_contents;
  dialog_widget_ = constrained_window::ShowWebModalDialogViewsOwned(
      dialog_delegate_.get(), web_contents,
      views::Widget::InitParams::CLIENT_OWNS_WIDGET);
  CHECK(dialog_widget_);
  dialog_widget_->MakeCloseSynchronous(base::BindOnce(
      &WasmBrowserSecurityWarningDialog::OnDialogWidgetClosed,
      base::Unretained(this)));

  CHECK(manager->IsDialogActive());
  CHECK(tab_strip_model->IsTabBlocked(tab_index));
  return true;
}

void WasmBrowserSecurityWarningDialog::OnTabStripModelChanged(
    const TabStripModelChange& change) {
  switch (change.type()) {
    case TabStripModelChange::kInserted: {
      const TabStripModelChange::Insert* const insert = change.GetInsert();
      CHECK(insert);
      for (const TabStripModelChange::ContentsWithIndex& contents :
           insert->contents) {
        AttachToWebContents(contents.contents);
      }
      return;
    }
    case TabStripModelChange::kReplaced: {
      const TabStripModelChange::Replace* const replacement =
          change.GetReplace();
      CHECK(replacement);
      DetachFromWebContents(replacement->old_contents);
      AttachToWebContents(replacement->new_contents);
      return;
    }
    case TabStripModelChange::kSelectionOnly:
    case TabStripModelChange::kRemoved:
    case TabStripModelChange::kMoved:
      return;
  }
}

void WasmBrowserSecurityWarningDialog::OnTabWillBeRemoved(
    content::WebContents* web_contents) {
  DetachFromWebContents(web_contents);
}

void WasmBrowserSecurityWarningDialog::CloseAllDialogsForBrowserClose() {
  if (closing_all_dialogs_) {
    return;
  }
  closing_all_dialogs_ = true;

  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  if (tab_strip_model) {
    for (int index = 0; index < tab_strip_model->count(); ++index) {
      content::WebContents* const web_contents =
          tab_strip_model->GetWebContentsAt(index);
      if (!web_contents) {
        continue;
      }
      CloseDialogsForWebContents(web_contents);
      web_modal::WebContentsModalDialogManager* const manager =
          GetDialogManager(web_contents);
      CHECK(!manager->IsDialogActive());
      CHECK(!tab_strip_model->IsTabBlocked(index));
      if (manager->delegate() == this) {
        manager->SetDelegate(nullptr);
      }
    }
  }

  CHECK(!dialog_widget_);
  CHECK(!dialog_delegate_);
  CHECK(!dialog_web_contents_);
  CHECK(!blocked_web_contents_);
  CHECK(!blocked_tab_);
  closing_all_dialogs_ = false;
}

views::View* WasmBrowserSecurityWarningDialog::dismiss_button_for_testing()
    const {
  return dialog_delegate_ ? dialog_delegate_->GetOkButton() : nullptr;
}

void WasmBrowserSecurityWarningDialog::AttachToWebContents(
    content::WebContents* web_contents) {
  if (!web_contents || web_contents->IsBeingDestroyed()) {
    return;
  }
  web_modal::WebContentsModalDialogManager* const manager =
      GetDialogManager(web_contents);
  CHECK(!manager->delegate() || manager->delegate() == this);
  manager->SetDelegate(this);
}

void WasmBrowserSecurityWarningDialog::DetachFromWebContents(
    content::WebContents* web_contents) {
  if (!web_contents || web_contents->IsBeingDestroyed()) {
    // Browser's model observer normally reaches this while the old contents
    // is still live. Do not query a manager that has already entered its
    // WebContents destruction path; the manager owns its own synchronous
    // close there. A live dialog must already have delivered its close
    // callback before that point, so retaining it would be a lifecycle bug.
    CHECK_NE(dialog_web_contents_, web_contents);
    CHECK_NE(blocked_web_contents_, web_contents);
    return;
  }
  CloseDialogsForWebContents(web_contents);
  web_modal::WebContentsModalDialogManager* const manager =
      GetDialogManager(web_contents);
  CHECK(!manager->IsDialogActive());
  if (manager->delegate() == this) {
    manager->SetDelegate(nullptr);
  }
}

void WasmBrowserSecurityWarningDialog::CloseDialogsForWebContents(
    content::WebContents* web_contents) {
  if (!web_contents || web_contents->IsBeingDestroyed()) {
    return;
  }
  web_modal::WebContentsModalDialogManager* const manager =
      GetDialogManager(web_contents);
  if (!manager->IsDialogActive()) {
    return;
  }
  manager->CloseAllDialogs();
  CHECK(!manager->IsDialogActive());
}

void WasmBrowserSecurityWarningDialog::OnDialogWidgetClosed(
    views::Widget::ClosedReason /*reason*/) {
  CHECK(dialog_widget_);
  CHECK(dialog_delegate_);
  dialog_widget_.reset();
  dialog_delegate_.reset();
  dialog_web_contents_ = nullptr;
}

void WasmBrowserSecurityWarningDialog::SetWebContentsBlocked(
    content::WebContents* web_contents,
    bool blocked) {
  CHECK(browser_);
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  int index = tab_strip_model->GetIndexOfWebContents(web_contents);
  if (blocked) {
    CHECK_NE(index, TabStripModel::kNoTab);
    if (tab_strip_model->IsTabBlocked(index)) {
      CHECK_EQ(blocked_web_contents_, web_contents);
      CHECK(blocked_tab_);
      return;
    }
    tabs::TabInterface* const tab = tab_strip_model->GetTabAtIndex(index);
    CHECK(tab);
    CHECK(!blocked_web_contents_);
    CHECK(!blocked_tab_);
    blocked_web_contents_ = web_contents;
    blocked_tab_ = tab;
  } else if (index == TabStripModel::kNoTab) {
    // A discard swaps the contents before it delivers kReplaced. The old
    // manager then synchronously closes the old child Widget, but its
    // unblock callback must affect the still-live TabInterface, not a stale
    // WebContents lookup.
    CHECK_EQ(blocked_web_contents_, web_contents);
    CHECK(blocked_tab_);
    index = tab_strip_model->GetIndexOfTab(blocked_tab_);
    CHECK_NE(index, TabStripModel::kNoTab);
  }
  if (!blocked && !tab_strip_model->IsTabBlocked(index)) {
    CHECK_EQ(blocked_web_contents_, web_contents);
    blocked_web_contents_ = nullptr;
    blocked_tab_ = nullptr;
    return;
  }
  tab_strip_model->SetTabBlocked(index, blocked);
  CHECK_EQ(tab_strip_model->IsTabBlocked(index), blocked);
  ++blocked_state_change_count_;
  if (!blocked) {
    CHECK_EQ(blocked_web_contents_, web_contents);
    blocked_web_contents_ = nullptr;
    blocked_tab_ = nullptr;
  }
}

web_modal::WebContentsModalDialogHost*
WasmBrowserSecurityWarningDialog::GetWebContentsModalDialogHost(
    content::WebContents* web_contents) {
  CHECK(browser_);
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK_EQ(web_contents, tab_strip_model->GetActiveWebContents())
      << "Wasm Browser supports a modal host only for its active tab";
  return browser_->GetBrowserView().GetWebContentsModalDialogHostFor(
      web_contents);
}

bool WasmBrowserSecurityWarningDialog::IsWebContentsVisible(
    content::WebContents* web_contents) {
  CHECK(browser_);
  TabStripModel* const tab_strip_model = browser_->tab_strip_model();
  return tab_strip_model && web_contents == tab_strip_model->GetActiveWebContents() &&
         browser_->GetBrowserView().IsVisible();
}

}  // namespace chrome

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_CORE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_CORE_H_

#include <memory>
#include <vector>

#include "base/callback_list.h"
#include "base/functional/callback_forward.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "components/sessions/core/session_id.h"
#include "ui/base/unowned_user_data/unowned_user_data_host.h"

class Browser;
class BrowserActions;
class BrowserWindowFeatures;
class DesktopBrowserWindowCapabilities;
class Profile;
class TabStripModel;
class TabStripModelChange;
struct TabStripSelectionChange;

namespace content {
class WebContents;
}  // namespace content

namespace chrome {
class WasmTabBootstrapDelegate;
}  // namespace chrome

namespace tabs {
class TabInterface;
}  // namespace tabs

namespace web_modal {
class WebContentsModalDialogHost;
}  // namespace web_modal

namespace ui {
class BaseWindow;
}  // namespace ui

namespace views {
class View;
}  // namespace views

// A process-local BrowserWindowInterface owner for the opt-in Wasm lifecycle
// smoke. It owns the real, source-selected tab model and
// BrowserWindowFeatures setup. An explicit smoke may bind a non-owning
// BaseWindow and relay its one bounded tab through a view-side adapter. This
// remains distinct from Browser::Create and the joined browser/window close
// lifecycle. Its caller must drain that bounded close before profile shutdown;
// process shutdown while FinishClose is pending remains outside this smoke.
class WasmBrowserWindowCore final : public BrowserWindowInterface {
 public:
  explicit WasmBrowserWindowCore(Profile* profile);
  WasmBrowserWindowCore(const WasmBrowserWindowCore&) = delete;
  WasmBrowserWindowCore& operator=(const WasmBrowserWindowCore&) = delete;
  ~WasmBrowserWindowCore() override;

  // Completes the empty-model ownership proof. A future live close path must
  // replace this with real modal, unload, and BrowserView teardown ordering.
  void CloseForWasmBrowserWindowCoreSmoke();

  // Dispatches the BrowserWindowInterface active-tab callback after the
  // view-side adapter has attached or detached the model-owned WebContents.
  // This does not make the core a BrowserView owner: the joined
  // browser/window lifecycle must still own that relation directly.
  void NotifyActiveTabDidChangeForWasmSmoke();

  // Binds the bounded model to a real BaseWindow after its Views Widget has
  // initialized. The callbacks are view-side only: this core never owns a
  // BrowserView or BrowserWidget and therefore cannot create a dependency
  // cycle with the structural Views target.
  using ActiveContentsChangedCallback = base::RepeatingCallback<void(
      content::WebContents* old_contents,
      content::WebContents* new_contents,
      int active_index,
      int reason)>;
  using ContentsDetachedCallback =
      base::RepeatingCallback<void(content::WebContents*, bool was_active)>;
  void BindWindowForWasmBrowserWindowViewSmoke(
      ui::BaseWindow* window,
      ActiveContentsChangedCallback active_contents_changed_callback,
      ContentsDetachedCallback contents_detached_callback,
      base::OnceClosure destroy_window_callback);
  void InitPostBrowserViewConstructionForWasmBrowserWindowViewSmoke(
      views::View* browser_view);
  void OnWindowActivationChangedForWasmBrowserWindowViewSmoke(
      ui::BaseWindow* window,
      bool active);
  void RequestCloseForWasmBrowserWindowViewSmoke();
  void UnbindWindowForWasmBrowserWindowViewSmoke(ui::BaseWindow* window);
  base::WeakPtr<WasmBrowserWindowCore>
  GetWeakPtrForWasmBrowserWindowViewSmoke();

  // BrowserWindowInterface:
  ui::UnownedUserDataHost& GetUnownedUserDataHost() override;
  const ui::UnownedUserDataHost& GetUnownedUserDataHost() const override;
  ui::BaseWindow* GetWindow() override;
  const ui::BaseWindow* GetWindow() const override;
  Profile* GetProfile() override;
  const Profile* GetProfile() const override;
  const SessionID& GetSessionID() const override;
  bool IsDeleteScheduled() const override;
  base::CallbackListSubscription RegisterBrowserDidClose(
      BrowserDidCloseCallback callback) override;
  Type GetType() const override;
  base::WeakPtr<BrowserWindowInterface> GetWeakPtr() override;

  // content::PageNavigator:
  content::WebContents* OpenURL(
      const content::OpenURLParams& params,
      base::OnceCallback<void(content::NavigationHandle&)>
          navigation_handle_callback) override;

  void OpenGURL(const GURL& gurl,
                WindowOpenDisposition disposition) override;
  TabStripModel* GetTabStripModel() override;
  const TabStripModel* GetTabStripModel() const override;
  bool IsTabStripVisible() override;
  base::CallbackListSubscription RegisterBrowserCloseCancelled(
      BrowserCloseCancelledCallback callback) override;
  base::CallbackListSubscription RegisterActiveTabDidChange(
      ActiveTabChangeCallback callback) override;
  tabs::TabInterface* GetActiveTabInterface() override;
  BrowserWindowFeatures& GetFeatures() override;
  const BrowserWindowFeatures& GetFeatures() const override;
  web_modal::WebContentsModalDialogHost*
  GetWebContentsModalDialogHostForWindow() override;
  web_modal::WebContentsModalDialogHost* GetWebContentsModalDialogHostForTab(
      tabs::TabInterface* tab_interface) override;
  bool IsActive() const override;
  base::CallbackListSubscription RegisterDidBecomeActive(
      DidBecomeActiveCallback callback) override;
  base::CallbackListSubscription RegisterDidBecomeInactive(
      DidBecomeInactiveCallback callback) override;
  BrowserActions* GetActions() override;
  std::vector<tabs::TabInterface*> GetAllTabInterfaces() override;
  Browser* GetBrowserForMigrationOnly() override;
  const Browser* GetBrowserForMigrationOnly() const override;
  bool IsTabModalPopupDeprecated() const override;
  bool CreatedBySessionRestore() const override;
  DesktopBrowserWindowCapabilities* capabilities() override;
  const DesktopBrowserWindowCapabilities* capabilities() const override;

 private:
  class TabStripModelObserver;

  void NotifyBrowserDidClose();
  void ScheduleManagerDeletionForWasmBrowserWindowSmoke();
  void DeleteFromManagerForWasmBrowserWindowSmoke();
  void OnTabWillBeRemovedForWasmBrowserWindowViewSmoke(
      tabs::TabInterface* tab,
      int index);
  void OnTabStripModelChangedForWasmBrowserWindowViewSmoke(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection);
  void OnTabStripEmptyForWasmBrowserWindowViewSmoke();
  void FinishCloseForWasmBrowserWindowViewSmoke();

  using BrowserDidCloseCallbackList =
      base::RepeatingCallbackList<void(BrowserWindowInterface*)>;
  using BrowserCloseCancelledCallbackList = base::RepeatingCallbackList<
      void(BrowserWindowInterface*, ClosingStatus)>;
  using ActiveTabChangeCallbackList =
      base::RepeatingCallbackList<void(BrowserWindowInterface*)>;
  using DidBecomeActiveCallbackList =
      base::RepeatingCallbackList<void(BrowserWindowInterface*)>;
  using DidBecomeInactiveCallbackList =
      base::RepeatingCallbackList<void(BrowserWindowInterface*)>;

  const raw_ptr<Profile> profile_;
  const SessionID session_id_;
  ui::UnownedUserDataHost unowned_user_data_host_;
  std::unique_ptr<chrome::WasmTabBootstrapDelegate> tab_delegate_;
  std::unique_ptr<TabStripModel> tab_strip_model_;
  std::unique_ptr<TabStripModelObserver> tab_strip_model_observer_;

  // These callback lists must outlive BrowserWindowFeatures: the selected
  // command controller holds an active-tab subscription until its teardown.
  BrowserDidCloseCallbackList browser_did_close_callbacks_;
  BrowserCloseCancelledCallbackList browser_close_cancelled_callbacks_;
  ActiveTabChangeCallbackList active_tab_changed_callbacks_;
  DidBecomeActiveCallbackList did_become_active_callbacks_;
  DidBecomeInactiveCallbackList did_become_inactive_callbacks_;

  std::unique_ptr<BrowserWindowFeatures> features_;
  raw_ptr<tabs::TabInterface> last_notified_active_tab_ = nullptr;
  raw_ptr<ui::BaseWindow> window_ = nullptr;
  ActiveContentsChangedCallback active_contents_changed_callback_;
  ContentsDetachedCallback contents_detached_callback_;
  base::OnceClosure destroy_window_callback_;
  bool is_delete_scheduled_ = false;
  bool is_active_ = false;
  bool browser_view_initialized_ = false;
  bool close_requested_ = false;
  bool features_torn_down_ = false;

  base::WeakPtrFactory<WasmBrowserWindowCore> weak_ptr_factory_{this};
};

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_WINDOW_CORE_H_

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_H_

#include <memory>
#include <vector>

#include "base/callback_list.h"
#include "base/functional/callback_forward.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window_deleter.h"
#include "components/sessions/core/session_id.h"
#include "ui/base/mojom/window_show_state.mojom.h"
#include "ui/base/unowned_user_data/unowned_user_data_host.h"
#include "ui/gfx/geometry/rect.h"

class BrowserActions;
class BrowserView;
class BrowserWindow;
class BrowserWindowFeatures;
class DesktopBrowserWindowCapabilities;
class Profile;
class TabStripModel;
class TabStripModelChange;
struct TabStripSelectionChange;

namespace chrome {
class WasmTabBootstrapDelegate;
}  // namespace chrome

namespace content {
class NavigationHandle;
class WebContents;
}  // namespace content

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
enum class CloseRequestResult;
}  // namespace views

// The source-selected Wasm Browser is the first real Browser owner admitted
// into the M6 graph. It intentionally implements only one TYPE_NORMAL window
// with one no-unload tab; unsupported full-Chrome routes fail at their feature
// boundary rather than impersonating the desktop Browser implementation.
//
// BrowserManagerService owns created instances. BrowserView/BrowserWidget own
// the Views side through BrowserWindow, and this Browser controls the ordered
// tab -> feature -> window -> manager destruction sequence.
class Browser final : public BrowserWindowInterface {
 public:
  struct CreateParams {
    explicit CreateParams(Profile* profile, bool user_gesture = false);
    CreateParams(const CreateParams&);
    CreateParams& operator=(const CreateParams&);
    ~CreateParams();

    Type type = TYPE_NORMAL;
    raw_ptr<Profile> profile = nullptr;
    bool user_gesture = false;
    bool in_tab_dragging = false;
    gfx::Rect initial_bounds;
    ui::mojom::WindowShowState initial_show_state =
        ui::mojom::WindowShowState::kDefault;
  };

  // Creates a manager-owned normal Browser. This is intentionally narrower
  // than desktop Browser::Create: popup/app/DevTools, tab dragging, session
  // restoration, and externally supplied BrowserWindows remain unsupported.
  static Browser* Create(const CreateParams& params);
  static CreationStatus GetCreationStatusForProfile(Profile* profile);

  Browser(const Browser&) = delete;
  Browser& operator=(const Browser&) = delete;
  ~Browser() override;

  Type type() const { return type_; }
  Profile* profile() const { return profile_.get(); }
  BrowserWindow* window() const { return window_.get(); }
  TabStripModel* tab_strip_model() const { return tab_strip_model_.get(); }
  BrowserWindowFeatures* browser_window_features() const {
    return features_.get();
  }
  SessionID session_id() const { return session_id_; }
  BrowserView& GetBrowserView();

  base::WeakPtr<Browser> AsWeakPtr();
  base::WeakPtr<const Browser> AsWeakPtr() const;

  // Starts the bounded close lifecycle. Repeated platform close requests are
  // absorbed while the model's non-nestable finish task is pending.
  void OnWindowClosing();

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
  class WindowObserver;

  explicit Browser(const CreateParams& params);

  void OnWindowActivationChanged(bool active);
  views::CloseRequestResult OnWindowCloseRequested();
  void OnTabWillBeRemoved(tabs::TabInterface* tab, int index);
  void OnTabStripModelChanged(TabStripModel* tab_strip_model,
                              const TabStripModelChange& change,
                              const TabStripSelectionChange& selection);
  void OnTabStripEmpty();
  void PostFinishClose();
  void NotifyActiveTabDidChange();
  void FinishClose();
  void NotifyBrowserDidClose();
  void ScheduleManagerDeletion();
  void DeleteFromManager();

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

  const CreateParams create_params_;
  const Type type_;
  const raw_ptr<Profile> profile_;
  const SessionID session_id_;
  ui::UnownedUserDataHost unowned_user_data_host_;
  std::unique_ptr<chrome::WasmTabBootstrapDelegate> tab_delegate_;
  std::unique_ptr<TabStripModel> tab_strip_model_;
  std::unique_ptr<TabStripModelObserver> tab_strip_model_observer_;
  std::unique_ptr<BrowserWindowFeatures> features_;
  std::unique_ptr<BrowserWindow, BrowserWindowDeleter> window_;
  std::unique_ptr<WindowObserver> window_observer_;

  BrowserDidCloseCallbackList browser_did_close_callbacks_;
  BrowserCloseCancelledCallbackList browser_close_cancelled_callbacks_;
  ActiveTabChangeCallbackList active_tab_changed_callbacks_;
  DidBecomeActiveCallbackList did_become_active_callbacks_;
  DidBecomeInactiveCallbackList did_become_inactive_callbacks_;

  raw_ptr<tabs::TabInterface> last_notified_active_tab_ = nullptr;
  bool is_delete_scheduled_ = false;
  bool is_active_ = false;
  bool close_requested_ = false;
  bool finish_close_posted_ = false;
  bool features_torn_down_ = false;

  base::WeakPtrFactory<Browser> weak_ptr_factory_{this};
};

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_H_

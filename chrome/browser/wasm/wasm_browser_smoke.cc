// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_smoke.h"

#include <cstdio>
#include <memory>
#include <vector>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/utf_string_conversions.h"
#include "base/run_loop.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_top_controls_view.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/webui/version/version_ui.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/webui_config.h"
#include "content/public/common/url_constants.h"
#include "ui/base/page_transition_types.h"
#include "ui/events/event.h"
#include "ui/events/keycodes/keyboard_codes.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/focus/focus_manager.h"
#include "ui/views/widget/root_view.h"
#include "ui/views/widget/widget.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserSmokeMarker[] = "CHROMIUM_WASM_M6_BROWSER:PASS";
constexpr char kBrowserSmokeReadyMarker[] = "CHROMIUM_WASM_M6_BROWSER:READY";
constexpr char kTopControlsSmokeMarker[] =
    "CHROMIUM_WASM_M6_TOP_CONTROLS:PASS";
constexpr char kVersionWebUISmokeMarker[] =
    "CHROMIUM_WASM_M6_VERSION_WEBUI:PASS";
constexpr gfx::Rect kBrowserSmokeBounds(0, 0, 640, 480);
constexpr base::TimeDelta kBrowserSmokeVisibleDuration = base::Milliseconds(250);
constexpr base::TimeDelta kNavigationTimeout = base::Seconds(5);
constexpr char kFirstNavigationUrl[] =
    "data:text/html;base64,"
    "PCFkb2N0eXBlIGh0bWw+PHRpdGxlPndhc20tdG9wLWNvbnRyb2xzLWE8L3RpdGxlPjxib2R5Pndhc20tdG9wLWNvbnRyb2xzLWE8L2JvZHk+";
constexpr char kSecondNavigationUrl[] =
    "data:text/html;base64,"
    "PCFkb2N0eXBlIGh0bWw+PHRpdGxlPndhc20tdG9wLWNvbnRyb2xzLWI8L3RpdGxlPjxib2R5Pndhc20tdG9wLWNvbnRyb2xzLWI8L2JvZHk+";
constexpr char kVersionWebUIUrl[] = "chrome://version/";

struct BrowserSmokeState {
  BrowserWindowInterface* expected_browser = nullptr;
  std::vector<content::WebContents*> expected_active_contents;
  size_t active_tab_change_count = 0;
  bool did_close = false;
};

void OnActiveTabChanged(BrowserSmokeState* state,
                        BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK_EQ(browser, state->expected_browser);
  CHECK_LT(state->active_tab_change_count,
           state->expected_active_contents.size());

  tabs::TabInterface* const active_tab = browser->GetActiveTabInterface();
  content::WebContents* const active_contents =
      active_tab ? active_tab->GetContents() : nullptr;
  CHECK_EQ(active_contents,
           state->expected_active_contents[state->active_tab_change_count]);
  ++state->active_tab_change_count;
}

void OnBrowserDidClose(BrowserSmokeState* state,
                       BrowserWindowInterface* browser) {
  CHECK(state);
  CHECK(browser);
  CHECK(!state->did_close);
  CHECK_EQ(browser, state->expected_browser);
  CHECK(browser->IsDeleteScheduled());
  state->did_close = true;
}

class ActiveTabNavigationObserver final
    : public content::WebContentsObserver {
 public:
  explicit ActiveTabNavigationObserver(content::WebContents* web_contents)
      : content::WebContentsObserver(web_contents) {
    CHECK(web_contents);
  }

  ActiveTabNavigationObserver(const ActiveTabNavigationObserver&) = delete;
  ActiveTabNavigationObserver& operator=(const ActiveTabNavigationObserver&) =
      delete;
  ~ActiveTabNavigationObserver() override = default;

  void WaitForNavigation(const GURL& expected_url,
                         bool expect_typed_user_navigation,
                         base::OnceClosure start_navigation) {
    CHECK(expected_url.is_valid());
    CHECK(start_navigation);
    CHECK(!waiting_for_navigation_);
    CHECK(!wait_quit_closure_);
    CHECK(web_contents());

    expected_url_ = expected_url;
    expect_typed_user_navigation_ = expect_typed_user_navigation;
    waiting_for_navigation_ = true;
    committed_primary_main_frame_ = false;
    stopped_loading_after_commit_ = false;
    timed_out_ = false;

    base::RunLoop navigation_run_loop;
    wait_quit_closure_ = navigation_run_loop.QuitClosure();
    navigation_timeout_.Start(
        FROM_HERE, kNavigationTimeout,
        base::BindOnce(&ActiveTabNavigationObserver::OnNavigationTimeout,
                       base::Unretained(this)));
    std::move(start_navigation).Run();
    navigation_run_loop.Run();
    navigation_timeout_.Stop();

    CHECK(!timed_out_);
    CHECK(committed_primary_main_frame_);
    CHECK(stopped_loading_after_commit_);
    CHECK(web_contents());
    CHECK_EQ(web_contents()->GetLastCommittedURL(), expected_url_);

    waiting_for_navigation_ = false;
    expected_url_ = GURL();
    expect_typed_user_navigation_ = false;
  }

 private:
  // content::WebContentsObserver:
  void DidFinishNavigation(
      content::NavigationHandle* navigation_handle) override {
    CHECK(navigation_handle);
    if (!waiting_for_navigation_ ||
        !navigation_handle->IsInPrimaryMainFrame() ||
        !navigation_handle->HasCommitted() || navigation_handle->IsErrorPage() ||
        navigation_handle->GetURL() != expected_url_) {
      return;
    }

    CHECK(!committed_primary_main_frame_);
    if (expect_typed_user_navigation_) {
      CHECK(ui::PageTransitionCoreTypeIs(
          navigation_handle->GetPageTransition(), ui::PAGE_TRANSITION_TYPED));
      CHECK(navigation_handle->HasUserGesture());
    }
    CHECK(web_contents());
    CHECK_EQ(web_contents()->GetLastCommittedURL(), expected_url_);
    committed_primary_main_frame_ = true;

    // A synchronous completion may not produce a later DidStopLoading()
    // callback after this observer starts waiting. The WebContents loading
    // state remains the authoritative completion signal in that case.
    if (!web_contents()->IsLoading()) {
      stopped_loading_after_commit_ = true;
      FinishNavigationWait();
    }
  }

  void DidStopLoading() override {
    if (!waiting_for_navigation_ || !committed_primary_main_frame_) {
      return;
    }

    stopped_loading_after_commit_ = true;
    FinishNavigationWait();
  }

  void OnNavigationTimeout() {
    timed_out_ = true;
    FinishNavigationWait();
  }

  void FinishNavigationWait() {
    if (wait_quit_closure_) {
      std::move(wait_quit_closure_).Run();
    }
  }

  base::OneShotTimer navigation_timeout_;
  base::OnceClosure wait_quit_closure_;
  GURL expected_url_;
  bool expect_typed_user_navigation_ = false;
  bool waiting_for_navigation_ = false;
  bool committed_primary_main_frame_ = false;
  bool stopped_loading_after_commit_ = false;
  bool timed_out_ = false;
};

void SendKeyPress(views::Widget* widget, ui::KeyboardCode key_code) {
  CHECK(widget);
  ui::KeyEvent press(ui::EventType::kKeyPressed, key_code, 0,
                     base::TimeTicks::Now());
  widget->OnKeyEvent(&press);
  ui::KeyEvent release(ui::EventType::kKeyReleased, key_code, 0,
                       base::TimeTicks::Now());
  widget->OnKeyEvent(&release);
}

void ClickButton(views::LabelButton* button) {
  CHECK(button);
  CHECK(button->GetEnabled());
  const gfx::Point center = button->GetLocalBounds().CenterPoint();
  button->OnMousePressed(ui::MouseEvent(
      ui::EventType::kMousePressed, center, center, base::TimeTicks::Now(),
      ui::EF_LEFT_MOUSE_BUTTON, ui::EF_LEFT_MOUSE_BUTTON));
  button->OnMouseReleased(ui::MouseEvent(
      ui::EventType::kMouseReleased, center, center, base::TimeTicks::Now(),
      ui::EF_LEFT_MOUSE_BUTTON, ui::EF_LEFT_MOUSE_BUTTON));
}

void SubmitAddressAndWait(ActiveTabNavigationObserver* navigation_observer,
                          views::Widget* widget,
                          views::Textfield* address_field,
                          const GURL& expected_url) {
  CHECK(navigation_observer);
  CHECK(widget);
  CHECK(address_field);
  navigation_observer->WaitForNavigation(
      expected_url, /*expect_typed_user_navigation=*/true,
      base::BindOnce(
          [](views::Widget* widget, views::Textfield* address_field,
             const GURL& expected_url) {
            address_field->SetText(base::UTF8ToUTF16(expected_url.spec()));
            address_field->RequestFocus();
            CHECK_EQ(widget->GetFocusManager()->GetFocusedView(),
                     address_field);
            SendKeyPress(widget, ui::VKEY_RETURN);
          },
          base::Unretained(widget), base::Unretained(address_field),
          expected_url));
}

void ClickNavigationButtonAndWait(
    ActiveTabNavigationObserver* navigation_observer,
    views::LabelButton* button,
    const GURL& expected_url) {
  CHECK(navigation_observer);
  CHECK(button);
  navigation_observer->WaitForNavigation(
      expected_url, /*expect_typed_user_navigation=*/false,
      base::BindOnce(&ClickButton, base::Unretained(button)));
}

void CloseEmptyBrowserForSmoke(Profile* profile,
                               BrowserManagerService* browser_manager,
                               GlobalBrowserCollection* global_collection) {
  CHECK(profile);
  CHECK(browser_manager);
  CHECK(global_collection);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

  // Browser::Create deliberately exposes an empty model before a caller
  // supplies its first initial WebContents. Exercise that close edge first so
  // it cannot strand an initialized BrowserWidget/BWF graph.
  Browser::CreateParams params(profile, /*user_gesture=*/false);
  Browser* const raw_browser = Browser::Create(params);
  CHECK(raw_browser);
  base::WeakPtr<Browser> weak_browser = raw_browser->AsWeakPtr();
  raw_browser->GetWindow()->Close();
  base::RunLoop().RunUntilIdle();

  CHECK(!weak_browser);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());
}

}  // namespace

bool RunWasmBrowserSmoke(WasmProfile* profile) {
  CHECK(profile);
  BrowserManagerService* const browser_manager =
      BrowserManagerServiceFactory::GetForProfile(profile);
  CHECK(browser_manager);
  CHECK(browser_manager->IsEmpty());

  GlobalBrowserCollection* const global_collection =
      GlobalBrowserCollection::GetInstance();
  CHECK(global_collection);
  CHECK(global_collection->IsEmpty());

  CloseEmptyBrowserForSmoke(profile, browser_manager, global_collection);

  Browser::CreateParams params(profile, /*user_gesture=*/true);
  Browser* const raw_browser = Browser::Create(params);
  CHECK(raw_browser);
  CHECK_EQ(browser_manager->GetSize(), 1u);
  CHECK_EQ(raw_browser->GetBrowserForMigrationOnly(), raw_browser);
  CHECK(raw_browser->window());
  CHECK_EQ(raw_browser->GetWindow(), raw_browser->window());

  BrowserView& browser_view = raw_browser->GetBrowserView();
  CHECK_EQ(browser_view.browser(), raw_browser);
  browser_view.SetBounds(kBrowserSmokeBounds);
  CHECK_EQ(browser_view.GetBounds(), kBrowserSmokeBounds);

  content::WebContents::CreateParams create_params(profile);
  std::unique_ptr<content::WebContents> first_contents =
      content::WebContents::Create(create_params);
  CHECK(first_contents);
  content::WebContents* const raw_first_contents = first_contents.get();
  TabStripModel* const tab_strip_model = raw_browser->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK(tab_strip_model->empty());
  tab_strip_model->AppendWebContents(std::move(first_contents),
                                     /*foreground=*/true);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(raw_browser->GetActiveTabInterface(),
           tab_strip_model->GetActiveTab());

  std::unique_ptr<content::WebContents> second_contents =
      content::WebContents::Create(create_params);
  CHECK(second_contents);
  content::WebContents* const raw_second_contents = second_contents.get();
  tab_strip_model->AppendWebContents(std::move(second_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);

  browser_view.Show();
  CHECK(browser_view.IsVisible());

  // Let the real Aura/Ozone widget traverse a compositor turn before closing
  // it. The Node smoke verifies the resulting canvas copy, frame, readiness,
  // and keyboard-focus reports; merely constructing a Widget is not enough
  // evidence that this Browser-owned window is presentable.
  base::RunLoop visible_run_loop;
  base::OneShotTimer visible_timer;
  visible_timer.Start(FROM_HERE, kBrowserSmokeVisibleDuration,
                      visible_run_loop.QuitClosure());
  visible_run_loop.Run();
  std::puts(kBrowserSmokeReadyMarker);

  // Exercise the purpose-built Views row through its public input path. This
  // is intentionally not a desktop Toolbar or omnibox proof: it verifies the
  // selected BrowserCommandController-backed buttons and the restricted
  // active-tab URL field while the real BrowserWidget is visible.
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  CHECK(top_controls);
  views::Widget* const browser_widget = browser_view.GetWidget();
  CHECK(browser_widget);
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  CHECK_EQ(browser_view.contents_web_view()->bounds().y(),
           top_controls->GetPreferredSize().height());

  views::Textfield* const address_field =
      top_controls->address_field_for_testing();
  views::LabelButton* const back_button =
      top_controls->back_button_for_testing();
  views::LabelButton* const forward_button =
      top_controls->forward_button_for_testing();
  views::LabelButton* const reload_button =
      top_controls->reload_button_for_testing();
  views::LabelButton* const stop_button =
      top_controls->stop_button_for_testing();
  CHECK(address_field);
  CHECK(back_button);
  CHECK(forward_button);
  CHECK(reload_button);
  CHECK(stop_button);
  CHECK_EQ(address_field->GetText(), u"about:blank");
  CHECK(!back_button->GetEnabled());
  CHECK(!forward_button->GetEnabled());
  CHECK(reload_button->GetEnabled());
  CHECK(!stop_button->GetEnabled());

  const GURL first_navigation_url(kFirstNavigationUrl);
  const GURL second_navigation_url(kSecondNavigationUrl);
  CHECK(first_navigation_url.is_valid());
  CHECK(second_navigation_url.is_valid());
  content::NavigationController& first_navigation_controller =
      raw_first_contents->GetController();
  ActiveTabNavigationObserver navigation_observer(raw_first_contents);

  SubmitAddressAndWait(&navigation_observer, browser_widget, address_field,
                       first_navigation_url);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(first_navigation_url.spec()));
  CHECK(!address_field->GetInvalid());

  SubmitAddressAndWait(&navigation_observer, browser_widget, address_field,
                       second_navigation_url);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(second_navigation_url.spec()));
  CHECK(first_navigation_controller.CanGoBack());
  CHECK(!first_navigation_controller.CanGoForward());
  CHECK(back_button->GetEnabled());
  CHECK(!forward_button->GetEnabled());
  CHECK(reload_button->GetEnabled());
  CHECK(!stop_button->GetEnabled());

  ClickNavigationButtonAndWait(&navigation_observer, back_button,
                               first_navigation_url);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(first_navigation_url.spec()));
  CHECK(first_navigation_controller.CanGoForward());
  CHECK(forward_button->GetEnabled());

  ClickNavigationButtonAndWait(&navigation_observer, forward_button,
                               second_navigation_url);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(second_navigation_url.spec()));
  const int history_entry_count = first_navigation_controller.GetEntryCount();
  const int history_entry_index =
      first_navigation_controller.GetCurrentEntryIndex();

  ClickNavigationButtonAndWait(&navigation_observer, reload_button,
                               second_navigation_url);
  CHECK_EQ(first_navigation_controller.GetEntryCount(), history_entry_count);
  CHECK_EQ(first_navigation_controller.GetCurrentEntryIndex(),
           history_entry_index);

  // Chrome's real VersionUI is the first source-selected WebUI route. Enter
  // it through the actual Views address field instead of a direct controller
  // construction, then verify the config and controller installed for the
  // committed page. Its Version resources and static logo source are bundled
  // in the normal chrome_wasm resource packs.
  const GURL version_webui_url(kVersionWebUIUrl);
  SubmitAddressAndWait(&navigation_observer, browser_widget, address_field,
                       version_webui_url);
  CHECK_EQ(raw_first_contents->GetLastCommittedURL(), version_webui_url);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(version_webui_url.spec()));
  content::WebUI* const web_ui = raw_first_contents->GetWebUI();
  CHECK(web_ui);
  content::WebUIConfig* const web_ui_config = web_ui->GetWebUIConfig();
  CHECK(web_ui_config);
  CHECK_EQ(web_ui_config->scheme(), content::kChromeUIScheme);
  CHECK_EQ(web_ui_config->host(), "version");
  VersionUI* const version_ui =
      static_cast<VersionUI*>(web_ui->GetController());
  CHECK(version_ui);
  CHECK_EQ(version_ui->web_ui(), web_ui);
  const int version_history_entry_count =
      first_navigation_controller.GetEntryCount();
  const int version_history_entry_index =
      first_navigation_controller.GetCurrentEntryIndex();
  std::puts(kVersionWebUISmokeMarker);

  // A focused address field is specific to the selected tab. Switching away
  // must clear/refresh it before Return can reach the new active WebContents.
  address_field->SetText(u"https://stale-tab-text.invalid/");
  address_field->RequestFocus();
  CHECK_EQ(browser_widget->GetFocusManager()->GetFocusedView(),
           address_field);
  tab_strip_model->ActivateTabAt(1);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK(!address_field->HasFocus());
  CHECK_EQ(address_field->GetText(), u"about:blank");
  CHECK(!address_field->GetInvalid());
  tab_strip_model->ActivateTabAt(0);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(version_webui_url.spec()));

  // Unsupported schemes must fail at the address-field boundary rather than
  // being handed to a partially selected Chrome WebUI/JavaScript route.
  address_field->SetText(u"javascript:document.title='not-selected'");
  address_field->RequestFocus();
  SendKeyPress(browser_widget, ui::VKEY_RETURN);
  CHECK(address_field->GetInvalid());
  CHECK_EQ(first_navigation_controller.GetEntryCount(),
           version_history_entry_count);
  CHECK_EQ(first_navigation_controller.GetCurrentEntryIndex(),
           version_history_entry_index);
  CHECK_EQ(raw_first_contents->GetLastCommittedURL(), version_webui_url);
  browser_widget->GetFocusManager()->ClearFocus();
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(version_webui_url.spec()));
  std::puts(kTopControlsSmokeMarker);

  BrowserSmokeState state;
  state.expected_browser = raw_browser;
  base::CallbackListSubscription active_tab_subscription =
      raw_browser->RegisterActiveTabDidChange(
          base::BindRepeating(&OnActiveTabChanged, &state));
  base::CallbackListSubscription close_subscription =
      raw_browser->RegisterBrowserDidClose(
          base::BindRepeating(&OnBrowserDidClose, &state));
  base::WeakPtr<Browser> weak_browser = raw_browser->AsWeakPtr();

  // The model owns both WebContents while BrowserView owns only the selected
  // native view. Verify an explicit switch, a background close, then an
  // active close that selects and reattaches the surviving tab.
  state.expected_active_contents.push_back(raw_second_contents);
  tab_strip_model->ActivateTabAt(1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(state.active_tab_change_count, 1u);

  tab_strip_model->GetTabAtIndex(0)->Close();
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(state.active_tab_change_count, 1u);

  std::unique_ptr<content::WebContents> third_contents =
      content::WebContents::Create(create_params);
  CHECK(third_contents);
  content::WebContents* const raw_third_contents = third_contents.get();
  tab_strip_model->AppendWebContents(std::move(third_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);

  state.expected_active_contents.push_back(raw_third_contents);
  tab_strip_model->ActivateTabAt(1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_third_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_third_contents);
  CHECK_EQ(state.active_tab_change_count, 2u);

  state.expected_active_contents.push_back(raw_second_contents);
  tab_strip_model->GetTabAtIndex(1)->Close();
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(state.active_tab_change_count, 3u);

  std::unique_ptr<content::WebContents> fourth_contents =
      content::WebContents::Create(create_params);
  CHECK(fourth_contents);
  tab_strip_model->AppendWebContents(std::move(fourth_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);

  // Exercise both BaseWindow close requests before the model's non-nestable
  // finish task runs. BrowserView must keep the Widget alive and absorb the
  // repeated request rather than letting client-owned native destruction race
  // tab removal.
  state.expected_active_contents.push_back(nullptr);
  raw_browser->GetWindow()->Close();
  raw_browser->GetWindow()->Close();
  CHECK(weak_browser);
  CHECK(tab_strip_model->empty());
  CHECK(!raw_browser->IsDeleteScheduled());
  CHECK(!browser_view.GetActiveWebContents());
  CHECK_EQ(state.active_tab_change_count,
           state.expected_active_contents.size());

  base::RunLoop().RunUntilIdle();

  CHECK(state.did_close);
  CHECK(!weak_browser);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

  std::puts(kBrowserSmokeMarker);
  return true;
}

}  // namespace chrome

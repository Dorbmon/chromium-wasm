// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_smoke.h"

#include <cstdio>
#include <memory>
#include <optional>
#include <vector>

#include "base/check.h"
#include "base/check_op.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/utf_string_conversions.h"
#include "base/run_loop.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/wasm/wasm_browser.h"
#include "chrome/browser/wasm/wasm_browser_menu.h"
#include "chrome/browser/wasm/wasm_settings_ui.h"
#include "chrome/browser/wasm/wasm_tab_strip_view.h"
#include "chrome/browser/wasm/wasm_top_controls_view.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/tabs/tab_strip_model_observer.h"
#include "chrome/browser/ui/webui/version/version_ui.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "components/tabs/public/tab_interface.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_controller.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/webui_config.h"
#include "content/public/common/url_constants.h"
#include "net/socket/wisp_transport_wasm.h"
#include "ui/base/accelerators/accelerator.h"
#include "ui/base/page_transition_types.h"
#include "ui/events/event.h"
#include "ui/events/event_constants.h"
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
#include "url/url_constants.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_smoke.cc must only be built for WebAssembly"
#endif

// This import is implemented by ozone_wasm's host bridge. The controlled
// HTTPS smoke reports a real WebContents paint only after its exact fixture
// has committed; it must not infer page readiness from a surface frame alone.
extern "C" int chromium_wasm_report_readiness(
    int shell_ready,
    int surface_ready,
    int first_visually_nonempty_paint);

namespace chrome {

namespace {

constexpr char kBrowserSmokeMarker[] = "CHROMIUM_WASM_M6_BROWSER:PASS";
constexpr char kBrowserSmokeReadyMarker[] = "CHROMIUM_WASM_M6_BROWSER:READY";
constexpr char kTopControlsSmokeMarker[] =
    "CHROMIUM_WASM_M6_TOP_CONTROLS:PASS";
// This is deliberately a Views-routing proof: it injects KeyEvents through
// the BrowserWidget and verifies FocusManager registration and command
// routing. Host DOM/Ozone delivery is a separate platform gate.
constexpr char kViewsAcceleratorsSmokeMarker[] =
    "CHROMIUM_WASM_M6_VIEWS_ACCELERATORS:PASS";
constexpr char kTabStripSmokeMarker[] = "CHROMIUM_WASM_M6_TAB_STRIP:PASS";
constexpr char kVersionWebUISmokeMarker[] =
    "CHROMIUM_WASM_M6_VERSION_WEBUI:PASS";
constexpr char kSettingsBootstrapSmokeMarker[] =
    "CHROMIUM_WASM_M6_SETTINGS_BOOTSTRAP:PASS";
constexpr char kBrowserMenuSmokeMarker[] =
    "CHROMIUM_WASM_M6_BROWSER_MENU:PASS";
constexpr char kControlledHttpsSmokeMarker[] =
    "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:PASS";
constexpr char kControlledHttpsSmokeReadyMarker[] =
    "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:READY";
constexpr char kControlledHttpsSmokeNavigatedMarker[] =
    "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:NAVIGATED";
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
constexpr char kSettingsWebUIUrl[] = "chrome://settings/";
constexpr char kControlledHttpsUrlSwitch[] =
    "wasm-browser-controlled-https-url";
constexpr char kControlledHttpsHost[] = "a.test";
constexpr char kControlledHttpsPath[] = "/m5/m6-ui";
constexpr char16_t kControlledHttpsTitle[] = u"Chromium Wasm M6 UI fixture";

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

// Verifies that the Views button path retains the TabStripModel's real user
// gesture signal. Direct model activation remains below only for unrelated
// model-close lifecycle coverage.
class UserGestureTabSelectionObserver final : public TabStripModelObserver {
 public:
  explicit UserGestureTabSelectionObserver(TabStripModel* tab_strip_model)
      : tab_strip_model_(tab_strip_model) {
    CHECK(tab_strip_model_);
  }

  UserGestureTabSelectionObserver(const UserGestureTabSelectionObserver&) =
      delete;
  UserGestureTabSelectionObserver& operator=(
      const UserGestureTabSelectionObserver&) = delete;
  ~UserGestureTabSelectionObserver() override {
    if (observing_ && tab_strip_model_) {
      tab_strip_model_->RemoveObserver(this);
    }
  }

  void Expect(tabs::TabInterface* expected_tab) {
    CHECK(expected_tab);
    CHECK(!observing_);
    expected_tab_ = expected_tab;
    saw_expected_selection_ = false;
    tab_strip_model_->AddObserver(this);
    observing_ = true;
  }

  void VerifyAndReset() {
    CHECK(observing_);
    CHECK(saw_expected_selection_);
    tab_strip_model_->RemoveObserver(this);
    observing_ = false;
    expected_tab_ = nullptr;
  }

 private:
  // TabStripModelObserver:
  void OnTabStripModelChanged(
      TabStripModel* tab_strip_model,
      const TabStripModelChange& change,
      const TabStripSelectionChange& selection) override {
    CHECK_EQ(tab_strip_model, tab_strip_model_);
    if (!selection.active_tab_changed()) {
      return;
    }

    CHECK(!saw_expected_selection_);
    CHECK_EQ(change.type(), TabStripModelChange::kSelectionOnly);
    CHECK_EQ(selection.new_tab, expected_tab_);
    CHECK_EQ(selection.reason,
             TabStripModelObserver::CHANGE_REASON_USER_GESTURE);
    saw_expected_selection_ = true;
  }

  void OnTabStripModelDestroyed(TabStripModel* tab_strip_model) override {
    CHECK_EQ(tab_strip_model, tab_strip_model_);
    tab_strip_model_ = nullptr;
    expected_tab_ = nullptr;
    observing_ = false;
  }

  TabStripModel* tab_strip_model_;
  tabs::TabInterface* expected_tab_ = nullptr;
  bool observing_ = false;
  bool saw_expected_selection_ = false;
};

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
    WaitForNavigationImpl(expected_url, expect_typed_user_navigation,
                          /*require_first_visually_nonempty_paint=*/false,
                          std::move(start_navigation), base::OnceClosure());
  }

  // Waits for the primary-main-frame commit, loading completion, and the
  // renderer's first non-empty layout paint for this exact navigation. This is
  // deliberately distinct from a compositor turn: a canvas frame could still
  // contain the prior page while the new document is unpainted.
  void WaitForNavigationAndFirstVisuallyNonEmptyPaint(
      const GURL& expected_url,
      bool expect_typed_user_navigation,
      base::OnceClosure start_navigation,
      base::OnceClosure on_primary_main_frame_commit) {
    WaitForNavigationImpl(expected_url, expect_typed_user_navigation,
                          /*require_first_visually_nonempty_paint=*/true,
                          std::move(start_navigation),
                          std::move(on_primary_main_frame_commit));
  }

 private:
  void WaitForNavigationImpl(
      const GURL& expected_url,
      bool expect_typed_user_navigation,
      bool require_first_visually_nonempty_paint,
      base::OnceClosure start_navigation,
      base::OnceClosure on_primary_main_frame_commit) {
    CHECK(expected_url.is_valid());
    CHECK(start_navigation);
    CHECK(!waiting_for_navigation_);
    CHECK(!wait_quit_closure_);
    CHECK(web_contents());

    expected_url_ = expected_url;
    expect_typed_user_navigation_ = expect_typed_user_navigation;
    require_first_visually_nonempty_paint_ =
        require_first_visually_nonempty_paint;
    on_primary_main_frame_commit_ = std::move(on_primary_main_frame_commit);
    waiting_for_navigation_ = true;
    committed_primary_main_frame_ = false;
    stopped_loading_after_commit_ = false;
    first_visually_nonempty_paint_after_commit_ = false;
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
    if (require_first_visually_nonempty_paint_) {
      CHECK(first_visually_nonempty_paint_after_commit_);
    }
    CHECK(!on_primary_main_frame_commit_);
    CHECK(web_contents());
    CHECK_EQ(web_contents()->GetLastCommittedURL(), expected_url_);

    waiting_for_navigation_ = false;
    expected_url_ = GURL();
    expect_typed_user_navigation_ = false;
    require_first_visually_nonempty_paint_ = false;
  }

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

    // Notify the host at the verified commit boundary. The ensuing first
    // non-empty paint and compositor presentation must therefore follow this
    // marker, rather than merely describing the prior about:blank frame.
    if (on_primary_main_frame_commit_) {
      std::move(on_primary_main_frame_commit_).Run();
    }

    // `CompletedFirstVisuallyNonEmptyPaint()` is scoped to the current primary
    // Page. This catches a paint that completed synchronously during the
    // navigation callback while still excluding the superseded about:blank
    // Page.
    if (require_first_visually_nonempty_paint_ &&
        web_contents()->CompletedFirstVisuallyNonEmptyPaint()) {
      first_visually_nonempty_paint_after_commit_ = true;
    }

    // A synchronous completion may not produce a later DidStopLoading()
    // callback after this observer starts waiting. The WebContents loading
    // state remains the authoritative completion signal in that case.
    if (!web_contents()->IsLoading()) {
      stopped_loading_after_commit_ = true;
      MaybeFinishNavigationWait();
    }
  }

  void DidStopLoading() override {
    if (!waiting_for_navigation_ || !committed_primary_main_frame_) {
      return;
    }

    stopped_loading_after_commit_ = true;
    MaybeFinishNavigationWait();
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    // Do not credit an initial about:blank paint or an unrelated navigation.
    // This observer becomes eligible only after the exact fixture navigation
    // committed in the primary main frame above.
    if (!waiting_for_navigation_ ||
        !require_first_visually_nonempty_paint_ ||
        !committed_primary_main_frame_ || !web_contents() ||
        web_contents()->GetLastCommittedURL() != expected_url_) {
      return;
    }

    CHECK(web_contents()->CompletedFirstVisuallyNonEmptyPaint());
    first_visually_nonempty_paint_after_commit_ = true;
    MaybeFinishNavigationWait();
  }

  void OnNavigationTimeout() {
    timed_out_ = true;
    QuitNavigationWait();
  }

  void MaybeFinishNavigationWait() {
    if (!committed_primary_main_frame_ || !stopped_loading_after_commit_ ||
        (require_first_visually_nonempty_paint_ &&
         !first_visually_nonempty_paint_after_commit_)) {
      return;
    }
    QuitNavigationWait();
  }

  void QuitNavigationWait() {
    if (wait_quit_closure_) {
      std::move(wait_quit_closure_).Run();
    }
  }

  base::OneShotTimer navigation_timeout_;
  base::OnceClosure wait_quit_closure_;
  base::OnceClosure on_primary_main_frame_commit_;
  GURL expected_url_;
  bool expect_typed_user_navigation_ = false;
  bool require_first_visually_nonempty_paint_ = false;
  bool waiting_for_navigation_ = false;
  bool committed_primary_main_frame_ = false;
  bool stopped_loading_after_commit_ = false;
  bool first_visually_nonempty_paint_after_commit_ = false;
  bool timed_out_ = false;
};

void SendKeyPress(views::Widget* widget,
                  ui::KeyboardCode key_code,
                  ui::EventFlags flags = ui::EF_NONE) {
  CHECK(widget);
  ui::KeyEvent press(ui::EventType::kKeyPressed, key_code, flags,
                     base::TimeTicks::Now());
  widget->OnKeyEvent(&press);
  ui::KeyEvent release(ui::EventType::kKeyReleased, key_code, flags,
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

void SendAcceleratorAndWait(ActiveTabNavigationObserver* navigation_observer,
                            views::Widget* widget,
                            ui::KeyboardCode key_code,
                            ui::EventFlags flags,
                            const GURL& expected_url) {
  CHECK(navigation_observer);
  CHECK(widget);
  navigation_observer->WaitForNavigation(
      expected_url, /*expect_typed_user_navigation=*/false,
      base::BindOnce(
          [](views::Widget* widget, ui::KeyboardCode key_code,
             ui::EventFlags flags) { SendKeyPress(widget, key_code, flags); },
          base::Unretained(widget), key_code, flags));
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

GURL GetControlledHttpsSmokeUrl() {
  const base::CommandLine* const command_line =
      base::CommandLine::ForCurrentProcess();
  CHECK(command_line);
  CHECK(command_line->HasSwitch(kControlledHttpsUrlSwitch));

  const GURL url(
      command_line->GetSwitchValueASCII(kControlledHttpsUrlSwitch));
  CHECK(url.is_valid());
  CHECK(url.SchemeIs(url::kHttpsScheme));
  CHECK_EQ(url.host(), kControlledHttpsHost);
  // The local relay deliberately chooses an ephemeral H2 port. Requiring an
  // explicit port prevents this test-only command line from silently widening
  // into a normal public-navigation input surface.
  CHECK(url.has_port());
  CHECK_GT(url.EffectiveIntPort(), 0);
  CHECK_LE(url.EffectiveIntPort(), 65535);
  CHECK(!url.has_username());
  CHECK(!url.has_password());
  CHECK(!url.has_query());
  CHECK(!url.has_ref());
  CHECK_EQ(url.path(), kControlledHttpsPath);
  return url;
}

void WaitForBrowserSmokePresentation() {
  base::RunLoop visible_run_loop;
  base::OneShotTimer visible_timer;
  visible_timer.Start(FROM_HERE, kBrowserSmokeVisibleDuration,
                      visible_run_loop.QuitClosure());
  visible_run_loop.Run();
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

  // Exercise the purpose-built Views strips through their public input paths.
  // This is intentionally not a desktop tab strip, Toolbar, or omnibox proof:
  // it verifies two model-owned tab buttons plus selected
  // BrowserCommandController-backed navigation and a restricted URL field.
  WasmTabStripView* const wasm_tab_strip = browser_view.wasm_tab_strip();
  CHECK(wasm_tab_strip);
  CHECK(raw_browser->IsTabStripVisible());
  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  CHECK(top_controls);
  WasmBrowserMenuView* const browser_menu =
      browser_view.wasm_browser_menu();
  CHECK(browser_menu);
  views::Widget* const browser_widget = browser_view.GetWidget();
  CHECK(browser_widget);
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  CHECK_EQ(browser_view.contents_web_view()->bounds().y(),
           wasm_tab_strip->GetPreferredSize().height() +
               top_controls->GetPreferredSize().height());

  views::LabelButton* const first_tab_button =
      wasm_tab_strip->tab_button_for_testing(0);
  views::LabelButton* const second_tab_button =
      wasm_tab_strip->tab_button_for_testing(1);
  CHECK(first_tab_button);
  CHECK(second_tab_button);
  CHECK(first_tab_button->GetVisible());
  CHECK(second_tab_button->GetVisible());
  CHECK(first_tab_button->GetEnabled());
  CHECK(second_tab_button->GetEnabled());
  CHECK(first_tab_button->GetBackground());
  CHECK(!second_tab_button->GetBackground());

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
  views::LabelButton* const menu_button =
      top_controls->menu_button_for_testing();
  CHECK(address_field);
  CHECK(back_button);
  CHECK(forward_button);
  CHECK(reload_button);
  CHECK(stop_button);
  CHECK(menu_button);
  CHECK_EQ(address_field->GetText(), u"about:blank");
  CHECK(!back_button->GetEnabled());
  CHECK(!forward_button->GetEnabled());
  CHECK(reload_button->GetEnabled());
  CHECK(!stop_button->GetEnabled());
  CHECK(!browser_menu->IsOpen());

  // Verify that the source-selected browser accelerators are registered with
  // the real Views FocusManager, then exercise focus through a keyboard event
  // rather than calling the address field directly.
  ui::Accelerator accelerator;
  CHECK(browser_view.GetAccelerator(IDC_FOCUS_LOCATION, &accelerator));
  CHECK(accelerator ==
        ui::Accelerator(ui::VKEY_L, ui::EF_PLATFORM_ACCELERATOR));
  CHECK(browser_widget->GetFocusManager()->IsAcceleratorRegistered(
      accelerator));
  CHECK(browser_view.GetAccelerator(IDC_SELECT_NEXT_TAB, &accelerator));
  CHECK(accelerator ==
        ui::Accelerator(ui::VKEY_TAB, ui::EF_CONTROL_DOWN));
  CHECK(browser_widget->GetFocusManager()->IsAcceleratorRegistered(
      accelerator));
  SendKeyPress(browser_widget, ui::VKEY_L, ui::EF_PLATFORM_ACCELERATOR);
  CHECK_EQ(browser_widget->GetFocusManager()->GetFocusedView(),
           address_field);
  CHECK_EQ(address_field->GetSelectedText(), u"about:blank");
  browser_widget->GetFocusManager()->ClearFocus();

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
  CHECK_EQ(first_tab_button->GetText(), u"wasm-top-controls-a");
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(first_navigation_url.spec()));
  CHECK(!address_field->GetInvalid());

  SubmitAddressAndWait(&navigation_observer, browser_widget, address_field,
                       second_navigation_url);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(first_tab_button->GetText(), u"wasm-top-controls-b");
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

  // The same real NavigationController operations must work through registered
  // browser accelerators. These KeyEvents enter the actual Widget, so Views'
  // FocusManager chooses BrowserView rather than a direct command-controller
  // call. This does not stand in for host DOM/Ozone keyboard delivery.
  SendAcceleratorAndWait(&navigation_observer, browser_widget, ui::VKEY_LEFT,
                         ui::EF_ALT_DOWN, first_navigation_url);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(first_navigation_url.spec()));
  SendAcceleratorAndWait(&navigation_observer, browser_widget, ui::VKEY_RIGHT,
                         ui::EF_ALT_DOWN, second_navigation_url);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(second_navigation_url.spec()));
  SendAcceleratorAndWait(&navigation_observer, browser_widget, ui::VKEY_R,
                         ui::EF_PLATFORM_ACCELERATOR, second_navigation_url);
  SendAcceleratorAndWait(
      &navigation_observer, browser_widget, ui::VKEY_R,
      ui::EF_PLATFORM_ACCELERATOR | ui::EF_SHIFT_DOWN, second_navigation_url);
  CHECK_EQ(first_navigation_controller.GetEntryCount(), history_entry_count);
  CHECK_EQ(first_navigation_controller.GetCurrentEntryIndex(),
           history_entry_index);

  // The Wasm app menu is a real child panel of BrowserView, not host HTML or
  // a second native Widget. Opening it must reserve layout inside the same
  // one-surface Views tree, then its Settings action must navigate the active
  // model-owned WebContents through Chromium's NavigationController.
  const int closed_contents_y = browser_view.contents_web_view()->bounds().y();
  ClickButton(menu_button);
  CHECK(browser_menu->IsOpen());
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  CHECK_GT(browser_view.contents_web_view()->bounds().y(), closed_contents_y);
  views::LabelButton* const menu_reload_button =
      browser_menu->reload_button_for_testing();
  views::LabelButton* const menu_about_button =
      browser_menu->about_button_for_testing();
  views::LabelButton* const menu_settings_button =
      browser_menu->settings_button_for_testing();
  CHECK(menu_reload_button);
  CHECK(menu_about_button);
  CHECK(menu_settings_button);
  CHECK(menu_reload_button->GetVisible());
  CHECK(menu_about_button->GetVisible());
  CHECK(menu_settings_button->GetVisible());
  CHECK(menu_reload_button->GetEnabled());
  CHECK(menu_about_button->GetEnabled());
  CHECK(menu_settings_button->GetEnabled());

  const GURL settings_webui_url(kSettingsWebUIUrl);
  navigation_observer.WaitForNavigation(
      settings_webui_url, /*expect_typed_user_navigation=*/false,
      base::BindOnce(&ClickButton, base::Unretained(menu_settings_button)));
  CHECK(!browser_menu->IsOpen());
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  CHECK_EQ(browser_view.contents_web_view()->bounds().y(), closed_contents_y);
  CHECK_EQ(raw_first_contents->GetLastCommittedURL(), settings_webui_url);
  CHECK_EQ(raw_first_contents->GetTitle(), u"Settings \u2014 Chromium Wasm");
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(settings_webui_url.spec()));
  content::WebUI* const settings_web_ui = raw_first_contents->GetWebUI();
  CHECK(settings_web_ui);
  content::WebUIConfig* const settings_web_ui_config =
      settings_web_ui->GetWebUIConfig();
  CHECK(settings_web_ui_config);
  CHECK_EQ(settings_web_ui_config->scheme(), content::kChromeUIScheme);
  CHECK_EQ(settings_web_ui_config->host(), "settings");
  CHECK(settings_web_ui->GetController());
  WasmSettingsUI* const settings_ui =
      settings_web_ui->GetController()->GetAs<WasmSettingsUI>();
  CHECK(settings_ui);
  CHECK_EQ(settings_ui->web_ui(), settings_web_ui);
  std::puts(kSettingsBootstrapSmokeMarker);

  // Chrome's real VersionUI remains source-selected. Reach it through the
  // same visible app menu rather than a direct controller construction, then
  // verify the concrete config and controller installed for the committed
  // page. Its Version resources and static logo source are bundled in the
  // normal chrome_wasm resource packs.
  const GURL version_webui_url(kVersionWebUIUrl);
  ClickButton(menu_button);
  CHECK(browser_menu->IsOpen());
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  navigation_observer.WaitForNavigation(
      version_webui_url, /*expect_typed_user_navigation=*/false,
      base::BindOnce(&ClickButton, base::Unretained(menu_about_button)));
  CHECK(!browser_menu->IsOpen());
  CHECK_EQ(raw_first_contents->GetLastCommittedURL(), version_webui_url);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(version_webui_url.spec()));
  content::WebUI* const web_ui = raw_first_contents->GetWebUI();
  CHECK(web_ui);
  content::WebUIConfig* const web_ui_config = web_ui->GetWebUIConfig();
  CHECK(web_ui_config);
  CHECK_EQ(web_ui_config->scheme(), content::kChromeUIScheme);
  CHECK_EQ(web_ui_config->host(), "version");
  CHECK(web_ui->GetController());
  // VersionUI predates WebUIController's optional type-token mechanism. Its
  // exact config and host are already checked above, so this source-selected
  // upstream controller cast remains the valid concrete assertion here.
  VersionUI* const version_ui =
      static_cast<VersionUI*>(web_ui->GetController());
  CHECK(version_ui);
  CHECK_EQ(version_ui->web_ui(), web_ui);
  const int version_history_entry_count =
      first_navigation_controller.GetEntryCount();
  const int version_history_entry_index =
      first_navigation_controller.GetCurrentEntryIndex();
  ClickButton(menu_button);
  CHECK(browser_menu->IsOpen());
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  ClickNavigationButtonAndWait(&navigation_observer, menu_reload_button,
                               version_webui_url);
  CHECK(!browser_menu->IsOpen());
  CHECK_EQ(first_navigation_controller.GetEntryCount(),
           version_history_entry_count);
  CHECK_EQ(first_navigation_controller.GetCurrentEntryIndex(),
           version_history_entry_index);
  std::puts(kBrowserMenuSmokeMarker);
  std::puts(kVersionWebUISmokeMarker);

  // A focused address field is specific to the selected tab. Switching away
  // must clear/refresh it before Return can reach the new active WebContents.
  address_field->SetText(u"https://stale-tab-text.invalid/");
  address_field->RequestFocus();
  CHECK_EQ(browser_widget->GetFocusManager()->GetFocusedView(),
           address_field);
  // An open command panel belongs to the selected tab. A genuine Views tab
  // selection must dismiss it before rebinding the active WebContents, so a
  // stale Reload command cannot be invoked against the new tab.
  ClickButton(menu_button);
  CHECK(browser_menu->IsOpen());
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  CHECK_GT(browser_view.contents_web_view()->bounds().y(), closed_contents_y);
  UserGestureTabSelectionObserver tab_selection_observer(tab_strip_model);
  tab_selection_observer.Expect(tab_strip_model->GetTabAtIndex(1));
  ClickButton(second_tab_button);
  tab_selection_observer.VerifyAndReset();
  CHECK(!browser_menu->IsOpen());
  browser_widget->GetRootView()->DeprecatedLayoutImmediately();
  CHECK_EQ(browser_view.contents_web_view()->bounds().y(), closed_contents_y);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK(!address_field->HasFocus());
  CHECK_EQ(address_field->GetText(), u"about:blank");
  CHECK(!address_field->GetInvalid());
  CHECK(!first_tab_button->GetBackground());
  CHECK(second_tab_button->GetBackground());
  tab_selection_observer.Expect(tab_strip_model->GetTabAtIndex(0));
  ClickButton(first_tab_button);
  tab_selection_observer.VerifyAndReset();
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK(first_tab_button->GetBackground());
  CHECK(!second_tab_button->GetBackground());
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(version_webui_url.spec()));

  // Switch through the registered keyboard accelerators as well as the Views
  // buttons above. The model observer verifies the keyboard path preserves
  // its real user-gesture selection reason and the view stays attached first.
  tab_selection_observer.Expect(tab_strip_model->GetTabAtIndex(1));
  SendKeyPress(browser_widget, ui::VKEY_TAB, ui::EF_CONTROL_DOWN);
  tab_selection_observer.VerifyAndReset();
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(address_field->GetText(), u"about:blank");
  tab_selection_observer.Expect(tab_strip_model->GetTabAtIndex(0));
  SendKeyPress(browser_widget, ui::VKEY_TAB,
               ui::EF_CONTROL_DOWN | ui::EF_SHIFT_DOWN);
  tab_selection_observer.VerifyAndReset();
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_first_contents);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(version_webui_url.spec()));

  SendKeyPress(browser_widget, ui::VKEY_L, ui::EF_PLATFORM_ACCELERATOR);
  CHECK_EQ(browser_widget->GetFocusManager()->GetFocusedView(),
           address_field);
  CHECK_EQ(address_field->GetSelectedText(),
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
  std::puts(kViewsAcceleratorsSmokeMarker);
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
  CHECK(first_tab_button->GetVisible());
  CHECK(!second_tab_button->GetVisible());
  CHECK_EQ(state.active_tab_change_count, 1u);

  std::unique_ptr<content::WebContents> third_contents =
      content::WebContents::Create(create_params);
  CHECK(third_contents);
  content::WebContents* const raw_third_contents = third_contents.get();
  tab_strip_model->AppendWebContents(std::move(third_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK(first_tab_button->GetVisible());
  CHECK(second_tab_button->GetVisible());

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
  CHECK(first_tab_button->GetVisible());
  CHECK(!second_tab_button->GetVisible());
  CHECK_EQ(state.active_tab_change_count, 3u);

  std::unique_ptr<content::WebContents> fourth_contents =
      content::WebContents::Create(create_params);
  CHECK(fourth_contents);
  tab_strip_model->AppendWebContents(std::move(fourth_contents),
                                     /*foreground=*/false);
  CHECK_EQ(tab_strip_model->count(), 2);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_second_contents);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_second_contents);
  CHECK(first_tab_button->GetVisible());
  CHECK(second_tab_button->GetVisible());

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
  CHECK(!first_tab_button->GetVisible());
  CHECK(!second_tab_button->GetVisible());
  CHECK_EQ(state.active_tab_change_count,
           state.expected_active_contents.size());

  std::puts(kTabStripSmokeMarker);

  base::RunLoop().RunUntilIdle();

  CHECK(state.did_close);
  CHECK(!weak_browser);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

  std::puts(kBrowserSmokeMarker);
  return true;
}

bool RunWasmBrowserControlledHttpsSmoke(WasmProfile* profile) {
  CHECK(profile);
  BrowserManagerService* const browser_manager =
      BrowserManagerServiceFactory::GetForProfile(profile);
  CHECK(browser_manager);
  CHECK(browser_manager->IsEmpty());

  GlobalBrowserCollection* const global_collection =
      GlobalBrowserCollection::GetInstance();
  CHECK(global_collection);
  CHECK(global_collection->IsEmpty());

  const GURL controlled_https_url = GetControlledHttpsSmokeUrl();
  CHECK(net::IsWasmWispTransportConfigured())
      << "controlled HTTPS smoke requires an explicitly configured WISP "
         "transport";

  Browser::CreateParams params(profile, /*user_gesture=*/true);
  Browser* const raw_browser = Browser::Create(params);
  CHECK(raw_browser);
  CHECK_EQ(browser_manager->GetSize(), 1u);
  CHECK(raw_browser->window());

  content::WebContents::CreateParams create_params(profile);
  std::unique_ptr<content::WebContents> contents =
      content::WebContents::Create(create_params);
  CHECK(contents);
  content::WebContents* const raw_contents = contents.get();
  TabStripModel* const tab_strip_model = raw_browser->tab_strip_model();
  CHECK(tab_strip_model);
  CHECK(tab_strip_model->empty());
  tab_strip_model->AppendWebContents(std::move(contents),
                                     /*foreground=*/true);
  CHECK_EQ(tab_strip_model->count(), 1);
  CHECK_EQ(tab_strip_model->GetActiveWebContents(), raw_contents);

  BrowserView& browser_view = raw_browser->GetBrowserView();
  CHECK_EQ(browser_view.browser(), raw_browser);
  CHECK_EQ(browser_view.GetActiveWebContents(), raw_contents);
  browser_view.SetBounds(kBrowserSmokeBounds);
  CHECK_EQ(browser_view.GetBounds(), kBrowserSmokeBounds);
  browser_view.Show();
  CHECK(browser_view.IsVisible());
  WaitForBrowserSmokePresentation();
  std::puts(kControlledHttpsSmokeReadyMarker);

  WasmTopControlsView* const top_controls = browser_view.wasm_top_controls();
  CHECK(top_controls);
  views::Textfield* const address_field =
      top_controls->address_field_for_testing();
  views::Widget* const browser_widget = browser_view.GetWidget();
  CHECK(address_field);
  CHECK(browser_widget);

  const int port = controlled_https_url.EffectiveIntPort();
  CHECK_GT(port, 0);
  CHECK_LE(port, 65535);
  CHECK(net::BeginWasmWispTransportDiagnostics(
      controlled_https_url.host(), static_cast<uint16_t>(port)));
  const std::optional<net::WasmWispTransportDiagnostics>
      initial_wisp_diagnostics = net::GetWasmWispTransportDiagnostics();
  CHECK(initial_wisp_diagnostics);
  // WebSocket-open and handshake bits are process-lifetime carrier counters;
  // only the stream bit is scoped by BeginWasmWispTransportDiagnostics(). A
  // preexisting carrier is therefore harmless, but no matching destination
  // stream may be credited before this exact address-field navigation.
  CHECK_EQ(initial_wisp_diagnostics->completion_flags &
               net::kWasmWispDiagnosticStreamConfirmed,
           0);

  ActiveTabNavigationObserver navigation_observer(raw_contents);
  navigation_observer.WaitForNavigationAndFirstVisuallyNonEmptyPaint(
      controlled_https_url, /*expect_typed_user_navigation=*/true,
      base::BindOnce(
          [](views::Widget* widget, views::Textfield* address_field,
             const GURL& expected_url) {
            address_field->SetText(base::UTF8ToUTF16(expected_url.spec()));
            address_field->RequestFocus();
            CHECK_EQ(widget->GetFocusManager()->GetFocusedView(),
                     address_field);
            SendKeyPress(widget, ui::VKEY_RETURN);
          },
          base::Unretained(browser_widget), base::Unretained(address_field),
          controlled_https_url),
      base::BindOnce([] { std::puts(kControlledHttpsSmokeNavigatedMarker); }));
  CHECK_EQ(raw_contents->GetLastCommittedURL(), controlled_https_url);
  CHECK_EQ(raw_contents->GetTitle(), kControlledHttpsTitle);
  CHECK_EQ(address_field->GetText(),
           base::UTF8ToUTF16(controlled_https_url.spec()));
  CHECK(!address_field->GetInvalid());
  CHECK_EQ(chromium_wasm_report_readiness(
               /*shell_ready=*/-1, /*surface_ready=*/-1,
               /*first_visually_nonempty_paint=*/1),
           1);
  // Force a normal Views invalidation after the exact page has both committed
  // and reported its first non-empty paint. This yields a fresh Ozone canvas
  // presentation after the commit marker rather than accepting a retained
  // about:blank frame from before navigation.
  browser_view.SchedulePaint();

  const std::optional<net::WasmWispTransportDiagnostics> wisp_diagnostics =
      net::GetWasmWispTransportDiagnostics();
  CHECK(wisp_diagnostics);
  CHECK_EQ(wisp_diagnostics->completion_flags,
           net::kWasmWispDiagnosticAllRequired);

  // The commit marker and real invalidation above precede this bounded
  // compositor turn. The host independently requires its new canvas frame
  // before close rather than accepting the initial about:blank window.
  WaitForBrowserSmokePresentation();

  BrowserSmokeState state;
  state.expected_browser = raw_browser;
  state.expected_active_contents.push_back(nullptr);
  base::CallbackListSubscription active_tab_subscription =
      raw_browser->RegisterActiveTabDidChange(
          base::BindRepeating(&OnActiveTabChanged, &state));
  base::CallbackListSubscription close_subscription =
      raw_browser->RegisterBrowserDidClose(
          base::BindRepeating(&OnBrowserDidClose, &state));
  base::WeakPtr<Browser> weak_browser = raw_browser->AsWeakPtr();

  // Close through the same real BaseWindow route that an end-user close
  // request uses. The Browser's ordered model -> BWF -> BrowserWindowDeleter
  // path must complete before the test-only Chrome process exits.
  raw_browser->GetWindow()->Close();
  CHECK(weak_browser);
  CHECK(tab_strip_model->empty());
  CHECK(!raw_browser->IsDeleteScheduled());
  CHECK(!browser_view.GetActiveWebContents());
  base::RunLoop().RunUntilIdle();

  CHECK(state.did_close);
  CHECK_EQ(state.active_tab_change_count,
           state.expected_active_contents.size());
  CHECK(!weak_browser);
  CHECK(browser_manager->IsEmpty());
  CHECK(global_collection->IsEmpty());

  std::puts(kControlledHttpsSmokeMarker);
  return true;
}

}  // namespace chrome

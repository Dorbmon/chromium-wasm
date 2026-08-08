// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_view_smoke.h"

#include <cstdio>
#include <memory>
#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/run_loop.h"
#include "base/timer/timer.h"
#include "build/build_config.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "chrome/browser/ui/views/frame/browser_widget.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/web_contents.h"
#include "ui/display/screen.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/views/controls/webview/webview.h"
#include "ui/views/views_delegate.h"
#include "ui/views/widget/desktop_aura/desktop_screen_ozone.h"
#include "ui/views/widget/root_view.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_view_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kBrowserViewSmokeMarker[] = "CHROMIUM_WASM_M6_BROWSER_VIEW";
constexpr gfx::Rect kBrowserViewSmokeBounds(0, 0, 640, 480);
constexpr base::TimeDelta kBrowserViewSmokeVisibleDuration =
    base::Milliseconds(250);

// Widget::Init() requires an embedding ViewsDelegate. This generic delegate is
// deliberately scoped to the smoke: it supplies no Chrome command, Browser,
// or profile policy, and its lifetime strictly contains the Widget teardown.
class BrowserViewSmokeViewsDelegate final : public views::ViewsDelegate {
 public:
  BrowserViewSmokeViewsDelegate() = default;
  BrowserViewSmokeViewsDelegate(const BrowserViewSmokeViewsDelegate&) = delete;
  BrowserViewSmokeViewsDelegate& operator=(
      const BrowserViewSmokeViewsDelegate&) = delete;
  ~BrowserViewSmokeViewsDelegate() override = default;
};

void ReportBrowserViewSmokeStep(const char* step) {
  std::fprintf(stderr, "%s:STEP=%s\n", kBrowserViewSmokeMarker, step);
}

}  // namespace

bool RunWasmBrowserViewSmoke(WasmProfile* profile) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(profile);
  CHECK(!views::ViewsDelegate::GetInstance());
  BrowserViewSmokeViewsDelegate views_delegate;

  // This installs the regular Aura ScreenOzone adapter, which in turn owns
  // the Ozone platform's real WasmScreen. Keep it scoped around the Widget so
  // its PlatformScreen outlives all Aura window operations during teardown.
  CHECK(!display::Screen::HasScreen());
  views::DesktopScreenOzone ozone_screen;

  // BrowserView is owned by BrowserWidget's RootView after Init(). Do not put
  // it in a unique_ptr: the explicit helper below breaks that ownership cycle.
  ReportBrowserViewSmokeStep("construct-view");
  BrowserView* browser_view = new BrowserView(/*browser=*/nullptr);
  ReportBrowserViewSmokeStep("view-constructed");
  auto browser_widget = std::make_unique<BrowserWidget>(browser_view);
  ReportBrowserViewSmokeStep("widget-constructed");
  BrowserWidget* const widget = browser_widget.get();
  browser_view->set_browser_widget(std::move(browser_widget));
  ReportBrowserViewSmokeStep("widget-owned-by-view");
  widget->InitBrowserWidget();
  ReportBrowserViewSmokeStep("widget-initialized");

  CHECK_EQ(browser_view->browser_widget(), widget);
  CHECK_EQ(browser_view->GetWidget(), widget);
  CHECK(widget->browser_native_widget());
  CHECK(browser_view->GetNativeWindow());
  CHECK_EQ(BrowserView::GetBrowserViewForNativeWindow(
               browser_view->GetNativeWindow()),
           browser_view);

  // WebView does not own this WebContents. This smoke keeps the owner local so
  // the BrowserView boundary remains free of Browser and TabModel lifecycle.
  content::WebContents::CreateParams create_params(profile);
  std::unique_ptr<content::WebContents> contents =
      content::WebContents::Create(create_params);
  CHECK(contents);
  ReportBrowserViewSmokeStep("web-contents-created");
  content::WebContents* const raw_contents = contents.get();
  browser_view->OnActiveTabChanged(/*old_contents=*/nullptr, raw_contents,
                                   /*index=*/0, /*reason=*/0);
  ReportBrowserViewSmokeStep("web-contents-attached");
  CHECK_EQ(browser_view->GetActiveWebContents(), raw_contents);
  CHECK_EQ(browser_view->contents_web_view()->GetWebContents(), raw_contents);

  // Set bounds after attachment so the real FillLayout resizes the selected
  // WebView, then expose the actual Aura/Ozone window through BrowserView.
  browser_view->SetBounds(kBrowserViewSmokeBounds);
  CHECK_EQ(browser_view->GetBounds().size(), kBrowserViewSmokeBounds.size());
  widget->GetRootView()->DeprecatedLayoutImmediately();
  CHECK_EQ(browser_view->GetContentsSize(), kBrowserViewSmokeBounds.size());
  ReportBrowserViewSmokeStep("contents-sized");
  browser_view->Show();
  CHECK(browser_view->IsVisible());
  ReportBrowserViewSmokeStep("widget-shown");

  // Give the shown Aura/Ozone Widget one bounded UI turn before teardown.
  // This is not a frame assertion. Only the browser host can validate
  // presentation through reportFrame/reportReadiness on a real canvas.
  base::RunLoop visible_run_loop;
  base::OneShotTimer visible_timer;
  visible_timer.Start(FROM_HERE, kBrowserViewSmokeVisibleDuration,
                      visible_run_loop.QuitClosure());
  visible_run_loop.Run();
  ReportBrowserViewSmokeStep("visible-turn-complete");

  // Do not use BrowserWindow::Close(): it is intentionally unsupported by
  // this object-only slice. Detach the externally-owned contents first, then
  // break the canonical BrowserView/BrowserWidget cycle. CLIENT_OWNS_WIDGET
  // posts native host shutdown; drain it before reporting success.
  browser_view->OnTabDetached(raw_contents, /*was_active=*/true);
  CHECK(!browser_view->GetActiveWebContents());
  contents.reset();
  ReportBrowserViewSmokeStep("web-contents-detached");
  BrowserView::DestroyForWasmBrowserViewSmoke(browser_view);
  ReportBrowserViewSmokeStep("widget-reset");
  base::RunLoop().RunUntilIdle();
  ReportBrowserViewSmokeStep("native-teardown-drained");

  std::fprintf(stderr, "%s:PASS\n", kBrowserViewSmokeMarker);
  return true;
}

}  // namespace chrome

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_downloads_ui.h"

#include <memory>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/memory/ref_counted_memory.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/url_data_source.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/webui_config_map.h"
#include "content/public/common/url_constants.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_downloads_ui.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kWasmDownloadsHost[] = "downloads";

bool IsWasmDownloadsRootURL(const GURL& url) {
  return url.SchemeIs(content::kChromeUIScheme) &&
         url.host() == kWasmDownloadsHost &&
         (url.path() == "/" || url.path().empty()) && !url.has_username() &&
         !url.has_password() && !url.has_port() && !url.has_query() &&
         !url.has_ref();
}

// This document is intentionally static. It has no JavaScript, rows, buttons,
// DownloadManager query, or export action that could look like a completed M7
// downloads implementation.
constexpr char kWasmDownloadsUnavailableHtml[] = R"HTML(<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="light dark">
  <title>Downloads — Chromium Wasm</title>
  <style>
    :root { color-scheme: light dark; font: 16px/1.5 sans-serif; }
    body { margin: 0; background: Canvas; color: CanvasText; }
    main { box-sizing: border-box; margin: 0 auto; max-width: 760px; padding: 32px 24px 48px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    h2 { margin: 28px 0 8px; font-size: 19px; }
    p { max-width: 68ch; }
    .badge { display: inline-block; margin: 0 0 18px; padding: 3px 8px; border: 1px solid currentColor; border-radius: 999px; font-weight: 600; }
    .notice { border-inline-start: 4px solid #d97706; padding: 12px 16px; background: color-mix(in srgb, #d97706 12%, Canvas); }
  </style>
</head>
<body>
  <main id="wasm-downloads-bootstrap" aria-labelledby="page-title">
    <h1 id="page-title">Downloads</h1>
    <p class="badge" id="wasm-downloads-state">Unavailable until M7 OPFS/export</p>
    <section class="notice" aria-labelledby="unavailable-title">
      <h2 id="unavailable-title">No download storage or export is available</h2>
      <p>The M6 Wasm profile intentionally has no
      <code>DownloadManagerDelegate</code>. This root-only browser WebUI is a
      truthful status page, not the desktop Chrome Downloads application.</p>
      <p>There are no download records, controls, synthetic completion states,
      filesystem writes, or export actions. M7 must provide OPFS-backed
      download storage and an explicit export lifecycle before those routes can
      be exposed.</p>
    </section>
  </main>
</body>
</html>
)HTML";

class WasmDownloadsDataSource final : public content::URLDataSource {
 public:
  WasmDownloadsDataSource() = default;
  WasmDownloadsDataSource(const WasmDownloadsDataSource&) = delete;
  WasmDownloadsDataSource& operator=(const WasmDownloadsDataSource&) = delete;
  ~WasmDownloadsDataSource() override = default;

  std::string GetSource() override { return kWasmDownloadsHost; }

  void StartDataRequest(const GURL& url,
                        const content::WebContents::Getter& /*wc_getter*/,
                        GotDataCallback callback) override {
    if (!IsWasmDownloadsRootURL(url)) {
      std::move(callback).Run(nullptr);
      return;
    }
    std::move(callback).Run(base::MakeRefCounted<base::RefCountedString>(
        std::string(kWasmDownloadsUnavailableHtml)));
  }

  std::string GetMimeType(const GURL& /*url*/) override {
    return "text/html";
  }

  bool AllowCaching() override { return false; }
};

}  // namespace

WasmDownloadsUI::WasmDownloadsUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  DCHECK(web_ui);
  DCHECK(web_ui->GetWebContents());
  content::URLDataSource::Add(
      web_ui->GetWebContents()->GetBrowserContext(),
      std::make_unique<WasmDownloadsDataSource>());
}

WasmDownloadsUI::~WasmDownloadsUI() = default;

WEB_UI_CONTROLLER_TYPE_IMPL(WasmDownloadsUI)

WasmDownloadsUIConfig::WasmDownloadsUIConfig()
    : DefaultWebUIConfig(content::kChromeUIScheme, kWasmDownloadsHost) {}

WasmDownloadsUIConfig::~WasmDownloadsUIConfig() = default;

bool WasmDownloadsUIConfig::ShouldHandleURL(const GURL& url) {
  return IsWasmDownloadsRootURL(url);
}

void EnsureWasmDownloadsWebUIConfigRegistered() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  static bool registered = false;
  if (registered) {
    return;
  }
  content::WebUIConfigMap::GetInstance().AddWebUIConfig(
      std::make_unique<WasmDownloadsUIConfig>());
  registered = true;
}

}  // namespace chrome

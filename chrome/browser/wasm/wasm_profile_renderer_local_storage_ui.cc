// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_renderer_local_storage_ui.h"

#include <memory>
#include <string>
#include <string_view>
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
#error "wasm_profile_renderer_local_storage_ui.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kWasmProfileRendererLocalStorageHost[] = "m7-local-storage";

bool IsWasmProfileRendererLocalStorageToken(std::string_view token) {
  if (token.size() != 64) {
    return false;
  }
  for (const char character : token) {
    if (!((character >= '0' && character <= '9') ||
          (character >= 'a' && character <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool IsWasmProfileRendererLocalStorageRootURL(const GURL& url) {
  // The opaque test token is carried only in the transient page's query. The
  // ChromeMain parser already bounds it to lowercase hexadecimal before this
  // WebUI is created, and no URL is ever emitted through the fixed receipt.
  if (!url.SchemeIs(content::kChromeUIScheme) ||
      url.host() != kWasmProfileRendererLocalStorageHost ||
      !(url.path().empty() || url.path() == "/") || url.has_username() ||
      url.has_password() || url.has_port() || url.has_ref()) {
    return false;
  }
  const std::string_view query = url.query();
  constexpr std::string_view kWritePrefix = "mode=renderer-write&token=";
  constexpr std::string_view kVerifyPrefix = "mode=renderer-verify&token=";
  if (query.starts_with(kWritePrefix)) {
    return IsWasmProfileRendererLocalStorageToken(
        query.substr(kWritePrefix.size()));
  }
  if (query.starts_with(kVerifyPrefix)) {
    return IsWasmProfileRendererLocalStorageToken(
        query.substr(kVerifyPrefix.size()));
  }
  return false;
}

bool IsWasmProfileRendererLocalStorageScriptURL(const GURL& url) {
  return url.SchemeIs(content::kChromeUIScheme) &&
         url.host() == kWasmProfileRendererLocalStorageHost &&
         url.path() == "/m7_local_storage_renderer.js" &&
         !url.has_username() && !url.has_password() && !url.has_port() &&
         !url.has_query() && !url.has_ref();
}

constexpr char kRendererLocalStorageHtml[] = R"HTML(<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>m7-local-storage-pending</title>
  <script src="m7_local_storage_renderer.js"></script>
</head>
<body></body>
</html>
)HTML";

// This must remain an external script. URLDataSource's default CSP rejects
// inline script, and the external resource makes the test use a normal Blink
// script fetch/execution path before it touches window.localStorage.
constexpr char kRendererLocalStorageScript[] = R"JS((() => {
  "use strict";
  const parameters = new URLSearchParams(globalThis.location.search);
  const mode = parameters.get("mode");
  const token = parameters.get("token");
  const tokenPattern = /^[0-9a-f]{64}$/;
  const tokenKey = "m7-renderer-local-storage-token-v1";
  const fenceKey = "m7-renderer-local-storage-close-fence-v1";
  const fail = () => { document.title = "m7-local-storage-failed"; };

  if (!tokenPattern.test(token || "")) {
    fail();
    return;
  }
  try {
    if (mode === "renderer-write") {
      globalThis.localStorage.setItem(tokenKey, token);
      document.title = "m7-local-storage-renderer-write-ok";
      return;
    }
    if (mode === "renderer-verify" &&
        globalThis.localStorage.getItem(tokenKey) === token) {
      // A distinct mutation guarantees an UpdateMaps candidate for the second
      // module's close fence without making the stored token itself a no-op.
      globalThis.localStorage.setItem(fenceKey, token);
      document.title = "m7-local-storage-renderer-verify-ok";
      return;
    }
  } catch (_error) {
    // The browser side intentionally receives one fixed, token-free failure
    // title; it never observes page exception text.
  }
  fail();
})();
)JS";

class WasmProfileRendererLocalStorageDataSource final
    : public content::URLDataSource {
 public:
  WasmProfileRendererLocalStorageDataSource() = default;
  WasmProfileRendererLocalStorageDataSource(
      const WasmProfileRendererLocalStorageDataSource&) = delete;
  WasmProfileRendererLocalStorageDataSource& operator=(
      const WasmProfileRendererLocalStorageDataSource&) = delete;
  ~WasmProfileRendererLocalStorageDataSource() override = default;

  std::string GetSource() override {
    return kWasmProfileRendererLocalStorageHost;
  }

  void StartDataRequest(const GURL& url,
                        const content::WebContents::Getter& /*wc_getter*/,
                        GotDataCallback callback) override {
    if (IsWasmProfileRendererLocalStorageRootURL(url)) {
      std::move(callback).Run(base::MakeRefCounted<base::RefCountedString>(
          std::string(kRendererLocalStorageHtml)));
      return;
    }
    if (IsWasmProfileRendererLocalStorageScriptURL(url)) {
      std::move(callback).Run(base::MakeRefCounted<base::RefCountedString>(
          std::string(kRendererLocalStorageScript)));
      return;
    }
    std::move(callback).Run(nullptr);
  }

  std::string GetMimeType(const GURL& url) override {
    return IsWasmProfileRendererLocalStorageScriptURL(url)
               ? "text/javascript"
               : "text/html";
  }

  bool AllowCaching() override { return false; }
};

}  // namespace

WasmProfileRendererLocalStorageUI::WasmProfileRendererLocalStorageUI(
    content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  DCHECK(web_ui);
  DCHECK(web_ui->GetWebContents());
  content::URLDataSource::Add(
      web_ui->GetWebContents()->GetBrowserContext(),
      std::make_unique<WasmProfileRendererLocalStorageDataSource>());
}

WasmProfileRendererLocalStorageUI::~WasmProfileRendererLocalStorageUI() =
    default;

WEB_UI_CONTROLLER_TYPE_IMPL(WasmProfileRendererLocalStorageUI)

WasmProfileRendererLocalStorageUIConfig::
    WasmProfileRendererLocalStorageUIConfig()
    : DefaultWebUIConfig(content::kChromeUIScheme,
                          kWasmProfileRendererLocalStorageHost) {}

WasmProfileRendererLocalStorageUIConfig::
    ~WasmProfileRendererLocalStorageUIConfig() = default;

bool WasmProfileRendererLocalStorageUIConfig::ShouldHandleURL(
    const GURL& url) {
  return IsWasmProfileRendererLocalStorageRootURL(url);
}

void EnsureWasmProfileRendererLocalStorageWebUIConfigRegistered() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  static bool registered = false;
  if (registered) {
    return;
  }
  content::WebUIConfigMap::GetInstance().AddWebUIConfig(
      std::make_unique<WasmProfileRendererLocalStorageUIConfig>());
  registered = true;
}

}  // namespace chrome

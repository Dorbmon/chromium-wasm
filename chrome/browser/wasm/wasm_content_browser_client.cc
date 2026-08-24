// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_content_browser_client.h"

#include <memory>
#include <string>

#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_browser_main_parts.h"
#include "components/embedder_support/user_agent_utils.h"
#include "content/public/common/url_constants.h"
#include "url/gurl.h"
#include "url/url_constants.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_content_browser_client.cc must only be built for WebAssembly"
#endif

namespace {

constexpr char kWasmVersionHost[] = "version";
constexpr char kWasmSettingsHost[] = "settings";
constexpr char kWasmHistoryHost[] = "history";
constexpr char kWasmDownloadsHost[] = "downloads";
constexpr char kWasmThemeHost[] = "theme";
constexpr char kWasmResourcesHost[] = "resources";

bool IsWasmRootChromeUrl(const GURL& url, const char* host) {
  return url.SchemeIs(content::kChromeUIScheme) && url.host() == host &&
         (url.path() == "/" || url.path().empty()) && !url.has_username() &&
         !url.has_password() && !url.has_port() && !url.has_query() &&
         !url.has_ref();
}

}  // namespace

WasmContentBrowserClient::WasmContentBrowserClient() = default;

WasmContentBrowserClient::~WasmContentBrowserClient() = default;

std::unique_ptr<content::BrowserMainParts>
WasmContentBrowserClient::CreateBrowserMainParts(bool is_integration_test) {
  return std::make_unique<WasmBrowserMainParts>(is_integration_test);
}

std::string WasmContentBrowserClient::GetApplicationLocale() {
  return "en-US";
}

std::string WasmContentBrowserClient::GetAcceptLangs(
    content::BrowserContext* /*context*/) {
  // The volatile M6 profile does not expose user-configurable language prefs.
  // Keep network negotiation deterministic until the profile settings slice is
  // backed by OPFS.
  return "en-US,en";
}

std::string WasmContentBrowserClient::GetProduct() {
  return embedder_support::GetProductAndVersion();
}

std::string WasmContentBrowserClient::GetUserAgent() {
  return embedder_support::GetUserAgent();
}

blink::UserAgentMetadata WasmContentBrowserClient::GetUserAgentMetadata() {
  return embedder_support::GetUserAgentMetadata();
}

bool WasmContentBrowserClient::AllowCompressionDictionaryTransport(
    content::BrowserContext* /*context*/) {
  // This service owns profile-backed dictionary state. Keep it disabled until
  // it has durable backing and a result-bearing terminal drain at shutdown.
  return false;
}

bool WasmContentBrowserClient::IsHandledURL(const GURL& url) {
  if (!url.is_valid())
    return false;

  // The M6 foundation supports ordinary web navigation and empty documents.
  // It source-selects VersionUI plus bounded static Settings/History/Downloads
  // roots. Theme and resources remain dependency-only subresource origins
  // rather than general user-navigable Chrome routes.
  return url.SchemeIsHTTPOrHTTPS() || url.SchemeIs(url::kAboutScheme) ||
         url.SchemeIs(url::kDataScheme) || url.SchemeIs(url::kBlobScheme) ||
         (url.SchemeIs(content::kChromeUIScheme) &&
          (url.host() == kWasmVersionHost || url.host() == kWasmSettingsHost ||
           IsWasmRootChromeUrl(url, kWasmHistoryHost) ||
           IsWasmRootChromeUrl(url, kWasmDownloadsHost) ||
           url.host() == kWasmThemeHost || url.host() == kWasmResourcesHost));
}

bool WasmContentBrowserClient::ShouldEnableBtm(
    content::BrowserContext* /*browser_context*/) {
  // This service owns profile-backed SQLite state. Keep it disabled until it
  // has durable backing and a result-bearing terminal drain at shutdown.
  return false;
}

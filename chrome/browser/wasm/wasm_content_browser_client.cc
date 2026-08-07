// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_content_browser_client.h"

#include <memory>
#include <string>

#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_browser_main_parts.h"
#include "components/embedder_support/user_agent_utils.h"
#include "url/gurl.h"
#include "url/url_constants.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_content_browser_client.cc must only be built for WebAssembly"
#endif

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

bool WasmContentBrowserClient::IsHandledURL(const GURL& url) {
  if (!url.is_valid())
    return false;

  // The M6 foundation supports ordinary web navigation and empty documents.
  // Chrome WebUI URLs are intentionally not marked handled until their real
  // controllers and browser services are source-selected.
  return url.SchemeIsHTTPOrHTTPS() || url.SchemeIs(url::kAboutScheme) ||
         url.SchemeIs(url::kDataScheme) || url.SchemeIs(url::kBlobScheme);
}

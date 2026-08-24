// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_CONTENT_BROWSER_CLIENT_H_
#define CHROME_BROWSER_WASM_WASM_CONTENT_BROWSER_CLIENT_H_

#include <memory>
#include <string>

#include "content/public/browser/content_browser_client.h"

class GURL;

namespace blink {
struct UserAgentMetadata;
}

namespace content {
class BrowserContext;
class BrowserMainParts;
}

// Chrome's browser-side Content client for the source-selected Wasm process.
//
// This intentionally starts from ContentBrowserClient rather than inheriting
// ChromeContentBrowserClient: the latter owns desktop startup, policy, and
// keyed-service graph assumptions which do not exist in the M6 foundation.
// Chrome-specific browser behavior joins this client one explicit feature
// boundary at a time.
class WasmContentBrowserClient final : public content::ContentBrowserClient {
 public:
  WasmContentBrowserClient();
  WasmContentBrowserClient(const WasmContentBrowserClient&) = delete;
  WasmContentBrowserClient& operator=(const WasmContentBrowserClient&) =
      delete;
  ~WasmContentBrowserClient() override;

  // content::ContentBrowserClient:
  std::unique_ptr<content::BrowserMainParts> CreateBrowserMainParts(
      bool is_integration_test) override;
  std::string GetApplicationLocale() override;
  std::string GetAcceptLangs(content::BrowserContext* context) override;
  std::string GetProduct() override;
  std::string GetUserAgent() override;
  blink::UserAgentMetadata GetUserAgentMetadata() override;
  bool AllowCompressionDictionaryTransport(
      content::BrowserContext* context) override;
  bool IsHandledURL(const GURL& url) override;
  bool ShouldEnableBtm(content::BrowserContext* browser_context) override;
};

#endif  // CHROME_BROWSER_WASM_WASM_CONTENT_BROWSER_CLIENT_H_

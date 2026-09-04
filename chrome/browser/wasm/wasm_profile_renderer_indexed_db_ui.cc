// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_renderer_indexed_db_ui.h"

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
#error "wasm_profile_renderer_indexed_db_ui.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kWasmProfileRendererIndexedDBHost[] = "m7-indexed-db";

bool IsWasmProfileRendererIndexedDBToken(std::string_view token) {
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

bool IsWasmProfileRendererIndexedDBRootURL(const GURL& url) {
  // The opaque test tokens are carried only in the transient page's query.
  // The ChromeMain parser already bounds them to lowercase hexadecimal before
  // this WebUI is created, and no URL is ever emitted through a fixed receipt.
  if (!url.SchemeIs(content::kChromeUIScheme) ||
      url.host() != kWasmProfileRendererIndexedDBHost ||
      !(url.path().empty() || url.path() == "/") || url.has_username() ||
      url.has_password() || url.has_port() || url.has_ref()) {
    return false;
  }

  const std::string_view query = url.query();
  constexpr std::string_view kWritePrefix =
      "mode=renderer-write&token-a=";
  constexpr std::string_view kCacheAPIWriteReadbackSuffix =
      "&cache-api=write-readback";
  constexpr std::string_view kVerifyAWriteBPrefix =
      "mode=renderer-verify-a-write-b&token-a=";
  constexpr std::string_view kVerifyAWriteBSeparator = "&token-b=";
  constexpr std::string_view kVerifyBPrefix =
      "mode=renderer-verify-b&token-b=";

  if (query.starts_with(kWritePrefix)) {
    std::string_view token = query.substr(kWritePrefix.size());
    if (token.ends_with(kCacheAPIWriteReadbackSuffix)) {
      token = token.substr(
          0, token.size() - kCacheAPIWriteReadbackSuffix.size());
    }
    return IsWasmProfileRendererIndexedDBToken(token);
  }
  if (query.starts_with(kVerifyBPrefix)) {
    return IsWasmProfileRendererIndexedDBToken(
        query.substr(kVerifyBPrefix.size()));
  }
  if (!query.starts_with(kVerifyAWriteBPrefix)) {
    return false;
  }

  const std::string_view tokens = query.substr(kVerifyAWriteBPrefix.size());
  const size_t separator = tokens.find(kVerifyAWriteBSeparator);
  if (separator == std::string_view::npos) {
    return false;
  }
  const std::string_view token_a = tokens.substr(0, separator);
  const std::string_view token_b =
      tokens.substr(separator + kVerifyAWriteBSeparator.size());
  return IsWasmProfileRendererIndexedDBToken(token_a) &&
         IsWasmProfileRendererIndexedDBToken(token_b) && token_a != token_b;
}

bool IsWasmProfileRendererIndexedDBScriptURL(const GURL& url) {
  return url.SchemeIs(content::kChromeUIScheme) &&
         url.host() == kWasmProfileRendererIndexedDBHost &&
         url.path() == "/m7_indexed_db_renderer.js" &&
         !url.has_username() && !url.has_password() && !url.has_port() &&
         !url.has_query() && !url.has_ref();
}

constexpr char kRendererIndexedDBHtml[] = R"HTML(<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>m7-indexed-db-pending</title>
  <script src="m7_indexed_db_renderer.js"></script>
</head>
<body></body>
</html>
)HTML";

// This must remain an external script. URLDataSource's default CSP rejects
// inline script, and the external resource makes the test use a normal Blink
// script fetch/execution path before it touches globalThis.indexedDB.
constexpr char kRendererIndexedDBScript[] = R"JS((() => {
  "use strict";
  const parameters = new URLSearchParams(globalThis.location.search);
  const mode = parameters.get("mode");
  const tokenA = parameters.get("token-a");
  const tokenB = parameters.get("token-b");
  const requireCacheApiWriteReadback =
      parameters.get("cache-api") === "write-readback";
  const tokenPattern = /^[0-9a-f]{64}$/;
  const databaseName = "m7-renderer-indexed-db-v1";
  const storeName = "m7-renderer-indexed-db-store-v1";
  const tokenKey = "m7-renderer-indexed-db-token-v1";
  const fenceKey = "m7-renderer-indexed-db-close-fence-v1";
  const fenceValue = "m7-renderer-indexed-db-close-fence-value-v1";
  // Never surface an exception value or a token. The fixed category is enough
  // to distinguish a renderer storage failure from a navigation failure in
  // this source-selected test artifact.
  const fixedFailureCategories = new Set([
    "arguments", "fence-abort", "fence-error", "fence-exception",
    "cache-api-match-error", "cache-api-match-exception",
    "cache-api-readback-mismatch", "cache-api-open-error",
    "cache-api-put-error",
    "open-abort", "open-backing-store", "open-blocked", "open-exception",
    "open-invalid-state", "open-missing-bucket", "open-not-allowed",
    "open-other", "open-quota", "open-security", "open-unknown",
    "read-a-mismatch", "read-b-mismatch", "read-error", "read-exception",
    "unknown", "write-abort", "write-error", "write-exception",
  ]);
  const fail = (category = "unknown") => {
    const fixedCategory = fixedFailureCategories.has(category) ? category :
        "unknown";
    console.error(
        "CHROMIUM_WASM_M7_INDEXED_DB_RENDERER_FAILURE:" + fixedCategory);
    document.title = "m7-indexed-db-failed";
  };

  const classifyOpenError = (request) => {
    switch (request.error && request.error.name) {
      case "AbortError": return "open-abort";
      case "InvalidStateError": return "open-invalid-state";
      case "NotAllowedError": return "open-not-allowed";
      case "QuotaExceededError": return "open-quota";
      case "SecurityError": return "open-security";
      case "UnknownError":
        if (request.error && request.error.message === "Internal error.") {
          return "open-missing-bucket";
        }
        return request.error && request.error.message ===
            "Internal error opening backing store for indexedDB.open." ?
            "open-backing-store" : "open-unknown";
      default: return "open-other";
    }
  };

  const hasExactParameters = (expectedNames) => {
    const names = Array.from(parameters.keys());
    return names.length === expectedNames.length &&
        names.every((name, index) => name === expectedNames[index]);
  };

  const openDatabase = () => new Promise((resolve, reject) => {
    let request;
    try {
      request = globalThis.indexedDB.open(databaseName, 1);
    } catch (_error) {
      reject("open-exception");
      return;
    }
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(storeName)) {
        database.createObjectStore(storeName);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(classifyOpenError(request));
    request.onblocked = () => reject("open-blocked");
  });

  const readToken = (database) => new Promise((resolve, reject) => {
    let request;
    try {
      request = database.transaction(storeName, "readonly")
          .objectStore(storeName).get(tokenKey);
    } catch (_error) {
      reject("read-exception");
      return;
    }
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject("read-error");
  });

  const writeToken = (database, token) => new Promise((resolve, reject) => {
    let transaction;
    try {
      transaction = database.transaction(storeName, "readwrite");
      transaction.objectStore(storeName).put(token, tokenKey);
    } catch (_error) {
      reject("write-exception");
      return;
    }
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject("write-error");
    transaction.onabort = () => reject("write-abort");
  });

  const writeFence = (database) => new Promise((resolve, reject) => {
    let transaction;
    try {
      transaction = database.transaction(storeName, "readwrite");
      transaction.objectStore(storeName).put(fenceValue, fenceKey);
    } catch (_error) {
      reject("fence-exception");
      return;
    }
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject("fence-error");
    transaction.onabort = () => reject("fence-abort");
  });

  const writeAndReadCacheApiToken = async (token) => {
    const cacheName = "m7-renderer-cache-api-write-readback-v1-" + token;
    const request = new Request(
        "https://m7-cache-api-write-readback.test/" + token,
        {method: "GET"});
    let cache;
    try {
      cache = await globalThis.caches.open(cacheName);
    } catch (_error) {
      throw "cache-api-open-error";
    }
    // Keep the browser-side CacheStorageCacheHandle live until the browser
    // participant observes the native backend close/index-replacement receipt.
    // The page performs no Cache API calls after publishing its title.
    globalThis.__m7RendererCacheApiWriteReadbackCache = cache;
    try {
      await cache.put(request, new Response(token));
    } catch (_error) {
      throw "cache-api-put-error";
    }
    let response;
    try {
      response = await cache.match(request);
    } catch (_error) {
      throw "cache-api-match-error";
    }
    if (!response) {
      throw "cache-api-readback-mismatch";
    }
    try {
      if (await response.text() !== token) {
        throw "cache-api-readback-mismatch";
      }
    } catch (category) {
      throw category === "cache-api-readback-mismatch" ? category :
          "cache-api-match-exception";
    }
  };

  const complete = async () => {
    if (mode === "renderer-write" &&
        hasExactParameters(requireCacheApiWriteReadback ?
            ["mode", "token-a", "cache-api"] : ["mode", "token-a"]) &&
        tokenPattern.test(tokenA || "") && tokenB === null) {
      const database = await openDatabase();
      try {
        await writeToken(database, tokenA);
        if (requireCacheApiWriteReadback) {
          await writeAndReadCacheApiToken(tokenA);
        }
      } finally {
        database.close();
      }
      document.title = requireCacheApiWriteReadback ?
          "m7-indexed-db-renderer-write-cache-api-write-readback-ok" :
          "m7-indexed-db-renderer-write-ok";
      return;
    }

    if (mode === "renderer-verify-a-write-b" &&
        hasExactParameters(["mode", "token-a", "token-b"]) &&
        tokenPattern.test(tokenA || "") && tokenPattern.test(tokenB || "") &&
        tokenA !== tokenB) {
      const database = await openDatabase();
      try {
        if (await readToken(database) !== tokenA) {
          fail("read-a-mismatch");
          return;
        }
        await writeToken(database, tokenB);
      } finally {
        database.close();
      }
      document.title = "m7-indexed-db-renderer-verify-a-write-b-ok";
      return;
    }

    if (mode === "renderer-verify-b" &&
        hasExactParameters(["mode", "token-b"]) &&
        tokenA === null && tokenPattern.test(tokenB || "")) {
      const database = await openDatabase();
      try {
        if (await readToken(database) !== tokenB) {
          fail("read-b-mismatch");
          return;
        }
        await writeFence(database);
      } finally {
        database.close();
      }
      document.title = "m7-indexed-db-renderer-verify-b-ok";
      return;
    }

    fail("arguments");
  };

  complete().catch((category) => fail(category));
})();
)JS";

class WasmProfileRendererIndexedDBDataSource final
    : public content::URLDataSource {
 public:
  WasmProfileRendererIndexedDBDataSource() = default;
  WasmProfileRendererIndexedDBDataSource(
      const WasmProfileRendererIndexedDBDataSource&) = delete;
  WasmProfileRendererIndexedDBDataSource& operator=(
      const WasmProfileRendererIndexedDBDataSource&) = delete;
  ~WasmProfileRendererIndexedDBDataSource() override = default;

  std::string GetSource() override {
    return kWasmProfileRendererIndexedDBHost;
  }

  void StartDataRequest(const GURL& url,
                        const content::WebContents::Getter& /*wc_getter*/,
                        GotDataCallback callback) override {
    if (IsWasmProfileRendererIndexedDBRootURL(url)) {
      std::move(callback).Run(base::MakeRefCounted<base::RefCountedString>(
          std::string(kRendererIndexedDBHtml)));
      return;
    }
    if (IsWasmProfileRendererIndexedDBScriptURL(url)) {
      std::move(callback).Run(base::MakeRefCounted<base::RefCountedString>(
          std::string(kRendererIndexedDBScript)));
      return;
    }
    std::move(callback).Run(nullptr);
  }

  std::string GetMimeType(const GURL& url) override {
    return IsWasmProfileRendererIndexedDBScriptURL(url)
               ? "text/javascript"
               : "text/html";
  }

  bool AllowCaching() override { return false; }
};

}  // namespace

WasmProfileRendererIndexedDBUI::WasmProfileRendererIndexedDBUI(
    content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  DCHECK(web_ui);
  DCHECK(web_ui->GetWebContents());
  content::URLDataSource::Add(
      web_ui->GetWebContents()->GetBrowserContext(),
      std::make_unique<WasmProfileRendererIndexedDBDataSource>());
}

WasmProfileRendererIndexedDBUI::~WasmProfileRendererIndexedDBUI() = default;

WEB_UI_CONTROLLER_TYPE_IMPL(WasmProfileRendererIndexedDBUI)

WasmProfileRendererIndexedDBUIConfig::WasmProfileRendererIndexedDBUIConfig()
    : DefaultWebUIConfig(content::kChromeUIScheme,
                          kWasmProfileRendererIndexedDBHost) {}

WasmProfileRendererIndexedDBUIConfig::~WasmProfileRendererIndexedDBUIConfig() =
    default;

bool WasmProfileRendererIndexedDBUIConfig::ShouldHandleURL(const GURL& url) {
  return IsWasmProfileRendererIndexedDBRootURL(url);
}

void EnsureWasmProfileRendererIndexedDBWebUIConfigRegistered() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  static bool registered = false;
  if (registered) {
    return;
  }
  content::WebUIConfigMap::GetInstance().AddWebUIConfig(
      std::make_unique<WasmProfileRendererIndexedDBUIConfig>());
  registered = true;
}

}  // namespace chrome

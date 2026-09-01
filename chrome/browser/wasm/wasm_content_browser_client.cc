// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_content_browser_client.h"

#include <memory>
#include <string>
#include <string_view>

#include "base/files/file_path.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_browser_main_parts.h"
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
// GN's include checker does not evaluate this target-specific definition.
#include "chrome/browser/wasm/wasm_profile_preferences_smoke.h"  // nogncheck
#endif
#include "components/embedder_support/user_agent_utils.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition_config.h"
#include "content/public/common/url_constants.h"
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
// GN's include checker does not evaluate this target-specific definition.
#include "services/network/public/mojom/network_context.mojom.h"  // nogncheck
#endif
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
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
constexpr char kWasmNetworkDataDirectory[] = "Network";
#endif
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
constexpr char kWasmM7RendererLocalStorageHost[] = "m7-local-storage";

bool IsWasmM7RendererLocalStorageToken(std::string_view token) {
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
#endif

bool IsWasmRootChromeUrl(const GURL& url, const char* host) {
  return url.SchemeIs(content::kChromeUIScheme) && url.host() == host &&
         (url.path() == "/" || url.path().empty()) && !url.has_username() &&
         !url.has_password() && !url.has_port() && !url.has_query() &&
         !url.has_ref();
}

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
bool IsWasmM7RendererLocalStorageURL(const GURL& url) {
  if (!url.SchemeIs(content::kChromeUIScheme) ||
      url.host() != kWasmM7RendererLocalStorageHost || url.has_username() ||
      url.has_password() || url.has_port() || url.has_ref()) {
    return false;
  }
  // The root is the only navigable test document, and only its private
  // renderer mode/token query is permitted. Its external script is the sole
  // additional resource needed by the test WebUI; arbitrary subpaths remain
  // external protocols.
  if (url.path().empty() || url.path() == "/") {
    const std::string_view query = url.query();
    constexpr std::string_view kWritePrefix = "mode=renderer-write&token=";
    constexpr std::string_view kVerifyPrefix = "mode=renderer-verify&token=";
    if (query.starts_with(kWritePrefix)) {
      return IsWasmM7RendererLocalStorageToken(
          query.substr(kWritePrefix.size()));
    }
    if (query.starts_with(kVerifyPrefix)) {
      return IsWasmM7RendererLocalStorageToken(
          query.substr(kVerifyPrefix.size()));
    }
    return false;
  }
  return url.path() == "/m7_local_storage_renderer.js" && !url.has_query();
}
#endif

#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
constexpr char kWasmM7RendererIndexedDBHost[] = "m7-indexed-db";
constexpr char kWasmM7RendererIndexedDBPartitionDomain[] = "wasmindexeddb";
constexpr char kWasmM7RendererIndexedDBPartitionName[] = "indexeddb";

bool IsWasmM7RendererIndexedDBToken(std::string_view token) {
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

bool IsWasmM7RendererIndexedDBURL(const GURL& url) {
  if (!url.SchemeIs(content::kChromeUIScheme) ||
      url.host() != kWasmM7RendererIndexedDBHost || url.has_username() ||
      url.has_password() || url.has_port() || url.has_ref()) {
    return false;
  }
  // The root is the only navigable test document, and only its private
  // renderer mode/token query is permitted. Its external script is the sole
  // additional resource needed by the test WebUI; arbitrary subpaths remain
  // external protocols.
  if (url.path().empty() || url.path() == "/") {
    const std::string_view query = url.query();
    constexpr std::string_view kWritePrefix =
        "mode=renderer-write&token-a=";
    constexpr std::string_view kVerifyAWriteBPrefix =
        "mode=renderer-verify-a-write-b&token-a=";
    constexpr std::string_view kVerifyAWriteBSeparator = "&token-b=";
    constexpr std::string_view kVerifyBPrefix =
        "mode=renderer-verify-b&token-b=";
    if (query.starts_with(kWritePrefix)) {
      return IsWasmM7RendererIndexedDBToken(
          query.substr(kWritePrefix.size()));
    }
    if (query.starts_with(kVerifyBPrefix)) {
      return IsWasmM7RendererIndexedDBToken(
          query.substr(kVerifyBPrefix.size()));
    }
    if (!query.starts_with(kVerifyAWriteBPrefix)) {
      return false;
    }

    const std::string_view tokens =
        query.substr(kVerifyAWriteBPrefix.size());
    const size_t separator = tokens.find(kVerifyAWriteBSeparator);
    if (separator == std::string_view::npos) {
      return false;
    }
    const std::string_view token_a = tokens.substr(0, separator);
    const std::string_view token_b =
        tokens.substr(separator + kVerifyAWriteBSeparator.size());
    return IsWasmM7RendererIndexedDBToken(token_a) &&
           IsWasmM7RendererIndexedDBToken(token_b) && token_a != token_b;
  }
  return url.path() == "/m7_indexed_db_renderer.js" && !url.has_query();
}

bool IsWasmM7RendererIndexedDBSite(const GURL& site) {
  // StoragePartition selection is site-scoped rather than resource-scoped.
  // The page and its one allowed script must resolve to the same non-default
  // partition even when Content has canonicalized the supplied site URL.
  return site.SchemeIs(content::kChromeUIScheme) &&
         site.host() == kWasmM7RendererIndexedDBHost &&
         (site.path().empty() || site.path() == "/") &&
         !site.has_username() && !site.has_password() && !site.has_port() &&
         !site.has_query() && !site.has_ref();
}
#endif

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

void WasmContentBrowserClient::ConfigureNetworkContextParams(
    content::BrowserContext* context,
    bool in_memory,
    const base::FilePath& relative_partition_path,
    network::mojom::NetworkContextParams* network_context_params,
    cert_verifier::mojom::CertVerifierCreationParams*
        cert_verifier_creation_params) {
  content::ContentBrowserClient::ConfigureNetworkContextParams(
      context, in_memory, relative_partition_path, network_context_params,
      cert_verifier_creation_params);

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  // The normal Wasm profile deliberately keeps every StoragePartition store
  // in memory. This optional capability changes only the default in-memory
  // partition's CookieManager: its actual Cookies SQLite database uses
  // Chromium's canonical Default/Network/Cookies layout under the V4-mounted
  // profile, while every other network file path and every non-network
  // partition service remains memory-backed.
  if (!chrome::IsWasmProfilePreferencesCookieSmokeEnabled() || !context ||
      !in_memory || !relative_partition_path.empty()) {
    return;
  }

  const base::FilePath profile_path = context->GetPath();
  if (profile_path.empty() || network_context_params->file_paths) {
    // The source-selected Wasm client owns no other persistent NetworkContext
    // paths. Refuse to overlay another owner rather than broadening the
    // Cookie-only acceptance capability.
    return;
  }
  network_context_params->file_paths =
      network::mojom::NetworkContextFilePaths::New();
  network_context_params->file_paths->data_directory =
      profile_path.AppendASCII(kWasmNetworkDataDirectory);
  network_context_params->file_paths->cookie_database_name =
      base::FilePath(FILE_PATH_LITERAL("Cookies"));
  // NetworkContext defaults this to true and requires an OS crypto provider
  // on non-mobile platforms. The M7 probe has no such provider, so it proves
  // only an explicitly unencrypted test cookie database, never production
  // cookie-at-rest protection.
  network_context_params->enable_encrypted_cookies = false;
  network_context_params->restore_old_session_cookies = false;
  network_context_params->persist_session_cookies = false;
  network_context_params->http_cache_enabled = false;
#endif

#if defined(CHROME_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN_PROBE)
  // This fresh shutdown artifact configures exactly one non-memory default
  // NetworkContext with a persistent Cookies SQLite store under
  // Default/Network/Cookies. The matching probe accepts no aggregate partition
  // result or durable profile claim; its network-owned SQLite row-readback and
  // CookieManager close receipts are the sole service-level observations.
  // Normal Wasm Chrome never compiles this branch and keeps its default
  // partition in-memory.
  if (!context || in_memory || !relative_partition_path.empty()) {
    return;
  }
  const base::FilePath profile_path = context->GetPath();
  if (profile_path.empty() || network_context_params->file_paths) {
    return;
  }
  network_context_params->file_paths =
      network::mojom::NetworkContextFilePaths::New();
  network_context_params->file_paths->data_directory =
      profile_path.AppendASCII(kWasmNetworkDataDirectory);
  network_context_params->file_paths->cookie_database_name =
      base::FilePath(FILE_PATH_LITERAL("Cookies"));
  // The isolated Wasm test path has no OS crypto provider. This is an
  // explicitly unencrypted test database, not a production cookie-at-rest
  // configuration.
  network_context_params->enable_encrypted_cookies = false;
  network_context_params->restore_old_session_cookies = false;
  network_context_params->persist_session_cookies = false;
  network_context_params->http_cache_enabled = false;
#endif
}

content::StoragePartitionConfig
WasmContentBrowserClient::GetStoragePartitionConfigForSite(
    content::BrowserContext* browser_context,
    const GURL& site) {
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
  if (IsWasmM7RendererIndexedDBSite(site)) {
    // The isolated M7 IndexedDB probe owns one persistent, non-default
    // StoragePartition. The lowercase domain and name satisfy Chromium's
    // partition-path contract; normal Wasm sites retain the base default
    // selection below.
    return content::StoragePartitionConfig::Create(
        browser_context, kWasmM7RendererIndexedDBPartitionDomain,
        kWasmM7RendererIndexedDBPartitionName,
        /*in_memory=*/false);
  }
#endif
  return content::ContentBrowserClient::GetStoragePartitionConfigForSite(
      browser_context, site);
}

bool WasmContentBrowserClient::IsHandledURL(const GURL& url) {
  if (!url.is_valid())
    return false;

  // The M6 foundation supports ordinary web navigation and empty documents.
  // It source-selects VersionUI plus bounded static Settings/History/Downloads
  // roots. Theme and resources remain dependency-only subresource origins
  // rather than general user-navigable Chrome routes. The renderer M7 build
  // additionally permits only its exact root document and external script.
  return url.SchemeIsHTTPOrHTTPS() || url.SchemeIs(url::kAboutScheme) ||
         url.SchemeIs(url::kDataScheme) || url.SchemeIs(url::kBlobScheme) ||
         (url.SchemeIs(content::kChromeUIScheme) &&
          (url.host() == kWasmVersionHost || url.host() == kWasmSettingsHost ||
           IsWasmRootChromeUrl(url, kWasmHistoryHost) ||
           IsWasmRootChromeUrl(url, kWasmDownloadsHost) ||
           url.host() == kWasmThemeHost || url.host() == kWasmResourcesHost
#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
           || IsWasmM7RendererLocalStorageURL(url)
#endif
#if defined(CHROME_WASM_M7_PROFILE_INDEXED_DB_SMOKE_TEST)
           || IsWasmM7RendererIndexedDBURL(url)
#endif
           ));
}

bool WasmContentBrowserClient::ShouldEnableBtm(
    content::BrowserContext* /*browser_context*/) {
  // This service owns profile-backed SQLite state. Keep it disabled until it
  // has durable backing and a result-bearing terminal drain at shutdown.
  return false;
}

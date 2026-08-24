// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_settings_ui.h"

#include <stdint.h>

#include <memory>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/memory/ref_counted_memory.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_browser_host_storage_estimate.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/url_data_source.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/webui_config_map.h"
#include "content/public/common/url_constants.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_settings_ui.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kWasmSettingsHost[] = "settings";

bool IsWasmSettingsRootURL(const GURL& url) {
  return url.SchemeIs(content::kChromeUIScheme) &&
         url.host() == kWasmSettingsHost &&
         (url.path() == "/" || url.path().empty()) && !url.has_username() &&
         !url.has_password() && !url.has_port() && !url.has_query() &&
         !url.has_ref();
}

std::string BytesForWasmSettings(uint64_t bytes) {
  return base::StrCat({base::NumberToString(bytes), " bytes"});
}

// This renders only an already-captured immutable snapshot. It never queries
// the host bridge, profile, filesystem, or a mutable singleton while a
// URLDataSource request is in progress.
std::string BuildWasmSettingsStorageEstimateHtml(
    const WasmBrowserHostStorageEstimateSnapshot& snapshot) {
  std::string details;
  std::string zero_remaining_warning;
  switch (snapshot.state()) {
    case WasmBrowserHostStorageEstimateSnapshot::State::kPending:
      details = R"HTML(
        <dd id="wasm-settings-storage-estimate-state">Pending a read-only
        outer-origin estimate from the host browser.</dd>)HTML";
      break;
    case WasmBrowserHostStorageEstimateSnapshot::State::kAvailable: {
      const uint64_t remaining_bytes =
          snapshot.quota_bytes() - snapshot.usage_bytes();
      details = base::StrCat(
          {R"HTML(
        <dd id="wasm-settings-storage-estimate-state">Available from the
        host browser.</dd>
        <dt>Aggregate usage</dt>
        <dd id="wasm-settings-storage-estimate-usage">)HTML",
           BytesForWasmSettings(snapshot.usage_bytes()),
           R"HTML(</dd>
        <dt>Aggregate quota</dt>
        <dd id="wasm-settings-storage-estimate-quota">)HTML",
           BytesForWasmSettings(snapshot.quota_bytes()),
           R"HTML(</dd>)HTML"});
      details = base::StrCat(
          {std::move(details), R"HTML(
        <dt>Estimated remaining capacity</dt>
        <dd id="wasm-settings-storage-estimate-remaining">)HTML",
           BytesForWasmSettings(remaining_bytes),
           R"HTML(</dd>)HTML"});
      if (remaining_bytes == 0) {
        zero_remaining_warning = R"HTML(
      <p id="wasm-settings-storage-estimate-zero-remaining-warning"
          class="notice" role="status"><strong>Capacity warning:</strong>
      the host reported 0 bytes of remaining aggregate origin capacity. This
      is not Chromium Wasm profile quota, an OPFS reservation, a persistence
      grant, or an enforcement limit; it does not establish that the volatile
      profile is full.</p>)HTML";
      }
      break;
    }
    case WasmBrowserHostStorageEstimateSnapshot::State::kUnavailable:
      details = R"HTML(
        <dd id="wasm-settings-storage-estimate-state">Unavailable. The host
        browser does not expose an outer-origin storage estimate.</dd>)HTML";
      break;
    case WasmBrowserHostStorageEstimateSnapshot::State::kError:
      details = R"HTML(
        <dd id="wasm-settings-storage-estimate-state">Error. The host
        browser did not provide a valid outer-origin storage estimate.</dd>)HTML";
      break;
  }

  return base::StrCat(
      {R"HTML(
    <section aria-labelledby="storage-estimate-title">
      <h2 id="storage-estimate-title">Host-origin storage capacity</h2>
      <p id="wasm-settings-storage-estimate-scope">This is an
      <strong>outer-origin aggregate estimate</strong> from the host page's
      <code>navigator.storage.estimate()</code>. It is <strong>not Chromium
      Wasm profile quota</strong>, profile usage, an OPFS reservation, a
      persistence grant, or an enforcement limit.</p>
      <dl id="wasm-settings-storage-estimate">
        <dt>Estimate status</dt>)HTML",
       std::move(details), R"HTML(
      </dl>)HTML",
       std::move(zero_remaining_warning), R"HTML(
      <p>This read-only diagnostic is captured during Chrome startup. It does
      not request persistent storage, create files, or enable durable profile
      data.</p>
    </section>)HTML"});
}

// Keep this document self-contained. In particular, it has no script, host
// bridge, desktop SettingsUI resources, or setting-changing control. That
// lets the standard trusted chrome:// WebUI CSP remain in force.
constexpr char kWasmSettingsBootstrapHtmlPrefix[] = R"HTML(<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="light dark">
  <title>Settings — Chromium Wasm</title>
  <style>
    :root { color-scheme: light dark; font: 16px/1.5 sans-serif; }
    body { margin: 0; background: Canvas; color: CanvasText; }
    main { box-sizing: border-box; margin: 0 auto; max-width: 760px; padding: 32px 24px 48px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    h2 { margin: 28px 0 8px; font-size: 19px; }
    p, li, dd { max-width: 68ch; }
    .badge { display: inline-block; margin: 0 0 18px; padding: 3px 8px; border: 1px solid currentColor; border-radius: 999px; font-weight: 600; }
    .notice { border-inline-start: 4px solid #d97706; padding: 12px 16px; background: color-mix(in srgb, #d97706 12%, Canvas); }
    dl { margin: 0; }
    dt { font-weight: 600; margin-top: 10px; }
    dd { margin-inline-start: 0; }
    .footnote { margin-top: 28px; color: color-mix(in srgb, CanvasText 72%, Canvas); }
  </style>
</head>
<body>
  <main id="wasm-settings-bootstrap" aria-labelledby="page-title">
    <h1 id="page-title">Settings</h1>
    <p class="badge" id="wasm-settings-state">Limited M6 bootstrap</p>

    <section class="notice" aria-labelledby="limited-title">
      <h2 id="limited-title">This page is read-only and volatile</h2>
      <p>This is a small Chromium Wasm <code>chrome://settings</code> WebUI
      status page. It is rendered by the browser WebUI in the Wasm canvas, but
      it is not the desktop Chrome Settings application.</p>
      <p>No setting on this page can be changed. The M6 profile is deliberately
      volatile, so this page must not be used as evidence that settings or
      profile data survive browser or outer-page reloads.</p>
    </section>

    <section aria-labelledby="scope-title">
      <h2 id="scope-title">Current M6 scope</h2>
      <dl>
        <dt>Available route</dt>
        <dd>The trusted <code>chrome://settings/</code> route and this static
        status document.</dd>
        <dt>Storage</dt>
        <dd>No durable settings storage is provided here. OPFS-backed profile
        persistence is a later M7 requirement.</dd>
        <dt>Controls</dt>
        <dd>No appearance, privacy, search, sync, downloads, account, site, or
        system-setting controls are exposed by this bootstrap.</dd>
      </dl>
    </section>

    <!-- wasm-settings-host-storage-estimate -->
)HTML";

constexpr char kWasmSettingsBootstrapHtmlSuffix[] = R"HTML(
    <section aria-labelledby="future-title">
      <h2 id="future-title">Not yet implemented</h2>
      <ul>
        <li>Chrome's full SettingsUI resource and handler graph.</li>
        <li>Preference mutation, validation, and durable recovery.</li>
        <li>Desktop operating-system integrations and account services.</li>
      </ul>
    </section>

    <p class="footnote">The browser UI and profile implementation are still
    under active M6 development. This status is intentionally explicit rather
    than implying feature or persistence support that has not been verified.</p>
  </main>
</body>
</html>)HTML";

std::string BuildWasmSettingsBootstrapHtml(
    const WasmBrowserHostStorageEstimateSnapshot& snapshot) {
  return base::StrCat({kWasmSettingsBootstrapHtmlPrefix,
                       BuildWasmSettingsStorageEstimateHtml(snapshot),
                       kWasmSettingsBootstrapHtmlSuffix});
}

// A native URLDataSource keeps the status page inside Chromium's WebUI load
// path. It deliberately serves only the document root and returns no data for
// unselected subpaths rather than pretending to implement Settings routes.
class WasmSettingsDataSource final : public content::URLDataSource {
 public:
  explicit WasmSettingsDataSource(
      scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot>
          storage_estimate_snapshot)
      : storage_estimate_snapshot_(std::move(storage_estimate_snapshot)) {
    CHECK(storage_estimate_snapshot_);
  }
  WasmSettingsDataSource(const WasmSettingsDataSource&) = delete;
  WasmSettingsDataSource& operator=(const WasmSettingsDataSource&) = delete;
  ~WasmSettingsDataSource() override = default;

  // content::URLDataSource:
  std::string GetSource() override { return kWasmSettingsHost; }

  void StartDataRequest(const GURL& url,
                        const content::WebContents::Getter& /*wc_getter*/,
                        GotDataCallback callback) override {
    // The config selects chrome://settings. Keep the data source equally
    // narrow in case an unexpected URL reaches it through the data manager.
    if (!IsWasmSettingsRootURL(url)) {
      std::move(callback).Run(nullptr);
      return;
    }

    std::move(callback).Run(base::MakeRefCounted<base::RefCountedString>(
        BuildWasmSettingsBootstrapHtml(*storage_estimate_snapshot_)));
  }

  std::string GetMimeType(const GURL& /*url*/) override {
    return "text/html";
  }

  // The status deliberately describes volatile M6 state. Avoid carrying a
  // stale document across a later source-selection or lifecycle change.
  bool AllowCaching() override { return false; }

 private:
  // This snapshot is captured by the owning WebUI while it is created on the
  // browser UI sequence. StartDataRequest serves this immutable object rather
  // than reaching into live host state on a URLDataSource I/O path.
  const scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot>
      storage_estimate_snapshot_;
};

}  // namespace

WasmSettingsUI::WasmSettingsUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui),
      storage_estimate_snapshot_(GetWasmBrowserHostStorageEstimateSnapshot()) {
  DCHECK(web_ui);
  DCHECK(web_ui->GetWebContents());
  DCHECK(storage_estimate_snapshot_);

  // BrowserContext owns the source. No Profile, SettingsUI, preference, or
  // desktop browser-service dependency is needed for this read-only document.
  // Capture the generation-stamped diagnostic now. A later Promise completion
  // belongs to a later Settings navigation; it cannot mutate this document's
  // URLDataSource payload while that payload is being served.
  content::URLDataSource::Add(
      web_ui->GetWebContents()->GetBrowserContext(),
      std::make_unique<WasmSettingsDataSource>(
          storage_estimate_snapshot_));
}

WasmSettingsUI::~WasmSettingsUI() = default;

scoped_refptr<const WasmBrowserHostStorageEstimateSnapshot>
WasmSettingsUI::GetStorageEstimateSnapshotForTesting() const {
  return storage_estimate_snapshot_;
}

WEB_UI_CONTROLLER_TYPE_IMPL(WasmSettingsUI)

WasmSettingsUIConfig::WasmSettingsUIConfig()
    : DefaultWebUIConfig(content::kChromeUIScheme, kWasmSettingsHost) {}

WasmSettingsUIConfig::~WasmSettingsUIConfig() = default;

bool WasmSettingsUIConfig::ShouldHandleURL(const GURL& url) {
  return IsWasmSettingsRootURL(url);
}

void EnsureWasmSettingsWebUIConfigRegistered() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  static bool registered = false;
  if (registered) {
    return;
  }

  content::WebUIConfigMap::GetInstance().AddWebUIConfig(
      std::make_unique<WasmSettingsUIConfig>());
  registered = true;
}

}  // namespace chrome

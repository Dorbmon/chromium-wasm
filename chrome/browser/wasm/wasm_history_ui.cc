// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_history_ui.h"

#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/memory/ref_counted_memory.h"
#include "base/strings/escape.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "chrome/browser/wasm/wasm_session_navigation_journal.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/url_data_source.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/webui_config_map.h"
#include "content/public/common/url_constants.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_history_ui.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kWasmHistoryHost[] = "history";

bool IsWasmHistoryRootURL(const GURL& url) {
  return url.SchemeIs(content::kChromeUIScheme) &&
         url.host() == kWasmHistoryHost &&
         (url.path() == "/" || url.path().empty()) && !url.has_username() &&
         !url.has_password() && !url.has_port() && !url.has_query() &&
         !url.has_ref();
}

std::string BuildWasmHistoryHtml(
    const std::vector<WasmSessionNavigationJournal::Entry>& entries) {
  // |entries| is a UI-sequence snapshot copied into the data source at WebUI
  // construction. StartDataRequest may execute on IO, so it must not inspect
  // WasmProfile or the live journal here.
  std::string html = R"HTML(<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="light dark">
  <title>History — Chromium Wasm</title>
  <style>
    :root { color-scheme: light dark; font: 16px/1.5 sans-serif; }
    body { margin: 0; background: Canvas; color: CanvasText; }
    main { box-sizing: border-box; margin: 0 auto; max-width: 760px; padding: 32px 24px 48px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    h2 { margin: 28px 0 8px; font-size: 19px; }
    p, li { max-width: 68ch; }
    .badge { display: inline-block; margin: 0 0 18px; padding: 3px 8px; border: 1px solid currentColor; border-radius: 999px; font-weight: 600; }
    .notice { border-inline-start: 4px solid #d97706; padding: 12px 16px; background: color-mix(in srgb, #d97706 12%, Canvas); }
    ol { padding-inline-start: 28px; }
    li { overflow-wrap: anywhere; }
    code { font-family: ui-monospace, monospace; }
  </style>
</head>
<body>
  <main id="wasm-history-bootstrap" aria-labelledby="page-title">
    <h1 id="page-title">History</h1>
    <p class="badge" id="wasm-history-state">Volatile M6 session journal</p>
    <section class="notice" aria-labelledby="scope-title">
      <h2 id="scope-title">Not desktop Chrome History</h2>
      <p>This read-only page shows a bounded, in-memory journal of committed
      primary-frame web visits from the live Wasm tabs. It is not backed by
      Chrome HistoryService, has no search or deletion controls, and is lost
      when the Wasm browser process stops.</p>
      <p>Credentials, query and fragment components, internal documents, and
      <code>data:</code> document bodies are never retained here.</p>
    </section>
    <section aria-labelledby="entries-title">
      <h2 id="entries-title">This session</h2>
)HTML";

  if (entries.empty()) {
    html.append("      <p id=\"wasm-history-empty\">No eligible web visits "
                "have committed in this session.</p>\n");
  } else {
    html.append("      <ol id=\"wasm-history-entries\">\n");
    for (const WasmSessionNavigationJournal::Entry& entry : entries) {
      html.append("        <li data-wasm-history-sequence=\"");
      html.append(std::to_string(entry.sequence));
      html.append("\"><code>");
      // The journal redacts sensitive URL components before snapshotting; HTML
      // escaping remains mandatory because even a redacted path is untrusted
      // web input.
      html.append(base::EscapeForHTML(entry.display_url));
      html.append("</code></li>\n");
    }
    html.append("      </ol>\n");
  }
  html.append(R"HTML(    </section>
  </main>
</body>
</html>
)HTML");
  return html;
}

class WasmHistoryDataSource final : public content::URLDataSource {
 public:
  explicit WasmHistoryDataSource(
      std::vector<WasmSessionNavigationJournal::Entry> entries)
      : entries_(std::move(entries)) {}
  WasmHistoryDataSource(const WasmHistoryDataSource&) = delete;
  WasmHistoryDataSource& operator=(const WasmHistoryDataSource&) = delete;
  ~WasmHistoryDataSource() override = default;

  std::string GetSource() override { return kWasmHistoryHost; }

  void StartDataRequest(const GURL& url,
                        const content::WebContents::Getter& /*wc_getter*/,
                        GotDataCallback callback) override {
    if (!IsWasmHistoryRootURL(url)) {
      std::move(callback).Run(nullptr);
      return;
    }
    std::move(callback).Run(base::MakeRefCounted<base::RefCountedString>(
        BuildWasmHistoryHtml(entries_)));
  }

  std::string GetMimeType(const GURL& /*url*/) override {
    return "text/html";
  }

  bool AllowCaching() override { return false; }

 private:
  // Immutable UI-thread snapshot. This object can serve on IO without reading
  // live profile state or retaining a profile/WebContents pointer.
  const std::vector<WasmSessionNavigationJournal::Entry> entries_;
};

}  // namespace

WasmHistoryUI::WasmHistoryUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  DCHECK(web_ui);
  DCHECK(web_ui->GetWebContents());

  // This config is registered only by WasmBrowserMainParts, before it creates
  // its WasmProfile. Do not replace it with generic Chrome WebUI registration:
  // that graph owns desktop HistoryUI and would duplicate this root host.
  auto* const profile = static_cast<WasmProfile*>(
      web_ui->GetWebContents()->GetBrowserContext());
  CHECK(profile);
  base::WeakPtr<WasmSessionNavigationJournal> journal =
      profile->GetSessionNavigationJournalWeakPtr();
  std::vector<WasmSessionNavigationJournal::Entry> snapshot;
  if (journal) {
    snapshot = journal->GetSnapshot();
  }
  entry_count_ = snapshot.size();

  content::URLDataSource::Add(
      web_ui->GetWebContents()->GetBrowserContext(),
      std::make_unique<WasmHistoryDataSource>(std::move(snapshot)));
}

WasmHistoryUI::~WasmHistoryUI() = default;

WEB_UI_CONTROLLER_TYPE_IMPL(WasmHistoryUI)

WasmHistoryUIConfig::WasmHistoryUIConfig()
    : DefaultWebUIConfig(content::kChromeUIScheme, kWasmHistoryHost) {}

WasmHistoryUIConfig::~WasmHistoryUIConfig() = default;

bool WasmHistoryUIConfig::ShouldHandleURL(const GURL& url) {
  return IsWasmHistoryRootURL(url);
}

void EnsureWasmHistoryWebUIConfigRegistered() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  static bool registered = false;
  if (registered) {
    return;
  }
  content::WebUIConfigMap::GetInstance().AddWebUIConfig(
      std::make_unique<WasmHistoryUIConfig>());
  registered = true;
}

}  // namespace chrome

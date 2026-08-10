// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_session_navigation_journal.h"

#include <limits>
#include <utility>

#include "base/check.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_session_navigation_journal.cc must only be built for WebAssembly"
#endif

namespace {

std::string RedactedDisplayUrl(const GURL& url) {
  if (!url.is_valid()) {
    return std::string();
  }

  // The bounded M6 History page is a session-navigation journal, not a
  // general-purpose URL disclosure surface. Only web documents are retained;
  // internal, data, file, blob, and other scheme-specific paths stay out of
  // it. This also ensures a data: body cannot consume a journal slot.
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return std::string();
  }

  GURL::Replacements replacements;
  replacements.ClearUsername();
  replacements.ClearPassword();
  replacements.ClearQuery();
  replacements.ClearRef();
  const GURL redacted = url.ReplaceComponents(replacements);
  if (!redacted.is_valid() ||
      redacted.spec().size() >
          WasmSessionNavigationJournal::kMaximumDisplayUrlBytes) {
    return std::string();
  }
  return redacted.spec();
}

}  // namespace

WasmSessionNavigationJournal::WasmSessionNavigationJournal() = default;

WasmSessionNavigationJournal::~WasmSessionNavigationJournal() = default;

void WasmSessionNavigationJournal::RecordCommittedPrimaryMainFrameNavigation(
    const GURL& url) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (shutdown_) {
    return;
  }
  const std::string display_url = RedactedDisplayUrl(url);
  if (display_url.empty() || next_sequence_ == std::numeric_limits<uint64_t>::max()) {
    return;
  }

  entries_.push_back(Entry{next_sequence_, display_url});
  ++next_sequence_;
  while (entries_.size() > kMaximumEntries) {
    entries_.pop_front();
  }
}

std::vector<WasmSessionNavigationJournal::Entry>
WasmSessionNavigationJournal::GetSnapshot() const {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (shutdown_) {
    return {};
  }
  return std::vector<Entry>(entries_.begin(), entries_.end());
}

void WasmSessionNavigationJournal::Clear() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (shutdown_) {
    return;
  }
  entries_.clear();
  next_sequence_ = 1;
}

void WasmSessionNavigationJournal::Shutdown() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (shutdown_) {
    return;
  }
  shutdown_ = true;
  entries_.clear();
  // Do not leave a late WebContents callback or a live URLDataSource holding
  // a usable profile-owned object while Profile tears down keyed services.
  weak_ptr_factory_.InvalidateWeakPtrsAndDoom();
}

base::WeakPtr<WasmSessionNavigationJournal>
WasmSessionNavigationJournal::GetWeakPtr() {
  if (shutdown_) {
    return nullptr;
  }
  return weak_ptr_factory_.GetWeakPtr();
}

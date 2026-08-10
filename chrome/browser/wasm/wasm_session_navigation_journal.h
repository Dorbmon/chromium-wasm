// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_SESSION_NAVIGATION_JOURNAL_H_
#define CHROME_BROWSER_WASM_WASM_SESSION_NAVIGATION_JOURNAL_H_

#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

#include "base/memory/weak_ptr.h"

class GURL;

// A deliberately small, profile-owned journal for the M6 Wasm browser.
//
// This is not HistoryService: records are process-local, bounded, and dropped
// with WasmProfile. It records only a redacted display URL for a committed
// primary-main-frame HTTP(S) navigation. In particular, it never retains
// credentials, query/ref components, internal URLs, or data: document bodies.
class WasmSessionNavigationJournal {
 public:
  struct Entry {
    uint64_t sequence = 0;
    std::string display_url;
  };

  static constexpr size_t kMaximumEntries = 64;
  static constexpr size_t kMaximumDisplayUrlBytes = 2048;

  WasmSessionNavigationJournal();
  WasmSessionNavigationJournal(const WasmSessionNavigationJournal&) = delete;
  WasmSessionNavigationJournal& operator=(
      const WasmSessionNavigationJournal&) = delete;
  ~WasmSessionNavigationJournal();

  void RecordCommittedPrimaryMainFrameNavigation(const GURL& url);
  std::vector<Entry> GetSnapshot() const;
  void Clear();

  // Permanently disarms all observer and data-source weak references. The
  // owning WasmProfile calls this before its keyed-service shutdown starts.
  void Shutdown();

  base::WeakPtr<WasmSessionNavigationJournal> GetWeakPtr();

 private:
  std::deque<Entry> entries_;
  uint64_t next_sequence_ = 1;
  bool shutdown_ = false;
  base::WeakPtrFactory<WasmSessionNavigationJournal> weak_ptr_factory_{this};
};

#endif  // CHROME_BROWSER_WASM_WASM_SESSION_NAVIGATION_JOURNAL_H_

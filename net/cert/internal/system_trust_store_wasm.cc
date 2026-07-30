// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/cert/internal/system_trust_store.h"

#include <memory>
#include <utility>

namespace net {

std::unique_ptr<SystemTrustStore> CreateSslSystemTrustStoreChromeRoot(
    std::unique_ptr<TrustStoreChrome> chrome_root) {
  // WebAssembly has no host or local certificate store. Keep Chromium's root
  // store and its normal WebPKI validation without adding ambient trust.
  return CreateChromeOnlySystemTrustStore(std::move(chrome_root));
}

}  // namespace net

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/public/browser/wasm_dom_storage_test_support.h"

#include <utility>

#include "content/browser/dom_storage/dom_storage_context_wrapper.h"

namespace content {

bool BindWasmLocalStorageTestApi(
    DOMStorageContext* context,
    mojo::PendingReceiver<storage::mojom::WasmLocalStorageTestApi> receiver) {
  if (!context) {
    return false;
  }

  // StoragePartitionImpl always owns a DOMStorageContextWrapper. This
  // source-selected bridge is intentionally valid only for the context
  // returned by StoragePartition::GetDOMStorageContext().
  auto* const wrapper = static_cast<DOMStorageContextWrapper*>(context);
  wrapper->BindWasmLocalStorageTestApi(std::move(receiver));
  return true;
}

bool SealWasmLocalStorageForTest(DOMStorageContext* context) {
  if (!context) {
    return false;
  }

  auto* const wrapper = static_cast<DOMStorageContextWrapper*>(context);
  return wrapper->SealLocalStorageForWasmProfileTest();
}

}  // namespace content

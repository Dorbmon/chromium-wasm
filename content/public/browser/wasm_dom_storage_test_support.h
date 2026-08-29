// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_PUBLIC_BROWSER_WASM_DOM_STORAGE_TEST_SUPPORT_H_
#define CONTENT_PUBLIC_BROWSER_WASM_DOM_STORAGE_TEST_SUPPORT_H_

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
#include "components/services/storage/public/mojom/wasm_local_storage_test_api.mojom.h"
#endif
#include "content/common/content_export.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"

namespace content {

class DOMStorageContext;

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST)
// Binds the source-selected M7 LocalStorage close-fence protocol through the
// real default partition's DOMStorageContext. `context` must be the instance
// obtained from StoragePartition::GetDOMStorageContext(); this bridge has no
// normal-build declaration or behavior.
CONTENT_EXPORT bool BindWasmLocalStorageTestApi(
    DOMStorageContext* context,
    mojo::PendingReceiver<storage::mojom::WasmLocalStorageTestApi> receiver);

// Seals the same real DOMStorageContext before its LocalStorage control remote
// is closed. Once sealed, a Storage Service disconnect cannot create a new
// LocalStorage binding during the close-fence receipt.
CONTENT_EXPORT bool SealWasmLocalStorageForTest(DOMStorageContext* context);
#endif

}  // namespace content

#endif  // CONTENT_PUBLIC_BROWSER_WASM_DOM_STORAGE_TEST_SUPPORT_H_

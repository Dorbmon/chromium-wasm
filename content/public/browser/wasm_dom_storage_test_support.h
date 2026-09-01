// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_PUBLIC_BROWSER_WASM_DOM_STORAGE_TEST_SUPPORT_H_
#define CONTENT_PUBLIC_BROWSER_WASM_DOM_STORAGE_TEST_SUPPORT_H_

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_LOCAL_STORAGE_CLOSE_FENCE_TEST)
#include "components/services/storage/public/mojom/wasm_local_storage_test_api.mojom.h"
#endif
#include "content/common/content_export.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"

namespace content {

class DOMStorageContext;

#if defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_LOCAL_STORAGE_CLOSE_FENCE_TEST)
// Binds the source-selected M7 LocalStorage close-fence protocol through the
// real default partition's DOMStorageContext. `context` must be the instance
// obtained from StoragePartition::GetDOMStorageContext(); this bridge has no
// normal-build declaration or behavior.
CONTENT_EXPORT bool BindWasmLocalStorageTestApi(
    DOMStorageContext* context,
    mojo::PendingReceiver<storage::mojom::WasmLocalStorageTestApi> receiver);

// Asks the real StoragePartition to reset its renderer-side LocalStorage
// connections. This reaches Blink's StorageController and releases cached
// StorageAreas that can outlive a destroyed LocalDOMWindow in an in-process
// renderer. It is deliberately only a reset request: callers must still wait
// for their result-bearing close fence before treating the area as unbound.
CONTENT_EXPORT bool ResetWasmLocalStorageConnectionsForTest(
    DOMStorageContext* context);

// Seals the same real DOMStorageContext before its LocalStorage control remote
// is closed. Once sealed, a Storage Service disconnect cannot create a new
// LocalStorage binding during the close-fence receipt.
CONTENT_EXPORT bool SealWasmLocalStorageForTest(DOMStorageContext* context);
#endif

}  // namespace content

#endif  // CONTENT_PUBLIC_BROWSER_WASM_DOM_STORAGE_TEST_SUPPORT_H_

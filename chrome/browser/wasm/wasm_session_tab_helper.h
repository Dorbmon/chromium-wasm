// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_SESSION_TAB_HELPER_H_
#define CHROME_BROWSER_WASM_WASM_SESSION_TAB_HELPER_H_

#include "components/sessions/core/session_id.h"

namespace content {
class WebContents;
}

namespace chrome {

// Attaches the real SessionTabHelper to `web_contents` if it is not already
// attached. The Wasm bootstrap intentionally supplies no delegate lookup, so
// the helper assigns a real transient tab ID without choosing a session
// persistence service. A joined Wasm TabModel lifecycle must call this before
// constructing its TabModel.
void EnsureWasmSessionTabHelper(content::WebContents* web_contents);

// Returns the real transient tab ID created by EnsureWasmSessionTabHelper().
// Keeping the SessionTabHelper API private prevents a caller from accidentally
// treating the empty Wasm delegate lookup as a full session-service lifecycle.
SessionID GetWasmSessionTabId(content::WebContents* web_contents);

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_SESSION_TAB_HELPER_H_

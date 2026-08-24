// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_readiness.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_readiness.cc must only be built for WebAssembly"
#endif

// This import is implemented by ozone_wasm's versioned host bridge. Keep
// Chrome shell construction separate from canvas presentation and document
// paint: neither is established merely because a BrowserView has been shown.
extern "C" int chromium_wasm_report_readiness(
    int shell_ready,
    int surface_ready,
    int first_visually_nonempty_paint);

namespace chrome {

bool ReportWasmBrowserShellReady() {
  return chromium_wasm_report_readiness(
             /*shell_ready=*/1,
             /*surface_ready=*/-1,
             /*first_visually_nonempty_paint=*/-1) == 1;
}

}  // namespace chrome

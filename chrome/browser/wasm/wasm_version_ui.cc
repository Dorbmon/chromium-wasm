// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_version_ui.h"

#include <memory>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/ui/webui/version/version_ui.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/webui_config_map.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_version_ui.cc must only be built for WebAssembly"
#endif

namespace chrome {

void EnsureWasmVersionWebUIConfigRegistered() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  static bool registered = false;
  if (registered) {
    return;
  }

  content::WebUIConfigMap::GetInstance().AddWebUIConfig(
      std::make_unique<VersionUIConfig>());
  registered = true;
}

}  // namespace chrome

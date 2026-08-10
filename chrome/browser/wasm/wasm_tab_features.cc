// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/tabs/public/tab_features.h"

#include <memory>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/ui/tab_ui_helper.h"
#include "components/tabs/public/tab_interface.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_features.cc must only be built for WebAssembly"
#endif

namespace tabs {

TabFeatures::TabFeatures() = default;

TabFeatures::~TabFeatures() = default;

void TabFeatures::Init(TabInterface& tab, Profile* profile) {
  CHECK(!initialized_);
  initialized_ = true;

  // Per-WebContents Wasm policy belongs to PrepareWasmTabWebContents, which
  // also runs for TabModel::DiscardContents replacements. TabFeatures itself
  // retains only the UI helper lifetime.
  static_cast<void>(profile);
  tab_ui_helper_ = std::make_unique<TabUIHelper>(tab);
}

}  // namespace tabs

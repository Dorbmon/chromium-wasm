// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/ui_features.h"

#include "base/feature_list.h"
#include "build/build_config.h"
#include "ui/base/ui_base_features.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_toolkit_features.cc must only be built for WebAssembly"
#endif

namespace features {

// Keep these definitions behaviorally equivalent to the corresponding
// definitions in ui_features.cc. They are the complete UI-feature surface
// referenced by the source-selected Chrome color mixers. Selecting the desktop
// ui_features target would also select its desktop BrowserProcess dependency.
BASE_FEATURE(kTabGroupColorRefresh, base::FEATURE_DISABLED_BY_DEFAULT);

bool IsTabGroupColorRefreshEnabled() {
  return base::FeatureList::IsEnabled(kDesktopGlowUp) ||
         base::FeatureList::IsEnabled(kTabGroupColorRefresh);
}

BASE_FEATURE(kWebuiRefresh2026, base::FEATURE_DISABLED_BY_DEFAULT);

bool IsWebuiRefresh2026Enabled() {
  return base::FeatureList::IsEnabled(kDesktopGlowUp) ||
         base::FeatureList::IsEnabled(kWebuiRefresh2026);
}

}  // namespace features

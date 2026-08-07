// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/ui_features.h"

#include "base/feature_list.h"
#include "base/metrics/field_trial_params.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_animation_features.cc must only be built for WebAssembly"
#endif

namespace features {

// Keep these definitions byte-for-byte equivalent in behavior to the relevant
// declarations in ui_features.cc. They are the only UI feature symbols used by
// the real side-panel and vertical-tab-strip animation providers selected for
// the first Wasm BrowserWindowFeatures lifecycle.
BASE_FEATURE(kSidePanelFlyoverAnimation, base::FEATURE_ENABLED_BY_DEFAULT);

bool UseSidePanelFlyoverAnimation() {
  return base::FeatureList::IsEnabled(kSidePanelFlyoverAnimation);
}

BASE_FEATURE_PARAM(int,
                   kSidePanelFlyoverDurationMs,
                   &kSidePanelFlyoverAnimation,
                   "flyover_animation_duration_ms",
                   350);

}  // namespace features

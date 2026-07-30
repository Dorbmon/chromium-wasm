// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/base/resource/resource_bundle.h"

namespace ui {

void ResourceBundle::LoadCommonResources() {
  // Common packs are staged in the module filesystem and use the ordinary
  // ResourceBundle data-pack path rather than an outer-browser resource API.
  LoadChromeResources();
}

gfx::Image& ResourceBundle::GetNativeImageNamed(int resource_id) {
  // Wasm has no separate host-native image type. Canvas presentation consumes
  // the same Skia-backed gfx::Image returned by the portable resource path.
  return GetImageNamed(resource_id);
}

}  // namespace ui

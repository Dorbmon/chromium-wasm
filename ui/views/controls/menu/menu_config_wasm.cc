// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/views/controls/menu/menu_config.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "menu_config_wasm.cc must only be built for Wasm"
#endif

namespace views {

void MenuConfig::InitPlatform() {
  // A browser-hosted canvas exposes no operating-system menu metrics. Retain
  // InitCommon's generic Views defaults rather than inventing host-native menu
  // behavior. BrowserWidget separately rejects unsupported system-menu routes.
}

}  // namespace views

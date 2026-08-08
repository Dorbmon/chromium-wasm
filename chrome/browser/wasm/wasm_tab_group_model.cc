// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/tabs/tab_group_model.h"

#include "build/build_config.h"
#include "components/tab_groups/tab_group_id.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_group_model.cc must only be built for WebAssembly"
#endif

// A Wasm TabStripModel always has a null TabGroupModel. These out-of-line
// definitions are still required by its member layout, but no group operation
// is source-selected or silently supported by the first tab core.
TabGroupModel::TabGroupModel() = default;

TabGroupModel::~TabGroupModel() = default;

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/core/layout/layout_theme_default.h"

#include "build/build_config.h"
#include "third_party/blink/renderer/platform/wtf/std_lib_extras.h"

#if !BUILDFLAG(IS_WASM)
#error "layout_theme_wasm.cc must only be built for WebAssembly"
#endif

namespace blink {
namespace {

// There are no special themes on WebAssembly.
class LayoutThemeWasm : public LayoutThemeDefault {
 public:
  static scoped_refptr<LayoutTheme> Create() {
    return base::AdoptRef(new LayoutThemeWasm());
  }
};

}  // namespace

LayoutTheme& LayoutTheme::NativeTheme() {
  DEFINE_STATIC_REF(LayoutTheme, layout_theme, (LayoutThemeWasm::Create()));
  return *layout_theme;
}

}  // namespace blink

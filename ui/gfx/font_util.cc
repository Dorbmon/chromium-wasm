// Copyright 2019 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/gfx/font_util.h"

#include "build/build_config.h"
#include "skia/ext/font_utils.h"

#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_CHROMEOS)
#include <fontconfig/fontconfig.h>
#include "ui/gfx/linux/fontconfig_util.h"
#endif

#if BUILDFLAG(IS_WIN)
#include "ui/gfx/win/direct_write.h"
#endif

#if BUILDFLAG(IS_WASM)
#include "ui/gfx/font_util_wasm.h"
#endif

namespace gfx {

void InitializeFonts() {
  // Implicit initialization can cause a long delay on the first rendering if
  // the font cache has to be regenerated for some reason. Doing it explicitly
  // here helps in cases where the browser process is starting up in the
  // background (resources have not yet been granted to cast) since it prevents
  // the long delay the user would have seen on first rendering.

#if BUILDFLAG(IS_WASM)
  // This must run before any caller reaches skia::DefaultFontMgr(). The Wasm
  // platform has no system font service, and its Skia fallback is deliberately
  // empty rather than a fake metrics provider.
  InitializeFontsWasm();
#endif

#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_CHROMEOS)
  // Early initialize FontConfig.
  InitializeGlobalFontConfigAsync();
#endif  // BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_CHROMEOS)

#if BUILDFLAG(IS_WIN)
  gfx::win::InitializeDirectWrite();
#endif  // BUILDFLAG(IS_WIN)
  skia::InitializeFontRendering();
}

}  // namespace gfx

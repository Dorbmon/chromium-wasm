// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/gfx/font_util_wasm.h"

#include <array>
#include <ostream>

#include "base/check.h"
#include "base/check_op.h"
#include "skia/ext/font_utils.h"
#include "third_party/skia/include/core/SkData.h"
#include "third_party/skia/include/core/SkFont.h"
#include "third_party/skia/include/core/SkFontTypes.h"
#include "third_party/skia/include/core/SkFontMgr.h"
#include "third_party/skia/include/core/SkFontStyle.h"
#include "third_party/skia/include/core/SkTypeface.h"
#include "third_party/skia/include/ports/SkFontMgr_data.h"

namespace gfx {
namespace {

constexpr char kWasmDefaultFontPath[] = "/assets/Roboto-Regular.ttf";
constexpr char kFontMetricsProbe[] = "Chromium";

void CheckUsableTypeface(const SkTypeface& typeface) {
  CHECK_NE(typeface.unicharToGlyph('x'), 0u)
      << "Wasm default font has no basic Latin glyphs";

  SkFont font(sk_ref_sp(&typeface), 13.0f);
  CHECK_GT(font.measureText(kFontMetricsProbe, sizeof(kFontMetricsProbe) - 1,
                            SkTextEncoding::kUTF8),
           0.0f)
      << "Wasm default font has zero text metrics";
}

}  // namespace

void InitializeFontsWasm() {
  std::array<sk_sp<SkData>, 1> font_data = {
      SkData::MakeFromFileName(kWasmDefaultFontPath),
  };
  CHECK(font_data[0]) << "Missing bundled Wasm font " << kWasmDefaultFontPath;

  sk_sp<SkFontMgr> font_manager = SkFontMgr_New_Custom_Data(font_data);
  CHECK(font_manager);
  CHECK_GT(font_manager->countFamilies(), 0);

  sk_sp<SkTypeface> bundled_typeface =
      font_manager->legacyMakeTypeface(nullptr, SkFontStyle());
  CHECK(bundled_typeface) << "Bundled Wasm font could not be decoded";
  CheckUsableTypeface(*bundled_typeface);

  // font_utils requires an override before its singleton is first requested.
  // The next lookup proves that the same generic fallback used by Views has
  // real glyphs and metrics rather than Skia's intentional empty fallback.
  skia::OverrideDefaultSkFontMgr(std::move(font_manager));
  sk_sp<SkTypeface> default_typeface =
      skia::MakeTypefaceFromName("sans", SkFontStyle());
  CHECK(default_typeface);
  CheckUsableTypeface(*default_typeface);
}

}  // namespace gfx

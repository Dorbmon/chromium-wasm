// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/strings/sys_string_conversions.h"

#include "base/strings/utf_string_conversions.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "sys_string_conversions_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

std::string SysWideToUTF8(const std::wstring& wide) {
  return WideToUTF8(wide);
}

std::wstring SysUTF8ToWide(std::string_view utf8) {
  return UTF8ToWide(utf8);
}

std::string SysWideToNativeMB(const std::wstring& wide) {
  // Web APIs and the Emscripten virtual filesystem use UTF-8.
  return WideToUTF8(wide);
}

std::wstring SysNativeMBToWide(std::string_view native_mb) {
  return UTF8ToWide(native_mb);
}

}  // namespace base

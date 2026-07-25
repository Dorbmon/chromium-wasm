// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/native_library.h"

#include <string_view>

#include "base/check.h"
#include "base/strings/strcat.h"
#include "base/strings/string_util.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "native_library_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

std::string NativeLibraryLoadError::ToString() const {
  return message;
}

NativeLibrary LoadNativeLibrary(const FilePath& library_path,
                                NativeLibraryLoadError* error) {
  if (error) {
    error->message =
        StrCat({"Native libraries are unsupported in WebAssembly: ",
                library_path.AsUTF8Unsafe()});
  }
  return nullptr;
}

void UnloadNativeLibrary(NativeLibrary library) {
  CHECK(!library);
}

void* GetFunctionPointerFromNativeLibrary(NativeLibrary library,
                                          const char* name) {
  CHECK(!library);
  return nullptr;
}

std::string GetNativeLibraryName(std::string_view name) {
  DCHECK(IsStringASCII(name));
  return StrCat({"lib", name, ".so"});
}

std::string GetLoadableModuleName(std::string_view name) {
  return GetNativeLibraryName(name);
}

}  // namespace base

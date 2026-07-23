// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/files/file.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "file_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

File::Error File::Lock(File::LockMode /*mode*/) {
  // The pinned Emscripten runtime reports success for F_SETLK without
  // enforcing a lock. Returning an explicit unsupported result prevents
  // callers from treating that fake success as a profile or data-integrity
  // guarantee.
  return FILE_ERROR_INVALID_OPERATION;
}

File::Error File::Unlock() {
  return FILE_ERROR_INVALID_OPERATION;
}

}  // namespace base

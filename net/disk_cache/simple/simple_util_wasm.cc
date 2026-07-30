// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/disk_cache/simple/simple_util.h"

#include "base/files/file_util.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "simple_util_wasm.cc must only be built for WebAssembly"
#endif

namespace disk_cache::simple_util {

bool SimpleCacheDeleteFile(const base::FilePath& path) {
  return base::DeleteFile(path);
}

}  // namespace disk_cache::simple_util

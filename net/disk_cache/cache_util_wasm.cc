// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/disk_cache/cache_util.h"

#include "base/files/file_util.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "cache_util_wasm.cc must only be built for WebAssembly"
#endif

namespace disk_cache {

bool MoveCache(const base::FilePath& from_path,
               const base::FilePath& to_path) {
  return base::Move(from_path, to_path);
}

}  // namespace disk_cache

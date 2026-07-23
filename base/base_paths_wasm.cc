// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/base_paths.h"

#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "base_paths_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

bool PathProviderWasm(int key, FilePath* result) {
  FilePath candidate;
  switch (key) {
    case DIR_TEMP:
      candidate = FilePath("/tmp");
      break;
    case DIR_HOME:
      candidate = FilePath("/home/web_user");
      break;

    // The JavaScript and WebAssembly module artifacts are host resources, not
    // files in MEMFS. Returning a synthesized path would make resource and
    // executable-file checks incorrectly succeed.
    case FILE_EXE:
    case FILE_MODULE:
    case DIR_EXE:
    case DIR_MODULE:
    case DIR_ASSETS:
    case DIR_USER_DESKTOP:
    case DIR_SRC_TEST_DATA_ROOT:
    case DIR_OUT_TEST_DATA_ROOT:
    case DIR_GEN_TEST_DATA_ROOT:
    case DIR_TEST_DATA:
      return false;
    default:
      return false;
  }

  if (!DirectoryExists(candidate)) {
    return false;
  }
  *result = candidate;
  return true;
}

}  // namespace base

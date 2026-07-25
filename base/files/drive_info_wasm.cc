// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/files/drive_info.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "drive_info_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

std::optional<DriveInfo> GetFileDriveInfo(const FilePath& file_path) {
  // A virtual filesystem path does not identify a host storage device.
  return std::nullopt;
}

}  // namespace base

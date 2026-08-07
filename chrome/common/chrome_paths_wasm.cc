// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/common/chrome_paths_internal.h"

#include "base/files/file_path.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "chrome_paths_wasm.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr base::FilePath::CharType kProfileRoot[] =
    FILE_PATH_LITERAL("/profile");

bool GetProfileSubdirectory(const base::FilePath::CharType* name,
                            base::FilePath* result) {
  *result = base::FilePath(kProfileRoot).Append(name);
  return true;
}

}  // namespace

bool GetDefaultUserDataDirectory(base::FilePath* result) {
  *result = base::FilePath(kProfileRoot);
  return true;
}

void GetUserCacheDirectory(const base::FilePath& profile_dir,
                           base::FilePath* result) {
  *result = profile_dir;
}

bool GetUserDocumentsDirectory(base::FilePath* result) {
  return GetProfileSubdirectory(FILE_PATH_LITERAL("Documents"), result);
}

bool GetUserDownloadsDirectory(base::FilePath* result) {
  return GetProfileSubdirectory(FILE_PATH_LITERAL("Downloads"), result);
}

bool GetUserMusicDirectory(base::FilePath* result) {
  return GetProfileSubdirectory(FILE_PATH_LITERAL("Music"), result);
}

bool GetUserPicturesDirectory(base::FilePath* result) {
  return GetProfileSubdirectory(FILE_PATH_LITERAL("Pictures"), result);
}

bool GetUserVideosDirectory(base::FilePath* result) {
  return GetProfileSubdirectory(FILE_PATH_LITERAL("Videos"), result);
}

bool ProcessNeedsProfileDir(const std::string& process_type) {
  // M6 is intentionally a single-process build. Child process paths are not
  // meaningful until a distinct execution model is introduced.
  return process_type.empty();
}

}  // namespace chrome

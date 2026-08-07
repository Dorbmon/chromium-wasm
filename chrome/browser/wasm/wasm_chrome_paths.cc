// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/common/chrome_paths.h"

#include <optional>

#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/no_destructor.h"
#include "base/path_service.h"
#include "base/threading/thread_restrictions.h"
#include "build/build_config.h"
#include "chrome/common/chrome_paths_internal.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_chrome_paths.cc must only be built for WebAssembly"
#endif

namespace {

constexpr base::FilePath::CharType kDictionariesDirectory[] =
    FILE_PATH_LITERAL("Dictionaries");
constexpr base::FilePath::CharType kLocalStateFilename[] =
    FILE_PATH_LITERAL("Local State");
constexpr base::FilePath::CharType kResourcesDirectory[] =
    FILE_PATH_LITERAL("resources");
constexpr base::FilePath::CharType kResourcesPackFilename[] =
    FILE_PATH_LITERAL("resources.pak");

std::optional<bool> g_override_using_default_data_directory_for_testing;

base::FilePath& GetInvalidSpecifiedUserDataDirInternal() {
  static base::NoDestructor<base::FilePath> path;
  return *path;
}

bool GetAssetsDirectory(base::FilePath* result) {
  return base::PathService::Get(base::DIR_ASSETS, result);
}

}  // namespace

namespace chrome {

// This is intentionally the Chrome PathService provider symbol. In addition
// to registering the narrow Wasm range, that makes the bounded profile
// directory creation below an explicitly reviewed blocking call.
bool PathProvider(int key, base::FilePath* result) {
  base::FilePath path;
  bool create_directory = false;

  switch (key) {
    case DIR_USER_DATA:
      if (!GetDefaultUserDataDirectory(&path)) {
        return false;
      }
      create_directory = true;
      break;
    case DIR_APP_DICTIONARIES:
      if (!base::PathService::Get(DIR_USER_DATA, &path)) {
        return false;
      }
      path = path.Append(kDictionariesDirectory);
      create_directory = true;
      break;
    case DIR_RESOURCES:
      if (!GetAssetsDirectory(&path)) {
        return false;
      }
      path = path.Append(kResourcesDirectory);
      break;
    case FILE_LOCAL_STATE:
      if (!base::PathService::Get(DIR_USER_DATA, &path)) {
        return false;
      }
      path = path.Append(kLocalStateFilename);
      break;
    case FILE_RESOURCES_PACK:
      if (!GetAssetsDirectory(&path)) {
        return false;
      }
      path = path.Append(kResourcesPackFilename);
      break;

    // Downloads, component updates, crash reporting, record/replay, and the
    // separate DevUI resource pack do not have an M6 Wasm implementation or
    // staged asset. Returning false is an explicit unsupported result, rather
    // than a synthesized host-like path.
    default:
      return false;
  }

  if (create_directory) {
    base::ScopedAllowBlocking allow_blocking;
    if (!base::CreateDirectory(path)) {
      return false;
    }
  }

  *result = path;
  return true;
}

std::optional<bool> IsUsingDefaultDataDirectory() {
  if (g_override_using_default_data_directory_for_testing.has_value()) {
    return g_override_using_default_data_directory_for_testing;
  }

  base::FilePath user_data_directory;
  if (!base::PathService::Get(DIR_USER_DATA, &user_data_directory)) {
    return std::nullopt;
  }

  base::FilePath default_user_data_directory;
  if (!GetDefaultUserDataDirectory(&default_user_data_directory)) {
    return std::nullopt;
  }
  return user_data_directory == default_user_data_directory;
}

void SetUsingDefaultUserDataDirectoryForTesting(
    std::optional<bool> is_default) {
  g_override_using_default_data_directory_for_testing = is_default;
}

void RegisterPathProvider() {
  base::PathService::RegisterProvider(PathProvider, PATH_START, PATH_END);
}

void SetInvalidSpecifiedUserDataDir(const base::FilePath& user_data_dir) {
  GetInvalidSpecifiedUserDataDirInternal() = user_data_dir;
}

const base::FilePath& GetInvalidSpecifiedUserDataDir() {
  return GetInvalidSpecifiedUserDataDirInternal();
}

}  // namespace chrome

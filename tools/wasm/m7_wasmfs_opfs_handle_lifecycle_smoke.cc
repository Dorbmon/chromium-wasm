// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Isolated bounded OPFS SyncAccessHandle lifecycle probe. This target is
// deliberately separate from Chrome and the M7 profile work. It proves only
// that a bounded set of distinct WasmFS OPFS paths can be closed by one live
// module, reopened and closed by another live module in the same document,
// then verified and reaped after an outer-document replacement.

#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <emscripten/emscripten.h>
#include <emscripten/threading.h>
#include <emscripten/wasmfs.h>

#include <array>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <string_view>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m7_wasmfs_opfs_handle_lifecycle_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE";
constexpr char kHolderRole[] = "holder";
constexpr char kReopenRole[] = "reopen";
constexpr char kVerifyRole[] = "verify";
constexpr char kRolePrefix[] = "--m7-opfs-role=";
constexpr char kRunPrefix[] = "--m7-opfs-run=";
constexpr size_t kMinimumRunIdLength = 16;
constexpr size_t kMaximumRunIdLength = 128;
constexpr size_t kPathCount = 32;
constexpr size_t kPayloadSize = 8;
constexpr char kHolderClosedMarker[] =
    "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:"
    "HOLDER_CLOSED_32 files=32 write=ok fdatasync=ok close=ok";
constexpr char kReopenClosedMarker[] =
    "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:"
    "REOPEN_CLOSED_32 files=32 read=ok fdatasync=ok close=ok";
constexpr char kVerifyReapMarker[] =
    "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:"
    "VERIFY_REAP_32 files=32 read=ok close=ok cleanup=ok";

enum class Role {
  kHolder,
  kReopen,
  kVerify,
};

struct Arguments {
  Role role = Role::kHolder;
  std::string run_id;
};

struct Paths {
  std::string root;
  std::array<std::string, kPathCount> files;
};

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

int Unsupported(const char* reason) {
  std::fprintf(stderr, "%s:UNSUPPORTED reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 2;
}

[[noreturn]] void FailImmediately(const char* reason) {
  Fail(reason);
  std::abort();
}

void Require(bool condition, const char* reason) {
  if (!condition) {
    FailImmediately(reason);
  }
}

bool HasPrefix(std::string_view value, std::string_view prefix) {
  return value.size() >= prefix.size() && value.substr(0, prefix.size()) == prefix;
}

bool IsValidRunId(std::string_view run_id) {
  if (run_id.size() < kMinimumRunIdLength ||
      run_id.size() > kMaximumRunIdLength) {
    return false;
  }
  for (unsigned char value : run_id) {
    if (!std::isalnum(value) && value != '-' && value != '_') {
      return false;
    }
  }
  return true;
}

const char* ParseRole(std::string_view value, Role* role) {
  if (value == kHolderRole) {
    *role = Role::kHolder;
  } else if (value == kReopenRole) {
    *role = Role::kReopen;
  } else if (value == kVerifyRole) {
    *role = Role::kVerify;
  } else {
    return "invalid_role";
  }
  return nullptr;
}

const char* ParseArguments(int argc, char* argv[], Arguments* arguments) {
  bool saw_role = false;
  bool saw_run_id = false;
  for (int index = 1; index < argc; ++index) {
    const std::string_view argument(argv[index]);
    if (HasPrefix(argument, kRolePrefix)) {
      if (saw_role) {
        return "duplicate_role";
      }
      saw_role = true;
      if (const char* error =
              ParseRole(argument.substr(std::strlen(kRolePrefix)),
                        &arguments->role)) {
        return error;
      }
      continue;
    }
    if (HasPrefix(argument, kRunPrefix)) {
      if (saw_run_id) {
        return "duplicate_run_id";
      }
      saw_run_id = true;
      arguments->run_id = argument.substr(std::strlen(kRunPrefix));
      continue;
    }
    return "unexpected_argument";
  }
  if (!saw_role || !saw_run_id) {
    return "missing_role_or_run_id";
  }
  return IsValidRunId(arguments->run_id) ? nullptr : "invalid_run_id";
}

const char* RoleName(Role role) {
  switch (role) {
    case Role::kHolder:
      return kHolderRole;
    case Role::kReopen:
      return kReopenRole;
    case Role::kVerify:
      return kVerifyRole;
  }
  std::abort();
}

Paths MakePaths(const std::string& run_id) {
  Paths paths;
  paths.root = "/opfs/" + run_id;
  for (size_t index = 0; index < paths.files.size(); ++index) {
    paths.files[index] = paths.root + "/entry-" + std::to_string(index);
  }
  for (size_t left = 0; left < paths.files.size(); ++left) {
    for (size_t right = left + 1; right < paths.files.size(); ++right) {
      Require(paths.files[left] != paths.files[right], "paths_not_distinct");
    }
  }
  return paths;
}

std::array<uint8_t, kPayloadSize> PayloadFor(size_t index) {
  Require(index < kPathCount, "payload_index_out_of_range");
  const uint8_t value = static_cast<uint8_t>(index);
  return {0x6d, 0x37, 0x68, value, static_cast<uint8_t>(value ^ 0xa5),
          static_cast<uint8_t>(value + 0x31), 0x00, 0x5a};
}

void MountOpfs() {
  backend_t backend = wasmfs_create_opfs_backend();
  Require(backend != nullptr, "opfs_backend_create");
  Require(wasmfs_create_directory("/opfs", 0700, backend) == 0,
          "opfs_mount");
}

void RequireExactWrite(int descriptor,
                       const std::array<uint8_t, kPayloadSize>& payload,
                       const char* reason) {
  Require(write(descriptor, payload.data(), payload.size()) ==
              static_cast<ssize_t>(payload.size()),
          reason);
}

void RequireExactRead(int descriptor,
                      const std::array<uint8_t, kPayloadSize>& expected,
                      const char* reason) {
  std::array<uint8_t, kPayloadSize> actual{};
  Require(pread(descriptor, actual.data(), actual.size(), 0) ==
              static_cast<ssize_t>(actual.size()),
          reason);
  Require(std::memcmp(actual.data(), expected.data(), actual.size()) == 0,
          reason);
}

[[noreturn]] void RetainLiveRuntime() {
  // The OPFS backend owns a ProxyWorker whose normal global teardown performs
  // a blocking pthread join on the browser main thread. Do not return from
  // main. The generated pthread runtime catches this unwind and keeps this
  // module instance live; the outer document replacement is the only teardown
  // boundary exercised by this probe.
  emscripten_exit_with_live_runtime();
}

[[noreturn]] void RunHolder(const Paths& paths) {
  Require(mkdir(paths.root.c_str(), 0700) == 0, "holder_root_create");
  for (size_t index = 0; index < paths.files.size(); ++index) {
    const int descriptor = open(paths.files[index].c_str(),
                                O_CREAT | O_EXCL | O_RDWR, /*mode=*/0600);
    Require(descriptor >= 0, "holder_file_create");
    RequireExactWrite(descriptor, PayloadFor(index), "holder_file_write");
    Require(fdatasync(descriptor) == 0, "holder_file_fdatasync");
    Require(close(descriptor) == 0, "holder_file_close");
  }
  std::fprintf(stdout, "%s\n", kHolderClosedMarker);
  std::fflush(stdout);
  RetainLiveRuntime();
}

[[noreturn]] void RunReopen(const Paths& paths) {
  for (size_t index = 0; index < paths.files.size(); ++index) {
    const int descriptor = open(paths.files[index].c_str(), O_RDWR);
    Require(descriptor >= 0, "reopen_file_open");
    RequireExactRead(descriptor, PayloadFor(index), "reopen_file_read");
    Require(fdatasync(descriptor) == 0, "reopen_file_fdatasync");
    Require(close(descriptor) == 0, "reopen_file_close");
  }
  std::fprintf(stdout, "%s\n", kReopenClosedMarker);
  std::fflush(stdout);
  RetainLiveRuntime();
}

[[noreturn]] void RunVerifyAndReap(const Paths& paths) {
  for (size_t index = 0; index < paths.files.size(); ++index) {
    const int descriptor = open(paths.files[index].c_str(), O_RDWR);
    Require(descriptor >= 0, "verify_file_open");
    RequireExactRead(descriptor, PayloadFor(index), "verify_file_read");
    Require(close(descriptor) == 0, "verify_file_close");
  }
  for (const std::string& path : paths.files) {
    Require(unlink(path.c_str()) == 0, "verify_file_delete");
  }
  Require(rmdir(paths.root.c_str()) == 0, "verify_root_delete");
  std::fprintf(stdout, "%s\n", kVerifyReapMarker);
  std::fflush(stdout);
  RetainLiveRuntime();
}

}  // namespace

int main(int argc, char* argv[]) {
  Arguments arguments;
  if (const char* argument_error = ParseArguments(argc, argv, &arguments)) {
    return Fail(argument_error);
  }
  if (emscripten_is_main_browser_thread()) {
    return Unsupported("application_main_on_browser_thread");
  }
  if (!emscripten_has_threading_support()) {
    return Unsupported("pthread_support_unavailable");
  }

  std::fprintf(stdout, "%s:RUNTIME_START role=%s run_id=redacted\n", kPrefix,
               RoleName(arguments.role));
  std::fflush(stdout);
  MountOpfs();
  const Paths paths = MakePaths(arguments.run_id);
  switch (arguments.role) {
    case Role::kHolder:
      RunHolder(paths);
    case Role::kReopen:
      RunReopen(paths);
    case Role::kVerify:
      RunVerifyAndReap(paths);
  }
  std::abort();
}

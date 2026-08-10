// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Isolated OPFS SyncAccessHandle writer-exclusivity probe. This target is
// deliberately separate from Chrome and from the M7 persistence smoke: it
// establishes only what two independently instantiated WasmFS runtimes do
// when they contend for one OPFS file.

#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <emscripten/emscripten.h>
#include <emscripten/threading.h>
#include <emscripten/wasmfs.h>

#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <string_view>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m7_wasmfs_opfs_exclusivity_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY";
constexpr char kContenderOpenBeginMarker[] =
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:CONTENDER_OPEN_BEGIN mode=O_RDWR";
constexpr char kHolderRole[] = "holder";
constexpr char kContenderRole[] = "contender";
constexpr char kReopenRole[] = "reopen";
constexpr char kRolePrefix[] = "--m7-opfs-role=";
constexpr char kRunPrefix[] = "--m7-opfs-run=";
constexpr size_t kMinimumRunIdLength = 16;
constexpr size_t kMaximumRunIdLength = 128;
constexpr std::array<uint8_t, 1> kWriterData{0xa7};

enum class Role {
  kHolder,
  kContender,
  kReopen,
};

struct Arguments {
  Role role = Role::kHolder;
  std::string run_id;
};

struct Paths {
  std::string root;
  std::string writer;
};

// This is deliberately not RAII. The holder must retain an open WasmFS
// descriptor and its OPFS SyncAccessHandle after its application pthread has
// unwound into emscripten_exit_with_live_runtime(). The outer document is the
// only teardown boundary exercised by this probe.
int g_holder_fd = -1;

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
  } else if (value == kContenderRole) {
    *role = Role::kContender;
  } else if (value == kReopenRole) {
    *role = Role::kReopen;
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
    case Role::kContender:
      return kContenderRole;
    case Role::kReopen:
      return kReopenRole;
  }
  std::abort();
}

Paths MakePaths(const std::string& run_id) {
  Paths paths;
  paths.root = "/opfs/" + run_id;
  paths.writer = paths.root + "/writer.bin";
  return paths;
}

void MountOpfs() {
  backend_t backend = wasmfs_create_opfs_backend();
  Require(backend != nullptr, "opfs_backend_create");
  Require(wasmfs_create_directory("/opfs", 0700, backend) == 0,
          "opfs_mount");
}

void RequireExactWrite(int descriptor, const uint8_t* data, size_t size,
                       const char* reason) {
  Require(write(descriptor, data, size) == static_cast<ssize_t>(size), reason);
}

void RequireExactRead(int descriptor, const uint8_t* expected, size_t size,
                      const char* reason) {
  std::array<uint8_t, kWriterData.size()> actual{};
  Require(size == actual.size(), "unexpected_reader_size");
  Require(pread(descriptor, actual.data(), actual.size(), 0) ==
              static_cast<ssize_t>(actual.size()),
          reason);
  Require(std::memcmp(actual.data(), expected, actual.size()) == 0, reason);
}

[[noreturn]] void RetainLiveRuntime() {
  // The OPFS backend owns a ProxyWorker whose normal global teardown performs
  // a blocking pthread join on the browser main thread. Do not return from
  // main. The generated pthread runtime catches this unwind and keeps this
  // module instance live; the outer document replacement later disposes it.
  emscripten_exit_with_live_runtime();
}

[[noreturn]] void RunHolder(const Paths& paths) {
  Require(mkdir(paths.root.c_str(), 0700) == 0, "holder_root_create");
  const int descriptor =
      open(paths.writer.c_str(), O_CREAT | O_EXCL | O_RDWR, /*mode=*/0600);
  Require(descriptor >= 0, "holder_writer_create");
  RequireExactWrite(descriptor, kWriterData.data(), kWriterData.size(),
                    "holder_writer_write");
  Require(fdatasync(descriptor) == 0, "holder_writer_fdatasync");
  g_holder_fd = descriptor;
  Require(g_holder_fd >= 0, "holder_fd_not_retained");
  std::fprintf(stdout, "%s:HOLDER_READY access_fd_held=1 fdatasync=ok\n",
               kPrefix);
  std::fflush(stdout);
  RetainLiveRuntime();
}

[[noreturn]] void RunContender(const Paths& paths) {
  // This is a diagnostic boundary only. A held SyncAccessHandle should make
  // the following writable open return EACCES; it must never be treated as a
  // successful or queued lock operation.
  std::fprintf(stdout, "%s\n", kContenderOpenBeginMarker);
  std::fflush(stdout);
  errno = 0;
  const int descriptor = open(paths.writer.c_str(), O_RDWR);
  const int open_errno = errno;
  Require(descriptor == -1 && open_errno == EACCES,
          "contender_writer_not_eacces");
  // Errno integer values are libc ABI details. The native equality above is
  // the assertion; expose its symbolic result so the host does not impose a
  // Linux errno-number convention on this Wasm target.
  std::fprintf(stdout, "%s:CONTENDER_EACCES errno=eacces\n", kPrefix);
  std::fflush(stdout);
  RetainLiveRuntime();
}

[[noreturn]] void RunReopen(const Paths& paths) {
  const int descriptor = open(paths.writer.c_str(), O_RDWR);
  Require(descriptor >= 0, "reopen_writer_open");
  RequireExactRead(descriptor, kWriterData.data(), kWriterData.size(),
                   "reopen_writer_read");
  Require(fdatasync(descriptor) == 0, "reopen_writer_fdatasync");
  Require(close(descriptor) == 0, "reopen_writer_close");
  Require(unlink(paths.writer.c_str()) == 0, "reopen_writer_delete");
  Require(rmdir(paths.root.c_str()) == 0, "reopen_root_delete");
  std::fprintf(stdout, "%s:REOPEN_OK cleanup=ok\n", kPrefix);
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
    case Role::kContender:
      RunContender(paths);
    case Role::kReopen:
      RunReopen(paths);
  }
  std::abort();
}

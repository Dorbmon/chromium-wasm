// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Isolated normal-shutdown probe for the pinned WasmFS OPFS backend. The
// dedicated host Worker starts this target, so returning from main exercises
// Emscripten's normal atexit path away from the page's browser-main thread.

#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

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
#error "m7_wasmfs_opfs_shutdown_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M7_OPFS_SHUTDOWN";
constexpr char kCompletionMarker[] =
    "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:NATIVE_COMPLETE "
    "rw=ok fdatasync=ok close=ok cleanup=ok";
constexpr char kAtexitMarker[] =
    "CHROMIUM_WASM_M7_OPFS_ATEXIT:after-native-complete";
constexpr char kRunPrefix[] = "--m7-opfs-run=";
constexpr size_t kMinimumRunIdLength = 16;
constexpr size_t kMaximumRunIdLength = 128;
constexpr std::array<uint8_t, 12> kPayload{
    0x73, 0x68, 0x75, 0x74, 0x00, 0x64,
    0x6f, 0x77, 0x6e, 0x2d, 0x6f, 0x6b,
};

// Set only after the native completion marker has been accepted by stdout.
// The atexit callback uses this to make its marker an ordering proof rather
// than merely evidence that a callback was registered.
bool g_native_completion_flushed = false;

struct Paths {
  std::string root;
  std::string file;
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

void RecordAtexitAfterNativeCompletion() {
  if (!g_native_completion_flushed) {
    std::fprintf(stderr, "%s:FAIL reason=atexit_before_native_complete\n",
                 kPrefix);
    std::fflush(stderr);
    std::abort();
  }

  const int written = std::fprintf(stdout, "%s\n", kAtexitMarker);
  if (written <= 0 || std::fflush(stdout) != 0) {
    std::fprintf(stderr, "%s:FAIL reason=atexit_marker_flush\n", kPrefix);
    std::fflush(stderr);
    std::abort();
  }
}

bool HasPrefix(std::string_view value, std::string_view prefix) {
  return value.size() >= prefix.size() &&
         value.substr(0, prefix.size()) == prefix;
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

const char* ParseRunId(int argc, char* argv[], std::string* run_id) {
  bool saw_run_id = false;
  for (int index = 1; index < argc; ++index) {
    const std::string_view argument(argv[index]);
    if (!HasPrefix(argument, kRunPrefix)) {
      return "unexpected_argument";
    }
    if (saw_run_id) {
      return "duplicate_run_id";
    }
    saw_run_id = true;
    *run_id = argument.substr(std::strlen(kRunPrefix));
  }
  if (!saw_run_id) {
    return "missing_run_id";
  }
  return IsValidRunId(*run_id) ? nullptr : "invalid_run_id";
}

Paths MakePaths(const std::string& run_id) {
  Paths paths;
  paths.root = "/opfs/" + run_id;
  paths.file = paths.root + "/shutdown.bin";
  return paths;
}

void MountOpfs() {
  backend_t backend = wasmfs_create_opfs_backend();
  Require(backend != nullptr, "opfs_backend_create");
  Require(wasmfs_create_directory("/opfs", 0700, backend) == 0, "opfs_mount");
}

void RequireExactWrite(int descriptor,
                       const uint8_t* data,
                       size_t size,
                       const char* reason) {
  Require(write(descriptor, data, size) == static_cast<ssize_t>(size), reason);
}

void RequireExactRead(int descriptor,
                      const uint8_t* expected,
                      size_t size,
                      const char* reason) {
  std::array<uint8_t, kPayload.size()> actual{};
  Require(size == actual.size(), "unexpected_read_size");
  Require(pread(descriptor, actual.data(), actual.size(), 0) ==
              static_cast<ssize_t>(actual.size()),
          reason);
  Require(std::memcmp(actual.data(), expected, actual.size()) == 0, reason);
}

void RunNormalShutdownWork(const Paths& paths) {
  Require(mkdir(paths.root.c_str(), 0700) == 0, "namespace_create");
  const int descriptor =
      open(paths.file.c_str(), O_CREAT | O_EXCL | O_RDWR, /*mode=*/0600);
  Require(descriptor >= 0, "file_create");
  RequireExactWrite(descriptor, kPayload.data(), kPayload.size(), "file_write");
  Require(fdatasync(descriptor) == 0, "file_fdatasync");
  RequireExactRead(descriptor, kPayload.data(), kPayload.size(), "file_read");
  Require(close(descriptor) == 0, "file_close");
  Require(unlink(paths.file.c_str()) == 0, "file_cleanup");
  Require(rmdir(paths.root.c_str()) == 0, "namespace_cleanup");
}

}  // namespace

int main(int argc, char* argv[]) {
  std::string run_id;
  if (const char* argument_error = ParseRunId(argc, argv, &run_id)) {
    return Fail(argument_error);
  }
  if (emscripten_is_main_browser_thread()) {
    return Unsupported("application_main_on_browser_thread");
  }
  if (!emscripten_has_threading_support()) {
    return Unsupported("pthread_support_unavailable");
  }

  std::fprintf(stdout, "%s:RUNTIME_START run_id=redacted\n", kPrefix);
  std::fflush(stdout);
  Require(std::atexit(RecordAtexitAfterNativeCompletion) == 0,
          "atexit_register");
  MountOpfs();
  RunNormalShutdownWork(MakePaths(run_id));

  // This marker is deliberately emitted after every descriptor and namespace
  // cleanup operation. The normal return below is the test subject: it must
  // reach the generated EXIT_RUNTIME path, whose normal onExit(0) delivery is
  // separately required by the host proof.
  const int completion_written =
      std::fprintf(stdout, "%s\n", kCompletionMarker);
  Require(completion_written > 0, "completion_marker_write");
  Require(std::fflush(stdout) == 0, "completion_marker_flush");
  g_native_completion_flushed = true;
  return 0;
}

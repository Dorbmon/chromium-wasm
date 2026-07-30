// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <array>
#include <memory>
#include <string>
#include <utility>

#include "base/at_exit.h"
#include "base/command_line.h"
#include "base/containers/span.h"
#include "base/files/file.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/files/scoped_temp_dir.h"
#include "base/functional/bind.h"
#include "base/memory/ref_counted.h"
#include "base/message_loop/message_pump_type.h"
#include "base/run_loop.h"
#include "base/strings/string_util.h"
#include "base/task/single_thread_task_executor.h"
#include "base/task/thread_pool/thread_pool_instance.h"
#include "build/build_config.h"
#include "net/base/cache_type.h"
#include "net/base/io_buffer.h"
#include "net/base/net_errors.h"
#include "net/base/request_priority.h"
#include "net/disk_cache/cache_util.h"
#include "net/disk_cache/disk_cache.h"
#include "net/disk_cache/simple/simple_util.h"

#if !BUILDFLAG(IS_WASM)
#error "m3_disk_cache_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX disk-cache semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M3_DISK_CACHE";
constexpr char kCacheKey[] = "https://wasm.test/cache-entry";
constexpr char kCachePayload[] = "chromium-wasm-simple-cache-payload";
constexpr char kOldDeletePayload[] = "old payload";
constexpr char kNewDeletePayload[] = "new payload";

int Fail(const char* reason) {
  fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  fflush(stderr);
  return 1;
}

void PrintPhase(const char* name) {
  printf("%s:PHASE name=%s status=ok\n", kPrefix, name);
  fflush(stdout);
}

disk_cache::BackendResult CreateBackendAndWait(
    net::BackendType backend_type,
    const base::FilePath& path) {
  disk_cache::BackendResult callback_result;
  bool callback_called = false;
  base::RunLoop run_loop;
  disk_cache::BackendResult result = disk_cache::CreateCacheBackend(
      net::DISK_CACHE, backend_type, /*file_operations=*/nullptr, path,
      /*max_bytes=*/1024 * 1024,
      disk_cache::ResetHandling::kNeverReset, /*net_log=*/nullptr,
      /*cache_encryption_delegate=*/nullptr,
      base::BindOnce(
          [](disk_cache::BackendResult* output, bool* called,
             base::RunLoop* loop, disk_cache::BackendResult result) {
            *output = std::move(result);
            *called = true;
            loop->Quit();
          },
          &callback_result, &callback_called, &run_loop));
  if (result.net_error != net::ERR_IO_PENDING) {
    return result;
  }
  run_loop.Run();
  if (!callback_called) {
    return disk_cache::BackendResult::MakeError(net::ERR_UNEXPECTED);
  }
  return callback_result;
}

disk_cache::EntryResult CreateEntryAndWait(disk_cache::Backend* backend) {
  disk_cache::EntryResult callback_result;
  bool callback_called = false;
  base::RunLoop run_loop;
  disk_cache::EntryResult result = backend->CreateEntry(
      kCacheKey, net::HIGHEST,
      base::BindOnce(
          [](disk_cache::EntryResult* output, bool* called,
             base::RunLoop* loop, disk_cache::EntryResult result) {
            *output = std::move(result);
            *called = true;
            loop->Quit();
          },
          &callback_result, &callback_called, &run_loop));
  if (result.net_error() != net::ERR_IO_PENDING) {
    return result;
  }
  run_loop.Run();
  if (!callback_called) {
    return disk_cache::EntryResult::MakeError(net::ERR_UNEXPECTED);
  }
  return callback_result;
}

disk_cache::EntryResult OpenEntryAndWait(disk_cache::Backend* backend) {
  disk_cache::EntryResult callback_result;
  bool callback_called = false;
  base::RunLoop run_loop;
  disk_cache::EntryResult result = backend->OpenEntry(
      kCacheKey, net::HIGHEST,
      base::BindOnce(
          [](disk_cache::EntryResult* output, bool* called,
             base::RunLoop* loop, disk_cache::EntryResult result) {
            *output = std::move(result);
            *called = true;
            loop->Quit();
          },
          &callback_result, &callback_called, &run_loop));
  if (result.net_error() != net::ERR_IO_PENDING) {
    return result;
  }
  run_loop.Run();
  if (!callback_called) {
    return disk_cache::EntryResult::MakeError(net::ERR_UNEXPECTED);
  }
  return callback_result;
}

int WriteEntryAndWait(disk_cache::Entry* entry,
                      const scoped_refptr<net::IOBuffer>& buffer,
                      int length) {
  int callback_result = net::ERR_UNEXPECTED;
  bool callback_called = false;
  base::RunLoop run_loop;
  const int result = entry->WriteData(
      /*index=*/0, /*offset=*/0, buffer.get(), length,
      base::BindOnce(
          [](int* output, bool* called, base::RunLoop* loop, int result) {
            *output = result;
            *called = true;
            loop->Quit();
          },
          &callback_result, &callback_called, &run_loop),
      /*truncate=*/true);
  if (result != net::ERR_IO_PENDING) {
    return result;
  }
  run_loop.Run();
  return callback_called ? callback_result : net::ERR_UNEXPECTED;
}

int ReadEntryAndWait(disk_cache::Entry* entry,
                     const scoped_refptr<net::IOBuffer>& buffer,
                     int length) {
  int callback_result = net::ERR_UNEXPECTED;
  bool callback_called = false;
  base::RunLoop run_loop;
  const int result = entry->ReadData(
      /*index=*/0, /*offset=*/0, buffer.get(), length,
      base::BindOnce(
          [](int* output, bool* called, base::RunLoop* loop, int result) {
            *output = result;
            *called = true;
            loop->Quit();
          },
          &callback_result, &callback_called, &run_loop));
  if (result != net::ERR_IO_PENDING) {
    return result;
  }
  run_loop.Run();
  return callback_called ? callback_result : net::ERR_UNEXPECTED;
}

bool IsSimpleBackend(disk_cache::Backend* backend) {
  base::StringPairs stats;
  backend->GetStats(&stats);
  for (const auto& [name, value] : stats) {
    if (name == "Cache type" && value == "Simple Cache") {
      return true;
    }
  }
  return false;
}

const char* TestFilesystemHelpers(const base::FilePath& root) {
  const base::FilePath source = root.AppendASCII("cache-to-move");
  const base::FilePath destination = root.AppendASCII("moved-cache");
  const base::FilePath source_file = source.AppendASCII("entry");
  const base::FilePath destination_file = destination.AppendASCII("entry");
  if (!base::CreateDirectory(source) ||
      !base::WriteFile(source_file, "move payload")) {
    return "move_fixture_create";
  }
  if (!disk_cache::MoveCache(source, destination) ||
      base::PathExists(source) || !base::PathExists(destination_file)) {
    return "move_result";
  }
  std::string moved_contents;
  if (!base::ReadFileToString(destination_file, &moved_contents) ||
      moved_contents != "move payload") {
    return "move_contents";
  }

  const base::FilePath delete_path = root.AppendASCII("delete-entry");
  if (!base::WriteFile(delete_path, kOldDeletePayload)) {
    return "delete_fixture_create";
  }
  base::File old_file(delete_path,
                      base::File::FLAG_OPEN | base::File::FLAG_READ);
  if (!old_file.IsValid()) {
    return "delete_fixture_open";
  }
  if (!disk_cache::simple_util::SimpleCacheDeleteFile(delete_path) ||
      base::PathExists(delete_path) ||
      !base::WriteFile(delete_path, kNewDeletePayload)) {
    return "delete_and_reuse";
  }
  std::string reused_contents;
  if (!base::ReadFileToString(delete_path, &reused_contents) ||
      reused_contents != kNewDeletePayload) {
    return "delete_reuse_contents";
  }
  std::array<uint8_t, sizeof(kOldDeletePayload) - 1> old_contents;
  if (!old_file.ReadAndCheck(/*offset=*/0, base::span(old_contents)) ||
      memcmp(old_contents.data(), kOldDeletePayload, old_contents.size()) !=
          0) {
    return "delete_open_handle_contents";
  }
  return nullptr;
}

const char* TestSimpleCache(const base::FilePath& root) {
  const base::FilePath cache_path = root.AppendASCII("simple-cache");
  disk_cache::BackendResult backend_result =
      CreateBackendAndWait(net::CACHE_BACKEND_DEFAULT, cache_path);
  if (backend_result.net_error != net::OK || !backend_result.backend) {
    return "default_backend_create";
  }
  std::unique_ptr<disk_cache::Backend> backend =
      std::move(backend_result.backend);
  if (!IsSimpleBackend(backend.get())) {
    return "default_backend_not_simple";
  }

  disk_cache::EntryResult entry_result = CreateEntryAndWait(backend.get());
  if (entry_result.net_error() != net::OK || entry_result.opened()) {
    return "entry_create";
  }
  disk_cache::ScopedEntryPtr entry(entry_result.ReleaseEntry());
  const int payload_size = static_cast<int>(strlen(kCachePayload));
  auto write_buffer =
      base::MakeRefCounted<net::StringIOBuffer>(kCachePayload);
  if (WriteEntryAndWait(entry.get(), write_buffer, payload_size) !=
      payload_size) {
    return "entry_write";
  }
  entry.reset();
  backend.reset();

  base::RunLoop flush_loop;
  disk_cache::FlushCacheThreadAsynchronouslyForTesting(
      base::BindOnce(&base::RunLoop::Quit, base::Unretained(&flush_loop)));
  flush_loop.Run();
  base::RunLoop().RunUntilIdle();

  backend_result =
      CreateBackendAndWait(net::CACHE_BACKEND_DEFAULT, cache_path);
  if (backend_result.net_error != net::OK || !backend_result.backend) {
    return "backend_reopen";
  }
  backend = std::move(backend_result.backend);
  if (!IsSimpleBackend(backend.get())) {
    return "reopened_backend_not_simple";
  }
  entry_result = OpenEntryAndWait(backend.get());
  if (entry_result.net_error() != net::OK || !entry_result.opened()) {
    return "entry_reopen";
  }
  entry.reset(entry_result.ReleaseEntry());
  if (entry->GetDataSize(/*index=*/0) != payload_size) {
    return "reopened_entry_size";
  }
  auto read_buffer =
      base::MakeRefCounted<net::IOBufferWithSize>(payload_size);
  if (ReadEntryAndWait(entry.get(), read_buffer, payload_size) !=
          payload_size ||
      memcmp(read_buffer->data(), kCachePayload, payload_size) != 0) {
    return "reopened_entry_contents";
  }
  entry.reset();
  backend.reset();

  return nullptr;
}

const char* TestExplicitBlockfileFailure(const base::FilePath& root) {
  disk_cache::BackendResult callback_result;
  bool callback_called = false;
  base::RunLoop run_loop;
  disk_cache::BackendResult initial_result = disk_cache::CreateCacheBackend(
      net::DISK_CACHE, net::CACHE_BACKEND_BLOCKFILE,
      /*file_operations=*/nullptr, root.AppendASCII("blockfile-cache"),
      /*max_bytes=*/1024 * 1024,
      disk_cache::ResetHandling::kNeverReset, /*net_log=*/nullptr,
      /*cache_encryption_delegate=*/nullptr,
      base::BindOnce(
          [](disk_cache::BackendResult* output, bool* called,
             base::RunLoop* loop, disk_cache::BackendResult result) {
            *output = std::move(result);
            *called = true;
            loop->Quit();
          },
          &callback_result, &callback_called, &run_loop));
  if (initial_result.net_error != net::ERR_IO_PENDING ||
      initial_result.backend || callback_called) {
    return "blockfile_failure_not_async";
  }

  run_loop.Run();
  if (!callback_called || callback_result.net_error != net::ERR_FAILED ||
      callback_result.backend) {
    return "blockfile_failure_result";
  }
  return nullptr;
}

}  // namespace

int main(int argc, char** argv) {
  printf("%s:RUNTIME_START\n", kPrefix);
  fflush(stdout);

  base::AtExitManager at_exit_manager;
  base::CommandLine::Init(argc, argv);
  base::SingleThreadTaskExecutor application_executor(
      base::MessagePumpType::DEFAULT);
  base::ThreadPoolInstance::CreateAndStartWithDefaultParams(
      "m3_disk_cache_smoke");

  base::ScopedTempDir temp_dir;
  if (!temp_dir.CreateUniqueTempDir()) {
    return Fail("temp_directory");
  }
  const char* error = TestFilesystemHelpers(temp_dir.GetPath());
  if (error) {
    return Fail(error);
  }
  PrintPhase("filesystem_helpers");

  error = TestSimpleCache(temp_dir.GetPath());
  if (error) {
    return Fail(error);
  }
  PrintPhase("simple_cache_round_trip");

  error = TestExplicitBlockfileFailure(temp_dir.GetPath());
  if (error) {
    return Fail(error);
  }
  PrintPhase("blockfile_failure_contract");

  disk_cache::FlushCacheThreadForTesting();
  base::RunLoop().RunUntilIdle();
  base::ThreadPoolInstance::Get()->Shutdown();

  printf("%s:RUNTIME_END\n", kPrefix);
  printf(
      "%s:RESULT filesystem=memfs move=ok delete_open_reuse=ok "
      "default_backend=simple write_read=ok reopen=ok "
      "blockfile=unsupported_async\n",
      kPrefix);
  printf("%s:PASS\n", kPrefix);
  fflush(stdout);
  return 0;
}

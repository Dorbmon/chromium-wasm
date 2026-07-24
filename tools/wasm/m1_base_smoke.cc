// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/heap.h>
#include <emscripten/html5.h>
#include <emscripten/threading.h>
#include <emscripten/version.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <set>
#include <string>
#include <vector>

#include "base/base_paths.h"
#include "base/byte_size.h"
#include "base/command_line.h"
#include "base/containers/span.h"
#include "base/files/file.h"
#include "base/files/file_enumerator.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/memory/page_size.h"
#include "base/path_service.h"
#include "base/process/launch.h"
#include "base/process/process.h"
#include "base/process/process_handle.h"
#include "base/rand_util.h"
#include "base/synchronization/condition_variable.h"
#include "base/synchronization/lock.h"
#include "base/synchronization/waitable_event.h"
#include "base/system/sys_info.h"
#include "base/threading/platform_thread.h"
#include "base/threading/thread_local_storage.h"
#include "base/time/time.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_base_smoke must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_BASE";
constexpr base::TimeDelta kPhaseTimeout = base::Seconds(3);
constexpr base::TimeDelta kPollInterval = base::Milliseconds(2);
constexpr int kCounterIterations = 2000;

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
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

void BeginPhase(const char* phase) {
  std::fprintf(stdout, "%s:PHASE name=%s\n", kPrefix, phase);
  std::fflush(stdout);
}

template <typename Predicate>
bool WaitUntil(Predicate predicate, base::TimeDelta timeout = kPhaseTimeout) {
  const base::TimeTicks deadline = base::TimeTicks::Now() + timeout;
  while (!predicate()) {
    const base::TimeDelta remaining = deadline - base::TimeTicks::Now();
    if (!remaining.is_positive()) {
      return predicate();
    }
    base::PlatformThread::YieldCurrentThread();
    base::PlatformThread::Sleep(std::min(remaining, kPollInterval));
  }
  return true;
}

bool HasNonZeroByte(base::span<const uint8_t> bytes) {
  return std::ranges::any_of(bytes, [](uint8_t byte) { return byte != 0; });
}

bool ReadAllBytes(const base::FilePath& path, std::vector<uint8_t>* contents) {
  base::File file(path, base::File::FLAG_OPEN | base::File::FLAG_READ);
  if (!file.IsValid()) {
    return false;
  }

  const int64_t length = file.GetLength();
  if (length < 0 || length > 4096) {
    return false;
  }
  contents->assign(static_cast<size_t>(length), 0);
  return file.ReadAtCurrentPosAndCheck(base::span(*contents));
}

void TestPathsAndFiles() {
  BeginPhase("paths_files");

  base::FilePath current_path;
  base::FilePath temp_path;
  base::FilePath home_path;
  Require(base::PathService::Get(base::DIR_CURRENT, &current_path),
          "path_current_unavailable");
  Require(current_path.IsAbsolute() && base::DirectoryExists(current_path),
          "path_current_invalid");
  Require(base::PathService::Get(base::DIR_TEMP, &temp_path),
          "path_temp_unavailable");
  Require(temp_path == base::FilePath("/tmp") &&
              base::DirectoryExists(temp_path),
          "path_temp_invalid");
  Require(base::PathService::Get(base::DIR_HOME, &home_path),
          "path_home_unavailable");
  Require(home_path == base::FilePath("/home/web_user") &&
              base::DirectoryExists(home_path),
          "path_home_invalid");

  base::FilePath direct_temp_path;
  Require(base::GetTempDir(&direct_temp_path) &&
              direct_temp_path == temp_path,
          "get_temp_dir_mismatch");
  Require(base::GetHomeDir() == home_path, "get_home_dir_mismatch");

  const base::FilePath untouched_path("unchanged-on-failure");
  base::FilePath executable_path = untouched_path;
  Require(!base::PathService::Get(base::FILE_EXE, &executable_path) &&
              executable_path == untouched_path,
          "path_executable_claimed_supported");
  base::FilePath module_path = untouched_path;
  Require(!base::PathService::Get(base::FILE_MODULE, &module_path) &&
              module_path == untouched_path,
          "path_module_claimed_supported");

  base::FilePath workspace;
  Require(base::CreateTemporaryDirInDir(temp_path, "m1-base-smoke",
                                        &workspace),
          "temp_workspace_create");
  Require(workspace.IsAbsolute() && temp_path.IsParent(workspace) &&
              workspace.DirName() == temp_path &&
              base::DirectoryExists(workspace),
          "temp_workspace_invalid");

  const base::FilePath empty_path = workspace.Append("empty.bin");
  Require(base::WriteFile(empty_path, base::span<const uint8_t>()),
          "empty_file_create");
  std::vector<uint8_t> observed;
  Require(ReadAllBytes(empty_path, &observed) && observed.empty(),
          "empty_file_round_trip");
  base::File::Info empty_info;
  Require(base::GetFileInfo(empty_path, &empty_info) &&
              !empty_info.is_directory && empty_info.size == 0,
          "empty_file_stat");

  constexpr std::array<uint8_t, 8> kInitialData{
      0x10, 0x20, 0x00, 0x40, 0x50, 0x60, 0x70, 0x80};
  constexpr std::array<uint8_t, 3> kMiddlePatch{0xA0, 0x00, 0xB0};
  constexpr std::array<uint8_t, 3> kAppendData{0xC0, 0x00, 0xD0};
  constexpr size_t kSmallerLength = 7;
  constexpr size_t kLargerLength = 13;

  const base::FilePath binary_path = workspace.Append("binary.bin");
  Require(base::WriteFile(binary_path, base::span(kInitialData)),
          "binary_file_create");
  Require(ReadAllBytes(binary_path, &observed) &&
              observed ==
                  std::vector<uint8_t>(kInitialData.begin(), kInitialData.end()),
          "binary_file_initial_round_trip");

  std::vector<uint8_t> expected(kInitialData.begin(), kInitialData.end());
  {
    base::File file(binary_path, base::File::FLAG_OPEN |
                                     base::File::FLAG_READ |
                                     base::File::FLAG_WRITE);
    Require(file.IsValid(), "binary_file_open_read_write");
    Require(file.Seek(base::File::FROM_END, 0) ==
                static_cast<int64_t>(expected.size()),
            "binary_file_seek_end");
    Require(file.Seek(base::File::FROM_BEGIN, 3) == 3,
            "binary_file_seek_middle");
    Require(file.WriteAtCurrentPosAndCheck(base::span(kMiddlePatch)),
            "binary_file_middle_write");
    Require(file.Seek(base::File::FROM_CURRENT, 0) == 6,
            "binary_file_seek_after_middle_write");
    std::copy(kMiddlePatch.begin(), kMiddlePatch.end(), expected.begin() + 3);

    std::array<uint8_t, kInitialData.size()> in_place_observed{};
    Require(file.Seek(base::File::FROM_BEGIN, 0) == 0,
            "binary_file_seek_begin");
    Require(file.ReadAtCurrentPosAndCheck(base::span(in_place_observed)) &&
                std::ranges::equal(in_place_observed, expected),
            "binary_file_middle_round_trip");
  }

  {
    base::File file(binary_path,
                    base::File::FLAG_OPEN | base::File::FLAG_APPEND);
    Require(file.IsValid(), "binary_file_open_append");
    Require(file.Seek(base::File::FROM_BEGIN, 0) == 0,
            "binary_file_append_seek");
    Require(file.WriteAtCurrentPosAndCheck(base::span(kAppendData)),
            "binary_file_append");
    expected.insert(expected.end(), kAppendData.begin(), kAppendData.end());
    Require(file.GetLength() == static_cast<int64_t>(expected.size()),
            "binary_file_append_length");
  }

  {
    base::File file(binary_path, base::File::FLAG_OPEN |
                                     base::File::FLAG_READ |
                                     base::File::FLAG_WRITE);
    Require(file.IsValid(), "binary_file_open_truncate");
    Require(file.SetLength(kSmallerLength) &&
                file.GetLength() == static_cast<int64_t>(kSmallerLength),
            "binary_file_truncate_smaller");
    expected.resize(kSmallerLength);

    std::array<uint8_t, kSmallerLength> smaller_observed{};
    Require(file.ReadAndCheck(0, base::span(smaller_observed)) &&
                std::ranges::equal(smaller_observed, expected),
            "binary_file_truncate_smaller_content");

    Require(file.SetLength(kLargerLength) &&
                file.GetLength() == static_cast<int64_t>(kLargerLength),
            "binary_file_truncate_larger");
    expected.resize(kLargerLength, 0);
    Require(file.Flush(), "binary_file_flush");
  }

  Require(ReadAllBytes(binary_path, &observed) && observed == expected,
          "binary_file_flush_reopen_round_trip");
  Require(std::ranges::all_of(
              base::span(observed).subspan(kSmallerLength),
              [](uint8_t byte) { return byte == 0; }),
          "binary_file_growth_not_zero_filled");

  const base::FilePath renamed_path = workspace.Append("renamed.bin");
  base::File::Error replace_error = base::File::FILE_ERROR_FAILED;
  Require(base::ReplaceFile(binary_path, renamed_path, &replace_error),
          "binary_file_rename");
  Require(!base::PathExists(binary_path) && base::PathExists(renamed_path),
          "binary_file_rename_paths");
  base::File::Info renamed_info;
  Require(base::GetFileInfo(renamed_path, &renamed_info) &&
              !renamed_info.is_directory &&
              !renamed_info.is_symbolic_link &&
              renamed_info.size == static_cast<int64_t>(kLargerLength),
          "binary_file_renamed_stat");

  const base::FilePath nested_path = workspace.Append("nested");
  const base::FilePath deeper_path = nested_path.Append("deeper");
  Require(base::CreateDirectoryAndGetError(deeper_path, nullptr) &&
              base::DirectoryExists(nested_path) &&
              base::DirectoryExists(deeper_path),
          "nested_directories_create");
  base::File::Info deeper_info;
  Require(base::GetFileInfo(deeper_path, &deeper_info) &&
              deeper_info.is_directory,
          "nested_directory_stat");

  constexpr std::array<uint8_t, 4> kChildData{0x51, 0x00, 0x52, 0x53};
  constexpr std::array<uint8_t, 3> kLeafData{0x61, 0x62, 0x63};
  const base::FilePath child_path = nested_path.Append("child.bin");
  const base::FilePath leaf_path = deeper_path.Append("leaf.bin");
  Require(base::WriteFile(child_path, base::span(kChildData)),
          "nested_child_write");
  Require(base::WriteFile(leaf_path, base::span(kLeafData)),
          "nested_leaf_write");

  const std::set<std::string> expected_entries{
      "empty.bin",       "nested/",        "nested/child.bin",
      "nested/deeper/",  "nested/deeper/leaf.bin",
      "renamed.bin",
  };
  std::set<std::string> actual_entries;
  base::FileEnumerator enumerator(
      workspace, /*recursive=*/true,
      base::FileEnumerator::FILES | base::FileEnumerator::DIRECTORIES,
      base::FilePath::StringType(),
      base::FileEnumerator::FolderSearchPolicy::MATCH_ONLY,
      base::FileEnumerator::ErrorPolicy::STOP_ENUMERATION);
  for (base::FilePath entry = enumerator.Next(); !entry.empty();
       entry = enumerator.Next()) {
    base::FilePath relative;
    Require(workspace.AppendRelativePath(entry, &relative),
            "recursive_enumeration_relative_path");
    std::string key = relative.value();
    if (enumerator.GetInfo().IsDirectory()) {
      key.push_back('/');
    }
    Require(actual_entries.insert(std::move(key)).second,
            "recursive_enumeration_duplicate");
  }
  Require(enumerator.GetError() == base::File::FILE_OK,
          "recursive_enumeration_error");
  Require(actual_entries == expected_entries,
          "recursive_enumeration_set_mismatch");

  const base::FilePath missing_path = workspace.Append("missing.bin");
  Require(!base::PathExists(missing_path), "missing_file_exists");
  base::File missing_file(missing_path,
                          base::File::FLAG_OPEN | base::File::FLAG_READ);
  Require(!missing_file.IsValid() &&
              missing_file.error_details() ==
                  base::File::FILE_ERROR_NOT_FOUND,
          "missing_file_open_error");
  base::File::Info missing_info;
  Require(!base::GetFileInfo(missing_path, &missing_info),
          "missing_file_stat_succeeded");
  Require(base::DeleteFile(missing_path), "missing_file_delete_not_idempotent");

  base::File duplicate_create(empty_path,
                              base::File::FLAG_CREATE |
                                  base::File::FLAG_WRITE);
  Require(!duplicate_create.IsValid() &&
              duplicate_create.error_details() ==
                  base::File::FILE_ERROR_EXISTS,
          "existing_file_create_error");

  const base::FilePath missing_directory =
      workspace.Append("missing-directory");
  base::FileEnumerator missing_enumerator(
      missing_directory, /*recursive=*/true, base::FileEnumerator::FILES,
      base::FilePath::StringType(),
      base::FileEnumerator::FolderSearchPolicy::MATCH_ONLY,
      base::FileEnumerator::ErrorPolicy::STOP_ENUMERATION);
  Require(missing_enumerator.Next().empty() &&
              missing_enumerator.GetError() ==
                  base::File::FILE_ERROR_NOT_FOUND,
          "missing_directory_enumeration_error");

  const base::FilePath parent_reference =
      nested_path.Append(base::FilePath::kParentDirectory)
          .Append("parent-denied.bin");
  Require(parent_reference.ReferencesParent(),
          "parent_reference_not_detected");
  errno = 0;
  base::File parent_denied(parent_reference,
                           base::File::FLAG_CREATE_ALWAYS |
                               base::File::FLAG_WRITE);
  const int parent_error = errno;
  Require(!parent_denied.IsValid() &&
              parent_denied.error_details() ==
                  base::File::FILE_ERROR_ACCESS_DENIED &&
              parent_error == EACCES,
          "parent_reference_not_denied");
  Require(!base::PathExists(workspace.Append("parent-denied.bin")),
          "parent_reference_created_file");

  base::File lock_file(renamed_path, base::File::FLAG_OPEN |
                                         base::File::FLAG_READ |
                                         base::File::FLAG_WRITE);
  Require(lock_file.IsValid(), "lock_file_open");
  Require(lock_file.Lock(base::File::LockMode::kShared) ==
                  base::File::FILE_ERROR_INVALID_OPERATION &&
              lock_file.Lock(base::File::LockMode::kExclusive) ==
                  base::File::FILE_ERROR_INVALID_OPERATION &&
              lock_file.Unlock() ==
                  base::File::FILE_ERROR_INVALID_OPERATION,
          "file_lock_not_explicitly_unsupported");

  const base::PlatformFile closed_descriptor = lock_file.GetPlatformFile();
  Require(closed_descriptor != base::kInvalidPlatformFile,
          "closed_descriptor_invalid_before_close");
  lock_file.Close();
  Require(!lock_file.IsValid(), "file_close_did_not_invalidate");
  base::stat_wrapper_t closed_descriptor_info;
  errno = 0;
  const int closed_descriptor_result =
      base::File::Fstat(closed_descriptor, &closed_descriptor_info);
  const int closed_descriptor_error = errno;
  Require(closed_descriptor_result == -1 &&
              closed_descriptor_error == EBADF,
          "closed_descriptor_not_ebadf");

  Require(base::DeletePathRecursively(workspace),
          "temp_workspace_cleanup_failed");
  Require(!base::PathExists(workspace), "temp_workspace_still_exists");
}

void TestProcessIdentity() {
  BeginPhase("process_identity");

  const base::ProcessId process_id = base::GetCurrentProcId();
  const base::ProcessHandle process_handle = base::GetCurrentProcessHandle();
  Require(process_id != base::kNullProcessId &&
              base::GetCurrentProcId() == process_id,
          "current_process_id");
  Require(process_handle != base::kNullProcessHandle &&
              base::GetCurrentProcessHandle() == process_handle,
          "current_process_handle");
  Require(base::GetProcId(process_handle) == process_id,
          "current_process_handle_id");
  Require(base::GetParentProcessId(process_handle) == base::kNullProcessId,
          "current_process_parent");

  const base::UniqueProcId first_unique_id = base::GetUniqueIdForProcess();
  const base::UniqueProcId second_unique_id = base::GetUniqueIdForProcess();
  Require(first_unique_id == second_unique_id &&
              first_unique_id.GetUnsafeValue() == process_id,
          "unique_process_id");

  base::Process current = base::Process::Current();
  Require(current.IsValid() && current.is_current() &&
              current.Handle() == process_handle && current.Pid() == process_id,
          "process_current");

  base::Process duplicate = current.Duplicate();
  Require(duplicate.IsValid() && duplicate.is_current() &&
              duplicate.Handle() == process_handle &&
              duplicate.Pid() == process_id,
          "process_duplicate");
  const base::ProcessHandle released_handle = duplicate.Release();
  Require(released_handle == process_handle && !duplicate.IsValid() &&
              duplicate.Handle() == base::kNullProcessHandle &&
              duplicate.Pid() == base::kNullProcessId,
          "process_release");

  base::Process released(released_handle);
  Require(released.IsValid() && released.is_current() &&
              released.Pid() == process_id,
          "process_released_handle");
  released.Close();
  Require(!released.IsValid() && !released.is_current() &&
              released.Handle() == base::kNullProcessHandle &&
              released.Pid() == base::kNullProcessId,
          "process_close");
  Require(current.IsValid(), "process_duplicate_close_affected_current");

  base::Process reopened = base::Process::Open(process_id);
  Require(reopened.IsValid() && reopened.is_current() &&
              reopened.Pid() == process_id,
          "process_open_current");
  reopened.Close();

  const base::ProcessId non_current_id =
      process_id == std::numeric_limits<base::ProcessId>::max()
          ? process_id - 1
          : process_id + 1;
  Require(non_current_id != process_id &&
              non_current_id != base::kNullProcessId,
          "non_current_process_id_selection");
  Require(base::GetProcId(non_current_id) == base::kNullProcessId &&
              base::GetParentProcessId(non_current_id) ==
                  static_cast<base::ProcessId>(-1),
          "non_current_process_identity");
  base::Process non_current = base::Process::Open(non_current_id);
  Require(!non_current.IsValid() && !non_current.is_current() &&
              non_current.Pid() == base::kNullProcessId,
          "process_open_non_current");
  Require(!base::Process::OpenWithExtraPrivileges(non_current_id).IsValid(),
          "process_open_non_current_extra_privileges");
  Require(current.CreationTime().is_null(), "process_creation_time_available");
  Require(!base::Process::CanSetPriority() &&
              current.GetPriority() ==
                  base::Process::Priority::kUserBlocking &&
              !current.SetPriority(base::Process::Priority::kBestEffort) &&
              current.GetOSPriority() == -1,
          "process_priority_supported");
  int process_exit_code = 123;
  Require(!current.Terminate(0, false) &&
              !current.WaitForExit(&process_exit_code) &&
              !current.WaitForExitWithTimeout(base::Milliseconds(1),
                                              &process_exit_code) &&
              process_exit_code == 123,
          "process_control_supported");

  const base::CommandLine unsupported_command(base::CommandLine::NO_PROGRAM);
  base::Process launched =
      base::LaunchProcess(unsupported_command, base::LaunchOptions());
  Require(!launched.IsValid() && !launched.is_current() &&
              launched.Pid() == base::kNullProcessId,
          "process_launch_not_explicitly_unsupported");
  std::string process_output = "unexpected";
  Require(!base::GetAppOutput(unsupported_command, &process_output) &&
              process_output.empty(),
          "process_stdout_capture_supported");
  process_output = "unexpected";
  Require(!base::GetAppOutputAndError(unsupported_command, &process_output) &&
              process_output.empty(),
          "process_output_capture_supported");
  process_output = "unexpected";
  process_exit_code = 123;
  Require(!base::GetAppOutputWithExitCode(
              unsupported_command, &process_output, &process_exit_code) &&
              process_output.empty() && process_exit_code == -1,
          "process_exit_capture_supported");

  current.Close();
  Require(!current.IsValid(), "process_current_close");
  Require(base::GetCurrentProcId() == process_id &&
              base::GetCurrentProcessHandle() == process_handle,
          "process_identity_changed_after_close");
}

void TestSysInfo() {
  BeginPhase("sys_info");

  constexpr size_t kWasmPageSize = 65536;
  const int processor_count = base::SysInfo::NumberOfProcessors();
  Require(processor_count >= 1 &&
              base::SysInfo::NumberOfProcessors() == processor_count,
          "sys_info_processor_count");
  Require(base::GetPageSize() == kWasmPageSize,
          "sys_info_page_size");
  Require(base::SysInfo::VMAllocationGranularity() == kWasmPageSize,
          "sys_info_allocation_granularity");

  const size_t heap_size = emscripten_get_heap_size();
  const size_t heap_max = emscripten_get_heap_max();
  Require(heap_size >= kWasmPageSize &&
              heap_size % kWasmPageSize == 0 &&
              heap_max >= heap_size && heap_max % kWasmPageSize == 0,
          "sys_info_wasm_heap");
  Require(base::SysInfo::AmountOfVirtualMemory().InBytes() == heap_max &&
              base::SysInfo::AmountOfVirtualMemory().is_positive(),
          "sys_info_virtual_memory");
  Require(base::SysInfo::AmountOfTotalPhysicalMemory().is_zero() &&
              base::SysInfo::AmountOfAvailablePhysicalMemory().is_zero(),
          "sys_info_physical_memory_claimed_available");

  const base::FilePath memfs_path("/tmp");
  Require(!base::SysInfo::AmountOfFreeDiskSpace(memfs_path).has_value() &&
              !base::SysInfo::AmountOfTotalDiskSpace(memfs_path).has_value() &&
              !base::SysInfo::AmountOfDiskSpace(memfs_path).has_value(),
          "sys_info_disk_space_claimed_available");

  Require(base::SysInfo::OperatingSystemName() == "Emscripten",
          "sys_info_os_name");
  Require(base::SysInfo::OperatingSystemArchitecture() == "wasm32",
          "sys_info_os_architecture");
  Require(base::SysInfo::ProcessCPUArchitecture() == "wasm32",
          "sys_info_process_architecture");
  Require(base::SysInfo::CPUModelName().empty(),
          "sys_info_cpu_model_claimed_available");
  Require(!base::SysInfo::OperatingSystemVersion().empty(),
          "sys_info_os_version");
  int32_t major_version = -1;
  int32_t minor_version = -1;
  int32_t bugfix_version = -1;
  base::SysInfo::OperatingSystemVersionNumbers(
      &major_version, &minor_version, &bugfix_version);
  Require(major_version == __EMSCRIPTEN_MAJOR__ &&
              minor_version == __EMSCRIPTEN_MINOR__ &&
              bugfix_version == __EMSCRIPTEN_TINY__,
          "sys_info_os_version_numbers");

  const double performance_before = emscripten_performance_now();
  const base::TimeDelta uptime = base::SysInfo::Uptime();
  const double performance_after = emscripten_performance_now();
  const double uptime_milliseconds = uptime.InMillisecondsF();
  Require(uptime.is_positive() &&
              uptime_milliseconds + 1.0 >= performance_before &&
              uptime_milliseconds <= performance_after + 1.0 &&
              uptime < base::Days(3650),
          "sys_info_uptime_value");
  base::PlatformThread::Sleep(base::Milliseconds(10));
  const base::TimeDelta later_uptime = base::SysInfo::Uptime();
  Require(later_uptime > uptime &&
              later_uptime - uptime < base::Seconds(2),
          "sys_info_uptime_progress");
}

struct TlsPayload {
  std::atomic<int>* destructor_count;
  int marker;
};

void DestroyTlsPayload(void* value) {
  auto* payload = static_cast<TlsPayload*>(value);
  payload->destructor_count->fetch_add(1, std::memory_order_release);
}

class PlatformBasicsDelegate final
    : public base::PlatformThread::Delegate {
 public:
  PlatformBasicsDelegate(int index,
                         base::PlatformThreadId application_id,
                         base::ThreadLocalStorage::Slot* tls_slot,
                         base::WaitableEvent* release_event,
                         std::atomic<int>* started,
                         std::atomic<int>* handoff_bits,
                         std::atomic<int>* tls_destructor_count)
      : index_(index),
        application_id_(application_id),
        tls_slot_(tls_slot),
        release_event_(release_event),
        started_(started),
        handoff_bits_(handoff_bits),
        name_("m1-worker-" + std::to_string(index)),
        tls_payload_{tls_destructor_count, 0x5100 + index} {}

  void ThreadMain() override {
    bool ok = !emscripten_is_main_browser_thread() &&
              !emscripten_is_main_runtime_thread();

    id_ = base::PlatformThread::CurrentId();
    ok = ok && id_ != base::kInvalidThreadId && id_ != application_id_;

    base::PlatformThread::SetName(name_);
    const char* current_name = base::PlatformThread::GetName();
    ok = ok && current_name && std::strcmp(current_name, name_.c_str()) == 0;

    ok = ok && tls_slot_->Get() == nullptr;
    tls_slot_->Set(&tls_payload_);
    ok = ok && tls_slot_->Get() == &tls_payload_;

    std::array<uint8_t, 257> entropy{};
    base::RandBytes(entropy);
    entropy_ok_.store(HasNonZeroByte(entropy), std::memory_order_release);
    ok = ok && entropy_ok_.load(std::memory_order_acquire);

    const base::TimeTicks sleep_start = base::TimeTicks::Now();
    base::PlatformThread::YieldCurrentThread();
    base::PlatformThread::Sleep(base::Milliseconds(10));
    const base::TimeDelta elapsed = base::TimeTicks::Now() - sleep_start;
    ok = ok && elapsed >= base::Milliseconds(5) &&
         elapsed < base::Seconds(2);
    ok = ok && base::PlatformThread::CurrentId() == id_;
    ok = ok && tls_slot_->Get() == &tls_payload_;

    handoff_bits_->fetch_or(1 << index_, std::memory_order_release);
    started_->fetch_add(1, std::memory_order_release);

    ok = release_event_->TimedWait(kPhaseTimeout) && ok;
    ok = ok && tls_slot_->Get() == &tls_payload_;
    succeeded_.store(ok, std::memory_order_release);
    // Leave the value installed so pthread teardown exercises the Chromium TLS
    // destructor path before PlatformThread::Join() returns.
  }

  base::PlatformThreadId id() const { return id_; }

  bool succeeded() const {
    return succeeded_.load(std::memory_order_acquire);
  }

  bool entropy_ok() const {
    return entropy_ok_.load(std::memory_order_acquire);
  }

 private:
  const int index_;
  const base::PlatformThreadId application_id_;
  base::ThreadLocalStorage::Slot* const tls_slot_;
  base::WaitableEvent* const release_event_;
  std::atomic<int>* const started_;
  std::atomic<int>* const handoff_bits_;
  const std::string name_;
  TlsPayload tls_payload_;
  base::PlatformThreadId id_;
  std::atomic<bool> entropy_ok_{false};
  std::atomic<bool> succeeded_{false};
};

void TestPlatformThreadAndTls() {
  BeginPhase("platform_thread_tls");

  const base::PlatformThreadId application_id =
      base::PlatformThread::CurrentId();
  Require(application_id != base::kInvalidThreadId,
          "application_thread_id_invalid");
  Require(base::PlatformThread::CurrentId() == application_id,
          "application_thread_id_unstable");

  base::PlatformThread::SetName("m1-application");
  const char* application_name = base::PlatformThread::GetName();
  Require(application_name &&
              std::strcmp(application_name, "m1-application") == 0,
          "application_thread_name");

  const base::TimeTicks sleep_start = base::TimeTicks::Now();
  base::PlatformThread::YieldCurrentThread();
  base::PlatformThread::Sleep(base::Milliseconds(20));
  const base::TimeDelta slept = base::TimeTicks::Now() - sleep_start;
  Require(slept >= base::Milliseconds(10) && slept < base::Seconds(2),
          "platform_thread_sleep");

  std::atomic<int> tls_destructor_count{0};
  base::ThreadLocalStorage::Slot tls_slot(&DestroyTlsPayload);
  TlsPayload application_payload{&tls_destructor_count, 0x51A0};
  tls_slot.Set(&application_payload);
  Require(tls_slot.Get() == &application_payload,
          "application_tls_initial_value");

  base::WaitableEvent release_event(
      base::WaitableEvent::ResetPolicy::MANUAL,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<int> started{0};
  std::atomic<int> handoff_bits{0};
  PlatformBasicsDelegate first(0, application_id, &tls_slot, &release_event,
                               &started, &handoff_bits,
                               &tls_destructor_count);
  PlatformBasicsDelegate second(1, application_id, &tls_slot, &release_event,
                                &started, &handoff_bits,
                                &tls_destructor_count);
  std::array<base::PlatformThreadHandle, 2> handles;

  Require(base::PlatformThread::Create(0, &first, &handles[0]),
          "platform_thread_create_first");
  Require(base::PlatformThread::Create(0, &second, &handles[1]),
          "platform_thread_create_second");
  Require(!handles[0].is_null() && !handles[1].is_null(),
          "platform_thread_handle_null");
  Require(!handles[0].is_equal(handles[1]), "platform_thread_handles_equal");
  Require(WaitUntil([&started] {
            return started.load(std::memory_order_acquire) == 2;
          }),
          "platform_workers_start_timeout");
  Require(handoff_bits.load(std::memory_order_acquire) == 0b11,
          "atomic_handoff");
  Require(tls_slot.Get() == &application_payload, "application_tls_isolation");

  release_event.Signal();
  base::PlatformThread::Join(handles[0]);
  base::PlatformThread::Join(handles[1]);

  Require(first.id() != second.id(), "platform_worker_ids_equal");
  Require(first.id() != application_id && second.id() != application_id,
          "platform_worker_id_matches_application");
  Require(first.succeeded() && second.succeeded(),
          "platform_worker_contract");
  Require(first.entropy_ok() && second.entropy_ok(), "worker_secure_entropy");
  Require(tls_destructor_count.load(std::memory_order_acquire) == 2,
          "worker_tls_destructors");
  Require(tls_slot.Get() == &application_payload,
          "application_tls_changed_after_join");
  tls_slot.Set(nullptr);
}

class TryLockDelegate final : public base::PlatformThread::Delegate {
 public:
  explicit TryLockDelegate(base::Lock* lock) : lock_(lock) {}

  void ThreadMain() override {
    started_.store(true, std::memory_order_release);
    const bool acquired = lock_->Try();
    acquired_.store(acquired, std::memory_order_release);
    if (acquired) {
      lock_->Release();
    }
    completed_.store(true, std::memory_order_release);
  }

  bool started() const { return started_.load(std::memory_order_acquire); }
  bool completed() const {
    return completed_.load(std::memory_order_acquire);
  }
  bool acquired() const { return acquired_.load(std::memory_order_acquire); }

 private:
  base::Lock* const lock_;
  std::atomic<bool> started_{false};
  std::atomic<bool> completed_{false};
  std::atomic<bool> acquired_{false};
};

class CounterDelegate final : public base::PlatformThread::Delegate {
 public:
  CounterDelegate(base::Lock* lock,
                  int* counter,
                  std::atomic<int>* started)
      : lock_(lock), counter_(counter), started_(started) {}

  void ThreadMain() override {
    started_->fetch_add(1, std::memory_order_release);
    for (int i = 0; i < kCounterIterations; ++i) {
      {
        base::AutoLock guard(*lock_);
        ++*counter_;
      }
      if ((i & 127) == 0) {
        base::PlatformThread::YieldCurrentThread();
      }
    }
  }

 private:
  base::Lock* const lock_;
  int* const counter_;
  std::atomic<int>* const started_;
};

void TestLock() {
  BeginPhase("lock");

  base::Lock lock;
  lock.Acquire();
  TryLockDelegate try_delegate(&lock);
  base::PlatformThreadHandle try_handle;
  Require(base::PlatformThread::Create(0, &try_delegate, &try_handle),
          "try_lock_thread_create");
  Require(WaitUntil([&try_delegate] { return try_delegate.started(); }),
          "try_lock_thread_start_timeout");
  const bool try_completed_while_held =
      WaitUntil([&try_delegate] { return try_delegate.completed(); },
                base::Milliseconds(250));
  lock.Release();
  Require(WaitUntil([&try_delegate] { return try_delegate.completed(); }),
          "try_lock_thread_completion_timeout");
  base::PlatformThread::Join(try_handle);
  Require(try_completed_while_held, "lock_try_blocked");
  Require(!try_delegate.acquired(), "lock_try_acquired_held_lock");

  if (!lock.Try()) {
    FailImmediately("lock_try_uncontended");
  }
  lock.Release();

  int counter = 0;
  std::atomic<int> started{0};
  CounterDelegate first(&lock, &counter, &started);
  CounterDelegate second(&lock, &counter, &started);
  std::array<base::PlatformThreadHandle, 2> handles;
  Require(base::PlatformThread::Create(0, &first, &handles[0]),
          "lock_counter_create_first");
  Require(base::PlatformThread::Create(0, &second, &handles[1]),
          "lock_counter_create_second");
  Require(WaitUntil([&started] {
            return started.load(std::memory_order_acquire) == 2;
          }),
          "lock_counter_start_timeout");

  for (int i = 0; i < kCounterIterations; ++i) {
    base::AutoLock guard(lock);
    ++counter;
  }
  base::PlatformThread::Join(handles[0]);
  base::PlatformThread::Join(handles[1]);
  Require(counter == 3 * kCounterIterations, "lock_shared_counter");
}

struct ConditionState {
  ConditionState() : condition(&lock) {}

  base::Lock lock;
  base::ConditionVariable condition;
  int permits = 0;
  bool broadcast = false;
  std::atomic<int> entered{0};
  std::atomic<int> signaled{0};
  std::atomic<bool> timed_out{false};
};

class ConditionDelegate final : public base::PlatformThread::Delegate {
 public:
  explicit ConditionDelegate(ConditionState* state) : state_(state) {}

  void ThreadMain() override {
    const base::TimeTicks deadline = base::TimeTicks::Now() + kPhaseTimeout;
    base::AutoLock guard(state_->lock);
    state_->entered.fetch_add(1, std::memory_order_release);

    while (state_->permits == 0 && !state_->broadcast) {
      const base::TimeDelta remaining = deadline - base::TimeTicks::Now();
      if (!remaining.is_positive()) {
        state_->timed_out.store(true, std::memory_order_release);
        return;
      }
      state_->condition.TimedWait(remaining);
    }

    if (state_->permits > 0) {
      --state_->permits;
      state_->signaled.fetch_add(1, std::memory_order_release);
    }

    while (!state_->broadcast) {
      const base::TimeDelta remaining = deadline - base::TimeTicks::Now();
      if (!remaining.is_positive()) {
        state_->timed_out.store(true, std::memory_order_release);
        return;
      }
      state_->condition.TimedWait(remaining);
    }
  }

 private:
  ConditionState* const state_;
};

void TestConditionVariable() {
  BeginPhase("condition_variable");

  ConditionState state;
  ConditionDelegate first(&state);
  ConditionDelegate second(&state);
  std::array<base::PlatformThreadHandle, 2> handles;
  Require(base::PlatformThread::Create(0, &first, &handles[0]),
          "condition_create_first");
  Require(base::PlatformThread::Create(0, &second, &handles[1]),
          "condition_create_second");
  Require(WaitUntil([&state] {
            return state.entered.load(std::memory_order_acquire) == 2;
          }),
          "condition_workers_start_timeout");

  {
    base::AutoLock guard(state.lock);
    state.permits = 1;
    state.condition.Signal();
  }
  Require(WaitUntil([&state] {
            return state.signaled.load(std::memory_order_acquire) == 1;
          }),
          "condition_signal_timeout");
  base::PlatformThread::Sleep(base::Milliseconds(25));
  Require(state.signaled.load(std::memory_order_acquire) == 1,
          "condition_signal_woke_multiple");

  {
    base::AutoLock guard(state.lock);
    state.broadcast = true;
    state.condition.Broadcast();
  }
  base::PlatformThread::Join(handles[0]);
  base::PlatformThread::Join(handles[1]);
  Require(!state.timed_out.load(std::memory_order_acquire),
          "condition_worker_timed_out");

  base::Lock timeout_lock;
  base::ConditionVariable timeout_condition(&timeout_lock);
  const base::TimeTicks timeout_start = base::TimeTicks::Now();
  const base::TimeTicks timeout_deadline =
      timeout_start + base::Milliseconds(60);
  {
    base::AutoLock guard(timeout_lock);
    while (base::TimeTicks::Now() < timeout_deadline) {
      timeout_condition.TimedWait(timeout_deadline -
                                  base::TimeTicks::Now());
    }
  }
  const base::TimeDelta elapsed = base::TimeTicks::Now() - timeout_start;
  Require(elapsed >= base::Milliseconds(45) && elapsed < base::Seconds(2),
          "condition_timeout_elapsed");
}

class EventWaitDelegate final : public base::PlatformThread::Delegate {
 public:
  EventWaitDelegate(base::WaitableEvent* event,
                    std::atomic<int>* started,
                    std::atomic<int>* released)
      : event_(event), started_(started), released_(released) {}

  void ThreadMain() override {
    started_->fetch_add(1, std::memory_order_release);
    const bool result = event_->TimedWait(kPhaseTimeout);
    result_.store(result, std::memory_order_release);
    if (result) {
      released_->fetch_add(1, std::memory_order_release);
    }
  }

  bool result() const { return result_.load(std::memory_order_acquire); }

 private:
  base::WaitableEvent* const event_;
  std::atomic<int>* const started_;
  std::atomic<int>* const released_;
  std::atomic<bool> result_{false};
};

class DelayedSignalDelegate final : public base::PlatformThread::Delegate {
 public:
  explicit DelayedSignalDelegate(base::WaitableEvent* event) : event_(event) {}

  void ThreadMain() override {
    started_.store(true, std::memory_order_release);
    base::PlatformThread::Sleep(base::Milliseconds(40));
    event_->Signal();
  }

  bool started() const { return started_.load(std::memory_order_acquire); }

 private:
  base::WaitableEvent* const event_;
  std::atomic<bool> started_{false};
};

void TestWaitableEvent() {
  BeginPhase("waitable_event");

  {
    base::WaitableEvent initially_signaled(
        base::WaitableEvent::ResetPolicy::MANUAL,
        base::WaitableEvent::InitialState::SIGNALED);
    Require(initially_signaled.IsSignaled(),
            "manual_initial_signal_missing");
    initially_signaled.Wait();
    Require(initially_signaled.IsSignaled(),
            "manual_initial_signal_consumed");
    initially_signaled.Reset();
    Require(!initially_signaled.IsSignaled(), "manual_reset_failed");
  }

  {
    base::WaitableEvent event(
        base::WaitableEvent::ResetPolicy::MANUAL,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    std::atomic<int> started{0};
    std::atomic<int> released{0};
    EventWaitDelegate first(&event, &started, &released);
    EventWaitDelegate second(&event, &started, &released);
    std::array<base::PlatformThreadHandle, 2> handles;
    Require(base::PlatformThread::Create(0, &first, &handles[0]),
            "manual_event_create_first");
    Require(base::PlatformThread::Create(0, &second, &handles[1]),
            "manual_event_create_second");
    Require(WaitUntil([&started] {
              return started.load(std::memory_order_acquire) == 2;
            }),
            "manual_event_workers_start_timeout");
    event.Signal();
    Require(WaitUntil([&released] {
              return released.load(std::memory_order_acquire) == 2;
            }),
            "manual_event_release_timeout");
    base::PlatformThread::Join(handles[0]);
    base::PlatformThread::Join(handles[1]);
    Require(first.result() && second.result(), "manual_event_wait_result");
    Require(event.IsSignaled(), "manual_event_not_sticky");
    event.Reset();
    Require(!event.IsSignaled(), "manual_event_reset");
  }

  {
    base::WaitableEvent initially_signaled(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::SIGNALED);
    Require(initially_signaled.IsSignaled(),
            "auto_initial_signal_missing");
    Require(!initially_signaled.IsSignaled(),
            "auto_initial_signal_not_consumed");
  }

  {
    base::WaitableEvent event(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    std::atomic<int> started{0};
    std::atomic<int> released{0};
    EventWaitDelegate first(&event, &started, &released);
    EventWaitDelegate second(&event, &started, &released);
    std::array<base::PlatformThreadHandle, 2> handles;
    Require(base::PlatformThread::Create(0, &first, &handles[0]),
            "auto_event_create_first");
    Require(base::PlatformThread::Create(0, &second, &handles[1]),
            "auto_event_create_second");
    Require(WaitUntil([&started] {
              return started.load(std::memory_order_acquire) == 2;
            }),
            "auto_event_workers_start_timeout");

    event.Signal();
    Require(WaitUntil([&released] {
              return released.load(std::memory_order_acquire) >= 1;
            }),
            "auto_event_first_release_timeout");
    base::PlatformThread::Sleep(base::Milliseconds(25));
    Require(released.load(std::memory_order_acquire) == 1,
            "auto_event_single_signal_released_multiple");
    event.Signal();
    Require(WaitUntil([&released] {
              return released.load(std::memory_order_acquire) == 2;
            }),
            "auto_event_second_release_timeout");
    base::PlatformThread::Join(handles[0]);
    base::PlatformThread::Join(handles[1]);
    Require(first.result() && second.result(), "auto_event_wait_result");
    Require(!event.IsSignaled(), "auto_event_signal_not_consumed");
  }

  {
    base::WaitableEvent timeout_event(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    Require(!timeout_event.TimedWait(base::TimeDelta()),
            "event_zero_timeout");
    Require(!timeout_event.TimedWait(base::Milliseconds(-1)),
            "event_negative_timeout");
    const base::TimeTicks start = base::TimeTicks::Now();
    Require(!timeout_event.TimedWait(base::Milliseconds(60)),
            "event_timeout_reported_signal");
    const base::TimeDelta elapsed = base::TimeTicks::Now() - start;
    Require(elapsed >= base::Milliseconds(45) &&
                elapsed < base::Seconds(2),
            "event_timeout_elapsed");
  }

  {
    base::WaitableEvent first(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::SIGNALED);
    base::WaitableEvent second(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::SIGNALED);
    std::array<base::WaitableEvent*, 2> waitables{&first, &second};
    Require(base::WaitableEvent::WaitMany(base::span(waitables)) == 0,
            "event_wait_many_lowest_index");
    Require(!first.IsSignaled(), "event_wait_many_did_not_consume_winner");
    Require(second.IsSignaled(), "event_wait_many_consumed_non_winner");
  }

  {
    base::WaitableEvent first(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    base::WaitableEvent second(
        base::WaitableEvent::ResetPolicy::AUTOMATIC,
        base::WaitableEvent::InitialState::NOT_SIGNALED);
    DelayedSignalDelegate delegate(&second);
    base::PlatformThreadHandle handle;
    Require(base::PlatformThread::Create(0, &delegate, &handle),
            "event_wait_many_create");
    Require(WaitUntil([&delegate] { return delegate.started(); }),
            "event_wait_many_worker_start_timeout");
    std::array<base::WaitableEvent*, 2> waitables{&first, &second};
    const base::TimeTicks start = base::TimeTicks::Now();
    Require(base::WaitableEvent::WaitMany(base::span(waitables)) == 1,
            "event_wait_many_blocking_index");
    const base::TimeDelta elapsed = base::TimeTicks::Now() - start;
    Require(elapsed >= base::Milliseconds(20) &&
                elapsed < base::Seconds(2),
            "event_wait_many_blocking_elapsed");
    base::PlatformThread::Join(handle);
  }
}

class HandshakeDelegate final : public base::PlatformThread::Delegate {
 public:
  HandshakeDelegate(base::WaitableEvent* worker_to_application,
                    base::WaitableEvent* application_to_worker,
                    std::atomic<int>* payload)
      : worker_to_application_(worker_to_application),
        application_to_worker_(application_to_worker),
        payload_(payload) {}

  void ThreadMain() override {
    bool ok = !emscripten_is_main_browser_thread() &&
              !emscripten_is_main_runtime_thread();
    worker_to_application_->Signal();
    ok = application_to_worker_->TimedWait(kPhaseTimeout) && ok;
    const int request = payload_->load(std::memory_order_acquire);
    ok = ok && request == 0x51A1;
    payload_->store(request + 1, std::memory_order_release);
    succeeded_.store(ok, std::memory_order_release);
    worker_to_application_->Signal();
  }

  bool succeeded() const {
    return succeeded_.load(std::memory_order_acquire);
  }

 private:
  base::WaitableEvent* const worker_to_application_;
  base::WaitableEvent* const application_to_worker_;
  std::atomic<int>* const payload_;
  std::atomic<bool> succeeded_{false};
};

void TestBidirectionalHandshake() {
  BeginPhase("bidirectional_handshake");

  base::WaitableEvent worker_to_application(
      base::WaitableEvent::ResetPolicy::AUTOMATIC,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  base::WaitableEvent application_to_worker(
      base::WaitableEvent::ResetPolicy::AUTOMATIC,
      base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::atomic<int> payload{0};
  HandshakeDelegate delegate(&worker_to_application, &application_to_worker,
                             &payload);
  base::PlatformThreadHandle handle;
  Require(base::PlatformThread::Create(0, &delegate, &handle),
          "handshake_thread_create");
  Require(worker_to_application.TimedWait(kPhaseTimeout),
          "worker_to_application_timeout");
  payload.store(0x51A1, std::memory_order_release);
  application_to_worker.Signal();
  Require(worker_to_application.TimedWait(kPhaseTimeout),
          "worker_reply_timeout");
  base::PlatformThread::Join(handle);
  Require(delegate.succeeded(), "bidirectional_worker_contract");
  Require(payload.load(std::memory_order_acquire) == 0x51A2,
          "bidirectional_payload");
}

}  // namespace

int main() {
  if (emscripten_is_main_browser_thread()) {
    return Fail("application_main_on_browser_thread");
  }
  if (emscripten_is_main_runtime_thread()) {
    return Fail("application_main_on_runtime_thread");
  }
  if (!emscripten_has_threading_support()) {
    return Fail("pthread_support_unavailable");
  }

  std::fprintf(stdout, "%s:RUNTIME_START\n", kPrefix);
  std::fflush(stdout);

  const base::Time wall_start = base::Time::Now();
  if (wall_start.InMillisecondsSinceUnixEpoch() < 1577836800000LL) {
    return Fail("wall_clock_not_plausible");
  }

  base::TimeTicks previous = base::TimeTicks::Now();
  for (int i = 0; i < 1000; ++i) {
    const base::TimeTicks current = base::TimeTicks::Now();
    if (current < previous) {
      return Fail("monotonic_clock_went_backwards");
    }
    previous = current;
  }

  const base::TimeTicks sleep_start = base::TimeTicks::Now();
  base::PlatformThread::Sleep(base::Milliseconds(250));
  const base::TimeDelta slept = base::TimeTicks::Now() - sleep_start;
  if (slept < base::Milliseconds(200) || slept > base::Seconds(5)) {
    return Fail("bounded_sleep_elapsed");
  }
  if (base::Time::Now() <= wall_start) {
    return Fail("wall_clock_did_not_progress");
  }
  if (!base::TimeTicks::IsHighResolution() ||
      !base::TimeTicks::IsConsistentAcrossProcesses() ||
      base::TimeTicks::GetClock() !=
          base::TimeTicks::Clock::WASM_EMSCRIPTEN_GET_NOW) {
    return Fail("monotonic_clock_metadata");
  }
  if (base::ThreadTicks::IsSupported()) {
    return Fail("thread_cpu_clock_claimed_supported");
  }

  std::array<uint8_t, 513> first{};
  std::array<uint8_t, 513> second{};
  base::RandBytes(first);
  base::RandBytes(second);
  if (!HasNonZeroByte(first) || !HasNonZeroByte(second)) {
    return Fail("secure_entropy_all_zero");
  }
  if (first == second) {
    return Fail("secure_entropy_buffers_equal");
  }

  TestPlatformThreadAndTls();
  TestLock();
  TestConditionVariable();
  TestWaitableEvent();
  TestBidirectionalHandshake();
  TestPathsAndFiles();
  TestProcessIdentity();
  TestSysInfo();

  std::fprintf(stdout, "%s:RUNTIME_END\n", kPrefix);
  std::fprintf(
      stdout,
      "%s:RESULT wall_time=ok monotonic_time=ok bounded_sleep=ok "
      "secure_entropy=ok worker_entropy=ok platform_thread=ok "
      "thread_ids=ok thread_names=diagnostic_ok yield_sleep=ok "
      "atomic_handoff=ok tls=ok tls_destructors=ok lock=ok lock_try=ok "
      "condition_signal=ok condition_broadcast=ok condition_timeout=ok "
      "event_manual=ok event_auto=ok event_reset=ok event_timeout=ok "
      "event_wait_many=ok bidirectional=ok joins=ok path_current=ok "
      "path_temp=ok path_home=ok path_executable=unsupported "
      "path_module=unsupported temp_workspace=ok file_empty=ok "
      "filesystem=memfs file_binary_nul=ok file_seek=ok "
      "file_middle_overwrite=ok file_append=ok file_truncate=ok "
      "file_zero_fill=ok file_flush=memfs_only file_reopen=ok "
      "file_rename_stat=ok "
      "directories=ok enumeration=ok file_errors=ok "
      "parent_traversal=denied file_lock=invalid_operation "
      "closed_fd=ebadf cleanup=ok process_identity=ok "
      "process_handle=ok unique_proc_id=ok process_current=ok "
      "process_duplicate=ok process_release_close=ok "
      "process_open_noncurrent=invalid process_control=unsupported "
      "process_launch=unsupported process_output=unsupported "
      "sysinfo_processors=ok page_size=65536 "
      "allocation_granularity=65536 wasm_heap=current_ok "
      "virtual_memory=wasm_max physical_memory=unavailable "
      "disk_space=unavailable os_name=emscripten os_arch=wasm32 "
      "cpu_arch=wasm32 cpu_model=unavailable uptime=runtime_clock "
      "browser_main_free=ok\n",
      kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <emscripten/emscripten.h>
#include <emscripten/threading.h>
#include <emscripten/wasmfs.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m7_wasmfs_opfs_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M7_OPFS";
constexpr char kWritePhase[] = "write";
constexpr char kVerifyPhase[] = "verify";
constexpr char kRecoveryPrecommitPhase[] = "recovery-precommit";
constexpr char kRecoveryPrecommitVerifyPhase[] =
    "recovery-precommit-verify";
constexpr char kRecoveryPostcommitPhase[] = "recovery-postcommit";
constexpr char kRecoveryPostcommitVerifyPhase[] =
    "recovery-postcommit-verify";
constexpr char kRecoveryInterruptionReadyPrefix[] =
    "CHROMIUM_WASM_M7_OPFS:RECOVERY_INTERRUPTION_READY";
constexpr char kRecoveryVerifyStartedPrefix[] =
    "CHROMIUM_WASM_M7_OPFS:RECOVERY_VERIFY_STARTED";
constexpr char kRecoveryReadyPrefix[] =
    "CHROMIUM_WASM_M7_OPFS:RECOVERY_READY";
constexpr char kRecoveryPrecommitBoundary[] =
    "after_tmp_fdatasync_before_rename";
constexpr char kRecoveryPostcommitBoundary[] =
    "after_completed_rename_return";
constexpr char kPhasePrefix[] = "--m7-opfs-phase=";
constexpr char kRunPrefix[] = "--m7-opfs-run=";
constexpr size_t kMinimumRunIdLength = 12;
constexpr size_t kMaximumRunIdLength = 80;
constexpr int kSchemaVersion = 1;

constexpr std::array<uint8_t, 13> kInitialData{
    0x11, 0x22, 0x00, 0x44, 0x55, 0x66, 0x77,
    0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd,
};
constexpr std::array<uint8_t, 3> kPatchData{0xa0, 0x00, 0xb0};
constexpr std::array<uint8_t, 7> kSchemaData{
    'M', '7', 'O', 'P', 'F', 'S', static_cast<uint8_t>(kSchemaVersion),
};
constexpr std::array<uint8_t, 8> kCommitGenerationAData{
    0x73, 0x74, 0x61, 0x74, 0x65, 0x00, 0x41, 0x0a,
};
constexpr std::array<uint8_t, 8> kCommitGenerationBData{
    0x73, 0x74, 0x61, 0x74, 0x65, 0x00, 0x42, 0x0a,
};
constexpr std::array<uint8_t, 5> kNestedData{
    0x6e, 0x65, 0x73, 0x74, 0x00,
};
constexpr std::array<uint8_t, 4> kDeletedData{
    0xde,
    0xad,
    0xbe,
    0xef,
};

struct Arguments {
  std::string phase;
  std::string run_id;
};

struct FixturePaths {
  std::string root;
  std::string tree;
  std::string nested;
  std::string empty;
  std::string data;
  std::string schema;
  std::string temporary_commit;
  std::string commit;
  std::string nested_child;
  std::string deleted;
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

void PrintPhase(const char* name) {
  std::fprintf(stdout, "%s:PHASE name=%s status=ok\n", kPrefix, name);
  std::fflush(stdout);
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
  return std::all_of(run_id.begin(), run_id.end(), [](unsigned char value) {
    return std::isalnum(value) || value == '-' || value == '_';
  });
}

bool IsKnownPhase(std::string_view phase) {
  return phase == kWritePhase || phase == kVerifyPhase ||
         phase == kRecoveryPrecommitPhase ||
         phase == kRecoveryPrecommitVerifyPhase ||
         phase == kRecoveryPostcommitPhase ||
         phase == kRecoveryPostcommitVerifyPhase;
}

bool IsRecoveryInterruptionPhase(std::string_view phase) {
  return phase == kRecoveryPrecommitPhase || phase == kRecoveryPostcommitPhase;
}

const char* ParseArguments(int argc, char* argv[], Arguments* arguments) {
  bool saw_phase = false;
  bool saw_run_id = false;
  for (int index = 1; index < argc; ++index) {
    const std::string_view argument(argv[index]);
    if (HasPrefix(argument, kPhasePrefix)) {
      if (saw_phase) {
        return "duplicate_phase";
      }
      saw_phase = true;
      arguments->phase = argument.substr(std::strlen(kPhasePrefix));
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

  if (!saw_phase || !saw_run_id) {
    return "missing_phase_or_run_id";
  }
  if (!IsKnownPhase(arguments->phase)) {
    return "invalid_phase";
  }
  if (!IsValidRunId(arguments->run_id)) {
    return "invalid_run_id";
  }
  return nullptr;
}

FixturePaths MakeFixturePaths(const std::string& run_id) {
  FixturePaths paths;
  paths.root = "/opfs/" + run_id;
  paths.tree = paths.root + "/tree";
  paths.nested = paths.tree + "/nested";
  paths.empty = paths.tree + "/empty";
  paths.data = paths.tree + "/data.bin";
  paths.schema = paths.tree + "/schema.bin";
  paths.temporary_commit = paths.tree + "/commit.tmp";
  paths.commit = paths.tree + "/commit.bin";
  paths.nested_child = paths.nested + "/child.bin";
  paths.deleted = paths.tree + "/deleted.bin";
  return paths;
}

void MountOpfs(const char* mount_point) {
  backend_t backend = wasmfs_create_opfs_backend();
  Require(backend != nullptr, "opfs_backend_create");
  Require(wasmfs_create_directory(mount_point, 0700, backend) == 0,
          "opfs_mount");
}

void RequireDirectoryCreate(const std::string& path, const char* reason) {
  Require(mkdir(path.c_str(), 0700) == 0, reason);
}

bool IsMissing(const std::string& path) {
  struct stat info = {};
  errno = 0;
  return stat(path.c_str(), &info) == -1 && errno == ENOENT;
}

void RequireExactWrite(int descriptor,
                       const uint8_t* bytes,
                       size_t length,
                       const char* reason) {
  Require(write(descriptor, bytes, length) == static_cast<ssize_t>(length),
          reason);
}

void RequireExactPwrite(int descriptor,
                        const uint8_t* bytes,
                        size_t length,
                        off_t offset,
                        const char* reason) {
  Require(pwrite(descriptor, bytes, length, offset) ==
              static_cast<ssize_t>(length),
          reason);
}

void RequireExactRead(int descriptor,
                      const uint8_t* expected,
                      size_t length,
                      const char* reason) {
  std::vector<uint8_t> actual(length, 0);
  Require(read(descriptor, actual.data(), actual.size()) ==
              static_cast<ssize_t>(length),
          reason);
  Require(std::memcmp(actual.data(), expected, length) == 0, reason);
}

void RequireExactPread(int descriptor,
                       const uint8_t* expected,
                       size_t length,
                       off_t offset,
                       const char* reason) {
  std::vector<uint8_t> actual(length, 0);
  Require(pread(descriptor, actual.data(), actual.size(), offset) ==
              static_cast<ssize_t>(length),
          reason);
  Require(std::memcmp(actual.data(), expected, length) == 0, reason);
}

template <size_t N>
void WriteDurableNewFile(const std::string& path,
                         const std::array<uint8_t, N>& contents,
                         const char* create_reason,
                         const char* write_reason,
                         const char* sync_reason,
                         const char* close_reason) {
  const int descriptor =
      open(path.c_str(), O_CREAT | O_EXCL | O_WRONLY, /*mode=*/0600);
  Require(descriptor >= 0, create_reason);
  RequireExactWrite(descriptor, contents.data(), contents.size(), write_reason);
  Require(fdatasync(descriptor) == 0, sync_reason);
  Require(close(descriptor) == 0, close_reason);
}

template <size_t N>
void VerifyExactFile(const std::string& path,
                     const std::array<uint8_t, N>& expected,
                     const char* open_reason,
                     const char* stat_reason,
                     const char* read_reason,
                     const char* close_reason) {
  const int descriptor = open(path.c_str(), O_RDONLY);
  Require(descriptor >= 0, open_reason);
  struct stat info = {};
  Require(fstat(descriptor, &info) == 0 &&
              info.st_size == static_cast<off_t>(expected.size()),
          stat_reason);
  RequireExactRead(descriptor, expected.data(), expected.size(), read_reason);
  RequireExactPread(descriptor, expected.data(), expected.size(), 0,
                    read_reason);
  Require(close(descriptor) == 0, close_reason);
}

std::array<uint8_t, 16> ExpectedData() {
  std::array<uint8_t, 16> expected{};
  std::copy(kInitialData.begin(), kInitialData.begin() + 9, expected.begin());
  std::copy(kPatchData.begin(), kPatchData.end(), expected.begin() + 3);
  return expected;
}

std::set<std::string> ReadDirectoryNames(const std::string& path,
                                         const char* open_reason,
                                         const char* read_reason,
                                         const char* close_reason) {
  DIR* directory = opendir(path.c_str());
  Require(directory != nullptr, open_reason);

  std::set<std::string> names;
  errno = 0;
  while (dirent* entry = readdir(directory)) {
    if (std::strcmp(entry->d_name, ".") != 0 &&
        std::strcmp(entry->d_name, "..") != 0) {
      Require(names.insert(entry->d_name).second, read_reason);
    }
  }
  Require(errno == 0, read_reason);
  Require(closedir(directory) == 0, close_reason);
  return names;
}

void RequireDirectoryNames(const std::string& path,
                           std::set<std::string> expected,
                           const char* open_reason,
                           const char* read_reason,
                           const char* close_reason) {
  Require(ReadDirectoryNames(path, open_reason, read_reason, close_reason) ==
              std::move(expected),
          read_reason);
}

void VerifyMetadata(const std::string& path, off_t expected_size,
                    const char* reason) {
  struct stat info = {};
  Require(stat(path.c_str(), &info) == 0 && S_ISREG(info.st_mode) &&
              info.st_size == expected_size,
          reason);
}

void TestSameInstanceWriteOpenCoalescing(const FixturePaths& paths) {
  // WasmFS caches one OPFSFile/OpenState per in-process path identity. A second
  // writable open therefore joins the first SyncAccessHandle; it is not a
  // lock-acquisition test and must not be treated as proof of SQLite/LevelDB
  // locking. A real cross-module contention test belongs in a later host gate.
  const int first = open(paths.data.c_str(), O_RDWR);
  Require(first >= 0, "same_instance_first_write_open");
  const int second = open(paths.data.c_str(), O_RDWR);
  Require(second >= 0, "same_instance_write_open_not_coalesced");
  Require(close(second) == 0, "same_instance_second_close");
  Require(close(first) == 0, "same_instance_first_close");
}

void RunWritePhase(const FixturePaths& paths) {
  PrintPhase("fixture_create");
  Require(IsMissing(paths.root), "fixture_preexisting");
  RequireDirectoryCreate(paths.root, "fixture_root_create");
  RequireDirectoryCreate(paths.tree, "fixture_tree_create");
  RequireDirectoryCreate(paths.nested, "fixture_nested_create");
  RequireDirectoryCreate(paths.empty, "fixture_empty_create");

  PrintPhase("random_access_truncate_sync");
  const int descriptor =
      open(paths.data.c_str(), O_CREAT | O_EXCL | O_RDWR, /*mode=*/0600);
  Require(descriptor >= 0, "data_create");
  RequireExactWrite(descriptor, kInitialData.data(), kInitialData.size(),
                    "data_initial_write");
  RequireExactPwrite(descriptor, kPatchData.data(), kPatchData.size(), 3,
                     "data_patch_pwrite");
  Require(ftruncate(descriptor, 9) == 0, "data_truncate_shrink");
  Require(ftruncate(descriptor, 16) == 0, "data_truncate_grow");
  const std::array<uint8_t, 16> expected_data = ExpectedData();
  RequireExactPread(descriptor, expected_data.data(), expected_data.size(), 0,
                    "data_pread_after_truncate");
  struct stat info = {};
  Require(fstat(descriptor, &info) == 0 && info.st_size == 16,
          "data_fstat_after_truncate");
  Require(fdatasync(descriptor) == 0, "data_fdatasync");
  Require(close(descriptor) == 0, "data_close_after_sync");
  VerifyExactFile(paths.data, expected_data, "data_reopen", "data_reopen_stat",
                  "data_reopen_pread", "data_reopen_close");
  VerifyMetadata(paths.data, 16, "data_closed_stat");

  PrintPhase("temp_rename_and_tree");
  WriteDurableNewFile(paths.schema, kSchemaData, "schema_create",
                      "schema_write", "schema_fdatasync", "schema_close");
  WriteDurableNewFile(paths.commit, kCommitGenerationAData,
                      "commit_generation_a_create", "commit_generation_a_write",
                      "commit_generation_a_fdatasync",
                      "commit_generation_a_close");
  VerifyExactFile(paths.commit, kCommitGenerationAData,
                  "commit_generation_a_reopen", "commit_generation_a_stat",
                  "commit_generation_a_read", "commit_generation_a_reopen_close");
  WriteDurableNewFile(paths.temporary_commit, kCommitGenerationBData,
                      "commit_generation_b_create", "commit_generation_b_write",
                      "commit_generation_b_fdatasync",
                      "commit_generation_b_close");
  Require(rename(paths.temporary_commit.c_str(), paths.commit.c_str()) == 0,
          "temp_to_existing_final_rename");
  Require(IsMissing(paths.temporary_commit), "temp_present_after_rename");
  // This observes a completed replacement only. The isolated smoke has no
  // pending-move interruption hook, so it deliberately does not claim atomic
  // crash recovery semantics.
  VerifyExactFile(paths.commit, kCommitGenerationBData,
                  "rename_replace_final_open", "rename_replace_final_stat",
                  "rename_replace_final_read", "rename_replace_final_close");
  WriteDurableNewFile(paths.nested_child, kNestedData, "nested_create",
                      "nested_write", "nested_fdatasync", "nested_close");
  WriteDurableNewFile(paths.deleted, kDeletedData, "delete_create",
                      "delete_write", "delete_fdatasync", "delete_close");
  Require(unlink(paths.deleted.c_str()) == 0, "delete_file");
  Require(IsMissing(paths.deleted), "deleted_file_present");
  RequireDirectoryNames(paths.root, {"tree"}, "root_enumerate_open",
                        "root_enumerate", "root_enumerate_close");
  RequireDirectoryNames(paths.tree,
                        {"commit.bin", "data.bin", "empty", "nested",
                         "schema.bin"},
                        "tree_enumerate_open", "tree_enumerate",
                        "tree_enumerate_close");
  RequireDirectoryNames(paths.nested, {"child.bin"}, "nested_enumerate_open",
                        "nested_enumerate", "nested_enumerate_close");
  RequireDirectoryNames(paths.empty, {}, "empty_enumerate_open",
                        "empty_enumerate", "empty_enumerate_close");

  PrintPhase("same_instance_open_semantics");
  TestSameInstanceWriteOpenCoalescing(paths);

  std::fprintf(stdout,
               "%s:WRITE_READY schema=%d random_access=ok truncate=ok "
               "fdatasync=ok reopen=ok metadata=ok directories=ok "
               "temp_rename=ok rename_replace=ok atomic_recovery=not_claimed "
               "delete=ok same_instance_open=coalesced "
               "lock_proof=not_claimed\n",
               kPrefix, kSchemaVersion);
  std::fflush(stdout);
}

void RemoveFile(const std::string& path, const char* reason) {
  Require(unlink(path.c_str()) == 0, reason);
}

void RemoveDirectory(const std::string& path, const char* reason) {
  Require(rmdir(path.c_str()) == 0, reason);
}

void CreateRecoveryFixture(const FixturePaths& paths) {
  PrintPhase("recovery_fixture_create");
  Require(IsMissing(paths.root), "recovery_fixture_preexisting");
  RequireDirectoryCreate(paths.root, "recovery_root_create");
  RequireDirectoryCreate(paths.tree, "recovery_tree_create");
  WriteDurableNewFile(paths.commit, kCommitGenerationAData,
                      "recovery_generation_a_create",
                      "recovery_generation_a_write",
                      "recovery_generation_a_fdatasync",
                      "recovery_generation_a_close");
  WriteDurableNewFile(paths.temporary_commit, kCommitGenerationBData,
                      "recovery_generation_b_create",
                      "recovery_generation_b_write",
                      "recovery_generation_b_fdatasync",
                      "recovery_generation_b_close");
  VerifyExactFile(paths.commit, kCommitGenerationAData,
                  "recovery_generation_a_reopen",
                  "recovery_generation_a_reopen_stat",
                  "recovery_generation_a_reopen_read",
                  "recovery_generation_a_reopen_close");
  VerifyExactFile(paths.temporary_commit, kCommitGenerationBData,
                  "recovery_generation_b_reopen",
                  "recovery_generation_b_reopen_stat",
                  "recovery_generation_b_reopen_read",
                  "recovery_generation_b_reopen_close");
  RequireDirectoryNames(paths.tree, {"commit.bin", "commit.tmp"},
                        "recovery_fixture_tree_open",
                        "recovery_fixture_tree_entries",
                        "recovery_fixture_tree_close");
}

void PrintRecoveryInterruptionReady(const char* phase, const char* boundary) {
  std::fprintf(stdout,
               "%s phase=%s boundary=%s "
               "atomic_recovery=not_claimed database_recovery=not_claimed\n",
               kRecoveryInterruptionReadyPrefix, phase, boundary);
  std::fflush(stdout);
}

void RunRecoveryPrecommitPhase(const FixturePaths& paths) {
  // This is an application-visible cut point, not a hook inside OPFS move().
  // The fresh document must retain the known-good generation and discard the
  // independently durable temporary generation.
  CreateRecoveryFixture(paths);
  PrintPhase("recovery_precommit_interruption_boundary");
  PrintRecoveryInterruptionReady(kRecoveryPrecommitPhase,
                                 kRecoveryPrecommitBoundary);
}

void RunRecoveryPostcommitPhase(const FixturePaths& paths) {
  // This cut point occurs only after the complete WasmFS rename call has
  // returned. It does not observe or claim behavior during the browser-owned
  // FileSystemFileHandle.move() implementation.
  CreateRecoveryFixture(paths);
  Require(rename(paths.temporary_commit.c_str(), paths.commit.c_str()) == 0,
          "recovery_postcommit_rename");
  Require(IsMissing(paths.temporary_commit),
          "recovery_postcommit_temp_present_after_rename");
  VerifyExactFile(paths.commit, kCommitGenerationBData,
                  "recovery_postcommit_generation_b_open",
                  "recovery_postcommit_generation_b_stat",
                  "recovery_postcommit_generation_b_read",
                  "recovery_postcommit_generation_b_close");
  RequireDirectoryNames(paths.tree, {"commit.bin"},
                        "recovery_postcommit_tree_open",
                        "recovery_postcommit_tree_entries",
                        "recovery_postcommit_tree_close");
  PrintPhase("recovery_postcommit_interruption_boundary");
  PrintRecoveryInterruptionReady(kRecoveryPostcommitPhase,
                                 kRecoveryPostcommitBoundary);
}

void PrintRecoveryVerifyStarted(const char* phase, const char* boundary) {
  std::fprintf(stdout, "%s phase=%s boundary=%s\n",
               kRecoveryVerifyStartedPrefix, phase, boundary);
  std::fflush(stdout);
}

void CleanupRecoveryFixture(const FixturePaths& paths, const char* prefix) {
  RemoveFile(paths.commit, prefix);
  RemoveDirectory(paths.tree, "recovery_cleanup_tree");
  RemoveDirectory(paths.root, "recovery_cleanup_root");
  Require(IsMissing(paths.root), "recovery_cleanup_root_present");
}

void RunRecoveryPrecommitVerifyPhase(const FixturePaths& paths) {
  PrintRecoveryVerifyStarted(kRecoveryPrecommitVerifyPhase,
                             kRecoveryPrecommitBoundary);
  PrintPhase("recovery_precommit_fresh_instance_verify");
  VerifyExactFile(paths.commit, kCommitGenerationAData,
                  "recovery_precommit_generation_a_open",
                  "recovery_precommit_generation_a_stat",
                  "recovery_precommit_generation_a_read",
                  "recovery_precommit_generation_a_close");
  VerifyExactFile(paths.temporary_commit, kCommitGenerationBData,
                  "recovery_precommit_generation_b_open",
                  "recovery_precommit_generation_b_stat",
                  "recovery_precommit_generation_b_read",
                  "recovery_precommit_generation_b_close");
  RequireDirectoryNames(paths.tree, {"commit.bin", "commit.tmp"},
                        "recovery_precommit_tree_open",
                        "recovery_precommit_tree_entries",
                        "recovery_precommit_tree_close");

  // The temporary generation is not a completed application commit. This is
  // deliberately a tiny recovery policy, not a SQLite or LevelDB journal.
  RemoveFile(paths.temporary_commit, "recovery_precommit_discard_temp");
  Require(IsMissing(paths.temporary_commit),
          "recovery_precommit_temp_present_after_discard");
  VerifyExactFile(paths.commit, kCommitGenerationAData,
                  "recovery_precommit_retained_generation_a_open",
                  "recovery_precommit_retained_generation_a_stat",
                  "recovery_precommit_retained_generation_a_read",
                  "recovery_precommit_retained_generation_a_close");
  RequireDirectoryNames(paths.tree, {"commit.bin"},
                        "recovery_precommit_recovered_tree_open",
                        "recovery_precommit_recovered_tree_entries",
                        "recovery_precommit_recovered_tree_close");
  CleanupRecoveryFixture(paths, "recovery_precommit_cleanup_commit");

  std::fprintf(stdout,
               "%s phase=%s outcome=retained_generation_a_discarded_temp "
               "atomic_recovery=not_claimed database_recovery=not_claimed "
               "cleanup=ok\n",
               kRecoveryReadyPrefix, kRecoveryPrecommitVerifyPhase);
  std::fflush(stdout);
}

void RunRecoveryPostcommitVerifyPhase(const FixturePaths& paths) {
  PrintRecoveryVerifyStarted(kRecoveryPostcommitVerifyPhase,
                             kRecoveryPostcommitBoundary);
  PrintPhase("recovery_postcommit_fresh_instance_verify");
  VerifyExactFile(paths.commit, kCommitGenerationBData,
                  "recovery_postcommit_generation_b_open",
                  "recovery_postcommit_generation_b_stat",
                  "recovery_postcommit_generation_b_read",
                  "recovery_postcommit_generation_b_close");
  Require(IsMissing(paths.temporary_commit),
          "recovery_postcommit_temp_present");
  RequireDirectoryNames(paths.tree, {"commit.bin"},
                        "recovery_postcommit_tree_open",
                        "recovery_postcommit_tree_entries",
                        "recovery_postcommit_tree_close");
  CleanupRecoveryFixture(paths, "recovery_postcommit_cleanup_commit");

  std::fprintf(stdout,
               "%s phase=%s outcome=retained_generation_b_after_rename "
               "atomic_recovery=not_claimed database_recovery=not_claimed "
               "cleanup=ok\n",
               kRecoveryReadyPrefix, kRecoveryPostcommitVerifyPhase);
  std::fflush(stdout);
}

void RunVerifyPhase(const FixturePaths& paths) {
  // This is emitted only after the fresh Wasm module has mounted OPFS. The
  // next outer-document gate uses it to distinguish a real module invocation
  // from an in-page reentry into the write instance.
  std::fprintf(stdout, "%s:VERIFY_STARTED schema=%d run_id=redacted\n", kPrefix,
               kSchemaVersion);
  std::fflush(stdout);
  PrintPhase("fresh_instance_verify");
  const std::array<uint8_t, 16> expected_data = ExpectedData();
  VerifyExactFile(paths.data, expected_data, "verify_data_open",
                  "verify_data_stat", "verify_data_read", "verify_data_close");
  VerifyExactFile(paths.schema, kSchemaData, "verify_schema_open",
                  "verify_schema_stat", "verify_schema_read",
                  "verify_schema_close");
  VerifyExactFile(paths.commit, kCommitGenerationBData,
                  "verify_rename_replace_final_open",
                  "verify_rename_replace_final_stat",
                  "verify_rename_replace_final_read",
                  "verify_rename_replace_final_close");
  VerifyExactFile(paths.nested_child, kNestedData, "verify_nested_open",
                  "verify_nested_stat", "verify_nested_read",
                  "verify_nested_close");
  Require(IsMissing(paths.temporary_commit), "verify_temp_present");
  Require(IsMissing(paths.deleted), "verify_deleted_present");
  RequireDirectoryNames(paths.root, {"tree"}, "verify_root_open",
                        "verify_root_entries", "verify_root_close");
  RequireDirectoryNames(paths.tree,
                        {"commit.bin", "data.bin", "empty", "nested",
                         "schema.bin"},
                        "verify_tree_open", "verify_tree_entries",
                        "verify_tree_close");
  RequireDirectoryNames(paths.nested, {"child.bin"}, "verify_nested_dir_open",
                        "verify_nested_dir_entries", "verify_nested_dir_close");
  RequireDirectoryNames(paths.empty, {}, "verify_empty_open",
                        "verify_empty_entries", "verify_empty_close");

  PrintPhase("fixture_delete");
  RemoveFile(paths.data, "cleanup_data");
  RemoveFile(paths.schema, "cleanup_schema");
  RemoveFile(paths.commit, "cleanup_commit");
  RemoveFile(paths.nested_child, "cleanup_nested_child");
  RemoveDirectory(paths.empty, "cleanup_empty");
  RemoveDirectory(paths.nested, "cleanup_nested");
  RemoveDirectory(paths.tree, "cleanup_tree");
  RemoveDirectory(paths.root, "cleanup_root");
  Require(IsMissing(paths.root), "cleanup_root_present");

  std::fprintf(stdout,
               "%s:VERIFY_READY schema=%d persisted_bytes=ok persisted_tree=ok "
               "temp_absent=ok rename_replace=ok atomic_recovery=not_claimed "
               "deleted_absent=ok cleanup=ok\n",
               kPrefix, kSchemaVersion);
  std::fflush(stdout);
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

  std::fprintf(stdout, "%s:RUNTIME_START phase=%s run_id=redacted\n", kPrefix,
               arguments.phase.c_str());
  std::fflush(stdout);

  MountOpfs("/opfs");
  const FixturePaths paths = MakeFixturePaths(arguments.run_id);
  if (arguments.phase == kWritePhase) {
    RunWritePhase(paths);
  } else if (arguments.phase == kVerifyPhase) {
    RunVerifyPhase(paths);
  } else if (arguments.phase == kRecoveryPrecommitPhase) {
    RunRecoveryPrecommitPhase(paths);
  } else if (arguments.phase == kRecoveryPrecommitVerifyPhase) {
    RunRecoveryPrecommitVerifyPhase(paths);
  } else if (arguments.phase == kRecoveryPostcommitPhase) {
    RunRecoveryPostcommitPhase(paths);
  } else {
    RunRecoveryPostcommitVerifyPhase(paths);
  }

  if (IsRecoveryInterruptionPhase(arguments.phase)) {
    // The host posts the native interruption-ready witness and immediately
    // replaces the outer document. No destructor, close, or application
    // cleanup path follows this boundary. This is a controlled abrupt document
    // disposal at an application-visible boundary, not a failure injected
    // inside the OPFS move implementation and not a database recovery claim.
    emscripten_exit_with_live_runtime();
  }

  std::fprintf(stdout, "%s:RUNTIME_END phase=%s\n", kPrefix,
               arguments.phase.c_str());
  std::fprintf(stdout, "%s:PASS phase=%s\n", kPrefix,
               arguments.phase.c_str());
  std::fflush(stdout);

  // The pinned WasmFS OPFS backend owns a dedicated ProxyWorker. Letting the
  // generated global exit path tear it down attempts a blocking pthread join
  // on the browser main thread. This isolated feasibility smoke instead lets
  // the outer document replacement dispose the live runtime after every file
  // descriptor has been closed and fdatasynced above. It therefore proves
  // primitive OPFS persistence across fresh documents and the bounded
  // application-boundary recovery dispositions above. It does not prove
  // orderly WasmFS shutdown or OPFS/database crash-recovery durability.
  emscripten_exit_with_live_runtime();
}

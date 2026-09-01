// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SQLITE_RECOVERY_VFS_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SQLITE_RECOVERY_VFS_H_

#include <atomic>
#include <cstddef>

#include "base/threading/platform_thread.h"
#include "third_party/sqlite/sqlite3.h"

namespace chrome {

// A private, non-default forwarding VFS for the source-selected SQLite
// interruption-recovery witness. It forwards every normal SQLite operation to
// Chromium's already-installed default VFS. Once armed on its owner thread,
// it aborts only after the real xSync() of the main database file returned
// SQLITE_OK. This is deliberately not a general failure-injection API.
class ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs final {
 public:
  using MainDatabaseSyncCallback = void (*)();

  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs(
      base::PlatformThreadId owner_thread,
      MainDatabaseSyncCallback main_database_sync_callback);
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs(
      const ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs&) = delete;
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& operator=(
      const ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs&) = delete;
  ~ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs();

  const char* name() const { return kName; }

  // Arms exactly one owner-thread main-database xSync() callback. If the real
  // SQLite commit returns, the caller must disarm and treat that path as a
  // witness failure rather than an ordinary write success.
  void ArmForCommit();
  void DisarmAfterCommit();

 private:
  struct WrappedFile;

  static constexpr char kName[] =
      "WasmProfileDatabaseSqliteCommitInterruptionVfs";

  static ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& FromVfs(
      sqlite3_vfs* vfs);
  static WrappedFile& FromFile(sqlite3_file* file);
  static const sqlite3_io_methods* IoMethodsFor(sqlite3_file* wrapped_file);

  sqlite3_vfs* TargetVfs();
  bool TryClaimFirstSuccessfulMainDatabaseSync(bool is_main_database);

  static int Open(sqlite3_vfs* vfs,
                  const char* file_name,
                  sqlite3_file* result_file,
                  int desired_flags,
                  int* used_flags);
  static int Delete(sqlite3_vfs* vfs, const char* file_name, int sync_dir);
  static int Access(sqlite3_vfs* vfs,
                    const char* file_name,
                    int flags,
                    int* result);
  static int FullPathname(sqlite3_vfs* vfs,
                          const char* file_name,
                          int result_size,
                          char* result);
  static int Randomness(sqlite3_vfs* vfs, int result_size, char* result);
  static int Sleep(sqlite3_vfs* vfs, int microseconds);
  static int GetLastError(sqlite3_vfs* vfs,
                          int message_size,
                          char* message);
  static int CurrentTimeInt64(sqlite3_vfs* vfs, sqlite3_int64* result_ms);

  static int Close(sqlite3_file* file);
  static int Read(sqlite3_file* file,
                  void* buffer,
                  int amount,
                  sqlite3_int64 offset);
  static int Write(sqlite3_file* file,
                   const void* buffer,
                   int amount,
                   sqlite3_int64 offset);
  static int Truncate(sqlite3_file* file, sqlite3_int64 size);
  static int Sync(sqlite3_file* file, int flags);
  static int FileSize(sqlite3_file* file, sqlite3_int64* result_size);
  static int Lock(sqlite3_file* file, int lock_type);
  static int Unlock(sqlite3_file* file, int lock_type);
  static int CheckReservedLock(sqlite3_file* file, int* result);
  static int FileControl(sqlite3_file* file, int operation, void* argument);
  static int SectorSize(sqlite3_file* file);
  static int DeviceCharacteristics(sqlite3_file* file);
  static int ShmMap(sqlite3_file* file,
                    int region,
                    int size,
                    int extend,
                    void volatile** result);
  static int ShmLock(sqlite3_file* file, int offset, int count, int flags);
  static void ShmBarrier(sqlite3_file* file);
  static int ShmUnmap(sqlite3_file* file, int delete_flag);
  static int Fetch(sqlite3_file* file,
                   sqlite3_int64 offset,
                   int amount,
                   void** result);
  static int Unfetch(sqlite3_file* file,
                     sqlite3_int64 offset,
                     void* result);

  sqlite3_vfs vfs_{};
  sqlite3_vfs* target_vfs_ = nullptr;
  const base::PlatformThreadId owner_thread_;
  const MainDatabaseSyncCallback main_database_sync_callback_;
  std::atomic<bool> armed_{false};
  std::atomic<bool> abort_claimed_{false};
  size_t live_file_count_ = 0;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_DATABASE_SQLITE_RECOVERY_VFS_H_

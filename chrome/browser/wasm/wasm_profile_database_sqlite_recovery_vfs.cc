// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_database_sqlite_recovery_vfs.h"

#include <cstdlib>
#include <cstring>
#include <type_traits>

#include "base/check.h"
#include "base/check_op.h"

namespace chrome {

struct ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::WrappedFile {
  // This must remain first so SQLite can safely treat a WrappedFile as its
  // sqlite3_file allocation.
  sqlite3_file sqlite_file;
  sqlite3_file* target_file;
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs* owner;
  bool is_main_database;
};

ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::
    ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs(
        base::PlatformThreadId owner_thread,
        MainDatabaseSyncCallback main_database_sync_callback)
    : owner_thread_(owner_thread),
      main_database_sync_callback_(main_database_sync_callback) {
  CHECK(main_database_sync_callback_);
  // This VFS is never the default. A duplicate registration would let a
  // second test owner intercept the first owner's connection, so fail closed.
  CHECK_EQ(sqlite3_vfs_find(kName), nullptr);
  // The only construction site has already opened the seed database through
  // sql::Database, so Chromium's VFSWrapper is installed before this size-only
  // lookup. Do not cache this pointer as the forwarding target here: that
  // remains lazy in the first VFS callback so the selected connection wraps
  // the current Chromium default exactly.
  sqlite3_vfs* default_vfs = sqlite3_vfs_find(nullptr);
  CHECK(default_vfs);
  CHECK_GE(default_vfs->iVersion, 3);
  CHECK_GT(default_vfs->mxPathname, 0);
  std::memset(&vfs_, 0, sizeof(vfs_));
  vfs_.iVersion = 3;
  vfs_.szOsFile = sizeof(WrappedFile);
  vfs_.mxPathname = default_vfs->mxPathname;
  vfs_.zName = kName;
  vfs_.pAppData = this;
  vfs_.xOpen = &Open;
  vfs_.xDelete = &Delete;
  vfs_.xAccess = &Access;
  vfs_.xFullPathname = &FullPathname;
  // Chrome does not allow SQLite dynamic-extension loading. Do not advertise
  // a synthetic implementation for those unavailable operations.
  vfs_.xDlOpen = nullptr;
  vfs_.xDlError = nullptr;
  vfs_.xDlSym = nullptr;
  vfs_.xDlClose = nullptr;
  vfs_.xRandomness = &Randomness;
  vfs_.xSleep = &Sleep;
  // SQLite is built with SQLITE_OMIT_DEPRECATED, matching VFSWrapper.
  vfs_.xCurrentTime = nullptr;
  vfs_.xGetLastError = &GetLastError;
  vfs_.xCurrentTimeInt64 = &CurrentTimeInt64;
  // The system-call interception API is intentionally unavailable in Chrome's
  // VFSWrapper, so this forwarding VFS must not claim to implement it.
  vfs_.xSetSystemCall = nullptr;
  vfs_.xGetSystemCall = nullptr;
  vfs_.xNextSystemCall = nullptr;
  CHECK_EQ(sqlite3_vfs_register(&vfs_, /*makeDflt=*/false), SQLITE_OK);
}

ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::
    ~ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs() {
  CHECK_EQ(live_file_count_, 0u);
  CHECK_EQ(sqlite3_vfs_unregister(&vfs_), SQLITE_OK);
}

void ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::ArmForCommit() {
  CHECK_EQ(owner_thread_, base::PlatformThread::CurrentId());
  CHECK(!abort_claimed_.load(std::memory_order_relaxed));
  CHECK(!armed_.exchange(true, std::memory_order_acq_rel));
}

void ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::
    DisarmAfterCommit() {
  CHECK_EQ(owner_thread_, base::PlatformThread::CurrentId());
  armed_.store(false, std::memory_order_release);
}

ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs&
ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::FromVfs(
    sqlite3_vfs* vfs) {
  CHECK(vfs);
  auto* owner = static_cast<
      ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs*>(vfs->pAppData);
  CHECK(owner);
  return *owner;
}

ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::WrappedFile&
ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::FromFile(
    sqlite3_file* file) {
  CHECK(file);
  auto* wrapped = reinterpret_cast<WrappedFile*>(file);
  CHECK(wrapped->target_file);
  CHECK(wrapped->target_file->pMethods);
  CHECK(wrapped->owner);
  return *wrapped;
}

const sqlite3_io_methods*
ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::IoMethodsFor(
    sqlite3_file* wrapped_file) {
  static_assert(std::is_standard_layout_v<WrappedFile>);
  static_assert(offsetof(WrappedFile, sqlite_file) == 0);
  CHECK(wrapped_file);
  CHECK(wrapped_file->pMethods);
  switch (wrapped_file->pMethods->iVersion) {
    case 1: {
      static const sqlite3_io_methods kVersion1Methods = {
          .iVersion = 1,
          .xClose = &Close,
          .xRead = &Read,
          .xWrite = &Write,
          .xTruncate = &Truncate,
          .xSync = &Sync,
          .xFileSize = &FileSize,
          .xLock = &Lock,
          .xUnlock = &Unlock,
          .xCheckReservedLock = &CheckReservedLock,
          .xFileControl = &FileControl,
          .xSectorSize = &SectorSize,
          .xDeviceCharacteristics = &DeviceCharacteristics,
      };
      return &kVersion1Methods;
    }
    case 2: {
      static const sqlite3_io_methods kVersion2Methods = {
          .iVersion = 2,
          .xClose = &Close,
          .xRead = &Read,
          .xWrite = &Write,
          .xTruncate = &Truncate,
          .xSync = &Sync,
          .xFileSize = &FileSize,
          .xLock = &Lock,
          .xUnlock = &Unlock,
          .xCheckReservedLock = &CheckReservedLock,
          .xFileControl = &FileControl,
          .xSectorSize = &SectorSize,
          .xDeviceCharacteristics = &DeviceCharacteristics,
          .xShmMap = &ShmMap,
          .xShmLock = &ShmLock,
          .xShmBarrier = &ShmBarrier,
          .xShmUnmap = &ShmUnmap,
      };
      return &kVersion2Methods;
    }
    case 3: {
      static const sqlite3_io_methods kVersion3Methods = {
          .iVersion = 3,
          .xClose = &Close,
          .xRead = &Read,
          .xWrite = &Write,
          .xTruncate = &Truncate,
          .xSync = &Sync,
          .xFileSize = &FileSize,
          .xLock = &Lock,
          .xUnlock = &Unlock,
          .xCheckReservedLock = &CheckReservedLock,
          .xFileControl = &FileControl,
          .xSectorSize = &SectorSize,
          .xDeviceCharacteristics = &DeviceCharacteristics,
          .xShmMap = &ShmMap,
          .xShmLock = &ShmLock,
          .xShmBarrier = &ShmBarrier,
          .xShmUnmap = &ShmUnmap,
          .xFetch = &Fetch,
          .xUnfetch = &Unfetch,
      };
      return &kVersion3Methods;
    }
  }
  CHECK(false);
}

sqlite3_vfs*
ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::TargetVfs() {
  if (!target_vfs_) {
    // Resolve only from a VFS callback, after Database::OpenInternal has
    // installed Chromium's VFSWrapper. Resolving in the constructor could
    // bypass the wrapper and change production VFS behavior under test.
    target_vfs_ = sqlite3_vfs_find(nullptr);
    CHECK(target_vfs_);
    CHECK_NE(target_vfs_, &vfs_);
  }
  return target_vfs_;
}

bool ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::
    TryClaimFirstSuccessfulMainDatabaseSync(bool is_main_database) {
  if (!is_main_database ||
      base::PlatformThread::CurrentId() != owner_thread_ ||
      !armed_.load(std::memory_order_acquire)) {
    return false;
  }
  bool expected = false;
  return abort_claimed_.compare_exchange_strong(expected, true,
                                                std::memory_order_acq_rel);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Open(
    sqlite3_vfs* vfs,
    const char* file_name,
    sqlite3_file* result_file,
    int desired_flags,
    int* used_flags) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  auto* target_file = static_cast<sqlite3_file*>(
      sqlite3_malloc(static_cast<int>(target_vfs->szOsFile)));
  if (!target_file) {
    return SQLITE_NOMEM;
  }
  // Preserve SQLite's filename pointer exactly. The delegated unix VFS may
  // require the original lifetime/representation for its pathname handling.
  const int result = target_vfs->xOpen(target_vfs, file_name, target_file,
                                       desired_flags, used_flags);
  if (result != SQLITE_OK) {
    sqlite3_free(target_file);
    return result;
  }

  auto* wrapped = reinterpret_cast<WrappedFile*>(result_file);
  wrapped->sqlite_file.pMethods = IoMethodsFor(target_file);
  wrapped->target_file = target_file;
  wrapped->owner = &owner;
  wrapped->is_main_database = (desired_flags & SQLITE_OPEN_MAIN_DB) != 0;
  ++owner.live_file_count_;
  return SQLITE_OK;
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Delete(
    sqlite3_vfs* vfs,
    const char* file_name,
    int sync_dir) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  return target_vfs->xDelete(target_vfs, file_name, sync_dir);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Access(
    sqlite3_vfs* vfs,
    const char* file_name,
    int flags,
    int* result) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  return target_vfs->xAccess(target_vfs, file_name, flags, result);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::FullPathname(
    sqlite3_vfs* vfs,
    const char* file_name,
    int result_size,
    char* result) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  return target_vfs->xFullPathname(target_vfs, file_name, result_size, result);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Randomness(
    sqlite3_vfs* vfs,
    int result_size,
    char* result) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  return target_vfs->xRandomness(target_vfs, result_size, result);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Sleep(
    sqlite3_vfs* vfs,
    int microseconds) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  return target_vfs->xSleep(target_vfs, microseconds);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::GetLastError(
    sqlite3_vfs* vfs,
    int message_size,
    char* message) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  return target_vfs->xGetLastError(target_vfs, message_size, message);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::CurrentTimeInt64(
    sqlite3_vfs* vfs,
    sqlite3_int64* result_ms) {
  ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs& owner = FromVfs(vfs);
  sqlite3_vfs* target_vfs = owner.TargetVfs();
  CHECK(target_vfs->xCurrentTimeInt64);
  return target_vfs->xCurrentTimeInt64(target_vfs, result_ms);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Close(
    sqlite3_file* file) {
  WrappedFile& wrapped = FromFile(file);
  const int result = wrapped.target_file->pMethods->xClose(wrapped.target_file);
  sqlite3_free(wrapped.target_file);
  CHECK_GT(wrapped.owner->live_file_count_, 0u);
  --wrapped.owner->live_file_count_;
  wrapped.sqlite_file.pMethods = nullptr;
  wrapped.target_file = nullptr;
  wrapped.owner = nullptr;
  return result;
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Read(
    sqlite3_file* file,
    void* buffer,
    int amount,
    sqlite3_int64 offset) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xRead(wrapped.target_file, buffer,
                                              amount, offset);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Write(
    sqlite3_file* file,
    const void* buffer,
    int amount,
    sqlite3_int64 offset) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xWrite(wrapped.target_file, buffer,
                                               amount, offset);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Truncate(
    sqlite3_file* file,
    sqlite3_int64 size) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xTruncate(wrapped.target_file, size);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Sync(
    sqlite3_file* file,
    int flags) {
  WrappedFile& wrapped = FromFile(file);
  // Never fabricate a successful Sync. The phase exists only after the exact
  // main-database xSync reaches the backing VFS and reports SQLITE_OK.
  const int result = wrapped.target_file->pMethods->xSync(wrapped.target_file,
                                                           flags);
  if (result == SQLITE_OK &&
      wrapped.owner->TryClaimFirstSuccessfulMainDatabaseSync(
          wrapped.is_main_database)) {
    wrapped.owner->main_database_sync_callback_();
    // The callback emitted the fixed, path-free post-sync phase. Abort before
    // SQLite's Commit() can return to the smoke task.
    std::abort();
  }
  return result;
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::FileSize(
    sqlite3_file* file,
    sqlite3_int64* result_size) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xFileSize(wrapped.target_file,
                                                  result_size);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Lock(
    sqlite3_file* file,
    int lock_type) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xLock(wrapped.target_file, lock_type);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Unlock(
    sqlite3_file* file,
    int lock_type) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xUnlock(wrapped.target_file,
                                                lock_type);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::CheckReservedLock(
    sqlite3_file* file,
    int* result) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xCheckReservedLock(wrapped.target_file,
                                                           result);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::FileControl(
    sqlite3_file* file,
    int operation,
    void* argument) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xFileControl(wrapped.target_file,
                                                      operation, argument);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::SectorSize(
    sqlite3_file* file) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xSectorSize(wrapped.target_file);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::
    DeviceCharacteristics(sqlite3_file* file) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xDeviceCharacteristics(
      wrapped.target_file);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::ShmMap(
    sqlite3_file* file,
    int region,
    int size,
    int extend,
    void volatile** result) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xShmMap(wrapped.target_file, region,
                                                size, extend, result);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::ShmLock(
    sqlite3_file* file,
    int offset,
    int count,
    int flags) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xShmLock(wrapped.target_file, offset,
                                                 count, flags);
}

void ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::ShmBarrier(
    sqlite3_file* file) {
  WrappedFile& wrapped = FromFile(file);
  wrapped.target_file->pMethods->xShmBarrier(wrapped.target_file);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::ShmUnmap(
    sqlite3_file* file,
    int delete_flag) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xShmUnmap(wrapped.target_file,
                                                  delete_flag);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Fetch(
    sqlite3_file* file,
    sqlite3_int64 offset,
    int amount,
    void** result) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xFetch(wrapped.target_file, offset,
                                               amount, result);
}

int ScopedWasmProfileDatabaseSqliteCommitInterruptionVfs::Unfetch(
    sqlite3_file* file,
    sqlite3_int64 offset,
    void* result) {
  WrappedFile& wrapped = FromFile(file);
  return wrapped.target_file->pMethods->xUnfetch(wrapped.target_file, offset,
                                                 result);
}

}  // namespace chrome

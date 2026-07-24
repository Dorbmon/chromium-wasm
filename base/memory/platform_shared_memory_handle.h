// Copyright 2022 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef BASE_MEMORY_PLATFORM_SHARED_MEMORY_HANDLE_H_
#define BASE_MEMORY_PLATFORM_SHARED_MEMORY_HANDLE_H_

#include <stdint.h>

#include "base/base_export.h"
#include "build/build_config.h"

#if BUILDFLAG(IS_APPLE)
#include <mach/mach.h>

#include "base/apple/scoped_mach_port.h"
#elif BUILDFLAG(IS_FUCHSIA)
#include <lib/zx/vmo.h>
#elif BUILDFLAG(IS_WIN)
#include "base/win/scoped_handle.h"
#include "base/win/windows_types.h"
#elif BUILDFLAG(IS_POSIX)
#include <sys/types.h>

#include "base/files/scoped_file.h"
#endif

namespace base::subtle {

#if BUILDFLAG(IS_WASM)
// Process-local shared memory capabilities. These values are opaque outside the
// Wasm shared memory backend and must never be interpreted as file descriptors
// or storage addresses.
enum class PlatformSharedMemoryHandleRights : uint8_t {
  kInvalid = 0,
  kReadOnly,
  kWritable,
  kUnsafe,
};

struct BASE_EXPORT PlatformSharedMemoryHandle {
  uint64_t region_id = 0;
  uint64_t generation = 0;
  PlatformSharedMemoryHandleRights rights =
      PlatformSharedMemoryHandleRights::kInvalid;

  bool is_valid() const {
    return region_id != 0 && generation != 0 &&
           rights != PlatformSharedMemoryHandleRights::kInvalid;
  }

  friend bool operator==(const PlatformSharedMemoryHandle&,
                         const PlatformSharedMemoryHandle&) = default;
};

class PlatformSharedMemoryRegion;

// Move-only owner of one process-local registry reference.
class BASE_EXPORT ScopedPlatformSharedMemoryHandle {
 public:
  ScopedPlatformSharedMemoryHandle();
  explicit ScopedPlatformSharedMemoryHandle(
      PlatformSharedMemoryHandle handle);
  ScopedPlatformSharedMemoryHandle(ScopedPlatformSharedMemoryHandle&&);
  ScopedPlatformSharedMemoryHandle& operator=(
      ScopedPlatformSharedMemoryHandle&&);
  ScopedPlatformSharedMemoryHandle(const ScopedPlatformSharedMemoryHandle&) =
      delete;
  ScopedPlatformSharedMemoryHandle& operator=(
      const ScopedPlatformSharedMemoryHandle&) = delete;
  ~ScopedPlatformSharedMemoryHandle();

  bool is_valid() const { return handle_.is_valid(); }
  PlatformSharedMemoryHandle get() const { return handle_; }
  [[nodiscard]] PlatformSharedMemoryHandle release();
  void reset(PlatformSharedMemoryHandle handle = {});

 private:
  friend class PlatformSharedMemoryRegion;

  void SetRightsForConversion(PlatformSharedMemoryHandleRights rights);

  PlatformSharedMemoryHandle handle_;
};
#endif

#if BUILDFLAG(IS_POSIX) && !BUILDFLAG(IS_APPLE) && !BUILDFLAG(IS_ANDROID)
// Helper structs to keep two descriptors on POSIX. It's needed to support
// ConvertToReadOnly().
struct BASE_EXPORT FDPair {
  // The main shared memory descriptor that is used for mapping. May be either
  // writable or read-only, depending on region's mode.
  int fd;
  // The read-only descriptor, valid only in kWritable mode. Replaces |fd| when
  // a region is converted to read-only.
  int readonly_fd;

  friend bool operator==(const FDPair&, const FDPair&) = default;
};

struct BASE_EXPORT ScopedFDPair {
  ScopedFDPair();
  ScopedFDPair(ScopedFD in_fd, ScopedFD in_readonly_fd);
  ScopedFDPair(ScopedFDPair&&);
  ScopedFDPair& operator=(ScopedFDPair&&);
  ~ScopedFDPair();

  FDPair get() const;

  ScopedFD fd;
  ScopedFD readonly_fd;
};
#endif

// Platform-specific shared memory type used by the shared memory system.
#if BUILDFLAG(IS_APPLE)
using PlatformSharedMemoryHandle = mach_port_t;
using ScopedPlatformSharedMemoryHandle = apple::ScopedMachSendRight;
#elif BUILDFLAG(IS_FUCHSIA)
using PlatformSharedMemoryHandle = zx::unowned_vmo;
using ScopedPlatformSharedMemoryHandle = zx::vmo;
#elif BUILDFLAG(IS_WIN)
using PlatformSharedMemoryHandle = HANDLE;
using ScopedPlatformSharedMemoryHandle = win::ScopedHandle;
#elif BUILDFLAG(IS_ANDROID)
using PlatformSharedMemoryHandle = int;
using ScopedPlatformSharedMemoryHandle = ScopedFD;
#elif BUILDFLAG(IS_WASM)
// Defined above.
#else
using PlatformSharedMemoryHandle = FDPair;
using ScopedPlatformSharedMemoryHandle = ScopedFDPair;
#endif

}  // namespace base::subtle

#endif  // BASE_MEMORY_PLATFORM_SHARED_MEMORY_HANDLE_H_

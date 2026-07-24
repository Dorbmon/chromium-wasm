// Copyright 2018 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/memory/platform_shared_memory_handle.h"

#include <utility>

#if BUILDFLAG(IS_WASM)
#include "base/check.h"
#include "base/check_op.h"
#include "base/memory/process_local_shared_memory_wasm.h"
#endif

namespace base::subtle {

#if BUILDFLAG(IS_WASM)
ScopedPlatformSharedMemoryHandle::ScopedPlatformSharedMemoryHandle() = default;

ScopedPlatformSharedMemoryHandle::ScopedPlatformSharedMemoryHandle(
    PlatformSharedMemoryHandle handle)
    : handle_(handle) {}

ScopedPlatformSharedMemoryHandle::ScopedPlatformSharedMemoryHandle(
    ScopedPlatformSharedMemoryHandle&& other)
    : handle_(other.release()) {}

ScopedPlatformSharedMemoryHandle& ScopedPlatformSharedMemoryHandle::operator=(
    ScopedPlatformSharedMemoryHandle&& other) {
  if (this != &other) {
    reset();
    handle_ = other.release();
  }
  return *this;
}

ScopedPlatformSharedMemoryHandle::~ScopedPlatformSharedMemoryHandle() {
  reset();
}

PlatformSharedMemoryHandle ScopedPlatformSharedMemoryHandle::release() {
  return std::exchange(handle_, PlatformSharedMemoryHandle());
}

void ScopedPlatformSharedMemoryHandle::reset(
    PlatformSharedMemoryHandle handle) {
  CHECK(handle_.region_id == 0 || handle_.generation == 0 ||
        handle_ != handle);
  wasm::ReleaseHandleReference(handle_);
  handle_ = handle;
}

void ScopedPlatformSharedMemoryHandle::SetRightsForConversion(
    PlatformSharedMemoryHandleRights rights) {
  CHECK(handle_.is_valid());
  CHECK_NE(rights, PlatformSharedMemoryHandleRights::kInvalid);
  handle_.rights = rights;
}
#endif

#if BUILDFLAG(IS_POSIX) && !BUILDFLAG(IS_APPLE) && !BUILDFLAG(IS_ANDROID)
ScopedFDPair::ScopedFDPair() = default;

ScopedFDPair::ScopedFDPair(ScopedFDPair&&) = default;

ScopedFDPair& ScopedFDPair::operator=(ScopedFDPair&&) = default;

ScopedFDPair::~ScopedFDPair() = default;

ScopedFDPair::ScopedFDPair(ScopedFD in_fd, ScopedFD in_readonly_fd)
    : fd(std::move(in_fd)), readonly_fd(std::move(in_readonly_fd)) {}

FDPair ScopedFDPair::get() const {
  return {fd.get(), readonly_fd.get()};
}
#endif

}  // namespace base::subtle

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "mojo/public/cpp/platform/platform_handle.h"

#include <utility>

#include "base/check.h"
#include "base/logging.h"
#include "base/memory/process_local_shared_memory_wasm.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "platform_handle_wasm.cc is only for WebAssembly"
#endif

namespace mojo {

PlatformHandle::PlatformHandle() = default;

PlatformHandle::PlatformHandle(PlatformHandle&& other) {
  *this = std::move(other);
}

PlatformHandle::PlatformHandle(
    base::subtle::ScopedPlatformSharedMemoryHandle handle)
    : type_(handle.is_valid() ? Type::kWasmSharedMemory : Type::kNone),
      wasm_shared_memory_handle_(std::move(handle)) {}

PlatformHandle::~PlatformHandle() = default;

PlatformHandle& PlatformHandle::operator=(PlatformHandle&& other) {
  if (this == &other) {
    return *this;
  }
  reset();
  type_ = other.type_;
  wasm_shared_memory_handle_ =
      std::move(other.wasm_shared_memory_handle_);
  other.type_ = Type::kNone;
  return *this;
}

void PlatformHandle::ToMojoPlatformHandle(PlatformHandle handle,
                                          MojoPlatformHandle* out_handle) {
  DCHECK(out_handle);
  out_handle->struct_size = sizeof(*out_handle);
  if (!handle.is_valid()) {
    out_handle->type = MOJO_PLATFORM_HANDLE_TYPE_INVALID;
    out_handle->value = 0;
    return;
  }

  CHECK_EQ(handle.type_, Type::kWasmSharedMemory);
  const uint64_t token =
      base::subtle::wasm::ExportHandleForTransport(
          handle.TakeSharedMemoryHandle());
  if (token == 0) {
    out_handle->type = MOJO_PLATFORM_HANDLE_TYPE_INVALID;
    out_handle->value = 0;
    return;
  }
  out_handle->type = MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY;
  out_handle->value = token;
}

PlatformHandle PlatformHandle::FromMojoPlatformHandle(
    const MojoPlatformHandle* handle) {
  DCHECK(handle);
  if (handle->struct_size < sizeof(*handle) ||
      handle->type == MOJO_PLATFORM_HANDLE_TYPE_INVALID) {
    return PlatformHandle();
  }
  if (handle->type != MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY) {
    LOG(ERROR) << "Native platform handles are unsupported in WebAssembly";
    return PlatformHandle();
  }

  auto shared_memory_handle =
      base::subtle::wasm::ImportHandleForTransport(handle->value);
  if (!shared_memory_handle.is_valid()) {
    LOG(ERROR) << "Invalid or consumed Wasm shared-memory transport token";
    return PlatformHandle();
  }
  return PlatformHandle(std::move(shared_memory_handle));
}

void PlatformHandle::reset() {
  wasm_shared_memory_handle_.reset();
  type_ = Type::kNone;
}

void PlatformHandle::release() {
  (void)wasm_shared_memory_handle_.release();
  type_ = Type::kNone;
}

PlatformHandle PlatformHandle::Clone() const {
  if (!is_valid()) {
    return PlatformHandle();
  }
  CHECK_EQ(type_, Type::kWasmSharedMemory);
  return PlatformHandle(base::subtle::wasm::DuplicateHandle(
      wasm_shared_memory_handle_.get()));
}

}  // namespace mojo

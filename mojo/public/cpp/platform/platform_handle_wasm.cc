// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "mojo/public/cpp/platform/platform_handle.h"

#include <utility>

#include "base/logging.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "platform_handle_wasm.cc is only for WebAssembly"
#endif

namespace mojo {

PlatformHandle::PlatformHandle() = default;

PlatformHandle::PlatformHandle(PlatformHandle&& other) {
  *this = std::move(other);
}

PlatformHandle::~PlatformHandle() = default;

PlatformHandle& PlatformHandle::operator=(PlatformHandle&& other) {
  type_ = other.type_;
  other.type_ = Type::kNone;
  return *this;
}

void PlatformHandle::ToMojoPlatformHandle(PlatformHandle handle,
                                          MojoPlatformHandle* out_handle) {
  DCHECK(out_handle);
  CHECK_EQ(handle.type_, Type::kNone)
      << "Native platform handles are unsupported in WebAssembly";
  out_handle->struct_size = sizeof(*out_handle);
  out_handle->type = MOJO_PLATFORM_HANDLE_TYPE_INVALID;
  out_handle->value = 0;
}

PlatformHandle PlatformHandle::FromMojoPlatformHandle(
    const MojoPlatformHandle* handle) {
  DCHECK(handle);
  if (handle->struct_size >= sizeof(*handle) &&
      handle->type != MOJO_PLATFORM_HANDLE_TYPE_INVALID) {
    LOG(ERROR) << "Native platform handles are unsupported in WebAssembly";
  }
  return PlatformHandle();
}

void PlatformHandle::reset() {
  type_ = Type::kNone;
}

void PlatformHandle::release() {
  type_ = Type::kNone;
}

PlatformHandle PlatformHandle::Clone() const {
  CHECK_EQ(type_, Type::kNone)
      << "Native platform handles are unsupported in WebAssembly";
  return PlatformHandle();
}

}  // namespace mojo

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/files/file.h"

#include <fcntl.h>

#include "base/files/file_tracing.h"
#include "base/notreached.h"
#include "base/posix/eintr_wrapper.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "file_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

namespace {

short FcntlFlockType(File::LockMode mode) {
  switch (mode) {
    case File::LockMode::kShared:
      return F_RDLCK;
    case File::LockMode::kExclusive:
      return F_WRLCK;
  }
  NOTREACHED();
}

File::Error CallFcntlFlock(PlatformFile file, short type) {
  struct flock lock = {};
  lock.l_type = type;
  lock.l_whence = SEEK_SET;
  lock.l_start = 0;
  lock.l_len = 0;  // Lock the entire file.
  if (HANDLE_EINTR(fcntl(file, F_SETLK, &lock)) == -1) {
    return File::GetLastFileError();
  }
  return File::FILE_OK;
}

}  // namespace

File::Error File::Lock(File::LockMode mode) {
  SCOPED_FILE_TRACE("Lock");
  return CallFcntlFlock(file_.get(), FcntlFlockType(mode));
}

File::Error File::Unlock() {
  SCOPED_FILE_TRACE("Unlock");
  return CallFcntlFlock(file_.get(), F_UNLCK);
}

}  // namespace base

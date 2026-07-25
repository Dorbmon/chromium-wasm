// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/base/file_stream_context.h"

#include <errno.h>

#include <optional>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/numerics/safe_conversions.h"
#include "base/task/task_runner.h"
#include "build/build_config.h"
#include "net/base/io_buffer.h"
#include "net/base/net_errors.h"

#if !BUILDFLAG(IS_WASM)
#error "file_stream_context_wasm.cc must only be built for WebAssembly"
#endif

namespace net {

FileStream::Context::Context(scoped_refptr<base::TaskRunner> task_runner)
    : Context(base::File(), std::move(task_runner)) {}

FileStream::Context::Context(base::File file,
                             scoped_refptr<base::TaskRunner> task_runner)
    : file_(std::move(file)), task_runner_(std::move(task_runner)) {}

FileStream::Context::~Context() = default;

int FileStream::Context::Read(IOBuffer* in_buf,
                              int buf_len,
                              CompletionOnceCallback callback) {
  DCHECK(!async_in_progress_);

  scoped_refptr<IOBuffer> buf = in_buf;
  const bool posted = task_runner_->PostTaskAndReplyWithResult(
      FROM_HERE,
      base::BindOnce(&Context::ReadFileImpl, base::Unretained(this), buf,
                     buf_len),
      base::BindOnce(&Context::OnAsyncCompleted, base::Unretained(this),
                     std::move(callback)));
  DCHECK(posted);

  async_in_progress_ = true;
  return ERR_IO_PENDING;
}

int FileStream::Context::Write(IOBuffer* in_buf,
                               int buf_len,
                               CompletionOnceCallback callback) {
  DCHECK(!async_in_progress_);

  scoped_refptr<IOBuffer> buf = in_buf;
  const bool posted = task_runner_->PostTaskAndReplyWithResult(
      FROM_HERE,
      base::BindOnce(&Context::WriteFileImpl, base::Unretained(this), buf,
                     buf_len),
      base::BindOnce(&Context::OnAsyncCompleted, base::Unretained(this),
                     std::move(callback)));
  DCHECK(posted);

  async_in_progress_ = true;
  return ERR_IO_PENDING;
}

FileStream::Context::IOResult FileStream::Context::SeekFileImpl(
    int64_t offset) {
  int64_t result = file_.Seek(base::File::FROM_BEGIN, offset);
  if (result == -1) {
    return IOResult::FromOSError(errno);
  }
  return IOResult(result, 0);
}

void FileStream::Context::OnFileOpened() {}

FileStream::Context::IOResult FileStream::Context::ReadFileImpl(
    scoped_refptr<IOBuffer> buf,
    int buf_len) {
  std::optional<size_t> result = file_.ReadAtCurrentPosNoBestEffort(
      buf->first(base::checked_cast<size_t>(buf_len)));
  if (!result.has_value()) {
    return IOResult::FromOSError(errno);
  }
  return IOResult(result.value(), 0);
}

FileStream::Context::IOResult FileStream::Context::WriteFileImpl(
    scoped_refptr<IOBuffer> buf,
    int buf_len) {
  std::optional<size_t> result = file_.WriteAtCurrentPosNoBestEffort(
      buf->first(base::checked_cast<size_t>(buf_len)));
  if (!result.has_value()) {
    return IOResult::FromOSError(errno);
  }
  return IOResult(result.value(), 0);
}

}  // namespace net

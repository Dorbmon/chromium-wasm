// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/logging.h"

#include <cerrno>
#include <cstdio>
#include <system_error>

#include "base/immediate_crash.h"

namespace logging {

namespace {

int g_min_log_level = LOGGING_INFO;

}  // namespace

std::ostream* g_swallow_stream;

void SetMinLogLevel(int level) {
  g_min_log_level = level < LOGGING_FATAL ? level : LOGGING_FATAL;
}

int GetMinLogLevel() {
  return g_min_log_level;
}

bool ShouldCreateLogMessage(int severity) {
  return severity >= g_min_log_level;
}

int GetVlogVerbosity() {
  return g_min_log_level < 0 ? -g_min_log_level : -1;
}

int GetVlogLevelHelper(const char*, size_t) {
  return GetVlogVerbosity();
}

LogMessage::LogMessage(const char* file, int line, LogSeverity severity)
    : severity_(severity), message_start_(0), file_(file), line_(line) {
  if (file_) {
    stream_ << file_ << ':' << line_ << ": ";
    message_start_ = stream_.view().size();
  }
}

LogMessage::~LogMessage() {
  Flush();
}

void LogMessage::Flush() {
  const std::string message = stream_.str();
  std::fwrite(message.data(), 1, message.size(), stderr);
  if (message.empty() || message.back() != '\n') {
    std::fputc('\n', stderr);
  }
  std::fflush(stderr);
}

std::string LogMessage::BuildCrashString() const {
  return stream_.str();
}

LogMessageFatal::~LogMessageFatal() {
  Flush();
  base::ImmediateCrash();
}

SystemErrorCode GetLastSystemErrorCode() {
  return errno;
}

std::string SystemErrorCodeToString(SystemErrorCode error_code) {
  return std::system_category().message(error_code);
}

ErrnoLogMessage::ErrnoLogMessage(const char* file,
                                 int line,
                                 LogSeverity severity,
                                 SystemErrorCode err)
    : LogMessage(file, line, severity), err_(err) {}

ErrnoLogMessage::~ErrnoLogMessage() {
  AppendError();
}

void ErrnoLogMessage::AppendError() {
  stream() << " (" << err_ << ": " << SystemErrorCodeToString(err_) << ')';
}

ErrnoLogMessageFatal::~ErrnoLogMessageFatal() {
  AppendError();
  Flush();
  base::ImmediateCrash();
}

void RawLog(int level, const char* message) {
  if (level >= g_min_log_level) {
    std::fputs(message, stderr);
    std::fflush(stderr);
  }
  if (level == LOGGING_FATAL) {
    base::ImmediateCrash();
  }
}

void CloseLogFile() {}

}  // namespace logging

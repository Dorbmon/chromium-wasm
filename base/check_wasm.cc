// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/check.h"

#include <cstdlib>
#include <tuple>

#include "base/logging.h"

namespace logging {

namespace {

LogMessage* MakeCheckMessage(const base::Location& location,
                             LogSeverity severity,
                             const char* kind,
                             const char* condition) {
  auto* message =
      new LogMessage(location.file_name(), location.line_number(), severity);
  message->stream() << kind << " failed: " << condition << ". ";
  return message;
}

LogMessage* MakeErrnoCheckMessage(const base::Location& location,
                                  LogSeverity severity,
                                  const char* kind,
                                  const char* condition) {
  auto* message = new ErrnoLogMessage(location.file_name(),
                                      location.line_number(), severity,
                                      GetLastSystemErrorCode());
  message->stream() << kind << " failed: " << condition << ". ";
  return message;
}

}  // namespace

CheckError::CheckError(LogMessage* log_message) : log_message_(log_message) {}

CheckError CheckError::Check(const char* condition,
                             base::NotFatalUntil fatal_milestone,
                             const base::Location& location) {
  // M1 builds are non-official developer builds, where Chromium intentionally
  // treats milestone-gated checks as fatal.
  std::ignore = fatal_milestone;
  return CheckError(
      MakeCheckMessage(location, LOGGING_FATAL, "Check", condition));
}

LogMessage* CheckError::CheckOp(char* log_message_str,
                                base::NotFatalUntil fatal_milestone,
                                const base::Location& location) {
  std::ignore = fatal_milestone;
  LogMessage* message =
      MakeCheckMessage(location, LOGGING_FATAL, "Check", log_message_str);
  std::free(log_message_str);
  return message;
}

CheckError CheckError::DCheck(const char* condition,
                              const base::Location& location) {
  return CheckError(
      MakeCheckMessage(location, LOGGING_DCHECK, "DCHECK", condition));
}

LogMessage* CheckError::DCheckOp(char* log_message_str,
                                 const base::Location& location) {
  LogMessage* message =
      MakeCheckMessage(location, LOGGING_DCHECK, "DCHECK", log_message_str);
  std::free(log_message_str);
  return message;
}

CheckError CheckError::DumpWillBeCheck(const char* condition,
                                       const base::Location& location) {
  return CheckError(
      MakeCheckMessage(location, LOGGING_FATAL, "Check", condition));
}

LogMessage* CheckError::DumpWillBeCheckOp(
    char* log_message_str,
    const base::Location& location) {
  LogMessage* message =
      MakeCheckMessage(location, LOGGING_FATAL, "Check", log_message_str);
  std::free(log_message_str);
  return message;
}

CheckError CheckError::DPCheck(const char* condition,
                               const base::Location& location) {
  return CheckError(
      MakeErrnoCheckMessage(location, LOGGING_DCHECK, "DCHECK", condition));
}

CheckError CheckError::NotImplemented(const char* function,
                                      const base::Location& location) {
  auto* message =
      new LogMessage(location.file_name(), location.line_number(), LOGGING_ERROR);
  message->stream() << "Not implemented reached in " << function << ". ";
  return CheckError(message);
}

std::ostream& CheckError::stream() {
  return log_message_->stream();
}

CheckError::~CheckError() {
  const bool is_fatal = log_message_->severity() == LOGGING_FATAL;
  log_message_.reset();
  if (is_fatal) {
    base::ImmediateCrash();
  }
}

CheckNoreturnError::~CheckNoreturnError() {
  log_message_.reset();
  base::ImmediateCrash();
}

CheckNoreturnError CheckNoreturnError::Check(
    const char* condition,
    const base::Location& location) {
  return CheckNoreturnError(
      MakeCheckMessage(location, LOGGING_FATAL, "Check", condition));
}

LogMessage* CheckNoreturnError::CheckOp(char* log_message_str,
                                        const base::Location& location) {
  LogMessage* message =
      MakeCheckMessage(location, LOGGING_FATAL, "Check", log_message_str);
  std::free(log_message_str);
  return message;
}

CheckNoreturnError CheckNoreturnError::PCheck(
    const char* condition,
    const base::Location& location) {
  return CheckNoreturnError(
      MakeErrnoCheckMessage(location, LOGGING_FATAL, "Check", condition));
}

CheckNoreturnError CheckNoreturnError::PCheck(
    const base::Location& location) {
  return PCheck("", location);
}

NotReachedError NotReachedError::NotReached(
    base::NotFatalUntil fatal_milestone,
    const base::Location& location) {
  std::ignore = fatal_milestone;
  return NotReachedError(
      MakeCheckMessage(location, LOGGING_FATAL, "Check", "false"));
}

NotReachedError NotReachedError::DumpWillBeNotReached(
    const base::Location& location) {
  return NotReachedError(
      MakeCheckMessage(location, LOGGING_FATAL, "NOTREACHED", "false"));
}

NotReachedError::~NotReachedError() = default;

NotReachedNoreturnError::NotReachedNoreturnError(
    const base::Location& location)
    : CheckError(
          MakeCheckMessage(location, LOGGING_FATAL, "NOTREACHED", "false")) {}

NotReachedNoreturnError::~NotReachedNoreturnError() {
  log_message_.reset();
  base::ImmediateCrash();
}

void RawCheckFailure(const char* message) {
  RawLog(LOGGING_FATAL, message);
  base::ImmediateCrash();
}

}  // namespace logging

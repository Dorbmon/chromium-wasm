// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/process/process.h"

#include <utility>

#include <emscripten/emscripten.h>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "process_wasm.cc must only be built for WebAssembly"
#endif

namespace base {
namespace {

ProcessHandle NormalizeProcessHandle(ProcessHandle handle) {
  return handle == GetCurrentProcessHandle() ? handle : kNullProcessHandle;
}

}  // namespace

Process::Process(ProcessHandle handle)
    : process_(NormalizeProcessHandle(handle)) {}

Process::Process(Process&& other)
    : process_(std::exchange(other.process_, kNullProcessHandle)) {}

Process::~Process() = default;

Process& Process::operator=(Process&& other) {
  if (this != &other) {
    process_ = std::exchange(other.process_, kNullProcessHandle);
  }
  return *this;
}

// static
Process Process::Current() {
  return Process(GetCurrentProcessHandle());
}

// static
Process Process::Open(ProcessId pid) {
  return pid == GetCurrentProcId() ? Current() : Process();
}

// static
Process Process::OpenWithExtraPrivileges(ProcessId pid) {
  return Open(pid);
}

// static
bool Process::CanSetPriority() {
  return false;
}

// static
void Process::TerminateCurrentProcessImmediately(int exit_code) {
  // EXIT_RUNTIME is enabled for the Chromium Wasm toolchain. This clears the
  // runtime keepalive state and exits the whole module rather than only the
  // calling pthread.
  emscripten_force_exit(exit_code);
}

bool Process::IsValid() const {
  return process_ == GetCurrentProcessHandle();
}

ProcessHandle Process::Handle() const {
  return process_;
}

Process Process::Duplicate() const {
  return IsValid() ? Current() : Process();
}

ProcessHandle Process::Release() {
  return std::exchange(process_, kNullProcessHandle);
}

ProcessId Process::Pid() const {
  return GetProcId(process_);
}

Time Process::CreationTime() const {
  // Emscripten does not expose module-instantiation wall time. A null Time is
  // the API's explicit unavailable value.
  return Time();
}

bool Process::is_current() const {
  return IsValid();
}

void Process::Close() {
  process_ = kNullProcessHandle;
}

bool Process::Terminate(int /*exit_code*/, bool /*wait*/) const {
  // There are no non-current processes to terminate. Current-process shutdown
  // must use TerminateCurrentProcessImmediately().
  return false;
}

bool Process::WaitForExit(int* /*exit_code*/) const {
  return false;
}

bool Process::WaitForExitWithTimeout(TimeDelta /*timeout*/,
                                     int* /*exit_code*/) const {
  return false;
}

void Process::Exited(int /*exit_code*/) const {
  // No external process observer exists in the single-process model.
}

Process::Priority Process::GetPriority() const {
  // This is the documented fallback when priority cannot be queried.
  return Priority::kUserBlocking;
}

bool Process::SetPriority(Priority /*priority*/) {
  return false;
}

int Process::GetOSPriority() const {
  return -1;
}

}  // namespace base

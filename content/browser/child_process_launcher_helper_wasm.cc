// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/browser/child_process_launcher_helper.h"

#include "base/check.h"
#include "build/build_config.h"
#include "content/browser/child_process_launcher.h"
#include "content/public/browser/child_process_termination_info.h"

#if !BUILDFLAG(IS_WASM)
#error "child_process_launcher_helper_wasm.cc is only for WebAssembly"
#endif

namespace content::internal {

std::optional<mojo::NamedPlatformChannel>
ChildProcessLauncherHelper::CreateNamedPlatformChannelOnLauncherThread() {
  DCHECK(CurrentlyOnProcessLauncherTaskRunner());
  return std::nullopt;
}

void ChildProcessLauncherHelper::BeforeLaunchOnClientThread() {
  DCHECK(client_task_runner_->RunsTasksInCurrentSequence());
  CHECK(false)
      << "Child process launch is unsupported in single-process WebAssembly";
}

std::unique_ptr<FileMappedForLaunch>
ChildProcessLauncherHelper::GetFilesToMap() {
  DCHECK(CurrentlyOnProcessLauncherTaskRunner());
  return std::make_unique<FileMappedForLaunch>();
}

bool ChildProcessLauncherHelper::IsUsingLaunchOptions() {
  return false;
}

bool ChildProcessLauncherHelper::BeforeLaunchOnLauncherThread(
    [[maybe_unused]] FileMappedForLaunch& files_to_register,
    [[maybe_unused]] base::LaunchOptions* options) {
  DCHECK(CurrentlyOnProcessLauncherTaskRunner());
  return false;
}

ChildProcessLauncherHelper::Process
ChildProcessLauncherHelper::LaunchProcessOnLauncherThread(
    [[maybe_unused]] const base::LaunchOptions* options,
    [[maybe_unused]] std::unique_ptr<FileMappedForLaunch> files_to_register,
    bool* is_synchronous_launch,
    int* launch_result) {
  DCHECK(CurrentlyOnProcessLauncherTaskRunner());
  CHECK(is_synchronous_launch);
  CHECK(launch_result);
  *is_synchronous_launch = true;
  *launch_result = LAUNCH_RESULT_FAILURE;
  return Process();
}

void ChildProcessLauncherHelper::AfterLaunchOnLauncherThread(
    const ChildProcessLauncherHelper::Process& process,
    [[maybe_unused]] const base::LaunchOptions* options) {
  DCHECK(CurrentlyOnProcessLauncherTaskRunner());
  CHECK(!process.process.IsValid());
}

ChildProcessTerminationInfo ChildProcessLauncherHelper::GetTerminationInfo(
    const ChildProcessLauncherHelper::Process& process,
    [[maybe_unused]] bool known_dead) {
  CHECK(!process.process.IsValid());
  ChildProcessTerminationInfo info;
  info.status = base::TERMINATION_STATUS_LAUNCH_FAILED;
  info.exit_code = LAUNCH_RESULT_FAILURE;
  return info;
}

// static
bool ChildProcessLauncherHelper::TerminateProcess(
    const base::Process& process,
    [[maybe_unused]] int exit_code) {
  CHECK(!process.IsValid());
  return false;
}

// static
void ChildProcessLauncherHelper::ForceNormalProcessTerminationSync(
    ChildProcessLauncherHelper::Process process) {
  DCHECK(CurrentlyOnProcessLauncherTaskRunner());
  CHECK(!process.process.IsValid());
}

void ChildProcessLauncherHelper::SetProcessPriorityOnLauncherThread(
    base::Process process,
    [[maybe_unused]] base::Process::Priority priority) {
  DCHECK(CurrentlyOnProcessLauncherTaskRunner());
  CHECK(!process.IsValid());
}

}  // namespace content::internal

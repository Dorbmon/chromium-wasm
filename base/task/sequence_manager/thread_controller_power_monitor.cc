// Copyright 2020 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/task/sequence_manager/thread_controller_power_monitor.h"

#include "base/trace_event/trace_event.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#include "base/feature_list.h"
#include "base/power_monitor/power_monitor.h"
#endif

namespace base::sequence_manager::internal {

namespace {

#if !BUILDFLAG(IS_WASM)
// Activate the power management events that affect task scheduling.
BASE_FEATURE(kUsePowerMonitorWithThreadController, FEATURE_ENABLED_BY_DEFAULT);
#endif

// TODO(crbug.com/40127966): Remove this when the experiment becomes the
// default.
bool g_use_thread_controller_power_monitor_ = false;

}  // namespace

ThreadControllerPowerMonitor::ThreadControllerPowerMonitor() = default;

ThreadControllerPowerMonitor::~ThreadControllerPowerMonitor() {
#if !BUILDFLAG(IS_WASM)
  PowerMonitor::GetInstance()->RemovePowerSuspendObserver(this);
#endif
}

void ThreadControllerPowerMonitor::BindToCurrentThread() {
#if BUILDFLAG(IS_WASM)
  // Browser power notifications do not have a host bridge in M1. Leave the
  // observer explicitly unregistered so delayed tasks are never suppressed
  // based on a power state that Wasm cannot observe.
  return;
#else
  // Occasionally registration happens twice (i.e. when the
  // ThreadController::SetDefaultTaskRunner() re-initializes the
  // ThreadController).
  auto* power_monitor = PowerMonitor::GetInstance();
  if (is_observer_registered_) {
    power_monitor->RemovePowerSuspendObserver(this);
  }

  // Register the observer to deliver notifications on the current thread.
  power_monitor->AddPowerSuspendObserver(this);
  is_observer_registered_ = true;
#endif
}

bool ThreadControllerPowerMonitor::IsProcessInPowerSuspendState() {
  return is_power_suspended_;
}

// static
void ThreadControllerPowerMonitor::InitializeFeatures() {
  DCHECK(!g_use_thread_controller_power_monitor_);
#if !BUILDFLAG(IS_WASM)
  g_use_thread_controller_power_monitor_ =
      FeatureList::IsEnabled(kUsePowerMonitorWithThreadController);
#endif
}

// static
void ThreadControllerPowerMonitor::OverrideUsePowerMonitorForTesting(
    bool use_power_monitor) {
  g_use_thread_controller_power_monitor_ = use_power_monitor;
}

// static
void ThreadControllerPowerMonitor::ResetForTesting() {
  g_use_thread_controller_power_monitor_ = false;
}

void ThreadControllerPowerMonitor::OnSuspend() {
  if (!g_use_thread_controller_power_monitor_) {
    return;
  }
  DCHECK(!is_power_suspended_);

  TRACE_EVENT_BEGIN("base", "ThreadController::Suspended",
                    perfetto::Track(reinterpret_cast<uint64_t>(this),
                                    perfetto::ThreadTrack::Current()));
  is_power_suspended_ = true;
}

void ThreadControllerPowerMonitor::OnResume() {
  if (!g_use_thread_controller_power_monitor_) {
    return;
  }

  // It is possible a suspend was already happening before the observer was
  // added to the power monitor. Ignoring the resume notification in that case.
  if (is_power_suspended_) {
    TRACE_EVENT_END("base" /* ThreadController::Suspended */,
                    perfetto::Track(reinterpret_cast<uint64_t>(this),
                                    perfetto::ThreadTrack::Current()));
    is_power_suspended_ = false;
  }
}

}  // namespace base::sequence_manager::internal

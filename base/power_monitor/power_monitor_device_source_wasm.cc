// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/power_monitor/power_monitor_device_source.h"

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "power_monitor_device_source_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

PowerStateObserver::BatteryPowerStatus
PowerMonitorDeviceSource::GetBatteryPowerStatus() const {
  // The Battery Status API is unavailable in current browsers, so do not infer
  // external power from the absence of a host signal.
  return PowerStateObserver::BatteryPowerStatus::kUnknown;
}

}  // namespace base

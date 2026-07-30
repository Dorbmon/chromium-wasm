// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "services/device/time_zone_monitor/time_zone_monitor.h"

#include <memory>

#include "base/task/sequenced_task_runner.h"

namespace device {
namespace {

// Emscripten does not expose host time-zone change notifications to this
// process. The base class captures ICU's initialized default time zone and
// reports that zone when each client registers.
class TimeZoneMonitorWasm final : public TimeZoneMonitor {
 public:
  TimeZoneMonitorWasm() = default;
  TimeZoneMonitorWasm(const TimeZoneMonitorWasm&) = delete;
  TimeZoneMonitorWasm& operator=(const TimeZoneMonitorWasm&) = delete;
  ~TimeZoneMonitorWasm() override = default;
};

}  // namespace

// static
std::unique_ptr<TimeZoneMonitor> TimeZoneMonitor::Create(
    scoped_refptr<base::SequencedTaskRunner> /*file_task_runner*/) {
  return std::make_unique<TimeZoneMonitorWasm>();
}

}  // namespace device

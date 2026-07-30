// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "gpu/config/gpu_info_collector.h"

#include "base/check.h"

namespace gpu {

bool CollectContextGraphicsInfo(GPUInfo* gpu_info) {
  DCHECK(gpu_info);

  // M3 does not create a native GL context. Leave GPUInfo unchanged and report
  // that context graphics information could not be collected.
  return false;
}

bool CollectBasicGraphicsInfo(GPUInfo* gpu_info) {
  DCHECK(gpu_info);

  // The host browser does not expose native adapter metadata to the module.
  // Do not synthesize vendor, device, or driver values.
  return false;
}

}  // namespace gpu

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/features.h"

namespace base::features {

bool IsReducePPMsEnabled() {
  // M1 does not initialize Finch or Base's process-wide feature registry.
  // Preserve the default behavior of the disabled-by-default experiment.
  return false;
}

}  // namespace base::features

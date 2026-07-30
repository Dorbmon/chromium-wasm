// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <cstddef>

#include "partition_alloc/internal/page_allocator_internal.h"

namespace partition_alloc::internal {

size_t GetZeroSegmentSizeFromOS() {
  return 0;
}

}  // namespace partition_alloc::internal

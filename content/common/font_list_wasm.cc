// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/common/font_list.h"

namespace content {

base::ListValue GetFontList_SlowBlocking() {
  // The Wasm host bridge does not expose the outer browser's installed fonts.
  // Returning no entries accurately reports that platform font enumeration is
  // unavailable without leaking host identity or inventing bundled families.
  return base::ListValue();
}

}  // namespace content

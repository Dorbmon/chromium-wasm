// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <string>

namespace syncer {

std::string GetPersonalizableDeviceNameInternal() {
  // WebAssembly has no trustworthy native device name. Use a deterministic
  // platform label rather than inspecting or exporting host identity.
  return "Chromium WebAssembly";
}

}  // namespace syncer

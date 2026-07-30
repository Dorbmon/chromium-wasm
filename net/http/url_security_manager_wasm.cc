// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/http/url_security_manager.h"

#include <memory>

namespace net {

// static
std::unique_ptr<URLSecurityManager> URLSecurityManager::Create() {
  // Non-Windows platforms use explicit allowlists. Empty allowlists deny both
  // ambient credentials and Kerberos delegation.
  return std::make_unique<URLSecurityManagerAllowlist>();
}

}  // namespace net

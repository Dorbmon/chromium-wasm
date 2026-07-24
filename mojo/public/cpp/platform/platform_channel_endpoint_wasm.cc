// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "mojo/public/cpp/platform/platform_channel_endpoint.h"

#include <string>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "platform_channel_endpoint_wasm.cc is only for WebAssembly"
#endif

namespace mojo {

PlatformChannelEndpoint::PlatformChannelEndpoint() = default;
PlatformChannelEndpoint::PlatformChannelEndpoint(
    PlatformChannelEndpoint&& other) = default;
PlatformChannelEndpoint::PlatformChannelEndpoint(PlatformHandle handle)
    : handle_(std::move(handle)) {
  CHECK(!handle_.is_valid());
}
PlatformChannelEndpoint::~PlatformChannelEndpoint() = default;
PlatformChannelEndpoint& PlatformChannelEndpoint::operator=(
    PlatformChannelEndpoint&& other) = default;

void PlatformChannelEndpoint::reset() {
  handle_.reset();
}

PlatformChannelEndpoint PlatformChannelEndpoint::Clone() const {
  CHECK(!is_valid());
  return {};
}

void PlatformChannelEndpoint::PrepareToPass(HandlePassingInfo&,
                                            std::string&) {
  CHECK(false) << "Platform channels are unsupported on WebAssembly";
}

void PlatformChannelEndpoint::PrepareToPass(HandlePassingInfo&,
                                            base::CommandLine&) {
  CHECK(false) << "Platform channels are unsupported on WebAssembly";
}

void PlatformChannelEndpoint::PrepareToPass(base::LaunchOptions&,
                                            base::CommandLine&) {
  CHECK(false) << "Process launching is unsupported on WebAssembly";
}

std::string PlatformChannelEndpoint::PrepareToPass(base::LaunchOptions&) {
  CHECK(false) << "Process launching is unsupported on WebAssembly";
}

void PlatformChannelEndpoint::ProcessLaunchAttempted() {
  reset();
}

PlatformChannelEndpoint PlatformChannelEndpoint::RecoverFromString(
    std::string_view) {
  return {};
}

}  // namespace mojo

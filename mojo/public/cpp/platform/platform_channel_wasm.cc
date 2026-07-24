// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "mojo/public/cpp/platform/platform_channel.h"

#include <string>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "platform_channel_wasm.cc is only for WebAssembly"
#endif

namespace mojo {

PlatformChannel::PlatformChannel() {
  CHECK(false) << "Platform channels are unsupported on WebAssembly";
}

PlatformChannel::PlatformChannel(PlatformChannelEndpoint local,
                                 PlatformChannelEndpoint remote)
    : local_endpoint_(std::move(local)), remote_endpoint_(std::move(remote)) {
  CHECK(false) << "Platform channels are unsupported on WebAssembly";
}
PlatformChannel::PlatformChannel(PlatformChannel&& other) = default;
PlatformChannel& PlatformChannel::operator=(PlatformChannel&& other) = default;
PlatformChannel::~PlatformChannel() = default;

void PlatformChannel::PrepareToPassRemoteEndpoint(HandlePassingInfo*,
                                                  std::string*) {
  CHECK(false) << "Platform channels are unsupported on WebAssembly";
}

std::string PlatformChannel::PrepareToPassRemoteEndpoint(
    base::LaunchOptions&) {
  CHECK(false) << "Process launching is unsupported on WebAssembly";
}

void PlatformChannel::PrepareToPassRemoteEndpoint(HandlePassingInfo*,
                                                  base::CommandLine*) {
  CHECK(false) << "Platform channels are unsupported on WebAssembly";
}

void PlatformChannel::PrepareToPassRemoteEndpoint(base::LaunchOptions*,
                                                  base::CommandLine*) {
  CHECK(false) << "Process launching is unsupported on WebAssembly";
}

void PlatformChannel::RemoteProcessLaunchAttempted() {
  remote_endpoint_.reset();
}

PlatformChannelEndpoint PlatformChannel::RecoverPassedEndpointFromString(
    std::string_view) {
  return {};
}

PlatformChannelEndpoint PlatformChannel::RecoverPassedEndpointFromCommandLine(
    const base::CommandLine&) {
  return {};
}

bool PlatformChannel::CommandLineHasPassedEndpoint(
    const base::CommandLine&) {
  return false;
}

}  // namespace mojo

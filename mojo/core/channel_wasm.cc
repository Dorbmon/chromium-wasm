// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "mojo/core/channel.h"

#include <utility>

#include "build/build_config.h"
#include "mojo/core/connection_params.h"

#if !BUILDFLAG(IS_WASM)
#error "channel_wasm.cc is only for WebAssembly"
#endif

namespace mojo::core {

scoped_refptr<Channel> Channel::Create(
    Delegate* delegate,
    ConnectionParams connection_params,
    HandlePolicy handle_policy,
    scoped_refptr<base::SingleThreadTaskRunner> io_task_runner) {
  // M1 has no remote node and therefore no platform transport to construct.
  return nullptr;
}

}  // namespace mojo::core

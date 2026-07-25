// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/debug/debugger.h"

#include <emscripten.h>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "debugger_wasm.cc must only be built for WebAssembly"
#endif

namespace base::debug {

bool BeingDebugged() {
  // Browser APIs do not reveal whether developer tools are attached.
  return false;
}

void VerifyDebugger() {}

void BreakDebuggerAsyncSafe() {
  emscripten_debugger();
}

}  // namespace base::debug

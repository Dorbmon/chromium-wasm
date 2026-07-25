// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/debug/stack_trace.h"

#include <stdio.h>

#include <ostream>

#include "base/containers/span.h"
#include "base/strings/cstring_view.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "stack_trace_wasm.cc must only be built for WebAssembly"
#endif

namespace base::debug {

bool EnableInProcessStackDumping() {
  // Wasm traps are surfaced by the host harness; there are no native signals
  // on which Chromium can install an in-process stack dumper.
  return false;
}

size_t CollectStackTrace(span<const void*> trace) {
  if (trace.empty()) {
    return 0;
  }

  // Clang supports the immediate caller address for wasm32. Deeper native
  // unwinding is not available without host JavaScript stack processing.
  trace[0] = __builtin_return_address(0);
  return trace[0] ? 1u : 0u;
}

// static
void StackTrace::PrintMessageWithPrefix(cstring_view prefix_string,
                                        cstring_view message) {
  (void)fwrite(prefix_string.data(), 1, prefix_string.size(), stderr);
  (void)fwrite(message.data(), 1, message.size(), stderr);
}

void StackTrace::PrintWithPrefixImpl(cstring_view prefix_string) const {
  for (const void* address : addresses()) {
    fprintf(stderr, "%.*s%p\n", static_cast<int>(prefix_string.size()),
            prefix_string.data(), address);
  }
}

void StackTrace::OutputToStreamWithPrefixImpl(
    std::ostream* os,
    cstring_view prefix_string) const {
  for (const void* address : addresses()) {
    *os << prefix_string << address << '\n';
  }
}

}  // namespace base::debug

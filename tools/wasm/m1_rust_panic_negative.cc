// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/threading.h>

#include <cstdio>

#include "build/build_config.h"
#include "tools/wasm/m1_rust_smoke.rs.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_rust_panic_negative must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_RUST_PANIC";

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

}  // namespace

int main() {
  if (emscripten_is_main_browser_thread()) {
    return Fail("application_main_on_browser_thread");
  }
  if (emscripten_is_main_runtime_thread()) {
    return Fail("application_main_on_runtime_thread");
  }
  if (!emscripten_has_threading_support()) {
    return Fail("pthread_support_unavailable");
  }

  std::fprintf(stdout, "%s:RUNTIME_START\n", kPrefix);
  std::fprintf(
      stdout,
      "%s:PANIC_TRIGGER marker=chromium_wasm_m1_expected_panic\n",
      kPrefix);
  std::fflush(stdout);

  chromium_wasm::rust_smoke::TriggerExpectedPanic();

  std::fprintf(stdout, "%s:FALSE_SUCCESS panic_returned\n", kPrefix);
  std::fflush(stdout);
  return Fail("panic_returned");
}

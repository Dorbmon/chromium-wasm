// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/emscripten.h>
#include <emscripten/threading.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <thread>

#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "hello_wasm must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

#if !defined(ARCH_CPU_WASM_FAMILY) || !defined(ARCH_CPU_WASM32)
#error "WebAssembly CPU macros are missing"
#endif

#if !defined(ARCH_CPU_32_BITS) || !defined(ARCH_CPU_LITTLE_ENDIAN)
#error "WebAssembly representation macros are missing"
#endif

#if !defined(ARCH_CPU_NO_NATIVE_EXECUTABLE_MEMORY)
#error "WebAssembly must not advertise native executable memory"
#endif

namespace {

std::atomic<int> g_static_constructor_count{0};
thread_local int g_thread_local_value = 7;

class StaticConstructorProbe {
 public:
  StaticConstructorProbe() { ++g_static_constructor_count; }
};

StaticConstructorProbe g_static_constructor_probe;

int Fail(const char* reason) {
  std::fprintf(stderr, "CHROMIUM_WASM_M0:FAIL reason=%s\n", reason);
  std::fflush(stderr);
  return 1;
}

}  // namespace

int main() {
  static_assert(sizeof(void*) == 4);
  static_assert(sizeof(wchar_t) == 4);

  if (emscripten_is_main_browser_thread()) {
    return Fail("application_main_on_browser_thread");
  }
  if (emscripten_is_main_runtime_thread()) {
    return Fail("application_main_on_runtime_thread");
  }
  if (!emscripten_has_threading_support()) {
    return Fail("pthread_support_unavailable");
  }
  if (g_static_constructor_count.load() != 1) {
    return Fail("static_constructor");
  }
  if (g_thread_local_value != 7) {
    return Fail("application_thread_local");
  }

  std::fprintf(stdout, "CHROMIUM_WASM_M0:RUNTIME_START\n");
  std::fflush(stdout);

  std::atomic<int> phase{0};
  std::atomic<bool> worker_succeeded{false};
  std::thread worker([&phase, &worker_succeeded] {
    g_thread_local_value = 41;
    phase.store(1, std::memory_order_release);
    phase.notify_one();
    phase.wait(1, std::memory_order_acquire);
    worker_succeeded.store(
        phase.load(std::memory_order_acquire) == 2 &&
            g_thread_local_value == 41,
        std::memory_order_release);
  });

  phase.wait(0, std::memory_order_acquire);
  phase.store(2, std::memory_order_release);
  phase.notify_one();
  worker.join();

  if (!worker_succeeded.load(std::memory_order_acquire)) {
    return Fail("pthread_atomic_wake_or_thread_local");
  }

  const auto steady_start = std::chrono::steady_clock::now();
  const double emscripten_start = emscripten_get_now();
  std::this_thread::sleep_for(std::chrono::milliseconds(250));
  const auto steady_elapsed = std::chrono::steady_clock::now() - steady_start;
  const double emscripten_elapsed = emscripten_get_now() - emscripten_start;

  if (steady_elapsed < std::chrono::milliseconds(200)) {
    return Fail("steady_clock");
  }
  if (emscripten_elapsed < 200.0) {
    return Fail("emscripten_timer");
  }

  std::fprintf(stdout, "CHROMIUM_WASM_M0:RUNTIME_END\n");
  std::fprintf(stdout,
               "CHROMIUM_WASM_M0:STDOUT pthread=ok atomic_wake=ok timer=ok "
               "static_constructor=ok thread_local=ok\n");
  std::fprintf(stderr, "CHROMIUM_WASM_M0:STDERR capture=ok\n");
  std::fprintf(stdout, "CHROMIUM_WASM_M0:PASS\n");
  std::fflush(stdout);
  std::fflush(stderr);
  return 0;
}

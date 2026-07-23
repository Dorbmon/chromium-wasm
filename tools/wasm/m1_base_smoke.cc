// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/threading.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <thread>

#include "base/containers/span.h"
#include "base/rand_util.h"
#include "base/time/time.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_base_smoke must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_BASE";

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

bool HasNonZeroByte(base::span<const uint8_t> bytes) {
  return std::ranges::any_of(bytes, [](uint8_t byte) { return byte != 0; });
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
  std::fflush(stdout);

  const base::Time wall_start = base::Time::Now();
  if (wall_start.InMillisecondsSinceUnixEpoch() < 1577836800000LL) {
    return Fail("wall_clock_not_plausible");
  }

  base::TimeTicks previous = base::TimeTicks::Now();
  for (int i = 0; i < 1000; ++i) {
    const base::TimeTicks current = base::TimeTicks::Now();
    if (current < previous) {
      return Fail("monotonic_clock_went_backwards");
    }
    previous = current;
  }

  const base::TimeTicks sleep_start = base::TimeTicks::Now();
  std::this_thread::sleep_for(std::chrono::milliseconds(250));
  const base::TimeDelta slept = base::TimeTicks::Now() - sleep_start;
  if (slept < base::Milliseconds(200) || slept > base::Seconds(5)) {
    return Fail("bounded_sleep_elapsed");
  }
  if (base::Time::Now() <= wall_start) {
    return Fail("wall_clock_did_not_progress");
  }
  if (!base::TimeTicks::IsHighResolution() ||
      !base::TimeTicks::IsConsistentAcrossProcesses() ||
      base::TimeTicks::GetClock() !=
          base::TimeTicks::Clock::WASM_EMSCRIPTEN_GET_NOW) {
    return Fail("monotonic_clock_metadata");
  }
  if (base::ThreadTicks::IsSupported()) {
    return Fail("thread_cpu_clock_claimed_supported");
  }

  std::array<uint8_t, 513> first{};
  std::array<uint8_t, 513> second{};
  base::RandBytes(first);
  base::RandBytes(second);
  if (!HasNonZeroByte(first) || !HasNonZeroByte(second)) {
    return Fail("secure_entropy_all_zero");
  }
  if (first == second) {
    return Fail("secure_entropy_buffers_equal");
  }

  bool worker_succeeded = false;
  std::thread worker([&worker_succeeded] {
    std::array<uint8_t, 257> worker_bytes{};
    base::RandBytes(worker_bytes);
    worker_succeeded = HasNonZeroByte(worker_bytes);
  });
  worker.join();
  if (!worker_succeeded) {
    return Fail("worker_secure_entropy");
  }

  std::fprintf(stdout, "%s:RUNTIME_END\n", kPrefix);
  std::fprintf(stdout,
               "%s:RESULT wall_time=ok monotonic_time=ok bounded_sleep=ok "
               "secure_entropy=ok worker_entropy=ok\n",
               kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}

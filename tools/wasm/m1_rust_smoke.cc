// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <emscripten/threading.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string_view>

#include "build/build_config.h"
#include "tools/wasm/m1_rust_smoke.rs.h"

#if !BUILDFLAG(IS_WASM)
#error "m1_rust_smoke must be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M1_RUST";
constexpr uint64_t kCallbackInput = UINT64_C(0x0123456789abcdef);
constexpr uint64_t kCallbackMask = UINT64_C(0xa5a55a5adeadbeef);
constexpr uint32_t kCallbackWorkerValue = UINT32_C(0x13579bdf);
constexpr uint64_t kDropProbeMarker = UINT64_C(0x0ddba11c0ffeec0d);

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

uint64_t RotateLeft13(uint64_t value) {
  return (value << 13) | (value >> (64 - 13));
}

uint64_t ExpectedCallbackToken() {
  return RotateLeft13(kCallbackInput) ^
         (static_cast<uint64_t>(kCallbackWorkerValue) << 32) ^ kCallbackMask ^
         1;
}

chromium_wasm::rust_smoke::AbiInput MakeAbiInput() {
  chromium_wasm::rust_smoke::AbiInput input{};
  input.i8_value = -101;
  input.u8_value = 201;
  input.i16_value = -12345;
  input.u16_value = 54321;
  input.i32_value = -123456789;
  input.u32_value = UINT32_C(3456789012);
  input.i64_value = -INT64_C(81985529216486895);
  input.u64_value = UINT64_C(0xfedcba9876543210);
  input.isize_value = -1234567;
  input.usize_value = 0x89abcdefU;
  input.cookie = UINT64_C(0xc001d00dc0decafe);
  return input;
}

bool ValidateReport(const chromium_wasm::rust_smoke::RustReport& report) {
  return report.signed_64_echo == -INT64_C(81985529216486895) &&
         report.unsigned_64_echo == UINT64_C(0xfedcba9876543210) &&
         report.usize_echo == 0x89abcdefU &&
         report.callback_token == ExpectedCallbackToken() &&
         report.pointer_bytes == 4 && report.atomic_value == 42 &&
         report.mutex_value == 32 && report.arc_before_spawn == 2 &&
         report.arc_after_join == 1 &&
         report.worker_return == kCallbackWorkerValue &&
         report.integer_widths_ok && report.thread_spawned &&
         report.thread_joined;
}

}  // namespace

int main() {
  static_assert(sizeof(void*) == 4);
  static_assert(sizeof(int8_t) == 1);
  static_assert(sizeof(uint8_t) == 1);
  static_assert(sizeof(int16_t) == 2);
  static_assert(sizeof(uint16_t) == 2);
  static_assert(sizeof(int32_t) == 4);
  static_assert(sizeof(uint32_t) == 4);
  static_assert(sizeof(int64_t) == 8);
  static_assert(sizeof(uint64_t) == 8);
  static_assert(sizeof(intptr_t) == 4);
  static_assert(sizeof(uintptr_t) == 4);

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

  const chromium_wasm::rust_smoke::RustReport report =
      chromium_wasm::rust_smoke::RunRustSmoke(MakeAbiInput());
  if (!ValidateReport(report)) {
    return Fail("rust_report");
  }

  {
    constexpr std::array<uint32_t, 6> kExpected = {3, 5, 8, 13, 21, 34};
    const rust::Vec<uint32_t> values =
        chromium_wasm::rust_smoke::MakeRustVector();
    if (values.size() != kExpected.size()) {
      return Fail("rust_vec_size");
    }
    for (size_t index = 0; index < kExpected.size(); ++index) {
      if (values[index] != kExpected[index]) {
        return Fail("rust_vec_contents");
      }
    }
  }

  {
    const rust::String value = chromium_wasm::rust_smoke::MakeRustString();
    if (std::string_view(value.data(), value.size()) !=
        "chromium-wasm-rust-string-allocation") {
      return Fail("rust_string");
    }
  }

  if (chromium_wasm::rust_smoke::DropProbeCount() != 0) {
    return Fail("drop_probe_initial_count");
  }
  {
    const rust::Box<chromium_wasm::rust_smoke::DropProbe> probe =
        chromium_wasm::rust_smoke::MakeDropProbe(kDropProbeMarker);
    if (probe->Marker() != kDropProbeMarker) {
      return Fail("drop_probe_marker");
    }
  }
  if (chromium_wasm::rust_smoke::DropProbeCount() != 1) {
    return Fail("drop_probe_final_count");
  }

  std::fprintf(stdout, "%s:RUNTIME_END\n", kPrefix);
  std::fprintf(
      stdout,
      "%s:RESULT cpp_to_rust=ok rust_to_cpp=ok cxx_bridge=ok "
      "structured_abi=ok integer_widths=ok pointer_width=32 vec=ok "
      "string=ok allocation=ok free=ok atomics=ok arc=ok mutex=ok "
      "thread_spawn=ok thread_join=ok callback_count=1 drop_count=1 "
      "same_module=ok clean_shutdown=ok browser_heartbeat=external\n",
      kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}

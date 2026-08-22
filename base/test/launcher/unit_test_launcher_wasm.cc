// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/test/launcher/unit_test_launcher.h"

#include <utility>

#include "base/check.h"
#include "base/command_line.h"
#include "base/test/allow_check_is_test_for_testing.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "unit_test_launcher_wasm.cc must only be built for WebAssembly"
#endif

namespace base {

namespace {

int RunUnitTestsInWasmProcess(int argc,
                              char** argv,
                              RunTestSuiteCallback run_test_suite) {
  test::AllowCheckIsTestForTesting();
  CHECK(CommandLine::InitializedForCurrentProcess() ||
        CommandLine::Init(argc, argv));
  return std::move(run_test_suite).Run();
}

}  // namespace

int LaunchUnitTests(int argc,
                    char** argv,
                    RunTestSuiteCallback run_test_suite,
                    size_t /*retry_limit*/) {
  return RunUnitTestsInWasmProcess(argc, argv, std::move(run_test_suite));
}

int LaunchUnitTestsSerially(int argc,
                            char** argv,
                            RunTestSuiteCallback run_test_suite) {
  return RunUnitTestsInWasmProcess(argc, argv, std::move(run_test_suite));
}

}  // namespace base

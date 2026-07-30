#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


BLOCKFILE_SOURCES = (
    "addr.cc",
    "backend_impl.cc",
    "bitmap.cc",
    "block_files.cc",
    "disk_format.cc",
    "entry_impl.cc",
    "eviction.cc",
    "file.cc",
    "file_lock.cc",
    "in_flight_backend_io.cc",
    "in_flight_io.cc",
    "mapped_file.cc",
    "rankings.cc",
    "sparse_control.cc",
    "stats.cc",
)


class M3NetDiskCacheSourceContractTest(unittest.TestCase):
    def test_wasm_selects_only_real_simple_cache_platform_helpers(
        self,
    ) -> None:
        build = source("net/BUILD.gn")
        wasm_sources = build.split(
            "  if (is_wasm) {\n"
            "    sources += [\n"
            '      "base/file_stream_context_wasm.cc",',
            1,
        )[1].split("  if (is_posix || is_fuchsia)", 1)[0]

        self.assertIn('"disk_cache/cache_util_wasm.cc",', wasm_sources)
        self.assertIn(
            '"disk_cache/simple/simple_util_wasm.cc",', wasm_sources
        )
        self.assertNotIn("cache_util_posix.cc", wasm_sources)
        self.assertNotIn("simple_util_posix.cc", wasm_sources)
        self.assertNotIn("file_posix.cc", wasm_sources)
        self.assertNotIn("mapped_file_posix.cc", wasm_sources)

        for basename in BLOCKFILE_SOURCES:
            self.assertIn(
                f'"disk_cache/blockfile/{basename}",', wasm_sources
            )
        self.assertFalse(
            (ROOT_DIR / "net/disk_cache/blockfile/mapped_file_wasm.cc").exists()
        )
        self.assertFalse(
            (ROOT_DIR / "net/disk_cache/blockfile/file_wasm.cc").exists()
        )

    def test_wasm_helpers_propagate_real_filesystem_results(self) -> None:
        move = source("net/disk_cache/cache_util_wasm.cc")
        delete = source("net/disk_cache/simple/simple_util_wasm.cc")

        self.assertIn(
            '#error "cache_util_wasm.cc must only be built for WebAssembly"',
            move,
        )
        self.assertIn("return base::Move(from_path, to_path);", move)
        self.assertNotIn("return true;", move)
        self.assertNotIn("mmap", move)

        self.assertIn(
            '#error "simple_util_wasm.cc must only be built for '
            'WebAssembly"',
            delete,
        )
        self.assertIn("return base::DeleteFile(path);", delete)
        self.assertNotIn("return true;", delete)

    def test_wasm_http_cache_selection_cannot_be_overridden(self) -> None:
        experiment = source("net/disk_cache/backend_experiment.h")
        configurator = source(
            "components/network_session_configurator/browser/"
            "network_session_configurator.cc"
        )
        chooser = configurator.split(
            "net::URLRequestContextBuilder::HttpCacheParams::Type "
            "ChooseCacheType() {",
            1,
        )[1].split("}  // namespace network_session_configurator", 1)[0]

        self.assertIn("BUILDFLAG(IS_WASM)", experiment)
        wasm_return = (
            "#if BUILDFLAG(IS_WASM)\n"
            "  // The blockfile backend requires writable MAP_SHARED "
            "mappings, which the\n"
            "  // Wasm filesystem cannot provide. Do not let a field trial "
            "select it.\n"
            "  return net::URLRequestContextBuilder::HttpCacheParams::"
            "DISK_SIMPLE;\n"
            "#else"
        )
        self.assertIn(wasm_return, chooser)
        self.assertLess(
            chooser.index(wasm_return),
            chooser.index("kDiskCacheBackendExperiment"),
        )

    def test_cache_creator_has_no_wasm_blockfile_link_edge(self) -> None:
        implementation = source("net/disk_cache/disk_cache.cc")

        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            '#include "net/disk_cache/blockfile/backend_impl.h"\n'
            "#endif",
            implementation,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_ANDROID) || BUILDFLAG(IS_FUCHSIA) || "
            "BUILDFLAG(IS_WASM)\n"
            "  static const bool kSimpleBackendIsDefault = true;",
            implementation,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_ANDROID) || BUILDFLAG(IS_WASM)\n"
            "  FailAttempt();\n"
            "#else\n"
            "  auto cache = std::make_unique<disk_cache::BackendImpl>",
            implementation,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  // Block backend.\n"
            "  BackendImpl::FlushForTesting();\n"
            "#endif",
            implementation,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  constexpr int kBackendCount = 1;\n"
            "#else\n"
            "  constexpr int kBackendCount = 2;\n"
            "#endif",
            implementation,
        )
        self.assertIn(
            "#if !BUILDFLAG(IS_WASM)\n"
            "  // Block backend.\n"
            "  BackendImpl::FlushAsynchronouslyForTesting("
            "repeating_callback);\n"
            "#endif",
            implementation,
        )
        self.assertNotIn("MappedFile", implementation)

    def test_simple_backend_uses_base_file_without_mapping_or_locking(
        self,
    ) -> None:
        basic_file = source("net/disk_cache/basic_cache_file.cc")
        operations = source("net/disk_cache/disk_cache.cc")
        simple_sources = "\n".join(
            source(path)
            for path in (
                "net/disk_cache/simple/simple_backend_impl.cc",
                "net/disk_cache/simple/simple_entry_impl.cc",
                "net/disk_cache/simple/simple_synchronous_entry.cc",
            )
        )

        for method in ("Read", "Write", "GetInfo", "SetLength"):
            self.assertIn(f"file_.{method}(", basic_file)
        for operation in (
            "base::CreateDirectory(path)",
            "base::DeleteFile(path)",
            "base::ReplaceFile(from_path, to_path, error)",
        ):
            self.assertIn(operation, operations)
        for unsupported_primitive in ("MappedFile", "mmap(", ".Lock("):
            self.assertNotIn(unsupported_primitive, simple_sources)

    def test_blockfile_experiment_expectation_is_platform_aware(self) -> None:
        test = source(
            "components/network_session_configurator/browser/"
            "network_session_configurator_unittest.cc"
        )
        blockfile_test = test.split(
            "TEST_F(NetworkSessionConfiguratorTest, "
            "DiskCacheExperimentBlockfileBackend)",
            1,
        )[1].split(
            "TEST_F(NetworkSessionConfiguratorTest, "
            "DiskCacheExperimentDefaultBackend)",
            1,
        )[0]

        self.assertIn("#if BUILDFLAG(IS_WASM)", blockfile_test)
        self.assertIn("HttpCacheParams::DISK_SIMPLE", blockfile_test)
        self.assertIn("HttpCacheParams::DISK_BLOCKFILE", blockfile_test)

    def test_runtime_smoke_covers_memfs_round_trip_and_explicit_failure(
        self,
    ) -> None:
        build = source("tools/wasm/BUILD.gn")
        smoke = source("tools/wasm/m3_disk_cache_smoke.cc")
        harness = source("tools/wasm/serve.py")

        self.assertIn('executable("m3_disk_cache_smoke")', build)
        self.assertIn('"//net",', build)
        for behavior in (
            "disk_cache::MoveCache(source, destination)",
            "CACHE_BACKEND_DEFAULT",
            'value == "Simple Cache"',
            "WriteEntryAndWait",
            "OpenEntryAndWait",
            "FlushCacheThreadAsynchronouslyForTesting",
        ):
            self.assertIn(behavior, smoke)

        delete_contract = smoke.split(
            "const base::FilePath delete_path", 1
        )[1].split("return nullptr;", 1)[0]
        delete_steps = (
            "base::File old_file(delete_path,",
            "old_file.IsValid()",
            "SimpleCacheDeleteFile(delete_path)",
            "base::WriteFile(delete_path, kNewDeletePayload)",
            "base::ReadFileToString(delete_path, &reused_contents)",
            "old_file.ReadAndCheck(/*offset=*/0, base::span(old_contents))",
            "memcmp(old_contents.data(), kOldDeletePayload, "
            "old_contents.size())",
        )
        delete_positions = [
            delete_contract.index(step) for step in delete_steps
        ]
        self.assertEqual(delete_positions, sorted(delete_positions))

        blockfile_contract = smoke.split(
            "const char* TestExplicitBlockfileFailure", 1
        )[1].split("}  // namespace", 1)[0]
        before_run, after_run = blockfile_contract.split(
            "run_loop.Run();", 1
        )
        self.assertIn("CACHE_BACKEND_BLOCKFILE", before_run)
        self.assertIn(
            "initial_result.net_error != net::ERR_IO_PENDING", before_run
        )
        self.assertIn(
            "initial_result.backend || callback_called", before_run
        )
        self.assertNotIn("callback_result.net_error", before_run)
        self.assertIn(
            "!callback_called || callback_result.net_error != "
            "net::ERR_FAILED",
            after_run,
        )
        self.assertIn("callback_result.backend", after_run)
        self.assertIn('PrintPhase("blockfile_failure_contract")', smoke)

        self.assertIn('"disk_cache": SmokeCase(', harness)
        self.assertIn('"delete_open_reuse": "ok"', harness)
        self.assertIn('"blockfile": "unsupported_async"', harness)


if __name__ == "__main__":
    unittest.main()

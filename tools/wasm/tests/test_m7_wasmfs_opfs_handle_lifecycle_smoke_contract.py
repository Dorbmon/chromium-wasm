#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the isolated M7 bounded OPFS lifecycle binary."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M7WasmfsOpfsHandleLifecycleSmokeContractTest(unittest.TestCase):
    def test_target_keeps_wasmfs_out_of_chrome_and_other_m7_targets(self) -> None:
        root_build = source("BUILD.gn")
        wasm_tools_build = source("tools/wasm/BUILD.gn")
        chrome_build = source("chrome/BUILD.gn")

        self.assertIn(
            'config("m7_wasmfs_opfs_handle_lifecycle_smoke_link")',
            wasm_tools_build,
        )
        self.assertIn('ldflags = [ "-sWASMFS=1" ]', wasm_tools_build)
        self.assertIn(
            'executable("m7_wasmfs_opfs_handle_lifecycle_smoke")',
            wasm_tools_build,
        )
        self.assertIn(
            'sources = [ "m7_wasmfs_opfs_handle_lifecycle_smoke.cc" ]',
            wasm_tools_build,
        )
        self.assertIn(
            '"//tools/wasm:m7_wasmfs_opfs_handle_lifecycle_smoke($default_toolchain)",',
            root_build,
        )
        self.assertNotIn("m7_wasmfs_opfs_handle_lifecycle_smoke", chrome_build)

    def test_source_keeps_strict_role_thread_and_mount_contract(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_handle_lifecycle_smoke.cc")

        for token in (
            '#if !BUILDFLAG(IS_WASM)',
            '#if BUILDFLAG(IS_POSIX)',
            'constexpr char kHolderRole[] = "holder";',
            'constexpr char kReopenRole[] = "reopen";',
            'constexpr char kVerifyRole[] = "verify";',
            'constexpr char kRolePrefix[] = "--m7-opfs-role=";',
            'constexpr char kRunPrefix[] = "--m7-opfs-run=";',
            'constexpr size_t kPathCount = 32;',
            "bool IsValidRunId(std::string_view run_id)",
            "wasmfs_create_opfs_backend()",
            'wasmfs_create_directory("/opfs", 0700, backend)',
            "emscripten_is_main_browser_thread()",
            "emscripten_has_threading_support()",
            "emscripten_exit_with_live_runtime();",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)

        self.assertIn("application_main_on_browser_thread", smoke)
        self.assertIn("pthread_support_unavailable", smoke)
        self.assertNotIn("F_SETLK", smoke)
        self.assertNotIn("F_SETLKW", smoke)

    def test_holder_closes_32_distinct_paths_before_its_live_marker(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_handle_lifecycle_smoke.cc")
        holder = re.search(
            r"\[\[noreturn\]\] void RunHolder\(const Paths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(holder)
        body = holder.group("body")
        for token in (
            "mkdir(paths.root.c_str(), 0700)",
            "for (size_t index = 0; index < paths.files.size(); ++index)",
            "O_CREAT | O_EXCL | O_RDWR",
            "RequireExactWrite",
            "fdatasync(descriptor)",
            "close(descriptor)",
            "kHolderClosedMarker",
            "RetainLiveRuntime();",
        ):
            with self.subTest(token=token):
                self.assertIn(token, body)
        self.assertLess(body.index("fdatasync(descriptor)"), body.index("close(descriptor)"))
        self.assertLess(body.index("close(descriptor)"), body.index("kHolderClosedMarker"))
        self.assertLess(
            body.index("kHolderClosedMarker"), body.index("RetainLiveRuntime();")
        )
        self.assertIn('paths.root = "/opfs/" + run_id;', smoke)
        self.assertIn('paths.root + "/entry-" + std::to_string(index)', smoke)
        self.assertIn("paths.files[left] != paths.files[right]", smoke)

    def test_reopen_and_fresh_verifier_close_before_reaping(self) -> None:
        smoke = source("tools/wasm/m7_wasmfs_opfs_handle_lifecycle_smoke.cc")
        reopen = re.search(
            r"\[\[noreturn\]\] void RunReopen\(const Paths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        verify = re.search(
            r"\[\[noreturn\]\] void RunVerifyAndReap\(const Paths& paths\) "
            r"\{(?P<body>.*?)\n\}",
            smoke,
            re.DOTALL,
        )
        self.assertIsNotNone(reopen)
        self.assertIsNotNone(verify)
        reopen_body = reopen.group("body")
        verify_body = verify.group("body")
        for token in (
            "open(paths.files[index].c_str(), O_RDWR)",
            "RequireExactRead",
            "fdatasync(descriptor)",
            "close(descriptor)",
            "kReopenClosedMarker",
            "RetainLiveRuntime();",
        ):
            with self.subTest(role="reopen", token=token):
                self.assertIn(token, reopen_body)
        for token in (
            "open(paths.files[index].c_str(), O_RDWR)",
            "RequireExactRead",
            "close(descriptor)",
            "unlink(path.c_str())",
            "rmdir(paths.root.c_str())",
            "kVerifyReapMarker",
            "RetainLiveRuntime();",
        ):
            with self.subTest(role="verify", token=token):
                self.assertIn(token, verify_body)
        self.assertLess(
            verify_body.index("close(descriptor)"), verify_body.index("unlink(path.c_str())")
        )
        self.assertLess(
            verify_body.index("unlink(path.c_str())"),
            verify_body.index("rmdir(paths.root.c_str())"),
        )

    def test_host_keeps_opfs_operations_inside_wasmfs_and_limits_claims(self) -> None:
        host = source("tools/wasm/host/m7_wasmfs_opfs_handle_lifecycle_smoke.js")

        for token in (
            'const MODULE_NAME = "m7_wasmfs_opfs_handle_lifecycle_smoke";',
            'const EXERCISE_PHASE = "exercise";',
            'const VERIFY_PHASE = "verify";',
            "const CAPABILITY_PROBE_SOURCE = `",
            "async function probeRequiredOpfsCapability(deadline, progress)",
            "const holder = startRuntime",
            "const reopen = startRuntime",
            "await requireLiveCompletion(holder, deadline, \"holder-marker\"",
            "await requireLiveCompletion(reopen, deadline, \"reopen-marker\"",
            "location.replace(verifyUrl.href);",
            'browserHandleLimitObserved: false',
            'handleExhaustionProven: false',
            'allocatorReuseObservable: false',
            'profilePersistenceProven: false',
            'sqliteLeveldbLockSemanticsProven: false',
            'crashRecoveryProven: false',
        ):
            with self.subTest(token=token):
                self.assertIn(token, host)
        self.assertLess(
            host.index("await requireLiveCompletion(holder, deadline, \"holder-marker\""),
            host.index("const reopen = startRuntime"),
        )
        self.assertLess(
            host.index("await postResult(context, result);"),
            host.index("location.replace(verifyUrl.href);"),
        )
        for forbidden in (
            "navigator.storage.getDirectory(",
            ".createSyncAccessHandle(",
            ".getFile(",
            ".createWritable(",
            ".removeEntry(",
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "IDBFS",
            "MEMFS",
            "FS.syncfs",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)


if __name__ == "__main__":
    unittest.main()

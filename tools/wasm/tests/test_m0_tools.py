#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
from collections import deque
import hashlib
from io import BytesIO
from io import StringIO
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import bootstrap
import m0_common
from m0_common import M0Error, gn_args_text, load_manifest, parse_timeout, run
import run_browser_smoke
import run_node_smoke
import serve


BASE_RESULT_LINE = (
    "CHROMIUM_WASM_M1_BASE:RESULT "
    + " ".join(
        f"{key}={value}" for key, value in serve.BASE_RESULT_VALUES.items()
    )
)
TASK_RESULT_NUMERIC_VALUES = {
    "wake_count": "3",
    "wait_count": "1",
    "idle_wake_returns": "1",
    "worker_to_app_latency_ms": "0",
    "sleeping_quit_latency_ms": "0",
    "idle_elapsed_ms": "250",
    "idle_wake_latency_ms": "0",
}
TASK_RESULT_LINE = (
    "CHROMIUM_WASM_M1_TASK:RESULT "
    + " ".join(
        (
            *(
                f"{key}={value}"
                for key, value in serve.TASK_RESULT_VALUES.items()
            ),
            *(
                f"{key}={value}"
                for key, value in TASK_RESULT_NUMERIC_VALUES.items()
            ),
        )
    )
)
RUST_RESULT_LINE = (
    "CHROMIUM_WASM_M1_RUST:RESULT "
    + " ".join(
        f"{key}={value}" for key, value in serve.RUST_RESULT_VALUES.items()
    )
)
V8_BASE_RESULT_LINE = (
    "CHROMIUM_WASM_M2_V8_BASE:RESULT "
    + " ".join(
        f"{key}={value}"
        for key, value in serve.V8_BASE_RESULT_VALUES.items()
    )
)
V8_SNAPSHOTLESS_RESULT_NUMERIC_VALUES = {
    "native_callback_calls": "6",
    "feature_cycles": "3",
    "gc_cycles": "3",
    "module_cycles": "3",
    "module_resolve_calls": "3",
    "timer_delay_ms": "25",
    "timer_elapsed_us": "25581",
    "timer_cycles": "1",
    "test262_license_bytes": "2213",
    "test262_license_fnv1a": "1790394517849644",
    "test262_embedded_source_bytes": "40217",
    "test262_cases": "14",
    "test262_executions": "25",
    "test262_passed": "25",
    "test262_failed": "0",
    "test262_scripts": "22",
    "test262_modules": "3",
    "test262_strict": "14",
    "test262_sloppy": "11",
    "test262_async": "4",
    "test262_negative_parse": "2",
    "test262_negative_runtime": "2",
    "test262_negative_resolution": "1",
    "test262_detach_calls": "2",
    "test262_resolver_calls": "5",
    "test262_module_compile_attempts": "7",
    "test262_runtime_ms": "68",
    "snapshot_bytes": "288812",
    "snapshot_create_ms": "1965",
    "isolate_runs_ms": "71",
    "runtime_ms": "2043",
    "v8_heap_total_max_sampled_bytes": "786432",
    "v8_heap_used_max_sampled_bytes": "120368",
    "v8_heap_physical_max_sampled_bytes": "786432",
    "v8_malloced_max_sampled_bytes": "32812",
    "v8_peak_malloced_bytes": "98576",
    "v8_external_max_sampled_bytes": "2097189",
    "v8_heap_limit_bytes": "834666496",
    "v8_total_allocated_max_per_isolate_bytes": "4334152",
    "v8_shared_read_only_used_bytes": "1764660",
    "array_buffer_peak_bytes": "2097168",
    "wasm_linear_initial_bytes": "67108864",
    "wasm_linear_after_cycle_1_bytes": "598999040",
    "wasm_linear_after_cycle_2_bytes": "598999040",
    "wasm_linear_after_cycle_3_bytes": "598999040",
    "wasm_linear_peak_bytes": "598999040",
    "wasm_linear_limit_bytes": "2147483648",
}
V8_SNAPSHOTLESS_RESULT_LINE = (
    "CHROMIUM_WASM_M2_V8_JS:RESULT "
    + " ".join(
        f"{key}={value}"
        for key, value in serve.V8_SNAPSHOTLESS_RESULT_VALUES.items()
    )
    + " "
    + " ".join(
        f"{key}={value}"
        for key, value in V8_SNAPSHOTLESS_RESULT_NUMERIC_VALUES.items()
    )
)
V8_SNAPSHOTLESS_STAGE_LINES = tuple(
    f"CHROMIUM_WASM_M2_V8_JS:STAGE name={name}"
    for name in serve.V8_SNAPSHOTLESS_STAGE_NAMES
)
V8_SNAPSHOTLESS_TEST262_CASE_LINES = (
    serve.V8_SNAPSHOTLESS_TEST262_CASE_LINES
)
V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE = (
    serve.V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE
)
SHARED_MEMORY_RESULT_LINE = (
    "CHROMIUM_WASM_M1_SHARED_MEMORY:RESULT "
    + " ".join(
        f"{key}={value}"
        for key, value in serve.SHARED_MEMORY_RESULT_VALUES.items()
    )
)
SHARED_MEMORY_METRICS_LINE = (
    "CHROMIUM_WASM_M1_SHARED_MEMORY:METRICS "
    "initial_heap_bytes=67108864 peak_heap_bytes=67108864 "
    "max_heap_bytes=2147483648"
)
MOJO_RESULT_LINE = (
    "CHROMIUM_WASM_M1_MOJO:RESULT "
    + " ".join(
        f"{key}={value}"
        for key, value in serve.MOJO_RESULT_VALUES.items()
    )
)
MOJO_METRICS_LINE = (
    "CHROMIUM_WASM_M1_MOJO:METRICS "
    "initial_heap_bytes=67108864 peak_heap_bytes=67108864 "
    "max_heap_bytes=2147483648"
)


DRIVER_PATH = (
    TOOLS_DIR.parents[1] / "build/toolchain/wasm/emscripten_driver.py"
)
DRIVER_SPEC = importlib.util.spec_from_file_location(
    "chromium_wasm_emscripten_driver", DRIVER_PATH
)
assert DRIVER_SPEC is not None and DRIVER_SPEC.loader is not None
emscripten_driver = importlib.util.module_from_spec(DRIVER_SPEC)
DRIVER_SPEC.loader.exec_module(emscripten_driver)


class ManifestTest(unittest.TestCase):
    def test_manifest_has_primary_wasm_args(self) -> None:
        manifest = load_manifest()
        arguments = gn_args_text(manifest)
        self.assertIn('target_os = "emscripten"\n', arguments)
        self.assertIn("enable_chromium_wasm_port = true\n", arguments)
        self.assertIn("enable_rust = true\n", arguments)
        self.assertIn("is_component_build = false\n", arguments)
        self.assertIn("use_custom_libcxx = false\n", arguments)

    def test_manifest_has_reproducible_m2_v8_args(self) -> None:
        manifest = load_manifest()
        arguments = gn_args_text(manifest, "m2_v8_gn_args")
        for expected in (
            "enable_chromium_wasm_v8 = true\n",
            'v8_target_cpu = "arm"\n',
            "v8_target_is_simulator = true\n",
            "v8_jitless = true\n",
            "v8_enable_webassembly = false\n",
            "v8_enable_sparkplug = false\n",
            "v8_enable_maglev = false\n",
            "v8_enable_turbofan = false\n",
            "v8_use_external_startup_data = false\n",
            "v8_enable_i18n_support = false\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, arguments)

    def test_manifest_has_reproducible_m3_content_args(self) -> None:
        manifest = load_manifest()
        arguments = gn_args_text(manifest, "m3_content_gn_args")
        for expected in (
            "enable_chromium_wasm_v8 = true\n",
            "enable_chromium_wasm_content = true\n",
            "use_partition_alloc = true\n",
            "use_allocator_shim = false\n",
            "use_partition_alloc_as_malloc = false\n",
            "enable_backup_ref_ptr_support = false\n",
            "safe_browsing_mode = 0\n",
            "disable_fieldtrial_testing_config = true\n",
            "chromium_wasm_pthread_pool_size = 8\n",
            "chromium_wasm_logical_processor_limit = 8\n",
            "use_aura = true\n",
            "use_ozone = true\n",
            "use_crash_key_stubs = true\n",
            "v8_use_perfetto_json_export = false\n",
            "enable_vulkan = false\n",
            "enable_swiftshader = false\n",
            "angle_shared_libvulkan = false\n",
            "angle_build_vulkan_system_info = false\n",
            "angle_enable_vulkan = false\n",
            "angle_enable_swiftshader = false\n",
            "angle_enable_gl = false\n",
            "use_dawn = false\n",
            "enable_guest_view = false\n",
            "enable_plugins = false\n",
            "enable_printing = false\n",
            "enable_oop_printing = false\n",
            "enable_paint_preview = false\n",
            "enable_compute_pressure = false\n",
            "is_p2p_enabled = false\n",
            "build_with_model_execution = false\n",
            'v8_target_cpu = "arm"\n',
            "v8_snapshot_toolchain = "
            '"//build/toolchain/linux:clang_x86_v8_arm"\n',
            "v8_snapshot_toolchain_runtime_root = "
            '"//out/wasm-i386-runtime/root"\n',
            "v8_jitless = true\n",
            "v8_use_external_startup_data = false\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, arguments)
        self.assertNotIn("toolkit_views =", arguments)

    def test_manifest_has_reproducible_m6_chrome_args(self) -> None:
        manifest = load_manifest()
        arguments = gn_args_text(manifest, "m6_chrome_gn_args")
        for expected in (
            "enable_chromium_wasm_v8 = true\n",
            "enable_chromium_wasm_content = true\n",
            "enable_chromium_wasm_chrome = true\n",
            "use_aura = true\n",
            "use_ozone = true\n",
            "toolkit_views = true\n",
            "enable_hidpi = true\n",
            "enable_supervised_users = false\n",
            "enable_background_contents = false\n",
            "enable_background_mode = false\n",
            "enable_downgrade_processing = false\n",
            "enable_session_service = false\n",
            "enable_chrome_notifications = false\n",
            "enable_message_center = false\n",
            "enable_platform_experience = false\n",
            "enable_updater = false\n",
            "enable_update_notifications = false\n",
            "enterprise_watermark = false\n",
            "chrome_root_store_cert_management_ui = false\n",
            "enable_webui_certificate_viewer = false\n",
            "enable_extensions = false\n",
            "enable_library_cdms = false\n",
            "enable_widevine = false\n",
            "enable_printing = false\n",
            "enable_oop_printing = false\n",
            'v8_target_cpu = "arm"\n',
            "v8_target_is_simulator = true\n",
            "v8_jitless = true\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, arguments)

    def test_m3_safe_browsing_stops_before_platform_resource_generation(
        self,
    ) -> None:
        manifest = load_manifest()
        arguments = gn_args_text(manifest, "m3_content_gn_args")
        self.assertIn("safe_browsing_mode = 0\n", arguments)

        resources_build = (
            TOOLS_DIR.parents[1] / "components" / "resources" / "BUILD.gn"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'if (safe_browsing_mode > 0) {\n'
            '    deps += [\n'
            '      "//components/safe_browsing/content/resources:'
            'make_file_types_protobuf",\n',
            resources_build,
        )

    def test_m3_uses_an_empty_fieldtrial_testing_config(self) -> None:
        manifest = load_manifest()
        arguments = gn_args_text(manifest, "m3_content_gn_args")
        self.assertIn(
            "disable_fieldtrial_testing_config = true\n", arguments
        )

        field_trial_build = (
            TOOLS_DIR.parents[1]
            / "components"
            / "variations"
            / "field_trial_config"
            / "BUILD.gn"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "if (!disable_fieldtrial_testing_config) {", field_trial_build
        )
        self.assertIn('args += [ "--empty" ]', field_trial_build)


class CommonTest(unittest.TestCase):
    def test_context_identifies_port_base_and_manifest(self) -> None:
        manifest = load_manifest()
        stdout = StringIO()
        with (
            mock.patch.object(
                m0_common,
                "checked_output",
                side_effect=("port-commit", "m0-commit"),
            ) as checked_output,
            mock.patch("sys.stdout", stdout),
        ):
            context = m0_common.print_context(
                "runner.py", manifest, case="mojo"
            )

        checked_output.assert_has_calls(
            [
                mock.call(["git", "rev-parse", "HEAD"]),
                mock.call(
                    [
                        "git",
                        "rev-parse",
                        "wasm-m0-primary-toolchain^{commit}",
                    ]
                ),
            ]
        )
        line = stdout.getvalue().strip()
        self.assertTrue(line.startswith("CHROMIUM_WASM_M0:CONFIG "))
        emitted = json.loads(line.split(" ", 1)[1])
        self.assertEqual(emitted, context)
        self.assertEqual(emitted["port_commit"], "port-commit")
        self.assertEqual(
            emitted["m0_base"],
            {
                "tag": "wasm-m0-primary-toolchain",
                "commit": "m0-commit",
            },
        )
        self.assertEqual(
            emitted["toolchain_manifest"],
            {
                "path": "tools/wasm/toolchain_manifest.json",
                "schema_version": 1,
                "sha256": hashlib.sha256(
                    m0_common.MANIFEST_PATH.read_bytes()
                ).hexdigest(),
            },
        )

    def test_timeout_must_be_finite_positive_and_bounded(self) -> None:
        for value in ("0.01", "20", "120"):
            self.assertEqual(parse_timeout(value), float(value))
        for value in ("0", "-1", "nan", "inf", "-inf", "121"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parse_timeout(value)

    def test_command_failure_preserves_bounded_context(self) -> None:
        error = subprocess.CalledProcessError(
            1,
            ["tool", "argument"],
            output="STDOUT-BEGIN\n" + ("x" * 10000),
            stderr=("y" * 10000) + "\nSTDERR-END",
        )
        with (
            mock.patch("subprocess.run", side_effect=error),
            self.assertRaises(M0Error) as caught,
        ):
            run(["tool", "argument"])
        message = str(caught.exception)
        self.assertIn("STDOUT-BEGIN", message)
        self.assertIn("STDERR-END", message)
        self.assertIn("command output truncated", message)
        self.assertLess(len(message), 4500)


class BootstrapTest(unittest.TestCase):
    def test_base_gitlink_matches_manifest(self) -> None:
        manifest = load_manifest()
        chromium_revision = manifest["chromium"]["revision"]
        angle = manifest["git_dependencies"]["angle"]
        self.assertEqual(
            bootstrap.gitlink_revision(chromium_revision, angle["path"]),
            angle.get("upstream_revision", angle["revision"]),
        )

    def test_bootstrap_contains_no_checkout_absolute_path(self) -> None:
        source = (TOOLS_DIR / "bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("/home/", source)

    def test_activated_emscripten_config_is_pinned(self) -> None:
        manifest = load_manifest()
        self.assertEqual(
            bootstrap.sha256(emscripten_driver.EMSDK_ROOT / ".emscripten"),
            manifest["emscripten"]["config_sha256"],
        )

    def test_compiler_driver_replaces_host_emscripten_environment(self) -> None:
        poison = {
            "EM_CONFIG": "/invalid/config",
            "EM_CACHE": "/invalid/cache",
            "EM_LLVM_ROOT": "/invalid/llvm",
            "EM_BINARYEN_ROOT": "/invalid/binaryen",
            "EM_NODE_JS": "/invalid/node",
            "EMCC_CFLAGS": "--chromium-wasm-host-poison",
            "EMSDK_PYTHON": "/bin/false",
            "EMMAKEN_COMPILER": "poison",
            "_EMCC_CCACHE": "1",
            "EMPROFILE": "poison",
        }
        with mock.patch.dict(os.environ, poison):
            environment = emscripten_driver.pinned_environment()
        for name, value in poison.items():
            self.assertNotEqual(environment.get(name), value)
        self.assertEqual(
            environment["EM_CONFIG"],
            str(emscripten_driver.EMSDK_ROOT / ".emscripten"),
        )
        self.assertEqual(
            environment["EM_CACHE"],
            str(emscripten_driver.REPO_ROOT / "out/wasm-emscripten-cache"),
        )

    def test_compiler_driver_selects_c_or_defaults_to_cxx(self) -> None:
        self.assertEqual(
            emscripten_driver.split_tool_and_args(["emcc", "-c", "input.c"]),
            ("emcc", ["-c", "input.c"]),
        )
        self.assertEqual(
            emscripten_driver.split_tool_and_args(
                ["em++", "-c", "input.cc"]
            ),
            ("em++", ["-c", "input.cc"]),
        )
        self.assertEqual(
            emscripten_driver.split_tool_and_args(["-c", "input.cc"]),
            ("em++", ["-c", "input.cc"]),
        )

    def test_generated_configuration_includes_milestone_profiles(self) -> None:
        manifest = load_manifest()
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            mock.patch.object(
                bootstrap, "REPO_ROOT", Path(temporary_directory)
            ),
        ):
            bootstrap.ensure_generated_configuration(
                manifest, install=True
            )
            generated_root = Path(temporary_directory)
            self.assertEqual(
                (generated_root / "out/wasm/args.gn").read_text(
                    encoding="utf-8"
                ),
                gn_args_text(manifest),
            )
            self.assertEqual(
                (generated_root / "out/wasm-v8-m2/args.gn").read_text(
                    encoding="utf-8"
                ),
                gn_args_text(manifest, "m2_v8_gn_args"),
            )
            self.assertEqual(
                (generated_root / "out/wasm-content-m3/args.gn").read_text(
                    encoding="utf-8"
                ),
                gn_args_text(manifest, "m3_content_gn_args"),
            )
            self.assertEqual(
                (generated_root / "out/wasm-chrome-m6/args.gn").read_text(
                    encoding="utf-8"
                ),
                gn_args_text(manifest, "m6_chrome_gn_args"),
            )
            self.assertIn(
                "build_with_chromium = !enable_chromium_wasm_port || "
                "enable_chromium_wasm_content || "
                "enable_chromium_wasm_chrome\n",
                (
                    generated_root / "build/config/gclient_args.gni"
                ).read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (generated_root / "build/util/LASTCHANGE").read_text(
                    encoding="utf-8"
                ),
                "LASTCHANGE="
                "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9-"
                "refs/branch-heads/7871@{#3786}\n"
                "LASTCHANGE_YEAR=2026\n",
            )
            self.assertEqual(
                (
                    generated_root / "build/util/LASTCHANGE.committime"
                ).read_text(encoding="utf-8"),
                "1784580336",
            )
            bootstrap.ensure_generated_configuration(
                manifest, install=False
            )


class NodeRunnerTest(unittest.TestCase):
    def test_runner_waits_for_on_exit(self) -> None:
        source = run_node_smoke.runner_source("file:///hello_wasm.js", 1000)
        self.assertIn("onExit(code)", source)
        self.assertIn("await Promise.race([exitPromise, timeoutPromise])", source)
        self.assertIn("clearTimeout(timeoutId)", source)

    def test_stream_validation_is_separate(self) -> None:
        stdout = "\n".join(
            (
                run_node_smoke.RUNTIME_START,
                run_node_smoke.RUNTIME_END,
                run_node_smoke.STDOUT_SENTINEL,
                run_node_smoke.PASS_SENTINEL,
                'CHROMIUM_WASM_M0:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(
            stdout, run_node_smoke.STDERR_SENTINEL
        )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\n" + run_node_smoke.STDERR_SENTINEL, ""
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\n" + run_node_smoke.STDERR_SENTINEL,
                run_node_smoke.STDERR_SENTINEL
                + "\n"
                + run_node_smoke.STDOUT_SENTINEL,
            )

    def test_base_case_uses_base_module_and_sentinels(self) -> None:
        case_name, module = run_node_smoke.resolve_case_and_module(
            "base", None
        )
        self.assertEqual(case_name, "base")
        self.assertEqual(module, Path("out/wasm/m1_base_smoke.js"))
        self.assertEqual(
            run_node_smoke.resolve_case_and_module(
                None, Path("custom/m1_base_smoke.js")
            ),
            ("base", Path("custom/m1_base_smoke.js")),
        )
        with self.assertRaises(M0Error):
            run_node_smoke.resolve_case_and_module(
                "base", Path("out/wasm/hello_wasm.js")
            )

        stdout = "\n".join(
            (
                "CHROMIUM_WASM_M1_BASE:RUNTIME_START",
                "CHROMIUM_WASM_M1_BASE:RUNTIME_END",
                BASE_RESULT_LINE,
                "CHROMIUM_WASM_M1_BASE:PASS",
                'CHROMIUM_WASM_M1_BASE:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(stdout, "", "base")
        for old, new in (
            ("process_launch=unsupported", "process_launch=ok"),
            (BASE_RESULT_LINE, f"{BASE_RESULT_LINE} unexpected=ok"),
            ("wall_time=ok", "wall_time=ok wall_time=ok"),
            (BASE_RESULT_LINE, f"{BASE_RESULT_LINE}\n{BASE_RESULT_LINE}"),
        ):
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(old, new, 1), "", "base"
                )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\nCHROMIUM_WASM_M1_BASE:FAIL reason=test",
                "",
                "base",
            )

    def test_tasks_case_requires_complete_result_contract(self) -> None:
        case_name, module = run_node_smoke.resolve_case_and_module(
            "tasks", None
        )
        self.assertEqual(case_name, "tasks")
        self.assertEqual(module, Path("out/wasm/m1_task_smoke.js"))
        self.assertEqual(
            run_node_smoke.resolve_case_and_module(
                None, Path("custom/m1_task_smoke.js")
            ),
            ("tasks", Path("custom/m1_task_smoke.js")),
        )
        with self.assertRaises(M0Error):
            run_node_smoke.resolve_case_and_module(
                "tasks", Path("out/wasm/m1_base_smoke.js")
            )

        stdout = "\n".join(
            (
                "CHROMIUM_WASM_M1_TASK:RUNTIME_START",
                "CHROMIUM_WASM_M1_TASK:RUNTIME_END",
                TASK_RESULT_LINE,
                "CHROMIUM_WASM_M1_TASK:PASS",
                'CHROMIUM_WASM_M1_TASK:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(stdout, "", "tasks")
        for requirement in serve.TASK_RESULT_REQUIREMENTS:
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(requirement, "<missing>", 1), "", "tasks"
                )
        for old, new in (
            (" wake_count=3", " wake_count=2"),
            (" wait_count=1", " wait_count=0"),
            (" idle_wake_returns=1", " idle_wake_returns=2"),
            (
                " worker_to_app_latency_ms=0",
                " worker_to_app_latency_ms=1000",
            ),
            (" idle_elapsed_ms=250", " idle_elapsed_ms=199"),
            (" idle_wake_latency_ms=0", " idle_wake_latency_ms=-1"),
            (TASK_RESULT_LINE, f"{TASK_RESULT_LINE} unexpected=ok"),
            (" immediate=ok", " immediate=ok immediate=ok"),
            (TASK_RESULT_LINE, f"{TASK_RESULT_LINE}\n{TASK_RESULT_LINE}"),
        ):
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(old, new, 1), "", "tasks"
                )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\nCHROMIUM_WASM_M1_TASK:FAIL reason=test",
                "",
                "tasks",
            )

    def test_rust_case_requires_complete_result_contract(self) -> None:
        case_name, module = run_node_smoke.resolve_case_and_module(
            "rust", None
        )
        self.assertEqual(case_name, "rust")
        self.assertEqual(module, Path("out/wasm/m1_rust_smoke.js"))
        self.assertEqual(
            run_node_smoke.resolve_case_and_module(
                None, Path("custom/m1_rust_smoke.js")
            ),
            ("rust", Path("custom/m1_rust_smoke.js")),
        )
        with self.assertRaises(M0Error):
            run_node_smoke.resolve_case_and_module(
                "rust", Path("out/wasm/m1_task_smoke.js")
            )

        stdout = "\n".join(
            (
                "CHROMIUM_WASM_M1_RUST:RUNTIME_START",
                "CHROMIUM_WASM_M1_RUST:RUNTIME_END",
                RUST_RESULT_LINE,
                "CHROMIUM_WASM_M1_RUST:PASS",
                'CHROMIUM_WASM_M1_RUST:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(stdout, "", "rust")
        for requirement in serve.RUST_RESULT_REQUIREMENTS:
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(requirement, "<missing>", 1), "", "rust"
                )
        for old, new in (
            ("pointer_width=32", "pointer_width=64"),
            (RUST_RESULT_LINE, f"{RUST_RESULT_LINE} unexpected=ok"),
            ("cpp_to_rust=ok", "cpp_to_rust=ok cpp_to_rust=ok"),
            (RUST_RESULT_LINE, f"{RUST_RESULT_LINE}\n{RUST_RESULT_LINE}"),
        ):
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(old, new, 1), "", "rust"
                )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\nCHROMIUM_WASM_M1_RUST:FAIL reason=test",
                "",
                "rust",
            )

    def test_v8_base_case_requires_complete_result_contract(self) -> None:
        case_name, module = run_node_smoke.resolve_case_and_module(
            "v8_base", None
        )
        self.assertEqual(case_name, "v8_base")
        self.assertEqual(
            serve.smoke_case(case_name).gn_args_key,
            "m2_v8_gn_args",
        )
        self.assertEqual(
            module, Path("out/wasm/wasm_v8_base_smoke.js")
        )
        self.assertEqual(
            run_node_smoke.resolve_case_and_module(
                None, Path("custom/wasm_v8_base_smoke.js")
            ),
            ("v8_base", Path("custom/wasm_v8_base_smoke.js")),
        )
        with self.assertRaises(M0Error):
            run_node_smoke.resolve_case_and_module(
                "v8_base", Path("out/wasm/m1_base_smoke.js")
            )

        stdout = "\n".join(
            (
                "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_START",
                "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_END",
                V8_BASE_RESULT_LINE,
                "CHROMIUM_WASM_M2_V8_BASE:PASS",
                'CHROMIUM_WASM_M2_V8_BASE:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(stdout, "", "v8_base")
        for requirement in serve.V8_BASE_RESULT_REQUIREMENTS:
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(requirement, "<missing>", 1),
                    "",
                    "v8_base",
                )
        for old, new in (
            ("target=arm", "target=wasm"),
            (V8_BASE_RESULT_LINE, f"{V8_BASE_RESULT_LINE} unexpected=ok"),
            ("threads=ok", "threads=ok threads=ok"),
            (
                V8_BASE_RESULT_LINE,
                f"{V8_BASE_RESULT_LINE}\n{V8_BASE_RESULT_LINE}",
            ),
        ):
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(old, new, 1), "", "v8_base"
                )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\nCHROMIUM_WASM_M2_V8_BASE:FAIL reason=test",
                "",
                "v8_base",
            )

    def test_v8_snapshotless_case_requires_complete_contract(self) -> None:
        case_name, module = run_node_smoke.resolve_case_and_module(
            "v8_snapshotless", None
        )
        self.assertEqual(case_name, "v8_snapshotless")
        self.assertEqual(
            serve.smoke_case(case_name).gn_args_key,
            "m2_v8_gn_args",
        )
        self.assertEqual(
            module, Path("out/wasm/wasm_v8_snapshotless_smoke.js")
        )
        self.assertEqual(
            run_node_smoke.resolve_case_and_module(
                None, Path("custom/wasm_v8_snapshotless_smoke.js")
            ),
            (
                "v8_snapshotless",
                Path("custom/wasm_v8_snapshotless_smoke.js"),
            ),
        )
        with self.assertRaises(M0Error):
            run_node_smoke.resolve_case_and_module(
                "v8_snapshotless",
                Path("out/wasm/wasm_v8_base_smoke.js"),
            )

        stdout = "\n".join(
            (
                "CHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
                *V8_SNAPSHOTLESS_STAGE_LINES,
                *V8_SNAPSHOTLESS_TEST262_CASE_LINES,
                V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE,
                "CHROMIUM_WASM_M2_V8_JS:RUNTIME_END",
                V8_SNAPSHOTLESS_RESULT_LINE,
                "CHROMIUM_WASM_M2_V8_JS:PASS",
                'CHROMIUM_WASM_M2_V8_JS:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(
            stdout, "", "v8_snapshotless"
        )
        for requirement in serve.V8_SNAPSHOTLESS_RESULT_REQUIREMENTS:
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(requirement, "<missing>", 1),
                    "",
                    "v8_snapshotless",
                )
        for name, value in V8_SNAPSHOTLESS_RESULT_NUMERIC_VALUES.items():
            with (
                self.subTest(numeric_name=name),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(
                        f"{name}={value}", f"{name}=not-a-number", 1
                    ),
                    "",
                    "v8_snapshotless",
                )
        for old, new in (
            ("target=arm", "target=wasm"),
            ("feature_cycles=3", "feature_cycles=2"),
            ("native_callback_calls=6", "native_callback_calls=5"),
            ("gc_cycles=3", "gc_cycles=2"),
            ("module_cycles=3", "module_cycles=2"),
            ("module_resolve_calls=3", "module_resolve_calls=2"),
            ("timer_delay_ms=25", "timer_delay_ms=24"),
            ("timer_elapsed_us=25581", "timer_elapsed_us=24999"),
            ("timer_cycles=1", "timer_cycles=2"),
            ("test262_executions=25", "test262_executions=24"),
            (
                "test262_license_fnv1a=1790394517849644",
                "test262_license_fnv1a=1790394517849645",
            ),
            (
                "test262_module_compile_attempts=7",
                "test262_module_compile_attempts=6",
            ),
            ("test262_runtime_ms=68", "test262_runtime_ms=72"),
            ("runtime_ms=2043", "runtime_ms=1"),
            (
                "v8_heap_used_max_sampled_bytes=120368",
                "v8_heap_used_max_sampled_bytes=999999",
            ),
            (
                "wasm_linear_peak_bytes=598999040",
                "wasm_linear_peak_bytes=1",
            ),
            (
                "array_buffer_peak_bytes=2097168",
                "array_buffer_peak_bytes=1",
            ),
            (
                "v8_external_max_sampled_bytes=2097189",
                "v8_external_max_sampled_bytes=1",
            ),
            (
                V8_SNAPSHOTLESS_RESULT_LINE,
                f"{V8_SNAPSHOTLESS_RESULT_LINE} unexpected=ok",
            ),
            ("arrays=ok", "arrays=ok arrays=ok"),
            (
                V8_SNAPSHOTLESS_RESULT_LINE,
                f"{V8_SNAPSHOTLESS_RESULT_LINE}\n"
                f"{V8_SNAPSHOTLESS_RESULT_LINE}",
            ),
        ):
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(old, new, 1),
                    "",
                    "v8_snapshotless",
                )
        first_stage = V8_SNAPSHOTLESS_STAGE_LINES[0]
        second_stage = V8_SNAPSHOTLESS_STAGE_LINES[1]
        for invalid_stdout in (
            stdout.replace(first_stage, "", 1),
            stdout.replace(first_stage, f"{first_stage}\n{first_stage}", 1),
            stdout.replace(first_stage, f"{first_stage} unexpected", 1),
            stdout.replace(
                f"{first_stage}\n{second_stage}",
                f"{second_stage}\n{first_stage}",
                1,
            ),
            stdout.replace(
                f"CHROMIUM_WASM_M2_V8_JS:RUNTIME_START\n{first_stage}",
                f"{first_stage}\nCHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
                1,
            ),
        ):
            with (
                self.subTest(invalid_stage_output=invalid_stdout),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    invalid_stdout, "", "v8_snapshotless"
                )
        first_case = V8_SNAPSHOTLESS_TEST262_CASE_LINES[0]
        second_case = V8_SNAPSHOTLESS_TEST262_CASE_LINES[1]
        for invalid_stdout in (
            stdout.replace(first_case, "", 1),
            stdout.replace(first_case, f"{first_case}\n{first_case}", 1),
            stdout.replace(first_case, f"{first_case} unexpected", 1),
            stdout.replace(
                f"{first_case}\n{second_case}",
                f"{second_case}\n{first_case}",
                1,
            ),
            stdout.replace(
                f"{first_case}\n{second_case}", second_case, 1
            ).replace(
                "CHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
                f"{first_case}\nCHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
                1,
            ),
            stdout.replace(V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE, "", 1),
            stdout.replace(
                V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE,
                f"{V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE}\n"
                f"{V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE}",
                1,
            ),
            stdout.replace(
                "executions=25 passed=25",
                "executions=24 passed=24",
                1,
            ),
            stdout.replace(
                f"{V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE}\n"
                "CHROMIUM_WASM_M2_V8_JS:RUNTIME_END",
                "CHROMIUM_WASM_M2_V8_JS:RUNTIME_END\n"
                f"{V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE}",
                1,
            ),
        ):
            with (
                self.subTest(invalid_test262_output=invalid_stdout),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    invalid_stdout, "", "v8_snapshotless"
                )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\nCHROMIUM_WASM_M2_V8_JS:FAIL reason=test",
                "",
                "v8_snapshotless",
            )

    def test_shared_memory_case_requires_complete_result_contract(self) -> None:
        case_name, module = run_node_smoke.resolve_case_and_module(
            "shared_memory", None
        )
        self.assertEqual(case_name, "shared_memory")
        self.assertEqual(
            module, Path("out/wasm/m1_shared_memory_smoke.js")
        )
        self.assertEqual(
            run_node_smoke.resolve_case_and_module(
                None, Path("custom/m1_shared_memory_smoke.js")
            ),
            (
                "shared_memory",
                Path("custom/m1_shared_memory_smoke.js"),
            ),
        )
        with self.assertRaises(M0Error):
            run_node_smoke.resolve_case_and_module(
                "shared_memory", Path("out/wasm/m1_rust_smoke.js")
            )

        stdout = "\n".join(
            (
                "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_START",
                "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_END",
                SHARED_MEMORY_METRICS_LINE,
                SHARED_MEMORY_RESULT_LINE,
                "CHROMIUM_WASM_M1_SHARED_MEMORY:PASS",
                (
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:NODE_EXIT "
                    '{"exitCode":0}'
                ),
            )
        )
        run_node_smoke.validate_streams(stdout, "", "shared_memory")
        for requirement in serve.SHARED_MEMORY_RESULT_REQUIREMENTS:
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(requirement, "<missing>", 1),
                    "",
                    "shared_memory",
                )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout.replace(
                    "worker_threads_created=1",
                    "worker_threads_created=10",
                ),
                "",
                "shared_memory",
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout.replace(
                    f"{SHARED_MEMORY_METRICS_LINE}\n"
                    f"{SHARED_MEMORY_RESULT_LINE}",
                    f"{SHARED_MEMORY_RESULT_LINE}\n"
                    f"{SHARED_MEMORY_METRICS_LINE}",
                ),
                "",
                "shared_memory",
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout.replace(
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:PASS\n"
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:NODE_EXIT "
                    '{"exitCode":0}',
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:NODE_EXIT "
                    '{"exitCode":0}\n'
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:PASS",
                ),
                "",
                "shared_memory",
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout.replace(
                    "initial_heap_bytes=67108864",
                    "initial_heap_bytes=garbage",
                ),
                "",
                "shared_memory",
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout
                + "\nCHROMIUM_WASM_M1_SHARED_MEMORY:FAIL reason=test",
                "",
                "shared_memory",
            )

    def test_mojo_case_requires_complete_result_contract(self) -> None:
        case_name, module = run_node_smoke.resolve_case_and_module(
            "mojo", None
        )
        self.assertEqual(case_name, "mojo")
        self.assertEqual(module, Path("out/wasm/m1_mojo_smoke.js"))
        self.assertEqual(
            run_node_smoke.resolve_case_and_module(
                None, Path("custom/m1_mojo_smoke.js")
            ),
            ("mojo", Path("custom/m1_mojo_smoke.js")),
        )
        with self.assertRaises(M0Error):
            run_node_smoke.resolve_case_and_module(
                "mojo", Path("out/wasm/m1_shared_memory_smoke.js")
            )

        stdout = "\n".join(
            (
                "CHROMIUM_WASM_M1_MOJO:RUNTIME_START",
                "CHROMIUM_WASM_M1_MOJO:RUNTIME_END",
                MOJO_METRICS_LINE,
                MOJO_RESULT_LINE,
                "CHROMIUM_WASM_M1_MOJO:PASS",
                'CHROMIUM_WASM_M1_MOJO:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(stdout, "", "mojo")
        for requirement in serve.MOJO_RESULT_REQUIREMENTS:
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(requirement, "<missing>", 1),
                    "",
                    "mojo",
                )
        for old, new in (
            ("unsafe_duplicate=ok", "unsafe_duplicate=okay"),
            (
                "platform_region_single_owner=ok",
                "platform_region_single_owner=leaked",
            ),
            (
                "platform_region_unwrap_failure_closes=ok",
                "platform_region_unwrap_failure_closes=leaked",
            ),
            ("initial_heap_bytes=67108864", "initial_heap_bytes=garbage"),
            (
                MOJO_RESULT_LINE,
                f"{MOJO_RESULT_LINE} unexpected_field=ok",
            ),
            (
                "single_node=ok",
                "single_node=ok single_node=ok",
            ),
            (
                "peak_heap_bytes=67108864",
                "peak_heap_bytes=33554432",
            ),
        ):
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_node_smoke.validate_streams(
                    stdout.replace(old, new), "", "mojo"
                )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout.replace(
                    f"{MOJO_METRICS_LINE}\n{MOJO_RESULT_LINE}",
                    f"{MOJO_RESULT_LINE}\n{MOJO_METRICS_LINE}",
                ),
                "",
                "mojo",
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout.replace(
                    "CHROMIUM_WASM_M1_MOJO:PASS\n"
                    'CHROMIUM_WASM_M1_MOJO:NODE_EXIT {"exitCode":0}',
                    'CHROMIUM_WASM_M1_MOJO:NODE_EXIT {"exitCode":0}\n'
                    "CHROMIUM_WASM_M1_MOJO:PASS",
                ),
                "",
                "mojo",
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout.replace(
                    "CHROMIUM_WASM_M1_MOJO:PASS",
                    "CHROMIUM_WASM_M1_MOJO:PASS\n"
                    "CHROMIUM_WASM_M1_MOJO:PASS",
                ),
                "",
                "mojo",
            )
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\nCHROMIUM_WASM_M1_MOJO:FAIL reason=test",
                "",
                "mojo",
            )


class ServerTest(unittest.TestCase):
    def test_security_headers_mime_and_focusable_canvas(self) -> None:
        handler = object.__new__(serve.M0RequestHandler)
        handler._headers_buffer = [b"HTTP/1.1 200 OK\r\n"]
        handler.request_version = "HTTP/1.1"
        handler.wfile = BytesIO()
        handler.end_headers()
        headers = handler.wfile.getvalue().decode("ascii")
        self.assertIn(
            "Cross-Origin-Opener-Policy: same-origin\r\n", headers
        )
        self.assertIn(
            "Cross-Origin-Embedder-Policy: require-corp\r\n", headers
        )
        self.assertEqual(
            serve.CONTENT_TYPES[".wasm"], "application/wasm"
        )
        host_page = (
            TOOLS_DIR / "host/hello.html"
        ).read_text(encoding="utf-8")
        self.assertIn('canvas id="browser-canvas" tabindex="0"', host_page)
        self.assertIn("if (!response.ok)", host_page)
        self.assertIn("response.status", host_page)
        self.assertIn('modulePath: "/out/wasm/hello_wasm.js"', host_page)
        self.assertIn('modulePath: "/out/wasm/m1_base_smoke.js"', host_page)
        self.assertIn('modulePath: "/out/wasm/m1_task_smoke.js"', host_page)
        self.assertIn('modulePath: "/out/wasm/m1_rust_smoke.js"', host_page)
        self.assertIn(
            'modulePath: "/out/wasm/wasm_v8_base_smoke.js"',
            host_page,
        )
        self.assertIn(
            'modulePath: "/out/wasm/wasm_v8_snapshotless_smoke.js"',
            host_page,
        )
        self.assertIn(
            'modulePath: "/out/wasm/m1_shared_memory_smoke.js"',
            host_page,
        )
        self.assertIn(
            'modulePath: "/out/wasm/m1_mojo_smoke.js"',
            host_page,
        )
        self.assertIn("minimumRuntimeMs: 250", host_page)
        self.assertIn(
            "runtimeElapsed >= (caseConfiguration.minimumRuntimeMs ?? 200)",
            host_page,
        )
        for requirement in serve.TASK_RESULT_REQUIREMENTS:
            self.assertIn(requirement, host_page)
        for requirement in serve.RUST_RESULT_REQUIREMENTS:
            self.assertIn(requirement, host_page)
        for requirement in serve.V8_BASE_RESULT_REQUIREMENTS:
            self.assertIn(requirement, host_page)
        for requirement in serve.V8_SNAPSHOTLESS_RESULT_REQUIREMENTS:
            self.assertIn(requirement, host_page)
        for requirement in serve.SHARED_MEMORY_RESULT_REQUIREMENTS:
            self.assertIn(requirement, host_page)
        for requirement in serve.MOJO_RESULT_REQUIREMENTS:
            self.assertIn(requirement, host_page)
        self.assertIn(
            "requestAnimationFrame(animationFrameHeartbeat)", host_page
        )
        self.assertIn("animationFrameDelta", host_page)
        self.assertIn("addEventListener(\"error\"", host_page)
        self.assertIn("addEventListener(\"unhandledrejection\"", host_page)
        self.assertIn("onAbort(reason)", host_page)

    def test_server_exposes_only_selected_case_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            for name in (
                "m1_base_smoke.js",
                "m1_base_smoke.wasm",
                "m1_base_smoke.wasm.map",
                "hello_wasm.js",
                "unrelated.js",
            ):
                (out_dir / name).write_bytes(b"test")
            state = serve.ServerState(
                token="token",
                out_dir=out_dir,
                result_queue=queue.Queue(maxsize=1),
                smoke_case_name="base",
                smoke_case=serve.smoke_case("base"),
            )
            self.assertEqual(
                serve.artifact_for_request(
                    state, "/out/wasm/m1_base_smoke.js"
                ),
                out_dir / "m1_base_smoke.js",
            )
            self.assertEqual(
                serve.artifact_for_request(
                    state, "/out/wasm/m1_base_smoke.wasm"
                ),
                out_dir / "m1_base_smoke.wasm",
            )
            self.assertIsNone(
                serve.artifact_for_request(
                    state, "/out/wasm/hello_wasm.js"
                )
            )
            self.assertIsNone(
                serve.artifact_for_request(state, "/out/wasm/unrelated.js")
            )

    def test_server_allowlists_v8_base_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            for name in (
                "wasm_v8_base_smoke.js",
                "wasm_v8_base_smoke.wasm",
                "wasm_v8_base_smoke.wasm.map",
                "m1_base_smoke.js",
            ):
                (out_dir / name).write_bytes(b"test")
            state = serve.ServerState(
                token="token",
                out_dir=out_dir,
                result_queue=queue.Queue(maxsize=1),
                smoke_case_name="v8_base",
                smoke_case=serve.smoke_case("v8_base"),
            )
            for name in (
                "wasm_v8_base_smoke.js",
                "wasm_v8_base_smoke.wasm",
                "wasm_v8_base_smoke.wasm.map",
            ):
                self.assertEqual(
                    serve.artifact_for_request(
                        state, f"/out/wasm/{name}"
                    ),
                    out_dir / name,
                )
            self.assertIsNone(
                serve.artifact_for_request(
                    state, "/out/wasm/m1_base_smoke.js"
                )
            )

    def test_server_allowlists_v8_snapshotless_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            out_dir = Path(temporary_directory)
            for name in (
                "wasm_v8_snapshotless_smoke.js",
                "wasm_v8_snapshotless_smoke.wasm",
                "wasm_v8_snapshotless_smoke.wasm.map",
                "wasm_v8_base_smoke.js",
            ):
                (out_dir / name).write_bytes(b"test")
            state = serve.ServerState(
                token="token",
                out_dir=out_dir,
                result_queue=queue.Queue(maxsize=1),
                smoke_case_name="v8_snapshotless",
                smoke_case=serve.smoke_case("v8_snapshotless"),
            )
            for name in (
                "wasm_v8_snapshotless_smoke.js",
                "wasm_v8_snapshotless_smoke.wasm",
                "wasm_v8_snapshotless_smoke.wasm.map",
            ):
                self.assertEqual(
                    serve.artifact_for_request(
                        state, f"/out/wasm/{name}"
                    ),
                    out_dir / name,
                )
            self.assertIsNone(
                serve.artifact_for_request(
                    state, "/out/wasm/wasm_v8_base_smoke.js"
                )
            )


class BrowserRunnerTest(unittest.TestCase):
    def test_failure_diagnostics_preserve_structured_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            diagnostics_dir = Path(temporary_directory)
            browser = mock.Mock()
            browser.poll.return_value = 17
            diagnostic_path = (
                run_browser_smoke.write_failure_diagnostics(
                    diagnostics_dir,
                    case_name="mojo",
                    stage="validate_result",
                    error=M0Error("result mismatch"),
                    context={"port_commit": "port-commit"},
                    browser_path=Path("/browser"),
                    browser_version_output="Chromium 150.0",
                    browser=browser,
                    browser_stderr=deque(["first", "last"]),
                    runtime_result={
                        "stdout": ["runtime stdout"],
                        "stderr": ["runtime stderr"],
                    },
                    timeout_seconds=30.0,
                    out_dir=Path("/out/wasm"),
                    no_sandbox=False,
                )
            )
            diagnostic_text = diagnostic_path.read_text(encoding="utf-8")
            diagnostic = json.loads(diagnostic_text)

        self.assertEqual(
            diagnostic_path.name, "mojo-browser-failure.json"
        )
        self.assertEqual(diagnostic["stage"], "validate_result")
        self.assertEqual(diagnostic["failure"]["type"], "M0Error")
        self.assertEqual(
            diagnostic["host_browser"]["stderr_tail"],
            ["first", "last"],
        )
        self.assertEqual(diagnostic["host_browser"]["return_code"], 17)
        self.assertEqual(
            diagnostic["runtime_result"]["stderr"], ["runtime stderr"]
        )
        self.assertNotIn("token", diagnostic_text.lower())
        self.assertNotIn("url", diagnostic_text.lower())

    def test_browser_discovery_failure_saves_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            diagnostics_dir = Path(temporary_directory) / "diagnostics"
            stderr = StringIO()
            context = {
                "port_commit": "port-commit",
                "m0_base": {
                    "tag": "wasm-m0-primary-toolchain",
                    "commit": "m0-commit",
                },
            }
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_browser_smoke.py",
                        "--case",
                        "hello",
                        "--diagnostics-dir",
                        str(diagnostics_dir),
                    ],
                ),
                mock.patch.object(
                    run_browser_smoke,
                    "load_manifest",
                    return_value=load_manifest(),
                ),
                mock.patch.object(
                    run_browser_smoke,
                    "print_context",
                    return_value=context,
                ),
                mock.patch.object(
                    run_browser_smoke,
                    "find_browser",
                    side_effect=M0Error("browser unavailable"),
                ),
                mock.patch.object(sys, "stderr", stderr),
            ):
                self.assertEqual(run_browser_smoke.main(), 1)

            diagnostic_path = (
                diagnostics_dir / "hello-browser-failure.json"
            )
            diagnostic = json.loads(
                diagnostic_path.read_text(encoding="utf-8")
            )

        self.assertEqual(diagnostic["stage"], "find_browser")
        self.assertEqual(diagnostic["context"], context)
        self.assertEqual(
            diagnostic["failure"]["message"], "browser unavailable"
        )
        self.assertIn("CHROMIUM_WASM_M0:DIAGNOSTICS", stderr.getvalue())
        self.assertIn(
            "CHROMIUM_WASM_M0:FAIL reason=browser unavailable",
            stderr.getvalue(),
        )

    def test_no_sandbox_is_explicit(self) -> None:
        browser = Path("/browser")
        command = run_browser_smoke.browser_command(
            browser, "/profile", "http://127.0.0.1/", no_sandbox=False
        )
        self.assertNotIn("--no-sandbox", command)
        self.assertEqual(command[-1], "http://127.0.0.1/")
        command = run_browser_smoke.browser_command(
            browser, "/profile", "http://127.0.0.1/", no_sandbox=True
        )
        self.assertIn("--no-sandbox", command)
        self.assertEqual(command[-1], "http://127.0.0.1/")

    def test_explicit_browser_has_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            explicit = Path(temporary_directory) / "explicit-chrome"
            environment = Path(temporary_directory) / "environment-chrome"
            explicit.touch()
            environment.touch()
            with (
                mock.patch.object(
                    run_browser_smoke,
                    "browser_version",
                    return_value=((1, 2, 3), "Chrome 1.2.3"),
                ),
                mock.patch.dict(
                    os.environ,
                    {"CHROMIUM_WASM_BROWSER": str(environment)},
                ),
            ):
                selected, _ = run_browser_smoke.find_browser(explicit)
            self.assertEqual(selected, explicit.resolve())

    def test_result_requires_heartbeat_and_streams(self) -> None:
        result = {
            "protocol": 1,
            "case": "hello",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 4,
                "animationFrameDelta": 4,
                "elapsedMs": 250,
            },
            "stdout": [
                "CHROMIUM_WASM_M0:RUNTIME_START",
                "CHROMIUM_WASM_M0:RUNTIME_END",
                "CHROMIUM_WASM_M0:STDOUT",
                "CHROMIUM_WASM_M0:PASS",
            ],
            "stderr": ["CHROMIUM_WASM_M0:STDERR capture=ok"],
        }
        run_browser_smoke.validate_result(result)
        result["heartbeat"] = {
            "timerDelta": 0,
            "animationFrameDelta": 4,
            "elapsedMs": 250,
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result)
        result["heartbeat"] = {
            "timerDelta": 4,
            "animationFrameDelta": 0,
            "elapsedMs": 250,
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result)
        result["heartbeat"] = {
            "timerDelta": 4,
            "animationFrameDelta": float("nan"),
            "elapsedMs": 250,
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result)

    def test_base_result_requires_base_case_sentinels(self) -> None:
        result = {
            "protocol": 1,
            "case": "base",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 4,
                "animationFrameDelta": 4,
                "elapsedMs": 250,
            },
            "stdout": [
                "CHROMIUM_WASM_M1_BASE:RUNTIME_START",
                "CHROMIUM_WASM_M1_BASE:RUNTIME_END",
                BASE_RESULT_LINE,
                "CHROMIUM_WASM_M1_BASE:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "base")
        for old, new in (
            ("process_output=unsupported", "process_output=ok"),
            (BASE_RESULT_LINE, f"{BASE_RESULT_LINE} unexpected=ok"),
            ("wall_time=ok", "wall_time=ok wall_time=ok"),
            (BASE_RESULT_LINE, f"{BASE_RESULT_LINE}\n{BASE_RESULT_LINE}"),
        ):
            invalid_result = {
                **result,
                "stdout": [
                    line.replace(old, new, 1) for line in result["stdout"]
                ],
            }
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(invalid_result, "base")
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M1_BASE:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result, "base")

    def test_v8_base_result_requires_complete_result_contract(self) -> None:
        result = {
            "protocol": 1,
            "case": "v8_base",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 20,
                "animationFrameDelta": 12,
                "elapsedMs": 250,
            },
            "stdout": [
                "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_START",
                "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_END",
                V8_BASE_RESULT_LINE,
                "CHROMIUM_WASM_M2_V8_BASE:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "v8_base")
        short_result = {
            **result,
            "heartbeat": {
                **result["heartbeat"],
                "elapsedMs": 199,
            },
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(short_result, "v8_base")
        for requirement in serve.V8_BASE_RESULT_REQUIREMENTS:
            invalid_result = {
                **result,
                "stdout": [
                    "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_START",
                    "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_END",
                    V8_BASE_RESULT_LINE.replace(
                        requirement, "<missing>", 1
                    ),
                    "CHROMIUM_WASM_M2_V8_BASE:PASS",
                ],
            }
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "v8_base"
                )
        for old, new in (
            ("simulator_config=arm", "simulator_config=unsupported"),
            (V8_BASE_RESULT_LINE, f"{V8_BASE_RESULT_LINE} unexpected=ok"),
            (
                "jitless_config=on",
                "jitless_config=on jitless_config=on",
            ),
            (
                V8_BASE_RESULT_LINE,
                f"{V8_BASE_RESULT_LINE}\n{V8_BASE_RESULT_LINE}",
            ),
        ):
            invalid_result = {
                **result,
                "stdout": [
                    line.replace(old, new, 1) for line in result["stdout"]
                ],
            }
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "v8_base"
                )
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M2_V8_BASE:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result, "v8_base")

    def test_v8_snapshotless_result_requires_complete_contract(self) -> None:
        result = {
            "protocol": 1,
            "case": "v8_snapshotless",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 180,
                "animationFrameDelta": 100,
                "elapsedMs": 1800,
            },
            "stdout": [
                "CHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
                *V8_SNAPSHOTLESS_STAGE_LINES,
                *V8_SNAPSHOTLESS_TEST262_CASE_LINES,
                V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE,
                "CHROMIUM_WASM_M2_V8_JS:RUNTIME_END",
                V8_SNAPSHOTLESS_RESULT_LINE,
                "CHROMIUM_WASM_M2_V8_JS:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "v8_snapshotless")
        short_result = {
            **result,
            "heartbeat": {
                **result["heartbeat"],
                "elapsedMs": 999,
            },
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(
                short_result, "v8_snapshotless"
            )
        for requirement in serve.V8_SNAPSHOTLESS_RESULT_REQUIREMENTS:
            invalid_result = {
                **result,
                "stdout": [
                    "CHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
                    *V8_SNAPSHOTLESS_STAGE_LINES,
                    *V8_SNAPSHOTLESS_TEST262_CASE_LINES,
                    V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE,
                    "CHROMIUM_WASM_M2_V8_JS:RUNTIME_END",
                    V8_SNAPSHOTLESS_RESULT_LINE.replace(
                        requirement, "<missing>", 1
                    ),
                    "CHROMIUM_WASM_M2_V8_JS:PASS",
                ],
            }
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "v8_snapshotless"
                )
        invalid_result = {
            **result,
            "stdout": [
                line
                for line in result["stdout"]
                if line != V8_SNAPSHOTLESS_TEST262_CASE_LINES[0]
            ],
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(
                invalid_result, "v8_snapshotless"
            )
        invalid_result = {
            **result,
            "stdout": [
                line.replace(
                    V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE,
                    "CHROMIUM_WASM_M2_V8_JS:TEST262_SUMMARY "
                    "cases=14 executions=24 passed=24 failed=0 status=ok",
                    1,
                )
                for line in result["stdout"]
            ],
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(
                invalid_result, "v8_snapshotless"
            )
        for name, value in V8_SNAPSHOTLESS_RESULT_NUMERIC_VALUES.items():
            invalid_result = {
                **result,
                "stdout": [
                    line.replace(
                        f"{name}={value}", f"{name}=not-a-number", 1
                    )
                    for line in result["stdout"]
                ],
            }
            with (
                self.subTest(numeric_name=name),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "v8_snapshotless"
                )
        for old, new in (
            ("simulator=arm", "simulator=unsupported"),
            ("feature_cycles=3", "feature_cycles=2"),
            ("native_callback_calls=6", "native_callback_calls=5"),
            ("gc_cycles=3", "gc_cycles=2"),
            ("module_cycles=3", "module_cycles=2"),
            ("module_resolve_calls=3", "module_resolve_calls=2"),
            ("timer_delay_ms=25", "timer_delay_ms=24"),
            ("timer_elapsed_us=25581", "timer_elapsed_us=24999"),
            ("timer_cycles=1", "timer_cycles=2"),
            ("test262_executions=25", "test262_executions=24"),
            (
                "test262_license_fnv1a=1790394517849644",
                "test262_license_fnv1a=1790394517849645",
            ),
            (
                "test262_module_compile_attempts=7",
                "test262_module_compile_attempts=6",
            ),
            ("test262_runtime_ms=68", "test262_runtime_ms=72"),
            (
                "v8_heap_total_max_sampled_bytes=786432",
                "v8_heap_total_max_sampled_bytes=999999999",
            ),
            (
                "v8_malloced_max_sampled_bytes=32812",
                "v8_malloced_max_sampled_bytes=999999",
            ),
            (
                "array_buffer_peak_bytes=2097168",
                "array_buffer_peak_bytes=1",
            ),
            (
                "v8_external_max_sampled_bytes=2097189",
                "v8_external_max_sampled_bytes=1",
            ),
            (
                V8_SNAPSHOTLESS_RESULT_LINE,
                f"{V8_SNAPSHOTLESS_RESULT_LINE} unexpected=ok",
            ),
            ("jitless=on", "jitless=on jitless=on"),
            (
                V8_SNAPSHOTLESS_RESULT_LINE,
                f"{V8_SNAPSHOTLESS_RESULT_LINE}\n"
                f"{V8_SNAPSHOTLESS_RESULT_LINE}",
            ),
        ):
            invalid_result = {
                **result,
                "stdout": [
                    line.replace(old, new, 1) for line in result["stdout"]
                ],
            }
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "v8_snapshotless"
                )
        valid_stdout = "\n".join(result["stdout"])
        first_stage = V8_SNAPSHOTLESS_STAGE_LINES[0]
        second_stage = V8_SNAPSHOTLESS_STAGE_LINES[1]
        for invalid_stdout in (
            valid_stdout.replace(first_stage, "", 1),
            valid_stdout.replace(
                first_stage, f"{first_stage}\n{first_stage}", 1
            ),
            valid_stdout.replace(
                first_stage, f"{first_stage} unexpected", 1
            ),
            valid_stdout.replace(
                f"{first_stage}\n{second_stage}",
                f"{second_stage}\n{first_stage}",
                1,
            ),
            valid_stdout.replace(
                f"CHROMIUM_WASM_M2_V8_JS:RUNTIME_START\n{first_stage}",
                f"{first_stage}\nCHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
                1,
            ),
        ):
            invalid_result = {
                **result,
                "stdout": invalid_stdout.splitlines(),
            }
            with (
                self.subTest(invalid_stage_output=invalid_stdout),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "v8_snapshotless"
                )
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M2_V8_JS:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(
                result, "v8_snapshotless"
            )

    def test_tasks_result_requires_complete_result_contract(self) -> None:
        result = {
            "protocol": 1,
            "case": "tasks",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 40,
                "animationFrameDelta": 20,
                "elapsedMs": 650,
            },
            "stdout": [
                "CHROMIUM_WASM_M1_TASK:RUNTIME_START",
                "CHROMIUM_WASM_M1_TASK:RUNTIME_END",
                TASK_RESULT_LINE,
                "CHROMIUM_WASM_M1_TASK:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "tasks")
        for requirement in serve.TASK_RESULT_REQUIREMENTS:
            invalid_result = {
                **result,
                "stdout": [
                    "CHROMIUM_WASM_M1_TASK:RUNTIME_START",
                    "CHROMIUM_WASM_M1_TASK:RUNTIME_END",
                    TASK_RESULT_LINE.replace(requirement, "<missing>", 1),
                    "CHROMIUM_WASM_M1_TASK:PASS",
                ],
            }
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(invalid_result, "tasks")
        for old, new in (
            (" wake_count=3", " wake_count=11"),
            (" wait_count=1", " wait_count=9"),
            (" idle_wake_returns=1", " idle_wake_returns=2"),
            (
                " sleeping_quit_latency_ms=0",
                " sleeping_quit_latency_ms=1000",
            ),
            (" idle_elapsed_ms=250", " idle_elapsed_ms=2000"),
            (" idle_wake_latency_ms=0", " idle_wake_latency_ms=invalid"),
            (TASK_RESULT_LINE, f"{TASK_RESULT_LINE} unexpected=ok"),
            (" immediate=ok", " immediate=ok immediate=ok"),
            (TASK_RESULT_LINE, f"{TASK_RESULT_LINE}\n{TASK_RESULT_LINE}"),
        ):
            invalid_result = {
                **result,
                "stdout": [
                    line.replace(old, new, 1) for line in result["stdout"]
                ],
            }
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(invalid_result, "tasks")
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M1_TASK:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result, "tasks")

    def test_rust_result_requires_complete_result_contract(self) -> None:
        result = {
            "protocol": 1,
            "case": "rust",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 40,
                "animationFrameDelta": 20,
                "elapsedMs": 650,
            },
            "stdout": [
                "CHROMIUM_WASM_M1_RUST:RUNTIME_START",
                "CHROMIUM_WASM_M1_RUST:RUNTIME_END",
                RUST_RESULT_LINE,
                "CHROMIUM_WASM_M1_RUST:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "rust")
        for requirement in serve.RUST_RESULT_REQUIREMENTS:
            invalid_result = {
                **result,
                "stdout": [
                    "CHROMIUM_WASM_M1_RUST:RUNTIME_START",
                    "CHROMIUM_WASM_M1_RUST:RUNTIME_END",
                    RUST_RESULT_LINE.replace(requirement, "<missing>", 1),
                    "CHROMIUM_WASM_M1_RUST:PASS",
                ],
            }
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(invalid_result, "rust")
        for old, new in (
            ("pointer_width=32", "pointer_width=64"),
            (RUST_RESULT_LINE, f"{RUST_RESULT_LINE} unexpected=ok"),
            ("cpp_to_rust=ok", "cpp_to_rust=ok cpp_to_rust=ok"),
            (RUST_RESULT_LINE, f"{RUST_RESULT_LINE}\n{RUST_RESULT_LINE}"),
        ):
            invalid_result = {
                **result,
                "stdout": [
                    line.replace(old, new, 1) for line in result["stdout"]
                ],
            }
            with (
                self.subTest(replacement=new),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(invalid_result, "rust")
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M1_RUST:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result, "rust")

    def test_shared_memory_result_requires_complete_contract(self) -> None:
        result = {
            "protocol": 1,
            "case": "shared_memory",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 40,
                "animationFrameDelta": 20,
                "elapsedMs": 650,
            },
            "stdout": [
                "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_START",
                "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_END",
                SHARED_MEMORY_METRICS_LINE,
                SHARED_MEMORY_RESULT_LINE,
                "CHROMIUM_WASM_M1_SHARED_MEMORY:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "shared_memory")
        short_result = {
            **result,
            "heartbeat": {
                **result["heartbeat"],
                "elapsedMs": 225,
            },
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(
                short_result, "shared_memory"
            )
        for requirement in serve.SHARED_MEMORY_RESULT_REQUIREMENTS:
            invalid_result = {
                **result,
                "stdout": [
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_START",
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_END",
                    SHARED_MEMORY_METRICS_LINE.replace(
                        requirement, "<missing>", 1
                    ),
                    SHARED_MEMORY_RESULT_LINE.replace(
                        requirement, "<missing>", 1
                    ),
                    "CHROMIUM_WASM_M1_SHARED_MEMORY:PASS",
                ],
            }
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "shared_memory"
                )
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M1_SHARED_MEMORY:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result, "shared_memory")

    def test_mojo_result_requires_complete_contract(self) -> None:
        result = {
            "protocol": 1,
            "case": "mojo",
            "status": "pass",
            "exitCode": 0,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "canvasFocused": True,
            "failedChecks": [],
            "error": None,
            "heartbeat": {
                "timerDelta": 40,
                "animationFrameDelta": 20,
                "elapsedMs": 650,
            },
            "stdout": [
                "CHROMIUM_WASM_M1_MOJO:RUNTIME_START",
                "CHROMIUM_WASM_M1_MOJO:RUNTIME_END",
                MOJO_METRICS_LINE,
                MOJO_RESULT_LINE,
                "CHROMIUM_WASM_M1_MOJO:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "mojo")
        short_result = {
            **result,
            "heartbeat": {
                **result["heartbeat"],
                "elapsedMs": 225,
            },
        }
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(short_result, "mojo")
        for requirement in serve.MOJO_RESULT_REQUIREMENTS:
            invalid_result = {
                **result,
                "stdout": [
                    "CHROMIUM_WASM_M1_MOJO:RUNTIME_START",
                    "CHROMIUM_WASM_M1_MOJO:RUNTIME_END",
                    MOJO_METRICS_LINE.replace(
                        requirement, "<missing>", 1
                    ),
                    MOJO_RESULT_LINE.replace(
                        requirement, "<missing>", 1
                    ),
                    "CHROMIUM_WASM_M1_MOJO:PASS",
                ],
            }
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(M0Error),
            ):
                run_browser_smoke.validate_result(
                    invalid_result, "mojo"
                )
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M1_MOJO:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result, "mojo")


if __name__ == "__main__":
    unittest.main()

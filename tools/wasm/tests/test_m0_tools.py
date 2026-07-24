#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
from io import BytesIO
import importlib.util
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
from m0_common import M0Error, gn_args_text, load_manifest, parse_timeout, run
import run_browser_smoke
import run_node_smoke
import serve


TASK_RESULT_LINE = " ".join(serve.TASK_RESULT_REQUIREMENTS)
RUST_RESULT_LINE = " ".join(serve.RUST_RESULT_REQUIREMENTS)
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


class CommonTest(unittest.TestCase):
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
            angle["revision"],
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
                "CHROMIUM_WASM_M1_BASE:RESULT clocks=ok",
                "CHROMIUM_WASM_M1_BASE:PASS",
                'CHROMIUM_WASM_M1_BASE:NODE_EXIT {"exitCode":0}',
            )
        )
        run_node_smoke.validate_streams(stdout, "", "base")
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
        with self.assertRaises(M0Error):
            run_node_smoke.validate_streams(
                stdout + "\nCHROMIUM_WASM_M1_RUST:FAIL reason=test",
                "",
                "rust",
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
            'modulePath: "/out/wasm/m1_shared_memory_smoke.js"',
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
        for requirement in serve.SHARED_MEMORY_RESULT_REQUIREMENTS:
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


class BrowserRunnerTest(unittest.TestCase):
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
                "CHROMIUM_WASM_M1_BASE:RESULT clocks=ok",
                "CHROMIUM_WASM_M1_BASE:PASS",
            ],
            "stderr": [],
        }
        run_browser_smoke.validate_result(result, "base")
        result["stdout"] = [
            *result["stdout"],
            "CHROMIUM_WASM_M1_BASE:FAIL reason=test",
        ]
        with self.assertRaises(M0Error):
            run_browser_smoke.validate_result(result, "base")

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


if __name__ == "__main__":
    unittest.main()

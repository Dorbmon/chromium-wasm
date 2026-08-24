#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 instantiateStreaming page smoke."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error, REPO_ROOT
import run_m8_wasm_browser_devtools_protocol_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}
INSTANTIATE_STREAMING_MODULE_BASE64 = (
    "AGFzbQEAAAABBwFgAn9/AX8DAgEABwcBA2FkZAAACgkBBwAgACABags="
)
INSTANTIATE_STREAMING_MODULE_BYTES = base64.b64decode(
    INSTANTIATE_STREAMING_MODULE_BASE64
)
INSTANTIATE_STREAMING_MODULE_SHA256 = (
    "f61fd62f57c41269c3c23f360eeaf1090b1db9c38651106674d48bc65dba88ba"
)


def successful_instantiate_streaming_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SCOPE,
        "status": "pass",
        "m8GateComplete": False,
        "runtimeExitCode": 0,
        "processExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusAccepted": True,
        "networkEnableObserved": True,
        "runtimeEnableObserved": True,
        "runtimeEvaluateObserved": True,
        "pageWebAssemblyUnavailableObserved": False,
        "pageWebAssemblyAdd42Observed": False,
        "pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed": True,
        "pageWebAssemblyTablesObserved": False,
        "pageWebAssemblyTableConstructedImportedIndirectCallObserved": False,
        "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved": False,
        "pageWebAssemblyTableGrowthObserved": False,
        "pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved": False,
        "pageWebAssemblyMemoriesObserved": False,
        "pageWebAssemblyMemoryConstructedImportedReadWriteObserved": False,
        "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved": False,
        "pageWebAssemblyExceptionsObserved": False,
        "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved": False,
        "pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved": False,
        "pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved": False,
        "pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved": False,
        "pageWebAssemblyMemoryGrowthObserved": False,
        "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved": False,
        "pageWebAssemblyThreadsObserved": False,
        "runtimeConsoleApiCalledObserved": True,
        "detachedObserved": True,
        "lifecyclePassObserved": True,
        "abort": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": VERSIONS,
        "frameReports": [
            {"id": 1, "width": 640, "height": 480, "timestampMs": 1.0},
        ],
        "readiness": readiness,
        "readinessReports": [readiness],
        "stdout": [],
        "stderr": [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyInstantiateStreamingDomSmokeTest(unittest.TestCase):
    def test_fixed_module_has_exact_bytes_hash_and_add_export(self) -> None:
        self.assertEqual(len(INSTANTIATE_STREAMING_MODULE_BYTES), 41)
        self.assertEqual(
            hashlib.sha256(INSTANTIATE_STREAMING_MODULE_BYTES).hexdigest(),
            INSTANTIATE_STREAMING_MODULE_SHA256,
        )
        self.assertEqual(INSTANTIATE_STREAMING_MODULE_BYTES[:8], b"\0asm\x01\0\0\0")
        self.assertEqual(
            INSTANTIATE_STREAMING_MODULE_BYTES,
            bytes(
                (
                    0,
                    97,
                    115,
                    109,
                    1,
                    0,
                    0,
                    0,
                    1,
                    7,
                    1,
                    96,
                    2,
                    127,
                    127,
                    1,
                    127,
                    3,
                    2,
                    1,
                    0,
                    7,
                    7,
                    1,
                    3,
                    97,
                    100,
                    100,
                    0,
                    0,
                    10,
                    9,
                    1,
                    7,
                    0,
                    32,
                    0,
                    32,
                    1,
                    106,
                    11,
                )
            ),
        )

    def test_pinned_node_instantiates_the_fixed_wasm_mime_data_url(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        script = f"""
const result = await WebAssembly.instantiateStreaming(fetch(
    'data:application/wasm;base64,{INSTANTIATE_STREAMING_MODULE_BASE64}'));
if (!(result.module instanceof WebAssembly.Module) ||
    !(result.instance instanceof WebAssembly.Instance) ||
    result.instance.exports.add(20, 22) !== 42) {{
  throw new Error('fixed instantiateStreaming witness failed');
}}
process.stdout.write('instantiate-streaming-add-42');
"""
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        self.assertEqual("instantiate-streaming-add-42", completed.stdout)

    def test_mode_is_one_fixed_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG
        self.assertEqual(config.mode_id, "page-webassembly-instantiate-streaming")
        self.assertEqual(
            config.sentinel,
            "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_DOM",
        )
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-webassembly-instantiate-streaming-smoke",),
        )
        self.assertTrue(
            dict(config.page_webassembly_expectations)[
                "pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed"
            ]
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_instantiate_streaming(True),
            config,
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_instantiate_streaming(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_result_requires_only_the_fixed_streaming_witness(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG
        smoke.validate_result(
            successful_instantiate_streaming_result(),
            expected_versions=VERSIONS,
            smoke_config=config,
        )
        for field, expected in config.page_webassembly_expectations:
            with self.subTest(field=field):
                result = copy.deepcopy(successful_instantiate_streaming_result())
                result[field] = not expected
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result, expected_versions=VERSIONS, smoke_config=config
                    )
        result = successful_instantiate_streaming_result()
        result["m8GateComplete"] = True
        with self.assertRaisesRegex(M0Error, "m8GateComplete mismatch"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_result_rejects_wrong_or_repeated_marker(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG
        result = successful_instantiate_streaming_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_ADD42_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 0"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

        result = successful_instantiate_streaming_result()
        result["stderr"] = successful_instantiate_streaming_result()["stderr"] + [
            smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_url_and_server_bind_the_closed_mode_to_its_token(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG
        server = SimpleNamespace(server_address=("127.0.0.1", 31337))
        url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
            smoke_config=config,
        )
        self.assertEqual(
            parse_qs(urlsplit(url).query, keep_blank_values=True)["mode"],
            ["page-webassembly-instantiate-streaming"],
        )
        payload = json.dumps(successful_instantiate_streaming_result()).encode(
            "utf-8"
        )
        self.assertEqual(
            smoke.parse_result_payload(payload, smoke_config=config),
            successful_instantiate_streaming_result(),
        )

        result_server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        result_server.result_token = "fixed-instantiate-streaming-token"
        result_server.smoke_config = config
        thread = threading.Thread(target=result_server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = result_server.server_address[:2]
            binding_url = (
                "http://"
                f"{host}:{port}{smoke.HOST_ROOT}/config/"
                "fixed-instantiate-streaming-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {
                        "protocol": 1,
                        "mode": "page-webassembly-instantiate-streaming",
                    },
                )
            with self.assertRaises(HTTPError) as context:
                urlopen(
                    f"http://{host}:{port}{smoke.HOST_ROOT}/config/wrong-token",
                    timeout=5,
                )
            self.assertEqual(context.exception.code, 404)
            context.exception.close()
        finally:
            result_server.shutdown()
            result_server.server_close()
            thread.join(timeout=5)

    def test_host_keeps_module_execution_native_and_mode_token_bound(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            'const PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE =',
            '"page-webassembly-instantiate-streaming";',
            "PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_MODE",
            "PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER",
            "pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed:",
            "query.getAll(\"mode\")",
            "fetchExpectedSmokeMode",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in (
            "new WebAssembly",
            "WebAssembly.validate",
            "WebAssembly.Module",
            "WebAssembly.Instance",
            "WebAssembly.instantiateStreaming",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_native_route_has_one_literal_streaming_witness(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol_header = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"
        )
        protocol = source("chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc")
        runner = source("tools/wasm/run_m8_wasm_browser_devtools_protocol_dom_smoke.py")
        self.assertIn(
            '"wasm-browser-m8-page-webassembly-instantiate-streaming-smoke"',
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyInstantiateStreamingDevToolsProtocolSmoke",
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyInstantiateStreamingDevToolsProtocolSmoke",
            lifecycle,
        )
        self.assertIn("kInstantiateStreamingDataUrlModuleAdd42", protocol_header)
        self.assertIn("--page-webassembly-instantiate-streaming", runner)

        command_start = protocol.index(
            "kPageWebAssemblyInstantiateStreamingRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kFixedDevToolsProtocolSmokeUrl", command_start
        )
        command = protocol[command_start:command_end]
        for expected in (
            "WebAssembly.instantiateStreaming(fetch('data:application/wasm;base64,"
            + INSTANTIATE_STREAMING_MODULE_BASE64
            + "'))",
            '"awaitPromise":true',
            "r.module instanceof WebAssembly.Module",
            "r.instance instanceof WebAssembly.Instance",
            "r.instance.exports.add(20,22)!==42",
            "wasm-instantiate-streaming-data-url-add-42",
            "chromium-wasm-m8-page-webassembly-instantiate-streaming-data-url-add-42",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, command)
        for forbidden in (
            "new WebAssembly.Memory",
            "new WebAssembly.Table",
            "SharedArrayBuffer",
            "Atomics",
            "DataView",
            "memory.grow(",
            "table.grow(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, command)

    def test_existing_constructor_witness_remains_distinct(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG
        self.assertNotEqual(smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG, config)
        self.assertFalse(
            dict(config.page_webassembly_expectations)[
                "pageWebAssemblyAdd42Observed"
            ]
        )


if __name__ == "__main__":
    unittest.main()

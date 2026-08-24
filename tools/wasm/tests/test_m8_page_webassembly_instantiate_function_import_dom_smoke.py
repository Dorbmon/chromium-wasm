#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 instantiate() function-import page smoke."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import re
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
INSTANTIATE_FUNCTION_IMPORT_MODULE_BASE64 = (
    "AGFzbQEAAAABBwFgAn9/AX8CCwEDZW52A2FkZAAAAwIBAAcHAQNydW4AAQoKAQgAIAAgARAACw=="
)
INSTANTIATE_FUNCTION_IMPORT_MODULE_BYTES = base64.b64decode(
    INSTANTIATE_FUNCTION_IMPORT_MODULE_BASE64
)
INSTANTIATE_FUNCTION_IMPORT_MODULE_SHA256 = (
    "ec17979c4fe355f0c48e6df74d01e5606db27d93baa2a0df4c34c3489d80cbc0"
)


def successful_instantiate_function_import_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_SCOPE,
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
        "pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed": False,
        "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed": True,
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
            smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyInstantiateFunctionImportDomSmokeTest(unittest.TestCase):
    def test_fixed_module_has_exact_bytes_hash_and_function_import(self) -> None:
        self.assertEqual(len(INSTANTIATE_FUNCTION_IMPORT_MODULE_BYTES), 55)
        self.assertEqual(
            hashlib.sha256(INSTANTIATE_FUNCTION_IMPORT_MODULE_BYTES).hexdigest(),
            INSTANTIATE_FUNCTION_IMPORT_MODULE_SHA256,
        )
        self.assertEqual(
            INSTANTIATE_FUNCTION_IMPORT_MODULE_BYTES[:8], b"\0asm\x01\0\0\0"
        )
        self.assertEqual(
            INSTANTIATE_FUNCTION_IMPORT_MODULE_BYTES,
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
                    2,
                    11,
                    1,
                    3,
                    101,
                    110,
                    118,
                    3,
                    97,
                    100,
                    100,
                    0,
                    0,
                    3,
                    2,
                    1,
                    0,
                    7,
                    7,
                    1,
                    3,
                    114,
                    117,
                    110,
                    0,
                    1,
                    10,
                    10,
                    1,
                    8,
                    0,
                    32,
                    0,
                    32,
                    1,
                    16,
                    0,
                    11,
                )
            ),
        )

    def test_native_raw_bytes_pin_i32_import_and_run_body(self) -> None:
        protocol = source("chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc")
        command_start = protocol.index(
            "kPageWebAssemblyInstantiateFunctionImportRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kFixedDevToolsProtocolSmokeUrl", command_start
        )
        command = protocol[command_start:command_end]
        match = re.search(
            r'R"json\((?P<bytes>\d+(?:,\d+)*)\]\);\)json"', command
        )
        self.assertIsNotNone(match)
        assert match is not None
        native_bytes = bytes(int(value) for value in match["bytes"].split(","))

        self.assertEqual(native_bytes, INSTANTIATE_FUNCTION_IMPORT_MODULE_BYTES)
        self.assertEqual(
            hashlib.sha256(native_bytes).hexdigest(),
            INSTANTIATE_FUNCTION_IMPORT_MODULE_SHA256,
        )

        def read_unsigned_leb128(cursor: int) -> tuple[int, int]:
            result = 0
            shift = 0
            while True:
                self.assertLess(cursor, len(native_bytes))
                value = native_bytes[cursor]
                cursor += 1
                result |= (value & 0x7F) << shift
                if value & 0x80 == 0:
                    return result, cursor
                shift += 7

        self.assertEqual(native_bytes[:8], b"\0asm\x01\0\0\0")
        sections: dict[int, bytes] = {}
        cursor = 8
        while cursor < len(native_bytes):
            section_id = native_bytes[cursor]
            section_size, cursor = read_unsigned_leb128(cursor + 1)
            section_end = cursor + section_size
            self.assertLessEqual(section_end, len(native_bytes))
            self.assertNotIn(section_id, sections)
            sections[section_id] = native_bytes[cursor:section_end]
            cursor = section_end
        self.assertEqual(cursor, len(native_bytes))
        self.assertEqual(set(sections), {1, 2, 3, 7, 10})

        # One function type: (i32, i32) -> i32.
        self.assertEqual(sections[1], bytes((1, 0x60, 2, 0x7F, 0x7F, 1, 0x7F)))
        # One function import: env.add using type index 0.
        self.assertEqual(
            sections[2],
            bytes((1, 3, ord("e"), ord("n"), ord("v"), 3, ord("a"), ord("d"), ord("d"), 0, 0)),
        )
        # One defined function with type 0, exported as run at function index 1.
        self.assertEqual(sections[3], bytes((1, 0)))
        self.assertEqual(
            sections[7],
            bytes((1, 3, ord("r"), ord("u"), ord("n"), 0, 1)),
        )
        # run has no locals and executes local.get 0, local.get 1, call 0, end.
        self.assertEqual(
            sections[10], bytes((1, 8, 0, 0x20, 0, 0x20, 1, 0x10, 0, 0x0B))
        )

    def test_pinned_node_awaits_instantiate_and_witnesses_one_i32_callback(
        self,
    ) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        script = f"""
const bytes = Uint8Array.from(
    Buffer.from('{INSTANTIATE_FUNCTION_IMPORT_MODULE_BASE64}', 'base64'));
let callbackCount = 0;
const add = (left, right) => {{
  ++callbackCount;
  if (callbackCount !== 1 || !Number.isInteger(left) ||
      !Number.isInteger(right) || left !== 20 || right !== 22) {{
    throw new Error('fixed i32 import callback arguments changed');
  }}
  return left + right;
}};
const result = await WebAssembly.instantiate(bytes, {{env: {{add}}}});
if (!(result.module instanceof WebAssembly.Module) ||
    !(result.instance instanceof WebAssembly.Instance) ||
    result.instance.exports.run(20, 22) !== 42 || callbackCount !== 1) {{
  throw new Error('fixed instantiate function-import witness failed');
}}
process.stdout.write('instantiate-function-import-i32-20-22-add-42');
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
        self.assertEqual(
            "instantiate-function-import-i32-20-22-add-42", completed.stdout
        )

    def test_mode_is_one_fixed_experimental_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_SMOKE_CONFIG
        self.assertEqual(
            config.mode_id, "page-webassembly-instantiate-function-import"
        )
        self.assertEqual(
            config.sentinel,
            "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_DOM",
        )
        self.assertEqual(
            config.runtime_arguments,
            (
                "--wasm-browser-m8-page-webassembly-instantiate-function-import-smoke",
            ),
        )
        expectations = dict(config.page_webassembly_expectations)
        self.assertTrue(
            expectations[
                "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed"
            ]
        )
        self.assertFalse(
            expectations[
                "pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed"
            ]
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_instantiate_function_import(
                True
            ),
            config,
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_instantiate_function_import(
                False
            ),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_preexisting_page_webassembly_modes_close_the_import_witness(
        self,
    ) -> None:
        field = (
            "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed"
        )
        closed_configs = (
            smoke.DEFAULT_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG,
        )
        self.assertEqual(len(closed_configs), 13)
        for config in closed_configs:
            with self.subTest(runner_mode=config.mode_id):
                expectations = dict(config.page_webassembly_expectations)
                self.assertIn(field, expectations)
                self.assertIs(expectations[field], False)

        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        modes = [config.query_mode for config in closed_configs]
        host = (
            REPO_ROOT
            / "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        script = f"""
import {{parseDevToolsProtocolSmokeQuery}} from {json.dumps(host.as_uri())};
const modes = {json.dumps(modes)};
const field = {json.dumps(field)};
const records = modes.map((mode) => {{
  const query = new URLSearchParams({{
    token: "token",
    module: "chrome_wasm",
    timeoutMs: "30000",
    versions: JSON.stringify({json.dumps(VERSIONS)}),
  }});
  if (mode !== null) {{
    query.append("mode", mode);
  }}
  const parsed = parseDevToolsProtocolSmokeQuery(query);
  return [parsed.smokeMode.id,
          parsed.smokeMode.pageWebAssemblyExpectations[field]];
}});
process.stdout.write(JSON.stringify(records));
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
        self.assertEqual(
            [[config.mode_id, False] for config in closed_configs],
            json.loads(completed.stdout),
        )

    def test_result_requires_the_import_callback_witness_and_false_m8_gate(
        self,
    ) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_SMOKE_CONFIG
        smoke.validate_result(
            successful_instantiate_function_import_result(),
            expected_versions=VERSIONS,
            smoke_config=config,
        )
        for field, expected in config.page_webassembly_expectations:
            with self.subTest(field=field):
                result = copy.deepcopy(successful_instantiate_function_import_result())
                result[field] = not expected
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result, expected_versions=VERSIONS, smoke_config=config
                    )
        result = successful_instantiate_function_import_result()
        result["m8GateComplete"] = True
        with self.assertRaisesRegex(M0Error, "m8GateComplete mismatch"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_result_rejects_a_missing_or_repeated_exact_marker(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_SMOKE_CONFIG
        result = successful_instantiate_function_import_result()
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

    def test_url_and_server_bind_the_closed_mode_to_its_token(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_SMOKE_CONFIG
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
            ["page-webassembly-instantiate-function-import"],
        )
        payload = json.dumps(successful_instantiate_function_import_result()).encode(
            "utf-8"
        )
        self.assertEqual(
            smoke.parse_result_payload(payload, smoke_config=config),
            successful_instantiate_function_import_result(),
        )

        result_server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        result_server.result_token = "fixed-instantiate-function-import-token"
        result_server.smoke_config = config
        thread = threading.Thread(target=result_server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = result_server.server_address[:2]
            binding_url = (
                "http://"
                f"{host}:{port}{smoke.HOST_ROOT}/config/"
                "fixed-instantiate-function-import-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {
                        "protocol": 1,
                        "mode": "page-webassembly-instantiate-function-import",
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

        result = successful_instantiate_function_import_result()
        result["stderr"] = successful_instantiate_function_import_result()[
            "stderr"
        ] + [smoke.PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_MARKER]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_host_keeps_execution_native_and_mode_token_bound(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            'const PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_MODE =',
            '"page-webassembly-instantiate-function-import";',
            "PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_SMOKE_MODE",
            "PAGE_WEBASSEMBLY_INSTANTIATE_FUNCTION_IMPORT_MARKER",
            "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed:",
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
            "WebAssembly.instantiate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_native_route_has_one_literal_instantiate_import_witness(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol_header = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"
        )
        protocol = source("chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc")
        runner = source("tools/wasm/run_m8_wasm_browser_devtools_protocol_dom_smoke.py")

        self.assertIn(
            '"wasm-browser-m8-page-webassembly-instantiate-function-import-smoke"',
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyInstantiateFunctionImportDevToolsProtocolSmoke",
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyInstantiateFunctionImportDevToolsProtocolSmoke",
            lifecycle,
        )
        self.assertIn(
            "kInstantiateFunctionImportModuleInstanceAdd42", protocol_header
        )
        self.assertIn("--page-webassembly-instantiate-function-import", runner)

        command_start = protocol.index(
            "kPageWebAssemblyInstantiateFunctionImportRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kFixedDevToolsProtocolSmokeUrl", command_start
        )
        command = protocol[command_start:command_end]
        for expected in (
            "await WebAssembly.instantiate(bytes,{env:{add}})",
            '"awaitPromise":true',
            "r.module instanceof WebAssembly.Module",
            "r.instance instanceof WebAssembly.Instance",
            "r.instance.exports.run(20,22)!==42",
            "callbackCount!==1",
            "Number.isInteger(left)",
            "Number.isInteger(right)",
            "left!==20||right!==22",
            "wasm-instantiate-function-import-module-instance-callback-i32-20-22-add-42",
            "chromium-wasm-m8-page-webassembly-instantiate-function-import-module-instance-callback-i32-20-22-add-42",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, command)
        for forbidden in (
            "WebAssembly.instantiateStreaming",
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


if __name__ == "__main__":
    unittest.main()

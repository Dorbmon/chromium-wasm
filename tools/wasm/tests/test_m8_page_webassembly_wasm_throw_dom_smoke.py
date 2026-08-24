#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 page-WebAssembly-Wasm-throw smoke."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_wasm_browser_devtools_protocol_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {"chromium": "c", "v8": "v", "emscripten": "e", "port": "p"}

# The fixed module imports a zero-payload tag as env.tag and exports one
# thrower() function. Its body is local declarations, throw 0, and end.
# Keep this module literal so the contract remains narrower than exception
# proposal coverage.
WASM_THROW_MODULE_BYTES = bytes(
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
        4,
        1,
        96,
        0,
        0,
        2,
        12,
        1,
        3,
        101,
        110,
        118,
        3,
        116,
        97,
        103,
        4,
        0,
        0,
        3,
        2,
        1,
        0,
        7,
        11,
        1,
        7,
        116,
        104,
        114,
        111,
        119,
        101,
        114,
        0,
        0,
        10,
        6,
        1,
        4,
        0,
        8,
        0,
        11,
    )
)
WASM_THROW_MODULE_SHA256 = (
    "4eed4c816377e1ec571ca17b5a5d5a100e1ea62a800073f285ab14596077dd80"
)


def successful_wasm_throw_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_WASM_THROW_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_WASM_THROW_SCOPE,
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
        "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed": False,
        "pageWebAssemblyTablesObserved": False,
        "pageWebAssemblyTableConstructedImportedIndirectCallObserved": False,
        "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved": False,
        "pageWebAssemblyTableGrowthObserved": False,
        "pageWebAssemblyMemoriesObserved": False,
        "pageWebAssemblyMemoryConstructedImportedReadWriteObserved": False,
        "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved": False,
        "pageWebAssemblyExceptionsObserved": True,
        "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved": False,
        "pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved": True,
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
            smoke.PAGE_WEBASSEMBLY_WASM_THROW_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyWasmThrowDomSmokeTest(unittest.TestCase):
    def test_fixed_module_has_exact_bytes_hash_and_throw_opcode(self) -> None:
        self.assertEqual(len(WASM_THROW_MODULE_BYTES), 53)
        self.assertEqual(
            hashlib.sha256(WASM_THROW_MODULE_BYTES).hexdigest(),
            WASM_THROW_MODULE_SHA256,
        )
        self.assertEqual(WASM_THROW_MODULE_BYTES[:8], b"\0asm\x01\0\0\0")
        self.assertIn(
            b"\x02\x0c\x01\x03env\x03tag\x04\x00\x00",
            WASM_THROW_MODULE_BYTES,
        )
        self.assertIn(
            b"\x0a\x06\x01\x04\x00\x08\x00\x0b",
            WASM_THROW_MODULE_BYTES,
        )

    def test_mode_is_a_single_fixed_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG
        self.assertEqual(config.mode_id, "page-webassembly-wasm-throw")
        self.assertEqual(config.query_mode, "page-webassembly-wasm-throw")
        self.assertEqual(
            config.sentinel, "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_WASM_THROW_DOM"
        )
        self.assertEqual(config.case, "browser_page_webassembly_wasm_throw_m8")
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-webassembly-wasm-throw-smoke",),
        )
        self.assertEqual(
            config.page_webassembly_expectations,
            (
                ("pageWebAssemblyUnavailableObserved", False),
                ("pageWebAssemblyAdd42Observed", False),
                (
                    "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed",
                    False,
                ),
                ("pageWebAssemblyTablesObserved", False),
                (
                    "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
                    False,
                ),
                (
                    "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
                    False,
                ),
                ("pageWebAssemblyTableGrowthObserved", False),
                ("pageWebAssemblyMemoriesObserved", False),
                (
                    "pageWebAssemblyMemoryConstructedImportedReadWriteObserved",
                    False,
                ),
                (
                    "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
                    False,
                ),
                ("pageWebAssemblyExceptionsObserved", True),
                (
                    "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
                    False,
                ),
                (
                    "pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved",
                    True,
                ),
                ("pageWebAssemblyMemoryGrowthObserved", False),
                (
                    "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
                    False,
                ),
                ("pageWebAssemblyThreadsObserved", False),
            ),
        )
        self.assertIs(smoke.smoke_config_for_page_webassembly_wasm_throw(True), config)
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_wasm_throw(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_result_requires_only_the_fixed_wasm_throw_witness(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG
        smoke.validate_result(
            successful_wasm_throw_result(),
            expected_versions=VERSIONS,
            smoke_config=config,
        )
        for field, expected in config.page_webassembly_expectations:
            with self.subTest(field=field):
                result = copy.deepcopy(successful_wasm_throw_result())
                result[field] = not expected
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result, expected_versions=VERSIONS, smoke_config=config
                    )
        result = successful_wasm_throw_result()
        result["m8GateComplete"] = True
        with self.assertRaisesRegex(M0Error, "m8GateComplete mismatch"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_result_rejects_wrong_or_repeated_throw_marker(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG
        result = successful_wasm_throw_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 0"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

        result = successful_wasm_throw_result()
        result["stderr"] = successful_wasm_throw_result()["stderr"] + [
            smoke.PAGE_WEBASSEMBLY_WASM_THROW_MARKER
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_url_and_server_bind_the_closed_wasm_throw_mode_to_its_token(
        self,
    ) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG
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
            parse_qs(urlsplit(url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [
                    json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))
                ],
                "mode": ["page-webassembly-wasm-throw"],
            },
        )
        payload = json.dumps(successful_wasm_throw_result()).encode("utf-8")
        self.assertEqual(
            smoke.parse_result_payload(payload, smoke_config=config),
            successful_wasm_throw_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

        result_server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        result_server.result_token = "fixed-wasm-throw-mode-token"
        result_server.smoke_config = config
        thread = threading.Thread(target=result_server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = result_server.server_address[:2]
            binding_url = (
                "http://"
                f"{host}:{port}{smoke.HOST_ROOT}/config/fixed-wasm-throw-mode-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {"protocol": 1, "mode": "page-webassembly-wasm-throw"},
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
            'const PAGE_WEBASSEMBLY_WASM_THROW_MODE = "page-webassembly-wasm-throw";',
            "PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_MODE",
            "PAGE_WEBASSEMBLY_WASM_THROW_MARKER",
            "pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved:",
            "query.getAll(\"mode\")",
            "DevTools protocol query has an invalid mode",
            "fetchExpectedSmokeMode",
            "DevTools protocol query mode does not match its binding",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in (
            "new WebAssembly",
            "WebAssembly.validate",
            "WebAssembly.Module",
            "WebAssembly.Instance",
            "WebAssembly.Tag",
            "WebAssembly.Exception",
            "globalThis.WebAssembly",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        self.assertLess(
            host.index("const expectedSmokeMode = await fetchExpectedSmokeMode"),
            host.index("const result = validateResult(await host.run("),
        )

    def test_native_route_has_one_literal_wasm_throw_witness(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol_header = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"
        )
        protocol = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc"
        )
        runner = source("tools/wasm/run_m8_wasm_browser_devtools_protocol_dom_smoke.py")
        self.assertIn(
            '"wasm-browser-m8-page-webassembly-wasm-throw-smoke"', main_parts
        )
        self.assertIn(
            "StartPageWebAssemblyWasmThrowDevToolsProtocolSmoke", main_parts
        )
        self.assertIn(
            "StartPageWebAssemblyWasmThrowDevToolsProtocolSmoke", lifecycle
        )
        self.assertIn("kWasmThrowImportedTagJsCatch", protocol_header)
        self.assertIn("--page-webassembly-wasm-throw", runner)

        command_start = protocol.index(
            "kPageWebAssemblyWasmThrowRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kPageWebAssemblyWasmThrowPayloadRuntimeEvaluateCommand",
            command_start,
        )
        command = protocol[command_start:command_end]
        for expected in (
            "WebAssembly.validate(b)",
            "new WebAssembly.Tag({parameters:[]})",
            "new WebAssembly.Module(b)",
            "new WebAssembly.Instance(m,{env:{tag}})",
            "i.exports.thrower()",
            "error instanceof WebAssembly.Exception&&error.is(tag)",
            "wasm-throw-imported-tag-js-catch",
            "chromium-wasm-m8-page-webassembly-wasm-throw-imported-tag-js-catch",
            "0,97,115,109,1,0,0,0,1,4,1,96,0,0,2,12,1,3,101,110,118,3,116,97,103,4,0,0,3,2,1,0,7,11,1,7,116,104,114,111,119,101,114,0,0,10,6,1,4,0,8,0,11",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, command)
        for forbidden in (
            "WebAssembly.Memory",
            "memory.grow",
            "WebAssembly.Table",
            "table.grow",
            "thrower:()=>",
            "catch_all",
            "SharedArrayBuffer",
            "Atomics",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, command)

    def test_existing_exception_and_opcode_modes_remain_distinct(self) -> None:
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_exceptions(True),
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_wasm_memory_grow_opcode(
                True
            ),
            smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG,
        )


if __name__ == "__main__":
    unittest.main()

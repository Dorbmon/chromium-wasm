#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 Wasm-memory.grow-opcode page smoke."""

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

# The fixed module imports one unshared min-one/max-two-page memory and
# exports grow(). Its entire body is local declarations, i32.const 1,
# memory.grow 0, and end. Keep this literal independent from the prior
# JavaScript Memory.grow witness.
WASM_MEMORY_GROW_OPCODE_MODULE_BYTES = bytes(
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
        5,
        1,
        96,
        0,
        1,
        127,
        2,
        16,
        1,
        3,
        101,
        110,
        118,
        6,
        109,
        101,
        109,
        111,
        114,
        121,
        2,
        1,
        1,
        2,
        3,
        2,
        1,
        0,
        7,
        8,
        1,
        4,
        103,
        114,
        111,
        119,
        0,
        0,
        10,
        8,
        1,
        6,
        0,
        65,
        1,
        64,
        0,
        11,
    )
)
WASM_MEMORY_GROW_OPCODE_MODULE_SHA256 = (
    "0df594f78d533e8ed48daf4b604e49cef42d169dd3304208f3edef72a15fd4fa"
)


def successful_wasm_memory_grow_opcode_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SCOPE,
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
        "pageWebAssemblyTablesObserved": False,
        "pageWebAssemblyTableConstructedImportedIndirectCallObserved": False,
        "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved": False,
        "pageWebAssemblyTableGrowthObserved": False,
        "pageWebAssemblyMemoriesObserved": True,
        "pageWebAssemblyMemoryConstructedImportedReadWriteObserved": False,
        "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved": False,
        "pageWebAssemblyExceptionsObserved": False,
        "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved": False,
        "pageWebAssemblyMemoryGrowthObserved": True,
        "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved": True,
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
            smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyWasmMemoryGrowOpcodeDomSmokeTest(unittest.TestCase):
    def test_fixed_module_has_exact_bytes_hash_and_opcode(self) -> None:
        self.assertEqual(len(WASM_MEMORY_GROW_OPCODE_MODULE_BYTES), 57)
        self.assertEqual(
            hashlib.sha256(WASM_MEMORY_GROW_OPCODE_MODULE_BYTES).hexdigest(),
            WASM_MEMORY_GROW_OPCODE_MODULE_SHA256,
        )
        self.assertEqual(WASM_MEMORY_GROW_OPCODE_MODULE_BYTES[:8], b"\0asm\x01\0\0\0")
        self.assertIn(
            b"\x02\x10\x01\x03env\x06memory\x02\x01\x01\x02",
            WASM_MEMORY_GROW_OPCODE_MODULE_BYTES,
        )
        self.assertIn(
            b"\x0a\x08\x01\x06\x00\x41\x01\x40\x00\x0b",
            WASM_MEMORY_GROW_OPCODE_MODULE_BYTES,
        )

    def test_mode_is_one_fixed_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG
        self.assertEqual(
            config.mode_id, "page-webassembly-wasm-memory-grow-opcode"
        )
        self.assertEqual(
            config.query_mode, "page-webassembly-wasm-memory-grow-opcode"
        )
        self.assertEqual(
            config.sentinel,
            "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_DOM",
        )
        self.assertEqual(
            config.case, "browser_page_webassembly_wasm_memory_grow_opcode_m8"
        )
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-webassembly-wasm-memory-grow-opcode-smoke",),
        )
        self.assertEqual(
            config.page_webassembly_expectations,
            (
                ("pageWebAssemblyUnavailableObserved", False),
                ("pageWebAssemblyAdd42Observed", False),
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
                ("pageWebAssemblyMemoriesObserved", True),
                (
                    "pageWebAssemblyMemoryConstructedImportedReadWriteObserved",
                    False,
                ),
                (
                    "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
                    False,
                ),
                ("pageWebAssemblyExceptionsObserved", False),
                (
                    "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
                    False,
                ),
                ("pageWebAssemblyMemoryGrowthObserved", True),
                (
                    "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
                    True,
                ),
                ("pageWebAssemblyThreadsObserved", False),
            ),
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_wasm_memory_grow_opcode(
                True
            ),
            config,
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_wasm_memory_grow_opcode(
                False
            ),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_result_requires_only_the_fixed_opcode_witness(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG
        smoke.validate_result(
            successful_wasm_memory_grow_opcode_result(),
            expected_versions=VERSIONS,
            smoke_config=config,
        )
        for field, expected in config.page_webassembly_expectations:
            with self.subTest(field=field):
                result = copy.deepcopy(successful_wasm_memory_grow_opcode_result())
                result[field] = not expected
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result, expected_versions=VERSIONS, smoke_config=config
                    )
        result = successful_wasm_memory_grow_opcode_result()
        result["m8GateComplete"] = True
        with self.assertRaisesRegex(M0Error, "m8GateComplete mismatch"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_result_rejects_wrong_or_repeated_opcode_marker(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG
        result = successful_wasm_memory_grow_opcode_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 0"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

        result = successful_wasm_memory_grow_opcode_result()
        result["stderr"] = successful_wasm_memory_grow_opcode_result()[
            "stderr"
        ] + [smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result, expected_versions=VERSIONS, smoke_config=config
            )

    def test_url_and_server_bind_the_closed_opcode_mode_to_its_token(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG
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
                "mode": ["page-webassembly-wasm-memory-grow-opcode"],
            },
        )
        payload = json.dumps(successful_wasm_memory_grow_opcode_result()).encode(
            "utf-8"
        )
        self.assertEqual(
            smoke.parse_result_payload(payload, smoke_config=config),
            successful_wasm_memory_grow_opcode_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

        result_server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        result_server.result_token = "fixed-wasm-memory-grow-opcode-token"
        result_server.smoke_config = config
        thread = threading.Thread(target=result_server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = result_server.server_address[:2]
            binding_url = (
                "http://"
                f"{host}:{port}{smoke.HOST_ROOT}/config/"
                "fixed-wasm-memory-grow-opcode-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {"protocol": 1, "mode": "page-webassembly-wasm-memory-grow-opcode"},
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
            'const PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE =',
            '"page-webassembly-wasm-memory-grow-opcode";',
            "PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_MODE",
            "PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER",
            "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:",
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
            "memory.grow(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        self.assertLess(
            host.index("const expectedSmokeMode = await fetchExpectedSmokeMode"),
            host.index("const result = validateResult(await host.run("),
        )

    def test_native_route_has_one_literal_wasm_memory_grow_opcode_witness(
        self,
    ) -> None:
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
            '"wasm-browser-m8-page-webassembly-wasm-memory-grow-opcode-smoke"',
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyWasmMemoryGrowOpcodeDevToolsProtocolSmoke",
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyWasmMemoryGrowOpcodeDevToolsProtocolSmoke",
            lifecycle,
        )
        self.assertIn("kWasmMemoryGrowOpcodeImport", protocol_header)
        self.assertIn(
            "--page-webassembly-wasm-memory-grow-opcode", runner
        )

        command_start = protocol.index(
            "kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kFixedDevToolsProtocolSmokeUrl", command_start
        )
        command = protocol[command_start:command_end]
        for expected in (
            "WebAssembly.validate(b)",
            "new WebAssembly.Memory({initial:1,maximum:2})",
            "new WebAssembly.Module(b)",
            "new WebAssembly.Instance(m,{env:{memory}})",
            "i.exports.grow()!==1",
            "beforeGrowth.byteLength!==0",
            "grownBuffer.byteLength!==131072",
            "wasm-memory-grow-opcode-import-one-to-two-pages",
            "chromium-wasm-m8-page-webassembly-wasm-memory-grow-opcode-import-one-to-two-pages",
            "0,97,115,109,1,0,0,0,1,5,1,96,0,1,127,2,16,1,3,101,110,118,6,109,101,109,111,114,121,2,1,1,2,",
            "3,2,1,0,7,8,1,4,103,114,111,119,0,0,10,8,1,6,0,65,1,64,0,11",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, command)
        for forbidden in (
            "memory.grow(",
            "WebAssembly.Table",
            "WebAssembly.Tag",
            "WebAssembly.Exception",
            "SharedArrayBuffer",
            "Atomics",
            "DataView",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, command)

    def test_existing_modes_remain_distinct(self) -> None:
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_exceptions(True),
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_memory_growth(True),
            smoke.PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG,
        )


if __name__ == "__main__":
    unittest.main()

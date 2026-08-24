#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 page-WebAssembly-exceptions smoke."""

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

# The fixed module imports `env.thrower` as a function and `env.tag` as a
# zero-payload exception tag. Its only exported function catches that tag
# after calling the imported JavaScript thrower and returns 42. Keep this
# module literal so the test cannot accidentally turn into generic exception
# coverage.
EXCEPTION_MODULE_BYTES = bytes(
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
        8,
        2,
        96,
        0,
        0,
        96,
        0,
        1,
        127,
        2,
        26,
        2,
        3,
        101,
        110,
        118,
        7,
        116,
        104,
        114,
        111,
        119,
        101,
        114,
        0,
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
        1,
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
        13,
        1,
        11,
        0,
        6,
        127,
        16,
        0,
        7,
        0,
        65,
        42,
        11,
        11,
    )
)
EXCEPTION_MODULE_SHA256 = (
    "206e527ad1303603c64031ae0357733dd430cc1da548f541ec62c150d74b3bfe"
)


def successful_page_exceptions_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SCOPE,
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
        "pageWebAssemblyMemoriesObserved": False,
        "pageWebAssemblyMemoryConstructedImportedReadWriteObserved": False,
        "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved": False,
        "pageWebAssemblyExceptionsObserved": True,
        "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved": True,
        "pageWebAssemblyMemoryGrowthObserved": False,
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
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyExceptionsDomSmokeTest(unittest.TestCase):
    def test_fixed_exception_module_has_exact_bytes_hash_and_semantics(
        self,
    ) -> None:
        self.assertEqual(len(EXCEPTION_MODULE_BYTES), 74)
        self.assertEqual(
            hashlib.sha256(EXCEPTION_MODULE_BYTES).hexdigest(),
            EXCEPTION_MODULE_SHA256,
        )
        self.assertEqual(EXCEPTION_MODULE_BYTES[:8], b"\0asm\x01\0\0\0")

        # Import section: `env.thrower` is function type 1, and `env.tag` is
        # a zero-payload exception tag of type 0. The code body uses `try`
        # result i32, `call 0`, `catch 0`, and `i32.const 42`.
        self.assertIn(
            b"\x02\x1a\x02\x03env\x07thrower\x00\x01"
            b"\x03env\x03tag\x04\x00\x00",
            EXCEPTION_MODULE_BYTES,
        )
        self.assertIn(
            b"\x0a\x0d\x01\x0b\x00\x06\x7f\x10\x00"
            b"\x07\x00\x41\x2a\x0b\x0b",
            EXCEPTION_MODULE_BYTES,
        )

    def test_page_exceptions_mode_is_a_single_fixed_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG
        self.assertEqual(config.mode_id, "page-webassembly-exceptions")
        self.assertEqual(config.query_mode, "page-webassembly-exceptions")
        self.assertEqual(
            config.sentinel,
            "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_EXCEPTIONS_DOM",
        )
        self.assertEqual(config.case, "browser_page_webassembly_exceptions_m8")
        self.assertEqual(
            config.scope,
            "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
            "runtime-enable-runtime-evaluate-page-webassembly-exception-construct-import-"
            "tag-js-throw-wasm-catch-console-event-detach-close",
        )
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-webassembly-exceptions-smoke",),
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
                    True,
                ),
                ("pageWebAssemblyMemoryGrowthObserved", False),
                ("pageWebAssemblyThreadsObserved", False),
            ),
        )
        self.assertEqual(
            config.native_markers,
            (
                smoke.NETWORK_ENABLE_MARKER,
                smoke.RUNTIME_ENABLE_MARKER,
                smoke.RUNTIME_EVALUATE_MARKER,
                smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            ),
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_exceptions(True), config
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_exceptions(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_page_exceptions_result_requires_only_its_fixed_witness(
        self,
    ) -> None:
        smoke.validate_result(
            successful_page_exceptions_result(),
            expected_versions=VERSIONS,
            smoke_config=smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
        )
        for field, value in (
            ("pageWebAssemblyUnavailableObserved", True),
            ("pageWebAssemblyAdd42Observed", True),
            ("pageWebAssemblyTablesObserved", True),
            (
                "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
                True,
            ),
            (
                "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
                True,
            ),
            ("pageWebAssemblyTableGrowthObserved", True),
            ("pageWebAssemblyMemoriesObserved", True),
            (
                "pageWebAssemblyMemoryConstructedImportedReadWriteObserved",
                True,
            ),
            (
                "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
                True,
            ),
            ("pageWebAssemblyExceptionsObserved", False),
            (
                "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
                False,
            ),
            ("pageWebAssemblyMemoryGrowthObserved", True),
            ("pageWebAssemblyThreadsObserved", True),
            ("m8GateComplete", True),
        ):
            with self.subTest(field=field):
                result = copy.deepcopy(successful_page_exceptions_result())
                result[field] = value
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result,
                        expected_versions=VERSIONS,
                        smoke_config=(
                            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG
                        ),
                    )

    def test_page_exceptions_result_rejects_wrong_or_repeated_native_markers(
        self,
    ) -> None:
        result = successful_page_exceptions_result()
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
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
            )

        result = successful_page_exceptions_result()
        result["stderr"] = successful_page_exceptions_result()["stderr"] + [
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
            )

    def test_url_and_server_payload_bind_the_closed_page_exceptions_mode(
        self,
    ) -> None:
        server = SimpleNamespace(server_address=("127.0.0.1", 31337))
        default_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
        )
        exceptions_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
            smoke_config=smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
        )
        self.assertNotIn("mode=", default_url)
        self.assertEqual(
            parse_qs(urlsplit(default_url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [
                    json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))
                ],
            },
        )
        self.assertEqual(
            parse_qs(urlsplit(exceptions_url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [
                    json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))
                ],
                "mode": ["page-webassembly-exceptions"],
            },
        )

        payload = json.dumps(successful_page_exceptions_result()).encode("utf-8")
        self.assertEqual(
            smoke.parse_result_payload(
                payload,
                smoke_config=smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
            ),
            successful_page_exceptions_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

    def test_server_binds_the_page_exceptions_mode_to_the_result_token(
        self,
    ) -> None:
        config = smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG
        server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        server.result_token = "fixed-exceptions-mode-token"
        server.smoke_config = config
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            host, port = server.server_address[:2]
            binding_url = (
                "http://"
                f"{host}:{port}{smoke.HOST_ROOT}/config/"
                "fixed-exceptions-mode-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {"protocol": 1, "mode": "page-webassembly-exceptions"},
                )
            with self.assertRaises(HTTPError) as context:
                urlopen(
                    f"http://{host}:{port}{smoke.HOST_ROOT}/config/wrong-token",
                    timeout=5,
                )
            self.assertEqual(context.exception.code, 404)
            context.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_existing_modes_remain_closed_and_distinct(self) -> None:
        self.assertEqual(
            smoke.DEFAULT_SMOKE_CONFIG.runtime_arguments,
            ("--wasm-browser-devtools-protocol-smoke",),
        )
        self.assertEqual(
            smoke.DEFAULT_SMOKE_CONFIG.page_webassembly_expectations,
            (("pageWebAssemblyUnavailableObserved", True),),
        )
        self.assertIsNone(smoke.DEFAULT_SMOKE_CONFIG.query_mode)
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_table_growth(True),
            smoke.PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_CONFIG,
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_memory_growth(True),
            smoke.PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
        )

    def test_host_rejects_query_tampering_before_the_module_loader(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            'const PAGE_WEBASSEMBLY_EXCEPTIONS_MODE = "page-webassembly-exceptions";',
            "const PAGE_WEBASSEMBLY_EXCEPTIONS_SWITCH =",
            '"--wasm-browser-m8-page-webassembly-exceptions-smoke";',
            "PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER",
            "PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_MODE",
            "pageWebAssemblyAdd42Observed: false",
            "pageWebAssemblyTablesObserved: false",
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved: false",
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false",
            "pageWebAssemblyTableGrowthObserved: false",
            "pageWebAssemblyMemoriesObserved: false",
            "pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false",
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false",
            "pageWebAssemblyExceptionsObserved: true",
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: true",
            "pageWebAssemblyMemoryGrowthObserved: false",
            "pageWebAssemblyThreadsObserved: false",
            'query.getAll("mode")',
            "DevTools protocol query has an invalid mode",
            "DevTools protocol query has an unsupported field",
            "fetchExpectedSmokeMode",
            "DevTools protocol query mode does not match its binding",
            "PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_MODE ?",
            "[PAGE_WEBASSEMBLY_EXCEPTIONS_SWITCH]",
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

    def test_native_route_has_one_literal_exception_witness(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol_header = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"
        )
        protocol = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc"
        )
        self.assertIn(
            '"wasm-browser-m8-page-webassembly-exceptions-smoke"', main_parts
        )
        self.assertIn(
            "browser_lifecycle_->StartPageWebAssemblyExceptionDevToolsProtocolSmoke();",
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyExceptionDevToolsProtocolSmoke", lifecycle
        )
        self.assertIn(
            "kExceptionImportedTagJsThrowWasmCatch", protocol_header
        )
        for expected in (
            "kExceptionImportedTagJsThrowWasmCatch",
            "kPageWebAssemblyExceptionRuntimeEvaluateCommand",
            "WebAssembly.validate(b)",
            "new WebAssembly.Tag({parameters:[]})",
            "new WebAssembly.Exception(tag,[])",
            "new WebAssembly.Module",
            "new WebAssembly.Instance",
            "env:{tag,thrower:()=>{throw exception}}",
            "i.exports.run()!==42",
            "wasm-exception-imported-tag-js-throw-wasm-catch",
            "chromium-wasm-m8-page-webassembly-exception-imported-tag-js-throw-wasm-catch",
            "kPageWebAssemblyExceptionSuccessMarker",
            "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:",
            "EXCEPTION_CONSTRUCTED_IMPORTED_TAG_JS_THROW_WASM_CATCH_42_OK",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, protocol)

        command_start = protocol.index(
            "kPageWebAssemblyExceptionRuntimeEvaluateCommand"
        )
        command_end = protocol.index(
            "constexpr char kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeEvaluateCommand",
            command_start,
        )
        command = protocol[command_start:command_end]
        for expected in (
            "0,97,115,109,1,0,0,0,1,8,2,96,0,0,96,0,1,127,2,26,2,3,101,110,118,7,116,104,114,111,119,101,114,0,1,3,101,110,118,3,116,97,103,4,0,0,",
            "3,2,1,1,7,7,1,3,114,117,110,0,1,10,13,1,11,0,6,127,16,0,7,0,65,42,11,11",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, command)
        self.assertLess(
            command.index("new WebAssembly.Tag({parameters:[]})"),
            command.index("new WebAssembly.Exception(tag,[])"),
        )
        self.assertLess(
            command.index("new WebAssembly.Exception(tag,[])"),
            command.index("i.exports.run()!==42"),
        )
        for forbidden in (
            "WebAssembly.Memory",
            "memory.grow",
            "WebAssembly.Table",
            "table.grow",
            "SharedArrayBuffer",
            "Atomics",
            "WebAssembly.Function",
            "WebAssembly.JSTag",
            "catch_all",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, command)


if __name__ == "__main__":
    unittest.main()

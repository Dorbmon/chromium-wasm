#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the bounded M8 page-WebAssembly-table browser-host smoke."""

from __future__ import annotations

import copy
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


def successful_page_table_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_TABLE_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_TABLE_SCOPE,
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
        "pageWebAssemblyTablesObserved": True,
        "pageWebAssemblyTableConstructedImportedIndirectCallObserved": True,
        "pageWebAssemblyTableGrowthObserved": False,
        "pageWebAssemblyMemoriesObserved": False,
        "pageWebAssemblyExceptionsObserved": False,
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
            smoke.PAGE_WEBASSEMBLY_TABLE_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyTableDomSmokeTest(unittest.TestCase):
    def test_page_table_mode_is_a_single_fixed_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG
        self.assertEqual(config.mode_id, "page-webassembly-table")
        self.assertEqual(config.query_mode, "page-webassembly-table")
        self.assertEqual(
            config.sentinel, "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_TABLE_DOM"
        )
        self.assertEqual(config.case, "browser_page_webassembly_table_m8")
        self.assertEqual(
            config.scope,
            "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
            "runtime-enable-runtime-evaluate-page-webassembly-table-construct-import-"
            "element-initialize-indirect-call-console-event-detach-close",
        )
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-webassembly-table-smoke",),
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
                ("pageWebAssemblyTablesObserved", True),
                (
                    "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
                    True,
                ),
                ("pageWebAssemblyTableGrowthObserved", False),
                ("pageWebAssemblyMemoriesObserved", False),
                ("pageWebAssemblyExceptionsObserved", False),
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
                smoke.PAGE_WEBASSEMBLY_TABLE_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            ),
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_table(True), config
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly_table(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_page_table_result_requires_only_its_fixed_witness(self) -> None:
        smoke.validate_result(
            successful_page_table_result(),
            expected_versions=VERSIONS,
            smoke_config=smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
        )
        for field, value in (
            ("pageWebAssemblyUnavailableObserved", True),
            ("pageWebAssemblyAdd42Observed", True),
            ("pageWebAssemblyTablesObserved", False),
            ("pageWebAssemblyTableConstructedImportedIndirectCallObserved", False),
            ("pageWebAssemblyTableGrowthObserved", True),
            ("pageWebAssemblyMemoriesObserved", True),
            ("pageWebAssemblyExceptionsObserved", True),
            ("pageWebAssemblyMemoryGrowthObserved", True),
            ("pageWebAssemblyThreadsObserved", True),
            ("m8GateComplete", True),
        ):
            with self.subTest(field=field):
                result = copy.deepcopy(successful_page_table_result())
                result[field] = value
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result,
                        expected_versions=VERSIONS,
                        smoke_config=smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
                    )

    def test_page_table_result_rejects_wrong_or_repeated_native_markers(
        self,
    ) -> None:
        result = successful_page_table_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_MEMORY_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 0"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
            )

        result = successful_page_table_result()
        result["stderr"] = successful_page_table_result()["stderr"] + [
            smoke.PAGE_WEBASSEMBLY_TABLE_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
            )

    def test_url_and_server_payload_bind_the_closed_page_table_mode(self) -> None:
        server = SimpleNamespace(server_address=("127.0.0.1", 31337))
        default_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
        )
        table_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
            smoke_config=smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
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
            parse_qs(urlsplit(table_url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [
                    json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))
                ],
                "mode": ["page-webassembly-table"],
            },
        )

        payload = json.dumps(successful_page_table_result()).encode("utf-8")
        self.assertEqual(
            smoke.parse_result_payload(
                payload, smoke_config=smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG
            ),
            successful_page_table_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

    def test_server_binds_the_page_table_mode_to_the_result_token(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG
        server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        server.result_token = "fixed-table-mode-token"
        server.smoke_config = config
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            host, port = server.server_address[:2]
            binding_url = (
                f"http://{host}:{port}{smoke.HOST_ROOT}/config/fixed-table-mode-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {"protocol": 1, "mode": "page-webassembly-table"},
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
            (
                ("pageWebAssemblyUnavailableObserved", True),
                (
                    "pageWebAssemblyInstantiateFunctionImportModuleInstanceCallbackI32Add42Observed",
                    False,
                ),
            ),
        )
        self.assertIsNone(smoke.DEFAULT_SMOKE_CONFIG.query_mode)
        self.assertIs(
            smoke.smoke_config_for_page_webassembly(True),
            smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
        )
        self.assertNotEqual(
            smoke.PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
            smoke.PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
        )

    def test_host_rejects_query_tampering_before_the_module_loader(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            'const PAGE_WEBASSEMBLY_TABLE_MODE = "page-webassembly-table";',
            "const PAGE_WEBASSEMBLY_TABLE_SWITCH =",
            '"--wasm-browser-m8-page-webassembly-table-smoke";',
            "PAGE_WEBASSEMBLY_TABLE_MARKER",
            "PAGE_WEBASSEMBLY_TABLE_SMOKE_MODE",
            "pageWebAssemblyAdd42Observed: false",
            "pageWebAssemblyTablesObserved: true",
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved: true",
            "pageWebAssemblyTableGrowthObserved: false",
            "pageWebAssemblyMemoriesObserved: false",
            "pageWebAssemblyExceptionsObserved: false",
            "pageWebAssemblyMemoryGrowthObserved: false",
            "pageWebAssemblyThreadsObserved: false",
            "query.getAll(\"mode\")",
            "DevTools protocol query has an invalid mode",
            "DevTools protocol query has an unsupported field",
            "fetchExpectedSmokeMode",
            "DevTools protocol query mode does not match its binding",
            "PAGE_WEBASSEMBLY_TABLE_SMOKE_MODE ?",
            "[PAGE_WEBASSEMBLY_TABLE_SWITCH]",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        for forbidden in (
            "new WebAssembly",
            "WebAssembly.validate",
            "WebAssembly.Module",
            "WebAssembly.Instance",
            "globalThis.WebAssembly",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)
        self.assertLess(
            host.index("const expectedSmokeMode = await fetchExpectedSmokeMode"),
            host.index("const result = validateResult(await host.run("),
        )

    def test_native_route_has_one_literal_table_import_indirect_call_witness(
        self,
    ) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc"
        )
        self.assertIn(
            '"wasm-browser-m8-page-webassembly-table-smoke"', main_parts
        )
        self.assertIn(
            "browser_lifecycle_->StartPageWebAssemblyTableDevToolsProtocolSmoke();",
            main_parts,
        )
        self.assertIn(
            "StartPageWebAssemblyTableDevToolsProtocolSmoke", lifecycle
        )
        for expected in (
            "WasmBrowserDevToolsProtocolSmokeMode::kTableImportIndirectCall",
            "kPageWebAssemblyTableRuntimeEvaluateCommand",
            "new WebAssembly.Table",
            "element:'anyfunc'",
            "new WebAssembly.Module",
            "new WebAssembly.Instance",
            "i.exports.call(41)",
            "wasm-table-import-indirect-call",
            "chromium-wasm-m8-page-webassembly-table-import-indirect-call",
            "kPageWebAssemblyTableSuccessMarker",
            "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:",
            "TABLE_CONSTRUCTED_IMPORTED_ELEMENT_INITIALIZED_INDIRECT_CALL_42_OK",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, protocol)

        table_command_start = protocol.index(
            "kPageWebAssemblyTableRuntimeEvaluateCommand"
        )
        table_command_end = protocol.index(
            "constexpr char kPageWebAssemblyTableGrowthRuntimeEvaluateCommand",
            table_command_start,
        )
        table_command = protocol[table_command_start:table_command_end]
        for expected in (
            "0,97,115,109,1,0,0,0,1,6,1,96,1,127,1,127,",
            "2,16,1,3,101,110,118,5,116,97,98,108,101,1,112,1,1,1,",
            "3,3,2,0,0,7,8,1,4,99,97,108,108,0,1,9,7,1,0,65,0,11,1,0,",
            "10,19,2,7,0,32,0,65,1,106,11,9,0,32,0,65,0,17,0,0,11",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, table_command)
        for forbidden in (
            "WebAssembly.Memory",
            ".grow(",
            "WebAssembly.Exception",
            "SharedArrayBuffer",
            "Atomics",
            "externref",
            "ref.func",
            ".get(",
            ".set(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, table_command)


if __name__ == "__main__":
    unittest.main()

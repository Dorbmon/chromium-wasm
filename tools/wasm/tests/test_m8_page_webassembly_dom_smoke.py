#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the fixed M8 page-WebAssembly browser-host smoke."""

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


def successful_page_result() -> dict[str, object]:
    readiness = {
        "shellReady": True,
        "surfaceReady": True,
        "firstVisuallyNonEmptyPaint": True,
    }
    return {
        "protocol": 1,
        "case": smoke.PAGE_WEBASSEMBLY_CASE,
        "scope": smoke.PAGE_WEBASSEMBLY_SCOPE,
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
        "pageWebAssemblyAdd42Observed": True,
        "pageWebAssemblyTablesObserved": False,
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
            smoke.PAGE_WEBASSEMBLY_ADD42_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ],
        "failedChecks": [],
        "error": None,
    }


class M8PageWebAssemblyDomSmokeTest(unittest.TestCase):
    def test_page_mode_is_a_single_fixed_configuration(self) -> None:
        config = smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG
        self.assertEqual(config.mode_id, smoke.PAGE_WEBASSEMBLY_MODE)
        self.assertEqual(config.query_mode, "page-webassembly")
        self.assertEqual(config.sentinel, smoke.PAGE_WEBASSEMBLY_SENTINEL)
        self.assertEqual(config.case, "browser_page_webassembly_m8")
        self.assertEqual(
            config.runtime_arguments,
            ("--wasm-browser-m8-page-webassembly-smoke",),
        )
        self.assertEqual(
            config.page_webassembly_expectations,
            (
                ("pageWebAssemblyUnavailableObserved", False),
                ("pageWebAssemblyAdd42Observed", True),
                ("pageWebAssemblyTablesObserved", False),
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
                smoke.PAGE_WEBASSEMBLY_ADD42_MARKER,
                smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
                smoke.DETACHED_MARKER,
                smoke.LIFECYCLE_PASS_MARKER,
            ),
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly(True),
            smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
        )
        self.assertIs(
            smoke.smoke_config_for_page_webassembly(False),
            smoke.DEFAULT_SMOKE_CONFIG,
        )

    def test_page_result_requires_only_the_fixed_add42_witness(self) -> None:
        smoke.validate_result(
            successful_page_result(),
            expected_versions=VERSIONS,
            smoke_config=smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
        )
        for field, value in (
            ("pageWebAssemblyUnavailableObserved", True),
            ("pageWebAssemblyAdd42Observed", False),
            ("pageWebAssemblyTablesObserved", True),
            ("pageWebAssemblyMemoriesObserved", True),
            ("pageWebAssemblyExceptionsObserved", True),
            ("pageWebAssemblyMemoryGrowthObserved", True),
            ("pageWebAssemblyThreadsObserved", True),
            ("m8GateComplete", True),
        ):
            with self.subTest(field=field):
                result = copy.deepcopy(successful_page_result())
                result[field] = value
                with self.assertRaisesRegex(M0Error, rf"{field} mismatch"):
                    smoke.validate_result(
                        result,
                        expected_versions=VERSIONS,
                        smoke_config=smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
                    )

    def test_page_result_rejects_unavailable_or_repeated_native_markers(self) -> None:
        result = successful_page_result()
        result["stderr"] = [
            smoke.NETWORK_ENABLE_MARKER,
            smoke.RUNTIME_ENABLE_MARKER,
            smoke.RUNTIME_EVALUATE_MARKER,
            smoke.PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
            smoke.RUNTIME_CONSOLE_API_CALLED_MARKER,
            smoke.DETACHED_MARKER,
            smoke.LIFECYCLE_PASS_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 0"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
            )

        result = successful_page_result()
        result["stderr"] = successful_page_result()["stderr"] + [
            smoke.PAGE_WEBASSEMBLY_ADD42_MARKER,
        ]
        with self.assertRaisesRegex(M0Error, "marker count is 2"):
            smoke.validate_result(
                result,
                expected_versions=VERSIONS,
                smoke_config=smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
            )

    def test_url_and_server_payload_bind_the_closed_page_mode(self) -> None:
        server = SimpleNamespace(server_address=("127.0.0.1", 31337))
        default_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
        )
        page_url = smoke.smoke_url(
            server,
            "token",
            VERSIONS,
            module_name="chrome_wasm",
            timeout_seconds=30.0,
            smoke_config=smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG,
        )
        self.assertNotIn("mode=", default_url)
        self.assertEqual(
            parse_qs(urlsplit(default_url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))],
            },
        )
        self.assertEqual(
            parse_qs(urlsplit(page_url).query, keep_blank_values=True),
            {
                "token": ["token"],
                "module": ["chrome_wasm"],
                "timeoutMs": ["30000"],
                "versions": [
                    json.dumps(VERSIONS, sort_keys=True, separators=(",", ":"))
                ],
                "mode": ["page-webassembly"],
            },
        )

        payload = json.dumps(successful_page_result()).encode("utf-8")
        self.assertEqual(
            smoke.parse_result_payload(
                payload, smoke_config=smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG
            ),
            successful_page_result(),
        )
        self.assertIsNone(smoke.parse_result_payload(payload))

    def test_server_binds_the_page_mode_to_the_result_token(self) -> None:
        server = smoke.DevToolsProtocolSmokeServer(
            ("127.0.0.1", 0), smoke.DevToolsProtocolSmokeRequestHandler
        )
        server.result_token = "fixed-mode-token"
        server.smoke_config = smoke.PAGE_WEBASSEMBLY_SMOKE_CONFIG
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            host, port = server.server_address[:2]
            binding_url = (
                f"http://{host}:{port}{smoke.HOST_ROOT}/config/fixed-mode-token"
            )
            with urlopen(binding_url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read()),
                    {"protocol": 1, "mode": "page-webassembly"},
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

    def test_default_mode_keeps_the_unavailable_boundary_and_fixed_argument(self) -> None:
        self.assertEqual(
            smoke.DEFAULT_SMOKE_CONFIG.runtime_arguments,
            ("--wasm-browser-devtools-protocol-smoke",),
        )
        self.assertEqual(
            smoke.DEFAULT_SMOKE_CONFIG.page_webassembly_expectations,
            (("pageWebAssemblyUnavailableObserved", True),),
        )
        self.assertIsNone(smoke.DEFAULT_SMOKE_CONFIG.query_mode)

    def test_host_rejects_query_tampering_before_the_module_loader(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        )
        for expected in (
            'const PAGE_WEBASSEMBLY_MODE = "page-webassembly";',
            'const PAGE_WEBASSEMBLY_SWITCH = "--wasm-browser-m8-page-webassembly-smoke";',
            "PAGE_WEBASSEMBLY_ADD42_MARKER",
            "pageWebAssemblyAdd42Observed: true",
            "pageWebAssemblyTablesObserved: false",
            "pageWebAssemblyMemoriesObserved: false",
            "pageWebAssemblyExceptionsObserved: false",
            "pageWebAssemblyMemoryGrowthObserved: false",
            "pageWebAssemblyThreadsObserved: false",
            "query.getAll(\"mode\")",
            "DevTools protocol query has an invalid mode",
            "DevTools protocol query has an unsupported field",
            "fetchExpectedSmokeMode",
            "DevTools protocol query mode does not match its binding",
            "arguments: this.#smokeMode === DEFAULT_SMOKE_MODE ?",
            "[SWITCH] : [PAGE_WEBASSEMBLY_SWITCH]",
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

    def test_native_route_has_one_literal_module_and_lifecycle_entrypoint(self) -> None:
        main_parts = source("chrome/browser/wasm/wasm_browser_main_parts.cc")
        lifecycle = source("chrome/browser/wasm/wasm_browser_lifecycle.cc")
        protocol = source(
            "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.cc"
        )
        self.assertIn(
            '"wasm-browser-m8-page-webassembly-smoke"', main_parts
        )
        self.assertIn(
            "browser_lifecycle_->StartPageWebAssemblyDevToolsProtocolSmoke();",
            main_parts,
        )
        self.assertIn(
            "StartDevToolsProtocolSmokeInternal(/*exercises_page_webassembly=*/true)",
            lifecycle,
        )
        for expected in (
            "WasmBrowserDevToolsProtocolSmokeMode::kValidateModuleInstanceAdd42",
            "kPageWebAssemblyRuntimeEvaluateCommand",
            'R"json("(()=>{const b=new Uint8Array([)json"',
            "R\"json(0,97,115,109,1,0,0,0,1,7,1,96,2,127,127,1,127,3,2,1,0,7,7,1,3,97,)json\"",
            "R\"json(100,100,0,0,10,9,1,7,0,32,0,32,1,106,11]);)json\"",
            "WebAssembly.validate(b)",
            "new WebAssembly.Module(b)",
            "new WebAssembly.Instance(m)",
            "i.exports.add(20,22)",
            "kPageWebAssemblySuccessMarker",
            smoke.PAGE_WEBASSEMBLY_ADD42_MARKER,
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, protocol)


if __name__ == "__main__":
    unittest.main()

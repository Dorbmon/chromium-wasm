#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the two-fresh-module LocalStorage DOM runner."""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_default_partition_local_storage_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "a" * 40,
    "v8": "b" * 40,
    "emscripten": "c" * 40,
}
ARTIFACT_IDENTITY = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "build_config": {"bytes": 71, "sha256": "d" * 64},
    "build_config_provenance": smoke.BUILD_CONFIG_PROVENANCE,
    "loader": {"bytes": 72, "sha256": "e" * 64},
    "module_name": smoke.PRODUCT_MODULE_NAME,
    "wasm": {"bytes": 73, "sha256": "f" * 64},
}
CAPTURE_HARNESS_IDENTITY = {
    "host_html": {"bytes": 74, "sha256": "0" * 64},
    "host_js": {"bytes": 75, "sha256": "1" * 64},
    "runner_source": {"bytes": 76, "sha256": "2" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}
ORIGIN = "http://127.0.0.1:43129"
RESULT_CAPABILITY = "r" * 32
SESSION_CAPABILITY = "s" * 32


def passing_run(
    mode: str, ordinal: int, escrow: smoke.TokenEscrow
) -> dict[str, object]:
    markers = smoke.expected_markers(mode, escrow)
    return {
        "abortObserved": False,
        "expectedCleanExitStatusObserved": False,
        "factoryRejected": False,
        "factoryResolved": True,
        "factorySettled": True,
        "freshLoaderImport": True,
        "freshModuleObject": True,
        "leaseReleasedMarkerObserved": True,
        "lifecycleComplete": True,
        "markerCount": len(markers),
        "markerSequenceAccepted": True,
        "markerSource": "stderr-only-fixed-local-storage-grammar",
        "markers": markers,
        "mode": mode,
        "moduleIdentity": str(ordinal) * 32,
        "onExitCount": 1,
        "ordinal": ordinal,
        "outputLineCount": len(markers),
        "processExitCode": 0,
        "processExitCount": 1,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "stdoutMarkerCount": 0,
    }


def passing_result(escrow: smoke.TokenEscrow) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
        "capture_harness": copy.deepcopy(CAPTURE_HARNESS_IDENTITY),
        "versions": copy.deepcopy(VERSIONS),
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "digest": escrow.digest,
            "rawTokenExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
        },
        "exactlyTwoFreshModulesProven": True,
        "orderedDefaultPartitionLocalStorageCloseReopenProven": True,
        "rendererJavaScriptLocalStorageProven": False,
        "crashOrPowerLossDurabilityProven": False,
        "fullStoragePartitionPersistenceProven": False,
        "hostBoundary": {
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "hostDomStorageAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "runs": [
            passing_run("write", 1, escrow),
            passing_run("verify", 2, escrow),
        ],
        "bridge": {
            "protocol": 1,
            "permanent": True,
            "frozen": True,
            "installedBeforeFirstModuleFactory": True,
            "processExitDispatches": 2,
            "activeAtResult": True,
        },
        "quiescence": [
            {
                "callbacksAfterQuiescence": 5,
                "callbacksAtClear": 5,
                "moduleOrdinal": 1,
                "quiet": True,
                "quietWindowMs": smoke.FINAL_QUIESCENCE_MS,
            },
            {
                "callbacksAfterQuiescence": 10,
                "callbacksAtClear": 10,
                "moduleOrdinal": 2,
                "quiet": True,
                "quietWindowMs": smoke.FINAL_QUIESCENCE_MS,
            },
        ],
        "error": None,
    }


def validate(result: dict[str, object], escrow: smoke.TokenEscrow) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
        expected_origin=ORIGIN,
        escrow=escrow,
        result_token=RESULT_CAPABILITY,
        session=SESSION_CAPABILITY,
    )


class M7DefaultPartitionLocalStorageDomSmokeTest(unittest.TestCase):
    def test_uses_the_dedicated_two_module_artifact(self) -> None:
        self.assertEqual(
            smoke.PRODUCT_MODULE_NAME,
            "chrome_wasm_m7_default_partition_local_storage_test",
        )
        self.assertEqual(
            smoke.DEFAULT_OUT_DIR,
            Path("out/wasm-chrome-m7-default-partition-local-storage"),
        )
        self.assertEqual(smoke.PRODUCT_GN_TARGET, "//chrome:chrome_wasm")
        self.assertEqual(
            smoke.PRODUCT_GN_ENABLE_ARGUMENT,
            "enable_chromium_wasm_m7_default_partition_local_storage_test=true",
        )
        self.assertEqual(
            smoke.DEFAULT_GN_ARGUMENTS,
            'import("//out/wasm-chrome-m6/args.gn") '
            "enable_chromium_wasm_m7_default_partition_local_storage_test=true",
        )

    def test_accepts_exact_two_module_write_then_verify_receipt(self) -> None:
        escrow = smoke.new_token_escrow()
        result = passing_result(escrow)
        validate(result, escrow)
        self.assertEqual(
            result["runs"][0]["markers"],
            smoke.expected_markers("write", escrow),
        )
        self.assertEqual(
            result["runs"][1]["markers"],
            smoke.expected_markers("verify", escrow),
        )

    def test_rejects_wrong_module_marker_order_and_host_boundary(self) -> None:
        escrow = smoke.new_token_escrow()
        wrong_module = passing_result(escrow)
        artifact = wrong_module["artifact"]
        assert isinstance(artifact, dict)
        artifact["module_name"] = "chrome_wasm"
        with self.assertRaises(M0Error):
            validate(wrong_module, escrow)

        wrong_marker_order = passing_result(escrow)
        runs = wrong_marker_order["runs"]
        assert isinstance(runs, list)
        second_run = runs[1]
        assert isinstance(second_run, dict)
        markers = second_run["markers"]
        assert isinstance(markers, list)
        markers[1], markers[2] = markers[2], markers[1]
        with self.assertRaises(M0Error):
            validate(wrong_marker_order, escrow)

        crossed_boundary = passing_result(escrow)
        boundary = crossed_boundary["hostBoundary"]
        assert isinstance(boundary, dict)
        boundary["hostWebLocksAccessAttempted"] = True
        with self.assertRaises(M0Error):
            validate(crossed_boundary, escrow)

    def test_host_validator_accepts_runner_schema(self) -> None:
        escrow = smoke.new_token_escrow()
        payload = json.dumps(passing_result(escrow), separators=(",", ":"))
        script = r'''
import {validateChromeWasmDefaultPartitionLocalStorageResult} from
  "./tools/wasm/host/chrome_wasm_default_partition_local_storage_smoke.js";
const result = JSON.parse(process.argv[1]);
const validated =
    validateChromeWasmDefaultPartitionLocalStorageResult(result);
if (validated.status !== "pass" || validated.error !== null) {
  throw new Error("host validator rejected runner-shaped receipt");
}
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script, payload],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_server_snapshots_routes_and_headers(self) -> None:
        escrow = smoke.new_token_escrow()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / smoke.DEFAULT_OUT_DIR.name
            out_dir.mkdir()
            (out_dir / "args.gn").write_text(
                "enable_chromium_wasm_m7_default_partition_local_storage_test"
                " = true\n",
                encoding="utf-8",
            )
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.js").write_bytes(
                b"export default function() { return Promise.resolve({}); }\n"
            )
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.wasm").write_bytes(
                b"\x00asm\x01\x00\x00\x00"
            )
            host_dir = root / "host"
            host_dir.mkdir()
            (host_dir / smoke.HOST_HTML_NAME).write_bytes(b"<!doctype html>\n")
            (host_dir / smoke.HOST_JS_NAME).write_bytes(b"export {};\n")
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                RESULT_CAPABILITY,
                SESSION_CAPABILITY,
                escrow,
                host_dir=host_dir,
                runner_source_path=Path(__file__),
            )
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.01},
                daemon=True,
            )
            thread.start()
            try:
                smoke.verify_server_delivery(server)
                host, port = server.server_address[:2]
                connection = http.client.HTTPConnection(host, port, timeout=5)
                connection.request(
                    "GET",
                    f"{smoke.HOST_ROOT}/bootstrap/{SESSION_CAPABILITY}",
                    headers={"Cache-Control": "no-store"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.getheader("Cross-Origin-Embedder-Policy"),
                    "require-corp",
                )
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["tokenDigest"], escrow.digest)
                self.assertTrue(
                    secrets.compare_digest(payload["token"], escrow.token)
                )
                connection.close()

                replay = http.client.HTTPConnection(host, port, timeout=5)
                replay.request(
                    "GET",
                    f"{smoke.HOST_ROOT}/bootstrap/{SESSION_CAPABILITY}",
                )
                self.assertEqual(replay.getresponse().status, 409)
                replay.close()
            finally:
                smoke._stop_server(server, thread, True)

    def test_host_source_stays_at_the_narrow_boundary(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_default_partition_local_storage_smoke.js"
        )
        self.assertIn('await this.runModule("write", 1, this.deadline);', host)
        self.assertIn('await this.runModule("verify", 2, this.deadline);', host)
        self.assertIn(
            '"--wasm-profile-local-storage-token=" + this.rawToken',
            host,
        )
        self.assertIn("CHROMIUM_WASM_M7_LOCAL_STORAGE:", host)
        for forbidden in (
            "navigator.storage",
            "navigator.locks",
            "window.localStorage",
            "ccall(",
            "getValue(",
            "HEAPU8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

    def test_host_releases_completed_module_memory_between_fresh_runs(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_default_partition_local_storage_smoke.js"
        )
        for expected in (
            "this.loaderFactories = new WeakSet();",
            "this.moduleObjects = new WeakSet();",
            "wasmBinary: this.wasmBinary,",
            "run.factoryModule = undefined;",
            "run.runtimeModule = undefined;",
            "run.loaderFactory = undefined;",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        self.assertNotIn("wasmBinary: this.wasmBinary.slice()", host)

    def test_host_uses_one_deadline_for_both_fresh_modules(self) -> None:
        host = source(
            "tools/wasm/host/chrome_wasm_default_partition_local_storage_smoke.js"
        )
        for expected in (
            "this.deadline = performance.now() + context.timeoutMs;",
            'await this.runModule("write", 1, this.deadline);',
            'await this.runModule("verify", 2, this.deadline);',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, host)
        self.assertNotIn(
            "const deadline = performance.now() + this.context.timeoutMs;", host
        )


if __name__ == "__main__":
    unittest.main()

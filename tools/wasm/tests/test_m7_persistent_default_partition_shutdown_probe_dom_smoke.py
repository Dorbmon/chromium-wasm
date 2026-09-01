#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the structural default-partition shutdown smoke."""

from __future__ import annotations

import copy
import http.client
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_persistent_default_partition_shutdown_probe_dom_smoke as smoke


VERSIONS = {"chromium": "a" * 40, "v8": "b" * 40, "emscripten": "c" * 40}
RESULT_CAPABILITY = "r" * 32
ORIGIN = "http://127.0.0.1:43131"
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


def passing_result(
    *,
    versions: dict[str, str] | None = None,
    artifact: dict[str, object] | None = None,
    capture_harness: dict[str, object] | None = None,
    origin: str = ORIGIN,
) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "origin": origin,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "artifact": copy.deepcopy(artifact or ARTIFACT_IDENTITY),
        "capture_harness": copy.deepcopy(capture_harness or CAPTURE_HARNESS_IDENTITY),
        "versions": copy.deepcopy(versions or VERSIONS),
        "exactEmptyProbeSwitchPassed": True,
        "freshSourceSelectedShutdownArtifactProven": True,
        "actualPersistentDefaultPartitionCreatedProven": True,
        "creationSealProven": True,
        "partitionMapDroppedProven": True,
        "preferencesFenceProven": True,
        "sealedLeaseRetainedReceiptProven": True,
        "failClosedRetirementProven": True,
        "structuralShutdownWitnessProven": True,
        "nonzeroProcessExitAndAckProven": True,
        "aggregatePartitionCloseProven": False,
        "durableProfileFlushProven": False,
        "profilePersistenceProven": False,
        "profileStorageLeaseReleasedProven": False,
        "freshDocumentReloadProven": False,
        "crashRecoveryProven": False,
        "hostBoundary": {
            "hostDomStorageAccessAttempted": False,
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "run": {
            "arguments": [smoke.EXACT_EMPTY_PROBE_SWITCH],
            "abortObserved": False,
            "factoryOutcome": "expected-nonzero-exit-status",
            "factorySettled": True,
            "freshModuleObject": True,
            "leaseReleasedMarkerObserved": False,
            "markerCount": len(smoke.EXPECTED_MARKERS),
            "markerSequenceAccepted": True,
            "markerSource": "stderr-only-fixed-structural-shutdown-grammar",
            "markers": list(smoke.EXPECTED_MARKERS),
            "noFailMarkerObserved": True,
            "nonzeroProcessExitAndAckReceived": True,
            "onExitCount": 1,
            "processExitBeforeOnExit": True,
            "processExitCode": 23,
            "processExitCount": 1,
            "runtimeExitCode": 23,
            "runtimeInitialized": True,
            "stdoutMarkerCount": 0,
            "unexpectedMarkerObserved": False,
        },
        "bridge": {
            "activeAtResult": False,
            "duplicateProcessExitRejected": 0,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "noActiveProcessExitRejected": 0,
            "permanent": True,
            "processExitDispatches": 1,
            "protocol": 1,
        },
        "quiescence": {
            "callbacksAfterQuietWindow": 9,
            "callbacksAtLifecycleComplete": 9,
            "quiet": True,
            "quietWindowMs": smoke.FINAL_QUIESCENCE_MS,
        },
        "error": None,
    }


def validate(
    result: dict[str, object],
    *,
    versions: dict[str, str] | None = None,
    artifact: dict[str, object] | None = None,
    capture_harness: dict[str, object] | None = None,
    origin: str = ORIGIN,
) -> None:
    smoke.validate_result(
        result,
        expected_versions=versions or VERSIONS,
        expected_artifact_identity=artifact or ARTIFACT_IDENTITY,
        expected_capture_harness_identity=capture_harness or CAPTURE_HARNESS_IDENTITY,
        expected_origin=origin,
        result_token=RESULT_CAPABILITY,
    )


def request(
    server: smoke.PersistentDefaultPartitionShutdownProbeServer,
    method: str,
    path: str,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        headers: dict[str, str] = {}
        if body is not None:
            headers = {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            }
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


class M7PersistentDefaultPartitionShutdownProbeDomSmokeTest(unittest.TestCase):
    def test_uses_only_the_dedicated_shutdown_artifact_and_empty_switch(self) -> None:
        self.assertEqual(
            smoke.PRODUCT_MODULE_NAME,
            "chrome_wasm_m7_persistent_default_partition_shutdown_probe",
        )
        self.assertEqual(
            smoke.DEFAULT_OUT_DIR,
            Path("out/wasm-chrome-m7-persistent-default-partition-shutdown-probe"),
        )
        self.assertEqual(smoke.PRODUCT_GN_TARGET, "//chrome:chrome_wasm")
        self.assertEqual(
            smoke.PRODUCT_GN_ENABLE_ARGUMENT,
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe=true",
        )
        self.assertEqual(
            smoke.DEFAULT_GN_ARGUMENTS,
            'import("//out/wasm-chrome-m6/args.gn") '
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe=true",
        )
        self.assertEqual(
            smoke.EXACT_EMPTY_PROBE_SWITCH,
            "--wasm-persistent-default-partition-shutdown-probe=",
        )
        self.assertEqual(
            smoke.EXPECTED_MARKERS,
            (
                smoke.M7_SHUTDOWN_MARKER_PREFIX + "DEFAULT_PARTITION_CREATED",
                smoke.M7_SHUTDOWN_MARKER_PREFIX + "PARTITION_CREATION_SEALED",
                smoke.M7_SHUTDOWN_MARKER_PREFIX
                + "LATE_PARTITION_CREATION_REJECTED",
                smoke.M7_SHUTDOWN_MARKER_PREFIX + "PARTITION_MAP_DROPPED",
                smoke.M7_SHUTDOWN_MARKER_PREFIX + "PREFERENCES_FENCE_OK",
                smoke.SEALED_LEASE_RETAINED_MARKER,
                smoke.M7_SHUTDOWN_MARKER_PREFIX + "FAIL_CLOSED_RETIREMENT",
            ),
        )

    def test_accepts_only_the_fixed_structural_shutdown_receipt(self) -> None:
        validate(passing_result())

    def test_rejects_lease_release_wrong_order_zero_exit_and_broader_claims(self) -> None:
        wrong_switch = passing_result()
        run = wrong_switch["run"]
        assert isinstance(run, dict)
        run["arguments"] = ["--wasm-persistent-default-partition-shutdown-probe=x"]
        with self.assertRaises(M0Error):
            validate(wrong_switch)

        wrong_order = passing_result()
        run = wrong_order["run"]
        assert isinstance(run, dict)
        markers = run["markers"]
        assert isinstance(markers, list)
        markers[1], markers[2] = markers[2], markers[1]
        with self.assertRaises(M0Error):
            validate(wrong_order)

        lease_released = passing_result()
        run = lease_released["run"]
        assert isinstance(run, dict)
        run["leaseReleasedMarkerObserved"] = True
        with self.assertRaises(M0Error):
            validate(lease_released)

        zero_exit = passing_result()
        run = zero_exit["run"]
        assert isinstance(run, dict)
        run["processExitCode"] = 0
        run["runtimeExitCode"] = 0
        with self.assertRaises(M0Error):
            validate(zero_exit)

        for field in (
            "aggregatePartitionCloseProven",
            "durableProfileFlushProven",
            "profilePersistenceProven",
            "profileStorageLeaseReleasedProven",
            "freshDocumentReloadProven",
            "crashRecoveryProven",
        ):
            with self.subTest(field=field):
                broader_claim = passing_result()
                broader_claim[field] = True
                with self.assertRaises(M0Error):
                    validate(broader_claim)

    def test_requires_exact_fresh_output_source_selection(self) -> None:
        selected = (
            "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe"
            " = true\n"
        ).encode("utf-8")
        smoke.validate_m7_output_configuration(selected, smoke.DEFAULT_OUT_DIR)

        with self.assertRaises(M0Error):
            smoke.validate_m7_output_configuration(
                selected,
                Path("out/wasm-chrome-m7-persistent-default-partition-policy-probe"),
            )
        with self.assertRaises(M0Error):
            smoke.validate_m7_output_configuration(
                selected
                + b"enable_chromium_wasm_m7_persistent_default_partition_policy_probe = true\n",
                smoke.DEFAULT_OUT_DIR,
            )
        with self.assertRaises(M0Error):
            smoke.validate_m7_output_configuration(
                selected
                + (
                    b"enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe"
                    b" = true\n"
                ),
                smoke.DEFAULT_OUT_DIR,
            )
        with self.assertRaises(M0Error):
            smoke.validate_m7_output_configuration(
                b"enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe = false\n",
                smoke.DEFAULT_OUT_DIR,
            )

    def test_server_snapshots_only_the_fixed_artifact_and_requires_ack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            out_dir = root / smoke.DEFAULT_OUT_DIR.name
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            (out_dir / "args.gn").write_text(
                "enable_chromium_wasm_m7_persistent_default_partition_shutdown_probe"
                " = true\n",
                encoding="utf-8",
            )
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.js").write_bytes(
                b"export default function() {}\n"
            )
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.wasm").write_bytes(
                b"\x00asm\x01\x00\x00\x00"
            )
            (host_dir / smoke.HOST_HTML_NAME).write_bytes(b"<!doctype html>\n")
            (host_dir / smoke.HOST_JS_NAME).write_bytes(b"export {};\n")
            runner_source = root / "runner.py"
            runner_source.write_bytes(b"# runner\n")
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                RESULT_CAPABILITY,
                host_dir=host_dir,
                runner_source_path=runner_source,
            )
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.01},
                daemon=True,
            )
            thread.start()
            try:
                smoke.verify_server_delivery(server)
                origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
                result = passing_result(
                    artifact=smoke.artifact_identity(server),
                    capture_harness=smoke.capture_harness_identity(server),
                    origin=origin,
                )
                result_body = json.dumps(result, separators=(",", ":")).encode("utf-8")
                status, _headers, _body = request(
                    server,
                    "POST",
                    f"{smoke.HOST_ROOT}/result/{RESULT_CAPABILITY}",
                    result_body,
                )
                self.assertEqual(status, 204)
                with self.assertRaises(queue.Empty):
                    server.result_queue.get_nowait()

                acknowledgement = json.dumps(
                    {"protocol": 1, "case": smoke.CASE, "scope": smoke.SCOPE},
                    separators=(",", ":"),
                ).encode("utf-8")
                status, _headers, _body = request(
                    server,
                    "POST",
                    f"{smoke.HOST_ROOT}/ack/{RESULT_CAPABILITY}",
                    acknowledgement,
                )
                self.assertEqual(status, 204)
                delivered = server.result_queue.get(timeout=1)
                self.assertEqual(delivered, result)
                smoke.validate_result(
                    delivered,
                    expected_versions=VERSIONS,
                    expected_artifact_identity=smoke.artifact_identity(server),
                    expected_capture_harness_identity=smoke.capture_harness_identity(server),
                    expected_origin=origin,
                    result_token=RESULT_CAPABILITY,
                )
            finally:
                smoke._stop_server(server, thread, True)


if __name__ == "__main__":
    unittest.main()

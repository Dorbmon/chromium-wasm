#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import hashlib
import http.client
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from tools.wasm.m0_common import M0Error, REPO_ROOT
from tools.wasm import run_m9_measurement_baseline as baseline


def wasm_heap_buffer_capacity_snapshot(capacity_bytes: int) -> dict[str, object]:
    return {
        "buffer_kind": "SharedArrayBuffer",
        "heap_u8_exported": True,
        "shared": True,
        "wasm_heap_buffer_capacity_bytes": capacity_bytes,
    }


def native_memory_snapshot(
    capacity_bytes: int,
    *,
    maximum_bytes: int = 2_147_483_648,
    mapped_bytes: int = 0,
) -> dict[str, int]:
    return {
        "page_allocator_total_mapped_bytes": mapped_bytes,
        "wasm_linear_memory_capacity_bytes": capacity_bytes,
        "wasm_linear_memory_headroom_bytes": maximum_bytes - capacity_bytes,
        "wasm_linear_memory_maximum_bytes": maximum_bytes,
    }


def worker_snapshot(
    *, workers_constructed: int = 8, loaded_messages: int = 8
) -> dict[str, int]:
    return {
        "construction_attempts": workers_constructed,
        "error_events": 0,
        "loaded_control_messages": loaded_messages,
        "message_error_events": 0,
        "workers_constructed": workers_constructed,
    }


def passing_snapshot() -> dict[str, object]:
    timing = {
        "host_module_evaluated": 1.0,
        "host_run_started": 2.0,
        "loader_fetch_started": 3.0,
        "loader_response_ready": 4.0,
        "loader_blob_ready": 5.0,
        "module_import_started": 6.0,
        "module_factory_export_ready": 7.0,
        "factory_call_started": 8.0,
        "runtime_initialized": 9.0,
        "first_frame_callback_after_canvas_copy": 10.0,
        "surface_ready_callback": 11.0,
        "ready": 12.0,
        "shutdown_requested": 13.0,
        "runtime_exit": 14.0,
    }
    durations = {
        name: round(
            timing[end] - (0.0 if start == "navigation_start" else timing[start]),
            3,
        )
        for name, (start, end) in baseline._DURATION_PAIRS.items()
    }
    return {
        "case": baseline.CASE,
        "cold_start_definition": baseline.COLD_START_DEFINITION,
        "durations_ms": durations,
        "failure": None,
        "first_frame": {
            "chromium_timestamp_ms": 2.5,
            "height": 600,
            "host_callback_after_canvas_copy_ms": 10.0,
            "id": 1,
            "width": 800,
        },
        "host": {
            "canvas_focused": True,
            "cross_origin_isolated": True,
            "shared_array_buffer_available": True,
        },
        "lifecycle": {
            "active_ozone_focus_observed": True,
            "factory_rejected": False,
            "factory_settled": True,
            "fatal_error_count": 0,
            "process_exit_code": 0,
            "readiness": {
                "firstVisuallyNonEmptyPaint": False,
                "shellReady": True,
                "surfaceReady": True,
            },
            "runtime_exit_code": 0,
            "runtime_initialized": True,
            "shutdown_results": [1, 0],
            "status_sequence": [
                "starting",
                "loading",
                "ready",
                "shutting_down",
                "complete",
            ],
            "unhandled_rejection_count": 0,
            "window_error_count": 0,
        },
        "m9_gate_complete": False,
        "measurement_limits": list(baseline.SAMPLE_MEASUREMENT_LIMITS),
        "native_memory_snapshot": {
            "at_first_frame": native_memory_snapshot(67_108_864),
            "at_pre_shutdown": native_memory_snapshot(67_108_864),
            "at_runtime_initialized": native_memory_snapshot(67_108_864),
            "definition": baseline.NATIVE_MEMORY_SNAPSHOT_DEFINITION,
        },
        "wasm_heap_buffer_capacity": {
            "at_first_frame": wasm_heap_buffer_capacity_snapshot(67_108_864),
            "at_runtime_initialized": wasm_heap_buffer_capacity_snapshot(
                67_108_864
            ),
            "at_runtime_exit": wasm_heap_buffer_capacity_snapshot(67_108_864),
            "definition": baseline.WASM_HEAP_BUFFER_CAPACITY_DEFINITION,
            "grew_before_first_frame_callback": False,
            "grew_by_runtime_exit": False,
        },
        "performance_gate": False,
        "release_status": baseline.RELEASE_STATUS,
        "schema_version": baseline.SCHEMA_VERSION,
        "scope": baseline.SCOPE,
        "status": "complete",
        "timing_ms": timing,
        "worker_observation": {
            "at_first_frame": worker_snapshot(),
            "at_runtime_initialized": worker_snapshot(),
            "at_runtime_exit": worker_snapshot(),
            "definition": baseline.WORKER_OBSERVATION_DEFINITION,
        },
    }


def passing_capture_harness() -> dict[str, object]:
    return {
        "artifact_delivery": baseline.ARTIFACT_DELIVERY,
        "host_html": {"bytes": 11, "sha256": "1" * 64},
        "host_js": {"bytes": 12, "sha256": "2" * 64},
        "host_protocol": baseline.HOST_PROTOCOL,
        "kind": baseline.HARNESS_KIND,
        "loader_route": baseline.HARNESS_LOADER_ROUTE,
        "runner_source": {"bytes": 13, "sha256": "3" * 64},
        "source_snapshot_provenance": baseline.SOURCE_SNAPSHOT_PROVENANCE,
        "version_provenance": baseline.VERSION_PROVENANCE,
    }


def passing_result() -> dict[str, object]:
    return baseline.make_baseline_result(
        artifact={
            "args_gn": {"bytes": 5, "sha256": "a" * 64},
            "artifact_source_provenance": "unverified",
            "loader": {"bytes": 10, "sha256": "b" * 64},
            "module_name": "chrome_wasm",
            "wasm": {"bytes": 20, "sha256": "c" * 64},
        },
        capture_harness=passing_capture_harness(),
        host_browser_version="Chromium 1.2.3.4",
        snapshot=passing_snapshot(),
        versions={
            "chromium": "d" * 40,
            "emscripten": "e" * 40,
            "v8": "0" * 40,
        },
    )


class M9MeasurementServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.out_dir = self.root / "out"
        self.out_dir.mkdir()
        self.loader_bytes = b"export default function chromeWasm() {}\n"
        self.wasm_bytes = b"\x00asm\x01\x00\x00\x00"
        self.args_gn_bytes = b'target_os = "emscripten"\n'
        (self.out_dir / "chrome_wasm.js").write_bytes(self.loader_bytes)
        (self.out_dir / "chrome_wasm.wasm").write_bytes(self.wasm_bytes)
        (self.out_dir / "args.gn").write_bytes(self.args_gn_bytes)
        self.server = baseline.create_measurement_server(
            "127.0.0.1", 0, self.out_dir, module_name="chrome_wasm"
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def _request(self, path: str) -> tuple[int, dict[str, str], bytes]:
        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def _assert_headers(self, headers: dict[str, str]) -> None:
        for name, expected in baseline.REQUIRED_HEADERS.items():
            self.assertEqual(expected, headers.get(name))

    def test_serves_immutable_host_and_artifact_snapshots(self) -> None:
        expected = {
            "/__m9__/": ("text/html; charset=utf-8", b"M9 baseline"),
            "/__m9__/chrome_wasm_m9_measurement_host.js": (
                "text/javascript; charset=utf-8",
                b"not a benchmark",
            ),
            "/__m9__/artifacts/chrome_wasm.js": (
                "text/javascript; charset=utf-8",
                self.loader_bytes,
            ),
            "/__m9__/artifacts/chrome_wasm.wasm": (
                "application/wasm",
                self.wasm_bytes,
            ),
        }
        # The server and result identity must not observe a file replacement
        # after their single immutable input snapshot.
        (self.out_dir / "chrome_wasm.js").write_bytes(b"tampered")
        (self.out_dir / "chrome_wasm.wasm").write_bytes(b"tampered")
        (self.out_dir / "args.gn").write_bytes(b"tampered")
        identity = baseline.artifact_identity(self.server, module_name="chrome_wasm")
        self.assertEqual(
            hashlib.sha256(self.args_gn_bytes).hexdigest(),
            identity["args_gn"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(self.loader_bytes).hexdigest(),
            identity["loader"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(self.wasm_bytes).hexdigest(),
            identity["wasm"]["sha256"],
        )
        for path, (content_type, contents) in expected.items():
            with self.subTest(path=path):
                status, headers, body = self._request(path)
                self.assertEqual(http.client.OK, status)
                self._assert_headers(headers)
                self.assertEqual(content_type, headers.get("Content-Type"))
                self.assertIn(contents, body)

    def test_rejects_traversal_and_nonexact_artifact_names(self) -> None:
        for path in (
            "/__m9__/artifacts/chrome_wasm.data",
            "/__m9__/artifacts/chrome_wasm.js/extra",
            "/__m9__/artifacts/args.gn",
            "/__m9__/artifacts/../chrome_wasm.js",
            "/__m9__/artifacts/%2e%2e/chrome_wasm.js",
            "/__m9__/unknown",
        ):
            with self.subTest(path=path):
                status, headers, body = self._request(path)
                self.assertEqual(http.client.NOT_FOUND, status)
                self._assert_headers(headers)
                self.assertEqual("text/plain; charset=utf-8", headers.get("Content-Type"))
                self.assertEqual(b"not found\n", body)

    def test_url_and_artifact_identity_are_exact_and_path_free(self) -> None:
        url = baseline.measurement_url(
            self.server, module_name="chrome_wasm", timeout_seconds=12.5
        )
        parsed = urlsplit(url)
        self.assertEqual("/__m9__/", parsed.path)
        self.assertEqual(
            {"module": ["chrome_wasm"], "timeout_ms": ["12500"]},
            parse_qs(parsed.query, strict_parsing=True),
        )
        identity = baseline.artifact_identity(self.server, module_name="chrome_wasm")
        self.assertEqual("chrome_wasm", identity["module_name"])
        self.assertEqual(len(self.loader_bytes), identity["loader"]["bytes"])
        self.assertEqual(len(self.wasm_bytes), identity["wasm"]["bytes"])
        self.assertEqual(len(self.args_gn_bytes), identity["args_gn"]["bytes"])
        self.assertEqual(
            hashlib.sha256(self.args_gn_bytes).hexdigest(),
            identity["args_gn"]["sha256"],
        )
        self.assertEqual(
            baseline.ARTIFACT_SOURCE_PROVENANCE,
            identity["artifact_source_provenance"],
        )
        self.assertNotIn(str(self.out_dir), repr(identity))

    def test_rejects_alternate_product_module_at_server_url_and_identity_boundaries(
        self,
    ) -> None:
        alternate_module = "alternate_wasm"
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            baseline.create_measurement_server(
                "127.0.0.1",
                0,
                self.root / "missing-output",
                module_name=alternate_module,
            )
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            baseline.measurement_url(
                self.server, module_name=alternate_module, timeout_seconds=12.5
            )
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            baseline.artifact_identity(self.server, module_name=alternate_module)

    def test_harness_identity_keeps_runner_and_host_source_snapshots(self) -> None:
        source_root = self.root / "measurement-source"
        source_root.mkdir()
        host_dir = source_root / "host"
        host_dir.mkdir()
        original_html = b"<html>original measurement host</html>"
        original_js = b"export const originalHost = true;\n"
        original_runner = b"# original runner snapshot\n"
        (host_dir / "chrome_wasm_m9_measurement.html").write_bytes(original_html)
        (host_dir / "chrome_wasm_m9_measurement_host.js").write_bytes(original_js)
        runner_source = source_root / "runner.py"
        runner_source.write_bytes(original_runner)

        source_server = baseline.create_measurement_server(
            "127.0.0.1",
            0,
            self.out_dir,
            module_name="chrome_wasm",
            host_dir=host_dir,
            runner_source_path=runner_source,
        )
        source_thread = threading.Thread(
            target=source_server.serve_forever, daemon=True
        )
        source_thread.start()
        try:
            # Mutating source files after server startup must not change the
            # exact byte identities or the host bytes that server owns.
            (host_dir / "chrome_wasm_m9_measurement.html").write_bytes(b"tampered")
            (host_dir / "chrome_wasm_m9_measurement_host.js").write_bytes(
                b"tampered"
            )
            runner_source.write_bytes(b"tampered")
            harness = baseline.capture_harness_identity(source_server)
            self.assertEqual(original_html, source_server.host_html)
            self.assertEqual(original_js, source_server.host_js)
            self.assertEqual(original_runner, source_server.runner_source)
            for path, expected in (
                ("/__m9__/", original_html),
                ("/__m9__/chrome_wasm_m9_measurement_host.js", original_js),
            ):
                host, port = source_server.server_address[:2]
                connection = http.client.HTTPConnection(host, port, timeout=10)
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    self.assertEqual(http.client.OK, response.status)
                    self.assertEqual(expected, response.read())
                finally:
                    connection.close()
            self.assertEqual(
                hashlib.sha256(original_html).hexdigest(),
                harness["host_html"]["sha256"],
            )
            self.assertEqual(
                hashlib.sha256(original_js).hexdigest(),
                harness["host_js"]["sha256"],
            )
            self.assertEqual(
                hashlib.sha256(original_runner).hexdigest(),
                harness["runner_source"]["sha256"],
            )
            self.assertEqual(
                baseline.SOURCE_SNAPSHOT_PROVENANCE,
                harness["source_snapshot_provenance"],
            )
            self.assertNotIn("checkout", repr(harness).lower())
        finally:
            source_server.shutdown()
            source_server.server_close()
            source_thread.join(timeout=5)


class M9MeasurementValidationTest(unittest.TestCase):
    def test_accepts_complete_observational_baseline(self) -> None:
        baseline.validate_measurement_snapshot(passing_snapshot())

    def test_rejects_gate_claims_and_missing_nonbenchmark_limit(self) -> None:
        for field, invalid in (
            ("m9_gate_complete", True),
            ("performance_gate", True),
            ("release_status", "releasable"),
        ):
            with self.subTest(field=field):
                sample = passing_snapshot()
                sample[field] = invalid
                with self.assertRaisesRegex(M0Error, f"{field} mismatch"):
                    baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["measurement_limits"] = []
        with self.assertRaisesRegex(M0Error, "bounded caveats"):
            baseline.validate_measurement_snapshot(sample)

    def test_rejects_numeric_lookalikes_for_sample_gate_and_schema_fields(self) -> None:
        for field, value, error in (
            ("m9_gate_complete", 0, "m9_gate_complete is not boolean"),
            ("performance_gate", 0, "performance_gate is not boolean"),
            ("schema_version", True, "schema version is invalid"),
            ("schema_version", 1.0, "schema version is invalid"),
        ):
            with self.subTest(field=field, value=value):
                sample = passing_snapshot()
                sample[field] = value
                with self.assertRaisesRegex(M0Error, error):
                    baseline.validate_measurement_snapshot(sample)

    def test_rejects_nonmonotonic_timing_or_unobserved_frame_copy(self) -> None:
        sample = passing_snapshot()
        sample["timing_ms"]["runtime_initialized"] = 15.0
        with self.assertRaisesRegex(M0Error, "out of order"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["first_frame"] = None
        with self.assertRaisesRegex(M0Error, "first host frame"):
            baseline.validate_measurement_snapshot(sample)

    def test_rejects_missing_or_extra_evidence_fields(self) -> None:
        cases = (
            ("timing_ms", "runtime_exit"),
            ("lifecycle", "fatal_error_count"),
            ("lifecycle", "process_exit_code"),
            ("native_memory_snapshot", "at_pre_shutdown"),
            ("wasm_heap_buffer_capacity", "at_runtime_exit"),
            ("worker_observation", "at_runtime_exit"),
        )
        for container, field in cases:
            with self.subTest(container=container, field=field):
                sample = passing_snapshot()
                del sample[container][field]  # type: ignore[index]
                with self.assertRaisesRegex(M0Error, "schema mismatch"):
                    baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["wasm_heap_buffer_capacity"]["unbounded_peak_bytes"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "schema mismatch"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["native_memory_snapshot"]["unbounded_rss_bytes"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "schema mismatch"):
            baseline.validate_measurement_snapshot(sample)

    def test_rejects_reordered_statuses_and_incomplete_shutdown(self) -> None:
        sample = passing_snapshot()
        sample["lifecycle"]["status_sequence"] = [  # type: ignore[index]
            "starting",
            "loading",
            "shutting_down",
            "ready",
            "complete",
        ]
        with self.assertRaisesRegex(M0Error, "missing or reordered"):
            baseline.validate_measurement_snapshot(sample)

        for field, value, error in (
            ("factory_settled", False, "did not settle"),
            ("runtime_exit_code", 1, "runtime exit is nonzero"),
            ("shutdown_results", [1], "return exactly"),
            ("fatal_error_count", 1, "fatal_error_count is nonzero"),
        ):
            with self.subTest(field=field):
                sample = passing_snapshot()
                sample["lifecycle"][field] = value  # type: ignore[index]
                with self.assertRaisesRegex(M0Error, error):
                    baseline.validate_measurement_snapshot(sample)

    def test_rejects_missing_or_invalid_lifecycle_exit_values(self) -> None:
        for field, value, error in (
            ("runtime_exit_code", True, "runtime exit code is invalid"),
            ("runtime_exit_code", 0.0, "runtime exit code is invalid"),
            ("process_exit_code", None, "process exit code is invalid"),
            ("process_exit_code", False, "process exit code is invalid"),
            ("process_exit_code", 0.0, "process exit code is invalid"),
            ("process_exit_code", 1, "bridge process exit is nonzero"),
            ("shutdown_results", [True, 0], "return exactly"),
            ("shutdown_results", [1, 0.0], "return exactly"),
        ):
            with self.subTest(field=field, value=value):
                sample = passing_snapshot()
                sample["lifecycle"][field] = value  # type: ignore[index]
                with self.assertRaisesRegex(M0Error, error):
                    baseline.validate_measurement_snapshot(sample)

    def test_rejects_duration_that_disagrees_with_its_event_boundaries(self) -> None:
        sample = passing_snapshot()
        sample["durations_ms"]["shutdown_request_to_runtime_exit"] = 0.0  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "disagrees with its timestamps"):
            baseline.validate_measurement_snapshot(sample)

    def test_rejects_nonshared_capacity_and_missing_worker_ready_evidence(self) -> None:
        sample = passing_snapshot()
        sample["wasm_heap_buffer_capacity"]["at_first_frame"][  # type: ignore[index]
            "buffer_kind"
        ] = "ArrayBuffer"
        with self.assertRaisesRegex(M0Error, "not a shared Wasm heap buffer"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["worker_observation"]["at_runtime_initialized"][
            "loaded_control_messages"
        ] = 0  # type: ignore[index]
        sample["worker_observation"]["at_first_frame"]["loaded_control_messages"] = 0
        with self.assertRaisesRegex(M0Error, "loaded-control"):
            baseline.validate_measurement_snapshot(sample)

    def test_rejects_capacity_growth_flags_that_disagree_with_samples(self) -> None:
        sample = passing_snapshot()
        sample["wasm_heap_buffer_capacity"][  # type: ignore[index]
            "at_first_frame"
        ]["wasm_heap_buffer_capacity_bytes"] = 100_000_000
        sample["wasm_heap_buffer_capacity"][  # type: ignore[index]
            "at_runtime_exit"
        ]["wasm_heap_buffer_capacity_bytes"] = 100_000_000
        sample["wasm_heap_buffer_capacity"]["grew_by_runtime_exit"] = True  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "first-frame growth flag disagrees"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["wasm_heap_buffer_capacity"][  # type: ignore[index]
            "at_runtime_exit"
        ]["wasm_heap_buffer_capacity_bytes"] = 100_000_000
        with self.assertRaisesRegex(M0Error, "runtime-exit growth flag disagrees"):
            baseline.validate_measurement_snapshot(sample)

    def test_rejects_malformed_native_memory_snapshots(self) -> None:
        native = "native_memory_snapshot"
        point = "at_first_frame"

        sample = passing_snapshot()
        sample[native][point]["wasm_linear_memory_capacity_bytes"] = 3.5  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "capacity is invalid"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample[native][point]["page_allocator_total_mapped_bytes"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "not Wasm-page aligned"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample[native][point]["wasm_linear_memory_maximum_bytes"] = 65_536  # type: ignore[index]
        sample[native][point]["wasm_linear_memory_headroom_bytes"] = 0  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "maximum is below current capacity"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample[native][point]["wasm_linear_memory_headroom_bytes"] = -1  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "headroom is invalid"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample[native][point]["wasm_linear_memory_headroom_bytes"] += (  # type: ignore[index]
            baseline.WASM_MEMORY_PAGE_BYTES
        )
        with self.assertRaisesRegex(M0Error, "headroom disagrees"):
            baseline.validate_measurement_snapshot(sample)

    def test_rejects_regressing_native_linear_memory_capacity(self) -> None:
        sample = passing_snapshot()
        sample["native_memory_snapshot"]["at_pre_shutdown"][  # type: ignore[index]
            "wasm_linear_memory_capacity_bytes"
        ] = 65_536
        sample["native_memory_snapshot"]["at_pre_shutdown"][  # type: ignore[index]
            "wasm_linear_memory_headroom_bytes"
        ] = 2_147_418_112
        with self.assertRaisesRegex(M0Error, "capacity regressed"):
            baseline.validate_measurement_snapshot(sample)

    def test_accepts_nonmonotonic_page_allocator_mappings_without_leak_inference(
        self,
    ) -> None:
        sample = passing_snapshot()
        snapshot = sample["native_memory_snapshot"]  # type: ignore[index]
        snapshot["at_runtime_initialized"][  # type: ignore[index]
            "page_allocator_total_mapped_bytes"
        ] = 4 * baseline.WASM_MEMORY_PAGE_BYTES
        snapshot["at_first_frame"][  # type: ignore[index]
            "page_allocator_total_mapped_bytes"
        ] = baseline.WASM_MEMORY_PAGE_BYTES
        snapshot["at_pre_shutdown"][  # type: ignore[index]
            "page_allocator_total_mapped_bytes"
        ] = 8 * baseline.WASM_MEMORY_PAGE_BYTES
        baseline.validate_measurement_snapshot(sample)

    def test_accepts_asynchronously_refreshed_native_and_heap_capacity_samples(
        self,
    ) -> None:
        sample = passing_snapshot()
        snapshot = sample["native_memory_snapshot"]  # type: ignore[index]
        for point in ("at_first_frame", "at_pre_shutdown"):
            snapshot[point]["wasm_linear_memory_capacity_bytes"] += (  # type: ignore[index]
                baseline.WASM_MEMORY_PAGE_BYTES
            )
            snapshot[point]["wasm_linear_memory_headroom_bytes"] -= (  # type: ignore[index]
                baseline.WASM_MEMORY_PAGE_BYTES
            )
        # The independently refreshed HEAPU8 view can lag a concurrent
        # memory.grow; the native counter remains internally exact.
        baseline.validate_measurement_snapshot(sample)

    def test_rejects_impossible_or_regressing_worker_evidence(self) -> None:
        sample = passing_snapshot()
        sample["worker_observation"]["at_first_frame"][  # type: ignore[index]
            "workers_constructed"
        ] = 9
        with self.assertRaisesRegex(M0Error, "more constructed workers than attempts"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["worker_observation"]["at_first_frame"][  # type: ignore[index]
            "loaded_control_messages"
        ] = 9
        with self.assertRaisesRegex(M0Error, "more loaded messages than workers"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["worker_observation"]["at_runtime_exit"][  # type: ignore[index]
            "error_events"
        ] = -1
        with self.assertRaisesRegex(M0Error, "error_events is invalid"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["worker_observation"]["at_runtime_initialized"][  # type: ignore[index]
            "message_error_events"
        ] = 1
        with self.assertRaisesRegex(M0Error, "message_error_events regressed"):
            baseline.validate_measurement_snapshot(sample)

        sample = passing_snapshot()
        sample["worker_observation"]["at_runtime_initialized"][  # type: ignore[index]
            "error_events"
        ] = 1
        with self.assertRaisesRegex(M0Error, "error_events regressed"):
            baseline.validate_measurement_snapshot(sample)

    def test_result_wraps_one_sample_without_inventing_a_benchmark(self) -> None:
        artifact = {
            "args_gn": {"bytes": 5, "sha256": "a" * 64},
            "artifact_source_provenance": "unverified",
            "loader": {"bytes": 10, "sha256": "b" * 64},
            "module_name": "chrome_wasm",
            "wasm": {"bytes": 20, "sha256": "c" * 64},
        }
        result = baseline.make_baseline_result(
            artifact=artifact,
            capture_harness=passing_capture_harness(),
            host_browser_version="Chromium 1.2.3.4",
            snapshot=passing_snapshot(),
            versions={
                "chromium": "d" * 40,
                "emscripten": "e" * 40,
                "v8": "0" * 40,
            },
        )
        self.assertEqual(baseline.BASELINE_KIND, result["kind"])
        self.assertFalse(result["m9_gate_complete"])
        self.assertFalse(result["performance_gate"])
        self.assertEqual(baseline.SCHEMA_VERSION, result["schema_version"])
        self.assertEqual(
            baseline.SOURCE_SNAPSHOT_PROVENANCE,
            result["capture_harness"]["source_snapshot_provenance"],
        )
        self.assertIn("runner_source", result["capture_harness"])
        self.assertNotIn("port", result["versions"])
        self.assertEqual(
            "unverified", result["artifact"]["artifact_source_provenance"]
        )
        self.assertNotIn("PASS", repr(result))

    def test_result_schema_rejects_substituted_product_module(self) -> None:
        result = passing_result()
        result["artifact"]["module_name"] = "alternate_wasm"  # type: ignore[index]
        with self.assertRaisesRegex(
            M0Error, "only supports the chrome_wasm product module"
        ):
            baseline.validate_baseline_result(result)

    def test_result_schema_rejects_false_artifact_or_harness_provenance(self) -> None:
        result = baseline.make_baseline_result(
            artifact={
                "args_gn": {"bytes": 5, "sha256": "a" * 64},
                "artifact_source_provenance": "unverified",
                "loader": {"bytes": 10, "sha256": "b" * 64},
                "module_name": "chrome_wasm",
                "wasm": {"bytes": 20, "sha256": "c" * 64},
            },
            capture_harness=passing_capture_harness(),
            host_browser_version="Chromium 1.2.3.4",
            snapshot=passing_snapshot(),
            versions={
                "chromium": "d" * 40,
                "emscripten": "e" * 40,
                "v8": "0" * 40,
            },
        )
        result["artifact"]["artifact_source_provenance"] = "verified"  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "source provenance"):
            baseline.validate_baseline_result(result)

        result = baseline.make_baseline_result(
            artifact={
                "args_gn": {"bytes": 5, "sha256": "a" * 64},
                "artifact_source_provenance": "unverified",
                "loader": {"bytes": 10, "sha256": "b" * 64},
                "module_name": "chrome_wasm",
                "wasm": {"bytes": 20, "sha256": "c" * 64},
            },
            capture_harness=passing_capture_harness(),
            host_browser_version="Chromium 1.2.3.4",
            snapshot=passing_snapshot(),
            versions={
                "chromium": "d" * 40,
                "emscripten": "e" * 40,
                "v8": "0" * 40,
            },
        )
        result["capture_harness"]["runner_source"]["sha256"] = "not-a-snapshot"  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "runner_source SHA-256"):
            baseline.validate_baseline_result(result)

        result["capture_harness"]["runner_source"]["sha256"] = "3" * 64  # type: ignore[index]
        result["versions"] = {"chromium": "d" * 40}  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "versions schema mismatch"):
            baseline.validate_baseline_result(result)

        result["versions"] = {
            "chromium": "d" * 40,
            "emscripten": "",
            "v8": "0" * 40,
        }  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "version emscripten is invalid"):
            baseline.validate_baseline_result(result)

        result["versions"] = {
            "chromium": "d" * 40,
            "emscripten": "e" * 40,
            "unexpected": "1" * 40,
            "v8": "0" * 40,
        }  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "versions schema mismatch"):
            baseline.validate_baseline_result(result)

    def test_result_rejects_numeric_lookalikes_for_gate_schema_and_protocol(self) -> None:
        for field, value, error in (
            ("m9_gate_complete", 0, "result m9_gate_complete is not boolean"),
            ("performance_gate", 0, "result performance_gate is not boolean"),
            ("schema_version", True, "result schema version is invalid"),
            ("schema_version", 1.0, "result schema version is invalid"),
        ):
            with self.subTest(field=field, value=value):
                result = passing_result()
                result[field] = value
                with self.assertRaisesRegex(M0Error, error):
                    baseline.validate_baseline_result(result)

        for value in (True, 1.0, 0, 2):
            with self.subTest(host_protocol=value):
                result = passing_result()
                result["capture_harness"]["host_protocol"] = value  # type: ignore[index]
                with self.assertRaisesRegex(M0Error, r"host.?protocol is invalid"):
                    baseline.validate_baseline_result(result)


class M9MeasurementCleanupTest(unittest.TestCase):
    def test_main_rejects_alternate_module_before_server_or_browser(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(baseline, "check_boundary") as check_boundary,
            mock.patch.object(
                baseline, "create_measurement_server"
            ) as create_measurement_server,
            mock.patch.object(baseline, "run_measurement") as run_measurement,
            mock.patch.object(
                baseline.sys,
                "argv",
                ["measurement-baseline", "--module-name", "alternate_wasm"],
            ),
            mock.patch.object(baseline.sys, "stderr", stderr),
            self.assertRaisesRegex(SystemExit, "^2$"),
        ):
            baseline.main()

        self.assertIn("--module-name must be chrome_wasm", stderr.getvalue())
        check_boundary.assert_not_called()
        create_measurement_server.assert_not_called()
        run_measurement.assert_not_called()

    def test_main_preserves_unstarted_server_thread_start_failure(self) -> None:
        server = mock.Mock()
        server_thread = mock.Mock()
        server_thread.start.side_effect = RuntimeError("server thread start failed")
        server_thread.join.side_effect = RuntimeError(
            "cannot join thread before it is started"
        )

        with (
            mock.patch.object(baseline, "check_boundary"),
            mock.patch.object(baseline, "load_manifest", return_value={}),
            mock.patch.object(
                baseline, "toolchain_manifest_versions", return_value={}
            ),
            mock.patch.object(
                baseline, "create_measurement_server", return_value=server
            ),
            mock.patch.object(baseline, "artifact_identity", return_value={}),
            mock.patch.object(
                baseline.threading, "Thread", return_value=server_thread
            ),
            mock.patch.object(baseline.sys, "argv", ["measurement-baseline"]),
            self.assertRaisesRegex(RuntimeError, "server thread start failed"),
        ):
            baseline.main()

        server.shutdown.assert_not_called()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_not_called()

    def test_run_measurement_preserves_unstarted_stderr_reader_failure(self) -> None:
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-measurement-profile"
        stderr_thread = mock.Mock()
        stderr_thread.start.side_effect = RuntimeError("stderr reader start failed")
        stderr_thread.join.side_effect = RuntimeError(
            "cannot join thread before it is started"
        )

        with (
            mock.patch.object(
                baseline,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                baseline.tempfile, "TemporaryDirectory", return_value=profile
            ),
            mock.patch.object(baseline, "unused_loopback_port", return_value=12345),
            mock.patch.object(
                baseline, "browser_command", return_value=["/fake/browser", "url"]
            ),
            mock.patch.object(baseline.subprocess, "Popen", return_value=browser),
            mock.patch.object(
                baseline.threading, "Thread", return_value=stderr_thread
            ),
            mock.patch.object(
                baseline,
                "abort_browser_group",
                side_effect=RuntimeError("browser cleanup failed"),
            ) as abort_browser_group,
            self.assertRaisesRegex(RuntimeError, "stderr reader start failed"),
        ):
            baseline.run_measurement(
                server=mock.Mock(),
                url="http://127.0.0.1:12345/__m9__/",
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
            )

        abort_browser_group.assert_called_once_with(browser, mock.ANY)
        stderr_thread.join.assert_not_called()
        profile.cleanup.assert_called_once_with()

    def test_run_measurement_rejects_browser_group_cleanup_after_completion(
        self,
    ) -> None:
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-measurement-profile"
        stderr_thread = mock.Mock()
        client = mock.Mock()
        client.evaluate.return_value = True

        with (
            mock.patch.object(
                baseline,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                baseline.tempfile, "TemporaryDirectory", return_value=profile
            ),
            mock.patch.object(baseline, "unused_loopback_port", return_value=12345),
            mock.patch.object(
                baseline, "browser_command", return_value=["/fake/browser", "url"]
            ),
            mock.patch.object(baseline.subprocess, "Popen", return_value=browser),
            mock.patch.object(
                baseline.threading, "Thread", return_value=stderr_thread
            ),
            mock.patch.object(baseline, "wait_for_page_client", return_value=client),
            mock.patch.object(baseline, "_wait_for_status", side_effect=[{}, {}]),
            mock.patch.object(
                baseline,
                "stop_browser_group",
                side_effect=M0Error("browser group cleanup failed"),
            ) as stop_browser_group,
            self.assertRaisesRegex(M0Error, "browser group cleanup failed"),
        ):
            baseline.run_measurement(
                server=mock.Mock(),
                url="http://127.0.0.1:12345/__m9__/",
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
            )

        stop_browser_group.assert_called_once_with(browser, mock.ANY)
        profile.cleanup.assert_called_once_with()

    def test_main_closes_and_joins_after_shutdown_error_without_masking_failure(
        self,
    ) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 12345)
        server.module_name = baseline.PRODUCT_MODULE_NAME
        server.shutdown.side_effect = RuntimeError("server shutdown failed")
        server_thread = mock.Mock()
        stderr = io.StringIO()

        with (
            mock.patch.object(baseline, "check_boundary"),
            mock.patch.object(baseline, "load_manifest", return_value={}),
            mock.patch.object(
                baseline, "toolchain_manifest_versions", return_value={}
            ),
            mock.patch.object(
                baseline, "create_measurement_server", return_value=server
            ),
            mock.patch.object(baseline, "artifact_identity", return_value={}),
            mock.patch.object(
                baseline,
                "run_measurement",
                side_effect=M0Error("measurement startup failed"),
            ),
            mock.patch.object(
                baseline.threading, "Thread", return_value=server_thread
            ),
            mock.patch.object(baseline.sys, "argv", ["measurement-baseline"]),
            mock.patch.object(baseline.sys, "stderr", stderr),
        ):
            self.assertEqual(1, baseline.main())

        self.assertIn("measurement startup failed", stderr.getvalue())
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=5)

    def test_main_never_emits_captured_before_server_cleanup_succeeds(self) -> None:
        for method, failure in (
            ("shutdown", "server shutdown failed"),
            ("server_close", "server close failed"),
            ("join", "server thread join failed"),
        ):
            with self.subTest(method=method):
                server = mock.Mock()
                server.server_address = ("127.0.0.1", 12345)
                server.module_name = baseline.PRODUCT_MODULE_NAME
                server_thread = mock.Mock()
                if method == "join":
                    server_thread.join.side_effect = RuntimeError(failure)
                else:
                    getattr(server, method).side_effect = RuntimeError(failure)
                stdout = io.StringIO()

                with (
                    mock.patch.object(baseline, "check_boundary"),
                    mock.patch.object(baseline, "load_manifest", return_value={}),
                    mock.patch.object(
                        baseline, "toolchain_manifest_versions", return_value={}
                    ),
                    mock.patch.object(
                        baseline, "create_measurement_server", return_value=server
                    ),
                    mock.patch.object(
                        baseline, "artifact_identity", return_value={}
                    ),
                    mock.patch.object(
                        baseline, "capture_harness_identity", return_value={}
                    ),
                    mock.patch.object(
                        baseline,
                        "run_measurement",
                        return_value=(passing_snapshot(), "test-browser"),
                    ),
                    mock.patch.object(
                        baseline,
                        "make_baseline_result",
                        return_value={"captured": "result"},
                    ),
                    mock.patch.object(
                        baseline.threading, "Thread", return_value=server_thread
                    ),
                    mock.patch.object(
                        baseline.sys, "argv", ["measurement-baseline"]
                    ),
                    mock.patch.object(baseline.sys, "stdout", stdout),
                    self.assertRaisesRegex(RuntimeError, failure),
                ):
                    baseline.main()

                self.assertNotIn(f"{baseline.SENTINEL}:CAPTURED", stdout.getvalue())
                server.shutdown.assert_called_once_with()
                server.server_close.assert_called_once_with()
                server_thread.join.assert_called_once_with(timeout=5)

    def test_main_rejects_live_measurement_server_after_successful_capture(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 12345)
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = True
        stdout = io.StringIO()

        with (
            mock.patch.object(baseline, "check_boundary"),
            mock.patch.object(baseline, "load_manifest", return_value={}),
            mock.patch.object(
                baseline, "toolchain_manifest_versions", return_value={}
            ),
            mock.patch.object(
                baseline, "create_measurement_server", return_value=server
            ),
            mock.patch.object(baseline, "artifact_identity", return_value={}),
            mock.patch.object(
                baseline, "measurement_url", return_value="http://measurement.test/"
            ),
            mock.patch.object(
                baseline, "capture_harness_identity", return_value={}
            ),
            mock.patch.object(
                baseline,
                "run_measurement",
                return_value=(passing_snapshot(), "test-browser"),
            ),
            mock.patch.object(
                baseline,
                "make_baseline_result",
                return_value={"captured": "result"},
            ),
            mock.patch.object(
                baseline.threading, "Thread", return_value=server_thread
            ),
            mock.patch.object(baseline.sys, "argv", ["measurement-baseline"]),
            mock.patch.object(baseline.sys, "stdout", stdout),
            self.assertRaisesRegex(M0Error, "M9 measurement server did not stop"),
        ):
            baseline.main()

        self.assertNotIn(f"{baseline.SENTINEL}:CAPTURED", stdout.getvalue())
        server_thread.start.assert_called_once_with()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=5)
        server_thread.is_alive.assert_called_once_with()

    def test_main_rejects_browser_cleanup_failure_without_capture_marker(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 12345)
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = True
        stderr = io.StringIO()
        stdout = io.StringIO()

        with (
            mock.patch.object(baseline, "check_boundary"),
            mock.patch.object(baseline, "load_manifest", return_value={}),
            mock.patch.object(
                baseline, "toolchain_manifest_versions", return_value={}
            ),
            mock.patch.object(
                baseline, "create_measurement_server", return_value=server
            ),
            mock.patch.object(baseline, "artifact_identity", return_value={}),
            mock.patch.object(
                baseline, "measurement_url", return_value="http://measurement.test/"
            ),
            mock.patch.object(
                baseline,
                "run_measurement",
                side_effect=M0Error("browser group cleanup failed"),
            ),
            mock.patch.object(
                baseline.threading, "Thread", return_value=server_thread
            ),
            mock.patch.object(baseline.sys, "argv", ["measurement-baseline"]),
            mock.patch.object(baseline.sys, "stderr", stderr),
            mock.patch.object(baseline.sys, "stdout", stdout),
        ):
            self.assertEqual(1, baseline.main())

        self.assertIn("browser group cleanup failed", stderr.getvalue())
        self.assertNotIn(f"{baseline.SENTINEL}:CAPTURED", stdout.getvalue())
        server_thread.start.assert_called_once_with()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=5)
        server_thread.is_alive.assert_called_once_with()



class M9MeasurementSourceContractTest(unittest.TestCase):
    def test_host_and_runner_remain_observational_and_bounded(self) -> None:
        host = (
            REPO_ROOT / "tools/wasm/host/chrome_wasm_m9_measurement_host.js"
        ).read_text(encoding="utf-8")
        runner = (
            REPO_ROOT / "tools/wasm/run_m9_measurement_baseline.py"
        ).read_text(encoding="utf-8")
        html = (
            REPO_ROOT / "tools/wasm/host/chrome_wasm_m9_measurement.html"
        ).read_text(encoding="utf-8")

        for token in (
            "observational M9 baseline, not a benchmark or a release gate",
            "mainScriptUrlOrBlob",
            "first_frame_callback_after_canvas_copy",
            "SharedArrayBuffer",
            "new Proxy(nativeWorker",
            'event?.data?.cmd === "loaded"',
            "m9_gate_complete: false",
            "performance_gate: false",
            "status_sequence",
            "TERMINAL_GRACE_OBSERVATION_MS",
            'const PRODUCT_MODULE_NAME = "chrome_wasm"',
            "moduleName !== PRODUCT_MODULE_NAME",
            "query must select the chrome_wasm product module",
            "HEAPU8.buffer.byteLength capacity; not allocated or resident memory usage",
            "not raster, compositor, or vsync presentation timing",
            "not worker utilization or saturation",
            "recordStartupFailure",
            "one outer-page navigation in a fresh host-browser profile",
        ):
            with self.subTest(host_token=token):
                self.assertIn(token, host)
        self.assertIn('id="browser-canvas"', html)
        self.assertIn("runChromeWasmM9MeasurementFromQuery", html)
        for token in (
            'BASELINE_KIND = "pre-release-m9-measurement-baseline"',
            "create_measurement_server",
            "validate_measurement_snapshot",
            "validate_baseline_result",
            "artifact_source_provenance",
            "capture_harness_identity",
            "runner_source",
            "source_snapshot_provenance",
            "toolchain_manifest_versions",
            'PRODUCT_MODULE_NAME = "chrome_wasm"',
            "_require_product_module_name",
            "--module-name must be chrome_wasm",
            "one fresh host run only; no cross-run performance inference",
            ":CAPTURED ",
            "check_boundary(out_dir)",
        ):
            with self.subTest(runner_token=token):
                self.assertIn(token, runner)
        self.assertNotIn(":PASS", runner)
        self.assertNotIn("benchmark score", host.lower())

    def _run_host_query(self, query: str) -> dict[str, object]:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_m9_measurement_host.js"
        script = f"""
class HTMLElement {{}}
class HTMLCanvasElement extends HTMLElement {{
  constructor() {{
    super();
    this.width = 800;
    this.height = 600;
    this.style = {{}};
  }}
  focus() {{ document.activeElement = this; }}
}}
globalThis.HTMLElement = HTMLElement;
globalThis.HTMLCanvasElement = HTMLCanvasElement;
const root = new HTMLElement();
root.dataset = {{state: "starting"}};
const canvas = new HTMLCanvasElement();
const status = new HTMLElement();
status.textContent = "";
globalThis.document = {{
  activeElement: null,
  baseURI: "http://127.0.0.1/__m9__/",
  querySelector(selector) {{
    return selector === "#measurement-root" ? root :
        selector === "#browser-canvas" ? canvas :
        selector === "#measurement-status" ? status : null;
  }},
}};
globalThis.location = {{
  origin: "http://127.0.0.1",
  search: {json.dumps(query)},
}};
globalThis.crossOriginIsolated = true;
let fetchCalls = 0;
globalThis.fetch = () => {{
  fetchCalls += 1;
  throw new Error("unexpected measurement loader fetch");
}};
const host = await import({json.dumps(host.as_uri())});
await host.runChromeWasmM9MeasurementFromQuery();
const snapshot = globalThis.__chromiumWasmM9MeasurementV1.snapshot();
process.stdout.write(JSON.stringify({{rootState: root.dataset.state, snapshot, fetchCalls}}));
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
        return json.loads(completed.stdout)

    def test_malformed_query_exposes_a_failed_host_snapshot(self) -> None:
        observed = self._run_host_query("?module=chrome_wasm")
        self.assertEqual("failed", observed["rootState"])
        self.assertEqual("failed", observed["snapshot"]["status"])
        self.assertEqual(
            ["starting", "failed"],
            observed["snapshot"]["lifecycle"]["status_sequence"],
        )
        self.assertIn("query is invalid", observed["snapshot"]["failure"])
        self.assertEqual(0, observed["fetchCalls"])

    def test_alternate_module_query_is_rejected_before_loader_fetch(self) -> None:
        observed = self._run_host_query(
            "?module=alternate_wasm&timeout_ms=10000"
        )
        self.assertEqual("failed", observed["rootState"])
        self.assertEqual("failed", observed["snapshot"]["status"])
        self.assertEqual(
            ["starting", "failed"],
            observed["snapshot"]["lifecycle"]["status_sequence"],
        )
        self.assertIn(
            "must select the chrome_wasm product module",
            observed["snapshot"]["failure"],
        )
        self.assertEqual(0, observed["fetchCalls"])

    def test_native_memory_snapshot_rejects_unavailable_and_malformed_exports(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_m9_measurement_host.js"
        script = f"""
const {{nativeMemorySnapshot}} = await import({json.dumps(host.as_uri())});
const exports = {{
  chromium_wasm_browser_host_memory_linear_capacity_bytes: 67108864,
  chromium_wasm_browser_host_memory_linear_maximum_bytes: 2147483648,
  chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes: 0,
}};
function moduleFor(values) {{
  return {{ccall(name) {{
    if (!(name in values)) throw new Error("missing export");
    return values[name];
  }}}};
}}
function failure(values) {{
  try {{
    nativeMemorySnapshot(moduleFor(values));
  }} catch (error) {{
    return String(error);
  }}
  return "accepted";
}}
const valid = nativeMemorySnapshot(moduleFor(exports));
const missing = failure({{
  chromium_wasm_browser_host_memory_linear_capacity_bytes: 67108864,
}});
const malformed = failure({{...exports,
  chromium_wasm_browser_host_memory_linear_capacity_bytes: 3.5,
}});
const unaligned = failure({{...exports,
  chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes: 1,
}});
const maximum = failure({{...exports,
  chromium_wasm_browser_host_memory_linear_maximum_bytes: 65536,
}});
process.stdout.write(JSON.stringify({{valid, missing, malformed, unaligned, maximum}}));
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
        observed = json.loads(completed.stdout)
        self.assertEqual(2_080_374_784, observed["valid"]["wasm_linear_memory_headroom_bytes"])
        self.assertIn("unavailable", observed["missing"])
        self.assertIn("exact nonnegative", observed["malformed"])
        self.assertIn("not Wasm-page aligned", observed["unaligned"])
        self.assertIn("maximum is below", observed["maximum"])

    def test_host_javascript_parses_when_node_is_available(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        host = REPO_ROOT / "tools/wasm/host/chrome_wasm_m9_measurement_host.js"
        completed = subprocess.run(
            [
                str(node),
                "--experimental-default-type=module",
                "--check",
                str(host),
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )


if __name__ == "__main__":
    unittest.main()

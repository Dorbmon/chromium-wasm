#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused host/runner contracts for the M8 AudioManager output smoke.

These tests deliberately do not build media/audio or launch a browser. They
lock the browser-bound protocol, redaction shape, immutable snapshot server,
and unsigned 16-word descriptor ABI before native integration is exercised.
"""

from __future__ import annotations

import copy
from collections import deque
import hashlib
from http import HTTPStatus
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_audio_manager_output_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "a" * 40,
    "v8": "b" * 40,
    "emscripten": "c" * 40,
}
ARTIFACT = {
    "artifactDelivery": smoke.ARTIFACT_DELIVERY,
    "artifactSourceProvenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "buildConfig": {"bytes": 7, "sha256": "d" * 64},
    "buildConfigProvenance": smoke.BUILD_CONFIG_PROVENANCE,
    "loader": {"bytes": 8, "sha256": "e" * 64},
    "moduleName": smoke.DEFAULT_MODULE_NAME,
    "wasm": {"bytes": 9, "sha256": "f" * 64},
}
CAPTURE_HARNESS = {
    "bridgeLibrary": {"bytes": 10, "sha256": "0" * 64},
    "hostHtml": {"bytes": 11, "sha256": "1" * 64},
    "hostJs": {"bytes": 12, "sha256": "2" * 64},
    "runnerSource": {"bytes": 13, "sha256": "3" * 64},
    "sourceSnapshotProvenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "versionProvenance": smoke.VERSION_PROVENANCE,
    "workletJs": {"bytes": 14, "sha256": "4" * 64},
}
ORIGIN = "http://127.0.0.1:43127"


def passing_result() -> dict[str, object]:
    result: dict[str, object] = {field: False for field in smoke.RESULT_FIELDS}
    result.update(
        {
            "protocol": smoke.HOST_PROTOCOL,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "status": "pass",
            "failureCode": None,
            "limitations": list(smoke.LIMITATIONS),
            "artifact": copy.deepcopy(ARTIFACT),
            "captureHarness": copy.deepcopy(CAPTURE_HARNESS),
            "versions": copy.deepcopy(VERSIONS),
            "origin": ORIGIN,
            "secureContext": True,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "sameOriginDocument": True,
            "descriptorProtocol": smoke.DESCRIPTOR_PROTOCOL,
            "capacityFrames": smoke.CAPACITY_FRAMES,
            "channels": smoke.CHANNELS,
            "sampleRate": smoke.SAMPLE_RATE,
            "framesPerBuffer": smoke.FRAMES_PER_BUFFER,
            "totalFrames": smoke.TOTAL_FRAMES,
            "descriptorRegistered": True,
            "descriptorRegistrationCount": 1,
            "descriptorGeneration": 7,
            "descriptorValidated": True,
            "memoryIdentityStable": True,
            "memoryIdentityChecks": 4,
            "nativeMarkerSource": "stderr-only",
            "nativeMarkers": list(smoke.EXPECTED_MARKERS),
            "nativeMarkerSequenceAccepted": True,
            "runtimeInitialized": True,
            "runtimeFactorySettled": True,
            "runtimeAborted": False,
            "onExitCount": 1,
            "runtimeExitCode": 0,
            "normalModuleExitObserved": True,
            "trustedGesture": True,
            "resumeRequestedInTrustedGesture": True,
            "audioContextRunning": True,
            "workletReady": True,
            "workletProgressObserved": True,
            "workletDrained": True,
            "outputArmed": True,
            "startObserved": True,
            "stopObserved": True,
            "unregisterObserved": True,
            "producedFrames": smoke.TOTAL_FRAMES,
            "consumedFrames": smoke.TOTAL_FRAMES,
            "workletFramesRead": smoke.TOTAL_FRAMES,
            "workletNonSilentFrames": smoke.TOTAL_FRAMES,
            "underrunFrames": 0,
            "producerError": 0,
            "hostState": 3,
            "workletStopRequested": True,
            "workletDisconnected": True,
            "audioContextClosed": True,
            "cleanupComplete": True,
            "m8GateComplete": False,
            "audioManagerOutputPathProven": True,
            "audioServiceIntegrated": False,
            "inputProven": False,
            "deviceChangePolicyProven": False,
            "mutePolicyProven": False,
            "tabSwitchingProven": False,
            "browserMediaPlaybackProven": False,
            "normalRuntimeShutdownProven": False,
        }
    )
    assert set(result) == smoke.RESULT_FIELDS
    return result


def failure_result() -> dict[str, object]:
    return {
        "protocol": smoke.HOST_PROTOCOL,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "fail",
        "failureClass": "host-lifecycle",
        "firstFatalTag": "marker-unexpected",
        "nativeFailureStage": None,
        "lifecycle": {
            "cleanupComplete": True,
            "descriptorRegistered": True,
            "factorySettled": True,
            "markerCount": 2,
            "normalExitObserved": False,
            "outputArmed": False,
            "runtimeInitialized": True,
            "unregisterObserved": False,
            "workletDrained": False,
            "workletReady": False,
        },
    }


def validate(result: dict[str, object]) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT,
        expected_capture_harness_identity=CAPTURE_HARNESS,
        expected_origin=ORIGIN,
    )


class M8AudioManagerOutputResultTest(unittest.TestCase):
    def test_accepts_complete_native_output_evidence(self) -> None:
        validate(passing_result())

    def test_rejects_lifecycle_marker_header_and_nonclaim_mutations(self) -> None:
        mutations = (
            lambda result: result.__setitem__("normalModuleExitObserved", False),
            lambda result: result.__setitem__("onExitCount", 0),
            lambda result: result.__setitem__("runtimeExitCode", 1),
            lambda result: result.__setitem__("nativeMarkerSource", "stdout-only"),
            lambda result: result["nativeMarkers"].pop(),
            lambda result: result.__setitem__("descriptorRegistrationCount", 2),
            lambda result: result.__setitem__("descriptorGeneration", 0),
            lambda result: result.__setitem__("producedFrames", 11999),
            lambda result: result.__setitem__("hostState", 2),
            lambda result: result.__setitem__("audioServiceIntegrated", True),
            lambda result: result.__setitem__("normalRuntimeShutdownProven", True),
            lambda result: result["limitations"].pop(),
            lambda result: result.__setitem__("rawNativeOutput", "not-allowed"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_failure_summary_is_fixed_and_carries_no_raw_text(self) -> None:
        summary = smoke.validate_failed_host_result_summary(failure_result())
        self.assertEqual(summary["firstFatalTag"], "marker-unexpected")
        for mutation in (
            lambda result: result.__setitem__("nativeFailureStage", "raw-data"),
            lambda result: result["lifecycle"].__setitem__("raw", "not-allowed"),
            lambda result: result["lifecycle"].__setitem__("markerCount", 7),
            lambda result: result.__setitem__("untrusted", "not-allowed"),
        ):
            with self.subTest(mutation=mutation):
                result = failure_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    smoke.validate_failed_host_result_summary(result)

    def test_recognizes_only_the_native_fixed_failure_stages(self) -> None:
        result = failure_result()
        result["failureClass"] = "native-fixed-failure"
        result["nativeFailureStage"] = "drain"
        summary = smoke.validate_failed_host_result_summary(result)
        self.assertEqual(summary["nativeFailureStage"], "drain")
        result["nativeFailureStage"] = "descriptor"
        with self.assertRaises(M0Error):
            smoke.validate_failed_host_result_summary(result)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            smoke._reject_duplicate_object_keys(
                [("protocol", 1), ("protocol", 1)]
            )

    def test_pre_ready_fixed_failure_is_reconstructed_before_timeout(self) -> None:
        class RunningBrowser:
            def poll(self) -> None:
                return None

        class EventServer:
            def __init__(self) -> None:
                self.result_lock = threading.Lock()
                self.ready_received = False
                self.ready_event_order = None
                self.ready_payload = None
                self.result_received = True
                self.result_event_order = 1
                self.result_payload = failure_result()

        kind, value = smoke._wait_for_ready_or_early_result(
            EventServer(),
            RunningBrowser(),
            time.monotonic() + 1.0,
            "wait-host-ready",
            deque(),
        )
        self.assertEqual(kind, "result")
        summary = smoke._validate_early_result_before_ready(value)
        self.assertEqual(summary["firstFatalTag"], "marker-unexpected")

    def test_http_acceptance_order_rejects_interleaved_result_before_ready(self) -> None:
        class RunningBrowser:
            def poll(self) -> None:
                return None

        ready_payload = {
            "protocol": smoke.HOST_PROTOCOL,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "ready": True,
        }
        class EventServer:
            def __init__(self) -> None:
                self.result_lock = threading.Lock()
                # This is the exact interleaving that independent queue
                # polling could mishandle: result was accepted before ready,
                # but both are visible on the next runner iteration.
                self.ready_received = True
                self.ready_event_order = 2
                self.ready_payload = ready_payload
                self.result_received = True
                self.result_event_order = 1
                self.result_payload = failure_result()

        kind, value = smoke._wait_for_ready_or_early_result(
            EventServer(),
            RunningBrowser(),
            time.monotonic() + 1.0,
            "wait-host-ready",
            deque(),
        )
        self.assertEqual(kind, "result")
        self.assertEqual(value, failure_result())

    def test_ready_before_later_result_preserves_the_ready_path(self) -> None:
        class RunningBrowser:
            def poll(self) -> None:
                return None

        ready_payload = {
            "protocol": smoke.HOST_PROTOCOL,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "ready": True,
        }

        class EventServer:
            def __init__(self) -> None:
                self.result_lock = threading.Lock()
                self.ready_received = True
                self.ready_event_order = 1
                self.ready_payload = ready_payload
                self.result_received = True
                self.result_event_order = 2
                self.result_payload = failure_result()

        kind, value = smoke._wait_for_ready_or_early_result(
            EventServer(),
            RunningBrowser(),
            time.monotonic() + 1.0,
            "wait-host-ready",
            deque(),
        )
        self.assertEqual(kind, "ready")
        self.assertEqual(value, ready_payload)

    def test_pre_ready_pass_result_is_rejected_without_raw_payload(self) -> None:
        class RunningBrowser:
            def poll(self) -> None:
                return None

        class EventServer:
            def __init__(self) -> None:
                self.result_lock = threading.Lock()
                self.ready_received = False
                self.ready_event_order = None
                self.ready_payload = None
                self.result_received = True
                self.result_event_order = 1
                self.result_payload = passing_result()

        kind, value = smoke._wait_for_ready_or_early_result(
            EventServer(),
            RunningBrowser(),
            time.monotonic() + 1.0,
            "wait-host-ready",
            deque(),
        )
        self.assertEqual(kind, "result")
        with self.assertRaises(M0Error):
            smoke._validate_early_result_before_ready(value)

    def test_result_in_ready_to_click_gap_prevents_the_click(self) -> None:
        class EventServer:
            def __init__(self) -> None:
                self.result_lock = threading.Lock()
                self.result_received = True
                self.result_payload = failure_result()

        class Client:
            clicked = False

            def dispatch_primary_click(self, _x: float, _y: float) -> None:
                self.clicked = True

        client = Client()
        result = smoke._dispatch_primary_click_at_result_boundary(
            EventServer(), client
        )
        self.assertEqual(result, failure_result())
        self.assertFalse(client.clicked)
        summary = smoke._validate_result_before_trusted_click(result)
        self.assertEqual(summary["firstFatalTag"], "marker-unexpected")

    def test_click_boundary_holds_acceptance_lock_through_dispatch(self) -> None:
        class EventServer:
            def __init__(self) -> None:
                self.result_lock = threading.Lock()
                self.result_received = False
                self.result_payload = None

        server = EventServer()
        result_accepted = threading.Event()

        class Client:
            lock_held_during_dispatch = False
            result_accepted_during_dispatch = True
            worker: threading.Thread | None = None

            def dispatch_primary_click(self, x: float, y: float) -> None:
                self.lock_held_during_dispatch = server.result_lock.locked()
                if (x, y) != (smoke.START_BUTTON_X, smoke.START_BUTTON_Y):
                    raise AssertionError("unexpected click coordinates")

                def accept_result() -> None:
                    with server.result_lock:
                        server.result_received = True
                        server.result_payload = failure_result()
                        result_accepted.set()

                self.worker = threading.Thread(target=accept_result)
                self.worker.start()
                self.result_accepted_during_dispatch = result_accepted.wait(0.05)

        client = Client()
        self.assertIsNone(
            smoke._dispatch_primary_click_at_result_boundary(server, client)
        )
        self.assertTrue(client.lock_held_during_dispatch)
        self.assertFalse(client.result_accepted_during_dispatch)
        assert client.worker is not None
        client.worker.join(timeout=1)
        self.assertFalse(client.worker.is_alive())
        self.assertTrue(result_accepted.is_set())

    def test_pre_click_pass_result_is_rejected_without_raw_payload(self) -> None:
        class EventServer:
            def __init__(self) -> None:
                self.result_lock = threading.Lock()
                self.result_received = True
                self.result_payload = passing_result()

        class Client:
            def dispatch_primary_click(self, _x: float, _y: float) -> None:
                raise AssertionError("pre-click result must suppress dispatch")

        result = smoke._dispatch_primary_click_at_result_boundary(
            EventServer(), Client()
        )
        assert result is not None
        with self.assertRaises(M0Error):
            smoke._validate_result_before_trusted_click(result)

    def test_host_validator_accepts_runner_shaped_result(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "m8_audio_manager_output_smoke.js"
        ).as_uri()
        payload = json.dumps(passing_result(), separators=(",", ":"))
        script = (
            "globalThis.location = {origin: "
            + json.dumps(ORIGIN)
            + "};\nimport {validateM8AudioManagerOutputResult} from "
            + json.dumps(host_uri)
            + ";\nconst result = JSON.parse(process.argv[1]);\n"
            + "if (validateM8AudioManagerOutputResult(result).status !== 'pass') {"
            + " throw new Error('validator rejected result'); }\n"
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script, payload],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class M8AudioManagerOutputServerTest(unittest.TestCase):
    def test_server_snapshots_only_exact_routes_and_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out_dir = root / "out"
            out_dir.mkdir()
            (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.js").write_bytes(b"loader")
            (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.wasm").write_bytes(b"\0asm")
            (out_dir / "args.gn").write_text("is_wasm = true\n", encoding="utf-8")
            host_dir = root / "host"
            host_dir.mkdir()
            for name in (
                "m8_audio_manager_output_smoke.html",
                "m8_audio_manager_output_smoke.js",
                "m8_audio_manager_output_worklet.js",
            ):
                (host_dir / name).write_text(name + "\n", encoding="utf-8")
            bridge_path = root / "m8_audio_manager_output_bridge_v1.js"
            bridge_path.write_text("bridge\n", encoding="utf-8")
            runner_path = root / "runner.py"
            runner_path.write_text("runner\n", encoding="utf-8")
            ready_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                "a" * 24,
                ready_queue,
                result_queue,
                host_dir=host_dir,
                bridge_library_path=bridge_path,
                runner_source_path=runner_path,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                smoke.verify_server_delivery(server)
                host, port = server.server_address[:2]
                base = f"http://{host}:{port}{smoke.HOST_ROOT}"
                with urlopen(base + "/") as response:
                    self.assertEqual(response.status, HTTPStatus.OK)
                    self.assertEqual(
                        response.headers["Cross-Origin-Opener-Policy"], "same-origin"
                    )
                    self.assertEqual(
                        response.headers["Cross-Origin-Embedder-Policy"], "require-corp"
                    )
                for path in (
                    "/m8_audio_manager_output_bridge_v1.js",
                    "/artifacts/other.wasm",
                    "/run_m8_audio_manager_output_smoke.py",
                ):
                    with self.subTest(path=path):
                        with self.assertRaises(HTTPError) as error:
                            urlopen(base + path)
                        self.assertEqual(error.exception.code, HTTPStatus.NOT_FOUND)
                        error.exception.close()

                def post(path: str, payload: dict[str, object]) -> None:
                    request = Request(
                        base + path,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(request) as response:
                        self.assertEqual(response.status, HTTPStatus.NO_CONTENT)

                # Exercise handler-side ordering, not only the runner's
                # synthetic interleaving model: result acceptance precedes
                # ready acceptance and must remain visible atomically.
                post(f"/result/{server.result_token}", failure_result())
                post(
                    f"/ready/{server.result_token}",
                    {
                        "protocol": smoke.HOST_PROTOCOL,
                        "case": smoke.CASE,
                        "scope": smoke.SCOPE,
                        "ready": True,
                    },
                )
                with server.result_lock:
                    self.assertEqual(server.result_event_order, 1)
                    self.assertEqual(server.ready_event_order, 2)
                    self.assertEqual(server.next_event_order, 2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())

    def test_default_bridge_snapshot_is_the_linked_media_bridge(self) -> None:
        self.assertEqual(
            smoke.BRIDGE_LIBRARY_PATH,
            smoke.REPO_ROOT / "media" / "audio" / "wasm_audio_bridge.js",
        )
        self.assertTrue(smoke.BRIDGE_LIBRARY_PATH.is_file())
        expected = smoke.snapshot_regular_file(
            smoke.BRIDGE_LIBRARY_PATH,
            maximum_bytes=smoke.MAX_SNAPSHOT_BYTES,
            description="expected linked M8 audio bridge",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out_dir = root / "out"
            out_dir.mkdir()
            (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.js").write_bytes(b"loader")
            (out_dir / f"{smoke.DEFAULT_MODULE_NAME}.wasm").write_bytes(b"\0asm")
            (out_dir / "args.gn").write_text("is_wasm = true\n", encoding="utf-8")
            host_dir = root / "host"
            host_dir.mkdir()
            for name in (
                "m8_audio_manager_output_smoke.html",
                "m8_audio_manager_output_smoke.js",
                "m8_audio_manager_output_worklet.js",
            ):
                (host_dir / name).write_text(name + "\n", encoding="utf-8")
            runner_path = root / "runner.py"
            runner_path.write_text("runner\n", encoding="utf-8")
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                "a" * 24,
                queue.Queue(maxsize=1),
                queue.Queue(maxsize=1),
                host_dir=host_dir,
                runner_source_path=runner_path,
            )
            try:
                self.assertEqual(server.bridge_library, expected)
                self.assertEqual(
                    smoke.capture_harness_identity(server)["bridgeLibrary"],
                    {
                        "bytes": len(expected),
                        "sha256": hashlib.sha256(expected).hexdigest(),
                    },
                )
            finally:
                server.server_close()

    def test_url_carries_only_the_fixed_context(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 43127)
            result_token = "a" * 24
            module_name = smoke.DEFAULT_MODULE_NAME

        url = smoke.smoke_url(
            Server(),
            "a" * 24,
            VERSIONS,
            artifact=ARTIFACT,
            capture_harness=CAPTURE_HARNESS,
            module_name=smoke.DEFAULT_MODULE_NAME,
            timeout_seconds=45.0,
        )
        parsed = urlsplit(url)
        self.assertEqual(parsed.path, smoke.HOST_ROOT + "/")
        query = parse_qs(parsed.query, strict_parsing=True)
        self.assertEqual(
            set(query), {"artifact", "captureHarness", "module", "timeoutMs", "token", "versions"}
        )
        self.assertEqual(query["token"], ["a" * 24])
        self.assertEqual(query["module"], [smoke.DEFAULT_MODULE_NAME])
        self.assertEqual(query["timeoutMs"], ["45000"])


class M8AudioManagerOutputSourceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.build = source("media/audio/BUILD.gn")
        self.native = source("media/audio/wasm_audio_manager_output_smoke.cc")
        self.host = source("tools/wasm/host/m8_audio_manager_output_smoke.js")
        self.worklet = source("tools/wasm/host/m8_audio_manager_output_worklet.js")
        self.html = source("tools/wasm/host/m8_audio_manager_output_smoke.html")
        self.runner = source("tools/wasm/run_m8_audio_manager_output_smoke.py")

    def test_pins_unsigned_sixteen_word_header_and_fixed_drain(self) -> None:
        for text in (self.host, self.worklet):
            with self.subTest(source=text[:24]):
                self.assertIn("Uint32Array", text)
                self.assertIn("HEADER_WORDS = 16", text)
                self.assertIn("CAPACITY_FRAMES = 4096", text)
                self.assertIn("CHANNELS = 2", text)
                self.assertIn("SAMPLE_RATE = 48000", text)
                self.assertIn("FRAMES_PER_BUFFER = 480", text)
                self.assertIn("TOTAL_FRAMES = 12000", text)
                self.assertIn("HOST_STATE_ERROR = 0xffffffff", text)
        self.assertIn("(snapshot[7] - snapshot[8]) >>> 0", self.host)
        self.assertIn("(writeIndex - readIndex) >>> 0", self.worklet)
        self.assertIn("header[8] === header[7]", self.host)
        self.assertIn("header[7] === header[9]", self.host)
        self.assertIn("producedFrames === TOTAL_FRAMES", self.worklet)

    def test_default_module_name_matches_the_gn_executable_artifact(self) -> None:
        self.assertEqual(smoke.DEFAULT_MODULE_NAME, "wasm_audio_manager_output_smoke")
        self.assertIn(
            'executable("wasm_audio_manager_output_smoke")', self.build
        )
        self.assertIn(
            'DEFAULT_MODULE_NAME = "wasm_audio_manager_output_smoke"', self.host
        )
        self.assertIn(
            'DEFAULT_MODULE_NAME = "wasm_audio_manager_output_smoke"', self.runner
        )

    def test_trusted_click_precedes_worklet_arm_and_native_start(self) -> None:
        trusted = self.host.index("event.isTrusted !== true")
        resume = self.host.index("const resumePromise = context.resume();")
        worklet = self.host.index("context.audioWorklet.addModule")
        armed = self.host.index("this.outputArmed = true")
        self.assertLess(trusted, resume)
        self.assertLess(resume, worklet)
        self.assertLess(worklet, armed)
        self.assertIn("isOutputArmed", self.host)
        self.assertIn("registerOutputRing", self.host)
        self.assertIn("unregisterOutputRing", self.host)
        self.assertIn(
            "dispatch_primary_click(START_BUTTON_X, START_BUTTON_Y)", self.runner
        )
        self.assertNotIn("Runtime.evaluate", self.runner)
        self.assertNotIn(".click()", self.runner)

    def test_requires_strict_marker_exit_and_cleanup_lifecycle(self) -> None:
        self.assertIn('const MARKER_PREFIX = "CHROMIUM_WASM_M8_AUDIO_MANAGER:"',
                      self.host)
        for suffix in ("READY", "OPENED", "STARTED", "DRAINED", "STOPPED", "CLOSED"):
            self.assertIn(f"${{MARKER_PREFIX}}{suffix}", self.host)
        self.assertIn("destination !== \"stderr\"", self.host)
        self.assertIn("this.markerIndex !== 4", self.host)
        self.assertNotIn("this.markerIndex < 5", self.host)
        self.assertIn("this.markerIndex < 4 || !this.unregisterObserved", self.host)
        self.assertIn("this.onExitCount !== 1 || code !== 0", self.host)
        self.assertIn("!this.unregisterObserved", self.host)
        self.assertIn("this.audioContextClosed", self.host)
        self.assertIn("this.workletDisconnected", self.host)
        self.assertIn("this.cleanupComplete", self.host)
        self.assertIn("does_not_prove_start_stop_start_or_stream_reuse", self.host)
        self.assertIn("does_not_prove_start_stop_start_or_stream_reuse", self.runner)
        self.assertIn("normalModuleExitObserved", self.runner)
        self.assertIn("validate_failed_host_result_summary", self.runner)

    def test_native_failure_stage_allowlists_match_cxx_fail_calls(self) -> None:
        native_stages = frozenset(re.findall(r'Fail\("([a-z-]+)"\)', self.native))
        self.assertEqual(native_stages, smoke.FAILURE_STAGES)
        for stage in sorted(native_stages):
            self.assertIn(f'"{stage}"', self.host)
            self.assertIn(f'"{stage}"', self.runner)

    def test_cross_layer_marker_arm_and_unregister_order_match_native(self) -> None:
        native_markers = re.findall(r'EmitMarker\("([A-Z]+)"\)', self.native)
        self.assertEqual(
            native_markers,
            ["READY", "OPENED", "STARTED", "DRAINED", "STOPPED", "CLOSED"],
        )
        wait_for_host_start = self.native.index(
            "if (!WaitForHostStart(state->wasm_stream)"
        )
        post_start = self.native.index("PostStart(manager.get(), source, state)")
        stop_and_close = self.native.rindex(
            "const OperationResult stop_result = PostStopAndClose("
        )
        self.assertLess(
            self.native.index('EmitMarker("OPENED")'),
            wait_for_host_start,
        )
        self.assertLess(wait_for_host_start, post_start)
        self.assertLess(
            self.native.index('EmitMarker("DRAINED")'),
            stop_and_close,
        )
        self.assertLess(stop_and_close, self.native.index('EmitMarker("STOPPED")'))
        self.assertLess(
            self.native.index('EmitMarker("CLOSED")'), self.native.rindex("return 0;")
        )
        self.assertIn("this.markerIndex === 5 && !this.unregisterObserved", self.host)

    def test_native_timeout_ownership_keeps_queued_audio_tasks_alive(self) -> None:
        self.assertIn(
            "public base::RefCountedThreadSafe<FiniteSource>", self.native
        )
        self.assertIn(
            "public base::RefCountedThreadSafe<StreamState>", self.native
        )
        self.assertIn("class OperationCompletion final", self.native)
        self.assertIn("base::MakeRefCounted<OperationCompletion>()", self.native)
        self.assertNotIn("base::WaitableEvent completed;", self.native)
        self.assertNotIn("&completed", self.native)
        self.assertIn("class TerminalAudioTombstone final", self.native)
        self.assertIn("std::move(*thread_pool)", self.native)
        self.assertIn("std::move(*log_factory)", self.native)
        self.assertIn("std::move(*manager),", self.native)
        self.assertIn("std::move(*source), std::move(*state)", self.native)
        self.assertIn("kPostRejected", self.native)
        self.assertIn("RequiresTerminalTombstone", self.native)
        open_failure = self.native.split(
            "if (open_result != OperationResult::kSuccess) {", 1
        )[1]
        self.assertIn("RequiresTerminalTombstone(open_result)", open_failure)
        self.assertIn(
            "const OperationResult stop_result = PostStopAndClose(manager.get(), state);",
            open_failure,
        )

    def test_bridge_ordering_allows_preclick_register_only_postdrained_unregister(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "m8_audio_manager_output_smoke.js"
        ).as_uri()
        script = """
globalThis.location = {origin: "http://127.0.0.1:43127"};
import {M8AudioManagerOutputSmoke} from %s;
const buffer = new SharedArrayBuffer(64 * 1024 * 1024);
const header = new Uint32Array(buffer, 0, 16);
header.set([1, 4096, 2, 48000, 480, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
const descriptor = {
  protocol: 1, generation: 7, ringBuffer: buffer, headerByteOffset: 0,
  samplesByteOffset: 64, capacityFrames: 4096, channels: 2,
  sampleRate: 48000, framesPerBuffer: 480,
};
const makeFake = (markerIndex) => ({
  callbackCount: 0,
  descriptor: null,
  descriptorRegistered: false,
  descriptorRegistrationCount: 0,
  failureCode: null,
  finished: false,
  markerIndex,
  outputArmed: false,
  unregisterObserved: false,
  wasmMemory: {buffer},
  noteCallback() { this.callbackCount += 1; },
  verifyMemoryIdentity() { return true; },
  maybeReadyForClick() { this.readyCalled = true; },
  maybeCompleteNativeLifecycle() { this.completedCalled = true; },
  setFailure(code) { if (this.failureCode === null) this.failureCode = code; },
  hasStoppedHeader() { return true; },
  normalModuleExitObserved: false,
  onExitCount: 0,
  runtimeExitCode: null,
});
const preClick = makeFake(0);
if (M8AudioManagerOutputSmoke.prototype.registerOutputRing.call(preClick, descriptor) !== true ||
    preClick.failureCode !== null || preClick.descriptorRegistered !== true ||
    preClick.outputArmed !== false) {
  throw new Error("pre-click-register");
}
header[6] = 2;
const beforeDrained = makeFake(3);
beforeDrained.descriptor = {generation: 7, header};
beforeDrained.descriptorRegistered = true;
if (M8AudioManagerOutputSmoke.prototype.unregisterOutputRing.call(beforeDrained, 7) !== false ||
    beforeDrained.failureCode !== "descriptor-unregister-invalid") {
  throw new Error("unregister-before-drained");
}
const afterDrained = makeFake(4);
afterDrained.descriptor = {generation: 7, header};
afterDrained.descriptorRegistered = true;
if (M8AudioManagerOutputSmoke.prototype.unregisterOutputRing.call(afterDrained, 7) !== true ||
    afterDrained.failureCode !== null || afterDrained.unregisterObserved !== true) {
  throw new Error("unregister-after-drained");
}
const afterStopped = makeFake(5);
afterStopped.descriptor = {generation: 7, header};
afterStopped.descriptorRegistered = true;
if (M8AudioManagerOutputSmoke.prototype.unregisterOutputRing.call(afterStopped, 7) !== false ||
    afterStopped.failureCode !== "descriptor-unregister-invalid") {
  throw new Error("unregister-after-stopped");
}
const delayedStderr = makeFake(4);
delayedStderr.unregisterObserved = true;
M8AudioManagerOutputSmoke.prototype.onExit.call(delayedStderr, 0);
if (delayedStderr.failureCode !== null || delayedStderr.normalModuleExitObserved !== true ||
    delayedStderr.runtimeExitCode !== 0) {
  throw new Error("exit-before-forwarded-stopped-closed");
}
const earlyExit = makeFake(3);
earlyExit.unregisterObserved = true;
M8AudioManagerOutputSmoke.prototype.onExit.call(earlyExit, 0);
if (earlyExit.failureCode !== "native-runtime-exit-invalid") {
  throw new Error("exit-before-drained");
}
""" % json.dumps(host_uri)
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_resumed_audio_context_must_retain_the_fixed_48khz_rate(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "m8_audio_manager_output_smoke.js"
        ).as_uri()
        script = """
globalThis.location = {origin: "http://127.0.0.1:43127"};
import {M8AudioManagerOutputSmoke} from %s;
const smoke = {
  deadline: performance.now() + 1000,
  descriptor: {},
  failureCode: null,
  verifyMemoryIdentity() { return true; },
  setFailure(code) { if (this.failureCode === null) this.failureCode = code; },
};
await M8AudioManagerOutputSmoke.prototype.finishTrustedStart.call(
    smoke, {state: "running", sampleRate: 44100}, Promise.resolve());
if (smoke.failureCode !== "audio-context-sample-rate-invalid") {
  throw new Error("accepted-non-48khz-context");
}
""" % json.dumps(host_uri)
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_host_runner_and_page_do_not_serialize_arbitrary_output(self) -> None:
        for text in (self.host, self.worklet, self.html):
            with self.subTest(source=text[:24]):
                self.assertNotIn("String(error)", text)
                self.assertNotIn("error.message", text)
                self.assertNotIn("console.error", text)
        self.assertIn("<suppressed-nonstring>", self.host)
        self.assertIn("stderr lines suppressed", self.runner)
        self.assertIn("snapshot_regular_files", self.runner)
        self.assertIn("snapshot_regular_file", self.runner)
        self.assertIn("verify_server_delivery(server)", self.runner)
        self.assertIn("bridgeLibrary", self.runner)
        self.assertIn('"media" / "audio" / "wasm_audio_bridge.js"', self.runner)
        self.assertIn("M8 AudioManager output host failure.", self.html)


if __name__ == "__main__":
    unittest.main()

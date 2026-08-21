#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the isolated M8 C++-pthread to host-WebAudio ring feasibility smoke.

The runner serves only a small fixed host page, worklet, coordinator, and the
two exact target artifacts under COOP/COEP. It waits for host readiness, then
sends one physical DevTools mouse click to the fixed start button. The click is
the only action that may initiate AudioContext.resume(); the runner neither
evaluates page commands nor calls a Wasm export. This proves no Chromium media
integration, device policy, tab switching, normal Wasm shutdown, or playback.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

from m0_common import M0Error, REPO_ROOT, parse_timeout
from m4_cdp import unused_loopback_port, wait_for_page_client
from run_browser_smoke import browser_command, find_browser, stop_browser


SENTINEL = "CHROMIUM_WASM_M8_WEBAUDIO_RING_DOM"
CASE = "m8_webaudio_ring"
SCOPE = "target-local-cpp-pthread-shared-memory-ring-to-host-audioworklet"
MODULE_NAME = "m8_webaudio_ring_smoke"
HOST_ROOT = "/__m8_webaudio_ring__"
HOST_PROTOCOL = 1
DESCRIPTOR_PROTOCOL = 1
CAPACITY_FRAMES = 4096
CHANNELS = 2
TOTAL_FRAMES = 12288
START_BUTTON_X = 120.0
START_BUTTON_Y = 48.0
MAX_RESULT_BYTES = 32 * 1024
MAX_UNDERRUN_FRAMES = 1 << 20
MAX_COUNTER = 1 << 20
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
FAILURE_CODES = frozenset(
    {
        "audio-context-close-failed",
        "audio-context-create-failed",
        "audio-context-not-running",
        "descriptor-invalid",
        "descriptor-duplicate",
        "document-prerequisite",
        "factory-failed",
        "host-exception",
        "memory-growth-rejected",
        "module-loader-failed",
        "native-marker-timeout",
        "native-output-invalid",
        "native-runtime-abort",
        "native-runtime-exited",
        "producer-report-invalid",
        "result-post-failed",
        "runtime-startup-timeout",
        "trusted-gesture-invalid",
        "wasm-memory-create-failed",
        "worklet-add-module-failed",
        "worklet-drain-invalid",
        "worklet-drain-timeout",
        "worklet-node-create-failed",
        "worklet-protocol-invalid",
        "worklet-runtime-failed",
    }
)
RESULT_KEYS = frozenset(
    {
        "audioContextClosed",
        "audioContextRunning",
        "browserMediaPlaybackProven",
        "case",
        "channels",
        "chromiumAudioManagerIntegrated",
        "chromiumAudioServiceIntegrated",
        "chromiumMediaSchedulingPreserved",
        "cleanupComplete",
        "crossOriginIsolated",
        "descriptorProtocol",
        "descriptorValidated",
        "failureCode",
        "m8GateComplete",
        "memoryGrowthPolicy",
        "memoryGrowthRejected",
        "memoryGrowthSignals",
        "memoryIdentityChecks",
        "memoryIdentityStable",
        "muteVolumeDevicePolicyProven",
        "nativeProducerDoneMarker",
        "nativeProducerStartedMarker",
        "nativeReady",
        "nodeDisconnected",
        "normalRuntimeShutdownProven",
        "producerFinished",
        "producerStarted",
        "protocol",
        "resumeRequestedInTrustedGesture",
        "runtimeAborted",
        "runtimeExited",
        "runtimeFactorySettled",
        "runtimeInitialized",
        "scope",
        "secureContext",
        "sharedArrayBuffer",
        "startRequested",
        "status",
        "tabSwitchingProven",
        "totalFrames",
        "trustedGesture",
        "workletDrained",
        "workletProgressObserved",
        "workletReady",
        "workletStopRequested",
        "workletUnderrunFrames",
    }
)
RESULT_BOOL_FIELDS = frozenset(
    {
        "audioContextClosed",
        "audioContextRunning",
        "browserMediaPlaybackProven",
        "chromiumAudioManagerIntegrated",
        "chromiumAudioServiceIntegrated",
        "chromiumMediaSchedulingPreserved",
        "cleanupComplete",
        "crossOriginIsolated",
        "descriptorValidated",
        "m8GateComplete",
        "memoryGrowthRejected",
        "memoryIdentityStable",
        "muteVolumeDevicePolicyProven",
        "nativeProducerDoneMarker",
        "nativeProducerStartedMarker",
        "nativeReady",
        "nodeDisconnected",
        "normalRuntimeShutdownProven",
        "producerFinished",
        "producerStarted",
        "resumeRequestedInTrustedGesture",
        "runtimeAborted",
        "runtimeExited",
        "runtimeFactorySettled",
        "runtimeInitialized",
        "secureContext",
        "sharedArrayBuffer",
        "startRequested",
        "tabSwitchingProven",
        "trustedGesture",
        "workletDrained",
        "workletProgressObserved",
        "workletReady",
        "workletStopRequested",
    }
)


class M8WebAudioRingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    out_dir: Path
    token: str
    ready_queue: queue.Queue[dict[str, Any]]
    result_queue: queue.Queue[dict[str, Any]]
    result_lock: threading.Lock
    ready_received: bool
    result_received: bool
    html_bytes: bytes
    host_js_bytes: bytes
    worklet_js_bytes: bytes


class M8WebAudioRingRequestHandler(BaseHTTPRequestHandler):
    server: M8WebAudioRingServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_bytes(
        self, status: HTTPStatus, content_type: str, body: bytes
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_bytes(
            HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        )

    def _artifact_path(self, name: str) -> Path | None:
        if name not in {f"{MODULE_NAME}.js", f"{MODULE_NAME}.wasm"}:
            return None
        artifact = (self.server.out_dir / name).resolve()
        try:
            artifact.relative_to(self.server.out_dir)
        except ValueError:
            return None
        return artifact if artifact.is_file() else None

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.html_bytes
            )
            return
        static_paths = {
            f"{HOST_ROOT}/m8_webaudio_ring_smoke.js": (
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
            ),
            f"{HOST_ROOT}/m8_webaudio_ring_worklet.js": (
                "text/javascript; charset=utf-8",
                self.server.worklet_js_bytes,
            ),
        }
        static = static_paths.get(path)
        if static is not None:
            self._send_bytes(HTTPStatus.OK, static[0], static[1])
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            artifact = self._artifact_path(path[len(prefix) :])
            if artifact is not None:
                content_type = (
                    "application/wasm"
                    if artifact.suffix == ".wasm"
                    else "text/javascript; charset=utf-8"
                )
                self._send_bytes(HTTPStatus.OK, content_type, artifact.read_bytes())
                return
        self._not_found()

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_RESULT_BYTES:
            return None
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            return None
        try:
            value = json.loads(
                self.rfile.read(content_length).decode("utf-8"),
                object_pairs_hook=_json_object_without_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == f"{HOST_ROOT}/ready/{self.server.token}":
            value = self._read_json_body()
            if not _is_ready_payload(value):
                self._send_bytes(
                    HTTPStatus.BAD_REQUEST,
                    "text/plain; charset=utf-8",
                    b"invalid ready result\n",
                )
                return
            with self.server.result_lock:
                if self.server.ready_received:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"duplicate ready result\n",
                    )
                    return
                self.server.ready_received = True
                try:
                    self.server.ready_queue.put_nowait(value)
                except queue.Full:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"ready queue full\n",
                    )
                    return
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path == f"{HOST_ROOT}/result/{self.server.token}":
            value = self._read_json_body()
            if not _is_result_payload(value):
                self._send_bytes(
                    HTTPStatus.BAD_REQUEST,
                    "text/plain; charset=utf-8",
                    b"invalid result\n",
                )
                return
            with self.server.result_lock:
                if self.server.result_received:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"duplicate result\n",
                    )
                    return
                self.server.result_received = True
                try:
                    self.server.result_queue.put_nowait(value)
                except queue.Full:
                    self._send_bytes(
                        HTTPStatus.CONFLICT,
                        "text/plain; charset=utf-8",
                        b"result queue full\n",
                    )
                    return
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self._not_found()


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _is_ready_payload(value: object) -> bool:
    return isinstance(value, dict) and value == {
        "protocol": HOST_PROTOCOL,
        "case": CASE,
        "scope": SCOPE,
        "ready": True,
    }


def _is_result_payload(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != RESULT_KEYS:
        return False
    if (
        type(value.get("protocol")) is not int
        or value.get("protocol") != HOST_PROTOCOL
        or value.get("case") != CASE
        or value.get("scope") != SCOPE
        or value.get("status") not in {"pass", "fail"}
    ):
        return False
    if (
        value.get("descriptorProtocol") != DESCRIPTOR_PROTOCOL
        or type(value.get("descriptorProtocol")) is not int
        or value.get("channels") != CHANNELS
        or type(value.get("channels")) is not int
        or value.get("totalFrames") != TOTAL_FRAMES
        or type(value.get("totalFrames")) is not int
        or value.get("memoryGrowthPolicy") != "reject-on-any-memory-growth"
    ):
        return False
    for field in RESULT_BOOL_FIELDS:
        if type(value.get(field)) is not bool:
            return False
    for field in ("memoryGrowthSignals", "memoryIdentityChecks"):
        count = value.get(field)
        if type(count) is not int or not 0 <= count <= MAX_COUNTER:
            return False
    underruns = value.get("workletUnderrunFrames")
    if underruns is not None and (
        type(underruns) is not int or not 0 <= underruns <= MAX_UNDERRUN_FRAMES
    ):
        return False
    failure_code = value.get("failureCode")
    if value.get("status") == "pass":
        return failure_code is None
    return failure_code in FAILURE_CODES


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    token: str,
    ready_queue: queue.Queue[dict[str, Any]],
    result_queue: queue.Queue[dict[str, Any]],
) -> M8WebAudioRingServer:
    if not TOKEN_RE.fullmatch(token):
        raise M0Error("M8 WebAudio token is invalid")
    resolved_out_dir = out_dir.resolve()
    if not resolved_out_dir.is_dir() or any(
        not (resolved_out_dir / name).is_file()
        for name in (f"{MODULE_NAME}.js", f"{MODULE_NAME}.wasm")
    ):
        raise M0Error("M8 WebAudio artifacts are missing")
    host_dir = Path(__file__).with_name("host")
    required_host_paths = {
        "html_bytes": host_dir / "m8_webaudio_ring_smoke.html",
        "host_js_bytes": host_dir / "m8_webaudio_ring_smoke.js",
        "worklet_js_bytes": host_dir / "m8_webaudio_ring_worklet.js",
    }
    if any(not path.is_file() for path in required_host_paths.values()):
        raise M0Error("M8 WebAudio host files are missing")
    server = M8WebAudioRingServer((host, port), M8WebAudioRingRequestHandler)
    server.out_dir = resolved_out_dir
    server.token = token
    server.ready_queue = ready_queue
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.ready_received = False
    server.result_received = False
    server.html_bytes = required_host_paths["html_bytes"].read_bytes()
    server.host_js_bytes = required_host_paths["host_js_bytes"].read_bytes()
    server.worklet_js_bytes = required_host_paths["worklet_js_bytes"].read_bytes()
    return server


def smoke_url(server: M8WebAudioRingServer, token: str, timeout_seconds: float) -> str:
    if token != server.token:
        raise M0Error("M8 WebAudio URL token does not match server")
    timeout_ms = max(1000, min(90000, int(timeout_seconds * 1000)))
    host, port = server.server_address[:2]
    return (
        f"http://{host}:{port}{HOST_ROOT}/?"
        + urlencode({"token": token, "timeoutMs": str(timeout_ms)})
    )


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    actual = result.get(field)
    if type(actual) is not type(expected) or actual != expected:
        raise M0Error(f"M8 WebAudio result {field} is invalid")


def _require_bool(result: dict[str, Any], field: str, expected: bool) -> None:
    if type(result.get(field)) is not bool or result.get(field) is not expected:
        raise M0Error(f"M8 WebAudio result {field} is invalid")


def validate_result(result: dict[str, Any]) -> None:
    if not _is_result_payload(result):
        raise M0Error("M8 WebAudio result shape is invalid")
    for field, expected in {
        "protocol": HOST_PROTOCOL,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "failureCode": None,
        "descriptorProtocol": DESCRIPTOR_PROTOCOL,
        "memoryGrowthPolicy": "reject-on-any-memory-growth",
        "memoryGrowthSignals": 0,
        "channels": CHANNELS,
        "totalFrames": TOTAL_FRAMES,
    }.items():
        _require_equal(result, field, expected)
    for field in (
        "secureContext",
        "crossOriginIsolated",
        "sharedArrayBuffer",
        "memoryIdentityStable",
        "descriptorValidated",
        "nativeReady",
        "nativeProducerStartedMarker",
        "nativeProducerDoneMarker",
        "runtimeInitialized",
        "runtimeFactorySettled",
        "trustedGesture",
        "resumeRequestedInTrustedGesture",
        "audioContextRunning",
        "workletReady",
        "workletProgressObserved",
        "workletDrained",
        "producerStarted",
        "producerFinished",
        "startRequested",
        "workletStopRequested",
        "nodeDisconnected",
        "audioContextClosed",
        "cleanupComplete",
    ):
        _require_bool(result, field, True)
    for field in (
        "memoryGrowthRejected",
        "runtimeAborted",
        "runtimeExited",
        "m8GateComplete",
        "chromiumAudioManagerIntegrated",
        "chromiumAudioServiceIntegrated",
        "chromiumMediaSchedulingPreserved",
        "muteVolumeDevicePolicyProven",
        "tabSwitchingProven",
        "browserMediaPlaybackProven",
        "normalRuntimeShutdownProven",
    ):
        _require_bool(result, field, False)
    underruns = result.get("workletUnderrunFrames")
    if type(underruns) is not int or not 0 <= underruns <= MAX_UNDERRUN_FRAMES:
        raise M0Error("M8 WebAudio underrun measurement is invalid")
    memory_identity_checks = result.get("memoryIdentityChecks")
    if type(memory_identity_checks) is not int or memory_identity_checks <= 0:
        raise M0Error("M8 WebAudio memory identity evidence is invalid")


def _wait_for_queue(
    values: queue.Queue[dict[str, Any]],
    browser: subprocess.Popen[object],
    deadline: float,
    stage: str,
) -> dict[str, Any]:
    while True:
        if browser.poll() is not None:
            raise M0Error(f"M8 WebAudio browser exited at {stage}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(f"M8 WebAudio timeout at {stage}")
        try:
            return values.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    browser: subprocess.Popen[object] | None,
    ready_received: bool,
    runtime_result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "m8-webaudio-ring-failure.json"
    # Keep diagnostics structural. Browser stderr, thrown messages, endpoint
    # tokens, and native text can contain arbitrary data and are never copied.
    payload = {
        "schema_version": 1,
        "runner": "run_m8_webaudio_ring_smoke.py",
        "case": CASE,
        "scope": SCOPE,
        "stage": stage,
        "failureClass": "m8-webaudio-ring-runner-failure",
        "browserExited": browser is not None and browser.poll() is not None,
        "readyReceived": ready_received,
        "resultStatus": (
            runtime_result.get("status")
            if isinstance(runtime_result, dict)
            and runtime_result.get("status") in {"pass", "fail"}
            else None
        ),
        "resultFailureCode": (
            runtime_result.get("failureCode")
            if isinstance(runtime_result, dict)
            and runtime_result.get("failureCode") in FAILURE_CODES
            else None
        ),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated M8 WebAudio ring feasibility smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm"))
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=45.0)
    args = parser.parse_args()
    if args.timeout < 3.0 or args.timeout > 90.0:
        parser.error("--timeout must be between 3 and 90 seconds")

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics-m8-webaudio"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: M8WebAudioRingServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[object] | None = None
    client: Any | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    runtime_result: dict[str, Any] | None = None
    stage = "prepare"

    try:
        browser_path, _browser_version = find_browser(args.browser)
        token = secrets.token_urlsafe(24)
        ready_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create-server"
        server = create_server(
            "127.0.0.1", 0, out_dir, token, ready_queue, result_queue
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m8-webaudio-server",
            daemon=True,
        )
        server_thread.start()
        url = smoke_url(server, token, args.timeout)
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m8-webaudio-")
        debug_port = unused_loopback_port()
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = [
            "--remote-allow-origins=http://localhost",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
        ]
        stage = "launch-browser"
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + args.timeout
        stage = "connect-devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)
        stage = "wait-host-ready"
        ready = _wait_for_queue(ready_queue, browser, deadline, stage)
        if not _is_ready_payload(ready):
            raise M0Error("M8 WebAudio ready payload is invalid")
        # This is physical DevTools mouse input, not a DOM click()/evaluation or
        # direct Wasm export. The coordinator rejects non-trusted DOM events.
        stage = "trusted-start-click"
        client.dispatch_primary_click(START_BUTTON_X, START_BUTTON_Y)
        stage = "wait-result"
        runtime_result = _wait_for_queue(result_queue, browser, deadline, stage)
        stage = "validate-result"
        validate_result(runtime_result)
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, ValueError):
        if diagnostics_dir is not None:
            write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                browser=browser,
                ready_received=server.ready_received if server is not None else False,
                runtime_result=runtime_result,
            )
        print(f"{SENTINEL}:FAIL stage={stage}", flush=True)
        return 1
    finally:
        if client is not None:
            client.close()
        if browser is not None:
            stop_browser(browser)
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=5)
        if profile is not None:
            profile.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

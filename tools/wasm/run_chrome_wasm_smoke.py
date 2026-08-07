#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the scoped M6 Chrome foundation gate in a real host browser.

This checks the linked single-process Chrome foundation only. Its required
exit code deliberately documents that the real Chrome Views browser lifecycle
has not yet been source-selected; it must never be reported as the full M6 UI
acceptance gate.
"""

from __future__ import annotations

import argparse
from collections import deque
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

from check_m6_chrome_boundary import check_boundary
from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)
from run_content_shell_smoke import manifest_versions


SENTINEL = "CHROMIUM_WASM_M6_CHROME_FOUNDATION"
FOUNDATION_CASE = "chrome_foundation_m6"
FOUNDATION_SCOPE = "foundation-only"
FOUNDATION_EXIT_CODE = 13
FOUNDATION_MARKER = (
    "chrome_wasm M6 foundation initialized, but the source-selected Chrome "
    "Views browser lifecycle is not available yet"
)
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_MAX_RESULT_BYTES = 1024 * 1024


class ChromeM6Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    result_queue: queue.Queue[dict[str, Any]]
    result_token: str
    result_received: bool
    result_lock: threading.Lock


class ChromeM6RequestHandler(BaseHTTPRequestHandler):
    server: ChromeM6Server

    def log_message(self, _format: str, *_args: object) -> None:
        # The runner owns diagnostics and keeps ordinary successful traffic
        # silent so its scoped sentinel remains machine-readable.
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_bytes(
        self,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_bytes(
            HTTPStatus.NOT_FOUND,
            "text/plain; charset=utf-8",
            b"not found\n",
        )

    def _artifact_path(self, requested_name: str) -> Path | None:
        expected_names = {
            f"{self.server.module_name}.js",
            f"{self.server.module_name}.wasm",
        }
        if requested_name not in expected_names:
            return None
        candidate = (self.server.out_dir / requested_name).resolve()
        try:
            candidate.relative_to(self.server.out_dir)
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        return candidate

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in ("/__m6__", "/__m6__/"):
            self._send_bytes(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                self.server.html_bytes,
            )
            return
        if path == "/__m6__/chrome_wasm_host.js":
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js_bytes,
            )
            return
        prefix = "/__m6__/artifacts/"
        if path.startswith(prefix):
            artifact = self._artifact_path(path[len(prefix) :])
            if artifact is None:
                self._not_found()
                return
            content_type = (
                "application/wasm"
                if artifact.suffix == ".wasm"
                else "text/javascript; charset=utf-8"
            )
            self._send_bytes(HTTPStatus.OK, content_type, artifact.read_bytes())
            return
        self._not_found()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        expected = f"/__m6__/result/{self.server.result_token}"
        if path != expected:
            self._not_found()
            return
        content_length = self.headers.get("Content-Length")
        try:
            byte_count = int(content_length) if content_length is not None else -1
        except ValueError:
            byte_count = -1
        if byte_count < 0 or byte_count > _MAX_RESULT_BYTES:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid result size\n",
            )
            return
        payload = _parse_foundation_result_payload(self.rfile.read(byte_count))
        if payload is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid foundation result\n",
            )
            return
        if not _accept_foundation_result(self.server, payload):
            self._send_bytes(
                HTTPStatus.CONFLICT,
                "text/plain; charset=utf-8",
                b"foundation result already received\n",
            )
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def _reject_duplicate_result_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Avoid silently accepting a result whose JSON keys were overwritten."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON result object key")
        result[key] = value
    return result


def _parse_foundation_result_payload(payload: bytes) -> dict[str, Any] | None:
    """Decode the one expected report before it consumes the one-shot slot."""
    try:
        result = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_result_object_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(result, dict)
        or type(result.get("protocol")) is not int
        or result.get("protocol") != 1
        or result.get("case") != FOUNDATION_CASE
        or result.get("scope") != FOUNDATION_SCOPE
    ):
        return None
    return result


def _accept_foundation_result(
    server: ChromeM6Server, result: dict[str, Any]
) -> bool:
    """Atomically enqueue one already-schema-checked foundation result."""
    with server.result_lock:
        if server.result_received:
            return False
        try:
            server.result_queue.put_nowait(result)
        except queue.Full:
            return False
        server.result_received = True
    return True


def create_chrome_m6_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
) -> ChromeM6Server:
    if not _MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    resolved_out_dir = out_dir.resolve()
    if not resolved_out_dir.is_dir():
        raise M0Error(f"Chrome output directory is missing: {resolved_out_dir}")
    html_path = Path(__file__).with_name("host") / "chrome_wasm.html"
    host_js_path = Path(__file__).with_name("host") / "chrome_wasm_host.js"
    server = ChromeM6Server((host, port), ChromeM6RequestHandler)
    server.out_dir = resolved_out_dir
    server.module_name = module_name
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_received = False
    server.result_lock = threading.Lock()
    server.html_bytes = html_path.read_bytes()
    server.host_js_bytes = host_js_path.read_bytes()
    return server


def chrome_m6_url(
    server: ChromeM6Server,
    result_token: str,
    versions: dict[str, str],
    *,
    module_name: str,
    timeout_seconds: float,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "token": result_token,
            "module": module_name,
            "timeoutMs": str(int(timeout_seconds * 1000)),
            "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
        }
    )
    return f"http://{host}:{port}/__m6__/?{query}"


def _exact_json_value_equal(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (
            actual.keys() == expected.keys()
            and all(
                _exact_json_value_equal(actual[key], expected[key])
                for key in expected
            )
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _exact_json_value_equal(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected)
        )
    return actual == expected


def _require_equal(
    result: dict[str, Any], field: str, expected: object
) -> None:
    if not _exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"Chrome foundation result {field} mismatch: expected {expected!r}, "
            f"got {result.get(field)!r}"
        )


def _require_finite_number(value: object, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M0Error(f"Chrome foundation {description} is not numeric")
    numeric = float(value)
    if not numeric == numeric or numeric in (float("inf"), float("-inf")):
        raise M0Error(f"Chrome foundation {description} is not finite")
    return numeric


def validate_chrome_foundation_result(
    result: dict[str, Any], *, expected_versions: dict[str, str]
) -> None:
    for field, expected in {
        "protocol": 1,
        "case": FOUNDATION_CASE,
        "scope": FOUNDATION_SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": FOUNDATION_EXIT_CODE,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "foundationMarkerObserved": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }.items():
        _require_equal(result, field, expected)

    process_exit_code = result.get("processExitCode")
    if process_exit_code is not None and (
        type(process_exit_code) is not int
        or process_exit_code != FOUNDATION_EXIT_CODE
    ):
        raise M0Error("Chrome bridge process exit disagrees with onExit")
    if not _exact_json_value_equal(result.get("versions"), expected_versions):
        raise M0Error("Chrome foundation versions do not match the manifest")

    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        value = result.get(field)
        if not isinstance(value, list) or value:
            raise M0Error(f"Chrome foundation {field} is not empty")
    for field in ("stdout", "stderr"):
        if not isinstance(result.get(field), list):
            raise M0Error(f"Chrome foundation {field} is not a list")
    stderr = "\n".join(str(line) for line in result["stderr"])
    if FOUNDATION_MARKER not in stderr:
        raise M0Error("Chrome foundation stderr is missing its lifecycle marker")

    heartbeat = result.get("heartbeat")
    if not isinstance(heartbeat, dict):
        raise M0Error("Chrome foundation result is missing heartbeat evidence")
    _require_equal(heartbeat, "anchor", "runtime-initialized")
    if _require_finite_number(heartbeat.get("elapsedMs"), "heartbeat elapsedMs") < 100:
        raise M0Error("Chrome foundation heartbeat interval was too short")
    heartbeat_ticks: dict[str, int] = {}
    for field in (
        "timerStartTicks",
        "timerEndTicks",
        "animationFrameStartTicks",
        "animationFrameEndTicks",
    ):
        value = heartbeat.get(field)
        if type(value) is not int or value < 0:
            raise M0Error(f"Chrome foundation heartbeat {field} is not an integer")
        heartbeat_ticks[field] = value
    for field, start, end in (
        ("timerDelta", "timerStartTicks", "timerEndTicks"),
        (
            "animationFrameDelta",
            "animationFrameStartTicks",
            "animationFrameEndTicks",
        ),
    ):
        value = heartbeat.get(field)
        if type(value) is not int or value < 2:
            raise M0Error(f"Chrome foundation heartbeat {field} did not advance")
        if value != heartbeat_ticks[end] - heartbeat_ticks[start]:
            raise M0Error(f"Chrome foundation heartbeat {field} is inconsistent")
    max_timer_gap_ms = _require_finite_number(
        heartbeat.get("maxTimerGapMs"), "heartbeat maxTimerGapMs"
    )
    if max_timer_gap_ms < 0 or max_timer_gap_ms > 250:
        raise M0Error("Chrome foundation heartbeat gap exceeded 250 ms")


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    context: dict[str, object] | None,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    runtime_result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-foundation-m6-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_chrome_wasm_smoke.py",
        "case": FOUNDATION_CASE,
        "scope": FOUNDATION_SCOPE,
        "status": "fail",
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "context": context,
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
        "runtime_result": runtime_result,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the scoped M6 Chrome Wasm foundation smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-chrome-m6")
    )
    parser.add_argument("--module-name", default="chrome_wasm")
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="failure directory (default: OUT_DIR/diagnostics)",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=60.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")

    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / "diagnostics"
    elif not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    if not _MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")

    server: ChromeM6Server | None = None
    server_thread: threading.Thread | None = None
    server_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    stage = "check_artifacts"

    try:
        stage = "check_boundary"
        check_boundary(out_dir)
        for suffix in (".js", ".wasm"):
            artifact = out_dir / f"{args.module_name}{suffix}"
            if not artifact.is_file():
                raise M0Error(f"Chrome foundation artifact is missing: {artifact}")
        stage = "load_manifest"
        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        stage = "print_context"
        context = print_context(
            "run_chrome_wasm_smoke.py",
            manifest,
            case=FOUNDATION_CASE,
            scope=FOUNDATION_SCOPE,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER "
            + json.dumps({"browser_version": browser_version}, sort_keys=True),
            flush=True,
        )
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "create_server"
        server = create_chrome_m6_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m6-chrome-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        url = chrome_m6_url(
            server,
            token,
            versions,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )

        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m6-")
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command.insert(1, "--enable-logging=stderr")
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m6-chrome-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()

        stage = "wait_for_result"
        deadline = time.monotonic() + args.timeout
        while result is None:
            if browser.poll() is not None:
                raise M0Error(
                    "host browser exited before the M6 foundation result "
                    f"(status {browser.returncode}): " + "\n".join(browser_stderr)
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise M0Error("M6 Chrome foundation timeout: " + "\n".join(browser_stderr))
            try:
                result = result_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue

        stage = "validate_result"
        validate_chrome_foundation_result(result, expected_versions=versions)
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            diagnostic_path = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=exc,
                context=context,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                runtime_result=result,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic_path)}, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
                flush=True,
            )
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if profile is not None:
            profile.cleanup()
        if server is not None:
            if server_started:
                server.shutdown()
            server.server_close()
        if server_started and server_thread is not None:
            server_thread.join(timeout=3)


if __name__ == "__main__":
    sys.exit(main())

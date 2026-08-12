#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the Blob-backed M8 worker messaging baseline through Content Shell.

This uses a data: page and Blob worker deliberately. It proves the bounded
startup, transfer, heartbeat, termination, and shell-shutdown path only; it
does not cover worker script fetch, CSP/CORS, origin policy, or scheduling
fairness under Chromium's pthread load.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m3_content_server import (
    M8_DEDICATED_WORKER_CASE,
    create_m3_server,
    m8_dedicated_worker_smoke_url,
)
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)


SENTINEL = "CHROMIUM_WASM_M8_DEDICATED_WORKER"


def manifest_versions(
    manifest: dict[str, Any], port_revision: str
) -> dict[str, str]:
    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
            "port": port_revision,
        }
    except (KeyError, TypeError) as exc:
        raise M0Error("manifest is missing an M8 version field") from exc
    if not all(
        isinstance(value, str) and value for value in versions.values()
    ):
        raise M0Error("manifest contains an invalid M8 version field")
    return versions


def validate_result(
    result: dict[str, Any], expected_versions: dict[str, str]
) -> dict[str, Any]:
    if result.get("protocol") != 1:
        raise M0Error("M8 worker result has an unexpected protocol")
    if result.get("case") != M8_DEDICATED_WORKER_CASE:
        raise M0Error("M8 worker result has an unexpected case")
    if result.get("status") != "pass":
        raise M0Error(
            "M8 dedicated worker reported failure: "
            + json.dumps(result, sort_keys=True)
        )
    if result.get("versions") != expected_versions:
        raise M0Error("M8 worker result version identity does not match")
    if result.get("failedChecks") != []:
        raise M0Error("M8 worker result reported failed checks")
    if result.get("crossOriginIsolated") is not True:
        raise M0Error("M8 worker host is not cross-origin isolated")
    if result.get("sharedArrayBuffer") is not True:
        raise M0Error("M8 worker host has no SharedArrayBuffer")
    if result.get("canvasFocused") is not True:
        raise M0Error("M8 worker host canvas lost focus")

    readiness = result.get("readiness")
    if not isinstance(readiness, dict):
        raise M0Error("M8 worker result lacks readiness diagnostics")
    if readiness.get("navigationCommitted") is not True:
        raise M0Error("M8 worker fixture did not commit")
    probe = readiness.get("pageProbe")
    if not isinstance(probe, dict):
        raise M0Error("M8 worker result lacks its page probe")
    expected_probe = {
        "protocol": 1,
        "fixture": "chromium-wasm-m8-dedicated-worker-v1",
        "workerSource": "blob-data-url",
        "ready": True,
        "workerCreated": True,
        "mainTransferDetached": True,
        "receivedSequence": 37,
        "receivedPayload": "worker-message:reply",
        "receivedByteLength": 4,
        "receivedBytes": [5, 8, 15, 16],
        "workerBusyStarted": True,
        "terminationRequested": True,
        "postTerminationHeartbeatCount": 0,
        "workerTerminated": True,
        "failure": None,
    }
    for key, expected in expected_probe.items():
        if probe.get(key) != expected:
            raise M0Error(
                f"M8 worker probe field {key!r} does not match {expected!r}"
            )
    for key in (
        "workerTimerTicks",
        "mainTimerTicks",
        "workerHeartbeatCount",
        "workerHeartbeatsBeforeBusy",
        "mainTimerTicksDuringBusy",
        "heartbeatsAtTermination",
        "workerBusyIterations",
    ):
        value = probe.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise M0Error(f"M8 worker probe has invalid {key}")
    if probe["workerTimerTicks"] < 2:
        raise M0Error("M8 worker did not establish two heartbeats")
    if probe["workerHeartbeatCount"] < 2:
        raise M0Error("M8 worker heartbeat count is incomplete")
    if probe["workerHeartbeatsBeforeBusy"] < 2:
        raise M0Error("M8 worker began CPU work before its heartbeats")
    if probe["mainTimerTicksDuringBusy"] < 1:
        raise M0Error("M8 page timer did not run during worker CPU work")
    if probe["heartbeatsAtTermination"] < 2:
        raise M0Error("M8 worker terminated before its heartbeats")
    if probe.get("workerBusyStarted") is not True:
        raise M0Error("M8 worker did not start bounded CPU work")
    busy_duration = probe.get("workerBusyDurationMs")
    if (
        not isinstance(busy_duration, (int, float))
        or isinstance(busy_duration, bool)
        or busy_duration < 65
    ):
        raise M0Error("M8 worker did not report bounded CPU work")
    if probe.get("terminationRequested") is not True:
        raise M0Error("M8 worker termination was not requested")
    if probe.get("postTerminationHeartbeatCount") != 0:
        raise M0Error("M8 worker emitted a heartbeat after termination")

    shutdown = result.get("shutdown")
    if not isinstance(shutdown, dict):
        raise M0Error("M8 worker result lacks shutdown diagnostics")
    if (
        shutdown.get("ok") is not True
        or shutdown.get("complete") is not True
        or shutdown.get("exitCode") != 0
        or shutdown.get("runtimeExitCode") != 0
    ):
        raise M0Error("M8 worker Content Shell shutdown was not clean")
    return probe


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
    result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_path = diagnostics_dir / "m8-dedicated-worker-failure.json"
    diagnostic = {
        "schema_version": 1,
        "runner": "run_m8_dedicated_worker_smoke.py",
        "case": M8_DEDICATED_WORKER_CASE,
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
        "runtime_result": result,
    }
    temporary = diagnostic_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(diagnostic_path)
    return diagnostic_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a page dedicated worker inside Wasm Content Shell."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default="content_shell_wasm")
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="failure directory (default: OUT_DIR/diagnostics-m8-worker)",
    )
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument("--verbose-server", action="store_true")
    args = parser.parse_args()

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / "diagnostics-m8-worker"
    elif not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    server = None
    server_thread = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    context: dict[str, object] | None = None
    result: dict[str, Any] | None = None
    stage = "load_manifest"

    try:
        if not (out_dir / f"{args.module_name}.js").is_file() or not (
            out_dir / f"{args.module_name}.wasm"
        ).is_file():
            raise M0Error("M8 worker Content Shell artifacts are missing")

        manifest = load_manifest()
        versions = manifest_versions(manifest, checked_output(["git", "rev-parse", "HEAD"]))
        context = print_context(
            "run_m8_dedicated_worker_smoke.py",
            manifest,
            case=M8_DEDICATED_WORKER_CASE,
            gn_args=manifest.get(
                "m3_content_gn_args", manifest.get("gn_args")
            ),
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
        server = create_m3_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
            verbose=args.verbose_server,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m8-dedicated-worker-server",
            daemon=True,
        )
        server_thread.start()
        url = m8_dedicated_worker_smoke_url(
            server,
            token,
            versions,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )

        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m8-worker-")
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
            name="chromium-wasm-m8-dedicated-worker-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()

        stage = "wait_for_result"
        deadline = time.monotonic() + args.timeout
        while result is None:
            if browser.poll() is not None:
                raise M0Error(
                    "host browser exited before the M8 worker result "
                    f"(status {browser.returncode}): "
                    + "\n".join(browser_stderr)
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise M0Error(
                    "M8 dedicated worker browser timeout: "
                    + "\n".join(browser_stderr)
                )
            try:
                result = result_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue

        stage = "validate_runtime_contract"
        probe = validate_result(result, versions)
        print(
            f"{SENTINEL}:PASS "
            + json.dumps(
                {
                    "main_timer_ticks": probe["mainTimerTicks"],
                    "worker_timer_ticks": probe["workerTimerTicks"],
                    "transferred_bytes": probe["receivedBytes"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        path = write_failure_diagnostics(
            diagnostics_dir,
            stage=stage,
            error=exc,
            context=context,
            browser_path=browser_path,
            browser_version=browser_version,
            browser=browser,
            browser_stderr=browser_stderr,
            result=result,
        )
        print(f"{SENTINEL}:FAIL diagnostics={path}: {exc}", file=sys.stderr)
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=2)
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=2)
        if profile is not None:
            profile.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

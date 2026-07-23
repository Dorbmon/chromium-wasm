#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
from collections import deque
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, TextIO

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from serve import SMOKE_CASES, create_server, smoke_case, smoke_url


def fail_for_case(case_name: str, message: str) -> int:
    prefix = smoke_case(case_name).sentinel_prefix
    print(f"{prefix}:FAIL reason={message}", file=sys.stderr, flush=True)
    return 1


def browser_version(path: Path) -> tuple[tuple[int, ...], str] | None:
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    output = (completed.stdout or completed.stderr).strip()
    match = re.search(r"(\d+(?:\.\d+)+)", output)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split(".")), output


def find_browser(explicit: Path | None) -> tuple[Path, str]:
    def require_browser(candidate: Path, source: str) -> tuple[Path, str]:
        resolved = candidate.expanduser().resolve()
        if not resolved.is_file():
            raise M0Error(f"{source} browser does not exist")
        version = browser_version(resolved)
        if version is None:
            raise M0Error(f"{source} browser is not executable")
        return resolved, version[1]

    if explicit is not None:
        return require_browser(explicit, "--browser")
    for environment_name in ("CHROMIUM_WASM_BROWSER", "CHROME_PATH"):
        if os.environ.get(environment_name):
            return require_browser(
                Path(os.environ[environment_name]), environment_name
            )
    for executable_name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        executable = shutil.which(executable_name)
        if executable:
            return require_browser(Path(executable), "PATH")

    candidates = list(
        Path.home().glob(
            ".cache/ms-playwright/chromium-*/chrome-linux*/chrome"
        )
    )

    usable: list[tuple[tuple[int, ...], Path, str]] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        version = browser_version(resolved)
        if version is not None:
            usable.append((version[0], resolved, version[1]))
    if not usable:
        raise M0Error(
            "no headless Chromium executable found; pass --browser or set "
            "CHROMIUM_WASM_BROWSER"
        )
    _, path, version_output = max(usable, key=lambda entry: entry[0])
    return path, version_output


def drain_stream(stream: TextIO, destination: deque[str]) -> None:
    for line in stream:
        destination.append(line.rstrip())


def stop_browser(browser: subprocess.Popen[str]) -> None:
    if browser.poll() is not None:
        return
    try:
        os.killpg(browser.pid, signal.SIGTERM)
        browser.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if browser.poll() is None:
            try:
                os.killpg(browser.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            try:
                browser.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass


def browser_command(
    browser: Path,
    profile: str,
    url: str,
    *,
    no_sandbox: bool,
) -> list[str]:
    command = [str(browser), "--headless=new"]
    if no_sandbox:
        command.append("--no-sandbox")
    command.extend(
        [
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            url,
        ]
    )
    return command


def validate_result(
    result: dict[str, Any], smoke_case_name: str = "hello"
) -> None:
    selected_case = smoke_case(smoke_case_name)
    expected = {
        "protocol": 1,
        "case": smoke_case_name,
        "status": "pass",
        "exitCode": 0,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        if result.get(field) != expected_value:
            raise M0Error(
                f"browser result {field} mismatch: "
                f"expected {expected_value}, got {result.get(field)}"
            )
    heartbeat = result.get("heartbeat")
    if not isinstance(heartbeat, dict):
        raise M0Error("browser result is missing heartbeat evidence")
    delta = heartbeat.get("delta")
    if (
        not isinstance(delta, (int, float))
        or not math.isfinite(delta)
        or delta < 3
    ):
        raise M0Error("browser main-thread heartbeat did not advance")
    elapsed_ms = heartbeat.get("elapsedMs")
    if (
        not isinstance(elapsed_ms, (int, float))
        or not math.isfinite(elapsed_ms)
        or elapsed_ms < 200
    ):
        raise M0Error("browser runtime interval was shorter than 200 ms")

    stdout = result.get("stdout")
    stderr = result.get("stderr")
    if not isinstance(stdout, list) or not isinstance(stderr, list):
        raise M0Error("browser did not return separate stdout/stderr arrays")
    stdout_text = "\n".join(str(line) for line in stdout)
    stderr_text = "\n".join(str(line) for line in stderr)
    for sentinel in selected_case.required_stdout:
        if sentinel not in stdout_text:
            raise M0Error(f"browser stdout is missing {sentinel}")
    for sentinel in selected_case.required_stderr:
        if sentinel not in stderr_text:
            raise M0Error(f"browser stderr is missing {sentinel}")
    if selected_case.require_separate_streams and (
        any(
            sentinel in stdout_text
            for sentinel in selected_case.required_stderr
        )
        or "CHROMIUM_WASM_M0:STDOUT" in stderr_text
    ):
        raise M0Error("browser stdout and stderr were not captured separately")
    failure_sentinel = f"{selected_case.sentinel_prefix}:FAIL"
    if failure_sentinel in stdout_text + stderr_text:
        raise M0Error("browser runtime emitted a failure sentinel")
    runtime_start = f"{selected_case.sentinel_prefix}:RUNTIME_START"
    runtime_end = f"{selected_case.sentinel_prefix}:RUNTIME_END"
    pass_sentinel = f"{selected_case.sentinel_prefix}:PASS"
    if not (
        stdout_text.index(runtime_start)
        < stdout_text.index(runtime_end)
        < stdout_text.index(pass_sentinel)
    ):
        raise M0Error("browser runtime sentinels are out of order")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a Chromium Wasm smoke in a real headless browser."
    )
    parser.add_argument("--case", choices=tuple(SMOKE_CASES), required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm"))
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=60.0)
    args = parser.parse_args()

    server = None
    server_thread = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    try:
        manifest = load_manifest()
        browser_path, version_output = find_browser(args.browser)
        out_dir = args.out_dir
        if not out_dir.is_absolute():
            out_dir = REPO_ROOT / out_dir
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        server = create_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            smoke_case_name=args.case,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m0-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        port_commit = checked_output(["git", "rev-parse", "HEAD"])
        url = smoke_url(
            server,
            token,
            manifest,
            port_commit,
            timeout_seconds=max(1.0, args.timeout - 1.0),
            smoke_case_name=args.case,
        )
        print_context(
            "run_browser_smoke.py",
            manifest,
            browser_version=version_output,
            case=args.case,
            host_browser_sandbox=not args.no_sandbox,
        )

        browser_stderr: deque[str] = deque(maxlen=200)
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m0-")
        browser = subprocess.Popen(
            browser_command(
                browser_path,
                profile.name,
                url,
                no_sandbox=args.no_sandbox,
            ),
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
            name="chromium-wasm-m0-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()

        deadline = time.monotonic() + args.timeout
        result: dict[str, Any] | None = None
        while result is None:
            if browser.poll() is not None:
                tail = "\n".join(browser_stderr)
                raise M0Error(
                    f"browser exited before reporting a result "
                    f"(status {browser.returncode}): {tail}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                tail = "\n".join(browser_stderr)
                raise M0Error(f"browser smoke timeout: {tail}")
            try:
                result = result_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue

        validate_result(result, args.case)
        selected_case = smoke_case(args.case)
        print(
            f"{selected_case.sentinel_prefix}:BROWSER_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{selected_case.sentinel_prefix}_BROWSER:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        return fail_for_case(args.case, str(exc))
    finally:
        if browser is not None:
            stop_browser(browser)
        if profile is not None:
            profile.cleanup()
        if server is not None:
            if server_thread_started:
                server.shutdown()
            server.server_close()
        if server_thread_started and server_thread is not None:
            server_thread.join(timeout=3)


if __name__ == "__main__":
    sys.exit(main())

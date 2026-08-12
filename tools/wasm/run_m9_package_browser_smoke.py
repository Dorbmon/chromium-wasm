#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Boot a staged pre-release package in a real browser.

The package intentionally contains ``chromium-wasm.js`` rather than the input
target's ``chrome_wasm.js`` name. This smoke serves *only* the staged names;
therefore a successful frame proves the release host's Blob-backed Emscripten
pthread loader route and renamed Wasm locateFile mapping. It is not an M6 UI,
M7 persistence, M8 compatibility, or M9 release acceptance test.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any

if __package__:
    from .m0_common import M0Error, REPO_ROOT, parse_timeout
    from .m4_cdp import unused_loopback_port, wait_for_page_client
    from .run_browser_smoke import (
        browser_command,
        drain_stream,
        find_browser,
        stop_browser,
    )
    from .run_m9_package_smoke import create_package_smoke_server
else:
    from m0_common import M0Error, REPO_ROOT, parse_timeout
    from m4_cdp import unused_loopback_port, wait_for_page_client
    from run_browser_smoke import (
        browser_command,
        drain_stream,
        find_browser,
        stop_browser,
    )
    from run_m9_package_smoke import create_package_smoke_server


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE"
SCOPE = "real-browser-package-loader-pthread-bootstrap-and-host-shutdown-only"
RELEASE_STATUS = "pre_m7_m8_not_releasable"

_STATUS_EXPRESSION = r"""
(() => {
  const root = document.querySelector("#chrome-root");
  const status = document.querySelector("#chrome-status");
  const shutdown = document.querySelector("#shutdown");
  const versions = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(status instanceof HTMLElement) ||
      !(shutdown instanceof HTMLButtonElement) ||
      !(versions instanceof HTMLElement)) {
    // CDP can list a target while its initial document is still being
    // replaced by the staged package index. Treat that transient state as
    // pending rather than attaching a false permanent page failure to the
    // correct URL before its DOM is installed.
    return {
      documentReadyState: document.readyState,
      pending: true,
      statusText: "package host elements are not installed yet",
    };
  }
  let payload = null;
  try {
    payload = JSON.parse(status.textContent);
  } catch (_) {
    return {
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      pageState: root.dataset.state,
      pending: true,
      statusText: status.textContent.slice(0, 256),
    };
  }
  return {
    crossOriginIsolated: globalThis.crossOriginIsolated === true,
    framesPresented: payload.framesPresented,
    pageState: root.dataset.state,
    readiness: payload.readiness,
    records: payload.records,
    releaseStatus: payload.releaseStatus,
    runtimeInitialized: payload.runtimeInitialized,
    processExitCode: payload.processExitCode,
    shutdownDisabled: shutdown.disabled,
    shutdownRequested: payload.shutdownRequested,
    displayedVersions: versions.textContent,
  };
})()
"""


def _status(client: Any) -> dict[str, Any]:
    value = client.evaluate(_STATUS_EXPRESSION)
    if not isinstance(value, dict):
        raise M0Error("package host status is not an object")
    return value


def _fatal_record(status: dict[str, Any]) -> str | None:
    records = status.get("records")
    if not isinstance(records, list):
        return None
    for record in records:
        if isinstance(record, dict) and record.get("kind") == "fatal":
            return str(record.get("value", "unknown host fatal"))
    return None


def _is_ready(status: dict[str, Any]) -> bool:
    readiness = status.get("readiness")
    displayed_versions = status.get("displayedVersions")
    return (
        status.get("crossOriginIsolated") is True
        and status.get("releaseStatus") == RELEASE_STATUS
        and status.get("runtimeInitialized") is True
        and type(status.get("framesPresented")) is int
        and status["framesPresented"] >= 1
        and isinstance(readiness, dict)
        and readiness.get("surfaceReady") is True
        and status.get("pageState") == "running"
        and isinstance(displayed_versions, str)
        and "staging checkout" in displayed_versions
        and "artifact source provenance" in displayed_versions
        and "unverified" in displayed_versions
    )


def _wait_for_status(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    predicate: Any,
    description: str,
) -> dict[str, Any]:
    last_status: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                f"host browser exited while {description} (status "
                f"{browser.returncode}): " + "\n".join(browser_stderr)
            )
        status = _status(client)
        last_status = status
        if status.get("pageError"):
            raise M0Error(f"package host page error: {status['pageError']}")
        fatal = _fatal_record(status)
        if fatal is not None:
            raise M0Error(f"package host reported fatal: {fatal}")
        if predicate(status):
            return status
        time.sleep(0.05)
    raise M0Error(
        f"timed out while {description}: "
        + json.dumps(last_status, sort_keys=True, default=str)
    )


def run_package_browser_smoke(
    *,
    dist_dir: Path,
    browser_argument: Path | None,
    no_sandbox: bool,
    timeout: float,
) -> dict[str, object]:
    server = None
    server_thread = None
    browser: subprocess.Popen[str] | None = None
    stderr_thread = None
    browser_stderr: deque[str] = deque(maxlen=300)
    client: Any = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    try:
        browser_path, browser_version = find_browser(browser_argument)
        server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-package-browser-server",
            daemon=True,
        )
        server_thread.start()
        host, port = server.server_address[:2]
        url = f"http://{host}:{port}/"
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-package-")
        debug_port = unused_loopback_port()
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=no_sandbox
        )
        command[1:1] = [
            "--enable-logging=stderr",
            "--remote-allow-origins=http://localhost",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
        ]
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
            name="chromium-wasm-m9-package-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        deadline = time.monotonic() + timeout
        client = wait_for_page_client(debug_port, url, deadline)
        ready = _wait_for_status(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            predicate=_is_ready,
            description="waiting for a real package frame",
        )

        client.evaluate('document.querySelector("#shutdown").click(); true')
        clean_shutdown = _wait_for_status(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            predicate=lambda status: (
                status.get("shutdownRequested") is True
                and status.get("shutdownDisabled") is True
                and status.get("processExitCode") == 0
            ),
            description="waiting for clean fixed package-host shutdown",
        )
        return {
            "browser_version": browser_version,
            "frames_presented": ready["framesPresented"],
            "process_exit_code": clean_shutdown["processExitCode"],
            "release_status": ready["releaseStatus"],
            "scope": SCOPE,
            "shutdown_disabled": clean_shutdown["shutdownDisabled"],
            "shutdown_requested": clean_shutdown["shutdownRequested"],
        }
    finally:
        if client is not None:
            client.close()
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=5)
        if profile is not None:
            profile.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Boot a staged pre-release Chromium Wasm package in Chrome."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 10:
        parser.error("--timeout must allow package startup and shutdown")
    try:
        result = run_package_browser_smoke(
            dist_dir=args.dist_dir,
            browser_argument=args.browser,
            no_sandbox=args.no_sandbox,
            timeout=args.timeout,
        )
        print(
            f"{SENTINEL}:BROWSER_SMOKE_PASS "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    except (M0Error, OSError, TypeError, ValueError) as exc:
        print(f"{SENTINEL}:BROWSER_SMOKE_FAIL reason={exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

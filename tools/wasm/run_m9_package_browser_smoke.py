#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Boot a staged pre-release package in a real browser.

The package intentionally contains ``chromium-wasm.js`` rather than the input
target's ``chrome_wasm.js`` name. This smoke serves *only* the staged names;
therefore a successful frame proves the release host's Blob-backed Emscripten
pthread loader route and renamed Wasm locateFile mapping.  Its optional second
epoch first performs an orderly host shutdown, then navigates the *outer*
document and requires a fresh packaged loader lifetime in the same host
browser.  It is not an M6 UI, M7 persistence, M8 compatibility, or M9 release
acceptance test.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if __package__:
    from . import package as package_tool
    from .m0_common import M0Error, REPO_ROOT, parse_timeout
    from .m4_cdp import unused_loopback_port, wait_for_page_client
    from .run_browser_smoke import (
        browser_command,
        find_browser,
    )
    from .m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from .m9_server_cleanup import shutdown_server_bounded
    from .run_m9_package_smoke import create_package_smoke_server
else:
    import package as package_tool

    from m0_common import M0Error, REPO_ROOT, parse_timeout
    from m4_cdp import unused_loopback_port, wait_for_page_client
    from run_browser_smoke import (
        browser_command,
        find_browser,
    )
    from m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from m9_server_cleanup import shutdown_server_bounded
    from run_m9_package_smoke import create_package_smoke_server


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE"
SCOPE = "real-browser-package-loader-pthread-bootstrap-and-host-shutdown-only"
OUTER_DOCUMENT_RESTART_SCOPE = (
    "real-browser-package-two-outer-document-epochs-loader-pthread-bootstrap-"
    "and-host-shutdown-only"
)
RELEASE_STATUS = package_tool.RELEASE_STATUS
EPOCH_QUERY_KEY = "m9_package_epoch"

_STATUS_EXPRESSION = r"""
(() => {
  const navigation = performance.getEntriesByType("navigation")[0];
  const documentIdentity = {
    href: location.href,
    navigation: navigation && typeof navigation === "object" ? {
      name: navigation.name,
      startTime: navigation.startTime,
      type: navigation.type,
    } : null,
    timeOrigin: performance.timeOrigin,
  };
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
      documentIdentity,
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
      documentIdentity,
      pageState: root.dataset.state,
      pending: true,
      statusText: status.textContent.slice(0, 256),
    };
  }
  return {
    crossOriginIsolated: globalThis.crossOriginIsolated === true,
    documentIdentity,
    framesPresented: payload.framesPresented,
    pageState: root.dataset.state,
    packageMetadata: payload.packageMetadata,
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


def _runtime_metadata_from_server_snapshot(server: Any) -> dict[str, object]:
    try:
        artifacts = server.snapshot.artifacts
        version_bytes = artifacts["VERSION.json"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise M0Error("package server is missing its immutable VERSION.json") from exc
    try:
        package_tool.verify_release_snapshot(artifacts)
        return package_tool.package_runtime_status_metadata(version_bytes)
    except package_tool.PackageError as exc:
        raise M0Error(f"package server snapshot metadata is invalid: {exc}") from exc


def _exact_json_value_equal(actual: object, expected: object) -> bool:
    """Compare JSON-shaped values without Python bool/int coercion."""

    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        if set(actual) != set(expected):
            return False
        return all(
            _exact_json_value_equal(actual[key], expected[key])
            for key in actual
        )
    if type(actual) is list:
        return len(actual) == len(expected) and all(
            _exact_json_value_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def _require_runtime_metadata(
    value: object, expected: dict[str, object]
) -> None:
    """Require the ready host's bounded metadata to equal the server snapshot."""
    if not _exact_json_value_equal(value, expected):
        raise M0Error(
            "package host runtime metadata does not match immutable "
            "VERSION.json snapshot"
        )


def _status(client: Any) -> dict[str, Any]:
    value = client.evaluate(_STATUS_EXPRESSION)
    if not isinstance(value, dict):
        raise M0Error("package host status is not an object")
    return value


def _make_epoch_url(url: str, epoch: str) -> str:
    """Add one exact, single-use document epoch to a package URL."""

    if not isinstance(epoch, str) or not epoch:
        raise M0Error("package document epoch is invalid")
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.netloc or parsed.fragment:
        raise M0Error("package document URL is invalid")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == EPOCH_QUERY_KEY for key, _value in pairs):
        raise M0Error("package document URL already contains an epoch")
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            urlencode([*pairs, (EPOCH_QUERY_KEY, epoch)]),
            "",
        )
    )


def _require_document_identity(
    status: dict[str, Any],
    *,
    expected_url: str,
    expected_epoch: str,
    prior_time_origin: float | None = None,
) -> float:
    """Bind a ready package host to one exact outer-document lifetime.

    A Page target URL alone can describe a navigation in progress or an old
    attached document.  Require the exact epoch-bearing URL from both the
    document and Navigation Timing, then retain its independent time origin.
    The caller compares the origin across outer-document lifetimes.
    """

    identity = status.get("documentIdentity")
    if not isinstance(identity, dict):
        raise M0Error("package host document identity is missing")
    observed_url = identity.get("href")
    if not isinstance(observed_url, str) or observed_url != expected_url:
        raise M0Error("package host document URL does not match its epoch")
    parsed = urlsplit(observed_url)
    epoch_values = [
        value
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key == EPOCH_QUERY_KEY
    ]
    if epoch_values != [expected_epoch]:
        raise M0Error("package host document epoch is invalid")

    navigation = identity.get("navigation")
    if not isinstance(navigation, dict):
        raise M0Error("package host navigation timing identity is missing")
    if navigation.get("name") != expected_url or navigation.get("type") != "navigate":
        raise M0Error("package host navigation timing URL does not match its epoch")
    start_time = navigation.get("startTime")
    if isinstance(start_time, bool) or not isinstance(start_time, (int, float)):
        raise M0Error("package host navigation timing start is invalid")
    if not math.isfinite(float(start_time)) or float(start_time) < 0:
        raise M0Error("package host navigation timing start is invalid")

    time_origin = identity.get("timeOrigin")
    if isinstance(time_origin, bool) or not isinstance(time_origin, (int, float)):
        raise M0Error("package host document time origin is invalid")
    result = float(time_origin)
    if not math.isfinite(result) or result <= 0:
        raise M0Error("package host document time origin is invalid")
    if prior_time_origin is not None and result == prior_time_origin:
        raise M0Error("package host outer-document time origin did not change")
    return result


def _require_ready_package_document(
    status: dict[str, Any],
    *,
    expected_url: str,
    expected_epoch: str,
    expected_package_metadata: dict[str, object],
    prior_time_origin: float | None = None,
) -> float:
    """Bind one ready document to both its URL epoch and served metadata."""

    _require_runtime_metadata(status.get("packageMetadata"), expected_package_metadata)
    return _require_document_identity(
        status,
        expected_url=expected_url,
        expected_epoch=expected_epoch,
        prior_time_origin=prior_time_origin,
    )


def _is_clean_shutdown(status: dict[str, Any]) -> bool:
    exit_code = status.get("processExitCode")
    return (
        status.get("shutdownRequested") is True
        and status.get("shutdownDisabled") is True
        and type(exit_code) is int
        and exit_code == 0
    )


def _require_clean_shutdown(status: dict[str, Any], description: str) -> None:
    if not _is_clean_shutdown(status):
        raise M0Error(f"{description} did not complete with process exit code 0")


def _restart_after_clean_shutdown(
    *,
    client: Any,
    clean_shutdown: dict[str, Any],
    restart_url: str,
    debug_port: int,
    deadline: float,
) -> Any:
    """Navigate only after a verified first host shutdown and reattach CDP."""

    _require_clean_shutdown(clean_shutdown, "first fixed package-host shutdown")
    try:
        navigation = client.call("Page.navigate", {"url": restart_url})
        if not isinstance(navigation.get("frameId"), str) or not navigation["frameId"]:
            raise M0Error("Page.navigate did not return a frame identity")
    finally:
        # A navigation invalidates the first document's observation channel.
        # Always close it before asking DevTools for the exact fresh target.
        client.close()
    return wait_for_page_client(debug_port, restart_url, deadline)


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
        and (
            "unverified" in displayed_versions
            or "local_clean_build_attested" in displayed_versions
        )
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


def _wait_for_ready_package_document(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    expected_url: str,
    expected_epoch: str,
    expected_package_metadata: dict[str, object],
    prior_time_origin: float | None,
    description: str,
) -> tuple[dict[str, Any], float]:
    ready = _wait_for_status(
        client=client,
        browser=browser,
        browser_stderr=browser_stderr,
        deadline=deadline,
        predicate=_is_ready,
        description=description,
    )
    return (
        ready,
        _require_ready_package_document(
            ready,
            expected_url=expected_url,
            expected_epoch=expected_epoch,
            expected_package_metadata=expected_package_metadata,
            prior_time_origin=prior_time_origin,
        ),
    )


def _request_clean_shutdown(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    description: str,
) -> dict[str, Any]:
    client.evaluate('document.querySelector("#shutdown").click(); true')
    clean_shutdown = _wait_for_status(
        client=client,
        browser=browser,
        browser_stderr=browser_stderr,
        deadline=deadline,
        predicate=_is_clean_shutdown,
        description=description,
    )
    _require_clean_shutdown(clean_shutdown, description)
    return clean_shutdown


def _epoch_result(
    ready: dict[str, Any], clean_shutdown: dict[str, Any]
) -> dict[str, object]:
    _require_clean_shutdown(clean_shutdown, "package-host shutdown")
    return {
        "frames_presented": ready["framesPresented"],
        "process_exit_code": clean_shutdown["processExitCode"],
        "shutdown_disabled": clean_shutdown["shutdownDisabled"],
        "shutdown_requested": clean_shutdown["shutdownRequested"],
    }


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    """Runs one cleanup action without preventing the remaining cleanup."""

    try:
        action()
    except BaseException as exc:
        if cleanup_error is None:
            return exc
    return cleanup_error


def _join_package_browser_server(thread: threading.Thread) -> None:
    """Joins a started package server and rejects an incomplete teardown."""

    thread.join(timeout=5)
    if thread.is_alive():
        raise M0Error("M9 package browser server did not stop")


def run_package_browser_smoke(
    *,
    dist_dir: Path,
    browser_argument: Path | None,
    no_sandbox: bool,
    timeout: float,
    outer_document_restart: bool = False,
) -> dict[str, object]:
    server = None
    server_thread = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    stderr_reader: BrowserStderrReader | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    client: Any = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    primary_error: BaseException | None = None
    try:
        browser_path, browser_version = find_browser(browser_argument)
        server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-package-browser-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        expected_package_metadata = _runtime_metadata_from_server_snapshot(server)
        host, port = server.server_address[:2]
        package_url = f"http://{host}:{port}/"
        first_epoch = secrets.token_urlsafe(18)
        first_url = _make_epoch_url(package_url, first_epoch)
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-package-")
        debug_port = unused_loopback_port()
        command = browser_command(
            browser_path, profile.name, first_url, no_sandbox=no_sandbox
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
        stderr_reader = BrowserStderrReader(
            browser.stderr,
            browser_stderr,
            name="chromium-wasm-m9-package-browser-stderr",
            thread_factory=threading.Thread,
        )
        stderr_reader.start()
        deadline = time.monotonic() + timeout
        client = wait_for_page_client(debug_port, first_url, deadline)
        first_ready, first_time_origin = _wait_for_ready_package_document(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_url=first_url,
            expected_epoch=first_epoch,
            expected_package_metadata=expected_package_metadata,
            prior_time_origin=None,
            description="waiting for the first real package frame",
        )
        first_shutdown = _request_clean_shutdown(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            description="waiting for the first clean fixed package-host shutdown",
        )
        first_result = _epoch_result(first_ready, first_shutdown)
        if not outer_document_restart:
            return {
                "browser_version": browser_version,
                "frames_presented": first_result["frames_presented"],
                "process_exit_code": first_result["process_exit_code"],
                "release_status": first_ready["releaseStatus"],
                "scope": SCOPE,
                "served_version_json_sha256": expected_package_metadata[
                    "versionJsonSha256"
                ],
                "shutdown_disabled": first_result["shutdown_disabled"],
                "shutdown_requested": first_result["shutdown_requested"],
            }

        second_epoch = secrets.token_urlsafe(18)
        if second_epoch == first_epoch:
            raise M0Error("package restart document epoch was reused")
        second_url = _make_epoch_url(package_url, second_epoch)
        client = _restart_after_clean_shutdown(
            client=client,
            clean_shutdown=first_shutdown,
            restart_url=second_url,
            debug_port=debug_port,
            deadline=deadline,
        )
        second_ready, _second_time_origin = _wait_for_ready_package_document(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_url=second_url,
            expected_epoch=second_epoch,
            expected_package_metadata=expected_package_metadata,
            prior_time_origin=first_time_origin,
            description="waiting for the fresh outer-document package frame",
        )
        second_shutdown = _request_clean_shutdown(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            description="waiting for the second clean fixed package-host shutdown",
        )
        second_result = _epoch_result(second_ready, second_shutdown)
        return {
            "browser_version": browser_version,
            "epochs": [first_result, second_result],
            "outer_document_restart": True,
            "release_status": first_ready["releaseStatus"],
            "scope": OUTER_DOCUMENT_RESTART_SCOPE,
            "served_version_json_sha256": expected_package_metadata[
                "versionJsonSha256"
            ],
        }
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        if client is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, client.close)
        if browser is not None and stderr_reader is not None and stderr_reader.started:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: stop_browser_group(browser, stderr_reader)
            )
        elif browser is not None:
            # This can only be a startup-failure path.  It still needs to
            # terminate the dedicated session, not merely the browser leader.
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: abort_browser_group(browser, stderr_reader)
            )
        if server is not None:
            if server_thread_started:
                cleanup_error = _run_cleanup_action(
                    cleanup_error,
                    lambda: shutdown_server_bounded(
                        server, timeout=5, description="M9 package browser server"
                    ),
                )
            cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
        if server_thread_started and server_thread is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: _join_package_browser_server(server_thread)
            )
        if server is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: server.join_request_handlers(
                    timeout=5, description="M9 package browser server"
                ),
            )
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Boot a staged pre-release Chromium Wasm package in Chrome."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument(
        "--outer-document-restart",
        action="store_true",
        help=(
            "after one clean package-host shutdown, navigate the outer document "
            "to a fresh package epoch and require a second clean lifetime"
        ),
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 10:
        parser.error("--timeout must allow package startup and shutdown")
    if args.outer_document_restart and args.timeout < 20:
        parser.error("--outer-document-restart requires two package lifetimes")
    try:
        result = run_package_browser_smoke(
            dist_dir=args.dist_dir,
            browser_argument=args.browser,
            no_sandbox=args.no_sandbox,
            timeout=args.timeout,
            outer_document_restart=args.outer_document_restart,
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

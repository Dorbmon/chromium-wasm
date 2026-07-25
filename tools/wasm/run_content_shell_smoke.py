#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the M3 single-process Content Shell gate in a host Chromium."""

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
    M3_CASE,
    compare_screenshots,
    create_m3_server,
    decode_png,
    load_screenshot_contract,
    m3_smoke_url,
    validate_m3_result,
)
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)


SENTINEL = "CHROMIUM_WASM_M3_CONTENT"


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
    actual_png: bytes | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    if actual_png is not None:
        (diagnostics_dir / "content-shell-m3-actual.png").write_bytes(
            actual_png
        )
    sanitized_result = result
    if result is not None:
        sanitized_result = json.loads(json.dumps(result))
        screenshot = sanitized_result.get("screenshot")
        if isinstance(screenshot, dict) and "dataBase64" in screenshot:
            screenshot["dataBase64"] = "<saved as content-shell-m3-actual.png>"
    diagnostic_path = diagnostics_dir / "content-shell-m3-failure.json"
    diagnostic = {
        "schema_version": 1,
        "runner": "run_content_shell_smoke.py",
        "case": M3_CASE,
        "status": "fail",
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": str(error),
        },
        "context": context,
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
        "runtime_result": sanitized_result,
    }
    temporary = diagnostic_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(diagnostic_path)
    return diagnostic_path


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
        raise M0Error("manifest is missing an M3 version field") from exc
    if not all(
        isinstance(value, str) and value for value in versions.values()
    ):
        raise M0Error("manifest contains an invalid M3 version field")
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic M3 Content Shell presentation and "
            "responsiveness gate."
        )
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default="content_shell_wasm")
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="failure directory (default: OUT_DIR/diagnostics)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="reviewed PNG baseline (default comes from the M3 contract)",
    )
    parser.add_argument(
        "--capture-baseline",
        type=Path,
        help=(
            "write one candidate baseline and exit 2; this never reports the "
            "M3 gate as passing"
        ),
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument("--verbose-server", action="store_true")
    args = parser.parse_args()
    if args.baseline is not None and args.capture_baseline is not None:
        parser.error(
            "--baseline and --capture-baseline are mutually exclusive"
        )

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / "diagnostics"
    elif not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    server = None
    server_thread = None
    server_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    actual_png: bytes | None = None
    context: dict[str, object] | None = None
    stage = "load_contract"

    try:
        contract = load_screenshot_contract()
        baseline_path = args.baseline
        if baseline_path is None:
            baseline_path = (
                Path(__file__).with_name("testdata")
                / str(contract["baseline"])
            )
        elif not baseline_path.is_absolute():
            baseline_path = REPO_ROOT / baseline_path
        capture_path = args.capture_baseline
        if capture_path is not None and not capture_path.is_absolute():
            capture_path = REPO_ROOT / capture_path
        if capture_path is not None and capture_path.exists():
            raise M0Error(
                f"refusing to overwrite existing baseline: {capture_path}"
            )
        if capture_path is None and not baseline_path.is_file():
            raise M0Error(
                "reviewed M3 baseline is missing; use --capture-baseline "
                "after the runtime contract passes, review the image, then "
                "run again with --baseline"
            )

        stage = "load_manifest"
        manifest = load_manifest()
        port_revision = checked_output(["git", "rev-parse", "HEAD"])
        versions = manifest_versions(manifest, port_revision)
        stage = "print_context"
        context = print_context(
            "run_content_shell_smoke.py",
            manifest,
            case=M3_CASE,
            gn_args=manifest.get(
                "m3_content_gn_args", manifest.get("gn_args")
            ),
            module_name=args.module_name,
            screenshot_channel_tolerance=contract["channel_tolerance"],
            screenshot_maximum_different_pixel_ratio=(
                contract["maximum_different_pixel_ratio"]
            ),
            host_browser_sandbox=not args.no_sandbox,
        )

        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER "
            + json.dumps(
                {"browser_version": browser_version},
                sort_keys=True,
                separators=(",", ":"),
            ),
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
            name="chromium-wasm-m3-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        url = m3_smoke_url(
            server,
            token,
            versions,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )

        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m3-")
        stage = "launch_browser"
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
            name="chromium-wasm-m3-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()

        stage = "wait_for_result"
        deadline = time.monotonic() + args.timeout
        while result is None:
            if browser.poll() is not None:
                raise M0Error(
                    "host browser exited before the M3 result "
                    f"(status {browser.returncode}): "
                    + "\n".join(browser_stderr)
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise M0Error(
                    "M3 browser timeout: " + "\n".join(browser_stderr)
                )
            try:
                result = result_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue

        stage = "validate_runtime_contract"
        actual_png = validate_m3_result(
            result, expected_versions=versions
        )
        actual_image = decode_png(actual_png)
        if (
            actual_image.width != contract["width"]
            or actual_image.height != contract["height"]
        ):
            raise M0Error("M3 PNG dimensions do not match the contract")

        if capture_path is not None:
            stage = "capture_baseline"
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture_path.write_bytes(actual_png)
            print(
                f"{SENTINEL}:BASELINE_CAPTURED_REVIEW_REQUIRED "
                + json.dumps(
                    {"path": str(capture_path)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
            return 2

        stage = "compare_screenshot"
        comparison = compare_screenshots(
            actual_png,
            baseline_path.read_bytes(),
            channel_tolerance=int(contract["channel_tolerance"]),
            maximum_different_pixel_ratio=float(
                contract["maximum_different_pixel_ratio"]
            ),
        )
        if not comparison.matches:
            raise M0Error(
                "M3 screenshot exceeded tolerance: "
                + json.dumps(
                    comparison.as_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        print(
            f"{SENTINEL}:SCREENSHOT "
            + json.dumps(
                comparison.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(
                {
                    "heartbeat": result["heartbeat"],
                    "inputResult": result["inputResult"],
                    "readiness": result["readiness"],
                    "shutdown": result["shutdown"],
                    "versions": result["versions"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
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
                result=result,
                actual_png=actual_png,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps(
                    {"path": str(diagnostic_path)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL "
                f"reason={diagnostic_error}",
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

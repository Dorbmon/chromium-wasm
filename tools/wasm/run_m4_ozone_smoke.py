#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run trusted M4 host input through Ozone/Aura in host Chrome."""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
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
    M4_CASE,
    M4_FOCUS_CASE,
    M4_WHEEL_CASE,
    M4_KEYBOARD_CASE,
    M4_PRINTABLE_KEY_CASE,
    create_m3_server,
    m4_focus_smoke_url,
    m4_smoke_url,
    m4_wheel_smoke_url,
    m4_keyboard_smoke_url,
    m4_printable_key_smoke_url,
    validate_m4_result,
    validate_m4_focus_result,
    validate_m4_wheel_result,
    validate_m4_keyboard_result,
    validate_m4_printable_key_result,
)
from m4_cdp import DevToolsClient, unused_loopback_port, wait_for_page_client
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)
from run_content_shell_smoke import manifest_versions


SENTINEL = "CHROMIUM_WASM_M4_OZONE"


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
    case: str,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_path = diagnostics_dir / f"m4-{case}-failure.json"
    diagnostic = {
        "schema_version": 1,
        "runner": "run_m4_ozone_smoke.py",
        "case": case,
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
        "runtime_result": result,
    }
    temporary = diagnostic_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(diagnostic_path)
    return diagnostic_path


def _require_finite_number(value: object, description: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise M0Error(f"{description} must be a finite number")
    return float(value)


def canvas_click_position(
    state: dict[str, Any], geometry: dict[str, Any]
) -> tuple[float, float]:
    try:
        target_x = state["targetX"]
        target_y = state["targetY"]
    except KeyError as exc:
        raise M0Error(
            "M4 host did not publish fixture target coordinates"
        ) from exc
    if (
        not isinstance(target_x, int)
        or isinstance(target_x, bool)
        or not isinstance(target_y, int)
        or isinstance(target_y, bool)
        or target_x < 0
        or target_y < 0
    ):
        raise M0Error("M4 host published invalid fixture target coordinates")
    left = _require_finite_number(geometry.get("left"), "canvas left")
    top = _require_finite_number(geometry.get("top"), "canvas top")
    client_left = _require_finite_number(
        geometry.get("clientLeft"), "canvas clientLeft"
    )
    client_top = _require_finite_number(
        geometry.get("clientTop"), "canvas clientTop"
    )
    client_width = _require_finite_number(
        geometry.get("clientWidth"), "canvas clientWidth"
    )
    client_height = _require_finite_number(
        geometry.get("clientHeight"), "canvas clientHeight"
    )
    width = _require_finite_number(geometry.get("width"), "canvas width")
    height = _require_finite_number(geometry.get("height"), "canvas height")
    if client_width <= 0 or client_height <= 0 or width <= 0 or height <= 0:
        raise M0Error("M4 canvas has nonpositive dimensions")
    if target_x >= width or target_y >= height:
        raise M0Error("M4 fixture target is outside the backing canvas")
    return (
        left + client_left + (target_x + 0.5) * client_width / width,
        top + client_top + (target_y + 0.5) * client_height / height,
    )


def read_canvas_geometry(client: DevToolsClient) -> dict[str, Any]:
    value = client.evaluate(
        """(() => {
          const canvas = document.querySelector('#browser-canvas');
          if (!(canvas instanceof HTMLCanvasElement)) return null;
          const rect = canvas.getBoundingClientRect();
          return {
            left: rect.left,
            top: rect.top,
            clientLeft: canvas.clientLeft,
            clientTop: canvas.clientTop,
            clientWidth: canvas.clientWidth,
            clientHeight: canvas.clientHeight,
            width: canvas.width,
            height: canvas.height,
          };
        })()"""
    )
    if not isinstance(value, dict):
        raise M0Error("M4 host canvas geometry is unavailable")
    return value


def read_focus_sink_position(client: DevToolsClient) -> tuple[float, float]:
    value = client.evaluate(
        """(() => {
          const sink = document.querySelector('#m4-focus-sink');
          if (!(sink instanceof HTMLButtonElement) || sink.hidden) return null;
          const rect = sink.getBoundingClientRect();
          return {
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height,
            viewportWidth: innerWidth,
            viewportHeight: innerHeight,
          };
        })()"""
    )
    if not isinstance(value, dict):
        raise M0Error("M4 host focus sink geometry is unavailable")
    left = _require_finite_number(value.get("left"), "focus sink left")
    top = _require_finite_number(value.get("top"), "focus sink top")
    width = _require_finite_number(value.get("width"), "focus sink width")
    height = _require_finite_number(value.get("height"), "focus sink height")
    viewport_width = _require_finite_number(
        value.get("viewportWidth"), "focus sink viewport width"
    )
    viewport_height = _require_finite_number(
        value.get("viewportHeight"), "focus sink viewport height"
    )
    if width <= 0 or height <= 0 or viewport_width <= 0 or viewport_height <= 0:
        raise M0Error("M4 host focus sink has nonpositive dimensions")
    center_x = left + width / 2
    center_y = top + height / 2
    if (
        center_x < 0
        or center_y < 0
        or center_x >= viewport_width
        or center_y >= viewport_height
    ):
        raise M0Error("M4 host focus sink center is outside the viewport")
    return center_x, center_y


def wait_for_input_state(
    client: DevToolsClient,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
    state_expression: str,
    expected_state: str,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before accepting M4 input "
                f"(status {browser.returncode}): " + "\n".join(browser_stderr)
            )
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            result = None
        if result is not None:
            raise M0Error(
                "M4 host finished before accepting trusted DOM input: "
                + json.dumps(result, sort_keys=True, separators=(",", ":"))
            )
        state = client.evaluate(state_expression)
        if (
            isinstance(state, dict)
            and state.get("state") == expected_state
        ):
            return state
        time.sleep(0.05)
    raise M0Error(f"M4 host did not become ready for {expected_state}")


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before the M4 result "
                f"(status {browser.returncode}): " + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        try:
            return result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue
    raise M0Error("M4 browser timeout: " + "\n".join(browser_stderr))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run trusted host DOM input through Ozone and Aura."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default="content_shell_wasm")
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="failure directory (default: OUT_DIR/diagnostics-m4)",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument(
        "--input",
        choices=("pointer", "wheel", "keyboard", "printable-key", "focus"),
        default="pointer",
        help="trusted DOM input path to drive",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument("--verbose-server", action="store_true")
    args = parser.parse_args()

    if args.input == "pointer":
        case = M4_CASE
        state_expression = "window.__chromiumWasmM4State || null"
        expected_state = "awaiting-dom-pointer"
        input_driver = "Chrome DevTools Input.dispatchMouseEvent:mouse"
    elif args.input == "wheel":
        case = M4_WHEEL_CASE
        state_expression = "window.__chromiumWasmM4WheelState || null"
        expected_state = "awaiting-dom-wheel"
        input_driver = "Chrome DevTools Input.dispatchMouseEvent:mouseWheel"
    elif args.input == "keyboard":
        case = M4_KEYBOARD_CASE
        state_expression = "window.__chromiumWasmM4KeyboardState || null"
        expected_state = "awaiting-dom-keyboard-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent + "
            "Input.dispatchKeyEvent:rawKeyDown/keyUp"
        )
    elif args.input == "printable-key":
        case = M4_PRINTABLE_KEY_CASE
        state_expression = "window.__chromiumWasmM4PrintableKeyState || null"
        expected_state = "awaiting-dom-printable-key-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent + "
            "Input.dispatchKeyEvent:rawKeyDown/keyUp without text"
        )
    else:
        case = M4_FOCUS_CASE
        state_expression = "window.__chromiumWasmM4FocusState || null"
        expected_state = "awaiting-dom-focus-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent + "
            "Input.dispatchKeyEvent:rawKeyDown"
        )

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / "diagnostics-m4"
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
    client: DevToolsClient | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    stage = "load_manifest"

    try:
        manifest = load_manifest()
        port_revision = checked_output(["git", "rev-parse", "HEAD"])
        versions = manifest_versions(manifest, port_revision)
        stage = "print_context"
        context = print_context(
            "run_m4_ozone_smoke.py",
            manifest,
            case=case,
            gn_args=manifest.get(
                "m3_content_gn_args", manifest.get("gn_args")
            ),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            input_driver=input_driver,
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
            name="chromium-wasm-m4-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        if args.input == "pointer":
            url = m4_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "wheel":
            url = m4_wheel_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "keyboard":
            url = m4_keyboard_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "printable-key":
            url = m4_printable_key_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        else:
            url = m4_focus_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )

        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m4-")
        debug_port = unused_loopback_port()
        stage = "launch_browser"
        command = browser_command(
            browser_path,
            profile.name,
            url,
            no_sandbox=args.no_sandbox,
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
            name="chromium-wasm-m4-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()

        deadline = time.monotonic() + args.timeout
        stage = "connect_devtools"
        # Connecting and immediately evaluating while Content Shell is still
        # establishing its UI sequence can perturb the Wasm scheduler. Let the
        # page begin normally, then use DevTools solely as the external input
        # driver.
        stage = "allow_wasm_startup"
        time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
        if browser.poll() is not None:
            raise M0Error("host browser exited during M4 startup")

        expected_url_prefix = url.split("?", 1)[0]
        client = wait_for_page_client(debug_port, expected_url_prefix, deadline)
        stage = "wait_for_input_state"
        state = wait_for_input_state(
            client,
            browser,
            browser_stderr,
            result_queue,
            deadline,
            state_expression,
            expected_state,
        )
        stage = "measure_canvas"
        click_x, click_y = canvas_click_position(
            state, read_canvas_geometry(client)
        )
        if args.input == "pointer":
            stage = "dispatch_trusted_dom_pointer"
            client.dispatch_primary_click(click_x, click_y)
        elif args.input == "wheel":
            stage = "dispatch_trusted_dom_wheel"
            client.dispatch_mouse_wheel(click_x, click_y, 0.0, 160.0)
        elif args.input == "keyboard":
            stage = "dispatch_trusted_dom_keyboard_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_keyboard_activation"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-key",
            )
            stage = "dispatch_trusted_dom_key"
            client.dispatch_arrow_down()
        elif args.input == "printable-key":
            stage = "dispatch_trusted_dom_printable_key_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_printable_key_activation"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-printable-key",
            )
            stage = "dispatch_trusted_dom_printable_key"
            client.dispatch_key_a()
        else:
            stage = "dispatch_trusted_dom_focus_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_focus_key_down"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-focus-key-down",
            )
            stage = "dispatch_trusted_dom_focus_key_down"
            client.dispatch_arrow_down_down()
            stage = "wait_for_focus_loss"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-focus-loss",
            )
            stage = "measure_focus_sink"
            focus_sink_x, focus_sink_y = read_focus_sink_position(client)
            stage = "dispatch_trusted_host_focus_loss"
            client.dispatch_primary_click(focus_sink_x, focus_sink_y)
        stage = "wait_for_result"
        result = wait_for_result(
            browser, browser_stderr, result_queue, deadline
        )
        stage = "validate_runtime_contract"
        if args.input == "pointer":
            validate_m4_result(result, expected_versions=versions)
            input_key = "pointerInput"
        elif args.input == "wheel":
            validate_m4_wheel_result(result, expected_versions=versions)
            input_key = "wheelInput"
        elif args.input == "keyboard":
            validate_m4_keyboard_result(result, expected_versions=versions)
            input_key = "keyboardInput"
        elif args.input == "printable-key":
            validate_m4_printable_key_result(
                result, expected_versions=versions
            )
            input_key = "keyboardInput"
        else:
            validate_m4_focus_result(result, expected_versions=versions)
            input_key = "focusInput"
        print(
            f"{SENTINEL}:BROWSER_RESULT "
            + json.dumps(
                {
                    input_key: result[input_key],
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
                case=case,
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
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
                flush=True,
            )
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if client is not None:
            client.close()
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

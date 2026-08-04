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
    M4_SELECT_CASE,
    M4_RESIZE_CASE,
    M4_CONTEXT_MENU_CASE,
    M4_TOOLTIP_CASE,
    M4_SELECTION_CASE,
    M4_PRIMARY_PASTE_CASE,
    M4_COPY_PASTE_CASE,
    M4_FOCUS_CASE,
    M4_WHEEL_CASE,
    M4_KEYBOARD_CASE,
    M4_PRINTABLE_KEY_CASE,
    M4_BACKSPACE_CASE,
    M4_IME_BRIDGE_CASE,
    create_m3_server,
    m4_focus_smoke_url,
    m4_smoke_url,
    m4_select_smoke_url,
    m4_resize_smoke_url,
    m4_context_menu_smoke_url,
    m4_tooltip_smoke_url,
    m4_selection_smoke_url,
    m4_primary_paste_smoke_url,
    m4_copy_paste_smoke_url,
    m4_wheel_smoke_url,
    m4_keyboard_smoke_url,
    m4_printable_key_smoke_url,
    m4_backspace_smoke_url,
    m4_ime_bridge_smoke_url,
    validate_m4_result,
    validate_m4_select_result,
    validate_m4_resize_result,
    validate_m4_context_menu_result,
    validate_m4_tooltip_result,
    validate_m4_selection_result,
    validate_m4_primary_paste_result,
    validate_m4_copy_paste_result,
    validate_m4_focus_result,
    validate_m4_wheel_result,
    validate_m4_keyboard_result,
    validate_m4_printable_key_result,
    validate_m4_backspace_result,
    validate_m4_ime_bridge_result,
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


def canvas_point_position(
    state: dict[str, Any],
    geometry: dict[str, Any],
    *,
    x_field: str,
    y_field: str,
    description: str,
) -> tuple[float, float]:
    """Map one fixture backing-canvas point into host CSS coordinates."""

    try:
        target_x = state[x_field]
        target_y = state[y_field]
    except KeyError as exc:
        raise M0Error(
            f"M4 host did not publish fixture {description} coordinates"
        ) from exc
    if (
        not isinstance(target_x, int)
        or isinstance(target_x, bool)
        or not isinstance(target_y, int)
        or isinstance(target_y, bool)
        or target_x < 0
        or target_y < 0
    ):
        raise M0Error(
            f"M4 host published invalid fixture {description} coordinates"
        )
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
        raise M0Error(
            f"M4 fixture {description} is outside the backing canvas"
        )
    return (
        left + client_left + (target_x + 0.5) * client_width / width,
        top + client_top + (target_y + 0.5) * client_height / height,
    )


def canvas_click_position(
    state: dict[str, Any], geometry: dict[str, Any]
) -> tuple[float, float]:
    return canvas_point_position(
        state,
        geometry,
        x_field="targetX",
        y_field="targetY",
        description="target",
    )


def canvas_pointer_exit_position(
    inside_x: float, geometry: dict[str, Any]
) -> tuple[float, float]:
    """Choose a trusted pointer position immediately above the canvas."""

    top = _require_finite_number(geometry.get("top"), "canvas top")
    # CDP accepts viewport-relative coordinates just beyond an edge. This also
    # handles a canvas flush with the viewport top without pretending its
    # outside point belongs to the Wasm display.
    return inside_x, top - 1.0


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
    last_state: Any = None
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
        last_state = state
        if (
            isinstance(state, dict)
            and state.get("state") == expected_state
        ):
            return state
        time.sleep(0.05)
    raise M0Error(
        f"M4 host did not become ready for {expected_state}: "
        + json.dumps(last_state, sort_keys=True, separators=(",", ":"))
    )


def validate_backspace_key_a_stage(state: dict[str, Any]) -> None:
    """Require the host's frozen KeyA Blink-edit proof before Backspace."""

    proof = state.get("keyAProof")
    if not isinstance(proof, dict):
        raise M0Error("M4 Backspace KeyA stage did not publish a proof")
    for field in (
        "outerTraceExact",
        "innerTraceExact",
        "textTraceExact",
        "noComposition",
        "frameAfterKeyADown",
    ):
        if proof.get(field) is not True:
            raise M0Error(
                "M4 Backspace KeyA stage did not prove " + field
            )
    if proof.get("value") != "a":
        raise M0Error("M4 Backspace KeyA stage did not retain value 'a'")
    for field in ("selectionStart", "selectionEnd"):
        value = proof.get(field)
        if type(value) is not int or value != 1:
            raise M0Error(
                f"M4 Backspace KeyA stage {field} is not exactly 1"
            )


def validate_selection_activation_stage(state: dict[str, Any]) -> None:
    """Require a frozen native collapsed-selection proof before the drag."""

    proof = state.get("activationProof")
    if not isinstance(proof, dict):
        raise M0Error("M4 selection activation did not publish a proof")
    for field in (
        "outerTraceExact",
        "activationEvidence",
        "selectionCollapsed",
        "selectionDirectionNeutral",
        "selectedTextEmpty",
        "frameAfterActivation",
    ):
        if proof.get(field) is not True:
            raise M0Error(
                "M4 selection activation did not prove " + field
            )
    selection_start = proof.get("selectionStart")
    selection_end = proof.get("selectionEnd")
    if (
        type(selection_start) is not int
        or type(selection_end) is not int
        or selection_start < 0
        or selection_end < 0
        or selection_start != selection_end
    ):
        raise M0Error(
            "M4 selection activation did not retain a collapsed native "
            "selection"
        )
    if proof.get("selectionDirection") not in ("none", "forward"):
        raise M0Error(
            "M4 selection activation selection direction is invalid"
        )
    if proof.get("selectedText") != "":
        raise M0Error("M4 selection activation selected text is not empty")


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
        choices=(
            "pointer",
            "select",
            "resize",
            "context-menu",
            "tooltip",
            "selection",
            "primary-paste",
            "copy-paste",
            "wheel",
            "keyboard",
            "printable-key",
            "backspace",
            "ime-bridge",
            "focus",
        ),
        default="pointer",
        help="trusted DOM input path to drive",
    )
    parser.add_argument(
        "--ime-terminal",
        choices=("commit", "cancel"),
        default="commit",
        help="M4 IME terminal action when --input=ime-bridge",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument("--verbose-server", action="store_true")
    args = parser.parse_args()

    if args.input != "ime-bridge" and args.ime_terminal != "commit":
        parser.error("--ime-terminal requires --input=ime-bridge")

    if args.input == "pointer":
        case = M4_CASE
        state_expression = "window.__chromiumWasmM4State || null"
        expected_state = "awaiting-dom-pointer"
        input_driver = "Chrome DevTools Input.dispatchMouseEvent:mouse"
    elif args.input == "select":
        case = M4_SELECT_CASE
        state_expression = "window.__chromiumWasmM4SelectState || null"
        expected_state = "awaiting-dom-select-open"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent two primary clicks; "
            "the second target is derived from native popup canvas pixels"
        )
    elif args.input == "resize":
        case = M4_RESIZE_CASE
        state_expression = None
        expected_state = None
        input_driver = (
            "host.resize 800x600 -> 640x480 -> 800x600 at DPR 1; "
            "no Chrome DevTools input"
        )
    elif args.input == "context-menu":
        case = M4_CONTEXT_MENU_CASE
        state_expression = (
            "window.__chromiumWasmM4ContextMenuState || null"
        )
        expected_state = "awaiting-dom-context-menu-activation"
        input_driver = (
            "Chrome DevTools primary activation and drag, secondary click, "
            "scan-derived Copy click, then raw ControlLeft+KeyV; no "
            "clipboard or DOM text commands"
        )
    elif args.input == "tooltip":
        case = M4_TOOLTIP_CASE
        state_expression = "window.__chromiumWasmM4TooltipState || null"
        expected_state = "awaiting-dom-tooltip-race"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent: five mouseMoved "
            "records: immediate title-to-title-less race, duplicate title "
            "hover for Blink coalescing, then a real host-canvas pointerleave; "
            "no click, "
            "keyboard, text, clipboard, or "
            "DOM commands"
        )
    elif args.input == "selection":
        case = M4_SELECTION_CASE
        state_expression = "window.__chromiumWasmM4SelectionState || null"
        expected_state = "awaiting-dom-selection-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent primary click followed "
            "by a primary drag with two held-button moves; no text commands"
        )
    elif args.input == "primary-paste":
        case = M4_PRIMARY_PASTE_CASE
        state_expression = "window.__chromiumWasmM4PrimaryPasteState || null"
        expected_state = "awaiting-dom-primary-paste-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent primary click and drag "
            "followed by a middle click; no clipboard or text commands"
        )
    elif args.input == "copy-paste":
        case = M4_COPY_PASTE_CASE
        state_expression = "window.__chromiumWasmM4CopyPasteState || null"
        expected_state = "awaiting-dom-copy-paste-source-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent source/decoy drags "
            "plus raw ControlLeft+KeyC and ControlLeft+KeyV; no clipboard "
            "or text commands"
        )
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
            "Input.dispatchKeyEvent:rawKeyDown/autoRepeat/keyUp"
        )
    elif args.input == "printable-key":
        case = M4_PRINTABLE_KEY_CASE
        state_expression = "window.__chromiumWasmM4PrintableKeyState || null"
        expected_state = "awaiting-dom-printable-key-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent + "
            "Input.dispatchKeyEvent:rawKeyDown/keyUp without text"
        )
    elif args.input == "backspace":
        case = M4_BACKSPACE_CASE
        state_expression = "window.__chromiumWasmM4BackspaceState || null"
        expected_state = "awaiting-dom-backspace-activation"
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent + raw KeyA then raw "
            "Backspace Input.dispatchKeyEvent pairs without text; the runner "
            "waits for the trusted KeyA Blink edit before dispatching "
            "Backspace"
        )
    elif args.input == "ime-bridge":
        case = M4_IME_BRIDGE_CASE
        state_expression = "window.__chromiumWasmM4ImeBridgeState || null"
        expected_state = "awaiting-dom-ime-bridge-activation"
        terminal_driver = (
            "Input.insertText" if args.ime_terminal == "commit"
            else "Input.imeSetComposition(empty)"
        )
        input_driver = (
            "Chrome DevTools Input.dispatchMouseEvent + "
            "Input.imeSetComposition followed by " + terminal_driver +
            "; the terminal is bound to its trusted candidate before Ozone "
            "delivers the composition to Blink"
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
        elif args.input == "select":
            url = m4_select_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "resize":
            url = m4_resize_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "context-menu":
            # The native menu proof has six separately observed physical
            # phases, including pixel-derived overlay targeting.
            url = m4_context_menu_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(90.0, max(1.0, args.timeout - 5.0)),
            )
        elif args.input == "tooltip":
            url = m4_tooltip_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "selection":
            url = m4_selection_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "primary-paste":
            url = m4_primary_paste_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "copy-paste":
            # This case has eight separately observed physical input phases.
            # Leave time for the outer driver to collect the posted result.
            url = m4_copy_paste_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(90.0, max(1.0, args.timeout - 5.0)),
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
        elif args.input == "backspace":
            url = m4_backspace_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
            )
        elif args.input == "ime-bridge":
            url = m4_ime_bridge_smoke_url(
                server,
                token,
                versions,
                module_name=args.module_name,
                timeout_seconds=min(30.0, max(1.0, args.timeout - 1.0)),
                terminal_mode=args.ime_terminal,
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

        if args.input == "resize":
            # This case drives only the normal host resize API from the Wasm
            # harness. It deliberately neither connects to DevTools nor sends
            # any outer-browser input event.
            stage = "wait_for_host_resize_result"
            result = wait_for_result(
                browser, browser_stderr, result_queue, deadline
            )
            stage = "validate_runtime_contract"
            validate_m4_resize_result(result, expected_versions=versions)
            print(
                f"{SENTINEL}:BROWSER_RESULT "
                + json.dumps(
                    {
                        "resizeProof": result["resizeProof"],
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
        canvas_geometry = read_canvas_geometry(client)
        if args.input == "primary-paste":
            click_x, click_y = canvas_point_position(
                state,
                canvas_geometry,
                x_field="sourceTargetX",
                y_field="sourceTargetY",
                description="primary-paste source target",
            )
        elif args.input == "context-menu":
            click_x, click_y = canvas_point_position(
                state,
                canvas_geometry,
                x_field="sourceTargetX",
                y_field="sourceTargetY",
                description="context-menu source target",
            )
        elif args.input == "copy-paste":
            click_x, click_y = canvas_point_position(
                state,
                canvas_geometry,
                x_field="copySourceTargetX",
                y_field="copySourceTargetY",
                description="copy-paste source target",
            )
        elif args.input == "tooltip":
            click_x, click_y = canvas_point_position(
                state,
                canvas_geometry,
                x_field="hoverTargetX",
                y_field="hoverTargetY",
                description="tooltip title target",
            )
            rapid_clear_x, rapid_clear_y = canvas_point_position(
                state,
                canvas_geometry,
                x_field="clearTargetX",
                y_field="clearTargetY",
                description="rapid tooltip title-less target",
            )
        else:
            click_x, click_y = canvas_click_position(state, canvas_geometry)
        if args.input == "pointer":
            stage = "dispatch_trusted_dom_pointer"
            client.dispatch_primary_click(click_x, click_y)
        elif args.input == "select":
            stage = "dispatch_trusted_dom_select_opener"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_select_popup"
            select_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-select-option",
            )
            stage = "measure_select_popup_option"
            option_x, option_y = canvas_point_position(
                select_state,
                canvas_geometry,
                x_field="optionTargetX",
                y_field="optionTargetY",
                description="scan-derived native select option",
            )
            stage = "dispatch_trusted_dom_select_option"
            client.dispatch_primary_click(option_x, option_y)
        elif args.input == "selection":
            stage = "dispatch_trusted_dom_selection_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_selection_drag"
            selection_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-selection-drag",
            )
            stage = "validate_selection_activation"
            validate_selection_activation_stage(selection_state)
            stage = "measure_selection_drag"
            drag_start_x, drag_start_y = canvas_point_position(
                selection_state,
                canvas_geometry,
                x_field="dragStartX",
                y_field="dragStartY",
                description="drag start",
            )
            drag_middle_x, drag_middle_y = canvas_point_position(
                selection_state,
                canvas_geometry,
                x_field="dragMiddleX",
                y_field="dragMiddleY",
                description="drag middle",
            )
            drag_end_x, drag_end_y = canvas_point_position(
                selection_state,
                canvas_geometry,
                x_field="dragEndX",
                y_field="dragEndY",
                description="drag end",
            )
            stage = "dispatch_trusted_dom_selection_drag"
            client.dispatch_primary_drag(
                drag_start_x,
                drag_start_y,
                drag_middle_x,
                drag_middle_y,
                drag_end_x,
                drag_end_y,
            )
        elif args.input == "primary-paste":
            stage = "dispatch_trusted_dom_primary_paste_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_primary_paste_drag"
            primary_paste_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-primary-paste-drag",
            )
            stage = "measure_primary_paste_drag"
            drag_start_x, drag_start_y = canvas_point_position(
                primary_paste_state,
                canvas_geometry,
                x_field="dragStartX",
                y_field="dragStartY",
                description="primary-paste drag start",
            )
            drag_middle_x, drag_middle_y = canvas_point_position(
                primary_paste_state,
                canvas_geometry,
                x_field="dragMiddleX",
                y_field="dragMiddleY",
                description="primary-paste drag middle",
            )
            drag_end_x, drag_end_y = canvas_point_position(
                primary_paste_state,
                canvas_geometry,
                x_field="dragEndX",
                y_field="dragEndY",
                description="primary-paste drag end",
            )
            stage = "dispatch_trusted_dom_primary_paste_drag"
            client.dispatch_primary_drag(
                drag_start_x,
                drag_start_y,
                drag_middle_x,
                drag_middle_y,
                drag_end_x,
                drag_end_y,
            )
            stage = "wait_for_primary_selection"
            primary_selection_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-primary-paste",
            )
            stage = "measure_primary_paste_target"
            paste_x, paste_y = canvas_point_position(
                primary_selection_state,
                canvas_geometry,
                x_field="pasteTargetX",
                y_field="pasteTargetY",
                description="primary-paste target",
            )
            stage = "dispatch_trusted_dom_primary_paste"
            client.dispatch_middle_click(paste_x, paste_y)
        elif args.input == "context-menu":
            stage = "dispatch_trusted_dom_context_menu_source_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_context_menu_drag"
            context_drag_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-context-menu-drag",
            )
            stage = "measure_context_menu_drag"
            drag_start_x, drag_start_y = canvas_point_position(
                context_drag_state,
                canvas_geometry,
                x_field="dragStartX",
                y_field="dragStartY",
                description="context-menu drag start",
            )
            drag_middle_x, drag_middle_y = canvas_point_position(
                context_drag_state,
                canvas_geometry,
                x_field="dragMiddleX",
                y_field="dragMiddleY",
                description="context-menu drag middle",
            )
            drag_end_x, drag_end_y = canvas_point_position(
                context_drag_state,
                canvas_geometry,
                x_field="dragEndX",
                y_field="dragEndY",
                description="context-menu drag end",
            )
            stage = "dispatch_trusted_dom_context_menu_drag"
            client.dispatch_primary_drag(
                drag_start_x,
                drag_start_y,
                drag_middle_x,
                drag_middle_y,
                drag_end_x,
                drag_end_y,
            )
            stage = "wait_for_context_menu_secondary_click"
            context_open_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-context-menu-open",
            )
            stage = "measure_context_menu_secondary_target"
            secondary_x, secondary_y = canvas_point_position(
                context_open_state,
                canvas_geometry,
                x_field="sourceTargetX",
                y_field="sourceTargetY",
                description="context-menu secondary target",
            )
            stage = "dispatch_trusted_dom_context_menu_secondary_click"
            client.dispatch_secondary_click(secondary_x, secondary_y)
            stage = "wait_for_context_menu_copy"
            menu_copy_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-context-menu-copy",
            )
            stage = "measure_scan_derived_context_menu_copy_target"
            copy_x, copy_y = canvas_point_position(
                menu_copy_state,
                canvas_geometry,
                x_field="menuTargetX",
                y_field="menuTargetY",
                description="scan-derived context-menu Copy target",
            )
            stage = "dispatch_trusted_dom_context_menu_copy"
            client.dispatch_primary_click(copy_x, copy_y)
            stage = "wait_for_context_menu_paste_activation"
            paste_activation_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-context-menu-paste-activation",
            )
            stage = "measure_context_menu_paste_target"
            paste_x, paste_y = canvas_point_position(
                paste_activation_state,
                canvas_geometry,
                x_field="pasteTargetX",
                y_field="pasteTargetY",
                description="context-menu paste target",
            )
            stage = "dispatch_trusted_dom_context_menu_paste_activation"
            client.dispatch_primary_click(paste_x, paste_y)
            stage = "wait_for_context_menu_ctrl_v"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-context-menu-paste",
            )
            stage = "dispatch_trusted_dom_context_menu_ctrl_v"
            client.dispatch_ctrl_v()
        elif args.input == "tooltip":
            stage = "dispatch_trusted_dom_tooltip_race_hover"
            client.dispatch_mouse_move(click_x, click_y)
            stage = "dispatch_trusted_dom_tooltip_race_clear"
            client.dispatch_mouse_move(rapid_clear_x, rapid_clear_y)
            stage = "wait_for_tooltip_hover"
            tooltip_hover_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-tooltip-hover",
            )
            stage = "measure_tooltip_confirm_target"
            hover_x, hover_y = canvas_point_position(
                tooltip_hover_state,
                canvas_geometry,
                x_field="confirmTargetX",
                y_field="confirmTargetY",
                description="tooltip confirm title target",
            )
            stage = "dispatch_trusted_dom_tooltip_confirm"
            client.dispatch_mouse_move(hover_x, hover_y)
            stage = "dispatch_trusted_dom_tooltip_confirm_duplicate"
            client.dispatch_mouse_move(hover_x, hover_y)
            stage = "wait_for_tooltip_exit"
            tooltip_clear_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-tooltip-exit",
            )
            stage = "measure_tooltip_canvas_exit"
            exit_x, exit_y = canvas_pointer_exit_position(
                hover_x, canvas_geometry
            )
            stage = "dispatch_trusted_dom_tooltip_canvas_exit"
            client.dispatch_mouse_move(exit_x, exit_y)
        elif args.input == "copy-paste":
            stage = "dispatch_trusted_dom_copy_source_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_bare_key_c_rejection"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-bare-shortcut-rejection",
            )
            stage = "dispatch_trusted_dom_bare_key_c"
            client.dispatch_bare_key_c()
            stage = "wait_for_copy_source_drag"
            copy_drag_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-source-drag",
            )
            stage = "measure_copy_source_drag"
            copy_drag_start_x, copy_drag_start_y = canvas_point_position(
                copy_drag_state,
                canvas_geometry,
                x_field="copyDragStartX",
                y_field="copyDragStartY",
                description="copy-paste COPY drag start",
            )
            copy_drag_middle_x, copy_drag_middle_y = canvas_point_position(
                copy_drag_state,
                canvas_geometry,
                x_field="copyDragMiddleX",
                y_field="copyDragMiddleY",
                description="copy-paste COPY drag middle",
            )
            copy_drag_end_x, copy_drag_end_y = canvas_point_position(
                copy_drag_state,
                canvas_geometry,
                x_field="copyDragEndX",
                y_field="copyDragEndY",
                description="copy-paste COPY drag end",
            )
            stage = "dispatch_trusted_dom_copy_source_drag"
            client.dispatch_primary_drag(
                copy_drag_start_x,
                copy_drag_start_y,
                copy_drag_middle_x,
                copy_drag_middle_y,
                copy_drag_end_x,
                copy_drag_end_y,
            )
            stage = "wait_for_ctrl_c"
            copy_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-copy",
            )
            stage = "dispatch_trusted_dom_ctrl_c"
            client.dispatch_ctrl_c()
            stage = "wait_for_decoy_activation"
            decoy_activation_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-decoy-activation",
            )
            stage = "measure_decoy_activation"
            decoy_x, decoy_y = canvas_point_position(
                decoy_activation_state,
                canvas_geometry,
                x_field="decoyTargetX",
                y_field="decoyTargetY",
                description="copy-paste DECOY target",
            )
            stage = "dispatch_trusted_dom_decoy_activation"
            client.dispatch_primary_click(decoy_x, decoy_y)
            stage = "wait_for_decoy_drag"
            decoy_drag_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-decoy-drag",
            )
            stage = "measure_decoy_drag"
            decoy_drag_start_x, decoy_drag_start_y = canvas_point_position(
                decoy_drag_state,
                canvas_geometry,
                x_field="decoyDragStartX",
                y_field="decoyDragStartY",
                description="copy-paste DECOY drag start",
            )
            decoy_drag_middle_x, decoy_drag_middle_y = canvas_point_position(
                decoy_drag_state,
                canvas_geometry,
                x_field="decoyDragMiddleX",
                y_field="decoyDragMiddleY",
                description="copy-paste DECOY drag middle",
            )
            decoy_drag_end_x, decoy_drag_end_y = canvas_point_position(
                decoy_drag_state,
                canvas_geometry,
                x_field="decoyDragEndX",
                y_field="decoyDragEndY",
                description="copy-paste DECOY drag end",
            )
            stage = "dispatch_trusted_dom_decoy_drag"
            client.dispatch_primary_drag(
                decoy_drag_start_x,
                decoy_drag_start_y,
                decoy_drag_middle_x,
                decoy_drag_middle_y,
                decoy_drag_end_x,
                decoy_drag_end_y,
            )
            stage = "wait_for_paste_activation"
            paste_activation_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-paste-activation",
            )
            stage = "measure_paste_target"
            paste_x, paste_y = canvas_point_position(
                paste_activation_state,
                canvas_geometry,
                x_field="pasteTargetX",
                y_field="pasteTargetY",
                description="copy-paste paste target",
            )
            stage = "dispatch_trusted_dom_paste_activation"
            client.dispatch_primary_click(paste_x, paste_y)
            stage = "wait_for_ctrl_v"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-paste",
            )
            stage = "dispatch_trusted_dom_ctrl_v"
            client.dispatch_ctrl_v()
            stage = "wait_for_primary_selection_verification"
            primary_verify_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-copy-paste-primary-verify",
            )
            stage = "measure_primary_selection_verification_target"
            primary_verify_x, primary_verify_y = canvas_point_position(
                primary_verify_state,
                canvas_geometry,
                x_field="primaryVerifyTargetX",
                y_field="primaryVerifyTargetY",
                description="copy-paste primary-selection verification target",
            )
            stage = "dispatch_trusted_dom_primary_selection_verification"
            client.dispatch_middle_click(primary_verify_x, primary_verify_y)
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
        elif args.input == "backspace":
            stage = "dispatch_trusted_dom_backspace_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_backspace_key_a"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-backspace-key-a",
            )
            stage = "dispatch_trusted_dom_backspace_key_a"
            client.dispatch_key_a()
            stage = "wait_for_backspace_key_a_blink_edit"
            key_a_state = wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-backspace",
            )
            validate_backspace_key_a_stage(key_a_state)
            stage = "dispatch_trusted_dom_backspace"
            client.dispatch_backspace()
        elif args.input == "ime-bridge":
            stage = "dispatch_trusted_dom_ime_bridge_activation"
            client.dispatch_primary_click(click_x, click_y)
            stage = "wait_for_ime_bridge_preedit"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-ime-preedit",
            )
            stage = "dispatch_trusted_outer_ime_preedit"
            client.dispatch_ime_preedit()
            stage = f"wait_for_ime_bridge_{args.ime_terminal}"
            wait_for_input_state(
                client,
                browser,
                browser_stderr,
                result_queue,
                deadline,
                state_expression,
                "awaiting-dom-ime-terminal",
            )
            stage = f"dispatch_outer_ime_{args.ime_terminal}"
            if args.ime_terminal == "commit":
                client.dispatch_ime_commit()
            else:
                client.dispatch_ime_cancel()
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
        elif args.input == "select":
            validate_m4_select_result(result, expected_versions=versions)
            input_key = "pointerInput"
        elif args.input == "context-menu":
            validate_m4_context_menu_result(
                result, expected_versions=versions
            )
            input_key = "pointerInput"
        elif args.input == "tooltip":
            validate_m4_tooltip_result(result, expected_versions=versions)
            input_key = "pointerInput"
        elif args.input == "selection":
            validate_m4_selection_result(result, expected_versions=versions)
            input_key = "pointerInput"
        elif args.input == "primary-paste":
            validate_m4_primary_paste_result(
                result, expected_versions=versions
            )
            input_key = "pointerInput"
        elif args.input == "copy-paste":
            validate_m4_copy_paste_result(
                result, expected_versions=versions
            )
            input_key = "keyboardInput"
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
        elif args.input == "backspace":
            validate_m4_backspace_result(
                result, expected_versions=versions
            )
            input_key = "keyboardInput"
        elif args.input == "ime-bridge":
            validate_m4_ime_bridge_result(
                result,
                expected_versions=versions,
                terminal_mode=args.ime_terminal,
            )
            input_key = "imeProxyInput"
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

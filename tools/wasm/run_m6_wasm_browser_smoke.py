#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the manager-owned Wasm Browser smoke under pinned Node.

The explicit --wasm-browser-smoke path first closes an empty source-selected
Browser, then exercises a bounded Views tab strip, top-controls row, and
one-surface in-canvas menu. It navigates that menu to the selected VersionUI
and explicit read-only Settings bootstrap before proving two-tab switching and
close ordering in its Aura/Ozone BrowserView. This mock-canvas harness requires
terminal markers and host-side presentation evidence; a zero process exit alone
cannot certify that the Browser-owned window was visible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from check_m6_chrome_boundary import check_boundary
from m0_common import (
    M0Error,
    REPO_ROOT,
    load_manifest,
    parse_timeout,
    print_context,
    relative_to_repo,
)
from run_node_smoke import node_executable


SENTINEL = "CHROMIUM_WASM_M6_BROWSER"
PASS_MARKER = f"{SENTINEL}:PASS"
READY_MARKER = f"{SENTINEL}:READY"
TOP_CONTROLS_MARKER = "CHROMIUM_WASM_M6_TOP_CONTROLS:PASS"
VIEWS_ACCELERATORS_MARKER = "CHROMIUM_WASM_M6_VIEWS_ACCELERATORS:PASS"
TAB_STRIP_MARKER = "CHROMIUM_WASM_M6_TAB_STRIP:PASS"
VERSION_WEBUI_MARKER = "CHROMIUM_WASM_M6_VERSION_WEBUI:PASS"
SETTINGS_BOOTSTRAP_MARKER = "CHROMIUM_WASM_M6_SETTINGS_BOOTSTRAP:PASS"
BROWSER_MENU_MARKER = "CHROMIUM_WASM_M6_BROWSER_MENU:PASS"
RESULT_PREFIX = f"{SENTINEL}:NODE_EXIT "
NODE_PASS_MARKER = f"{SENTINEL}_NODE:PASS"
SMOKE_SWITCH = "--wasm-browser-smoke"
DEFAULT_MODULE_NAME = "chrome_wasm"
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def runner_source(module_url: str, timeout_ms: int) -> str:
    """Returns the isolated Node harness for one real Browser lifecycle."""
    return f"""
import createModule from {json.dumps(module_url)};

const passMarker = {json.dumps(PASS_MARKER)};
const readyMarker = {json.dumps(READY_MARKER)};
const resultPrefix = {json.dumps(RESULT_PREFIX)};
const result = {{
  abort: null,
  canvasCopies: 0,
  fatalReports: [],
  focusReports: [],
  frameReports: [],
  passObserved: false,
  processExitReports: [],
  readyObserved: false,
  readinessReports: [],
  rejection: null,
  runtimeExitCode: null,
}};
const stdout = [];
const stderr = [];

class MockCanvasContext {{
  createImageData(width, height) {{
    return {{
      width,
      height,
      data: new Uint8ClampedArray(width * height * 4),
    }};
  }}

  putImageData(imageData, x, y) {{
    if (x !== 0 || y !== 0 || !imageData ||
        !(imageData.data instanceof Uint8ClampedArray)) {{
      throw new Error('invalid Wasm frame copy');
    }}
    ++result.canvasCopies;
  }}
}}

class MockCanvas {{
  constructor() {{
    this.width = 0;
    this.height = 0;
    this.clientWidth = 0;
    this.clientHeight = 0;
    this.style = {{}};
    this.tabIndex = 0;
    this.context = new MockCanvasContext();
  }}

  getContext(kind, options) {{
    if (kind !== '2d' || !options || options.alpha !== false) {{
      return null;
    }}
    return this.context;
  }}

  getBoundingClientRect() {{
    return {{
      bottom: this.height,
      height: this.height,
      left: 0,
      right: this.width,
      top: 0,
      width: this.width,
      x: 0,
      y: 0,
    }};
  }}

  addEventListener() {{}}
  removeEventListener() {{}}
  focus() {{}}
}}

globalThis.HTMLCanvasElement = MockCanvas;
globalThis.CustomEvent = class CustomEvent {{
  constructor(type, options = {{}}) {{
    this.type = type;
    this.detail = options.detail;
  }}
}};
globalThis.dispatchEvent = () => true;
globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({{
  protocol: 1,
  reportFatal(message) {{
    result.fatalReports.push(String(message));
  }},
  reportProcessExit(report) {{
    result.processExitReports.push(report);
  }},
  reportFrame(report) {{
    result.frameReports.push(report);
  }},
  reportReadiness(report) {{
    result.readinessReports.push(report);
  }},
  reportOzoneCursor() {{
    return true;
  }},
  reportOzoneFocusState(report) {{
    result.focusReports.push(report);
  }},
  reportOzoneTextInputDelivery() {{}},
  reportOzoneTextInputState() {{}},
}});

let resolveExit;
let rejectExit;
const exitPromise = new Promise((resolve, reject) => {{
  resolveExit = resolve;
  rejectExit = reject;
}});
let timeoutId;
const timeoutPromise = new Promise((_, reject) => {{
  timeoutId = setTimeout(
      () => reject(new Error('runtime timeout')), {timeout_ms});
}});

try {{
  await createModule({{
    arguments: [{json.dumps(SMOKE_SWITCH)}],
    canvas: new MockCanvas(),
    locateFile(path) {{
      return new URL(path, new URL('.', {json.dumps(module_url)})).href;
    }},
    noExitRuntime: false,
    print(line) {{
      const text = String(line);
      stdout.push(text);
      process.stdout.write(text + '\\n');
    }},
    printErr(line) {{
      const text = String(line);
      stderr.push(text);
      process.stderr.write(text + '\\n');
    }},
    onAbort(reason) {{
      result.abort = String(reason);
      rejectExit(new Error('abort: ' + result.abort));
    }},
    onExit(code) {{
      resolveExit(Number(code));
    }},
  }});
  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);
}} catch (error) {{
  result.rejection = String(error);
}} finally {{
  clearTimeout(timeoutId);
}}

result.passObserved = stdout.concat(stderr).some(
    (line) => line.includes(passMarker));
result.readyObserved = stdout.concat(stderr).some(
    (line) => line.includes(readyMarker));
process.stdout.write(resultPrefix + JSON.stringify(result) + '\\n');
if (result.rejection || result.abort || result.runtimeExitCode !== 0) {{
  process.exitCode = 1;
}}
"""


def _require_exact_int(value: object, description: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise M0Error(f"{description} is invalid")
    return value


def _parse_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise M0Error("Node runner emitted no unique Browser result")
    try:
        parsed = json.loads(lines[0][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error("Node runner emitted malformed Browser result") from exc
    if not isinstance(parsed, dict):
        raise M0Error("Node runner Browser result is not an object")
    return parsed


def _validate_frames(reports: object) -> None:
    if not isinstance(reports, list) or not reports:
        raise M0Error("Browser runtime reported no compositor frames")
    previous_frame_id = 0
    for report in reports:
        if not isinstance(report, dict) or report.get("protocol") != 1:
            raise M0Error("Browser frame report is invalid")
        frame_id = _require_exact_int(report.get("id"), "Browser frame ID", minimum=1)
        if frame_id <= previous_frame_id:
            raise M0Error("Browser frame IDs are not monotonic")
        _require_exact_int(report.get("width"), "Browser frame width", minimum=1)
        _require_exact_int(report.get("height"), "Browser frame height", minimum=1)
        timestamp = report.get("timestampMs")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise M0Error("Browser frame timestamp is invalid")
        previous_frame_id = frame_id


def _validate_ready_surface(reports: object) -> None:
    if not isinstance(reports, list) or not any(
        isinstance(report, dict)
        and report.get("protocol") == 1
        and report.get("surfaceReady") is True
        for report in reports
    ):
        raise M0Error("Browser runtime never reported a ready surface")


def _validate_active_focus(reports: object) -> None:
    if not isinstance(reports, list) or not any(
        isinstance(report, dict)
        and report.get("protocol") == 1
        and report.get("keyboardTargetPresent") is True
        and report.get("active") is True
        for report in reports
    ):
        raise M0Error("Browser runtime never observed an active keyboard target")


def validate_result(result: dict[str, Any], output: str) -> None:
    if result.get("runtimeExitCode") != 0:
        raise M0Error("Browser runtime did not exit zero")
    if result.get("abort") is not None or result.get("rejection") is not None:
        raise M0Error("Browser runtime aborted or rejected")
    if result.get("readyObserved") is not True or READY_MARKER not in output:
        raise M0Error("Browser runtime is missing its ready marker")
    if result.get("passObserved") is not True or PASS_MARKER not in output:
        raise M0Error("Browser runtime is missing its pass marker")
    if TOP_CONTROLS_MARKER not in output:
        raise M0Error("Browser runtime is missing its top-controls marker")
    if VIEWS_ACCELERATORS_MARKER not in output:
        raise M0Error("Browser runtime is missing its Views accelerators marker")
    if TAB_STRIP_MARKER not in output:
        raise M0Error("Browser runtime is missing its tab-strip marker")
    if VERSION_WEBUI_MARKER not in output:
        raise M0Error("Browser runtime is missing its Version WebUI marker")
    if SETTINGS_BOOTSTRAP_MARKER not in output:
        raise M0Error("Browser runtime is missing its Settings bootstrap marker")
    if BROWSER_MENU_MARKER not in output:
        raise M0Error("Browser runtime is missing its in-canvas menu marker")
    _require_exact_int(result.get("canvasCopies"), "Browser canvas copy count", minimum=1)

    fatal_reports = result.get("fatalReports")
    if not isinstance(fatal_reports, list) or fatal_reports:
        raise M0Error("Browser host reported a fatal error")

    _validate_frames(result.get("frameReports"))
    _validate_ready_surface(result.get("readinessReports"))
    _validate_active_focus(result.get("focusReports"))

    process_exits = result.get("processExitReports")
    if not isinstance(process_exits, list):
        raise M0Error("Browser process-exit reports are invalid")
    for report in process_exits:
        if not isinstance(report, dict) or report.get("protocol") != 1:
            raise M0Error("Browser process-exit report is invalid")
        if report.get("exitCode") != 0:
            raise M0Error("Browser process reported a nonzero exit")


def run_smoke(
    module: Path, node: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [
                str(node),
                "--experimental-default-type=module",
                "--eval",
                runner_source(module.as_uri(), max(1, int(timeout * 1000))),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout + 5.0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise M0Error("Browser Node process timed out") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the manager-owned Wasm Browser smoke."
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-chrome-m6")
    )
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--timeout", type=parse_timeout, default=30.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")
    if not _MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")

    try:
        out_dir = args.out_dir
        if not out_dir.is_absolute():
            out_dir = REPO_ROOT / out_dir
        out_dir = out_dir.resolve()
        module = out_dir / f"{args.module_name}.js"
        wasm = module.with_suffix(".wasm")
        if not module.is_file() or not wasm.is_file():
            raise M0Error("Browser smoke artifacts are missing")
        check_boundary(out_dir)
        manifest = load_manifest()
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m6_wasm_browser_smoke.py",
            manifest,
            case="manager_owned_browser_lifecycle_m6",
            scope="browser-window-factory-deleter-manager-presentation",
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module=relative_to_repo(module),
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )
        started = time.perf_counter()
        completed = run_smoke(module, node, args.timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        # Keep the full inline observation private to validation. The stable
        # NODE_RESULT below is the reproducible smoke evidence.
        for line in completed.stdout.splitlines(keepends=True):
            if not line.startswith(RESULT_PREFIX):
                sys.stdout.write(line)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise M0Error(
                "Browser Node process exited with status " f"{completed.returncode}"
            )
        result = _parse_result(completed.stdout)
        validate_result(result, f"{completed.stdout}\n{completed.stderr}")
        print(
            f"{SENTINEL}:NODE_RESULT "
            + json.dumps(
                {
                    "artifact": relative_to_repo(module),
                    "canvasCopies": result["canvasCopies"],
                    "focusReports": len(result["focusReports"]),
                    "frameReports": len(result["frameReports"]),
                    "readinessReports": len(result["readinessReports"]),
                    "startupMs": elapsed_ms,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(NODE_PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, KeyError, ValueError) as exc:
        print(f"{SENTINEL}:NODE_FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

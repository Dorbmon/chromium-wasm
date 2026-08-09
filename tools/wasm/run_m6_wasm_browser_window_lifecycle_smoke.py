#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the Wasm browser-window shutdown-lifecycle smoke under pinned Node.

The lifecycle creates a real bounded BrowserWindowInterface, BrowserView, and
one model-owned WebContents before asking its manager to drain the Core's
asynchronous physical destruction. This mock-canvas harness supplies the
normal Ozone host bridge, but intentionally proves the shutdown marker and
zero exit rather than treating frame presentation as the lifecycle criterion.
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


SENTINEL = "CHROMIUM_WASM_M6_BROWSER_WINDOW_LIFECYCLE"
PASS_MARKER = f"{SENTINEL}:PASS"
RESULT_PREFIX = f"{SENTINEL}:NODE_EXIT "
NODE_PASS_MARKER = f"{SENTINEL}_NODE:PASS"
SMOKE_SWITCH = "--wasm-browser-window-lifecycle-smoke"
DEFAULT_MODULE_NAME = "chrome_wasm"
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def runner_source(module_url: str, timeout_ms: int) -> str:
    """Returns the isolated Node harness for one lifecycle shutdown run."""
    return f"""
import createModule from {json.dumps(module_url)};

const passMarker = {json.dumps(PASS_MARKER)};
const resultPrefix = {json.dumps(RESULT_PREFIX)};
const result = {{
  abort: null,
  canvasCopies: 0,
  fatalReports: [],
  focusReports: [],
  frameReports: [],
  markerObserved: false,
  processExitReports: [],
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

result.markerObserved = stdout.concat(stderr).some(
    (line) => line.includes(passMarker));
process.stdout.write(resultPrefix + JSON.stringify(result) + '\\n');
if (result.rejection || result.abort || result.runtimeExitCode !== 0) {{
  process.exitCode = 1;
}}
"""


def _parse_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise M0Error("Node runner emitted no unique lifecycle result")
    try:
        parsed = json.loads(lines[0][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error("Node runner emitted malformed lifecycle result") from exc
    if not isinstance(parsed, dict):
        raise M0Error("Node runner lifecycle result is not an object")
    return parsed


def validate_result(result: dict[str, Any], output: str) -> None:
    if result.get("runtimeExitCode") != 0:
        raise M0Error("lifecycle runtime did not exit zero")
    if result.get("abort") is not None or result.get("rejection") is not None:
        raise M0Error("lifecycle runtime aborted or rejected")
    if PASS_MARKER not in output:
        raise M0Error("lifecycle runtime is missing its pass marker")

    fatal_reports = result.get("fatalReports")
    if not isinstance(fatal_reports, list) or fatal_reports:
        raise M0Error("lifecycle host reported a fatal error")

    process_exits = result.get("processExitReports")
    if not isinstance(process_exits, list):
        raise M0Error("lifecycle process-exit reports are invalid")
    for report in process_exits:
        if not isinstance(report, dict) or report.get("protocol") != 1:
            raise M0Error("lifecycle process-exit report is invalid")
        if report.get("exitCode") != 0:
            raise M0Error("lifecycle process reported a nonzero exit")


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
        raise M0Error("lifecycle Node process timed out") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Wasm BrowserWindow shutdown-lifecycle smoke."
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
            raise M0Error("lifecycle smoke artifacts are missing")
        check_boundary(out_dir)
        manifest = load_manifest()
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m6_wasm_browser_window_lifecycle_smoke.py",
            manifest,
            case="browser_window_lifecycle_shutdown_m6",
            scope="physical-core-destruction-before-profile-shutdown",
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module=relative_to_repo(module),
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )
        started = time.perf_counter()
        completed = run_smoke(module, node, args.timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        # Keep the inline result private to validation. Its compact summary
        # below is stable evidence for the lifecycle gate.
        for line in completed.stdout.splitlines(keepends=True):
            if not line.startswith(RESULT_PREFIX):
                sys.stdout.write(line)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise M0Error(
                "lifecycle Node process exited with status "
                f"{completed.returncode}"
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

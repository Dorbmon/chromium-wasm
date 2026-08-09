#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the Chrome host-to-Ozone accelerator smoke under pinned Node."""

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
import run_m6_wasm_browser_smoke as browser_smoke


SENTINEL = "CHROMIUM_WASM_M6_HOST_ACCELERATORS"
PASS_MARKER = f"{SENTINEL}:PASS"
READY_MARKER = f"{SENTINEL}:READY"
RESULT_PREFIX = f"{SENTINEL}:NODE_EXIT "
NODE_PASS_MARKER = f"{SENTINEL}_NODE:PASS"
SMOKE_SWITCH = "--wasm-browser-host-accelerator-smoke"
DEFAULT_MODULE_NAME = "chrome_wasm"
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _replace_once(source: str, old: str, new: str, description: str) -> str:
    if source.count(old) != 1:
        raise M0Error(f"browser runner no longer has one {description} hook")
    return source.replace(old, new, 1)


def runner_source(module_url: str, timeout_ms: int) -> str:
    """Returns a strict Node host that uses only Chrome's exported key ABI."""
    source = browser_smoke.runner_source(module_url, timeout_ms)
    source = _replace_once(
        source, browser_smoke.PASS_MARKER, PASS_MARKER, "pass marker"
    )
    source = _replace_once(
        source, browser_smoke.READY_MARKER, READY_MARKER, "ready marker"
    )
    source = _replace_once(
        source, browser_smoke.RESULT_PREFIX, RESULT_PREFIX, "result marker"
    )
    source = _replace_once(
        source, browser_smoke.SMOKE_SWITCH, SMOKE_SWITCH, "switch"
    )

    result_anchor = "const result = {\n"
    source = _replace_once(
        source,
        result_anchor,
        "const hostKeyTransitions = [\n"
        "  ['ControlLeft', 1],\n"
        "  ['KeyL', 1],\n"
        "  ['KeyL', 0],\n"
        "  ['ControlLeft', 0],\n"
        "];\n"
        "let wasmModule = null;\n"
        "let hostInputSubmitted = false;\n"
        "const result = {\n"
        "  hostInputCheckAccepted: false,\n"
        "  hostInputTransitions: [],\n",
        "result object",
    )

    promise_anchor = "let timeoutId;\n"
    host_submission = """let timeoutId;
function submitHostAccelerator() {
  if (hostInputSubmitted) {
    return;
  }
  if (!wasmModule) {
    setTimeout(submitHostAccelerator, 0);
    return;
  }
  hostInputSubmitted = true;
  try {
    for (const [code, down] of hostKeyTransitions) {
      const accepted = wasmModule.ccall(
          'chromium_wasm_browser_host_key', 'number', ['string', 'number'],
          [code, down]);
      if (accepted !== 1) {
        throw new Error('host key ABI rejected ' + code + ':' + down);
      }
      result.hostInputTransitions.push({code, down});
    }
    const checkAccepted = wasmModule.ccall(
        'chromium_wasm_browser_host_accelerator_check', 'number', [], []);
    if (checkAccepted !== 1) {
      throw new Error('host accelerator verification was not queued');
    }
    result.hostInputCheckAccepted = true;
  } catch (error) {
    result.rejection = String(error);
    rejectExit(error);
  }
}

"""
    source = _replace_once(
        source, promise_anchor, host_submission, "host submission"
    )
    source = _replace_once(
        source,
        "      stdout.push(text);\n      process.stdout.write(text + '\\n');",
        "      stdout.push(text);\n"
        "      process.stdout.write(text + '\\n');\n"
        "      if (text.includes(readyMarker)) {\n"
        "        result.readyObserved = true;\n"
        "        queueMicrotask(submitHostAccelerator);\n"
        "      }",
        "stdout hook",
    )
    source = _replace_once(
        source,
        "      stderr.push(text);\n      process.stderr.write(text + '\\n');",
        "      stderr.push(text);\n"
        "      process.stderr.write(text + '\\n');\n"
        "      if (text.includes(readyMarker)) {\n"
        "        result.readyObserved = true;\n"
        "        queueMicrotask(submitHostAccelerator);\n"
        "      }",
        "stderr hook",
    )
    source = _replace_once(
        source, "  await createModule({", "  const moduleOptions = {", "factory call"
    )
    source = _replace_once(
        source,
        "    onExit(code) {\n"
        "      resolveExit(Number(code));\n"
        "    },\n"
        "  });\n"
        "  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);",
        "    onExit(code) {\n"
        "      resolveExit(Number(code));\n"
        "    },\n"
        "    onRuntimeInitialized() {\n"
        "      wasmModule = this;\n"
        "    },\n"
        "  };\n"
        "  createModule(moduleOptions).catch((error) => {\n"
        "    result.rejection = String(error);\n"
        "    rejectExit(error);\n"
        "  });\n"
        "  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);",
        "runtime initialization",
    )
    return source


def _parse_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise M0Error("Node runner emitted no unique host-accelerator result")
    try:
        parsed = json.loads(lines[0][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error(
            "Node runner emitted malformed host-accelerator result"
        ) from exc
    if not isinstance(parsed, dict):
        raise M0Error("Node runner host-accelerator result is not an object")
    return parsed


def _validate_host_input(result: dict[str, Any]) -> None:
    expected = [
        {"code": "ControlLeft", "down": 1},
        {"code": "KeyL", "down": 1},
        {"code": "KeyL", "down": 0},
        {"code": "ControlLeft", "down": 0},
    ]
    if result.get("hostInputTransitions") != expected:
        raise M0Error("host accelerator ABI did not accept the exact Ctrl+L records")
    if result.get("hostInputCheckAccepted") is not True:
        raise M0Error("host accelerator verification was not accepted")


def validate_result(result: dict[str, Any], output: str) -> None:
    if result.get("runtimeExitCode") != 0:
        raise M0Error("Host-accelerator runtime did not exit zero")
    if result.get("abort") is not None or result.get("rejection") is not None:
        raise M0Error("Host-accelerator runtime aborted or rejected")
    if result.get("readyObserved") is not True or READY_MARKER not in output:
        raise M0Error("Host-accelerator runtime is missing its ready marker")
    if result.get("passObserved") is not True or PASS_MARKER not in output:
        raise M0Error("Host-accelerator runtime is missing its pass marker")
    _validate_host_input(result)
    browser_smoke._require_exact_int(
        result.get("canvasCopies"), "Host-accelerator canvas copy count", minimum=1
    )

    fatal_reports = result.get("fatalReports")
    if not isinstance(fatal_reports, list) or fatal_reports:
        raise M0Error("Host-accelerator host reported a fatal error")

    browser_smoke._validate_frames(result.get("frameReports"))
    browser_smoke._validate_ready_surface(result.get("readinessReports"))
    browser_smoke._validate_active_focus(result.get("focusReports"))

    process_exits = result.get("processExitReports")
    if not isinstance(process_exits, list):
        raise M0Error("Host-accelerator process-exit reports are invalid")
    for report in process_exits:
        if not isinstance(report, dict) or report.get("protocol") != 1:
            raise M0Error("Host-accelerator process-exit report is invalid")
        if report.get("exitCode") != 0:
            raise M0Error("Host-accelerator process reported a nonzero exit")


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
        raise M0Error("Host-accelerator Node process timed out") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Chrome host-to-Ozone accelerator smoke."
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
            raise M0Error("Host-accelerator smoke artifacts are missing")
        check_boundary(out_dir)
        manifest = load_manifest()
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m6_wasm_browser_host_accelerator_smoke.py",
            manifest,
            case="chrome_host_to_ozone_accelerator_m6",
            scope="physical-key-abi-ozone-aura-views-focus",
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module=relative_to_repo(module),
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )
        started = time.perf_counter()
        completed = run_smoke(module, node, args.timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        for line in completed.stdout.splitlines(keepends=True):
            if not line.startswith(RESULT_PREFIX):
                sys.stdout.write(line)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise M0Error(
                "Host-accelerator Node process exited with status "
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

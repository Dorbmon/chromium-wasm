#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run ordinary no-switch Wasm Browser launch and shutdown under pinned Node."""

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


SENTINEL = "CHROMIUM_WASM_M6_NORMAL_BROWSER"
READY_MARKER = f"{SENTINEL}:READY"
PASS_MARKER = f"{SENTINEL}:PASS"
RESULT_PREFIX = f"{SENTINEL}:NODE_EXIT "
NODE_PASS_MARKER = f"{SENTINEL}_NODE:PASS"
DEFAULT_MODULE_NAME = "chrome_wasm"
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _replace_once(source: str, old: str, new: str, description: str) -> str:
    if source.count(old) != 1:
        raise M0Error(f"browser runner no longer has one {description} hook")
    return source.replace(old, new, 1)


def runner_source(module_url: str, timeout_ms: int) -> str:
    """Returns a strict no-switch host that requests browser-main shutdown."""
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
        source,
        f"arguments: [{json.dumps(browser_smoke.SMOKE_SWITCH)}],",
        "arguments: [],",
        "ordinary launch arguments",
    )

    source = _replace_once(
        source,
        "const result = {\n",
        "let wasmModule = null;\n"
        "let shutdownRequested = false;\n"
        "const result = {\n"
        "  hostShutdownRequests: [],\n",
        "result object",
    )
    source = _replace_once(
        source,
        "let timeoutId;\n",
        "let timeoutId;\n"
        "function hasVisibleBrowserEvidence() {\n"
        "  return result.frameReports.length > 0 &&\n"
        "      result.readinessReports.some((report) =>\n"
        "          report && report.surfaceReady === true) &&\n"
        "      result.focusReports.some((report) =>\n"
        "          report && report.keyboardTargetPresent === true &&\n"
        "          report.active === true);\n"
        "}\n"
        "function maybeRequestHostShutdown() {\n"
        "  if (shutdownRequested || !wasmModule || !result.readyObserved ||\n"
        "      !hasVisibleBrowserEvidence()) {\n"
        "    return;\n"
        "  }\n"
        "  shutdownRequested = true;\n"
        "  try {\n"
        "    const first = wasmModule.ccall(\n"
        "        'chromium_wasm_browser_host_request_shutdown', 'number', [], []);\n"
        "    const second = wasmModule.ccall(\n"
        "        'chromium_wasm_browser_host_request_shutdown', 'number', [], []);\n"
        "    result.hostShutdownRequests.push(first, second);\n"
        "    if (first !== 1 || second !== 0) {\n"
        "      throw new Error('host shutdown ABI did not accept exactly once');\n"
        "    }\n"
        "  } catch (error) {\n"
        "    result.rejection = String(error);\n"
        "    rejectExit(error);\n"
        "  }\n"
        "}\n",
        "shutdown request hook",
    )
    source = _replace_once(
        source,
        "      stdout.push(text);\n      process.stdout.write(text + '\\n');",
        "      stdout.push(text);\n"
        "      process.stdout.write(text + '\\n');\n"
        "      if (text.includes(readyMarker)) {\n"
        "        result.readyObserved = true;\n"
        "        queueMicrotask(maybeRequestHostShutdown);\n"
        "      }",
        "stdout ready hook",
    )
    source = _replace_once(
        source,
        "      stderr.push(text);\n      process.stderr.write(text + '\\n');",
        "      stderr.push(text);\n"
        "      process.stderr.write(text + '\\n');\n"
        "      if (text.includes(readyMarker)) {\n"
        "        result.readyObserved = true;\n"
        "        queueMicrotask(maybeRequestHostShutdown);\n"
        "      }",
        "stderr ready hook",
    )
    source = _replace_once(
        source,
        "  await createModule({",
        "  const moduleOptions = {",
        "factory call",
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
        "      if (result.readyObserved) {\n"
        "        queueMicrotask(maybeRequestHostShutdown);\n"
        "      }\n"
        "    },\n"
        "  };\n"
        "  createModule(moduleOptions).catch((error) => {\n"
        "    result.rejection = String(error);\n"
        "    rejectExit(error);\n"
        "  });\n"
        "  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);",
        "runtime initialization",
    )
    for old, new, description in (
        (
            "  reportFrame(report) {\n"
            "    result.frameReports.push(report);\n"
            "  },",
            "  reportFrame(report) {\n"
            "    result.frameReports.push(report);\n"
            "    queueMicrotask(maybeRequestHostShutdown);\n"
            "  },",
            "frame evidence hook",
        ),
        (
            "  reportReadiness(report) {\n"
            "    result.readinessReports.push(report);\n"
            "  },",
            "  reportReadiness(report) {\n"
            "    result.readinessReports.push(report);\n"
            "    queueMicrotask(maybeRequestHostShutdown);\n"
            "  },",
            "readiness evidence hook",
        ),
        (
            "  reportOzoneFocusState(report) {\n"
            "    result.focusReports.push(report);\n"
            "  },",
            "  reportOzoneFocusState(report) {\n"
            "    result.focusReports.push(report);\n"
            "    queueMicrotask(maybeRequestHostShutdown);\n"
            "  },",
            "focus evidence hook",
        ),
    ):
        source = _replace_once(source, old, new, description)
    return source


def _parse_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise M0Error("Node runner emitted no unique normal Browser result")
    try:
        parsed = json.loads(lines[0][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error("Node runner emitted malformed normal Browser result") from exc
    if not isinstance(parsed, dict):
        raise M0Error("Node runner normal Browser result is not an object")
    return parsed


def validate_result(result: dict[str, Any], output: str) -> None:
    if result.get("runtimeExitCode") != 0:
        raise M0Error("ordinary Browser runtime did not exit zero")
    if result.get("abort") is not None or result.get("rejection") is not None:
        raise M0Error("ordinary Browser runtime aborted or rejected")
    if result.get("readyObserved") is not True or READY_MARKER not in output:
        raise M0Error("ordinary Browser runtime is missing its ready marker")
    if result.get("passObserved") is not True or PASS_MARKER not in output:
        raise M0Error("ordinary Browser runtime is missing its pass marker")
    if result.get("hostShutdownRequests") != [1, 0]:
        raise M0Error("ordinary Browser host shutdown ABI was not one-shot")

    browser_smoke._require_exact_int(
        result.get("canvasCopies"), "ordinary Browser canvas copy count", minimum=1
    )
    fatal_reports = result.get("fatalReports")
    if not isinstance(fatal_reports, list) or fatal_reports:
        raise M0Error("ordinary Browser host reported a fatal error")
    browser_smoke._validate_frames(result.get("frameReports"))
    browser_smoke._validate_ready_surface(result.get("readinessReports"))
    browser_smoke._validate_active_focus(result.get("focusReports"))

    process_exits = result.get("processExitReports")
    if not isinstance(process_exits, list):
        raise M0Error("ordinary Browser process-exit reports are invalid")
    for report in process_exits:
        if not isinstance(report, dict) or report.get("protocol") != 1:
            raise M0Error("ordinary Browser process-exit report is invalid")
        if report.get("exitCode") != 0:
            raise M0Error("ordinary Browser process reported a nonzero exit")


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
        raise M0Error("ordinary Browser Node process timed out") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run ordinary no-switch Wasm Browser launch and shutdown."
    )
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm-chrome-m6"))
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
            raise M0Error("ordinary Browser smoke artifacts are missing")
        check_boundary(out_dir)
        manifest = load_manifest()
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m6_wasm_browser_normal_lifecycle_smoke.py",
            manifest,
            case="ordinary_slim_browser_lifecycle_m6",
            scope="normal-browser-main-host-shutdown-manager-drain",
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
                "ordinary Browser Node process exited with status "
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

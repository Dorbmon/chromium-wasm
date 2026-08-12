#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the fixed in-process DevTools Network.enable smoke under pinned Node.

This is intentionally not a DevTools frontend or remote-debugging harness. It
starts one lifecycle-owned Browser tab, navigates it to one fixed data URL,
waits for native code to issue the one literal Network.enable request through
DevToolsAgentHost, then requires the native success marker, detach marker,
and normal lifecycle teardown in order.
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
import run_m6_wasm_browser_lifecycle_smoke as lifecycle_smoke


SENTINEL = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL"
NETWORK_ENABLE_MARKER = f"{SENTINEL}:NETWORK_ENABLE_OK"
DETACHED_MARKER = f"{SENTINEL}:DETACHED"
LIFECYCLE_PASS_MARKER = lifecycle_smoke.PASS_MARKER
RESULT_PREFIX = f"{SENTINEL}:NODE_EXIT "
NODE_PASS_MARKER = f"{SENTINEL}_NODE:PASS"
SMOKE_SWITCH = "--wasm-browser-devtools-protocol-smoke"
DEFAULT_MODULE_NAME = "chrome_wasm"
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def runner_source(module_url: str, timeout_ms: int) -> str:
    """Returns the existing strict canvas host with M8 protocol identities."""
    # The Node bridge is only presentation/lifecycle plumbing. No DevTools
    # command, protocol result, frontend asset, socket, or pipe passes through
    # it: those remain entirely inside the switch-gated native client.
    return (
        lifecycle_smoke.runner_source(module_url, timeout_ms)
        .replace(lifecycle_smoke.READY_MARKER, NETWORK_ENABLE_MARKER)
        .replace(lifecycle_smoke.RESULT_PREFIX, RESULT_PREFIX)
        .replace(lifecycle_smoke.SMOKE_SWITCH, SMOKE_SWITCH)
    )


def _parse_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise M0Error("Node runner emitted no unique DevTools protocol result")
    try:
        parsed = json.loads(lines[0][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error("Node runner emitted malformed DevTools protocol result") from exc
    if not isinstance(parsed, dict):
        raise M0Error("Node runner DevTools protocol result is not an object")
    return parsed


def _require_unique_ordered_markers(output: str) -> None:
    markers = (
        (NETWORK_ENABLE_MARKER, "Network.enable success"),
        (DETACHED_MARKER, "DevTools detach"),
        (LIFECYCLE_PASS_MARKER, "Browser lifecycle teardown"),
    )
    positions: list[int] = []
    for marker, description in markers:
        count = output.count(marker)
        if count != 1:
            raise M0Error(
                f"DevTools protocol runtime emitted {count} {description} markers"
            )
        positions.append(output.index(marker))
    if positions != sorted(positions):
        raise M0Error(
            "DevTools protocol success, detach, and Browser close markers are "
            "not ordered"
        )


def validate_result(result: dict[str, Any], output: str) -> None:
    # The shared lifecycle harness already proves a real visible Browser, a
    # compositor frame, normal process exit, and no host fatal error. Substitute
    # only its ready marker with the native Network.enable completion marker.
    lifecycle_smoke.validate_result(
        result,
        output.replace(NETWORK_ENABLE_MARKER, lifecycle_smoke.READY_MARKER),
    )
    _require_unique_ordered_markers(output)


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
        raise M0Error("DevTools protocol Node process timed out") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed in-process DevTools Network.enable smoke."
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
            raise M0Error("DevTools protocol smoke artifacts are missing")
        check_boundary(out_dir)
        manifest = load_manifest()
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m8_wasm_browser_devtools_protocol_smoke.py",
            manifest,
            case="fixed_in_process_devtools_network_enable_m8",
            scope="fixed-data-url-primary-webcontents-network-enable-detach-close",
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
                "DevTools protocol Node process exited with status "
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
                    "frameReports": len(result["frameReports"]),
                    "networkEnable": True,
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

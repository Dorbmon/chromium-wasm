#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the bounded standalone V8 ARM32 WebAssembly codegen smoke.

This runner binds one generated, V8-only GN profile to the toolchain manifest
before invoking V8's fixed ARM simulator/Liftoff runtime contract. It is
deliberately separate from the experimental Chrome codegen profile and remains
evidence for one fixed standalone V8 program only.
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

from m0_common import (
    M0Error,
    REPO_ROOT,
    gn_args_text,
    load_manifest,
    parse_timeout,
    relative_to_repo,
)
from run_node_smoke import node_executable


SENTINEL = "CHROMIUM_WASM_M8_V8_ARM32_WASM"
PROFILE_NAME = "m8-v8-arm32-codegen-smoke"
MANIFEST_KEY = "m8_v8_arm32_codegen_smoke_gn_args"
DEFAULT_OUT_DIR = Path("out/wasm-v8-m8-codegen-smoke")
MODULE_NAME = "wasm_v8_arm32_wasm_codegen_smoke.js"
V8_RUNTIME_RUNNER = (
    REPO_ROOT / "v8/tools/wasm/run-arm32-wasm-codegen-smoke.mjs"
)
NODE_PASS_PREFIX = f"{SENTINEL}_NODE:PASS "
NODE_FAIL_PREFIX = f"{SENTINEL}_NODE:FAIL "
MAX_NODE_FAILURE_RECEIPT_BYTES = 1024
GN_ASSIGNMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*) = (?P<value>.+)$"
)
EXPECTED_PROFILE_ASSIGNMENTS = {
    "target_os": '"emscripten"',
    "target_cpu": '"wasm"',
    "enable_chromium_wasm_port": "true",
    "enable_chromium_wasm_v8": "true",
    "enable_chromium_wasm_content": "false",
    "enable_chromium_wasm_chrome": "false",
    "is_debug": "false",
    "dcheck_always_on": "false",
    "v8_enable_debugging_features": "false",
    "v8_enable_verification_features": "false",
    "v8_target_cpu": '"arm"',
    "v8_target_is_simulator": "true",
    "v8_jitless": "false",
    "v8_enable_webassembly": "true",
    "v8_enable_turbofan": "true",
    "v8_enable_drumbrake": "false",
    "v8_enable_sparkplug": "false",
    "v8_enable_maglev": "false",
    "v8_enable_wasm_arm32_codegen_smoke": "true",
}
EXPECTED_NODE_RESULT = {
    "factoryCalls": 1,
    "onAbortCount": 0,
    "onExitCount": 1,
    "status": "pass",
    "stderrLines": 0,
    "stdoutLines": 20,
}
NODE_FAILURE_REQUIRED_KEYS = frozenset(
    {
        "factoryCalls",
        "onAbortCount",
        "onExitCount",
        "reason",
        "status",
        "stderrLines",
        "stdoutLines",
    }
)
NODE_FAILURE_ALLOWED_KEYS = NODE_FAILURE_REQUIRED_KEYS | {"detail"}
NODE_FAILURE_COUNT_KEYS = (
    "factoryCalls",
    "onAbortCount",
    "onExitCount",
    "stderrLines",
    "stdoutLines",
)


def parse_gn_assignments(lines: object) -> dict[str, str]:
    """Parse the closed profile format and reject ambiguity before GN runs."""

    if not isinstance(lines, list):
        raise M0Error("standalone V8 codegen GN profile is not a list")
    assignments: dict[str, str] = {}
    for line in lines:
        if not isinstance(line, str):
            raise M0Error("standalone V8 codegen GN profile has a non-string")
        match = GN_ASSIGNMENT_RE.fullmatch(line)
        if match is None:
            raise M0Error("standalone V8 codegen GN profile has an invalid assignment")
        name = match.group("name")
        if name in assignments:
            raise M0Error("standalone V8 codegen GN profile repeats an assignment")
        assignments[name] = match.group("value")
    return assignments


def validate_profile(manifest: dict[str, object]) -> list[str]:
    """Require the exact non-jitless, non-debug standalone V8 configuration."""

    try:
        profile = manifest[MANIFEST_KEY]
    except KeyError as error:
        raise M0Error("standalone V8 codegen profile is absent from the manifest") from error
    assignments = parse_gn_assignments(profile)
    for name, expected in EXPECTED_PROFILE_ASSIGNMENTS.items():
        if assignments.get(name) != expected:
            raise M0Error(
                "standalone V8 codegen profile does not pin "
                f"{name} = {expected}"
            )
    return list(profile)


def resolve_out_dir(out_dir: Path) -> Path:
    resolved = out_dir.resolve()
    if not resolved.is_dir():
        raise M0Error("the standalone V8 codegen output directory does not exist")
    return resolved


def verify_profile_binding(
    manifest: dict[str, object], out_dir: Path
) -> tuple[Path, Path]:
    """Bind the selected output to precisely the manifest profile bytes."""

    validate_profile(manifest)
    resolved_out_dir = resolve_out_dir(out_dir)
    args_gn = resolved_out_dir / "args.gn"
    if not args_gn.is_file():
        raise M0Error("the standalone V8 codegen args.gn does not exist")
    expected = gn_args_text(manifest, MANIFEST_KEY).encode("utf-8")
    if args_gn.read_bytes() != expected:
        raise M0Error(
            "selected build args do not exactly match the standalone V8 "
            "codegen manifest profile"
        )
    module = (resolved_out_dir / MODULE_NAME).resolve()
    if module.parent != resolved_out_dir:
        raise M0Error("standalone V8 codegen module escapes the output directory")
    wasm = module.with_suffix(".wasm")
    if module.suffix != ".js" or not module.is_file():
        raise M0Error("the standalone V8 codegen JavaScript module does not exist")
    if not wasm.is_file():
        raise M0Error("the standalone V8 codegen Wasm sidecar does not exist")
    return module, wasm


def runner_command(node: Path, module: Path, timeout_ms: int) -> list[str]:
    """Construct only the fixed V8-owned runtime-contract invocation."""

    if timeout_ms < 1 or timeout_ms > 600_000:
        raise M0Error("standalone V8 codegen timeout is outside the V8 contract")
    return [
        str(node),
        "--experimental-default-type=module",
        str(V8_RUNTIME_RUNNER),
        "--timeout-ms",
        str(timeout_ms),
        str(module),
    ]


def validate_runtime_output(
    stdout: str, stderr: str, module: Path, wasm: Path
) -> dict[str, object]:
    """Accept one exact successful receipt from the fixed nested V8 runner."""

    if stderr:
        raise M0Error("standalone V8 codegen runtime wrote stderr on success")
    lines = stdout.splitlines()
    if len(lines) != 1 or not lines[0].startswith(NODE_PASS_PREFIX):
        raise M0Error("standalone V8 codegen runtime receipt is invalid")
    try:
        receipt: Any = json.loads(lines[0][len(NODE_PASS_PREFIX) :])
    except json.JSONDecodeError as error:
        raise M0Error("standalone V8 codegen runtime receipt is not JSON") from error
    if not isinstance(receipt, dict):
        raise M0Error("standalone V8 codegen runtime receipt is not an object")
    expected = {
        "artifact": str(module),
        "wasm": str(wasm),
        **EXPECTED_NODE_RESULT,
    }
    if receipt != expected:
        raise M0Error("standalone V8 codegen runtime receipt disagrees with contract")
    return receipt


def bounded_node_failure_receipt(stdout: str) -> str | None:
    """Return one schema-checked, bounded nested failure receipt if available."""

    receipts = [
        line[len(NODE_FAIL_PREFIX) :]
        for line in stdout.splitlines()
        if line.startswith(NODE_FAIL_PREFIX)
    ]
    if len(receipts) != 1:
        return None
    encoded = receipts[0].encode("utf-8", errors="replace")
    if len(encoded) > MAX_NODE_FAILURE_RECEIPT_BYTES:
        return None
    try:
        receipt: Any = json.loads(receipts[0])
    except json.JSONDecodeError:
        return None
    if not isinstance(receipt, dict):
        return None
    if not NODE_FAILURE_REQUIRED_KEYS.issubset(receipt):
        return None
    if not set(receipt).issubset(NODE_FAILURE_ALLOWED_KEYS):
        return None
    if receipt["status"] != "fail" or not isinstance(receipt["reason"], str):
        return None
    if len(receipt["reason"]) > 240:
        return None
    if "detail" in receipt and (
        not isinstance(receipt["detail"], str) or len(receipt["detail"]) > 240
    ):
        return None
    for name in NODE_FAILURE_COUNT_KEYS:
        value = receipt[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
    normalized = json.dumps(
        receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(normalized.encode("utf-8")) > MAX_NODE_FAILURE_RECEIPT_BYTES:
        return None
    return normalized


def run_smoke(out_dir: Path, timeout_seconds: float) -> dict[str, object]:
    """Verify configuration first, then execute the bounded V8 evidence."""

    manifest = load_manifest()
    module, wasm = verify_profile_binding(manifest, out_dir)
    node = node_executable(manifest)
    if not node.is_file():
        raise M0Error("the pinned Node executable is not installed")
    if not V8_RUNTIME_RUNNER.is_file():
        raise M0Error("the fixed V8 runtime contract runner does not exist")

    timeout_ms = max(1, int(timeout_seconds * 1000))
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            runner_command(node, module, timeout_ms),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5.0,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise M0Error("standalone V8 codegen Node process timed out") from error
    if completed.returncode != 0:
        receipt = bounded_node_failure_receipt(completed.stdout)
        detail = (
            f"; nested Node failure receipt={receipt}" if receipt is not None else ""
        )
        raise M0Error(
            "standalone V8 codegen runtime contract exited with status "
            f"{completed.returncode}{detail}"
        )
    receipt = validate_runtime_output(completed.stdout, completed.stderr, module, wasm)
    return {
        "artifact": relative_to_repo(module),
        "buildProfile": PROFILE_NAME,
        "case": "standalone_v8_arm32_wasm_codegen_m8",
        "elapsedMs": round((time.perf_counter() - started) * 1000, 3),
        "m8GateComplete": False,
        "manifestKey": MANIFEST_KEY,
        "runtime": receipt,
        "scope": "fixed-standalone-v8-arm32-simulator-liftoff-codegen-only",
        "status": "pass",
        "v8ProvenanceEstablished": False,
        "wasmBytes": wasm.stat().st_size,
        "limitations": [
            "does_not_run_chrome_or_blink",
            "does_not_run_webassembly_spec_or_js_api_suites",
            "does_not_establish_immutable_v8_dependency_provenance",
            "does_not_complete_m8",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the standalone ARM32 simulator V8 Wasm codegen smoke."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 1.0:
        parser.error("--timeout must be at least one second")

    try:
        result = run_smoke(args.out_dir, args.timeout)
    except (M0Error, OSError, ValueError) as error:
        print(f"{SENTINEL}:FAIL reason={error}", file=sys.stderr, flush=True)
        return 1
    print(
        f"{SENTINEL}:RESULT "
        + json.dumps(result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(f"{SENTINEL}:PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

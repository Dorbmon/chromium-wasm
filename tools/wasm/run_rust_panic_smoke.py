#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from m0_common import (
    M0Error,
    REPO_ROOT,
    load_manifest,
    parse_timeout,
    print_context,
    relative_to_repo,
)
from run_node_smoke import node_executable


PANIC_PREFIX = "CHROMIUM_WASM_M1_RUST_PANIC"
NODE_PREFIX = "CHROMIUM_WASM_M1_RUST_PANIC_NODE"
EXPECTED_MODULE_NAME = "m1_rust_panic_negative.js"
EXPECTED_PANIC_MARKER = "chromium_wasm_m1_expected_panic"
RUNTIME_START = f"{PANIC_PREFIX}:RUNTIME_START"
PANIC_TRIGGER = (
    f"{PANIC_PREFIX}:PANIC_TRIGGER marker={EXPECTED_PANIC_MARKER}"
)
FALSE_SUCCESS = f"{PANIC_PREFIX}:FALSE_SUCCESS"
MODULE_PASS = f"{PANIC_PREFIX}:PASS"
MODULE_FAIL = f"{PANIC_PREFIX}:FAIL"
POSITIVE_MODULE_PASS = "CHROMIUM_WASM_M1_RUST:PASS"
OBSERVATION_PREFIX = f"{NODE_PREFIX}:OBSERVATION "


def runner_source(module_url: str, timeout_ms: int) -> str:
    return f"""
import createModule from {json.dumps(module_url)};

let resolveTermination;
let terminationObserved = false;
const terminationPromise = new Promise((resolve) => {{
  resolveTermination = resolve;
}});

function recordTermination(kind, details = {{}}) {{
  if (terminationObserved) {{
    return;
  }}
  terminationObserved = true;
  resolveTermination({{kind, ...details}});
}}

const timeoutId = setTimeout(
    () => recordTermination("timeout"), {timeout_ms});
try {{
  Promise.resolve(createModule({{
    print(line) {{
      process.stdout.write(String(line) + "\\n");
    }},
    printErr(line) {{
      process.stderr.write(String(line) + "\\n");
    }},
    onExit(code) {{
      const exitCode = Number(code);
      process.stderr.write(
          {json.dumps(NODE_PREFIX + ":ON_EXIT ")}
          + JSON.stringify({{exitCode}}) + "\\n");
      recordTermination(
          exitCode === 0 ? "zero_exit" : "nonzero_exit", {{exitCode}});
    }},
    onAbort(reason) {{
      const abortReason = String(reason);
      process.stderr.write(
          {json.dumps(NODE_PREFIX + ":ON_ABORT ")}
          + JSON.stringify({{reason: abortReason}}) + "\\n");
      recordTermination("abort", {{reason: abortReason}});
    }},
  }})).catch((error) => {{
    const message = String(error);
    process.stderr.write(
        {json.dumps(NODE_PREFIX + ":MODULE_REJECTION ")}
        + JSON.stringify({{error: message}}) + "\\n");
    recordTermination("rejection", {{error: message}});
  }});
}} catch (error) {{
  const message = String(error);
  process.stderr.write(
      {json.dumps(NODE_PREFIX + ":MODULE_REJECTION ")}
      + JSON.stringify({{error: message}}) + "\\n");
  recordTermination("rejection", {{error: message}});
}}

const observation = await terminationPromise;
clearTimeout(timeoutId);
process.stdout.write(
    {json.dumps(OBSERVATION_PREFIX)}
    + JSON.stringify(observation) + "\\n");
"""


def parse_observation(stdout: str, stderr: str) -> dict[str, object] | None:
    lines = [
        line
        for line in (*stdout.splitlines(), *stderr.splitlines())
        if line.startswith(OBSERVATION_PREFIX)
    ]
    if not lines:
        return None
    if len(lines) != 1:
        raise M0Error("panic runner emitted repeated termination evidence")
    try:
        observation = json.loads(lines[0][len(OBSERVATION_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error("panic runner emitted invalid termination evidence") from exc
    if not isinstance(observation, dict):
        raise M0Error("panic runner termination evidence is not an object")
    return observation


def validate_panic_result(
    returncode: int, stdout: str, stderr: str
) -> str:
    if RUNTIME_START not in stdout:
        raise M0Error(f"panic stdout is missing {RUNTIME_START}")
    if PANIC_TRIGGER not in stdout:
        raise M0Error(f"panic stdout is missing {PANIC_TRIGGER}")
    if stdout.index(RUNTIME_START) >= stdout.index(PANIC_TRIGGER):
        raise M0Error("panic runtime sentinels are out of order")

    module_stdout = "\n".join(
        line
        for line in stdout.splitlines()
        if line != RUNTIME_START
        and line != PANIC_TRIGGER
        and not line.startswith(f"{NODE_PREFIX}:")
    )
    module_stderr = "\n".join(
        line
        for line in stderr.splitlines()
        if not line.startswith(f"{NODE_PREFIX}:")
    )
    if EXPECTED_PANIC_MARKER not in f"{module_stdout}\n{module_stderr}":
        raise M0Error("Rust panic diagnostics are missing the expected marker")

    combined_output = f"{stdout}\n{stderr}"
    for false_success in (
        FALSE_SUCCESS,
        MODULE_PASS,
        MODULE_FAIL,
        POSITIVE_MODULE_PASS,
    ):
        if false_success in combined_output:
            raise M0Error(
                f"panic module falsely reported success with {false_success}"
            )

    observation = parse_observation(stdout, stderr)
    if observation is None:
        if returncode != 0:
            return "process_nonzero"
        raise M0Error("panic module returned without abort or nonzero evidence")

    kind = observation.get("kind")
    if kind == "abort":
        return "abort"
    if kind == "nonzero_exit":
        exit_code = observation.get("exitCode")
        if (
            isinstance(exit_code, bool)
            or not isinstance(exit_code, (int, float))
            or exit_code == 0
        ):
            raise M0Error("panic runner recorded an invalid nonzero exit")
        return "nonzero_exit"
    if kind == "zero_exit":
        raise M0Error("panic module exited successfully")
    if kind == "timeout":
        raise M0Error("panic module timed out")
    if kind == "rejection":
        raise M0Error("panic module rejected without an abort callback")
    raise M0Error(f"panic runner recorded unsupported termination {kind!r}")


def resolve_module(module: Path | None) -> Path:
    if module is None:
        return Path("out/wasm") / EXPECTED_MODULE_NAME
    if module.name != EXPECTED_MODULE_NAME:
        raise M0Error(
            f"Rust panic smoke requires {EXPECTED_MODULE_NAME}"
        )
    return module


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the expected Rust panic in an isolated Wasm process."
    )
    parser.add_argument("module", type=Path, nargs="?")
    parser.add_argument("--timeout", type=parse_timeout, default=20.0)
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        module = resolve_module(args.module)
        if not module.is_absolute():
            module = REPO_ROOT / module
        module = module.resolve()
        wasm = module.with_suffix(".wasm")
        if not module.is_file():
            raise M0Error("the generated Rust panic .js module does not exist")
        if not wasm.is_file():
            raise M0Error(
                "the generated Rust panic .wasm sidecar does not exist"
            )

        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_rust_panic_smoke.py",
            manifest,
            module=relative_to_repo(module),
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )

        try:
            completed = subprocess.run(
                [
                    str(node),
                    "--experimental-default-type=module",
                    "--eval",
                    runner_source(
                        module.as_uri(),
                        max(1, int(args.timeout * 1000)),
                    ),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=args.timeout + 5.0,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise M0Error("Rust panic Node process timeout") from exc

        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        termination = validate_panic_result(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )
        print(
            f"{NODE_PREFIX}:RESULT outcome=expected_abort "
            f"termination={termination}",
            flush=True,
        )
        print(f"{NODE_PREFIX}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"{NODE_PREFIX}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

from m0_common import (
    M0Error,
    REPO_ROOT,
    fail,
    load_manifest,
    parse_timeout,
    print_context,
    relative_to_repo,
)


PASS_SENTINEL = "CHROMIUM_WASM_M0:PASS"
FAIL_SENTINEL = "CHROMIUM_WASM_M0:FAIL"
STDOUT_SENTINEL = "CHROMIUM_WASM_M0:STDOUT"
STDERR_SENTINEL = "CHROMIUM_WASM_M0:STDERR capture=ok"
RUNTIME_START = "CHROMIUM_WASM_M0:RUNTIME_START"
RUNTIME_END = "CHROMIUM_WASM_M0:RUNTIME_END"


def node_executable(manifest: dict[str, object]) -> Path:
    emscripten = manifest["emscripten"]
    assert isinstance(emscripten, dict)
    return (
        REPO_ROOT
        / "third_party/emsdk/node"
        / f"{emscripten['node_version']}_64bit"
        / "bin/node"
    )


def runner_source(module_url: str, timeout_ms: int) -> str:
    return f"""
import createModule from {json.dumps(module_url)};

let resolveExit;
let rejectExit;
const exitPromise = new Promise((resolve, reject) => {{
  resolveExit = resolve;
  rejectExit = reject;
}});
let timeoutId;
const timeoutPromise = new Promise((_, reject) => {{
  timeoutId = setTimeout(
      () => reject(new Error("runtime timeout")), {timeout_ms});
}});

let exitCode;
try {{
  await createModule({{
    print(line) {{
      process.stdout.write(String(line) + "\\n");
    }},
    printErr(line) {{
      process.stderr.write(String(line) + "\\n");
    }},
    onExit(code) {{
      resolveExit(Number(code));
    }},
    onAbort(reason) {{
      rejectExit(new Error("abort: " + String(reason)));
    }},
  }});
  exitCode = await Promise.race([exitPromise, timeoutPromise]);
}} finally {{
  clearTimeout(timeoutId);
}}
process.stdout.write(
    "CHROMIUM_WASM_M0:NODE_EXIT " + JSON.stringify({{exitCode}}) + "\\n");
if (exitCode !== 0) {{
  process.exitCode = 1;
}}
"""


def validate_streams(stdout: str, stderr: str) -> None:
    for sentinel in (RUNTIME_START, RUNTIME_END, STDOUT_SENTINEL, PASS_SENTINEL):
        if sentinel not in stdout:
            raise M0Error(f"stdout is missing {sentinel}")
    if STDERR_SENTINEL not in stderr:
        raise M0Error("stderr capture sentinel is missing")
    if STDERR_SENTINEL in stdout or STDOUT_SENTINEL in stderr:
        raise M0Error("stdout and stderr were not captured separately")
    if FAIL_SENTINEL in stdout or FAIL_SENTINEL in stderr:
        raise M0Error("runtime emitted a failure sentinel")
    if not (
        stdout.index(RUNTIME_START)
        < stdout.index(RUNTIME_END)
        < stdout.index(PASS_SENTINEL)
    ):
        raise M0Error("runtime sentinels are out of order")
    if '"exitCode":0' not in stdout:
        raise M0Error("Node runner did not observe a zero runtime exit")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M0 pthread smoke module with pinned Node."
    )
    parser.add_argument("module", type=Path)
    parser.add_argument("--timeout", type=parse_timeout, default=20.0)
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        module = args.module
        if not module.is_absolute():
            module = REPO_ROOT / module
        module = module.resolve()
        wasm = module.with_suffix(".wasm")
        if module.suffix != ".js" or not module.is_file():
            raise M0Error("the generated .js module does not exist")
        if not wasm.is_file():
            raise M0Error("the generated .wasm sidecar does not exist")

        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_node_smoke.py",
            manifest,
            module=relative_to_repo(module),
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )

        source = runner_source(
            module.as_uri(), max(1, int(args.timeout * 1000))
        )
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [
                    str(node),
                    "--experimental-default-type=module",
                    "--eval",
                    source,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=args.timeout + 5.0,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise M0Error("Node process timeout") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000

        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise M0Error(f"Node exited with status {completed.returncode}")
        validate_streams(completed.stdout, completed.stderr)

        wasm_bytes = wasm.read_bytes()
        result = {
            "artifact": relative_to_repo(module),
            "compressed_wasm_bytes": len(gzip.compress(wasm_bytes, mtime=0)),
            "startup_ms": round(elapsed_ms, 3),
            "status": "pass",
            "wasm_bytes": len(wasm_bytes),
        }
        print(
            "CHROMIUM_WASM_M0:NODE_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print("CHROMIUM_WASM_M0_NODE:PASS", flush=True)
        return 0
    except (M0Error, OSError, TypeError, KeyError, ValueError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())

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
    load_manifest,
    parse_timeout,
    print_context,
    relative_to_repo,
)
from serve import SMOKE_CASES, smoke_case, validate_case_stdout


PASS_SENTINEL = "CHROMIUM_WASM_M0:PASS"
FAIL_SENTINEL = "CHROMIUM_WASM_M0:FAIL"
STDOUT_SENTINEL = "CHROMIUM_WASM_M0:STDOUT"
STDERR_SENTINEL = "CHROMIUM_WASM_M0:STDERR capture=ok"
RUNTIME_START = "CHROMIUM_WASM_M0:RUNTIME_START"
RUNTIME_END = "CHROMIUM_WASM_M0:RUNTIME_END"


def fail_for_case(case_name: str, message: str) -> int:
    prefix = smoke_case(case_name).sentinel_prefix
    print(f"{prefix}:FAIL reason={message}", file=sys.stderr, flush=True)
    return 1


def node_executable(manifest: dict[str, object]) -> Path:
    emscripten = manifest["emscripten"]
    assert isinstance(emscripten, dict)
    return (
        REPO_ROOT
        / "third_party/emsdk/node"
        / f"{emscripten['node_version']}_64bit"
        / "bin/node"
    )


def runner_source(
    module_url: str,
    timeout_ms: int,
    sentinel_prefix: str = "CHROMIUM_WASM_M0",
) -> str:
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
    {json.dumps(sentinel_prefix + ":NODE_EXIT ")}
        + JSON.stringify({{exitCode}}) + "\\n");
if (exitCode !== 0) {{
  process.exitCode = 1;
}}
"""


def validate_streams(
    stdout: str, stderr: str, smoke_case_name: str = "hello"
) -> None:
    selected_case = smoke_case(smoke_case_name)
    for sentinel in selected_case.required_stdout:
        if sentinel not in stdout:
            raise M0Error(f"stdout is missing {sentinel}")
    for sentinel in selected_case.required_stderr:
        if sentinel not in stderr:
            raise M0Error(f"stderr is missing {sentinel}")
    if selected_case.require_separate_streams and (
        any(sentinel in stdout for sentinel in selected_case.required_stderr)
        or STDOUT_SENTINEL in stderr
    ):
        raise M0Error("stdout and stderr were not captured separately")
    failure_sentinel = f"{selected_case.sentinel_prefix}:FAIL"
    if failure_sentinel in stdout or failure_sentinel in stderr:
        raise M0Error("runtime emitted a failure sentinel")
    runtime_start = f"{selected_case.sentinel_prefix}:RUNTIME_START"
    runtime_end = f"{selected_case.sentinel_prefix}:RUNTIME_END"
    pass_sentinel = f"{selected_case.sentinel_prefix}:PASS"
    if not (
        stdout.index(runtime_start)
        < stdout.index(runtime_end)
        < stdout.index(pass_sentinel)
    ):
        raise M0Error("runtime sentinels are out of order")
    validate_case_stdout(smoke_case_name, stdout)
    exit_sentinel = (
        f'{selected_case.sentinel_prefix}:NODE_EXIT {{"exitCode":0}}'
    )
    if exit_sentinel not in stdout:
        raise M0Error("Node runner did not observe a zero runtime exit")
    if stdout.index(pass_sentinel) >= stdout.index(exit_sentinel):
        raise M0Error("Node exit marker preceded the runtime pass marker")


def resolve_case_and_module(
    smoke_case_name: str | None, module: Path | None
) -> tuple[str, Path]:
    if smoke_case_name is None:
        if module is None:
            raise M0Error("a module path or --case is required")
        matching_cases = [
            name
            for name, candidate in SMOKE_CASES.items()
            if candidate.module_name == module.name
        ]
        if not matching_cases:
            raise M0Error(
                "cannot infer the smoke case from the module name; pass --case"
            )
        smoke_case_name = matching_cases[0]

    selected_case = smoke_case(smoke_case_name)
    if module is None:
        module = Path("out/wasm") / selected_case.module_name
    elif module.name != selected_case.module_name:
        raise M0Error(
            f"{smoke_case_name} smoke requires {selected_case.module_name}"
        )
    return smoke_case_name, module


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a Chromium Wasm smoke module with pinned Node."
    )
    parser.add_argument("module", type=Path, nargs="?")
    parser.add_argument("--case", choices=tuple(SMOKE_CASES))
    parser.add_argument("--timeout", type=parse_timeout, default=20.0)
    args = parser.parse_args()

    smoke_case_name = args.case or "hello"
    try:
        manifest = load_manifest()
        smoke_case_name, module = resolve_case_and_module(
            args.case, args.module
        )
        selected_case = smoke_case(smoke_case_name)
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
            case=smoke_case_name,
            module=relative_to_repo(module),
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )

        source = runner_source(
            module.as_uri(),
            max(1, int(args.timeout * 1000)),
            selected_case.sentinel_prefix,
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
        validate_streams(
            completed.stdout, completed.stderr, smoke_case_name
        )

        wasm_bytes = wasm.read_bytes()
        result = {
            "artifact": relative_to_repo(module),
            "compressed_wasm_bytes": len(gzip.compress(wasm_bytes, mtime=0)),
            "startup_ms": round(elapsed_ms, 3),
            "status": "pass",
            "wasm_bytes": len(wasm_bytes),
        }
        print(
            f"{selected_case.sentinel_prefix}:NODE_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{selected_case.sentinel_prefix}_NODE:PASS", flush=True)
        return 0
    except (M0Error, OSError, TypeError, KeyError, ValueError) as exc:
        return fail_for_case(smoke_case_name, str(exc))


if __name__ == "__main__":
    sys.exit(main())

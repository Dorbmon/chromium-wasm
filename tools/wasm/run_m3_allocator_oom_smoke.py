#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
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


MODULE_PREFIX = "CHROMIUM_WASM_M3_ALLOCATOR"
NODE_PREFIX = "CHROMIUM_WASM_M3_ALLOCATOR_NODE"
EXPECTED_MODULE_NAME = "m3_allocator_oom_smoke.js"
MODES = ("unchecked", "ordinary")
OBSERVATION_PREFIX = f"{NODE_PREFIX}:OBSERVATION "
EXPECTED_INITIAL_HEAP_BYTES = 64 * 1024 * 1024
EXPECTED_MAXIMUM_HEAP_BYTES = 2 * 1024 * 1024 * 1024
EXPECTED_ABORT_PROCESS_STATUS = 1
MAX_SAFE_INTEGER = (1 << 53) - 1
LIMIT_PATTERN = re.compile(
    rf"^{MODULE_PREFIX}:LIMIT mode=(?P<mode>unchecked|ordinary) "
    r"current_heap_bytes=(?P<current>[0-9]+) "
    r"max_heap_bytes=(?P<maximum>[0-9]+) "
    r"request_bytes=(?P<request>[0-9]+)$",
    re.MULTILINE,
)


def runner_source(
    module_url: str,
    mode: str,
    timeout_ms: int,
) -> str:
    if mode not in MODES:
        raise M0Error(f"unsupported allocator mode {mode!r}")
    return f"""
import createModule from {json.dumps(module_url)};

const triggerMarker =
    {json.dumps(f"{MODULE_PREFIX}:TRIGGER mode=ordinary allocator=malloc")};
let resolveTermination;
let terminationObserved = false;
let triggerSeen = false;
let baseOomAfterTrigger = false;
const terminationPromise = new Promise((resolve) => {{
  resolveTermination = resolve;
}});

function recordTermination(kind, details = {{}}) {{
  if (terminationObserved) {{
    return;
  }}
  terminationObserved = true;
  resolveTermination({{kind, ...details, baseOomAfterTrigger}});
}}

const timeoutId = setTimeout(
    () => recordTermination("timeout"), {timeout_ms});
try {{
  Promise.resolve(createModule({{
    arguments: [{json.dumps(mode)}],
    print(line) {{
      const text = String(line);
      if (text === triggerMarker) {{
        triggerSeen = true;
      }}
      process.stdout.write(text + "\\n");
    }},
    printErr(line) {{
      const text = String(line);
      if (triggerSeen && text.trimEnd() === "Out of memory") {{
        baseOomAfterTrigger = true;
      }}
      process.stderr.write(text + "\\n");
    }},
    onExit(code) {{
      if (!Number.isSafeInteger(code)) {{
        recordTermination("invalid_exit", {{
          exitCodeType: typeof code,
          exitCode: String(code),
        }});
        return;
      }}
      const exitCode = code;
      recordTermination(
          exitCode === 0 ? "zero_exit" : "nonzero_exit", {{exitCode}});
    }},
    onAbort(reason) {{
      recordTermination("abort", {{reason: String(reason)}});
    }},
  }})).catch((error) => {{
    recordTermination("rejection", {{error: String(error)}});
  }});
}} catch (error) {{
  recordTermination("rejection", {{error: String(error)}});
}}

const observation = await terminationPromise;
clearTimeout(timeoutId);
process.stdout.write(
    {json.dumps(OBSERVATION_PREFIX)}
    + JSON.stringify({{mode: {json.dumps(mode)}, ...observation}}) + "\\n");
"""


def parse_observation(
    stdout: str,
    stderr: str,
    mode: str,
) -> dict[str, object] | None:
    lines = [
        line
        for line in (*stdout.splitlines(), *stderr.splitlines())
        if line.startswith(OBSERVATION_PREFIX)
    ]
    if not lines:
        return None
    if len(lines) != 1:
        raise M0Error(f"{mode} run emitted repeated termination evidence")
    try:
        observation = json.loads(lines[0][len(OBSERVATION_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error(
            f"{mode} run emitted invalid termination evidence"
        ) from exc
    if not isinstance(observation, dict):
        raise M0Error(f"{mode} termination evidence is not an object")
    if observation.get("mode") != mode:
        raise M0Error(f"{mode} termination evidence names the wrong mode")
    return observation


def validate_limit(stdout: str, mode: str) -> tuple[int, int]:
    limit_lines = [
        line
        for line in stdout.splitlines()
        if line.startswith(f"{MODULE_PREFIX}:LIMIT ")
    ]
    if len(limit_lines) != 1:
        raise M0Error(f"{mode} run must emit exactly one linear-memory limit")
    match = LIMIT_PATTERN.fullmatch(limit_lines[0])
    if match is None:
        raise M0Error(f"{mode} run emitted a malformed linear-memory limit")
    if match.group("mode") != mode:
        raise M0Error(f"{mode} run emitted a limit for the wrong mode")
    current = int(match.group("current"))
    maximum = int(match.group("maximum"))
    request = int(match.group("request"))
    if current != EXPECTED_INITIAL_HEAP_BYTES:
        raise M0Error(f"{mode} run did not use the linked initial memory")
    if maximum != EXPECTED_MAXIMUM_HEAP_BYTES:
        raise M0Error(f"{mode} run did not use the linked maximum memory")
    if request != maximum + 1:
        raise M0Error(f"{mode} run did not request beyond maximum memory")
    return current, maximum


def require_ordered(stdout: str, markers: tuple[str, ...], mode: str) -> None:
    positions = []
    for marker in markers:
        occurrences = stdout.count(marker)
        if occurrences == 0:
            raise M0Error(f"{mode} stdout is missing {marker}")
        if occurrences != 1:
            raise M0Error(f"{mode} stdout repeated {marker}")
        positions.append(stdout.index(marker))
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise M0Error(f"{mode} runtime sentinels are out of order")


def validate_observed_exit(
    observation: dict[str, object],
    mode: str,
) -> None:
    kind = observation.get("kind")
    if kind not in ("zero_exit", "nonzero_exit"):
        return
    exit_code = observation.get("exitCode")
    if (
        type(exit_code) is not int
        or abs(exit_code) > MAX_SAFE_INTEGER
        or (kind == "zero_exit" and exit_code != 0)
        or (kind == "nonzero_exit" and exit_code == 0)
    ):
        raise M0Error(f"{mode} run recorded an invalid module exit code")


def validate_unchecked_result(
    returncode: int,
    stdout: str,
    stderr: str,
) -> str:
    validate_limit(stdout, "unchecked")
    require_ordered(
        stdout,
        (
            f"{MODULE_PREFIX}:RUNTIME_START mode=unchecked",
            f"{MODULE_PREFIX}:LIMIT mode=unchecked",
            (
                f"{MODULE_PREFIX}:POLICY mode=unchecked "
                "terminate_on_oom=enabled"
            ),
            f"{MODULE_PREFIX}:CONTROL mode=unchecked success=1",
            (
                f"{MODULE_PREFIX}:HEAP_AFTER mode=unchecked "
                f"heap_bytes={EXPECTED_INITIAL_HEAP_BYTES} unchanged=1"
            ),
            (
                f"{MODULE_PREFIX}:RESULT mode=unchecked "
                "success=0 pointer_null=1"
            ),
            f"{MODULE_PREFIX}:PASS mode=unchecked",
        ),
        "unchecked",
    )
    if f"{MODULE_PREFIX}:FAIL" in f"{stdout}\n{stderr}":
        raise M0Error("unchecked run emitted a failure sentinel")
    if type(returncode) is not int or returncode != 0:
        raise M0Error(
            f"unchecked Node process exited with status {returncode}"
        )

    observation = parse_observation(stdout, stderr, "unchecked")
    if observation is None:
        raise M0Error("unchecked run emitted no termination evidence")
    validate_observed_exit(observation, "unchecked")
    if observation.get("kind") != "zero_exit":
        raise M0Error("unchecked allocation did not exit normally")
    if observation.get("baseOomAfterTrigger") is not False:
        raise M0Error("unchecked run recorded an unexpected Base OOM")
    return "returned_null"


def validate_ordinary_result(
    returncode: int,
    stdout: str,
    stderr: str,
) -> str:
    validate_limit(stdout, "ordinary")
    require_ordered(
        stdout,
        (
            f"{MODULE_PREFIX}:RUNTIME_START mode=ordinary",
            f"{MODULE_PREFIX}:LIMIT mode=ordinary",
            (
                f"{MODULE_PREFIX}:POLICY mode=ordinary "
                "terminate_on_oom=enabled"
            ),
            f"{MODULE_PREFIX}:CONTROL mode=ordinary success=1",
            f"{MODULE_PREFIX}:TRIGGER mode=ordinary allocator=malloc",
        ),
        "ordinary",
    )
    combined = f"{stdout}\n{stderr}"
    for false_success in (
        f"{MODULE_PREFIX}:FALSE_SUCCESS",
        f"{MODULE_PREFIX}:PASS mode=ordinary",
        f"{MODULE_PREFIX}:FAIL",
    ):
        if false_success in combined:
            raise M0Error(
                f"ordinary allocation falsely continued with {false_success}"
            )

    observation = parse_observation(stdout, stderr, "ordinary")
    if observation is None:
        raise M0Error(
            "ordinary allocation returned without termination evidence"
        )

    kind = observation.get("kind")
    validate_observed_exit(observation, "ordinary")
    if kind == "abort":
        if (
            type(returncode) is not int
            or returncode != EXPECTED_ABORT_PROCESS_STATUS
        ):
            raise M0Error(
                "ordinary Node process reported an inconsistent abort status"
            )
        if observation.get("baseOomAfterTrigger") is not True:
            raise M0Error(
                "ordinary allocation is missing a causal Base OOM diagnostic"
            )
        reason = observation.get("reason")
        if not isinstance(reason, str) or not reason:
            raise M0Error("ordinary abort evidence has no reason")
        return "abort"
    if kind == "nonzero_exit":
        raise M0Error("ordinary allocation exited instead of aborting")
    if kind == "zero_exit":
        raise M0Error("ordinary allocation exited successfully")
    if kind == "invalid_exit":
        raise M0Error("ordinary run recorded an invalid module exit code")
    if kind == "timeout":
        raise M0Error("ordinary allocation timed out")
    if kind == "rejection":
        raise M0Error("ordinary module rejected without an abort callback")
    raise M0Error(f"ordinary run recorded unsupported termination {kind!r}")


def resolve_module(module: Path | None) -> Path:
    if module is None:
        return Path("out/wasm-content-m3") / EXPECTED_MODULE_NAME
    if module.name != EXPECTED_MODULE_NAME:
        raise M0Error(f"allocator smoke requires {EXPECTED_MODULE_NAME}")
    return module


def run_mode(
    node: Path,
    module: Path,
    mode: str,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [
                str(node),
                "--experimental-default-type=module",
                "--eval",
                runner_source(
                    module.as_uri(),
                    mode,
                    max(1, int(timeout * 1000)),
                ),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout + 5.0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise M0Error(f"{mode} allocator Node process timeout") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify ordinary and unchecked Chromium Base OOM policies under "
            "pinned Node."
        )
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
            raise M0Error("the generated allocator .js module does not exist")
        if not wasm.is_file():
            raise M0Error(
                "the generated allocator .wasm sidecar does not exist"
            )

        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m3_allocator_oom_smoke.py",
            manifest,
            module=relative_to_repo(module),
            node_version=manifest["emscripten"][
                "node_version"
            ],  # type: ignore[index]
        )

        outcomes: dict[str, str] = {}
        for mode, validator in (
            ("unchecked", validate_unchecked_result),
            ("ordinary", validate_ordinary_result),
        ):
            completed = run_mode(node, module, mode, args.timeout)
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            outcomes[mode] = validator(
                completed.returncode,
                completed.stdout,
                completed.stderr,
            )

        print(
            f"{NODE_PREFIX}:RESULT "
            f"unchecked={outcomes['unchecked']} "
            "ordinary=expected_abort "
            f"ordinary_termination={outcomes['ordinary']}",
            flush=True,
        )
        print(f"{NODE_PREFIX}:PASS", flush=True)
        return 0
    except (M0Error, OSError, TypeError, KeyError, ValueError) as exc:
        print(f"{NODE_PREFIX}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

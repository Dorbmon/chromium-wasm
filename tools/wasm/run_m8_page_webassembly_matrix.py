#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the closed experimental M8 page-WebAssembly browser smoke matrix.

This is test orchestration only.  Each child invocation is the existing fixed
native DevTools protocol smoke, so no caller-selected page expression, Wasm
module, or DevTools command crosses this wrapper.  The matrix deliberately
uses the separate codegen experiment profile and reports that M8 remains
incomplete even if every bounded child probe passes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys

from m0_common import M0Error, REPO_ROOT, parse_timeout
import run_m8_wasm_browser_devtools_protocol_dom_smoke as page_wasm_smoke


SENTINEL = "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_MATRIX"
RUNNER_PATH = Path(__file__).with_name(
    "run_m8_wasm_browser_devtools_protocol_dom_smoke.py"
)
M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE = (
    page_wasm_smoke.M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE
)

# Keep this explicit and closed.  The child runner intentionally permits only
# one of these switches at a time, so every entry gets an independent browser
# process and lifecycle observation.
PAGE_WEBASSEMBLY_MODE_FLAGS = (
    "--page-webassembly",
    "--page-webassembly-memory",
    "--page-webassembly-table",
    "--page-webassembly-table-growth",
    "--page-webassembly-memory-growth",
    "--page-webassembly-exceptions",
    "--page-webassembly-wasm-memory-grow-opcode",
    "--page-webassembly-wasm-table-grow-opcode",
    "--page-webassembly-wasm-throw",
    "--page-webassembly-wasm-throw-payload",
    "--page-webassembly-js-throw-payload",
    "--page-webassembly-instantiate-streaming",
)


@dataclass(frozen=True)
class MatrixOptions:
    """The common, non-page-selected inputs passed to every fixed child."""

    build_profile: str
    browser: Path | None
    out_dir: Path | None
    module_name: str
    diagnostics_dir: Path | None
    no_sandbox: bool
    timeout: float


def _runner_page_webassembly_mode_flags() -> tuple[str, ...]:
    """Return the page modes already accepted by the fixed child runner."""

    return (
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_MEMORY_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_TABLE_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_EXCEPTIONS_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_WASM_THROW_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE}",
        f"--{page_wasm_smoke.PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE}",
    )


def validate_page_webassembly_mode_flags(mode_flags: tuple[str, ...]) -> None:
    """Reject an incomplete, duplicate, reordered, or unknown matrix."""

    if len(mode_flags) != 12:
        raise M0Error("M8 page-WebAssembly matrix must contain exactly 12 modes")
    if any(not isinstance(mode_flag, str) for mode_flag in mode_flags):
        raise M0Error("M8 page-WebAssembly matrix contains a non-string mode")
    if len(set(mode_flags)) != len(mode_flags):
        raise M0Error("M8 page-WebAssembly matrix contains a duplicate mode")
    if mode_flags != _runner_page_webassembly_mode_flags():
        raise M0Error(
            "M8 page-WebAssembly matrix does not match the closed ordered "
            "child-runner modes"
        )


def require_codegen_build_profile(build_profile: str) -> str:
    """Keep this aggregate separate from the default M6 profile."""

    if build_profile != M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE:
        raise M0Error(
            "M8 page-WebAssembly matrix requires --build-profile "
            f"{M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE}"
        )
    return build_profile


def runner_command(
    mode_flag: str,
    options: MatrixOptions,
) -> list[str]:
    """Build one child command from only the closed matrix inputs."""

    validate_page_webassembly_mode_flags(PAGE_WEBASSEMBLY_MODE_FLAGS)
    require_codegen_build_profile(options.build_profile)
    if mode_flag not in PAGE_WEBASSEMBLY_MODE_FLAGS:
        raise M0Error(f"M8 page-WebAssembly matrix has an unknown mode: {mode_flag}")

    command = [
        sys.executable,
        "-B",
        str(RUNNER_PATH),
        "--build-profile",
        options.build_profile,
    ]
    if options.browser is not None:
        command.extend(("--browser", str(options.browser)))
    if options.out_dir is not None:
        command.extend(("--out-dir", str(options.out_dir)))
    command.extend(("--module-name", options.module_name))
    if options.diagnostics_dir is not None:
        command.extend(("--diagnostics-dir", str(options.diagnostics_dir)))
    if options.no_sandbox:
        command.append("--no-sandbox")
    command.extend(("--timeout", str(options.timeout), mode_flag))
    return command


def aggregate_result(options: MatrixOptions) -> dict[str, object]:
    """Create the false-only result emitted after every child passes."""

    validate_page_webassembly_mode_flags(PAGE_WEBASSEMBLY_MODE_FLAGS)
    require_codegen_build_profile(options.build_profile)
    return {
        "protocol": 1,
        "case": "browser_page_webassembly_matrix_m8",
        "status": "pass",
        "buildProfile": options.build_profile,
        "pageWebAssemblyModeCount": len(PAGE_WEBASSEMBLY_MODE_FLAGS),
        "pageWebAssemblyModes": list(PAGE_WEBASSEMBLY_MODE_FLAGS),
        "m8GateComplete": False,
        "limitations": [
            "only_aggregates_fixed_page_webassembly_smokes",
            "does_not_run_page_webassembly_spec_or_js_api_suites",
            "does_not_establish_v8_provenance_or_m8_completion",
        ],
    }


def run_matrix(options: MatrixOptions) -> dict[str, object]:
    """Run each fixed mode once and fail closed on the first child failure."""

    validate_page_webassembly_mode_flags(PAGE_WEBASSEMBLY_MODE_FLAGS)
    require_codegen_build_profile(options.build_profile)
    for mode_flag in PAGE_WEBASSEMBLY_MODE_FLAGS:
        command = runner_command(mode_flag, options)
        print(f"{SENTINEL}:MODE_START {mode_flag}", flush=True)
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
        )
        if completed.returncode != 0:
            raise M0Error(
                "M8 page-WebAssembly matrix mode failed "
                f"{mode_flag}: exit status {completed.returncode}"
            )
        print(f"{SENTINEL}:MODE_PASS {mode_flag}", flush=True)
    return aggregate_result(options)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run every fixed experimental M8 page-WebAssembly smoke."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--module-name", default="chrome_wasm")
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    parser.add_argument(
        "--build-profile",
        default=M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE,
        help=(
            "must be m8-codegen-experiment; this test-only profile is not an "
            "M8 completion gate"
        ),
    )
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")

    options = MatrixOptions(
        build_profile=args.build_profile,
        browser=args.browser,
        out_dir=args.out_dir,
        module_name=args.module_name,
        diagnostics_dir=args.diagnostics_dir,
        no_sandbox=args.no_sandbox,
        timeout=args.timeout,
    )
    try:
        result = run_matrix(options)
    except (M0Error, OSError, subprocess.SubprocessError) as exc:
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
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

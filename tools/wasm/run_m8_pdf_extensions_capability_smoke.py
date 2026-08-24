#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the bounded M8.7 Wasm extensions/PDF boundary witness under Node.

This runner proves only the build flags selected for a standalone Wasm Chrome
target. It does not launch a browser, load an extension, start an extension
worker, access extension storage, parse a PDF, or prove PDF/PDFium support.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from m0_common import M0Error, REPO_ROOT, load_manifest, parse_timeout
from run_node_smoke import node_executable, runner_source


PREFIX = "CHROMIUM_WASM_M8_PDF_EXTENSIONS"
MODULE_NAME = "wasm_pdf_extensions_capability_smoke.js"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
EXPECTED_RESULT = (
    f"{PREFIX}:RESULT extensions=disabled extensions_core=disabled "
    "extension_service=not_selected "
    "extension_background_lifecycle=not_selected "
    "extension_content_scripts=not_selected extension_storage=not_selected "
    "extension_native_messaging=not_selected pdf=disabled pdf_ink2=disabled "
    "pdf_save_to_drive=disabled bundled_pdf_extension=not_selected "
    "pdfium=not_selected pdf_viewer=not_selected"
)
EXPECTED_MARKERS = (
    f"{PREFIX}:RUNTIME_START",
    f"{PREFIX}:PHASE name=extensions_buildflags status=disabled",
    f"{PREFIX}:PHASE name=pdf_buildflags status=disabled",
    EXPECTED_RESULT,
    f"{PREFIX}:RUNTIME_END",
    f"{PREFIX}:PASS",
)


def resolve_module(out_dir: Path) -> Path:
    resolved_out_dir = out_dir.resolve()
    module = (resolved_out_dir / MODULE_NAME).resolve()
    if module.parent != resolved_out_dir:
        raise M0Error("resolved module escapes the selected output directory")
    if module.suffix != ".js" or not module.is_file():
        raise M0Error("the generated extensions/PDF module does not exist")
    if not module.with_suffix(".wasm").is_file():
        raise M0Error("the generated extensions/PDF Wasm sidecar does not exist")
    return module


def validate_streams(stdout: str, stderr: str) -> None:
    if f"{PREFIX}:FAIL" in stdout or f"{PREFIX}:FAIL" in stderr:
        raise M0Error("native extensions/PDF witness emitted a failure marker")
    if stdout.count(f"{PREFIX}:NODE_EXIT {{\"exitCode\":0}}") != 1:
        raise M0Error("Node did not observe exactly one zero native exit")

    previous = -1
    for marker in EXPECTED_MARKERS:
        if stdout.count(marker) != 1:
            raise M0Error(f"stdout must contain exactly one {marker}")
        position = stdout.index(marker)
        if position <= previous:
            raise M0Error("native extensions/PDF markers are out of order")
        previous = position

    exit_marker = f"{PREFIX}:NODE_EXIT {{\"exitCode\":0}}"
    if stdout.index(exit_marker) <= previous:
        raise M0Error("Node exit marker preceded native boundary completion")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M8 Wasm extensions/PDF boundary witness under Node."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=parse_timeout, default=30.0)
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        module = resolve_module(args.out_dir)
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")

        source = runner_source(
            module.as_uri(), max(1, int(args.timeout * 1000)), PREFIX
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

        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise M0Error(f"Node exited with status {completed.returncode}")
        validate_streams(completed.stdout, completed.stderr)

        wasm = module.with_suffix(".wasm")
        result = {
            "artifact": str(module.relative_to(REPO_ROOT)),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "m8GateComplete": False,
            "scope": "compiled-extension-and-pdf-buildflag-boundary-only",
            "status": "pass",
            "wasm_bytes": wasm.stat().st_size,
        }
        print(
            f"{PREFIX}:NODE_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{PREFIX}_NODE:PASS", flush=True)
        return 0
    except (M0Error, OSError, ValueError) as exc:
        print(f"{PREFIX}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

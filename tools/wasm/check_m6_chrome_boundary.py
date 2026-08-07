#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify the generated M6 Chrome Wasm dependency boundary.

The source contracts keep the selected targets narrow, but this guard also
checks the generated GN graph.  In particular, a public dependency added to a
transitive target must not silently reintroduce a desktop Chrome aggregate.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from m0_common import M0Error, REPO_ROOT


SENTINEL = "CHROMIUM_WASM_M6_CHROME_BOUNDARY"
_SOURCE_TARGET = "//chrome:chrome_wasm"
_FORBIDDEN_TARGETS = (
    "//chrome/common:common",
    "//chrome/common:common_lib",
    "//chrome/common:constants",
    "//components/update_client",
    "//components/crash/core/app",
    "//third_party/crashpad/crashpad/util",
)


def check_boundary(out_dir: Path) -> None:
    resolved_out_dir = out_dir.resolve()
    if not resolved_out_dir.is_dir():
        raise M0Error(f"GN output directory is missing: {resolved_out_dir}")

    gn = REPO_ROOT / "buildtools/linux64/gn"
    if not gn.is_file():
        raise M0Error(f"GN executable is missing: {gn}")

    for target in _FORBIDDEN_TARGETS:
        result = subprocess.run(
            [str(gn), "path", str(resolved_out_dir), _SOURCE_TARGET, target],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise M0Error(
                f"gn path failed for {_SOURCE_TARGET} -> {target}: "
                + result.stderr.strip()
            )
        if "No non-data paths found between these two targets." not in result.stdout:
            raise M0Error(
                "M6 Chrome source closure reaches a forbidden target "
                f"({_SOURCE_TARGET} -> {target}):\n{result.stdout.strip()}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that chrome_wasm does not re-enter desktop Chrome aggregates."
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-chrome-m6")
    )
    args = parser.parse_args()
    out_dir = args.out_dir if args.out_dir.is_absolute() else REPO_ROOT / args.out_dir

    try:
        check_boundary(out_dir)
    except (M0Error, OSError) as exc:
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1

    print(f"{SENTINEL}:PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

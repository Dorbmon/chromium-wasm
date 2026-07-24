#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run an emsdk compiler entry point with repository-owned configuration."""

from __future__ import annotations

import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
EMSDK_ROOT = REPO_ROOT / "third_party/emsdk"
SUPPORTED_TOOLS = frozenset(("emcc", "em++"))
DEFAULT_TOOL = "em++"


def split_tool_and_args(arguments: list[str]) -> tuple[str, list[str]]:
    """Return the requested compiler and its arguments.

    GN invokes the driver with an explicit `emcc` selector for C sources. C++
    and Rust linker invocations use the selectorless form so rustc receives a
    linker path containing no embedded command-line arguments.
    """
    if arguments and arguments[0] in SUPPORTED_TOOLS:
        return arguments[0], arguments[1:]
    return DEFAULT_TOOL, arguments


def pinned_environment() -> dict[str, str]:
    """Return an environment that cannot inherit another Emscripten SDK."""
    environment = os.environ.copy()
    for name in tuple(environment):
        if (
            name.startswith(
                (
                    "EM_",
                    "EMBUILDER_",
                    "EMCC_",
                    "EMMAKEN_",
                    "EMSDK_",
                    "EMSCRIPTEN_",
                    "EMTEST_",
                    "_EMCC_",
                )
            )
            or name in (
                "BINARYEN_ROOT",
                "EMPROFILE",
                "EMSDK",
                "EMSCRIPTEN",
            )
        ):
            environment.pop(name)

    python_reldir = (
        REPO_ROOT / "third_party/depot_tools/python3_bin_reldir.txt"
    )
    if not python_reldir.is_file():
        raise RuntimeError("pinned depot_tools Python has not been bootstrapped")
    python = (
        REPO_ROOT
        / "third_party/depot_tools"
        / python_reldir.read_text(encoding="utf-8").strip()
        / "python3"
    )
    if not python.is_file():
        raise RuntimeError("pinned depot_tools Python executable is missing")

    cache = REPO_ROOT / "out/wasm-emscripten-cache"
    environment.update(
        {
            "EM_CACHE": str(cache),
            "EM_CONFIG": str(EMSDK_ROOT / ".emscripten"),
            "EM_PORTS": str(cache / "ports"),
            "EMSDK_PYTHON": str(python),
        }
    )
    return environment


def main() -> int:
    tool_name, arguments = split_tool_and_args(sys.argv[1:])
    tool = EMSDK_ROOT / "upstream/emscripten" / tool_name
    if not tool.is_file():
        print("pinned Emscripten SDK is not installed", file=sys.stderr)
        return 1
    try:
        environment = pinned_environment()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    os.execve(
        tool,
        [str(tool), *arguments],
        environment,
    )


if __name__ == "__main__":
    sys.exit(main())

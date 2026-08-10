#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run an emsdk compiler entry point with repository-owned configuration."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
EMSDK_ROOT = REPO_ROOT / "third_party/emsdk"
SUPPORTED_TOOLS = frozenset(("emcc", "em++"))
DEFAULT_TOOL = "em++"
EMSCRIPTEN_SOURCE_LOCK = REPO_ROOT / "out/wasm-emscripten-source.lock"


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


def acquire_emscripten_source_lock() -> int:
    """Hold a shared source/cache lock until the compiler process exits.

    The optional Emscripten source-pin bootstrap takes the matching exclusive
    lock while replacing the source distribution and its EM_CACHE directory.
    Make the descriptor inheritable so the flock survives ``os.execve`` into
    emcc/em++ and is released only when that compiler invocation exits.
    """
    try:
        EMSCRIPTEN_SOURCE_LOCK.parent.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(
            "Emscripten source update lock escapes the checkout"
        ) from exc
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        EMSCRIPTEN_SOURCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(EMSCRIPTEN_SOURCE_LOCK, flags, 0o600)
    except OSError as exc:
        raise RuntimeError("cannot open Emscripten source update lock") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("Emscripten source update lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        os.set_inheritable(descriptor, True)
    except OSError as exc:
        os.close(descriptor)
        raise RuntimeError("cannot acquire Emscripten source update lock") from exc
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def main() -> int:
    tool_name, arguments = split_tool_and_args(sys.argv[1:])
    try:
        source_lock = acquire_emscripten_source_lock()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        tool = EMSDK_ROOT / "upstream/emscripten" / tool_name
        if not tool.is_file():
            print("pinned Emscripten SDK is not installed", file=sys.stderr)
            return 1
        environment = pinned_environment()
        os.execve(
            tool,
            [str(tool), *arguments],
            environment,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"cannot execute pinned Emscripten compiler: {exc}", file=sys.stderr)
        return 1
    finally:
        os.close(source_lock)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).with_name("toolchain_manifest.json")
M0_BASE_TAG = "wasm-m0-primary-toolchain"
MAX_COMMAND_DIAGNOSTIC_CHARS = 4096
MAX_TIMEOUT_SECONDS = 120.0


class M0Error(RuntimeError):
    pass


def parse_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or timeout > MAX_TIMEOUT_SECONDS
    ):
        raise argparse.ArgumentTypeError(
            f"timeout must be finite and in (0, {MAX_TIMEOUT_SECONDS:g}]"
        )
    return timeout


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    if manifest.get("schema_version") != 1:
        raise M0Error("unsupported toolchain manifest schema")
    return manifest


def gn_args_text(manifest: dict[str, Any]) -> str:
    return "\n".join(manifest["gn_args"]) + "\n"


def relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def print_context(
    script: str, manifest: dict[str, Any], **extra: object
) -> dict[str, object]:
    context: dict[str, object] = {
        "script": script,
        "port_commit": checked_output(["git", "rev-parse", "HEAD"]),
        "m0_base": {
            "tag": M0_BASE_TAG,
            "commit": checked_output(
                ["git", "rev-parse", f"{M0_BASE_TAG}^{{commit}}"]
            ),
        },
        "toolchain_manifest": {
            "path": relative_to_repo(MANIFEST_PATH),
            "schema_version": manifest["schema_version"],
            "sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        },
        "chromium": manifest["chromium"],
        "emscripten": manifest["emscripten"],
        "gn_args": manifest["gn_args"],
    }
    context.update(extra)
    print(
        "CHROMIUM_WASM_M0:CONFIG "
        + json.dumps(context, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    return context


def run(
    command: Sequence[str],
    *,
    cwd: Path = REPO_ROOT,
    capture_output: bool = True,
    check: bool = True,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=check,
            capture_output=capture_output,
            text=True,
            env=process_env,
            timeout=timeout,
        )
    except OSError as exc:
        raise M0Error(
            f"command failed: {shlex.join(command)}: {exc}"
        ) from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        diagnostics = []
        for label in ("stdout", "stderr"):
            output = getattr(exc, label, None)
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            if output:
                diagnostics.append(f"{label}:\n{str(output).strip()}")
        detail = "\n".join(diagnostics)
        if len(detail) > MAX_COMMAND_DIAGNOSTIC_CHARS:
            marker = "\n... command output truncated ...\n"
            context_chars = (
                MAX_COMMAND_DIAGNOSTIC_CHARS - len(marker)
            ) // 2
            detail = (
                detail[:context_chars]
                + marker
                + detail[-context_chars:]
            )
        message = f"command failed: {shlex.join(command)}: {exc}"
        if detail:
            message += f"\n{detail}"
        raise M0Error(message) from exc


def checked_output(command: Sequence[str], *, cwd: Path = REPO_ROOT) -> str:
    return run(command, cwd=cwd).stdout.strip()


def fail(message: str) -> int:
    print(f"CHROMIUM_WASM_M0:FAIL reason={message}", file=sys.stderr, flush=True)
    return 1

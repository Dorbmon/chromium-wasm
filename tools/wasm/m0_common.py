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
TEST262_CHECKOUT_PATH = Path("v8/test/test262/data")
TEST262_DEPS_PATH = "test/test262/data"
TEST262_LICENSE_PATH = Path("LICENSE")
TEST262_REMOTE = (
    "https://chromium.googlesource.com/"
    "external/github.com/tc39/test262.git"
)


class M0Error(RuntimeError):
    pass


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_test262_manifest(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    test262 = manifest.get("test262")
    if not isinstance(test262, dict):
        raise M0Error("toolchain manifest test262 must be an object")
    expected_fields = {
        "path",
        "deps_path",
        "remote",
        "revision",
        "license_path",
        "license_size_bytes",
        "license_sha256",
    }
    if set(test262) != expected_fields:
        raise M0Error("toolchain manifest test262 fields mismatch")

    configured_path = test262.get("path")
    if not isinstance(configured_path, str):
        raise M0Error("Test262 checkout path must be a string")
    path = Path(configured_path)
    if path.is_absolute() or ".." in path.parts:
        raise M0Error("Test262 checkout path must stay in the checkout")
    if configured_path != TEST262_CHECKOUT_PATH.as_posix():
        raise M0Error(
            "Test262 checkout path mismatch: "
            f"expected {TEST262_CHECKOUT_PATH}, got {configured_path}"
        )

    deps_path = test262.get("deps_path")
    if deps_path != TEST262_DEPS_PATH:
        raise M0Error(
            "Test262 V8 DEPS path mismatch: "
            f"expected {TEST262_DEPS_PATH}, got {deps_path}"
        )
    remote = test262.get("remote")
    if remote != TEST262_REMOTE:
        raise M0Error(
            "Test262 remote mismatch: "
            f"expected {TEST262_REMOTE}, got {remote}"
        )
    if not _is_lower_hex(test262.get("revision"), 40):
        raise M0Error(
            "Test262 revision must be a lowercase 40-character Git hash"
        )

    license_path = test262.get("license_path")
    if license_path != TEST262_LICENSE_PATH.as_posix():
        raise M0Error(
            "Test262 license path mismatch: "
            f"expected {TEST262_LICENSE_PATH}, got {license_path}"
        )
    license_size = test262.get("license_size_bytes")
    if (
        isinstance(license_size, bool)
        or not isinstance(license_size, int)
        or license_size <= 0
    ):
        raise M0Error("Test262 license size must be a positive integer")
    if not _is_lower_hex(test262.get("license_sha256"), 64):
        raise M0Error(
            "Test262 license hash must be a lowercase SHA-256"
        )
    return test262


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
    validate_test262_manifest(manifest)
    return manifest


def gn_args_text(
    manifest: dict[str, Any], key: str = "gn_args"
) -> str:
    return "\n".join(manifest[key]) + "\n"


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
        "test262": manifest["test262"],
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

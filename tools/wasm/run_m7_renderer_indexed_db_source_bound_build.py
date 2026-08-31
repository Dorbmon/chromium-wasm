#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Create a local top-level-clean-build receipt for the M7 IndexedDB witness.

The regular outer-reload smoke intentionally labels its served artifact as
``unverified``: a snapshot hash alone does not say which source produced it.
This tool creates a fresh, isolated output from a top-level tracked-clean
checkout and records the checkout tree, pinned Emscripten source distribution,
exact generated GN args, and selected JS/Wasm hashes. The outer-reload runner
can later require that receipt before it changes the artifact label to
``local_top_level_clean_build_emscripten_only_attested``.

This is a cooperative local reproducibility receipt, not independent or
signed supply-chain provenance and not an M7 completion claim.  The checkout
has six documented, untracked bootstrap-tool symlinks in this workspace; they
are allowed only when each is an actual symlink at its exact known path. Every
other tracked, staged, or nonignored untracked top-level change fails the
build receipt. Ignored inputs and nested dependency worktree state are not
inspected or source-bound by this limited receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping


_TOOLS_DIRECTORY = str(Path(__file__).resolve().parent)
if _TOOLS_DIRECTORY not in sys.path:
    sys.path.insert(0, _TOOLS_DIRECTORY)

from check_m6_chrome_boundary import check_boundary
from m0_common import M0Error, REPO_ROOT
from m9_descriptor_snapshot import (
    hash_regular_files,
    snapshot_regular_file,
    snapshot_regular_file_with_identity,
)
import run_m9_clean_build_attestation as clean_build


SENTINEL = "CHROMIUM_WASM_M7_RENDERER_INDEXED_DB_SOURCE_BOUND_BUILD"
PASS_MARKER = f"{SENTINEL}:PASS"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
SCHEMA_VERSION = 1
CASE = "chrome_wasm_m7_renderer_indexed_db_source_bound_build"
SCOPE = (
    "top-level-clean-tracked-checkout-pinned-emscripten-source-distribution-fresh-gn-"
    "renderer-indexed-db-chrome-wasm-build-only"
)
STATUS = "local_top_level_clean_rebuild_only"
RELEASE_STATUS = "not_a_release"
M7_GATE_COMPLETE = False
PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_indexed_db_test"
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_NINJA_TARGET = "chrome_wasm"
PRODUCT_GN_ENABLE_ARGUMENT = "enable_chromium_wasm_m7_profile_indexed_db_test"
GN_ARGS_PROFILE = "m6_chrome_gn_args+renderer_indexed_db_test"
DEFAULT_OUT_DIR = Path(
    "out/attested-m7/wasm-chrome-m7-profile-indexed-db"
)
ATTESTATION_FILENAME = "m7_renderer_indexed_db_source_bound_receipt.json"
ARTIFACT_SOURCE_PROVENANCE = "local_top_level_clean_build_emscripten_only_attested"
BOOTSTRAP_MODE = "verify-only"
BOOTSTRAP_SCOPE = "pinned-emscripten-source-distribution-only"
BOOTSTRAP_MARKER = (
    "CHROMIUM_WASM_EMSCRIPTEN_SOURCE_ONLY:"
    "PINNED_SOURCE_DISTRIBUTION_PASS mode=verify-only"
)
MANIFEST_RELATIVE_PATH = "tools/wasm/toolchain_manifest.json"
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
MAX_RECEIPT_BYTES = 32 * 1024
MAX_GN_ARGS_BYTES = 1024 * 1024
CHROME_WASM_BUILD_TIMEOUT_SECONDS = 10_800.0
GIT_REVISION_LENGTH = 40
SHA256_LENGTH = 64

# These are provisioned toolchain links, not source inputs. Keep this list
# exact: a new untracked path must be examined rather than silently allowed.
ALLOWED_UNTRACKED_TOOL_SYMLINKS = frozenset(
    (
        "build/linux/debian_bullseye_amd64-sysroot",
        "build/linux/debian_bullseye_i386-sysroot",
        "buildtools/linux64",
        "third_party/llvm-build",
        "third_party/node/linux",
        "third_party/rust-toolchain",
    )
)

LIMITATIONS = (
    "cooperative-local-reproducibility-receipt-not-independent-provenance",
    "allows-only-documented-untracked-bootstrap-tool-symlinks",
    "does-not-prove-port-checkout-descends-from-manifest-chromium-revision",
    "does-not-run-a-full-m3-bootstrap",
    "does-not-verify-the-full-chromium-gitlink-dependency-closure",
    "does-not-validate-the-complete-chromium-m3-dependency-and-build-tool-closure",
    "does-not-bind-ignored-worktree-inputs-or-nested-dependency-working-tree-state",
    "does-not-prove-default-profile-persistence-or-general-storage-partitions",
    "does-not-prove-crash-power-loss-directory-durability-or-locking",
    "does-not-complete-m7",
)

_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_M7_SELECTOR_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(enable_chromium_wasm_m7_[a-z0-9_]+)(?![A-Za-z0-9_])"
)
_M7_SELECTED_TRUE_LINE_RE = re.compile(
    r"^[ \t]*"
    + re.escape(PRODUCT_GN_ENABLE_ARGUMENT)
    + r"[ \t]*=[ \t]*true[ \t]*$",
    re.MULTILINE,
)
_RECEIPT_FIELDS = frozenset(
    (
        "artifacts",
        "bootstrap",
        "case",
        "checkout",
        "gn",
        "limitations",
        "m7_gate_complete",
        "output_directory",
        "release_status",
        "schema_version",
        "scope",
        "source_selection",
        "status",
        "toolchain_manifest",
    )
)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _parse_json_object(contents: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise M0Error(f"{description} is invalid") from exc
    if type(value) is not dict:
        raise M0Error(f"{description} is invalid")
    return value


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def _require_exact_fields(
    value: object, fields: frozenset[str], description: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise M0Error(f"renderer IndexedDB source receipt {description} is invalid")
    return value


def _require_revision(value: object, description: str) -> str:
    if type(value) is not str or not _REVISION_RE.fullmatch(value):
        raise M0Error(f"renderer IndexedDB source receipt {description} is invalid")
    return value


def _require_identity(value: object, description: str) -> dict[str, object]:
    identity = _require_exact_fields(value, frozenset(("bytes", "sha256")), description)
    if (
        type(identity["bytes"]) is not int
        or identity["bytes"] <= 0
        or type(identity["sha256"]) is not str
        or not _SHA256_RE.fullmatch(identity["sha256"])
    ):
        raise M0Error(f"renderer IndexedDB source receipt {description} is invalid")
    return {"bytes": identity["bytes"], "sha256": identity["sha256"]}


def _manifest_record(manifest: dict[str, Any], contents: bytes) -> dict[str, object]:
    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
            "rust": manifest["rust"]["source_revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
        }
    except (KeyError, TypeError) as exc:
        raise M0Error("renderer IndexedDB manifest lacks source versions") from exc
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or not all(
            type(value) is str and _REVISION_RE.fullmatch(value)
            for value in versions.values()
        )
    ):
        raise M0Error("renderer IndexedDB manifest source versions are invalid")
    return {
        "path": MANIFEST_RELATIVE_PATH,
        "schema_version": 1,
        "sha256": hashlib.sha256(contents).hexdigest(),
        "versions": {name: str(versions[name]) for name in sorted(versions)},
    }


def capture_manifest() -> tuple[dict[str, Any], dict[str, object], object]:
    """Descriptor-snapshot the manifest and retain its private file identity."""

    capture = snapshot_regular_file_with_identity(
        REPO_ROOT / MANIFEST_RELATIVE_PATH,
        maximum_bytes=MAX_GN_ARGS_BYTES,
        description="renderer IndexedDB source-bound toolchain manifest",
    )
    manifest = _parse_json_object(capture.contents, "renderer IndexedDB manifest")
    # Reuse the established M9 parser before consuming its M6 GN profile.
    clean_build.expected_m6_chrome_gn_args(manifest)
    return manifest, _manifest_record(manifest, capture.contents), capture.pinned_identity


def expected_m7_gn_args_from_m6_args(m6_args: bytes) -> bytes:
    """Append the one permitted M7 selector to self-contained M6 GN args."""

    if type(m6_args) is not bytes or not m6_args or len(m6_args) > MAX_GN_ARGS_BYTES:
        raise M0Error("renderer IndexedDB M6 GN arguments are invalid")
    try:
        text = m6_args.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise M0Error("renderer IndexedDB M6 GN arguments are not UTF-8") from exc
    if "\x00" in text or "\r" in text or not text.endswith("\n"):
        raise M0Error("renderer IndexedDB M6 GN arguments are invalid")
    if _M7_SELECTOR_TOKEN_RE.search(text):
        raise M0Error("renderer IndexedDB M6 GN arguments contain an M7 selection")
    expected = m6_args + f"{PRODUCT_GN_ENABLE_ARGUMENT} = true\n".encode("ascii")
    if len(expected) > MAX_GN_ARGS_BYTES:
        raise M0Error("renderer IndexedDB GN arguments are too large")
    validate_m7_indexed_db_gn_selection(expected)
    return expected


def validate_m7_indexed_db_gn_selection(args_gn: bytes) -> None:
    """Reject every M7 expression except one literal selected-test opt-in.

    GN supports boolean expressions, so inspecting only ``= true`` assignments
    would permit another M7 test through expressions such as ``!false``. This
    intentionally rejects any M7-shaped token in a comment or string too: the
    generated source-bound args do not need one, and ambiguity is not safe for
    this single-artifact receipt.
    """

    if type(args_gn) is not bytes or not args_gn or len(args_gn) > MAX_GN_ARGS_BYTES:
        raise M0Error("renderer IndexedDB GN arguments are invalid")
    try:
        text = args_gn.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise M0Error("renderer IndexedDB GN arguments are not UTF-8") from exc
    if "\x00" in text or "\r" in text:
        raise M0Error("renderer IndexedDB GN arguments are invalid")
    selectors = _M7_SELECTOR_TOKEN_RE.findall(text)
    if selectors != [PRODUCT_GN_ENABLE_ARGUMENT]:
        raise M0Error(
            "renderer IndexedDB GN arguments must contain exactly one selected M7 selector"
        )
    if len(_M7_SELECTED_TRUE_LINE_RE.findall(text)) != 1:
        raise M0Error(
            "renderer IndexedDB GN arguments must use a literal selected M7 opt-in"
        )


def expected_m7_gn_args(manifest: dict[str, Any]) -> bytes:
    return expected_m7_gn_args_from_m6_args(
        clean_build.expected_m6_chrome_gn_args(manifest)
    )


def _capture_exact_gn_args(out_dir: Path, expected: bytes) -> tuple[dict[str, object], object]:
    capture = snapshot_regular_file_with_identity(
        out_dir / "args.gn",
        maximum_bytes=MAX_GN_ARGS_BYTES,
        description="renderer IndexedDB generated GN args",
    )
    if capture.contents != expected:
        raise M0Error("renderer IndexedDB generated GN args differ from the source-bound profile")
    return {
        "bytes": len(capture.contents),
        "profile": GN_ARGS_PROFILE,
        "sha256": hashlib.sha256(capture.contents).hexdigest(),
    }, capture.pinned_identity


def _capture_artifacts(out_dir: Path) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    names = (
        f"{PRODUCT_MODULE_NAME}.js",
        f"{PRODUCT_MODULE_NAME}.wasm",
    )
    captures = hash_regular_files(
        out_dir,
        names,
        maximum_bytes=MAX_ARTIFACT_BYTES,
        description="renderer IndexedDB source-bound artifacts",
    )
    return (
        {name: captures[name].byte_identity() for name in names},
        {name: captures[name].pinned_identity for name in names},
    )


def _relative_output_directory(out_dir: Path) -> str:
    try:
        return out_dir.resolve(strict=True).relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise M0Error("renderer IndexedDB source-bound output is outside the checkout") from exc


def _git_output(arguments: tuple[str, ...], description: str) -> str:
    result = clean_build.run_required_command(["git", *arguments], description)
    if type(result.stdout) is not str:
        raise M0Error(f"{description} did not return text output")
    return result.stdout.rstrip("\n")


def require_clean_attested_checkout() -> None:
    """Require clean tracked source plus only the exact bootstrap symlinks."""

    status = _git_output(
        (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=all",
        ),
        "renderer IndexedDB source-bound Git status",
    )
    unexpected: list[str] = []
    for entry in (value for value in status.split("\0") if value):
        if not entry.startswith("?? "):
            unexpected.append(entry)
            continue
        relative = entry[3:]
        candidate = REPO_ROOT / relative
        if relative not in ALLOWED_UNTRACKED_TOOL_SYMLINKS or not candidate.is_symlink():
            unexpected.append(entry)
    if unexpected:
        preview = ", ".join(unexpected[:3])
        suffix = "" if len(unexpected) <= 3 else ", ..."
        raise M0Error(
            "renderer IndexedDB source-bound build requires a clean tracked "
            f"checkout ({preview}{suffix})"
        )


def checkout_identity() -> dict[str, str]:
    identity = clean_build.checkout_identity()
    return {
        "commit": _require_revision(identity.get("commit"), "checkout commit"),
        "tree": _require_revision(identity.get("tree"), "checkout tree"),
    }


def _bootstrap_command() -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "tools/wasm/bootstrap.py"),
        "--emscripten-source-only",
        "--verify-only",
    ]


def _require_bootstrap_marker(output: object) -> None:
    if type(output) is not str or output.splitlines().count(BOOTSTRAP_MARKER) != 1:
        raise M0Error("renderer IndexedDB bootstrap did not emit its exact pass marker")


def _gn_command(out_dir: Path, args: bytes) -> list[str]:
    try:
        text = args.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise M0Error("renderer IndexedDB GN args are not UTF-8") from exc
    return [
        str(REPO_ROOT / "buildtools/linux64/gn"),
        "gen",
        str(out_dir),
        "--args=" + text,
        "--fail-on-unused-args",
    ]


def _autoninja_command(out_dir: Path) -> list[str]:
    return [
        str(REPO_ROOT / "third_party/depot_tools/autoninja"),
        "-C",
        str(out_dir),
        PRODUCT_NINJA_TARGET,
    ]


def _run_chrome_wasm_build(out_dir: Path) -> None:
    """Build the full selected target within its explicit fresh-build bound."""

    clean_build.run_required_command(
        _autoninja_command(out_dir),
        "renderer IndexedDB fresh chrome_wasm build",
        timeout_seconds=CHROME_WASM_BUILD_TIMEOUT_SECONDS,
    )


def make_receipt(
    *,
    checkout: dict[str, str],
    manifest: dict[str, object],
    gn_args: dict[str, object],
    artifacts: dict[str, dict[str, object]],
    out_dir: Path,
) -> dict[str, object]:
    """Construct a canonical, deliberately non-release M7 build receipt."""

    expected_names = {
        f"{PRODUCT_MODULE_NAME}.js",
        f"{PRODUCT_MODULE_NAME}.wasm",
    }
    if set(checkout) != {"commit", "tree"}:
        raise M0Error("renderer IndexedDB receipt checkout is invalid")
    normalized_checkout = {
        name: _require_revision(checkout[name], f"receipt checkout {name}")
        for name in ("commit", "tree")
    }
    normalized_manifest = _validate_manifest_record(manifest)
    if set(gn_args) != {"bytes", "profile", "sha256"}:
        raise M0Error("renderer IndexedDB receipt GN args are invalid")
    normalized_gn_args = _require_identity(
        {"bytes": gn_args.get("bytes"), "sha256": gn_args.get("sha256")},
        "GN args",
    )
    if gn_args.get("profile") != GN_ARGS_PROFILE:
        raise M0Error("renderer IndexedDB receipt GN args are invalid")
    normalized_gn_args["profile"] = GN_ARGS_PROFILE
    if set(artifacts) != expected_names:
        raise M0Error("renderer IndexedDB receipt artifacts are invalid")
    normalized_artifacts = {
        name: _require_identity(artifacts[name], f"artifact {name}")
        for name in sorted(expected_names)
    }
    return {
        "artifacts": normalized_artifacts,
        "bootstrap": {
            "marker": BOOTSTRAP_MARKER,
            "mode": BOOTSTRAP_MODE,
            "scope": BOOTSTRAP_SCOPE,
        },
        "case": CASE,
        "checkout": normalized_checkout,
        "gn": {
            "args": normalized_gn_args,
            "target": PRODUCT_GN_TARGET,
            "target_build_name": PRODUCT_NINJA_TARGET,
        },
        "limitations": list(LIMITATIONS),
        "m7_gate_complete": M7_GATE_COMPLETE,
        "output_directory": _relative_output_directory(out_dir),
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "source_selection": {
            "gn_enable_argument": PRODUCT_GN_ENABLE_ARGUMENT,
            "module_name": PRODUCT_MODULE_NAME,
        },
        "status": STATUS,
        "toolchain_manifest": normalized_manifest,
    }


def _validate_manifest_record(value: object) -> dict[str, object]:
    manifest = _require_exact_fields(
        value,
        frozenset(("path", "schema_version", "sha256", "versions")),
        "toolchain manifest",
    )
    versions = _require_exact_fields(
        manifest["versions"],
        frozenset(("chromium", "emscripten", "rust", "v8")),
        "toolchain manifest versions",
    )
    if (
        manifest["path"] != MANIFEST_RELATIVE_PATH
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or type(manifest["sha256"]) is not str
        or not _SHA256_RE.fullmatch(manifest["sha256"])
    ):
        raise M0Error("renderer IndexedDB source receipt toolchain manifest is invalid")
    normalized = {
        "path": MANIFEST_RELATIVE_PATH,
        "schema_version": 1,
        "sha256": manifest["sha256"],
        "versions": {
            name: _require_revision(versions[name], f"manifest version {name}")
            for name in sorted(versions)
        },
    }
    return normalized


def validate_receipt_payload(
    value: object,
    *,
    expected_checkout: Mapping[str, str],
    expected_manifest: Mapping[str, object],
    expected_gn_args: bytes,
    expected_artifacts: Mapping[str, Mapping[str, object]],
    out_dir: Path,
) -> dict[str, object]:
    """Validate a receipt against the exact current source and served bytes."""

    receipt = _require_exact_fields(value, _RECEIPT_FIELDS, "schema")
    if (
        type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != SCHEMA_VERSION
        or receipt["case"] != CASE
        or receipt["scope"] != SCOPE
        or receipt["status"] != STATUS
        or receipt["release_status"] != RELEASE_STATUS
        or receipt["m7_gate_complete"] is not False
        or receipt["limitations"] != list(LIMITATIONS)
        or receipt["output_directory"] != _relative_output_directory(out_dir)
    ):
        raise M0Error("renderer IndexedDB source receipt metadata is invalid")
    checkout = _require_exact_fields(receipt["checkout"], frozenset(("commit", "tree")), "checkout")
    normalized_checkout = {
        name: _require_revision(checkout[name], f"checkout {name}")
        for name in ("commit", "tree")
    }
    if normalized_checkout != dict(expected_checkout):
        raise M0Error("renderer IndexedDB source receipt checkout differs from current source")
    manifest = _validate_manifest_record(receipt["toolchain_manifest"])
    if manifest != dict(expected_manifest):
        raise M0Error("renderer IndexedDB source receipt manifest differs from current source")
    bootstrap = _require_exact_fields(
        receipt["bootstrap"],
        frozenset(("marker", "mode", "scope")),
        "bootstrap",
    )
    if bootstrap != {
        "marker": BOOTSTRAP_MARKER,
        "mode": BOOTSTRAP_MODE,
        "scope": BOOTSTRAP_SCOPE,
    }:
        raise M0Error("renderer IndexedDB source receipt bootstrap is invalid")
    source_selection = _require_exact_fields(
        receipt["source_selection"],
        frozenset(("gn_enable_argument", "module_name")),
        "source selection",
    )
    if source_selection != {
        "gn_enable_argument": PRODUCT_GN_ENABLE_ARGUMENT,
        "module_name": PRODUCT_MODULE_NAME,
    }:
        raise M0Error("renderer IndexedDB source receipt source selection is invalid")
    gn = _require_exact_fields(receipt["gn"], frozenset(("args", "target", "target_build_name")), "GN")
    gn_args = _require_exact_fields(
        gn["args"],
        frozenset(("bytes", "profile", "sha256")),
        "GN args",
    )
    actual_gn = _require_identity(
        {"bytes": gn_args["bytes"], "sha256": gn_args["sha256"]},
        "GN args",
    )
    if (
        gn_args["profile"] != GN_ARGS_PROFILE
        or gn["target"] != PRODUCT_GN_TARGET
        or gn["target_build_name"] != PRODUCT_NINJA_TARGET
    ):
        raise M0Error("renderer IndexedDB source receipt GN is invalid")
    expected_gn = _byte_identity(expected_gn_args)
    if actual_gn != expected_gn:
        raise M0Error("renderer IndexedDB source receipt GN args differ from current output")
    artifact_values = _require_exact_fields(
        receipt["artifacts"],
        frozenset((f"{PRODUCT_MODULE_NAME}.js", f"{PRODUCT_MODULE_NAME}.wasm")),
        "artifacts",
    )
    normalized_artifacts = {
        name: _require_identity(artifact_values[name], f"artifact {name}")
        for name in sorted(artifact_values)
    }
    normalized_expected_artifacts = {
        name: _require_identity(expected_artifacts[name], f"expected artifact {name}")
        for name in sorted(expected_artifacts)
    }
    if set(normalized_expected_artifacts) != set(normalized_artifacts):
        raise M0Error("renderer IndexedDB expected artifacts are invalid")
    if normalized_artifacts != normalized_expected_artifacts:
        raise M0Error("renderer IndexedDB source receipt artifacts differ from served bytes")
    return receipt


def _required_flag(name: str, description: str) -> int:
    value = getattr(os, name, None)
    if type(value) is not int or value == 0:
        raise M0Error(f"{description} requires host {name} support")
    return value


def _write_all(descriptor: int, contents: bytes, description: str) -> None:
    view = memoryview(contents)
    while view:
        try:
            written = os.write(descriptor, view)
        except OSError as exc:
            raise M0Error(f"could not write {description}") from exc
        if written <= 0:
            raise M0Error(f"could not write {description}")
        view = view[written:]


def _read_exact(descriptor: int, expected_size: int, description: str) -> bytes:
    """Read one complete receipt generation from an already-open descriptor."""

    remaining = expected_size
    chunks: list[bytes] = []
    while remaining:
        try:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
        except OSError as exc:
            raise M0Error(f"could not read {description}") from exc
        if not chunk:
            raise M0Error(f"{description} changed while it was read")
        chunks.append(chunk)
        remaining -= len(chunk)
    try:
        trailing = os.read(descriptor, 1)
    except OSError as exc:
        raise M0Error(f"could not read {description}") from exc
    if trailing:
        raise M0Error(f"{description} changed while it was read")
    return b"".join(chunks)


def write_receipt(out_dir: Path, receipt: dict[str, object]) -> Path:
    """O_EXCL-write and read back the canonical receipt under the fresh root."""

    contents = _canonical_json_bytes(receipt)
    if not contents or len(contents) > MAX_RECEIPT_BYTES:
        raise M0Error("renderer IndexedDB source receipt is too large")
    output = clean_build.revalidate_output_dir(out_dir)
    root_flags = (
        os.O_RDONLY
        | _required_flag("O_DIRECTORY", "renderer IndexedDB source receipt")
        | _required_flag("O_NOFOLLOW", "renderer IndexedDB source receipt")
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | _required_flag("O_NOFOLLOW", "renderer IndexedDB source receipt")
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        root_descriptor = os.open(output, root_flags)
    except OSError as exc:
        raise M0Error("could not open renderer IndexedDB source receipt output") from exc
    descriptor = -1
    try:
        try:
            descriptor = os.open(ATTESTATION_FILENAME, file_flags, 0o600, dir_fd=root_descriptor)
        except FileExistsError as exc:
            raise M0Error("renderer IndexedDB source receipt already exists") from exc
        _write_all(descriptor, contents, "renderer IndexedDB source receipt")
        try:
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise M0Error("could not finalize renderer IndexedDB source receipt") from exc
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != len(contents):
            raise M0Error("renderer IndexedDB source receipt changed while written")
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed = _read_exact(
            descriptor,
            len(contents),
            "renderer IndexedDB source receipt",
        )
        if observed != contents:
            raise M0Error("renderer IndexedDB source receipt changed while written")
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.close(root_descriptor)
        except OSError:
            pass
    destination = output / ATTESTATION_FILENAME
    if snapshot_regular_file(
        destination,
        maximum_bytes=MAX_RECEIPT_BYTES,
        description="renderer IndexedDB written source receipt",
    ) != contents:
        raise M0Error("renderer IndexedDB source receipt changed after write")
    return destination


def verify_runtime_receipt(
    receipt_path: Path,
    *,
    out_dir: Path,
    served_args_gn: bytes,
    served_artifacts: Mapping[str, bytes],
) -> dict[str, object]:
    """Bind a receipt to the current clean tree and the server's byte copies."""

    output = clean_build.revalidate_output_dir(out_dir)
    expected_receipt_path = output / ATTESTATION_FILENAME
    try:
        if receipt_path.resolve(strict=True) != expected_receipt_path.resolve(strict=True):
            raise M0Error("renderer IndexedDB source receipt is not in the selected output")
    except FileNotFoundError as exc:
        raise M0Error("renderer IndexedDB source receipt is missing") from exc
    require_clean_attested_checkout()
    checkout = checkout_identity()
    manifest, manifest_record, _manifest_identity = capture_manifest()
    expected_args = expected_m7_gn_args(manifest)
    if served_args_gn != expected_args:
        raise M0Error("renderer IndexedDB served GN args are not source-bound")
    expected_names = {
        f"{PRODUCT_MODULE_NAME}.js",
        f"{PRODUCT_MODULE_NAME}.wasm",
    }
    if set(served_artifacts) != expected_names or not all(
        type(contents) is bytes and contents for contents in served_artifacts.values()
    ):
        raise M0Error("renderer IndexedDB served artifacts are invalid")
    artifacts = {
        name: _byte_identity(served_artifacts[name]) for name in sorted(served_artifacts)
    }
    receipt_contents = snapshot_regular_file(
        receipt_path,
        maximum_bytes=MAX_RECEIPT_BYTES,
        description="renderer IndexedDB source-bound receipt",
    )
    receipt = _parse_json_object(receipt_contents, "renderer IndexedDB source receipt")
    if receipt_contents != _canonical_json_bytes(receipt):
        raise M0Error("renderer IndexedDB source receipt is not canonical")
    return validate_receipt_payload(
        receipt,
        expected_checkout=checkout,
        expected_manifest=manifest_record,
        expected_gn_args=expected_args,
        expected_artifacts=artifacts,
        out_dir=output,
    )


def run_source_bound_build(out_dir: Path) -> tuple[dict[str, object], Path]:
    """Build the selected module in a fresh output and persist its receipt."""

    output = clean_build.resolve_new_output_dir(out_dir)
    if output.name != DEFAULT_OUT_DIR.name:
        raise M0Error(
            "renderer IndexedDB source-bound build requires the isolated runtime output leaf"
        )
    require_clean_attested_checkout()
    initial_checkout = checkout_identity()
    manifest, manifest_record, manifest_identity = capture_manifest()
    expected_args = expected_m7_gn_args(manifest)

    bootstrap = clean_build.run_required_command(
        _bootstrap_command(), "renderer IndexedDB pinned bootstrap verify-only check"
    )
    _require_bootstrap_marker(bootstrap.stdout)
    output = clean_build.revalidate_new_output_dir(output)
    clean_build.run_required_command(
        _gn_command(output, expected_args), "renderer IndexedDB fresh GN generation"
    )
    output = clean_build.revalidate_output_dir(output)
    initial_gn_args, initial_gn_identity = _capture_exact_gn_args(output, expected_args)
    check_boundary(output)
    _run_chrome_wasm_build(output)
    output = clean_build.revalidate_output_dir(output)
    final_gn_args, final_gn_identity = _capture_exact_gn_args(output, expected_args)
    if initial_gn_args != final_gn_args or initial_gn_identity != final_gn_identity:
        raise M0Error("renderer IndexedDB generated GN args changed during build")
    artifacts, artifact_identities = _capture_artifacts(output)

    final_manifest, final_manifest_record, final_manifest_identity = capture_manifest()
    final_checkout = checkout_identity()
    require_clean_attested_checkout()
    if initial_checkout != final_checkout:
        raise M0Error("renderer IndexedDB checkout changed during build")
    if manifest_record != final_manifest_record or manifest_identity != final_manifest_identity:
        raise M0Error("renderer IndexedDB manifest changed during build")
    if expected_m7_gn_args(final_manifest) != expected_args:
        raise M0Error("renderer IndexedDB expected GN args changed during build")
    final_artifacts, final_artifact_identities = _capture_artifacts(output)
    if artifacts != final_artifacts or artifact_identities != final_artifact_identities:
        raise M0Error("renderer IndexedDB artifacts changed during build")

    receipt = make_receipt(
        checkout=initial_checkout,
        manifest=final_manifest_record,
        gn_args=final_gn_args,
        artifacts=final_artifacts,
        out_dir=output,
    )
    destination = write_receipt(output, receipt)
    output = clean_build.revalidate_output_dir(output)
    require_clean_attested_checkout()
    if checkout_identity() != initial_checkout:
        raise M0Error("renderer IndexedDB checkout changed while writing receipt")
    post_manifest, post_manifest_record, post_manifest_identity = capture_manifest()
    if (
        final_manifest_record != post_manifest_record
        or final_manifest_identity != post_manifest_identity
        or expected_m7_gn_args(post_manifest) != expected_args
    ):
        raise M0Error("renderer IndexedDB manifest changed while writing receipt")
    post_gn_args, post_gn_identity = _capture_exact_gn_args(output, expected_args)
    post_artifacts, post_artifact_identities = _capture_artifacts(output)
    if (
        post_gn_args != final_gn_args
        or post_gn_identity != final_gn_identity
        or post_artifacts != final_artifacts
        or post_artifact_identities != final_artifact_identities
    ):
        raise M0Error("renderer IndexedDB output changed while writing receipt")
    verify_runtime_receipt(
        destination,
        out_dir=output,
        served_args_gn=expected_args,
        served_artifacts={
            name: snapshot_regular_file(
                output / name,
                maximum_bytes=MAX_ARTIFACT_BYTES,
                description=f"renderer IndexedDB final artifact {name}",
            )
            for name in sorted(final_artifacts)
        },
    )
    return receipt, destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a fresh source-bound Chrome Wasm renderer IndexedDB artifact "
            "and write its local receipt."
        )
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    try:
        receipt, destination = run_source_bound_build(args.out_dir)
        print(
            RESULT_PREFIX
            + _canonical_json_bytes({"receipt": receipt, "path": str(destination)}).decode("utf-8").rstrip("\n"),
            flush=True,
        )
        print(PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError) as exc:
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

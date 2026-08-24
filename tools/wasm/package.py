#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Stage and verify a deterministic, explicitly pre-release Wasm package.

This tool deliberately stages only the self-contained Chrome Wasm executable
and the narrow host files it needs.  It is not a release command: M7 profile
durability, M8 compatibility coverage, and the M9 reliability gate remain
separate requirements.  In particular, the generated VERSION.json always
labels the output as not releasable.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Iterable

if __package__:
    from . import run_m9_clean_build_attestation as clean_build_attestation
    from .m0_common import (
        M0Error,
        REPO_ROOT,
        checked_output,
        load_manifest,
        print_context,
        run,
    )
else:
    import run_m9_clean_build_attestation as clean_build_attestation

    from m0_common import (
        M0Error,
        REPO_ROOT,
        checked_output,
        load_manifest,
        print_context,
        run,
    )


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE"
PACKAGE_SCHEMA_VERSION = 4
HOST_PROTOCOL_VERSION = 1
PACKAGE_RUNTIME_STATUS_PROTOCOL = 1
RELEASE_STATUS = "pre_m7_m8_not_releasable"
PRODUCT_NAME = "chromium-wasm"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
PACKAGE_INPUT_MODULE_NAME = "chrome_wasm"
TOOLCHAIN_MANIFEST_PACKAGE_PATH = "TOOLCHAIN.json"
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
MAX_CLEAN_BUILD_ATTESTATION_BYTES = 1024 * 1024
MAX_TARGET_NOTICE_BYTES = 64 * 1024 * 1024
MAX_TOOLCHAIN_MANIFEST_BYTES = 1024 * 1024
LICENSES_SCRIPT = REPO_ROOT / "tools/licenses/licenses.py"
TARGET_THIRD_PARTY_NOTICES_PATH = "LICENSES/THIRD_PARTY_NOTICES.txt"
TARGET_THIRD_PARTY_NOTICES_MARKER = b"License notice for The Chromium Project"
LICENSES_GN_TARGET = "//chrome:chrome_wasm"
LICENSES_TARGET_OS = "emscripten"

# This is a package truthfulness contract, not a feature-negotiation surface.
# A staged pre-release must carry precisely these literal Boolean values until
# the corresponding milestone gates have independent passing evidence.
EXPECTED_GATE_STATE = {
    "persistent_profile_complete": False,
    "page_webassembly_enabled": False,
    "m8_complete": False,
    "m9_release_complete": False,
}

ARTIFACT_SOURCE_PROVENANCE_UNVERIFIED = "unverified"
ARTIFACT_SOURCE_PROVENANCE_LOCAL_CLEAN_BUILD_ATTESTED = (
    "local_clean_build_attested"
)
ALLOWED_ARTIFACT_SOURCE_PROVENANCE = frozenset(
    (
        ARTIFACT_SOURCE_PROVENANCE_UNVERIFIED,
        ARTIFACT_SOURCE_PROVENANCE_LOCAL_CLEAN_BUILD_ATTESTED,
    )
)

REQUIRED_HEADERS = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}
REQUIRED_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".wasm": "application/wasm",
}

# Keep public package names independent of the fixed `chrome_wasm` input
# module. Package staging intentionally supports that one product module only,
# so its generated target-aware notices remain bound to the copied artifacts.
HOST_ASSETS = (
    ("release_index.html", "index.html"),
    ("release_host.js", "chromium-wasm-host.js"),
    ("chrome_wasm_pointer_input.js", "chromium-wasm-pointer-input.js"),
    (
        "chrome_wasm_release_wisp_config.js",
        "chromium-wasm-release-wisp-config.js",
    ),
    ("chrome_wasm_text_input.js", "chromium-wasm-text-input.js"),
    ("chrome_wasm_clipboard_input.js", "chromium-wasm-clipboard-input.js"),
    (
        "chrome_wasm_storage_estimate.js",
        "chromium-wasm-storage-estimate.js",
    ),
)
STATIC_PACKAGE_PATHS = tuple(destination for _, destination in HOST_ASSETS) + (
    "README.txt",
    "LICENSES/Chromium-LICENSE.txt",
    "LICENSES/PRE_RELEASE_NOTICE.txt",
    TARGET_THIRD_PARTY_NOTICES_PATH,
)
PACKAGE_PATHS = frozenset(
    (
        TOOLCHAIN_MANIFEST_PACKAGE_PATH,
        "VERSION.json",
        "chromium-wasm.js",
        "chromium-wasm.wasm",
        *STATIC_PACKAGE_PATHS,
    )
)

README_TEXT = """Chromium Wasm pre-release package
==================================

This directory is a deterministic staging artifact, not a distributable
Chromium release. Its VERSION.json has release_status
\"pre_m7_m8_not_releasable\". Do not describe it as security-equivalent to
desktop Chromium or as having a persistent browser profile.

Its canonical VERSION.json gate_state is fixed to:

  persistent_profile_complete=false
  page_webassembly_enabled=false
  m8_complete=false
  m9_release_complete=false

Those values are required package metadata, not optional limitations text.

The build.staging_checkout value records only the Git checkout that ran this
staging tool. The copied build artifacts have
build.artifact_source_provenance = \"unverified\"; staging does not assert that
they were built from that checkout.

TOOLCHAIN.json is an exact copy of the checked-out toolchain manifest and its
SHA-256 is bound by VERSION.json. It records configured dependency references,
but does not make a mutable or otherwise unapproved dependency reference an
authorized immutable pin.

Serve this directory from one HTTPS or localhost origin. Every response,
including JavaScript workers and the Wasm binary, must carry:

  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: require-corp
  Cross-Origin-Resource-Policy: same-origin
  X-Content-Type-Options: nosniff

The server must use application/wasm for chromium-wasm.wasm and JavaScript MIME
types for the JavaScript host and generated loader. The host page requires a
cross-origin-isolated context so Chromium's application pthread can run away
from the browser's JavaScript main thread.

WISP is opt-in. Before the release host starts, an operator may install the
versioned public input globalThis.__chromiumWasmReleaseWispV1 with an object
containing version=1 and a secure WSS endpoint whose path ends in "/". The
host accepts no plaintext WS endpoint, credentials, query, fragment, or
additional WISP settings. It validates and copies this input into the
Emscripten module before Chromium starts. If the input is omitted, Chromium
networking is explicitly unavailable; the host does not replace browser
networking with page fetch().

Known non-release limitations:

  * Browser, renderer, services, and GPU work remain in one Wasm process; this
    is not Chromium's desktop sandbox or Site Isolation security model.
  * The Chrome profile is not mounted on a proven durable OPFS backend.
  * This package has not passed the M8 compatibility or M9 stress/reliability
    gate. Its target-aware third-party notices do not complete Emscripten
    toolchain or system-library attribution closure.
  * The recorded staging checkout is not a verified source identity for the
    copied build artifacts.

The in-canvas browser UI is implemented by Chromium. The surrounding page is
only a loader and narrow host bridge.
"""

LICENSE_NOTICE_TEXT = """Pre-release license notice
========================

This directory is not a release artifact and does not contain a complete
third-party attribution bundle. Chromium-LICENSE.txt is copied from this
checkout's top-level Chromium license. THIRD_PARTY_NOTICES.txt is generated by
Chromium's target-aware license tool for //chrome:chrome_wasm with
target_os=emscripten. It does not establish Emscripten toolchain/runtime or
system-library attribution closure. A distributable release must add a
reviewed, complete third-party license closure before its release status can be
changed.
"""


README_LOCAL_CLEAN_BUILD_ATTESTED_TEXT = README_TEXT.replace(
    'The copied build artifacts have\n'
    'build.artifact_source_provenance = "unverified"; staging does not assert that\n'
    'they were built from that checkout.',
    'The copied build artifacts have\n'
    'build.artifact_source_provenance = "local_clean_build_attested"; at staging\n'
    'time they exactly matched a local clean-build attestation for this checkout. '
    'That label requires the manifest Chromium commit to be an ancestor of the '
    'staging checkout; a same-tree rewritten commit is not accepted.',
).replace(
    '  * The recorded staging checkout is not a verified source identity for the\n'
    '    copied build artifacts.',
    '  * The copied module bytes matched a local clean-build attestation at staging\n'
    '    time. This is not release provenance or a completed M9 acceptance result.',
)


class PackageError(M0Error):
    """A package input or staged output violates the release-prep contract."""


def _sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolved_existing_directory(path: Path, description: str) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_dir():
        raise PackageError(f"{description} must be a real existing directory: {path}")
    return resolved


def _resolved_destination(path: Path) -> Path:
    # resolve(strict=False) still resolves all existing parent links. A final
    # symlink is rejected separately so staging cannot replace an unexpected
    # location through a link.
    raw_destination = path.absolute()
    current = Path(raw_destination.anchor)
    for component in raw_destination.parts[1:]:
        if component == ".":
            continue
        if component == "..":
            current = current.parent
            continue
        current /= component
        if current.exists() and current.is_symlink():
            raise PackageError("dist directory must not contain a symlink component")

    destination = path.resolve(strict=False)
    if destination == destination.parent:
        raise PackageError("dist directory must not be a filesystem root")
    if path.exists() and path.is_symlink():
        raise PackageError("dist directory must not be a symlink")
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise PackageError(
            "dist directory parent must be a real existing directory: "
            f"{parent}"
        )
    return destination


def _require_regular_file(path: Path, description: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise PackageError(f"{description} is missing: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise PackageError(f"{description} must be a regular non-symlink file: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise PackageError(f"{description} has an invalid size: {path}")
    return path


def _validate_module_name(module_name: str) -> str:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise PackageError(
            "module name must contain only ASCII letters, digits, or underscores"
        )
    if module_name != PACKAGE_INPUT_MODULE_NAME:
        raise PackageError(
            "package staging only supports the chrome_wasm input module"
        )
    return module_name


def _read_gn_args(path: Path) -> tuple[str, str]:
    _require_regular_file(path, "build args")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError("build args must be UTF-8") from exc
    if "\x00" in text:
        raise PackageError("build args contain a NUL byte")

    arguments = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not arguments:
        raise PackageError("build args must contain at least one argument")
    for argument in arguments:
        # GN labels start with // and are intentionally allowed. Absolute host
        # paths must not leak into a reproducible version manifest.
        if re.search(r'=\s*"/(?!/)', argument) or re.search(
            r'=\s*"[A-Za-z]:[\\/]', argument
        ):
            raise PackageError("build args contain an absolute host path")
    return _sha256_bytes(raw), "\n".join(arguments)


def _canonical_clean_build_attestation(value: object) -> bytes:
    """Return the canonical encoding written by the clean-build runner."""

    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _stable_file_bytes(path: Path, description: str, maximum_bytes: int) -> bytes:
    """Read one bounded regular file while rejecting an observable replacement."""

    _require_regular_file(path, description)
    before = path.stat()
    if before.st_size > maximum_bytes:
        raise PackageError(f"{description} is too large: {path}")
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise PackageError(f"could not read {description}: {path}") from exc
    _require_regular_file(path, description)
    after = path.stat()
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if identity(before) != identity(after) or len(contents) != after.st_size:
        raise PackageError(f"{description} changed while it was read")
    return contents


def _load_clean_build_attestation(
    *, out_dir: Path, attestation_path: Path
) -> dict[str, object]:
    """Load exactly the canonical record paired with this selected output."""

    expected_path = out_dir / clean_build_attestation.ATTESTATION_FILENAME
    _require_regular_file(attestation_path, "clean-build attestation")
    _require_regular_file(expected_path, "clean-build attestation")
    if attestation_path.resolve() != expected_path.resolve():
        raise PackageError(
            "clean-build attestation must be the record in the selected build output"
        )
    contents = _stable_file_bytes(
        expected_path,
        "clean-build attestation",
        MAX_CLEAN_BUILD_ATTESTATION_BYTES,
    )
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {constant}")
            ),
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackageError(f"clean-build attestation is invalid: {exc}") from exc
    if type(value) is not dict:
        raise PackageError("clean-build attestation must contain an object")
    if _canonical_clean_build_attestation(value) != contents:
        raise PackageError(
            "clean-build attestation is not canonical deterministic JSON"
        )
    return value


def _require_attested_manifest_chromium_ancestry(
    manifest: Mapping[str, object], checkout_commit: str
) -> None:
    """Require a commit-level source binding for an attested package label.

    A copied source tree can retain every file while losing its upstream parent
    edge.  That is not sufficient source provenance for the stronger local
    clean-build label, so this check intentionally has no tree-equality
    fallback.
    """

    chromium = manifest.get("chromium")
    if not isinstance(chromium, Mapping):
        raise PackageError("attested package toolchain manifest lacks Chromium")
    chromium_revision = chromium.get("revision")
    if not isinstance(chromium_revision, str) or not GIT_REVISION_RE.fullmatch(
        chromium_revision
    ):
        raise PackageError("attested package Chromium source revision is invalid")
    if not isinstance(checkout_commit, str) or not GIT_REVISION_RE.fullmatch(
        checkout_commit
    ):
        raise PackageError("attested package checkout identity is invalid")
    try:
        run(
            ["git", "cat-file", "-e", f"{chromium_revision}^{{commit}}"]
        )
        run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                chromium_revision,
                checkout_commit,
            ]
        )
    except M0Error as exc:
        raise PackageError(
            "attested package requires the manifest Chromium revision to be an "
            "ancestor of the staging checkout; an identical tree or rewritten "
            "commit is not accepted as source provenance"
        ) from exc


def _expected_clean_build_attestation(
    *,
    out_dir: Path,
    module_name: str,
    manifest: dict[str, Any],
    port_revision: str,
) -> dict[str, object]:
    """Recompute the runner's record against the current clean source state."""

    if module_name != PACKAGE_INPUT_MODULE_NAME:
        raise PackageError(
            "clean-build attestation only supports the chrome_wasm input module"
        )
    try:
        clean_build_attestation.require_clean_top_level_checkout()
        checkout = clean_build_attestation.checkout_identity()
        current_manifest, manifest_identity = (
            clean_build_attestation.load_manifest_snapshot()
        )
        if current_manifest != manifest:
            raise PackageError(
                "clean-build attestation manifest does not match the current checkout"
            )
        _require_attested_manifest_chromium_ancestry(
            current_manifest, checkout["commit"]
        )
        expected_args = clean_build_attestation.expected_m6_chrome_gn_args(
            current_manifest
        )
        gn_args = clean_build_attestation.require_exact_generated_gn_args(
            out_dir, expected_args
        )
        artifacts = clean_build_attestation.module_artifact_records(out_dir)
        expected = clean_build_attestation.make_attestation(
            checkout=checkout,
            manifest=manifest_identity,
            gn_args=gn_args,
            artifacts=artifacts,
            out_dir=out_dir,
        )
    except PackageError:
        raise
    except (
        M0Error,
        clean_build_attestation.M0Error,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise PackageError(
            f"clean-build attestation cannot be validated: {exc}"
        ) from exc
    if port_revision != checkout["commit"]:
        raise PackageError(
            "staging checkout does not match the clean-build attestation checkout"
        )
    return expected


def _validate_clean_build_attestation(
    *,
    out_dir: Path,
    module_name: str,
    manifest: dict[str, Any],
    port_revision: str,
    attestation_path: Path,
) -> dict[str, object]:
    """Bind a requested local attestation to current bytes and source identity."""

    supplied = _load_clean_build_attestation(
        out_dir=out_dir, attestation_path=attestation_path
    )
    expected = _expected_clean_build_attestation(
        out_dir=out_dir,
        module_name=module_name,
        manifest=manifest,
        port_revision=port_revision,
    )
    if supplied != expected:
        raise PackageError(
            "clean-build attestation does not exactly match the selected output "
            "and current clean source identity"
        )
    return supplied


def _validate_staged_attested_module_artifacts(
    staging: Path, attestation: dict[str, object]
) -> None:
    """Require the staged renamed module bytes to retain the attested identity."""

    artifacts = attestation.get("artifacts")
    if type(artifacts) is not dict:
        raise PackageError("clean-build attestation module artifacts are invalid")
    for source_name, staged_name in (
        ("chrome_wasm.js", "chromium-wasm.js"),
        ("chrome_wasm.wasm", "chromium-wasm.wasm"),
    ):
        expected = artifacts.get(source_name)
        if type(expected) is not dict:
            raise PackageError("clean-build attestation module artifacts are invalid")
        staged = staging / staged_name
        _require_regular_file(staged, f"staged attested module artifact {staged_name}")
        if (
            staged.stat().st_size != expected.get("bytes")
            or sha256_file(staged) != expected.get("sha256")
        ):
            raise PackageError(
                "staged module artifact does not match the clean-build attestation: "
                f"{staged_name}"
            )


def _readme_text(artifact_source_provenance: str) -> str:
    if artifact_source_provenance == ARTIFACT_SOURCE_PROVENANCE_UNVERIFIED:
        return README_TEXT
    if (
        artifact_source_provenance
        == ARTIFACT_SOURCE_PROVENANCE_LOCAL_CLEAN_BUILD_ATTESTED
    ):
        return README_LOCAL_CLEAN_BUILD_ATTESTED_TEXT
    raise PackageError("artifact source provenance is invalid")


def _copy_file(source: Path, destination: Path) -> None:
    _require_regular_file(source, "package input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o644)
    # Artifact bytes, not local mtimes, are the reproducibility identity. Set
    # a stable timestamp too so a later archive operation starts deterministic.
    os.utime(destination, (0, 0), follow_symlinks=False)


def _write_file(destination: Path, contents: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(contents)
    destination.chmod(0o644)
    os.utime(destination, (0, 0), follow_symlinks=False)


def _generate_target_third_party_notices(*, out_dir: Path, destination: Path) -> None:
    """Generate one bounded Chromium-target notice file in private staging.

    Chromium's license tool resolves third-party metadata from the selected GN
    target rather than from a broad source-tree scan.  This is intentionally a
    target-level notice only: packaging must not infer an Emscripten runtime or
    system-library attribution closure from it.
    """

    _require_regular_file(LICENSES_SCRIPT, "Chromium license generator")
    if destination.exists():
        raise PackageError("target third-party notices destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(
            [
                sys.executable,
                str(LICENSES_SCRIPT),
                "license_file",
                "--gn-out-dir",
                str(out_dir),
                "--gn-target",
                LICENSES_GN_TARGET,
                "--target-os",
                LICENSES_TARGET_OS,
                "--format",
                "notice",
                str(destination),
            ],
            cwd=REPO_ROOT,
            timeout=120.0,
        )
    except M0Error as exc:
        raise PackageError(
            f"could not generate target third-party notices: {exc}"
        ) from exc

    contents = _stable_file_bytes(
        destination,
        "target third-party notices",
        MAX_TARGET_NOTICE_BYTES,
    )
    if TARGET_THIRD_PARTY_NOTICES_MARKER not in contents:
        raise PackageError("target third-party notices are not Chromium notice output")
    # The generator preserves its previous mtime when it can. Rewriting the
    # checked bytes gives every package artifact a deterministic mode and
    # timestamp before VERSION.json records its hash.
    _write_file(destination, contents)


def _tree_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise PackageError(f"package tree contains a symlink: {relative}")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise PackageError(f"package tree contains a non-regular file: {relative}")
        paths.append(relative)
    return sorted(paths)


def _file_records(root: Path, paths: Iterable[str]) -> list[dict[str, object]]:
    records = []
    for relative in sorted(paths):
        path = root / relative
        _require_regular_file(path, f"staged package artifact {relative}")
        records.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def _manifest_versions(manifest: dict[str, Any]) -> dict[str, str]:
    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
        }
    except (KeyError, TypeError) as exc:
        raise PackageError("toolchain manifest lacks a package version field") from exc
    if not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise PackageError("toolchain manifest contains an invalid package revision")
    return versions


def _version_manifest(
    *,
    manifest: dict[str, Any],
    manifest_sha256: str,
    port_revision: str,
    module_name: str,
    gn_args_sha256: str,
    gn_args: str,
    artifacts: list[dict[str, object]],
    artifact_source_provenance: str,
) -> dict[str, object]:
    if not GIT_REVISION_RE.fullmatch(port_revision):
        raise PackageError(
            "staging checkout must be a lowercase 40-character Git hash"
        )
    if artifact_source_provenance not in ALLOWED_ARTIFACT_SOURCE_PROVENANCE:
        raise PackageError("artifact source provenance is invalid")
    source_identity_limitation = (
        "The staging checkout is not verified as the source identity of the copied "
        "build artifacts."
        if artifact_source_provenance == ARTIFACT_SOURCE_PROVENANCE_UNVERIFIED
        else (
            "The copied module bytes matched a local clean-build attestation at "
            "staging time; this is not release provenance or completed M9 validation."
        )
    )
    return {
        "artifacts": artifacts,
        "build": {
            "artifact_source_provenance": artifact_source_provenance,
            "gn_args": gn_args.split("\n"),
            "gn_args_sha256": gn_args_sha256,
            "input_module_name": module_name,
            "resource_delivery": "embedded-in-wasm-current-build",
            "staging_checkout": port_revision,
        },
        "gate_state": EXPECTED_GATE_STATE.copy(),
        "host": {
            "bridge_protocol": HOST_PROTOCOL_VERSION,
            "mime_types": REQUIRED_MIME_TYPES,
            "required_headers": REQUIRED_HEADERS,
        },
        "known_limitations": [
            "M7 durable OPFS profile integration is incomplete.",
            "The gate_state records persistent_profile_complete=false and "
            "page_webassembly_enabled=false.",
            "M8 compatibility coverage is incomplete.",
            "M9 stress, reliability, and final release validation are incomplete.",
            "The single-process Wasm port is not security-equivalent to desktop Chromium.",
            "THIRD_PARTY_NOTICES.txt covers Chromium GN target dependencies only; "
            "Emscripten toolchain/runtime and system-library attribution closure "
            "remains incomplete.",
            "Bundled TOOLCHAIN.json records configured dependency references but "
            "does not make a mutable or otherwise unapproved dependency reference "
            "an authorized immutable pin.",
            source_identity_limitation,
        ],
        "product": PRODUCT_NAME,
        "release_status": RELEASE_STATUS,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "toolchain_manifest": {
            "path": TOOLCHAIN_MANIFEST_PACKAGE_PATH,
            "sha256": manifest_sha256,
        },
        "versions": _manifest_versions(manifest),
    }


def _source_paths(
    *, out_dir: Path, module_name: str, host_dir: Path
) -> dict[str, Path]:
    sources = {
        "chromium-wasm.js": out_dir / f"{module_name}.js",
        "chromium-wasm.wasm": out_dir / f"{module_name}.wasm",
    }
    for source_name, destination_name in HOST_ASSETS:
        sources[destination_name] = host_dir / source_name
    sources["LICENSES/Chromium-LICENSE.txt"] = REPO_ROOT / "LICENSE"
    return sources


def _validate_source_layout(
    *, out_dir: Path, module_name: str, host_dir: Path
) -> None:
    _require_regular_file(out_dir / "args.gn", "build args")
    for destination, source in _source_paths(
        out_dir=out_dir, module_name=module_name, host_dir=host_dir
    ).items():
        _require_regular_file(source, f"package input for {destination}")


def _validate_self_contained_loader(
    *, out_dir: Path, module_name: str, host_dir: Path
) -> None:
    """Reject a build whose generated runtime needs omitted sidecar files.

    The pre-release layout deliberately renames the generated loader. The
    paired release host verifies the loader and Wasm bytes against
    ``VERSION.json`` before it imports the loader through Emscripten's
    ``mainScriptUrlOrBlob`` pthread path. The generated loader's ordinary
    same-name JavaScript worker fallback is therefore not a package sidecar.
    A generated data package or distinct worker script, however, would need
    an explicitly designed package layout and must not be silently dropped.
    """
    loader_path = out_dir / f"{module_name}.js"
    host_path = host_dir / "release_host.js"
    try:
        loader = loader_path.read_text(encoding="utf-8")
        host = host_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError("generated loader and release host must be UTF-8") from exc
    if f"{module_name}.wasm" not in loader:
        raise PackageError("generated loader does not expose its expected Wasm sidecar")
    for sidecar in (f"{module_name}.data", f"{module_name}.worker.js"):
        if sidecar in loader or (out_dir / sidecar).exists():
            raise PackageError(
                "generated loader requires an unsupported external sidecar: "
                f"{sidecar}"
            )
    for required_host_fragment in (
        "fetchVerifiedArtifact(",
        "mainScriptUrlOrBlob",
        "inputModuleName",
        "LOADER_ARTIFACT_PATH",
        "WASM_ARTIFACT_PATH",
        "wasmBinary,",
        '"./chromium-wasm-release-wisp-config.js"',
    ):
        if required_host_fragment not in host:
            raise PackageError(
                "release host no longer satisfies the renamed loader contract"
            )


def _validate_destination(destination: Path, out_dir: Path) -> None:
    repo_root = REPO_ROOT.resolve()
    if destination == repo_root or _is_within(repo_root, destination) or _is_within(
        destination, repo_root
    ):
        raise PackageError("dist directory must not overlap the repository root")
    if destination == out_dir or _is_within(destination, out_dir) or _is_within(
        out_dir, destination
    ):
        raise PackageError("dist directory must not overlap the build output directory")
    if not destination.exists():
        return
    if destination.is_symlink() or not destination.is_dir():
        raise PackageError("dist directory must be a missing or empty real directory")
    if any(destination.iterdir()):
        raise PackageError("dist directory already exists and is not empty")


def _publish_staging_directory(staging: Path, destination: Path) -> None:
    if destination.exists():
        # _validate_destination already established that this is our explicitly
        # selected empty directory. rmdir is deliberately limited to it.
        destination.rmdir()
    try:
        os.replace(staging, destination)
    except OSError as exc:
        raise PackageError(
            f"could not atomically publish package directory {destination}: {exc}"
        ) from exc


def package_release(
    *,
    out_dir: Path,
    dist_dir: Path,
    module_name: str,
    manifest: dict[str, Any],
    port_revision: str,
    host_dir: Path | None = None,
    clean_build_attestation_path: Path | None = None,
) -> dict[str, object]:
    """Stage one deterministic, explicitly non-releasable package directory."""
    module_name = _validate_module_name(module_name)
    resolved_out_dir = _resolved_existing_directory(out_dir, "build output directory")
    resolved_dist_dir = _resolved_destination(dist_dir)
    resolved_host_dir = _resolved_existing_directory(
        host_dir or (Path(__file__).resolve().parent / "host"), "host source directory"
    )
    _validate_destination(resolved_dist_dir, resolved_out_dir)
    _validate_source_layout(
        out_dir=resolved_out_dir,
        module_name=module_name,
        host_dir=resolved_host_dir,
    )
    _validate_self_contained_loader(
        out_dir=resolved_out_dir,
        module_name=module_name,
        host_dir=resolved_host_dir,
    )

    gn_args_sha256, gn_args = _read_gn_args(resolved_out_dir / "args.gn")
    manifest_path = Path(__file__).with_name("toolchain_manifest.json")
    try:
        manifest_bytes = manifest_path.read_bytes()
        on_disk_manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError("toolchain manifest cannot be read for packaging") from exc
    if manifest != on_disk_manifest:
        raise PackageError(
            "package manifest must be the checked-out toolchain manifest"
        )
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    _manifest_versions(manifest)

    artifact_source_provenance = ARTIFACT_SOURCE_PROVENANCE_UNVERIFIED
    attestation: dict[str, object] | None = None
    if clean_build_attestation_path is not None:
        attestation = _validate_clean_build_attestation(
            out_dir=resolved_out_dir,
            module_name=module_name,
            manifest=manifest,
            port_revision=port_revision,
            attestation_path=clean_build_attestation_path,
        )
        artifact_source_provenance = (
            ARTIFACT_SOURCE_PROVENANCE_LOCAL_CLEAN_BUILD_ATTESTED
        )

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{resolved_dist_dir.name}.staging-",
            dir=resolved_dist_dir.parent,
        )
    )
    try:
        for destination, source in _source_paths(
            out_dir=resolved_out_dir,
            module_name=module_name,
            host_dir=resolved_host_dir,
        ).items():
            _copy_file(source, staging / destination)
        # Stage the exact bytes that were parsed and hashed above. Reopening the
        # source manifest here would let a concurrent change make VERSION.json
        # describe different bytes from the bundled dependency record.
        _write_file(staging / TOOLCHAIN_MANIFEST_PACKAGE_PATH, manifest_bytes)
        notice_path = staging / TARGET_THIRD_PARTY_NOTICES_PATH
        _generate_target_third_party_notices(
            out_dir=resolved_out_dir,
            destination=notice_path,
        )
        _require_regular_file(notice_path, "target third-party notices")
        if attestation is not None:
            _validate_staged_attested_module_artifacts(staging, attestation)
            # Recompute after all package inputs are copied so an attested label
            # is never published if output bytes, manifest, or checkout identity
            # changed during staging.
            if (
                _validate_clean_build_attestation(
                    out_dir=resolved_out_dir,
                    module_name=module_name,
                    manifest=manifest,
                    port_revision=port_revision,
                    attestation_path=clean_build_attestation_path,
                )
                != attestation
            ):
                raise PackageError(
                    "clean-build attestation changed while the package was staged"
                )
        _write_file(
            staging / "README.txt",
            _readme_text(artifact_source_provenance).encode("utf-8"),
        )
        _write_file(
            staging / "LICENSES/PRE_RELEASE_NOTICE.txt",
            LICENSE_NOTICE_TEXT.encode("utf-8"),
        )

        artifact_paths = _tree_paths(staging)
        version = _version_manifest(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            port_revision=port_revision,
            module_name=module_name,
            gn_args_sha256=gn_args_sha256,
            gn_args=gn_args,
            artifacts=_file_records(staging, artifact_paths),
            artifact_source_provenance=artifact_source_provenance,
        )
        _write_file(staging / "VERSION.json", _canonical_json(version))
        verify_release_tree(staging)
        _publish_staging_directory(staging, resolved_dist_dir)
        return verify_release_tree(resolved_dist_dir)
    finally:
        # The only recursive removal is an un-published mkdtemp directory that
        # this invocation created next to the selected destination.
        if staging.exists():
            shutil.rmtree(staging)


def _load_version_bytes(contents: bytes) -> dict[str, Any]:
    """Parse the exact canonical VERSION.json bytes from one package snapshot."""

    if type(contents) is not bytes or not contents:
        raise PackageError("VERSION.json must contain non-empty bytes")
    if len(contents) > MAX_ARTIFACT_BYTES:
        raise PackageError("VERSION.json has an invalid size")
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {constant}")
            ),
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackageError(f"VERSION.json is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError("VERSION.json must contain an object")
    if _canonical_json(value) != contents:
        raise PackageError("VERSION.json is not canonical deterministic JSON")
    return value


def _load_version(path: Path) -> dict[str, Any]:
    _require_regular_file(path, "VERSION.json")
    return _load_version_bytes(path.read_bytes())


def _load_toolchain_manifest_bytes(contents: bytes) -> dict[str, Any]:
    """Parse bounded bundled manifest bytes without trusting their metadata."""

    if type(contents) is not bytes or not contents:
        raise PackageError("bundled toolchain manifest must contain non-empty bytes")
    if len(contents) > MAX_TOOLCHAIN_MANIFEST_BYTES:
        raise PackageError("bundled toolchain manifest has an invalid size")
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {constant}")
            ),
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackageError(f"bundled toolchain manifest is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError("bundled toolchain manifest must contain an object")
    return value


def _validate_bundled_toolchain_manifest(
    version: dict[str, Any], contents: bytes
) -> None:
    """Bind package version metadata to the exact bundled dependency record."""

    bundled_versions = _manifest_versions(_load_toolchain_manifest_bytes(contents))
    if bundled_versions != version["versions"]:
        raise PackageError(
            "bundled toolchain manifest versions do not match VERSION.json"
        )


def _validate_gate_state(gate_state: object) -> None:
    """Require the exact false-only milestone declaration for this package."""

    if type(gate_state) is not dict or set(gate_state) != set(EXPECTED_GATE_STATE):
        raise PackageError("VERSION.json gate state schema is invalid")
    for key, expected_value in EXPECTED_GATE_STATE.items():
        value = gate_state[key]
        # bool is an int subclass in Python, so use an exact type check before
        # comparing the value. JSON 0 or 1 must never stand in for a gate.
        if type(value) is not bool:
            raise PackageError("VERSION.json gate state values must be booleans")
        if value is not expected_value:
            raise PackageError("VERSION.json gate state must retain false values")


def _validate_version_metadata(version: dict[str, Any]) -> list[dict[str, object]]:
    """Validate exact VERSION.json schema independent of live artifact paths."""

    expected_keys = {
        "artifacts",
        "build",
        "gate_state",
        "host",
        "known_limitations",
        "product",
        "release_status",
        "schema_version",
        "toolchain_manifest",
        "versions",
    }
    if set(version) != expected_keys:
        raise PackageError("VERSION.json fields do not match the package schema")
    if version["schema_version"] != PACKAGE_SCHEMA_VERSION:
        raise PackageError("VERSION.json has an unsupported schema version")
    if version["product"] != PRODUCT_NAME:
        raise PackageError("VERSION.json product is invalid")
    if version["release_status"] != RELEASE_STATUS:
        raise PackageError("VERSION.json must retain the pre-release status")

    _validate_gate_state(version["gate_state"])

    versions = version["versions"]
    if not isinstance(versions, dict) or set(versions) != {
        "chromium",
        "v8",
        "emscripten",
    } or not all(
        isinstance(value, str) and GIT_REVISION_RE.fullmatch(value)
        for value in versions.values()
    ):
        raise PackageError("VERSION.json versions are invalid")

    build = version["build"]
    if not isinstance(build, dict) or set(build) != {
        "artifact_source_provenance",
        "gn_args",
        "gn_args_sha256",
        "input_module_name",
        "resource_delivery",
        "staging_checkout",
    }:
        raise PackageError("VERSION.json build metadata is invalid")
    if not isinstance(build["gn_args"], list) or not build["gn_args"]:
        raise PackageError("VERSION.json GN arguments are invalid")
    if not all(isinstance(argument, str) for argument in build["gn_args"]):
        raise PackageError("VERSION.json GN arguments must be strings")
    if not isinstance(build["gn_args_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", build["gn_args_sha256"]
    ):
        raise PackageError("VERSION.json GN args hash is invalid")
    if build["input_module_name"] != PACKAGE_INPUT_MODULE_NAME:
        raise PackageError("VERSION.json module name is invalid")
    if build["resource_delivery"] != "embedded-in-wasm-current-build":
        raise PackageError("VERSION.json resource delivery declaration is invalid")
    if (
        type(build["artifact_source_provenance"]) is not str
        or build["artifact_source_provenance"]
        not in ALLOWED_ARTIFACT_SOURCE_PROVENANCE
    ):
        raise PackageError("VERSION.json artifact source provenance is invalid")
    if not isinstance(build["staging_checkout"], str) or not GIT_REVISION_RE.fullmatch(
        build["staging_checkout"]
    ):
        raise PackageError("VERSION.json staging checkout is invalid")

    host = version["host"]
    if not isinstance(host, dict) or host != {
        "bridge_protocol": HOST_PROTOCOL_VERSION,
        "mime_types": REQUIRED_MIME_TYPES,
        "required_headers": REQUIRED_HEADERS,
    }:
        raise PackageError("VERSION.json host requirements are invalid")

    manifest = version["toolchain_manifest"]
    if not isinstance(manifest, dict) or set(manifest) != {"path", "sha256"}:
        raise PackageError("VERSION.json toolchain manifest metadata is invalid")
    if manifest["path"] != TOOLCHAIN_MANIFEST_PACKAGE_PATH or not isinstance(
        manifest["sha256"], str
    ) or not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]):
        raise PackageError("VERSION.json toolchain manifest identity is invalid")

    limitations = version["known_limitations"]
    if not isinstance(limitations, list) or len(limitations) < 4 or not all(
        isinstance(limitation, str) and limitation for limitation in limitations
    ):
        raise PackageError("VERSION.json known limitations are invalid")

    artifacts = version["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise PackageError("VERSION.json artifact list is invalid")
    expected_artifact_paths = sorted(PACKAGE_PATHS - {"VERSION.json"})
    observed_paths: list[str] = []
    toolchain_manifest_artifact: dict[str, object] | None = None
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise PackageError("VERSION.json artifact record is invalid")
        relative = artifact["path"]
        if not isinstance(relative, str) or relative not in PACKAGE_PATHS:
            raise PackageError("VERSION.json artifact path is invalid")
        if relative == "VERSION.json":
            raise PackageError("VERSION.json must not self-hash")
        if not isinstance(artifact["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", artifact["sha256"]
        ):
            raise PackageError("VERSION.json artifact hash is invalid")
        if type(artifact["size_bytes"]) is not int or artifact["size_bytes"] <= 0:
            raise PackageError("VERSION.json artifact size is invalid")
        observed_paths.append(relative)
        if relative == TOOLCHAIN_MANIFEST_PACKAGE_PATH:
            toolchain_manifest_artifact = artifact
    if observed_paths != expected_artifact_paths:
        raise PackageError("VERSION.json artifacts are not complete and ordered")
    if (
        toolchain_manifest_artifact is None
        or toolchain_manifest_artifact["sha256"] != manifest["sha256"]
    ):
        raise PackageError(
            "VERSION.json toolchain manifest artifact identity is invalid"
        )
    return artifacts


def _validate_version(version: dict[str, Any], root: Path) -> None:
    """Validate VERSION.json metadata and its records against a live tree."""

    for artifact in _validate_version_metadata(version):
        relative = artifact["path"]
        candidate = root / relative
        _require_regular_file(candidate, f"staged package artifact {relative}")
        if candidate.stat().st_size != artifact["size_bytes"] or sha256_file(
            candidate
        ) != artifact["sha256"]:
            raise PackageError(f"staged package artifact hash mismatch: {relative}")
    _validate_bundled_toolchain_manifest(
        version,
        (root / TOOLCHAIN_MANIFEST_PACKAGE_PATH).read_bytes(),
    )


def verify_release_snapshot(artifacts: Mapping[str, bytes]) -> dict[str, object]:
    """Verify the exact in-memory bytes that a package server will expose.

    Unlike ``verify_release_tree()``, this function never opens a package path.
    It is for a descriptor-pinned snapshot whose contents must be validated
    without giving a later filesystem mutation another observation point.
    """

    if not isinstance(artifacts, Mapping):
        raise PackageError("package snapshot artifacts must be a mapping")
    try:
        paths = set(artifacts)
    except TypeError as exc:
        raise PackageError("package snapshot artifact paths are invalid") from exc
    if not all(type(path) is str for path in paths):
        raise PackageError("package snapshot artifact paths are invalid")
    if paths != PACKAGE_PATHS:
        unexpected = sorted(paths - PACKAGE_PATHS)
        missing = sorted(PACKAGE_PATHS - paths)
        raise PackageError(
            "package snapshot file layout mismatch: "
            f"missing={missing} unexpected={unexpected}"
        )

    captured: dict[str, bytes] = {}
    for relative in sorted(PACKAGE_PATHS):
        try:
            contents = artifacts[relative]
        except (KeyError, TypeError) as exc:
            raise PackageError(
                f"package snapshot artifact is missing: {relative}"
            ) from exc
        if type(contents) is not bytes:
            raise PackageError(
                f"package snapshot artifact must be bytes: {relative}"
            )
        if len(contents) <= 0 or len(contents) > MAX_ARTIFACT_BYTES:
            raise PackageError(
                f"package snapshot artifact has an invalid size: {relative}"
            )
        captured[relative] = contents

    version_bytes = captured["VERSION.json"]
    version = _load_version_bytes(version_bytes)
    for artifact in _validate_version_metadata(version):
        relative = artifact["path"]
        contents = captured[relative]
        if (
            len(contents) != artifact["size_bytes"]
            or _sha256_bytes(contents) != artifact["sha256"]
        ):
            raise PackageError(f"staged package artifact hash mismatch: {relative}")
    _validate_bundled_toolchain_manifest(
        version,
        captured[TOOLCHAIN_MANIFEST_PACKAGE_PATH],
    )
    return {
        "artifact_count": len(version["artifacts"]),
        "artifact_source_provenance": version["build"][
            "artifact_source_provenance"
        ],
        "release_status": version["release_status"],
        "version_sha256": _sha256_bytes(version_bytes),
    }


def package_runtime_status_metadata(version_bytes: bytes) -> dict[str, object]:
    """Project validated raw VERSION.json into fixed host runtime status data.

    This is a bounded status projection of the immutable served metadata bytes,
    not a source-provenance or release-provenance claim for package artifacts.
    It deliberately reuses the package's canonical JSON and exact schema
    validators so browser-smoke metadata cannot drift from staging semantics.
    """

    version = _load_version_bytes(version_bytes)
    _validate_version_metadata(version)
    build = version["build"]
    gate_state = version["gate_state"]
    versions = version["versions"]
    return {
        "build": {
            "artifactSourceProvenance": build["artifact_source_provenance"],
            "inputModuleName": build["input_module_name"],
            "resourceDelivery": build["resource_delivery"],
            "stagingCheckout": build["staging_checkout"],
        },
        "gateState": {
            name: gate_state[name] for name in EXPECTED_GATE_STATE
        },
        "product": version["product"],
        "protocol": PACKAGE_RUNTIME_STATUS_PROTOCOL,
        "releaseStatus": version["release_status"],
        "schemaVersion": version["schema_version"],
        "versionJsonSha256": _sha256_bytes(version_bytes),
        "versions": {
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "v8": versions["v8"],
        },
    }


def verify_release_tree(dist_dir: Path) -> dict[str, object]:
    """Verify one already-staged package without inspecting source build output."""
    root = _resolved_existing_directory(dist_dir, "dist directory")
    paths = _tree_paths(root)
    if set(paths) != PACKAGE_PATHS:
        unexpected = sorted(set(paths) - PACKAGE_PATHS)
        missing = sorted(PACKAGE_PATHS - set(paths))
        raise PackageError(
            "package file layout mismatch: "
            f"missing={missing} unexpected={unexpected}"
        )
    version = _load_version(root / "VERSION.json")
    _validate_version(version, root)
    return {
        "artifact_count": len(version["artifacts"]),
        "artifact_source_provenance": version["build"][
            "artifact_source_provenance"
        ],
        "dist_dir": str(root),
        "release_status": version["release_status"],
        "version_sha256": sha256_file(root / "VERSION.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage or verify an explicitly pre-release Chromium Wasm package."
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument(
        "--module-name",
        default=PACKAGE_INPUT_MODULE_NAME,
        help="fixed input module name; only chrome_wasm is supported",
    )
    parser.add_argument(
        "--clean-build-attestation",
        type=Path,
        help=(
            "require this selected output's m9_clean_build_attestation.json and "
            "label matching module bytes local_clean_build_attested"
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify an existing package without staging files",
    )
    args = parser.parse_args()

    try:
        if args.verify:
            if args.clean_build_attestation is not None:
                raise PackageError(
                    "--clean-build-attestation is only valid while staging a package"
                )
            result = verify_release_tree(args.dist_dir)
        else:
            manifest = load_manifest()
            port_revision = checked_output(["git", "rev-parse", "HEAD"])
            print_context(
                "package.py",
                manifest,
                mode="stage-pre-release",
                input_module_name=args.module_name,
                requested_clean_build_attestation=(
                    args.clean_build_attestation is not None
                ),
                release_status=RELEASE_STATUS,
            )
            result = package_release(
                out_dir=args.out_dir,
                dist_dir=args.dist_dir,
                module_name=args.module_name,
                manifest=manifest,
                port_revision=port_revision,
                clean_build_attestation_path=args.clean_build_attestation,
            )
        print(
            f"{SENTINEL}:PASS "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    except (M0Error, OSError, TypeError, ValueError) as exc:
        print(f"{SENTINEL}:FAIL reason={exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

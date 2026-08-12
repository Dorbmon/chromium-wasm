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
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any, Iterable

if __package__:
    from .m0_common import (
        M0Error,
        REPO_ROOT,
        checked_output,
        load_manifest,
        print_context,
    )
else:
    from m0_common import (
        M0Error,
        REPO_ROOT,
        checked_output,
        load_manifest,
        print_context,
    )


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE"
PACKAGE_SCHEMA_VERSION = 2
HOST_PROTOCOL_VERSION = 1
RELEASE_STATUS = "pre_m7_m8_not_releasable"
PRODUCT_NAME = "chromium-wasm"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024

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

# Keep these names independent of the input target's generated names.  A
# package consumer must never need to know whether the builder called its
# executable chrome_wasm or something else.
HOST_ASSETS = (
    ("release_index.html", "index.html"),
    ("release_host.js", "chromium-wasm-host.js"),
    ("chrome_wasm_pointer_input.js", "chromium-wasm-pointer-input.js"),
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
)
PACKAGE_PATHS = frozenset(
    (
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

The build.staging_checkout value records only the Git checkout that ran this
staging tool. The copied build artifacts have
build.artifact_source_provenance = \"unverified\"; staging does not assert that
they were built from that checkout.

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

Known non-release limitations:

  * Browser, renderer, services, and GPU work remain in one Wasm process; this
    is not Chromium's desktop sandbox or Site Isolation security model.
  * The Chrome profile is not mounted on a proven durable OPFS backend.
  * This package has not passed the M8 compatibility or M9 stress/reliability
    gate, and its license directory is not the final third-party attribution
    closure.
  * The recorded staging checkout is not a verified source identity for the
    copied build artifacts.

The in-canvas browser UI is implemented by Chromium. The surrounding page is
only a loader and narrow host bridge.
"""

LICENSE_NOTICE_TEXT = """Pre-release license notice
========================

This directory is not a release artifact and does not contain a complete
third-party attribution bundle. Chromium-LICENSE.txt is copied from this
checkout's top-level Chromium license only. A distributable release must add a
reviewed, complete third-party license closure before its release status can be
changed.
"""


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
        json.dumps(value, indent=2, sort_keys=True, separators=(",", ": "))
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
) -> dict[str, object]:
    if not GIT_REVISION_RE.fullmatch(port_revision):
        raise PackageError(
            "staging checkout must be a lowercase 40-character Git hash"
        )
    return {
        "artifacts": artifacts,
        "build": {
            "artifact_source_provenance": "unverified",
            "gn_args": gn_args.split("\n"),
            "gn_args_sha256": gn_args_sha256,
            "input_module_name": module_name,
            "resource_delivery": "embedded-in-wasm-current-build",
            "staging_checkout": port_revision,
        },
        "host": {
            "bridge_protocol": HOST_PROTOCOL_VERSION,
            "mime_types": REQUIRED_MIME_TYPES,
            "required_headers": REQUIRED_HEADERS,
        },
        "known_limitations": [
            "M7 durable OPFS profile integration is incomplete.",
            "M8 compatibility coverage is incomplete.",
            "M9 stress, reliability, and final release validation are incomplete.",
            "The single-process Wasm port is not security-equivalent to desktop Chromium.",
            "The LICENSES directory is not a complete third-party attribution closure.",
            (
                "The staging checkout is not verified as the source identity "
                "of the copied build artifacts."
            ),
        ],
        "product": PRODUCT_NAME,
        "release_status": RELEASE_STATUS,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "toolchain_manifest": {
            "path": "tools/wasm/toolchain_manifest.json",
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
    paired release host uses Emscripten's mainScriptUrlOrBlob pthread path, so
    the generated loader's ordinary same-name JavaScript worker fallback is
    not a package sidecar. A generated data package or distinct worker script,
    however, would need an explicitly designed package layout and must not be
    silently dropped.
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
        "mainScriptUrlOrBlob",
        "inputModuleName",
        '"./chromium-wasm.wasm"',
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
        on_disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError("toolchain manifest cannot be read for packaging") from exc
    if manifest != on_disk_manifest:
        raise PackageError(
            "package manifest must be the checked-out toolchain manifest"
        )
    manifest_sha256 = sha256_file(manifest_path)
    _manifest_versions(manifest)

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
        _write_file(staging / "README.txt", README_TEXT.encode("utf-8"))
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


def _load_version(path: Path) -> dict[str, Any]:
    _require_regular_file(path, "VERSION.json")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackageError(f"VERSION.json is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError("VERSION.json must contain an object")
    if _canonical_json(value) != path.read_bytes():
        raise PackageError("VERSION.json is not canonical deterministic JSON")
    return value


def _validate_version(version: dict[str, Any], root: Path) -> None:
    expected_keys = {
        "artifacts",
        "build",
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
    if not isinstance(build["input_module_name"], str) or not MODULE_NAME_RE.fullmatch(
        build["input_module_name"]
    ):
        raise PackageError("VERSION.json module name is invalid")
    if build["resource_delivery"] != "embedded-in-wasm-current-build":
        raise PackageError("VERSION.json resource delivery declaration is invalid")
    if build["artifact_source_provenance"] != "unverified":
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
    if manifest["path"] != "tools/wasm/toolchain_manifest.json" or not isinstance(
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
        candidate = root / relative
        _require_regular_file(candidate, f"staged package artifact {relative}")
        if candidate.stat().st_size != artifact["size_bytes"] or sha256_file(
            candidate
        ) != artifact["sha256"]:
            raise PackageError(f"staged package artifact hash mismatch: {relative}")
    if observed_paths != expected_artifact_paths:
        raise PackageError("VERSION.json artifacts are not complete and ordered")


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
    parser.add_argument("--module-name", default="chrome_wasm")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify an existing package without staging files",
    )
    args = parser.parse_args()

    try:
        if args.verify:
            result = verify_release_tree(args.dist_dir)
        else:
            manifest = load_manifest()
            port_revision = checked_output(["git", "rev-parse", "HEAD"])
            print_context(
                "package.py",
                manifest,
                mode="stage-pre-release",
                input_module_name=args.module_name,
                release_status=RELEASE_STATUS,
            )
            result = package_release(
                out_dir=args.out_dir,
                dist_dir=args.dist_dir,
                module_name=args.module_name,
                manifest=manifest,
                port_revision=port_revision,
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

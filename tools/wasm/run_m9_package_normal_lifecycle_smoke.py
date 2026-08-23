#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run one ordinary Browser lifecycle from a verified pre-release package.

This runner deliberately consumes only the immutable in-memory package tree
captured by ``run_m9_package_smoke``.  It maps the package's public
``chromium-wasm`` module names to the private ``chrome_wasm`` names expected by
the existing ordinary Node lifecycle harness.  The resulting observation is a
package-snapshot Node lifecycle only: it neither serves a document nor claims a
Chrome UI, source/release provenance, M7 persistence, M8 compatibility, or M9
release completion.
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator, Mapping

if __package__:
    from . import package as package_tool
    from .m0_common import M0Error, REPO_ROOT, parse_timeout
    from .m9_descriptor_snapshot import snapshot_regular_file
    from . import run_m6_wasm_browser_normal_lifecycle_smoke as normal_lifecycle
    from . import run_m9_package_smoke as package_smoke
else:
    import package as package_tool

    from m0_common import M0Error, REPO_ROOT, parse_timeout
    from m9_descriptor_snapshot import snapshot_regular_file
    import run_m6_wasm_browser_normal_lifecycle_smoke as normal_lifecycle
    import run_m9_package_smoke as package_smoke


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE_NORMAL_LIFECYCLE"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
PASS_MARKER = f"{SENTINEL}:PASS"
FAIL_MARKER = f"{SENTINEL}:FAIL"
SCOPE = "package-snapshot-node-lifecycle-only"

PUBLIC_MODULE_NAME = "chromium-wasm"
PRIVATE_MODULE_NAME = "chrome_wasm"
PACKAGE_ARTIFACT_DELIVERY = "verified-package-snapshot-private-temporary-file"
NODE_DELIVERY = "explicit-package-pinned-node-private-temporary-file"
MAX_NODE_BYTES = 1024 * 1024 * 1024
NODE_VERSION_TIMEOUT_SECONDS = 10.0
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NODE_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){2}$")

_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_PACKAGE_ARTIFACT_FIELDS = frozenset(
    (
        "artifact_delivery",
        "artifact_source_provenance",
        "loader",
        "module_name",
        "public_module_name",
        "wasm",
    )
)
_NODE_IDENTITY_FIELDS = frozenset(("delivery", "sha256", "version"))
_RESULT_FIELDS = frozenset(
    (
        "artifact",
        "canvasCopies",
        "focusReports",
        "frameReports",
        "node",
        "packageRuntimeMetadata",
        "readinessReports",
        "scope",
        "startupMs",
    )
)


@dataclass(frozen=True)
class PinnedNodeRequirement:
    """The Node identity declared by the immutable bundled toolchain record."""

    version: str
    sha256: str


@dataclass(frozen=True)
class PinnedNodeSnapshot:
    """One private byte capture of the explicit package-pinned Node binary."""

    contents: bytes
    requirement: PinnedNodeRequirement


@dataclass(frozen=True)
class PackageLifecycleSnapshot:
    """The exact package bytes and metadata used by one Node lifecycle run."""

    artifact: normal_lifecycle.ArtifactSnapshot
    artifact_identity: dict[str, object]
    node_requirement: PinnedNodeRequirement
    runtime_metadata: dict[str, object]



def _exact_json_value_equal(value: object, expected: object) -> bool:
    """Compare JSON-shaped values without accepting bool/int aliases."""

    if type(value) is not type(expected):
        return False
    if type(value) is dict:
        return set(value) == set(expected) and all(
            _exact_json_value_equal(value[key], expected[key]) for key in value
        )
    if type(value) is list:
        return len(value) == len(expected) and all(
            _exact_json_value_equal(actual, wanted)
            for actual, wanted in zip(value, expected)
        )
    return value == expected


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise M0Error(f"package Node lifecycle {description} schema is invalid")
    return value


def _byte_identity(contents: bytes) -> dict[str, object]:
    if type(contents) is not bytes or not contents:
        raise M0Error("package Node lifecycle artifact bytes are invalid")
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"package Node lifecycle {description} byte count is invalid")
    digest = identity.get("sha256")
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise M0Error(f"package Node lifecycle {description} SHA-256 is invalid")


def _package_runtime_metadata(
    artifacts: Mapping[str, bytes], verification: Mapping[str, object]
) -> dict[str, object]:
    """Project and cross-check fixed VERSION.json metadata from package bytes."""

    try:
        version_bytes = artifacts["VERSION.json"]
        metadata = package_tool.package_runtime_status_metadata(version_bytes)
    except (KeyError, TypeError, package_tool.PackageError) as error:
        raise M0Error("package Node lifecycle VERSION.json metadata is invalid") from error

    if type(metadata) is not dict:
        raise M0Error("package Node lifecycle VERSION.json metadata is invalid")
    try:
        release_status = verification["release_status"]
        version_sha256 = verification["version_sha256"]
        artifact_source_provenance = verification["artifact_source_provenance"]
        build = metadata["build"]
        gate_state = metadata["gateState"]
    except (KeyError, TypeError) as error:
        raise M0Error("package Node lifecycle verification metadata is invalid") from error
    if (
        metadata.get("releaseStatus") != package_tool.RELEASE_STATUS
        or release_status != metadata["releaseStatus"]
        or metadata.get("versionJsonSha256") != version_sha256
        or not _exact_json_value_equal(gate_state, package_tool.EXPECTED_GATE_STATE)
        or type(build) is not dict
        or build.get("artifactSourceProvenance") != artifact_source_provenance
    ):
        raise M0Error("package Node lifecycle VERSION.json metadata disagrees")
    return metadata


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON constant {value!r}")


def _node_requirement(toolchain_bytes: bytes) -> PinnedNodeRequirement:
    """Read only the Node pin needed to execute this package-snapshot test."""

    if type(toolchain_bytes) is not bytes or not toolchain_bytes:
        raise M0Error("package Node lifecycle bundled toolchain metadata is invalid")
    try:
        manifest = json.loads(
            toolchain_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonstandard_json_constant,
        )
        emscripten = manifest["emscripten"]
        artifact_hashes = emscripten["artifact_sha256"]
        version = emscripten["node_version"]
        digest = artifact_hashes["node"]
    except (
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as error:
        raise M0Error("package Node lifecycle bundled Node pin is invalid") from error
    if (
        type(version) is not str
        or not NODE_VERSION_RE.fullmatch(version)
        or type(digest) is not str
        or not SHA256_RE.fullmatch(digest)
    ):
        raise M0Error("package Node lifecycle bundled Node pin is invalid")
    return PinnedNodeRequirement(version=version, sha256=digest)


def package_lifecycle_snapshot_from_tree(
    tree: package_smoke.PackageTreeSnapshot,
) -> PackageLifecycleSnapshot:
    """Bind the package's public executable bytes to one private Node input.

    Revalidate the snapshot's in-memory mapping here rather than trusting a
    caller-supplied verification record.  This neither reads a raw output
    directory nor establishes source/release provenance for the staged bytes.
    """

    try:
        artifacts = tree.artifacts
        verification = package_tool.verify_release_snapshot(artifacts)
        loader = artifacts[f"{PUBLIC_MODULE_NAME}.js"]
        wasm = artifacts[f"{PUBLIC_MODULE_NAME}.wasm"]
        toolchain_bytes = artifacts[package_tool.TOOLCHAIN_MANIFEST_PACKAGE_PATH]
    except (AttributeError, KeyError, TypeError, package_tool.PackageError) as error:
        raise M0Error(f"package Node lifecycle snapshot is invalid: {error}") from error

    metadata = _package_runtime_metadata(artifacts, verification)
    if type(loader) is not bytes or type(wasm) is not bytes:
        raise M0Error("package Node lifecycle executable snapshot is invalid")
    try:
        artifact_source_provenance = metadata["build"]["artifactSourceProvenance"]
    except (KeyError, TypeError) as error:
        raise M0Error("package Node lifecycle artifact provenance is invalid") from error
    if type(artifact_source_provenance) is not str:
        raise M0Error("package Node lifecycle artifact provenance is invalid")

    artifact = normal_lifecycle.ArtifactSnapshot(
        module_name=PRIVATE_MODULE_NAME,
        loader=loader,
        wasm=wasm,
    )
    artifact_identity = {
        "artifact_delivery": PACKAGE_ARTIFACT_DELIVERY,
        "artifact_source_provenance": artifact_source_provenance,
        "loader": _byte_identity(loader),
        "module_name": PRIVATE_MODULE_NAME,
        "public_module_name": PUBLIC_MODULE_NAME,
        "wasm": _byte_identity(wasm),
    }
    validate_package_artifact_identity(
        artifact_identity,
        expected_artifact_identity=artifact_identity,
        expected_runtime_metadata=metadata,
    )
    return PackageLifecycleSnapshot(
        artifact=artifact,
        artifact_identity=artifact_identity,
        node_requirement=_node_requirement(toolchain_bytes),
        runtime_metadata=metadata,
    )


def capture_package_lifecycle_snapshot(dist_dir: Path) -> PackageLifecycleSnapshot:
    """Capture one descriptor-pinned verified package tree before any child runs."""

    return package_lifecycle_snapshot_from_tree(
        package_smoke.snapshot_package_tree(dist_dir)
    )


def validate_package_artifact_identity(
    value: object,
    *,
    expected_artifact_identity: dict[str, object] | None = None,
    expected_runtime_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate the package/public-to-private executable byte identity."""

    artifact = _require_exact_fields(
        value, _PACKAGE_ARTIFACT_FIELDS, "artifact identity"
    )
    if artifact.get("artifact_delivery") != PACKAGE_ARTIFACT_DELIVERY:
        raise M0Error("package Node lifecycle artifact delivery is invalid")
    if artifact.get("module_name") != PRIVATE_MODULE_NAME:
        raise M0Error("package Node lifecycle private module name is invalid")
    if artifact.get("public_module_name") != PUBLIC_MODULE_NAME:
        raise M0Error("package Node lifecycle public module name is invalid")
    if type(artifact.get("artifact_source_provenance")) is not str:
        raise M0Error("package Node lifecycle artifact source provenance is invalid")
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if expected_runtime_metadata is not None:
        try:
            expected_provenance = expected_runtime_metadata["build"][
                "artifactSourceProvenance"
            ]
        except (KeyError, TypeError) as error:
            raise M0Error("package Node lifecycle expected metadata is invalid") from error
        if artifact["artifact_source_provenance"] != expected_provenance:
            raise M0Error(
                "package Node lifecycle artifact source provenance disagrees with "
                "VERSION.json"
            )
    if expected_artifact_identity is not None and not _exact_json_value_equal(
        artifact, expected_artifact_identity
    ):
        raise M0Error("package Node lifecycle artifact identity disagrees with expectation")
    return artifact


def capture_pinned_node(
    node: Path, requirement: PinnedNodeRequirement
) -> PinnedNodeSnapshot:
    """Copy the explicit Node binary only after it matches the bundled pin."""

    if not isinstance(node, Path):
        raise M0Error("package Node lifecycle Node path is invalid")
    try:
        node_metadata = node.lstat()
    except OSError as error:
        raise M0Error("package Node lifecycle pinned Node binary is unavailable") from error
    if not stat.S_ISREG(node_metadata.st_mode) or not (
        node_metadata.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    ):
        raise M0Error("package Node lifecycle pinned Node binary is not executable")
    contents = snapshot_regular_file(
        node,
        maximum_bytes=MAX_NODE_BYTES,
        description="package Node lifecycle pinned Node binary",
    )
    digest = hashlib.sha256(contents).hexdigest()
    if digest != requirement.sha256:
        raise M0Error("package Node lifecycle explicit Node hash disagrees with package")
    return PinnedNodeSnapshot(contents=contents, requirement=requirement)


def _node_identity(snapshot: PinnedNodeSnapshot) -> dict[str, str]:
    if (
        type(snapshot.contents) is not bytes
        or not snapshot.contents
        or not isinstance(snapshot.requirement, PinnedNodeRequirement)
        or not NODE_VERSION_RE.fullmatch(snapshot.requirement.version)
        or not SHA256_RE.fullmatch(snapshot.requirement.sha256)
        or hashlib.sha256(snapshot.contents).hexdigest() != snapshot.requirement.sha256
    ):
        raise M0Error("package Node lifecycle pinned Node snapshot is invalid")
    return {
        "delivery": NODE_DELIVERY,
        "sha256": snapshot.requirement.sha256,
        "version": snapshot.requirement.version,
    }


@contextlib.contextmanager
def materialized_pinned_node(snapshot: PinnedNodeSnapshot) -> Iterator[Path]:
    """Materialize the pinned Node bytes privately to avoid a path reread."""

    _node_identity(snapshot)
    with tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-package-node-") as path:
        executable = Path(path) / "node"
        try:
            executable.write_bytes(snapshot.contents)
            executable.chmod(0o700)
        except OSError as error:
            raise M0Error(
                f"cannot materialize package Node lifecycle pinned Node: {error}"
            ) from error
        yield executable


def validate_pinned_node_version(
    node: Path, requirement: PinnedNodeRequirement
) -> None:
    """Require the private pinned binary to report the bundled Node version."""

    try:
        completed = subprocess.run(
            [str(node), "--version"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=NODE_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise M0Error("package Node lifecycle pinned Node version check failed") from error
    if (
        completed.returncode != 0
        or completed.stdout.strip() != f"v{requirement.version}"
    ):
        raise M0Error("package Node lifecycle pinned Node version disagrees with package")


def _validate_node_identity(value: object, expected: dict[str, str]) -> None:
    node = _require_exact_fields(value, _NODE_IDENTITY_FIELDS, "Node identity")
    if not _exact_json_value_equal(node, expected):
        raise M0Error("package Node lifecycle Node identity disagrees with expectation")


def _require_nonnegative_int(value: object, description: str) -> int:
    if type(value) is not int or value < 0:
        raise M0Error(f"package Node lifecycle {description} is invalid")
    return value


def _require_positive_int(value: object, description: str) -> int:
    result = _require_nonnegative_int(value, description)
    if result < 1:
        raise M0Error(f"package Node lifecycle {description} is invalid")
    return result


def validate_package_result(
    value: object, *, expected: PackageLifecycleSnapshot, node: PinnedNodeSnapshot
) -> dict[str, object]:
    """Require a result to remain bound to this exact package/node snapshot."""

    result = _require_exact_fields(value, _RESULT_FIELDS, "result")
    if result.get("scope") != SCOPE:
        raise M0Error("package Node lifecycle scope is invalid")
    validate_package_artifact_identity(
        result.get("artifact"),
        expected_artifact_identity=expected.artifact_identity,
        expected_runtime_metadata=expected.runtime_metadata,
    )
    if not _exact_json_value_equal(
        result.get("packageRuntimeMetadata"), expected.runtime_metadata
    ):
        raise M0Error(
            "package Node lifecycle runtime metadata disagrees with VERSION.json"
        )
    _validate_node_identity(result.get("node"), _node_identity(node))
    for field in ("canvasCopies", "focusReports", "frameReports", "readinessReports"):
        _require_positive_int(result.get(field), field)
    startup_ms = result.get("startupMs")
    if (
        isinstance(startup_ms, bool)
        or not isinstance(startup_ms, (int, float))
        or not math.isfinite(float(startup_ms))
        or float(startup_ms) < 0
    ):
        raise M0Error("package Node lifecycle startupMs is invalid")
    return result


def _child_result(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Reuse the ordinary runner's strict native lifecycle validation."""

    if completed.returncode != 0:
        raise M0Error(
            "package Node lifecycle child exited with status "
            f"{completed.returncode}"
        )
    try:
        result = normal_lifecycle._parse_result(completed.stdout)
        normal_lifecycle.validate_result(
            result, f"{completed.stdout}\n{completed.stderr}"
        )
        return result
    except normal_lifecycle.M0Error as error:
        # The older sibling is executable both as a script and as a package,
        # and script-mode imports can give it a distinct M0Error class. Keep
        # this public wrapper's failure type stable in either import mode.
        if isinstance(error, M0Error):
            raise
        raise M0Error(
            f"package Node lifecycle child validation failed: {error}"
        ) from error


def run_package_normal_lifecycle(
    *, dist_dir: Path, node: Path, timeout: float
) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
    """Run one fresh ordinary Node lifecycle from package-snapshot bytes only."""

    expected = capture_package_lifecycle_snapshot(dist_dir)
    node_snapshot = capture_pinned_node(node, expected.node_requirement)
    if node_snapshot.requirement != expected.node_requirement:
        raise M0Error("package Node lifecycle pinned Node requirement changed")
    started = time.perf_counter()
    try:
        with materialized_pinned_node(node_snapshot) as pinned_node:
            validate_pinned_node_version(pinned_node, expected.node_requirement)
            with normal_lifecycle.materialized_artifact_snapshot(expected.artifact) as module:
                completed = normal_lifecycle.run_smoke(module, pinned_node, timeout)
    except normal_lifecycle.M0Error as error:
        if isinstance(error, M0Error):
            raise
        raise M0Error(f"package Node lifecycle child failed: {error}") from error
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    child = _child_result(completed)
    result: dict[str, object] = {
        "artifact": expected.artifact_identity,
        "canvasCopies": child["canvasCopies"],
        "focusReports": len(child["focusReports"]),
        "frameReports": len(child["frameReports"]),
        "node": _node_identity(node_snapshot),
        "packageRuntimeMetadata": expected.runtime_metadata,
        "readinessReports": len(child["readinessReports"]),
        "scope": SCOPE,
        "startupMs": elapsed_ms,
    }
    validate_package_result(result, expected=expected, node=node_snapshot)
    return result, completed


def _relay_child_output(completed: subprocess.CompletedProcess[str]) -> None:
    """Keep child diagnostics while reserving this runner's terminal record."""

    for line in completed.stdout.splitlines(keepends=True):
        if not line.startswith(normal_lifecycle.RESULT_PREFIX):
            sys.stdout.write(line)
    sys.stderr.write(completed.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one package-snapshot ordinary Wasm Browser Node lifecycle."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument(
        "--node",
        type=Path,
        required=True,
        help="explicit Node binary matching the bundled package toolchain pin",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=30.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")

    try:
        result, completed = run_package_normal_lifecycle(
            dist_dir=args.dist_dir,
            node=args.node,
            timeout=args.timeout,
        )
        _relay_child_output(completed)
        print(
            RESULT_PREFIX
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError, KeyError) as error:
        print(f"{FAIL_MARKER} reason={error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

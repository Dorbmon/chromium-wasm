#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exercise the bounded native timer smoke from verified package bytes.

The public pre-release package calls its executable ``chromium-wasm``. This
runner captures that package tree before opening a listening socket, maps only
the captured loader and module bytes to the private ``chrome_wasm`` aliases
expected by the timer host, and runs the existing native UI-sequence timer
lane. The public package index and release host are intentionally not changed
to expose test-only switches.

This is package/reliability preparation, not a release result. In particular,
the package VERSION.json must retain every false gate value and the nested
timer result must retain ``m9GateComplete: false``.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable

if __package__:
    from . import package as package_tool
    from . import run_m9_package_normal_lifecycle_smoke as package_lifecycle
    from . import run_m9_wasm_browser_repeating_timer_dom_smoke as timer
    from .m0_common import M0Error, REPO_ROOT, parse_timeout
    from .m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from .run_browser_smoke import browser_command, find_browser
else:
    import package as package_tool
    import run_m9_package_normal_lifecycle_smoke as package_lifecycle
    import run_m9_wasm_browser_repeating_timer_dom_smoke as timer

    from m0_common import M0Error, REPO_ROOT, parse_timeout
    from m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from run_browser_smoke import browser_command, find_browser


repeating_timer = timer

SENTINEL = "CHROMIUM_WASM_M9_PACKAGE_REPEATING_TIMER_DOM"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
PASS_MARKER = f"{SENTINEL}:PASS"
FAIL_MARKER = f"{SENTINEL}:FAIL"
SCOPE = (
    "verified-package-module-bytes-private-in-memory-alias-fixed-three-native-"
    "ui-repeating-timer-ticks-with-pre-shutdown-quiescence-only"
)
PUBLIC_MODULE_NAME = "chromium-wasm"
PRIVATE_MODULE_NAME = timer.PRODUCT_MODULE_NAME
PACKAGE_ARTIFACT_DELIVERY = "verified-package-snapshot-private-in-memory-alias"
PACKAGE_VERSION_PROVENANCE = (
    "verified-package-version-json-and-bundled-toolchain-metadata-only-not-"
    "source-or-release-provenance"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

LIMITATIONS = (
    "does_not_exercise_the_public_package_index_or_release_host_timer_mode",
    "does_not_claim_package_source_or_release_provenance",
    "does_not_prove_m7_persistent_profile_or_recovery",
    "does_not_prove_m8_feature_compatibility_or_page_webassembly",
    "does_not_complete_m9_reliability_or_release_gates",
    "does_not_measure_long_run_timer_reliability",
)

_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_PACKAGE_ARTIFACT_FIELDS = frozenset(
    (
        "artifact_delivery",
        "artifact_source_provenance",
        "loader",
        "private_module_name",
        "public_module_name",
        "wasm",
    )
)
_RUNTIME_METADATA_FIELDS = frozenset(
    (
        "build",
        "gateState",
        "product",
        "protocol",
        "releaseStatus",
        "schemaVersion",
        "versionJsonSha256",
        "versions",
    )
)
_RUNTIME_BUILD_FIELDS = frozenset(
    (
        "artifactSourceProvenance",
        "inputModuleName",
        "resourceDelivery",
        "stagingCheckout",
    )
)
_RUNTIME_VERSION_FIELDS = frozenset(("chromium", "emscripten", "v8"))
_RESULT_FIELDS = frozenset(
    (
        "m9GateComplete",
        "packageArtifact",
        "packageRuntimeMetadata",
        "releaseStatus",
        "repeatingTimer",
        "scope",
    )
)


@dataclass(frozen=True)
class PackageRepeatingTimerSnapshot:
    """Verified public package executable bytes and fixed gate metadata."""

    artifact: package_lifecycle.normal_lifecycle.ArtifactSnapshot
    artifact_identity: dict[str, object]
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
        raise M0Error(f"package repeating-timer {description} schema is invalid")
    return value


def _byte_identity(contents: bytes) -> dict[str, object]:
    if type(contents) is not bytes or not contents:
        raise M0Error("package repeating-timer executable bytes are invalid")
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"package repeating-timer {description} byte count is invalid")
    digest = identity.get("sha256")
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise M0Error(f"package repeating-timer {description} SHA-256 is invalid")


def _validate_runtime_metadata(value: object) -> dict[str, object]:
    """Require the package VERSION.json false-only gate contract."""

    metadata = _require_exact_fields(value, _RUNTIME_METADATA_FIELDS, "metadata")
    if (
        metadata.get("product") != package_tool.PRODUCT_NAME
        or metadata.get("protocol") != package_tool.PACKAGE_RUNTIME_STATUS_PROTOCOL
        or metadata.get("releaseStatus") != package_tool.RELEASE_STATUS
        or metadata.get("schemaVersion") != package_tool.PACKAGE_SCHEMA_VERSION
    ):
        raise M0Error("package repeating-timer runtime metadata is invalid")
    version_sha256 = metadata.get("versionJsonSha256")
    if type(version_sha256) is not str or not SHA256_RE.fullmatch(version_sha256):
        raise M0Error("package repeating-timer VERSION.json identity is invalid")

    gate_state = metadata.get("gateState")
    if type(gate_state) is not dict or set(gate_state) != set(
        package_tool.EXPECTED_GATE_STATE
    ):
        raise M0Error("package repeating-timer gate state schema is invalid")
    for name, expected in package_tool.EXPECTED_GATE_STATE.items():
        if type(gate_state.get(name)) is not bool or gate_state[name] is not expected:
            raise M0Error(
                "package repeating-timer gate state is not the false-only contract"
            )

    build = _require_exact_fields(
        metadata.get("build"), _RUNTIME_BUILD_FIELDS, "runtime build metadata"
    )
    provenance = build.get("artifactSourceProvenance")
    if (
        type(provenance) is not str
        or provenance not in package_tool.ALLOWED_ARTIFACT_SOURCE_PROVENANCE
    ):
        raise M0Error("package repeating-timer artifact source provenance is invalid")
    if (
        build.get("inputModuleName") != PRIVATE_MODULE_NAME
        or build.get("resourceDelivery") != "embedded-in-wasm-current-build"
        or type(build.get("stagingCheckout")) is not str
        or not GIT_REVISION_RE.fullmatch(build["stagingCheckout"])
    ):
        raise M0Error("package repeating-timer runtime build metadata is invalid")

    versions = _require_exact_fields(
        metadata.get("versions"), _RUNTIME_VERSION_FIELDS, "runtime versions"
    )
    if not all(
        type(revision) is str and GIT_REVISION_RE.fullmatch(revision)
        for revision in versions.values()
    ):
        raise M0Error("package repeating-timer runtime versions are invalid")
    return metadata


def _runtime_versions(metadata: dict[str, object]) -> dict[str, str]:
    """Project the package's bounded identities into the timer host protocol."""

    checked = _validate_runtime_metadata(metadata)
    build = checked["build"]
    versions = checked["versions"]
    assert isinstance(build, dict)
    assert isinstance(versions, dict)
    return {
        "chromium": versions["chromium"],
        "emscripten": versions["emscripten"],
        "port": build["stagingCheckout"],
        "v8": versions["v8"],
    }


def validate_package_artifact_identity(
    value: object,
    *,
    expected: dict[str, object] | None = None,
    runtime_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate public package bytes mapped to a private test-host name."""

    artifact = _require_exact_fields(value, _PACKAGE_ARTIFACT_FIELDS, "artifact")
    if artifact.get("artifact_delivery") != PACKAGE_ARTIFACT_DELIVERY:
        raise M0Error("package repeating-timer artifact delivery is invalid")
    if artifact.get("public_module_name") != PUBLIC_MODULE_NAME:
        raise M0Error("package repeating-timer public module name is invalid")
    if artifact.get("private_module_name") != PRIVATE_MODULE_NAME:
        raise M0Error("package repeating-timer private module name is invalid")
    provenance = artifact.get("artifact_source_provenance")
    if (
        type(provenance) is not str
        or provenance not in package_tool.ALLOWED_ARTIFACT_SOURCE_PROVENANCE
    ):
        raise M0Error("package repeating-timer artifact source provenance is invalid")
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if runtime_metadata is not None:
        metadata = _validate_runtime_metadata(runtime_metadata)
        build = metadata["build"]
        assert isinstance(build, dict)
        if provenance != build["artifactSourceProvenance"]:
            raise M0Error(
                "package repeating-timer artifact provenance disagrees with "
                "VERSION.json"
            )
    if expected is not None and not _exact_json_value_equal(artifact, expected):
        raise M0Error(
            "package repeating-timer artifact identity disagrees with expectation"
        )
    return artifact


def _validate_package_snapshot(
    snapshot: PackageRepeatingTimerSnapshot,
) -> PackageRepeatingTimerSnapshot:
    """Require a package snapshot to retain the bytes named by its identity."""

    if not isinstance(snapshot, PackageRepeatingTimerSnapshot):
        raise M0Error("package repeating-timer snapshot is invalid")
    metadata = _validate_runtime_metadata(snapshot.runtime_metadata)
    identity = validate_package_artifact_identity(
        snapshot.artifact_identity, runtime_metadata=metadata
    )
    artifact = snapshot.artifact
    if (
        not isinstance(artifact, package_lifecycle.normal_lifecycle.ArtifactSnapshot)
        or artifact.module_name != PRIVATE_MODULE_NAME
        or type(artifact.loader) is not bytes
        or not artifact.loader
        or type(artifact.wasm) is not bytes
        or not artifact.wasm
    ):
        raise M0Error("package repeating-timer private executable snapshot is invalid")
    for name, contents in (("loader", artifact.loader), ("wasm", artifact.wasm)):
        if not _exact_json_value_equal(identity.get(name), _byte_identity(contents)):
            raise M0Error(
                "package repeating-timer private executable snapshot does not "
                f"match its {name} identity"
            )
    return snapshot


def capture_package_repeating_timer_snapshot(
    dist_dir: Path,
) -> PackageRepeatingTimerSnapshot:
    """Capture only verified package bytes before a browser is launched."""

    lifecycle_snapshot = package_lifecycle.capture_package_lifecycle_snapshot(dist_dir)
    metadata = _validate_runtime_metadata(lifecycle_snapshot.runtime_metadata)
    artifact = lifecycle_snapshot.artifact
    if (
        artifact.module_name != PRIVATE_MODULE_NAME
        or type(artifact.loader) is not bytes
        or type(artifact.wasm) is not bytes
    ):
        raise M0Error("package repeating-timer private executable snapshot is invalid")
    build = metadata["build"]
    assert isinstance(build, dict)
    artifact_identity = {
        "artifact_delivery": PACKAGE_ARTIFACT_DELIVERY,
        "artifact_source_provenance": build["artifactSourceProvenance"],
        "loader": _byte_identity(artifact.loader),
        "private_module_name": PRIVATE_MODULE_NAME,
        "public_module_name": PUBLIC_MODULE_NAME,
        "wasm": _byte_identity(artifact.wasm),
    }
    validate_package_artifact_identity(
        artifact_identity, expected=artifact_identity, runtime_metadata=metadata
    )
    snapshot = PackageRepeatingTimerSnapshot(
        artifact=artifact,
        artifact_identity=artifact_identity,
        runtime_metadata=metadata,
    )
    return _validate_package_snapshot(snapshot)


def _timer_alias_identity(
    snapshot: PackageRepeatingTimerSnapshot,
    server: timer.RepeatingTimerSmokeServer,
) -> dict[str, object]:
    """Bind the timer-host module aliases to the verified public package bytes."""

    snapshot = _validate_package_snapshot(snapshot)
    package_artifact = snapshot.artifact_identity
    build = snapshot.runtime_metadata["build"]
    assert isinstance(build, dict)
    aliases = timer.artifact_identity(
        server,
        module_name=PRIVATE_MODULE_NAME,
        artifact_delivery=PACKAGE_ARTIFACT_DELIVERY,
        artifact_source_provenance=build["artifactSourceProvenance"],
    )
    expected = {
        "artifact_delivery": PACKAGE_ARTIFACT_DELIVERY,
        "artifact_source_provenance": build["artifactSourceProvenance"],
        "loader": package_artifact["loader"],
        "module_name": PRIVATE_MODULE_NAME,
        "wasm": package_artifact["wasm"],
    }
    if not _exact_json_value_equal(aliases, expected):
        raise M0Error(
            "package repeating-timer private aliases do not match package bytes"
        )
    return expected


def _validate_timer_alias_identity(
    value: object, snapshot: PackageRepeatingTimerSnapshot
) -> dict[str, object]:
    """Require the child validator to receive this package's exact aliases."""

    if type(value) is not dict:
        raise M0Error("package repeating-timer private alias is invalid")
    snapshot = _validate_package_snapshot(snapshot)
    package_artifact = snapshot.artifact_identity
    build = snapshot.runtime_metadata["build"]
    assert isinstance(build, dict)
    expected = {
        "artifact_delivery": PACKAGE_ARTIFACT_DELIVERY,
        "artifact_source_provenance": build["artifactSourceProvenance"],
        "loader": package_artifact["loader"],
        "module_name": PRIVATE_MODULE_NAME,
        "wasm": package_artifact["wasm"],
    }
    if not _exact_json_value_equal(value, expected):
        raise M0Error(
            "package repeating-timer private alias does not match package bytes"
        )
    return expected


def create_package_repeating_timer_server(
    host: str,
    port: int,
    snapshot: PackageRepeatingTimerSnapshot,
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> timer.RepeatingTimerSmokeServer:
    """Serve immutable private aliases of the previously verified package bytes."""

    snapshot = _validate_package_snapshot(snapshot)
    return timer.create_server_from_artifacts(
        host,
        port,
        {
            f"{PRIVATE_MODULE_NAME}.js": snapshot.artifact.loader,
            f"{PRIVATE_MODULE_NAME}.wasm": snapshot.artifact.wasm,
        },
        token,
        result_queue,
        module_name=PRIVATE_MODULE_NAME,
        host_dir=host_dir,
        runner_source_path=runner_source_path or Path(__file__),
    )


def package_repeating_timer_result(
    runtime_result: dict[str, Any], snapshot: PackageRepeatingTimerSnapshot
) -> dict[str, object]:
    """Wrap a timer-host observation in package-bound, false-only metadata."""

    return {
        "m9GateComplete": False,
        "packageArtifact": snapshot.artifact_identity,
        "packageRuntimeMetadata": snapshot.runtime_metadata,
        "releaseStatus": package_tool.RELEASE_STATUS,
        "repeatingTimer": runtime_result,
        "scope": SCOPE,
    }


def validate_package_repeating_timer_result(
    value: object,
    *,
    expected_snapshot: PackageRepeatingTimerSnapshot,
    expected_alias_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
) -> dict[str, object]:
    """Validate package metadata plus the existing strict timer evidence."""

    expected_snapshot = _validate_package_snapshot(expected_snapshot)
    result = _require_exact_fields(value, _RESULT_FIELDS, "result")
    if result.get("scope") != SCOPE:
        raise M0Error("package repeating-timer result scope is invalid")
    if type(result.get("m9GateComplete")) is not bool or result["m9GateComplete"]:
        raise M0Error("package repeating-timer result must not complete M9")
    if result.get("releaseStatus") != package_tool.RELEASE_STATUS:
        raise M0Error("package repeating-timer result release status is invalid")
    validate_package_artifact_identity(
        result.get("packageArtifact"),
        expected=expected_snapshot.artifact_identity,
        runtime_metadata=expected_snapshot.runtime_metadata,
    )
    if not _exact_json_value_equal(
        result.get("packageRuntimeMetadata"), expected_snapshot.runtime_metadata
    ):
        raise M0Error(
            "package repeating-timer runtime metadata disagrees with snapshot"
        )
    runtime_result = result.get("repeatingTimer")
    if type(runtime_result) is not dict:
        raise M0Error("package repeating-timer runtime result is invalid")
    _validate_timer_alias_identity(expected_alias_identity, expected_snapshot)
    build = expected_snapshot.runtime_metadata["build"]
    assert isinstance(build, dict)
    timer.validate_result(
        runtime_result,
        expected_versions=_runtime_versions(expected_snapshot.runtime_metadata),
        expected_artifact_identity=expected_alias_identity,
        expected_capture_harness_identity=expected_capture_harness_identity,
        expected_artifact_delivery=PACKAGE_ARTIFACT_DELIVERY,
        expected_artifact_source_provenance=build["artifactSourceProvenance"],
        expected_version_provenance=PACKAGE_VERSION_PROVENANCE,
    )
    return result


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    try:
        action()
    except BaseException as error:
        if cleanup_error is None:
            return error
    return cleanup_error


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    package_snapshot: PackageRepeatingTimerSnapshot | None,
    runtime_result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-package-repeating-timer-m9-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m9_package_repeating_timer_dom_smoke.py",
        "scope": SCOPE,
        "stage": stage,
        "limitations": list(LIMITATIONS),
        "failure": {"type": type(error).__name__, "message": str(error)},
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
        "package_artifact": (
            package_snapshot.artifact_identity if package_snapshot else None
        ),
        "package_runtime_metadata": (
            package_snapshot.runtime_metadata if package_snapshot else None
        ),
        "runtime_result": runtime_result,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded native UI timer from verified package bytes."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=60.0)
    args = parser.parse_args()
    if args.timeout < 3.0:
        parser.error("--timeout must be at least three seconds")

    dist_dir = (
        args.dist_dir if args.dist_dir.is_absolute() else REPO_ROOT / args.dist_dir
    )
    diagnostics_dir = args.diagnostics_dir or (
        Path(tempfile.gettempdir())
        / "chromium-wasm-m9-package-repeating-timer-diagnostics"
    )
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    server: timer.RepeatingTimerSmokeServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_reader: BrowserStderrReader | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    package_snapshot: PackageRepeatingTimerSnapshot | None = None
    runtime_result: dict[str, Any] | None = None
    result: dict[str, object] | None = None
    alias_identity: dict[str, object] | None = None
    capture_harness: dict[str, object] | None = None
    stage = "snapshot_package"
    primary_error: BaseException | None = None
    reported_error: Exception | None = None

    try:
        package_snapshot = capture_package_repeating_timer_snapshot(dist_dir)
        versions = _runtime_versions(package_snapshot.runtime_metadata)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

        stage = "create_server"
        server = create_package_repeating_timer_server(
            "127.0.0.1", 0, package_snapshot, token, result_queue
        )
        alias_identity = _timer_alias_identity(package_snapshot, server)
        capture_harness = timer.capture_harness_identity(
            server, version_provenance=PACKAGE_VERSION_PROVENANCE
        )
        context = {
            "artifact": package_snapshot.artifact_identity,
            "capture_harness": capture_harness,
            "host_browser_sandbox": not args.no_sandbox,
            "limitations": list(LIMITATIONS),
            "package_runtime_metadata": package_snapshot.runtime_metadata,
            "runtime_arguments": [timer.SWITCH],
            "scope": SCOPE,
            "script": "run_m9_package_repeating_timer_dom_smoke.py",
            "toolchain_versions": versions,
            "version_provenance": PACKAGE_VERSION_PROVENANCE,
        }
        print(
            "CHROMIUM_WASM_M0:CONFIG "
            + json.dumps(context, sort_keys=True, separators=(",", ":")),
            flush=True,
        )

        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        stage = "serve"
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-package-repeating-timer-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        url = timer.smoke_url(
            server,
            token,
            versions,
            artifact=alias_identity,
            capture_harness=capture_harness,
            module_name=PRIVATE_MODULE_NAME,
            timeout_seconds=max(1.0, args.timeout - 1.0),
        )
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m9-package-repeating-timer-"
        )
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = ["--enable-logging=stderr"]
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        stderr_reader = BrowserStderrReader(
            browser.stderr,
            browser_stderr,
            name="chromium-wasm-m9-package-repeating-timer-browser-stderr",
            thread_factory=threading.Thread,
        )
        stderr_reader.start()
        stage = "wait_for_normal_close_result"
        runtime_result = timer.wait_for_result(
            browser, browser_stderr, result_queue, time.monotonic() + args.timeout
        )
        result = package_repeating_timer_result(runtime_result, package_snapshot)
        stage = "validate_result"
        assert alias_identity is not None
        assert capture_harness is not None
        validate_package_repeating_timer_result(
            result,
            expected_snapshot=package_snapshot,
            expected_alias_identity=alias_identity,
            expected_capture_harness_identity=capture_harness,
        )
    except (M0Error, timer.M0Error, OSError, KeyError, TypeError, ValueError) as error:
        primary_error = error
        reported_error = error
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_error: BaseException | None = None
        if browser is not None and stderr_reader is not None and stderr_reader.started:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: stop_browser_group(browser, stderr_reader)
            )
        elif browser is not None:
            unowned_streams = ()
            if stderr_reader is None and browser.stderr is not None:
                unowned_streams = (browser.stderr,)
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: abort_browser_group(
                    browser, stderr_reader, unowned_streams=unowned_streams
                ),
            )
        server_cleanup_error = timer._cleanup_repeating_timer_server(
            server=server,
            server_thread=server_thread,
            server_thread_started=server_thread_started,
        )
        if cleanup_error is None:
            cleanup_error = server_cleanup_error
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            if isinstance(cleanup_error, Exception):
                reported_error = cleanup_error
            else:
                raise cleanup_error

    if reported_error is not None:
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=reported_error,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                package_snapshot=package_snapshot,
                runtime_result=runtime_result,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic)}, sort_keys=True),
                file=sys.stderr,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
            )
        print(f"{FAIL_MARKER} reason={reported_error}", file=sys.stderr, flush=True)
        return 1
    if result is None:
        raise RuntimeError("package repeating-timer smoke completed without a result")
    print(
        RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(PASS_MARKER, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

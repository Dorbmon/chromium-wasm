#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exercise fixed native tab churn from verified pre-release package bytes.

This runner captures and verifies one staged package tree before a server is
started.  It maps the package's public ``chromium-wasm`` executable names to
private ``chrome_wasm`` test-host aliases entirely in memory, then reuses the
fixed trusted-DOM/native Views tab-churn lane.  It does not read a raw build
output directory, alter the public package host, or claim that the public
package index exposes a tab-churn interface.

The resulting evidence is intentionally narrow: verified package executable
bytes can run the existing three-cycle test-only browser UI flow.  It is not
M7 persistence, M8 compatibility, package-source/release provenance, or M9
release evidence.
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
    from . import run_m9_wasm_browser_tab_churn_dom_smoke as tab_churn
    from .m0_common import M0Error, REPO_ROOT, parse_timeout
    from .m4_cdp import unused_loopback_port, wait_for_page_client
    from .m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from .m9_server_cleanup import shutdown_server_bounded
    from .run_browser_smoke import browser_command, find_browser
else:
    import package as package_tool
    import run_m9_package_normal_lifecycle_smoke as package_lifecycle
    import run_m9_wasm_browser_tab_churn_dom_smoke as tab_churn

    from m0_common import M0Error, REPO_ROOT, parse_timeout
    from m4_cdp import unused_loopback_port, wait_for_page_client
    from m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from m9_server_cleanup import shutdown_server_bounded
    from run_browser_smoke import browser_command, find_browser


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE_TAB_CHURN_DOM"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
PASS_MARKER = f"{SENTINEL}:PASS"
FAIL_MARKER = f"{SENTINEL}:FAIL"
SCOPE = (
    "verified-package-module-bytes-private-in-memory-alias-fixed-three-cycle-"
    "trusted-dom-native-tab-churn-only"
)
PACKAGE_ARTIFACT_DELIVERY = "verified-package-snapshot-private-in-memory-alias"
PACKAGE_VERSION_PROVENANCE = (
    "verified-package-version-json-and-bundled-toolchain-metadata-only-not-"
    "source-or-release-provenance"
)
PUBLIC_MODULE_NAME = "chromium-wasm"
PRIVATE_MODULE_NAME = "chrome_wasm"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

LIMITATIONS = (
    "does_not_exercise_the_public_package_index_or_release_host_tab_churn_mode",
    "does_not_claim_package_source_or_release_provenance",
    "does_not_prove_m7_persistent_profile_or_recovery",
    "does_not_prove_m8_feature_compatibility_or_page_webassembly",
    "does_not_complete_m9_reliability_or_release_gates",
    *tab_churn.LIMITATIONS,
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
        "scope",
        "tabChurn",
    )
)


@dataclass(frozen=True)
class PackageTabChurnSnapshot:
    """Verified package executable bytes and bounded package metadata."""

    artifact: package_lifecycle.normal_lifecycle.ArtifactSnapshot
    artifact_identity: dict[str, object]
    runtime_metadata: dict[str, object]


def _exact_json_value_equal(value: object, expected: object) -> bool:
    """Compare JSON-shaped values without bool/int coercion."""

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
        raise M0Error(f"package tab-churn {description} schema is invalid")
    return value


def _byte_identity(contents: bytes) -> dict[str, object]:
    if type(contents) is not bytes or not contents:
        raise M0Error("package tab-churn executable bytes are invalid")
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"package tab-churn {description} byte count is invalid")
    digest = identity.get("sha256")
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise M0Error(f"package tab-churn {description} SHA-256 is invalid")


def _validate_runtime_metadata(value: object) -> dict[str, object]:
    """Validate the bounded metadata projected from verified VERSION.json."""

    metadata = _require_exact_fields(value, _RUNTIME_METADATA_FIELDS, "metadata")
    if (
        metadata.get("product") != package_tool.PRODUCT_NAME
        or metadata.get("protocol") != package_tool.PACKAGE_RUNTIME_STATUS_PROTOCOL
        or metadata.get("releaseStatus") != package_tool.RELEASE_STATUS
        or metadata.get("schemaVersion") != package_tool.PACKAGE_SCHEMA_VERSION
    ):
        raise M0Error("package tab-churn runtime metadata is invalid")
    version_sha256 = metadata.get("versionJsonSha256")
    if type(version_sha256) is not str or not SHA256_RE.fullmatch(version_sha256):
        raise M0Error("package tab-churn VERSION.json identity is invalid")

    gate_state = metadata.get("gateState")
    if (
        type(gate_state) is not dict
        or set(gate_state) != set(package_tool.EXPECTED_GATE_STATE)
    ):
        raise M0Error("package tab-churn gate state schema is invalid")
    for name, expected in package_tool.EXPECTED_GATE_STATE.items():
        if type(gate_state.get(name)) is not bool or gate_state[name] is not expected:
            raise M0Error("package tab-churn gate state is not the false-only contract")

    build = _require_exact_fields(
        metadata.get("build"), _RUNTIME_BUILD_FIELDS, "runtime build metadata"
    )
    provenance = build.get("artifactSourceProvenance")
    if (
        type(provenance) is not str
        or provenance not in package_tool.ALLOWED_ARTIFACT_SOURCE_PROVENANCE
    ):
        raise M0Error("package tab-churn artifact source provenance is invalid")
    if (
        build.get("inputModuleName") != PRIVATE_MODULE_NAME
        or build.get("resourceDelivery") != "embedded-in-wasm-current-build"
        or type(build.get("stagingCheckout")) is not str
        or not GIT_REVISION_RE.fullmatch(build["stagingCheckout"])
    ):
        raise M0Error("package tab-churn runtime build metadata is invalid")

    versions = _require_exact_fields(
        metadata.get("versions"), _RUNTIME_VERSION_FIELDS, "runtime versions"
    )
    if not all(
        type(revision) is str and GIT_REVISION_RE.fullmatch(revision)
        for revision in versions.values()
    ):
        raise M0Error("package tab-churn runtime versions are invalid")
    return metadata


def _runtime_versions(metadata: dict[str, object]) -> dict[str, str]:
    checked = _validate_runtime_metadata(metadata)
    versions = checked["versions"]
    assert isinstance(versions, dict)
    return {
        "chromium": versions["chromium"],
        "v8": versions["v8"],
        "emscripten": versions["emscripten"],
    }


def validate_package_artifact_identity(
    value: object,
    *,
    expected: dict[str, object] | None = None,
    runtime_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate package-public bytes mapped to private test-host aliases."""

    artifact = _require_exact_fields(value, _PACKAGE_ARTIFACT_FIELDS, "artifact")
    if artifact.get("artifact_delivery") != PACKAGE_ARTIFACT_DELIVERY:
        raise M0Error("package tab-churn artifact delivery is invalid")
    if artifact.get("public_module_name") != PUBLIC_MODULE_NAME:
        raise M0Error("package tab-churn public module name is invalid")
    if artifact.get("private_module_name") != PRIVATE_MODULE_NAME:
        raise M0Error("package tab-churn private module name is invalid")
    provenance = artifact.get("artifact_source_provenance")
    if (
        type(provenance) is not str
        or provenance not in package_tool.ALLOWED_ARTIFACT_SOURCE_PROVENANCE
    ):
        raise M0Error("package tab-churn artifact source provenance is invalid")
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if runtime_metadata is not None:
        metadata = _validate_runtime_metadata(runtime_metadata)
        build = metadata["build"]
        assert isinstance(build, dict)
        if provenance != build["artifactSourceProvenance"]:
            raise M0Error(
                "package tab-churn artifact provenance disagrees with VERSION.json"
            )
    if expected is not None and not _exact_json_value_equal(artifact, expected):
        raise M0Error("package tab-churn artifact identity disagrees with expectation")
    return artifact


def capture_package_tab_churn_snapshot(dist_dir: Path) -> PackageTabChurnSnapshot:
    """Capture only verified staged package bytes before a browser is launched."""

    lifecycle_snapshot = package_lifecycle.capture_package_lifecycle_snapshot(dist_dir)
    artifact = lifecycle_snapshot.artifact
    metadata = _validate_runtime_metadata(lifecycle_snapshot.runtime_metadata)
    if (
        artifact.module_name != PRIVATE_MODULE_NAME
        or type(artifact.loader) is not bytes
        or type(artifact.wasm) is not bytes
    ):
        raise M0Error("package tab-churn private executable snapshot is invalid")
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
        artifact_identity, runtime_metadata=metadata, expected=artifact_identity
    )
    return PackageTabChurnSnapshot(
        artifact=artifact,
        artifact_identity=artifact_identity,
        runtime_metadata=metadata,
    )


def create_package_tab_churn_server(
    host: str,
    port: int,
    snapshot: PackageTabChurnSnapshot,
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    host_dir: Path | None = None,
    runner_source_path: Path | None = None,
) -> tab_churn.TabChurnSmokeServer:
    """Serve only private aliases of the captured package executable bytes."""

    if not isinstance(snapshot, PackageTabChurnSnapshot):
        raise M0Error("package tab-churn snapshot is invalid")
    validate_package_artifact_identity(
        snapshot.artifact_identity, runtime_metadata=snapshot.runtime_metadata
    )
    if snapshot.artifact.module_name != PRIVATE_MODULE_NAME:
        raise M0Error("package tab-churn private executable snapshot is invalid")
    aliases = {
        f"{PRIVATE_MODULE_NAME}.js": snapshot.artifact.loader,
        f"{PRIVATE_MODULE_NAME}.wasm": snapshot.artifact.wasm,
    }
    return tab_churn.create_server_from_artifacts(
        host,
        port,
        aliases,
        token,
        result_queue,
        module_name=PRIVATE_MODULE_NAME,
        host_dir=host_dir,
        runner_source_path=runner_source_path or Path(__file__),
    )


def _require_alias_identity_matches_package(
    alias_identity: dict[str, object], package_identity: dict[str, object]
) -> None:
    """Bind the test server's private aliases to public package byte hashes."""

    validated_package = validate_package_artifact_identity(package_identity)
    for name in ("loader", "wasm"):
        alias = alias_identity.get(name)
        package = validated_package.get(name)
        if not _exact_json_value_equal(alias, package):
            raise M0Error(
                "package tab-churn private alias does not match packaged "
                f"{name} bytes"
            )


def validate_package_tab_churn_result(
    value: object,
    *,
    expected_snapshot: PackageTabChurnSnapshot,
    expected_alias_identity: dict[str, object],
    expected_capture_harness_identity: dict[str, object],
    expected_pointer_abi_rejection_seed: bool,
) -> dict[str, object]:
    """Validate package binding plus all existing trusted DOM/UI evidence."""

    result = _require_exact_fields(value, _RESULT_FIELDS, "result")
    if result.get("scope") != SCOPE:
        raise M0Error("package tab-churn result scope is invalid")
    if type(result.get("m9GateComplete")) is not bool or result["m9GateComplete"]:
        raise M0Error("package tab-churn result must not complete M9")
    if result.get("releaseStatus") != package_tool.RELEASE_STATUS:
        raise M0Error("package tab-churn result release status is invalid")
    validate_package_artifact_identity(
        result.get("packageArtifact"),
        expected=expected_snapshot.artifact_identity,
        runtime_metadata=expected_snapshot.runtime_metadata,
    )
    if not _exact_json_value_equal(
        result.get("packageRuntimeMetadata"), expected_snapshot.runtime_metadata
    ):
        raise M0Error("package tab-churn runtime metadata disagrees with snapshot")
    _require_alias_identity_matches_package(
        expected_alias_identity, expected_snapshot.artifact_identity
    )
    runtime_result = result.get("tabChurn")
    if type(runtime_result) is not dict:
        raise M0Error("package tab-churn runtime result is invalid")
    tab_churn.validate_result(
        runtime_result,
        expected_versions=_runtime_versions(expected_snapshot.runtime_metadata),
        expected_artifact_identity=expected_alias_identity,
        expected_capture_harness_identity=expected_capture_harness_identity,
        expected_pointer_abi_rejection_seed=expected_pointer_abi_rejection_seed,
    )
    return result


def package_tab_churn_result(
    runtime_result: dict[str, Any], snapshot: PackageTabChurnSnapshot
) -> dict[str, object]:
    """Wrap a verified internal test-host result in package-only evidence."""

    return {
        "m9GateComplete": False,
        "packageArtifact": snapshot.artifact_identity,
        "packageRuntimeMetadata": snapshot.runtime_metadata,
        "releaseStatus": package_tool.RELEASE_STATUS,
        "scope": SCOPE,
        "tabChurn": runtime_result,
    }


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    try:
        action()
    except BaseException as error:
        if cleanup_error is None:
            return error
    return cleanup_error


def _cleanup_server(
    *,
    server: tab_churn.TabChurnSmokeServer | None,
    server_thread: threading.Thread | None,
    server_thread_started: bool,
) -> BaseException | None:
    cleanup_error: BaseException | None = None
    if server is not None:
        if server_thread_started:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: shutdown_server_bounded(
                    server, timeout=1, description="M9 package tab-churn server"
                ),
            )
        cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
    if server_thread_started and server_thread is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error, lambda: server_thread.join(timeout=1)
        )
        if server_thread.is_alive() and cleanup_error is None:
            cleanup_error = M0Error("M9 package tab-churn server did not stop")
    if server is not None:
        cleanup_error = _run_cleanup_action(
            cleanup_error,
            lambda: server.join_request_handlers(
                timeout=1, description="M9 package tab-churn server"
            ),
        )
    return cleanup_error


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    context: dict[str, object] | None,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    runtime_result: dict[str, Any] | None,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-package-tab-churn-m9-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m9_package_tab_churn_dom_smoke.py",
        "scope": SCOPE,
        "stage": stage,
        "limitations": list(LIMITATIONS),
        "failure": {"type": type(error).__name__, "message": str(error)},
        "context": context,
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
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
        description=(
            "Run fixed trusted-DOM/native tab churn from verified pre-release "
            "package bytes."
        )
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--pointer-abi-rejection-seed", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=90.0)
    args = parser.parse_args()
    if args.timeout < 15.0:
        parser.error("--timeout must be at least fifteen seconds")

    dist_dir = (
        args.dist_dir
        if args.dist_dir.is_absolute()
        else REPO_ROOT / args.dist_dir
    )
    diagnostics_dir = args.diagnostics_dir or (
        Path(tempfile.gettempdir()) / "chromium-wasm-m9-package-tab-churn-diagnostics"
    )
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    server: tab_churn.TabChurnSmokeServer | None = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    client: Any = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_reader: BrowserStderrReader | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    package_snapshot: PackageTabChurnSnapshot | None = None
    runtime_result: dict[str, Any] | None = None
    result: dict[str, object] | None = None
    context: dict[str, object] | None = None
    alias_identity: dict[str, object] | None = None
    capture_harness: dict[str, object] | None = None
    stage = "snapshot_package"
    primary_error: BaseException | None = None
    reported_error: Exception | None = None

    try:
        package_snapshot = capture_package_tab_churn_snapshot(dist_dir)
        versions = _runtime_versions(package_snapshot.runtime_metadata)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

        stage = "create_server"
        server = create_package_tab_churn_server(
            "127.0.0.1", 0, package_snapshot, token, result_queue
        )
        alias_identity = tab_churn.artifact_identity(
            server, module_name=PRIVATE_MODULE_NAME
        )
        capture_harness = tab_churn.capture_harness_identity(server)
        _require_alias_identity_matches_package(
            alias_identity, package_snapshot.artifact_identity
        )
        tab_churn.verify_required_exports(server.artifacts[f"{PRIVATE_MODULE_NAME}.js"])
        context = {
            "artifact": package_snapshot.artifact_identity,
            "capture_harness": capture_harness,
            "host_browser_sandbox": not args.no_sandbox,
            "limitations": list(LIMITATIONS),
            "package_runtime_metadata": package_snapshot.runtime_metadata,
            "pointer_abi_rejection_seed": args.pointer_abi_rejection_seed,
            "runtime_arguments": [tab_churn.SWITCH],
            "scope": SCOPE,
            "script": "run_m9_package_tab_churn_dom_smoke.py",
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
        stage = "start_server"
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-package-tab-churn-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        url = tab_churn.smoke_url(
            server,
            token,
            versions,
            artifact=alias_identity,
            capture_harness=capture_harness,
            module_name=PRIVATE_MODULE_NAME,
            timeout_seconds=max(1.0, args.timeout - 1.0),
            pointer_abi_rejection_seed=args.pointer_abi_rejection_seed,
        )
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m9-package-tab-churn-"
        )
        debug_port = unused_loopback_port()
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = [
            "--enable-logging=stderr",
            "--remote-allow-origins=http://localhost",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
        ]
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
            name="chromium-wasm-m9-package-tab-churn-browser-stderr",
            thread_factory=threading.Thread,
        )
        stderr_reader.start()
        deadline = time.monotonic() + args.timeout
        stage = "connect_devtools"
        client = wait_for_page_client(debug_port, url.split("?", 1)[0], deadline)
        for ordinal in range(1, tab_churn.STAGE_COUNT + 1):
            expected = tab_churn.stage_info(ordinal)
            stage = f"wait_for_stage_{ordinal}"
            state = tab_churn.wait_for_stage(
                client, browser, browser_stderr, result_queue, expected, deadline
            )
            stage = f"dispatch_stage_{ordinal}"
            tab_churn.click_target(client, state)
        stage = "wait_for_result"
        runtime_result = tab_churn.wait_for_result(
            browser, browser_stderr, result_queue, deadline
        )
        result = package_tab_churn_result(runtime_result, package_snapshot)
        stage = "validate_result"
        validate_package_tab_churn_result(
            result,
            expected_snapshot=package_snapshot,
            expected_alias_identity=alias_identity,
            expected_capture_harness_identity=capture_harness,
            expected_pointer_abi_rejection_seed=args.pointer_abi_rejection_seed,
        )
    # The legacy tab-churn runner imports ``m0_common`` as a top-level module.
    # A package-mode import therefore gives its M0Error a distinct class
    # identity from this runner's ``tools.wasm.m0_common.M0Error``.  Normalize
    # that shared failure into this command's ordinary diagnostic/exit path.
    except (
        M0Error,
        tab_churn.M0Error,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        primary_error = error
        reported_error = error
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_error: BaseException | None = None
        if client is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, client.close)
        if browser is not None and stderr_reader is not None and stderr_reader.started:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: stop_browser_group(browser, stderr_reader)
            )
        elif browser is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: abort_browser_group(browser, stderr_reader)
            )
        server_cleanup_error = _cleanup_server(
            server=server,
            server_thread=server_thread,
            server_thread_started=server_thread_started,
        )
        if cleanup_error is None:
            cleanup_error = server_cleanup_error
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error

    if reported_error is not None:
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=reported_error,
                context=context,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
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
        raise RuntimeError("package tab-churn completed without a result")
    print(
        f"{RESULT_PREFIX}" + json.dumps(result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(PASS_MARKER, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

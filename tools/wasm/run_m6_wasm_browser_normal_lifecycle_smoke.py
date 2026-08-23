#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run ordinary no-switch Wasm Browser launch and shutdown under pinned Node."""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator

from check_m6_chrome_boundary import check_boundary
from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m9_descriptor_snapshot import snapshot_regular_files
from run_content_shell_smoke import manifest_versions
from run_node_smoke import node_executable
import run_m6_wasm_browser_smoke as browser_smoke


SENTINEL = "CHROMIUM_WASM_M6_NORMAL_BROWSER"
READY_MARKER = f"{SENTINEL}:READY"
PASS_MARKER = f"{SENTINEL}:PASS"
RESULT_PREFIX = f"{SENTINEL}:NODE_EXIT "
NODE_PASS_MARKER = f"{SENTINEL}_NODE:PASS"
DEFAULT_MODULE_NAME = "chrome_wasm"
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_ARTIFACT_IDENTITY_FIELDS = frozenset(
    (
        "artifact_delivery",
        "artifact_source_provenance",
        "loader",
        "module_name",
        "wasm",
    )
)
_VERSION_IDENTITY_FIELDS = frozenset(("chromium", "v8", "emscripten", "port"))
# The ordinary Node runner imports its loader and starts pthread workers from
# this directory. It is a private temporary copy of captured bytes, not a
# source-provenance assertion about the selected output directory.
ARTIFACT_DELIVERY = "private-temporary-file-snapshot"
ARTIFACT_SOURCE_PROVENANCE = "unverified"


@dataclass(frozen=True)
class ArtifactSnapshot:
    """One immutable-in-process capture of the ordinary Node artifacts."""

    module_name: str
    loader: bytes
    wasm: bytes


def snapshot_run_version_identity(manifest: object) -> dict[str, str]:
    """Capture one normal-run version observation before Node starts.

    This is deliberately a run-local observation. It does not identify the
    captured executable bytes or establish source/artifact provenance.
    """

    try:
        versions = manifest_versions(
            manifest, checked_output(["git", "rev-parse", "HEAD"])
        )
    except M0Error as error:
        raise M0Error("ordinary Browser run version identity is invalid") from error
    if (
        not isinstance(versions, dict)
        or set(versions) != _VERSION_IDENTITY_FIELDS
        or not all(
            type(revision) is str and revision for revision in versions.values()
        )
    ):
        raise M0Error("ordinary Browser run version identity is invalid")
    return {name: versions[name] for name in sorted(_VERSION_IDENTITY_FIELDS)}


def _require_module_name(value: object, description: str) -> str:
    if type(value) is not str or not _MODULE_NAME_RE.fullmatch(value):
        raise M0Error(
            f"ordinary Browser {description} module name must contain only ASCII "
            "letters, digits, or _"
        )
    return value


def capture_artifact_snapshot(out_dir: Path, module_name: object) -> ArtifactSnapshot:
    """Capture the Node loader and Wasm bytes exactly once from this output dir."""
    module_name = _require_module_name(module_name, "artifact")
    artifact_names = (f"{module_name}.js", f"{module_name}.wasm")
    captured = snapshot_regular_files(
        out_dir,
        artifact_names,
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="ordinary Browser executable artifact",
    )
    return ArtifactSnapshot(
        module_name=module_name,
        loader=captured[f"{module_name}.js"],
        wasm=captured[f"{module_name}.wasm"],
    )


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def artifact_identity(snapshot: ArtifactSnapshot) -> dict[str, object]:
    """Return the identity of the bytes that the temporary Node files use."""
    module_name = _require_module_name(snapshot.module_name, "artifact")
    if type(snapshot.loader) is not bytes or type(snapshot.wasm) is not bytes:
        raise M0Error("ordinary Browser artifact snapshot is invalid")
    if not snapshot.loader or not snapshot.wasm:
        raise M0Error("ordinary Browser artifact snapshot is invalid")
    return {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "loader": _byte_identity(snapshot.loader),
        "module_name": module_name,
        "wasm": _byte_identity(snapshot.wasm),
    }


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"ordinary Browser {description} schema is invalid: expected "
            f"{sorted(expected)!r}, got {actual!r}"
        )
    return value


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"ordinary Browser {description} byte count is invalid")
    sha256 = identity.get("sha256")
    if type(sha256) is not str or not SHA256_RE.fullmatch(sha256):
        raise M0Error(f"ordinary Browser {description} SHA-256 is invalid")


def _exact_json_value_equal(value: object, expected: object) -> bool:
    """Compare JSON data without Python bool/int aliases."""
    if type(value) is not type(expected):
        return False
    if isinstance(value, dict):
        return set(value) == set(expected) and all(
            _exact_json_value_equal(value[key], expected[key]) for key in value
        )
    if isinstance(value, list):
        return len(value) == len(expected) and all(
            _exact_json_value_equal(actual, wanted)
            for actual, wanted in zip(value, expected)
        )
    return value == expected


def validate_artifact_identity(
    value: object,
    *,
    expected_module_name: object,
    expected_artifact_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate the exact ordinary-Node snapshot identity reported to M9."""
    module_name = _require_module_name(expected_module_name, "expected artifact")
    artifact = _require_exact_fields(
        value, _ARTIFACT_IDENTITY_FIELDS, "artifact identity"
    )
    if artifact.get("artifact_delivery") != ARTIFACT_DELIVERY:
        raise M0Error("ordinary Browser artifact delivery is invalid")
    if artifact.get("artifact_source_provenance") != ARTIFACT_SOURCE_PROVENANCE:
        raise M0Error("ordinary Browser artifact source provenance is invalid")
    if artifact.get("module_name") != module_name:
        raise M0Error(
            "ordinary Browser artifact module name disagrees with configured module"
        )
    for field in ("loader", "wasm"):
        _validate_byte_identity(artifact.get(field), f"artifact {field}")
    if expected_artifact_identity is not None and not _exact_json_value_equal(
        artifact, expected_artifact_identity
    ):
        raise M0Error("ordinary Browser artifact identity disagrees with expectation")
    return artifact


@contextlib.contextmanager
def materialized_artifact_snapshot(snapshot: ArtifactSnapshot) -> Iterator[Path]:
    """Materialize captured bytes for Node's file import and pthread workers."""
    module_name = _require_module_name(snapshot.module_name, "snapshot")
    if type(snapshot.loader) is not bytes or type(snapshot.wasm) is not bytes:
        raise M0Error("ordinary Browser artifact snapshot is invalid")
    with tempfile.TemporaryDirectory(
        prefix="chromium-wasm-m6-normal-artifact-"
    ) as path:
        snapshot_dir = Path(path)
        module = snapshot_dir / f"{module_name}.js"
        wasm = snapshot_dir / f"{module_name}.wasm"
        try:
            module.write_bytes(snapshot.loader)
            wasm.write_bytes(snapshot.wasm)
        except OSError as error:
            raise M0Error(
                f"cannot materialize ordinary Browser artifact snapshot: {error}"
            ) from error
        yield module


def _replace_once(source: str, old: str, new: str, description: str) -> str:
    if source.count(old) != 1:
        raise M0Error(f"browser runner no longer has one {description} hook")
    return source.replace(old, new, 1)


def runner_source(module_url: str, timeout_ms: int) -> str:
    """Returns a strict no-switch host that requests browser-main shutdown."""
    source = browser_smoke.runner_source(module_url, timeout_ms)
    source = _replace_once(
        source, browser_smoke.PASS_MARKER, PASS_MARKER, "pass marker"
    )
    source = _replace_once(
        source, browser_smoke.READY_MARKER, READY_MARKER, "ready marker"
    )
    source = _replace_once(
        source, browser_smoke.RESULT_PREFIX, RESULT_PREFIX, "result marker"
    )
    source = _replace_once(
        source,
        f"arguments: [{json.dumps(browser_smoke.SMOKE_SWITCH)}],",
        "arguments: [],",
        "ordinary launch arguments",
    )

    source = _replace_once(
        source,
        "const result = {\n",
        "let wasmModule = null;\n"
        "let shutdownRequested = false;\n"
        "const result = {\n"
        "  hostShutdownRequests: [],\n",
        "result object",
    )
    source = _replace_once(
        source,
        "let timeoutId;\n",
        "let timeoutId;\n"
        "function hasVisibleBrowserEvidence() {\n"
        "  return result.frameReports.length > 0 &&\n"
        "      result.readinessReports.some((report) =>\n"
        "          report && report.surfaceReady === true) &&\n"
        "      result.focusReports.some((report) =>\n"
        "          report && report.keyboardTargetPresent === true &&\n"
        "          report.active === true);\n"
        "}\n"
        "function maybeRequestHostShutdown() {\n"
        "  if (shutdownRequested || !wasmModule || !result.readyObserved ||\n"
        "      !hasVisibleBrowserEvidence()) {\n"
        "    return;\n"
        "  }\n"
        "  shutdownRequested = true;\n"
        "  try {\n"
        "    const first = wasmModule.ccall(\n"
        "        'chromium_wasm_browser_host_request_shutdown', 'number', [], []);\n"
        "    const second = wasmModule.ccall(\n"
        "        'chromium_wasm_browser_host_request_shutdown', 'number', [], []);\n"
        "    result.hostShutdownRequests.push(first, second);\n"
        "    if (first !== 1 || second !== 0) {\n"
        "      throw new Error('host shutdown ABI did not accept exactly once');\n"
        "    }\n"
        "  } catch (error) {\n"
        "    result.rejection = String(error);\n"
        "    rejectExit(error);\n"
        "  }\n"
        "}\n",
        "shutdown request hook",
    )
    source = _replace_once(
        source,
        "      stdout.push(text);\n      process.stdout.write(text + '\\n');",
        "      stdout.push(text);\n"
        "      process.stdout.write(text + '\\n');\n"
        "      if (text.includes(readyMarker)) {\n"
        "        result.readyObserved = true;\n"
        "        queueMicrotask(maybeRequestHostShutdown);\n"
        "      }",
        "stdout ready hook",
    )
    source = _replace_once(
        source,
        "      stderr.push(text);\n      process.stderr.write(text + '\\n');",
        "      stderr.push(text);\n"
        "      process.stderr.write(text + '\\n');\n"
        "      if (text.includes(readyMarker)) {\n"
        "        result.readyObserved = true;\n"
        "        queueMicrotask(maybeRequestHostShutdown);\n"
        "      }",
        "stderr ready hook",
    )
    source = _replace_once(
        source,
        "  await createModule({",
        "  const moduleOptions = {",
        "factory call",
    )
    source = _replace_once(
        source,
        "    onExit(code) {\n"
        "      resolveExit(Number(code));\n"
        "    },\n"
        "  });\n"
        "  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);",
        "    onExit(code) {\n"
        "      resolveExit(Number(code));\n"
        "    },\n"
        "    onRuntimeInitialized() {\n"
        "      wasmModule = this;\n"
        "      if (result.readyObserved) {\n"
        "        queueMicrotask(maybeRequestHostShutdown);\n"
        "      }\n"
        "    },\n"
        "  };\n"
        "  createModule(moduleOptions).catch((error) => {\n"
        "    result.rejection = String(error);\n"
        "    rejectExit(error);\n"
        "  });\n"
        "  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);",
        "runtime initialization",
    )
    for old, new, description in (
        (
            "  reportFrame(report) {\n"
            "    result.frameReports.push(report);\n"
            "  },",
            "  reportFrame(report) {\n"
            "    result.frameReports.push(report);\n"
            "    queueMicrotask(maybeRequestHostShutdown);\n"
            "  },",
            "frame evidence hook",
        ),
        (
            "  reportReadiness(report) {\n"
            "    result.readinessReports.push(report);\n"
            "  },",
            "  reportReadiness(report) {\n"
            "    result.readinessReports.push(report);\n"
            "    queueMicrotask(maybeRequestHostShutdown);\n"
            "  },",
            "readiness evidence hook",
        ),
        (
            "  reportOzoneFocusState(report) {\n"
            "    result.focusReports.push(report);\n"
            "  },",
            "  reportOzoneFocusState(report) {\n"
            "    result.focusReports.push(report);\n"
            "    queueMicrotask(maybeRequestHostShutdown);\n"
            "  },",
            "focus evidence hook",
        ),
    ):
        source = _replace_once(source, old, new, description)
    return source


def _parse_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise M0Error("Node runner emitted no unique normal Browser result")
    try:
        parsed = json.loads(lines[0][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise M0Error("Node runner emitted malformed normal Browser result") from exc
    if not isinstance(parsed, dict):
        raise M0Error("Node runner normal Browser result is not an object")
    return parsed


def validate_result(result: dict[str, Any], output: str) -> None:
    if result.get("runtimeExitCode") != 0:
        raise M0Error("ordinary Browser runtime did not exit zero")
    if result.get("abort") is not None or result.get("rejection") is not None:
        raise M0Error("ordinary Browser runtime aborted or rejected")
    if result.get("readyObserved") is not True or READY_MARKER not in output:
        raise M0Error("ordinary Browser runtime is missing its ready marker")
    if result.get("passObserved") is not True or PASS_MARKER not in output:
        raise M0Error("ordinary Browser runtime is missing its pass marker")
    if result.get("hostShutdownRequests") != [1, 0]:
        raise M0Error("ordinary Browser host shutdown ABI was not one-shot")

    browser_smoke._require_exact_int(
        result.get("canvasCopies"), "ordinary Browser canvas copy count", minimum=1
    )
    fatal_reports = result.get("fatalReports")
    if not isinstance(fatal_reports, list) or fatal_reports:
        raise M0Error("ordinary Browser host reported a fatal error")
    browser_smoke._validate_frames(result.get("frameReports"))
    browser_smoke._validate_ready_surface(result.get("readinessReports"))
    browser_smoke._validate_active_focus(result.get("focusReports"))

    process_exits = result.get("processExitReports")
    if not isinstance(process_exits, list):
        raise M0Error("ordinary Browser process-exit reports are invalid")
    for report in process_exits:
        if not isinstance(report, dict) or report.get("protocol") != 1:
            raise M0Error("ordinary Browser process-exit report is invalid")
        if report.get("exitCode") != 0:
            raise M0Error("ordinary Browser process reported a nonzero exit")


def run_smoke(
    module: Path, node: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [
                str(node),
                "--experimental-default-type=module",
                "--eval",
                runner_source(module.as_uri(), max(1, int(timeout * 1000))),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout + 5.0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise M0Error("ordinary Browser Node process timed out") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run ordinary no-switch Wasm Browser launch and shutdown."
    )
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm-chrome-m6"))
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--timeout", type=parse_timeout, default=30.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")
    if not _MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")

    try:
        out_dir = args.out_dir
        if not out_dir.is_absolute():
            out_dir = REPO_ROOT / out_dir
        check_boundary(out_dir)
        snapshot = capture_artifact_snapshot(out_dir, args.module_name)
        artifact = artifact_identity(snapshot)
        manifest = load_manifest()
        versions = snapshot_run_version_identity(manifest)
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m6_wasm_browser_normal_lifecycle_smoke.py",
            manifest,
            case="ordinary_slim_browser_lifecycle_m6",
            scope="normal-browser-main-host-shutdown-manager-drain",
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            module_name=args.module_name,
            artifact=artifact,
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )
        started = time.perf_counter()
        with materialized_artifact_snapshot(snapshot) as module:
            completed = run_smoke(module, node, args.timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        for line in completed.stdout.splitlines(keepends=True):
            if not line.startswith(RESULT_PREFIX):
                sys.stdout.write(line)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise M0Error(
                "ordinary Browser Node process exited with status "
                f"{completed.returncode}"
            )
        result = _parse_result(completed.stdout)
        validate_result(result, f"{completed.stdout}\n{completed.stderr}")
        print(
            f"{SENTINEL}:NODE_RESULT "
            + json.dumps(
                {
                    "artifact": artifact,
                    "canvasCopies": result["canvasCopies"],
                    "focusReports": len(result["focusReports"]),
                    "frameReports": len(result["frameReports"]),
                    "readinessReports": len(result["readinessReports"]),
                    "startupMs": elapsed_ms,
                    # This is only the child runner's local manifest/checkout
                    # observation, never executable or source provenance.
                    "versions": versions,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(NODE_PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, KeyError, ValueError) as exc:
        print(f"{SENTINEL}:NODE_FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the normal-profile post-readback shutdown-failure diagnostic.

This distinct artifact deliberately turns an already-successful volatile
Preferences readback into a failed shutdown fence.  It proves that the normal
Chrome result latch reports the failure as exit 13 rather than a clean exit.
It does not prove OPFS persistence, locking, recovery, or M7 completion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from check_m6_chrome_boundary import check_boundary
from m0_common import M0Error, REPO_ROOT, load_manifest, parse_timeout, print_context
from m9_descriptor_snapshot import snapshot_regular_file
from run_node_smoke import node_executable
import run_m6_wasm_browser_normal_lifecycle_smoke as normal_lifecycle
import run_m6_wasm_browser_smoke as browser_smoke


SENTINEL = "CHROMIUM_WASM_M7_NORMAL_PROFILE_FENCE_DIAGNOSTIC"
DIAGNOSTIC_MARKER = f"{SENTINEL}:READBACK_OK_FORCED_FAILURE"
RESULT_PREFIX = f"{SENTINEL}:NODE_EXIT "
NODE_PASS_MARKER = f"{SENTINEL}_NODE:PASS"
EXPECTED_EXIT_CODE = 13
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m7-normal-profile-fence-failure")
DEFAULT_MODULE_NAME = "chrome_wasm_m7_normal_profile_fence_failure_diagnostic"
PRODUCT_GN_ENABLE_ARGUMENT = (
    "enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic=true"
)
PRODUCT_GN_TARGET = "//chrome:chrome_wasm"
PRODUCT_GN_PROFILE_TARGET = "//chrome/browser/wasm:wasm_profile"
_NO_NON_DATA_PATH = "No non-data paths found between these two targets."
_FORBIDDEN_PROFILE_STORAGE_TARGET = "//chrome/browser/wasm:wasm_profile_storage"
_DIAGNOSTIC_DEFINE = "CHROME_WASM_M7_NORMAL_PROFILE_FENCE_FAILURE_DIAGNOSTIC=1"
_INCOMPATIBLE_PROFILE_DEFINES = (
    "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST=1",
    "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST=1",
)
_INCOMPATIBLE_PROFILE_TARGETS = (
    "//chrome/browser/wasm:wasm_profile_storage",
    "//chrome/browser/wasm:wasm_profile_preferences_smoke",
    "//chrome/browser/wasm:wasm_profile_database_smoke",
)
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_DIAGNOSTIC_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_normal_profile_fence_failure_diagnostic"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
_PREFERENCES_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_preferences_test"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
_DATABASE_GN_ENABLE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*enable_chromium_wasm_m7_profile_database_test"
    r"[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)


def _replace_once(source: str, old: str, new: str, description: str) -> str:
    if source.count(old) != 1:
        raise M0Error(f"normal-profile fence diagnostic runner lost its {description}")
    return source.replace(old, new, 1)


def runner_source(module_url: str, timeout_ms: int) -> str:
    """Return a no-switch Node host for the dedicated failure diagnostic.

    Emscripten normally consumes ``ExitStatus`` inside its generated loader.
    If a loader version instead exposes the expected object as the module
    factory rejection, accept only the exact own-data ``ExitStatus(13)``
    object.  Any other rejection remains a runner failure.  This has no
    profile-persistence claim.
    """

    source = normal_lifecycle.runner_source(module_url, timeout_ms)
    source = _replace_once(
        source,
        f"const resultPrefix = {json.dumps(normal_lifecycle.RESULT_PREFIX)};",
        f"const resultPrefix = {json.dumps(RESULT_PREFIX)};\n"
        f"const diagnosticMarker = {json.dumps(DIAGNOSTIC_MARKER)};\n"
        f"const expectedExitCode = {EXPECTED_EXIT_CODE};",
        "result prefix",
    )
    source = _replace_once(
        source,
        "const result = {\n  hostShutdownRequests: [],\n",
        "const result = {\n"
        "  expectedExitStatusObserved: false,\n"
        "  hostShutdownRequests: [],\n"
        "  lifecycleEvents: [],\n"
        "  onExitCodes: [],\n"
        "  outputEvents: [],\n",
        "result fields",
    )
    source = _replace_once(
        source,
        "const stderr = [];\n",
        "const stderr = [];\n"
        "let resolveDiagnosticMarker;\n"
        "const diagnosticMarkerPromise = new Promise((resolve) => {\n"
        "  resolveDiagnosticMarker = resolve;\n"
        "});\n"
        "const expectedExitStatusFields = Object.freeze([\n"
        "  'name', 'status', 'message',\n"
        "]);\n"
        "const expectedExitStatus = Object.freeze({\n"
        "  name: 'ExitStatus',\n"
        "  status: expectedExitCode,\n"
        "  message: `Program terminated with exit(${expectedExitCode})`,\n"
        "});\n"
        "function isExactExpectedEmscriptenExitStatus(value) {\n"
        "  try {\n"
        "    if (value === null || typeof value !== 'object' ||\n"
        "        Array.isArray(value)) {\n"
        "      return false;\n"
        "    }\n"
        "    const descriptors = Object.getOwnPropertyDescriptors(value);\n"
        "    const keys = Reflect.ownKeys(descriptors);\n"
        "    if (keys.length !== expectedExitStatusFields.length ||\n"
        "        keys.some((key) => typeof key !== 'string' ||\n"
        "            !expectedExitStatusFields.includes(key))) {\n"
        "      return false;\n"
        "    }\n"
        "    return expectedExitStatusFields.every((field) => {\n"
        "      const descriptor = descriptors[field];\n"
        "      return descriptor !== undefined && Object.hasOwn(descriptor, 'value') &&\n"
        "          !Object.hasOwn(descriptor, 'get') &&\n"
        "          !Object.hasOwn(descriptor, 'set') &&\n"
        "          descriptor.value === expectedExitStatus[field];\n"
        "    });\n"
        "  } catch (_error) {\n"
        "    return false;\n"
        "  }\n"
        "}\n",
        "ExitStatus classifier",
    )
    source = _replace_once(
        source,
        "  reportProcessExit(report) {\n"
        "    result.processExitReports.push(report);\n"
        "  },",
        "  reportProcessExit(report) {\n"
        "    result.processExitReports.push(report);\n"
        "    result.lifecycleEvents.push({\n"
        "      kind: 'processExit',\n"
        "      exitCode: Number(report && report.exitCode),\n"
        "    });\n"
        "  },",
        "host process-exit capture",
    )
    source = _replace_once(
        source,
        "      stdout.push(text);\n      process.stdout.write(text + '\\n');",
        "      stdout.push(text);\n"
        "      result.outputEvents.push({stream: 'stdout', text});\n"
        "      result.lifecycleEvents.push({kind: 'output', stream: 'stdout', text});\n"
        "      process.stdout.write(text + '\\n');",
        "stdout output capture",
    )
    source = _replace_once(
        source,
        "      stderr.push(text);\n      process.stderr.write(text + '\\n');",
        "      stderr.push(text);\n"
        "      result.outputEvents.push({stream: 'stderr', text});\n"
        "      result.lifecycleEvents.push({kind: 'output', stream: 'stderr', text});\n"
        "      if (text === diagnosticMarker) {\n"
        "        resolveDiagnosticMarker();\n"
        "      }\n"
        "      process.stderr.write(text + '\\n');",
        "stderr output capture",
    )
    source = _replace_once(
        source,
        "    onExit(code) {\n      resolveExit(Number(code));\n    },",
        "    onExit(code) {\n"
        "      const numericCode = Number(code);\n"
        "      result.onExitCodes.push(numericCode);\n"
        "      result.lifecycleEvents.push({kind: 'onExit', exitCode: numericCode});\n"
        "      resolveExit(numericCode);\n"
        "    },",
        "onExit capture",
    )
    source = _replace_once(
        source,
        "  createModule(moduleOptions).catch((error) => {\n"
        "    result.rejection = String(error);\n"
        "    rejectExit(error);\n"
        "  });\n"
        "  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);",
        "  const factoryPromise = createModule(moduleOptions).catch((error) => {\n"
        "    if (isExactExpectedEmscriptenExitStatus(error)) {\n"
        "      result.expectedExitStatusObserved = true;\n"
        "      return;\n"
        "    }\n"
        "    result.rejection = 'unexpected-module-factory-rejection';\n"
        "    rejectExit(new Error(result.rejection));\n"
        "  });\n"
        "  result.runtimeExitCode = await Promise.race([exitPromise, timeoutPromise]);\n"
        "  await factoryPromise;\n"
        "  await Promise.race([diagnosticMarkerPromise, timeoutPromise]);",
        "module factory rejection",
    )
    source = _replace_once(
        source,
        "if (result.rejection || result.abort || result.runtimeExitCode !== 0) {\n"
        "  process.exitCode = 1;\n"
        "}",
        "const expectedDiagnosticExit = result.runtimeExitCode === expectedExitCode &&\n"
        "    result.onExitCodes.length === 1 &&\n"
        "    result.onExitCodes[0] === expectedExitCode &&\n"
        "    result.abort === null && result.rejection === null &&\n"
        "    result.outputEvents.filter((event) => event.text === diagnosticMarker).length === 1;\n"
        "process.exitCode = expectedDiagnosticExit ? 0 : 1;",
        "diagnostic process exit",
    )
    return source


def _require_output_events(result: dict[str, Any]) -> list[dict[str, str]]:
    value = result.get("outputEvents")
    if not isinstance(value, list):
        raise M0Error("normal-profile fence diagnostic output events are invalid")
    events: list[dict[str, str]] = []
    for event in value:
        if (
            not isinstance(event, dict)
            or set(event) != {"stream", "text"}
            or event.get("stream") not in ("stdout", "stderr")
            or not isinstance(event.get("text"), str)
        ):
            raise M0Error("normal-profile fence diagnostic output event is invalid")
        events.append({"stream": event["stream"], "text": event["text"]})
    return events


def _require_lifecycle_events(result: dict[str, Any]) -> list[dict[str, object]]:
    value = result.get("lifecycleEvents")
    if not isinstance(value, list):
        raise M0Error("normal-profile fence diagnostic lifecycle events are invalid")

    events: list[dict[str, object]] = []
    for event in value:
        if not isinstance(event, dict):
            raise M0Error("normal-profile fence diagnostic lifecycle event is invalid")
        kind = event.get("kind")
        if kind == "output":
            if (
                set(event) != {"kind", "stream", "text"}
                or event.get("stream") not in ("stdout", "stderr")
                or not isinstance(event.get("text"), str)
            ):
                raise M0Error(
                    "normal-profile fence diagnostic output lifecycle event is invalid"
                )
        elif kind in ("processExit", "onExit"):
            if set(event) != {"kind", "exitCode"} or type(
                event.get("exitCode")
            ) is not int:
                raise M0Error(
                    "normal-profile fence diagnostic terminal lifecycle event is invalid"
                )
        else:
            raise M0Error("normal-profile fence diagnostic lifecycle event is invalid")
        events.append(event)
    return events


def _require_exact_markers(events: list[dict[str, str]]) -> None:
    normal_markers = (
        normal_lifecycle.DEFAULT_STORAGE_PARTITION_RECEIPT,
        normal_lifecycle.READY_MARKER,
        normal_lifecycle.PASS_MARKER,
    )
    marker_indices: list[int] = []
    for marker in normal_markers:
        matches = [
            index for index, event in enumerate(events) if event["text"] == marker
        ]
        if len(matches) != 1:
            raise M0Error(
                "normal-profile fence diagnostic marker is missing or repeated: "
                f"{marker}"
            )
        marker_indices.append(matches[0])
    if marker_indices != sorted(marker_indices):
        raise M0Error(
            "normal-profile fence diagnostic normal volatile-profile markers "
            "were not emitted in lifecycle order"
        )
    diagnostic_matches = [
        event
        for event in events
        if event["text"] == DIAGNOSTIC_MARKER
    ]
    if len(diagnostic_matches) != 1:
        raise M0Error(
            "normal-profile fence diagnostic marker is missing or repeated: "
            f"{DIAGNOSTIC_MARKER}"
        )
    if diagnostic_matches[0]["stream"] != "stderr":
        raise M0Error(
            "normal-profile fence diagnostic post-readback marker was not "
            "emitted through stderr"
        )


def _require_terminal_exit_order(events: list[dict[str, object]]) -> None:
    process_exit_indices = [
        index
        for index, event in enumerate(events)
        if event.get("kind") == "processExit"
        and event.get("exitCode") == EXPECTED_EXIT_CODE
    ]
    on_exit_indices = [
        index
        for index, event in enumerate(events)
        if event.get("kind") == "onExit"
        and event.get("exitCode") == EXPECTED_EXIT_CODE
    ]
    if len(process_exit_indices) != 1 or len(on_exit_indices) != 1:
        raise M0Error(
            "normal-profile fence diagnostic lifecycle lacks one status-13 exit"
        )
    if process_exit_indices[0] >= on_exit_indices[0]:
        raise M0Error(
            "normal-profile fence diagnostic host process exit did not precede "
            "the Emscripten onExit callback"
        )


def _require_lifecycle_projection(
    output_events: list[dict[str, str]],
    lifecycle_events: list[dict[str, object]],
    on_exit_codes: list[int],
    process_exits: list[dict[str, object]],
) -> None:
    projected_output = [
        {"stream": event["stream"], "text": event["text"]}
        for event in lifecycle_events
        if event["kind"] == "output"
    ]
    if projected_output != output_events:
        raise M0Error(
            "normal-profile fence diagnostic lifecycle output projection disagrees "
            "with print callbacks"
        )
    projected_on_exit = [
        event["exitCode"]
        for event in lifecycle_events
        if event["kind"] == "onExit"
    ]
    if projected_on_exit != on_exit_codes:
        raise M0Error(
            "normal-profile fence diagnostic lifecycle onExit projection disagrees "
            "with runtime callbacks"
        )
    projected_process_exit = [
        event["exitCode"]
        for event in lifecycle_events
        if event["kind"] == "processExit"
    ]
    process_exit_codes = [report["exitCode"] for report in process_exits]
    if projected_process_exit != process_exit_codes:
        raise M0Error(
            "normal-profile fence diagnostic lifecycle process-exit projection "
            "disagrees with host callbacks"
        )


def validate_m7_output_configuration(args_gn: bytes) -> None:
    """Require the dedicated artifact's explicit, isolated GN opt-in."""

    try:
        text = args_gn.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        raise M0Error("normal-profile fence diagnostic args.gn is not UTF-8") from error

    diagnostic_values = _DIAGNOSTIC_GN_ENABLE_ASSIGNMENT_RE.findall(text)
    if not diagnostic_values or any(value != "true" for value in diagnostic_values):
        raise M0Error(
            "normal-profile fence diagnostic args.gn lacks its explicit opt-in"
        )
    for name, assignment in (
        ("Preferences", _PREFERENCES_GN_ENABLE_ASSIGNMENT_RE),
        ("database", _DATABASE_GN_ENABLE_ASSIGNMENT_RE),
    ):
        if any(value == "true" for value in assignment.findall(text)):
            raise M0Error(
                "normal-profile fence diagnostic args.gn enables incompatible "
                f"M7 {name} storage"
            )


def validate_m7_generated_source_selection(out_dir: Path) -> None:
    """Require the generated graph to retain normal volatile-profile selection."""

    gn = REPO_ROOT / "buildtools/linux64/gn"
    if not gn.is_file():
        raise M0Error(f"GN executable is missing: {gn}")
    resolved_out_dir = out_dir.resolve()

    path = subprocess.run(
        [
            str(gn),
            "path",
            str(resolved_out_dir),
            PRODUCT_GN_TARGET,
            _FORBIDDEN_PROFILE_STORAGE_TARGET,
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if path.returncode:
        raise M0Error(
            "normal-profile fence diagnostic gn path failed: "
            + path.stderr.strip()
        )
    if _NO_NON_DATA_PATH not in path.stdout:
        raise M0Error(
            "normal-profile fence diagnostic reaches M7 profile storage:\n"
            + path.stdout.strip()
        )

    defines = subprocess.run(
        [str(gn), "desc", str(resolved_out_dir), PRODUCT_GN_PROFILE_TARGET, "defines"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if defines.returncode:
        raise M0Error(
            "normal-profile fence diagnostic gn desc defines failed: "
            + defines.stderr.strip()
        )
    if _DIAGNOSTIC_DEFINE not in defines.stdout:
        raise M0Error(
            "normal-profile fence diagnostic does not define its profile-only "
            "forced-failure capability"
        )
    if any(marker in defines.stdout for marker in _INCOMPATIBLE_PROFILE_DEFINES):
        raise M0Error(
            "normal-profile fence diagnostic selects an incompatible M7 profile mode"
        )

    deps = subprocess.run(
        [str(gn), "desc", str(resolved_out_dir), PRODUCT_GN_TARGET, "deps", "--all"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if deps.returncode:
        raise M0Error(
            "normal-profile fence diagnostic gn desc deps failed: "
            + deps.stderr.strip()
        )
    if any(target in deps.stdout for target in _INCOMPATIBLE_PROFILE_TARGETS):
        raise M0Error(
            "normal-profile fence diagnostic selects an incompatible M7 storage target"
        )


def _require_no_known_normal_lifecycle_regression(output: str) -> None:
    for diagnostic in normal_lifecycle.UNDRAINED_VOLATILE_PROFILE_DIAGNOSTICS:
        if diagnostic in output:
            raise M0Error(
                "normal-profile fence diagnostic activated an undrained "
                f"volatile-profile store: {diagnostic}"
            )
    if all(
        diagnostic in output
        for diagnostic in normal_lifecycle.NETWORK_CHANGE_NOTIFIER_NOT_IMPLEMENTED_DIAGNOSTICS
    ):
        raise M0Error(
            "normal-profile fence diagnostic reached the Wasm "
            "NetworkChangeNotifier NOTIMPLEMENTED path"
        )
    if all(
        diagnostic in output
        for diagnostic in (
            normal_lifecycle.BROWSER_DESKTOP_WINDOW_TREE_HOST_MODAL_NOT_IMPLEMENTED_DIAGNOSTICS
        )
    ):
        raise M0Error(
            "normal-profile fence diagnostic reached the Wasm modeless-window "
            "NOTIMPLEMENTED path"
        )


def validate_result(result: dict[str, Any]) -> None:
    """Validate one deliberately failed normal volatile-profile shutdown."""

    if result.get("runtimeExitCode") != EXPECTED_EXIT_CODE:
        raise M0Error(
            "normal-profile fence diagnostic runtime did not exit with status 13"
        )
    if result.get("onExitCodes") != [EXPECTED_EXIT_CODE]:
        raise M0Error(
            "normal-profile fence diagnostic did not receive exactly one "
            "onExit(13) callback"
        )
    if type(result.get("expectedExitStatusObserved")) is not bool:
        raise M0Error(
            "normal-profile fence diagnostic ExitStatus observation is invalid"
        )
    if result.get("abort") is not None or result.get("rejection") is not None:
        raise M0Error("normal-profile fence diagnostic runtime aborted or rejected")
    if result.get("readyObserved") is not True or result.get("passObserved") is not True:
        raise M0Error(
            "normal-profile fence diagnostic did not reach the normal visible "
            "browser lifecycle"
        )
    if result.get("hostShutdownRequests") != [1, 0]:
        raise M0Error(
            "normal-profile fence diagnostic host shutdown ABI was not one-shot"
        )

    events = _require_output_events(result)
    _require_exact_markers(events)
    lifecycle_events = _require_lifecycle_events(result)
    output = "\n".join(event["text"] for event in events)
    _require_no_known_normal_lifecycle_regression(output)

    browser_smoke._require_exact_int(
        result.get("canvasCopies"),
        "normal-profile fence diagnostic canvas copy count",
        minimum=1,
    )
    fatal_reports = result.get("fatalReports")
    if not isinstance(fatal_reports, list) or fatal_reports:
        raise M0Error("normal-profile fence diagnostic host reported a fatal error")
    browser_smoke._validate_frames(result.get("frameReports"))
    browser_smoke._validate_ready_surface(result.get("readinessReports"))
    browser_smoke._validate_active_focus(result.get("focusReports"))

    process_exits = result.get("processExitReports")
    if not isinstance(process_exits, list) or len(process_exits) != 1:
        raise M0Error(
            "normal-profile fence diagnostic did not report exactly one host "
            "process exit"
        )
    report = process_exits[0]
    if (
        not isinstance(report, dict)
        or report.get("protocol") != 1
        or report.get("exitCode") != EXPECTED_EXIT_CODE
    ):
        raise M0Error(
            "normal-profile fence diagnostic host process exit was not status 13"
        )
    _require_lifecycle_projection(
        events,
        lifecycle_events,
        [EXPECTED_EXIT_CODE],
        [report],
    )
    # The stderr marker is emitted on JsonPrefStore's file-sequence worker,
    # while normal lifecycle output and the process-exit bridge travel through
    # other workers. Their host callbacks have no shared delivery order. The
    # source contract separately proves the marker precedes Run(false)
    # natively; here only require the deterministic terminal callback order.
    _require_terminal_exit_order(lifecycle_events)


def _parse_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise M0Error(
            "Node runner emitted no unique normal-profile fence diagnostic result"
        )
    try:
        parsed = json.loads(lines[0][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as error:
        raise M0Error(
            "Node runner emitted malformed normal-profile fence diagnostic result"
        ) from error
    if not isinstance(parsed, dict):
        raise M0Error("Node runner normal-profile fence diagnostic result is invalid")
    return parsed


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
    except subprocess.TimeoutExpired as error:
        raise M0Error("normal-profile fence diagnostic Node process timed out") from error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the normal-profile post-readback shutdown-failure diagnostic."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument("--timeout", type=parse_timeout, default=45.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")
    if not _MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")
    if args.module_name != DEFAULT_MODULE_NAME:
        parser.error(
            "--module-name must select the normal-profile fence diagnostic artifact"
        )

    try:
        out_dir = args.out_dir
        if not out_dir.is_absolute():
            out_dir = REPO_ROOT / out_dir
        if out_dir.resolve().name != DEFAULT_OUT_DIR.name:
            raise M0Error(
                "normal-profile fence diagnostic must use its dedicated fresh "
                "output directory"
            )
        check_boundary(out_dir)
        args_gn = snapshot_regular_file(
            out_dir / "args.gn",
            maximum_bytes=MAX_SNAPSHOT_BYTES,
            description="normal-profile fence diagnostic selected args.gn",
        )
        validate_m7_output_configuration(args_gn)
        validate_m7_generated_source_selection(out_dir)
        snapshot = normal_lifecycle.capture_artifact_snapshot(out_dir, args.module_name)
        artifact = normal_lifecycle.artifact_identity(snapshot)
        manifest = load_manifest()
        versions = normal_lifecycle.snapshot_run_version_identity(manifest)
        node = node_executable(manifest)
        if not node.is_file():
            raise M0Error("the pinned Node executable is not installed")
        print_context(
            "run_m7_normal_profile_shutdown_fence_failure_smoke.py",
            manifest,
            case="normal_volatile_profile_post_readback_fence_failure_m7",
            scope=(
                "normal-browser-visible-lifecycle-test-only-post-readback-"
                "forced-fence-failure-no-profile-persistence-claim"
            ),
            gn_args=PRODUCT_GN_ENABLE_ARGUMENT,
            module_name=args.module_name,
            artifact=artifact,
            node_version=manifest["emscripten"]["node_version"],  # type: ignore[index]
        )
        started = time.perf_counter()
        with normal_lifecycle.materialized_artifact_snapshot(snapshot) as module:
            completed = run_smoke(module, node, args.timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        for line in completed.stdout.splitlines(keepends=True):
            if not line.startswith(RESULT_PREFIX):
                sys.stdout.write(line)
        sys.stderr.write(completed.stderr)
        # The generated loader normally reaches the final assignment in the
        # host and returns zero. Some pinned Node/Emscripten combinations keep
        # the native exit status after consuming ExitStatus internally. Accept
        # only that expected status here; validate_result() still requires the
        # one onExit(13) callback, one bridge report, exact marker sequence,
        # and all visible-browser evidence before this Python command returns
        # success.
        if completed.returncode not in (0, EXPECTED_EXIT_CODE):
            raise M0Error(
                "normal-profile fence diagnostic Node process exited with status "
                f"{completed.returncode}"
            )
        result = _parse_result(completed.stdout)
        validate_result(result)
        print(
            f"{SENTINEL}:NODE_RESULT "
            + json.dumps(
                {
                    "artifact": artifact,
                    "canvasCopies": result["canvasCopies"],
                    "expectedExitStatusObserved": result[
                        "expectedExitStatusObserved"
                    ],
                    "focusReports": len(result["focusReports"]),
                    "frameReports": len(result["frameReports"]),
                    "hostProcessExitCode": EXPECTED_EXIT_CODE,
                    "readinessReports": len(result["readinessReports"]),
                    "startupMs": elapsed_ms,
                    # This is a run-local checkout observation only; it is
                    # not executable, source, or storage provenance.
                    "versions": versions,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(NODE_PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, KeyError, ValueError) as error:
        print(f"{SENTINEL}:NODE_FAIL reason={error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

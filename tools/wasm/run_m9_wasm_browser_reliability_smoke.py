#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exercise repeatable fresh Chrome Wasm lifecycle and controlled-flow runs.

This M9 preparation runner deliberately composes existing, independently
validated M6 runners rather than adding a second lifecycle implementation.  A
normal-lifecycle cycle creates a fresh Node process and runs ordinary
no-switch Browser startup plus its owned host-shutdown path.  A controlled-flow
cycle creates a fresh real host-browser profile, drives the existing bounded
HTTPS/tab/menu/reload flow, then observes its fresh outer-document restart.

It is not a same-instance long-run/churn test.  In particular, it does not
measure Wasm memory growth, exhaust the pthread pool, prove WISP reconnects,
or claim persistent OPFS profile behavior or M8 compatibility.
"""

from __future__ import annotations

import argparse
import copy
import contextlib
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator, Sequence

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from run_content_shell_smoke import manifest_versions
import run_m6_wasm_browser_continuous_flow_dom_smoke as continuous_flow
import run_m6_wasm_browser_normal_lifecycle_smoke as normal_lifecycle


SENTINEL = "CHROMIUM_WASM_M9_RELIABILITY"
CASE = "fresh_lifecycle_and_controlled_flow_m9"
SCOPE = "repeatable-fresh-run-lifecycle-and-controlled-flow-only"
PASS_MARKER = f"{SENTINEL}:PASS"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
DIAGNOSTICS_PREFIX = f"{SENTINEL}:DIAGNOSTICS "
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
DEFAULT_NORMAL_MODULE_NAME = "chrome_wasm"
DEFAULT_CONTROLLED_FLOW_MODULE_NAME = "chrome_wasm_m6_https_test"
DEFAULT_NORMAL_LIFECYCLE_ITERATIONS = 3
DEFAULT_CONTROLLED_FLOW_ITERATIONS = 1
DEFAULT_NORMAL_TIMEOUT = 30.0
DEFAULT_CONTROLLED_FLOW_TIMEOUT = 120.0
MAX_ITERATIONS = 10
CHILD_PROCESS_GRACE_SECONDS = 20.0
COOPERATIVE_STOP_GRACE_SECONDS = 5.0
FORCED_KILL_GRACE_SECONDS = 3.0
OUTPUT_POLL_SECONDS = 0.05
OUTPUT_READ_CHUNK_BYTES = 64 * 1024
MAX_CHILD_OUTPUT_BYTES = 12 * 1024 * 1024
MAX_FAILURE_MESSAGE_CHARS = 2048
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PREFLIGHT_ARTIFACT_IDENTITY_CONTEXT = "the M9 parent preflight snapshot"
PARENT_RUN_VERSION_SNAPSHOT_CONTEXT = "the frozen M9 parent run version snapshot"
CONTROLLED_FLOW_HOST_FIXTURE_DELIVERY = "private-m9-temporary-directory-snapshot"
CONTROLLED_FLOW_HOST_FIXTURE_SOURCE_PROVENANCE = "unverified"
NORMAL_RESULT_PREFIX = f"{normal_lifecycle.SENTINEL}:NODE_RESULT "
_NORMAL_LIFECYCLE_FAILURE_MARKERS = (
    f"{normal_lifecycle.SENTINEL}:NODE_FAIL",
)
_NORMAL_LIFECYCLE_NATIVE_SUCCESS_MARKERS = (
    normal_lifecycle.READY_MARKER,
    normal_lifecycle.PASS_MARKER,
)
_NORMAL_LIFECYCLE_WRAPPER_SUCCESS_MARKERS = (normal_lifecycle.NODE_PASS_MARKER,)
CONTROLLED_FLOW_SCREENSHOT_PREFIX = f"{continuous_flow.SENTINEL}:SCREENSHOT "
CONTROLLED_FLOW_RESULT_PREFIX = f"{continuous_flow.SENTINEL}:FLOW_RESULT "
CONTROLLED_FLOW_RESTART_RESULT_PREFIX = f"{continuous_flow.SENTINEL}:RESTART_RESULT "
CONTROLLED_FLOW_PASS_MARKER = f"{continuous_flow.SENTINEL}:PASS"
_CONTROLLED_FLOW_FAILURE_MARKERS = (
    f"{continuous_flow.SENTINEL}:FAIL",
    f"{continuous_flow.SENTINEL}:DIAGNOSTICS_FAIL",
)
_CONTROLLED_FLOW_TERMINAL_JSON_PREFIXES = (
    CONTROLLED_FLOW_SCREENSHOT_PREFIX,
    CONTROLLED_FLOW_RESULT_PREFIX,
    CONTROLLED_FLOW_RESTART_RESULT_PREFIX,
)
MAX_SCREENSHOT_POLICY_CONTRACT_BYTES = 64 * 1024
_SNAPSHOT_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_SCREENSHOT_POLICY_IDENTITY_FIELDS = frozenset(("baseline", "contract"))
_CONTROLLED_FLOW_HOST_FIXTURE_IDENTITY_FIELDS = frozenset(
    (
        "delivery",
        "source_provenance",
        *continuous_flow.HOST_RESOURCE_FILES,
    )
)
_SCREENSHOT_COMPARISON_FIELDS = frozenset(
    (
        "matches",
        "width",
        "height",
        "differentPixels",
        "differentPixelRatio",
        "maximumChannelDelta",
        "meanChannelDelta",
        "channelTolerance",
        "maximumDifferentPixelRatio",
    )
)
_SCREENSHOT_CONTRACT_FIELDS = frozenset(
    (
        "schema_version",
        "fixture",
        "gateway_url",
        "baseline",
        "baseline_policy",
        "visual_strategy",
        "width",
        "height",
        "channel_tolerance",
        "maximum_different_pixel_ratio",
        "comparison",
    )
)
_VERSION_IDENTITY_FIELDS = frozenset(("chromium", "v8", "emscripten", "port"))

LIMITATIONS = (
    "does_not_measure_same_instance_tab_or_navigation_churn",
    "does_not_measure_wasm_memory_growth_or_address_space_pressure",
    "does_not_exhaust_or_measure_the_pthread_pool",
    "does_not_exercise_wisp_reconnect_or_public_network_reliability",
    "does_not_prove_opfs_profile_persistence_or_recovery",
    "does_not_claim_m8_feature_compatibility",
)


@dataclass(frozen=True)
class ChildExecution:
    """A bounded observation of one independently launched child runner."""

    name: str
    cycle: int
    elapsed_ms: float
    returncode: int
    stdout: str
    stderr: str


class _CappedPipeCapture:
    """Drain child pipes while retaining at most one shared byte budget.

    Reader threads keep draining after the cap is reached so a noisy child
    cannot block on a full pipe while its dedicated runner process group is
    being asked to clean up.
    """

    def __init__(self, byte_limit: int) -> None:
        self._byte_limit = byte_limit
        self._lock = threading.Lock()
        self._overflowed = threading.Event()
        self._reader_failed = threading.Event()
        self._reader_errors: list[BaseException] = []
        self._stdout_chunks: list[bytes] = []
        self._stderr_chunks: list[bytes] = []
        self._started_threads: list[threading.Thread] = []
        self._retained_bytes = 0

    @property
    def overflowed(self) -> bool:
        return self._overflowed.is_set()

    @property
    def reader_failed(self) -> bool:
        return self._reader_failed.is_set()

    @property
    def started_threads(self) -> tuple[threading.Thread, ...]:
        """Return only readers whose Thread.start() call completed."""

        return tuple(self._started_threads)

    def _append(self, chunks: list[bytes], chunk: bytes) -> None:
        with self._lock:
            remaining = self._byte_limit - self._retained_bytes
            if remaining <= 0:
                self._overflowed.set()
                return
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                self._retained_bytes += remaining
                self._overflowed.set()
                return
            chunks.append(chunk)
            self._retained_bytes += len(chunk)

    def _drain(self, stream: Any, chunks: list[bytes]) -> None:
        try:
            read_chunk = getattr(stream, "read1", stream.read)
            while chunk := read_chunk(OUTPUT_READ_CHUNK_BYTES):
                if not isinstance(chunk, bytes):
                    raise TypeError("child pipe did not produce bytes")
                self._append(chunks, chunk)
        except BaseException as exc:
            with self._lock:
                self._reader_errors.append(exc)
            self._reader_failed.set()

    def start(
        self, process: subprocess.Popen[bytes]
    ) -> tuple[threading.Thread, threading.Thread]:
        if process.stdout is None or process.stderr is None:
            raise M0Error("child output pipes are unavailable")
        stdout_thread = threading.Thread(
            target=self._drain,
            args=(process.stdout, self._stdout_chunks),
            name="chromium-wasm-m9-reliability-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._drain,
            args=(process.stderr, self._stderr_chunks),
            name="chromium-wasm-m9-reliability-stderr",
            daemon=True,
        )
        stdout_thread.start()
        self._started_threads.append(stdout_thread)
        stderr_thread.start()
        self._started_threads.append(stderr_thread)
        return stdout_thread, stderr_thread

    def text(self) -> tuple[str, str]:
        with self._lock:
            errors = tuple(self._reader_errors)
            stdout = b"".join(self._stdout_chunks)
            stderr = b"".join(self._stderr_chunks)
        if errors:
            raise M0Error(f"child output reader failed: {errors[0]}")
        # Check the raw cap before decoding. A retained prefix may end in a
        # partial UTF-8 sequence when the child overflows the shared budget.
        if self.overflowed:
            raise M0Error("child output exceeds the configured byte bound")
        try:
            return stdout.decode("utf-8"), stderr.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise M0Error("child output is not valid UTF-8") from exc


def positive_iteration_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("iteration count must be an integer") from exc
    if not 1 <= count <= MAX_ITERATIONS:
        raise argparse.ArgumentTypeError(
            f"iteration count must be in [1, {MAX_ITERATIONS}]"
        )
    return count


def _require_module_name(value: str, description: str) -> None:
    if not MODULE_NAME_RE.fullmatch(value):
        raise M0Error(f"{description} must contain only ASCII letters, digits, or _")


def _resolve_out_dir(out_dir: Path) -> Path:
    resolved = out_dir if out_dir.is_absolute() else REPO_ROOT / out_dir
    resolved = resolved.resolve()
    if not resolved.is_dir():
        raise M0Error("reliability output directory is missing")
    return resolved


def _require_artifacts(out_dir: Path, module_name: str, description: str) -> None:
    _require_module_name(module_name, description)
    for suffix in (".js", ".wasm"):
        if not (out_dir / f"{module_name}{suffix}").is_file():
            raise M0Error(f"{description} artifact is missing")


def _validate_version_identity(value: object, description: str) -> dict[str, str]:
    """Require the exact four identifiers reported by an M6 flow child."""

    if not isinstance(value, dict) or set(value) != _VERSION_IDENTITY_FIELDS:
        raise M0Error(f"{description} has invalid version identifiers")
    if not all(type(revision) is str and revision for revision in value.values()):
        raise M0Error(f"{description} has invalid version identifiers")
    return {name: value[name] for name in sorted(_VERSION_IDENTITY_FIELDS)}


def snapshot_parent_run_version_identity(manifest: object) -> dict[str, str]:
    """Freeze one parent-run version observation before any child starts.

    This combines the locally loaded toolchain manifest with the current port
    checkout once.  It is a run-local expected-value snapshot only: it does
    not attest to artifact bytes or establish source provenance.
    """

    try:
        versions = manifest_versions(
            manifest, checked_output(["git", "rev-parse", "HEAD"])
        )
        return _validate_version_identity(
            versions, "M9 parent run version snapshot"
        )
    except M0Error as error:
        raise M0Error("M9 parent run version snapshot is invalid") from error


def _snapshot_normal_lifecycle_preflight_artifact_identity(
    out_dir: Path, module_name: str
) -> dict[str, object]:
    """Hash the output bytes that every normal child must snapshot.

    The returned delivery and provenance fields deliberately describe the
    normal child runner's own temporary-file delivery, not an M9 source or GN
    assertion.  M9 retains this only as an expected byte identity for every
    independently launched child.
    """

    snapshot = normal_lifecycle.capture_artifact_snapshot(out_dir, module_name)
    identity = normal_lifecycle.artifact_identity(snapshot)
    normal_lifecycle.validate_artifact_identity(
        identity, expected_module_name=module_name
    )
    return identity


def _snapshot_controlled_flow_preflight_artifact_identity(
    out_dir: Path, module_name: str
) -> dict[str, object]:
    """Hash the output bytes that every controlled-flow server must snapshot.

    Reuse the bounded generic loader/Wasm capture from the normal runner, but
    label the expected record with the controlled-flow child's documented
    immutable-server delivery constant.  The common ``unverified`` provenance
    stays explicit: these hashes bind one M9 run's byte observations only.
    """

    snapshot = normal_lifecycle.capture_artifact_snapshot(out_dir, module_name)
    if (
        type(snapshot.module_name) is not str
        or snapshot.module_name != module_name
        or type(snapshot.loader) is not bytes
        or type(snapshot.wasm) is not bytes
    ):
        raise M0Error("controlled-flow M9 preflight artifact snapshot is invalid")
    identity = {
        "artifact_delivery": continuous_flow.ARTIFACT_DELIVERY,
        "artifact_source_provenance": continuous_flow.ARTIFACT_SOURCE_PROVENANCE,
        "loader": {
            "bytes": len(snapshot.loader),
            "sha256": hashlib.sha256(snapshot.loader).hexdigest(),
        },
        "module_name": snapshot.module_name,
        "wasm": {
            "bytes": len(snapshot.wasm),
            "sha256": hashlib.sha256(snapshot.wasm).hexdigest(),
        },
    }
    try:
        continuous_flow.validate_artifact_identity(
            identity, expected_artifact_identity=identity
        )
    except M0Error as error:
        raise M0Error(
            "controlled-flow M9 preflight artifact identity is invalid"
        ) from error
    return identity


def _require_normal_lifecycle_preflight_artifact_identity(
    out_dir: Path,
    module_name: str,
    expected_artifact_identity: dict[str, object],
) -> None:
    """Reject a normal-module output mutation before or after a child run."""

    try:
        normal_lifecycle.validate_artifact_identity(
            _snapshot_normal_lifecycle_preflight_artifact_identity(
                out_dir, module_name
            ),
            expected_module_name=module_name,
            expected_artifact_identity=expected_artifact_identity,
        )
    except M0Error as error:
        raise M0Error(
            "normal lifecycle artifact identity changed since the M9 parent "
            "preflight snapshot"
        ) from error


def _require_controlled_flow_preflight_artifact_identity(
    out_dir: Path,
    module_name: str,
    expected_artifact_identity: dict[str, object],
) -> None:
    """Reject a controlled-module output mutation before or after a child run."""

    try:
        continuous_flow.validate_artifact_identity(
            _snapshot_controlled_flow_preflight_artifact_identity(out_dir, module_name),
            expected_artifact_identity=expected_artifact_identity,
        )
    except M0Error as error:
        raise M0Error(
            "controlled flow artifact identity changed since the M9 parent "
            "preflight snapshot"
        ) from error


def _require_iteration_count(value: int, description: str) -> None:
    if type(value) is not int or not 1 <= value <= MAX_ITERATIONS:
        raise M0Error(
            f"{description} must be an integer in [1, {MAX_ITERATIONS}]"
        )


def _require_timeout(value: float, description: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise M0Error(f"{description} must be positive and finite")


def _exact_line_count(output: str, marker: str) -> int:
    return sum(line == marker for line in output.splitlines())


def _json_object_without_duplicate_keys(
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


def _parse_strict_json_object_line(
    line: str, prefix: str, description: str
) -> dict[str, Any]:
    try:
        result = json.loads(
            line[len(prefix) :],
            object_pairs_hook=_json_object_without_duplicate_keys,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise M0Error(f"{description} emitted malformed JSON") from error
    if not isinstance(result, dict):
        raise M0Error(f"{description} result is not an object")
    return result


def _parse_controlled_flow_terminal_json_line(
    line: str, prefix: str, description: str
) -> dict[str, Any]:
    """Parse one authoritative child terminal JSON record strictly."""
    return _parse_strict_json_object_line(line, prefix, description)


def _is_terminal_failure_marker(line: str, marker: str) -> bool:
    return line == marker or line.startswith(marker + " ")


def _validate_normal_lifecycle_terminal_records(
    execution: ChildExecution,
) -> dict[str, Any]:
    """Require the ordinary child's split-stream terminal transcript.

    Native Chrome writes READY and PASS to stderr, which the M6 wrapper
    relays unchanged.  The wrapper then writes its NODE_RESULT summary and
    NODE_PASS marker to stdout.  Those streams do not provide a trustworthy
    joint ordering, so validate the native stderr order and wrapper stdout
    order independently.  A NODE_FAIL marker on either stream is terminally
    disqualifying, including when a forged success transcript follows it.
    """

    description = f"normal lifecycle cycle {execution.cycle}"
    output = f"{execution.stdout}\n{execution.stderr}"
    for line in output.splitlines():
        for marker in _NORMAL_LIFECYCLE_FAILURE_MARKERS:
            if _is_terminal_failure_marker(line, marker):
                raise M0Error(f"{description} emitted child failure marker {marker}")

    stdout_lines = execution.stdout.splitlines()
    stderr_lines = execution.stderr.splitlines()
    for line in stdout_lines:
        if line in _NORMAL_LIFECYCLE_NATIVE_SUCCESS_MARKERS:
            raise M0Error(
                f"{description} emitted a native success terminal record on stdout"
            )
    for line in stderr_lines:
        if line in _NORMAL_LIFECYCLE_WRAPPER_SUCCESS_MARKERS or line.startswith(
            NORMAL_RESULT_PREFIX
        ):
            raise M0Error(
                f"{description} emitted a wrapper success terminal record on stderr"
            )

    native_indices: list[int] = []
    for marker in _NORMAL_LIFECYCLE_NATIVE_SUCCESS_MARKERS:
        indices = [
            index for index, line in enumerate(stderr_lines) if line == marker
        ]
        if len(indices) != 1:
            raise M0Error(
                f"{description} did not emit exactly one stderr {marker} record"
            )
        native_indices.append(indices[0])
    if native_indices != sorted(native_indices):
        raise M0Error(f"{description} native terminal records are unordered")

    node_pass_indices = [
        index
        for index, line in enumerate(stdout_lines)
        if line == normal_lifecycle.NODE_PASS_MARKER
    ]
    if len(node_pass_indices) != 1:
        raise M0Error(
            f"{description} did not emit exactly one stdout "
            f"{normal_lifecycle.NODE_PASS_MARKER} record"
        )

    result_indices = [
        index
        for index, line in enumerate(stdout_lines)
        if line.startswith(NORMAL_RESULT_PREFIX)
    ]
    if len(result_indices) != 1:
        raise M0Error(
            f"{description} did not emit exactly one stdout {NORMAL_RESULT_PREFIX} record"
        )

    ordered_indices = (result_indices[0], node_pass_indices[0])
    if tuple(sorted(ordered_indices)) != ordered_indices:
        raise M0Error(f"{description} wrapper terminal records are unordered")

    return _parse_strict_json_object_line(
        stdout_lines[result_indices[0]], NORMAL_RESULT_PREFIX, description
    )


def _validate_controlled_flow_terminal_records(
    execution: ChildExecution, output: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Require one ordered, stdout-only terminal transcript from one child.

    The M6 child emits its success transcript only after owned cleanup.  Its
    stderr remains diagnostic-only, while either failure marker on either
    stream is terminally disqualifying even if a forged success record follows.
    """

    description = f"controlled flow cycle {execution.cycle}"
    for line in output.splitlines():
        for marker in _CONTROLLED_FLOW_FAILURE_MARKERS:
            if _is_terminal_failure_marker(line, marker):
                raise M0Error(f"{description} emitted child failure marker {marker}")

    stderr_lines = execution.stderr.splitlines()
    for line in stderr_lines:
        if line == CONTROLLED_FLOW_PASS_MARKER or any(
            line.startswith(prefix)
            for prefix in _CONTROLLED_FLOW_TERMINAL_JSON_PREFIXES
        ):
            raise M0Error(
                f"{description} emitted a success terminal record on stderr"
            )

    stdout_lines = execution.stdout.splitlines()
    ordered_records: list[tuple[str, int]] = []
    for prefix in _CONTROLLED_FLOW_TERMINAL_JSON_PREFIXES:
        indices = [
            index
            for index, line in enumerate(stdout_lines)
            if line.startswith(prefix)
        ]
        if len(indices) != 1:
            raise M0Error(
                f"{description} did not emit exactly one stdout {prefix} record"
            )
        ordered_records.append((prefix, indices[0]))
    pass_indices = [
        index
        for index, line in enumerate(stdout_lines)
        if line == CONTROLLED_FLOW_PASS_MARKER
    ]
    if len(pass_indices) != 1:
        raise M0Error(
            f"{description} did not emit exactly one stdout "
            f"{CONTROLLED_FLOW_PASS_MARKER}"
        )
    terminal_indices = [index for _prefix, index in ordered_records] + pass_indices
    if terminal_indices != sorted(terminal_indices):
        raise M0Error(f"{description} terminal records are missing or unordered")

    records = [
        _parse_controlled_flow_terminal_json_line(
            stdout_lines[index], prefix, description
        )
        for prefix, index in ordered_records
    ]
    return records[0], records[1], records[2]


def _validated_child_output(execution: ChildExecution) -> str:
    output = f"{execution.stdout}\n{execution.stderr}"
    # The separating newline above is only for line-oriented marker parsing;
    # it is not child output and must not consume the shared capture budget.
    if (
        len(execution.stdout.encode("utf-8"))
        + len(execution.stderr.encode("utf-8"))
        > MAX_CHILD_OUTPUT_BYTES
    ):
        raise M0Error(
            f"{execution.name} cycle {execution.cycle} output exceeds the bound"
        )
    if execution.returncode != 0:
        raise M0Error(
            f"{execution.name} cycle {execution.cycle} exited with status "
            f"{execution.returncode}"
        )
    return output


def _child_evidence(
    execution: ChildExecution, *, terminal_markers: dict[str, int]
) -> dict[str, object]:
    """Preserve bounded exact child outcome metadata, never full output."""
    return {
        "name": execution.name,
        "cycle": execution.cycle,
        "returncode": execution.returncode,
        "elapsedMs": execution.elapsed_ms,
        "stdoutBytes": len(execution.stdout.encode("utf-8")),
        "stderrBytes": len(execution.stderr.encode("utf-8")),
        "stdoutSha256": hashlib.sha256(execution.stdout.encode("utf-8")).hexdigest(),
        "stderrSha256": hashlib.sha256(execution.stderr.encode("utf-8")).hexdigest(),
        "terminalMarkers": terminal_markers,
    }


def _require_nonnegative_number(value: object, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M0Error(f"{description} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise M0Error(f"{description} is invalid")
    return result


def _require_positive_int(value: object, description: str) -> int:
    if type(value) is not int or value < 1:
        raise M0Error(f"{description} is invalid")
    return value


def _exact_json_value_equal(value: object, expected: object) -> bool:
    """Compare parsed JSON without accepting Python bool/int aliases."""

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


def validate_screenshot_comparison(
    value: object,
    *,
    expected_screenshot_comparison: dict[str, int | float | bool] | None = None,
) -> dict[str, int | float | bool]:
    """Validate one child visual metric record and optional parent equality.

    A successful controlled-flow child may not substitute a looser visual
    threshold or report numerically equivalent-looking, differently typed
    values.  When M9 retained a policy, its own PNG recomputation is the
    authoritative metric record.
    """

    if not isinstance(value, dict) or set(value) != _SCREENSHOT_COMPARISON_FIELDS:
        raise M0Error("controlled-flow screenshot comparison is invalid")
    matches = value.get("matches")
    width = value.get("width")
    height = value.get("height")
    different_pixels = value.get("differentPixels")
    different_pixel_ratio = value.get("differentPixelRatio")
    maximum_channel_delta = value.get("maximumChannelDelta")
    mean_channel_delta = value.get("meanChannelDelta")
    channel_tolerance = value.get("channelTolerance")
    maximum_different_pixel_ratio = value.get("maximumDifferentPixelRatio")
    if (
        type(matches) is not bool
        or type(width) is not int
        or not 1 <= width <= continuous_flow.MAX_FRAME_DIMENSION
        or type(height) is not int
        or not 1 <= height <= continuous_flow.MAX_FRAME_DIMENSION
        or type(different_pixels) is not int
        or not 0 <= different_pixels <= width * height
        or type(maximum_channel_delta) is not int
        or not 0 <= maximum_channel_delta <= 255
        or type(channel_tolerance) is not int
        or not 0 <= channel_tolerance <= 255
        or type(different_pixel_ratio) is not float
        or not math.isfinite(different_pixel_ratio)
        or not 0 <= different_pixel_ratio <= 1
        or type(mean_channel_delta) is not float
        or not math.isfinite(mean_channel_delta)
        or not 0 <= mean_channel_delta <= 255
        or type(maximum_different_pixel_ratio) is not float
        or not math.isfinite(maximum_different_pixel_ratio)
        or not 0 <= maximum_different_pixel_ratio <= 1
    ):
        raise M0Error("controlled-flow screenshot comparison is invalid")
    pixel_count = width * height
    if (
        different_pixel_ratio != different_pixels / pixel_count
        or mean_channel_delta > maximum_channel_delta
        or matches is not (different_pixel_ratio <= maximum_different_pixel_ratio)
        or matches is not True
    ):
        raise M0Error("controlled-flow screenshot comparison is invalid")
    normalized: dict[str, int | float | bool] = {
        "matches": matches,
        "width": width,
        "height": height,
        "differentPixels": different_pixels,
        "differentPixelRatio": different_pixel_ratio,
        "maximumChannelDelta": maximum_channel_delta,
        "meanChannelDelta": mean_channel_delta,
        "channelTolerance": channel_tolerance,
        "maximumDifferentPixelRatio": maximum_different_pixel_ratio,
    }
    if expected_screenshot_comparison is not None and not _exact_json_value_equal(
        normalized, expected_screenshot_comparison
    ):
        raise M0Error(
            "controlled-flow screenshot comparison disagrees with the retained "
            "M9 parent recomputation"
        )
    return normalized


def _canonical_screenshot_contract_bytes(contract: object) -> bytes:
    """Encode the validated visual contract into one stable byte sequence."""

    if not isinstance(contract, dict):
        raise M0Error("controlled-flow screenshot contract is invalid")
    try:
        canonical = json.dumps(
            contract,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise M0Error("controlled-flow screenshot contract is invalid") from error
    if not canonical or len(canonical) > MAX_SCREENSHOT_POLICY_CONTRACT_BYTES:
        raise M0Error("controlled-flow screenshot contract is invalid")
    return canonical


def _validate_retained_screenshot_contract(value: object) -> dict[str, Any]:
    """Require the exact M6 visual contract before M9 retains its bytes."""

    if not isinstance(value, dict) or set(value) != _SCREENSHOT_CONTRACT_FIELDS:
        raise M0Error("controlled-flow screenshot contract is invalid")
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("fixture") != "chromium-wasm-m6-controlled-https-v1"
        or value.get("gateway_url")
        != continuous_flow.controlled_https.GATEWAY_FIXTURE_URL
    ):
        raise M0Error("controlled-flow screenshot contract is invalid")
    baseline = value.get("baseline")
    if (
        type(baseline) is not str
        or not baseline
        or "\x00" in baseline
        or Path(baseline).name != baseline
        or Path(baseline).suffix != ".png"
    ):
        raise M0Error("controlled-flow screenshot contract is invalid")
    for field in ("baseline_policy", "visual_strategy", "comparison"):
        if type(value.get(field)) is not str or not value[field]:
            raise M0Error("controlled-flow screenshot contract is invalid")
    if type(value.get("width")) is not int or value["width"] != 640:
        raise M0Error("controlled-flow screenshot contract is invalid")
    if type(value.get("height")) is not int or value["height"] != 480:
        raise M0Error("controlled-flow screenshot contract is invalid")
    tolerance = value.get("channel_tolerance")
    ratio = value.get("maximum_different_pixel_ratio")
    if (
        type(tolerance) is not int
        or not 0 <= tolerance <= 255
        or isinstance(ratio, bool)
        or not isinstance(ratio, (int, float))
        or not math.isfinite(float(ratio))
        or not 0 <= float(ratio) <= 1
    ):
        raise M0Error("controlled-flow screenshot contract is invalid")
    return dict(value)


def _snapshot_byte_identity(contents: object, description: str) -> dict[str, object]:
    if type(contents) is not bytes or not contents:
        raise M0Error(f"controlled-flow screenshot {description} is invalid")
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def screenshot_policy_identity(
    contract_bytes: object, baseline_png: object
) -> dict[str, object]:
    """Return the compact identity for one M9-held visual acceptance policy.

    This is an identity for the parent runner's retained comparison inputs. It
    is intentionally not an artifact-provenance or release assertion.
    """

    identity = {
        "contract": _snapshot_byte_identity(contract_bytes, "contract"),
        "baseline": _snapshot_byte_identity(baseline_png, "baseline"),
    }
    return validate_screenshot_policy_identity(identity)


def validate_screenshot_policy_identity(
    value: object,
    *,
    expected_screenshot_policy_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate exact screenshot-policy identity shape and optional equality."""

    if not isinstance(value, dict) or set(value) != _SCREENSHOT_POLICY_IDENTITY_FIELDS:
        raise M0Error("controlled-flow screenshot policy identity is invalid")
    normalized: dict[str, object] = {}
    for name in sorted(_SCREENSHOT_POLICY_IDENTITY_FIELDS):
        snapshot = value.get(name)
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != _SNAPSHOT_BYTE_IDENTITY_FIELDS
        ):
            raise M0Error("controlled-flow screenshot policy identity is invalid")
        byte_count = snapshot.get("bytes")
        digest = snapshot.get("sha256")
        if (
            type(byte_count) is not int
            or byte_count < 1
            or type(digest) is not str
            or SHA256_RE.fullmatch(digest) is None
        ):
            raise M0Error("controlled-flow screenshot policy identity is invalid")
        normalized[name] = {"bytes": byte_count, "sha256": digest}
    if expected_screenshot_policy_identity is not None:
        expected = validate_screenshot_policy_identity(
            expected_screenshot_policy_identity
        )
        if normalized != expected:
            raise M0Error(
                "controlled-flow screenshot policy identity disagrees with the "
                "retained M9 snapshot"
            )
    return normalized


def validate_controlled_flow_host_fixture_identity(
    value: object,
) -> dict[str, object]:
    """Validate M9's path-free identity for its private host fixture copy."""

    if (
        not isinstance(value, dict)
        or set(value) != _CONTROLLED_FLOW_HOST_FIXTURE_IDENTITY_FIELDS
        or value.get("delivery") != CONTROLLED_FLOW_HOST_FIXTURE_DELIVERY
        or value.get("source_provenance")
        != CONTROLLED_FLOW_HOST_FIXTURE_SOURCE_PROVENANCE
    ):
        raise M0Error("controlled-flow host fixture identity is invalid")
    normalized: dict[str, object] = {
        "delivery": CONTROLLED_FLOW_HOST_FIXTURE_DELIVERY,
        "source_provenance": CONTROLLED_FLOW_HOST_FIXTURE_SOURCE_PROVENANCE,
    }
    for name in sorted(continuous_flow.HOST_RESOURCE_FILES):
        snapshot = value.get(name)
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != _SNAPSHOT_BYTE_IDENTITY_FIELDS
        ):
            raise M0Error("controlled-flow host fixture identity is invalid")
        byte_count = snapshot.get("bytes")
        digest = snapshot.get("sha256")
        if (
            type(byte_count) is not int
            or byte_count < 1
            or type(digest) is not str
            or SHA256_RE.fullmatch(digest) is None
        ):
            raise M0Error("controlled-flow host fixture identity is invalid")
        normalized[name] = {"bytes": byte_count, "sha256": digest}
    return normalized


def controlled_flow_host_fixture_identity(host_snapshots: object) -> dict[str, object]:
    """Identify the exact four source bytes frozen for all M9 flow children.

    The provenance remains deliberately unverified.  This is only a path-free
    record of the private M9 copy supplied to every independently launched
    controlled-flow child in one invocation.
    """

    identity = {
        "delivery": CONTROLLED_FLOW_HOST_FIXTURE_DELIVERY,
        "source_provenance": CONTROLLED_FLOW_HOST_FIXTURE_SOURCE_PROVENANCE,
        **continuous_flow.host_resource_snapshot_identity(host_snapshots),
    }
    return validate_controlled_flow_host_fixture_identity(identity)


@contextlib.contextmanager
def materialized_controlled_flow_host_fixture(
    host_snapshots: object,
) -> Iterator[Path]:
    """Materialize one private four-file fixture for every M9 flow child."""

    snapshots = continuous_flow.validate_host_resource_snapshots(host_snapshots)
    with tempfile.TemporaryDirectory(
        prefix="chromium-wasm-m9-controlled-flow-host-"
    ) as temporary_directory:
        host_dir = Path(temporary_directory)
        try:
            for name, filename in continuous_flow.HOST_RESOURCE_FILES.items():
                destination = host_dir / filename
                with destination.open("xb") as fixture_file:
                    written = fixture_file.write(snapshots[name])
                if written != len(snapshots[name]):
                    raise M0Error(
                        "could not materialize complete controlled-flow host fixture"
                    )
        except OSError as error:
            raise M0Error(
                "could not materialize controlled-flow host fixture"
            ) from error
        yield host_dir


def _snapshot_controlled_screenshot_policy(
) -> tuple[dict[str, Any], bytes, dict[str, object]]:
    """Capture and validate the one M9 visual policy before any flow child.

    The controlled-flow child still owns its single-run checks. M9's aggregate
    acceptance instead retains these canonical contract bytes and reviewed PNG
    bytes once, then uses them for every independently launched child. No
    later child result causes a policy or baseline reread from disk.
    """

    loaded_contract = (
        continuous_flow.controlled_https.load_controlled_https_screenshot_contract()
    )
    contract_bytes = _canonical_screenshot_contract_bytes(
        _validate_retained_screenshot_contract(loaded_contract)
    )
    try:
        contract = json.loads(contract_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise M0Error("controlled-flow screenshot contract is invalid") from error
    contract = _validate_retained_screenshot_contract(contract)
    baseline_path = continuous_flow.CONTROLLED_HTTPS_SCREENSHOT_CONTRACT.with_name(
        contract["baseline"]
    )
    baseline_png = continuous_flow._snapshot_reviewed_screenshot_baseline(
        baseline_path
    )
    try:
        baseline = continuous_flow.decode_png(baseline_png)
    except (M0Error, TypeError) as error:
        raise M0Error(
            "controlled-flow screenshot baseline snapshot is invalid"
        ) from error
    if (
        baseline.width != contract.get("width")
        or baseline.height != contract.get("height")
    ):
        raise M0Error(
            "controlled-flow screenshot baseline dimensions disagree with the "
            "retained contract"
        )
    return (
        contract,
        baseline_png,
        screenshot_policy_identity(contract_bytes, baseline_png),
    )


def validate_normal_lifecycle_execution(
    execution: ChildExecution,
    *,
    expected_module_name: str,
    expected_artifact_identity: dict[str, object] | None = None,
    expected_artifact_identity_context: str = "a prior cycle",
    expected_run_version_snapshot: dict[str, str] | None = None,
) -> dict[str, object]:
    """Validate one independent no-switch lifecycle child result.

    Version identifiers are a child-run-local observation. When supplied, the
    M9 parent snapshot only binds those observations within this invocation;
    it does not establish source or artifact provenance.
    """
    _require_module_name(expected_module_name, "normal lifecycle module name")
    output = _validated_child_output(execution)
    result = _validate_normal_lifecycle_terminal_records(execution)
    expected_fields = {
        "artifact",
        "canvasCopies",
        "focusReports",
        "frameReports",
        "readinessReports",
        "startupMs",
        "versions",
    }
    if set(result) != expected_fields:
        raise M0Error("normal lifecycle result has an invalid schema")
    versions = _validate_version_identity(
        result.get("versions"), "normal lifecycle result"
    )
    if expected_run_version_snapshot is not None:
        try:
            expected_versions = _validate_version_identity(
                expected_run_version_snapshot,
                "normal-lifecycle expected M9 parent run snapshot",
            )
        except M0Error as error:
            raise M0Error(
                "normal-lifecycle expected M9 parent run snapshot is invalid"
            ) from error
        if not _exact_json_value_equal(versions, expected_versions):
            raise M0Error(
                "normal lifecycle child version identifiers disagree with "
                + PARENT_RUN_VERSION_SNAPSHOT_CONTEXT
            )
    try:
        artifact = normal_lifecycle.validate_artifact_identity(
            result.get("artifact"),
            expected_module_name=expected_module_name,
            expected_artifact_identity=expected_artifact_identity,
        )
    except M0Error as error:
        if expected_artifact_identity is not None:
            raise M0Error(
                "normal lifecycle artifact identity disagrees with "
                f"{expected_artifact_identity_context}"
            ) from error
        raise M0Error(
            "normal lifecycle result has an invalid artifact identity"
        ) from error
    return {
        "cycle": execution.cycle,
        "child": _child_evidence(
            execution,
            terminal_markers={
                "nativeReady": _exact_line_count(
                    output, normal_lifecycle.READY_MARKER
                ),
                "lifecyclePass": _exact_line_count(
                    output, normal_lifecycle.PASS_MARKER
                ),
                "nodePass": _exact_line_count(
                    output, normal_lifecycle.NODE_PASS_MARKER
                ),
                "summary": sum(
                    line.startswith(NORMAL_RESULT_PREFIX)
                    for line in execution.stdout.splitlines()
                ),
            },
        ),
        "artifact": artifact,
        "versions": versions,
        "canvasCopies": _require_positive_int(
            result.get("canvasCopies"), "normal lifecycle canvas copies"
        ),
        "focusReports": _require_positive_int(
            result.get("focusReports"), "normal lifecycle focus reports"
        ),
        "frameReports": _require_positive_int(
            result.get("frameReports"), "normal lifecycle frame reports"
        ),
        "readinessReports": _require_positive_int(
            result.get("readinessReports"), "normal lifecycle readiness reports"
        ),
        "startupMs": _require_nonnegative_number(
            result.get("startupMs"), "normal lifecycle startup time"
        ),
        "elapsedMs": execution.elapsed_ms,
    }


def _versions_from_flow_result(result: dict[str, Any]) -> dict[str, str]:
    return _validate_version_identity(
        result.get("versions"), "controlled flow result"
    )


def _artifact_identity_from_flow_result(result: dict[str, Any]) -> dict[str, object]:
    artifact = result.get("artifact")
    if not isinstance(artifact, dict):
        raise M0Error("controlled flow result has invalid artifact identity")
    try:
        # This validates the exact schema and concrete JSON types before the
        # child record is retained. Its own identity is only used here to
        # validate structure; the M6 child separately compares it with its
        # immutable server snapshot before emitting the result.
        continuous_flow.validate_artifact_identity(
            artifact, expected_artifact_identity=artifact
        )
    except M0Error as error:
        raise M0Error("controlled flow result has invalid artifact identity") from error
    return artifact


def validate_controlled_flow_execution(
    execution: ChildExecution,
    *,
    expected_module_name: str,
    expected_host_resource_identity: dict[str, object],
    expected_artifact_identity: dict[str, object] | None = None,
    expected_artifact_identity_context: str = "a prior cycle",
    expected_run_version_snapshot: dict[str, str] | None = None,
    screenshot_contract: dict[str, Any] | None = None,
    screenshot_baseline_png: bytes | None = None,
    expected_screenshot_policy_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate one fresh real-browser controlled-flow child result.

    M9 callers provide one retained host-resource identity, visual contract,
    reviewed PNG, and compact policy identity for every cycle. The raw host
    identity is M6's server-owned snapshot fact; M9's separately labeled
    private-fixture identity remains parent-only aggregate evidence.
    """
    _require_module_name(expected_module_name, "controlled flow module name")
    output = _validated_child_output(execution)
    (
        child_screenshot_comparison,
        flow_result,
        restart_result,
    ) = _validate_controlled_flow_terminal_records(
        execution, output
    )
    screenshot_comparison = validate_screenshot_comparison(
        child_screenshot_comparison
    )
    try:
        expected_host_resources = continuous_flow.validate_host_resource_snapshot_identity(
            expected_host_resource_identity
        )
    except M0Error as error:
        raise M0Error(
            "controlled-flow expected host resource identity is invalid"
        ) from error
    for phase, result in (
        ("flow", flow_result),
        ("restart", restart_result),
    ):
        try:
            continuous_flow.validate_host_resource_snapshot_identity(
                result.get("hostResources"),
                expected_host_resource_identity=expected_host_resources,
            )
        except M0Error as error:
            raise M0Error(
                f"controlled-flow {phase} host resource identity disagrees "
                "with the frozen M9 fixture snapshot"
            ) from error
    versions = _versions_from_flow_result(flow_result)
    if not _exact_json_value_equal(restart_result.get("versions"), versions):
        raise M0Error("controlled flow and restart version identifiers disagree")
    validation_versions = versions
    if expected_run_version_snapshot is not None:
        try:
            validation_versions = _validate_version_identity(
                expected_run_version_snapshot,
                "controlled-flow expected M9 parent run snapshot",
            )
        except M0Error as error:
            raise M0Error(
                "controlled-flow expected M9 parent run snapshot is invalid"
            ) from error
        if not _exact_json_value_equal(versions, validation_versions):
            raise M0Error(
                "controlled-flow child version identifiers disagree with "
                + PARENT_RUN_VERSION_SNAPSHOT_CONTEXT
            )
    artifact = _artifact_identity_from_flow_result(flow_result)
    if artifact.get("module_name") != expected_module_name:
        raise M0Error(
            "controlled flow artifact module name disagrees with configured "
            "controlled-flow module"
        )
    if expected_artifact_identity is not None:
        try:
            continuous_flow.validate_artifact_identity(
                artifact, expected_artifact_identity=expected_artifact_identity
            )
        except M0Error as error:
            raise M0Error(
                "controlled flow artifact identity disagrees with "
                f"{expected_artifact_identity_context}"
            ) from error
    validation_artifact_identity = (
        expected_artifact_identity
        if expected_artifact_identity is not None
        else artifact
    )
    try:
        continuous_flow.validate_artifact_identity(
            restart_result.get("artifact"),
            expected_artifact_identity=validation_artifact_identity,
        )
    except M0Error as error:
        raise M0Error("controlled flow and restart artifact identities disagree") from error
    if screenshot_contract is None:
        if (
            screenshot_baseline_png is not None
            or expected_screenshot_policy_identity is not None
        ):
            raise M0Error(
                "controlled-flow retained screenshot policy is missing its contract"
            )
        screenshot_contract = (
            continuous_flow.controlled_https.load_controlled_https_screenshot_contract()
        )
    elif (
        screenshot_baseline_png is None
        or expected_screenshot_policy_identity is None
    ):
        raise M0Error(
            "controlled-flow retained screenshot policy is missing its baseline "
            "or identity"
        )

    screenshot_policy: dict[str, object] | None = None
    if screenshot_baseline_png is not None:
        expected_contract_bytes = _canonical_screenshot_contract_bytes(
            screenshot_contract
        )
        screenshot_policy = screenshot_policy_identity(
            expected_contract_bytes, screenshot_baseline_png
        )
        if expected_screenshot_policy_identity is None:
            raise M0Error(
                "controlled-flow retained screenshot policy is missing its identity"
            )
        validate_screenshot_policy_identity(
            screenshot_policy,
            expected_screenshot_policy_identity=expected_screenshot_policy_identity,
        )

    actual_png = continuous_flow.validate_flow_result(
        flow_result,
        expected_versions=validation_versions,
        expected_artifact_identity=validation_artifact_identity,
        expected_host_resource_identity=expected_host_resources,
        screenshot_contract=screenshot_contract,
    )
    continuous_flow.validate_restart_result(
        restart_result,
        expected_versions=validation_versions,
        expected_artifact_identity=validation_artifact_identity,
        expected_host_resource_identity=expected_host_resources,
    )
    frames = flow_result.get("frameReports")
    restart_frames = restart_result.get("frameReports")
    if not isinstance(frames, list) or not isinstance(restart_frames, list):
        raise M0Error("controlled flow reports invalid frame evidence")
    validated = {
        "cycle": execution.cycle,
        "child": _child_evidence(
            execution,
            terminal_markers={
                "flowPass": _exact_line_count(
                    execution.stdout, CONTROLLED_FLOW_PASS_MARKER
                ),
                "flowResult": sum(
                    line.startswith(CONTROLLED_FLOW_RESULT_PREFIX)
                    for line in execution.stdout.splitlines()
                ),
                "restartResult": sum(
                    line.startswith(CONTROLLED_FLOW_RESTART_RESULT_PREFIX)
                    for line in execution.stdout.splitlines()
                ),
                "screenshot": sum(
                    line.startswith(CONTROLLED_FLOW_SCREENSHOT_PREFIX)
                    for line in execution.stdout.splitlines()
                ),
            },
        ),
        "artifact": artifact,
        "hostResources": expected_host_resources,
        "versions": versions,
        "flowFrames": len(frames),
        "restartFrames": len(restart_frames),
        "elapsedMs": execution.elapsed_ms,
        "outerPageFreshRestart": True,
        "controlledReload": True,
        "controlledTabLifecycle": True,
        "screenshotComparison": screenshot_comparison,
    }
    if screenshot_baseline_png is not None:
        if screenshot_policy is None:
            raise M0Error("controlled-flow retained screenshot policy is invalid")
        comparison = continuous_flow.compare_screenshots(
            actual_png,
            screenshot_baseline_png,
            channel_tolerance=int(screenshot_contract["channel_tolerance"]),
            maximum_different_pixel_ratio=float(
                screenshot_contract["maximum_different_pixel_ratio"]
            ),
        )
        if not comparison.matches:
            raise M0Error(
                "controlled-flow screenshot differs from the retained M9 reviewed "
                "baseline: "
                + json.dumps(comparison.as_dict(), sort_keys=True, separators=(",", ":"))
            )
        screenshot_comparison = validate_screenshot_comparison(
            screenshot_comparison,
            expected_screenshot_comparison=comparison.as_dict(),
        )
        validated["screenshotComparison"] = screenshot_comparison
        # This denotes the M9 parent's comparison inputs, not a policy
        # self-reported by the independently launched child.
        validated["screenshotPolicy"] = screenshot_policy
    return validated


def normal_lifecycle_command(
    *, out_dir: Path, module_name: str, timeout: float
) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "tools/wasm/run_m6_wasm_browser_normal_lifecycle_smoke.py"),
        "--out-dir",
        str(out_dir),
        "--module-name",
        module_name,
        "--timeout",
        f"{timeout:g}",
    ]


def controlled_flow_command(
    *,
    out_dir: Path,
    module_name: str,
    timeout: float,
    diagnostics_dir: Path,
    host_dir: Path,
    browser: Path | None,
    node: Path | None,
    relay_script: Path | None,
    no_sandbox: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "tools/wasm/run_m6_wasm_browser_continuous_flow_dom_smoke.py"),
        "--out-dir",
        str(out_dir),
        "--module-name",
        module_name,
        "--timeout",
        f"{timeout:g}",
        "--diagnostics-dir",
        str(diagnostics_dir),
        "--host-dir",
        str(host_dir),
    ]
    if browser is not None:
        command.extend(("--browser", str(browser)))
    if node is not None:
        command.extend(("--node", str(node)))
    if relay_script is not None:
        command.extend(("--relay-script", str(relay_script)))
    if no_sandbox:
        command.append("--no-sandbox")
    return command


def _signal_child_process_group(
    process: subprocess.Popen[bytes], signal_number: int
) -> None:
    """Signal only the dedicated child-runner group.

    The child runners independently own browser and relay sessions. SIGINT
    gives their normal cleanup paths a chance to run. A later force-kill is
    failure-only because it cannot prove cleanup of independently started
    descendants.
    """

    try:
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        return
    except OSError:
        # Keep a cooperative fallback for hosts without POSIX process groups;
        # it is never used as positive cleanup evidence.
        try:
            process.send_signal(signal_number)
        except ProcessLookupError:
            return


def _child_process_group_exists(process: subprocess.Popen[bytes]) -> bool:
    """Return whether the dedicated runner process group still exists.

    The leader may already be reaped while a same-group child retains no
    output pipe at all. A signal-zero group probe covers that case without
    treating a completed leader as sufficient cleanup evidence. An unavailable
    or unauthorized group probe fails closed rather than claiming cleanup.
    """

    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        raise M0Error(
            "cannot verify child runner process-group absence after leader exit"
        ) from exc


def _output_threads_stopped(threads: Sequence[threading.Thread]) -> bool:
    return not any(thread.is_alive() for thread in threads)


def _wait_for_process_and_output(
    process: subprocess.Popen[bytes],
    threads: Sequence[threading.Thread],
    timeout: float,
) -> bool:
    """Boundedly wait for the group leader and inherited-pipe readers.

    A runner can exit before a browser/relay descendant that inherited stdout
    or stderr. Process completion alone is therefore insufficient evidence
    that the runner process group has relinquished its diagnostic pipes.
    """

    deadline = time.monotonic() + timeout
    while True:
        if (
            process.poll() is not None
            and _output_threads_stopped(threads)
            and not _child_process_group_exists(process)
        ):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        alive_threads = [thread for thread in threads if thread.is_alive()]
        if alive_threads:
            for thread in alive_threads:
                thread.join(timeout=min(OUTPUT_POLL_SECONDS, remaining))
        else:
            time.sleep(min(OUTPUT_POLL_SECONDS, remaining))


def _stop_child_cooperatively(
    process: subprocess.Popen[bytes],
    threads: Sequence[threading.Thread],
) -> bool:
    """Stop the runner group and all inherited-pipe readers boundedly.

    The process-group signal intentionally remains valid even after the
    runner leader has exited: descendants can still retain its pipe ends.
    Return true only if the group required a SIGKILL escalation. Completion
    means the leader exited, readers reached EOF, and signal-zero confirms
    that no same-group descendant remains.
    """

    _signal_child_process_group(process, signal.SIGINT)
    if _wait_for_process_and_output(process, threads, COOPERATIVE_STOP_GRACE_SECONDS):
        return False
    _signal_child_process_group(process, signal.SIGKILL)
    if not _wait_for_process_and_output(process, threads, FORCED_KILL_GRACE_SECONDS):
        raise M0Error(
            "child runner process group or inherited output pipes did not "
            "exit after cooperative SIGINT and runner-process-group SIGKILL"
        )
    return True


def _join_output_threads(threads: Sequence[threading.Thread]) -> None:
    if not _wait_for_output_threads(threads, FORCED_KILL_GRACE_SECONDS):
        raise M0Error("child output pipe did not close after child exit")


def _wait_for_output_threads(
    threads: Sequence[threading.Thread], timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        alive_threads = [thread for thread in threads if thread.is_alive()]
        if not alive_threads:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        for thread in alive_threads:
            thread.join(timeout=min(OUTPUT_POLL_SECONDS, remaining))


def _close_child_pipes(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                # Do not obscure the original process/capture failure while
                # closing local diagnostic pipes.
                pass


def _cleanup_child_failure(
    process: subprocess.Popen[bytes] | None,
    threads: Sequence[threading.Thread],
) -> None:
    """Best-effort failure cleanup that never hides the primary exception."""

    if process is None:
        return
    try:
        _stop_child_cooperatively(process, threads)
    except BaseException:
        # The caller already has a primary failure. A second cleanup failure
        # is deliberately not promoted over it; no success record is emitted.
        pass
    try:
        _join_output_threads(threads)
    except BaseException:
        pass
    # A BufferedReader can be mid-read in a live reader thread. Closing it
    # first can itself block, so close only after bounded reader completion.
    if _output_threads_stopped(threads):
        _close_child_pipes(process)


def run_child(
    name: str, cycle: int, command: Sequence[str], timeout: float
) -> ChildExecution:
    """Run one fresh child with bounded streaming output and cleanup.

    An output overflow, reader fault, or deadline expiry interrupts the
    dedicated runner group. Any forced termination is always a failing
    outcome: child-owned browser/relay descendants may not have cleaned up.
    """

    _require_timeout(timeout, f"{name} cycle {cycle} process timeout")
    started = time.perf_counter()
    process: subprocess.Popen[bytes] | None = None
    capture: _CappedPipeCapture | None = None
    reader_threads: tuple[threading.Thread, threading.Thread] | None = None
    interruption_reason: str | None = None
    forced_kill = False
    group_cleanup_done = False
    try:
        process = subprocess.Popen(
            list(command),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        capture = _CappedPipeCapture(MAX_CHILD_OUTPUT_BYTES)
        try:
            reader_threads = capture.start(process)
        except BaseException:
            # If one Thread.start() succeeds and the other raises, retain the
            # started reader so the common exception cleanup can stop the
            # process, close its pipes, and bounded-join that reader.
            reader_threads = capture.started_threads
            raise
        deadline = time.monotonic() + timeout + CHILD_PROCESS_GRACE_SECONDS
        while True:
            if capture.overflowed:
                interruption_reason = "child output exceeds the configured byte bound"
                break
            if capture.reader_failed:
                interruption_reason = "child output reader failed"
                break
            if process.poll() is not None:
                break
            if time.monotonic() >= deadline:
                interruption_reason = "exceeded its process timeout"
                break
            time.sleep(OUTPUT_POLL_SECONDS)

        if interruption_reason is not None:
            forced_kill = _stop_child_cooperatively(process, reader_threads)
            group_cleanup_done = True
        else:
            # A reaped leader is not enough: a same-group descendant can keep
            # no pipe open at all. Require both EOF and an absent process
            # group before returning any child outcome to later validators.
            if not _wait_for_process_and_output(
                process, reader_threads, FORCED_KILL_GRACE_SECONDS
            ):
                interruption_reason = "child process group did not exit after leader completion"
                forced_kill = _stop_child_cooperatively(process, reader_threads)
                group_cleanup_done = True
        assert capture is not None
        if interruption_reason is not None:
            if forced_kill:
                raise M0Error(
                    f"{name} cycle {cycle} {interruption_reason}; force-killed "
                    "only the child runner process group after SIGINT. "
                    "Child-owned browser and relay sessions were independently "
                    "started, so their cleanup cannot be proven."
                )
            raise M0Error(f"{name} cycle {cycle} {interruption_reason}")
        stdout, stderr = capture.text()
        return ChildExecution(
            name=name,
            cycle=cycle,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    except BaseException:
        if not group_cleanup_done:
            _cleanup_child_failure(process, reader_threads or ())
        raise
    finally:
        if process is not None and _output_threads_stopped(reader_threads or ()):
            _close_child_pipes(process)


def _aggregate_cycles(cycles: list[dict[str, object]]) -> dict[str, object]:
    elapsed = [
        _require_nonnegative_number(cycle.get("elapsedMs"), "cycle elapsed time")
        for cycle in cycles
    ]
    if not elapsed:
        raise M0Error("reliability runner has no completed cycles")
    return {
        "completedCycles": len(cycles),
        "elapsedMs": {
            "minimum": min(elapsed),
            "maximum": max(elapsed),
            "total": round(sum(elapsed), 3),
        },
        "cycles": cycles,
    }


def run_reliability(
    *,
    out_dir: Path,
    normal_module_name: str,
    controlled_flow_module_name: str,
    normal_lifecycle_iterations: int,
    controlled_flow_iterations: int,
    normal_timeout: float,
    controlled_flow_timeout: float,
    diagnostics_dir: Path,
    browser: Path | None,
    node: Path | None,
    relay_script: Path | None,
    no_sandbox: bool,
    parent_run_version_snapshot: dict[str, str] | None = None,
) -> dict[str, object]:
    """Run independent fresh-lifecycle cycles and summarize their evidence."""
    _require_iteration_count(normal_lifecycle_iterations, "normal lifecycle count")
    _require_iteration_count(controlled_flow_iterations, "controlled flow count")
    _require_timeout(normal_timeout, "normal lifecycle timeout")
    _require_timeout(controlled_flow_timeout, "controlled flow timeout")
    if parent_run_version_snapshot is None:
        parent_versions = snapshot_parent_run_version_identity(load_manifest())
    else:
        try:
            parent_versions = _validate_version_identity(
                parent_run_version_snapshot, "M9 parent run version snapshot"
            )
        except M0Error as error:
            raise M0Error("M9 parent run version snapshot is invalid") from error
    _require_artifacts(out_dir, normal_module_name, "normal lifecycle")
    _require_artifacts(out_dir, controlled_flow_module_name, "controlled flow")

    # Freeze both configured module identities before any child can snapshot
    # them. The constants in these records describe the child delivery paths;
    # provenance remains explicitly unverified.
    normal_preflight_artifact_identity = (
        _snapshot_normal_lifecycle_preflight_artifact_identity(
            out_dir, normal_module_name
        )
    )
    controlled_flow_preflight_artifact_identity = (
        _snapshot_controlled_flow_preflight_artifact_identity(
            out_dir, controlled_flow_module_name
        )
    )

    normal_cycles: list[dict[str, object]] = []
    for cycle in range(1, normal_lifecycle_iterations + 1):
        _require_normal_lifecycle_preflight_artifact_identity(
            out_dir,
            normal_module_name,
            normal_preflight_artifact_identity,
        )
        execution = run_child(
            "normal lifecycle",
            cycle,
            normal_lifecycle_command(
                out_dir=out_dir,
                module_name=normal_module_name,
                timeout=normal_timeout,
            ),
            normal_timeout,
        )
        normal_cycle = validate_normal_lifecycle_execution(
            execution,
            expected_module_name=normal_module_name,
            expected_artifact_identity=copy.deepcopy(
                normal_preflight_artifact_identity
            ),
            expected_artifact_identity_context=PREFLIGHT_ARTIFACT_IDENTITY_CONTEXT,
            expected_run_version_snapshot=copy.deepcopy(parent_versions),
        )
        _require_normal_lifecycle_preflight_artifact_identity(
            out_dir,
            normal_module_name,
            normal_preflight_artifact_identity,
        )
        normal_cycles.append(normal_cycle)

    # Freeze every controlled-flow input before its first child starts. Every
    # later child receives only the parent-held visual policy and the same
    # private copy of the exact four trusted-DOM host resources.
    flow_host_snapshots = continuous_flow.snapshot_host_resources()
    flow_host_resource_identity = continuous_flow.host_resource_snapshot_identity(
        flow_host_snapshots
    )
    flow_host_fixture_identity = controlled_flow_host_fixture_identity(
        flow_host_snapshots
    )
    (
        flow_screenshot_contract,
        flow_screenshot_baseline_png,
        flow_screenshot_policy_identity,
    ) = _snapshot_controlled_screenshot_policy()

    flow_cycles: list[dict[str, object]] = []
    with materialized_controlled_flow_host_fixture(flow_host_snapshots) as host_dir:
        for cycle in range(1, controlled_flow_iterations + 1):
            _require_controlled_flow_preflight_artifact_identity(
                out_dir,
                controlled_flow_module_name,
                controlled_flow_preflight_artifact_identity,
            )
            execution = run_child(
                "controlled flow",
                cycle,
                controlled_flow_command(
                    out_dir=out_dir,
                    module_name=controlled_flow_module_name,
                    timeout=controlled_flow_timeout,
                    diagnostics_dir=diagnostics_dir / f"controlled-flow-{cycle:02d}",
                    host_dir=host_dir,
                    browser=browser,
                    node=node,
                    relay_script=relay_script,
                    no_sandbox=no_sandbox,
                ),
                controlled_flow_timeout,
            )
            flow_cycle = validate_controlled_flow_execution(
                execution,
                expected_module_name=controlled_flow_module_name,
                expected_host_resource_identity=copy.deepcopy(
                    flow_host_resource_identity
                ),
                expected_artifact_identity=copy.deepcopy(
                    controlled_flow_preflight_artifact_identity
                ),
                expected_artifact_identity_context=PREFLIGHT_ARTIFACT_IDENTITY_CONTEXT,
                expected_run_version_snapshot=copy.deepcopy(parent_versions),
                screenshot_contract=flow_screenshot_contract,
                screenshot_baseline_png=flow_screenshot_baseline_png,
                expected_screenshot_policy_identity=flow_screenshot_policy_identity,
            )
            try:
                validate_screenshot_policy_identity(
                    flow_cycle.get("screenshotPolicy"),
                    expected_screenshot_policy_identity=flow_screenshot_policy_identity,
                )
            except M0Error as error:
                raise M0Error(
                    "controlled-flow cycle does not retain the M9 screenshot policy "
                    "identity"
                ) from error
            _require_controlled_flow_preflight_artifact_identity(
                out_dir,
                controlled_flow_module_name,
                controlled_flow_preflight_artifact_identity,
            )
            flow_cycles.append(flow_cycle)

    normal_summary = _aggregate_cycles(normal_cycles)
    normal_summary.update(
        {
            "artifact": normal_preflight_artifact_identity,
            "kind": "fresh-node-module-process",
            "requestedCycles": normal_lifecycle_iterations,
            "ownedHostShutdown": True,
            # This is one parent-run observation retained before any child
            # starts. It is neither an artifact identity nor source provenance.
            "runVersionSnapshot": parent_versions,
        }
    )
    flow_summary = _aggregate_cycles(flow_cycles)
    flow_summary.update(
        {
            "artifact": controlled_flow_preflight_artifact_identity,
            "kind": "fresh-real-host-browser-profile-and-outer-restart",
            "requestedCycles": controlled_flow_iterations,
            "controlledHttpsNavigation": True,
            # This is one parent-run observation retained before any child
            # starts. It is neither an artifact identity nor source provenance.
            "runVersionSnapshot": parent_versions,
            # This identity names only the M9 parent-held four-file fixture
            # copy. It deliberately leaves source provenance unverified.
            "hostFixture": flow_host_fixture_identity,
            # This identity names only the M9 parent-held comparison inputs.
            # It does not establish source provenance or release readiness.
            "screenshotPolicy": flow_screenshot_policy_identity,
        }
    )
    return {
        "schema_version": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "pass",
        "normalLifecycle": normal_summary,
        "controlledFlow": flow_summary,
        "limitations": list(LIMITATIONS),
    }


def _bounded_failure_message(error: Exception) -> str:
    message = " ".join(str(error).split())
    if len(message) > MAX_FAILURE_MESSAGE_CHARS:
        message = message[:MAX_FAILURE_MESSAGE_CHARS] + "..."
    return message


def write_failure_diagnostics(
    diagnostics_dir: Path, *, error: Exception, stage: str
) -> Path:
    """Write a small failure record without copying child output or endpoints."""
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "m9-fresh-lifecycle-reliability-failure.json"
    payload = {
        "schema_version": 1,
        "case": CASE,
        "scope": SCOPE,
        "status": "fail",
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": _bounded_failure_message(error),
        },
        "limitations": list(LIMITATIONS),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded fresh-run Chrome Wasm reliability preparation."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--normal-module-name", default=DEFAULT_NORMAL_MODULE_NAME)
    parser.add_argument(
        "--controlled-flow-module-name", default=DEFAULT_CONTROLLED_FLOW_MODULE_NAME
    )
    parser.add_argument(
        "--normal-lifecycle-iterations",
        type=positive_iteration_count,
        default=DEFAULT_NORMAL_LIFECYCLE_ITERATIONS,
    )
    parser.add_argument(
        "--controlled-flow-iterations",
        type=positive_iteration_count,
        default=DEFAULT_CONTROLLED_FLOW_ITERATIONS,
    )
    parser.add_argument(
        "--normal-timeout", type=parse_timeout, default=DEFAULT_NORMAL_TIMEOUT
    )
    parser.add_argument(
        "--controlled-flow-timeout",
        type=parse_timeout,
        default=DEFAULT_CONTROLLED_FLOW_TIMEOUT,
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--relay-script", type=Path)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    args = parser.parse_args()

    stage = "resolve_paths"
    diagnostics_dir: Path | None = None
    try:
        out_dir = _resolve_out_dir(args.out_dir)
        diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
        if not diagnostics_dir.is_absolute():
            diagnostics_dir = REPO_ROOT / diagnostics_dir
        diagnostics_dir = diagnostics_dir.resolve()

        stage = "load_manifest"
        manifest = load_manifest()
        stage = "snapshot_parent_run_versions"
        parent_run_version_snapshot = snapshot_parent_run_version_identity(manifest)
        print_context(
            "run_m9_wasm_browser_reliability_smoke.py",
            manifest,
            case=CASE,
            scope=SCOPE,
            normal_lifecycle_iterations=args.normal_lifecycle_iterations,
            controlled_flow_iterations=args.controlled_flow_iterations,
            gn_args=manifest.get("m6_chrome_gn_args", manifest.get("gn_args")),
            limitations=list(LIMITATIONS),
        )
        stage = "run_fresh_cycles"
        result = run_reliability(
            out_dir=out_dir,
            normal_module_name=args.normal_module_name,
            controlled_flow_module_name=args.controlled_flow_module_name,
            parent_run_version_snapshot=parent_run_version_snapshot,
            normal_lifecycle_iterations=args.normal_lifecycle_iterations,
            controlled_flow_iterations=args.controlled_flow_iterations,
            normal_timeout=args.normal_timeout,
            controlled_flow_timeout=args.controlled_flow_timeout,
            diagnostics_dir=diagnostics_dir,
            browser=args.browser,
            node=args.node,
            relay_script=args.relay_script,
            no_sandbox=args.no_sandbox,
        )
        print(
            RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError) as error:
        if diagnostics_dir is not None:
            try:
                diagnostic = write_failure_diagnostics(
                    diagnostics_dir, error=error, stage=stage
                )
                print(
                    DIAGNOSTICS_PREFIX
                    + json.dumps({"path": str(diagnostic)}, sort_keys=True),
                    file=sys.stderr,
                    flush=True,
                )
            except OSError as diagnostic_error:
                print(
                    f"{DIAGNOSTICS_PREFIX}FAIL reason="
                    f"{_bounded_failure_message(diagnostic_error)}",
                    file=sys.stderr,
                    flush=True,
                )
        print(
            f"{SENTINEL}:FAIL reason={_bounded_failure_message(error)}",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

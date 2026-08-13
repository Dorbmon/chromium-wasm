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
import threading
import time
from typing import Any, Sequence

from m0_common import (
    M0Error,
    REPO_ROOT,
    load_manifest,
    parse_timeout,
    print_context,
)
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
NORMAL_RESULT_PREFIX = f"{normal_lifecycle.SENTINEL}:NODE_RESULT "

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


def _require_exact_marker(output: str, marker: str, description: str) -> None:
    if _exact_line_count(output, marker) != 1:
        raise M0Error(f"{description} did not emit exactly one {marker}")


def _parse_unique_json_line(
    output: str, prefix: str, description: str
) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise M0Error(f"{description} did not emit exactly one result record")
    try:
        result = json.loads(lines[0][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise M0Error(f"{description} emitted malformed JSON") from exc
    if not isinstance(result, dict):
        raise M0Error(f"{description} result is not an object")
    return result


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


def validate_normal_lifecycle_execution(
    execution: ChildExecution,
    *,
    expected_module_name: str,
    expected_artifact_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate one independent no-switch lifecycle child result."""
    _require_module_name(expected_module_name, "normal lifecycle module name")
    output = _validated_child_output(execution)
    _require_exact_marker(
        output,
        normal_lifecycle.PASS_MARKER,
        f"normal lifecycle cycle {execution.cycle}",
    )
    _require_exact_marker(
        output,
        normal_lifecycle.NODE_PASS_MARKER,
        f"normal lifecycle cycle {execution.cycle}",
    )
    result = _parse_unique_json_line(
        execution.stdout,
        NORMAL_RESULT_PREFIX,
        f"normal lifecycle cycle {execution.cycle}",
    )
    expected_fields = {
        "artifact",
        "canvasCopies",
        "focusReports",
        "frameReports",
        "readinessReports",
        "startupMs",
    }
    if set(result) != expected_fields:
        raise M0Error("normal lifecycle result has an invalid schema")
    try:
        artifact = normal_lifecycle.validate_artifact_identity(
            result.get("artifact"),
            expected_module_name=expected_module_name,
            expected_artifact_identity=expected_artifact_identity,
        )
    except M0Error as error:
        if expected_artifact_identity is not None:
            raise M0Error(
                "normal lifecycle artifact identity disagrees with a prior cycle"
            ) from error
        raise M0Error(
            "normal lifecycle result has an invalid artifact identity"
        ) from error
    return {
        "cycle": execution.cycle,
        "child": _child_evidence(
            execution,
            terminal_markers={
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
    versions = result.get("versions")
    if not isinstance(versions, dict):
        raise M0Error("controlled flow result has invalid version identifiers")
    if set(versions) != {"chromium", "v8", "emscripten", "port"}:
        raise M0Error("controlled flow result has invalid version identifiers")
    if not all(isinstance(value, str) and value for value in versions.values()):
        raise M0Error("controlled flow result has invalid version identifiers")
    return dict(versions)


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
    execution: ChildExecution, *, expected_module_name: str
) -> dict[str, object]:
    """Validate one fresh real-browser controlled-flow child result."""
    _require_module_name(expected_module_name, "controlled flow module name")
    output = _validated_child_output(execution)
    _require_exact_marker(
        output,
        f"{continuous_flow.SENTINEL}:PASS",
        f"controlled flow cycle {execution.cycle}",
    )
    flow_result = _parse_unique_json_line(
        execution.stdout,
        f"{continuous_flow.SENTINEL}:FLOW_RESULT ",
        f"controlled flow cycle {execution.cycle}",
    )
    restart_result = _parse_unique_json_line(
        execution.stdout,
        f"{continuous_flow.SENTINEL}:RESTART_RESULT ",
        f"controlled flow cycle {execution.cycle}",
    )
    versions = _versions_from_flow_result(flow_result)
    if restart_result.get("versions") != versions:
        raise M0Error("controlled flow and restart version identifiers disagree")
    artifact = _artifact_identity_from_flow_result(flow_result)
    if artifact.get("module_name") != expected_module_name:
        raise M0Error(
            "controlled flow artifact module name disagrees with configured "
            "controlled-flow module"
        )
    try:
        continuous_flow.validate_artifact_identity(
            restart_result.get("artifact"), expected_artifact_identity=artifact
        )
    except M0Error as error:
        raise M0Error("controlled flow and restart artifact identities disagree") from error
    screenshot_contract = (
        continuous_flow.controlled_https.load_controlled_https_screenshot_contract()
    )
    continuous_flow.validate_flow_result(
        flow_result,
        expected_versions=versions,
        expected_artifact_identity=artifact,
        screenshot_contract=screenshot_contract,
    )
    continuous_flow.validate_restart_result(
        restart_result,
        expected_versions=versions,
        expected_artifact_identity=artifact,
    )
    frames = flow_result.get("frameReports")
    restart_frames = restart_result.get("frameReports")
    if not isinstance(frames, list) or not isinstance(restart_frames, list):
        raise M0Error("controlled flow reports invalid frame evidence")
    return {
        "cycle": execution.cycle,
        "child": _child_evidence(
            execution,
            terminal_markers={
                "flowPass": _exact_line_count(
                    output, f"{continuous_flow.SENTINEL}:PASS"
                ),
                "flowResult": sum(
                    line.startswith(f"{continuous_flow.SENTINEL}:FLOW_RESULT ")
                    for line in execution.stdout.splitlines()
                ),
                "restartResult": sum(
                    line.startswith(f"{continuous_flow.SENTINEL}:RESTART_RESULT ")
                    for line in execution.stdout.splitlines()
                ),
            },
        ),
        "artifact": artifact,
        "versions": versions,
        "flowFrames": len(frames),
        "restartFrames": len(restart_frames),
        "elapsedMs": execution.elapsed_ms,
        "outerPageFreshRestart": True,
        "controlledReload": True,
        "controlledTabLifecycle": True,
    }


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
) -> dict[str, object]:
    """Run independent fresh-lifecycle cycles and summarize their evidence."""
    _require_iteration_count(normal_lifecycle_iterations, "normal lifecycle count")
    _require_iteration_count(controlled_flow_iterations, "controlled flow count")
    _require_timeout(normal_timeout, "normal lifecycle timeout")
    _require_timeout(controlled_flow_timeout, "controlled flow timeout")
    _require_artifacts(out_dir, normal_module_name, "normal lifecycle")
    _require_artifacts(out_dir, controlled_flow_module_name, "controlled flow")

    normal_cycles: list[dict[str, object]] = []
    normal_artifact_identity: dict[str, object] | None = None
    for cycle in range(1, normal_lifecycle_iterations + 1):
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
            expected_artifact_identity=normal_artifact_identity,
        )
        if normal_artifact_identity is None:
            normal_artifact_identity = copy.deepcopy(normal_cycle["artifact"])
        normal_cycles.append(normal_cycle)

    flow_cycles: list[dict[str, object]] = []
    for cycle in range(1, controlled_flow_iterations + 1):
        execution = run_child(
            "controlled flow",
            cycle,
            controlled_flow_command(
                out_dir=out_dir,
                module_name=controlled_flow_module_name,
                timeout=controlled_flow_timeout,
                diagnostics_dir=diagnostics_dir / f"controlled-flow-{cycle:02d}",
                browser=browser,
                node=node,
                relay_script=relay_script,
                no_sandbox=no_sandbox,
            ),
            controlled_flow_timeout,
        )
        flow_cycles.append(
            validate_controlled_flow_execution(
                execution, expected_module_name=controlled_flow_module_name
            )
        )

    if normal_artifact_identity is None:
        raise M0Error("reliability runner has no normal lifecycle artifact identity")
    normal_summary = _aggregate_cycles(normal_cycles)
    normal_summary.update(
        {
            "artifact": normal_artifact_identity,
            "kind": "fresh-node-module-process",
            "requestedCycles": normal_lifecycle_iterations,
            "ownedHostShutdown": True,
        }
    )
    flow_summary = _aggregate_cycles(flow_cycles)
    flow_summary.update(
        {
            "kind": "fresh-real-host-browser-profile-and-outer-restart",
            "requestedCycles": controlled_flow_iterations,
            "controlledHttpsNavigation": True,
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

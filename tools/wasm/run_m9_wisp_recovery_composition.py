#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Compose bounded M6 Chrome and M5 Content Shell WISP evidence.

This runner intentionally does not create a third WISP test implementation.
It starts the existing M6 controlled-HTTPS Chrome runner and the existing M5
Content Shell carrier-close recovery runner as two serial child processes.
Each child owns a newly-created host-browser profile.  Consequently, a pass
proves only that the independently validated child lanes passed against their
own fresh instances.  In particular, it is not evidence that Chrome recovered
from a carrier close in the same browser instance that performed the Chrome
controlled-HTTPS navigation.

Before either child starts, the composition hashes selected executable-entry,
host, relay, configuration, and build-artifact inputs for the two lanes. It
re-hashes those selected inputs after the relevant child finishes. This is not
a transitive Python-import or source-closure identity. These byte identities
are not source provenance; the result deliberately remains non-release and
marks artifact provenance as unverified.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Iterable, Sequence

from m0_common import MANIFEST_PATH, M0Error, REPO_ROOT, parse_timeout
import run_m5_wisp_smoke as m5_wisp
import run_m6_wasm_browser_controlled_https_smoke as m6_controlled_https


SENTINEL = "CHROMIUM_WASM_M9_WISP_RECOVERY_COMPOSITION"
SCHEMA_VERSION = 1
CASE = "cross_executable_wisp_recovery_composition_m9"
SCOPE = (
    "serial-fresh-process-m6-chrome-controlled-https-and-m5-content-shell-"
    "carrier-close-recovery"
)
KIND = "pre-release-m9-cross-executable-wisp-recovery-composition"
PASS_MARKER = f"{SENTINEL}:PASS"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
DIAGNOSTICS_PREFIX = f"{SENTINEL}:DIAGNOSTICS "
RELEASE_STATUS = "pre_m7_m8_not_releasable"
ARTIFACT_SOURCE_PROVENANCE = "unverified"
ARTIFACT_DELIVERY = (
    "child-runner-output-paths-preflight-and-postflight-byte-identity"
)
SOURCE_SNAPSHOT_PROVENANCE = (
    "selected-on-disk-byte-identities-before-child-launch-and-after-relevant-"
    "child-not-transitive-source-or-commit-provenance"
)
DEFAULT_CHROME_OUT_DIR = Path("out/wasm-chrome-m6")
DEFAULT_CONTENT_OUT_DIR = Path("out/wasm-content-m3")
DEFAULT_CHROME_MODULE_NAME = "chrome_wasm_m6_https_test"
DEFAULT_CONTENT_MODULE_NAME = "content_shell_wasm_m5_test"
DEFAULT_TIMEOUT = 120.0
M6_MIN_TIMEOUT_SECONDS = 5.0
CHILD_PROCESS_GRACE_SECONDS = 20.0
COOPERATIVE_STOP_GRACE_SECONDS = 5.0
FORCED_KILL_GRACE_SECONDS = 3.0
OUTPUT_POLL_SECONDS = 0.05
OUTPUT_READ_CHUNK_BYTES = 64 * 1024
MAX_CHILD_OUTPUT_BYTES = 12 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_FAILURE_MESSAGE_CHARS = 1024
FILE_HASH_CHUNK_BYTES = 1024 * 1024
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CHROME_RUNNER_PATH = REPO_ROOT / "tools/wasm/run_m6_wasm_browser_controlled_https_smoke.py"
CONTENT_RUNNER_PATH = REPO_ROOT / "tools/wasm/run_m5_wisp_smoke.py"
M6_HOST_HTML_PATH = (
    REPO_ROOT / "tools/wasm/host/chrome_wasm_browser_controlled_https_smoke.html"
)
M6_HOST_JS_PATH = (
    REPO_ROOT
    / "tools/wasm/host/chrome_wasm_browser_controlled_https_smoke_host.js"
)
M6_TEXT_INPUT_JS_PATH = REPO_ROOT / "tools/wasm/host/chrome_wasm_text_input.js"
M6_SCREENSHOT_CONTRACT_PATH = (
    REPO_ROOT / "tools/wasm/testdata/m6_controlled_https_screenshot_contract.json"
)
M5_HOST_SERVER_PATH = REPO_ROOT / "tools/wasm/m3_content_server.py"
M5_HOST_HTML_PATH = REPO_ROOT / "tools/wasm/host/content_shell.html"
M5_HOST_JS_PATH = REPO_ROOT / "tools/wasm/host/content_shell_host.js"
DEFAULT_RELAY_SCRIPT = REPO_ROOT / "tools/wasm/m5_wisp_test_server.js"

_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_VERSIONS_FIELDS = frozenset(("chromium", "v8", "emscripten", "port"))
_INPUT_SNAPSHOT_FIELDS = frozenset(
    (
        "artifact_source_provenance",
        "source_snapshot_provenance",
        "shared",
        "chrome_controlled_https",
        "content_shell_wisp_recovery",
    )
)
_SHARED_SNAPSHOT_FIELDS = frozenset(
    ("composition_runner_source", "toolchain_manifest", "wisp_relay_server_source")
)
_CHROME_SNAPSHOT_FIELDS = frozenset(
    (
        "artifact_delivery",
        "args_gn",
        "host_html",
        "host_js",
        "loader",
        "module_name",
        "runner_source",
        "screenshot_baseline",
        "screenshot_contract",
        "text_input_js",
        "wasm",
    )
)
_CONTENT_SNAPSHOT_FIELDS = frozenset(
    (
        "artifact_delivery",
        "args_gn",
        "host_html",
        "host_js",
        "host_server_source",
        "loader",
        "module_name",
        "runner_source",
        "wasm",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "artifact_source_provenance",
        "case",
        "children",
        "composition",
        "input_snapshots",
        "kind",
        "limitations",
        "m9_gate_complete",
        "release_status",
        "schema_version",
        "scope",
        "status",
        "versions",
    )
)
_CHILDREN_FIELDS = frozenset(
    ("chrome_controlled_https", "content_shell_wisp_carrier_close_recovery")
)
_COMPOSITION_FIELDS = frozenset(
    (
        "child_order",
        "cross_executable",
        "execution_model",
        "fresh_host_browser_profiles_owned_by_children",
        "m5_content_shell_carrier_close_recovery",
        "m6_chrome_controlled_https",
        "same_instance_chrome_recovery",
        "same_process",
        "shared_profile",
    )
)
_CHROME_CHILD_FIELDS = frozenset(
    (
        "browser_result_sha256",
        "controlled_reload",
        "elapsed_ms",
        "fresh_child_process",
        "fresh_host_browser_profile_owned_by_child",
        "relay_status_sha256",
        "returncode",
        "stderr_bytes",
        "stderr_sha256",
        "stdout_bytes",
        "stdout_sha256",
        "terminal_records",
        "wisp_configured",
    )
)
_CONTENT_CHILD_FIELDS = frozenset(
    (
        "browser_result_sha256",
        "carrier_close_reconnect_phase",
        "elapsed_ms",
        "fresh_child_process",
        "fresh_host_browser_profile_owned_by_child",
        "reconnect_recovery_requests",
        "relay_transcript_sha256",
        "returncode",
        "stderr_bytes",
        "stderr_sha256",
        "stdout_bytes",
        "stdout_sha256",
        "terminal_records",
        "wisp_sessions",
    )
)

LIMITATIONS = (
    (
        "cross-executable evidence only: the M5 carrier-close recovery ran in "
        "Content Shell, not in the Chrome instance exercised by M6"
    ),
    "does_not_prove_same_instance_chrome_wisp_carrier_close_recovery",
    "does_not_prove_public_network_reliability_or_long_run_reconnects",
    "does_not_measure_wasm_memory_growth_or_pthread_pool_exhaustion",
    "does_not_prove_opfs_profile_persistence_or_recovery",
    "does_not_complete_m7_or_m8_gates",
)


@dataclass(frozen=True)
class FileSnapshot:
    """The preflight byte identity of one direct child input path."""

    path: Path
    identity: dict[str, object]


@dataclass(frozen=True)
class ChildExecution:
    """Bounded terminal evidence from one independently launched child."""

    name: str
    elapsed_ms: float
    returncode: int
    stdout: str
    stderr: str


class _CappedPipeCapture:
    """Drains both child pipes while retaining no more than the hard cap."""

    def __init__(self, byte_limit: int) -> None:
        self._byte_limit = byte_limit
        self._lock = threading.Lock()
        self._overflowed = threading.Event()
        self._reader_failed = threading.Event()
        self._reader_errors: list[BaseException] = []
        self._stderr_chunks: list[bytes] = []
        self._stdout_chunks: list[bytes] = []
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

    def drain(self, stream: Any, chunks: list[bytes]) -> None:
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

    def text(self) -> tuple[str, str]:
        with self._lock:
            errors = tuple(self._reader_errors)
            stdout = b"".join(self._stdout_chunks)
            stderr = b"".join(self._stderr_chunks)
        if errors:
            raise M0Error(f"child output reader failed: {errors[0]}")
        if self.overflowed:
            raise M0Error("child output exceeds the configured byte bound")
        try:
            return stdout.decode("utf-8"), stderr.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise M0Error("child output is not valid UTF-8") from exc

    def start(
        self, process: subprocess.Popen[bytes]
    ) -> tuple[threading.Thread, threading.Thread]:
        if process.stdout is None or process.stderr is None:
            raise M0Error("child output pipes are unavailable")
        stdout_thread = threading.Thread(
            target=self.drain,
            args=(process.stdout, self._stdout_chunks),
            name="chromium-wasm-m9-wisp-child-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self.drain,
            args=(process.stderr, self._stderr_chunks),
            name="chromium-wasm-m9-wisp-child-stderr",
            daemon=True,
        )
        stdout_thread.start()
        self._started_threads.append(stdout_thread)
        stderr_thread.start()
        self._started_threads.append(stderr_thread)
        return stdout_thread, stderr_thread


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise M0Error(
            f"M9 WISP composition {description} schema is invalid: "
            f"expected {sorted(expected)!r}, got {actual!r}"
        )
    return value


def _require_module_name(value: str, description: str) -> None:
    if not isinstance(value, str) or not MODULE_NAME_RE.fullmatch(value):
        raise M0Error(f"{description} must contain only ASCII letters, digits, or _")


def _resolve_out_dir(value: Path, description: str) -> Path:
    candidate = value if value.is_absolute() else REPO_ROOT / value
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise M0Error(f"{description} output directory is missing: {resolved}")
    return resolved


def _resolve_file(value: Path, description: str) -> Path:
    resolved = value.resolve()
    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise M0Error(f"cannot read {description}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise M0Error(f"{description} is not a regular file")
    return resolved


def _output_file(out_dir: Path, name: str, description: str) -> Path:
    candidate = (out_dir / name).resolve()
    if candidate.parent != out_dir or not candidate.is_file():
        raise M0Error(f"{description} is missing or unsafe: {name}")
    return candidate


def _file_identity(path: Path, description: str) -> dict[str, object]:
    """Hash one nonempty file without retaining a large Wasm module in memory."""

    path = _resolve_file(path, description)
    try:
        before = path.stat()
    except OSError as exc:
        raise M0Error(f"cannot stat {description}: {exc}") from exc
    if before.st_size < 1 or before.st_size > MAX_SNAPSHOT_BYTES:
        raise M0Error(f"{description} byte size is outside the snapshot bound")

    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(FILE_HASH_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_SNAPSHOT_BYTES:
                    raise M0Error(f"{description} exceeds the snapshot bound")
                digest.update(chunk)
        after = path.stat()
    except OSError as exc:
        raise M0Error(f"cannot hash {description}: {exc}") from exc
    if (
        total != before.st_size
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        raise M0Error(f"{description} changed while its identity was captured")
    return {"bytes": total, "sha256": digest.hexdigest()}


def _snapshot_file(path: Path, description: str) -> FileSnapshot:
    resolved = _resolve_file(path, description)
    return FileSnapshot(path=resolved, identity=_file_identity(resolved, description))


def _snapshot_output_artifact(
    out_dir: Path, name: str, description: str
) -> FileSnapshot:
    path = _output_file(out_dir, name, description)
    return FileSnapshot(path=path, identity=_file_identity(path, description))


def _m6_screenshot_baseline_path() -> Path:
    """Resolve the reviewed baseline through M6's own validated contract."""

    contract = m6_controlled_https.load_controlled_https_screenshot_contract()
    baseline_name = contract.get("baseline")
    if type(baseline_name) is not str or not baseline_name:
        raise M0Error("M6 controlled-HTTPS screenshot baseline is invalid")
    return m6_controlled_https.CONTROLLED_HTTPS_SCREENSHOT_CONTRACT.parent / baseline_name


def snapshot_composition_inputs(
    *,
    chrome_out_dir: Path,
    chrome_module_name: str,
    content_out_dir: Path,
    content_module_name: str,
    relay_script: Path,
) -> dict[str, dict[str, FileSnapshot]]:
    """Capture selected entrypoint, host, relay, and artifact identities.

    This deliberately does not claim a transitive Python-import or source
    closure. The selected child-runner entrypoint source, host resources,
    relay server, manifest, GN args, and module artifacts are identified
    before launch.
    """

    _require_module_name(chrome_module_name, "Chrome module name")
    _require_module_name(content_module_name, "Content Shell module name")
    relay_script = _resolve_file(relay_script, "WISP relay script")
    return {
        "shared": {
            "composition_runner_source": _snapshot_file(
                Path(__file__), "composition runner source"
            ),
            "toolchain_manifest": _snapshot_file(
                MANIFEST_PATH, "toolchain manifest"
            ),
            "wisp_relay_server_source": _snapshot_file(
                relay_script, "WISP relay server source"
            ),
        },
        "chrome_controlled_https": {
            "args_gn": _snapshot_output_artifact(
                chrome_out_dir, "args.gn", "Chrome GN args"
            ),
            "loader": _snapshot_output_artifact(
                chrome_out_dir,
                f"{chrome_module_name}.js",
                "Chrome controlled-HTTPS loader",
            ),
            "wasm": _snapshot_output_artifact(
                chrome_out_dir,
                f"{chrome_module_name}.wasm",
                "Chrome controlled-HTTPS Wasm module",
            ),
            "runner_source": _snapshot_file(
                CHROME_RUNNER_PATH, "Chrome controlled-HTTPS runner source"
            ),
            "host_html": _snapshot_file(M6_HOST_HTML_PATH, "Chrome host HTML"),
            "host_js": _snapshot_file(M6_HOST_JS_PATH, "Chrome host JavaScript"),
            "text_input_js": _snapshot_file(
                M6_TEXT_INPUT_JS_PATH, "Chrome text-input bridge"
            ),
            "screenshot_contract": _snapshot_file(
                M6_SCREENSHOT_CONTRACT_PATH, "Chrome screenshot contract"
            ),
            "screenshot_baseline": _snapshot_file(
                _m6_screenshot_baseline_path(), "Chrome screenshot baseline"
            ),
        },
        "content_shell_wisp_recovery": {
            "args_gn": _snapshot_output_artifact(
                content_out_dir, "args.gn", "Content Shell GN args"
            ),
            "loader": _snapshot_output_artifact(
                content_out_dir,
                f"{content_module_name}.js",
                "Content Shell M5 loader",
            ),
            "wasm": _snapshot_output_artifact(
                content_out_dir,
                f"{content_module_name}.wasm",
                "Content Shell M5 Wasm module",
            ),
            "runner_source": _snapshot_file(
                CONTENT_RUNNER_PATH, "Content Shell M5 runner source"
            ),
            "host_server_source": _snapshot_file(
                M5_HOST_SERVER_PATH, "Content Shell host server source"
            ),
            "host_html": _snapshot_file(M5_HOST_HTML_PATH, "Content Shell host HTML"),
            "host_js": _snapshot_file(
                M5_HOST_JS_PATH, "Content Shell host JavaScript"
            ),
        },
    }


def verify_input_snapshots_unchanged(
    snapshots: dict[str, dict[str, FileSnapshot]],
    groups: Iterable[str] | None = None,
) -> None:
    """Reject a pass if a direct child input changed after preflight hashing."""

    selected_groups = tuple(groups) if groups is not None else tuple(snapshots)
    for group in selected_groups:
        files = snapshots.get(group)
        if not isinstance(files, dict):
            raise M0Error(f"M9 WISP composition snapshot group is missing: {group}")
        for name, snapshot in files.items():
            if not isinstance(snapshot, FileSnapshot):
                raise M0Error(
                    f"M9 WISP composition snapshot entry is invalid: {group}.{name}"
                )
            current = _file_identity(snapshot.path, f"{group}.{name}")
            if current != snapshot.identity:
                raise M0Error(
                    "M9 WISP composition input changed after preflight snapshot: "
                    f"{group}.{name}"
                )


def _byte_identity(snapshot: FileSnapshot) -> dict[str, object]:
    return dict(snapshot.identity)


def input_snapshot_identity(
    snapshots: dict[str, dict[str, FileSnapshot]],
    *,
    chrome_module_name: str,
    content_module_name: str,
) -> dict[str, object]:
    """Return a path-free, machine-readable direct-input identity record."""

    for group in (
        "shared",
        "chrome_controlled_https",
        "content_shell_wisp_recovery",
    ):
        if group not in snapshots:
            raise M0Error(f"M9 WISP composition snapshot group is missing: {group}")
    shared = snapshots["shared"]
    chrome = snapshots["chrome_controlled_https"]
    content = snapshots["content_shell_wisp_recovery"]
    try:
        return {
            "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
            "source_snapshot_provenance": SOURCE_SNAPSHOT_PROVENANCE,
            "shared": {
                name: _byte_identity(shared[name])
                for name in sorted(_SHARED_SNAPSHOT_FIELDS)
            },
            "chrome_controlled_https": {
                "artifact_delivery": ARTIFACT_DELIVERY,
                "args_gn": _byte_identity(chrome["args_gn"]),
                "host_html": _byte_identity(chrome["host_html"]),
                "host_js": _byte_identity(chrome["host_js"]),
                "loader": _byte_identity(chrome["loader"]),
                "module_name": chrome_module_name,
                "runner_source": _byte_identity(chrome["runner_source"]),
                "screenshot_baseline": _byte_identity(
                    chrome["screenshot_baseline"]
                ),
                "screenshot_contract": _byte_identity(
                    chrome["screenshot_contract"]
                ),
                "text_input_js": _byte_identity(chrome["text_input_js"]),
                "wasm": _byte_identity(chrome["wasm"]),
            },
            "content_shell_wisp_recovery": {
                "artifact_delivery": ARTIFACT_DELIVERY,
                "args_gn": _byte_identity(content["args_gn"]),
                "host_html": _byte_identity(content["host_html"]),
                "host_js": _byte_identity(content["host_js"]),
                "host_server_source": _byte_identity(content["host_server_source"]),
                "loader": _byte_identity(content["loader"]),
                "module_name": content_module_name,
                "runner_source": _byte_identity(content["runner_source"]),
                "wasm": _byte_identity(content["wasm"]),
            },
        }
    except KeyError as exc:
        raise M0Error("M9 WISP composition snapshot is incomplete") from exc


def _require_timeout(value: float, description: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise M0Error(f"{description} must be positive and finite")


def _require_m6_timeout(value: float) -> None:
    _require_timeout(value, "Chrome timeout")
    if value < M6_MIN_TIMEOUT_SECONDS:
        raise M0Error(
            "Chrome timeout must be at least five seconds for the M6 child"
        )


def chrome_child_command(
    *,
    out_dir: Path,
    module_name: str,
    timeout: float,
    diagnostics_dir: Path,
    browser: Path | None,
    node: Path | None,
    relay_script: Path,
    no_sandbox: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(CHROME_RUNNER_PATH),
        "--out-dir",
        str(out_dir),
        "--module-name",
        module_name,
        "--timeout",
        f"{timeout:g}",
        "--diagnostics-dir",
        str(diagnostics_dir),
        "--relay-script",
        str(relay_script),
    ]
    if browser is not None:
        command.extend(("--browser", str(browser)))
    if node is not None:
        command.extend(("--node", str(node)))
    if no_sandbox:
        command.append("--no-sandbox")
    return command


def content_child_command(
    *,
    out_dir: Path,
    module_name: str,
    timeout: float,
    diagnostics_dir: Path,
    browser: Path | None,
    node: Path | None,
    relay_script: Path,
    no_sandbox: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(CONTENT_RUNNER_PATH),
        "--out-dir",
        str(out_dir),
        "--module-name",
        module_name,
        "--timeout",
        f"{timeout:g}",
        "--diagnostics-dir",
        str(diagnostics_dir),
        "--relay-script",
        str(relay_script),
    ]
    if browser is not None:
        command.extend(("--browser", str(browser)))
    if node is not None:
        command.extend(("--node", str(node)))
    if no_sandbox:
        command.append("--no-sandbox")
    return command


def _signal_child_process_group(
    process: subprocess.Popen[bytes], signal_number: int
) -> None:
    """Signal only the child runner's dedicated process group.

    The M5/M6 Python runners start their own browser and relay sessions. A
    SIGINT to this runner group lets their normal ``finally`` cleanup stop
    those sessions cooperatively. A later forced kill cannot prove cleanup of
    those independently started sessions, and therefore always remains a
    failing, explicitly diagnostic outcome.
    """

    try:
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        return
    except OSError:
        # This fallback is useful on hosts without POSIX process groups. It is
        # still a cooperative request to the child runner, never success
        # evidence for an orphaned browser or relay.
        try:
            process.send_signal(signal_number)
        except ProcessLookupError:
            return


def _child_process_group_exists(process: subprocess.Popen[bytes]) -> bool:
    """Return whether the dedicated runner process group still exists.

    A reaped leader does not prove that browser or relay descendants have
    exited: a same-group descendant can retain no output pipe at all. Probe
    the group itself so a normal child result cannot hide that orphan. Hosts
    that cannot make an authoritative process-group probe fail closed.
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
    """Boundedly wait for the leader, its group, and inherited pipe readers."""

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
    process: subprocess.Popen[bytes], threads: Sequence[threading.Thread]
) -> bool:
    """Boundedly stop the runner group and inherited-pipe readers.

    SIGINT is sent to the process group even if its leader has already been
    reaped. A SIGKILL escalation is failure-only: it cannot prove the cleanup
    of child-owned browser or relay sessions.
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
                # Do not obscure an earlier child or capture failure while
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
        # The caller already has a primary failure. A cleanup failure is not
        # promoted over it; this path never produces successful evidence.
        pass
    try:
        _join_output_threads(threads)
    except BaseException:
        pass
    # A BufferedReader can be mid-read in a live reader thread. Closing it
    # first can itself block, so close only after bounded reader completion.
    if _output_threads_stopped(threads):
        _close_child_pipes(process)


def run_child(name: str, command: Sequence[str], timeout: float) -> ChildExecution:
    """Run a fresh child with bounded streaming output and cooperative cleanup."""

    _require_timeout(timeout, f"{name} timeout")
    started = time.perf_counter()
    process: subprocess.Popen[bytes] | None = None
    capture: _CappedPipeCapture | None = None
    reader_threads: tuple[threading.Thread, ...] | None = None
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
            # If stdout starts and stderr does not, retain only the started
            # reader for the common failure cleanup path.
            reader_threads = capture.started_threads
            raise
        deadline = time.monotonic() + float(timeout) + CHILD_PROCESS_GRACE_SECONDS
        while process.poll() is None:
            if capture.overflowed:
                interruption_reason = "child output exceeds the configured byte bound"
                break
            if capture.reader_failed:
                interruption_reason = "child output reader failed"
                break
            if time.monotonic() >= deadline:
                interruption_reason = "child exceeded its process timeout"
                break
            time.sleep(OUTPUT_POLL_SECONDS)

        if interruption_reason is not None:
            forced_kill = _stop_child_cooperatively(process, reader_threads)
            group_cleanup_done = True
        else:
            # A reaped leader alone is insufficient: descendants can retain
            # neither stdout nor stderr while still occupying the dedicated
            # runner group. Do not return any success evidence until the group
            # is absent and every inherited-pipe reader has reached EOF.
            if not _wait_for_process_and_output(
                process, reader_threads, FORCED_KILL_GRACE_SECONDS
            ):
                interruption_reason = (
                    "child process group did not exit after leader completion"
                )
                forced_kill = _stop_child_cooperatively(process, reader_threads)
                group_cleanup_done = True
        assert capture is not None
        if interruption_reason is not None:
            if forced_kill:
                raise M0Error(
                    f"{name} {interruption_reason}; force-killed only the "
                    "child runner process group after SIGINT. Child-owned "
                    "browser and relay sessions were independently started, "
                    "so their cleanup cannot be proven."
                )
            raise M0Error(f"{name} {interruption_reason}")
        stdout, stderr = capture.text()
        return ChildExecution(
            name=name,
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


def _combined_child_output(execution: ChildExecution) -> str:
    output = f"{execution.stdout}\n{execution.stderr}"
    if len(output.encode("utf-8")) > MAX_CHILD_OUTPUT_BYTES:
        raise M0Error(f"{execution.name} child output exceeds the bound")
    if execution.returncode != 0:
        raise M0Error(
            f"{execution.name} child exited with status {execution.returncode}"
        )
    return output


def _reject_duplicate_json_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _unique_json_record(
    output: str, prefix: str, description: str
) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise M0Error(f"{description} did not emit exactly one {prefix} record")
    try:
        record = json.loads(
            lines[0][len(prefix) :],
            object_pairs_hook=_reject_duplicate_json_object_keys,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise M0Error(f"{description} emitted malformed JSON") from exc
    if not isinstance(record, dict):
        raise M0Error(f"{description} result is not an object")
    return record


def _require_stdout_record_order(
    stdout: str, prefixes: Sequence[str], description: str
) -> list[int]:
    lines = stdout.splitlines()
    previous = -1
    indices: list[int] = []
    for prefix in prefixes:
        matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
        if len(matches) != 1 or matches[0] <= previous:
            raise M0Error(f"{description} terminal records are missing or unordered")
        previous = matches[0]
        indices.append(matches[0])
    return indices


def _require_stdout_pass_after_records(
    stdout: str,
    pass_marker: str,
    record_indices: Sequence[int],
    description: str,
) -> None:
    """Require exactly one child PASS in stdout after every terminal record."""

    lines = stdout.splitlines()
    pass_indices = [index for index, line in enumerate(lines) if line == pass_marker]
    if len(pass_indices) != 1:
        raise M0Error(
            f"{description} did not emit exactly one stdout {pass_marker}"
        )
    if not record_indices or pass_indices[0] <= max(record_indices):
        raise M0Error(
            f"{description} stdout PASS marker did not follow terminal records"
        )


def _versions_from_result(result: dict[str, Any], description: str) -> dict[str, str]:
    versions = _require_exact_fields(result.get("versions"), _VERSIONS_FIELDS, description)
    result_versions: dict[str, str] = {}
    for name in sorted(_VERSIONS_FIELDS):
        value = versions.get(name)
        if not isinstance(value, str) or not GIT_REVISION_RE.fullmatch(value):
            raise M0Error(f"{description} version {name} is invalid")
        result_versions[name] = value
    return result_versions


def _require_exact_value(value: object, expected: object, description: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise M0Error(f"{description} is invalid")


def _require_positive_integer(value: object, description: str) -> int:
    if type(value) is not int or value < 1:
        raise M0Error(f"{description} is invalid")
    return value


def _require_nonnegative_number(value: object, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M0Error(f"{description} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise M0Error(f"{description} is invalid")
    return result


def _validate_redacted_m6_result(result: dict[str, Any]) -> dict[str, str]:
    """Check the terminal public M6 record after its own full validator ran."""

    expected = {
        "protocol": 1,
        "case": m6_controlled_https.CASE,
        "scope": m6_controlled_https.SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusedAtStart": True,
        "proxyFocusedForText": True,
        "canvasFocusedForReload": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }
    for field, expected_value in expected.items():
        _require_exact_value(
            result.get(field), expected_value, f"M6 browser result {field}"
        )
    for field in ("fatalErrors", "windowErrors", "unhandledRejections"):
        _require_exact_value(result.get(field), [], f"M6 browser result {field}")
    controlled = result.get("controlledHttps")
    if not isinstance(controlled, dict):
        raise M0Error("M6 browser result lacks controlled-HTTPS evidence")
    for field in (
        "wispConfigured",
        "configurationPrecededFactory",
        "navigatedMarkerObserved",
        "reloadedMarkerObserved",
        "passMarkerObserved",
    ):
        _require_exact_value(
            controlled.get(field), True, f"M6 controlled-HTTPS evidence {field}"
        )
    screenshot = result.get("screenshot")
    if not isinstance(screenshot, dict):
        raise M0Error("M6 browser result lacks screenshot evidence")
    _require_exact_value(
        screenshot.get("dataBase64"), "<omitted>", "M6 redacted screenshot payload"
    )
    _require_exact_value(
        screenshot.get("mimeType"), "image/png", "M6 screenshot MIME type"
    )
    for field in ("width", "height", "frameId"):
        _require_positive_integer(screenshot.get(field), f"M6 screenshot {field}")
    _require_nonnegative_number(screenshot.get("timestampMs"), "M6 screenshot timestamp")
    for field in ("stdout", "stderr"):
        value = result.get(field)
        if not isinstance(value, list) or any(type(line) is not str for line in value):
            raise M0Error(f"M6 browser result {field} is invalid")
    embedded_output = "\n".join(result["stdout"] + result["stderr"])
    for marker in (
        m6_controlled_https.READY_MARKER,
        m6_controlled_https.NAVIGATED_MARKER,
        m6_controlled_https.RELOAD_READY_MARKER,
        m6_controlled_https.RELOADED_MARKER,
        m6_controlled_https.PASS_MARKER,
    ):
        if marker not in embedded_output:
            raise M0Error(f"M6 browser result is missing {marker}")
    return _versions_from_result(result, "M6 browser result")


def _canonical_json_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _child_output_evidence(execution: ChildExecution) -> dict[str, object]:
    stdout = execution.stdout.encode("utf-8")
    stderr = execution.stderr.encode("utf-8")
    return {
        "elapsed_ms": execution.elapsed_ms,
        "fresh_child_process": True,
        "fresh_host_browser_profile_owned_by_child": True,
        "returncode": execution.returncode,
        "stderr_bytes": len(stderr),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_bytes": len(stdout),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
    }


def validate_chrome_execution(execution: ChildExecution) -> tuple[dict[str, object], dict[str, str]]:
    """Validate the public M6 terminal records and retain bounded evidence."""

    _combined_child_output(execution)
    browser_prefix = f"{m6_controlled_https.SENTINEL}:BROWSER_RESULT "
    relay_prefix = f"{m6_controlled_https.SENTINEL}:RELAY_STATUS "
    record_indices = _require_stdout_record_order(
        execution.stdout, (browser_prefix, relay_prefix), "M6 child"
    )
    _require_stdout_pass_after_records(
        execution.stdout,
        m6_controlled_https.PASS_MARKER,
        record_indices,
        "M6 child",
    )
    browser_result = _unique_json_record(execution.stdout, browser_prefix, "M6 child")
    relay_status = _unique_json_record(execution.stdout, relay_prefix, "M6 child")
    versions = _validate_redacted_m6_result(browser_result)
    # The M6 child invokes this validator before emitting terminal output. Run
    # it again here so a fabricated terminal record cannot skip its relay proof.
    m6_controlled_https.validate_relay_status(relay_status)
    evidence = _child_output_evidence(execution)
    evidence.update(
        {
            "browser_result_sha256": _canonical_json_sha256(browser_result),
            "controlled_reload": True,
            "relay_status_sha256": _canonical_json_sha256(relay_status),
            "terminal_records": {
                "browser_result": 1,
                "pass": 1,
                "relay_status": 1,
            },
            "wisp_configured": True,
        }
    )
    return evidence, versions


def validate_content_execution(execution: ChildExecution) -> tuple[dict[str, object], dict[str, str]]:
    """Validate the public M5 carrier-close terminal records."""

    _combined_child_output(execution)
    pass_marker = f"{m5_wisp.SENTINEL}:PASS"
    ready_prefix = f"{m5_wisp.SENTINEL}:RELAY_READY "
    browser_prefix = f"{m5_wisp.SENTINEL}:BROWSER_RESULT "
    relay_prefix = f"{m5_wisp.SENTINEL}:RELAY_TRANSCRIPT "
    record_indices = _require_stdout_record_order(
        execution.stdout,
        (ready_prefix, browser_prefix, relay_prefix),
        "M5 child",
    )
    _require_stdout_pass_after_records(
        execution.stdout, pass_marker, record_indices, "M5 child"
    )
    ready_record = _unique_json_record(execution.stdout, ready_prefix, "M5 child")
    browser_result = _unique_json_record(execution.stdout, browser_prefix, "M5 child")
    relay_transcript = _unique_json_record(execution.stdout, relay_prefix, "M5 child")
    versions = _versions_from_result(browser_result, "M5 browser result")
    ready_line = json.dumps(ready_record, sort_keys=True, separators=(",", ":"))
    relay_ready = m5_wisp.parse_relay_ready_line(ready_line)
    # M5's established validators include the carrier-close chronology,
    # fresh WISP handshake, and recovery stream evidence.
    m5_wisp.validate_m5_result(
        browser_result, expected_versions=versions, relay_ready=relay_ready
    )
    m5_wisp.validate_relay_transcript(relay_transcript, relay_ready=relay_ready)
    if relay_transcript.get("reconnectPhase") != "recovered":
        raise M0Error("M5 relay transcript did not report carrier-close recovery")
    if relay_transcript.get("wispSessions") != 2:
        raise M0Error("M5 relay transcript did not report two WISP sessions")
    if relay_transcript.get("reconnectRecoveryRequests") != 1:
        raise M0Error("M5 relay transcript recovery request count is invalid")
    evidence = _child_output_evidence(execution)
    evidence.update(
        {
            "browser_result_sha256": _canonical_json_sha256(browser_result),
            "carrier_close_reconnect_phase": "recovered",
            "reconnect_recovery_requests": 1,
            "relay_transcript_sha256": _canonical_json_sha256(relay_transcript),
            "terminal_records": {
                "browser_result": 1,
                "pass": 1,
                "relay_ready": 1,
                "relay_transcript": 1,
            },
            "wisp_sessions": 2,
        }
    )
    return evidence, versions


def _validate_byte_identity(value: object, description: str) -> None:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    if type(identity.get("bytes")) is not int or identity["bytes"] < 1:
        raise M0Error(f"M9 WISP composition {description} byte count is invalid")
    sha256 = identity.get("sha256")
    if type(sha256) is not str or not SHA256_RE.fullmatch(sha256):
        raise M0Error(f"M9 WISP composition {description} SHA-256 is invalid")


def _validate_input_snapshot_identity(
    value: object, expected_identity: dict[str, object]
) -> None:
    identity = _require_exact_fields(value, _INPUT_SNAPSHOT_FIELDS, "input snapshots")
    _require_exact_value(
        identity.get("artifact_source_provenance"),
        ARTIFACT_SOURCE_PROVENANCE,
        "input snapshots artifact source provenance",
    )
    _require_exact_value(
        identity.get("source_snapshot_provenance"),
        SOURCE_SNAPSHOT_PROVENANCE,
        "input snapshots source snapshot provenance",
    )
    shared = _require_exact_fields(
        identity.get("shared"), _SHARED_SNAPSHOT_FIELDS, "shared input snapshots"
    )
    for field in _SHARED_SNAPSHOT_FIELDS:
        _validate_byte_identity(shared.get(field), f"shared input {field}")
    chrome = _require_exact_fields(
        identity.get("chrome_controlled_https"),
        _CHROME_SNAPSHOT_FIELDS,
        "Chrome input snapshots",
    )
    content = _require_exact_fields(
        identity.get("content_shell_wisp_recovery"),
        _CONTENT_SNAPSHOT_FIELDS,
        "Content Shell input snapshots",
    )
    for lane, lane_identity, fields in (
        ("Chrome", chrome, _CHROME_SNAPSHOT_FIELDS),
        ("Content Shell", content, _CONTENT_SNAPSHOT_FIELDS),
    ):
        _require_exact_value(
            lane_identity.get("artifact_delivery"),
            ARTIFACT_DELIVERY,
            f"{lane} artifact delivery",
        )
        module_name = lane_identity.get("module_name")
        if type(module_name) is not str or not MODULE_NAME_RE.fullmatch(module_name):
            raise M0Error(f"M9 WISP composition {lane} module name is invalid")
        for field in fields - {"artifact_delivery", "module_name"}:
            _validate_byte_identity(lane_identity.get(field), f"{lane} input {field}")
    if identity != expected_identity:
        raise M0Error(
            "M9 WISP composition input identities disagree with preflight snapshots"
        )


def _validate_versions(value: object) -> None:
    versions = _require_exact_fields(value, _VERSIONS_FIELDS, "version identifiers")
    for name in _VERSIONS_FIELDS:
        revision = versions.get(name)
        if type(revision) is not str or not GIT_REVISION_RE.fullmatch(revision):
            raise M0Error(f"M9 WISP composition version {name} is invalid")


def _validate_child_common(value: object, expected: frozenset[str], description: str) -> dict[str, Any]:
    child = _require_exact_fields(value, expected, description)
    for field in (
        "fresh_child_process",
        "fresh_host_browser_profile_owned_by_child",
    ):
        _require_exact_value(child.get(field), True, f"{description} {field}")
    _require_exact_value(child.get("returncode"), 0, f"{description} returncode")
    _require_nonnegative_number(child.get("elapsed_ms"), f"{description} elapsed time")
    for field in ("stdout_bytes", "stderr_bytes"):
        value = child.get(field)
        if type(value) is not int or value < 0:
            raise M0Error(f"{description} {field} is invalid")
    if child["stdout_bytes"] < 1:
        raise M0Error(f"{description} stdout_bytes is invalid")
    for field in ("stdout_sha256", "stderr_sha256"):
        sha256 = child.get(field)
        if type(sha256) is not str or not SHA256_RE.fullmatch(sha256):
            raise M0Error(f"{description} {field} is invalid")
    return child


def _validate_child_digest(value: object, description: str) -> None:
    if type(value) is not str or not SHA256_RE.fullmatch(value):
        raise M0Error(f"{description} is invalid")


def validate_composition_result(
    result: dict[str, Any], *, expected_input_identity: dict[str, object]
) -> None:
    """Validate that a successful result remains explicitly non-release."""

    result = _require_exact_fields(result, _RESULT_FIELDS, "result")
    expected = {
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "case": CASE,
        "kind": KIND,
        "m9_gate_complete": False,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "status": "pass",
    }
    for field, expected_value in expected.items():
        _require_exact_value(result.get(field), expected_value, f"result {field}")
    _require_exact_value(result.get("limitations"), list(LIMITATIONS), "result limitations")
    _validate_versions(result.get("versions"))
    _validate_input_snapshot_identity(result.get("input_snapshots"), expected_input_identity)

    composition = _require_exact_fields(
        result.get("composition"), _COMPOSITION_FIELDS, "composition"
    )
    expected_composition = {
        "child_order": [
            "chrome_controlled_https",
            "content_shell_wisp_carrier_close_recovery",
        ],
        "cross_executable": True,
        "execution_model": "serial-fresh-child-processes",
        "fresh_host_browser_profiles_owned_by_children": True,
        "m5_content_shell_carrier_close_recovery": True,
        "m6_chrome_controlled_https": True,
        "same_instance_chrome_recovery": False,
        "same_process": False,
        "shared_profile": False,
    }
    if composition != expected_composition:
        raise M0Error("M9 WISP composition execution model is invalid")

    children = _require_exact_fields(result.get("children"), _CHILDREN_FIELDS, "children")
    chrome = _validate_child_common(
        children.get("chrome_controlled_https"), _CHROME_CHILD_FIELDS, "M6 child"
    )
    _require_exact_value(chrome.get("controlled_reload"), True, "M6 child reload")
    _require_exact_value(chrome.get("wisp_configured"), True, "M6 child WISP")
    _require_exact_value(
        chrome.get("terminal_records"),
        {"browser_result": 1, "pass": 1, "relay_status": 1},
        "M6 child terminal records",
    )
    for field in ("browser_result_sha256", "relay_status_sha256"):
        _validate_child_digest(chrome.get(field), f"M6 child {field}")

    content = _validate_child_common(
        children.get("content_shell_wisp_carrier_close_recovery"),
        _CONTENT_CHILD_FIELDS,
        "M5 child",
    )
    _require_exact_value(
        content.get("carrier_close_reconnect_phase"),
        "recovered",
        "M5 child reconnect phase",
    )
    _require_exact_value(
        content.get("wisp_sessions"), 2, "M5 child WISP sessions"
    )
    _require_exact_value(
        content.get("reconnect_recovery_requests"),
        1,
        "M5 child recovery request count",
    )
    _require_exact_value(
        content.get("terminal_records"),
        {
            "browser_result": 1,
            "pass": 1,
            "relay_ready": 1,
            "relay_transcript": 1,
        },
        "M5 child terminal records",
    )
    for field in ("browser_result_sha256", "relay_transcript_sha256"):
        _validate_child_digest(content.get(field), f"M5 child {field}")


def make_composition_result(
    *,
    chrome_evidence: dict[str, object],
    content_evidence: dict[str, object],
    input_identity: dict[str, object],
    versions: dict[str, str],
) -> dict[str, object]:
    result: dict[str, object] = {
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "case": CASE,
        "children": {
            "chrome_controlled_https": chrome_evidence,
            "content_shell_wisp_carrier_close_recovery": content_evidence,
        },
        "composition": {
            "child_order": [
                "chrome_controlled_https",
                "content_shell_wisp_carrier_close_recovery",
            ],
            "cross_executable": True,
            "execution_model": "serial-fresh-child-processes",
            "fresh_host_browser_profiles_owned_by_children": True,
            "m5_content_shell_carrier_close_recovery": True,
            "m6_chrome_controlled_https": True,
            "same_instance_chrome_recovery": False,
            "same_process": False,
            "shared_profile": False,
        },
        "input_snapshots": input_identity,
        "kind": KIND,
        "limitations": list(LIMITATIONS),
        "m9_gate_complete": False,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "status": "pass",
        "versions": versions,
    }
    validate_composition_result(result, expected_input_identity=input_identity)
    return result


def run_composition(
    *,
    chrome_out_dir: Path,
    chrome_module_name: str,
    chrome_timeout: float,
    content_out_dir: Path,
    content_module_name: str,
    content_timeout: float,
    diagnostics_dir: Path,
    browser: Path | None,
    node: Path | None,
    relay_script: Path,
    no_sandbox: bool,
) -> dict[str, object]:
    """Run M6 then M5 in separate children and compose only bounded evidence."""

    _require_m6_timeout(chrome_timeout)
    _require_timeout(content_timeout, "Content Shell timeout")
    chrome_out_dir = _resolve_out_dir(chrome_out_dir, "Chrome")
    content_out_dir = _resolve_out_dir(content_out_dir, "Content Shell")
    relay_script = _resolve_file(relay_script, "WISP relay script")
    snapshots = snapshot_composition_inputs(
        chrome_out_dir=chrome_out_dir,
        chrome_module_name=chrome_module_name,
        content_out_dir=content_out_dir,
        content_module_name=content_module_name,
        relay_script=relay_script,
    )
    input_identity = input_snapshot_identity(
        snapshots,
        chrome_module_name=chrome_module_name,
        content_module_name=content_module_name,
    )

    chrome_execution = run_child(
        "Chrome controlled-HTTPS",
        chrome_child_command(
            out_dir=chrome_out_dir,
            module_name=chrome_module_name,
            timeout=chrome_timeout,
            diagnostics_dir=diagnostics_dir / "chrome-controlled-https",
            browser=browser,
            node=node,
            relay_script=relay_script,
            no_sandbox=no_sandbox,
        ),
        chrome_timeout,
    )
    chrome_evidence, chrome_versions = validate_chrome_execution(chrome_execution)
    verify_input_snapshots_unchanged(
        snapshots, ("shared", "chrome_controlled_https")
    )

    content_execution = run_child(
        "Content Shell WISP carrier-close recovery",
        content_child_command(
            out_dir=content_out_dir,
            module_name=content_module_name,
            timeout=content_timeout,
            diagnostics_dir=diagnostics_dir / "content-shell-wisp-recovery",
            browser=browser,
            node=node,
            relay_script=relay_script,
            no_sandbox=no_sandbox,
        ),
        content_timeout,
    )
    content_evidence, content_versions = validate_content_execution(content_execution)
    verify_input_snapshots_unchanged(
        snapshots, ("shared", "content_shell_wisp_recovery")
    )
    if chrome_versions != content_versions:
        raise M0Error(
            "M6 Chrome and M5 Content Shell child version identifiers disagree"
        )
    return make_composition_result(
        chrome_evidence=chrome_evidence,
        content_evidence=content_evidence,
        input_identity=input_identity,
        versions=chrome_versions,
    )


def _bounded_failure_message(error: Exception) -> str:
    message = " ".join(str(error).split())
    if len(message) > MAX_FAILURE_MESSAGE_CHARS:
        return message[:MAX_FAILURE_MESSAGE_CHARS] + "..."
    return message


def write_failure_diagnostics(
    diagnostics_dir: Path, *, stage: str, error: Exception
) -> Path:
    """Write a bounded failure record without child output or loopback URLs."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "m9-wisp-recovery-composition-failure.json"
    payload = {
        "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
        "case": CASE,
        "kind": KIND,
        "m9_gate_complete": False,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "stage": stage,
        "status": "fail",
        "failure": {
            "message": _bounded_failure_message(error),
            "type": type(error).__name__,
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
        description="Compose bounded M6 Chrome and M5 Content Shell WISP evidence."
    )
    parser.add_argument("--chrome-out-dir", type=Path, default=DEFAULT_CHROME_OUT_DIR)
    parser.add_argument("--chrome-module-name", default=DEFAULT_CHROME_MODULE_NAME)
    parser.add_argument("--content-out-dir", type=Path, default=DEFAULT_CONTENT_OUT_DIR)
    parser.add_argument("--content-module-name", default=DEFAULT_CONTENT_MODULE_NAME)
    parser.add_argument("--chrome-timeout", type=parse_timeout, default=DEFAULT_TIMEOUT)
    parser.add_argument("--content-timeout", type=parse_timeout, default=DEFAULT_TIMEOUT)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--relay-script", type=Path, default=DEFAULT_RELAY_SCRIPT)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    args = parser.parse_args()

    stage = "resolve_paths"
    diagnostics_dir: Path | None = None
    try:
        chrome_out_dir = _resolve_out_dir(args.chrome_out_dir, "Chrome")
        content_out_dir = _resolve_out_dir(args.content_out_dir, "Content Shell")
        relay_script = _resolve_file(args.relay_script, "WISP relay script")
        diagnostics_dir = args.diagnostics_dir or (
            chrome_out_dir / "diagnostics-m9-wisp-recovery-composition"
        )
        if not diagnostics_dir.is_absolute():
            diagnostics_dir = (REPO_ROOT / diagnostics_dir).resolve()

        stage = "run_serial_children"
        result = run_composition(
            chrome_out_dir=chrome_out_dir,
            chrome_module_name=args.chrome_module_name,
            chrome_timeout=args.chrome_timeout,
            content_out_dir=content_out_dir,
            content_module_name=args.content_module_name,
            content_timeout=args.content_timeout,
            diagnostics_dir=diagnostics_dir,
            browser=args.browser,
            node=args.node,
            relay_script=relay_script,
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
                    diagnostics_dir, stage=stage, error=error
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

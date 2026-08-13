#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build one fresh Chrome Wasm output and record its local source binding.

This is deliberately a narrow M9 preparation tool.  It only records that a
clean top-level checkout ran the pinned bootstrap check, generated a fresh GN
directory with the exact M6 Chrome arguments, passed the existing Chrome
dependency-boundary guard, and built ``chrome_wasm``.  It is not a release
command or an M9 acceptance result: M7 persistence, M8 feature coverage, and
the remaining M9 runtime/reliability work are outside this attestation.

The output directory must not exist before the run.  That makes the generated
``args.gn`` and module hashes attributable to this invocation instead of a
pre-existing incremental build.  Source cleanliness is checked before and
after the build so source changes cannot silently acquire the recorded commit
and tree identity.

If a final post-write validation fails, the runner deliberately leaves its
attestation record in the fresh output directory and returns failure.  It does
not attempt pathname cleanup: even a checked unlink can race a replacement.
The checks are cooperative local-workspace safeguards, not a hostile-filesystem
atomicity claim.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Sequence

# ``check_m6_chrome_boundary`` is also an executable sibling and imports
# ``m0_common`` by filename.  Import both through that same path in package
# and script mode so a boundary failure remains the same M0Error type.
_TOOLS_DIRECTORY = str(Path(__file__).resolve().parent)
if _TOOLS_DIRECTORY not in sys.path:
    sys.path.insert(0, _TOOLS_DIRECTORY)
from check_m6_chrome_boundary import check_boundary
from m0_common import M0Error, REPO_ROOT, gn_args_text, validate_test262_manifest
from m9_descriptor_snapshot import (
    hash_regular_file,
    hash_regular_files,
    snapshot_regular_file_with_identity,
)


SENTINEL = "CHROMIUM_WASM_M9_CLEAN_BUILD_ATTESTATION"
PASS_MARKER = f"{SENTINEL}:PASS"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
SCHEMA_VERSION = 1
CASE = "chrome_wasm_m9_clean_build_attestation"
SCOPE = (
    "clean-top-level-checkout-pinned-bootstrap-fresh-gn-chrome-wasm-build-"
    "and-boundary-only"
)
STATUS = "local_clean_rebuild_only"
RELEASE_STATUS = "not_a_release"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m9-clean-build")
BOOTSTRAP_PROFILE = "m3"
BOOTSTRAP_MARKER = "CHROMIUM_WASM_M3:BOOTSTRAP_PASS"
GN_ARGS_MANIFEST_KEY = "m6_chrome_gn_args"
GN_TARGET = "//chrome:chrome_wasm"
NINJA_TARGET = "chrome_wasm"
MODULE_NAME = "chrome_wasm"
ATTESTATION_FILENAME = "m9_clean_build_attestation.json"
MANIFEST_RELATIVE_PATH = "tools/wasm/toolchain_manifest.json"
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
MAX_GN_ARGS_BYTES = 1024 * 1024
MAX_COMMAND_DIAGNOSTIC_CHARS = 4096
# Capture command output in bytes before decoding it.  The final diagnostic is
# intentionally much smaller, but enforcing this cap while pipes are drained
# is what prevents a failing build tool from consuming unbounded runner memory.
MAX_COMMAND_OUTPUT_BYTES = 8 * 1024 * 1024
COMMAND_OUTPUT_READ_BYTES = 64 * 1024
COMMAND_POLL_SECONDS = 0.05
COMMAND_COOPERATIVE_STOP_SECONDS = 3.0
COMMAND_FORCED_STOP_SECONDS = 3.0
GIT_COMMAND_TIMEOUT_SECONDS = 60.0
BOOTSTRAP_COMMAND_TIMEOUT_SECONDS = 300.0
GN_COMMAND_TIMEOUT_SECONDS = 300.0
NINJA_COMMAND_TIMEOUT_SECONDS = 1800.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 300.0
GIT_REVISION_LENGTH = 40
SHA256_LENGTH = 64

LIMITATIONS = (
    "does_not_assess_m7_opfs_profile_persistence_or_recovery",
    "does_not_assess_m8_page_webassembly_audio_or_feature_compatibility",
    "does_not_run_a_browser_or_network_runtime_smoke",
    "does_not_measure_or_prove_m9_long_run_reliability",
    "does_not_supply_release_licenses_or_release_eligibility",
)


@dataclass(frozen=True)
class _FileIdentity:
    """The regular-file identity needed for post-write verification."""

    device: int
    inode: int
    mode: int
    size: int
    modification_time_ns: int
    change_time_ns: int


@dataclass(frozen=True)
class WrittenAttestation:
    """The exact regular file this invocation successfully created."""

    path: Path
    contents: bytes
    identity: _FileIdentity


@dataclass(frozen=True)
class _StableFileCapture:
    """Descriptor-captured bytes plus non-public metadata identity."""

    contents: bytes
    identity: _FileIdentity


@dataclass(frozen=True)
class _ManifestCapture:
    """One parsed manifest whose identity remains private to this runner."""

    manifest: dict[str, Any]
    record: dict[str, object]
    identity: _FileIdentity


@dataclass(frozen=True)
class _GnArgsCapture:
    """One exact generated-args record with its private file identity."""

    record: dict[str, object]
    identity: _FileIdentity


@dataclass(frozen=True)
class _ModuleArtifactsCapture:
    """Grouped module records and their private descriptor identities."""

    records: dict[str, dict[str, object]]
    identities: dict[str, _FileIdentity]


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _canonical_json_text(value: object) -> str:
    return _canonical_json_bytes(value).decode("utf-8").rstrip("\n")


def _manifest_path() -> Path:
    return REPO_ROOT / MANIFEST_RELATIVE_PATH


def _require_regular_file(
    path: Path,
    description: str,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> os.stat_result:
    try:
        file_status = path.lstat()
    except FileNotFoundError as exc:
        raise M0Error(f"{description} is missing: {path}") from exc
    if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(file_status.st_mode):
        raise M0Error(
            f"{description} must be a regular non-symlink file: {path}"
        )
    if file_status.st_size < 0 or file_status.st_size > maximum_bytes:
        raise M0Error(f"{description} has an invalid size: {path}")
    if not allow_empty and file_status.st_size == 0:
        raise M0Error(f"{description} must not be empty: {path}")
    return file_status


def _read_stable_file(
    path: Path,
    description: str,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> bytes:
    return _capture_stable_file(
        path,
        description,
        maximum_bytes=maximum_bytes,
        allow_empty=allow_empty,
    ).contents


def _capture_stable_file(
    path: Path,
    description: str,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> _StableFileCapture:
    """Capture one descriptor-pinned nonempty file and retain all metadata."""

    if allow_empty:
        raise M0Error(f"{description} stable read cannot allow an empty file")
    capture = snapshot_regular_file_with_identity(
        path,
        maximum_bytes=maximum_bytes,
        description=description,
    )
    return _StableFileCapture(
        contents=capture.contents,
        identity=_file_identity_from_pinned_identity(capture.pinned_identity),
    )


def stable_file_record(path: Path, description: str) -> dict[str, object]:
    """Return a size and digest only if a regular artifact stayed unchanged."""

    return hash_regular_file(
        path,
        maximum_bytes=MAX_ARTIFACT_BYTES,
        description=description,
    ).byte_identity()


def _require_real_directory(path: Path, description: str) -> Path:
    try:
        file_status = path.lstat()
    except FileNotFoundError as exc:
        raise M0Error(f"{description} is missing: {path}") from exc
    if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISDIR(file_status.st_mode):
        raise M0Error(f"{description} must be a real directory: {path}")
    return path


def _file_identity_from_pinned_identity(
    pinned_identity: tuple[int, int, int, int, int, int],
) -> _FileIdentity:
    """Preserve all descriptor-captured metadata for post-write comparison."""

    if (
        type(pinned_identity) is not tuple
        or len(pinned_identity) != 6
        or any(type(value) is not int for value in pinned_identity)
    ):
        raise M0Error("clean-build attestation snapshot identity is invalid")
    return _FileIdentity(
        device=pinned_identity[0],
        inode=pinned_identity[1],
        mode=pinned_identity[2],
        size=pinned_identity[3],
        modification_time_ns=pinned_identity[4],
        change_time_ns=pinned_identity[5],
    )


def _require_executable(path: Path, description: str) -> Path:
    _require_regular_file(
        path,
        description,
        maximum_bytes=MAX_ARTIFACT_BYTES,
        allow_empty=False,
    )
    if not os.access(path, os.X_OK):
        raise M0Error(f"{description} is not executable: {path}")
    return path


def _output_path_layout(out_dir: Path) -> tuple[Path, Path, Path, Path]:
    """Return a lexical ``checkout/out`` layout without following links."""

    checkout_root = REPO_ROOT.resolve()
    output_root = checkout_root / "out"
    raw_output = out_dir if out_dir.is_absolute() else checkout_root / out_dir
    if any(component == ".." for component in raw_output.parts):
        raise M0Error("clean-build output directory must not contain '..'")
    try:
        relative_output = raw_output.relative_to(output_root)
    except ValueError as exc:
        raise M0Error("clean-build output directory must stay below out/") from exc
    if not relative_output.parts:
        raise M0Error("clean-build output directory must not be out/ itself")
    if any(component in ("", ".", "..") for component in relative_output.parts):
        raise M0Error("clean-build output directory is invalid")
    return checkout_root, output_root, raw_output, relative_output


def revalidate_new_output_dir(out_dir: Path) -> Path:
    """Require a still-new output path without following link components.

    This is used both at initial argument validation and immediately before GN
    generation.  The second check prevents an existing parent from becoming a
    symlink while the bootstrap verification was running.
    """

    _, raw_output_root, raw_output, relative_output = _output_path_layout(out_dir)
    output_root = _require_real_directory(raw_output_root, "output root")

    current = output_root
    for component in relative_output.parts[:-1]:
        current /= component
        if not os.path.lexists(current):
            break
        _require_real_directory(current, "clean-build output parent")
    if os.path.lexists(raw_output):
        raise M0Error(
            "clean-build output directory must be new and nonexistent: "
            f"{raw_output}"
        )
    return raw_output


def resolve_new_output_dir(out_dir: Path) -> Path:
    """Limit a new build tree to a real ``out/`` descendant.

    Refusing existing files, directories, and dangling links keeps a failed or
    incremental output from being mistaken for a fresh local rebuild.  Reject
    link components as well: a result must not be redirected outside the
    checkout through an output-directory alias.
    """

    return revalidate_new_output_dir(out_dir)


def revalidate_output_dir(out_dir: Path) -> Path:
    """Recheck a generated output tree without following link components.

    A parent may have changed after the initial nonexistent-output check while
    GN or Ninja was running.  Before hashes or an attestation are trusted,
    require every currently present path component to be a real directory and
    require the resolved output to remain strictly beneath this checkout's
    canonical ``out/`` directory.
    """

    checkout_root, raw_output_root, raw_output, relative_output = (
        _output_path_layout(out_dir)
    )
    output_root = _require_real_directory(raw_output_root, "output root")
    current = output_root
    for component in relative_output.parts:
        current /= component
        _require_real_directory(current, "clean-build output path component")

    try:
        canonical_output_root = output_root.resolve(strict=True)
        canonical_output = raw_output.resolve(strict=True)
    except OSError as exc:
        raise M0Error("could not resolve clean-build output directory") from exc
    try:
        canonical_output.relative_to(canonical_output_root)
        canonical_output_root.relative_to(checkout_root)
    except ValueError as exc:
        raise M0Error(
            "resolved clean-build output directory must stay below checkout/out"
        ) from exc
    if canonical_output == canonical_output_root:
        raise M0Error("clean-build output directory must not be out/ itself")
    return canonical_output


def _bounded_command_diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    chunks: list[str] = []
    for label, value in (("stdout", result.stdout), ("stderr", result.stderr)):
        if isinstance(value, str) and value:
            chunks.append(f"{label}:\n{value.strip()}")
    detail = "\n".join(chunks)
    if len(detail) <= MAX_COMMAND_DIAGNOSTIC_CHARS:
        return detail
    marker = "\n... command output truncated ...\n"
    retained = (MAX_COMMAND_DIAGNOSTIC_CHARS - len(marker)) // 2
    return detail[:retained] + marker + detail[-retained:]


class _CappedCommandCapture:
    """Drain both command pipes while retaining one shared byte budget.

    The readers deliberately continue after the retained prefix reaches the
    limit.  That lets the runner interrupt a noisy command group without
    deadlocking on an inherited full pipe.
    """

    def __init__(self, byte_limit: int) -> None:
        if type(byte_limit) is not int or byte_limit <= 0:
            raise ValueError("command output byte limit must be positive")
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
        """Return only readers whose ``Thread.start`` completed."""

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
            while chunk := read_chunk(COMMAND_OUTPUT_READ_BYTES):
                if not isinstance(chunk, bytes):
                    raise TypeError("command pipe did not produce bytes")
                self._append(chunks, chunk)
        except BaseException as exc:
            with self._lock:
                self._reader_errors.append(exc)
            self._reader_failed.set()

    def start(self, process: subprocess.Popen[bytes]) -> tuple[threading.Thread, ...]:
        if process.stdout is None or process.stderr is None:
            raise M0Error("command output pipes are unavailable")
        stdout_thread = threading.Thread(
            target=self._drain,
            args=(process.stdout, self._stdout_chunks),
            name="chromium-wasm-m9-attestation-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._drain,
            args=(process.stderr, self._stderr_chunks),
            name="chromium-wasm-m9-attestation-stderr",
            daemon=True,
        )
        stdout_thread.start()
        self._started_threads.append(stdout_thread)
        stderr_thread.start()
        self._started_threads.append(stderr_thread)
        return tuple(self._started_threads)

    def text(self) -> tuple[str, str]:
        with self._lock:
            errors = tuple(self._reader_errors)
            stdout = b"".join(self._stdout_chunks)
            stderr = b"".join(self._stderr_chunks)
        if errors:
            raise M0Error(f"command output reader failed: {errors[0]}")
        # Check the raw cap before decoding: a retained prefix can end inside
        # a UTF-8 sequence when the cap lands in the middle of a code point.
        if self.overflowed:
            raise M0Error("command output exceeds the configured byte bound")
        try:
            return stdout.decode("utf-8"), stderr.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise M0Error("command output is not valid UTF-8") from exc


def _command_timeout_seconds(command: Sequence[str], description: str) -> float:
    """Return the finite timeout appropriate to one known local command."""

    if command and Path(command[0]).name == "git":
        return GIT_COMMAND_TIMEOUT_SECONDS
    if description == "pinned M3 bootstrap verify-only check":
        return BOOTSTRAP_COMMAND_TIMEOUT_SECONDS
    if description == "fresh Chrome Wasm GN generation":
        return GN_COMMAND_TIMEOUT_SECONDS
    if description == "fresh chrome_wasm autoninja build":
        return NINJA_COMMAND_TIMEOUT_SECONDS
    return DEFAULT_COMMAND_TIMEOUT_SECONDS


def _signal_command_group(
    process: subprocess.Popen[bytes], signal_number: int
) -> None:
    """Signal only the session-created command process group."""

    try:
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise M0Error("could not signal the clean-build command process group") from exc


def _command_group_exists(process: subprocess.Popen[bytes]) -> bool:
    """Fail closed unless the command's dedicated process group is absent."""

    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        raise M0Error(
            "cannot verify clean-build command process-group absence"
        ) from exc


def _output_threads_stopped(threads: Sequence[threading.Thread]) -> bool:
    return not any(thread.is_alive() for thread in threads)


def _wait_for_command_completion(
    process: subprocess.Popen[bytes],
    threads: Sequence[threading.Thread],
    timeout: float,
) -> bool:
    """Wait for leader exit, reader EOF, and process-group disappearance."""

    deadline = time.monotonic() + timeout
    while True:
        if (
            process.poll() is not None
            and _output_threads_stopped(threads)
            and not _command_group_exists(process)
        ):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        alive_threads = [thread for thread in threads if thread.is_alive()]
        if alive_threads:
            for thread in alive_threads:
                thread.join(timeout=min(COMMAND_POLL_SECONDS, remaining))
        else:
            time.sleep(min(COMMAND_POLL_SECONDS, remaining))


def _stop_command_group(
    process: subprocess.Popen[bytes], threads: Sequence[threading.Thread]
) -> bool:
    """Boundedly stop the command group; return whether SIGKILL was needed."""

    _signal_command_group(process, signal.SIGINT)
    if _wait_for_command_completion(
        process, threads, COMMAND_COOPERATIVE_STOP_SECONDS
    ):
        return False
    _signal_command_group(process, signal.SIGKILL)
    if not _wait_for_command_completion(process, threads, COMMAND_FORCED_STOP_SECONDS):
        raise M0Error(
            "clean-build command process group or output pipes did not exit "
            "after SIGINT and SIGKILL"
        )
    return True


def _close_command_pipes(process: subprocess.Popen[bytes]) -> None:
    """Close local pipes only after reader threads have stopped."""

    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                # Preserve the primary command/capture failure.
                pass


def _cleanup_command_failure(
    process: subprocess.Popen[bytes] | None,
    threads: Sequence[threading.Thread],
) -> None:
    """Best-effort bounded cleanup that never masks a primary exception."""

    if process is None:
        return
    try:
        _stop_command_group(process, threads)
    except BaseException:
        pass
    if _output_threads_stopped(threads):
        _close_command_pipes(process)


def _stop_command_for_primary_failure(
    process: subprocess.Popen[bytes],
    threads: Sequence[threading.Thread],
    description: str,
    reason: str,
) -> bool:
    """Stop a command without allowing cleanup trouble to hide ``reason``."""

    try:
        return _stop_command_group(process, threads)
    except BaseException as cleanup_error:
        raise M0Error(
            f"{description} {reason}; command cleanup could not be fully verified"
        ) from cleanup_error


def _run_bounded_command(
    command: Sequence[str], description: str, timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    """Run one local build prerequisite with bounded output and lifetime."""

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("command timeout must be positive and finite")
    process: subprocess.Popen[bytes] | None = None
    capture: _CappedCommandCapture | None = None
    reader_threads: tuple[threading.Thread, ...] = ()
    group_cleanup_done = False
    try:
        process = subprocess.Popen(
            list(command),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        capture = _CappedCommandCapture(MAX_COMMAND_OUTPUT_BYTES)
        try:
            reader_threads = capture.start(process)
        except BaseException:
            reader_threads = capture.started_threads
            raise
        deadline = time.monotonic() + timeout_seconds
        interruption_reason: str | None = None
        while True:
            if capture.overflowed:
                interruption_reason = "output exceeds the configured byte bound"
                break
            if capture.reader_failed:
                interruption_reason = "output reader failed"
                break
            if process.poll() is not None:
                break
            if time.monotonic() >= deadline:
                interruption_reason = "exceeded its command timeout"
                break
            time.sleep(COMMAND_POLL_SECONDS)

        forced_kill = False
        if interruption_reason is not None:
            forced_kill = _stop_command_for_primary_failure(
                process, reader_threads, description, interruption_reason
            )
            group_cleanup_done = True
        elif not _wait_for_command_completion(
            process, reader_threads, COMMAND_FORCED_STOP_SECONDS
        ):
            interruption_reason = "process group did not exit after leader completion"
            forced_kill = _stop_command_for_primary_failure(
                process, reader_threads, description, interruption_reason
            )
            group_cleanup_done = True

        if interruption_reason is not None:
            if forced_kill:
                raise M0Error(
                    f"{description} {interruption_reason}; force-killed its "
                    "dedicated process group after SIGINT"
                )
            raise M0Error(f"{description} {interruption_reason}")
        assert capture is not None
        stdout, stderr = capture.text()
        assert process.returncode is not None
        return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)
    except BaseException:
        if not group_cleanup_done:
            _cleanup_command_failure(process, reader_threads)
        raise
    finally:
        if process is not None and _output_threads_stopped(reader_threads):
            _close_command_pipes(process)


def run_required_command(
    command: Sequence[str], description: str, *, timeout_seconds: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run one named local prerequisite without inheriting shell parsing."""

    try:
        result = _run_bounded_command(
            command,
            description,
            _command_timeout_seconds(command, description)
            if timeout_seconds is None
            else timeout_seconds,
        )
    except (OSError, ValueError, UnicodeError) as exc:
        raise M0Error(f"could not start {description}: {exc}") from exc
    if result.returncode:
        diagnostic = _bounded_command_diagnostic(result)
        message = (
            f"{description} failed ({result.returncode}): "
            f"{shlex.join(list(command))}"
        )
        if diagnostic:
            message += f"\n{diagnostic}"
        raise M0Error(message)
    return result


def _git_output(arguments: Sequence[str], description: str) -> str:
    result = run_required_command(["git", *arguments], description)
    if not isinstance(result.stdout, str):
        raise M0Error(f"{description} did not return text output")
    return result.stdout.rstrip("\n")


def require_clean_top_level_checkout() -> None:
    """Fail closed on every top-level tracked, staged, or untracked entry."""

    status = _git_output(
        (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ),
        "top-level Git status",
    )
    if status:
        entries = [entry for entry in status.split("\0") if entry]
        preview = ", ".join(entries[:3])
        suffix = "" if len(entries) <= 3 else ", ..."
        raise M0Error(
            "M9 clean-build attestation requires no top-level dirty or "
            f"untracked paths ({preview}{suffix})"
        )


def checkout_identity() -> dict[str, str]:
    """Capture the source commit and its exact top-level Git tree."""

    reported_root = Path(
        _git_output(("rev-parse", "--show-toplevel"), "Git checkout root")
    ).resolve()
    if reported_root != REPO_ROOT.resolve():
        raise M0Error("M9 clean-build attestation must run from its checkout root")
    commit = _git_output(("rev-parse", "HEAD"), "Git commit identity")
    tree = _git_output(("rev-parse", "HEAD^{tree}"), "Git tree identity")
    if not _is_lower_hex(commit, GIT_REVISION_LENGTH):
        raise M0Error("Git commit identity is invalid")
    if not _is_lower_hex(tree, GIT_REVISION_LENGTH):
        raise M0Error("Git tree identity is invalid")
    return {"commit": commit, "tree": tree}


def _manifest_versions(manifest: dict[str, Any]) -> dict[str, str]:
    try:
        versions = {
            "chromium": manifest["chromium"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
            "rust": manifest["rust"]["source_revision"],
            "v8": manifest["git_dependencies"]["v8"]["revision"],
        }
    except (KeyError, TypeError) as exc:
        raise M0Error("toolchain manifest lacks a clean-build version field") from exc
    if not all(_is_lower_hex(value, GIT_REVISION_LENGTH) for value in versions.values()):
        raise M0Error("toolchain manifest has an invalid clean-build version field")
    return {name: str(versions[name]) for name in sorted(versions)}


def _load_manifest_capture() -> _ManifestCapture:
    """Capture, parse, and retain one descriptor-pinned toolchain manifest."""

    capture = _capture_stable_file(
        _manifest_path(),
        "toolchain manifest",
        maximum_bytes=MAX_GN_ARGS_BYTES,
    )
    try:
        manifest = json.loads(capture.contents.decode("utf-8"))
        if type(manifest) is not dict:
            raise M0Error("toolchain manifest must be an object")
        if manifest.get("schema_version") != 1:
            raise M0Error("unsupported toolchain manifest schema")
        validate_test262_manifest(manifest)
    except (M0Error, KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise M0Error(f"could not load toolchain manifest: {exc}") from exc
    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise M0Error("toolchain manifest schema is invalid")
    return _ManifestCapture(
        manifest=manifest,
        record={
            "path": MANIFEST_RELATIVE_PATH,
            "schema_version": schema_version,
            "sha256": hashlib.sha256(capture.contents).hexdigest(),
            "versions": _manifest_versions(manifest),
        },
        identity=capture.identity,
    )


def load_manifest_snapshot() -> tuple[dict[str, Any], dict[str, object]]:
    """Return the stable public manifest record without private metadata."""

    capture = _load_manifest_capture()
    return capture.manifest, capture.record


def expected_m6_chrome_gn_args(manifest: dict[str, Any]) -> bytes:
    """Return the unmodified M6 Chrome profile text selected for this build."""

    try:
        arguments = gn_args_text(manifest, GN_ARGS_MANIFEST_KEY)
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise M0Error("M9 clean-build GN arguments are invalid") from exc
    if type(arguments) is not str or not arguments or "\x00" in arguments:
        raise M0Error("M9 clean-build GN arguments are invalid")
    encoded = arguments.encode("utf-8")
    if len(encoded) > MAX_GN_ARGS_BYTES:
        raise M0Error("M9 clean-build GN arguments are too large")
    return encoded


def _capture_exact_generated_gn_args(
    out_dir: Path, expected_args: bytes
) -> _GnArgsCapture:
    capture = _capture_stable_file(
        out_dir / "args.gn",
        "generated GN args",
        maximum_bytes=MAX_GN_ARGS_BYTES,
    )
    if capture.contents != expected_args:
        raise M0Error(
            "generated GN args do not exactly match the pinned M6 Chrome profile"
        )
    return _GnArgsCapture(
        record={
            "bytes": len(capture.contents),
            "manifest_key": GN_ARGS_MANIFEST_KEY,
            "sha256": hashlib.sha256(capture.contents).hexdigest(),
        },
        identity=capture.identity,
    )


def require_exact_generated_gn_args(
    out_dir: Path, expected_args: bytes
) -> dict[str, object]:
    """Return public generated-args evidence without private metadata."""

    return _capture_exact_generated_gn_args(out_dir, expected_args).record


def _capture_module_artifacts(out_dir: Path) -> _ModuleArtifactsCapture:
    """Hash both module artifacts through one descriptor-pinned directory."""

    names = (f"{MODULE_NAME}.js", f"{MODULE_NAME}.wasm")
    captures = hash_regular_files(
        out_dir,
        names,
        maximum_bytes=MAX_ARTIFACT_BYTES,
        description="Chrome Wasm module artifacts",
    )
    return _ModuleArtifactsCapture(
        records={name: captures[name].byte_identity() for name in names},
        identities={
            name: _file_identity_from_pinned_identity(captures[name].pinned_identity)
            for name in names
        },
    )


def module_artifact_records(out_dir: Path) -> dict[str, dict[str, object]]:
    """Return public module records without private descriptor metadata."""

    return _capture_module_artifacts(out_dir).records


def _bootstrap_command() -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "tools/wasm/bootstrap.py"),
        "--profile",
        BOOTSTRAP_PROFILE,
        "--verify-only",
    ]


def _gn_gen_command(out_dir: Path, expected_args: bytes) -> list[str]:
    try:
        arguments = expected_args.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise M0Error("M9 clean-build GN arguments are not UTF-8") from exc
    return [
        str(_require_executable(REPO_ROOT / "buildtools/linux64/gn", "GN executable")),
        "gen",
        str(out_dir),
        "--args=" + arguments,
    ]


def _autoninja_command(out_dir: Path) -> list[str]:
    autoninja = _require_executable(
        REPO_ROOT / "third_party/depot_tools/autoninja", "autoninja executable"
    )
    return [str(autoninja), "-C", str(out_dir), NINJA_TARGET]


def _require_bootstrap_marker(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout if isinstance(result.stdout, str) else ""
    if sum(line == BOOTSTRAP_MARKER for line in output.splitlines()) != 1:
        raise M0Error("pinned M3 bootstrap did not emit its exact pass marker")


def _require_generated_out_dir(out_dir: Path) -> None:
    _require_real_directory(out_dir, "fresh clean-build output directory")


def make_attestation(
    *,
    checkout: dict[str, str],
    manifest: dict[str, object],
    gn_args: dict[str, object],
    artifacts: dict[str, dict[str, object]],
    out_dir: Path,
) -> dict[str, object]:
    """Build the fixed, deliberately non-release result schema."""

    if set(checkout) != {"commit", "tree"} or not all(
        _is_lower_hex(checkout.get(name), GIT_REVISION_LENGTH)
        for name in ("commit", "tree")
    ):
        raise M0Error("clean-build checkout identity is invalid")
    expected_manifest_keys = {"path", "schema_version", "sha256", "versions"}
    if set(manifest) != expected_manifest_keys:
        raise M0Error("clean-build toolchain manifest identity is invalid")
    expected_version_keys = {"chromium", "emscripten", "rust", "v8"}
    if (
        manifest["path"] != "tools/wasm/toolchain_manifest.json"
        or manifest["schema_version"] != 1
        or not _is_lower_hex(manifest["sha256"], SHA256_LENGTH)
        or type(manifest["versions"]) is not dict
        or set(manifest["versions"]) != expected_version_keys
        or not all(
            _is_lower_hex(manifest["versions"][name], GIT_REVISION_LENGTH)
            for name in expected_version_keys
        )
    ):
        raise M0Error("clean-build toolchain manifest identity is invalid")
    if set(gn_args) != {"bytes", "manifest_key", "sha256"}:
        raise M0Error("clean-build GN args identity is invalid")
    if (
        type(gn_args["bytes"]) is not int
        or gn_args["bytes"] <= 0
        or gn_args["manifest_key"] != GN_ARGS_MANIFEST_KEY
        or not _is_lower_hex(gn_args["sha256"], SHA256_LENGTH)
    ):
        raise M0Error("clean-build GN args identity is invalid")
    expected_artifact_names = {f"{MODULE_NAME}.js", f"{MODULE_NAME}.wasm"}
    if set(artifacts) != expected_artifact_names:
        raise M0Error("clean-build module artifacts are invalid")
    for artifact_name in sorted(artifacts):
        artifact = artifacts[artifact_name]
        if (
            type(artifact) is not dict
            or set(artifact) != {"bytes", "sha256"}
            or type(artifact["bytes"]) is not int
            or artifact["bytes"] <= 0
            or not _is_lower_hex(artifact["sha256"], SHA256_LENGTH)
        ):
            raise M0Error("clean-build module artifacts are invalid")
    try:
        output_directory = out_dir.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise M0Error("clean-build output directory must remain in the checkout") from exc
    return {
        "artifacts": {name: artifacts[name] for name in sorted(artifacts)},
        "bootstrap": {
            "mode": "verify-only",
            "profile": BOOTSTRAP_PROFILE,
        },
        "case": CASE,
        "checkout": {"commit": checkout["commit"], "tree": checkout["tree"]},
        "gn": {
            "args": gn_args,
            "target": GN_TARGET,
            "target_build_name": NINJA_TARGET,
        },
        "limitations": list(LIMITATIONS),
        "m9_gate_complete": False,
        "output_directory": output_directory,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "status": STATUS,
        "toolchain_manifest": manifest,
    }


def _capture_written_attestation(
    path: Path, expected_contents: bytes
) -> WrittenAttestation:
    """Require the just-written path to still be the exact expected file."""

    capture = _capture_stable_file(
        path,
        "clean-build attestation",
        maximum_bytes=MAX_GN_ARGS_BYTES,
    )
    if capture.contents != expected_contents:
        raise M0Error("clean-build attestation changed while it was written")
    return WrittenAttestation(
        path=path,
        contents=capture.contents,
        identity=capture.identity,
    )


def verify_written_attestation(written: WrittenAttestation) -> None:
    """Verify the final record still has its original identity and bytes."""

    try:
        observed = _capture_written_attestation(written.path, written.contents)
    except M0Error as exc:
        raise M0Error("clean-build attestation changed after it was written") from exc
    if (
        observed.identity != written.identity
        or observed.contents != written.contents
    ):
        raise M0Error("clean-build attestation changed after it was written")


def write_attestation(
    out_dir: Path, attestation: dict[str, object]
) -> WrittenAttestation:
    """Create one canonical result without replacing a pre-existing record."""

    _require_generated_out_dir(out_dir)
    destination = out_dir / ATTESTATION_FILENAME
    if os.path.lexists(destination):
        raise M0Error(f"clean-build attestation already exists: {destination}")
    encoded = _canonical_json_bytes(attestation)
    try:
        with destination.open("xb") as output_file:
            output_file.write(encoded)
            output_file.flush()
            os.fsync(output_file.fileno())
    except OSError as exc:
        raise M0Error(f"could not write clean-build attestation: {destination}") from exc
    return _capture_written_attestation(destination, encoded)


def run_clean_build_attestation(out_dir: Path) -> tuple[dict[str, object], Path]:
    """Execute the bounded clean-rebuild sequence and persist its binding."""

    resolved_out_dir = resolve_new_output_dir(out_dir)
    require_clean_top_level_checkout()
    initial_checkout = checkout_identity()
    initial_manifest_capture = _load_manifest_capture()
    expected_args = expected_m6_chrome_gn_args(initial_manifest_capture.manifest)

    bootstrap_result = run_required_command(
        _bootstrap_command(), "pinned M3 bootstrap verify-only check"
    )
    _require_bootstrap_marker(bootstrap_result)
    resolved_out_dir = revalidate_new_output_dir(resolved_out_dir)
    run_required_command(
        _gn_gen_command(resolved_out_dir, expected_args), "fresh Chrome Wasm GN generation"
    )
    resolved_out_dir = revalidate_output_dir(resolved_out_dir)
    initial_gn_args_capture = _capture_exact_generated_gn_args(
        resolved_out_dir, expected_args
    )
    check_boundary(resolved_out_dir)
    run_required_command(
        _autoninja_command(resolved_out_dir), "fresh chrome_wasm autoninja build"
    )
    resolved_out_dir = revalidate_output_dir(resolved_out_dir)
    final_gn_args_capture = _capture_exact_generated_gn_args(
        resolved_out_dir, expected_args
    )
    if (
        initial_gn_args_capture.record != final_gn_args_capture.record
        or initial_gn_args_capture.identity != final_gn_args_capture.identity
    ):
        raise M0Error("generated GN args changed during the Chrome Wasm build")
    artifacts_capture = _capture_module_artifacts(resolved_out_dir)

    final_manifest_capture = _load_manifest_capture()
    final_checkout = checkout_identity()
    require_clean_top_level_checkout()
    if initial_checkout != final_checkout:
        raise M0Error("Git checkout identity changed during the clean rebuild")
    if (
        initial_manifest_capture.record != final_manifest_capture.record
        or initial_manifest_capture.identity != final_manifest_capture.identity
    ):
        raise M0Error("toolchain manifest identity changed during the clean rebuild")
    if expected_m6_chrome_gn_args(final_manifest_capture.manifest) != expected_args:
        raise M0Error("M6 Chrome GN arguments changed during the clean rebuild")
    resolved_out_dir = revalidate_output_dir(resolved_out_dir)
    final_artifacts_capture = _capture_module_artifacts(resolved_out_dir)
    if (
        artifacts_capture.records != final_artifacts_capture.records
        or artifacts_capture.identities != final_artifacts_capture.identities
    ):
        raise M0Error("Chrome Wasm artifacts changed during the clean rebuild")

    attestation = make_attestation(
        checkout=initial_checkout,
        manifest=initial_manifest_capture.record,
        gn_args=final_gn_args_capture.record,
        artifacts=final_artifacts_capture.records,
        out_dir=resolved_out_dir,
    )
    written = write_attestation(resolved_out_dir, attestation)
    # The output tree is ignored by the top-level checkout.  Recheck after
    # writing to refuse a source mutation racing the final record creation.
    # On failure the record is intentionally retained; pathname cleanup could
    # unlink a replacement after a time-of-check/time-of-use race.
    resolved_out_dir = revalidate_output_dir(resolved_out_dir)
    require_clean_top_level_checkout()
    if checkout_identity() != initial_checkout:
        raise M0Error("Git checkout identity changed while writing attestation")
    post_write_manifest_capture = _load_manifest_capture()
    if (
        post_write_manifest_capture.record != final_manifest_capture.record
        or post_write_manifest_capture.identity != final_manifest_capture.identity
    ):
        raise M0Error("toolchain manifest changed while writing attestation")
    post_write_gn_args_capture = _capture_exact_generated_gn_args(
        resolved_out_dir, expected_args
    )
    if (
        post_write_gn_args_capture.record != final_gn_args_capture.record
        or post_write_gn_args_capture.identity != final_gn_args_capture.identity
    ):
        raise M0Error("generated GN args changed while writing attestation")
    post_write_artifacts_capture = _capture_module_artifacts(resolved_out_dir)
    if (
        post_write_artifacts_capture.records != final_artifacts_capture.records
        or post_write_artifacts_capture.identities
        != final_artifacts_capture.identities
    ):
        raise M0Error("Chrome Wasm artifacts changed while writing attestation")
    verify_written_attestation(written)
    return attestation, written.path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build one fresh chrome_wasm output from a clean checkout and "
            "write a non-release M9 local attestation."
        )
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    try:
        attestation, destination = run_clean_build_attestation(args.out_dir)
        result = {"attestation": attestation, "path": str(destination)}
        print(RESULT_PREFIX + _canonical_json_text(result), flush=True)
        print(PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError) as exc:
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

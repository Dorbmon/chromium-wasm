#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the non-release M9 clean-build attestation."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from tools.wasm import m0_common
from tools.wasm import run_m9_clean_build_attestation as attestation


descriptor_snapshot = sys.modules[attestation.hash_regular_file.__module__]


CHECKOUT = {"commit": "a" * 40, "tree": "b" * 40}
VERSIONS = {
    "chromium": "c" * 40,
    "emscripten": "d" * 40,
    "rust": "e" * 40,
    "v8": "f" * 40,
}
MANIFEST_IDENTITY = {
    "path": "tools/wasm/toolchain_manifest.json",
    "schema_version": 1,
    "sha256": "1" * 64,
    "versions": VERSIONS,
}


def manifest_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "chromium": {"revision": VERSIONS["chromium"]},
        "emscripten": {"source_revision": VERSIONS["emscripten"]},
        "git_dependencies": {"v8": {"revision": VERSIONS["v8"]}},
        "m6_chrome_gn_args": [
            'target_os = "emscripten"',
            'target_cpu = "wasm"',
            "enable_chromium_wasm_chrome = true",
        ],
        "rust": {"source_revision": VERSIONS["rust"]},
        "test262": {
            "path": m0_common.TEST262_CHECKOUT_PATH.as_posix(),
            "deps_path": m0_common.TEST262_DEPS_PATH,
            "remote": m0_common.TEST262_REMOTE,
            "revision": "0" * 40,
            "license_path": m0_common.TEST262_LICENSE_PATH.as_posix(),
            "license_size_bytes": 1,
            "license_sha256": "1" * 64,
        },
    }


def artifact_records() -> dict[str, dict[str, object]]:
    return {
        "chrome_wasm.js": {"bytes": 17, "sha256": "2" * 64},
        "chrome_wasm.wasm": {"bytes": 31, "sha256": "3" * 64},
    }


def gn_args_record() -> dict[str, object]:
    return {
        "bytes": 83,
        "manifest_key": attestation.GN_ARGS_MANIFEST_KEY,
        "sha256": "4" * 64,
    }


def file_identity(marker: int = 1) -> attestation._FileIdentity:
    return attestation._FileIdentity(
        device=marker,
        inode=marker + 1,
        mode=0o100644,
        size=marker + 2,
        modification_time_ns=marker + 3,
        change_time_ns=marker + 4,
    )


def directory_identity(marker: int = 1) -> attestation._DirectoryIdentity:
    return attestation._DirectoryIdentity(
        device=marker,
        inode=marker + 1,
        mode=0o40755,
    )


def manifest_capture(marker: int = 1) -> attestation._ManifestCapture:
    return attestation._ManifestCapture(
        manifest=manifest_data(),
        record=MANIFEST_IDENTITY,
        identity=file_identity(marker),
    )


def module_artifacts_capture(
    records: dict[str, dict[str, object]], marker: int = 1
) -> attestation._ModuleArtifactsCapture:
    return attestation._ModuleArtifactsCapture(
        records=records,
        identities={
            "chrome_wasm.js": file_identity(marker),
            "chrome_wasm.wasm": file_identity(marker + 10),
        },
        output_directory_identity=directory_identity(marker + 20),
    )


class CleanBuildOutputDirectoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "checkout"
        (self.root / "out").mkdir(parents=True)
        self.root_patch = mock.patch.object(attestation, "REPO_ROOT", self.root)
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temporary_directory.cleanup()

    def test_accepts_a_new_descendant_and_rejects_unsafe_locations(self) -> None:
        expected = self.root / "out" / "fresh" / "chrome"
        self.assertEqual(expected, attestation.resolve_new_output_dir(Path("out/fresh/chrome")))
        self.assertEqual(expected, attestation.resolve_new_output_dir(expected))

        invalid = (
            self.root / "out",
            self.root / "elsewhere",
            self.root / "out" / ".." / "escape",
        )
        for output in invalid:
            with self.subTest(output=output), self.assertRaises(attestation.M0Error):
                attestation.resolve_new_output_dir(output)

    def test_rejects_existing_file_directory_and_link_components(self) -> None:
        existing_file = self.root / "out" / "existing-file"
        existing_file.write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(attestation.M0Error, "new and nonexistent"):
            attestation.resolve_new_output_dir(existing_file)

        existing_directory = self.root / "out" / "existing-directory"
        existing_directory.mkdir()
        with self.assertRaisesRegex(attestation.M0Error, "new and nonexistent"):
            attestation.resolve_new_output_dir(existing_directory)

        linked_parent = self.root / "out" / "linked"
        linked_parent.symlink_to(self.root / "out", target_is_directory=True)
        with self.assertRaisesRegex(attestation.M0Error, "real directory"):
            attestation.resolve_new_output_dir(linked_parent / "fresh")

        dangling = self.root / "out" / "dangling"
        dangling.symlink_to(self.root / "not-present")
        with self.assertRaisesRegex(attestation.M0Error, "new and nonexistent"):
            attestation.resolve_new_output_dir(dangling)


class CleanBuildIdentityTest(unittest.TestCase):
    def test_dirty_or_untracked_status_fails_closed(self) -> None:
        dirty = subprocess.CompletedProcess(
            ["git", "status"], 0, " M chrome/browser/example.cc\0?? loose-file\0", ""
        )
        with mock.patch.object(attestation, "run_required_command", return_value=dirty):
            with self.assertRaisesRegex(attestation.M0Error, "dirty or untracked"):
                attestation.require_clean_top_level_checkout()

    def test_clean_status_requires_successful_git_command(self) -> None:
        failed = subprocess.CompletedProcess(["git", "status"], 1, "", "git failed")
        with mock.patch.object(
            attestation, "_run_bounded_command", return_value=failed
        ):
            with self.assertRaisesRegex(attestation.M0Error, "top-level Git status failed"):
                attestation.require_clean_top_level_checkout()

    def test_checkout_identity_requires_checkout_root_and_hashes(self) -> None:
        root = attestation.REPO_ROOT.resolve()
        outputs = iter((str(root), CHECKOUT["commit"], CHECKOUT["tree"]))
        with mock.patch.object(attestation, "_git_output", side_effect=outputs):
            self.assertEqual(CHECKOUT, attestation.checkout_identity())

        wrong_root = iter((str(root.parent), CHECKOUT["commit"], CHECKOUT["tree"]))
        with mock.patch.object(attestation, "_git_output", side_effect=wrong_root):
            with self.assertRaisesRegex(attestation.M0Error, "checkout root"):
                attestation.checkout_identity()

        malformed = iter((str(root), "not-a-commit", CHECKOUT["tree"]))
        with mock.patch.object(attestation, "_git_output", side_effect=malformed):
            with self.assertRaisesRegex(attestation.M0Error, "commit identity"):
                attestation.checkout_identity()

    def test_manifest_versions_reject_incomplete_or_non_hash_values(self) -> None:
        self.assertEqual(VERSIONS, attestation._manifest_versions(manifest_data()))
        missing = manifest_data()
        del missing["rust"]
        with self.assertRaisesRegex(attestation.M0Error, "lacks"):
            attestation._manifest_versions(missing)
        malformed = manifest_data()
        emscripten = malformed["emscripten"]
        assert isinstance(emscripten, dict)
        emscripten["source_revision"] = "bad"
        with self.assertRaisesRegex(attestation.M0Error, "invalid"):
            attestation._manifest_versions(malformed)


class CleanBuildCommandTest(unittest.TestCase):
    def _command(self, program: str) -> list[str]:
        return [sys.executable, "-c", program]

    def _bounded(
        self, program: str, *, timeout: float = 2.0
    ) -> subprocess.CompletedProcess[str]:
        return attestation._run_bounded_command(
            self._command(program), "test command", timeout
        )

    def test_bounded_command_returns_text_completed_process(self) -> None:
        result = self._bounded(
            "import sys; print('stdout'); print('stderr', file=sys.stderr)"
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("stdout\n", result.stdout)
        self.assertEqual("stderr\n", result.stderr)

    def test_required_command_keeps_nonzero_diagnostic_contract(self) -> None:
        command = self._command(
            "import sys; print('stdout'); print('stderr', file=sys.stderr); raise SystemExit(7)"
        )
        with self.assertRaisesRegex(
            attestation.M0Error, "test command failed \\(7\\).*stdout.*stderr"
        ):
            attestation.run_required_command(command, "test command", timeout_seconds=2)

    def test_command_output_cap_is_raw_shared_bytes_and_drains_after_overflow(
        self,
    ) -> None:
        program = "import sys; sys.stdout.buffer.write(b'a' * 8192); sys.stdout.flush()"
        with mock.patch.object(attestation, "MAX_COMMAND_OUTPUT_BYTES", 32):
            started = time.monotonic()
            with self.assertRaisesRegex(
                attestation.M0Error, "output exceeds the configured byte bound"
            ):
                self._bounded(program)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_command_output_cap_is_shared_across_stdout_and_stderr(self) -> None:
        program = (
            "import sys; "
            "sys.stdout.buffer.write(b'a' * 20); sys.stdout.flush(); "
            "sys.stderr.buffer.write(b'b' * 20); sys.stderr.flush()"
        )
        with mock.patch.object(attestation, "MAX_COMMAND_OUTPUT_BYTES", 32):
            with self.assertRaisesRegex(
                attestation.M0Error, "output exceeds the configured byte bound"
            ):
                self._bounded(program)

    def test_overflow_reason_survives_command_cleanup_failure(self) -> None:
        program = "import sys; sys.stdout.buffer.write(b'a' * 8192); sys.stdout.flush()"
        real_stop = attestation._stop_command_group
        stop_attempts = 0

        def fail_once_then_stop(
            process: subprocess.Popen[bytes], threads: object
        ) -> bool:
            nonlocal stop_attempts
            stop_attempts += 1
            if stop_attempts == 1:
                raise attestation.M0Error("cleanup failed")
            return real_stop(process, threads)

        with mock.patch.object(attestation, "MAX_COMMAND_OUTPUT_BYTES", 32), mock.patch.object(
            attestation,
            "_stop_command_group",
            side_effect=fail_once_then_stop,
        ):
            with self.assertRaisesRegex(
                attestation.M0Error,
                "output exceeds the configured byte bound; command cleanup could not be fully verified",
            ) as raised:
                self._bounded(program)
        self.assertIsInstance(raised.exception.__cause__, attestation.M0Error)
        self.assertEqual("cleanup failed", str(raised.exception.__cause__))
        self.assertEqual(2, stop_attempts)

    def test_quiet_command_timeout_stops_its_session(self) -> None:
        program = "import time; time.sleep(30)"
        with mock.patch.object(attestation, "COMMAND_COOPERATIVE_STOP_SECONDS", 0.1), mock.patch.object(
            attestation, "COMMAND_FORCED_STOP_SECONDS", 0.1
        ):
            started = time.monotonic()
            with self.assertRaisesRegex(attestation.M0Error, "command timeout"):
                self._bounded(program, timeout=0.1)
        self.assertLess(time.monotonic() - started, 2.0)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_reaped_leader_descendant_cannot_return_success(self) -> None:
        # The leader exits immediately after spawning a same-session child.
        # The child owns no inherited pipe, so success requires killpg(0), not
        # merely leader wait()/reader EOF.
        program = "import subprocess; subprocess.Popen(['sleep', '30'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
        with mock.patch.object(attestation, "COMMAND_COOPERATIVE_STOP_SECONDS", 0.1), mock.patch.object(
            attestation, "COMMAND_FORCED_STOP_SECONDS", 0.1
        ):
            with self.assertRaisesRegex(
                attestation.M0Error, "process group did not exit after leader completion"
            ):
                self._bounded(program, timeout=1.0)

    def test_partial_reader_start_keeps_started_reader_for_cleanup(self) -> None:
        started_threads: list[threading.Thread] = []
        real_thread = threading.Thread
        created_threads = 0

        def thread_factory(*args: object, **kwargs: object) -> threading.Thread:
            nonlocal created_threads
            thread = real_thread(*args, **kwargs)
            original_start = thread.start
            created_threads += 1
            if created_threads == 1:
                def record_start() -> None:
                    original_start()
                    started_threads.append(thread)
                thread.start = record_start  # type: ignore[method-assign]
            else:
                def fail_start() -> None:
                    raise RuntimeError("stderr reader start failed")
                thread.start = fail_start  # type: ignore[method-assign]
            return thread

        with mock.patch.object(attestation.threading, "Thread", side_effect=thread_factory):
            with self.assertRaisesRegex(RuntimeError, "stderr reader start failed"):
                self._bounded("import time; time.sleep(30)")
        self.assertEqual(1, len(started_threads))
        self.assertFalse(started_threads[0].is_alive())


class CleanBuildArtifactTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_hashes_regular_nonempty_file_and_rejects_unsafe_inputs(self) -> None:
        artifact = self.directory / "artifact.wasm"
        artifact.write_bytes(b"wasm-bytes")
        self.assertEqual(
            {
                "bytes": len(b"wasm-bytes"),
                "sha256": hashlib.sha256(b"wasm-bytes").hexdigest(),
            },
            attestation.stable_file_record(artifact, "test artifact"),
        )

        empty = self.directory / "empty.wasm"
        empty.touch()
        with self.assertRaisesRegex(attestation.M0Error, "snapshot is invalid"):
            attestation.stable_file_record(empty, "empty artifact")

        linked = self.directory / "linked.wasm"
        linked.symlink_to(artifact)
        with self.assertRaisesRegex(attestation.M0Error, "opened safely"):
            attestation.stable_file_record(linked, "linked artifact")

    def test_descriptor_stable_reads_reject_fifo_and_symlink(self) -> None:
        if not hasattr(os, "mkfifo") or not hasattr(os, "symlink"):
            self.skipTest("host lacks FIFO or symbolic-link support")
        fifo = self.directory / "artifact.fifo"
        os.mkfifo(fifo)
        target = self.directory / "target.wasm"
        target.write_bytes(b"trusted artifact")
        linked = self.directory / "linked.wasm"
        linked.symlink_to(target)

        for unsafe_path in (fifo, linked):
            with self.subTest(path=unsafe_path):
                with self.assertRaises(attestation.M0Error):
                    attestation.stable_file_record(unsafe_path, "unsafe artifact")
                with self.assertRaises(attestation.M0Error):
                    attestation._read_stable_file(
                        unsafe_path,
                        "unsafe generated GN args",
                        maximum_bytes=1024,
                    )

    def test_stable_hash_rejects_same_inode_mutate_restore_while_reading(
        self,
    ) -> None:
        artifact = self.directory / "artifact.wasm"
        contents = b"a" * (descriptor_snapshot._READ_CHUNK_BYTES + 1)
        artifact.write_bytes(contents)
        original_read = descriptor_snapshot.os.read
        changed = False

        def read_then_mutate(descriptor: int, size: int) -> bytes:
            nonlocal changed
            chunk = original_read(descriptor, size)
            if chunk and not changed:
                changed = True
                before = artifact.stat()
                time.sleep(0.01)
                artifact.write_bytes(b"b" * len(contents))
                artifact.write_bytes(contents)
                os.utime(
                    artifact,
                    ns=(before.st_atime_ns, before.st_mtime_ns),
                )
                after = artifact.stat()
                self.assertEqual(before.st_ino, after.st_ino)
                self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
                self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
            return chunk

        with mock.patch.object(
            descriptor_snapshot.os, "read", side_effect=read_then_mutate
        ):
            with self.assertRaisesRegex(attestation.M0Error, "changed while it was read"):
                attestation.stable_file_record(artifact, "test artifact")
        self.assertTrue(changed)

    def test_module_artifact_capture_retains_the_descriptor_pinned_root(self) -> None:
        out_dir = self.directory / "out"
        out_dir.mkdir()
        loader = out_dir / "chrome_wasm.js"
        module = out_dir / "chrome_wasm.wasm"
        loader.write_bytes(b"loader")
        module.write_bytes(b"module")
        capture = attestation._capture_module_artifacts(out_dir)

        metadata = out_dir.stat()
        self.assertEqual(
            attestation._DirectoryIdentity(
                device=metadata.st_dev,
                inode=metadata.st_ino,
                mode=metadata.st_mode,
            ),
            capture.output_directory_identity,
        )
        self.assertEqual(
            hashlib.sha256(b"loader").hexdigest(),
            capture.records["chrome_wasm.js"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(b"module").hexdigest(),
            capture.records["chrome_wasm.wasm"]["sha256"],
        )

    def test_module_artifact_records_reject_leaf_swap_before_group_revalidation(
        self,
    ) -> None:
        for name in ("chrome_wasm.js", "chrome_wasm.wasm"):
            with self.subTest(name=name):
                out_dir = self.directory / name
                out_dir.mkdir()
                selected = out_dir / name
                selected.write_bytes(b"selected")
                (out_dir / "chrome_wasm.js").touch(exist_ok=True)
                (out_dir / "chrome_wasm.wasm").touch(exist_ok=True)
                if name == "chrome_wasm.js":
                    (out_dir / "chrome_wasm.wasm").write_bytes(b"module")
                else:
                    (out_dir / "chrome_wasm.js").write_bytes(b"loader")
                original_hash = attestation._hash_regular_file_from_root
                replaced = False

                def hash_then_replace(*args: object, **kwargs: object) -> object:
                    nonlocal replaced
                    capture = original_hash(*args, **kwargs)
                    if not replaced and args[1] == name:
                        replaced = True
                        selected.unlink()
                        selected.write_bytes(b"replacement")
                    return capture

                with mock.patch.object(
                    attestation,
                    "_hash_regular_file_from_root",
                    side_effect=hash_then_replace,
                ):
                    with self.assertRaisesRegex(
                        attestation.M0Error, "changed while snapshotting"
                    ):
                        attestation.module_artifact_records(out_dir)
                self.assertTrue(replaced)

    def test_module_artifact_capture_rejects_output_directory_swap(self) -> None:
        out_dir = self.directory / "out"
        out_dir.mkdir()
        out_dir.joinpath("chrome_wasm.js").write_bytes(b"loader")
        out_dir.joinpath("chrome_wasm.wasm").write_bytes(b"module")
        retained = self.directory / "retained-output"
        original_hash = attestation._hash_regular_file_from_root
        swapped = False

        def hash_then_swap(*args: object, **kwargs: object) -> object:
            nonlocal swapped
            capture = original_hash(*args, **kwargs)
            if not swapped:
                swapped = True
                out_dir.rename(retained)
                out_dir.mkdir()
                out_dir.joinpath("chrome_wasm.js").write_bytes(b"replacement loader")
                out_dir.joinpath("chrome_wasm.wasm").write_bytes(b"replacement module")
            return capture

        with mock.patch.object(
            attestation,
            "_hash_regular_file_from_root",
            side_effect=hash_then_swap,
        ):
            with self.assertRaisesRegex(
                attestation.M0Error, "output directory changed while snapshotting"
            ):
                attestation._capture_module_artifacts(out_dir)
        self.assertTrue(swapped)

    def test_exact_gn_args_are_required_before_and_after_build(self) -> None:
        expected = b"is_debug = false\n"
        out_dir = self.directory / "out"
        out_dir.mkdir()
        (out_dir / "args.gn").write_bytes(expected)
        self.assertEqual(
            {
                "bytes": len(expected),
                "manifest_key": attestation.GN_ARGS_MANIFEST_KEY,
                "sha256": hashlib.sha256(expected).hexdigest(),
            },
            attestation.require_exact_generated_gn_args(out_dir, expected),
        )
        (out_dir / "args.gn").write_bytes(b"is_debug = true\n")
        with self.assertRaisesRegex(attestation.M0Error, "exactly match"):
            attestation.require_exact_generated_gn_args(out_dir, expected)

    def test_expected_m6_arguments_use_the_dedicated_manifest_key(self) -> None:
        expected = attestation.expected_m6_chrome_gn_args(manifest_data())
        self.assertEqual(
            b'target_os = "emscripten"\n'
            b'target_cpu = "wasm"\n'
            b"enable_chromium_wasm_chrome = true\n",
            expected,
        )
        broken = manifest_data()
        del broken["m6_chrome_gn_args"]
        with self.assertRaisesRegex(attestation.M0Error, "arguments are invalid"):
            attestation.expected_m6_chrome_gn_args(broken)


class CleanBuildManifestSnapshotTest(unittest.TestCase):
    def test_parses_captured_bytes_without_pathname_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest_path = Path(temporary_directory) / "toolchain_manifest.json"
            expected_manifest = manifest_data()
            contents = attestation._canonical_json_bytes(expected_manifest)
            manifest_path.write_bytes(contents)

            with (
                mock.patch.object(
                    attestation, "_manifest_path", return_value=manifest_path
                ),
                mock.patch.object(
                    Path,
                    "open",
                    side_effect=AssertionError("manifest must not be pathname-reopened"),
                ),
            ):
                manifest, identity = attestation.load_manifest_snapshot()

        self.assertEqual(expected_manifest, manifest)
        self.assertEqual(
            {
                "path": attestation.MANIFEST_RELATIVE_PATH,
                "schema_version": 1,
                "sha256": hashlib.sha256(contents).hexdigest(),
                "versions": VERSIONS,
            },
            identity,
        )


class CleanBuildAttestationSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "checkout"
        self.out_dir = self.root / "out" / "fresh"
        self.out_dir.mkdir(parents=True)
        self.root_patch = mock.patch.object(attestation, "REPO_ROOT", self.root)
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temporary_directory.cleanup()

    def _record(self) -> dict[str, object]:
        return attestation.make_attestation(
            checkout=CHECKOUT,
            manifest=MANIFEST_IDENTITY,
            gn_args=gn_args_record(),
            artifacts=artifact_records(),
            out_dir=self.out_dir,
        )

    def _write_module_artifacts(self, out_dir: Path) -> None:
        out_dir.joinpath("chrome_wasm.js").write_bytes(b"loader")
        out_dir.joinpath("chrome_wasm.wasm").write_bytes(b"module")

    def test_canonical_record_binds_tree_manifest_args_and_module_hashes(self) -> None:
        record = attestation.make_attestation(
            checkout=CHECKOUT,
            manifest=MANIFEST_IDENTITY,
            gn_args=gn_args_record(),
            artifacts=artifact_records(),
            out_dir=self.out_dir,
        )
        self.assertEqual(attestation.SCHEMA_VERSION, record["schema_version"])
        self.assertEqual("not_a_release", record["release_status"])
        self.assertFalse(record["m9_gate_complete"])
        self.assertEqual(CHECKOUT, record["checkout"])
        self.assertEqual(MANIFEST_IDENTITY, record["toolchain_manifest"])
        self.assertEqual(gn_args_record(), record["gn"]["args"])
        self.assertEqual(artifact_records(), record["artifacts"])
        self.assertEqual("out/fresh", record["output_directory"])

        encoded = attestation._canonical_json_bytes(record)
        self.assertEqual(encoded, attestation._canonical_json_bytes(record))
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertNotIn(b"releasable", encoded)

    def test_schema_rejects_extra_or_invalid_binding_fields(self) -> None:
        invalid_manifest = {**MANIFEST_IDENTITY, "extra": "not allowed"}
        with self.assertRaisesRegex(attestation.M0Error, "manifest identity"):
            attestation.make_attestation(
                checkout=CHECKOUT,
                manifest=invalid_manifest,
                gn_args=gn_args_record(),
                artifacts=artifact_records(),
                out_dir=self.out_dir,
            )

        invalid_artifacts = artifact_records()
        invalid_artifacts["chrome_wasm.data"] = {"bytes": 1, "sha256": "5" * 64}
        with self.assertRaisesRegex(attestation.M0Error, "module artifacts"):
            attestation.make_attestation(
                checkout=CHECKOUT,
                manifest=MANIFEST_IDENTITY,
                gn_args=gn_args_record(),
                artifacts=invalid_artifacts,
                out_dir=self.out_dir,
            )

    def test_write_is_canonical_and_never_replaces_an_existing_record(self) -> None:
        record = self._record()
        written = attestation.write_attestation(self.out_dir, record)
        self.assertEqual(
            attestation._canonical_json_bytes(record), written.path.read_bytes()
        )
        output_metadata = self.out_dir.stat()
        self.assertEqual(
            attestation._DirectoryIdentity(
                device=output_metadata.st_dev,
                inode=output_metadata.st_ino,
                mode=output_metadata.st_mode,
            ),
            written.output_directory_identity,
        )
        attestation.verify_written_attestation(written)
        with self.assertRaisesRegex(attestation.M0Error, "already exists"):
            attestation.write_attestation(self.out_dir, record)

    def test_writer_uses_descriptor_create_and_readback_without_pathname_open(
        self,
    ) -> None:
        record = self._record()
        original_open = os.open
        opens: list[tuple[object, int, int | None]] = []

        def traced_open(
            path: object,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            opens.append((path, flags, dir_fd))
            if dir_fd is None:
                return original_open(path, flags, mode)
            return original_open(path, flags, mode, dir_fd=dir_fd)

        with (
            mock.patch.object(
                Path,
                "open",
                side_effect=AssertionError("attestation must not use pathname open"),
            ),
            mock.patch.object(attestation, "_require_dir_fd_support"),
            mock.patch.object(attestation.os, "open", side_effect=traced_open),
        ):
            written = attestation.write_attestation(self.out_dir, record)
            attestation.verify_written_attestation(written)
        creation = [
            call
            for call in opens
            if call[0] == attestation.ATTESTATION_FILENAME and call[1] & os.O_CREAT
        ]
        self.assertEqual(1, len(creation))
        _, flags, directory_descriptor = creation[0]
        self.assertIsNotNone(directory_descriptor)
        self.assertTrue(flags & os.O_CREAT)
        self.assertTrue(flags & os.O_EXCL)
        self.assertTrue(flags & os.O_NOFOLLOW)
        self.assertEqual(
            attestation._canonical_json_bytes(record), written.contents
        )

    def test_writer_rejects_output_directory_swap_from_artifact_capture(self) -> None:
        self._write_module_artifacts(self.out_dir)
        capture = attestation._capture_module_artifacts(self.out_dir)
        retained = self.root / "retained-output"
        self.out_dir.rename(retained)
        self.out_dir.mkdir()
        self._write_module_artifacts(self.out_dir)

        with self.assertRaisesRegex(
            attestation.M0Error, "output directory changed before record creation"
        ):
            attestation.write_attestation(
                self.out_dir,
                self._record(),
                expected_output_directory_identity=(
                    capture.output_directory_identity
                ),
            )
        self.assertFalse((self.out_dir / attestation.ATTESTATION_FILENAME).exists())
        self.assertFalse((retained / attestation.ATTESTATION_FILENAME).exists())

    def test_writer_rejects_parent_directory_swap_from_artifact_capture(self) -> None:
        self._write_module_artifacts(self.out_dir)
        capture = attestation._capture_module_artifacts(self.out_dir)
        output_parent = self.root / "out"
        retained_parent = self.root / "retained-out"
        output_parent.rename(retained_parent)
        self.out_dir.parent.mkdir()
        self.out_dir.mkdir()
        self._write_module_artifacts(self.out_dir)

        with self.assertRaisesRegex(
            attestation.M0Error, "output directory changed before record creation"
        ):
            attestation.write_attestation(
                self.out_dir,
                self._record(),
                expected_output_directory_identity=(
                    capture.output_directory_identity
                ),
            )
        self.assertFalse((self.out_dir / attestation.ATTESTATION_FILENAME).exists())
        self.assertFalse(
            (retained_parent / "fresh" / attestation.ATTESTATION_FILENAME).exists()
        )

    def test_writer_rejects_existing_symlink_or_fifo_leaf(self) -> None:
        target = self.root / "outside-record"
        target.write_bytes(b"outside")
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind):
                destination = self.out_dir / attestation.ATTESTATION_FILENAME
                if kind == "symlink":
                    destination.symlink_to(target)
                else:
                    if not hasattr(os, "mkfifo"):
                        self.skipTest("host lacks FIFO support")
                    os.mkfifo(destination)
                with self.assertRaisesRegex(attestation.M0Error, "already exists"):
                    attestation.write_attestation(self.out_dir, self._record())
                self.assertTrue(os.path.lexists(destination))
                if kind == "symlink":
                    self.assertEqual(b"outside", target.read_bytes())
                destination.unlink()

    def test_post_write_identity_rejects_and_preserves_a_replacement(self) -> None:
        record = self._record()
        written = attestation.write_attestation(self.out_dir, record)
        written.path.unlink()
        written.path.write_bytes(b"replacement record")
        with self.assertRaisesRegex(attestation.M0Error, "changed after"):
            attestation.verify_written_attestation(written)
        self.assertEqual(b"replacement record", written.path.read_bytes())
        self.assertFalse(
            hasattr(attestation, "remove_written_attestation_if_unchanged")
        )

    def test_post_write_identity_rejects_same_inode_mutate_restore(self) -> None:
        record = self._record()
        written = attestation.write_attestation(self.out_dir, record)
        before = written.path.stat()
        time.sleep(0.01)
        written.path.write_bytes(b"x" * len(written.contents))
        written.path.write_bytes(written.contents)
        os.utime(
            written.path,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )
        after = written.path.stat()

        self.assertEqual(before.st_ino, after.st_ino)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
        self.assertEqual(written.contents, written.path.read_bytes())
        self.assertEqual(before.st_ctime_ns, written.identity.change_time_ns)
        with self.assertRaisesRegex(attestation.M0Error, "changed after"):
            attestation.verify_written_attestation(written)

    def test_verify_rejects_output_or_parent_directory_replacement(self) -> None:
        for kind in ("output", "parent"):
            with self.subTest(kind=kind):
                temporary_directory = tempfile.TemporaryDirectory()
                self.addCleanup(temporary_directory.cleanup)
                root = Path(temporary_directory.name) / "checkout"
                out_dir = root / "out" / "fresh"
                out_dir.mkdir(parents=True)
                with mock.patch.object(attestation, "REPO_ROOT", root):
                    record = attestation.make_attestation(
                        checkout=CHECKOUT,
                        manifest=MANIFEST_IDENTITY,
                        gn_args=gn_args_record(),
                        artifacts=artifact_records(),
                        out_dir=out_dir,
                    )
                    written = attestation.write_attestation(out_dir, record)
                    if kind == "output":
                        out_dir.rename(root / "retained-output")
                        out_dir.mkdir()
                    else:
                        out_dir.parent.rename(root / "retained-parent")
                        out_dir.parent.mkdir()
                        out_dir.mkdir()
                    (out_dir / attestation.ATTESTATION_FILENAME).write_bytes(
                        written.contents
                    )
                    with self.assertRaisesRegex(attestation.M0Error, "changed after"):
                        attestation.verify_written_attestation(written)

    def test_verify_rejects_symlink_or_fifo_leaf_replacement(self) -> None:
        target = self.root / "outside-record"
        target.write_bytes(b"outside")
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind):
                written = attestation.write_attestation(self.out_dir, self._record())
                written.path.unlink()
                if kind == "symlink":
                    written.path.symlink_to(target)
                else:
                    if not hasattr(os, "mkfifo"):
                        self.skipTest("host lacks FIFO support")
                    os.mkfifo(written.path)
                with self.assertRaisesRegex(attestation.M0Error, "changed after"):
                    attestation.verify_written_attestation(written)
                self.assertTrue(os.path.lexists(written.path))
                written.path.unlink()


class CleanBuildWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "checkout"
        (self.root / "out").mkdir(parents=True)
        self.gn = self.root / "buildtools/linux64/gn"
        self.autoninja = self.root / "third_party/depot_tools/autoninja"
        for executable in (self.gn, self.autoninja):
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
        self.root_patch = mock.patch.object(attestation, "REPO_ROOT", self.root)
        self.root_patch.start()
        self.out_dir = self.root / "out" / "fresh"
        self.expected_args = attestation.expected_m6_chrome_gn_args(manifest_data())

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temporary_directory.cleanup()

    def _command_runner(
        self, commands: list[tuple[list[str], str]], *, generated_args: bytes | None = None
    ):
        selected_args = self.expected_args if generated_args is None else generated_args

        def run(command: list[str], description: str) -> subprocess.CompletedProcess[str]:
            commands.append((list(command), description))
            if command == attestation._bootstrap_command():
                return subprocess.CompletedProcess(command, 0, attestation.BOOTSTRAP_MARKER + "\n", "")
            if command[:2] == [str(self.gn), "gen"]:
                output = Path(command[2])
                output.mkdir(parents=True)
                output.joinpath("args.gn").write_bytes(selected_args)
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[:1] == [str(self.autoninja)]:
                output = Path(command[2])
                output.joinpath("chrome_wasm.js").write_bytes(b"loader output")
                output.joinpath("chrome_wasm.wasm").write_bytes(b"wasm output")
                return subprocess.CompletedProcess(command, 0, "", "")
            self.fail(f"unexpected command: {command}")

        return run

    def _workflow_patches(self, command_runner):
        return contextlib.ExitStack(), {
            "run_required_command": mock.patch.object(
                attestation, "run_required_command", side_effect=command_runner
            ),
            "require_clean_top_level_checkout": mock.patch.object(
                attestation, "require_clean_top_level_checkout"
            ),
            "checkout_identity": mock.patch.object(
                attestation, "checkout_identity", return_value=CHECKOUT
            ),
            "_load_manifest_capture": mock.patch.object(
                attestation,
                "_load_manifest_capture",
                side_effect=[
                    manifest_capture(),
                    manifest_capture(),
                    manifest_capture(),
                ],
            ),
            "check_boundary": mock.patch.object(attestation, "check_boundary"),
        }

    def _write_live_manifest(self) -> Path:
        manifest_path = self.root / attestation.MANIFEST_RELATIVE_PATH
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(attestation._canonical_json_bytes(manifest_data()))
        return manifest_path

    def _mutate_same_inode_restore(self, path: Path) -> None:
        original = path.read_bytes()
        before = path.stat()
        time.sleep(0.01)
        path.write_bytes(b"x" * len(original))
        path.write_bytes(original)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = path.stat()
        self.assertEqual(before.st_ino, after.st_ino)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
        self.assertEqual(original, path.read_bytes())

    def test_workflow_runs_exact_bounded_commands_and_writes_binding(self) -> None:
        commands: list[tuple[list[str], str]] = []
        command_runner = self._command_runner(commands)
        stack, patches = self._workflow_patches(command_runner)
        with stack:
            active = {name: stack.enter_context(patch) for name, patch in patches.items()}
            record, destination = attestation.run_clean_build_attestation(self.out_dir)

        self.assertEqual(3, len(commands))
        self.assertEqual(
            [
                sys.executable,
                str(self.root / "tools/wasm/bootstrap.py"),
                "--profile",
                "m3",
                "--verify-only",
            ],
            commands[0][0],
        )
        self.assertEqual(
            [str(self.gn), "gen", str(self.out_dir), "--args=" + self.expected_args.decode("utf-8")],
            commands[1][0],
        )
        self.assertEqual(
            [str(self.autoninja), "-C", str(self.out_dir), "chrome_wasm"],
            commands[2][0],
        )
        active["check_boundary"].assert_called_once_with(self.out_dir)
        self.assertEqual(3, active["require_clean_top_level_checkout"].call_count)
        self.assertEqual(3, active["checkout_identity"].call_count)
        self.assertEqual(3, active["_load_manifest_capture"].call_count)
        self.assertEqual(
            attestation._canonical_json_bytes(record), destination.read_bytes()
        )
        self.assertEqual(
            hashlib.sha256(b"loader output").hexdigest(),
            record["artifacts"]["chrome_wasm.js"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(b"wasm output").hexdigest(),
            record["artifacts"]["chrome_wasm.wasm"]["sha256"],
        )

    def test_dirty_preflight_runs_no_build_command_and_creates_no_output(self) -> None:
        commands: list[tuple[list[str], str]] = []
        with (
            mock.patch.object(
                attestation,
                "require_clean_top_level_checkout",
                side_effect=attestation.M0Error("dirty checkout"),
            ),
            mock.patch.object(
                attestation,
                "run_required_command",
                side_effect=self._command_runner(commands),
            ),
        ):
            with self.assertRaisesRegex(attestation.M0Error, "dirty checkout"):
                attestation.run_clean_build_attestation(self.out_dir)
        self.assertEqual([], commands)
        self.assertFalse(self.out_dir.exists())

    def test_existing_output_is_rejected_before_cleanliness_or_commands(self) -> None:
        self.out_dir.mkdir()
        commands: list[tuple[list[str], str]] = []
        with (
            mock.patch.object(attestation, "require_clean_top_level_checkout") as clean,
            mock.patch.object(
                attestation,
                "run_required_command",
                side_effect=self._command_runner(commands),
            ),
        ):
            with self.assertRaisesRegex(attestation.M0Error, "new and nonexistent"):
                attestation.run_clean_build_attestation(self.out_dir)
        clean.assert_not_called()
        self.assertEqual([], commands)

    def test_wrong_generated_args_stop_before_boundary_or_autoninja(self) -> None:
        commands: list[tuple[list[str], str]] = []
        wrong_args = self.expected_args.replace(b"true", b"false")
        command_runner = self._command_runner(commands, generated_args=wrong_args)
        stack, patches = self._workflow_patches(command_runner)
        with stack:
            active = {name: stack.enter_context(patch) for name, patch in patches.items()}
            with self.assertRaisesRegex(attestation.M0Error, "exactly match"):
                attestation.run_clean_build_attestation(self.out_dir)
        self.assertEqual(2, len(commands))
        active["check_boundary"].assert_not_called()
        self.assertFalse((self.out_dir / attestation.ATTESTATION_FILENAME).exists())

    def test_parent_symlink_swap_after_bootstrap_prevents_gn(self) -> None:
        parent = self.root / "out" / "parent"
        parent.mkdir()
        out_dir = parent / "fresh"
        replacement_parent = self.root / "replacement-parent"
        commands: list[tuple[list[str], str]] = []

        def swap_after_bootstrap(
            command: list[str], description: str
        ) -> subprocess.CompletedProcess[str]:
            commands.append((list(command), description))
            if command != attestation._bootstrap_command():
                self.fail(f"unexpected command: {command}")
            parent.rmdir()
            replacement_parent.mkdir()
            parent.symlink_to(replacement_parent, target_is_directory=True)
            return subprocess.CompletedProcess(
                command, 0, attestation.BOOTSTRAP_MARKER + "\n", ""
            )

        stack, patches = self._workflow_patches(swap_after_bootstrap)
        with stack:
            active = {
                name: stack.enter_context(patch) for name, patch in patches.items()
            }
            with self.assertRaisesRegex(attestation.M0Error, "real directory"):
                attestation.run_clean_build_attestation(out_dir)
        self.assertEqual(1, len(commands))
        active["check_boundary"].assert_not_called()
        self.assertFalse(
            (replacement_parent / "fresh" / attestation.ATTESTATION_FILENAME).exists()
        )

    def test_parent_symlink_swap_after_gn_stops_before_boundary_or_record(self) -> None:
        parent = self.root / "out" / "parent"
        parent.mkdir()
        out_dir = parent / "fresh"
        replacement_parent = self.root / "replacement-parent"
        commands: list[tuple[list[str], str]] = []

        def swap_after_gn(
            command: list[str], description: str
        ) -> subprocess.CompletedProcess[str]:
            commands.append((list(command), description))
            if command == attestation._bootstrap_command():
                return subprocess.CompletedProcess(
                    command, 0, attestation.BOOTSTRAP_MARKER + "\n", ""
                )
            if command[:2] == [str(self.gn), "gen"]:
                output = Path(command[2])
                output.mkdir()
                output.joinpath("args.gn").write_bytes(self.expected_args)
                output.joinpath("args.gn").unlink()
                output.rmdir()
                parent.rmdir()
                replacement_parent.mkdir()
                replacement_output = replacement_parent / "fresh"
                replacement_output.mkdir()
                replacement_output.joinpath("args.gn").write_bytes(
                    self.expected_args
                )
                parent.symlink_to(replacement_parent, target_is_directory=True)
                return subprocess.CompletedProcess(command, 0, "", "")
            self.fail(f"unexpected command: {command}")

        stack, patches = self._workflow_patches(swap_after_gn)
        with stack:
            active = {
                name: stack.enter_context(patch) for name, patch in patches.items()
            }
            with self.assertRaisesRegex(attestation.M0Error, "real directory"):
                attestation.run_clean_build_attestation(out_dir)
        self.assertEqual(2, len(commands))
        active["check_boundary"].assert_not_called()
        self.assertFalse(
            (replacement_parent / "fresh" / attestation.ATTESTATION_FILENAME).exists()
        )

    def test_post_build_dirty_state_refuses_to_write_record(self) -> None:
        commands: list[tuple[list[str], str]] = []
        command_runner = self._command_runner(commands)
        stack, patches = self._workflow_patches(command_runner)
        patches["require_clean_top_level_checkout"] = mock.patch.object(
            attestation,
            "require_clean_top_level_checkout",
            side_effect=[None, attestation.M0Error("source became dirty")],
        )
        with stack:
            active = {name: stack.enter_context(patch) for name, patch in patches.items()}
            with self.assertRaisesRegex(attestation.M0Error, "source became dirty"):
                attestation.run_clean_build_attestation(self.out_dir)
        self.assertEqual(3, len(commands))
        self.assertFalse((self.out_dir / attestation.ATTESTATION_FILENAME).exists())
        self.assertEqual(2, active["require_clean_top_level_checkout"].call_count)

    def test_identity_change_during_build_refuses_to_write_record(self) -> None:
        commands: list[tuple[list[str], str]] = []
        changed_checkout = {"commit": "9" * 40, "tree": "8" * 40}
        command_runner = self._command_runner(commands)
        stack, patches = self._workflow_patches(command_runner)
        patches["checkout_identity"] = mock.patch.object(
            attestation,
            "checkout_identity",
            side_effect=[CHECKOUT, changed_checkout],
        )
        with stack:
            for patch in patches.values():
                stack.enter_context(patch)
            with self.assertRaisesRegex(attestation.M0Error, "identity changed during"):
                attestation.run_clean_build_attestation(self.out_dir)
        self.assertFalse((self.out_dir / attestation.ATTESTATION_FILENAME).exists())

    def test_artifact_change_after_build_refuses_to_write_record(self) -> None:
        commands: list[tuple[list[str], str]] = []
        changed_artifacts = artifact_records()
        changed_artifacts["chrome_wasm.wasm"] = {
            "bytes": 32,
            "sha256": "6" * 64,
        }
        command_runner = self._command_runner(commands)
        stack, patches = self._workflow_patches(command_runner)
        patches["_capture_module_artifacts"] = mock.patch.object(
            attestation,
            "_capture_module_artifacts",
            side_effect=[
                module_artifacts_capture(artifact_records()),
                module_artifacts_capture(changed_artifacts),
            ],
        )
        with stack:
            for patch in patches.values():
                stack.enter_context(patch)
            with self.assertRaisesRegex(attestation.M0Error, "artifacts changed during"):
                attestation.run_clean_build_attestation(self.out_dir)
        self.assertEqual(3, len(commands))
        self.assertFalse((self.out_dir / attestation.ATTESTATION_FILENAME).exists())

    def test_post_write_validation_failure_leaves_record_without_cleanup(self) -> None:
        commands: list[tuple[list[str], str]] = []
        command_runner = self._command_runner(commands)
        stack, patches = self._workflow_patches(command_runner)
        patches["require_clean_top_level_checkout"] = mock.patch.object(
            attestation,
            "require_clean_top_level_checkout",
            side_effect=[None, None, attestation.M0Error("source became dirty")],
        )
        with stack:
            active = {
                name: stack.enter_context(patch) for name, patch in patches.items()
            }
            with self.assertRaisesRegex(attestation.M0Error, "source became dirty"):
                attestation.run_clean_build_attestation(self.out_dir)
        self.assertEqual(3, len(commands))
        self.assertEqual(3, active["require_clean_top_level_checkout"].call_count)
        retained = self.out_dir / attestation.ATTESTATION_FILENAME
        self.assertTrue(retained.is_file())
        self.assertTrue(retained.read_bytes())

    def test_post_write_rejects_same_inode_mutate_restore_for_every_input(self) -> None:
        manifest_path = self._write_live_manifest()
        for name, error in (
            ("manifest", "toolchain manifest changed while writing"),
            ("args.gn", "generated GN args changed while writing"),
            ("chrome_wasm.js", "Chrome Wasm artifacts changed while writing"),
            ("chrome_wasm.wasm", "Chrome Wasm artifacts changed while writing"),
        ):
            with self.subTest(name=name):
                out_dir = self.root / "out" / f"metadata-{name}"
                commands: list[tuple[list[str], str]] = []
                command_runner = self._command_runner(commands)
                real_write_attestation = attestation.write_attestation
                changed = False

                def write_then_mutate(
                    destination_dir: Path,
                    record: dict[str, object],
                    *,
                    expected_output_directory_identity: (
                        attestation._DirectoryIdentity | None
                    ) = None,
                ) -> attestation.WrittenAttestation:
                    nonlocal changed
                    written = real_write_attestation(
                        destination_dir,
                        record,
                        expected_output_directory_identity=(
                            expected_output_directory_identity
                        ),
                    )
                    path = (
                        manifest_path
                        if name == "manifest"
                        else destination_dir / name
                    )
                    self._mutate_same_inode_restore(path)
                    changed = True
                    return written

                with (
                    mock.patch.object(
                        attestation,
                        "run_required_command",
                        side_effect=command_runner,
                    ),
                    mock.patch.object(attestation, "require_clean_top_level_checkout"),
                    mock.patch.object(
                        attestation, "checkout_identity", return_value=CHECKOUT
                    ),
                    mock.patch.object(attestation, "check_boundary"),
                    mock.patch.object(
                        attestation,
                        "write_attestation",
                        side_effect=write_then_mutate,
                    ),
                ):
                    with self.assertRaisesRegex(attestation.M0Error, error):
                        attestation.run_clean_build_attestation(out_dir)
                self.assertTrue(changed)
                self.assertEqual(3, len(commands))

    def test_build_rejects_same_inode_mutate_restore_for_every_cross_phase_input(
        self,
    ) -> None:
        for name, error in (
            ("manifest", "toolchain manifest identity changed during"),
            ("args.gn", "generated GN args changed during"),
            ("chrome_wasm.js", "Chrome Wasm artifacts changed during"),
            ("chrome_wasm.wasm", "Chrome Wasm artifacts changed during"),
        ):
            with self.subTest(name=name):
                manifest_path = self._write_live_manifest()
                out_dir = self.root / "out" / f"build-metadata-{name}"
                commands: list[tuple[list[str], str]] = []
                base_runner = self._command_runner(commands)
                changed = False

                def run_then_mutate(
                    command: list[str], description: str
                ) -> subprocess.CompletedProcess[str]:
                    nonlocal changed
                    result = base_runner(command, description)
                    if (
                        not changed
                        and name in ("manifest", "args.gn")
                        and command[:1] == [str(self.autoninja)]
                    ):
                        self._mutate_same_inode_restore(
                            manifest_path if name == "manifest" else out_dir / name
                        )
                        changed = True
                    return result

                original_capture_artifacts = attestation._capture_module_artifacts
                artifact_capture_count = 0

                def capture_then_mutate(
                    captured_out_dir: Path,
                ) -> attestation._ModuleArtifactsCapture:
                    nonlocal artifact_capture_count, changed
                    capture = original_capture_artifacts(captured_out_dir)
                    artifact_capture_count += 1
                    if (
                        not changed
                        and name in ("chrome_wasm.js", "chrome_wasm.wasm")
                        and artifact_capture_count == 1
                    ):
                        self._mutate_same_inode_restore(captured_out_dir / name)
                        changed = True
                    return capture

                with (
                    mock.patch.object(
                        attestation,
                        "run_required_command",
                        side_effect=run_then_mutate,
                    ),
                    mock.patch.object(attestation, "require_clean_top_level_checkout"),
                    mock.patch.object(
                        attestation, "checkout_identity", return_value=CHECKOUT
                    ),
                    mock.patch.object(attestation, "check_boundary"),
                    mock.patch.object(
                        attestation,
                        "_capture_module_artifacts",
                        side_effect=capture_then_mutate,
                    ),
                ):
                    with self.assertRaisesRegex(attestation.M0Error, error):
                        attestation.run_clean_build_attestation(out_dir)
                self.assertTrue(changed)
                self.assertEqual(3, len(commands))
                self.assertFalse(
                    (out_dir / attestation.ATTESTATION_FILENAME).exists()
                )

    def test_main_emits_one_canonical_result_followed_by_one_pass_marker(self) -> None:
        record = attestation.make_attestation(
            checkout=CHECKOUT,
            manifest=MANIFEST_IDENTITY,
            gn_args=gn_args_record(),
            artifacts=artifact_records(),
            out_dir=self.root / "out",
        )
        destination = self.root / "out" / attestation.ATTESTATION_FILENAME
        with (
            mock.patch.object(
                attestation,
                "run_clean_build_attestation",
                return_value=(record, destination),
            ),
            mock.patch.object(sys, "argv", ["attestation"]),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            self.assertEqual(0, attestation.main())
        lines = stdout.getvalue().splitlines()
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[0].startswith(attestation.RESULT_PREFIX))
        self.assertEqual(attestation.PASS_MARKER, lines[1])

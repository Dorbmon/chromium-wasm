#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the non-release M9 clean-build attestation."""

from __future__ import annotations

import contextlib
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.wasm import run_m9_clean_build_attestation as attestation


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
        with mock.patch.object(attestation.subprocess, "run", return_value=failed):
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
        with self.assertRaisesRegex(attestation.M0Error, "must not be empty"):
            attestation.stable_file_record(empty, "empty artifact")

        linked = self.directory / "linked.wasm"
        linked.symlink_to(artifact)
        with self.assertRaisesRegex(attestation.M0Error, "non-symlink"):
            attestation.stable_file_record(linked, "linked artifact")

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
        record = attestation.make_attestation(
            checkout=CHECKOUT,
            manifest=MANIFEST_IDENTITY,
            gn_args=gn_args_record(),
            artifacts=artifact_records(),
            out_dir=self.out_dir,
        )
        written = attestation.write_attestation(self.out_dir, record)
        self.assertEqual(
            attestation._canonical_json_bytes(record), written.path.read_bytes()
        )
        attestation.verify_written_attestation(written)
        with self.assertRaisesRegex(attestation.M0Error, "already exists"):
            attestation.write_attestation(self.out_dir, record)

    def test_post_write_identity_rejects_and_preserves_a_replacement(self) -> None:
        record = attestation.make_attestation(
            checkout=CHECKOUT,
            manifest=MANIFEST_IDENTITY,
            gn_args=gn_args_record(),
            artifacts=artifact_records(),
            out_dir=self.out_dir,
        )
        written = attestation.write_attestation(self.out_dir, record)
        written.path.unlink()
        written.path.write_bytes(b"replacement record")
        with self.assertRaisesRegex(attestation.M0Error, "changed after"):
            attestation.verify_written_attestation(written)
        self.assertEqual(b"replacement record", written.path.read_bytes())
        self.assertFalse(
            hasattr(attestation, "remove_written_attestation_if_unchanged")
        )


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
            "load_manifest_snapshot": mock.patch.object(
                attestation,
                "load_manifest_snapshot",
                side_effect=[
                    (manifest_data(), MANIFEST_IDENTITY),
                    (manifest_data(), MANIFEST_IDENTITY),
                ],
            ),
            "check_boundary": mock.patch.object(attestation, "check_boundary"),
        }

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
        self.assertEqual(2, active["load_manifest_snapshot"].call_count)
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
        patches["module_artifact_records"] = mock.patch.object(
            attestation,
            "module_artifact_records",
            side_effect=[artifact_records(), changed_artifacts],
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

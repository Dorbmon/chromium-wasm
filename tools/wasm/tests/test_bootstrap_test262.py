#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import copy
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import bootstrap
import m0_common
from m0_common import M0Error, load_manifest, validate_test262_manifest


def run_git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def create_git_origin(root: Path, license_contents: bytes) -> tuple[Path, str]:
    origin = root / "origin"
    origin.mkdir()
    run_git(origin, "init", "--quiet")
    (origin / "LICENSE").write_bytes(license_contents)
    source = origin / "test/example.js"
    source.parent.mkdir()
    source.write_text("/* pinned test source */\n", encoding="utf-8")
    run_git(origin, "add", "LICENSE", "test/example.js")
    run_git(
        origin,
        "-c",
        "user.name=Chromium Wasm Test",
        "-c",
        "user.email=chromium-wasm-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Add license",
    )
    return origin, run_git(origin, "rev-parse", "HEAD")


def local_test262_pin(
    origin: Path, revision: str, license_contents: bytes
) -> dict[str, object]:
    return {
        "path": "v8/test/test262/data",
        "deps_path": "test/test262/data",
        "remote": str(origin),
        "revision": revision,
        "license_path": "LICENSE",
        "license_size_bytes": len(license_contents),
        "license_sha256": hashlib.sha256(license_contents).hexdigest(),
    }


class Test262ManifestTest(unittest.TestCase):
    def test_manifest_records_exact_v8_test262_pin(self) -> None:
        manifest = load_manifest()
        test262 = validate_test262_manifest(manifest)
        self.assertEqual(
            test262,
            {
                "path": "v8/test/test262/data",
                "deps_path": "test/test262/data",
                "remote": (
                    "https://chromium.googlesource.com/"
                    "external/github.com/tc39/test262.git"
                ),
                "revision": (
                    "7e115f46ac64340827d505fa928ad436cb7ba5a6"
                ),
                "license_path": "LICENSE",
                "license_size_bytes": 2213,
                "license_sha256": (
                    "4dd9244dfe8197c75348c4b24ab53d29"
                    "d3b1cfad143ac76b5a3d8942aa354ce0"
                ),
            },
        )

    def test_manifest_rejects_unsafe_or_malformed_test262_fields(self) -> None:
        manifest = load_manifest()
        invalid_fields = (
            ("path", "/tmp/test262", "path must stay in the checkout"),
            ("path", "../test262", "path must stay in the checkout"),
            ("path", "v8/test/test262/data/", "checkout path mismatch"),
            ("deps_path", "../test262", "V8 DEPS path mismatch"),
            ("remote", "https://example.test/test262.git", "remote mismatch"),
            ("revision", "A" * 40, "lowercase 40-character Git hash"),
            ("revision", "0" * 39, "lowercase 40-character Git hash"),
            ("license_path", "../LICENSE", "license path mismatch"),
            ("license_size_bytes", True, "positive integer"),
            ("license_size_bytes", 0, "positive integer"),
            ("license_sha256", "A" * 64, "lowercase SHA-256"),
        )
        for field, value, error in invalid_fields:
            invalid = copy.deepcopy(manifest)
            invalid["test262"][field] = value
            with (
                self.subTest(field=field, value=value),
                self.assertRaisesRegex(M0Error, error),
            ):
                validate_test262_manifest(invalid)
        invalid = copy.deepcopy(manifest)
        invalid["test262"]["unexpected"] = "field"
        with self.assertRaisesRegex(M0Error, "fields mismatch"):
            validate_test262_manifest(invalid)

    def test_context_reports_test262_provenance(self) -> None:
        manifest = load_manifest()
        stdout = StringIO()
        with (
            mock.patch.object(
                m0_common,
                "checked_output",
                side_effect=("port-commit", "m0-commit"),
            ),
            mock.patch("sys.stdout", stdout),
        ):
            context = m0_common.print_context("bootstrap.py", manifest)

        emitted = json.loads(stdout.getvalue().split(" ", 1)[1])
        self.assertEqual(context["test262"], manifest["test262"])
        self.assertEqual(emitted["test262"], manifest["test262"])


class Test262DepsPinTest(unittest.TestCase):
    def test_v8_deps_matches_manifest_pin(self) -> None:
        bootstrap.verify_test262_v8_deps_pin(load_manifest())

    def test_v8_deps_revision_mismatch_is_rejected(self) -> None:
        manifest = copy.deepcopy(load_manifest())
        manifest["test262"]["revision"] = "0" * 40
        with self.assertRaisesRegex(
            M0Error, "V8 DEPS Test262 pin mismatch"
        ):
            bootstrap.verify_test262_v8_deps_pin(manifest)

    def test_v8_deps_duplicate_dependency_is_rejected(self) -> None:
        manifest = load_manifest()
        test262 = manifest["test262"]
        entry = (
            "  'test/test262/data':\n"
            "    Var('chromium_url') + "
            "'/external/github.com/tc39/test262.git' + '@' + "
            f"'{test262['revision']}',"
        )
        deps_text = (
            "  'chromium_url': "
            "'https://chromium.googlesource.com',\n"
            f"{entry}\n{entry}\n"
        )
        with (
            mock.patch.object(
                bootstrap, "checked_output", return_value=deps_text
            ),
            self.assertRaisesRegex(
                M0Error, "must define the Test262 dependency exactly once"
            ),
        ):
            bootstrap.verify_test262_v8_deps_pin(manifest)


class Test262CheckoutTest(unittest.TestCase):
    def test_installs_clean_exact_detached_checkout_atomically(self) -> None:
        license_contents = b"local pinned license\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision = create_git_origin(
                repo_root, license_contents
            )
            test262 = local_test262_pin(
                origin, revision, license_contents
            )
            checkout_root = repo_root / str(test262["path"])
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap.os, "replace", wraps=bootstrap.os.replace
                ) as replace,
            ):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )

            self.assertEqual(
                run_git(checkout_root, "rev-parse", "HEAD"), revision
            )
            self.assertEqual(
                run_git(checkout_root, "rev-parse", "--abbrev-ref", "HEAD"),
                "HEAD",
            )
            self.assertEqual(
                run_git(checkout_root, "remote", "get-url", "origin"),
                str(origin),
            )
            self.assertEqual(
                run_git(checkout_root, "status", "--short"), ""
            )
            self.assertEqual(
                replace.call_args.args[1], checkout_root
            )
            self.assertEqual(
                list(checkout_root.parent.glob(".data.install-*")), []
            )

    def test_bad_license_is_rejected_before_promotion(self) -> None:
        license_contents = b"local pinned license\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision = create_git_origin(
                repo_root, license_contents
            )
            test262 = local_test262_pin(
                origin, revision, license_contents
            )
            test262["license_sha256"] = "0" * 64
            checkout_root = repo_root / str(test262["path"])
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(
                    M0Error, "Test262 LICENSE hash mismatch"
                ),
            ):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )

            self.assertFalse(checkout_root.exists())
            self.assertEqual(
                list(checkout_root.parent.glob(".data.install-*")), []
            )

    def test_existing_invalid_checkout_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            checkout_root = repo_root / "v8/test/test262/data"
            checkout_root.mkdir(parents=True)
            marker = checkout_root / "keep-me"
            marker.write_text("user state", encoding="utf-8")
            test262 = copy.deepcopy(load_manifest()["test262"])
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(
                    M0Error,
                    "existing Test262 checkout is invalid; "
                    "refusing to overwrite it",
                ),
            ):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )

            self.assertEqual(
                marker.read_text(encoding="utf-8"), "user state"
            )

    def test_install_refuses_to_create_parent_outside_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repo_root = temporary_root / "repo"
            repo_root.mkdir()
            checkout_root = temporary_root / "outside/test262/data"
            test262 = copy.deepcopy(load_manifest()["test262"])
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(
                    M0Error, "parent must stay in the checkout"
                ),
            ):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )

            self.assertFalse(checkout_root.parent.exists())

    def test_checkout_verification_rejects_branch_and_dirty_tree(self) -> None:
        license_contents = b"local pinned license\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision = create_git_origin(
                repo_root, license_contents
            )
            test262 = local_test262_pin(
                origin, revision, license_contents
            )
            checkout_root = repo_root / str(test262["path"])
            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )
                run_git(checkout_root, "switch", "--quiet", "-c", "local")
                with self.assertRaisesRegex(
                    M0Error, "Test262 HEAD mismatch"
                ):
                    bootstrap.verify_test262_checkout(
                        test262, checkout_root
                    )

                run_git(
                    checkout_root,
                    "switch",
                    "--quiet",
                    "--detach",
                    revision,
                )
                (checkout_root / "untracked").write_text(
                    "dirty", encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    M0Error, "Test262 worktree mismatch"
                ):
                    bootstrap.verify_test262_checkout(
                        test262, checkout_root
                    )

    def test_checkout_verification_rejects_hidden_index_flags(self) -> None:
        license_contents = b"local pinned license\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision = create_git_origin(
                repo_root, license_contents
            )
            test262 = local_test262_pin(
                origin, revision, license_contents
            )
            checkout_root = repo_root / str(test262["path"])
            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )
                run_git(
                    checkout_root,
                    "update-index",
                    "--assume-unchanged",
                    "LICENSE",
                )
                (checkout_root / "LICENSE").write_bytes(b"hidden change\n")
                with self.assertRaisesRegex(
                    M0Error, "hidden index flags"
                ):
                    bootstrap.verify_test262_checkout(
                        test262, checkout_root
                    )

    def test_checkout_verification_rejects_sparse_checkout(self) -> None:
        license_contents = b"local pinned license\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision = create_git_origin(
                repo_root, license_contents
            )
            test262 = local_test262_pin(
                origin, revision, license_contents
            )
            checkout_root = repo_root / str(test262["path"])
            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )
                run_git(
                    checkout_root,
                    "sparse-checkout",
                    "set",
                    "--no-cone",
                    "LICENSE",
                )
                self.assertFalse(
                    (checkout_root / "test/example.js").exists()
                )
                with self.assertRaisesRegex(M0Error, "must not be sparse"):
                    bootstrap.verify_test262_checkout(
                        test262, checkout_root
                    )

    def test_path_appearing_during_install_is_not_replaced(self) -> None:
        test262 = copy.deepcopy(load_manifest()["test262"])
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            checkout_root = repo_root / str(test262["path"])
            checkout_root.parent.mkdir(parents=True)
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap.os.path,
                    "lexists",
                    side_effect=(False, True),
                ),
                mock.patch.object(bootstrap, "run"),
                mock.patch.object(
                    bootstrap,
                    "checked_output",
                    return_value=str(test262["revision"]),
                ),
                mock.patch.object(
                    bootstrap, "verify_test262_checkout"
                ),
                mock.patch.object(bootstrap.os, "replace") as replace,
                self.assertRaisesRegex(
                    M0Error, "path appeared during installation"
                ),
            ):
                bootstrap.install_test262_checkout(
                    test262, checkout_root
                )

            replace.assert_not_called()
            self.assertEqual(
                list(checkout_root.parent.glob(".data.install-*")), []
            )

    def test_verify_only_never_invokes_installer(self) -> None:
        manifest = load_manifest()
        checkout_root = bootstrap.REPO_ROOT / "v8/test/test262/data"
        with (
            mock.patch.object(bootstrap, "verify_test262_v8_deps_pin"),
            mock.patch.object(
                bootstrap,
                "test262_checkout_path",
                return_value=checkout_root,
            ),
            mock.patch.object(
                bootstrap, "verify_test262_checkout"
            ) as verify,
            mock.patch.object(
                bootstrap, "install_test262_checkout"
            ) as install,
        ):
            bootstrap.ensure_test262(manifest, install=False)

        install.assert_not_called()
        verify.assert_called_once_with(
            manifest["test262"], checkout_root
        )


if __name__ == "__main__":
    unittest.main()

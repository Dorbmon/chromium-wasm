#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

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
from m0_common import load_manifest


class HostGraphManifestTest(unittest.TestCase):
    def test_chromium_lastchange_metadata_matches_pinned_revision(self) -> None:
        manifest = load_manifest()
        chromium = manifest["chromium"]
        self.assertEqual(chromium["commit_timestamp"], 1784580336)
        self.assertEqual(
            chromium["commit_position"], "refs/branch-heads/7871@{#3786}"
        )

    def test_m3_runtime_dependencies_match_upstream_gitlinks(self) -> None:
        manifest = load_manifest()
        chromium_revision = manifest["chromium"]["revision"]
        dependencies = manifest["git_dependencies"]
        expected = {
            "skia": "587c5b0f5a7b0260826a0c19094c2d952195066e",
            "dawn": "d089fc91e7e4881362463faf8efe9ae435e34660",
            "boringssl": (
                "3a9254f16eda7a4c5d2260039ff23456a0a34de4"
            ),
            "icu": "3859e64eed5d34544b27fbcab0ac1685ce83df3c",
            "webrtc": "1f975dfd761af6e5d76d28333191973b258d82a8",
            "ffmpeg": "ad41607c61898cf7150e0fb20fe4bbabd44922a3",
            "libyuv": "8aeb3a9ca36341a640528e59b34b5d641080dca8",
        }
        self.assertTrue(expected.keys() <= set(bootstrap.REQUIRED_SUBMODULES))
        for name, revision in expected.items():
            with self.subTest(name=name):
                dependency = dependencies[name]
                self.assertEqual(dependency["revision"], revision)
                self.assertEqual(
                    bootstrap.gitlink_revision(
                        chromium_revision, dependency["path"]
                    ),
                    revision,
                )

    def test_host_proto_dependencies_match_upstream_gitlinks(self) -> None:
        manifest = load_manifest()
        chromium_revision = manifest["chromium"]["revision"]
        dependencies = manifest["git_dependencies"]
        expected = {
            "compiler_rt": (
                "03641f7a5b05e48e318d64369057db577cafc594"
            ),
            "protobuf_javascript": (
                "e6d763860001ba1a76a63adcff5efb12b1c96024"
            ),
        }
        self.assertTrue(expected.keys() <= set(bootstrap.REQUIRED_SUBMODULES))
        for name, revision in expected.items():
            with self.subTest(name=name):
                dependency = dependencies[name]
                self.assertEqual(dependency["revision"], revision)
                self.assertEqual(
                    bootstrap.gitlink_revision(
                        chromium_revision, dependency["path"]
                    ),
                    revision,
                )

    def test_perfetto_separates_upstream_and_port_revisions(self) -> None:
        manifest = load_manifest()
        perfetto = manifest["git_dependencies"]["perfetto"]
        self.assertEqual(
            perfetto["upstream_revision"],
            "9ede949f025303868fa0c42418f122ac47312539",
        )
        self.assertEqual(
            perfetto["revision"],
            "72722368828dde107df27d53410cab5ba232f8ee",
        )
        self.assertEqual(
            bootstrap.gitlink_revision(
                manifest["chromium"]["revision"], perfetto["path"]
            ),
            perfetto["upstream_revision"],
        )

    def test_source_validation_uses_port_revision_for_head(self) -> None:
        upstream_revision = "1" * 40
        port_revision = "2" * 40
        manifest = {
            "chromium": {
                "revision": "base",
                "tag": "1.2.3.4",
            },
            "git_dependencies": {
                "perfetto": {
                    "path": "third_party/perfetto",
                    "upstream_revision": upstream_revision,
                    "revision": port_revision,
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            dependency_root = repo_root / "third_party/perfetto"
            dependency_root.mkdir(parents=True)
            (dependency_root / ".git").touch()

            def checked_output(
                command: list[str], *, cwd: Path = repo_root
            ) -> str:
                if command == ["git", "show", "base:chrome/VERSION"]:
                    return "\n".join(
                        ("MAJOR=1", "MINOR=2", "BUILD=3", "PATCH=4")
                    )
                if command == ["git", "rev-parse", "HEAD"]:
                    self.assertEqual(cwd, dependency_root)
                    return port_revision
                if command == [
                    "git",
                    "status",
                    "--short",
                    "--untracked-files=no",
                ]:
                    self.assertEqual(cwd, dependency_root)
                    return ""
                self.fail(f"unexpected command: {command}")

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap, "REQUIRED_SUBMODULES", ("perfetto",)
                ),
                mock.patch.object(
                    bootstrap.platform, "system", return_value="Linux"
                ),
                mock.patch.object(
                    bootstrap.platform, "machine", return_value="x86_64"
                ),
                mock.patch.object(bootstrap, "run"),
                mock.patch.object(
                    bootstrap,
                    "checked_output",
                    side_effect=checked_output,
                ),
                mock.patch.object(
                    bootstrap,
                    "gitlink_revision",
                    side_effect=(upstream_revision, port_revision),
                ) as gitlink,
            ):
                bootstrap.ensure_source_dependencies(
                    manifest, install=False
                )

            self.assertEqual(
                gitlink.call_args_list,
                [
                    mock.call("base", "third_party/perfetto"),
                    mock.call("HEAD", "third_party/perfetto"),
                ],
            )


class HostToolchainBootstrapTest(unittest.TestCase):
    def test_verify_only_matches_installed_tools_without_installers(
        self,
    ) -> None:
        manifest = load_manifest()
        with (
            mock.patch.object(
                bootstrap, "run", wraps=bootstrap.run
            ) as run_command,
            mock.patch.object(
                bootstrap,
                "checked_output",
                wraps=bootstrap.checked_output,
            ) as checked_output,
        ):
            bootstrap.ensure_host_clang(
                manifest, Path(sys.executable), install=False
            )
            bootstrap.ensure_host_sysroot(
                manifest, Path(sys.executable), install=False
            )

        commands = [call.args[0] for call in run_command.call_args_list]
        checked_commands = [
            call.args[0] for call in checked_output.call_args_list
        ]
        installer_commands = [
            command
            for command in commands + checked_commands
            if any("install-sysroot.py" in argument for argument in command)
        ]
        self.assertEqual(installer_commands, [])
        clang_update_commands = [
            command
            for command in commands + checked_commands
            if any("tools/clang/scripts/update.py" in argument
                   for argument in command)
        ]
        self.assertEqual(len(clang_update_commands), 1)
        self.assertIn("--print-revision", clang_update_commands[0])

    def test_install_uses_chromium_clang_script(self) -> None:
        revision = "llvmorg-test-1"
        archive_hash = "a" * 64
        binary_hash = "b" * 64
        version_output = "clang version test (llvm test)"
        manifest = {
            "host_clang": {
                "path": "third_party/llvm-build/Release+Asserts",
                "revision": revision,
                "llvm_revision": "llvm-test",
                "version_output": version_output,
                "archive_sha256": archive_hash,
                "artifact_sha256": {
                    "clang": binary_hash,
                    "ld.lld": binary_hash,
                    "llvm-ar": binary_hash,
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            clang_root = (
                repo_root / "third_party/llvm-build/Release+Asserts"
            )
            (clang_root / "bin").mkdir(parents=True)
            for name in ("clang", "ld.lld", "llvm-ar"):
                (clang_root / "bin" / name).touch()
            (clang_root / "cr_build_revision").write_text(
                f"{revision},win\n", encoding="utf-8"
            )
            update_script = repo_root / "tools/clang/scripts/update.py"
            update_script.parent.mkdir(parents=True)
            update_script.touch()
            (repo_root / "DEPS").write_text(
                archive_hash, encoding="utf-8"
            )
            completed = subprocess.CompletedProcess(
                [], 0, stdout=f"{version_output}\nllvm-test\n", stderr=""
            )
            bootstrap_python = Path("/pinned/python3")
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap,
                    "checked_output",
                    return_value=revision,
                ),
                mock.patch.object(
                    bootstrap, "sha256", return_value=binary_hash
                ),
                mock.patch.object(
                    bootstrap, "run", return_value=completed
                ) as run_command,
            ):
                bootstrap.ensure_host_clang(
                    manifest, bootstrap_python, install=True
                )

            run_command.assert_any_call(
                [
                    str(bootstrap_python),
                    str(update_script),
                    "--output-dir",
                    str(clang_root),
                ],
                capture_output=False,
            )

    def test_install_uses_chromium_sysroot_script(self) -> None:
        archive_hash = "c" * 64
        url = "https://example.test/sysroot"
        manifest = {
            "host_sysroot": {
                "arch": "amd64",
                "platform": "bullseye",
                "path": "build/linux/debian_bullseye_amd64-sysroot",
                "metadata_path": (
                    "build/linux/sysroot_scripts/sysroots.json"
                ),
                "tarball": "debian_sysroot.tar.xz",
                "url": url,
                "sha256": archive_hash,
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            script_root = repo_root / "build/linux/sysroot_scripts"
            script_root.mkdir(parents=True)
            metadata = {
                "bullseye_amd64": {
                    "Sha256Sum": archive_hash,
                    "SysrootDir": "debian_bullseye_amd64-sysroot",
                    "Tarball": "debian_sysroot.tar.xz",
                    "URL": url,
                },
            }
            (script_root / "sysroots.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            install_script = script_root / "install-sysroot.py"
            install_script.touch()
            sysroot = (
                repo_root / "build/linux/debian_bullseye_amd64-sysroot"
            )
            (sysroot / "usr/include").mkdir(parents=True)
            (sysroot / "usr/include/stdlib.h").touch()
            lib_dir = sysroot / "usr/lib/x86_64-linux-gnu"
            lib_dir.mkdir(parents=True)
            (lib_dir / "crt1.o").touch()
            (sysroot / ".stamp").write_text(
                f"{url}/{archive_hash}", encoding="utf-8"
            )
            bootstrap_python = Path("/pinned/python3")
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(bootstrap, "run") as run_command,
            ):
                bootstrap.ensure_host_sysroot(
                    manifest, bootstrap_python, install=True
                )

            run_command.assert_called_once_with(
                [
                    str(bootstrap_python),
                    str(install_script),
                    "--arch=amd64",
                ],
                capture_output=False,
            )


if __name__ == "__main__":
    unittest.main()

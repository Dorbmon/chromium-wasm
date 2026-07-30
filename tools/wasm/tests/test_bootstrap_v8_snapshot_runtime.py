#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import hashlib
import os
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


class V8SnapshotRuntimeManifestTest(unittest.TestCase):
    def test_manifest_matches_chromium_i386_source_pins(self) -> None:
        manifest = load_manifest()
        sysroot = manifest["v8_snapshot_sysroot"]
        self.assertEqual(sysroot["arch"], "i386")
        self.assertEqual(
            sysroot["sha256"],
            "3de724b0d63478e1ae35f07b95d02261581a66e05c19aebe4e443d76179a565e",
        )

        runtime = manifest["v8_snapshot_runtime"]
        self.assertIn(
            'v8_snapshot_toolchain = '
            '"//build/toolchain/linux:clang_x86_v8_arm"',
            manifest["m3_content_gn_args"],
        )
        self.assertIn(
            "v8_snapshot_toolchain_runtime_root = "
            f'"//{runtime["path"]}"',
            manifest["m3_content_gn_args"],
        )
        package_list = (
            bootstrap.REPO_ROOT / runtime["package_list_path"]
        ).read_text(encoding="utf-8").splitlines()
        expected_hashes = {
            "libc6": (
                "6fe37330cca238038de35a5628ba4ae5788deb84e0bf15e2926ea76acbb00f72"
            ),
            "libgcc-s1": (
                "0a52edec5d626f8d9acf1998248d276760aff3950f44a308d27d4a2a488fe18d"
            ),
        }
        for package in runtime["packages"]:
            with self.subTest(package=package["name"]):
                self.assertEqual(
                    package["sha256"], expected_hashes[package["name"]]
                )
                self.assertEqual(package_list.count(package["url"]), 1)
        self.assertEqual(
            set(runtime["artifacts"]),
            {
                "lib/i386-linux-gnu/ld-2.31.so",
                "lib/i386-linux-gnu/libc-2.31.so",
                "lib/i386-linux-gnu/libdl-2.31.so",
                "lib/i386-linux-gnu/libgcc_s.so.1",
                "lib/i386-linux-gnu/libm-2.31.so",
                "lib/i386-linux-gnu/libpthread-2.31.so",
                "lib/i386-linux-gnu/librt-2.31.so",
            },
        )
        self.assertEqual(runtime["loader_path"], "lib/ld-linux.so.2")
        self.assertEqual(runtime["library_paths"], ["lib/i386-linux-gnu"])
        self.assertEqual(
            runtime["symlinks"],
            {
                "lib/ld-linux.so.2": (
                    "i386-linux-gnu/ld-2.31.so"
                ),
                "lib/i386-linux-gnu/ld-linux.so.2": "ld-2.31.so",
                "lib/i386-linux-gnu/libc.so.6": "libc-2.31.so",
                "lib/i386-linux-gnu/libdl.so.2": "libdl-2.31.so",
                "lib/i386-linux-gnu/libm.so.6": "libm-2.31.so",
                "lib/i386-linux-gnu/libpthread.so.0": (
                    "libpthread-2.31.so"
                ),
                "lib/i386-linux-gnu/librt.so.1": "librt-2.31.so",
            },
        )


class V8SnapshotRuntimeBootstrapTest(unittest.TestCase):
    def test_rejects_symlinked_runtime_parent(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            tempfile.TemporaryDirectory() as outside_directory,
        ):
            repo_root = Path(temporary_directory)
            (repo_root / "out").symlink_to(
                outside_directory, target_is_directory=True
            )
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(
                    bootstrap.M0Error, "must not be a symlink"
                ),
            ):
                bootstrap.v8_snapshot_runtime_path(
                    {"path": "out/wasm-i386-runtime/root"}
                )

    def test_rejects_package_outside_runtime_parent(self) -> None:
        runtime = {"path": "out/wasm-i386-runtime/root"}
        package = {"archive_path": "out/elsewhere/libc6.deb"}
        with self.assertRaisesRegex(
            bootstrap.M0Error, "directly under"
        ):
            bootstrap.v8_snapshot_package_archive_path(
                runtime, package
            )

    def test_installs_packages_into_verified_staging_tree(self) -> None:
        package_contents = {
            "libc6": b"libc-package",
            "libgcc-s1": b"libgcc-package",
        }
        artifact_contents = {
            "lib/i386-linux-gnu/ld-2.31.so": b"loader",
            "lib/i386-linux-gnu/libc-2.31.so": b"libc",
            "lib/i386-linux-gnu/libgcc_s.so.1": b"libgcc",
            "lib/i386-linux-gnu/libpthread-2.31.so": b"pthread",
        }
        symlinks = {
            "lib/ld-linux.so.2": "i386-linux-gnu/ld-2.31.so",
            "lib/i386-linux-gnu/libc.so.6": "libc-2.31.so",
            "lib/i386-linux-gnu/libpthread.so.0": "libpthread-2.31.so",
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            package_list_path = (
                repo_root
                / "build/linux/sysroot_scripts/generated_package_lists"
                / "bullseye.i386"
            )
            package_list_path.parent.mkdir(parents=True)
            packages = []
            urls = []
            for name, contents in package_contents.items():
                url = f"https://example.test/{name}.deb"
                urls.append(url)
                archive_path = Path(
                    f"out/wasm-i386-runtime/{name}.deb"
                )
                archive = repo_root / archive_path
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_bytes(contents)
                packages.append(
                    {
                        "name": name,
                        "archive_path": archive_path.as_posix(),
                        "url": url,
                        "size_bytes": len(contents),
                        "sha256": hashlib.sha256(contents).hexdigest(),
                    }
                )
            package_list_path.write_text(
                "\n".join(urls) + "\n", encoding="utf-8"
            )
            runtime = {
                "path": "out/wasm-i386-runtime/root",
                "package_list_path": (
                    "build/linux/sysroot_scripts/"
                    "generated_package_lists/bullseye.i386"
                ),
                "packages": packages,
                "artifacts": {
                    path: hashlib.sha256(contents).hexdigest()
                    for path, contents in artifact_contents.items()
                },
                "symlinks": symlinks,
                "loader_path": "lib/ld-linux.so.2",
                "library_paths": ["lib/i386-linux-gnu"],
            }

            def run_command(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                del kwargs
                if len(command) > 1 and command[1] == "--extract":
                    candidate_root = Path(command[-1])
                    for path, contents in artifact_contents.items():
                        artifact = candidate_root / path
                        artifact.parent.mkdir(parents=True, exist_ok=True)
                        artifact.write_bytes(contents)
                    for path, target in symlinks.items():
                        symlink = candidate_root / path
                        symlink.parent.mkdir(parents=True, exist_ok=True)
                        if not os.path.lexists(symlink):
                            symlink.symlink_to(target)
                    return subprocess.CompletedProcess(
                        command, 0, stdout="", stderr=""
                    )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        "GNU C Library (Debian GLIBC 2.31-13+deb11u5) "
                        "stable release version 2.31.\n"
                    ),
                    stderr="",
                )

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap.shutil,
                    "which",
                    return_value="/pinned/dpkg-deb",
                ),
                mock.patch.object(
                    bootstrap, "run", side_effect=run_command
                ) as runner,
            ):
                bootstrap.install_v8_snapshot_runtime(runtime)
                bootstrap.verify_v8_snapshot_runtime(
                    runtime, verify_execution=False
                )

            extraction_calls = [
                call
                for call in runner.call_args_list
                if len(call.args[0]) > 1
                and call.args[0][1] == "--extract"
            ]
            self.assertEqual(len(extraction_calls), 2)
            self.assertTrue(
                (
                    repo_root
                    / "out/wasm-i386-runtime/root/.stamp"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()

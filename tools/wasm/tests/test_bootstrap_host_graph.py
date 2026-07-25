#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
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
            "libjpeg_turbo": (
                "640f254ad0fa03f6b1f29f89b7dd9366f2f6e533"
            ),
            "quiche": "997d654308b6a1a17435e472ef5190aecb12e3eb",
            "re2": "972a15cedd008d846f1a39b2e88ce48d7f166cbd",
        }
        self.assertTrue(expected.keys() <= set(bootstrap.REQUIRED_SUBMODULES))
        for name, revision in expected.items():
            with self.subTest(name=name):
                dependency = dependencies[name]
                self.assertEqual(
                    dependency.get(
                        "upstream_revision", dependency["revision"]
                    ),
                    revision,
                )
                self.assertEqual(
                    bootstrap.gitlink_revision(
                        chromium_revision, dependency["path"]
                    ),
                    revision,
                )

    def test_m3_source_profile_covers_selected_content_gitlinks(self) -> None:
        manifest = load_manifest()
        chromium_revision = manifest["chromium"]["revision"]
        dependencies = manifest["git_dependencies"]
        expected_names = (
            "catapult",
            "ced",
            "crc32c",
            "dragonbox",
            "emoji_segmenter",
            "expat",
            "fast_float",
            "flac",
            "flatbuffers",
            "fp16",
            "freetype",
            "harfbuzz",
            "highway",
            "leveldb",
            "libaddressinput",
            "libcxx",
            "libcxxabi",
            "libgav1",
            "libjpeg_turbo",
            "libphonenumber",
            "libsrtp",
            "libwebm",
            "libwebp",
            "lss",
            "llvm_libc",
            "material_color_utilities",
            "ots",
            "quiche",
            "re2",
            "search_engines_data",
            "snappy",
            "sqlite",
            "vulkan_headers",
            "wuffs",
            "zstd",
        )
        self.assertEqual(
            bootstrap.M3_ADDITIONAL_SUBMODULES, expected_names
        )
        self.assertEqual(
            bootstrap.M3_REQUIRED_SUBMODULES,
            (
                *bootstrap.M0_REQUIRED_SUBMODULES,
                *expected_names,
            ),
        )
        self.assertEqual(
            set(bootstrap.M0_REQUIRED_SUBMODULES)
            & set(bootstrap.M3_ADDITIONAL_SUBMODULES),
            set(),
        )
        for name in expected_names:
            with self.subTest(name=name):
                dependency = dependencies[name]
                self.assertEqual(
                    bootstrap.gitlink_revision(
                        chromium_revision, dependency["path"]
                    ),
                    dependency.get(
                        "upstream_revision", dependency["revision"]
                    ),
                )

    def test_m3_nested_dawn_dependency_matches_its_gitlink(self) -> None:
        manifest = load_manifest()
        dependencies = manifest["git_dependencies"]
        nested = manifest["nested_git_dependencies"][
            "dawn_webgpu_headers"
        ]
        dawn = dependencies[nested["parent"]]
        self.assertEqual(
            bootstrap.M3_REQUIRED_NESTED_SUBMODULES,
            ("dawn_webgpu_headers",),
        )
        self.assertEqual(
            bootstrap.nested_gitlink_revision(
                bootstrap.REPO_ROOT / dawn["path"],
                dawn["revision"],
                nested["path"],
            ),
            nested["revision"],
        )
        bootstrap.ensure_nested_source_dependencies(
            manifest, install=False
        )

    def test_m3_generator_inputs_match_chromium_pins(self) -> None:
        manifest = load_manifest()
        gperf = manifest["gperf"]
        self.assertEqual(gperf["cipd_tag"], "version:3@3.2")
        self.assertEqual(
            gperf["cipd_instance"],
            "otrRUeHQr9zlxtT4sJfSJqspytBWr9IkPrhZ8bFolnYC",
        )
        bootstrap.verify_toolchain_ensure_pins(manifest)
        bootstrap.ensure_build_tools(
            manifest, Path("unused-in-verify-only"), install=False
        )

        node_modules = manifest["webui_node_modules"]
        self.assertEqual(
            node_modules["object_name"],
            "38df23cf794887ca7c81d57bf30f66c38c144e28",
        )
        bootstrap.ensure_webui_node_modules(manifest, install=False)

        node_runtime = manifest["chromium_node_runtime"]
        self.assertEqual(
            node_runtime["object_name"],
            "744e6926ffdd4a4fb2080ae2b9ce4575490261e7",
        )
        self.assertEqual(node_runtime["version_output"], "v24.12.0")
        bootstrap.ensure_chromium_node_runtime(
            manifest, install=False
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


class WebuiNodeModulesBootstrapTest(unittest.TestCase):
    def test_clean_install_is_atomic_and_verifies_extracted_tree(self) -> None:
        archive_buffer = BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            for name in ("./typescript", "./typescript/bin"):
                directory = tarfile.TarInfo(name)
                directory.type = tarfile.DIRTYPE
                directory.mode = 0o755
                archive.addfile(directory)
            contents = b"#!/usr/bin/env node\n"
            executable = tarfile.TarInfo("./typescript/bin/tsc")
            executable.mode = 0o755
            executable.size = len(contents)
            archive.addfile(executable, BytesIO(contents))
        archive_contents = archive_buffer.getvalue()
        object_name = hashlib.sha1(archive_contents).hexdigest()
        archive_sha256 = hashlib.sha256(archive_contents).hexdigest()
        node_modules = {
            "path": "third_party/node/node_modules",
            "archive_path": "third_party/node/node_modules.tar.gz",
            "sha1_path": "third_party/node/node_modules.tar.gz.sha1",
            "bucket": "chromium-nodejs",
            "object_name": object_name,
            "sha256": archive_sha256,
            "size_bytes": len(archive_contents),
            "generation": 42,
            "output_file": "node_modules.tar.gz",
        }
        manifest = {"webui_node_modules": node_modules}

        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            node_root = repo_root / "third_party/node"
            node_root.mkdir(parents=True)
            (node_root / "node_modules.tar.gz.sha1").write_text(
                object_name + "\n", encoding="utf-8"
            )
            (repo_root / "DEPS").write_text(
                "\n".join(
                    (
                        "'src/third_party/node/node_modules': {",
                        "'bucket': 'chromium-nodejs'",
                        f"'object_name': '{object_name}'",
                        f"'sha256sum': '{archive_sha256}'",
                        f"'size_bytes': {len(archive_contents)},",
                        "'generation': 42,",
                        "'output_file': 'node_modules.tar.gz'",
                    )
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap.urllib.request,
                    "urlopen",
                    return_value=BytesIO(archive_contents),
                ) as urlopen,
            ):
                bootstrap.ensure_webui_node_modules(
                    manifest, install=True
                )
                bootstrap.ensure_webui_node_modules(
                    manifest, install=False
                )
                self.assertEqual(urlopen.call_count, 1)
                executable_path = (
                    node_root / "node_modules/typescript/bin/tsc"
                )
                self.assertEqual(executable_path.read_bytes(), contents)
                executable_path.write_bytes(b"corrupt")
                with self.assertRaisesRegex(
                    bootstrap.M0Error, "entry mismatch"
                ):
                    bootstrap.ensure_webui_node_modules(
                        manifest, install=False
                    )

            request = urlopen.call_args.args[0]
            self.assertEqual(
                request.full_url,
                "https://storage.googleapis.com/"
                f"chromium-nodejs/{object_name}",
            )
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 120)
            self.assertEqual(
                list(node_root.glob(".node_modules.*-*")), []
            )


class ChromiumNodeRuntimeBootstrapTest(unittest.TestCase):
    @staticmethod
    def _archive() -> tuple[bytes, bytes]:
        archive_buffer = BytesIO()
        executable_contents = (
            b"#!/bin/sh\n"
            b"printf 'v24.12.0\\n'\n"
        )
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            for name in ("node-linux-x64", "node-linux-x64/bin"):
                directory = tarfile.TarInfo(name)
                directory.type = tarfile.DIRTYPE
                directory.mode = 0o755
                archive.addfile(directory)
            executable = tarfile.TarInfo(
                "node-linux-x64/bin/node"
            )
            executable.mode = 0o755
            executable.size = len(executable_contents)
            archive.addfile(executable, BytesIO(executable_contents))
        return archive_buffer.getvalue(), executable_contents

    @staticmethod
    def _manifest(
        archive_contents: bytes, executable_contents: bytes
    ) -> dict[str, object]:
        node_runtime = {
            "path": "third_party/node/linux/node-linux-x64",
            "archive_path": (
                "third_party/node/linux/node-linux-x64.tar.gz"
            ),
            "archive_root": "node-linux-x64",
            "bucket": "chromium-nodejs",
            "object_name": hashlib.sha1(archive_contents).hexdigest(),
            "sha256": hashlib.sha256(archive_contents).hexdigest(),
            "size_bytes": len(archive_contents),
            "generation": 42,
            "output_file": "node-linux-x64.tar.gz",
            "executable_path": "bin/node",
            "executable_sha256": hashlib.sha256(
                executable_contents
            ).hexdigest(),
            "version_output": "v24.12.0",
        }
        return {"chromium_node_runtime": node_runtime}

    @staticmethod
    def _write_deps(repo_root: Path, node_runtime: object) -> None:
        assert isinstance(node_runtime, dict)
        (repo_root / "DEPS").write_text(
            "\n".join(
                (
                    "'src/third_party/node/linux': {",
                    "'bucket': 'chromium-nodejs'",
                    f"'object_name': '{node_runtime['object_name']}'",
                    f"'sha256sum': '{node_runtime['sha256']}'",
                    f"'size_bytes': {node_runtime['size_bytes']},",
                    "'generation': 42,",
                    "'output_file': 'node-linux-x64.tar.gz'",
                )
            ),
            encoding="utf-8",
        )

    def test_clean_install_is_atomic_and_verifies_runtime(self) -> None:
        archive_contents, executable_contents = self._archive()
        manifest = self._manifest(
            archive_contents, executable_contents
        )
        node_runtime = manifest["chromium_node_runtime"]

        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            linux_root = repo_root / "third_party/node/linux"
            linux_root.mkdir(parents=True)
            self._write_deps(repo_root, node_runtime)
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap.urllib.request,
                    "urlopen",
                    return_value=BytesIO(archive_contents),
                ) as urlopen,
            ):
                bootstrap.ensure_chromium_node_runtime(
                    manifest, install=True
                )
                bootstrap.ensure_chromium_node_runtime(
                    manifest, install=False
                )
                self.assertEqual(urlopen.call_count, 1)
                executable = (
                    linux_root / "node-linux-x64/bin/node"
                )
                self.assertEqual(
                    executable.read_bytes(), executable_contents
                )
                executable.write_bytes(b"corrupt")
                with self.assertRaisesRegex(
                    bootstrap.M0Error, "entry mismatch"
                ):
                    bootstrap.ensure_chromium_node_runtime(
                        manifest, install=False
                    )

            request = urlopen.call_args.args[0]
            self.assertEqual(
                request.full_url,
                "https://storage.googleapis.com/chromium-nodejs/"
                f"{node_runtime['object_name']}",
            )
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 120)
            self.assertEqual(
                list(linux_root.glob(".node_runtime.*-*")), []
            )

    def test_archive_validation_rejects_escaping_paths_and_links(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            cases = (
                (
                    "path",
                    "node-linux-x64/../../escape",
                    tarfile.REGTYPE,
                    "",
                    "unsafe Chromium Node runtime archive path",
                ),
                (
                    "link",
                    "node-linux-x64/bin/node",
                    tarfile.SYMTYPE,
                    "../../escape",
                    "unsafe Chromium Node runtime archive symlink target",
                ),
            )
            for case_name, name, member_type, linkname, error in cases:
                with self.subTest(case=case_name):
                    archive_path = temporary_root / f"{case_name}.tar.gz"
                    with tarfile.open(archive_path, mode="w:gz") as archive:
                        member = tarfile.TarInfo(name)
                        member.type = member_type
                        member.linkname = linkname
                        archive.addfile(member)
                    with self.assertRaisesRegex(
                        bootstrap.M0Error, error
                    ):
                        bootstrap._archive_tree(
                            archive_path,
                            label="Chromium Node runtime",
                            archive_prefix="node-linux-x64",
                        )

    def test_download_stops_at_pinned_archive_size(self) -> None:
        archive_contents, executable_contents = self._archive()
        manifest = self._manifest(
            archive_contents, executable_contents
        )
        node_runtime = manifest["chromium_node_runtime"]
        assert isinstance(node_runtime, dict)
        node_runtime["size_bytes"] = len(archive_contents) - 1

        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "node.tar.gz"
            with mock.patch.object(
                bootstrap.urllib.request,
                "urlopen",
                return_value=BytesIO(archive_contents),
            ):
                with self.assertRaisesRegex(
                    bootstrap.M0Error, "exceeds"
                ):
                    bootstrap.download_gcs_archive(
                        node_runtime,
                        archive_path,
                        label="Chromium Node runtime",
                    )
            self.assertLessEqual(
                archive_path.stat().st_size,
                int(node_runtime["size_bytes"]),
            )

    def test_deps_pin_fields_must_share_the_requested_entry(self) -> None:
        archive_contents, executable_contents = self._archive()
        manifest = self._manifest(
            archive_contents, executable_contents
        )
        node_runtime = manifest["chromium_node_runtime"]
        assert isinstance(node_runtime, dict)
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            (repo_root / "DEPS").write_text(
                "\n".join(
                    (
                        "'src/third_party/node/linux': {",
                        "  'bucket': 'wrong-bucket',",
                        "}",
                        "'src/unrelated': {",
                        f"  'bucket': '{node_runtime['bucket']}',",
                        "  'objects': [{",
                        "    'object_name': "
                        f"'{node_runtime['object_name']}',",
                        "    'sha256sum': "
                        f"'{node_runtime['sha256']}',",
                        "    'size_bytes': "
                        f"{node_runtime['size_bytes']},",
                        "    'generation': 42,",
                        "    'output_file': 'node-linux-x64.tar.gz',",
                        "  }],",
                        "}",
                    )
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(
                    bootstrap.M0Error,
                    "missing Chromium Node runtime pin",
                ),
            ):
                bootstrap.verify_chromium_node_runtime_deps_pin(
                    node_runtime
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

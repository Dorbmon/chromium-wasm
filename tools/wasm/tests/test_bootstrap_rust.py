#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from io import BytesIO
import copy
import hashlib
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import bootstrap
from m0_common import M0Error, load_manifest


class RustToolchainManifestTest(unittest.TestCase):
    def test_linux_archive_matches_chromium_deps(self) -> None:
        manifest = load_manifest()
        rust = manifest["rust"]
        self.assertEqual(
            rust["archive"],
            "rust-toolchain-"
            "4c4205163abcbd08948b3efab796c543ba1ea687-"
            "5-llvmorg-23-init-10931-g20b6ec66.tar.xz",
        )
        self.assertEqual(
            rust["url"],
            "https://commondatastorage.googleapis.com/"
            "chromium-browser-clang/Linux_x64/"
            + rust["archive"],
        )
        self.assertEqual(rust["size_bytes"], 274476304)
        self.assertEqual(
            rust["sha256"],
            "5b4f776f6f308ac5e3f1df35cff546107d7d4843b5414294e74986f2e4dd3196",
        )
        bootstrap.verify_rust_deps_pin(manifest)
        bootstrap.verify_rust_source_pins(manifest, rust)

    def test_source_revision_mismatch_is_rejected(self) -> None:
        manifest = copy.deepcopy(load_manifest())
        rust = manifest["rust"]
        rust["source_revision"] = "0" * 40
        with self.assertRaisesRegex(
            M0Error, "Chromium Rust source revision mismatch"
        ):
            bootstrap.verify_rust_source_pins(manifest, rust)

    def test_toolchain_path_cannot_escape_checkout(self) -> None:
        for configured_path in ("/tmp/rust", "../rust", "third_party/../rust"):
            with (
                self.subTest(configured_path=configured_path),
                self.assertRaises(M0Error),
            ):
                bootstrap.rust_toolchain_path({"path": configured_path})


class RustToolchainVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rust = {
            "package_revision": (
                "4c4205163abcbd08948b3efab796c543ba1ea687-"
                "5-llvmorg-23-init-10931-g20b6ec66"
            ),
            "commit_hash": "4c4205163abcbd08948b3efab796c543ba1ea687",
            "host_target": "x86_64-unknown-linux-gnu",
            "version_line": (
                "rustc 1.2.3 abc "
                "(4c4205163abcbd08948b3efab796c543ba1ea687-"
                "5-llvmorg-23-init-10931-g20b6ec66 chromium)"
            ),
            "rustc_vv": {
                "version": "rustc 1.2.3 (4c4205163 2026-01-01)",
                "binary": "rustc",
                "commit-hash": (
                    "4c4205163abcbd08948b3efab796c543ba1ea687"
                ),
                "commit-date": "2026-01-01",
                "host": "x86_64-unknown-linux-gnu",
                "release": "1.2.3",
                "LLVM version": "23.0.0",
            },
            "required_targets": ["wasm32-unknown-emscripten"],
            "rustc_src_files": [
                "lib/rustlib/src/rust/library/Cargo.toml",
                "lib/rustlib/src/rust/library/core/src/lib.rs",
            ],
        }

    def create_toolchain(self, root: Path) -> Path:
        rustc = root / "bin/rustc"
        rustc.parent.mkdir(parents=True)
        rustc.write_text("pinned rustc", encoding="utf-8")
        (root / "VERSION").write_text(
            str(self.rust["version_line"]) + "\n",
            encoding="utf-8",
        )
        for relative_path in self.rust["rustc_src_files"]:
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("source", encoding="utf-8")
        return rustc

    def rustc_vv_output(self) -> str:
        return "\n".join(
            (
                str(self.rust["rustc_vv"]["version"]),
                "binary: rustc",
                "commit-hash: " + str(self.rust["commit_hash"]),
                "commit-date: 2026-01-01",
                "host: x86_64-unknown-linux-gnu",
                "release: 1.2.3",
                "LLVM version: 23.0.0",
            )
        )

    def test_verifies_version_compiler_targets_sysroot_and_sources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            toolchain_root = Path(temporary_directory) / "rust-toolchain"
            rustc = self.create_toolchain(toolchain_root)
            outputs = {
                (str(rustc), "-Vv"): self.rustc_vv_output(),
                (str(rustc), "--print", "target-list"): (
                    "x86_64-unknown-linux-gnu\n"
                    "wasm32-unknown-emscripten\n"
                ),
                (str(rustc), "--print", "sysroot"): str(toolchain_root),
            }

            def checked_output(command: list[str]) -> str:
                return outputs[tuple(command)]

            with mock.patch.object(
                bootstrap, "checked_output", side_effect=checked_output
            ) as run_command:
                bootstrap.verify_rust_toolchain(
                    self.rust, toolchain_root
                )

            self.assertEqual(run_command.call_count, 3)
            for call in run_command.call_args_list:
                self.assertEqual(call.args[0][0], str(rustc))

    def test_rejects_missing_required_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            toolchain_root = Path(temporary_directory) / "rust-toolchain"
            rustc = self.create_toolchain(toolchain_root)
            outputs = {
                (str(rustc), "-Vv"): self.rustc_vv_output(),
                (str(rustc), "--print", "target-list"): (
                    "x86_64-unknown-linux-gnu\n"
                ),
            }
            with (
                mock.patch.object(
                    bootstrap,
                    "checked_output",
                    side_effect=lambda command: outputs[tuple(command)],
                ),
                self.assertRaisesRegex(
                    M0Error, "missing target wasm32-unknown-emscripten"
                ),
            ):
                bootstrap.verify_rust_toolchain(
                    self.rust, toolchain_root
                )


class RustToolchainInstallTest(unittest.TestCase):
    def test_download_checks_exact_size_and_hash(self) -> None:
        contents = b"pinned archive"
        rust = {
            "url": "https://example.test/pinned-rust.tar.xz",
            "size_bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "rust.tar.xz"
            with mock.patch.object(
                bootstrap.urllib.request,
                "urlopen",
                return_value=BytesIO(contents),
            ) as urlopen:
                bootstrap.download_rust_archive(rust, archive_path)

            request = urlopen.call_args.args[0]
            self.assertEqual(request.full_url, rust["url"])
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 120)
            self.assertEqual(archive_path.read_bytes(), contents)

    def test_bad_hash_is_rejected_before_extraction(self) -> None:
        contents = b"not the pinned archive"
        rust = {
            "archive": "rust.tar.xz",
            "url": "https://example.test/pinned-rust.tar.xz",
            "size_bytes": len(contents),
            "sha256": "0" * 64,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory) / "third_party"
            parent.mkdir()
            toolchain_root = parent / "rust-toolchain"
            with (
                mock.patch.object(
                    bootstrap.urllib.request,
                    "urlopen",
                    return_value=BytesIO(contents),
                ),
                mock.patch.object(bootstrap.tarfile, "open") as tar_open,
                self.assertRaisesRegex(M0Error, "archive hash mismatch"),
            ):
                bootstrap.install_rust_toolchain(rust, toolchain_root)

            tar_open.assert_not_called()
            self.assertFalse(toolchain_root.exists())
            self.assertEqual(list(parent.glob(".rust-toolchain.install-*")), [])

    def test_unsafe_archive_path_is_rejected(self) -> None:
        archive_buffer = BytesIO()
        with tarfile.open(
            fileobj=archive_buffer, mode="w:xz"
        ) as archive:
            contents = b"escape"
            member = tarfile.TarInfo("../outside")
            member.size = len(contents)
            archive.addfile(member, BytesIO(contents))
        contents = archive_buffer.getvalue()
        rust = {
            "archive": "rust.tar.xz",
            "url": "https://example.test/pinned-rust.tar.xz",
            "size_bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory) / "third_party"
            parent.mkdir()
            toolchain_root = parent / "rust-toolchain"
            with (
                mock.patch.object(
                    bootstrap.urllib.request,
                    "urlopen",
                    return_value=BytesIO(contents),
                ),
                self.assertRaisesRegex(
                    M0Error, "failed to extract pinned Chromium Rust archive"
                ),
            ):
                bootstrap.install_rust_toolchain(rust, toolchain_root)

            self.assertFalse((parent / "outside").exists())
            self.assertFalse(toolchain_root.exists())
            self.assertEqual(list(parent.glob(".rust-toolchain.install-*")), [])

    def test_installs_from_sibling_staging_directory_atomically(self) -> None:
        archive_buffer = BytesIO()
        version_contents = b"staged VERSION\n"
        with tarfile.open(
            fileobj=archive_buffer, mode="w:xz"
        ) as archive:
            member = tarfile.TarInfo("VERSION")
            member.size = len(version_contents)
            archive.addfile(member, BytesIO(version_contents))
        contents = archive_buffer.getvalue()
        rust = {
            "archive": "rust.tar.xz",
            "url": "https://example.test/pinned-rust.tar.xz",
            "size_bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory) / "third_party"
            parent.mkdir()
            toolchain_root = parent / "rust-toolchain"
            with (
                mock.patch.object(
                    bootstrap.urllib.request,
                    "urlopen",
                    return_value=BytesIO(contents),
                ),
                mock.patch.object(
                    bootstrap, "verify_rust_toolchain"
                ) as verify,
                mock.patch.object(
                    bootstrap.os, "replace", wraps=bootstrap.os.replace
                ) as replace,
            ):
                bootstrap.install_rust_toolchain(rust, toolchain_root)

            candidate_root = verify.call_args.args[1]
            self.assertEqual(candidate_root.parent.parent, parent)
            self.assertEqual(replace.call_args.args[1], toolchain_root)
            self.assertEqual(
                (toolchain_root / "VERSION").read_bytes(),
                version_contents,
            )
            self.assertEqual(list(parent.glob(".rust-toolchain.install-*")), [])

    def test_preserves_an_existing_invalid_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            toolchain_root = Path(temporary_directory) / "rust-toolchain"
            toolchain_root.mkdir()
            marker = toolchain_root / "keep-me"
            marker.write_text("user state", encoding="utf-8")
            with (
                mock.patch.object(
                    bootstrap,
                    "verify_rust_toolchain",
                    side_effect=M0Error("invalid existing toolchain"),
                ),
                mock.patch.object(
                    bootstrap.urllib.request, "urlopen"
                ) as urlopen,
                self.assertRaisesRegex(
                    M0Error,
                    "existing Chromium Rust toolchain is invalid; "
                    "refusing to overwrite it",
                ),
            ):
                bootstrap.install_rust_toolchain({}, toolchain_root)

            urlopen.assert_not_called()
            self.assertEqual(marker.read_text(encoding="utf-8"), "user state")

    def test_verify_only_never_invokes_installer_or_network(self) -> None:
        manifest = {"rust": {"path": "third_party/rust-toolchain"}}
        with (
            mock.patch.object(bootstrap, "verify_rust_deps_pin"),
            mock.patch.object(bootstrap, "verify_rust_source_pins"),
            mock.patch.object(
                bootstrap, "verify_rust_toolchain"
            ) as verify,
            mock.patch.object(
                bootstrap, "install_rust_toolchain"
            ) as install,
            mock.patch.object(
                bootstrap.urllib.request, "urlopen"
            ) as urlopen,
        ):
            bootstrap.ensure_rust_toolchain(manifest, install=False)

        install.assert_not_called()
        urlopen.assert_not_called()
        verify.assert_called_once_with(
            manifest["rust"],
            bootstrap.REPO_ROOT / "third_party/rust-toolchain",
        )


if __name__ == "__main__":
    unittest.main()

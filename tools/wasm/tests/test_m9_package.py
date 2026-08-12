#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from copy import deepcopy

from tools.wasm import package
from tools.wasm.m0_common import REPO_ROOT, load_manifest
from tools.wasm.run_m9_package_smoke import package_response, run_package_smoke


PORT_REVISION = "a" * 40


class M9PackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.manifest = load_manifest()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _make_out_dir(self, name: str = "out") -> Path:
        out_dir = self.root / name
        out_dir.mkdir()
        (out_dir / "chrome_wasm.js").write_text(
            'const wasm = "chrome_wasm.wasm";\n'
            "export default async function() { return {wasm}; }\n",
            encoding="utf-8",
        )
        (out_dir / "chrome_wasm.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
        (out_dir / "args.gn").write_text(
            'target_os = "emscripten"\n'
            'target_cpu = "wasm"\n'
            'v8_snapshot_toolchain_runtime_root = "//out/runtime"\n',
            encoding="utf-8",
        )
        return out_dir

    def _stage(self, *, out_dir: Path | None = None, name: str = "dist") -> Path:
        dist_dir = self.root / name
        package.package_release(
            out_dir=out_dir or self._make_out_dir(),
            dist_dir=dist_dir,
            module_name="chrome_wasm",
            manifest=self.manifest,
            port_revision=PORT_REVISION,
        )
        return dist_dir

    def _snapshot(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_stages_exact_layout_with_honest_pre_release_metadata(self) -> None:
        dist_dir = self._stage()
        result = package.verify_release_tree(dist_dir)

        self.assertEqual(
            {
                "LICENSES/Chromium-LICENSE.txt",
                "LICENSES/PRE_RELEASE_NOTICE.txt",
                "README.txt",
                "VERSION.json",
                "chromium-wasm-clipboard-input.js",
                "chromium-wasm-host.js",
                "chromium-wasm-pointer-input.js",
                "chromium-wasm-storage-estimate.js",
                "chromium-wasm-text-input.js",
                "chromium-wasm.js",
                "chromium-wasm.wasm",
                "index.html",
            },
            set(self._snapshot(dist_dir)),
        )
        self.assertEqual("pre_m7_m8_not_releasable", result["release_status"])

        version = json.loads((dist_dir / "VERSION.json").read_text("utf-8"))
        self.assertEqual(package.PACKAGE_SCHEMA_VERSION, version["schema_version"])
        self.assertEqual(package.RELEASE_STATUS, version["release_status"])
        self.assertNotIn("port", version["versions"])
        self.assertEqual(PORT_REVISION, version["build"]["staging_checkout"])
        self.assertEqual(
            "unverified", version["build"]["artifact_source_provenance"]
        )
        self.assertEqual(
            "embedded-in-wasm-current-build", version["build"]["resource_delivery"]
        )
        self.assertEqual(
            package.REQUIRED_HEADERS, version["host"]["required_headers"]
        )
        self.assertNotIn("VERSION.json", [
            record["path"] for record in version["artifacts"]
        ])
        self.assertIn(
            "not a distributable", (dist_dir / "README.txt").read_text("utf-8")
        )
        self.assertIn(
            "not a verified source identity",
            (dist_dir / "README.txt").read_text("utf-8"),
        )
        self.assertIn(
            "does not contain a complete", (dist_dir / "LICENSES/PRE_RELEASE_NOTICE.txt").read_text(
                "utf-8"
            ),
        )

    def test_staging_is_byte_reproducible(self) -> None:
        first = self._stage(out_dir=self._make_out_dir("first-out"), name="first")
        second = self._stage(out_dir=self._make_out_dir("second-out"), name="second")

        self.assertEqual(self._snapshot(first), self._snapshot(second))
        self.assertEqual(0, (first / "chromium-wasm.js").stat().st_mtime)
        self.assertEqual(0, (second / "VERSION.json").stat().st_mtime)

    def test_rejects_nonempty_or_overlapping_destination(self) -> None:
        out_dir = self._make_out_dir()
        nonempty = self.root / "nonempty"
        nonempty.mkdir()
        marker = nonempty / "preserve-me"
        marker.write_text("user data", encoding="utf-8")
        with self.assertRaisesRegex(package.PackageError, "not empty"):
            package.package_release(
                out_dir=out_dir,
                dist_dir=nonempty,
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=PORT_REVISION,
            )
        self.assertEqual("user data", marker.read_text("utf-8"))

        with self.assertRaisesRegex(package.PackageError, "overlap the build output"):
            package.package_release(
                out_dir=out_dir,
                dist_dir=out_dir / "nested-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=PORT_REVISION,
            )

        repository_destination = REPO_ROOT / ".m9-package-test-never-created"
        with self.assertRaisesRegex(package.PackageError, "repository root"):
            package.package_release(
                out_dir=out_dir,
                dist_dir=repository_destination,
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=PORT_REVISION,
            )
        self.assertFalse(repository_destination.exists())

    def test_rejects_symlinked_destination_component(self) -> None:
        out_dir = self._make_out_dir()
        actual_parent = self.root / "actual-parent"
        actual_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        os.symlink(actual_parent, linked_parent)

        with self.assertRaisesRegex(package.PackageError, "symlink component"):
            package.package_release(
                out_dir=out_dir,
                dist_dir=linked_parent / "dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=PORT_REVISION,
            )

    def test_rejects_manifest_that_does_not_match_checked_out_provenance(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["chromium"]["revision"] = "b" * 40
        with self.assertRaisesRegex(package.PackageError, "checked-out toolchain"):
            package.package_release(
                out_dir=self._make_out_dir(),
                dist_dir=self.root / "dist",
                module_name="chrome_wasm",
                manifest=manifest,
                port_revision=PORT_REVISION,
            )

    def test_rejects_generated_runtime_sidecars_not_in_the_package_layout(self) -> None:
        out_dir = self._make_out_dir()
        (out_dir / "chrome_wasm.data").write_bytes(b"sidecar")
        with self.assertRaisesRegex(package.PackageError, "external sidecar"):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=PORT_REVISION,
            )

    def test_verification_rejects_tampering(self) -> None:
        dist_dir = self._stage()
        with (dist_dir / "chromium-wasm.wasm").open("ab") as output:
            output.write(b"tamper")
        with self.assertRaisesRegex(package.PackageError, "hash mismatch"):
            package.verify_release_tree(dist_dir)

    def test_verification_requires_unverified_artifact_source_provenance(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        version["build"]["artifact_source_provenance"] = "verified"
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "source provenance"):
            package.verify_release_tree(dist_dir)

    def test_verification_requires_a_git_staging_checkout(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        version["build"]["staging_checkout"] = "unverified"
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "staging checkout"):
            package.verify_release_tree(dist_dir)

    def test_static_package_response_contract(self) -> None:
        dist_dir = self._stage()
        for request_path, expected_mime in {
            "/": "text/html; charset=utf-8",
            "/chromium-wasm.js": "text/javascript; charset=utf-8",
            "/chromium-wasm.wasm": "application/wasm",
            "/VERSION.json": "application/json; charset=utf-8",
        }.items():
            with self.subTest(request_path=request_path):
                status, content_type, body = package_response(dist_dir, request_path)
                self.assertEqual(200, status)
                self.assertEqual(expected_mime, content_type)
                self.assertTrue(body)
        self.assertEqual(
            404, package_response(dist_dir, "/../VERSION.json")[0]
        )

    def test_static_package_socket_smoke_when_loopback_is_available(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
        except PermissionError:
            self.skipTest("test sandbox does not permit loopback socket binding")

        result = run_package_smoke(self._stage())
        self.assertEqual("pre_m7_m8_not_releasable", result["release_status"])
        self.assertEqual(
            "static-package-headers-mime-and-artifact-integrity-only", result["scope"]
        )
        endpoints = result["endpoints"]
        self.assertEqual(
            "application/wasm", endpoints["/chromium-wasm.wasm"]["content_type"]
        )

    def test_release_host_is_not_an_m6_test_route(self) -> None:
        host = (REPO_ROOT / "tools/wasm/host/release_host.js").read_text(
            encoding="utf-8"
        )
        index = (REPO_ROOT / "tools/wasm/host/release_index.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("/__m6__/", host)
        self.assertNotIn("/__m6__/", index)
        self.assertIn('"./chromium-wasm.js"', host)
        for module in (
            "chromium-wasm-pointer-input.js",
            "chromium-wasm-text-input.js",
            "chromium-wasm-clipboard-input.js",
            "chromium-wasm-storage-estimate.js",
        ):
            with self.subTest(module=module):
                self.assertIn(module, host)
        self.assertIn("pre_m7_m8_not_releasable", host)
        self.assertIn("not passed the M7/M8/M9", index)
        self.assertIn("staging checkout", host)
        self.assertIn("artifact source provenance", host)
        self.assertIn('artifact_source_provenance !== "unverified"', host)
        self.assertIn("not verified as the source identity", index)

    def test_browser_smoke_requires_the_blob_backed_renamed_loader_path(self) -> None:
        smoke = (REPO_ROOT / "tools/wasm/run_m9_package_browser_smoke.py").read_text(
            encoding="utf-8"
        )
        host = (REPO_ROOT / "tools/wasm/host/release_host.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("create_package_smoke_server", smoke)
        self.assertIn("*only* the staged names", smoke)
        self.assertIn("framesPresented", smoke)
        self.assertIn("processExitCode", smoke)
        self.assertIn("shutdownDisabled", smoke)
        self.assertIn("clean fixed package-host shutdown", smoke)
        self.assertIn("package host elements are not installed yet", smoke)
        self.assertIn("pending: true", smoke)
        self.assertIn("displayedVersions", smoke)
        self.assertIn("artifact source provenance", smoke)
        self.assertIn("mainScriptUrlOrBlob", host)
        self.assertIn("inputModuleName", host)
        self.assertIn('"./chromium-wasm.wasm"', host)


if __name__ == "__main__":
    unittest.main()

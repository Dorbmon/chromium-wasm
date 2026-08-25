#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from collections import deque
import hashlib
from http import HTTPStatus
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from typing import Callable
from unittest import mock
from urllib.error import HTTPError
from urllib.request import urlopen

from tools.wasm import package
from tools.wasm import run_m9_package_browser_smoke as package_browser_smoke
from tools.wasm import run_m9_package_smoke as package_smoke
from tools.wasm.m0_common import M0Error, REPO_ROOT, load_manifest
from tools.wasm.run_m9_package_smoke import (
    create_package_smoke_server,
    package_response,
    run_package_smoke,
    snapshot_package_tree,
)


PORT_REVISION = "a" * 40
ATTESTED_CHECKOUT = {"commit": PORT_REVISION, "tree": "b" * 40}


def _runtime_core_resource_receipt() -> list[dict[str, str]]:
    return [
        {"initiator_type": initiator_type, "path": path}
        for path, initiator_type in package_browser_smoke.RUNTIME_CORE_RESOURCE_RECEIPT
    ]


def _runtime_core_server_receipt() -> list[dict[str, object]]:
    return [
        {"path": path, "successful_get_count": 1}
        for path, _initiator in package_browser_smoke.RUNTIME_CORE_RESOURCE_RECEIPT
    ]


class M9PackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.manifest = load_manifest()
        self.clean_output_directories: list[tempfile.TemporaryDirectory[str]] = []
        self.target_notice_generator = package._generate_target_third_party_notices
        self.target_notice_patch = mock.patch.object(
            package,
            "_generate_target_third_party_notices",
            side_effect=self._write_fake_target_third_party_notices,
        )
        self.target_notice_patch.start()

    def tearDown(self) -> None:
        self.target_notice_patch.stop()
        for directory in self.clean_output_directories:
            directory.cleanup()
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

    def _refresh_staged_artifact_identity(
        self, dist_dir: Path, artifact_path: str
    ) -> None:
        """Make a deliberately replaced fixture artifact match VERSION.json."""

        contents = (dist_dir / artifact_path).read_bytes()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text(encoding="utf-8"))
        record = next(
            (
                candidate
                for candidate in version["artifacts"]
                if candidate["path"] == artifact_path
            ),
            None,
        )
        self.assertIsNotNone(record)
        assert isinstance(record, dict)
        record["sha256"] = hashlib.sha256(contents).hexdigest()
        record["size_bytes"] = len(contents)
        version_path.write_bytes(package._canonical_json(version))

    def _make_attested_out_dir(self) -> tuple[Path, dict[str, object]]:
        directory = tempfile.TemporaryDirectory(
            prefix="m9-package-attested-", dir=REPO_ROOT / "out"
        )
        self.clean_output_directories.append(directory)
        out_dir = Path(directory.name)
        (out_dir / "chrome_wasm.js").write_text(
            'const wasm = "chrome_wasm.wasm";\n'
            "export default async function() { return {wasm}; }\n",
            encoding="utf-8",
        )
        (out_dir / "chrome_wasm.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
        attestation = package.clean_build_attestation
        (out_dir / "args.gn").write_bytes(
            attestation.expected_m6_chrome_gn_args(self.manifest)
        )
        current_manifest, manifest_identity = attestation.load_manifest_snapshot()
        self.assertEqual(self.manifest, current_manifest)
        record = attestation.make_attestation(
            checkout=ATTESTED_CHECKOUT,
            manifest=manifest_identity,
            gn_args=attestation.require_exact_generated_gn_args(
                out_dir,
                attestation.expected_m6_chrome_gn_args(current_manifest),
            ),
            artifacts=attestation.module_artifact_records(out_dir),
            out_dir=out_dir,
        )
        (out_dir / attestation.ATTESTATION_FILENAME).write_bytes(
            attestation._canonical_json_bytes(record)
        )
        return out_dir, record

    def _clean_attestation_patches(
        self,
    ) -> tuple[mock._patch, mock._patch, mock._patch]:
        attestation = package.clean_build_attestation
        return (
            mock.patch.object(attestation, "require_clean_top_level_checkout"),
            mock.patch.object(
                attestation, "checkout_identity", return_value=ATTESTED_CHECKOUT
            ),
            mock.patch.object(package, "_require_attested_manifest_chromium_ancestry"),
        )

    def _snapshot(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def _package_delivery_response(
        self,
        snapshot: package_smoke.PackageTreeSnapshot,
        request_path: str,
        method: str,
    ) -> package_smoke.PackageEndpointResponse:
        if request_path == "/":
            artifact = "index.html"
        else:
            artifact = request_path.removeprefix("/")
        if artifact in snapshot.artifacts:
            expected_body = snapshot.artifacts[artifact]
            status = HTTPStatus.OK
            content_type = package.REQUIRED_MIME_TYPES.get(
                Path(artifact).suffix, "text/plain; charset=utf-8"
            )
        else:
            expected_body = package_smoke.NOT_FOUND_BODY
            status = HTTPStatus.NOT_FOUND
            content_type = package_smoke.NOT_FOUND_CONTENT_TYPE
        return package_smoke.PackageEndpointResponse(
            status=status,
            headers={
                **package.REQUIRED_HEADERS,
                "Cache-Control": "no-store",
                "Content-Length": str(len(expected_body)),
                "Content-Type": content_type,
            },
            body=expected_body if method == "GET" else b"",
        )

    def _valid_package_delivery(
        self, snapshot: package_smoke.PackageTreeSnapshot
    ) -> Callable[[str, int, str, str], package_smoke.PackageEndpointResponse]:
        def deliver(
            _host: str, _port: int, request_path: str, method: str
        ) -> package_smoke.PackageEndpointResponse:
            return self._package_delivery_response(snapshot, request_path, method)

        return deliver

    def _write_fake_target_third_party_notices(
        self, *, out_dir: Path, destination: Path
    ) -> None:
        self.assertTrue(out_dir.is_dir())
        package._write_file(
            destination,
            package.TARGET_THIRD_PARTY_NOTICES_MARKER
            + b"\n--------------------\nSynthetic target notice for tests.\n",
        )

    def test_stages_exact_layout_with_honest_pre_release_metadata(self) -> None:
        dist_dir = self._stage()
        result = package.verify_release_tree(dist_dir)

        self.assertEqual(
            {
                "LICENSES/Chromium-LICENSE.txt",
                "LICENSES/PRE_RELEASE_NOTICE.txt",
                "LICENSES/THIRD_PARTY_NOTICES.txt",
                "README.txt",
                "TOOLCHAIN.json",
                "VERSION.json",
                "chromium-wasm-clipboard-input.js",
                "chromium-wasm-file-picker.js",
                "chromium-wasm-host.js",
                "chromium-wasm-pointer-input.js",
                "chromium-wasm-release-wisp-config.js",
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
        self.assertEqual(4, package.PACKAGE_SCHEMA_VERSION)
        self.assertEqual(4, version["schema_version"])
        self.assertEqual(package.RELEASE_STATUS, version["release_status"])
        self.assertEqual(package.EXPECTED_GATE_STATE, version["gate_state"])
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
        toolchain_path = dist_dir / package.TOOLCHAIN_MANIFEST_PACKAGE_PATH
        self.assertEqual(
            (REPO_ROOT / "tools/wasm/toolchain_manifest.json").read_bytes(),
            toolchain_path.read_bytes(),
        )
        self.assertEqual(
            package.sha256_file(toolchain_path),
            version["toolchain_manifest"]["sha256"],
        )
        toolchain_record = next(
            record
            for record in version["artifacts"]
            if record["path"] == package.TOOLCHAIN_MANIFEST_PACKAGE_PATH
        )
        self.assertEqual(
            version["toolchain_manifest"]["sha256"], toolchain_record["sha256"]
        )
        self.assertEqual(toolchain_path.stat().st_size, toolchain_record["size_bytes"])
        notice_path = dist_dir / package.TARGET_THIRD_PARTY_NOTICES_PATH
        notice_record = next(
            record
            for record in version["artifacts"]
            if record["path"] == package.TARGET_THIRD_PARTY_NOTICES_PATH
        )
        self.assertEqual(package.sha256_file(notice_path), notice_record["sha256"])
        self.assertEqual(notice_path.stat().st_size, notice_record["size_bytes"])
        self.assertIn(
            package.TARGET_THIRD_PARTY_NOTICES_MARKER,
            notice_path.read_bytes(),
        )
        self.assertIn(
            "not a distributable", (dist_dir / "README.txt").read_text("utf-8")
        )
        self.assertIn(
            "not a verified source identity",
            (dist_dir / "README.txt").read_text("utf-8"),
        )
        self.assertIn(
            "__chromiumWasmReleaseWispV1",
            (dist_dir / "README.txt").read_text("utf-8"),
        )
        self.assertIn(
            "networking is explicitly unavailable",
            (dist_dir / "README.txt").read_text("utf-8"),
        )
        self.assertIn(
            "does not contain a complete", (dist_dir / "LICENSES/PRE_RELEASE_NOTICE.txt").read_text(
                "utf-8"
            ),
        )
        self.assertIn(
            "does not establish Emscripten",
            (dist_dir / "LICENSES/PRE_RELEASE_NOTICE.txt").read_text("utf-8"),
        )
        self.assertIn(
            "Emscripten toolchain/runtime",
            " ".join(version["known_limitations"]),
        )

    def test_runtime_status_metadata_is_fixed_snapshot_projection(self) -> None:
        dist_dir = self._stage()
        version_bytes = (dist_dir / "VERSION.json").read_bytes()
        metadata = package.package_runtime_status_metadata(version_bytes)

        self.assertEqual(
            {
                "build",
                "gateState",
                "product",
                "protocol",
                "releaseStatus",
                "schemaVersion",
                "versionJsonSha256",
                "versions",
            },
            set(metadata),
        )
        self.assertEqual(package.PACKAGE_RUNTIME_STATUS_PROTOCOL, metadata["protocol"])
        self.assertEqual(package.PRODUCT_NAME, metadata["product"])
        self.assertEqual(package.RELEASE_STATUS, metadata["releaseStatus"])
        self.assertEqual(package.PACKAGE_SCHEMA_VERSION, metadata["schemaVersion"])
        self.assertEqual(package.EXPECTED_GATE_STATE, metadata["gateState"])
        self.assertEqual(
            package.ARTIFACT_SOURCE_PROVENANCE_UNVERIFIED,
            metadata["build"]["artifactSourceProvenance"],
        )
        self.assertEqual(
            hashlib.sha256(version_bytes).hexdigest(), metadata["versionJsonSha256"]
        )
        self.assertNotIn("release provenance", repr(metadata).lower())
        self.assertNotIn("source identity", repr(metadata).lower())

    def test_runtime_status_metadata_rejects_substituted_or_noncanonical_version(
        self,
    ) -> None:
        version_path = self._stage() / "VERSION.json"
        version_bytes = version_path.read_bytes()
        version = json.loads(version_bytes.decode("utf-8"))
        version["release_status"] = "releasable"
        with self.assertRaisesRegex(package.PackageError, "pre-release status"):
            package.package_runtime_status_metadata(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "duplicate JSON object key"):
            package.package_runtime_status_metadata(
                b'{"artifacts":[],"artifacts":[]}'
            )

    def test_target_notice_generator_uses_chromium_target_aware_command(
        self,
    ) -> None:
        out_dir = self._make_out_dir()
        destination = self.root / "target-notice.txt"
        commands: list[list[str]] = []

        def generate_notice(
            command: list[str], *, cwd: Path, timeout: float
        ) -> mock.Mock:
            commands.append(command)
            self.assertEqual(REPO_ROOT, cwd)
            self.assertEqual(120.0, timeout)
            destination.write_bytes(
                package.TARGET_THIRD_PARTY_NOTICES_MARKER + b"\nnotice\n"
            )
            return mock.Mock()

        with mock.patch.object(package, "run", side_effect=generate_notice):
            self.target_notice_generator(
                out_dir=out_dir,
                destination=destination,
            )

        self.assertEqual(
            [
                [
                    sys.executable,
                    str(package.LICENSES_SCRIPT),
                    "license_file",
                    "--gn-out-dir",
                    str(out_dir),
                    "--gn-target",
                    "//chrome:chrome_wasm",
                    "--target-os",
                    "emscripten",
                    "--format",
                    "notice",
                    str(destination),
                ]
            ],
            commands,
        )
        self.assertEqual(0o644, destination.stat().st_mode & 0o777)
        self.assertEqual(0, destination.stat().st_mtime)

    def test_staging_rejects_missing_generated_target_notice(self) -> None:
        with mock.patch.object(
            package,
            "_generate_target_third_party_notices",
            return_value=None,
        ), self.assertRaisesRegex(package.PackageError, "target third-party notices"):
            self._stage()

    def test_staging_rejects_an_input_module_not_bound_to_target_notices(self) -> None:
        generator = mock.Mock()
        with mock.patch.object(
            package,
            "_generate_target_third_party_notices",
            generator,
        ), self.assertRaisesRegex(
            package.PackageError, "only supports the chrome_wasm input module"
        ):
            package.package_release(
                out_dir=self._make_out_dir(),
                dist_dir=self.root / "alternate-module-dist",
                module_name="alternate_wasm",
                manifest=self.manifest,
                port_revision=PORT_REVISION,
            )
        generator.assert_not_called()

    def test_verification_rejects_substituted_target_notice(self) -> None:
        dist_dir = self._stage()
        (dist_dir / package.TARGET_THIRD_PARTY_NOTICES_PATH).write_bytes(
            b"substituted target notice\n"
        )

        with self.assertRaisesRegex(
            package.PackageError,
            "hash mismatch: LICENSES/THIRD_PARTY_NOTICES.txt",
        ):
            package.verify_release_tree(dist_dir)

    def test_verification_rejects_unhashed_target_notice(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        version["artifacts"] = [
            record
            for record in version["artifacts"]
            if record["path"] != package.TARGET_THIRD_PARTY_NOTICES_PATH
        ]
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(
            package.PackageError, "artifacts are not complete and ordered"
        ):
            package.verify_release_tree(dist_dir)

    def test_verification_rejects_substituted_input_module_identity(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        version["build"]["input_module_name"] = "alternate_wasm"
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "module name is invalid"):
            package.verify_release_tree(dist_dir)

    def test_staging_is_byte_reproducible(self) -> None:
        first = self._stage(out_dir=self._make_out_dir("first-out"), name="first")
        second = self._stage(out_dir=self._make_out_dir("second-out"), name="second")

        self.assertEqual(self._snapshot(first), self._snapshot(second))
        self.assertEqual(0, (first / "chromium-wasm.js").stat().st_mtime)
        self.assertEqual(0, (second / "VERSION.json").stat().st_mtime)

    def test_default_stage_ignores_an_optional_clean_build_record(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        attestation = package.clean_build_attestation
        with mock.patch.object(
            attestation,
            "require_clean_top_level_checkout",
            side_effect=AssertionError("default package staging must not attest"),
        ), mock.patch.object(
            package,
            "_require_attested_manifest_chromium_ancestry",
            side_effect=AssertionError("default package staging must stay unverified"),
        ):
            dist_dir = self._stage(out_dir=out_dir)

        version = json.loads((dist_dir / "VERSION.json").read_text("utf-8"))
        self.assertEqual(
            package.ARTIFACT_SOURCE_PROVENANCE_UNVERIFIED,
            version["build"]["artifact_source_provenance"],
        )
        self.assertIn(
            "not a verified source identity",
            (dist_dir / "README.txt").read_text("utf-8"),
        )

    def test_attested_stage_rejects_rewritten_same_tree_source_identity(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        first_patch, second_patch, _ = self._clean_attestation_patches()
        chromium = self.manifest["chromium"]
        assert isinstance(chromium, dict)
        chromium_revision = chromium["revision"]
        assert isinstance(chromium_revision, str)
        with (
            first_patch,
            second_patch,
            mock.patch.object(
                package,
                "run",
                side_effect=(None, M0Error("not an ancestor")),
            ) as git,
            self.assertRaisesRegex(
                package.PackageError,
                "identical tree or rewritten commit is not accepted",
            ),
        ):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "rewritten-source-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=ATTESTED_CHECKOUT["commit"],
                clean_build_attestation_path=(
                    out_dir / package.clean_build_attestation.ATTESTATION_FILENAME
                ),
            )
        self.assertEqual(
            [
                mock.call(
                    ["git", "cat-file", "-e", f"{chromium_revision}^{{commit}}"]
                ),
                mock.call(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        chromium_revision,
                        ATTESTED_CHECKOUT["commit"],
                    ]
                ),
            ],
            git.call_args_list,
        )
        self.assertFalse((self.root / "rewritten-source-dist").exists())

    def test_stages_exact_matching_clean_build_attestation(self) -> None:
        out_dir, record = self._make_attested_out_dir()
        first_patch, second_patch, third_patch = self._clean_attestation_patches()
        with first_patch as clean, second_patch as checkout, third_patch as source:
            result = package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "attested-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=ATTESTED_CHECKOUT["commit"],
                clean_build_attestation_path=(
                    out_dir / package.clean_build_attestation.ATTESTATION_FILENAME
                ),
            )

        self.assertEqual(
            package.ARTIFACT_SOURCE_PROVENANCE_LOCAL_CLEAN_BUILD_ATTESTED,
            result["artifact_source_provenance"],
        )
        self.assertEqual(2, clean.call_count)
        self.assertEqual(2, checkout.call_count)
        self.assertEqual(2, source.call_count)
        self.assertEqual(
            package.ARTIFACT_SOURCE_PROVENANCE_LOCAL_CLEAN_BUILD_ATTESTED,
            package.verify_release_tree(self.root / "attested-dist")[
                "artifact_source_provenance"
            ],
        )
        version = json.loads(
            (self.root / "attested-dist" / "VERSION.json").read_text("utf-8")
        )
        self.assertEqual(
            package.ARTIFACT_SOURCE_PROVENANCE_LOCAL_CLEAN_BUILD_ATTESTED,
            version["build"]["artifact_source_provenance"],
        )
        self.assertEqual(
            ATTESTED_CHECKOUT["commit"], version["build"]["staging_checkout"]
        )
        self.assertEqual(record["artifacts"]["chrome_wasm.js"]["sha256"], next(
            item["sha256"]
            for item in version["artifacts"]
            if item["path"] == "chromium-wasm.js"
        ))
        self.assertIn(
            "local clean-build attestation",
            (self.root / "attested-dist" / "README.txt").read_text("utf-8"),
        )
        self.assertIn(
            "same-tree rewritten commit",
            (self.root / "attested-dist" / "README.txt").read_text("utf-8"),
        )
        self.assertIn(
            "not release provenance",
            " ".join(version["known_limitations"]),
        )

    def test_attested_stage_rejects_record_that_does_not_match_artifacts(self) -> None:
        out_dir, record = self._make_attested_out_dir()
        record["artifacts"]["chrome_wasm.wasm"]["sha256"] = "0" * 64
        attestation_path = (
            out_dir / package.clean_build_attestation.ATTESTATION_FILENAME
        )
        attestation_path.write_bytes(
            package.clean_build_attestation._canonical_json_bytes(record)
        )
        first_patch, second_patch, third_patch = self._clean_attestation_patches()
        with first_patch, second_patch, third_patch, self.assertRaisesRegex(
            package.PackageError, "does not exactly match"
        ):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "mismatched-attested-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=ATTESTED_CHECKOUT["commit"],
                clean_build_attestation_path=attestation_path,
            )

    def test_attested_stage_rejects_stale_selected_artifact(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        (out_dir / "chrome_wasm.wasm").write_bytes(b"\x00asm-stale-module")
        first_patch, second_patch, third_patch = self._clean_attestation_patches()
        with first_patch, second_patch, third_patch, self.assertRaisesRegex(
            package.PackageError, "does not exactly match"
        ):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "stale-attested-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=ATTESTED_CHECKOUT["commit"],
                clean_build_attestation_path=(
                    out_dir / package.clean_build_attestation.ATTESTATION_FILENAME
                ),
            )

    def test_attested_stage_rejects_gn_args_that_no_longer_match_m6(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        (out_dir / "args.gn").write_text('is_debug = true\n', encoding="utf-8")
        first_patch, second_patch, third_patch = self._clean_attestation_patches()
        with first_patch, second_patch, third_patch, self.assertRaisesRegex(
            package.PackageError, "cannot be validated"
        ):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "wrong-args-attested-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=ATTESTED_CHECKOUT["commit"],
                clean_build_attestation_path=(
                    out_dir / package.clean_build_attestation.ATTESTATION_FILENAME
                ),
            )

    def test_attested_stage_rejects_record_outside_selected_output(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        copied_record = self.root / "copied-attestation.json"
        copied_record.write_bytes(
            (
                out_dir / package.clean_build_attestation.ATTESTATION_FILENAME
            ).read_bytes()
        )
        with self.assertRaisesRegex(package.PackageError, "selected build output"):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "wrong-attestation-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=ATTESTED_CHECKOUT["commit"],
                clean_build_attestation_path=copied_record,
            )

    def test_attested_stage_requires_current_clean_checkout(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        attestation = package.clean_build_attestation
        with mock.patch.object(
            attestation,
            "require_clean_top_level_checkout",
            side_effect=attestation.M0Error("source is dirty"),
        ), self.assertRaisesRegex(package.PackageError, "cannot be validated"):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "dirty-attested-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision=ATTESTED_CHECKOUT["commit"],
                clean_build_attestation_path=(
                    out_dir / attestation.ATTESTATION_FILENAME
                ),
            )

    def test_attested_stage_requires_the_current_attested_commit(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        first_patch, second_patch, third_patch = self._clean_attestation_patches()
        with first_patch, second_patch, third_patch, self.assertRaisesRegex(
            package.PackageError, "staging checkout does not match"
        ):
            package.package_release(
                out_dir=out_dir,
                dist_dir=self.root / "wrong-commit-attested-dist",
                module_name="chrome_wasm",
                manifest=self.manifest,
                port_revision="c" * 40,
                clean_build_attestation_path=(
                    out_dir / package.clean_build_attestation.ATTESTATION_FILENAME
                ),
            )

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

    def test_verification_rejects_unbound_toolchain_manifest_artifact(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        toolchain_record = next(
            record
            for record in version["artifacts"]
            if record["path"] == package.TOOLCHAIN_MANIFEST_PACKAGE_PATH
        )
        toolchain_record["sha256"] = "0" * 64
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(
            package.PackageError, "toolchain manifest artifact identity"
        ):
            package.verify_release_tree(dist_dir)

    def test_captured_bytes_verifier_rejects_toolchain_manifest_tampering(self) -> None:
        snapshot = snapshot_package_tree(self._stage())
        artifacts = dict(snapshot.artifacts)
        artifacts[package.TOOLCHAIN_MANIFEST_PACKAGE_PATH] += b"tamper"

        with self.assertRaisesRegex(package.PackageError, "hash mismatch"):
            package.verify_release_snapshot(artifacts)

    def test_verification_rejects_self_consistent_toolchain_version_substitution(
        self,
    ) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        toolchain_path = dist_dir / package.TOOLCHAIN_MANIFEST_PACKAGE_PATH
        toolchain = json.loads(toolchain_path.read_text("utf-8"))
        toolchain["chromium"]["revision"] = "b" * 40
        toolchain_bytes = package._canonical_json(toolchain)
        toolchain_path.write_bytes(toolchain_bytes)
        toolchain_sha256 = hashlib.sha256(toolchain_bytes).hexdigest()
        version["toolchain_manifest"]["sha256"] = toolchain_sha256
        toolchain_record = next(
            record
            for record in version["artifacts"]
            if record["path"] == package.TOOLCHAIN_MANIFEST_PACKAGE_PATH
        )
        toolchain_record["sha256"] = toolchain_sha256
        toolchain_record["size_bytes"] = len(toolchain_bytes)
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(
            package.PackageError,
            "bundled toolchain manifest versions do not match VERSION.json",
        ):
            package.verify_release_tree(dist_dir)

    def test_captured_bytes_verifier_rejects_self_consistent_toolchain_version_substitution(
        self,
    ) -> None:
        snapshot = snapshot_package_tree(self._stage())
        artifacts = dict(snapshot.artifacts)
        version = json.loads(artifacts["VERSION.json"].decode("utf-8"))
        toolchain = json.loads(
            artifacts[package.TOOLCHAIN_MANIFEST_PACKAGE_PATH].decode("utf-8")
        )
        toolchain["git_dependencies"]["v8"]["revision"] = "b" * 40
        toolchain_bytes = package._canonical_json(toolchain)
        toolchain_sha256 = hashlib.sha256(toolchain_bytes).hexdigest()
        artifacts[package.TOOLCHAIN_MANIFEST_PACKAGE_PATH] = toolchain_bytes
        version["toolchain_manifest"]["sha256"] = toolchain_sha256
        toolchain_record = next(
            record
            for record in version["artifacts"]
            if record["path"] == package.TOOLCHAIN_MANIFEST_PACKAGE_PATH
        )
        toolchain_record["sha256"] = toolchain_sha256
        toolchain_record["size_bytes"] = len(toolchain_bytes)
        artifacts["VERSION.json"] = package._canonical_json(version)

        with self.assertRaisesRegex(
            package.PackageError,
            "bundled toolchain manifest versions do not match VERSION.json",
        ):
            package.verify_release_snapshot(artifacts)

    def test_verification_rejects_unknown_artifact_source_provenance(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        version["build"]["artifact_source_provenance"] = "verified"
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "source provenance"):
            package.verify_release_tree(dist_dir)

    def test_verification_rejects_nonstring_artifact_source_provenance(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        version["build"]["artifact_source_provenance"] = []
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "source provenance"):
            package.verify_release_tree(dist_dir)

    def test_verification_rejects_legacy_schema_version(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        version["schema_version"] = 2
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "unsupported schema version"):
            package.verify_release_tree(dist_dir)

    def test_verification_rejects_missing_gate_state(self) -> None:
        dist_dir = self._stage()
        version_path = dist_dir / "VERSION.json"
        version = json.loads(version_path.read_text("utf-8"))
        del version["gate_state"]
        version_path.write_bytes(package._canonical_json(version))

        with self.assertRaisesRegex(package.PackageError, "package schema"):
            package.verify_release_tree(dist_dir)

    def test_verification_rejects_gate_state_mutations(self) -> None:
        mutations: dict[str, Callable[[dict[str, object]], object]] = {
            "missing": lambda state: state.pop("m8_complete"),
            "extra": lambda state: state.__setitem__("future_gate", False),
            "zero": lambda state: state.__setitem__(
                "page_webassembly_enabled", 0
            ),
            "one": lambda state: state.__setitem__("m9_release_complete", 1),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                dist_dir = self._stage(
                    out_dir=self._make_out_dir(f"out-gate-state-{name}"),
                    name=f"gate-state-{name}",
                )
                version_path = dist_dir / "VERSION.json"
                version = json.loads(version_path.read_text("utf-8"))
                mutate(version["gate_state"])
                version_path.write_bytes(package._canonical_json(version))

                with self.assertRaisesRegex(package.PackageError, "gate state"):
                    package.verify_release_tree(dist_dir)

        for gate_name in package.EXPECTED_GATE_STATE:
            with self.subTest(name=f"true-{gate_name}"):
                dist_dir = self._stage(
                    out_dir=self._make_out_dir(
                        f"out-gate-state-true-{gate_name}"
                    ),
                    name=f"gate-state-true-{gate_name}",
                )
                version_path = dist_dir / "VERSION.json"
                version = json.loads(version_path.read_text("utf-8"))
                version["gate_state"][gate_name] = True
                version_path.write_bytes(package._canonical_json(version))

                with self.assertRaisesRegex(package.PackageError, "gate state"):
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
        snapshot = snapshot_package_tree(dist_dir)
        self.assertEqual(package.PACKAGE_PATHS, set(snapshot.artifacts))
        for request_path, expected_mime in {
            "/": "text/html; charset=utf-8",
            "/chromium-wasm.js": "text/javascript; charset=utf-8",
            "/chromium-wasm.wasm": "application/wasm",
            "/TOOLCHAIN.json": "application/json; charset=utf-8",
            "/VERSION.json": "application/json; charset=utf-8",
            "/LICENSES/THIRD_PARTY_NOTICES.txt": "text/plain; charset=utf-8",
        }.items():
            with self.subTest(request_path=request_path):
                status, content_type, body = package_response(
                    snapshot.artifacts, request_path
                )
                self.assertEqual(200, status)
                self.assertEqual(expected_mime, content_type)
                self.assertTrue(body)
        self.assertEqual(
            404, package_response(snapshot.artifacts, "/../VERSION.json")[0]
        )

    def test_package_snapshot_rejects_artifact_replacement_during_capture(self) -> None:
        dist_dir = self._stage()
        original_read = package_smoke._read_snapshot_file
        replaced = False

        def replace_after_copy(
            root_fd: int, relative: str, description: str
        ) -> tuple[bytes, package_smoke.ArtifactIdentity]:
            nonlocal replaced
            capture = original_read(root_fd, relative, description)
            if relative == "chromium-wasm.js" and not replaced:
                replacement = dist_dir / ".chromium-wasm.js.replacement"
                replacement.write_bytes(capture[0])
                replacement.replace(dist_dir / relative)
                replaced = True
            return capture

        with mock.patch.object(
            package_smoke,
            "_read_snapshot_file",
            side_effect=replace_after_copy,
        ), self.assertRaisesRegex(M0Error, "changed while it was snapshotted"):
            snapshot_package_tree(dist_dir)
        self.assertTrue(replaced)
        self.assertTrue(package.verify_release_tree(dist_dir))

    def test_package_snapshot_rejects_symlink_swap_before_fd_open(self) -> None:
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("host does not expose O_NOFOLLOW")

        dist_dir = self._stage()
        loader = dist_dir / "chromium-wasm.js"
        outside = self.root / "outside-loader.js"
        outside.write_bytes(b"outside-package-loader")
        original_open = os.open
        replaced = False

        def replace_before_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal replaced
            if path == "chromium-wasm.js" and dir_fd is not None and not replaced:
                loader.unlink()
                loader.symlink_to(outside)
                replaced = True
            return original_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(
            package_smoke.os,
            "open",
            side_effect=replace_before_open,
        ), self.assertRaisesRegex(M0Error, "cannot be opened safely"):
            snapshot_package_tree(dist_dir)
        self.assertTrue(replaced)

    def test_package_snapshot_rejects_fifo_swap_without_blocking(self) -> None:
        if not hasattr(os, "O_NONBLOCK") or not hasattr(os, "mkfifo"):
            self.skipTest("host does not expose O_NONBLOCK FIFO support")

        dist_dir = self._stage()
        loader = dist_dir / "chromium-wasm.js"
        original_open = os.open
        replaced = False
        observed_flags: int | None = None

        def replace_with_fifo_before_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal observed_flags, replaced
            if path == "chromium-wasm.js" and dir_fd is not None and not replaced:
                observed_flags = flags
                if not flags & os.O_NONBLOCK:
                    raise AssertionError("artifact open must be nonblocking")
                loader.unlink()
                os.mkfifo(loader)
                replaced = True
            return original_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(
            package_smoke.os,
            "open",
            side_effect=replace_with_fifo_before_open,
        ), self.assertRaisesRegex(M0Error, "is not a regular file"):
            snapshot_package_tree(dist_dir)

        self.assertTrue(replaced)
        if observed_flags is None:
            self.fail("FIFO replacement did not observe final artifact flags")
        self.assertNotEqual(0, observed_flags & os.O_NONBLOCK)
        self.assertEqual(
            0,
            package_smoke._no_follow_open_flags(directory=True) & os.O_NONBLOCK,
        )

    def test_package_snapshot_requires_nonblocking_artifact_open_support(self) -> None:
        with mock.patch.object(package_smoke.os, "O_NONBLOCK", 0):
            with self.assertRaisesRegex(M0Error, "O_NONBLOCK"):
                package_smoke._no_follow_open_flags(directory=False)

    def test_package_snapshot_rejects_symlinked_root_during_fd_walk(self) -> None:
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("host does not expose O_NOFOLLOW")

        dist_dir = self._stage()
        saved_root = self.root / "saved-package-root"
        outside_root = self.root / "outside-package-root"
        outside_root.mkdir()
        original_open = os.open
        replaced = False

        def replace_root_before_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal replaced
            if path == dist_dir.name and dir_fd is not None and not replaced:
                dist_dir.rename(saved_root)
                dist_dir.symlink_to(outside_root, target_is_directory=True)
                replaced = True
            return original_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(
            package_smoke.os,
            "open",
            side_effect=replace_root_before_open,
        ), self.assertRaisesRegex(M0Error, "root directory cannot be opened safely"):
            snapshot_package_tree(dist_dir)
        self.assertTrue(replaced)

    def test_package_snapshot_rejects_symlinked_intermediate_during_fd_walk(
        self,
    ) -> None:
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("host does not expose O_NOFOLLOW")

        dist_dir = self._stage()
        licenses = dist_dir / "LICENSES"
        saved_licenses = dist_dir / "saved-LICENSES"
        outside_licenses = self.root / "outside-LICENSES"
        outside_licenses.mkdir()
        original_open = os.open
        replaced = False

        def replace_intermediate_before_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal replaced
            if path == "LICENSES" and dir_fd is not None and not replaced:
                licenses.rename(saved_licenses)
                licenses.symlink_to(outside_licenses, target_is_directory=True)
                replaced = True
            return original_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(
            package_smoke.os,
            "open",
            side_effect=replace_intermediate_before_open,
        ), self.assertRaisesRegex(M0Error, "cannot be opened safely"):
            snapshot_package_tree(dist_dir)
        self.assertTrue(replaced)

    def test_package_snapshot_uses_captured_bytes_verifier(self) -> None:
        dist_dir = self._stage()
        with mock.patch.object(
            package_smoke,
            "verify_release_snapshot",
            wraps=package_smoke.verify_release_snapshot,
        ) as verify:
            snapshot = snapshot_package_tree(dist_dir)

        self.assertEqual(1, verify.call_count)
        self.assertEqual(
            "pre_m7_m8_not_releasable", snapshot.verification["release_status"]
        )
        self.assertNotIn("dist_dir", snapshot.verification)
        runner_source = (
            REPO_ROOT / "tools/wasm/run_m9_package_smoke.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("verify_release_tree", runner_source)

    def test_captured_bytes_verifier_rejects_true_m8_gate(self) -> None:
        snapshot = snapshot_package_tree(self._stage())
        artifacts = dict(snapshot.artifacts)
        version = json.loads(artifacts["VERSION.json"].decode("utf-8"))
        version["gate_state"]["m8_complete"] = True
        artifacts["VERSION.json"] = package._canonical_json(version)

        with self.assertRaisesRegex(package.PackageError, "gate state"):
            package.verify_release_snapshot(artifacts)

    def test_package_snapshot_rejects_captured_true_m8_gate(self) -> None:
        dist_dir = self._stage()
        original_read = package_smoke._read_snapshot_file
        replaced = False

        def capture_true_m8_gate(
            root_fd: int, relative: str, description: str
        ) -> tuple[bytes, package_smoke.ArtifactIdentity]:
            nonlocal replaced
            capture = original_read(root_fd, relative, description)
            if relative != "VERSION.json" or replaced:
                return capture
            version = json.loads(capture[0].decode("utf-8"))
            version["gate_state"]["m8_complete"] = True
            version["known_limitations"][0] += "x"
            replacement = package._canonical_json(version)
            self.assertEqual(len(capture[0]), len(replacement))
            replaced = True
            return replacement, capture[1]

        with mock.patch.object(
            package_smoke,
            "_read_snapshot_file",
            side_effect=capture_true_m8_gate,
        ), self.assertRaisesRegex(M0Error, "gate state"):
            snapshot_package_tree(dist_dir)
        self.assertTrue(replaced)

    def test_package_snapshot_rejects_duplicate_captured_version_json_keys(self) -> None:
        snapshot = snapshot_package_tree(self._stage())
        duplicate_version = b'{"artifacts":[],"artifacts":[]}'
        artifacts = dict(snapshot.artifacts)
        artifacts["VERSION.json"] = duplicate_version

        with self.assertRaisesRegex(package.PackageError, "duplicate JSON object key"):
            package.verify_release_snapshot(artifacts)

    def test_package_smoke_closes_server_when_thread_start_fails(self) -> None:
        snapshot = snapshot_package_tree(self._stage())
        server = mock.Mock()
        server.snapshot = snapshot
        thread = mock.Mock()
        thread.start.side_effect = RuntimeError("thread start failed")

        with mock.patch.object(
            package_smoke,
            "create_package_smoke_server",
            return_value=server,
        ), mock.patch.object(
            package_smoke.threading,
            "Thread",
            return_value=thread,
        ), self.assertRaisesRegex(RuntimeError, "thread start failed"):
            run_package_smoke(self.root / "ignored")

        server.shutdown.assert_not_called()
        server.server_close.assert_called_once_with()
        thread.join.assert_not_called()

    def test_package_smoke_rejects_server_thread_alive_after_join(self) -> None:
        snapshot = snapshot_package_tree(self._stage())
        server = mock.Mock()
        server.snapshot = snapshot
        server.server_address = ("127.0.0.1", 32123)
        thread = mock.Mock()
        thread.is_alive.return_value = True

        with mock.patch.object(
            package_smoke,
            "create_package_smoke_server",
            return_value=server,
        ), mock.patch.object(
            package_smoke.threading,
            "Thread",
            return_value=thread,
        ), mock.patch.object(
            package_smoke,
            "_fetch_package_response",
            side_effect=self._valid_package_delivery(snapshot),
        ), self.assertRaisesRegex(M0Error, "package smoke server did not stop"):
            run_package_smoke(self.root / "ignored")

        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=5)
        thread.is_alive.assert_called_once_with()

    def test_package_smoke_main_rejects_bounded_shutdown_without_pass_marker(
        self,
    ) -> None:
        """A shutdown deadline is a failure, not a static-package success."""

        snapshot = snapshot_package_tree(self._stage())
        server = mock.Mock()
        server.snapshot = snapshot
        server.server_address = ("127.0.0.1", 32123)
        thread = mock.Mock()
        thread.is_alive.return_value = False
        stdout = io.StringIO()

        with (
            mock.patch.object(
                package_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_smoke.threading,
                "Thread",
                return_value=thread,
            ),
            mock.patch.object(
                package_smoke,
                "_fetch_package_response",
                side_effect=self._valid_package_delivery(snapshot),
            ),
            mock.patch.object(
                package_smoke,
                "shutdown_server_bounded",
                side_effect=M0Error("M9 package smoke server shutdown timed out"),
            ) as shutdown,
            mock.patch.object(
                sys,
                "argv",
                ["package-smoke", "--dist-dir", str(self.root / "ignored")],
            ),
            mock.patch.object(sys, "stdout", stdout),
        ):
            self.assertEqual(1, package_smoke.main())

        self.assertIn(f"{package_smoke.SENTINEL}:SMOKE_FAIL", stdout.getvalue())
        self.assertNotIn(f"{package_smoke.SENTINEL}:SMOKE_PASS", stdout.getvalue())
        shutdown.assert_called_once_with(
            server, timeout=5, description="M9 package smoke server"
        )
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=5)
        thread.is_alive.assert_called_once_with()

    def test_package_smoke_main_rejects_live_handler_without_pass_marker(
        self,
    ) -> None:
        """A stopped serving loop alone cannot make a package smoke pass."""

        snapshot = snapshot_package_tree(self._stage())
        server = mock.Mock()
        server.snapshot = snapshot
        server.server_address = ("127.0.0.1", 32123)
        server.join_request_handlers.side_effect = M0Error(
            "M9 package smoke server request handlers did not stop"
        )
        thread = mock.Mock()
        thread.is_alive.return_value = False
        stdout = io.StringIO()

        with (
            mock.patch.object(
                package_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_smoke.threading,
                "Thread",
                return_value=thread,
            ),
            mock.patch.object(
                package_smoke,
                "_fetch_package_response",
                side_effect=self._valid_package_delivery(snapshot),
            ),
            mock.patch.object(
                sys,
                "argv",
                ["package-smoke", "--dist-dir", str(self.root / "ignored")],
            ),
            mock.patch.object(sys, "stdout", stdout),
        ):
            self.assertEqual(1, package_smoke.main())

        self.assertIn(f"{package_smoke.SENTINEL}:SMOKE_FAIL", stdout.getvalue())
        self.assertNotIn(f"{package_smoke.SENTINEL}:SMOKE_PASS", stdout.getvalue())
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=5)
        thread.is_alive.assert_called_once_with()
        server.join_request_handlers.assert_called_once_with(
            timeout=5, description="M9 package smoke server"
        )

    def test_package_smoke_preserves_endpoint_failure_when_server_stays_alive(
        self,
    ) -> None:
        snapshot = snapshot_package_tree(self._stage())
        server = mock.Mock()
        server.snapshot = snapshot
        server.server_address = ("127.0.0.1", 32123)
        thread = mock.Mock()
        thread.is_alive.return_value = True
        response = package_smoke.PackageEndpointResponse(
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            headers={},
            body=b"",
        )

        with mock.patch.object(
            package_smoke,
            "create_package_smoke_server",
            return_value=server,
        ), mock.patch.object(
            package_smoke.threading,
            "Thread",
            return_value=thread,
        ), mock.patch.object(
            package_smoke,
            "_fetch_package_response",
            return_value=response,
        ), self.assertRaisesRegex(M0Error, "package endpoint returned 500: /"):
            run_package_smoke(self.root / "ignored")

        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=5)
        thread.is_alive.assert_called_once_with()

    def test_static_package_server_serves_immutable_snapshot_after_mutation(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
        except PermissionError:
            self.skipTest("test sandbox does not permit loopback socket binding")

        dist_dir = self._stage()
        expected_loader = (dist_dir / "chromium-wasm.js").read_bytes()
        server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            (dist_dir / "chromium-wasm.js").write_bytes(b"mutated-package-loader")
            host, port = server.server_address[:2]
            with urlopen(
                f"http://{host}:{port}/chromium-wasm.js", timeout=10
            ) as response:
                self.assertEqual(200, response.status)
                self.assertEqual("text/javascript", response.headers.get_content_type())
                self.assertEqual(expected_loader, response.read())
                for name, value in package.REQUIRED_HEADERS.items():
                    self.assertEqual(value, response.headers.get(name))
            with self.assertRaises(TypeError):
                server.snapshot.artifacts["chromium-wasm.js"] = b"replacement"  # type: ignore[index]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_epoch_route_serves_unchanged_snapshot_and_records_successful_gets(
        self,
    ) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
        except PermissionError:
            self.skipTest("test sandbox does not permit loopback socket binding")

        dist_dir = self._stage()
        expected_loader = (dist_dir / "chromium-wasm.js").read_bytes()
        server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
        epoch = "epoch_token-1"
        route = server.register_epoch_route(epoch)
        self.assertEqual(
            f"{package_smoke.EPOCH_ROUTE_PREFIX}{epoch}/", route
        )
        self.assertEqual(
            (None, "/chromium-wasm.js"),
            server.resolve_epoch_scoped_request_path("/chromium-wasm.js"),
        )
        self.assertEqual(
            (epoch, "/"), server.resolve_epoch_scoped_request_path(route)
        )
        self.assertEqual(
            (epoch, "/chromium-wasm.js"),
            server.resolve_epoch_scoped_request_path(route + "chromium-wasm.js"),
        )
        for unsafe_path in (
            f"{package_smoke.EPOCH_ROUTE_PREFIX}unregistered/",
            f"{route}../VERSION.json",
            f"{route}%2e%2e/VERSION.json",
            f"{route}/VERSION.json",
            f"{package_smoke.EPOCH_ROUTE_PREFIX}{epoch}",
        ):
            with self.subTest(unsafe_path=unsafe_path):
                self.assertEqual(
                    (None, None),
                    server.resolve_epoch_scoped_request_path(unsafe_path),
                )

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            with urlopen(
                f"http://{host}:{port}/chromium-wasm.js", timeout=10
            ) as response:
                self.assertEqual(200, response.status)
                self.assertEqual(expected_loader, response.read())
            with urlopen(
                f"http://{host}:{port}{route}chromium-wasm.js", timeout=10
            ) as response:
                self.assertEqual(200, response.status)
                self.assertEqual(expected_loader, response.read())
                self.assertEqual("no-store", response.headers.get("Cache-Control"))
                for name, value in package.REQUIRED_HEADERS.items():
                    self.assertEqual(value, response.headers.get(name))
            with self.assertRaises(HTTPError) as error:
                urlopen(
                    f"http://{host}:{port}"
                    f"{package_smoke.EPOCH_ROUTE_PREFIX}unregistered/"
                    "chromium-wasm.js",
                    timeout=10,
                )
            self.assertEqual(404, error.exception.code)
            error.exception.close()
            self.assertEqual(
                {"/chromium-wasm.js": 1},
                server.epoch_successful_get_counts(epoch),
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            server.join_request_handlers(
                timeout=5, description="M9 epoch-route package server"
            )

    def test_epoch_route_rejects_reused_invalid_and_unbounded_receipts(self) -> None:
        server = create_package_smoke_server("127.0.0.1", 0, self._stage())
        try:
            for token in ("", "contains/slash", "contains space", "x" * 97):
                with self.subTest(token=token), self.assertRaisesRegex(
                    M0Error, "route token is invalid"
                ):
                    server.register_epoch_route(token)
            server.register_epoch_route("one")
            with self.assertRaisesRegex(M0Error, "token was reused"):
                server.register_epoch_route("one")
            server.register_epoch_route("two")
            server.register_epoch_route("three")
            with self.assertRaisesRegex(M0Error, "route count exceeds"):
                server.register_epoch_route("four")
            for _ in range(package_smoke.MAX_EPOCH_SUCCESSFUL_GETS + 1):
                server.record_epoch_successful_get("one", "/chromium-wasm.js")
            with self.assertRaisesRegex(M0Error, "receipt exceeded its bound"):
                server.epoch_successful_get_counts("one")
            with self.assertRaisesRegex(M0Error, "route is not registered"):
                server.epoch_successful_get_counts("missing")
        finally:
            server.server_close()

    def test_package_browser_metadata_uses_immutable_server_version_snapshot(
        self,
    ) -> None:
        dist_dir = self._stage()
        expected = package.package_runtime_status_metadata(
            (dist_dir / "VERSION.json").read_bytes()
        )
        server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
        try:
            version_path = dist_dir / "VERSION.json"
            mutated = json.loads(version_path.read_text("utf-8"))
            mutated["build"]["staging_checkout"] = "b" * 40
            version_path.write_bytes(package._canonical_json(mutated))

            self.assertEqual(
                expected,
                package_browser_smoke._runtime_metadata_from_server_snapshot(server),
            )
            self.assertNotEqual(
                expected,
                package.package_runtime_status_metadata(version_path.read_bytes()),
            )
        finally:
            server.server_close()

    def test_package_browser_rejects_missing_extra_or_substituted_runtime_metadata(
        self,
    ) -> None:
        expected = package.package_runtime_status_metadata(
            (self._stage() / "VERSION.json").read_bytes()
        )
        url = package_browser_smoke._make_epoch_url(
            "http://127.0.0.1:32123/", "metadata-epoch"
        )

        def status(metadata: object) -> dict[str, object]:
            return {
                "documentIdentity": {
                    "href": url,
                    "navigation": {
                        "name": url,
                        "startTime": 0,
                        "type": "navigate",
                    },
                    "timeOrigin": 1000.0,
                },
                "packageMetadata": metadata,
            }

        self.assertEqual(
            1000.0,
            package_browser_smoke._require_ready_package_document(
                status(deepcopy(expected)),
                expected_url=url,
                expected_epoch="metadata-epoch",
                expected_package_metadata=expected,
            ),
        )
        protocol_bool = deepcopy(expected)
        protocol_bool["protocol"] = True
        gate_int = deepcopy(expected)
        gate_int["gateState"]["m8_complete"] = 0
        for name, metadata in (
            ("missing", None),
            ("extra", {**expected, "unexpected": True}),
            (
                "substituted",
                {
                    **expected,
                    "releaseStatus": "releasable",
                },
            ),
            ("protocol bool alias", protocol_bool),
            ("nested gate int alias", gate_int),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(
                M0Error, "does not match immutable VERSION.json snapshot"
            ):
                package_browser_smoke._require_ready_package_document(
                    status(metadata),
                    expected_url=url,
                    expected_epoch="metadata-epoch",
                    expected_package_metadata=expected,
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
        expected_paths = {
            "/" if artifact == "index.html" else f"/{artifact}"
            for artifact in package.PACKAGE_PATHS
        }
        self.assertEqual(expected_paths, set(endpoints))
        for artifact in package.PACKAGE_PATHS:
            request_path = "/" if artifact == "index.html" else f"/{artifact}"
            with self.subTest(artifact=artifact):
                endpoint = endpoints[request_path]
                self.assertEqual(artifact, endpoint["artifact"])
                self.assertEqual(
                    package.REQUIRED_MIME_TYPES.get(
                        Path(artifact).suffix, "text/plain; charset=utf-8"
                    ),
                    endpoint["content_type"],
                )
                self.assertEqual(["GET", "HEAD"], endpoint["methods"])
                self.assertGreater(endpoint["bytes"], 0)
        self.assertEqual(
            {
                "path": package_smoke.NOT_FOUND_PATH,
                "bytes": len(package_smoke.NOT_FOUND_BODY),
                "content_type": package_smoke.NOT_FOUND_CONTENT_TYPE,
                "methods": ["GET", "HEAD"],
            },
            result["not_found"],
        )

    def test_static_package_delivery_rejects_substituted_response_facts(
        self,
    ) -> None:
        snapshot = snapshot_package_tree(self._stage())

        def with_body(
            response: package_smoke.PackageEndpointResponse, body: bytes
        ) -> package_smoke.PackageEndpointResponse:
            return package_smoke.PackageEndpointResponse(
                status=response.status,
                headers=response.headers,
                body=body,
            )

        def with_headers(
            response: package_smoke.PackageEndpointResponse,
            headers: dict[str, str | None],
        ) -> package_smoke.PackageEndpointResponse:
            return package_smoke.PackageEndpointResponse(
                status=response.status,
                headers=headers,
                body=response.body,
            )

        leaked_artifacts = dict(snapshot.artifacts)
        leaked_artifacts["README.txt"] = package_smoke.NOT_FOUND_BODY
        leaked_snapshot = package_smoke.PackageTreeSnapshot(
            artifacts=leaked_artifacts,
            verification=snapshot.verification,
        )
        cases: tuple[
            tuple[
                str,
                package_smoke.PackageTreeSnapshot,
                str,
                str,
                Callable[
                    [package_smoke.PackageEndpointResponse],
                    package_smoke.PackageEndpointResponse,
                ],
                str,
            ],
            ...,
        ] = (
            (
                "GET artifact bytes",
                snapshot,
                "/chromium-wasm.js",
                "GET",
                lambda response: with_body(response, b"substituted-package-loader"),
                "package endpoint bytes mismatch",
            ),
            (
                "canonical content length",
                snapshot,
                "/chromium-wasm.wasm",
                "GET",
                lambda response: with_headers(
                    response,
                    {**response.headers, "Content-Length": "0"},
                ),
                "package endpoint header mismatch",
            ),
            (
                "HEAD body",
                snapshot,
                "/",
                "HEAD",
                lambda response: with_body(response, b"unexpected-head-body"),
                "package endpoint HEAD body is not empty",
            ),
            (
                "not-found artifact leak",
                leaked_snapshot,
                package_smoke.NOT_FOUND_PATH,
                "GET",
                lambda response: response,
                "package not-found endpoint leaked a staged artifact",
            ),
        )
        for name, expected_snapshot, path, method, mutate, error in cases:
            with self.subTest(name=name):
                valid_delivery = self._valid_package_delivery(expected_snapshot)

                def deliver(
                    host: str,
                    port: int,
                    request_path: str,
                    request_method: str,
                ) -> package_smoke.PackageEndpointResponse:
                    response = valid_delivery(host, port, request_path, request_method)
                    if request_path == path and request_method == method:
                        return mutate(response)
                    return response

                with mock.patch.object(
                    package_smoke,
                    "_fetch_package_response",
                    side_effect=deliver,
                ), self.assertRaisesRegex(M0Error, error):
                    package_smoke._verify_static_package_delivery(
                        "127.0.0.1", 32123, expected_snapshot
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
        self.assertIn('LOADER_ARTIFACT_PATH = "chromium-wasm.js"', host)
        for module in (
            "chromium-wasm-pointer-input.js",
            "chromium-wasm-release-wisp-config.js",
            "chromium-wasm-text-input.js",
            "chromium-wasm-clipboard-input.js",
            "chromium-wasm-file-picker.js",
            "chromium-wasm-storage-estimate.js",
        ):
            with self.subTest(module=module):
                self.assertIn(module, host)
        self.assertIn("pre_m7_m8_not_releasable", host)
        self.assertIn("not passed the M7/M8/M9", index)
        self.assertIn("Required gate state", index)
        self.assertIn('id="gate-state"', index)
        self.assertIn("staging checkout", host)
        self.assertIn("artifact source provenance", host)
        self.assertIn("EXPECTED_GATE_STATE", host)
        self.assertIn("PACKAGE_SCHEMA_VERSION = 4", host)
        self.assertIn('"TOOLCHAIN.json"', host)
        self.assertIn("toolchain manifest artifact identity", host)
        self.assertIn(
            "version?.schema_version !== PACKAGE_SCHEMA_VERSION", host
        )
        self.assertIn("validateVersionMetadata(version)", host)
        self.assertIn("#renderGateState(gateState)", host)
        self.assertLess(
            host.index("validateVersionMetadata(version)"),
            host.index("this.#installBridge()"),
        )
        for name in package.EXPECTED_GATE_STATE:
            with self.subTest(gate_state_name=name):
                self.assertIn(name, host)
                self.assertIn(name, index)
        self.assertIn("ALLOWED_ARTIFACT_SOURCE_PROVENANCE", host)
        self.assertIn('"unverified"', host)
        self.assertIn('"local_clean_build_attested"', host)
        self.assertIn("local clean-build attestation", index)

    def test_release_host_passes_validated_wisp_to_emscripten_factory(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")

        fixture = self.root / "release-host-wisp-fixture"
        shutil.copytree(self._stage(), fixture)
        (fixture / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        (fixture / "chromium-wasm.js").write_text(
            """export default function(options) {
  globalThis.__capturedReleaseWispOptions = options;
  return Promise.resolve({});
}
""",
            encoding="utf-8",
        )
        self._refresh_staged_artifact_identity(fixture, "chromium-wasm.js")
        script = """
import {readFile} from "node:fs/promises";

class HTMLElement {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.style = {};
    this.textContent = "";
  }
  addEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
}
class HTMLCanvasElement extends HTMLElement {
  focus() { document.activeElement = this; }
}
class HTMLTextAreaElement extends HTMLElement {}
class HTMLButtonElement extends HTMLElement {}
Object.assign(globalThis, {
  HTMLElement,
  HTMLButtonElement,
  HTMLCanvasElement,
  HTMLTextAreaElement,
  crossOriginIsolated: true,
});
globalThis.addEventListener = () => {};
const root = new HTMLElement();
const canvas = new HTMLCanvasElement();
const textProxy = new HTMLTextAreaElement();
const status = new HTMLElement();
const versions = new HTMLElement();
const gateState = new HTMLElement();
const shutdown = new HTMLButtonElement();
const elements = new Map([
  ["#chrome-root", root], ["#browser-canvas", canvas],
  ["#browser-text-proxy", textProxy], ["#chrome-status", status],
  ["#versions", versions], ["#gate-state", gateState], ["#shutdown", shutdown],
]);
globalThis.document = {
  activeElement: null,
  createElement() { return new HTMLElement(); },
  querySelector(selector) { return elements.get(selector) || null; },
};
const endpointHost = ["release", "-", "gateway", ".invalid"].join("");
globalThis.__chromiumWasmReleaseWispV1 = Object.freeze({
  version: 1,
  endpoint: ["w", "ss:", "//", endpointHost, "/carrier/"].join(""),
});
const versionBytes = new Uint8Array(await readFile(__VERSION_PATH__));
const loaderBytes = new Uint8Array(await readFile(__LOADER_PATH__));
const wasmBytes = new Uint8Array(await readFile(__WASM_PATH__));
const loaderUrl = __LOADER_URI__;
function responseFor(bytes, url, contentType) {
  const headers = {
    "cache-control": "no-store",
    "content-length": String(bytes.byteLength),
    "content-type": contentType,
    "cross-origin-embedder-policy": "require-corp",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-content-type-options": "nosniff",
  };
  return {
    ok: true,
    url,
    headers: {get(name) { return headers[String(name).toLowerCase()] || null; }},
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
URL.createObjectURL = () => loaderUrl;
URL.revokeObjectURL = () => {};
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.endsWith("VERSION.json")) {
    return responseFor(versionBytes, url, "application/json; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.js")) {
    return responseFor(loaderBytes, url, "text/javascript; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.wasm")) {
    return responseFor(wasmBytes, url, "application/wasm");
  }
  throw new Error(`unexpected fetch ${url}`);
};
const {runChromiumWasmPreRelease} = await import(__HOST_URI__);
await runChromiumWasmPreRelease();
const options = globalThis.__capturedReleaseWispOptions;
const payload = JSON.parse(status.textContent);
process.stdout.write(JSON.stringify({
  factoryReceivedOption: Object.hasOwn(options, "chromiumWasmWisp"),
  optionFrozen: Object.isFrozen(options.chromiumWasmWisp),
  noAdditionalSettings: Object.keys(options.chromiumWasmWisp).length === 2,
  endpointProtocol: new URL(options.chromiumWasmWisp?.endpoint).protocol,
  endpointPath: new URL(options.chromiumWasmWisp?.endpoint).pathname,
  mainScriptUrlOrBlobIsBlob: options.mainScriptUrlOrBlob instanceof Blob,
  runtimeArtifactsVerified: payload.runtimeArtifactsVerified,
  wasmBinaryBytes: options.wasmBinary?.byteLength,
  wispConfigured: payload.wispConfigured,
  wispRecord: payload.records.find((record) => record.kind === "wisp")?.value,
}));
"""
        script = script.replace(
            "__VERSION_PATH__", json.dumps(str(fixture / "VERSION.json"))
        ).replace(
            "__LOADER_PATH__", json.dumps(str(fixture / "chromium-wasm.js"))
        ).replace(
            "__WASM_PATH__", json.dumps(str(fixture / "chromium-wasm.wasm"))
        ).replace(
            "__LOADER_URI__", json.dumps((fixture / "chromium-wasm.js").as_uri())
        ).replace(
            "__HOST_URI__",
            json.dumps((fixture / "chromium-wasm-host.js").as_uri()),
        )
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        self.assertEqual(
            {
                "endpointPath": "/carrier/",
                "endpointProtocol": "wss:",
                "factoryReceivedOption": True,
                "mainScriptUrlOrBlobIsBlob": True,
                "noAdditionalSettings": True,
                "optionFrozen": True,
                "runtimeArtifactsVerified": True,
                "wasmBinaryBytes": 8,
                "wispConfigured": True,
                "wispRecord": "configured",
            },
            json.loads(completed.stdout),
        )

    def test_release_host_rejects_unbound_metadata_and_executable_artifacts_before_import(
        self,
    ) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")

        fixture = self._stage(name="release-host-artifact-binding-fixture")
        (fixture / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        script = """
import {readFile} from "node:fs/promises";

class HTMLElement {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.style = {};
    this.textContent = "";
  }
  addEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
}
class HTMLCanvasElement extends HTMLElement {
  focus() { document.activeElement = this; }
}
class HTMLTextAreaElement extends HTMLElement {}
class HTMLButtonElement extends HTMLElement {}
Object.assign(globalThis, {
  HTMLElement,
  HTMLButtonElement,
  HTMLCanvasElement,
  HTMLTextAreaElement,
  crossOriginIsolated: true,
});
globalThis.addEventListener = () => {};
const versionBytes = new Uint8Array(await readFile(__VERSION_PATH__));
const loaderBytes = new Uint8Array(await readFile(__LOADER_PATH__));
const wasmBytes = new Uint8Array(await readFile(__WASM_PATH__));
let mode = "";
function responseFor(bytes, url, contentType, mutateHeaders = false) {
  const headers = {
    "cache-control": "no-store",
    "content-length": String(bytes.byteLength),
    "content-type": contentType,
    "cross-origin-embedder-policy": "require-corp",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-content-type-options": "nosniff",
  };
  if (mutateHeaders) headers["cross-origin-resource-policy"] = "cross-origin";
  return {
    ok: true,
    url: (mode === "loader-redirect" && url.endsWith("chromium-wasm.js")) ||
        (mode === "version-redirect" && url.endsWith("VERSION.json")) ?
        `${url}?redirected` : url,
    headers: {get(name) { return headers[String(name).toLowerCase()] || null; }},
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.endsWith("VERSION.json")) {
    return responseFor(
        versionBytes, url, "application/json; charset=utf-8",
        mode === "version-header");
  }
  if (url.endsWith("chromium-wasm.js")) {
    const bytes = mode === "loader-byte" ?
        new Uint8Array([...loaderBytes, 0]) : loaderBytes;
    return responseFor(
        bytes, url, "text/javascript; charset=utf-8", mode === "loader-header");
  }
  if (url.endsWith("chromium-wasm.wasm")) {
    const bytes = mode === "wasm-byte" ?
        new Uint8Array([...wasmBytes, 0]) : wasmBytes;
    return responseFor(bytes, url, "application/wasm");
  }
  throw new Error(`unexpected fetch ${url}`);
};
const {runChromiumWasmPreRelease} = await import(__HOST_URI__);
function installElements() {
  const root = new HTMLElement();
  const canvas = new HTMLCanvasElement();
  const textProxy = new HTMLTextAreaElement();
  const status = new HTMLElement();
  const versions = new HTMLElement();
  const gateState = new HTMLElement();
  const shutdown = new HTMLButtonElement();
  const elements = new Map([
    ["#chrome-root", root], ["#browser-canvas", canvas],
    ["#browser-text-proxy", textProxy], ["#chrome-status", status],
    ["#versions", versions], ["#gate-state", gateState], ["#shutdown", shutdown],
  ]);
  globalThis.document = {
    activeElement: null,
    createElement() { return new HTMLElement(); },
    querySelector(selector) { return elements.get(selector) || null; },
  };
}
async function observe(nextMode) {
  mode = nextMode;
  globalThis.__chromiumWasmHostBridgeV1 = undefined;
  installElements();
  try {
    await runChromiumWasmPreRelease();
    return "accepted";
  } catch (error) {
    return String(error);
  }
}
const results = {};
for (const entry of [
  "loader-byte", "wasm-byte", "loader-header", "loader-redirect",
  "version-header", "version-redirect",
]) {
  results[entry] = await observe(entry);
}
process.stdout.write(JSON.stringify(results));
"""
        script = script.replace(
            "__VERSION_PATH__", json.dumps(str(fixture / "VERSION.json"))
        ).replace(
            "__LOADER_PATH__", json.dumps(str(fixture / "chromium-wasm.js"))
        ).replace(
            "__WASM_PATH__", json.dumps(str(fixture / "chromium-wasm.wasm"))
        ).replace(
            "__HOST_URI__",
            json.dumps((fixture / "chromium-wasm-host.js").as_uri()),
        )
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        observed = json.loads(completed.stdout)
        self.assertIn(
            "generated loader disagrees with VERSION.json artifact identity",
            observed["loader-byte"],
        )
        self.assertIn(
            "generated Wasm disagrees with VERSION.json artifact identity",
            observed["wasm-byte"],
        )
        self.assertIn(
            "generated loader response headers are invalid",
            observed["loader-header"],
        )
        self.assertIn(
            "generated loader request was not exact",
            observed["loader-redirect"],
        )
        self.assertIn(
            "VERSION.json response headers are invalid",
            observed["version-header"],
        )
        self.assertIn(
            "VERSION.json request was not exact",
            observed["version-redirect"],
        )

    def test_release_host_projects_canonical_version_bytes_and_fails_without_webcrypto(
        self,
    ) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        version_path = self._stage() / "VERSION.json"
        version_bytes = version_path.read_bytes()
        expected = package.package_runtime_status_metadata(version_bytes)
        invalid_version = json.loads(version_bytes.decode("utf-8"))
        invalid_version["host"]["bridge_protocol"] = 99
        invalid_version_path = self.root / "invalid-VERSION.json"
        invalid_version_path.write_bytes(package._canonical_json(invalid_version))

        # release_host.js intentionally imports the public staged names, while
        # source files retain their implementation names. Exercise the source
        # module through a temporary package-shaped fixture instead of adding
        # an alias asset to the product tree solely for this Node test.
        fixture = self.root / "release-host-module-fixture"
        fixture.mkdir()
        (fixture / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        host_source = REPO_ROOT / "tools/wasm/host/release_host.js"
        host = fixture / "chromium-wasm-host.js"
        shutil.copyfile(host_source, host)
        for source_name, staged_name in package.HOST_ASSETS:
            if source_name == "release_host.js" or not source_name.endswith(".js"):
                continue
            shutil.copyfile(
                REPO_ROOT / "tools/wasm/host" / source_name,
                fixture / staged_name,
            )
        script = f"""
import {{readFile}} from "node:fs/promises";
const versionBytes = new Uint8Array(
    await readFile({json.dumps(str(version_path))}));
const invalidVersionBytes = new Uint8Array(
    await readFile({json.dumps(str(invalid_version_path))}));
const bomVersionBytes = new Uint8Array([0xef, 0xbb, 0xbf, ...versionBytes]);
function responseFor(bytes, url) {{
  const headers = {{
    "cache-control": "no-store",
    "content-length": String(bytes.byteLength),
    "content-type": "application/json; charset=utf-8",
    "cross-origin-embedder-policy": "require-corp",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-content-type-options": "nosniff",
  }};
  return {{
    ok: true,
    url,
    headers: {{
      get(name) {{
        return headers[String(name).toLowerCase()] || null;
      }},
    }},
    async arrayBuffer() {{
      return bytes.buffer.slice(
          bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    }},
  }};
}}
let served = versionBytes;
let initialRequestOptions = null;
globalThis.fetch = async (input, options) => {{
  if (initialRequestOptions === null) {{
    initialRequestOptions = {{
      cache: options?.cache,
      credentials: options?.credentials,
      redirect: options?.redirect,
    }};
  }}
  return responseFor(served, String(input));
}};
const {{loadVersion}} = await import({json.dumps(host.as_uri())});
const loaded = await loadVersion();
const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");
const hadOwnCrypto = Object.hasOwn(globalThis, "crypto");
let noCrypto = "accepted";
try {{
  Object.defineProperty(globalThis, "crypto", {{
    configurable: true,
    value: undefined,
    writable: true,
  }});
  await loadVersion();
}} catch (error) {{
  noCrypto = String(error);
}} finally {{
  if (hadOwnCrypto) {{
    Object.defineProperty(globalThis, "crypto", cryptoDescriptor);
  }} else {{
    delete globalThis.crypto;
  }}
}}
served = new Uint8Array([...versionBytes, 10]);
let noncanonical = "accepted";
try {{
  await loadVersion();
}} catch (error) {{
  noncanonical = String(error);
}}
served = bomVersionBytes;
let bom = "accepted";
try {{
  await loadVersion();
}} catch (error) {{
  bom = String(error);
}}
served = invalidVersionBytes;
let invalidSchema = "accepted";
try {{
  await loadVersion();
}} catch (error) {{
  invalidSchema = String(error);
}}
process.stdout.write(JSON.stringify({{
  metadata: loaded.packageMetadata,
  invalidSchema,
  bom,
  noCrypto,
  noncanonical,
  initialRequestOptions,
}}));
"""
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        observed = json.loads(completed.stdout)
        self.assertEqual(expected, observed["metadata"])
        self.assertEqual(
            {
                "cache": "no-store",
                "credentials": "same-origin",
                "redirect": "error",
            },
            observed["initialRequestOptions"],
        )
        self.assertIn("WebCrypto SHA-256 is unavailable", observed["noCrypto"])
        self.assertIn("not canonical deterministic JSON", observed["noncanonical"])
        self.assertIn("not canonical deterministic JSON", observed["bom"])
        self.assertIn("host requirements values are invalid", observed["invalidSchema"])

    def test_release_host_keeps_fatal_state_after_bounded_record_eviction(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")

        fixture = self.root / "sticky-fatal-release-host-fixture"
        shutil.copytree(self._stage(), fixture)
        (fixture / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        (fixture / "chromium-wasm.js").write_text(
            """export default function(options) {
  queueMicrotask(() => {
    globalThis.__chromiumWasmHostBridgeV1.reportReadiness({
      protocol: 1,
      shellReady: true,
      surfaceReady: true,
      firstVisuallyNonEmptyPaint: true,
    });
    options.onAbort("earlier fatal");
    for (let index = 0; index < 32; ++index) {
      options.print(`ordinary record ${index}`);
    }
  });
  return new Promise(() => {});
}
""",
            encoding="utf-8",
        )
        self._refresh_staged_artifact_identity(fixture, "chromium-wasm.js")
        script = """
import {readFile} from "node:fs/promises";

class HTMLElement {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.style = {};
    this.textContent = "";
  }
  addEventListener() {}
  append(...nodes) {
    this.children.push(...nodes);
    this.textContent += nodes.map((node) => node.textContent).join("");
  }
  replaceChildren(...nodes) {
    this.children = nodes;
    this.textContent = nodes.map((node) => node.textContent).join("");
  }
}
class HTMLCanvasElement extends HTMLElement {
  focus() { document.activeElement = this; }
}
class HTMLTextAreaElement extends HTMLElement {}
class HTMLButtonElement extends HTMLElement {}
Object.assign(globalThis, {
  HTMLElement,
  HTMLButtonElement,
  HTMLCanvasElement,
  HTMLTextAreaElement,
  crossOriginIsolated: true,
});
const root = new HTMLElement();
const canvas = new HTMLCanvasElement();
const textProxy = new HTMLTextAreaElement();
const status = new HTMLElement();
const versions = new HTMLElement();
const gateState = new HTMLElement();
const shutdown = new HTMLButtonElement();
const elements = new Map([
  ["#chrome-root", root], ["#browser-canvas", canvas],
  ["#browser-text-proxy", textProxy], ["#chrome-status", status],
  ["#versions", versions], ["#gate-state", gateState], ["#shutdown", shutdown],
]);
globalThis.document = {
  activeElement: null,
  createElement() { return new HTMLElement(); },
  querySelector(selector) { return elements.get(selector) || null; },
};
globalThis.addEventListener = () => {};
const versionBytes = new Uint8Array(await readFile(__VERSION_PATH__));
const loaderBytes = new Uint8Array(await readFile(__LOADER_PATH__));
const wasmBytes = new Uint8Array(await readFile(__WASM_PATH__));
const loaderUrl = __LOADER_URI__;
function responseFor(bytes, url, contentType) {
  const headers = {
    "cache-control": "no-store",
    "content-length": String(bytes.byteLength),
    "content-type": contentType,
    "cross-origin-embedder-policy": "require-corp",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-content-type-options": "nosniff",
  };
  return {
    ok: true,
    url,
    headers: {get(name) { return headers[String(name).toLowerCase()] || null; }},
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
URL.createObjectURL = () => loaderUrl;
URL.revokeObjectURL = () => {};
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.endsWith("VERSION.json")) {
    return responseFor(versionBytes, url, "application/json; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.js")) {
    return responseFor(loaderBytes, url, "text/javascript; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.wasm")) {
    return responseFor(wasmBytes, url, "application/wasm");
  }
  throw new Error(`unexpected fetch ${url}`);
};
const {runChromiumWasmPreRelease} = await import(__HOST_URI__);
await runChromiumWasmPreRelease();
await new Promise((resolve) => setTimeout(resolve, 0));
const payload = JSON.parse(status.textContent);
process.stdout.write(JSON.stringify({
  fatalCount: payload.fatalCount,
  fatalRecordRetained: payload.records.some((record) => record.kind === "fatal"),
  pageState: root.dataset.state,
  recordCount: payload.records.length,
}));
"""
        script = script.replace(
            "__VERSION_PATH__", json.dumps(str(fixture / "VERSION.json"))
        ).replace(
            "__LOADER_PATH__", json.dumps(str(fixture / "chromium-wasm.js"))
        ).replace(
            "__WASM_PATH__", json.dumps(str(fixture / "chromium-wasm.wasm"))
        ).replace(
            "__LOADER_URI__", json.dumps((fixture / "chromium-wasm.js").as_uri())
        ).replace(
            "__HOST_URI__",
            json.dumps((fixture / "chromium-wasm-host.js").as_uri()),
        )
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        self.assertEqual(
            {
                "fatalCount": 1,
                "fatalRecordRetained": False,
                "pageState": "failed",
                "recordCount": 32,
            },
            json.loads(completed.stdout),
        )

    def test_release_host_separates_runtime_and_native_exit_channels(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")

        fixture = self.root / "release-host-exit-channel-fixture"
        shutil.copytree(self._stage(), fixture)
        (fixture / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        (fixture / "chromium-wasm.js").write_text(
            """export default function(options) {
  if (globalThis.__m9ExitMode === "page-error-before-loader") {
    ++globalThis.__m9PageFailureLoaderCalls;
    return new Promise(() => {});
  }
  if (globalThis.__m9ExitMode === "loader-throw-before-initialization") {
    const calls = [];
    const module = {
      ccall(name) {
        calls.push(name);
        return 1;
      },
    };
    const bridge = globalThis.__chromiumWasmHostBridgeV1;
    globalThis.__m9SynchronousLoaderFailure = {
      calls,
      lateInitialize() {
        options.onRuntimeInitialized.call(module);
      },
      nativeExit(code) {
        bridge.reportProcessExit({protocol: 1, exitCode: code});
      },
      runtimeExit: options.onExit,
    };
    throw new Error("synthetic loader throw before initialization");
  }
  if (globalThis.__m9ExitMode === "loader-throw-after-initialization") {
    const calls = [];
    const module = {
      ccall(name) {
        calls.push(name);
        return 1;
      },
    };
    const bridge = globalThis.__chromiumWasmHostBridgeV1;
    options.onRuntimeInitialized.call(module);
    globalThis.__m9SynchronousLoaderFailure = {
      calls,
      nativeExit(code) {
        bridge.reportProcessExit({protocol: 1, exitCode: code});
      },
      runtimeExit: options.onExit,
    };
    throw new Error("synthetic loader throw after initialization");
  }
  queueMicrotask(() => {
    const module = {
      ccall(name) {
        if (globalThis.__m9ExitMode === "shutdown-abort-reentrant" &&
            name === "chromium_wasm_browser_host_request_shutdown") {
          options.onAbort("synthetic abort from shutdown ABI");
          throw new Error("synthetic shutdown abort");
        }
        return 1;
      },
    };
    const bridge = globalThis.__chromiumWasmHostBridgeV1;
    const nativeExit = (code) => bridge.reportProcessExit({
      protocol: 1,
      exitCode: code,
    });
    if (globalThis.__m9ExitMode !== "late-runtime-after-native-exit" &&
        globalThis.__m9ExitMode !== "abort-before-runtime-initialization") {
      options.onRuntimeInitialized.call(module);
    }
    const sendLatePresentation = (after) => {
      queueMicrotask(() => {
        bridge.reportFrame({
          protocol: 1,
          id: 1,
          width: 1,
          height: 1,
          timestampMs: 0,
        });
        bridge.reportReadiness({
          protocol: 1,
          shellReady: true,
          surfaceReady: true,
          firstVisuallyNonEmptyPaint: true,
        });
        after();
      });
    };
    switch (globalThis.__m9ExitMode) {
      case "clean":
        options.onExit(0);
        nativeExit(0);
        break;
      case "abort-after-clean-exit":
        options.onExit(0);
        nativeExit(0);
        options.onAbort("synthetic abort after clean exit");
        break;
      case "mismatch-runtime-first":
        options.onExit(0);
        nativeExit(1);
        break;
      case "mismatch-native-first":
        nativeExit(1);
        options.onExit(0);
        break;
      case "duplicate-runtime":
        options.onExit(0);
        options.onExit(0);
        nativeExit(0);
        break;
      case "duplicate-native":
        options.onExit(0);
        nativeExit(0);
        nativeExit(0);
        break;
      case "missing-runtime":
        nativeExit(0);
        break;
      case "missing-native":
        options.onExit(0);
        break;
      case "late-runtime-after-native-exit":
        nativeExit(0);
        options.onRuntimeInitialized.call(module);
        globalThis.__m9LateRuntimeInitialization = {
          shutdownDisabled: document.querySelector("#shutdown").disabled,
        };
        options.onExit(0);
        break;
      case "abort-before-runtime-initialization":
        options.onAbort("synthetic abort before initialization");
        options.onRuntimeInitialized.call(module);
        globalThis.__m9LateRuntimeInitialization = {
          shutdownDisabled: document.querySelector("#shutdown").disabled,
        };
        nativeExit(0);
        options.onExit(0);
        break;
      case "shutdown-abort-reentrant":
        document.querySelector("#shutdown").dispatch("click");
        nativeExit(0);
        options.onExit(0);
        break;
      case "late-presentation-after-runtime-exit":
        options.onExit(0);
        sendLatePresentation(() => nativeExit(0));
        break;
      case "late-presentation-after-native-exit":
        nativeExit(0);
        sendLatePresentation(() => options.onExit(0));
        break;
      case "late-presentation-after-abort":
        options.onAbort("synthetic abort before late presentation");
        sendLatePresentation(() => {
          nativeExit(0);
          options.onExit(0);
        });
        break;
      default:
        throw new Error(`unexpected exit mode ${String(globalThis.__m9ExitMode)}`);
    }
  });
  return new Promise(() => {});
}
""",
            encoding="utf-8",
        )
        self._refresh_staged_artifact_identity(fixture, "chromium-wasm.js")
        script = """
import {readFile} from "node:fs/promises";

class HTMLElement {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.style = {};
    this.textContent = "";
    this.value = "";
    this.#listeners = new Map();
  }
  #listeners;
  addEventListener(type, listener) {
    const listeners = this.#listeners.get(type) || new Set();
    listeners.add(listener);
    this.#listeners.set(type, listeners);
  }
  removeEventListener(type, listener) {
    const listeners = this.#listeners.get(type);
    listeners?.delete(listener);
    if (listeners?.size === 0) this.#listeners.delete(type);
  }
  dispatch(type) {
    for (const listener of this.#listeners.get(type) || []) {
      listener({type});
    }
  }
  append(...nodes) {
    this.children.push(...nodes);
    this.textContent += nodes.map((node) => node.textContent).join("");
  }
  replaceChildren(...nodes) {
    this.children = nodes;
    this.textContent = nodes.map((node) => node.textContent).join("");
  }
  focus() { document.activeElement = this; }
  blur() {
    if (document.activeElement === this) document.activeElement = null;
  }
  setSelectionRange() {}
}
class HTMLCanvasElement extends HTMLElement {}
class HTMLTextAreaElement extends HTMLElement {}
class HTMLButtonElement extends HTMLElement {}
Object.assign(globalThis, {
  HTMLElement,
  HTMLButtonElement,
  HTMLCanvasElement,
  HTMLTextAreaElement,
  crossOriginIsolated: true,
});
globalThis.window = globalThis;
const windowListeners = new Map();
globalThis.addEventListener = (type, listener) => {
  const listeners = windowListeners.get(type) || new Set();
  listeners.add(listener);
  windowListeners.set(type, listeners);
};
globalThis.removeEventListener = (type, listener) => {
  const listeners = windowListeners.get(type);
  listeners?.delete(listener);
  if (listeners?.size === 0) windowListeners.delete(type);
};
const versionBytes = new Uint8Array(await readFile(__VERSION_PATH__));
const loaderBytes = new Uint8Array(await readFile(__LOADER_PATH__));
const wasmBytes = new Uint8Array(await readFile(__WASM_PATH__));
const loaderUrl = __LOADER_URI__;
function responseFor(bytes, url, contentType) {
  const headers = {
    "cache-control": "no-store",
    "content-length": String(bytes.byteLength),
    "content-type": contentType,
    "cross-origin-embedder-policy": "require-corp",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-content-type-options": "nosniff",
  };
  return {
    ok: true,
    url,
    headers: {get(name) { return headers[String(name).toLowerCase()] || null; }},
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
URL.createObjectURL = () => loaderUrl;
URL.revokeObjectURL = () => {};
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.endsWith("VERSION.json")) {
    return responseFor(versionBytes, url, "application/json; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.js")) {
    if (globalThis.__m9ExitMode === "page-error-before-loader") {
      for (const listener of windowListeners.get("error") || []) {
        listener({error: new Error("synthetic page error before loader")});
      }
    }
    return responseFor(loaderBytes, url, "text/javascript; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.wasm")) {
    return responseFor(wasmBytes, url, "application/wasm");
  }
  throw new Error(`unexpected fetch ${url}`);
};
const {runChromiumWasmPreRelease} = await import(__HOST_URI__);
function installElements() {
  const root = new HTMLElement();
  const canvas = new HTMLCanvasElement();
  const textProxy = new HTMLTextAreaElement();
  const status = new HTMLElement();
  const versions = new HTMLElement();
  const gateState = new HTMLElement();
  const shutdown = new HTMLButtonElement();
  const elements = new Map([
    ["#chrome-root", root], ["#browser-canvas", canvas],
    ["#browser-text-proxy", textProxy], ["#chrome-status", status],
    ["#versions", versions], ["#gate-state", gateState], ["#shutdown", shutdown],
  ]);
  globalThis.document = {
    activeElement: null,
    hidden: false,
    addEventListener() {},
    removeEventListener() {},
    createElement() { return new HTMLElement(); },
    querySelector(selector) { return elements.get(selector) || null; },
  };
  return {root, status};
}
async function observe(mode) {
  globalThis.__chromiumWasmHostBridgeV1 = undefined;
  globalThis.__m9ExitMode = mode;
  globalThis.__m9LateRuntimeInitialization = null;
  globalThis.__m9PageFailureLoaderCalls = 0;
  globalThis.__m9SynchronousLoaderFailure = null;
  windowListeners.clear();
  const {root, status} = installElements();
  await runChromiumWasmPreRelease();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const synchronousLoaderFailure = mode.startsWith("loader-throw-");
  if (synchronousLoaderFailure) {
    const failure = globalThis.__m9SynchronousLoaderFailure;
    if (!failure) {
      throw new Error("synchronous loader failure fixture did not initialize");
    }
    document.querySelector("#shutdown").dispatch("click");
    failure.lateInitialize?.();
    failure.nativeExit(0);
    failure.runtimeExit(0);
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  const payload = JSON.parse(status.textContent);
  const latePresentation = mode.startsWith("late-presentation-after-");
  const pageErrorBeforeLoader = mode === "page-error-before-loader";
  const reentrantShutdownAbort = mode === "shutdown-abort-reentrant";
  return {
    fatalCount: payload.fatalCount,
    processExitCode: payload.processExitCode,
    runtimeExitCode: payload.runtimeExitCode,
    pageState: root.dataset.state || null,
    ...(globalThis.__m9LateRuntimeInitialization ? {
      runtimeInitialized: payload.runtimeInitialized,
      shutdownDisabledAfterLateInitialization:
          globalThis.__m9LateRuntimeInitialization.shutdownDisabled,
    } : {}),
    ...(reentrantShutdownAbort ? {
      runtimeInitialized: payload.runtimeInitialized,
      shutdownDisabled: document.querySelector("#shutdown").disabled,
      shutdownRequested: payload.shutdownRequested,
    } : {}),
    ...(synchronousLoaderFailure ? {
      calls: globalThis.__m9SynchronousLoaderFailure.calls,
      runtimeInitialized: payload.runtimeInitialized,
      shutdownDisabled: document.querySelector("#shutdown").disabled,
      shutdownRequested: payload.shutdownRequested,
    } : {}),
    ...(pageErrorBeforeLoader ? {
      loaderCalls: globalThis.__m9PageFailureLoaderCalls,
      shutdownDisabled: document.querySelector("#shutdown").disabled,
      shutdownRequested: payload.shutdownRequested,
    } : {}),
    ...(latePresentation ? {
      framesPresented: payload.framesPresented,
      readiness: payload.readiness,
      shutdownDisabled: document.querySelector("#shutdown").disabled,
    } : {}),
  };
}
const results = {};
for (const mode of [
  "clean", "mismatch-runtime-first", "mismatch-native-first",
  "duplicate-runtime", "duplicate-native", "missing-runtime", "missing-native",
  "abort-after-clean-exit", "page-error-before-loader",
  "late-runtime-after-native-exit", "abort-before-runtime-initialization",
  "shutdown-abort-reentrant", "loader-throw-before-initialization",
  "loader-throw-after-initialization",
  "late-presentation-after-runtime-exit",
  "late-presentation-after-native-exit", "late-presentation-after-abort",
]) {
  results[mode] = await observe(mode);
}
process.stdout.write(JSON.stringify(results));
"""
        script = script.replace(
            "__VERSION_PATH__", json.dumps(str(fixture / "VERSION.json"))
        ).replace(
            "__LOADER_PATH__", json.dumps(str(fixture / "chromium-wasm.js"))
        ).replace(
            "__WASM_PATH__", json.dumps(str(fixture / "chromium-wasm.wasm"))
        ).replace(
            "__LOADER_URI__", json.dumps((fixture / "chromium-wasm.js").as_uri())
        ).replace(
            "__HOST_URI__",
            json.dumps((fixture / "chromium-wasm-host.js").as_uri()),
        )
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            0, completed.returncode, completed.stdout + completed.stderr
        )
        self.assertEqual(
            {
                "clean": {
                    "fatalCount": 0,
                    "pageState": None,
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                },
                "abort-after-clean-exit": {
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                },
                "page-error-before-loader": {
                    "fatalCount": 1,
                    "loaderCalls": 0,
                    "pageState": "failed",
                    "processExitCode": None,
                    "runtimeExitCode": None,
                    "shutdownDisabled": True,
                    "shutdownRequested": False,
                },
                "mismatch-runtime-first": {
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 1,
                    "runtimeExitCode": 0,
                },
                "mismatch-native-first": {
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 1,
                    "runtimeExitCode": 0,
                },
                "duplicate-runtime": {
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                },
                "duplicate-native": {
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                },
                "missing-runtime": {
                    "fatalCount": 0,
                    "pageState": None,
                    "processExitCode": 0,
                    "runtimeExitCode": None,
                },
                "missing-native": {
                    "fatalCount": 0,
                    "pageState": None,
                    "processExitCode": None,
                    "runtimeExitCode": 0,
                },
                "late-runtime-after-native-exit": {
                    "fatalCount": 0,
                    "pageState": None,
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                    "runtimeInitialized": False,
                    "shutdownDisabledAfterLateInitialization": True,
                },
                "abort-before-runtime-initialization": {
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                    "runtimeInitialized": False,
                    "shutdownDisabledAfterLateInitialization": True,
                },
                "shutdown-abort-reentrant": {
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                    "runtimeInitialized": True,
                    "shutdownDisabled": True,
                    "shutdownRequested": False,
                },
                "loader-throw-after-initialization": {
                    "calls": [],
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                    "runtimeInitialized": True,
                    "shutdownDisabled": True,
                    "shutdownRequested": False,
                },
                "loader-throw-before-initialization": {
                    "calls": [],
                    "fatalCount": 1,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "runtimeExitCode": 0,
                    "runtimeInitialized": False,
                    "shutdownDisabled": True,
                    "shutdownRequested": False,
                },
                "late-presentation-after-runtime-exit": {
                    "fatalCount": 2,
                    "framesPresented": 0,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "readiness": None,
                    "runtimeExitCode": 0,
                    "shutdownDisabled": True,
                },
                "late-presentation-after-native-exit": {
                    "fatalCount": 2,
                    "framesPresented": 0,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "readiness": None,
                    "runtimeExitCode": 0,
                    "shutdownDisabled": True,
                },
                "late-presentation-after-abort": {
                    "fatalCount": 3,
                    "framesPresented": 0,
                    "pageState": "failed",
                    "processExitCode": 0,
                    "readiness": None,
                    "runtimeExitCode": 0,
                    "shutdownDisabled": True,
                },
            },
            json.loads(completed.stdout),
        )

    def test_release_host_disposes_pending_dom_bridges_at_terminal_state(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")

        fixture = self.root / "release-host-terminal-bridge-cleanup-fixture"
        shutil.copytree(self._stage(), fixture)
        (fixture / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        (fixture / "chromium-wasm.js").write_text(
            """export default function(options) {
  const failureMode = globalThis.__m9TerminalFailure;
  const loaderRejection = failureMode === "loader-rejection" ||
      failureMode === "hostile-loader-rejection";
  let resolveTerminalFailureStarted;
  if (failureMode !== "none") {
    globalThis.__m9TerminalFailureStarted = new Promise((resolve) => {
      resolveTerminalFailureStarted = resolve;
    });
  }
  let rejectLoader;
  const loaderPromise = loaderRejection ?
      new Promise((_resolve, reject) => { rejectLoader = reject; }) :
      new Promise(() => {});
  queueMicrotask(() => {
    const terminalFailureBeforeExit = failureMode !== "none";
    const terminalViaNative = globalThis.__m9TerminalViaNative === true;
    const calls = [];
    const module = {
      HEAPU8: new Uint8Array(128),
      _malloc() { return 8; },
      _free() {},
      ccall(name) {
        calls.push(name);
        return 1;
      },
    };
    options.onRuntimeInitialized.call(module);
    const bridge = globalThis.__chromiumWasmHostBridgeV1;
    const storageAccepted = bridge.requestOuterOriginStorageEstimate({
      protocol: 1,
      generation: 1,
    });
    const pickerAccepted = bridge.requestOzoneBrowserFilePicker({
      protocol: 1,
      requestId: 1,
    });
    Promise.resolve().then(() => {
      if (!globalThis.__m9StorageEstimateEntered) {
        throw new Error("release-host cleanup fixture did not defer storage");
      }
      const inputCountBeforeExit = document.body.children.length;
      let inputCountAfterFailure = null;
      let postFailurePickerAccepted = null;
      let postFailureStorageAccepted = null;
      const completeTerminalReports = () => {
        if (terminalViaNative) {
          bridge.reportProcessExit({protocol: 1, exitCode: 0});
        } else {
          options.onExit(0);
        }
        const inputCountAfterExit = document.body.children.length;
        bridge.reportOzoneBrowserFilePickerDelivery({
          protocol: 1,
          requestId: 1,
          accepted: false,
        });
        const postExitPickerAccepted = bridge.requestOzoneBrowserFilePicker({
          protocol: 1,
          requestId: terminalFailureBeforeExit ? 3 : 2,
        });
        const postExitStorageAccepted = bridge.requestOuterOriginStorageEstimate({
          protocol: 1,
          generation: terminalFailureBeforeExit ? 3 : 2,
        });
        if (terminalViaNative) {
          options.onExit(0);
        } else {
          bridge.reportProcessExit({protocol: 1, exitCode: 0});
        }
        globalThis.__m9TerminalBridgeCleanup = {
          calls,
          inputCountAfterFailure,
          inputCountAfterExit,
          inputCountBeforeExit,
          pickerAccepted,
          postFailurePickerAccepted,
          postFailureStorageAccepted,
          postExitPickerAccepted,
          postExitStorageAccepted,
          storageAccepted,
        };
      };
      const beginTerminalFailure = () => {
        inputCountAfterFailure = document.body.children.length;
        bridge.reportOzoneBrowserFilePickerDelivery({
          protocol: 1,
          requestId: 1,
          accepted: false,
        });
        postFailurePickerAccepted = bridge.requestOzoneBrowserFilePicker({
          protocol: 1,
          requestId: 2,
        });
        postFailureStorageAccepted = bridge.requestOuterOriginStorageEstimate({
          protocol: 1,
          generation: 2,
        });
        // Dispatch directly instead of relying on disabled-button behavior:
        // the host guard itself must reject shutdown after a terminal failure.
        document.querySelector("#shutdown").dispatch("click");
        globalThis.__m9FinishTerminalBridgeCleanup = completeTerminalReports;
        resolveTerminalFailureStarted?.();
      };
      const hostileDiagnostic = () => ({
        [Symbol.toPrimitive]() {
          throw new Error("synthetic hostile diagnostic conversion");
        },
      });
      switch (failureMode) {
        case "abort":
          options.onAbort("synthetic abort after initialization");
          beginTerminalFailure();
          return;
        case "hostile-abort":
          options.onAbort(hostileDiagnostic());
          beginTerminalFailure();
          return;
        case "loader-rejection":
          rejectLoader(new Error("synthetic loader rejection after initialization"));
          // A task boundary gives the host's factory-rejection handler a
          // chance to quiesce live bridges before this fixture attempts any
          // further bridge use. The harness replaces setTimeout to count
          // host timers, so use its preserved native timer explicitly.
          globalThis.__m9NativeSetTimeout(beginTerminalFailure, 0);
          return;
        case "hostile-loader-rejection":
          rejectLoader(hostileDiagnostic());
          globalThis.__m9NativeSetTimeout(beginTerminalFailure, 0);
          return;
        case "window-error":
          globalThis.__m9DispatchHostFailure("error", {
            error: new Error("synthetic window error after initialization"),
          });
          beginTerminalFailure();
          return;
        case "hostile-window-error":
          globalThis.__m9DispatchHostFailure("error", {
            error: hostileDiagnostic(),
          });
          beginTerminalFailure();
          return;
        case "unhandled-rejection":
          globalThis.__m9DispatchHostFailure("unhandledrejection", {
            reason: new Error("synthetic rejection after initialization"),
          });
          beginTerminalFailure();
          return;
        case "hostile-unhandled-rejection":
          globalThis.__m9DispatchHostFailure("unhandledrejection", {
            reason: hostileDiagnostic(),
          });
          beginTerminalFailure();
          return;
        case "none":
          completeTerminalReports();
          return;
        default:
          throw new Error(`unexpected terminal failure ${String(failureMode)}`);
      }
    }).catch((error) => {
      globalThis.__m9TerminalBridgeCleanupFailure = String(error);
    });
  });
  return loaderPromise;
}
""",
            encoding="utf-8",
        )
        self._refresh_staged_artifact_identity(fixture, "chromium-wasm.js")
        script = """
import {readFile} from "node:fs/promises";

const nativeSetTimeout = globalThis.setTimeout;
globalThis.__m9NativeSetTimeout = nativeSetTimeout;
const terminalFailure = __TERMINAL_FAILURE__;
const terminalFailureBeforeExit = terminalFailure !== "none";
const throwOnInputRemove = __THROW_ON_INPUT_REMOVE__;
const rejectEstimate = __REJECT_ESTIMATE__;
globalThis.__m9TerminalFailure = terminalFailure;
globalThis.__m9TerminalViaNative = __TERMINAL_VIA_NATIVE__;
const timerTokens = new Set();
globalThis.setTimeout = (callback, delay) => {
  const token = {callback, delay};
  timerTokens.add(token);
  return token;
};
globalThis.clearTimeout = (token) => {
  timerTokens.delete(token);
};

class HTMLElement {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.parentNode = null;
    this.style = {};
    this.textContent = "";
    this.value = "";
    this.#listeners = new Map();
  }
  #listeners;
  addEventListener(type, listener) {
    const listeners = this.#listeners.get(type) || new Set();
    listeners.add(listener);
    this.#listeners.set(type, listeners);
  }
  removeEventListener(type, listener) {
    const listeners = this.#listeners.get(type);
    listeners?.delete(listener);
    if (listeners?.size === 0) this.#listeners.delete(type);
  }
  dispatch(type) {
    for (const listener of this.#listeners.get(type) || []) {
      listener({type});
    }
  }
  listenerCount(type) { return this.#listeners.get(type)?.size || 0; }
  append(...nodes) {
    for (const node of nodes) {
      node.remove?.();
      node.parentNode = this;
      this.children.push(node);
    }
    this.textContent += nodes.map((node) => node.textContent).join("");
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.textContent = "";
    this.append(...nodes);
  }
  remove() {
    if (!this.parentNode) return;
    const siblings = this.parentNode.children;
    const index = siblings.indexOf(this);
    if (index >= 0) siblings.splice(index, 1);
    this.parentNode = null;
  }
  setAttribute() {}
  focus() { document.activeElement = this; }
  blur() {
    if (document.activeElement === this) document.activeElement = null;
  }
  setSelectionRange() {}
}
class HTMLCanvasElement extends HTMLElement {}
class HTMLTextAreaElement extends HTMLElement {}
class HTMLButtonElement extends HTMLElement {}
class HTMLInputElement extends HTMLElement {
  constructor() {
    super();
    this.showPickerCount = 0;
  }
  showPicker() { ++this.showPickerCount; }
  remove() {
    if (throwOnInputRemove && this.parentNode) {
      throw new Error("synthetic input removal failure");
    }
    super.remove();
  }
}
const documentListeners = new Map();
const windowListeners = new Map();
function addListener(map, type, listener) {
  const listeners = map.get(type) || new Set();
  listeners.add(listener);
  map.set(type, listeners);
}
function removeListener(map, type, listener) {
  const listeners = map.get(type);
  listeners?.delete(listener);
  if (listeners?.size === 0) map.delete(type);
}
function listenerCount(map, type) { return map.get(type)?.size || 0; }
Object.assign(globalThis, {
  HTMLElement,
  HTMLButtonElement,
  HTMLCanvasElement,
  HTMLInputElement,
  HTMLTextAreaElement,
  crossOriginIsolated: true,
});
globalThis.window = globalThis;
globalThis.addEventListener = (type, listener) =>
    addListener(windowListeners, type, listener);
globalThis.removeEventListener = (type, listener) =>
    removeListener(windowListeners, type, listener);
globalThis.__m9DispatchHostFailure = (type, event) => {
  for (const listener of windowListeners.get(type) || []) {
    listener(event);
  }
};
const body = new HTMLElement();
const createdInputs = [];
const root = new HTMLElement();
const canvas = new HTMLCanvasElement();
const textProxy = new HTMLTextAreaElement();
const status = new HTMLElement();
const versions = new HTMLElement();
const gateState = new HTMLElement();
const shutdown = new HTMLButtonElement();
const elements = new Map([
  ["#chrome-root", root], ["#browser-canvas", canvas],
  ["#browser-text-proxy", textProxy], ["#chrome-status", status],
  ["#versions", versions], ["#gate-state", gateState], ["#shutdown", shutdown],
]);
globalThis.document = {
  activeElement: null,
  body,
  hidden: false,
  visibilityState: "visible",
  addEventListener(type, listener) { addListener(documentListeners, type, listener); },
  removeEventListener(type, listener) {
    removeListener(documentListeners, type, listener);
  },
  createElement(tag) {
    if (tag === "input") {
      const input = new HTMLInputElement();
      createdInputs.push(input);
      return input;
    }
    return new HTMLElement();
  },
  querySelector(selector) { return elements.get(selector) || null; },
};
let settleEstimate;
let estimateCalls = 0;
const deferredEstimate = new Promise((resolve, reject) => {
  settleEstimate = {reject, resolve};
});
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    storage: {
      estimate() {
        ++estimateCalls;
        globalThis.__m9StorageEstimateEntered = true;
        return deferredEstimate;
      },
    },
    userActivation: {isActive: true},
  },
});
const versionBytes = new Uint8Array(await readFile(__VERSION_PATH__));
const loaderBytes = new Uint8Array(await readFile(__LOADER_PATH__));
const wasmBytes = new Uint8Array(await readFile(__WASM_PATH__));
const loaderUrl = __LOADER_URI__;
function responseFor(bytes, url, contentType) {
  const headers = {
    "cache-control": "no-store",
    "content-length": String(bytes.byteLength),
    "content-type": contentType,
    "cross-origin-embedder-policy": "require-corp",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-content-type-options": "nosniff",
  };
  return {
    ok: true,
    url,
    headers: {get(name) { return headers[String(name).toLowerCase()] || null; }},
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
URL.createObjectURL = () => loaderUrl;
URL.revokeObjectURL = () => {};
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.endsWith("VERSION.json")) {
    return responseFor(versionBytes, url, "application/json; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.js")) {
    return responseFor(loaderBytes, url, "text/javascript; charset=utf-8");
  }
  if (url.endsWith("chromium-wasm.wasm")) {
    return responseFor(wasmBytes, url, "application/wasm");
  }
  throw new Error(`unexpected fetch ${url}`);
};
const {runChromiumWasmPreRelease} = await import(__HOST_URI__);
await runChromiumWasmPreRelease();
await new Promise((resolve) => nativeSetTimeout(resolve, 0));
if (globalThis.__m9TerminalBridgeCleanupFailure) {
  throw new Error(globalThis.__m9TerminalBridgeCleanupFailure);
}
let failureSnapshot = null;
if (terminalFailureBeforeExit) {
  if (!globalThis.__m9TerminalFailureStarted) {
    throw new Error("release-host failure cleanup fixture did not start");
  }
  await globalThis.__m9TerminalFailureStarted;
  if (typeof globalThis.__m9FinishTerminalBridgeCleanup !== "function") {
    throw new Error("release-host failure cleanup fixture did not reach terminal state");
  }
  const input = createdInputs[0];
  failureSnapshot = {
    documentVisibilityListenerCount:
        listenerCount(documentListeners, "visibilitychange"),
    inputCancelListenerCount: input.listenerCount("cancel"),
    inputChangeListenerCount: input.listenerCount("change"),
    inputCount: body.children.length,
    shutdownDisabled: shutdown.disabled,
    textProxyListenerCount:
        textProxy.listenerCount("beforeinput") + textProxy.listenerCount("input") +
        textProxy.listenerCount("keydown") + textProxy.listenerCount("keyup") +
        textProxy.listenerCount("blur") + textProxy.listenerCount("paste"),
    timerCount: timerTokens.size,
    windowBlurListenerCount: listenerCount(windowListeners, "blur"),
  };
}
if (rejectEstimate) {
  settleEstimate.reject(new Error("synthetic deferred storage failure"));
} else {
  settleEstimate.resolve({usage: 256, quota: 1024});
}
await Promise.resolve();
await Promise.resolve();
if (terminalFailureBeforeExit) {
  // Let the deferred estimate settle while only the failure—not a later exit
  // report—can quiesce its completion route.
  await new Promise((resolve) => nativeSetTimeout(resolve, 0));
  globalThis.__m9FinishTerminalBridgeCleanup();
}
await new Promise((resolve) => nativeSetTimeout(resolve, 0));
if (globalThis.__m9TerminalBridgeCleanupFailure) {
  throw new Error(globalThis.__m9TerminalBridgeCleanupFailure);
}
const payload = JSON.parse(status.textContent);
const input = createdInputs[0];
process.stdout.write(JSON.stringify({
  calls: globalThis.__m9TerminalBridgeCleanup.calls,
  createdInputCount: createdInputs.length,
  documentVisibilityListenerCount: listenerCount(documentListeners, "visibilitychange"),
  fatalCount: payload.fatalCount,
  inputCancelListenerCount: input.listenerCount("cancel"),
  inputChangeListenerCount: input.listenerCount("change"),
  ...(terminalFailureBeforeExit ? {
    failureMode: terminalFailure,
    failureSnapshot,
    inputCountAfterFailure:
        globalThis.__m9TerminalBridgeCleanup.inputCountAfterFailure,
    postFailurePickerAccepted:
        globalThis.__m9TerminalBridgeCleanup.postFailurePickerAccepted,
    postFailureStorageAccepted:
        globalThis.__m9TerminalBridgeCleanup.postFailureStorageAccepted,
    shutdownRequested: payload.shutdownRequested,
  } : {}),
  inputCountAfterExit: globalThis.__m9TerminalBridgeCleanup.inputCountAfterExit,
  inputCountBeforeExit: globalThis.__m9TerminalBridgeCleanup.inputCountBeforeExit,
  inputRemoved: input.parentNode === null && !body.children.includes(input),
  pickerAccepted: globalThis.__m9TerminalBridgeCleanup.pickerAccepted,
  postExitPickerAccepted:
      globalThis.__m9TerminalBridgeCleanup.postExitPickerAccepted,
  postExitStorageAccepted:
      globalThis.__m9TerminalBridgeCleanup.postExitStorageAccepted,
  processExitCode: payload.processExitCode,
  runtimeExitCode: payload.runtimeExitCode,
  showPickerCount: input.showPickerCount,
  shutdownDisabled: shutdown.disabled,
  storageAccepted: globalThis.__m9TerminalBridgeCleanup.storageAccepted,
  storageEstimateCallCount: estimateCalls,
  storageResultRecordCount:
      payload.records.filter((record) => record.kind === "storage-estimate").length,
  textProxyListenerCount:
      textProxy.listenerCount("beforeinput") + textProxy.listenerCount("input") +
      textProxy.listenerCount("keydown") + textProxy.listenerCount("keyup") +
      textProxy.listenerCount("blur") + textProxy.listenerCount("paste"),
  timerCount: timerTokens.size,
  windowBlurListenerCount: listenerCount(windowListeners, "blur"),
}));
"""
        script = script.replace(
            "__VERSION_PATH__", json.dumps(str(fixture / "VERSION.json"))
        ).replace(
            "__LOADER_PATH__", json.dumps(str(fixture / "chromium-wasm.js"))
        ).replace(
            "__WASM_PATH__", json.dumps(str(fixture / "chromium-wasm.wasm"))
        ).replace(
            "__LOADER_URI__", json.dumps((fixture / "chromium-wasm.js").as_uri())
        ).replace(
            "__HOST_URI__",
            json.dumps((fixture / "chromium-wasm-host.js").as_uri()),
        )
        expected = {
            "calls": [],
            "createdInputCount": 1,
            "documentVisibilityListenerCount": 0,
            "fatalCount": 0,
            "inputCancelListenerCount": 0,
            "inputChangeListenerCount": 0,
            "inputCountAfterExit": 0,
            "inputCountBeforeExit": 1,
            "inputRemoved": True,
            "pickerAccepted": True,
            "postExitPickerAccepted": False,
            "postExitStorageAccepted": False,
            "processExitCode": 0,
            "runtimeExitCode": 0,
            "showPickerCount": 1,
            "shutdownDisabled": True,
            "storageAccepted": True,
            "storageEstimateCallCount": 1,
            "storageResultRecordCount": 0,
            "textProxyListenerCount": 0,
            "timerCount": 0,
            "windowBlurListenerCount": 0,
        }
        for terminal_failure in (
            "none",
            "abort",
            "hostile-abort",
            "loader-rejection",
            "hostile-loader-rejection",
            "window-error",
            "hostile-window-error",
            "unhandled-rejection",
            "hostile-unhandled-rejection",
        ):
            for terminal_via_native in (False, True):
                for reject_estimate in (False, True):
                    for throw_on_input_remove in (False, True):
                        with self.subTest(
                            terminal_failure=terminal_failure,
                            terminal_via_native=terminal_via_native,
                            reject_estimate=reject_estimate,
                            throw_on_input_remove=throw_on_input_remove,
                        ):
                            completed = subprocess.run(
                                [
                                    str(node),
                                    "--input-type=module",
                                    "--eval",
                                    script.replace(
                                        "__TERMINAL_FAILURE__",
                                        json.dumps(terminal_failure),
                                    ).replace(
                                        "__THROW_ON_INPUT_REMOVE__",
                                        "true" if throw_on_input_remove else "false",
                                    ).replace(
                                        "__REJECT_ESTIMATE__",
                                        "true" if reject_estimate else "false",
                                    ).replace(
                                        "__TERMINAL_VIA_NATIVE__",
                                        "true" if terminal_via_native else "false",
                                    ),
                                ],
                                capture_output=True,
                                encoding="utf-8",
                                check=False,
                            )
                            self.assertEqual(
                                0, completed.returncode,
                                completed.stdout + completed.stderr,
                            )
                            expected_for_case = {**expected}
                            if terminal_failure != "none":
                                input_count = 1 if throw_on_input_remove else 0
                                expected_for_case.update(
                                    {
                                        "failureMode": terminal_failure,
                                        "failureSnapshot": {
                                            "documentVisibilityListenerCount": 0,
                                            "inputCancelListenerCount": 0,
                                            "inputChangeListenerCount": 0,
                                            "inputCount": input_count,
                                            "shutdownDisabled": True,
                                            "textProxyListenerCount": 0,
                                            "timerCount": 0,
                                            "windowBlurListenerCount": 0,
                                        },
                                        "fatalCount": 2 if throw_on_input_remove else 1,
                                        "inputCountAfterFailure": input_count,
                                        "postFailurePickerAccepted": False,
                                        "postFailureStorageAccepted": False,
                                        "shutdownRequested": False,
                                    }
                                )
                            if throw_on_input_remove:
                                expected_for_case.update(
                                    {
                                        "fatalCount": (
                                            2 if terminal_failure != "none" else 1
                                        ),
                                        "inputCountAfterExit": 1,
                                        "inputRemoved": False,
                                    }
                                )
                            self.assertEqual(
                                expected_for_case, json.loads(completed.stdout)
                            )

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
        self.assertIn("fatalCount", smoke)
        self.assertIn("runtimeExitCode", smoke)
        self.assertIn("processExitCode", smoke)
        self.assertIn("shutdownDisabled", smoke)
        self.assertIn("clean fixed package-host shutdown", smoke)
        self.assertIn("package host elements are not installed yet", smoke)
        self.assertIn("pending: true", smoke)
        self.assertIn("displayedVersions", smoke)
        self.assertIn("artifact source provenance", smoke)
        self.assertIn('"local_clean_build_attested" in displayed_versions', smoke)
        self.assertIn("runtimeArtifactsVerified", smoke)
        self.assertIn("mainScriptUrlOrBlob", host)
        self.assertIn("inputModuleName", host)
        self.assertIn("fetchVerifiedArtifact(", host)
        self.assertIn("LOADER_ARTIFACT_PATH", host)
        self.assertIn("WASM_ARTIFACT_PATH", host)
        self.assertIn("wasmBinary,", host)
        self.assertIn(
            "runtimeArtifactsVerified: this.#runtimeArtifactsVerified", host
        )
        self.assertIn("#fatalCount = 0", host)
        self.assertIn("fatalCount: this.#fatalCount", host)
        self.assertIn("#runtimeExitCode = null", host)
        self.assertIn("runtimeExitCode: this.#runtimeExitCode", host)
        self.assertIn("#reportRuntimeExit", host)
        self.assertIn("#reportNativeProcessExit", host)
        self.assertIn("host.#reportRuntimeExit(code)", host)
        self.assertIn("if (this.#fatalCount === 0)", host)

    def test_package_browser_restart_epoch_binds_exact_url_and_fresh_document(self) -> None:
        initial_url = package_browser_smoke._make_epoch_url(
            "http://127.0.0.1:32123/", "first-epoch"
        )
        restart_url = package_browser_smoke._make_epoch_url(
            "http://127.0.0.1:32123/", "restart-epoch"
        )

        def status_for(url: str, time_origin: float) -> dict[str, object]:
            return {
                "documentIdentity": {
                    "href": url,
                    "navigation": {
                        "name": url,
                        "startTime": 0,
                        "type": "navigate",
                    },
                    "timeOrigin": time_origin,
                }
            }

        first_origin = package_browser_smoke._require_document_identity(
            status_for(initial_url, 1000.5),
            expected_url=initial_url,
            expected_epoch="first-epoch",
        )
        self.assertEqual(1000.5, first_origin)
        self.assertEqual(
            1001.5,
            package_browser_smoke._require_document_identity(
                status_for(restart_url, 1001.5),
                expected_url=restart_url,
                expected_epoch="restart-epoch",
                prior_time_origin=first_origin,
            ),
        )

        with self.assertRaisesRegex(M0Error, "URL does not match"):
            package_browser_smoke._require_document_identity(
                status_for(initial_url, 1001.5),
                expected_url=restart_url,
                expected_epoch="restart-epoch",
                prior_time_origin=first_origin,
            )
        with self.assertRaisesRegex(M0Error, "time origin did not change"):
            package_browser_smoke._require_document_identity(
                status_for(restart_url, first_origin),
                expected_url=restart_url,
                expected_epoch="restart-epoch",
                prior_time_origin=first_origin,
            )

    def test_package_browser_restart_refuses_unclean_first_exit_before_navigation(
        self,
    ) -> None:
        class StaleClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []
                self.closed = False

            def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
                self.calls.append((method, params))
                return {"frameId": "unused"}

            def close(self) -> None:
                self.closed = True

        client = StaleClient()
        with mock.patch.object(
            package_browser_smoke, "wait_for_page_client"
        ) as wait_for_client, self.assertRaisesRegex(
            M0Error, "first fixed package-host shutdown"
        ):
            package_browser_smoke._restart_after_clean_shutdown(
                client=client,
                clean_shutdown={
                    "fatalCount": 0,
                    "shutdownRequested": True,
                    "shutdownDisabled": True,
                    "runtimeExitCode": 0,
                    "processExitCode": 1,
                },
                restart_url="http://127.0.0.1:32123/?m9_package_epoch=restart",
                debug_port=32124,
                deadline=123.0,
            )
        self.assertEqual([], client.calls)
        self.assertFalse(client.closed)
        wait_for_client.assert_not_called()

    def test_package_browser_clean_shutdown_requires_exact_distinct_exit_channels(
        self,
    ) -> None:
        clean_shutdown = {
            "fatalCount": 0,
            "shutdownRequested": True,
            "shutdownDisabled": True,
            "runtimeExitCode": 0,
            "processExitCode": 0,
        }
        self.assertTrue(package_browser_smoke._is_clean_shutdown(clean_shutdown))
        for description, mutation in (
            ("missing runtime exit", {"runtimeExitCode": None}),
            ("missing native exit", {"processExitCode": None}),
            ("runtime boolean alias", {"runtimeExitCode": False}),
            ("runtime float alias", {"runtimeExitCode": 0.0}),
            ("native boolean alias", {"processExitCode": False}),
            ("native float alias", {"processExitCode": 0.0}),
            ("runtime nonzero", {"runtimeExitCode": 1}),
            ("native nonzero", {"processExitCode": 1}),
            ("mismatched exits", {"runtimeExitCode": 0, "processExitCode": 1}),
        ):
            with self.subTest(description=description):
                invalid = {**clean_shutdown, **mutation}
                self.assertFalse(package_browser_smoke._is_clean_shutdown(invalid))
                with self.assertRaisesRegex(
                    M0Error, "runtime and native process exit codes 0"
                ):
                    package_browser_smoke._require_clean_shutdown(
                        invalid, "fixed package-host shutdown"
                    )

    def test_package_browser_shutdown_revalidates_ready_document_and_metadata(
        self,
    ) -> None:
        expected_metadata = package.package_runtime_status_metadata(
            (self._stage() / "VERSION.json").read_bytes()
        )
        expected_url = package_browser_smoke._make_epoch_url(
            "http://127.0.0.1:32123/", "ready-epoch"
        )

        def terminal_status() -> dict[str, object]:
            return {
                "fatalCount": 0,
                "shutdownRequested": True,
                "shutdownDisabled": True,
                "runtimeExitCode": 0,
                "processExitCode": 0,
                "packageMetadata": deepcopy(expected_metadata),
                "documentIdentity": {
                    "href": expected_url,
                    "navigation": {
                        "name": expected_url,
                        "startTime": 0,
                        "type": "navigate",
                    },
                    "timeOrigin": 1000.0,
                },
            }

        client = mock.Mock()

        def request(status: dict[str, object]) -> dict[str, object]:
            with mock.patch.object(
                package_browser_smoke, "_wait_for_status", return_value=status
            ):
                return package_browser_smoke._request_clean_shutdown(
                    client=client,
                    browser=mock.Mock(),
                    browser_stderr=deque(),
                    deadline=123.0,
                    expected_url=expected_url,
                    expected_epoch="ready-epoch",
                    expected_package_metadata=expected_metadata,
                    expected_time_origin=1000.0,
                    description="waiting for fixed package-host shutdown",
                )

        accepted = terminal_status()
        self.assertEqual(accepted, request(accepted))
        client.evaluate.assert_called_once_with(
            'document.querySelector("#shutdown").click(); true'
        )

        foreign_document = terminal_status()
        foreign_url = package_browser_smoke._make_epoch_url(
            "http://127.0.0.1:32123/", "foreign-epoch"
        )
        foreign_document["documentIdentity"] = {
            "href": foreign_url,
            "navigation": {
                "name": foreign_url,
                "startTime": 0,
                "type": "navigate",
            },
            "timeOrigin": 1000.0,
        }
        with self.assertRaisesRegex(M0Error, "document URL does not match"):
            request(foreign_document)

        reloaded_document = terminal_status()
        reloaded_document["documentIdentity"]["timeOrigin"] = 1001.0  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "time origin does not match ready document"):
            request(reloaded_document)

        substituted_metadata = terminal_status()
        substituted_metadata["packageMetadata"]["releaseStatus"] = "forged"  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "immutable VERSION.json snapshot"):
            request(substituted_metadata)

    def test_package_browser_sticky_fatal_health_rejects_evicted_record(self) -> None:
        # The host record history is bounded to 32 entries. Model a fatal that
        # was followed by enough ordinary records to evict its own record, then
        # a valid-looking readiness report that used to overwrite page state.
        status = {
            "crossOriginIsolated": True,
            "displayedVersions": (
                "staging checkout test artifact source provenance unverified"
            ),
            "fatalCount": 1,
            "framesPresented": 1,
            "pageState": "running",
            "runtimeExitCode": 0,
            "processExitCode": 0,
            "readiness": {"surfaceReady": True},
            "records": [
                {"kind": "stdout", "value": f"ordinary record {index}"}
                for index in range(32)
            ],
            "releaseStatus": package.RELEASE_STATUS,
            "runtimeArtifactsVerified": True,
            "runtimeInitialized": True,
            "shutdownDisabled": True,
            "shutdownRequested": True,
        }

        self.assertEqual(32, len(status["records"]))
        self.assertTrue(
            all(record["kind"] != "fatal" for record in status["records"])
        )
        self.assertFalse(package_browser_smoke._is_ready(status))
        self.assertFalse(package_browser_smoke._is_clean_shutdown(status))
        with self.assertRaisesRegex(M0Error, "reported 1 fatal errors"):
            package_browser_smoke._validate_fatal_health(status)

        healthy = deepcopy(status)
        healthy["fatalCount"] = 0
        self.assertTrue(package_browser_smoke._is_ready(healthy))
        self.assertTrue(package_browser_smoke._is_clean_shutdown(healthy))
        for invalid_count in (
            True,
            0.0,
            -1,
            package_browser_smoke.MAX_SAFE_INTEGER + 1,
        ):
            with self.subTest(invalid_count=invalid_count):
                invalid = deepcopy(healthy)
                invalid["fatalCount"] = invalid_count
                self.assertFalse(package_browser_smoke._is_ready(invalid))
                self.assertFalse(package_browser_smoke._is_clean_shutdown(invalid))
                with self.assertRaisesRegex(M0Error, "fatal count is invalid"):
                    package_browser_smoke._validate_fatal_health(invalid)

    def test_package_browser_closes_unstarted_server_without_shutdown(self) -> None:
        server = mock.Mock()
        server.shutdown.side_effect = AssertionError(
            "an unstarted server must not be shut down"
        )
        server_thread = mock.Mock()
        server_thread.start.side_effect = RuntimeError("server thread start failed")

        with (
            mock.patch.object(
                package_browser_smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                package_browser_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_browser_smoke.threading,
                "Thread",
                return_value=server_thread,
            ),
            mock.patch.object(package_browser_smoke.subprocess, "Popen") as popen,
            self.assertRaisesRegex(RuntimeError, "server thread start failed"),
        ):
            package_browser_smoke.run_package_browser_smoke(
                dist_dir=Path("/fake/dist"),
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
            )

        server.shutdown.assert_not_called()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_not_called()
        popen.assert_not_called()

    def test_package_browser_preserves_unstarted_stderr_reader_failure(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        server.snapshot = snapshot_package_tree(self._stage())
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = True
        browser = mock.Mock()
        browser.stderr = object()
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        stderr_thread = mock.Mock()
        stderr_thread.start.side_effect = RuntimeError("stderr reader start failed")
        stderr_thread.join.side_effect = RuntimeError(
            "cannot join thread before it is started"
        )

        with (
            mock.patch.object(
                package_browser_smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                package_browser_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_browser_smoke.threading,
                "Thread",
                side_effect=[server_thread, stderr_thread],
            ),
            mock.patch.object(
                package_browser_smoke.tempfile,
                "TemporaryDirectory",
                return_value=profile,
            ),
            mock.patch.object(
                package_browser_smoke, "unused_loopback_port", return_value=32124
            ),
            mock.patch.object(
                package_browser_smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(
                package_browser_smoke.subprocess,
                "Popen",
                return_value=browser,
            ),
            mock.patch.object(
                package_browser_smoke,
                "abort_browser_group",
                side_effect=RuntimeError("browser cleanup failed"),
            ) as abort_browser_group,
            self.assertRaisesRegex(RuntimeError, "stderr reader start failed"),
        ):
            package_browser_smoke.run_package_browser_smoke(
                dist_dir=Path("/fake/dist"),
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
            )

        server_thread.start.assert_called_once_with()
        abort_browser_group.assert_called_once_with(browser, mock.ANY)
        stderr_thread.join.assert_not_called()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=5)
        server_thread.is_alive.assert_called_once_with()
        profile.cleanup.assert_called_once_with()

    def test_package_browser_restart_closes_stale_client_and_reattaches_exact_url(
        self,
    ) -> None:
        class StaleClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []
                self.closed = False

            def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
                self.calls.append((method, params))
                return {"frameId": "fresh-frame"}

            def close(self) -> None:
                self.closed = True

        client = StaleClient()
        fresh_client = object()
        restart_url = "http://127.0.0.1:32123/?m9_package_epoch=restart"
        with mock.patch.object(
            package_browser_smoke,
            "wait_for_page_client",
            return_value=fresh_client,
        ) as wait_for_client:
            result = package_browser_smoke._restart_after_clean_shutdown(
                client=client,
                clean_shutdown={
                    "fatalCount": 0,
                    "shutdownRequested": True,
                    "shutdownDisabled": True,
                    "runtimeExitCode": 0,
                    "processExitCode": 0,
                },
                restart_url=restart_url,
                debug_port=32124,
                deadline=123.0,
            )
        self.assertIs(fresh_client, result)
        self.assertEqual([("Page.navigate", {"url": restart_url})], client.calls)
        self.assertTrue(client.closed)
        wait_for_client.assert_called_once_with(32124, restart_url, 123.0)

    def test_package_startup_observation_reports_raw_snapshot_bytes_only(self) -> None:
        server = mock.Mock()
        server.snapshot = snapshot_package_tree(self._stage())
        artifacts = server.snapshot.artifacts
        with mock.patch.object(
            package_browser_smoke.time, "monotonic", return_value=12.5
        ):
            result = package_browser_smoke._package_startup_observation(
                server=server,
                ready={"runtimeArtifactsVerified": True},
                launch_started_at=10.0,
            )

        self.assertEqual(
            {
                "artifact_bytes": {
                    "loader_raw_bytes": len(artifacts["chromium-wasm.js"]),
                    "package_raw_bytes": sum(
                        len(value) for value in artifacts.values()
                    ),
                    "snapshot_artifact_count": len(artifacts),
                    "wasm_raw_bytes": len(artifacts["chromium-wasm.wasm"]),
                    "versioned_artifact_count": len(artifacts) - 1,
                },
                "artifact_delivery": (
                    package_browser_smoke.PACKAGE_OBSERVATION_ARTIFACT_DELIVERY
                ),
                "browser_launch_to_ready_observed_ms": 2500.0,
                "compression": package_browser_smoke.PACKAGE_OBSERVATION_COMPRESSION,
                "m9_gate_complete": False,
                "measurement_limits": list(
                    package_browser_smoke.PACKAGE_OBSERVATION_LIMITS
                ),
                "performance_gate": False,
                "release_status": package.RELEASE_STATUS,
                "runtime_artifacts_verified": True,
                "schema_version": (
                    package_browser_smoke.PACKAGE_OBSERVATION_SCHEMA_VERSION
                ),
                "scope": package_browser_smoke.PACKAGE_OBSERVATION_SCOPE,
            },
            result,
        )

    def test_package_startup_observation_rejects_unverified_runtime(self) -> None:
        with self.assertRaisesRegex(
            M0Error, "package observation requires verified runtime artifacts"
        ):
            package_browser_smoke._package_startup_observation(
                server=mock.Mock(),
                ready={"runtimeArtifactsVerified": False},
                launch_started_at=0.0,
            )

    def test_runtime_core_resource_receipt_requires_exact_paths_and_roles(self) -> None:
        receipt = _runtime_core_resource_receipt()
        self.assertEqual(
            receipt,
            package_browser_smoke.validate_runtime_core_resource_receipt(receipt),
        )

        missing = deepcopy(receipt)
        missing.pop()
        wrong_path = deepcopy(receipt)
        wrong_path[2]["path"] = "unexpected-resource.js"
        wrong_initiator = deepcopy(receipt)
        fetch_index = next(
            index
            for index, item in enumerate(wrong_initiator)
            if item["initiator_type"] == "fetch"
        )
        wrong_initiator[fetch_index]["initiator_type"] = "script"
        malformed = deepcopy(receipt)
        malformed[0].pop("initiator_type")
        for name, value, message in (
            ("missing", missing, "is incomplete"),
            ("wrong path", wrong_path, "path is invalid"),
            ("wrong initiator", wrong_initiator, "initiator is invalid"),
            ("malformed", malformed, "is malformed"),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(M0Error, message):
                package_browser_smoke.validate_runtime_core_resource_receipt(value)

    def test_runtime_core_resource_receipt_query_is_read_only_and_document_scoped(
        self,
    ) -> None:
        expected_url = "http://127.0.0.1:32123/?m9_package_epoch=receipt"
        expression = package_browser_smoke._runtime_core_resource_receipt_expression(
            expected_url
        )
        self.assertIn('performance.getEntriesByType("resource")', expression)
        self.assertIn("location.href !== expectedDocumentUrl", expression)
        self.assertIn("resourceUrl.origin !== documentUrl.origin", expression)
        self.assertIn("resourceUrl.search !== \"\"", expression)
        self.assertNotIn("fetch(", expression)
        self.assertIn(json.dumps(expected_url), expression)
        for path, initiator_type in package_browser_smoke.RUNTIME_CORE_RESOURCE_RECEIPT:
            with self.subTest(path=path):
                self.assertIn(json.dumps(path), expression)
                self.assertIn(json.dumps(initiator_type), expression)

        class Client:
            def __init__(self, result: object) -> None:
                self.result = result
                self.expressions: list[str] = []

            def evaluate(self, value: str) -> object:
                self.expressions.append(value)
                return self.result

        client = Client(_runtime_core_resource_receipt())
        self.assertEqual(
            _runtime_core_resource_receipt(),
            package_browser_smoke._capture_runtime_core_resource_receipt(
                client, expected_url=expected_url
            ),
        )
        self.assertEqual([expression], client.expressions)

        missing = _runtime_core_resource_receipt()
        missing.pop()
        with self.assertRaisesRegex(M0Error, "is incomplete"):
            package_browser_smoke._capture_runtime_core_resource_receipt(
                Client(missing), expected_url=expected_url
            )
        for invalid_url in (
            "https://127.0.0.1:32123/",
            "http://127.0.0.1:32123/#fragment",
            "not-a-url",
        ):
            with self.subTest(invalid_url=invalid_url), self.assertRaisesRegex(
                M0Error, "receipt URL is invalid"
            ):
                package_browser_smoke._runtime_core_resource_receipt_expression(
                    invalid_url
                )

    def test_runtime_core_server_receipt_requires_exact_successful_gets(self) -> None:
        receipt = _runtime_core_server_receipt()
        self.assertEqual(
            receipt,
            package_browser_smoke.validate_runtime_core_server_receipt(receipt),
        )
        missing = deepcopy(receipt)
        missing.pop()
        wrong_path = deepcopy(receipt)
        wrong_path[1]["path"] = "forged-resource.js"
        repeated_get = deepcopy(receipt)
        repeated_get[2]["successful_get_count"] = 2
        bool_get = deepcopy(receipt)
        bool_get[3]["successful_get_count"] = True
        malformed = deepcopy(receipt)
        malformed[0].pop("successful_get_count")
        for name, value, message in (
            ("missing", missing, "is incomplete"),
            ("wrong path", wrong_path, "path is invalid"),
            ("repeated GET", repeated_get, "successful GET count is invalid"),
            ("boolean GET", bool_get, "successful GET count is invalid"),
            ("malformed", malformed, "is malformed"),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(M0Error, message):
                package_browser_smoke.validate_runtime_core_server_receipt(value)

    def test_epoch_document_url_and_server_receipt_bind_one_token(self) -> None:
        epoch = "server_receipt-token"
        server = mock.Mock()
        server.register_epoch_route.return_value = (
            f"{package_smoke.EPOCH_ROUTE_PREFIX}{epoch}/"
        )
        server.epoch_successful_get_counts.return_value = {
            "/": 1,
            **{
                f"/{path}": 1
                for path, _initiator in (
                    package_browser_smoke.RUNTIME_CORE_RESOURCE_RECEIPT
                )
            },
        }
        self.assertEqual(
            (
                "http://127.0.0.1:32123"
                f"{package_smoke.EPOCH_ROUTE_PREFIX}{epoch}/"
                f"?m9_package_epoch={epoch}"
            ),
            package_browser_smoke._register_epoch_document_url(
                server, "http://127.0.0.1:32123/", epoch
            ),
        )
        server.register_epoch_route.assert_called_once_with(epoch)
        self.assertEqual(
            _runtime_core_server_receipt(),
            package_browser_smoke._capture_runtime_core_server_receipt(
                server, epoch=epoch
            ),
        )
        server.epoch_successful_get_counts.assert_called_once_with(epoch)

        server.register_epoch_route.return_value = "/unexpected/"
        with self.assertRaisesRegex(M0Error, "epoch route is invalid"):
            package_browser_smoke._register_epoch_document_url(
                server, "http://127.0.0.1:32123/", epoch
            )
        server.epoch_successful_get_counts.return_value = {
            "/chromium-wasm-host.js": 0
        }
        with self.assertRaisesRegex(M0Error, "server receipt"):
            package_browser_smoke._capture_runtime_core_server_receipt(
                server, epoch=epoch
            )

    def test_package_browser_default_result_remains_one_clean_epoch(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        server.snapshot = snapshot_package_tree(self._stage())
        expected_metadata = package.package_runtime_status_metadata(
            server.snapshot.artifacts["VERSION.json"]
        )
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        stderr_thread = mock.Mock()
        browser = mock.Mock()
        browser.stderr = object()
        browser.poll.return_value = None
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        client = mock.Mock()
        ready = {
            "fatalCount": 0,
            "framesPresented": 7,
            "releaseStatus": package.RELEASE_STATUS,
        }
        shutdown = {
            "fatalCount": 0,
            "shutdownRequested": True,
            "shutdownDisabled": True,
            "runtimeExitCode": 0,
            "processExitCode": 0,
        }

        with (
            mock.patch.object(
                package_browser_smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                package_browser_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_browser_smoke.threading,
                "Thread",
                side_effect=[server_thread, stderr_thread],
            ),
            mock.patch.object(
                package_browser_smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(
                package_browser_smoke.subprocess,
                "Popen",
                return_value=browser,
            ),
            mock.patch.object(
                package_browser_smoke.tempfile,
                "TemporaryDirectory",
                return_value=profile,
            ),
            mock.patch.object(
                package_browser_smoke, "unused_loopback_port", return_value=32124
            ),
            mock.patch.object(
                package_browser_smoke,
                "wait_for_page_client",
                return_value=client,
            ) as wait_for_client,
            mock.patch.object(
                package_browser_smoke,
                "_wait_for_ready_package_document",
                return_value=(ready, 1000.0),
            ) as wait_for_ready,
            mock.patch.object(
                package_browser_smoke,
                "_request_clean_shutdown",
                return_value=shutdown,
            ) as request_shutdown,
            mock.patch.object(
                package_browser_smoke.secrets,
                "token_urlsafe",
                return_value="first-epoch",
            ),
            mock.patch.object(
                package_browser_smoke, "stop_browser_group"
            ) as stop_browser_group,
            mock.patch.object(
                package_browser_smoke, "_restart_after_clean_shutdown"
            ) as restart,
            mock.patch.object(
                package_browser_smoke,
                "_capture_runtime_core_resource_receipt",
                return_value=_runtime_core_resource_receipt(),
            ) as capture_resource_receipt,
        ):
            result = package_browser_smoke.run_package_browser_smoke(
                dist_dir=Path("/fake/dist"),
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
            )

        initial_url = "http://127.0.0.1:32123/?m9_package_epoch=first-epoch"
        self.assertEqual(
            {
                "browser_version": "test-browser",
                "frames_presented": 7,
                "runtime_exit_code": 0,
                "process_exit_code": 0,
                "release_status": package.RELEASE_STATUS,
                "scope": package_browser_smoke.SCOPE,
                "served_version_json_sha256": expected_metadata[
                    "versionJsonSha256"
                ],
                "shutdown_disabled": True,
                "shutdown_requested": True,
            },
            result,
        )
        wait_for_client.assert_called_once()
        self.assertEqual(initial_url, wait_for_client.call_args.args[1])
        self.assertEqual(initial_url, wait_for_ready.call_args.kwargs["expected_url"])
        self.assertEqual("first-epoch", wait_for_ready.call_args.kwargs["expected_epoch"])
        self.assertFalse(
            wait_for_ready.call_args.kwargs["expected_wisp_configured"]
        )
        self.assertEqual(
            expected_metadata,
            wait_for_ready.call_args.kwargs["expected_package_metadata"],
        )
        request_shutdown.assert_called_once()
        self.assertEqual(
            initial_url, request_shutdown.call_args.kwargs["expected_url"]
        )
        self.assertEqual(
            "first-epoch", request_shutdown.call_args.kwargs["expected_epoch"]
        )
        self.assertEqual(
            expected_metadata,
            request_shutdown.call_args.kwargs["expected_package_metadata"],
        )
        self.assertEqual(
            1000.0, request_shutdown.call_args.kwargs["expected_time_origin"]
        )
        restart.assert_not_called()
        capture_resource_receipt.assert_not_called()
        stop_browser_group.assert_called_once_with(browser, mock.ANY)

    def test_package_browser_opt_in_adds_only_bounded_observation(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        server.snapshot = snapshot_package_tree(self._stage())
        expected_metadata = package.package_runtime_status_metadata(
            server.snapshot.artifacts["VERSION.json"]
        )
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        stderr_thread = mock.Mock()
        browser = mock.Mock()
        browser.stderr = object()
        browser.poll.return_value = None
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        client = mock.Mock()
        ready = {
            "fatalCount": 0,
            "framesPresented": 7,
            "releaseStatus": package.RELEASE_STATUS,
            "runtimeArtifactsVerified": True,
        }
        shutdown = {
            "fatalCount": 0,
            "shutdownRequested": True,
            "shutdownDisabled": True,
            "runtimeExitCode": 0,
            "processExitCode": 0,
        }
        observation = {"bounded": "observation"}

        with (
            mock.patch.object(
                package_browser_smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                package_browser_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_browser_smoke.threading,
                "Thread",
                side_effect=[server_thread, stderr_thread],
            ),
            mock.patch.object(
                package_browser_smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(
                package_browser_smoke.subprocess,
                "Popen",
                return_value=browser,
            ),
            mock.patch.object(
                package_browser_smoke.tempfile,
                "TemporaryDirectory",
                return_value=profile,
            ),
            mock.patch.object(
                package_browser_smoke, "unused_loopback_port", return_value=32124
            ),
            mock.patch.object(
                package_browser_smoke,
                "wait_for_page_client",
                return_value=client,
            ),
            mock.patch.object(
                package_browser_smoke,
                "_wait_for_ready_package_document",
                return_value=(ready, 1000.0),
            ),
            mock.patch.object(
                package_browser_smoke,
                "_request_clean_shutdown",
                return_value=shutdown,
            ),
            mock.patch.object(
                package_browser_smoke.secrets,
                "token_urlsafe",
                return_value="first-epoch",
            ),
            mock.patch.object(package_browser_smoke, "stop_browser_group"),
            mock.patch.object(
                package_browser_smoke,
                "_package_startup_observation",
                return_value=observation,
            ) as package_observation,
        ):
            result = package_browser_smoke.run_package_browser_smoke(
                dist_dir=Path("/fake/dist"),
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
                emit_package_observation=True,
            )

        self.assertEqual(
            {
                "browser_version": "test-browser",
                "frames_presented": 7,
                "runtime_exit_code": 0,
                "process_exit_code": 0,
                "release_status": package.RELEASE_STATUS,
                "scope": package_browser_smoke.SCOPE,
                "served_version_json_sha256": expected_metadata[
                    "versionJsonSha256"
                ],
                "shutdown_disabled": True,
                "shutdown_requested": True,
                "package_observation": observation,
            },
            result,
        )
        package_observation.assert_called_once_with(
            server=server,
            ready=ready,
            launch_started_at=mock.ANY,
        )
        self.assertIsInstance(
            package_observation.call_args.kwargs["launch_started_at"], float
        )

    def test_package_browser_observation_rejects_wisp_configuration(self) -> None:
        with mock.patch.object(package_browser_smoke, "find_browser") as find_browser:
            with self.assertRaisesRegex(
                M0Error, "requires the default WISP-disabled path"
            ):
                package_browser_smoke.run_package_browser_smoke(
                    dist_dir=Path("/fake/dist"),
                    browser_argument=None,
                    no_sandbox=False,
                    timeout=120.0,
                    release_wisp_endpoint="wss://carrier.example/",
                    emit_package_observation=True,
                )
        find_browser.assert_not_called()

    def test_package_browser_main_passes_opt_in_observation_flag(self) -> None:
        stdout = io.StringIO()
        result = {"bounded": "observation"}
        with (
            mock.patch.object(
                package_browser_smoke,
                "run_package_browser_smoke",
                return_value=result,
            ) as run_package_browser_smoke,
            mock.patch.object(
                sys,
                "argv",
                [
                    "package-browser",
                    "--dist-dir",
                    "/fake/dist",
                    "--emit-package-observation",
                ],
            ),
            mock.patch.object(sys, "stdout", stdout),
        ):
            self.assertEqual(0, package_browser_smoke.main())

        run_package_browser_smoke.assert_called_once_with(
            dist_dir=Path("/fake/dist"),
            browser_argument=None,
            no_sandbox=False,
            timeout=120.0,
            outer_document_restart=False,
            outer_document_restart_count=0,
            release_wisp_endpoint=None,
            emit_package_observation=True,
        )
        self.assertEqual(
            f"{package_browser_smoke.SENTINEL}:BROWSER_SMOKE_PASS "
            + '{"bounded":"observation"}\n',
            stdout.getvalue(),
        )

    def test_package_browser_main_rejects_browser_cleanup_without_pass_marker(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        server.snapshot = snapshot_package_tree(self._stage())
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = True
        stderr_thread = mock.Mock()
        browser = mock.Mock()
        browser.stderr = object()
        browser.poll.return_value = None
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        client = mock.Mock()
        ready = {
            "fatalCount": 0,
            "framesPresented": 7,
            "releaseStatus": package.RELEASE_STATUS,
        }
        shutdown = {
            "fatalCount": 0,
            "shutdownRequested": True,
            "shutdownDisabled": True,
            "runtimeExitCode": 0,
            "processExitCode": 0,
        }
        stdout = io.StringIO()

        with (
            mock.patch.object(
                package_browser_smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                package_browser_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_browser_smoke.threading,
                "Thread",
                side_effect=[server_thread, stderr_thread],
            ),
            mock.patch.object(
                package_browser_smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(
                package_browser_smoke.subprocess,
                "Popen",
                return_value=browser,
            ),
            mock.patch.object(
                package_browser_smoke.tempfile,
                "TemporaryDirectory",
                return_value=profile,
            ),
            mock.patch.object(
                package_browser_smoke, "unused_loopback_port", return_value=32124
            ),
            mock.patch.object(
                package_browser_smoke,
                "wait_for_page_client",
                return_value=client,
            ),
            mock.patch.object(
                package_browser_smoke,
                "_wait_for_ready_package_document",
                return_value=(ready, 1000.0),
            ),
            mock.patch.object(
                package_browser_smoke,
                "_request_clean_shutdown",
                return_value=shutdown,
            ),
            mock.patch.object(
                package_browser_smoke.secrets,
                "token_urlsafe",
                return_value="first-epoch",
            ),
            mock.patch.object(
                package_browser_smoke,
                "stop_browser_group",
                side_effect=M0Error("browser group cleanup failed"),
            ),
            mock.patch.object(
                sys,
                "argv",
                ["package-browser", "--dist-dir", "/fake/dist"],
            ),
            mock.patch.object(sys, "stdout", stdout),
        ):
            self.assertEqual(1, package_browser_smoke.main())

        self.assertIn(f"{package_browser_smoke.SENTINEL}:BROWSER_SMOKE_FAIL", stdout.getvalue())
        self.assertNotIn(f"{package_browser_smoke.SENTINEL}:BROWSER_SMOKE_PASS", stdout.getvalue())
        self.assertIn("browser group cleanup failed", stdout.getvalue())
        server_thread.start.assert_called_once_with()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=5)
        server_thread.is_alive.assert_called_once_with()

    def test_package_browser_restart_result_has_two_clean_epoch_records(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        server.snapshot = snapshot_package_tree(self._stage())
        expected_metadata = package.package_runtime_status_metadata(
            server.snapshot.artifacts["VERSION.json"]
        )
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        stderr_thread = mock.Mock()
        browser = mock.Mock()
        browser.stderr = object()
        browser.poll.return_value = None
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        first_client = mock.Mock()
        second_client = mock.Mock()
        first_ready = {
            "fatalCount": 0,
            "framesPresented": 7,
            "releaseStatus": package.RELEASE_STATUS,
        }
        second_ready = {
            "fatalCount": 0,
            "framesPresented": 11,
            "releaseStatus": package.RELEASE_STATUS,
        }
        clean_shutdown = {
            "fatalCount": 0,
            "shutdownRequested": True,
            "shutdownDisabled": True,
            "runtimeExitCode": 0,
            "processExitCode": 0,
        }

        with (
            mock.patch.object(
                package_browser_smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                package_browser_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_browser_smoke.threading,
                "Thread",
                side_effect=[server_thread, stderr_thread],
            ),
            mock.patch.object(
                package_browser_smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(
                package_browser_smoke.subprocess,
                "Popen",
                return_value=browser,
            ),
            mock.patch.object(
                package_browser_smoke.tempfile,
                "TemporaryDirectory",
                return_value=profile,
            ),
            mock.patch.object(
                package_browser_smoke, "unused_loopback_port", return_value=32124
            ),
            mock.patch.object(
                package_browser_smoke,
                "wait_for_page_client",
                return_value=first_client,
            ),
            mock.patch.object(
                package_browser_smoke,
                "_wait_for_ready_package_document",
                side_effect=[(first_ready, 1000.0), (second_ready, 1001.0)],
            ) as wait_for_ready,
            mock.patch.object(
                package_browser_smoke,
                "_request_clean_shutdown",
                side_effect=[clean_shutdown, clean_shutdown],
            ) as request_shutdown,
            mock.patch.object(
                package_browser_smoke.secrets,
                "token_urlsafe",
                side_effect=["first-epoch", "restart-epoch"],
            ),
            mock.patch.object(
                package_browser_smoke, "stop_browser_group"
            ) as stop_browser_group,
            mock.patch.object(
                package_browser_smoke,
                "_restart_after_clean_shutdown",
                return_value=second_client,
            ) as restart,
            mock.patch.object(
                package_browser_smoke,
                "_capture_runtime_core_resource_receipt",
                return_value=_runtime_core_resource_receipt(),
            ) as capture_resource_receipt,
        ):
            result = package_browser_smoke.run_package_browser_smoke(
                dist_dir=Path("/fake/dist"),
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
                outer_document_restart=True,
            )

        self.assertEqual(
            {
                "browser_version": "test-browser",
                "epochs": [
                    {
                        "frames_presented": 7,
                        "runtime_exit_code": 0,
                        "process_exit_code": 0,
                        "shutdown_disabled": True,
                        "shutdown_requested": True,
                    },
                    {
                        "frames_presented": 11,
                        "runtime_exit_code": 0,
                        "process_exit_code": 0,
                        "shutdown_disabled": True,
                        "shutdown_requested": True,
                    },
                ],
                "outer_document_restart": True,
                "release_status": package.RELEASE_STATUS,
                "scope": package_browser_smoke.OUTER_DOCUMENT_RESTART_SCOPE,
                "served_version_json_sha256": expected_metadata[
                    "versionJsonSha256"
                ],
            },
            result,
        )
        self.assertEqual(2, wait_for_ready.call_count)
        self.assertEqual(2, request_shutdown.call_count)
        restart.assert_called_once()
        capture_resource_receipt.assert_not_called()
        stop_browser_group.assert_called_once_with(browser, mock.ANY)
        self.assertEqual(
            "http://127.0.0.1:32123/?m9_package_epoch=restart-epoch",
            restart.call_args.kwargs["restart_url"],
        )
        self.assertEqual(1000.0, wait_for_ready.call_args_list[1].kwargs["prior_time_origin"])
        self.assertEqual(
            expected_metadata,
            wait_for_ready.call_args_list[0].kwargs["expected_package_metadata"],
        )
        self.assertEqual(
            expected_metadata,
            wait_for_ready.call_args_list[1].kwargs["expected_package_metadata"],
        )
        self.assertEqual(
            [False, False],
            [
                call.kwargs["expected_wisp_configured"]
                for call in wait_for_ready.call_args_list
            ],
        )
        first_shutdown_kwargs = request_shutdown.call_args_list[0].kwargs
        self.assertEqual(
            "http://127.0.0.1:32123/?m9_package_epoch=first-epoch",
            first_shutdown_kwargs["expected_url"],
        )
        self.assertEqual("first-epoch", first_shutdown_kwargs["expected_epoch"])
        self.assertEqual(
            expected_metadata, first_shutdown_kwargs["expected_package_metadata"]
        )
        self.assertEqual(1000.0, first_shutdown_kwargs["expected_time_origin"])
        second_shutdown_kwargs = request_shutdown.call_args_list[1].kwargs
        self.assertEqual(
            "http://127.0.0.1:32123/?m9_package_epoch=restart-epoch",
            second_shutdown_kwargs["expected_url"],
        )
        self.assertEqual("restart-epoch", second_shutdown_kwargs["expected_epoch"])
        self.assertEqual(
            expected_metadata, second_shutdown_kwargs["expected_package_metadata"]
        )
        self.assertEqual(1001.0, second_shutdown_kwargs["expected_time_origin"])

    def test_package_browser_three_epochs_retain_resource_receipts(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        server.snapshot = snapshot_package_tree(self._stage())
        server.register_epoch_route.side_effect = [
            f"{package_smoke.EPOCH_ROUTE_PREFIX}first-epoch/",
            f"{package_smoke.EPOCH_ROUTE_PREFIX}second-epoch/",
            f"{package_smoke.EPOCH_ROUTE_PREFIX}third-epoch/",
        ]
        expected_metadata = package.package_runtime_status_metadata(
            server.snapshot.artifacts["VERSION.json"]
        )
        server_thread = mock.Mock()
        server_thread.is_alive.return_value = False
        stderr_thread = mock.Mock()
        browser = mock.Mock()
        browser.stderr = object()
        browser.poll.return_value = None
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        first_client = mock.Mock()
        second_client = mock.Mock()
        third_client = mock.Mock()
        ready = [
            {
                "fatalCount": 0,
                "framesPresented": frame_count,
                "releaseStatus": package.RELEASE_STATUS,
            }
            for frame_count in (7, 11, 13)
        ]
        shutdown = {
            "fatalCount": 0,
            "shutdownRequested": True,
            "shutdownDisabled": True,
            "runtimeExitCode": 0,
            "processExitCode": 0,
        }
        receipt = _runtime_core_resource_receipt()
        server_receipt = _runtime_core_server_receipt()

        with (
            mock.patch.object(
                package_browser_smoke,
                "find_browser",
                return_value=(Path("/fake/browser"), "test-browser"),
            ),
            mock.patch.object(
                package_browser_smoke,
                "create_package_smoke_server",
                return_value=server,
            ),
            mock.patch.object(
                package_browser_smoke.threading,
                "Thread",
                side_effect=[server_thread, stderr_thread],
            ),
            mock.patch.object(
                package_browser_smoke,
                "browser_command",
                return_value=["/fake/browser", "profile", "url"],
            ),
            mock.patch.object(
                package_browser_smoke.subprocess,
                "Popen",
                return_value=browser,
            ),
            mock.patch.object(
                package_browser_smoke.tempfile,
                "TemporaryDirectory",
                return_value=profile,
            ),
            mock.patch.object(
                package_browser_smoke, "unused_loopback_port", return_value=32124
            ),
            mock.patch.object(
                package_browser_smoke,
                "wait_for_page_client",
                return_value=first_client,
            ),
            mock.patch.object(
                package_browser_smoke,
                "_wait_for_ready_package_document",
                side_effect=[
                    (ready[0], 1000.0),
                    (ready[1], 1001.0),
                    (ready[2], 1002.0),
                ],
            ) as wait_for_ready,
            mock.patch.object(
                package_browser_smoke,
                "_request_clean_shutdown",
                side_effect=[shutdown, shutdown, shutdown],
            ) as request_shutdown,
            mock.patch.object(
                package_browser_smoke.secrets,
                "token_urlsafe",
                side_effect=["first-epoch", "second-epoch", "third-epoch"],
            ),
            mock.patch.object(
                package_browser_smoke, "stop_browser_group"
            ) as stop_browser_group,
            mock.patch.object(
                package_browser_smoke,
                "_restart_after_clean_shutdown",
                side_effect=[second_client, third_client],
            ) as restart,
            mock.patch.object(
                package_browser_smoke,
                "_capture_runtime_core_resource_receipt",
                side_effect=[deepcopy(receipt), deepcopy(receipt), deepcopy(receipt)],
            ) as capture_resource_receipt,
            mock.patch.object(
                package_browser_smoke,
                "_capture_runtime_core_server_receipt",
                side_effect=[
                    deepcopy(server_receipt),
                    deepcopy(server_receipt),
                    deepcopy(server_receipt),
                ],
            ) as capture_server_receipt,
            mock.patch.object(
                package_browser_smoke,
                "_observe_post_exit_frame_quiescence",
            ) as observe_quiescence,
        ):
            result = package_browser_smoke.run_package_browser_smoke(
                dist_dir=Path("/fake/dist"),
                browser_argument=None,
                no_sandbox=False,
                timeout=120.0,
                outer_document_restart_count=(
                    package_browser_smoke.OUTER_DOCUMENT_RELOAD_STRESS_RESTART_COUNT
                ),
            )

        self.assertEqual(
            {
                "browser_version": "test-browser",
                "distinct_document_epoch_count": 3,
                "distinct_document_time_origin_count": 3,
                "epochs": [
                    {
                        "frames_presented": 7,
                        "post_exit_frame_quiescent": True,
                        "process_exit_code": 0,
                        "runtime_core_resource_receipt": receipt,
                        "runtime_core_server_receipt": server_receipt,
                        "runtime_exit_code": 0,
                        "shutdown_disabled": True,
                        "shutdown_requested": True,
                    },
                    {
                        "frames_presented": 11,
                        "post_exit_frame_quiescent": True,
                        "process_exit_code": 0,
                        "runtime_core_resource_receipt": receipt,
                        "runtime_core_server_receipt": server_receipt,
                        "runtime_exit_code": 0,
                        "shutdown_disabled": True,
                        "shutdown_requested": True,
                    },
                    {
                        "frames_presented": 13,
                        "post_exit_frame_quiescent": True,
                        "process_exit_code": 0,
                        "runtime_core_resource_receipt": receipt,
                        "runtime_core_server_receipt": server_receipt,
                        "runtime_exit_code": 0,
                        "shutdown_disabled": True,
                        "shutdown_requested": True,
                    },
                ],
                "limitations": list(
                    package_browser_smoke.OUTER_DOCUMENT_RELOAD_STRESS_LIMITATIONS
                ),
                "m9_gate_complete": False,
                "outer_document_epoch_count": 3,
                "outer_document_restarts": 2,
                "performance_gate": False,
                "release_status": package.RELEASE_STATUS,
                "scope": package_browser_smoke.OUTER_DOCUMENT_RELOAD_STRESS_SCOPE,
                "served_version_json_sha256": expected_metadata[
                    "versionJsonSha256"
                ],
            },
            result,
        )
        self.assertEqual(3, wait_for_ready.call_count)
        self.assertEqual(3, request_shutdown.call_count)
        self.assertEqual(2, restart.call_count)
        self.assertEqual(3, observe_quiescence.call_count)
        self.assertEqual(
            [
                mock.call(
                    first_client,
                    expected_url=(
                        "http://127.0.0.1:32123"
                        f"{package_smoke.EPOCH_ROUTE_PREFIX}first-epoch/"
                        "?m9_package_epoch=first-epoch"
                    ),
                ),
                mock.call(
                    second_client,
                    expected_url=(
                        "http://127.0.0.1:32123"
                        f"{package_smoke.EPOCH_ROUTE_PREFIX}second-epoch/"
                        "?m9_package_epoch=second-epoch"
                    ),
                ),
                mock.call(
                    third_client,
                    expected_url=(
                        "http://127.0.0.1:32123"
                        f"{package_smoke.EPOCH_ROUTE_PREFIX}third-epoch/"
                        "?m9_package_epoch=third-epoch"
                    ),
                ),
            ],
            capture_resource_receipt.call_args_list,
        )
        self.assertEqual(
            [
                mock.call(server, epoch="first-epoch"),
                mock.call(server, epoch="second-epoch"),
                mock.call(server, epoch="third-epoch"),
            ],
            capture_server_receipt.call_args_list,
        )
        self.assertEqual(
            [
                mock.call("first-epoch"),
                mock.call("second-epoch"),
                mock.call("third-epoch"),
            ],
            server.register_epoch_route.call_args_list,
        )
        self.assertEqual(
            [False, False, False],
            [
                call.kwargs["expected_wisp_configured"]
                for call in wait_for_ready.call_args_list
            ],
        )
        stop_browser_group.assert_called_once_with(browser, mock.ANY)

    def test_package_browser_rejects_invalid_outer_document_restart_count(self) -> None:
        with mock.patch.object(package_browser_smoke, "find_browser") as find_browser:
            for value in (True, -1, package_browser_smoke.MAX_OUTER_DOCUMENT_RESTARTS + 1):
                with self.subTest(value=value), self.assertRaisesRegex(
                    M0Error, "restart count is invalid"
                ):
                    package_browser_smoke.run_package_browser_smoke(
                        dist_dir=Path("/fake/dist"),
                        browser_argument=None,
                        no_sandbox=False,
                        timeout=120.0,
                        outer_document_restart_count=value,
                    )
        find_browser.assert_not_called()

    def test_package_browser_rejects_conflicting_outer_restart_selection(self) -> None:
        with mock.patch.object(package_browser_smoke, "find_browser") as find_browser:
            with self.assertRaisesRegex(M0Error, "selection and count disagree"):
                package_browser_smoke.run_package_browser_smoke(
                    dist_dir=Path("/fake/dist"),
                    browser_argument=None,
                    no_sandbox=False,
                    timeout=120.0,
                    outer_document_restart=True,
                    outer_document_restart_count=2,
                )
        find_browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()

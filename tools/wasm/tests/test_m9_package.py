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
from typing import Callable
from unittest import mock

from tools.wasm import package
from tools.wasm import run_m9_package_browser_smoke as package_browser_smoke
from tools.wasm.m0_common import M0Error, REPO_ROOT, load_manifest
from tools.wasm.run_m9_package_smoke import package_response, run_package_smoke


PORT_REVISION = "a" * 40
ATTESTED_CHECKOUT = {"commit": PORT_REVISION, "tree": "b" * 40}


class M9PackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.manifest = load_manifest()
        self.clean_output_directories: list[tempfile.TemporaryDirectory[str]] = []

    def tearDown(self) -> None:
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

    def _clean_attestation_patches(self) -> tuple[mock._patch, mock._patch]:
        attestation = package.clean_build_attestation
        return (
            mock.patch.object(attestation, "require_clean_top_level_checkout"),
            mock.patch.object(
                attestation, "checkout_identity", return_value=ATTESTED_CHECKOUT
            ),
        )

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
        self.assertEqual(3, package.PACKAGE_SCHEMA_VERSION)
        self.assertEqual(3, version["schema_version"])
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

    def test_default_stage_ignores_an_optional_clean_build_record(self) -> None:
        out_dir, _ = self._make_attested_out_dir()
        attestation = package.clean_build_attestation
        with mock.patch.object(
            attestation,
            "require_clean_top_level_checkout",
            side_effect=AssertionError("default package staging must not attest"),
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

    def test_stages_exact_matching_clean_build_attestation(self) -> None:
        out_dir, record = self._make_attested_out_dir()
        first_patch, second_patch = self._clean_attestation_patches()
        with first_patch as clean, second_patch as checkout:
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
        first_patch, second_patch = self._clean_attestation_patches()
        with first_patch, second_patch, self.assertRaisesRegex(
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
        first_patch, second_patch = self._clean_attestation_patches()
        with first_patch, second_patch, self.assertRaisesRegex(
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
        first_patch, second_patch = self._clean_attestation_patches()
        with first_patch, second_patch, self.assertRaisesRegex(
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
        first_patch, second_patch = self._clean_attestation_patches()
        with first_patch, second_patch, self.assertRaisesRegex(
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
        self.assertIn("Required gate state", index)
        self.assertIn('id="gate-state"', index)
        self.assertIn("staging checkout", host)
        self.assertIn("artifact source provenance", host)
        self.assertIn("EXPECTED_GATE_STATE", host)
        self.assertIn("PACKAGE_SCHEMA_VERSION = 3", host)
        self.assertIn(
            "version?.schema_version !== PACKAGE_SCHEMA_VERSION", host
        )
        self.assertIn("validateGateState(version?.gate_state)", host)
        self.assertIn("#renderGateState(gateState)", host)
        self.assertLess(
            host.index("validateGateState(version?.gate_state)"),
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
        self.assertIn('"local_clean_build_attested" in displayed_versions', smoke)
        self.assertIn("mainScriptUrlOrBlob", host)
        self.assertIn("inputModuleName", host)
        self.assertIn('"./chromium-wasm.wasm"', host)

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
                    "shutdownRequested": True,
                    "shutdownDisabled": True,
                    "processExitCode": 1,
                },
                restart_url="http://127.0.0.1:32123/?m9_package_epoch=restart",
                debug_port=32124,
                deadline=123.0,
            )
        self.assertEqual([], client.calls)
        self.assertFalse(client.closed)
        wait_for_client.assert_not_called()

    def test_package_browser_clean_shutdown_rejects_boolean_exit_code(self) -> None:
        self.assertFalse(
            package_browser_smoke._is_clean_shutdown(
                {
                    "shutdownRequested": True,
                    "shutdownDisabled": True,
                    "processExitCode": False,
                }
            )
        )
        with self.assertRaisesRegex(M0Error, "process exit code 0"):
            package_browser_smoke._require_clean_shutdown(
                {
                    "shutdownRequested": True,
                    "shutdownDisabled": True,
                    "processExitCode": False,
                },
                "fixed package-host shutdown",
            )

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
                    "shutdownRequested": True,
                    "shutdownDisabled": True,
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

    def test_package_browser_default_result_remains_one_clean_epoch(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        browser = mock.Mock()
        browser.stderr = object()
        browser.poll.return_value = None
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        client = mock.Mock()
        ready = {"framesPresented": 7, "releaseStatus": package.RELEASE_STATUS}
        shutdown = {
            "shutdownRequested": True,
            "shutdownDisabled": True,
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
                side_effect=lambda *_args, **_kwargs: mock.Mock(),
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
            mock.patch.object(package_browser_smoke, "stop_browser"),
            mock.patch.object(
                package_browser_smoke, "_restart_after_clean_shutdown"
            ) as restart,
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
                "process_exit_code": 0,
                "release_status": package.RELEASE_STATUS,
                "scope": package_browser_smoke.SCOPE,
                "shutdown_disabled": True,
                "shutdown_requested": True,
            },
            result,
        )
        wait_for_client.assert_called_once()
        self.assertEqual(initial_url, wait_for_client.call_args.args[1])
        self.assertEqual(initial_url, wait_for_ready.call_args.kwargs["expected_url"])
        self.assertEqual("first-epoch", wait_for_ready.call_args.kwargs["expected_epoch"])
        request_shutdown.assert_called_once()
        restart.assert_not_called()

    def test_package_browser_restart_result_has_two_clean_epoch_records(self) -> None:
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 32123)
        browser = mock.Mock()
        browser.stderr = object()
        browser.poll.return_value = None
        profile = mock.Mock()
        profile.name = "/tmp/m9-package-profile"
        first_client = mock.Mock()
        second_client = mock.Mock()
        first_ready = {"framesPresented": 7, "releaseStatus": package.RELEASE_STATUS}
        second_ready = {"framesPresented": 11, "releaseStatus": package.RELEASE_STATUS}
        clean_shutdown = {
            "shutdownRequested": True,
            "shutdownDisabled": True,
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
                side_effect=lambda *_args, **_kwargs: mock.Mock(),
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
                package_browser_smoke, "stop_browser"
            ),
            mock.patch.object(
                package_browser_smoke,
                "_restart_after_clean_shutdown",
                return_value=second_client,
            ) as restart,
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
                        "process_exit_code": 0,
                        "shutdown_disabled": True,
                        "shutdown_requested": True,
                    },
                    {
                        "frames_presented": 11,
                        "process_exit_code": 0,
                        "shutdown_disabled": True,
                        "shutdown_requested": True,
                    },
                ],
                "outer_document_restart": True,
                "release_status": package.RELEASE_STATUS,
                "scope": package_browser_smoke.OUTER_DOCUMENT_RESTART_SCOPE,
            },
            result,
        )
        self.assertEqual(2, wait_for_ready.call_count)
        self.assertEqual(2, request_shutdown.call_count)
        restart.assert_called_once()
        self.assertEqual(
            "http://127.0.0.1:32123/?m9_package_epoch=restart-epoch",
            restart.call_args.kwargs["restart_url"],
        )
        self.assertEqual(1000.0, wait_for_ready.call_args_list[1].kwargs["prior_time_origin"])


if __name__ == "__main__":
    unittest.main()

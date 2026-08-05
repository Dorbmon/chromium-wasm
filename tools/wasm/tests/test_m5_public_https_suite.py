#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the external-only multi-probe public M5 runner."""

from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote, quote_plus


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error, REPO_ROOT
import run_m5_public_https_smoke as public_smoke
import run_m5_public_https_suite as public_suite
from tools.wasm.tests.m3_source_contract_test_support import source


PUBLIC_ENDPOINT = "wss://relay.public.example.com/wisp/"
VERSIONS = {
    "chromium": "chromium-revision",
    "v8": "v8-revision",
    "emscripten": "emscripten-revision",
    "port": "port-revision",
}
PUBLIC_PROBES = (
    {
        "public_probe_url": "https://first.public.example.com/static/one",
        "expected_status": 200,
        "expected_protocol": "h2",
    },
    {
        "public_probe_url": "https://second.public.example.com/static/two",
        "expected_status": 200,
        "expected_protocol": "http/1.1",
    },
)


def manifest_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "public_wisp_endpoint": PUBLIC_ENDPOINT,
        "probes": list(copy.deepcopy(PUBLIC_PROBES)),
    }


def command_value(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


class PublicSuiteManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_manifest(self, payload: object) -> Path:
        path = self.directory / "public-suite.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_external_manifest_canonicalizes_two_distinct_hosts(self) -> None:
        payload = manifest_payload()
        payload["public_wisp_endpoint"] = (
            "wss://Relay.Public.Example.Com:443/wisp/"
        )
        probes = payload["probes"]
        assert isinstance(probes, list)
        probes[0]["public_probe_url"] = (
            "https://First.Public.Example.Com:443/static/one"
        )
        config = public_suite.load_public_suite_config(self.write_manifest(payload))

        self.assertEqual(config.public_wisp_endpoint, PUBLIC_ENDPOINT)
        self.assertEqual(
            config.probes,
            (
                public_suite.PublicProbe(
                    "https://first.public.example.com/static/one", 200, "h2"
                ),
                public_suite.PublicProbe(
                    "https://second.public.example.com/static/two",
                    200,
                    "http/1.1",
                ),
            ),
        )

    def test_manifest_validation_rejects_invalid_or_nonrepresentative_inputs(
        self,
    ) -> None:
        invalid_payloads: dict[str, object] = {}

        unknown_root = manifest_payload()
        unknown_root["note"] = "do not accept arbitrary manifest metadata"
        invalid_payloads["unknown_root"] = unknown_root

        unknown_probe = manifest_payload()
        unknown_probe["probes"][0]["header"] = "forbidden"  # type: ignore[index]
        invalid_payloads["unknown_probe"] = unknown_probe

        missing_probe = manifest_payload()
        missing_probe["probes"] = missing_probe["probes"][:1]  # type: ignore[index]
        invalid_payloads["one_probe"] = missing_probe

        zero_probes = manifest_payload()
        zero_probes["probes"] = []
        invalid_payloads["zero_probes"] = zero_probes

        non_list_probes = manifest_payload()
        non_list_probes["probes"] = {"unexpected": "object"}
        invalid_payloads["non_list_probes"] = non_list_probes

        missing_root_field = manifest_payload()
        del missing_root_field["probes"]
        invalid_payloads["missing_root_field"] = missing_root_field

        wrong_schema = manifest_payload()
        wrong_schema["schema_version"] = 2
        invalid_payloads["wrong_schema"] = wrong_schema

        too_many_probes = manifest_payload()
        too_many_probes["probes"] = list(PUBLIC_PROBES) * 3
        invalid_payloads["too_many_probes"] = too_many_probes

        duplicate_url = manifest_payload()
        duplicate_url["probes"][1]["public_probe_url"] = (  # type: ignore[index]
            PUBLIC_PROBES[0]["public_probe_url"]
        )
        invalid_payloads["duplicate_url"] = duplicate_url

        canonical_duplicate_url = manifest_payload()
        canonical_duplicate_probes = canonical_duplicate_url["probes"]
        assert isinstance(canonical_duplicate_probes, list)
        canonical_duplicate_probes[1]["public_probe_url"] = (
            "https://FIRST.PUBLIC.EXAMPLE.COM:443/static/one"
        )
        invalid_payloads["canonical_duplicate_url"] = canonical_duplicate_url

        duplicate_hostname = manifest_payload()
        duplicate_hostname["probes"][1]["public_probe_url"] = (  # type: ignore[index]
            "https://first.public.example.com/static/other"
        )
        invalid_payloads["duplicate_hostname"] = duplicate_hostname

        invalid_endpoint = manifest_payload()
        invalid_endpoint["public_wisp_endpoint"] = "wss://user@relay.example.com/wisp/"
        invalid_payloads["credentials"] = invalid_endpoint

        invalid_probe = manifest_payload()
        invalid_probe["probes"][0]["public_probe_url"] = (  # type: ignore[index]
            "https://127.0.0.1/static/one"
        )
        invalid_payloads["loopback"] = invalid_probe

        nul_probe = manifest_payload()
        nul_probe["probes"][0]["public_probe_url"] = (  # type: ignore[index]
            "https://first.public.example.com/static/one\x00"
        )
        invalid_payloads["nul_probe"] = nul_probe

        surrogate_probe = manifest_payload()
        surrogate_probe["probes"][0]["public_probe_url"] = (  # type: ignore[index]
            "https://first.public.example.com/static/one\ud800"
        )
        invalid_payloads["surrogate_probe"] = surrogate_probe

        non_success_status = manifest_payload()
        non_success_status["probes"][0]["expected_status"] = 204  # type: ignore[index]
        invalid_payloads["non_success_status"] = non_success_status

        invalid_protocol = manifest_payload()
        invalid_protocol["probes"][0]["expected_protocol"] = "h3"  # type: ignore[index]
        invalid_payloads["invalid_protocol"] = invalid_protocol

        bool_status = manifest_payload()
        bool_status["probes"][0]["expected_status"] = True  # type: ignore[index]
        invalid_payloads["bool_status"] = bool_status

        for name, payload in invalid_payloads.items():
            with self.subTest(name=name):
                with self.assertRaises(M0Error):
                    public_suite.load_public_suite_config(self.write_manifest(payload))

    def test_manifest_requires_both_http_protocols(self) -> None:
        for protocol in ("h2", "http/1.1"):
            with self.subTest(protocol=protocol):
                payload = manifest_payload()
                probes = payload["probes"]
                assert isinstance(probes, list)
                for probe in probes:
                    probe["expected_protocol"] = protocol
                with self.assertRaisesRegex(
                    M0Error, "must cover h2 and http/1.1"
                ):
                    public_suite.load_public_suite_config(
                        self.write_manifest(payload)
                    )

    def test_manifest_file_boundary_rejects_repo_missing_bad_encoding_and_duplicates(
        self,
    ) -> None:
        with self.assertRaises(M0Error):
            public_suite.load_public_suite_config(Path(__file__))
        with self.assertRaises(M0Error):
            public_suite.load_public_suite_config(self.directory / "missing.json")

        directory_path = self.directory / "not-a-file"
        directory_path.mkdir()
        with self.assertRaises(M0Error):
            public_suite.load_public_suite_config(directory_path)

        invalid_utf8 = self.directory / "invalid-utf8.json"
        invalid_utf8.write_bytes(b"\xff")
        with self.assertRaises(M0Error):
            public_suite.load_public_suite_config(invalid_utf8)

        duplicate_keys = self.directory / "duplicate-keys.json"
        duplicate_keys.write_text(
            '{"schema_version":1,"schema_version":1}', encoding="utf-8"
        )
        with self.assertRaises(M0Error):
            public_suite.load_public_suite_config(duplicate_keys)

        oversized = self.directory / "oversized.json"
        oversized.write_text(
            "x" * (public_suite.MAXIMUM_MANIFEST_BYTES + 1), encoding="utf-8"
        )
        with self.assertRaises(M0Error):
            public_suite.load_public_suite_config(oversized)

    def test_manifest_loader_reads_a_bounded_byte_payload(self) -> None:
        class TrackingBytesIO(io.BytesIO):
            def __init__(self, value: bytes) -> None:
                super().__init__(value)
                self.read_sizes: list[int] = []

            def read(self, size: int = -1) -> bytes:
                self.read_sizes.append(size)
                return super().read(size)

        manifest_file = TrackingBytesIO(
            b"x" * (public_suite.MAXIMUM_MANIFEST_BYTES + 1)
        )
        with mock.patch.object(Path, "open", return_value=manifest_file):
            with self.assertRaises(M0Error):
                public_suite._load_json_manifest(Path("untrusted.json"))
        self.assertEqual(
            manifest_file.read_sizes,
            [public_suite.MAXIMUM_MANIFEST_BYTES + 1],
        )

    def test_manifest_failure_precedes_all_child_launches(self) -> None:
        payload = manifest_payload()
        payload["probes"] = []
        manifest_path = self.write_manifest(payload)
        diagnostics_dir = self.directory / "diagnostics"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_m5_public_https_suite.py",
                    "--suite-manifest",
                    str(manifest_path),
                    "--diagnostics-dir",
                    str(diagnostics_dir),
                ],
            ),
            mock.patch.object(public_suite, "run_public_suite") as run,
            mock.patch.object(
                public_suite.secrets, "token_hex", return_value="invalid"
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(public_suite.main(), 1)
        run.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            f"{public_suite.SENTINEL}:FAIL run=run-invalid", stderr.getvalue()
        )
        artifacts = list(
            diagnostics_dir.glob("run-*/m5-public-https-suite-result.json")
        )
        self.assertEqual(len(artifacts), 1)
        artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
        self.assertEqual(artifact["failure"], "invalid_manifest")
        self.assertNotIn("versions", artifact)


class PublicSuiteExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        manifest_path = self.directory / "public-suite.json"
        manifest_path.write_text(json.dumps(manifest_payload()), encoding="utf-8")
        self.config = public_suite.load_public_suite_config(manifest_path)
        self.out_dir = self.directory / "out"
        self.diagnostics_dir = self.directory / "diagnostics"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def evidence(self, probe: public_suite.PublicProbe) -> dict[str, object]:
        return public_smoke.expected_public_devtools_network_evidence(
            expected_status=probe.expected_status,
            expected_protocol=probe.expected_protocol,
        )

    def evidence_record(
        self, ordinal: int
    ) -> public_suite.PublicProbeEvidence:
        return public_suite.PublicProbeEvidence(
            ordinal=ordinal,
            public_devtools_network=self.evidence(self.config.probes[ordinal - 1]),
        )

    def provenance(self) -> dict[str, object]:
        return public_smoke.public_provenance(VERSIONS)

    def completed(
        self,
        probe: public_suite.PublicProbe,
        returncode: int = 0,
        stdout: str | None = None,
        stderr: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if stdout is None:
            stdout = "\n".join(
                (
                    f"{public_smoke.SENTINEL}:PROVENANCE "
                    + json.dumps(
                        self.provenance(),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    f"{public_smoke.SENTINEL}:EVIDENCE "
                    + json.dumps(
                        self.evidence(probe),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    f"{public_smoke.SENTINEL}:PASS",
                )
            )
        return subprocess.CompletedProcess(
            args=["child"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    def test_probe_commands_are_fresh_child_invocations_with_unique_diagnostics(
        self,
    ) -> None:
        first = public_suite.public_probe_command(
            self.config,
            self.config.probes[0],
            1,
            browser=Path("/usr/bin/google-chrome"),
            out_dir=self.out_dir,
            module_name="content_shell_wasm_m5_public_test",
            diagnostics_dir=self.diagnostics_dir,
            no_sandbox=True,
            timeout=121.5,
        )
        second = public_suite.public_probe_command(
            self.config,
            self.config.probes[1],
            2,
            browser=Path("/usr/bin/google-chrome"),
            out_dir=self.out_dir,
            module_name="content_shell_wasm_m5_public_test",
            diagnostics_dir=self.diagnostics_dir,
            no_sandbox=True,
            timeout=121.5,
        )

        self.assertEqual(first[0], sys.executable)
        self.assertEqual(
            first[1], str(REPO_ROOT / "tools/wasm/run_m5_public_https_smoke.py")
        )
        self.assertEqual(
            command_value(first, "--public-wisp-endpoint"), PUBLIC_ENDPOINT
        )
        self.assertEqual(
            command_value(first, "--public-probe-url"),
            self.config.probes[0].public_probe_url,
        )
        self.assertEqual(command_value(first, "--expected-status"), "200")
        self.assertEqual(command_value(first, "--expected-protocol"), "h2")
        self.assertEqual(
            command_value(first, "--diagnostics-dir"),
            str(self.diagnostics_dir / "probe-001"),
        )
        self.assertEqual(
            command_value(second, "--diagnostics-dir"),
            str(self.diagnostics_dir / "probe-002"),
        )
        self.assertIn("--no-sandbox", first)
        self.assertEqual(command_value(first, "--timeout"), "121.5")

    def test_runner_starts_one_serial_child_per_probe(self) -> None:
        with mock.patch.object(
            public_suite.subprocess,
            "run",
            side_effect=[
                self.completed(self.config.probes[0]),
                self.completed(self.config.probes[1]),
            ],
        ) as run:
            evidence = public_suite.run_public_suite(
                self.config,
                browser=None,
                out_dir=self.out_dir,
                module_name="public-module",
                diagnostics_dir=self.diagnostics_dir,
                expected_versions=VERSIONS,
                no_sandbox=False,
                timeout=120.0,
            )

        self.assertEqual(tuple(record.ordinal for record in evidence), (1, 2))
        self.assertEqual(
            evidence[0].public_devtools_network,
            self.evidence(self.config.probes[0]),
        )
        self.assertEqual(
            evidence[1].public_devtools_network,
            self.evidence(self.config.probes[1]),
        )
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], REPO_ROOT)
            self.assertFalse(call.kwargs["check"])
            self.assertTrue(call.kwargs["capture_output"])
            self.assertFalse(call.kwargs["shell"])
            self.assertTrue(call.kwargs["text"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            command_value(commands[0], "--diagnostics-dir"),
            str(self.diagnostics_dir / "probe-001"),
        )
        self.assertEqual(
            command_value(commands[1], "--diagnostics-dir"),
            str(self.diagnostics_dir / "probe-002"),
        )

    def test_runner_rejects_invalid_versions_before_starting_a_child(self) -> None:
        with mock.patch.object(public_suite.subprocess, "run") as run:
            with self.assertRaises(M0Error):
                public_suite.run_public_suite(
                    self.config,
                    browser=None,
                    out_dir=self.out_dir,
                    module_name="public-module",
                    diagnostics_dir=self.diagnostics_dir,
                    expected_versions={**VERSIONS, "port": True},
                    no_sandbox=False,
                    timeout=120.0,
                )
        run.assert_not_called()

    def test_suite_version_snapshot_uses_the_local_manifest_and_head(self) -> None:
        manifest: dict[str, object] = {"sentinel": "manifest"}
        with (
            mock.patch.object(
                public_suite, "load_manifest", return_value=manifest
            ) as load_manifest,
            mock.patch.object(
                public_suite, "checked_output", return_value="port-revision"
            ) as checked_output,
            mock.patch.object(
                public_suite, "manifest_versions", return_value=VERSIONS
            ) as manifest_versions,
        ):
            self.assertEqual(public_suite.public_suite_versions(), VERSIONS)
        load_manifest.assert_called_once_with()
        checked_output.assert_called_once_with(["git", "rev-parse", "HEAD"])
        manifest_versions.assert_called_once_with(manifest, "port-revision")

    def test_runner_fails_fast_and_never_exposes_child_output(self) -> None:
        raw_child_output = " ".join(
            (
                PUBLIC_ENDPOINT,
                self.config.probes[1].public_probe_url,
                quote(PUBLIC_ENDPOINT, safe=""),
                quote_plus(self.config.probes[1].public_probe_url),
                "https://unrelated.example.net/path",
            )
        )
        with mock.patch.object(
            public_suite.subprocess,
            "run",
            side_effect=[
                self.completed(self.config.probes[0]),
                self.completed(
                    self.config.probes[1], returncode=1, stdout=raw_child_output
                ),
            ],
        ) as run:
            with self.assertRaises(public_suite.PublicSuiteProbeError) as raised:
                public_suite.run_public_suite(
                    self.config,
                    browser=None,
                    out_dir=self.out_dir,
                    module_name="public-module",
                    diagnostics_dir=self.diagnostics_dir,
                    expected_versions=VERSIONS,
                    no_sandbox=False,
                    timeout=120.0,
                )

        self.assertEqual(raised.exception.ordinal, 2)
        self.assertEqual(
            tuple(record.ordinal for record in raised.exception.successful_evidence),
            (1,),
        )
        self.assertEqual(run.call_count, 2)
        for forbidden in (
            PUBLIC_ENDPOINT,
            *[probe.public_probe_url for probe in self.config.probes],
        ):
            self.assertNotIn(forbidden, str(raised.exception))

    def test_runner_requires_exactly_one_child_pass_sentinel(self) -> None:
        duplicate_marker = "\n".join(
            (
                f"{public_smoke.SENTINEL}:PROVENANCE "
                + json.dumps(self.provenance(), sort_keys=True, separators=(",", ":")),
                f"{public_smoke.SENTINEL}:EVIDENCE "
                + json.dumps(self.evidence(self.config.probes[0])),
                f"{public_smoke.SENTINEL}:PASS",
                f"{public_smoke.SENTINEL}:PASS",
            )
        )
        with mock.patch.object(
            public_suite.subprocess,
            "run",
            return_value=self.completed(self.config.probes[0], stdout=duplicate_marker),
        ):
            with self.assertRaises(public_suite.PublicSuiteProbeError) as raised:
                public_suite.run_public_suite(
                    self.config,
                    browser=None,
                    out_dir=self.out_dir,
                    module_name="public-module",
                    diagnostics_dir=self.diagnostics_dir,
                    expected_versions=VERSIONS,
                    no_sandbox=False,
                    timeout=120.0,
                )
        self.assertEqual(raised.exception.ordinal, 1)

    def test_runner_rejects_contradictory_or_missing_child_records(self) -> None:
        valid_provenance = self.provenance()
        valid_evidence = self.evidence(self.config.probes[0])

        def encoded(value: object) -> str:
            return json.dumps(value, sort_keys=True, separators=(",", ":"))

        def provenance_line(value: str) -> str:
            return f"{public_smoke.SENTINEL}:PROVENANCE {value}"

        def evidence_line(value: str) -> str:
            return f"{public_smoke.SENTINEL}:EVIDENCE {value}"

        def child_stdout(
            evidence_value: str,
            *,
            provenance_value: str | None = None,
            pass_first: bool = False,
        ) -> str:
            if provenance_value is None:
                provenance_value = encoded(valid_provenance)
            lines = (
                provenance_line(provenance_value),
                evidence_line(evidence_value),
                f"{public_smoke.SENTINEL}:PASS",
            )
            if pass_first:
                lines = (lines[-1], *lines[:-1])
            return "\n".join(lines)

        wrong_status = copy.deepcopy(valid_evidence)
        wrong_status["responseStatus"] = 201
        wrong_protocol = copy.deepcopy(valid_evidence)
        wrong_protocol["responseProtocol"] = "http/1.1"
        extra_field = copy.deepcopy(valid_evidence)
        extra_field["url"] = "https://forbidden.example.net/"
        numeric_boolean = copy.deepcopy(valid_evidence)
        numeric_boolean["networkEnabled"] = 1
        boolean_protocol = copy.deepcopy(valid_evidence)
        boolean_protocol["protocol"] = True
        duplicated_protocol = encoded(valid_evidence).replace(
            '"protocol":1', '"protocol":true,"protocol":1', 1
        )
        stale_provenance = public_smoke.public_provenance(
            {**VERSIONS, "port": "stale-port-revision"}
        )
        expanded_provenance = {
            **valid_provenance,
            "url": "https://forbidden.example.net/",
        }
        boolean_provenance_protocol = {
            **valid_provenance,
            "protocol": True,
        }
        boolean_provenance_version = public_smoke.public_provenance(VERSIONS)
        boolean_provenance_version["versions"]["port"] = True
        duplicated_provenance_protocol = encoded(valid_provenance).replace(
            '"protocol":1', '"protocol":true,"protocol":1', 1
        )
        valid_provenance_encoded = encoded(valid_provenance)
        duplicated_provenance_version = valid_provenance_encoded.replace(
            '"port":"port-revision"',
            '"port":"other-port-revision","port":"port-revision"',
            1,
        )
        valid_evidence_encoded = encoded(valid_evidence)
        cases = (
            (
                "failure_in_stdout",
                "\n".join(
                    (
                        provenance_line(valid_provenance_encoded),
                        evidence_line(valid_evidence_encoded),
                        f"{public_smoke.SENTINEL}:FAIL reason=contradiction",
                        f"{public_smoke.SENTINEL}:PASS",
                    )
                ),
                "",
            ),
            (
                "missing_provenance",
                "\n".join(
                    (
                        evidence_line(valid_evidence_encoded),
                        f"{public_smoke.SENTINEL}:PASS",
                    )
                ),
                "",
            ),
            (
                "malformed_provenance_marker",
                "\n".join(
                    (
                        f"{public_smoke.SENTINEL}:PROVENANCE"
                        f"{valid_provenance_encoded}",
                        evidence_line(valid_evidence_encoded),
                        f"{public_smoke.SENTINEL}:PASS",
                    )
                ),
                "",
            ),
            (
                "missing_evidence",
                "\n".join(
                    (
                        provenance_line(valid_provenance_encoded),
                        f"{public_smoke.SENTINEL}:PASS",
                    )
                ),
                "",
            ),
            (
                "pass_before_records",
                child_stdout(valid_evidence_encoded, pass_first=True),
                "",
            ),
            (
                "provenance_after_evidence",
                "\n".join(
                    (
                        evidence_line(valid_evidence_encoded),
                        provenance_line(valid_provenance_encoded),
                        f"{public_smoke.SENTINEL}:PASS",
                    )
                ),
                "",
            ),
            (
                "duplicate_provenance",
                child_stdout(valid_evidence_encoded)
                + "\n"
                + provenance_line(valid_provenance_encoded),
                "",
            ),
            (
                "extra_malformed_provenance",
                child_stdout(valid_evidence_encoded)
                + "\n"
                + f"{public_smoke.SENTINEL}:PROVENANCEunexpected",
                "",
            ),
            (
                "indented_provenance",
                "\n".join(
                    (
                        f"  {provenance_line(valid_provenance_encoded)}",
                        evidence_line(valid_evidence_encoded),
                        f"{public_smoke.SENTINEL}:PASS",
                    )
                ),
                "",
            ),
            (
                "duplicate_provenance_version_key",
                child_stdout(
                    valid_evidence_encoded,
                    provenance_value=duplicated_provenance_version,
                ),
                "",
            ),
            (
                "provenance_in_stderr",
                child_stdout(valid_evidence_encoded),
                provenance_line(valid_provenance_encoded),
            ),
            (
                "indented_provenance_in_stderr",
                child_stdout(valid_evidence_encoded),
                f"  {provenance_line(valid_provenance_encoded)}",
            ),
            (
                "stale_provenance",
                child_stdout(
                    valid_evidence_encoded,
                    provenance_value=encoded(stale_provenance),
                ),
                "",
            ),
            (
                "expanded_provenance",
                child_stdout(
                    valid_evidence_encoded,
                    provenance_value=encoded(expanded_provenance),
                ),
                "",
            ),
            (
                "boolean_provenance_protocol",
                child_stdout(
                    valid_evidence_encoded,
                    provenance_value=encoded(boolean_provenance_protocol),
                ),
                "",
            ),
            (
                "boolean_provenance_version",
                child_stdout(
                    valid_evidence_encoded,
                    provenance_value=encoded(boolean_provenance_version),
                ),
                "",
            ),
            (
                "duplicate_provenance_key",
                child_stdout(
                    valid_evidence_encoded,
                    provenance_value=duplicated_provenance_protocol,
                ),
                "",
            ),
            ("wrong_status", child_stdout(encoded(wrong_status)), ""),
            ("wrong_protocol", child_stdout(encoded(wrong_protocol)), ""),
            ("extra_field", child_stdout(encoded(extra_field)), ""),
            ("numeric_boolean", child_stdout(encoded(numeric_boolean)), ""),
            ("boolean_protocol", child_stdout(encoded(boolean_protocol)), ""),
            ("duplicate_evidence_key", child_stdout(duplicated_protocol), ""),
            (
                "evidence_in_stderr",
                child_stdout(valid_evidence_encoded),
                evidence_line(valid_evidence_encoded),
            ),
            (
                "indented_evidence_in_stderr",
                child_stdout(valid_evidence_encoded),
                f"  {evidence_line(valid_evidence_encoded)}",
            ),
            (
                "indented_extra_evidence_in_stdout",
                child_stdout(valid_evidence_encoded)
                + "\n"
                + f"  {evidence_line(valid_evidence_encoded)}",
                "",
            ),
            (
                "indented_pass",
                child_stdout(valid_evidence_encoded).replace(
                    f"{public_smoke.SENTINEL}:PASS",
                    f"  {public_smoke.SENTINEL}:PASS",
                ),
                "",
            ),
        )
        for name, stdout, stderr in cases:
            with self.subTest(name=name):
                with mock.patch.object(
                    public_suite.subprocess,
                    "run",
                    return_value=self.completed(
                        self.config.probes[0], stdout=stdout, stderr=stderr
                    ),
                ):
                    with self.assertRaises(public_suite.PublicSuiteProbeError):
                        public_suite.run_public_suite(
                            self.config,
                            browser=None,
                            out_dir=self.out_dir,
                            module_name="public-module",
                            diagnostics_dir=self.diagnostics_dir,
                            expected_versions=VERSIONS,
                            no_sandbox=False,
                            timeout=120.0,
                        )

        valid_stdout = child_stdout(valid_evidence_encoded)
        with mock.patch.object(
            public_suite.subprocess,
            "run",
            return_value=self.completed(
                self.config.probes[0],
                stdout=valid_stdout,
                stderr=f"{public_smoke.SENTINEL}:FAIL reason=contradiction",
            ),
        ):
            with self.assertRaises(public_suite.PublicSuiteProbeError):
                public_suite.run_public_suite(
                    self.config,
                    browser=None,
                    out_dir=self.out_dir,
                    module_name="public-module",
                    diagnostics_dir=self.diagnostics_dir,
                    expected_versions=VERSIONS,
                    no_sandbox=False,
                    timeout=120.0,
                )

    def test_aggregate_artifacts_retain_fixed_cdp_evidence_and_are_url_free(
        self,
    ) -> None:
        evidence = (self.evidence_record(1), self.evidence_record(2))
        success = public_suite.write_suite_success_artifact(
            self.diagnostics_dir,
            evidence=evidence,
            config=self.config,
            versions=VERSIONS,
        )
        success_serialized = success.read_text(encoding="utf-8")
        failure = public_suite.write_suite_failure_artifact(
            self.diagnostics_dir,
            error=public_suite.PublicSuiteProbeError(
                2, "did not pass", evidence[:1]
            ),
            config=self.config,
            versions=VERSIONS,
        )
        failure_serialized = failure.read_text(encoding="utf-8")
        serialized = success_serialized + failure_serialized
        self.assertEqual(success, failure)
        for rendered in public_smoke._configured_public_url_variants(
            PUBLIC_ENDPOINT,
            *[probe.public_probe_url for probe in self.config.probes],
        ):
            with self.subTest(rendered=rendered):
                self.assertNotIn(rendered, serialized)
        with self.assertRaises(M0Error):
            public_suite._assert_redacted_artifact(
                {"diagnostic": "relay.public.example.com:443"}, self.config
            )
        self.assertIsNone(public_smoke.URL_LIKE_VALUE_PATTERN.search(serialized))
        success_artifact = json.loads(success_serialized)
        self.assertEqual(success_artifact["status"], "pass")
        self.assertEqual(success_artifact["versions"], VERSIONS)
        self.assertEqual(
            success_artifact["probes"],
            [
                {
                    "ordinal": 1,
                    "publicDevtoolsNetwork": self.evidence(self.config.probes[0]),
                },
                {
                    "ordinal": 2,
                    "publicDevtoolsNetwork": self.evidence(self.config.probes[1]),
                },
            ],
        )
        failure_artifact = json.loads(failure_serialized)
        self.assertEqual(failure_artifact["status"], "fail")
        self.assertEqual(failure_artifact["versions"], VERSIONS)
        self.assertEqual(failure_artifact["failedProbeOrdinal"], 2)

    def test_artifact_writers_reject_incomplete_or_misaligned_evidence(self) -> None:
        first = self.evidence_record(1)
        second = self.evidence_record(2)
        with self.assertRaises(M0Error):
            public_suite.write_suite_success_artifact(
                self.diagnostics_dir,
                evidence=(first,),
                config=self.config,
                versions=VERSIONS,
            )
        with self.assertRaises(M0Error):
            public_suite.write_suite_success_artifact(
                self.diagnostics_dir,
                evidence=(first, second),
                config=self.config,
                versions={**VERSIONS, "port": True},
            )
        with self.assertRaises(M0Error):
            public_suite.write_suite_failure_artifact(
                self.diagnostics_dir,
                error=public_suite.PublicSuiteProbeError(
                    2, "did not pass", (first,)
                ),
                config=self.config,
                versions={**VERSIONS, "port": True},
            )
        with self.assertRaises(M0Error):
            public_suite.write_suite_success_artifact(
                self.diagnostics_dir,
                evidence=(
                    public_suite.PublicProbeEvidence(
                        ordinal=True,
                        public_devtools_network=first.public_devtools_network,
                    ),
                    second,
                ),
                config=self.config,
                versions=VERSIONS,
            )
        with self.assertRaises(M0Error):
            public_suite.write_suite_failure_artifact(
                self.diagnostics_dir,
                error=public_suite.PublicSuiteProbeError(
                    True, "did not pass", ()
                ),
                config=self.config,
                versions=VERSIONS,
            )
        with self.assertRaises(M0Error):
            public_suite.write_suite_failure_artifact(
                self.diagnostics_dir,
                error=public_suite.PublicSuiteProbeError(
                    2, "did not pass", (second,)
                ),
                config=self.config,
                versions=VERSIONS,
            )
        type_confused_network = copy.deepcopy(
            second.public_devtools_network
        )
        type_confused_network["protocol"] = True
        with self.assertRaises(M0Error):
            public_suite.write_suite_success_artifact(
                self.diagnostics_dir,
                evidence=(
                    first,
                    public_suite.PublicProbeEvidence(
                        ordinal=2,
                        public_devtools_network=type_confused_network,
                    ),
                ),
                config=self.config,
                versions=VERSIONS,
            )

    def test_fresh_run_directory_never_reuses_a_stale_artifact(self) -> None:
        stale_directory = self.diagnostics_dir / "run-repeat"
        stale_directory.mkdir(parents=True)
        stale_artifact = stale_directory / "m5-public-https-suite-result.json"
        stale_artifact.write_text('{"status":"pass"}\n', encoding="utf-8")
        with mock.patch.object(
            public_suite.secrets,
            "token_hex",
            side_effect=("repeat", "fresh"),
        ):
            fresh_directory = public_suite.create_run_diagnostics_directory(
                self.diagnostics_dir
            )
        self.assertEqual(fresh_directory.name, "run-fresh")
        self.assertEqual(
            stale_artifact.read_text(encoding="utf-8"),
            '{"status":"pass"}\n',
        )
        self.assertFalse(
            (fresh_directory / "m5-public-https-suite-result.json").exists()
        )

    def test_main_emits_only_ordinal_progress_for_success_and_failure(self) -> None:
        manifest_path = self.directory / "main-suite.json"
        manifest_path.write_text(json.dumps(manifest_payload()), encoding="utf-8")
        diagnostics_dir = self.directory / "main-diagnostics"
        arguments = [
            "run_m5_public_https_suite.py",
            "--suite-manifest",
            str(manifest_path),
            "--diagnostics-dir",
            str(diagnostics_dir),
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        evidence = (self.evidence_record(1), self.evidence_record(2))
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.object(
                public_suite, "run_public_suite", return_value=evidence
            ) as run,
            mock.patch.object(
                public_suite, "public_suite_versions", return_value=VERSIONS
            ),
            mock.patch.object(
                public_suite.secrets, "token_hex", return_value="success"
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(public_suite.main(), 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(run.call_args.kwargs["expected_versions"], VERSIONS)
        self.assertEqual(
            stdout.getvalue().splitlines(),
            [
                f"{public_suite.SENTINEL}:START run=run-success probes=2",
                f"{public_suite.SENTINEL}:PROBE ordinal=1 status=pass",
                f"{public_suite.SENTINEL}:PROBE ordinal=2 status=pass",
                f"{public_suite.SENTINEL}:PASS run=run-success probes=2",
            ],
        )
        successful_artifacts = list(
            diagnostics_dir.glob("run-*/m5-public-https-suite-result.json")
        )
        self.assertEqual(len(successful_artifacts), 1)
        success_artifact = json.loads(
            successful_artifacts[0].read_text(encoding="utf-8")
        )
        self.assertEqual(success_artifact["status"], "pass")
        self.assertEqual(success_artifact["versions"], VERSIONS)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.object(
                public_suite,
                "run_public_suite",
                side_effect=public_suite.PublicSuiteProbeError(
                    2, "did not pass", evidence[:1]
                ),
            ) as run,
            mock.patch.object(
                public_suite, "public_suite_versions", return_value=VERSIONS
            ),
            mock.patch.object(
                public_suite.secrets, "token_hex", return_value="failure"
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(public_suite.main(), 1)
        self.assertEqual(
            stdout.getvalue().splitlines(),
            [f"{public_suite.SENTINEL}:START run=run-failure probes=2"],
        )
        self.assertEqual(
            stderr.getvalue().splitlines(),
            [f"{public_suite.SENTINEL}:FAIL run=run-failure probe=2"],
        )
        self.assertEqual(run.call_args.kwargs["expected_versions"], VERSIONS)
        all_artifacts = list(
            diagnostics_dir.glob("run-*/m5-public-https-suite-result.json")
        )
        self.assertEqual(len(all_artifacts), 2)
        failure_artifact = next(
            artifact
            for artifact in all_artifacts
            if json.loads(artifact.read_text(encoding="utf-8"))["status"] == "fail"
        )
        serialized = failure_artifact.read_text(encoding="utf-8")
        failure_result = json.loads(serialized)
        self.assertEqual(failure_result["status"], "fail")
        self.assertEqual(failure_result["versions"], VERSIONS)
        for value in (
            PUBLIC_ENDPOINT,
            *[probe.public_probe_url for probe in self.config.probes],
        ):
            self.assertNotIn(value, stdout.getvalue() + stderr.getvalue() + serialized)

    def test_main_redacts_real_raw_child_failure_output(self) -> None:
        manifest_path = self.directory / "raw-child-suite.json"
        manifest_path.write_text(json.dumps(manifest_payload()), encoding="utf-8")
        diagnostics_dir = self.directory / "raw-child-diagnostics"
        raw_child_output = " ".join(
            (
                PUBLIC_ENDPOINT,
                self.config.probes[1].public_probe_url,
                quote(PUBLIC_ENDPOINT, safe=""),
                quote_plus(self.config.probes[1].public_probe_url),
                "https://unrelated.example.net/path",
            )
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_m5_public_https_suite.py",
                    "--suite-manifest",
                    str(manifest_path),
                    "--diagnostics-dir",
                    str(diagnostics_dir),
                ],
            ),
            mock.patch.object(
                public_suite.subprocess,
                "run",
                side_effect=[
                    self.completed(self.config.probes[0]),
                    self.completed(
                        self.config.probes[1], returncode=1, stdout=raw_child_output
                    ),
                ],
            ),
            mock.patch.object(public_suite.secrets, "token_hex", return_value="raw"),
            mock.patch.object(
                public_suite, "public_suite_versions", return_value=VERSIONS
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(public_suite.main(), 1)
        artifact = next(
            diagnostics_dir.glob("run-*/m5-public-https-suite-result.json")
        ).read_text(encoding="utf-8")
        output = stdout.getvalue() + stderr.getvalue() + artifact
        for value in (
            PUBLIC_ENDPOINT,
            *[probe.public_probe_url for probe in self.config.probes],
            quote(PUBLIC_ENDPOINT, safe=""),
            quote_plus(self.config.probes[1].public_probe_url),
            "https://unrelated.example.net/path",
        ):
            self.assertNotIn(value, output)

    def test_main_keeps_a_committed_pass_authoritative_if_reporting_fails(self) -> None:
        class FailOnProgressOutput(io.StringIO):
            def write(self, value: str) -> int:
                if f"{public_suite.SENTINEL}:PROBE" in value:
                    raise BrokenPipeError("test closed report pipe")
                return super().write(value)

        manifest_path = self.directory / "reporting-suite.json"
        manifest_path.write_text(json.dumps(manifest_payload()), encoding="utf-8")
        diagnostics_dir = self.directory / "reporting-diagnostics"
        evidence = (self.evidence_record(1), self.evidence_record(2))
        stdout = FailOnProgressOutput()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_m5_public_https_suite.py",
                    "--suite-manifest",
                    str(manifest_path),
                    "--diagnostics-dir",
                    str(diagnostics_dir),
                ],
            ),
            mock.patch.object(
                public_suite, "run_public_suite", return_value=evidence
            ),
            mock.patch.object(
                public_suite, "public_suite_versions", return_value=VERSIONS
            ),
            mock.patch.object(
                public_suite.secrets, "token_hex", return_value="reporting"
            ),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(public_suite.main(), 0)
        artifact = next(
            diagnostics_dir.glob("run-*/m5-public-https-suite-result.json")
        )
        reporting_artifact = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(reporting_artifact["status"], "pass")
        self.assertEqual(reporting_artifact["versions"], VERSIONS)


class PublicSuiteSourceContractTest(unittest.TestCase):
    def test_wrapper_uses_the_one_probe_runner_in_fresh_serial_children(self) -> None:
        suite_source = source("tools/wasm/run_m5_public_https_suite.py")
        single_probe_source = source("tools/wasm/run_m5_public_https_smoke.py")

        self.assertIn("MINIMUM_PUBLIC_PROBES = 2", suite_source)
        self.assertIn("MAXIMUM_PUBLIC_PROBES = 4", suite_source)
        self.assertIn("must remain outside the repository", suite_source)
        self.assertIn("run_m5_public_https_smoke.py", suite_source)
        self.assertIn("subprocess.run(", suite_source)
        self.assertIn("capture_output=True", suite_source)
        self.assertIn("shell=False", suite_source)
        self.assertIn("_child_devtools_evidence", suite_source)
        self.assertIn("_reject_duplicate_evidence_keys", suite_source)
        self.assertIn("public_suite_versions", suite_source)
        self.assertIn("fail_prefix", suite_source)
        self.assertIn("provenance_prefix", suite_source)
        self.assertIn("validate_public_provenance", suite_source)
        self.assertIn('"versions": provenance["versions"]', suite_source)
        self.assertIn("create_run_diagnostics_directory", suite_source)
        self.assertIn("run-{secrets.token_hex(12)}", suite_source)
        self.assertIn(
            "for ordinal, probe in enumerate(config.probes, start=1)",
            suite_source,
        )
        self.assertIn("probe-{ordinal:03d}", suite_source)
        self.assertNotIn("run_m5_public_https_smoke.main()", suite_source)
        self.assertNotIn('parser.add_argument("--public-wisp-endpoint"', suite_source)
        self.assertNotIn('parser.add_argument("--public-probe-url"', suite_source)
        self.assertIn("expected_public_devtools_network_evidence", single_probe_source)
        self.assertIn("validate_public_devtools_network_evidence", single_probe_source)
        self.assertIn("PUBLIC_PROVENANCE_PROTOCOL", single_probe_source)
        self.assertIn("public_provenance", single_probe_source)
        self.assertIn("validate_public_provenance", single_probe_source)
        self.assertIn('f"{SENTINEL}:PROVENANCE "', single_probe_source)
        self.assertIn('f"{SENTINEL}:EVIDENCE "', single_probe_source)
        self.assertIn("tempfile.TemporaryDirectory(", single_probe_source)
        self.assertIn("prefix=\"chromium-wasm-m5-public-\"", single_probe_source)


if __name__ == "__main__":
    unittest.main()

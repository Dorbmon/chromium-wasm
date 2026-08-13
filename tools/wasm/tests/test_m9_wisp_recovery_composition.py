#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the bounded M9 WISP recovery composition runner."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from typing import Sequence
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m9_wisp_recovery_composition as composition


VERSIONS = {
    "chromium": "a" * 40,
    "v8": "b" * 40,
    "emscripten": "c" * 40,
    "port": "d" * 40,
}
SHA256 = "e" * 64


def byte_identity(byte_count: int = 1, sha256: str = SHA256) -> dict[str, object]:
    return {"bytes": byte_count, "sha256": sha256}


def input_identity() -> dict[str, object]:
    return {
        "artifact_source_provenance": composition.ARTIFACT_SOURCE_PROVENANCE,
        "source_snapshot_provenance": composition.SOURCE_SNAPSHOT_PROVENANCE,
        "shared": {
            name: byte_identity(index + 1)
            for index, name in enumerate(sorted(composition._SHARED_SNAPSHOT_FIELDS))
        },
        "chrome_controlled_https": {
            "artifact_delivery": composition.ARTIFACT_DELIVERY,
            "args_gn": byte_identity(2),
            "host_html": byte_identity(3),
            "host_js": byte_identity(4),
            "loader": byte_identity(5),
            "module_name": composition.DEFAULT_CHROME_MODULE_NAME,
            "runner_source": byte_identity(6),
            "screenshot_baseline": byte_identity(7),
            "screenshot_contract": byte_identity(8),
            "text_input_js": byte_identity(9),
            "wasm": byte_identity(10),
        },
        "content_shell_wisp_recovery": {
            "artifact_delivery": composition.ARTIFACT_DELIVERY,
            "args_gn": byte_identity(11),
            "host_html": byte_identity(12),
            "host_js": byte_identity(13),
            "host_server_source": byte_identity(14),
            "loader": byte_identity(15),
            "module_name": composition.DEFAULT_CONTENT_MODULE_NAME,
            "runner_source": byte_identity(16),
            "wasm": byte_identity(17),
        },
    }


def chrome_evidence() -> dict[str, object]:
    return {
        "browser_result_sha256": SHA256,
        "controlled_reload": True,
        "elapsed_ms": 12.5,
        "fresh_child_process": True,
        "fresh_host_browser_profile_owned_by_child": True,
        "relay_status_sha256": SHA256,
        "returncode": 0,
        "stderr_bytes": 0,
        "stderr_sha256": SHA256,
        "stdout_bytes": 17,
        "stdout_sha256": SHA256,
        "terminal_records": {
            "browser_result": 1,
            "pass": 1,
            "relay_status": 1,
        },
        "wisp_configured": True,
    }


def content_evidence() -> dict[str, object]:
    return {
        "browser_result_sha256": SHA256,
        "carrier_close_reconnect_phase": "recovered",
        "elapsed_ms": 25.0,
        "fresh_child_process": True,
        "fresh_host_browser_profile_owned_by_child": True,
        "reconnect_recovery_requests": 1,
        "relay_transcript_sha256": SHA256,
        "returncode": 0,
        "stderr_bytes": 0,
        "stderr_sha256": SHA256,
        "stdout_bytes": 19,
        "stdout_sha256": SHA256,
        "terminal_records": {
            "browser_result": 1,
            "pass": 1,
            "relay_ready": 1,
            "relay_transcript": 1,
        },
        "wisp_sessions": 2,
    }


def m6_browser_result() -> dict[str, object]:
    smoke = composition.m6_controlled_https
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m6GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "factorySettled": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusedAtStart": True,
        "proxyFocusedForText": True,
        "canvasFocusedForReload": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "versions": copy.deepcopy(VERSIONS),
        "controlledHttps": {
            "wispConfigured": True,
            "configurationPrecededFactory": True,
            "navigatedMarkerObserved": True,
            "reloadedMarkerObserved": True,
            "passMarkerObserved": True,
        },
        "screenshot": {
            "dataBase64": "<omitted>",
            "frameId": 1,
            "height": 480,
            "mimeType": "image/png",
            "timestampMs": 1.5,
            "width": 640,
        },
        "stdout": [
            smoke.READY_MARKER,
            smoke.NAVIGATED_MARKER,
            smoke.RELOAD_READY_MARKER,
            smoke.RELOADED_MARKER,
        ],
        "stderr": [smoke.PASS_MARKER],
    }


def chrome_execution() -> composition.ChildExecution:
    smoke = composition.m6_controlled_https
    stdout = "\n".join(
        (
            f"{smoke.SENTINEL}:BROWSER_RESULT "
            + json.dumps(m6_browser_result(), sort_keys=True, separators=(",", ":")),
            f"{smoke.SENTINEL}:RELAY_STATUS {{}}",
            smoke.PASS_MARKER,
        )
    ) + "\n"
    return composition.ChildExecution(
        name="Chrome controlled-HTTPS",
        elapsed_ms=12.5,
        returncode=0,
        stdout=stdout,
        stderr="",
    )


def m5_ready_record() -> dict[str, object]:
    return {
        "schema_version": 1,
        "httpsUrl": "https://a.test:43211/m5/",
        "redirectUrl": "https://a.test:43211/m5/redirect-cookie",
        "plaintextHttpControlUrl": "http://a.test:43212/m5/plaintext-control",
        "mixedContentTargetUrl": "http://a.test:43212/m5/mixed-content-target",
        "http1Url": "https://a.test:43213/m5/cors-resource",
        "tlsFailureUrl": "https://a.test:43214/m5/tls-name-mismatch",
        "transcriptUrl": "http://127.0.0.1:43210/status",
        "wispEndpoint": "ws://127.0.0.1:43210/wisp/",
    }


def m5_browser_result() -> dict[str, object]:
    return {"versions": copy.deepcopy(VERSIONS)}


def m5_relay_transcript() -> dict[str, object]:
    return {
        "reconnectPhase": "recovered",
        "reconnectRecoveryRequests": 1,
        "wispSessions": 2,
    }


def content_execution() -> composition.ChildExecution:
    smoke = composition.m5_wisp
    stdout = "\n".join(
        (
            f"{smoke.SENTINEL}:RELAY_READY "
            + json.dumps(m5_ready_record(), sort_keys=True, separators=(",", ":")),
            f"{smoke.SENTINEL}:BROWSER_RESULT "
            + json.dumps(m5_browser_result(), sort_keys=True, separators=(",", ":")),
            f"{smoke.SENTINEL}:RELAY_TRANSCRIPT "
            + json.dumps(
                m5_relay_transcript(), sort_keys=True, separators=(",", ":")
            ),
            f"{smoke.SENTINEL}:PASS",
        )
    ) + "\n"
    return composition.ChildExecution(
        name="Content Shell WISP carrier-close recovery",
        elapsed_ms=25.0,
        returncode=0,
        stdout=stdout,
        stderr="",
    )


class M9WispRecoveryCompositionTest(unittest.TestCase):
    def test_chrome_child_requires_exact_terminal_records_and_redacted_result(self) -> None:
        execution = chrome_execution()
        with mock.patch.object(
            composition.m6_controlled_https, "validate_relay_status"
        ) as validate_relay:
            evidence, versions = composition.validate_chrome_execution(execution)

        self.assertEqual(VERSIONS, versions)
        self.assertTrue(evidence["fresh_child_process"])
        self.assertEqual(
            {"browser_result": 1, "pass": 1, "relay_status": 1},
            evidence["terminal_records"],
        )
        validate_relay.assert_called_once_with({})
        self.assertEqual(
            hashlib.sha256(execution.stdout.encode("utf-8")).hexdigest(),
            evidence["stdout_sha256"],
        )

        duplicate = composition.ChildExecution(
            **{
                **execution.__dict__,
                "stdout": execution.stdout.replace(
                    composition.m6_controlled_https.PASS_MARKER,
                    composition.m6_controlled_https.PASS_MARKER
                    + "\n"
                    + composition.m6_controlled_https.PASS_MARKER,
                ),
            }
        )
        with self.assertRaisesRegex(M0Error, "exactly one"):
            composition.validate_chrome_execution(duplicate)

        early_pass = composition.ChildExecution(
            **{
                **execution.__dict__,
                "stdout": "\n".join(
                    (
                        composition.m6_controlled_https.PASS_MARKER,
                        *execution.stdout.splitlines()[:-1],
                    )
                )
                + "\n",
            }
        )
        with self.assertRaisesRegex(M0Error, "PASS marker did not follow"):
            composition.validate_chrome_execution(early_pass)

        stderr_only_pass = composition.ChildExecution(
            **{
                **execution.__dict__,
                "stdout": execution.stdout.replace(
                    composition.m6_controlled_https.PASS_MARKER + "\n", ""
                ),
                "stderr": composition.m6_controlled_https.PASS_MARKER + "\n",
            }
        )
        with self.assertRaisesRegex(M0Error, "exactly one stdout"):
            composition.validate_chrome_execution(stderr_only_pass)

        unredacted = m6_browser_result()
        assert isinstance(unredacted["screenshot"], dict)
        unredacted["screenshot"]["dataBase64"] = "not-redacted"
        malformed = composition.ChildExecution(
            **{
                **execution.__dict__,
                "stdout": execution.stdout.replace(
                    json.dumps(
                        m6_browser_result(), sort_keys=True, separators=(",", ":")
                    ),
                    json.dumps(unredacted, sort_keys=True, separators=(",", ":")),
                ),
            }
        )
        with self.assertRaisesRegex(M0Error, "redacted screenshot"):
            composition.validate_chrome_execution(malformed)

    def test_content_child_delegates_carrier_close_validation(self) -> None:
        execution = content_execution()
        relay_ready = object()
        with (
            mock.patch.object(
                composition.m5_wisp,
                "parse_relay_ready_line",
                return_value=relay_ready,
            ) as parse_ready,
            mock.patch.object(composition.m5_wisp, "validate_m5_result") as validate_m5,
            mock.patch.object(
                composition.m5_wisp, "validate_relay_transcript"
            ) as validate_transcript,
        ):
            evidence, versions = composition.validate_content_execution(execution)

        self.assertEqual(VERSIONS, versions)
        self.assertEqual("recovered", evidence["carrier_close_reconnect_phase"])
        self.assertEqual(2, evidence["wisp_sessions"])
        self.assertEqual(1, evidence["reconnect_recovery_requests"])
        parse_ready.assert_called_once()
        validate_m5.assert_called_once_with(
            m5_browser_result(), expected_versions=VERSIONS, relay_ready=relay_ready
        )
        validate_transcript.assert_called_once_with(
            m5_relay_transcript(), relay_ready=relay_ready
        )

        missing_recovery = content_execution()
        missing_recovery = composition.ChildExecution(
            **{
                **missing_recovery.__dict__,
                "stdout": missing_recovery.stdout.replace(
                    '"reconnectPhase":"recovered"',
                    '"reconnectPhase":"pending"',
                ),
            }
        )
        with (
            mock.patch.object(
                composition.m5_wisp,
                "parse_relay_ready_line",
                return_value=relay_ready,
            ),
            mock.patch.object(composition.m5_wisp, "validate_m5_result"),
            mock.patch.object(composition.m5_wisp, "validate_relay_transcript"),
            self.assertRaisesRegex(M0Error, "carrier-close recovery"),
        ):
            composition.validate_content_execution(missing_recovery)

    def test_content_child_rejects_missing_or_out_of_order_terminal_records(self) -> None:
        execution = content_execution()
        reordered = composition.ChildExecution(
            **{
                **execution.__dict__,
                "stdout": "\n".join(
                    reversed(execution.stdout.splitlines())
                )
                + "\n",
            }
        )
        with self.assertRaisesRegex(M0Error, "terminal records"):
            composition.validate_content_execution(reordered)

        early_pass = composition.ChildExecution(
            **{
                **execution.__dict__,
                "stdout": "\n".join(
                    (
                        f"{composition.m5_wisp.SENTINEL}:PASS",
                        *execution.stdout.splitlines()[:-1],
                    )
                )
                + "\n",
            }
        )
        with self.assertRaisesRegex(M0Error, "PASS marker did not follow"):
            composition.validate_content_execution(early_pass)

        failed = composition.ChildExecution(
            **{**execution.__dict__, "returncode": 1}
        )
        with self.assertRaisesRegex(M0Error, "exited with status 1"):
            composition.validate_content_execution(failed)

    def test_result_is_canonical_nonrelease_and_rejects_release_claims(self) -> None:
        expected_inputs = input_identity()
        result = composition.make_composition_result(
            chrome_evidence=chrome_evidence(),
            content_evidence=content_evidence(),
            input_identity=expected_inputs,
            versions=VERSIONS,
        )
        self.assertEqual("pass", result["status"])
        self.assertFalse(result["m9_gate_complete"])
        self.assertEqual(
            "pre_m7_m8_not_releasable", result["release_status"]
        )
        self.assertEqual("unverified", result["artifact_source_provenance"])
        self.assertTrue(result["composition"]["cross_executable"])
        self.assertFalse(result["composition"]["same_instance_chrome_recovery"])

        release_claim = copy.deepcopy(result)
        release_claim["release_status"] = "release"
        with self.assertRaisesRegex(M0Error, "release_status"):
            composition.validate_composition_result(
                release_claim, expected_input_identity=expected_inputs
            )

        same_instance_claim = copy.deepcopy(result)
        same_instance_claim["composition"]["same_instance_chrome_recovery"] = True
        with self.assertRaisesRegex(M0Error, "execution model"):
            composition.validate_composition_result(
                same_instance_claim, expected_input_identity=expected_inputs
            )

        verified_claim = copy.deepcopy(result)
        verified_claim["artifact_source_provenance"] = "verified"
        with self.assertRaisesRegex(M0Error, "artifact_source_provenance"):
            composition.validate_composition_result(
                verified_claim, expected_input_identity=expected_inputs
            )

    def test_snapshot_identity_binds_artifacts_runner_host_and_server_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            chrome_out = root / "chrome-out"
            content_out = root / "content-out"
            chrome_out.mkdir()
            content_out.mkdir()
            for out_dir, module_name in (
                (chrome_out, composition.DEFAULT_CHROME_MODULE_NAME),
                (content_out, composition.DEFAULT_CONTENT_MODULE_NAME),
            ):
                (out_dir / "args.gn").write_text("is_debug = true\n", encoding="utf-8")
                (out_dir / f"{module_name}.js").write_text(
                    "loader bytes\n", encoding="utf-8"
                )
                (out_dir / f"{module_name}.wasm").write_bytes(b"\x00asm")

            snapshots = composition.snapshot_composition_inputs(
                chrome_out_dir=chrome_out,
                chrome_module_name=composition.DEFAULT_CHROME_MODULE_NAME,
                content_out_dir=content_out,
                content_module_name=composition.DEFAULT_CONTENT_MODULE_NAME,
                relay_script=composition.DEFAULT_RELAY_SCRIPT,
            )
            identity = composition.input_snapshot_identity(
                snapshots,
                chrome_module_name=composition.DEFAULT_CHROME_MODULE_NAME,
                content_module_name=composition.DEFAULT_CONTENT_MODULE_NAME,
            )

            self.assertEqual(
                hashlib.sha256(b"loader bytes\n").hexdigest(),
                identity["chrome_controlled_https"]["loader"]["sha256"],
            )
            self.assertEqual(
                hashlib.sha256(b"\x00asm").hexdigest(),
                identity["content_shell_wisp_recovery"]["wasm"]["sha256"],
            )
            self.assertIn("runner_source", identity["chrome_controlled_https"])
            self.assertIn("host_server_source", identity["content_shell_wisp_recovery"])
            self.assertIn("wisp_relay_server_source", identity["shared"])
            composition.verify_input_snapshots_unchanged(snapshots)

    def test_snapshot_change_after_preflight_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "input.txt"
            path.write_text("before", encoding="utf-8")
            snapshot = composition._snapshot_file(path, "test input")
            snapshots = {"shared": {"input": snapshot}}
            path.write_text("after", encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "changed after preflight"):
                composition.verify_input_snapshots_unchanged(snapshots)

    def test_child_commands_forward_isolated_output_and_diagnostics_paths(self) -> None:
        chrome_command = composition.chrome_child_command(
            out_dir=Path("/chrome-out"),
            module_name="chrome_module",
            timeout=45.0,
            diagnostics_dir=Path("/diagnostics/chrome"),
            browser=Path("/browser"),
            node=Path("/node"),
            relay_script=Path("/relay.js"),
            no_sandbox=True,
        )
        content_command = composition.content_child_command(
            out_dir=Path("/content-out"),
            module_name="content_module",
            timeout=46.5,
            diagnostics_dir=Path("/diagnostics/content"),
            browser=Path("/browser"),
            node=Path("/node"),
            relay_script=Path("/relay.js"),
            no_sandbox=True,
        )
        self.assertEqual(sys.executable, chrome_command[0])
        self.assertEqual(str(composition.CHROME_RUNNER_PATH), chrome_command[1])
        self.assertEqual(str(composition.CONTENT_RUNNER_PATH), content_command[1])
        self.assertEqual("/node", chrome_command[chrome_command.index("--node") + 1])
        self.assertEqual("/node", content_command[content_command.index("--node") + 1])
        for command, out_dir, module, diagnostics in (
            (chrome_command, "/chrome-out", "chrome_module", "/diagnostics/chrome"),
            (content_command, "/content-out", "content_module", "/diagnostics/content"),
        ):
            self.assertEqual(out_dir, command[command.index("--out-dir") + 1])
            self.assertEqual(module, command[command.index("--module-name") + 1])
            self.assertEqual(diagnostics, command[command.index("--diagnostics-dir") + 1])
            self.assertEqual("/relay.js", command[command.index("--relay-script") + 1])
            self.assertIn("--no-sandbox", command)

    def test_run_composition_serializes_distinct_children_and_verifies_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            chrome_out = root / "chrome-out"
            content_out = root / "content-out"
            chrome_out.mkdir()
            content_out.mkdir()
            snapshots: dict[str, dict[str, composition.FileSnapshot]] = {}
            expected_inputs = input_identity()
            commands: list[tuple[str, list[str], float]] = []
            verified_groups: list[tuple[str, ...]] = []

            def fake_run_child(
                name: str, command: list[str], timeout: float
            ) -> composition.ChildExecution:
                commands.append((name, command, timeout))
                return (
                    chrome_execution()
                    if name == "Chrome controlled-HTTPS"
                    else content_execution()
                )

            with (
                mock.patch.object(
                    composition,
                    "snapshot_composition_inputs",
                    return_value=snapshots,
                ),
                mock.patch.object(
                    composition,
                    "input_snapshot_identity",
                    return_value=expected_inputs,
                ),
                mock.patch.object(composition, "run_child", side_effect=fake_run_child),
                mock.patch.object(
                    composition,
                    "validate_chrome_execution",
                    return_value=(chrome_evidence(), VERSIONS),
                ),
                mock.patch.object(
                    composition,
                    "validate_content_execution",
                    return_value=(content_evidence(), VERSIONS),
                ),
                mock.patch.object(
                    composition,
                    "verify_input_snapshots_unchanged",
                    side_effect=lambda _snapshots, groups: verified_groups.append(
                        tuple(groups)
                    ),
                ),
            ):
                result = composition.run_composition(
                    chrome_out_dir=chrome_out,
                    chrome_module_name=composition.DEFAULT_CHROME_MODULE_NAME,
                    chrome_timeout=31.0,
                    content_out_dir=content_out,
                    content_module_name=composition.DEFAULT_CONTENT_MODULE_NAME,
                    content_timeout=32.0,
                    diagnostics_dir=root / "diagnostics",
                    browser=Path("/browser"),
                    node=Path("/node"),
                    relay_script=composition.DEFAULT_RELAY_SCRIPT,
                    no_sandbox=True,
                )

        self.assertEqual(
            ["Chrome controlled-HTTPS", "Content Shell WISP carrier-close recovery"],
            [name for name, _command, _timeout in commands],
        )
        self.assertEqual(
            [("shared", "chrome_controlled_https"), ("shared", "content_shell_wisp_recovery")],
            verified_groups,
        )
        self.assertEqual("pass", result["status"])
        self.assertFalse(result["composition"]["same_instance_chrome_recovery"])

    def test_run_composition_rejects_m6_incompatible_timeout_before_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            chrome_out = root / "chrome-out"
            content_out = root / "content-out"
            chrome_out.mkdir()
            content_out.mkdir()
            with (
                mock.patch.object(composition, "run_child") as run_child,
                self.assertRaisesRegex(M0Error, "at least five seconds"),
            ):
                composition.run_composition(
                    chrome_out_dir=chrome_out,
                    chrome_module_name=composition.DEFAULT_CHROME_MODULE_NAME,
                    chrome_timeout=4.9,
                    content_out_dir=content_out,
                    content_module_name=composition.DEFAULT_CONTENT_MODULE_NAME,
                    content_timeout=32.0,
                    diagnostics_dir=root / "diagnostics",
                    browser=None,
                    node=None,
                    relay_script=composition.DEFAULT_RELAY_SCRIPT,
                    no_sandbox=False,
                )
        run_child.assert_not_called()

    def test_capped_streaming_output_rejects_child_without_buffering_full_output(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'x' * 65536); sys.stdout.flush()",
        ]
        with (
            mock.patch.object(composition, "MAX_CHILD_OUTPUT_BYTES", 32),
            mock.patch.object(composition, "OUTPUT_READ_CHUNK_BYTES", 16),
            self.assertRaisesRegex(M0Error, "output exceeds the configured byte bound"),
        ):
            composition.run_child("capped output", command, 5.0)

    def test_run_child_returns_only_after_normal_group_and_pipe_completion(self) -> None:
        execution = composition.run_child(
            "normal child",
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stdout.buffer.write(b'normal output\\n'); "
                    "sys.stderr.buffer.write(b'diagnostic output\\n')"
                ),
            ],
            5.0,
        )

        self.assertEqual(0, execution.returncode)
        self.assertEqual("normal output\n", execution.stdout)
        self.assertEqual("diagnostic output\n", execution.stderr)

    def test_partial_reader_start_preserves_error_and_cleans_started_reader(self) -> None:
        process = mock.Mock()
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        process.poll.return_value = None
        starts = 0
        started_readers: list[threading.Thread] = []
        failed_readers: list[threading.Thread] = []
        joined_readers: list[threading.Thread] = []
        events: list[str] = []
        original_start = composition.threading.Thread.start
        original_join = composition._join_output_threads

        def start_stdout_then_fail_stderr(thread: threading.Thread) -> None:
            nonlocal starts
            starts += 1
            if starts == 2:
                failed_readers.append(thread)
                raise RuntimeError("stderr reader did not start")
            started_readers.append(thread)
            original_start(thread)

        def fail_group_cleanup(
            observed_process: object, observed_threads: Sequence[threading.Thread]
        ) -> None:
            self.assertIs(process, observed_process)
            self.assertEqual(tuple(started_readers), tuple(observed_threads))
            events.append("stop")
            raise M0Error("cleanup failure")

        def join_started_readers(threads: Sequence[threading.Thread]) -> None:
            events.append("join")
            joined_readers.extend(threads)
            original_join(threads)

        def close_pipes(observed_process: object) -> None:
            self.assertIs(process, observed_process)
            events.append("close")

        with (
            mock.patch.object(composition.subprocess, "Popen", return_value=process),
            mock.patch.object(
                composition.threading.Thread,
                "start",
                autospec=True,
                side_effect=start_stdout_then_fail_stderr,
            ),
            mock.patch.object(
                composition,
                "_stop_child_cooperatively",
                side_effect=fail_group_cleanup,
            ) as stop_child,
            mock.patch.object(
                composition,
                "_join_output_threads",
                side_effect=join_started_readers,
            ),
            mock.patch.object(
                composition,
                "_close_child_pipes",
                side_effect=close_pipes,
            ),
            self.assertRaisesRegex(RuntimeError, "stderr reader did not start"),
        ):
            composition.run_child("partial reader start", ["child"], 1.0)

        stop_child.assert_called_once_with(process, mock.ANY)
        self.assertEqual(tuple(started_readers), stop_child.call_args.args[1])
        self.assertEqual(1, len(started_readers))
        self.assertEqual(1, len(failed_readers))
        self.assertEqual(started_readers, joined_readers)
        self.assertNotIn(failed_readers[0], joined_readers)
        self.assertEqual(["stop", "join", "close"], events[:3])

    def test_cooperative_timeout_cleanup_escalates_only_the_runner_group(self) -> None:
        process = mock.Mock()
        process.pid = 1234
        # The leader can already be reaped while descendants remain in its
        # process group. Cleanup must still signal that group.
        process.poll.return_value = 0
        with (
            mock.patch.object(composition.os, "killpg") as killpg,
            mock.patch.object(
                composition, "_wait_for_process_and_output", side_effect=[False, True]
            ),
        ):
            force_killed = composition._stop_child_cooperatively(process, ())

        self.assertTrue(force_killed)
        self.assertEqual(
            [
                mock.call(1234, signal.SIGINT),
                mock.call(1234, signal.SIGKILL),
            ],
            killpg.call_args_list,
        )

    def test_cooperative_timeout_cleanup_allows_child_finally_before_escalation(self) -> None:
        process = mock.Mock()
        process.pid = 1235
        process.poll.return_value = 0
        with (
            mock.patch.object(composition.os, "killpg") as killpg,
            mock.patch.object(
                composition, "_wait_for_process_and_output", return_value=True
            ),
        ):
            force_killed = composition._stop_child_cooperatively(process, ())

        self.assertFalse(force_killed)
        killpg.assert_called_once_with(1235, signal.SIGINT)

    def test_group_absence_probe_fails_closed_on_permission_error(self) -> None:
        process = mock.Mock()
        process.pid = 1236
        with (
            mock.patch.object(
                composition.os, "killpg", side_effect=PermissionError("denied")
            ),
            self.assertRaisesRegex(M0Error, "cannot verify child runner process-group"),
        ):
            composition._child_process_group_exists(process)

    def test_reaped_leader_pipe_holder_is_force_killed_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            child_pid_path = Path(temporary_directory) / "child.pid"
            # The leader exits successfully after starting a same-group child
            # that ignores SIGINT and retains both inherited output pipes.
            command = [
                "/bin/sh",
                "-c",
                (
                    "trap '' INT; (trap '' INT; sleep 60) & "
                    f"printf '%s' \"$!\" > {child_pid_path}"
                ),
            ]
            try:
                with (
                    mock.patch.object(
                        composition, "FORCED_KILL_GRACE_SECONDS", 0.25
                    ),
                    mock.patch.object(
                        composition, "COOPERATIVE_STOP_GRACE_SECONDS", 0.1
                    ),
                    mock.patch.object(composition, "OUTPUT_POLL_SECONDS", 0.01),
                    self.assertRaisesRegex(
                        M0Error, "force-killed only the child runner"
                    ),
                ):
                    composition.run_child("reaped pipe holder", command, 1.0)
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                for _ in range(50):
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    composition.time.sleep(0.01)
                else:
                    self.fail("force-killed pipe-holder descendant is still alive")
            finally:
                if child_pid_path.exists():
                    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_reaped_leader_devnull_descendant_cannot_return_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            child_pid_path = Path(temporary_directory) / "child.pid"
            # This descendant closes both captured pipes. It proves the normal
            # path also waits for group absence rather than EOF alone.
            command = [
                "/bin/sh",
                "-c",
                (
                    "trap '' INT; "
                    "(trap '' INT; sleep 60 </dev/null >/dev/null 2>&1) & "
                    f"printf '%s' \"$!\" > {child_pid_path}"
                ),
            ]
            try:
                with (
                    mock.patch.object(
                        composition, "FORCED_KILL_GRACE_SECONDS", 0.25
                    ),
                    mock.patch.object(
                        composition, "COOPERATIVE_STOP_GRACE_SECONDS", 0.1
                    ),
                    mock.patch.object(composition, "OUTPUT_POLL_SECONDS", 0.01),
                    self.assertRaisesRegex(
                        M0Error, "force-killed only the child runner"
                    ),
                ):
                    composition.run_child("reaped devnull descendant", command, 1.0)
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                for _ in range(50):
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    composition.time.sleep(0.01)
                else:
                    self.fail("force-killed devnull descendant is still alive")
            finally:
                if child_pid_path.exists():
                    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_bounded_failure_diagnostics_omit_child_output_and_keep_nonrelease_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            diagnostics_dir = Path(temporary_directory) / "diagnostics"
            diagnostic = composition.write_failure_diagnostics(
                diagnostics_dir,
                stage="m5_child",
                error=M0Error("child secret output should not be copied"),
            )
            payload = json.loads(diagnostic.read_text(encoding="utf-8"))

        self.assertEqual("fail", payload["status"])
        self.assertEqual("pre_m7_m8_not_releasable", payload["release_status"])
        self.assertEqual("unverified", payload["artifact_source_provenance"])
        self.assertNotIn("stdout", payload)
        self.assertNotIn("stderr", payload)
        self.assertEqual("m5_child", payload["stage"])


if __name__ == "__main__":
    unittest.main()

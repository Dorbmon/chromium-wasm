#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the isolated M7 host Web Locks scope probe."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_web_locks_scope_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


RUN_NAMESPACE = "run_namespace_0123456789"
ORIGIN = "http://127.0.0.1:45678"


def successful_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "runNamespace": RUN_NAMESPACE,
        "origin": ORIGIN,
        "secureContext": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "sameTopLevelDocumentSiblingDedicatedWorkersProven": True,
        "holderWorkerWebLocksAvailable": True,
        "contenderWorkerWebLocksAvailable": True,
        "ifAvailableReturnedNull": True,
        "contenderPendingBeforeExplicitRelease": True,
        "explicitReleaseQueuedGrantProven": True,
        "contenderPendingBeforeHolderTermination": True,
        "holderTerminationQueuedGrantProven": True,
        "holderWorkerTerminated": True,
        "webLocksScopeLimitation": (
            "per-storage-bucket-not-origin-wide-or-cross-document-proof"
        ),
        "terminationReacquisitionLimitation": (
            "observed-current-browser-behavior-not-profile-recovery"
        ),
        "workerEventTrace": [
            {"ordinal": 1, "marker": "holder:ready"},
            {"ordinal": 2, "marker": "contender:ready"},
            {"ordinal": 3, "marker": "holder:held:explicit"},
            {"ordinal": 4, "marker": "contender:if_available:explicit"},
            {"ordinal": 5, "marker": "contender:wait_queued:explicit"},
            {"ordinal": 6, "marker": "contender:state:explicit"},
            {"ordinal": 7, "marker": "parent:explicit-release-command"},
            {"ordinal": 8, "marker": "holder:released:explicit"},
            {"ordinal": 9, "marker": "contender:held:explicit"},
            {"ordinal": 10, "marker": "contender:released:explicit"},
            {"ordinal": 11, "marker": "holder:held:termination"},
            {"ordinal": 12, "marker": "contender:wait_queued:termination"},
            {"ordinal": 13, "marker": "contender:state:termination"},
            {"ordinal": 14, "marker": "parent:holder-termination-command"},
            {"ordinal": 15, "marker": "contender:held:termination"},
            {"ordinal": 16, "marker": "contender:released:termination"},
        ],
        "eventOrder": {
            "holderExplicitHeld": 3,
            "contenderIfAvailable": 4,
            "contenderExplicitQueued": 5,
            "contenderExplicitBlocked": 6,
            "explicitReleaseCommand": 7,
            "holderExplicitReleased": 8,
            "contenderExplicitGranted": 9,
            "contenderExplicitReleased": 10,
            "holderTerminationHeld": 11,
            "contenderTerminationQueued": 12,
            "contenderTerminationBlocked": 13,
            "holderTerminationCommand": 14,
            "contenderTerminationGranted": 15,
            "contenderTerminationReleased": 16,
        },
        "opfsTouched": False,
        "syncAccessHandleCoordinated": False,
        "syncAccessHandleWriterExclusivityProven": False,
        "posixFcntlLocksProven": False,
        "byteRangeLocksProven": False,
        "sqliteLeveldbLockSemanticsProven": False,
        "profilePersistenceProven": False,
        "atomicRecoveryProven": False,
        "crashRecoveryProven": False,
        "gracefulRuntimeShutdownProven": False,
        "gracefulProfileShutdownProven": False,
        "m7GateComplete": False,
        "failureDiagnostics": None,
        "error": None,
    }


def swap_trace_ordinals(result: dict[str, object], first: str, second: str) -> None:
    trace = result["workerEventTrace"]
    assert isinstance(trace, list)
    entries = {
        entry["marker"]: entry
        for entry in trace
        if isinstance(entry, dict) and isinstance(entry.get("marker"), str)
    }
    first_entry = entries[first]
    second_entry = entries[second]
    first_entry["ordinal"], second_entry["ordinal"] = (
        second_entry["ordinal"],
        first_entry["ordinal"],
    )


class M7WebLocksScopeDomSmokeTest(unittest.TestCase):
    def test_accepts_scoped_named_lock_evidence(self) -> None:
        smoke.validate_result(
            successful_result(),
            expected_origin=ORIGIN,
            expected_run_namespace=RUN_NAMESPACE,
        )

    def test_rejects_missing_lifetime_or_contention_evidence(self) -> None:
        mutations = (
            lambda result: result.__setitem__("ifAvailableReturnedNull", False),
            lambda result: result.__setitem__(
                "explicitReleaseQueuedGrantProven", False
            ),
            lambda result: result.__setitem__(
                "holderTerminationQueuedGrantProven", False
            ),
            lambda result: result["eventOrder"].__setitem__(
                "contenderExplicitGranted", 5
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaises(M0Error):
                    smoke.validate_result(
                        result,
                        expected_origin=ORIGIN,
                        expected_run_namespace=RUN_NAMESPACE,
                    )

    def test_rejects_overstated_opfs_or_persistence_claims(self) -> None:
        for field in (
            "opfsTouched",
            "syncAccessHandleCoordinated",
            "syncAccessHandleWriterExclusivityProven",
            "posixFcntlLocksProven",
            "byteRangeLocksProven",
            "sqliteLeveldbLockSemanticsProven",
            "profilePersistenceProven",
            "atomicRecoveryProven",
            "crashRecoveryProven",
            "gracefulRuntimeShutdownProven",
            "gracefulProfileShutdownProven",
            "m7GateComplete",
        ):
            with self.subTest(field=field):
                result = successful_result()
                result[field] = True
                with self.assertRaises(M0Error):
                    smoke.validate_result(
                        result,
                        expected_origin=ORIGIN,
                        expected_run_namespace=RUN_NAMESPACE,
                    )

    def test_parser_rejects_duplicate_keys_and_wrong_namespace(self) -> None:
        payload = json.dumps(successful_result()).encode("utf-8")
        self.assertIsNotNone(smoke.parse_result_payload(payload, RUN_NAMESPACE))
        self.assertIsNone(
            smoke.parse_result_payload(
                b'{"protocol":1,"protocol":1,"case":"m7_web_locks_scope"}',
                RUN_NAMESPACE,
            )
        )
        self.assertIsNone(smoke.parse_result_payload(payload, "different_namespace_123"))

    def test_rejects_unknown_claims_and_trace_ordinal_mismatches(self) -> None:
        def explicit_command_after_holder_release(result: dict[str, object]) -> None:
            swap_trace_ordinals(
                result,
                "parent:explicit-release-command",
                "holder:released:explicit",
            )
            result["eventOrder"]["explicitReleaseCommand"] = 8
            result["eventOrder"]["holderExplicitReleased"] = 7

        def next_case_before_explicit_contender_release(
            result: dict[str, object]
        ) -> None:
            swap_trace_ordinals(
                result,
                "contender:released:explicit",
                "holder:held:termination",
            )
            result["eventOrder"]["contenderExplicitReleased"] = 11
            result["eventOrder"]["holderTerminationHeld"] = 10

        mutations = (
            lambda result: result.__setitem__("unexpectedClaim", False),
            lambda result: result["workerEventTrace"][1].__setitem__("ordinal", 1),
            lambda result: result["workerEventTrace"][0].__setitem__(
                "marker", "unknown:marker"
            ),
            lambda result: result["eventOrder"].__setitem__(
                "holderExplicitHeld", 2
            ),
            lambda result: result.__setitem__(
                "workerEventTrace", result["workerEventTrace"] * 3
            ),
            explicit_command_after_holder_release,
            next_case_before_explicit_contender_release,
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                result = copy.deepcopy(successful_result())
                mutate(result)
                with self.assertRaises(M0Error):
                    smoke.validate_result(
                        result,
                        expected_origin=ORIGIN,
                        expected_run_namespace=RUN_NAMESPACE,
                    )

    def test_host_scope_uses_two_dedicated_workers_without_filesystem_apis(self) -> None:
        host = source("tools/wasm/host/m7_web_locks_scope_smoke.js")
        worker = source("tools/wasm/host/m7_web_locks_scope_smoke_worker.js")
        runner = source("tools/wasm/run_m7_web_locks_scope_dom_smoke.py")
        for marker in (
            "new Worker(workerUrl",
            "HOLDER_ROLE",
            "CONTENDER_ROLE",
            "ifAvailableReturnedNull: false",
            "explicitReleaseQueuedGrantProven: false",
            "holderTerminationQueuedGrantProven: false",
            "opfsTouched: false",
            "m7GateComplete: false",
            "holder-termination-command",
            "per-storage-bucket-not-origin-wide-or-cross-document-proof",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)
        for marker in (
            "navigator.locks.request",
            "ifAvailable: true",
            'self.addEventListener("message"',
            "DedicatedWorkerGlobalScope",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, worker)
        for forbidden in (
            "navigator.storage.getDirectory",
            "createSyncAccessHandle",
            "wasmfs_create",
            "F_SETLK",
            "F_SETLKW",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, worker)
        for marker in (
            'HOST_ROOT = "/__m7_web_locks_scope__"',
            '"Cross-Origin-Opener-Policy", "same-origin"',
            '"Cross-Origin-Embedder-Policy", "require-corp"',
            '"Cache-Control", "no-store"',
            '"Referrer-Policy", "no-referrer"',
            "result_token",
            "validate_result(",
            "MAX_TRACE_EVENTS = 32",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertNotIn("--out-dir", runner)
        self.assertNotIn("application/wasm", runner)

    def test_javascript_parses_with_node_when_available(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        for path in (
            "tools/wasm/host/m7_web_locks_scope_smoke.js",
            "tools/wasm/host/m7_web_locks_scope_smoke_worker.js",
        ):
            with self.subTest(path=path):
                completed = subprocess.run(
                    [node, "--check", str(TOOLS_DIR.parents[1] / path)],
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    "Node rejected Web Locks host asset:\n"
                    + completed.stdout
                    + completed.stderr,
                )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the M8 page dedicated-worker smoke harness."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlparse


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server
import run_m8_dedicated_worker_smoke


def versions() -> dict[str, str]:
    return {
        "chromium": "chromium-revision",
        "v8": "v8-revision",
        "emscripten": "emscripten-revision",
        "port": "port-revision",
    }


def passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": m3_content_server.M8_DEDICATED_WORKER_CASE,
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": versions(),
        "readiness": {
            "navigationCommitted": True,
            "pageProbe": {
                "protocol": 1,
                "fixture": "chromium-wasm-m8-dedicated-worker-v1",
                "workerSource": "blob-data-url",
                "ready": True,
                "workerCreated": True,
                "mainTransferDetached": True,
                "receivedSequence": 37,
                "receivedPayload": "worker-message:reply",
                "receivedByteLength": 4,
                "receivedBytes": [5, 8, 15, 16],
                "workerTimerTicks": 2,
                "workerHeartbeatCount": 2,
                "workerHeartbeatsBeforeBusy": 2,
                "workerBusyStarted": True,
                "workerBusyDurationMs": 75.0,
                "workerBusyIterations": 100,
                "mainTimerTicksDuringBusy": 5,
                "mainTimerTicks": 2,
                "terminationRequested": True,
                "heartbeatsAtTermination": 2,
                "postTerminationHeartbeatCount": 0,
                "workerTerminated": True,
                "failure": None,
            },
        },
        "shutdown": {
            "ok": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
        },
        "failedChecks": [],
    }


class M8DedicatedWorkerResultTest(unittest.TestCase):
    def test_complete_worker_contract_is_accepted(self) -> None:
        probe = run_m8_dedicated_worker_smoke.validate_result(
            passing_result(), versions()
        )

        self.assertEqual(probe["receivedBytes"], [5, 8, 15, 16])

    def test_missing_transfer_detach_is_rejected(self) -> None:
        result = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        probe = readiness["pageProbe"]
        assert isinstance(probe, dict)
        probe["mainTransferDetached"] = False

        with self.assertRaisesRegex(M0Error, "mainTransferDetached"):
            run_m8_dedicated_worker_smoke.validate_result(result, versions())

    def test_unclean_shutdown_is_rejected(self) -> None:
        result = passing_result()
        shutdown = result["shutdown"]
        assert isinstance(shutdown, dict)
        shutdown["runtimeExitCode"] = 1

        with self.assertRaisesRegex(M0Error, "shutdown"):
            run_m8_dedicated_worker_smoke.validate_result(result, versions())

    def test_page_timer_stall_during_worker_cpu_work_is_rejected(self) -> None:
        result = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        probe = readiness["pageProbe"]
        assert isinstance(probe, dict)
        probe["mainTimerTicksDuringBusy"] = 0

        with self.assertRaisesRegex(M0Error, "mainTimerTicksDuringBusy"):
            run_m8_dedicated_worker_smoke.validate_result(result, versions())

    def test_post_termination_heartbeat_is_rejected(self) -> None:
        result = passing_result()
        readiness = result["readiness"]
        assert isinstance(readiness, dict)
        probe = readiness["pageProbe"]
        assert isinstance(probe, dict)
        probe["postTerminationHeartbeatCount"] = 1

        with self.assertRaisesRegex(
            M0Error, "postTerminationHeartbeatCount"
        ):
            run_m8_dedicated_worker_smoke.validate_result(result, versions())


class M8DedicatedWorkerRoutingTest(unittest.TestCase):
    def test_smoke_url_selects_the_worker_fixture(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 43210)

        url = m3_content_server.m8_dedicated_worker_smoke_url(
            Server(), "test-token", versions(), module_name="content_shell_wasm"
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(
            query["case"], [m3_content_server.M8_DEDICATED_WORKER_CASE]
        )
        self.assertEqual(
            query["fixture"], ["/__m3__/m8-dedicated-worker-fixture.html"]
        )
        self.assertEqual(
            query["module"], ["/__m3__/artifacts/content_shell_wasm.js"]
        )
        self.assertTrue(
            m3_content_server.is_supported_result_case(
                m3_content_server.M8_DEDICATED_WORKER_CASE
            )
        )

    def test_fixture_and_host_require_worker_lifetime_evidence(self) -> None:
        fixture = m3_content_server.M8_DEDICATED_WORKER_FIXTURE.read_text(
            encoding="utf-8"
        )
        host = (m3_content_server.M3_HOST_DIR / "content_shell_host.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("new Worker(workerUrl)", fixture)
        self.assertIn("worker.postMessage", fixture)
        self.assertIn("workerBusyDurationMs", fixture)
        self.assertIn("postTerminationHeartbeatCount", fixture)
        self.assertIn("mainTransferDetached", fixture)
        self.assertIn("worker.terminate()", fixture)
        self.assertIn("hasM8DedicatedWorkerProbe", host)
        self.assertIn("runM8DedicatedWorkerSmokeFromQuery", host)


if __name__ == "__main__":
    unittest.main()

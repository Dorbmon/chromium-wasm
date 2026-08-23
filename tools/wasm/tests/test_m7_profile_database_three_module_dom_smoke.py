#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the M7 three-fresh-Module profile database acceptance."""

from __future__ import annotations

import copy
from collections import deque
import hashlib
import http.client
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m7_chrome_profile_database_dom_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


VERSIONS = {
    "chromium": "a" * 40,
    "v8": "b" * 40,
    "emscripten": "c" * 40,
}
ARTIFACT_IDENTITY = {
    "artifact_delivery": smoke.ARTIFACT_DELIVERY,
    "artifact_source_provenance": smoke.ARTIFACT_SOURCE_PROVENANCE,
    "build_config": {"bytes": 79, "sha256": "9" * 64},
    "build_config_provenance": smoke.BUILD_CONFIG_PROVENANCE,
    "loader": {"bytes": 10, "sha256": "d" * 64},
    "module_name": smoke.PRODUCT_MODULE_NAME,
    "wasm": {"bytes": 20, "sha256": "e" * 64},
}
CAPTURE_HARNESS_IDENTITY = {
    "host_html": {"bytes": 11, "sha256": "f" * 64},
    "host_js": {"bytes": 12, "sha256": "0" * 64},
    "runner_source": {"bytes": 13, "sha256": "1" * 64},
    "source_snapshot_provenance": smoke.SOURCE_SNAPSHOT_PROVENANCE,
    "version_provenance": smoke.VERSION_PROVENANCE,
}
ORIGIN = "http://127.0.0.1:43127"
TOKEN_A_DIGEST = "2" * 64
TOKEN_B_DIGEST = "3" * 64


def expected_markers(ordinal: int) -> list[str]:
    return smoke.expected_markers(
        ordinal, {"runOne": TOKEN_A_DIGEST, "runTwo": TOKEN_B_DIGEST}
    )


def passing_run(ordinal: int) -> dict[str, object]:
    markers = expected_markers(ordinal)
    modes = ("write-a", "verify-a-write-b", "verify-b")
    identities = ("4" * 32, "5" * 32, "6" * 32)
    return {
        "abort": None,
        "activeClearedAfterLifecycle": True,
        "expectedExitStatusObserved": False,
        "factoryError": None,
        "factorySettled": True,
        "freshModuleObject": True,
        "leaseReleasedMarkerObserved": True,
        "markerCount": len(markers),
        "markerSequenceAccepted": True,
        "markerSource": "stderr-only",
        "markers": markers,
        "mode": modes[ordinal - 1],
        "moduleIdentity": identities[ordinal - 1],
        "onExitCount": 1,
        "ordinal": ordinal,
        "postLifecycleTimerObserved": True,
        "markerDeliveryCompleteAtProcessExit": False,
        "processExitBeforeOnExit": True,
        "processExitCode": 0,
        "processExitCount": 1,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "sameModuleAsPrior": None if ordinal == 1 else False,
        "startKind": "initial" if ordinal == 1 else "setTimeout-0",
        "stderr": markers,
        "stdout": [],
    }


def passing_result() -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "pass",
        "m7GateComplete": False,
        "limitations": list(smoke.LIMITATIONS),
        "artifact": copy.deepcopy(ARTIFACT_IDENTITY),
        "capture_harness": copy.deepcopy(CAPTURE_HARNESS_IDENTITY),
        "versions": copy.deepcopy(VERSIONS),
        "origin": ORIGIN,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "sameOriginDocument": True,
        "preferencesRoundTripProven": False,
        "sqliteLevelDbGracefulCloseReopenProven": True,
        "sqliteLevelDbCrashRecoveryProven": False,
        "directoryDurabilityProven": False,
        "cookiesHistoryBookmarksSessionsProven": False,
        "webStorageAndServiceWorkerProven": False,
        "concurrentProfileContenderProven": False,
        "factoryCalls": 3,
        "bridge": {
            "protocol": 1,
            "permanent": True,
            "frozen": True,
            "installedBeforeModuleFactory": True,
            "processExitDispatches": 3,
            "noActiveProcessExitRejected": 0,
            "duplicateProcessExitRejected": 0,
            "lateProcessExitRejected": 0,
            "activeRunAtResult": None,
        },
        "transition": {
            "runTwoScheduledExactlyOnce": True,
            "runTwoScheduleMethod": "setTimeout(...,0)",
            "runTwoTimerFired": True,
            "runTwoScheduledAfterRunOneNativeExit": True,
            "runTwoScheduledAfterRunOneOnExit": True,
            "runTwoStartedAfterRunOneActiveClear": True,
            "runThreeScheduledExactlyOnce": True,
            "runThreeScheduleMethod": "setTimeout(...,0)",
            "runThreeTimerFired": True,
            "runThreeScheduledAfterRunTwoNativeExit": True,
            "runThreeScheduledAfterRunTwoOnExit": True,
            "runThreeStartedAfterRunTwoActiveClear": True,
        },
        "finalQuiescence": {
            "activeRunAtPreUploadCheck": None,
            "activeRunAtTaskEnd": None,
            "activeRunAtTaskStart": None,
            "bridgeRecheckedImmediatelyBeforeUpload": True,
            "callbacksAtPreUploadCheck": 23,
            "callbacksAtRunThreeActiveClear": 23,
            "callbacksAtTaskEnd": 23,
            "callbacksAtTaskStart": 23,
            "completed": True,
            "postLifecycleTimerObservedBeforeTask": True,
            "processExitDispatchesAtPreUploadCheck": 3,
            "processExitReportsAtPreUploadCheck": 3,
            "processExitReportsAtRunThreeActiveClear": 3,
            "processExitReportsAtTaskEnd": 3,
            "quiet": True,
            "quietWindowMs": smoke.FINAL_QUIESCENCE_MS,
            "rejectedProcessExitReportsAtPreUploadCheck": 0,
            "started": True,
            "startedAfterRunThreeActiveClear": True,
            "taskMethod": "setTimeout(...,0)",
            "taskScheduledExactlyOnce": True,
        },
        "tokenEvidence": {
            "algorithm": "SHA-256",
            "runOne": TOKEN_A_DIGEST,
            "runTwo": TOKEN_B_DIGEST,
            "distinct": True,
            "rawTokensExcluded": True,
            "rawTokenLeakDetected": False,
            "rawTokenRedactionCount": 0,
        },
        "hostBoundary": {
            "hostOpfsAccessAttempted": False,
            "hostWebLocksAccessAttempted": False,
            "nativeCallAttempted": False,
            "wasmDataInspectionAttempted": False,
        },
        "runs": [passing_run(1), passing_run(2), passing_run(3)],
        "fatalErrors": [],
        "windowErrors": [],
        "unhandledRejections": [],
        "failedChecks": [],
        "error": None,
    }


def passing_failure_result(
    native_failure_stage: str | None = None,
    native_database_phase: str | None = None,
    pre_dbimpl_construction_observed_before_second_file_exists_post: bool | None = None,
) -> dict[str, object]:
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "fail",
        "failureClass": (
            "native-fixed-failure"
            if native_failure_stage is not None
            else "host-lifecycle"
        ),
        "firstFatalTag": (
            "marker-native-failure"
            if native_failure_stage is not None
            else "factory-rejected"
        ),
        "abortPc": None,
        "fatalHeadline": None,
        "abortReasonKind": None,
        "abortObservationOrder": None,
        "nativeFailureStage": native_failure_stage,
        "nativeDatabasePhase": native_database_phase,
        "preDbImplConstructionObservedBeforeSecondFileExistsPost": (
            pre_dbimpl_construction_observed_before_second_file_exists_post
        ),
        "lifecycle": {
            "acceptedProcessExitCount": 1,
            "activeRunPresent": True,
            "bridgeInstalled": True,
            "bridgeInstalledBeforeModuleFactory": True,
            "callbackCount": 12,
            "factoryCalls": 1,
            "finalQuiescenceCompleted": False,
            "lastProcessExitCode": 1,
            "lastRuntimeExitCode": None,
            "leaseReleasedRunCount": 0,
            "onExitCount": 0,
            "processExitReportCount": 1,
            "rawTokenLeakDetected": False,
            "runCount": 1,
            "unhandledRejectionObserved": False,
            "windowErrorObserved": False,
        },
    }


def validate(result: dict[str, object]) -> None:
    smoke.validate_result(
        result,
        expected_versions=VERSIONS,
        expected_artifact_identity=ARTIFACT_IDENTITY,
        expected_capture_harness_identity=CAPTURE_HARNESS_IDENTITY,
        expected_origin=ORIGIN,
    )


class M7ProfileDatabaseThreeModuleDomSmokeTest(unittest.TestCase):
    def test_uses_only_the_dedicated_m7_profile_database_artifact(self) -> None:
        self.assertEqual(
            smoke.PRODUCT_MODULE_NAME, "chrome_wasm_m7_profile_database_test"
        )
        self.assertEqual(smoke.DEFAULT_MODULE_NAME, smoke.PRODUCT_MODULE_NAME)
        self.assertEqual(
            smoke.DEFAULT_OUT_DIR, Path("out/wasm-chrome-m7-profile-database")
        )
        self.assertEqual(smoke.PRODUCT_GN_TARGET, "//chrome:chrome_wasm")
        self.assertEqual(
            smoke.PRODUCT_GN_ENABLE_ARGUMENT,
            "enable_chromium_wasm_m7_profile_database_test=true",
        )
        self.assertEqual(
            smoke.DEFAULT_GN_ARGUMENTS,
            'import("//out/wasm-chrome-m6/args.gn") '
            "enable_chromium_wasm_m7_profile_database_test=true",
        )
        with self.assertRaises(M0Error):
            smoke._require_product_module_name("chrome_wasm", "test")

    def test_accepts_three_fresh_module_database_evidence(self) -> None:
        validate(passing_result())

    def test_host_validator_accepts_the_runner_result_shape(self) -> None:
        payload = json.dumps(passing_result(), separators=(",", ":"))
        script = r'''
globalThis.location = {origin: "http://127.0.0.1:43127"};
import {validateChromeWasmProfileDatabaseResult} from
  "./tools/wasm/host/chrome_wasm_profile_database_smoke.js";
const result = JSON.parse(process.argv[1]);
const validated = validateChromeWasmProfileDatabaseResult(result);
if (validated.status !== "pass" || validated.error !== null) {
  throw new Error("database host validator rejected runner-shaped evidence");
}
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script, payload],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_fake_loader_split_token_is_structurally_redacted(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "chrome_wasm_profile_database_smoke.js"
        ).as_uri()
        script = (
            "import {validateChromeWasmProfileDatabaseFailureSummary, "
            "runChromeWasmProfileDatabaseFromQuery} from "
            + json.dumps(host_uri)
            + ";\n"
            + r'''
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  throw new Error("Node Web Crypto is unavailable");
}
class FakeElement {
  constructor() {
    this.dataset = {};
    this.textContent = "";
  }
  append() {}
  replaceChildren() {}
}
class FakeCanvas extends FakeElement {
  focus() { document.activeElement = this; }
}
globalThis.HTMLElement = FakeElement;
globalThis.HTMLCanvasElement = FakeCanvas;
const root = new FakeElement();
const canvas = new FakeCanvas();
const status = new FakeElement();
const versions = new FakeElement();
globalThis.document = {
  activeElement: null,
  createElement() { return new FakeElement(); },
  querySelector(selector) {
    return new Map([
      ["#m7-profile-database-root", root],
      ["#m7-profile-database-canvas", canvas],
      ["#m7-profile-database-status", status],
      ["#m7-profile-database-versions", versions],
    ]).get(selector) ?? null;
  },
};
const eventListeners = new Map();
globalThis.addEventListener = (type, listener) => {
  const listeners = eventListeners.get(type) ?? [];
  listeners.push(listener);
  eventListeners.set(type, listeners);
};
globalThis.removeEventListener = (type, listener) => {
  eventListeners.set(type, (eventListeners.get(type) ?? []).filter(
      (candidate) => candidate !== listener));
};
globalThis.crossOriginIsolated = true;
globalThis.__foreignConversionCount = 0;

const loaderSource =
    'export default function(options) {\n' +
    '  const raw = options.arguments.find((argument) =>\n' +
    '      argument.startsWith("--wasm-profile-database-token-a=")).split("=")[1];\n' +
    '  globalThis.__fakeRawToken = raw;\n' +
    '  options.print({toString() {\n' +
    '    ++globalThis.__foreignConversionCount;\n' +
    '    return raw;\n' +
    '  }});\n' +
    '  options.printErr("CHROMIUM_WASM_M7_DATABASE_PHASE:task-post");\n' +
    '  options.printErr("CHROMIUM_WASM_M7_DATABASE_PHASE:leveldb-write-pre-dbimpl-construction");\n' +
    '  options.printErr("CHROMIUM_WASM_M7_DATABASE_PHASE:leveldb-write-env-file-exists-second-post");\n' +
    '  options.printErr("CHROMIUM_WASM_M7_DATABASE_PHASE:sqlite-write");\n' +
    '  options.printErr("CHROMIUM_WASM_M7_DATABASE_PHASE:leveldb-read");\n' +
    '  options.print(raw.slice(0, 31));\n' +
    '  options.printErr(raw.slice(31));\n' +
    '  globalThis.__chromiumWasmHostBridgeV1.reportFatal("fake loader failure");\n' +
    '  return Promise.resolve({});\n' +
    '}\n';
const loaderBytes = new TextEncoder().encode(loaderSource);
const wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (value) => value.toString(16).padStart(2, "0")).join("");
}
const artifact = {
  artifact_delivery: "immutable-in-memory-server-snapshot",
  artifact_source_provenance: "unverified",
  build_config: {bytes: 1, sha256: "a".repeat(64)},
  build_config_provenance: "selected-out-dir-args-gn-immutable-snapshot",
  loader: {bytes: loaderBytes.byteLength, sha256: await digest(loaderBytes)},
  module_name: "chrome_wasm_m7_profile_database_test",
  wasm: {bytes: wasmBytes.byteLength, sha256: await digest(wasmBytes)},
};
const captureHarness = {
  host_html: {bytes: 1, sha256: "b".repeat(64)},
  host_js: {bytes: 1, sha256: "c".repeat(64)},
  runner_source: {bytes: 1, sha256: "d".repeat(64)},
  source_snapshot_provenance:
      "on-disk-byte-snapshots-at-server-startup-not-commit-provenance",
  version_provenance:
      "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance",
};
const versionsValue = {
  chromium: "e".repeat(40),
  v8: "f".repeat(40),
  emscripten: "0".repeat(40),
};
const query = new URLSearchParams({
  token: "fake-loader-result-token-123456",
  module: artifact.module_name,
  timeoutMs: "1000",
  versions: JSON.stringify(versionsValue),
  artifact: JSON.stringify(artifact),
  captureHarness: JSON.stringify(captureHarness),
});
globalThis.location = new URL(
    "https://m7.test/__m7_chrome_profile_database__/?" + query);
const NativeURL = URL;
globalThis.URL = class extends NativeURL {};
URL.createObjectURL = () =>
    "data:text/javascript;base64," + Buffer.from(loaderSource).toString("base64");
URL.revokeObjectURL = () => {};
let posted = null;
function artifactResponse(url, bytes, contentType) {
  return {
    ok: true,
    url,
    headers: new Headers({
      "Cache-Control": "no-store",
      "Content-Type": contentType,
      "Cross-Origin-Embedder-Policy": "require-corp",
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    }),
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
globalThis.fetch = async (url, options = {}) => {
  if (options.method === "POST") {
    posted = JSON.parse(options.body);
    return {ok: true, status: 204};
  }
  if (url.endsWith(".js")) {
    return artifactResponse(url, loaderBytes, "text/javascript");
  }
  if (url.endsWith(".wasm")) {
    return artifactResponse(url, wasmBytes, "application/wasm");
  }
  throw new Error("unexpected fetch");
};

let rejected = false;
try {
  await runChromeWasmProfileDatabaseFromQuery();
} catch {
  rejected = true;
}
const raw = globalThis.__fakeRawToken;
if (!rejected || typeof raw !== "string" || raw.length !== 64 ||
    globalThis.__foreignConversionCount !== 0 || posted === null ||
    posted.status !== "fail" || posted.failureClass !== "opaque-token-leak" ||
    posted.nativeDatabasePhase !== "leveldb-read" ||
    posted.preDbImplConstructionObservedBeforeSecondFileExistsPost !== true ||
    posted.lifecycle.rawTokenLeakDetected !== true) {
  throw new Error("fake loader did not produce structural token-leak failure");
}
validateChromeWasmProfileDatabaseFailureSummary(posted);
const serialized = JSON.stringify(posted);
if (serialized.includes(raw) || serialized.includes("fake loader failure") ||
    serialized.includes("CHROMIUM_WASM_M7_DATABASE_PHASE:") ||
    status.textContent.includes(raw) ||
    status.textContent.includes("fake loader failure")) {
  throw new Error("fake loader failure exported unsafe diagnostics");
}
delete globalThis.__fakeRawToken;
'''
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_fake_loader_phase_telemetry_fails_closed_and_stays_structural(
        self,
    ) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "chrome_wasm_profile_database_smoke.js"
        ).as_uri()
        loader_source = r'''
export default function(options) {
  const phasePrefix = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
  const markerPrefix = "CHROMIUM_WASM_M7_DATABASE:";
  const scenario = globalThis.__phaseScenario;
  if (scenario === "inactive" || scenario === "late-before-complete" ||
      scenario === "late-task-post" || scenario === "missing-complete" ||
      scenario === "missing-post") {
    globalThis.__lifecycleFactoryCalls =
        (globalThis.__lifecycleFactoryCalls ?? 0) + 1;
    if (globalThis.__lifecycleFactoryCalls !== 1) return Promise.resolve({});
    return (async () => {
      const raw = options.arguments.find((argument) =>
          argument.startsWith("--wasm-profile-database-token-a=")).split("=")[1];
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest(
          "SHA-256", new TextEncoder().encode(raw))),
          (value) => value.toString(16).padStart(2, "0")).join("");
      const module = {};
      options.onRuntimeInitialized.call(module);
      options.printErr(markerPrefix + "READY");
      options.printErr(markerPrefix + "SQLITE_WRITE_ACCEPTED sha256=" + digest);
      options.printErr(markerPrefix + "LEVELDB_WRITE_ACCEPTED sha256=" + digest);
      options.printErr(markerPrefix + "DATABASES_CLOSED sha256=" + digest);
      options.printErr(markerPrefix + "FENCE_OK sha256=" + digest);
      options.printErr(markerPrefix + "LEASE_RELEASED");
      globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({
        protocol: 1,
        exitCode: 0,
      });
      options.onExit(0);
      if (scenario === "late-before-complete") {
        setTimeout(() => {
          options.printErr(phasePrefix + "leveldb-read-get");
          globalThis.__chromiumWasmHostBridgeV1.reportFatal(
              "late phase harness stop");
        }, 0);
        return module;
      }
      if (scenario === "missing-complete") return module;
      options.printErr(phasePrefix + "task-complete");
      if (scenario === "late-task-post") {
        setTimeout(() => {
          options.printErr(phasePrefix + "task-post");
          globalThis.__chromiumWasmHostBridgeV1.reportFatal(
              "late task-post harness stop");
        }, 0);
        return module;
      }
      if (scenario === "missing-post") return module;
      options.printErr(phasePrefix + "task-post");
      setTimeout(() => options.printErr(phasePrefix + "task-started"), 0);
      return module;
    })();
  }
  if (scenario === "raw") {
    const raw = options.arguments.find((argument) =>
        argument.startsWith("--wasm-profile-database-token-a=")).split("=")[1];
    globalThis.__phaseRaw = raw;
    options.printErr(phasePrefix + raw);
  } else if (scenario === "suffixed") {
    options.printErr(
        phasePrefix + "leveldb-write-env-file-exists-first-post-suffix");
  } else if (scenario === "unknown") {
    options.printErr(phasePrefix + "unknown");
  } else if (scenario === "stdout") {
    options.print(phasePrefix + "sqlite-read");
  } else if (scenario === "logger-logv-stdout") {
    options.print(phasePrefix + "leveldb-write-logger-logv-first-pre");
  } else if (scenario === "exact") {
    options.printErr(phasePrefix + "task-post");
    options.printErr(phasePrefix + "sqlite-write");
    options.printErr(phasePrefix + "task-complete");
  } else if (scenario === "duplicate-complete") {
    options.printErr(phasePrefix + "task-complete");
    options.printErr(phasePrefix + "task-complete");
  } else if (scenario === "duplicate-post") {
    options.printErr(phasePrefix + "task-post");
    options.printErr(phasePrefix + "task-post");
  } else if (scenario === "granular") {
    options.printErr(phasePrefix + "leveldb-write-open");
    options.printErr(phasePrefix + "leveldb-write-put");
    options.printErr(phasePrefix + "leveldb-write-compact");
    options.printErr(phasePrefix + "leveldb-write-close");
    options.printErr(phasePrefix + "leveldb-write-tracker");
    options.printErr(phasePrefix + "leveldb-read-open");
    options.printErr(phasePrefix + "leveldb-read-get");
    options.printErr(phasePrefix + "leveldb-read-close");
  } else if (scenario === "checkpoint") {
    options.printErr(phasePrefix + "leveldb-write-tracker");
  } else if (scenario === "environment") {
    options.printErr(phasePrefix + "leveldb-write-env-create-dir");
    options.printErr(phasePrefix + "leveldb-write-env-rename-file");
    options.printErr(phasePrefix + "leveldb-write-env-new-logger");
    options.printErr(phasePrefix + "leveldb-write-env-lock-file");
    options.printErr(phasePrefix + "leveldb-write-env-new-writable-file");
  } else if (scenario === "logger-logv") {
    options.printErr(phasePrefix + "leveldb-write-logger-logv-first-pre");
    options.printErr(phasePrefix + "leveldb-write-logger-logv-first-post");
  } else if (scenario === "logger-logv-suffix") {
    options.printErr(
        phasePrefix + "leveldb-write-logger-logv-first-post-suffix");
  } else if (scenario === "logger-logv-unknown") {
    options.printErr(phasePrefix + "leveldb-write-logger-logv-first");
  } else if (scenario === "file-exists-ordinals") {
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-first-pre");
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-first-post");
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-second-pre");
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-second-post");
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-later-pre");
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-later-post");
  } else if (scenario === "file-exists-second-post") {
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-second-post");
  } else if (scenario === "pre-then-second-post") {
    options.printErr(phasePrefix + "leveldb-write-pre-dbimpl-construction");
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-second-post");
  } else if (scenario === "duplicate-pre-dbimpl") {
    options.printErr(phasePrefix + "leveldb-write-pre-dbimpl-construction");
    options.printErr(phasePrefix + "leveldb-write-pre-dbimpl-construction");
  } else if (scenario === "duplicate-second-post") {
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-second-post");
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-second-post");
  } else if (scenario === "pre-after-second-post") {
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-second-post");
    options.printErr(phasePrefix + "leveldb-write-pre-dbimpl-construction");
  } else if (scenario === "obsolete-file-exists-pre") {
    options.printErr(phasePrefix + "leveldb-write-env-file-exists");
  } else if (scenario === "obsolete-file-exists-post") {
    options.printErr(phasePrefix + "leveldb-write-env-file-exists-returned");
  } else if (scenario === "pre-dbimpl") {
    options.printErr(phasePrefix + "leveldb-write-pre-dbimpl-construction");
  } else {
    throw new Error("unknown phase-loader scenario");
  }
  globalThis.__chromiumWasmHostBridgeV1.reportFatal("phase harness stop");
  return Promise.resolve({});
}
'''
        script = (
            "import {validateChromeWasmProfileDatabaseFailureSummary, "
            "runChromeWasmProfileDatabaseFromQuery} from "
            + json.dumps(host_uri)
            + ";\n"
            + "const loaderSource = "
            + json.dumps(loader_source)
            + ";\n"
            + r'''
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  throw new Error("Node Web Crypto is unavailable");
}
const scenario = process.argv[1];
const expectations = new Map([
  ["exact", ["bridge-report-fatal", "host-lifecycle", "task-complete"]],
  ["granular", ["bridge-report-fatal", "host-lifecycle", "leveldb-read-close"]],
  ["checkpoint", ["bridge-report-fatal", "host-lifecycle", "leveldb-write-tracker"]],
  ["environment", ["bridge-report-fatal", "host-lifecycle", "leveldb-write-env-new-writable-file"]],
  ["logger-logv", ["bridge-report-fatal", "host-lifecycle", "leveldb-write-logger-logv-first-post"]],
  ["logger-logv-suffix", ["phase-unexpected", "host-lifecycle", null]],
  ["logger-logv-unknown", ["phase-unexpected", "host-lifecycle", null]],
  ["file-exists-ordinals", ["bridge-report-fatal", "host-lifecycle", "leveldb-write-env-file-exists-later-post", false]],
  ["file-exists-second-post", ["bridge-report-fatal", "host-lifecycle", "leveldb-write-env-file-exists-second-post", false]],
  ["pre-then-second-post", ["bridge-report-fatal", "host-lifecycle", "leveldb-write-env-file-exists-second-post", true]],
  ["duplicate-pre-dbimpl", ["phase-unexpected", "host-lifecycle", "leveldb-write-pre-dbimpl-construction"]],
  ["duplicate-second-post", ["phase-unexpected", "host-lifecycle", "leveldb-write-env-file-exists-second-post", false]],
  ["pre-after-second-post", ["phase-unexpected", "host-lifecycle", "leveldb-write-env-file-exists-second-post", false]],
  ["obsolete-file-exists-pre", ["phase-unexpected", "host-lifecycle", null]],
  ["obsolete-file-exists-post", ["phase-unexpected", "host-lifecycle", null]],
  ["pre-dbimpl", ["bridge-report-fatal", "host-lifecycle", "leveldb-write-pre-dbimpl-construction"]],
  ["duplicate-complete", ["phase-unexpected", "host-lifecycle", "task-complete"]],
  ["duplicate-post", ["phase-unexpected", "host-lifecycle", "task-post"]],
  ["late-before-complete", ["bridge-report-fatal", "host-lifecycle", "leveldb-read-get"]],
  ["late-task-post", ["bridge-report-fatal", "host-lifecycle", null]],
  ["missing-complete", [null, "host-timeout", null]],
  ["missing-post", [null, "host-timeout", "task-complete"]],
  ["suffixed", ["phase-unexpected", "host-lifecycle", null]],
  ["unknown", ["phase-unexpected", "host-lifecycle", null]],
  ["stdout", ["phase-outside-stderr", "host-lifecycle", null]],
  ["logger-logv-stdout", ["phase-outside-stderr", "host-lifecycle", null]],
  ["raw", ["bridge-report-fatal", "opaque-token-leak", null]],
  ["inactive", ["phase-inactive", "host-lifecycle", null]],
]);
const expected = expectations.get(scenario);
if (!expected) throw new Error("test scenario is invalid");
const expectedPreDbImplConstructionObservedBeforeSecondFileExistsPost =
    expected.length === 4 ? expected[3] : null;
globalThis.__phaseScenario = scenario;
class FakeElement {
  constructor() {
    this.dataset = {};
    this.textContent = "";
  }
  append() {}
  replaceChildren() {}
}
class FakeCanvas extends FakeElement {
  focus() { document.activeElement = this; }
}
globalThis.HTMLElement = FakeElement;
globalThis.HTMLCanvasElement = FakeCanvas;
const root = new FakeElement();
const canvas = new FakeCanvas();
const status = new FakeElement();
const versions = new FakeElement();
globalThis.document = {
  activeElement: null,
  createElement() { return new FakeElement(); },
  querySelector(selector) {
    return new Map([
      ["#m7-profile-database-root", root],
      ["#m7-profile-database-canvas", canvas],
      ["#m7-profile-database-status", status],
      ["#m7-profile-database-versions", versions],
    ]).get(selector) ?? null;
  },
};
const eventListeners = new Map();
globalThis.addEventListener = (type, listener) => {
  const listeners = eventListeners.get(type) ?? [];
  listeners.push(listener);
  eventListeners.set(type, listeners);
};
globalThis.removeEventListener = (type, listener) => {
  eventListeners.set(type, (eventListeners.get(type) ?? []).filter(
      (candidate) => candidate !== listener));
};
globalThis.crossOriginIsolated = true;
const loaderBytes = new TextEncoder().encode(loaderSource);
const wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (value) => value.toString(16).padStart(2, "0")).join("");
}
const artifact = {
  artifact_delivery: "immutable-in-memory-server-snapshot",
  artifact_source_provenance: "unverified",
  build_config: {bytes: 1, sha256: "a".repeat(64)},
  build_config_provenance: "selected-out-dir-args-gn-immutable-snapshot",
  loader: {bytes: loaderBytes.byteLength, sha256: await digest(loaderBytes)},
  module_name: "chrome_wasm_m7_profile_database_test",
  wasm: {bytes: wasmBytes.byteLength, sha256: await digest(wasmBytes)},
};
const captureHarness = {
  host_html: {bytes: 1, sha256: "b".repeat(64)},
  host_js: {bytes: 1, sha256: "c".repeat(64)},
  runner_source: {bytes: 1, sha256: "d".repeat(64)},
  source_snapshot_provenance:
      "on-disk-byte-snapshots-at-server-startup-not-commit-provenance",
  version_provenance:
      "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance",
};
const query = new URLSearchParams({
  token: "fake-phase-loader-result-token-123456",
  module: artifact.module_name,
  timeoutMs: "1000",
  versions: JSON.stringify({
    chromium: "e".repeat(40),
    v8: "f".repeat(40),
    emscripten: "0".repeat(40),
  }),
  artifact: JSON.stringify(artifact),
  captureHarness: JSON.stringify(captureHarness),
});
globalThis.location = new URL(
    "https://m7.test/__m7_chrome_profile_database__/?" + query);
const NativeURL = URL;
globalThis.URL = class extends NativeURL {};
URL.createObjectURL = () =>
    "data:text/javascript;base64," + Buffer.from(loaderSource).toString("base64");
URL.revokeObjectURL = () => {};
let posted = null;
function artifactResponse(url, bytes, contentType) {
  return {
    ok: true,
    url,
    headers: new Headers({
      "Cache-Control": "no-store",
      "Content-Type": contentType,
      "Cross-Origin-Embedder-Policy": "require-corp",
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    }),
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
globalThis.fetch = async (url, options = {}) => {
  if (options.method === "POST") {
    posted = JSON.parse(options.body);
    return {ok: true, status: 204};
  }
  if (url.endsWith(".js")) return artifactResponse(url, loaderBytes, "text/javascript");
  if (url.endsWith(".wasm")) return artifactResponse(url, wasmBytes, "application/wasm");
  throw new Error("unexpected fetch");
};
let rejected = false;
try {
  await runChromeWasmProfileDatabaseFromQuery();
} catch {
  rejected = true;
}
if (!rejected || posted === null || posted.status !== "fail" ||
    posted.firstFatalTag !== expected[0] || posted.failureClass !== expected[1] ||
    posted.nativeDatabasePhase !== expected[2] ||
    posted.preDbImplConstructionObservedBeforeSecondFileExistsPost !==
        expectedPreDbImplConstructionObservedBeforeSecondFileExistsPost) {
  throw new Error("phase telemetry structural mismatch " + JSON.stringify({
    firstFatalTag: posted?.firstFatalTag ?? null,
    failureClass: posted?.failureClass ?? null,
    nativeDatabasePhase: posted?.nativeDatabasePhase ?? null,
    preDbImplConstructionObservedBeforeSecondFileExistsPost:
        posted?.preDbImplConstructionObservedBeforeSecondFileExistsPost ?? null,
  }));
}
validateChromeWasmProfileDatabaseFailureSummary(posted);
const serialized = JSON.stringify(posted);
const raw = globalThis.__phaseRaw;
if (serialized.includes("CHROMIUM_WASM_M7_DATABASE_PHASE:") ||
    serialized.includes("phase harness stop") ||
    (typeof raw === "string" && serialized.includes(raw)) ||
    status.textContent.includes("CHROMIUM_WASM_M7_DATABASE_PHASE:") ||
    (typeof raw === "string" && status.textContent.includes(raw))) {
  throw new Error("phase telemetry escaped structural diagnostics");
}
delete globalThis.__phaseRaw;
delete globalThis.__lifecycleFactoryCalls;
'''
        )
        for scenario in (
            "exact",
            "granular",
            "checkpoint",
            "environment",
            "logger-logv",
            "logger-logv-suffix",
            "logger-logv-unknown",
            "file-exists-ordinals",
            "file-exists-second-post",
            "pre-then-second-post",
            "duplicate-pre-dbimpl",
            "duplicate-second-post",
            "pre-after-second-post",
            "obsolete-file-exists-pre",
            "obsolete-file-exists-post",
            "pre-dbimpl",
            "duplicate-complete",
            "duplicate-post",
            "late-before-complete",
            "late-task-post",
            "missing-complete",
            "missing-post",
            "suffixed",
            "unknown",
            "stdout",
            "logger-logv-stdout",
            "raw",
            "inactive",
        ):
            with self.subTest(scenario=scenario):
                completed = subprocess.run(
                    ["node", "--input-type=module", "--eval", script, scenario],
                    capture_output=True,
                    check=False,
                    cwd=TOOLS_DIR.parents[1],
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_scope_expansion_or_missing_nonclaims(self) -> None:
        for field, value in (
            ("m7GateComplete", True),
            ("preferencesRoundTripProven", True),
            ("sqliteLevelDbCrashRecoveryProven", True),
            ("directoryDurabilityProven", True),
            ("cookiesHistoryBookmarksSessionsProven", True),
            ("webStorageAndServiceWorkerProven", True),
            ("concurrentProfileContenderProven", True),
        ):
            with self.subTest(field=field):
                result = passing_result()
                result[field] = value
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_marker_reordering_missing_close_or_wrong_digest(self) -> None:
        mutations = (
            lambda result: result["runs"][0]["markers"].reverse(),
            lambda result: result["runs"][0]["stderr"].append(
                f"{smoke.M7_DATABASE_MARKER_PREFIX}DATABASES_CLOSED "
                f"sha256={TOKEN_A_DIGEST}"
            ),
            lambda result: result["runs"][1]["markers"].__setitem__(
                4, f"{smoke.M7_DATABASE_MARKER_PREFIX}FENCE_OK sha256={TOKEN_A_DIGEST}"
            ),
            lambda result: result["runs"][2]["markers"].pop(3),
            lambda result: result["runs"][2]["stdout"].append(
                result["runs"][2]["markers"][0]
            ),
            lambda result: result["runs"][1]["stderr"].append(
                f"{smoke.M7_DATABASE_MARKER_PREFIX}FAIL stage=database"
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_private_token_and_marker_source_leaks(self) -> None:
        for mutation in (
            lambda result: result["runs"][0]["stderr"].append(
                "--wasm-profile-database-token-a=not-allowed"
            ),
            lambda result: result["runs"][2]["stdout"].append("<redacted>"),
            lambda result: result["tokenEvidence"].__setitem__(
                "rawTokenLeakDetected", True
            ),
            lambda result: result["tokenEvidence"].__setitem__(
                "rawTokenRedactionCount", 1
            ),
            lambda result: result["tokenEvidence"].__setitem__(
                "runTwo", TOKEN_A_DIGEST
            ),
        ):
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_database_phase_telemetry_in_success_evidence(self) -> None:
        phase_prefix = smoke.M7_DATABASE_PHASE_PREFIX
        raw_phase = phase_prefix + "a" * 64
        mutations = (
            lambda result: result["runs"][0]["stderr"].append(
                phase_prefix + "task-started"
            ),
            lambda result: result["runs"][1]["stderr"].append(
                phase_prefix + "leveldb-write-tracker"
            ),
            lambda result: result["runs"][2]["stderr"].append(
                phase_prefix + "leveldb-write-env-new-writable-file"
            ),
            lambda result: result["runs"][0]["stderr"].append(
                phase_prefix + "leveldb-write-env-file-exists-first-pre"
            ),
            lambda result: result["runs"][2]["stderr"].append(
                phase_prefix + "leveldb-write-env-file-exists-second-post"
            ),
            lambda result: result["runs"][0]["stderr"].append(
                phase_prefix + "leveldb-write-pre-dbimpl-construction"
            ),
            lambda result: result["runs"][1]["stderr"].append(
                phase_prefix + "leveldb-write-logger-logv-first-pre"
            ),
            lambda result: result["runs"][2]["stderr"].append(
                phase_prefix + "leveldb-write-logger-logv-first-post"
            ),
            lambda result: result["runs"][1]["stderr"].append(
                phase_prefix + "leveldb-read suffix"
            ),
            lambda result: result["runs"][2]["stderr"].append(
                phase_prefix + "unknown"
            ),
            lambda result: result["runs"][0]["stdout"].append(
                phase_prefix + "sqlite-write"
            ),
            lambda result: result["runs"][1]["stderr"].append(raw_phase),
            lambda result: result["runs"][2].__setitem__(
                "nativeDatabasePhase", "task-complete"
            ),
            lambda result: result["runs"][0].__setitem__(
                "taskCompletePhaseObserved", True
            ),
            lambda result: result["runs"][0].__setitem__(
                "taskPostPhaseObserved", True
            ),
            lambda result: result["runs"][0].__setitem__(
                "preDbImplConstructionPhaseObserved", True
            ),
            lambda result: result["runs"][0].__setitem__(
                "secondFileExistsPostPhaseObserved", True
            ),
            lambda result: result["runs"][0].__setitem__(
                "preDbImplConstructionObservedBeforeSecondFileExistsPost", True
            ),
            lambda result: result.__setitem__(
                "preDbImplConstructionObservedBeforeSecondFileExistsPost", False
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_any_missing_fresh_factory_or_module_identity(self) -> None:
        mutations = (
            lambda result: result.__setitem__("factoryCalls", 2),
            lambda result: result["runs"].pop(),
            lambda result: result["runs"][1].__setitem__(
                "sameModuleAsPrior", True
            ),
            lambda result: result["runs"][2].__setitem__(
                "moduleIdentity", result["runs"][0]["moduleIdentity"]
            ),
            lambda result: result["runs"][2].__setitem__("startKind", "initial"),
            lambda result: result["runs"][1].__setitem__(
                "postLifecycleTimerObserved", False
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_rejects_next_module_transition_or_final_quiescence_mutation(self) -> None:
        mutations = (
            lambda result: result["transition"].__setitem__(
                "runTwoScheduledAfterRunOneNativeExit", False
            ),
            lambda result: result["transition"].__setitem__(
                "runThreeScheduledAfterRunTwoOnExit", False
            ),
            lambda result: result["transition"].__setitem__(
                "runThreeScheduleMethod", "promise"
            ),
            lambda result: result["finalQuiescence"].__setitem__("quiet", False),
            lambda result: result["finalQuiescence"].__setitem__(
                "callbacksAtPreUploadCheck", 24
            ),
            lambda result: result["finalQuiescence"].__setitem__(
                "processExitReportsAtTaskEnd", 2
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = passing_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    validate(result)

    def test_accepts_or_rejects_only_fixed_failure_summary(self) -> None:
        smoke.validate_failed_host_result_summary(passing_failure_result())
        smoke.validate_failed_host_result_summary(
            passing_failure_result(native_failure_stage="database")
        )
        for phase in (
            "leveldb-write-env-file-exists-first-pre",
            "leveldb-write-env-file-exists-first-post",
            "leveldb-write-env-file-exists-second-pre",
            "leveldb-write-env-file-exists-second-post",
            "leveldb-write-env-file-exists-later-pre",
            "leveldb-write-env-file-exists-later-post",
            "leveldb-write-logger-logv-first-pre",
            "leveldb-write-logger-logv-first-post",
        ):
            with self.subTest(phase=phase):
                phase_summary = smoke.validate_failed_host_result_summary(
                    passing_failure_result(native_database_phase=phase)
                )
                self.assertEqual(phase_summary["nativeDatabasePhase"], phase)
        for phase in (
            "leveldb-write-logger-fatal-source-wasm-time",
            "leveldb-write-logger-fatal-source-time-formatting",
            "leveldb-write-logger-fatal-source-leveldb",
            "leveldb-write-logger-fatal-source-base-file",
        ):
            with self.subTest(phase=phase, mode="normal"):
                with self.assertRaises(M0Error):
                    smoke.validate_failed_host_result_summary(
                        passing_failure_result(native_database_phase=phase)
                    )
            with self.subTest(phase=phase, mode="abort-pc"):
                diagnostic_result = passing_failure_result(
                    native_database_phase=phase
                )
                diagnostic_result.update(
                    {
                        "firstFatalTag": "abort-reported",
                        "abortPc": {
                            "frame": "caller-caller",
                            "function": 42,
                            "offset": "0x1a",
                        },
                        "fatalHeadline": {
                            "family": "ambiguous",
                            "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
                        },
                        "abortReasonKind": "native-code-abort",
                        "abortObservationOrder": "before-process-exit",
                    }
                )
                phase_summary = smoke.validate_failed_host_result_summary(
                    diagnostic_result, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
                )
                self.assertEqual(phase_summary["nativeDatabasePhase"], phase)
        pre_dbimpl_phase_summary = smoke.validate_failed_host_result_summary(
            passing_failure_result(
                native_database_phase="leveldb-write-pre-dbimpl-construction"
            )
        )
        self.assertEqual(
            pre_dbimpl_phase_summary["nativeDatabasePhase"],
            "leveldb-write-pre-dbimpl-construction",
        )
        for observed in (False, True):
            with self.subTest(observed=observed):
                correlation_summary = smoke.validate_failed_host_result_summary(
                    passing_failure_result(
                        pre_dbimpl_construction_observed_before_second_file_exists_post=(
                            observed
                        )
                    )
                )
                self.assertIs(
                    correlation_summary[
                        "preDbImplConstructionObservedBeforeSecondFileExistsPost"
                    ],
                    observed,
                )
        for mutation in (
            lambda result: result.__setitem__("unexpected", "not-allowed"),
            lambda result: result.__setitem__("nativeFailureStage", "read"),
            lambda result: result.__setitem__(
                "nativeDatabasePhase",
                "leveldb-write-env-new-writable-file suffix",
            ),
            lambda result: result.__setitem__(
                "nativeDatabasePhase",
                "leveldb-write-logger-logv-first-pre-suffix",
            ),
            lambda result: result.__setitem__(
                "nativeDatabasePhase",
                "leveldb-write-logger-logv-first",
            ),
            lambda result: result.__setitem__(
                "nativeDatabasePhase", "leveldb-write-env-file-exists"
            ),
            lambda result: result.__setitem__(
                "nativeDatabasePhase",
                "leveldb-write-env-file-exists-returned",
            ),
            lambda result: result.__setitem__(
                "nativeDatabasePhase", "a" * 64
            ),
            lambda result: result.__setitem__("nativeDatabasePhase", 1),
            lambda result: result.pop("nativeDatabasePhase"),
            lambda result: result.__setitem__(
                "preDbImplConstructionObservedBeforeSecondFileExistsPost",
                "true",
            ),
            lambda result: result.__setitem__(
                "preDbImplConstructionObservedBeforeSecondFileExistsPost", 1
            ),
            lambda result: result.pop(
                "preDbImplConstructionObservedBeforeSecondFileExistsPost"
            ),
            lambda result: result.__setitem__(
                "taskCompletePhaseObserved", True
            ),
            lambda result: result.__setitem__(
                "taskPostPhaseObserved", True
            ),
            lambda result: result["lifecycle"].__setitem__("factoryCalls", 4),
            lambda result: result.__setitem__("firstFatalTag", "a" * 64),
        ):
            with self.subTest(mutation=mutation):
                result = passing_failure_result()
                mutation(result)
                with self.assertRaises(M0Error):
                    smoke.validate_failed_host_result_summary(result)

    def test_phase_failure_diagnostic_retains_only_the_fixed_enum(self) -> None:
        summary = smoke.validate_failed_host_result_summary(
            passing_failure_result(
                native_database_phase="leveldb-write-logger-logv-first-post",
                pre_dbimpl_construction_observed_before_second_file_exists_post=True,
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = smoke.write_failure_diagnostics(
                Path(temporary),
                stage="validate-failed-host-result-summary",
                error=M0Error("untrusted details are not diagnostic evidence"),
                browser_path=None,
                browser_version=None,
                browser=None,
                browser_stderr=deque(),
                page_result_received=True,
                host_failure_summary=summary,
            )
            serialized = diagnostic.read_text(encoding="utf-8")
        payload = json.loads(serialized)
        self.assertEqual(payload["host_failure_summary"], summary)
        self.assertEqual(
            payload["host_failure_summary"]["nativeDatabasePhase"],
            "leveldb-write-logger-logv-first-post",
        )
        self.assertIs(
            payload["host_failure_summary"][
                "preDbImplConstructionObservedBeforeSecondFileExistsPost"
            ],
            True,
        )
        self.assertNotIn(smoke.M7_DATABASE_PHASE_PREFIX, serialized)
        self.assertNotIn("a" * 64, serialized)

    def test_requires_explicit_database_output_configuration(self) -> None:
        smoke.validate_m7_output_configuration(
            b'import("//out/wasm-chrome-m6/args.gn")\n'
            b"enable_chromium_wasm_m7_profile_database_test = true\n"
        )
        for args_gn in (
            b"",
            b"enable_chromium_wasm_m7_profile_database_test = false\n",
            b"# enable_chromium_wasm_m7_profile_database_test = true\n",
            b"enable_chromium_wasm_m7_profile_database_test = true\n"
            b"enable_chromium_wasm_m7_profile_database_test = false\n",
        ):
            with self.subTest(args_gn=args_gn):
                with self.assertRaises(M0Error):
                    smoke.validate_m7_output_configuration(args_gn)

    def test_server_snapshots_database_host_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.js").write_bytes(b"loader")
            (out_dir / f"{smoke.PRODUCT_MODULE_NAME}.wasm").write_bytes(
                b"\x00asm-database"
            )
            (out_dir / "args.gn").write_text(
                "enable_chromium_wasm_m7_profile_database_test = true\n",
                encoding="utf-8",
            )
            (host_dir / "chrome_wasm_profile_database_smoke.html").write_bytes(
                b"<main>database test</main>"
            )
            (host_dir / "chrome_wasm_profile_database_smoke.js").write_bytes(
                b"export {}"
            )
            result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            token = "result-token-for-m7-database-123456"
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                token,
                result_queue,
                host_dir=host_dir,
                runner_source_path=Path(__file__),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                smoke.verify_server_delivery(server)
                identity = smoke.artifact_identity(
                    server, module_name=smoke.PRODUCT_MODULE_NAME
                )
                self.assertEqual(
                    identity["build_config"]["sha256"],
                    hashlib.sha256((out_dir / "args.gn").read_bytes()).hexdigest(),
                )
                connection = http.client.HTTPConnection(*server.server_address)
                try:
                    payload = json.dumps(
                        {
                            "protocol": 1,
                            "case": smoke.CASE,
                            "scope": smoke.SCOPE,
                        }
                    ).encode("utf-8")
                    path = f"{smoke.HOST_ROOT}/result/{token}"
                    connection.request(
                        "POST",
                        path,
                        body=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(connection.getresponse().status, 204)
                    connection.request(
                        "POST",
                        path,
                        body=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(connection.getresponse().status, 409)
                finally:
                    connection.close()
                self.assertEqual(result_queue.get_nowait()["case"], smoke.CASE)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())

    def test_host_and_runner_bind_the_frozen_database_protocol(self) -> None:
        host = source("tools/wasm/host/chrome_wasm_profile_database_smoke.js")
        runner = source("tools/wasm/run_m7_chrome_profile_database_dom_smoke.py")
        html = source("tools/wasm/host/chrome_wasm_profile_database_smoke.html")

        self.assertIn('const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:";', host)
        self.assertIn(
            'const M7_DATABASE_PHASE_PREFIX = '
            '"CHROMIUM_WASM_M7_DATABASE_PHASE:";',
            host,
        )
        self.assertIn(
            'M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:"',
            runner,
        )
        self.assertIn('const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_test";', host)
        self.assertIn('\"--wasm-profile-database-smoke=write-a\"', host)
        self.assertIn('\"--wasm-profile-database-smoke=verify-a-write-b\"', host)
        self.assertIn('\"--wasm-profile-database-smoke=verify-b\"', host)
        self.assertIn("SQLITE_WRITE_ACCEPTED", host)
        self.assertIn("LEVELDB_WRITE_ACCEPTED", host)
        self.assertIn("SQLITE_READ_A_OK", host)
        self.assertIn("LEVELDB_READ_A_OK", host)
        self.assertIn("SQLITE_READ_B_OK", host)
        self.assertIn("LEVELDB_READ_B_OK", host)
        self.assertIn("DATABASES_CLOSED", host)
        self.assertIn("FENCE_OK", host)
        self.assertIn("LEASE_RELEASED", host)
        for phase in (
            "task-post",
            "task-started",
            "sqlite-write",
            "sqlite-read",
            "leveldb-write",
            "leveldb-write-open",
            "leveldb-write-pre-dbimpl-construction",
            "leveldb-write-put",
            "leveldb-write-compact",
            "leveldb-write-close",
            "leveldb-write-tracker",
            "leveldb-write-env-file-exists-first-pre",
            "leveldb-write-env-file-exists-first-post",
            "leveldb-write-env-file-exists-second-pre",
            "leveldb-write-env-file-exists-second-post",
            "leveldb-write-env-file-exists-later-pre",
            "leveldb-write-env-file-exists-later-post",
            "leveldb-write-env-create-dir",
            "leveldb-write-env-rename-file",
            "leveldb-write-env-new-logger",
            "leveldb-write-logger-logv-first-pre",
            "leveldb-write-logger-logv-first-post",
            "leveldb-write-logger-fatal-source-wasm-time",
            "leveldb-write-logger-fatal-source-time-formatting",
            "leveldb-write-logger-fatal-source-leveldb",
            "leveldb-write-logger-fatal-source-base-file",
            "leveldb-write-env-lock-file",
            "leveldb-write-env-new-writable-file",
            "leveldb-read",
            "leveldb-read-open",
            "leveldb-read-get",
            "leveldb-read-close",
            "task-complete",
        ):
            with self.subTest(phase=phase):
                self.assertIn(f'"{phase}"', host)
                self.assertIn(f'"{phase}"', runner)
        self.assertIn("#scheduleNextRun(previousRun)", host)
        self.assertIn("#schedulePostLifecycleQuiescence(runThree)", host)
        self.assertIn("this.#runs.length === 3", host)
        self.assertIn("this.#runs.length !== 3", host)
        self.assertIn("processExitDispatchesAtPreUploadCheck === 3", host)
        self.assertIn("URL.createObjectURL(blob)", host)
        self.assertIn("wasmBinary: this.#wasmBinary", host)
        self.assertIn('if (typeof value !== "string")', host)
        self.assertIn('return "<suppressed-nonstring>";', host)
        self.assertNotIn("const text = String(value);", host)
        self.assertIn(
            "FENCE_OK follows DATABASES_CLOSED as lifecycle sequencing evidence only.",
            host,
        )
        self.assertIn(
            "FENCE_OK follows DATABASES_CLOSED as lifecycle sequencing evidence only.",
            runner,
        )
        self.assertIn(
            "profile database smoke failed; details suppressed", html
        )
        self.assertNotIn("String(error", html)
        self.assertNotIn("String(reason", html)
        capture_output = host[
            host.index("  #captureOutput(run, destination, line)") : host.index(
                "\n  #markersComplete(run)",
            )
        ]
        self.assertIn("if (containsNativeDatabasePhase)", capture_output)
        self.assertIn("FATAL_TAG.PHASE_OUTSIDE_STDERR", capture_output)
        self.assertIn("FATAL_TAG.PHASE_INACTIVE", capture_output)
        self.assertIn("FATAL_TAG.PHASE_UNEXPECTED", capture_output)
        self.assertIn("taskPostPhaseObserved: false", host)
        self.assertIn("taskCompletePhaseObserved: false", host)
        self.assertIn("preDbImplConstructionPhaseObserved: false", host)
        self.assertIn("secondFileExistsPostPhaseObserved: false", host)
        self.assertIn(
            "preDbImplConstructionObservedBeforeSecondFileExistsPost: null",
            host,
        )
        self.assertIn("if (run.taskPostPhaseObserved)", capture_output)
        self.assertIn("if (run.taskCompletePhaseObserved)", capture_output)
        self.assertIn("run.taskPostPhaseObserved = true", capture_output)
        self.assertIn("run.taskCompletePhaseObserved = true", capture_output)
        self.assertIn("if (run.preDbImplConstructionPhaseObserved)", capture_output)
        self.assertIn("if (run.secondFileExistsPostPhaseObserved)", capture_output)
        self.assertIn("run.preDbImplConstructionPhaseObserved = true", capture_output)
        self.assertIn("run.secondFileExistsPostPhaseObserved = true", capture_output)
        self.assertIn(
            "run.preDbImplConstructionObservedBeforeSecondFileExistsPost =",
            capture_output,
        )
        self.assertIn("run.nativeDatabasePhase = nativeDatabasePhase", capture_output)
        clean_completion = host[
            host.index("  #runIsCleanlyComplete(run)") : host.index(
                "\n  #maybeCompleteRun(run)",
            )
        ]
        self.assertIn("run.taskPostPhaseObserved === true", clean_completion)
        self.assertIn("run.taskCompletePhaseObserved === true", clean_completion)
        failure_summary = host[
            host.index("  failureSummary(failureClass = null)") : host.index(
                "\n  #result(status, error)",
            )
        ]
        self.assertIn(
            "nativeDatabasePhase: latestRun?.nativeDatabasePhase ?? null",
            failure_summary,
        )
        self.assertIn(
            "preDbImplConstructionObservedBeforeSecondFileExistsPost:",
            failure_summary,
        )
        run_snapshot = host[
            host.index("  #runSnapshot(run)") : host.index(
                "\n  #bridgeSnapshot()",
            )
        ]
        self.assertNotIn("nativeDatabasePhase", run_snapshot)
        self.assertNotIn(
            "preDbImplConstructionObservedBeforeSecondFileExistsPost",
            run_snapshot,
        )
        self.assertNotIn("preDbImplConstructionPhaseObserved", run_snapshot)
        self.assertNotIn("secondFileExistsPostPhaseObserved", run_snapshot)
        self.assertNotIn("taskPostPhaseObserved", run_snapshot)
        self.assertNotIn("taskCompletePhaseObserved", run_snapshot)
        self.assertNotIn("taskPostPhaseObserved", failure_summary)
        self.assertNotIn("taskCompletePhaseObserved", failure_summary)
        self.assertNotIn("preDbImplConstructionPhaseObserved", failure_summary)
        self.assertNotIn("secondFileExistsPostPhaseObserved", failure_summary)
        self.assertNotIn("taskPostPhaseObserved", runner)
        self.assertNotIn("taskCompletePhaseObserved", runner)
        for forbidden in (
            "navigator.storage",
            "navigator.locks",
            ".ccall(",
            "getDirectory",
            "HEAPU8",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host)

        self.assertIn("snapshot_regular_files", runner)
        self.assertIn("snapshot_regular_file", runner)
        self.assertIn("verify_server_delivery(server)", runner)
        self.assertIn("validate_m7_output_configuration", runner)
        self.assertIn(
            "enable_chromium_wasm_m7_profile_database_test=true", runner
        )
        self.assertIn("out/wasm-chrome-m7-profile-database", runner)
        self.assertIn("chrome_wasm_profile_database_smoke.js", runner)
        self.assertIn("processExitDispatches\": 3", runner)
        self.assertIn("native_database_phase = result.get(\"nativeDatabasePhase\")", runner)
        self.assertIn('"nativeDatabasePhase": native_database_phase', runner)
        self.assertIn(
            "pre_dbimpl_construction_observed_before_second_file_exists_post =",
            runner,
        )
        self.assertIn(
            '"preDbImplConstructionObservedBeforeSecondFileExistsPost": (',
            runner,
        )
        self.assertIn("chrome_wasm_profile_database_smoke.js", html)

    def test_exit_status_classifier_and_failure_summary_remain_structural(self) -> None:
        script = r'''
import {
  isExactNormalEmscriptenExitStatus,
  validateChromeWasmProfileDatabaseFailureSummary,
} from "./tools/wasm/host/chrome_wasm_profile_database_smoke.js";

const exact = {
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
};
if (!isExactNormalEmscriptenExitStatus(exact) ||
    isExactNormalEmscriptenExitStatus({...exact, status: 1}) ||
    isExactNormalEmscriptenExitStatus("Program terminated with exit(0)")) {
  throw new Error("ExitStatus classifier accepted an invalid value");
}
const validFailureSummary = {
  protocol: 1,
  case: "chrome_profile_database_three_fresh_modules_m7",
  scope: "same-origin-same-document-three-fresh-chrome-wasm-m7-profile-database-test-modules-graceful-close-reopen-only",
  status: "fail",
  failureClass: "native-fixed-failure",
  firstFatalTag: "marker-native-failure",
  abortPc: null,
  fatalHeadline: null,
  abortReasonKind: null,
  abortObservationOrder: null,
  nativeFailureStage: "database",
  nativeDatabasePhase: "leveldb-write-env-file-exists-second-post",
  preDbImplConstructionObservedBeforeSecondFileExistsPost: false,
  lifecycle: {
    acceptedProcessExitCount: 1,
    activeRunPresent: true,
    bridgeInstalled: true,
    bridgeInstalledBeforeModuleFactory: true,
    callbackCount: 12,
    factoryCalls: 1,
    finalQuiescenceCompleted: false,
    lastProcessExitCode: 1,
    lastRuntimeExitCode: null,
    leaseReleasedRunCount: 0,
    onExitCount: 0,
    processExitReportCount: 1,
    rawTokenLeakDetected: false,
    runCount: 1,
    unhandledRejectionObserved: false,
    windowErrorObserved: false,
  },
};
validateChromeWasmProfileDatabaseFailureSummary(validFailureSummary);
for (const phase of [
  "leveldb-write-logger-logv-first-pre",
  "leveldb-write-logger-logv-first-post",
  "leveldb-write-logger-fatal-source-wasm-time",
  "leveldb-write-logger-fatal-source-time-formatting",
  "leveldb-write-logger-fatal-source-leveldb",
  "leveldb-write-logger-fatal-source-base-file",
]) {
  const candidate = JSON.parse(JSON.stringify(validFailureSummary));
  candidate.nativeDatabasePhase = phase;
  validateChromeWasmProfileDatabaseFailureSummary(candidate);
}
for (const mutate of [
  (summary) => {
    summary.nativeDatabasePhase = "leveldb-write-logger-logv-first-pre-suffix";
  },
  (summary) => {
    summary.nativeDatabasePhase = "leveldb-write-logger-logv-first-post-suffix";
  },
  (summary) => {
    summary.nativeDatabasePhase = "leveldb-write-logger-logv-first";
  },
  (summary) => {
    summary.preDbImplConstructionObservedBeforeSecondFileExistsPost = "false";
  },
  (summary) => {
    summary.preDbImplConstructionObservedBeforeSecondFileExistsPost = 0;
  },
  (summary) => {
    delete summary.preDbImplConstructionObservedBeforeSecondFileExistsPost;
  },
]) {
  const candidate = JSON.parse(JSON.stringify(validFailureSummary));
  mutate(candidate);
  let rejected = false;
  try {
    validateChromeWasmProfileDatabaseFailureSummary(candidate);
  } catch {
    rejected = true;
  }
  if (!rejected) {
    throw new Error("failure summary accepted an invalid fixed boolean");
  }
}
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()

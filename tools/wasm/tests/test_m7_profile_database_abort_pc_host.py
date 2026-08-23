#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Host and runner contracts for the opt-in M7 abort-PC diagnostic."""

from __future__ import annotations

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


_DEFAULT_FATAL_HEADLINE = object()


def _failure_result(
    abort_pc: object, *, fatal_headline: object = _DEFAULT_FATAL_HEADLINE
) -> dict[str, object]:
    if fatal_headline is _DEFAULT_FATAL_HEADLINE:
        fatal_headline = {
            "family": "ambiguous",
            "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
        }
    return {
        "protocol": 1,
        "case": smoke.CASE,
        "scope": smoke.SCOPE,
        "status": "fail",
        "failureClass": "host-lifecycle",
        "firstFatalTag": "abort-reported",
        "abortPc": abort_pc,
        "fatalHeadline": fatal_headline,
        "abortReasonKind": "native-code-abort",
        "abortObservationOrder": "before-process-exit",
        "nativeFailureStage": None,
        "nativeDatabasePhase": None,
        "preDbImplConstructionObservedBeforeSecondFileExistsPost": None,
        "lifecycle": {
            "acceptedProcessExitCount": 0,
            "activeRunPresent": True,
            "bridgeInstalled": True,
            "bridgeInstalledBeforeModuleFactory": True,
            "callbackCount": 2,
            "factoryCalls": 1,
            "finalQuiescenceCompleted": False,
            "lastProcessExitCode": None,
            "lastRuntimeExitCode": None,
            "leaseReleasedRunCount": 0,
            "onExitCount": 0,
            "processExitReportCount": 0,
            "rawTokenLeakDetected": False,
            "runCount": 1,
            "unhandledRejectionObserved": False,
            "windowErrorObserved": False,
        },
    }


class M7ProfileDatabaseAbortPcHostTest(unittest.TestCase):
    def test_mode_selects_exact_module_and_output_configuration(self) -> None:
        self.assertEqual(
            smoke._module_name_for_diagnostic_mode(smoke.DIAGNOSTIC_MODE_NORMAL),
            smoke.PRODUCT_MODULE_NAME,
        )
        self.assertEqual(
            smoke._module_name_for_diagnostic_mode(smoke.DIAGNOSTIC_MODE_ABORT_PC),
            smoke.ABORT_PC_DIAGNOSTIC_MODULE_NAME,
        )
        self.assertEqual(
            smoke._out_dir_for_diagnostic_mode(smoke.DIAGNOSTIC_MODE_ABORT_PC),
            smoke.DEFAULT_ABORT_PC_DIAGNOSTIC_OUT_DIR,
        )
        with self.assertRaises(M0Error):
            smoke._require_product_module_name(
                smoke.PRODUCT_MODULE_NAME,
                "test",
                diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
            )
        with self.assertRaises(M0Error):
            smoke._require_product_module_name(
                smoke.ABORT_PC_DIAGNOSTIC_MODULE_NAME,
                "test",
                diagnostic_mode=smoke.DIAGNOSTIC_MODE_NORMAL,
            )

        diagnostic_args = (
            b"enable_chromium_wasm_m7_profile_database_test=true\n"
            b"enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=true\n"
        )
        smoke.validate_m7_output_configuration(
            diagnostic_args, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
        )
        with self.assertRaises(M0Error):
            smoke.validate_m7_output_configuration(
                diagnostic_args, diagnostic_mode=smoke.DIAGNOSTIC_MODE_NORMAL
            )

    def test_runner_snapshots_but_never_serves_symbol_sidecar(self) -> None:
        module_name = smoke.ABORT_PC_DIAGNOSTIC_MODULE_NAME
        sidecar_name = f"{module_name}.js.symbols"
        self.assertEqual(smoke.ABORT_PC_SYMBOL_SUFFIX, ".js.symbols")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out_dir = root / "out"
            host_dir = root / "host"
            out_dir.mkdir()
            host_dir.mkdir()
            loader = b"export default function() { return {}; }\n"
            wasm = b"\0asm\x01\0\0\0"
            symbols = b"raw-symbol-sidecar-must-never-be-served\n"
            (out_dir / f"{module_name}.js").write_bytes(loader)
            (out_dir / f"{module_name}.wasm").write_bytes(wasm)
            (out_dir / sidecar_name).write_bytes(symbols)
            (out_dir / "args.gn").write_text(
                "enable_chromium_wasm_m7_profile_database_test=true\n"
                "enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic=true\n",
                encoding="utf-8",
            )
            (host_dir / "chrome_wasm_profile_database_smoke.html").write_text(
                "<!doctype html>\n", encoding="utf-8"
            )
            (host_dir / "chrome_wasm_profile_database_smoke.js").write_text(
                "export {};\n", encoding="utf-8"
            )
            server = smoke.create_server(
                "127.0.0.1",
                0,
                out_dir,
                "abort-pc-result-token-123456",
                queue.Queue(maxsize=1),
                module_name=module_name,
                diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
                host_dir=host_dir,
                runner_source_path=Path(smoke.__file__),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                provenance = smoke.abort_pc_diagnostic_provenance(
                    server, module_name=module_name
                )
                self.assertEqual(provenance["mode"], smoke.DIAGNOSTIC_MODE_ABORT_PC)
                self.assertEqual(
                    provenance["mapping"],
                    "deferred-caller-caller-frame-no-raw-symbol-sidecar-served",
                )
                self.assertEqual(
                    provenance["symbols"],
                    {
                        "bytes": len(symbols),
                        "sha256": hashlib.sha256(symbols).hexdigest(),
                    },
                )
                self.assertNotIn(
                    sidecar_name,
                    server.artifacts,
                )
                host, port = server.server_address[:2]
                connection = http.client.HTTPConnection(host, port, timeout=10)
                try:
                    connection.request(
                        "GET",
                        f"{smoke.HOST_ROOT}/artifacts/"
                        + sidecar_name,
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 404)
                    self.assertNotIn(symbols, response.read())
                finally:
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())

    def test_failure_summary_retains_only_bounded_abort_pc_and_headline(self) -> None:
        caller_caller_observation = {
            "frame": "caller-caller",
            "function": 4294967295,
            "offset": "0xdeadbeef",
        }
        summary = smoke.validate_failed_host_result_summary(
            _failure_result(caller_caller_observation),
            diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
        )
        self.assertEqual(summary["abortPc"], caller_caller_observation)
        self.assertEqual(
            summary["fatalHeadline"],
            {
                "family": "ambiguous",
                "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
            },
        )
        self.assertIsNone(
            smoke.validate_failed_host_result_summary(
                _failure_result(None), diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
            )["abortPc"]
        )
        after_abort = _failure_result(
            {"frame": "caller-caller", "function": 1, "offset": "0x1"}
        )
        after_abort["abortReasonKind"] = None
        after_abort["abortObservationOrder"] = None
        with self.assertRaises(M0Error):
            smoke.validate_failed_host_result_summary(
                after_abort, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
            )
        for abort_pc in (
            {"frame": "caller-caller", "function": 4294967296, "offset": "0x1"},
            {"frame": "caller-caller", "function": -1, "offset": "0x1"},
            {"frame": "caller-caller", "function": 1, "offset": "0x0001"},
            {"frame": "caller-caller", "function": 1, "offset": "0x1A"},
            {"frame": "caller-caller", "function": 1, "offset": "0x100000000"},
            {"frame": "caller-caller", "function": "1", "offset": "0x1"},
            {"frame": "caller-caller", "function": 1},
            {"frame": "caller", "function": 1, "offset": "0x1"},
            {"frame": "caller-caller-caller", "function": 1, "offset": "0x1"},
            {"frame": "callee", "function": 1, "offset": "0x1"},
            {"frame": "top", "function": 1, "offset": "0x1"},
            {"function": 1, "offset": "0x1"},
            "raw-abort-pc",
        ):
            with self.subTest(abort_pc=abort_pc):
                with self.assertRaises(M0Error):
                    smoke.validate_failed_host_result_summary(
                        _failure_result(abort_pc),
                        diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
                    )
        with self.assertRaises(M0Error):
            smoke.validate_failed_host_result_summary(
                _failure_result(
                    {"frame": "caller-caller", "function": 1, "offset": "0x1"}
                )
            )

        normal_summary = smoke.validate_failed_host_result_summary(
            _failure_result(None, fatal_headline=None),
            diagnostic_mode=smoke.DIAGNOSTIC_MODE_NORMAL,
        )
        self.assertIsNone(normal_summary["fatalHeadline"])
        for headline in (
            {"family": "unknown", "provenance": smoke.FATAL_HEADLINE_PROVENANCE},
            {"family": "wasm-time", "provenance": "untrusted"},
            {"family": "wasm-time"},
            {"family": "wasm-time", "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
             "raw": "../../base/time/time_wasm.cc:44: Check failed: raw"},
            "../../base/time/time_wasm.cc:44: Check failed: raw",
        ):
            with self.subTest(headline=headline):
                with self.assertRaises(M0Error):
                    smoke.validate_failed_host_result_summary(
                        _failure_result(caller_caller_observation, fatal_headline=headline),
                        diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
                    )
        for family in ("wasm-time", "time-formatting", "leveldb", "base-file",
                       "ambiguous"):
            with self.subTest(family=family):
                self.assertEqual(
                    smoke.validate_failed_host_result_summary(
                        _failure_result(
                            caller_caller_observation,
                            fatal_headline={
                                "family": family,
                                "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
                            },
                        ),
                        diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
                    )["fatalHeadline"]["family"],
                    family,
                )
        for family in ("base-logging", "other-fatal"):
            with self.subTest(reserved_family=family):
                with self.assertRaises(M0Error):
                    smoke.validate_failed_host_result_summary(
                        _failure_result(
                            caller_caller_observation,
                            fatal_headline={
                                "family": family,
                                "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
                            },
                        ),
                        diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
                    )
        with self.assertRaises(M0Error):
            smoke.validate_failed_host_result_summary(
                _failure_result(
                    None,
                    fatal_headline={
                        "family": "ambiguous",
                        "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
                    },
                ),
                diagnostic_mode=smoke.DIAGNOSTIC_MODE_NORMAL,
            )
        for field, value in (
            ("abortReasonKind", "assertion-prefix"),
            ("abortObservationOrder", "after-process-exit-before-onexit"),
        ):
            forged = _failure_result(caller_caller_observation)
            forged[field] = value
            with self.subTest(forged_field=field):
                with self.assertRaises(M0Error):
                    smoke.validate_failed_host_result_summary(
                        forged, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
                    )

    def test_abort_pc_diagnostic_explicitly_rejects_clean_pass_status(self) -> None:
        with self.assertRaises(M0Error):
            smoke.reject_diagnostic_clean_result(
                {"status": "pass"}, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
            )
        smoke.reject_diagnostic_clean_result(
            {"status": "fail"}, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
        )
        smoke.reject_diagnostic_clean_result(
            {"status": "pass"}, diagnostic_mode=smoke.DIAGNOSTIC_MODE_NORMAL
        )

    def test_failure_diagnostics_preserve_only_trusted_abort_pc_hashes(self) -> None:
        provenance = {
            "mode": smoke.DIAGNOSTIC_MODE_ABORT_PC,
            "mapping": "deferred-caller-caller-frame-no-raw-symbol-sidecar-served",
            "artifact": {
                "loader": {"bytes": 11, "sha256": "a" * 64},
                "wasm": {"bytes": 12, "sha256": "b" * 64},
            },
            "args_gn": {"bytes": 13, "sha256": "c" * 64},
            "symbols": {"bytes": 14, "sha256": "d" * 64},
        }
        summary = smoke.validate_failed_host_result_summary(
            _failure_result(
                {"frame": "caller-caller", "function": 7, "offset": "0x42"},
                fatal_headline={
                    "family": "wasm-time",
                    "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
                },
            ),
            diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC,
        )
        browser_path = Path("/private/m7-abort-pc-browser-path-must-not-leak")
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = smoke.write_failure_diagnostics(
                Path(temporary),
                stage="test",
                error=M0Error("untrusted-error-" + "e" * 64),
                browser_path=browser_path,
                browser_version="untrusted-browser-version-" + "e" * 64,
                browser=None,
                browser_stderr=deque(),
                page_result_received=True,
                host_failure_summary=summary,
                abort_pc_diagnostic_provenance=provenance,
            )
            document = json.loads(diagnostic.read_text(encoding="utf-8"))
        self.assertEqual(
            document["abort_pc_diagnostic"],
            {
                **provenance,
                "observation": {
                    "frame": "caller-caller",
                    "function": 7,
                    "offset": "0x42",
                },
                "fatal_headline": {
                    "family": "wasm-time",
                    "provenance": smoke.FATAL_HEADLINE_PROVENANCE,
                },
            },
        )
        self.assertEqual(
            document["host_browser"]["version"],
            "untrusted-browser-version-<redacted>",
        )
        self.assertTrue(document["host_browser"]["path_provided"])
        self.assertNotIn("path", document["host_browser"])
        serialized = json.dumps(document, sort_keys=True)
        self.assertNotIn(str(browser_path), serialized)
        self.assertNotIn("e" * 64, serialized)

    def test_host_rejects_diagnostic_module_mismatch(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "chrome_wasm_profile_database_smoke.js"
        ).as_uri()
        script = (
            "import {runChromeWasmProfileDatabaseFromQuery} from "
            + json.dumps(host_uri)
            + r''';
globalThis.location = new URL(
    "https://m7.test/__m7_chrome_profile_database__/?" +
    new URLSearchParams({
      token: "fake-abort-pc-result-token-123456",
      module: "chrome_wasm_m7_profile_database_test",
      timeoutMs: "1000",
      diagnosticMode: "abort-pc",
    }));
let rejected = false;
try {
  await runChromeWasmProfileDatabaseFromQuery();
} catch {
  rejected = true;
}
if (!rejected) throw new Error("diagnostic module mismatch was accepted");
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

    def test_fake_loader_strictly_accepts_only_abort_pc_before_on_abort(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "chrome_wasm_profile_database_smoke.js"
        ).as_uri()
        loader_source = r'''
export default async function(options) {
  const scenario = globalThis.__abortPcScenario;
  const pcPrefix = "CHROMIUM_WASM_M7_ABORT_PC:";
  const marker = pcPrefix + "frame=caller-caller;function=42;offset=0x1a";
  const module = {};
  globalThis.__abortPcFactoryCalls =
      (globalThis.__abortPcFactoryCalls ?? 0) + 1;
  if (scenario === "inactive" && globalThis.__abortPcFactoryCalls > 1) {
    return new Promise(() => {});
  }
  options.onRuntimeInitialized.call(module);
  if (scenario === "inactive") {
    const raw = options.arguments.find((argument) =>
        argument.startsWith("--wasm-profile-database-token-a=")).split("=")[1];
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
    const hex = Array.from(new Uint8Array(digest),
        (value) => value.toString(16).padStart(2, "0")).join("");
    const databasePrefix = "CHROMIUM_WASM_M7_DATABASE:";
    const phasePrefix = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
    for (const line of [
      databasePrefix + "READY",
      databasePrefix + "SQLITE_WRITE_ACCEPTED sha256=" + hex,
      databasePrefix + "LEVELDB_WRITE_ACCEPTED sha256=" + hex,
      databasePrefix + "DATABASES_CLOSED sha256=" + hex,
      databasePrefix + "FENCE_OK sha256=" + hex,
      databasePrefix + "LEASE_RELEASED",
    ]) options.printErr(line);
    globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({
      protocol: 1,
      exitCode: 0,
    });
    options.onExit(0);
    options.printErr(phasePrefix + "task-post");
    options.printErr(phasePrefix + "task-complete");
    setTimeout(() => setTimeout(() => options.printErr(marker), 0), 0);
    return module;
  }
  if (scenario === "after-abort") {
    options.printErr(marker);
    options.onAbort("native code called abort()");
    options.printErr(marker);
    return module;
  }
  if (scenario === "normal-active") {
    options.printErr(marker);
  } else if (scenario === "unavailable") {
    options.printErr(pcPrefix + "unavailable");
  } else if (scenario === "duplicate") {
    options.printErr(marker);
    options.printErr(marker);
  } else if (scenario === "stdout") {
    options.print(marker);
  } else if (scenario === "suffix") {
    options.printErr(marker + "-suffix");
  } else if (scenario === "raw") {
    options.printErr(pcPrefix + "frame=caller-caller;function=raw;offset=0x1");
  } else if (scenario === "offset-nine") {
    options.printErr(pcPrefix + "frame=caller-caller;function=42;offset=0x100000000");
  } else if (scenario === "leading-zero") {
    options.printErr(pcPrefix + "frame=caller-caller;function=042;offset=0x1");
  } else if (scenario === "prior-caller-frame") {
    options.printErr(pcPrefix + "frame=caller;function=42;offset=0x1a");
  } else if (scenario === "wrong-depth") {
    options.printErr(pcPrefix + "frame=caller-caller-caller;function=42;offset=0x1a");
  } else if (scenario === "legacy-top-frame") {
    options.printErr(pcPrefix + "function=42;offset=0x1a");
  } else if (scenario === "wrong-frame") {
    options.printErr(pcPrefix + "frame=callee;function=42;offset=0x1a");
  } else if (scenario === "missing") {
    // onAbort below intentionally has no preceding marker.
  } else if (scenario !== "valid") {
    throw new Error("unknown abort-PC scenario");
  } else {
    options.printErr(marker);
  }
  options.onAbort("native code called abort()");
  return module;
}
'''
        script = (
            "import {validateChromeWasmProfileDatabaseFailureSummary, "
            "runChromeWasmProfileDatabaseFromQuery} from "
            + json.dumps(host_uri)
            + ";\nconst loaderSource = "
            + json.dumps(loader_source)
            + r''';
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  throw new Error("Node Web Crypto is unavailable");
}
const scenario = process.argv[1];
const normalMode = scenario === "inactive" || scenario === "normal-active";
const receiptViolations = new Set([
  "duplicate",
  "stdout",
  "suffix",
  "raw",
  "offset-nine",
  "leading-zero",
  "legacy-top-frame",
  "prior-caller-frame",
  "wrong-depth",
  "wrong-frame",
  "missing",
  "after-abort",
]);
const moduleName = normalMode ? "chrome_wasm_m7_profile_database_test" :
    "chrome_wasm_m7_profile_database_abort_pc_diagnostic";
const diagnosticMode = normalMode ? "normal" : "abort-pc";
const expected = new Map([
  ["valid", ["abort-reported", {frame: "caller-caller", function: 42, offset: "0x1a"}]],
  ["unavailable", ["abort-reported", null]],
  ["duplicate", ["abort-pc-duplicate", {frame: "caller-caller", function: 42, offset: "0x1a"}]],
  ["stdout", ["abort-pc-outside-stderr", null]],
  ["suffix", ["abort-pc-invalid", null]],
  ["raw", ["abort-pc-invalid", null]],
  ["offset-nine", ["abort-pc-invalid", null]],
  ["leading-zero", ["abort-pc-invalid", null]],
  ["legacy-top-frame", ["abort-pc-invalid", null]],
  ["prior-caller-frame", ["abort-pc-invalid", null]],
  ["wrong-depth", ["abort-pc-invalid", null]],
  ["wrong-frame", ["abort-pc-invalid", null]],
  ["missing", ["abort-pc-missing-before-abort", null]],
  ["inactive", ["abort-pc-inactive", null]],
  ["after-abort", ["abort-reported", {frame: "caller-caller", function: 42, offset: "0x1a"}]],
  ["normal-active", ["abort-pc-unexpected", null]],
]).get(scenario);
if (!expected) throw new Error("test scenario is invalid");
class FakeElement {
  constructor() { this.dataset = {}; this.textContent = ""; }
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
const listeners = new Map();
globalThis.addEventListener = (type, listener) => {
  const values = listeners.get(type) ?? [];
  values.push(listener);
  listeners.set(type, values);
};
globalThis.removeEventListener = (type, listener) => {
  listeners.set(type, (listeners.get(type) ?? []).filter(
      (candidate) => candidate !== listener));
};
globalThis.crossOriginIsolated = true;
globalThis.__abortPcScenario = scenario;
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
  module_name: moduleName,
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
  token: "fake-abort-pc-result-token-123456",
  module: moduleName,
  timeoutMs: "1000",
  diagnosticMode,
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
    posted.firstFatalTag !== expected[0] ||
    JSON.stringify(posted.abortPc) !== JSON.stringify(expected[1])) {
  throw new Error("abort-PC fake loader result mismatch");
}
if (scenario === "after-abort" &&
    (posted.abortReasonKind !== null || posted.abortObservationOrder !== null)) {
  throw new Error("post-abort marker retained a valid diagnostic receipt");
}
if (receiptViolations.has(scenario) &&
    (posted.abortReasonKind !== null || posted.abortObservationOrder !== null)) {
  throw new Error("invalid abort-PC receipt retained abort observation fields");
}
validateChromeWasmProfileDatabaseFailureSummary(posted);
const serialized = JSON.stringify(posted);
if (serialized.includes("CHROMIUM_WASM_M7_ABORT_PC:") ||
    serialized.includes("function=raw") ||
    status.textContent.includes("CHROMIUM_WASM_M7_ABORT_PC:")) {
  throw new Error("raw abort-PC marker escaped the failure summary");
}
delete globalThis.__abortPcScenario;
delete globalThis.__abortPcFactoryCalls;
process.stdout.write(JSON.stringify(posted));
'''
        )
        receipt_violations = frozenset(
            (
                "duplicate",
                "stdout",
                "suffix",
                "raw",
                "offset-nine",
                "leading-zero",
                "legacy-top-frame",
                "prior-caller-frame",
                "wrong-depth",
                "wrong-frame",
                "missing",
                "after-abort",
            )
        )
        for scenario in (
            "valid",
            "unavailable",
            "duplicate",
            "stdout",
            "suffix",
            "raw",
            "offset-nine",
            "leading-zero",
            "legacy-top-frame",
            "prior-caller-frame",
            "wrong-depth",
            "wrong-frame",
            "missing",
            "inactive",
            "after-abort",
            "normal-active",
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
                if scenario in receipt_violations:
                    result = json.loads(completed.stdout)
                    self.assertIsNone(result["abortReasonKind"])
                    self.assertIsNone(result["abortObservationOrder"])
                    with self.assertRaises(M0Error):
                        smoke.validate_failed_host_result_summary(
                            result, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
                        )

    def test_fake_loader_classifies_only_fixed_fatal_headlines(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "chrome_wasm_profile_database_smoke.js"
        ).as_uri()
        loader_source = r'''
export default async function(options) {
  const scenario = globalThis.__fatalHeadlineScenario;
  const pcPrefix = "CHROMIUM_WASM_M7_ABORT_PC:";
  const phasePrefix = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
  const marker = pcPrefix + "frame=caller-caller;function=42;offset=0x1a";
  const unavailable = pcPrefix + "unavailable";
  const pre = phasePrefix + "leveldb-write-logger-logv-first-pre";
  const post = phasePrefix + "leveldb-write-logger-logv-first-post";
  const fatalSourceBaseFile =
      phasePrefix + "leveldb-write-logger-fatal-source-base-file";
  const headline = {
    wasmTime: "../../base/time/time_wasm.cc:44: Check failed: source-suffix-wasm-time",
    timeFormatting:
        "../../base/i18n/time_formatting.cc:74: DCHECK failed: source-suffix-time-formatting",
    leveldb:
        "../../third_party/leveldatabase/env_chromium.cc:355: DCHECK failed: source-suffix-leveldb",
    baseFile:
        "../../base/files/file.cc:46: DCHECK failed: source-suffix-base-file",
  };
  // Exercise every frozen complete v1 header independently. The suffix is
  // deliberately arbitrary and must never enter a result or snapshot.
  const approvedHeadline = Object.freeze({
    "header-time-44": [
      "../../base/time/time_wasm.cc:44: Check failed: source-suffix-time-44",
      "wasm-time",
    ],
    "header-time-50": [
      "../../base/time/time_wasm.cc:50: Check failed: source-suffix-time-50",
      "wasm-time",
    ],
    "header-format-74": [
      "../../base/i18n/time_formatting.cc:74: DCHECK failed: source-suffix-format-74",
      "time-formatting",
    ],
    "header-format-76": [
      "../../base/i18n/time_formatting.cc:76: DCHECK failed: source-suffix-format-76",
      "time-formatting",
    ],
    "header-format-81": [
      "../../base/i18n/time_formatting.cc:81: DCHECK failed: source-suffix-format-81",
      "time-formatting",
    ],
    "header-leveldb-355": [
      "../../third_party/leveldatabase/env_chromium.cc:355: DCHECK failed: source-suffix-leveldb-355",
      "leveldb",
    ],
    "header-leveldb-1340": [
      "../../third_party/leveldatabase/env_chromium.cc:1340: Check failed: source-suffix-leveldb-1340",
      "leveldb",
    ],
    "header-file-46": [
      "../../base/files/file.cc:46: DCHECK failed: source-suffix-file-46",
      "base-file",
    ],
    "header-file-53": [
      "../../base/files/file.cc:53: DCHECK failed: source-suffix-file-53",
      "base-file",
    ],
    "header-file-posix-439": [
      "../../base/files/file_posix.cc:439: DCHECK failed: source-suffix-file-posix-439",
      "base-file",
    ],
  });
  const module = {};
  options.onRuntimeInitialized.call(module);
  const stderr = (line) => options.printErr(line);
  const stdout = (line) => options.print(line);
  const rawToken = options.arguments.find((argument) =>
      argument.startsWith("--wasm-profile-database-token-a=")).split("=")[1];
  let reason = "native code called abort()";
  if (Object.hasOwn(approvedHeadline, scenario)) {
    stderr(pre);
    stderr(approvedHeadline[scenario][0]);
    stderr(marker);
  } else if (scenario === "approved") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
  } else if (scenario === "unavailable") {
    stderr(pre);
    stderr(headline.timeFormatting);
    stderr(unavailable);
  } else if (scenario === "fatal-source-base-file") {
    stderr(pre);
    stderr(fatalSourceBaseFile);
    // The in-process observer emits its fixed source family before Chromium's
    // unchanged fatal headline. The later raw line must remain transient and
    // leave only the fixed native phase plus an ambiguous headline family.
    stderr(approvedHeadline["header-file-posix-439"][0]);
    stderr(marker);
  } else if (scenario === "fatal-source-after-post") {
    stderr(pre);
    stderr(post);
    stderr(fatalSourceBaseFile);
    stderr(marker);
  } else if (scenario === "fatal-source-before-pre") {
    stderr(fatalSourceBaseFile);
    stderr(marker);
  } else if (scenario === "fatal-source-normal") {
    stderr(fatalSourceBaseFile);
    options.onAbort(reason);
    return module;
  } else if (scenario === "other") {
    stderr(pre);
    stderr("../../base/unknown.cc:1: Check failed: source-suffix-other");
    stderr(marker);
  } else if (scenario === "conflicting") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(headline.timeFormatting);
    stderr(marker);
  } else if (scenario === "duplicate-headline") {
    stderr(pre);
    stderr(headline.leveldb);
    stderr(headline.leveldb);
    stderr(marker);
  } else if (scenario === "out-of-phase") {
    stderr(headline.wasmTime);
    stderr(pre);
    stderr(marker);
  } else if (scenario === "headline-stdout") {
    stderr(pre);
    stdout(headline.wasmTime);
    stderr(marker);
  } else if (scenario === "after-marker") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    stderr(headline.timeFormatting);
  } else if (scenario === "after-abort") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    options.onAbort(reason);
    stderr(headline.timeFormatting);
    return module;
  } else if (scenario === "post-before-marker") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(post);
    stderr(marker);
  } else if (scenario === "after-post") {
    stderr(pre);
    stderr(post);
    stderr(headline.wasmTime);
    stderr(marker);
  } else if (scenario === "pre-after-marker") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    stderr(pre);
  } else if (scenario === "pre-post-pre") {
    stderr(pre);
    stderr(post);
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
  } else if (scenario === "unknown-phase") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(phasePrefix + "unknown");
    stderr(marker);
  } else if (scenario === "check-kind") {
    stderr(pre);
    stderr("../../base/time/time_wasm.cc:44: DCHECK failed: source-suffix-kind");
    stderr(marker);
  } else if (scenario === "off-by-one") {
    stderr(pre);
    stderr("../../base/time/time_wasm.cc:45: Check failed: source-suffix-line");
    stderr(marker);
  } else if (scenario === "source-case") {
    stderr(pre);
    stderr("../../base/Time/time_wasm.cc:44: Check failed: source-suffix-case");
    stderr(marker);
  } else if (scenario === "source-slash") {
    stderr(pre);
    stderr("..\\..\\base\\time\\time_wasm.cc:44: Check failed: source-suffix-slash");
    stderr(marker);
  } else if (scenario === "suffix-only") {
    stderr(pre);
    stderr("source-suffix-only");
    stderr(marker);
  } else if (scenario === "header-in-middle") {
    stderr(pre);
    stderr("ordinary-prefix " + headline.wasmTime);
    stderr(marker);
  } else if (scenario === "token") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    options.onAbort(reason);
    stderr(headline.wasmTime + rawToken);
    return module;
  } else if (scenario === "malformed-pc") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(pcPrefix + "frame=caller-caller;function=raw;offset=0x1");
  } else if (scenario === "duplicate-pc") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    stderr(marker);
  } else if (scenario === "missing-pc") {
    stderr(pre);
    stderr(headline.wasmTime);
  } else if (scenario === "assertion-reason") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    reason = "Assertion failed: source-suffix-assertion";
  } else if (scenario === "other-reason") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    reason = "other-source-suffix-reason";
  } else if (scenario === "process-exit-before-abort") {
    stderr(pre);
    stderr(headline.wasmTime);
    stderr(marker);
    globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({
      protocol: 1,
      exitCode: 0,
    });
  } else if (scenario === "normal") {
    stderr(pre);
    stderr(headline.baseFile);
    stderr(marker);
  } else {
    throw new Error("unknown fatal-headline scenario");
  }
  options.onAbort(reason);
  return module;
}
'''
        script = (
            "import {validateChromeWasmProfileDatabaseFailureSummary, "
            "runChromeWasmProfileDatabaseFromQuery} from "
            + json.dumps(host_uri)
            + ";\nconst loaderSource = "
            + json.dumps(loader_source)
            + r''';
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  throw new Error("Node Web Crypto is unavailable");
}
const scenario = process.argv[1];
const normalMode = scenario === "normal" || scenario === "fatal-source-normal";
const pc = {frame: "caller-caller", function: 42, offset: "0x1a"};
const expected = new Map([
  ["header-time-44", ["abort-reported", pc, "wasm-time"]],
  ["header-time-50", ["abort-reported", pc, "wasm-time"]],
  ["header-format-74", ["abort-reported", pc, "time-formatting"]],
  ["header-format-76", ["abort-reported", pc, "time-formatting"]],
  ["header-format-81", ["abort-reported", pc, "time-formatting"]],
  ["header-leveldb-355", ["abort-reported", pc, "leveldb"]],
  ["header-leveldb-1340", ["abort-reported", pc, "leveldb"]],
  ["header-file-46", ["abort-reported", pc, "base-file"]],
  ["header-file-53", ["abort-reported", pc, "base-file"]],
  ["header-file-posix-439", ["abort-reported", pc, "base-file"]],
  ["approved", ["abort-reported", pc, "wasm-time"]],
  ["unavailable", ["abort-reported", null, "time-formatting"]],
  ["fatal-source-base-file", ["abort-reported", pc, "ambiguous"]],
  ["fatal-source-after-post", ["phase-unexpected", pc, null]],
  ["fatal-source-before-pre", ["phase-unexpected", pc, null]],
  ["fatal-source-normal", ["phase-unexpected", null, null]],
  ["other", ["abort-reported", pc, "ambiguous"]],
  ["conflicting", ["abort-reported", pc, "ambiguous"]],
  ["duplicate-headline", ["abort-reported", pc, "ambiguous"]],
  ["out-of-phase", ["abort-reported", pc, "ambiguous"]],
  ["headline-stdout", ["abort-reported", pc, "ambiguous"]],
  ["after-marker", ["abort-reported", pc, "ambiguous"]],
  ["after-abort", ["abort-reported", pc, "ambiguous"]],
  ["post-before-marker", ["abort-reported", pc, "ambiguous"]],
  ["after-post", ["abort-reported", pc, "ambiguous"]],
  ["pre-after-marker", ["abort-reported", pc, "ambiguous"]],
  ["pre-post-pre", ["abort-reported", pc, "ambiguous"]],
  ["unknown-phase", ["phase-unexpected", pc, "ambiguous"]],
  ["check-kind", ["abort-reported", pc, "ambiguous"]],
  ["off-by-one", ["abort-reported", pc, "ambiguous"]],
  ["source-case", ["abort-reported", pc, "ambiguous"]],
  ["source-slash", ["abort-reported", pc, "ambiguous"]],
  ["suffix-only", ["abort-reported", pc, "ambiguous"]],
  ["header-in-middle", ["abort-reported", pc, "ambiguous"]],
  ["token", ["abort-reported", pc, "ambiguous"]],
  ["malformed-pc", ["abort-pc-invalid", null, null]],
  ["duplicate-pc", ["abort-pc-duplicate", pc, null]],
  ["missing-pc", ["abort-pc-missing-before-abort", null, null]],
  ["assertion-reason", ["abort-reported", pc, null]],
  ["other-reason", ["abort-reported", pc, null]],
  ["process-exit-before-abort", ["abort-reported", pc, null]],
  ["normal", ["abort-pc-unexpected", null, null]],
]).get(scenario);
if (!expected) throw new Error("test scenario is invalid");
class FakeElement {
  constructor() { this.dataset = {}; this.textContent = ""; }
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
const listeners = new Map();
globalThis.addEventListener = (type, listener) => {
  const values = listeners.get(type) ?? [];
  values.push(listener);
  listeners.set(type, values);
};
globalThis.removeEventListener = (type, listener) => {
  listeners.set(type, (listeners.get(type) ?? []).filter(
      (candidate) => candidate !== listener));
};
globalThis.crossOriginIsolated = true;
globalThis.__fatalHeadlineScenario = scenario;
const loaderBytes = new TextEncoder().encode(loaderSource);
const wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (value) => value.toString(16).padStart(2, "0")).join("");
}
const moduleName = normalMode ? "chrome_wasm_m7_profile_database_test" :
    "chrome_wasm_m7_profile_database_abort_pc_diagnostic";
const artifact = {
  artifact_delivery: "immutable-in-memory-server-snapshot",
  artifact_source_provenance: "unverified",
  build_config: {bytes: 1, sha256: "a".repeat(64)},
  build_config_provenance: "selected-out-dir-args-gn-immutable-snapshot",
  loader: {bytes: loaderBytes.byteLength, sha256: await digest(loaderBytes)},
  module_name: moduleName,
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
  token: "fake-fatal-headline-result-token-123456",
  module: moduleName,
  timeoutMs: "1000",
  diagnosticMode: normalMode ? "normal" : "abort-pc",
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
const family = posted?.fatalHeadline === null ? null : posted?.fatalHeadline?.family;
if (!rejected || posted === null || posted.status !== "fail" ||
    posted.firstFatalTag !== expected[0] ||
    JSON.stringify(posted.abortPc) !== JSON.stringify(expected[1]) ||
    family !== expected[2]) {
  throw new Error("fatal-headline fake loader result mismatch");
}
if (posted.fatalHeadline !== null &&
    posted.fatalHeadline.provenance !==
        "fixed-active-stderr-logger-logv-fatal-headline-v1") {
  throw new Error("fatal headline provenance is invalid");
}
if (scenario === "fatal-source-base-file" &&
    posted.nativeDatabasePhase !==
        "leveldb-write-logger-fatal-source-base-file") {
  throw new Error("fixed fatal-source phase was not retained");
}
if (scenario === "fatal-source-after-post" &&
    posted.nativeDatabasePhase !== "leveldb-write-logger-logv-first-post") {
  throw new Error("out-of-interval fatal-source phase replaced prior phase");
}
if ((scenario === "fatal-source-before-pre" ||
     scenario === "fatal-source-normal") &&
    posted.nativeDatabasePhase !== null) {
  throw new Error("invalid fatal-source phase was retained");
}
validateChromeWasmProfileDatabaseFailureSummary(posted);
const serialized = JSON.stringify(posted);
if (serialized.includes("../../base/") ||
    serialized.includes("source-suffix") ||
    serialized.includes("Check failed:") ||
    serialized.includes("DCHECK failed:") ||
    status.textContent.includes("../../base/")) {
  throw new Error("raw fatal headline escaped the failure summary");
}
delete globalThis.__fatalHeadlineScenario;
process.stdout.write(JSON.stringify(posted));
'''
        )
        runner_rejections = frozenset(
            (
                "malformed-pc",
                "duplicate-pc",
                "missing-pc",
                "assertion-reason",
                "other-reason",
                "process-exit-before-abort",
                "unknown-phase",
                "fatal-source-after-post",
                "fatal-source-before-pre",
            )
        )
        frozen_header_scenarios = (
            "header-time-44",
            "header-time-50",
            "header-format-74",
            "header-format-76",
            "header-format-81",
            "header-leveldb-355",
            "header-leveldb-1340",
            "header-file-46",
            "header-file-53",
            "header-file-posix-439",
        )
        scenarios = (
            *frozen_header_scenarios,
            "approved",
            "unavailable",
            "fatal-source-base-file",
            "fatal-source-after-post",
            "fatal-source-before-pre",
            "fatal-source-normal",
            "other",
            "conflicting",
            "duplicate-headline",
            "out-of-phase",
            "headline-stdout",
            "after-marker",
            "after-abort",
            "post-before-marker",
            "after-post",
            "pre-after-marker",
            "pre-post-pre",
            "unknown-phase",
            "check-kind",
            "off-by-one",
            "source-case",
            "source-slash",
            "suffix-only",
            "header-in-middle",
            "token",
            "malformed-pc",
            "duplicate-pc",
            "missing-pc",
            "assertion-reason",
            "other-reason",
            "process-exit-before-abort",
            "normal",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                completed = subprocess.run(
                    ["node", "--input-type=module", "--eval", script, scenario],
                    capture_output=True,
                    check=False,
                    cwd=TOOLS_DIR.parents[1],
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                if scenario in ("normal", "fatal-source-normal"):
                    summary = smoke.validate_failed_host_result_summary(
                        result, diagnostic_mode=smoke.DIAGNOSTIC_MODE_NORMAL
                    )
                    self.assertIsNone(summary["fatalHeadline"])
                elif scenario in runner_rejections:
                    with self.assertRaises(M0Error):
                        smoke.validate_failed_host_result_summary(
                            result, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
                        )
                else:
                    summary = smoke.validate_failed_host_result_summary(
                        result, diagnostic_mode=smoke.DIAGNOSTIC_MODE_ABORT_PC
                    )
                    self.assertEqual(
                        summary["fatalHeadline"]["provenance"],
                        smoke.FATAL_HEADLINE_PROVENANCE,
                    )
                    self.assertNotIn("../../base/", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()

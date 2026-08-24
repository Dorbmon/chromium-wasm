#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused host contracts for the non-gating post-Sync observation."""

from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap
import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


HOST_PATH = ROOT_DIR / "tools/wasm/host/chrome_wasm_profile_database_write_interruption_smoke.js"
NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"


_NODE_HARNESS = r"""
import {pathToFileURL} from "node:url";

const hostUri = process.argv[1];
const ordinal = Number(process.argv[2]);
const scenario = process.argv[3];
if (![1, 2, 3].includes(ordinal) ||
    !["normal", "abort-first", "split-token", "split-capability", "split-session-capability", "late-clean", "extra-phase", "extra-abort-error", "wrong-abort-wrapper", "direct-before-wrapper", "abort-error-before-phase", "after-result-callback"].includes(scenario)) {
  throw new Error("invalid test input");
}
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  const {webcrypto} = await import("node:crypto");
  Object.defineProperty(globalThis, "crypto", {configurable: true, value: webcrypto});
}
function digestText(text) {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(
      (buffer) => Array.from(new Uint8Array(buffer),
          (byte) => byte.toString(16).padStart(2, "0")).join(""));
}
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
const versionsElement = new FakeElement();
globalThis.document = {
  activeElement: null,
  createElement() { return new FakeElement(); },
  querySelector(selector) {
    return new Map([
      ["#m7-profile-database-write-interruption-root", root],
      ["#m7-profile-database-write-interruption-canvas", canvas],
      ["#m7-profile-database-write-interruption-status", status],
      ["#m7-profile-database-write-interruption-versions", versionsElement],
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
function emitWindowError(event) {
  for (const listener of listeners.get("error") ?? []) listener(event);
}
class ErrorEvent {
  constructor(message) {
    this.error = null;
    this.message = message;
  }
}
globalThis.__emitControlledAbortWindowErrors = (mode) => {
  const abortError = "Uncaught RuntimeError: Aborted(native code called abort())";
  const wrapper = {
    message: "Uncaught [object ErrorEvent]",
    error: new ErrorEvent(abortError),
  };
  const direct = {message: abortError, error: null};
  if (mode === "wrong-abort-wrapper") {
    wrapper.message = "Uncaught [object WrongEvent]";
  }
  if (mode === "direct-before-wrapper") {
    emitWindowError(direct);
    emitWindowError(wrapper);
    return;
  }
  emitWindowError(wrapper);
  emitWindowError(direct);
  if (mode === "extra-abort-error") emitWindowError(direct);
};
globalThis.crossOriginIsolated = true;
Object.defineProperty(globalThis, "performance", {
  configurable: true,
  value: {
    timeOrigin: 1700000000000 + ordinal,
    now() { return Date.now(); },
    getEntriesByType(name) {
      return name === "navigation" ? [{type: ordinal === 1 ? "navigate" : "reload"}] : [];
    },
  },
});
const rawA = "a".repeat(64);
const rawB = "b".repeat(64);
const digestA = await digestText(rawA);
const digestB = await digestText(rawB);
globalThis.__digestA = digestA;
globalThis.__digestB = digestB;
const loaderSource = String.raw`
export default function(options) {
  const mode = options.arguments.find((arg) =>
      arg.startsWith("--wasm-profile-database-smoke="))?.split("=", 2)[1];
  const tokenA = options.arguments.find((arg) =>
      arg.startsWith("--wasm-profile-database-token-a="))?.split("=", 2)[1];
  const module = {};
  options.onRuntimeInitialized.call(module);
  const bridge = globalThis.__chromiumWasmHostBridgeV1;
  const clean = (markers) => {
    for (const marker of markers) options.printErr(marker);
    bridge.reportProcessExit({protocol: 1, exitCode: 0});
    options.onExit(0);
    return module;
  };
  if (mode === "write-a") {
    options.printErr("CHROMIUM_WASM_M7_DATABASE_PHASE:task-post");
    return clean([
      "CHROMIUM_WASM_M7_DATABASE:READY",
      "CHROMIUM_WASM_M7_DATABASE:SQLITE_WRITE_ACCEPTED sha256=" + globalThis.__digestA,
      "CHROMIUM_WASM_M7_DATABASE:LEVELDB_WRITE_ACCEPTED sha256=" + globalThis.__digestA,
      "CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_DATABASES_CLOSED",
      "CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_FENCE_OK",
      "CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_LEASE_RELEASED",
    ]);
  }
  if (mode === "observe-leveldb-write-b") {
    return clean([
      "CHROMIUM_WASM_M7_DATABASE:READY",
      "CHROMIUM_WASM_M7_DATABASE:LEVELDB_POST_SYNC_OBSERVATION outcome=b",
      "CHROMIUM_WASM_M7_DATABASE:SQLITE_POST_SYNC_REOPEN_INTEGRITY_OK",
      "CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_DATABASES_CLOSED",
      "CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_FENCE_OK",
      "CHROMIUM_WASM_M7_DATABASE:DIAGNOSTIC_LEASE_RELEASED",
    ]);
  }
  if (mode !== "interrupt-leveldb-write-b") throw new Error("unexpected mode");
  // The real PROXY_TO_PTHREAD factory resolves once its runtime is ready;
  // browser main then runs asynchronously on the worker.  Most scenarios
  // resolve this fake factory first and emit post-Sync callbacks on the next
  // task.  abort-first also covers callbacks arriving before resolution.
  const emitInterruption = () => {
    options.printErr("CHROMIUM_WASM_M7_DATABASE:READY");
    options.printErr("CHROMIUM_WASM_M7_DATABASE:SQLITE_READ_A_OK sha256=" + globalThis.__digestA);
    options.printErr("CHROMIUM_WASM_M7_DATABASE:LEVELDB_READ_A_OK sha256=" + globalThis.__digestA);
    if (globalThis.__scenario === "extra-phase") {
      options.printErr("CHROMIUM_WASM_M7_DATABASE_PHASE:task-started");
    }
    const phase = () => options.printErr(
        "CHROMIUM_WASM_M7_DATABASE_PHASE:leveldb-write-log-sync-returned");
    const abort = () => {
      options.onAbort("native code called abort()");
      if (globalThis.__scenario === "abort-error-before-phase") {
        globalThis.__emitControlledAbortWindowErrors(globalThis.__scenario);
        return;
      }
      setTimeout(() => globalThis.__emitControlledAbortWindowErrors(
          globalThis.__scenario), 0);
    };
    if (globalThis.__scenario === "split-token") {
      options.printErr(tokenA.slice(0, 63));
      options.printErr(tokenA.slice(63));
      phase();
      abort();
      return;
    }
    if (globalThis.__scenario === "split-capability") {
      options.printErr(globalThis.__resultToken.slice(0, 64));
      options.printErr(globalThis.__resultToken.slice(64));
      phase();
      abort();
      return;
    }
    if (globalThis.__scenario === "split-session-capability") {
      options.printErr(globalThis.__sessionCapability.slice(0, 64));
      options.printErr(globalThis.__sessionCapability.slice(64));
      phase();
      abort();
      return;
    }
    if (globalThis.__scenario === "abort-first" ||
        globalThis.__scenario === "abort-error-before-phase") {
      abort();
      phase();
    } else {
      phase();
      abort();
    }
    if (globalThis.__scenario === "late-clean") {
      setTimeout(() => {
        bridge.reportProcessExit({protocol: 1, exitCode: 0});
        options.onExit(0);
      }, 80);
    }
  };
  if (globalThis.__scenario === "abort-first") {
    emitInterruption();
  } else {
    setTimeout(emitInterruption, 0);
  }
  return module;
}
`;
const loaderBytes = new TextEncoder().encode(loaderSource);
const wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
const artifact = {
  artifact_delivery: "immutable-in-memory-server-snapshot",
  artifact_source_provenance: "unverified",
  build_config: {bytes: 1, sha256: "c".repeat(64)},
  build_config_provenance: "selected-out-dir-args-gn-immutable-snapshot",
  loader: {bytes: loaderBytes.byteLength, sha256: await digestText(loaderSource)},
  module_name: "chrome_wasm_m7_profile_database_write_interruption_diagnostic",
  wasm: {bytes: wasmBytes.byteLength, sha256: await digestText(
      String.fromCharCode(...wasmBytes))},
};
// Digest raw wasm bytes instead of its source-code string representation.
artifact.wasm.sha256 = Array.from(new Uint8Array(await crypto.subtle.digest(
    "SHA-256", wasmBytes)), (byte) => byte.toString(16).padStart(2, "0")).join("");
const captureHarness = {
  host_html: {bytes: 1, sha256: "d".repeat(64)},
  host_js: {bytes: 1, sha256: "e".repeat(64)},
  runner_source: {bytes: 1, sha256: "f".repeat(64)},
  source_snapshot_provenance:
      "on-disk-byte-snapshots-at-server-startup-not-commit-provenance",
  version_provenance:
      "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance",
};
const query = new URLSearchParams({
  resultToken: scenario === "split-capability" ? "r".repeat(128) : "r".repeat(48),
  session: scenario === "split-session-capability" ? "s".repeat(128) : "s".repeat(48),
  module: artifact.module_name,
  timeoutMs: "2000",
  versions: JSON.stringify({chromium: "0".repeat(40), v8: "1".repeat(40), emscripten: "2".repeat(40)}),
  artifact: JSON.stringify(artifact),
  captureHarness: JSON.stringify(captureHarness),
});
globalThis.__resultToken = query.get("resultToken");
globalThis.__sessionCapability = query.get("session");
globalThis.location = new URL(
    "https://m7.test/__m7_chrome_profile_database_write_interruption__/" +
    "?" + query);
const NativeURL = URL;
globalThis.URL = class extends NativeURL {};
URL.createObjectURL = () =>
    "data:text/javascript;base64," + Buffer.from(loaderSource).toString("base64");
URL.revokeObjectURL = () => {};
function headers(contentType = null) {
  const values = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if (contentType !== null) values["Content-Type"] = contentType;
  return new Headers(values);
}
const bootstrap = {
  protocol: 1,
  case: "chrome_profile_database_write_interruption_m7",
  scope: "same-origin-three-outer-documents-chrome-wasm-m7-profile-database-post-leveldb-log-sync-interruption-diagnostic-only",
  ordinal,
  mode: ordinal === 1 ? "write-a" : ordinal === 2 ?
      "interrupt-leveldb-write-b" : "observe-leveldb-write-b",
  tokenA: rawA,
  tokenB: ordinal === 1 ? null : rawB,
  tokenADigest: digestA,
  tokenBDigest: ordinal === 1 ? null : digestB,
};
let postedResult = null;
let postedReady = null;
let bootstrapPosts = 0;
let bootstrapGets = 0;
globalThis.__scenario = scenario;
globalThis.fetch = async (url, options = {}) => {
  const href = String(url);
  if (href.includes("/bootstrap/")) {
    if (options.method === "POST") {
      const receipt = JSON.parse(options.body);
      if (receipt.ordinal !== undefined || receipt.protocol !== 1 ||
          receipt.navigationType !== (ordinal === 1 ? "navigate" : "reload")) {
        throw new Error("invalid bootstrap evidence");
      }
      ++bootstrapPosts;
      return {status: 204, url: href, headers: headers()};
    }
    ++bootstrapGets;
    return {status: 200, url: href, headers: headers("application/json"),
      async json() { return bootstrap; }};
  }
  if (href.endsWith(".js")) {
    return {ok: true, url: href, headers: headers("text/javascript"),
      async arrayBuffer() { return loaderBytes.buffer.slice(
          loaderBytes.byteOffset, loaderBytes.byteOffset + loaderBytes.byteLength); }};
  }
  if (href.endsWith(".wasm")) {
    return {ok: true, url: href, headers: headers("application/wasm"),
      async arrayBuffer() { return wasmBytes.buffer.slice(
          wasmBytes.byteOffset, wasmBytes.byteOffset + wasmBytes.byteLength); }};
  }
  if (options.method === "POST" && href.includes("/result/")) {
    postedResult = JSON.parse(options.body);
    if (scenario === "after-result-callback") {
      setTimeout(() => globalThis.__chromiumWasmHostBridgeV1.reportFrame({}), 0);
    }
    return {status: 204, url: href, headers: headers()};
  }
  if (options.method === "POST" && href.includes("/ready/")) {
    postedReady = JSON.parse(options.body);
    return {status: 204, url: href, headers: headers()};
  }
  throw new Error("unexpected fetch");
};
const {runChromeWasmProfileDatabaseWriteInterruptionFromQuery} = await import(hostUri);
let rejected = false;
let result = null;
try {
  result = await runChromeWasmProfileDatabaseWriteInterruptionFromQuery();
} catch {
  rejected = true;
}
const serialized = JSON.stringify({postedResult, postedReady, result, status: status.textContent});
if (serialized.includes(rawA) || serialized.includes(rawB) ||
    serialized.includes(query.get("resultToken")) || serialized.includes(query.get("session"))) {
  throw new Error("opaque value leaked into host output");
}
if (scenario === "split-token" || scenario === "split-capability" ||
    scenario === "split-session-capability" ||
    scenario === "late-clean" || scenario === "extra-phase" ||
    scenario === "extra-abort-error" || scenario === "wrong-abort-wrapper" ||
    scenario === "direct-before-wrapper" ||
    scenario === "abort-error-before-phase") {
  if (!rejected || postedResult === null || postedResult.status !== "fail" ||
      postedReady !== null || root.dataset.state !== "fail") {
    throw new Error("late or split diagnostic callback was not fail-closed");
  }
} else if (scenario === "after-result-callback") {
  if (!rejected || postedResult === null || postedResult.status !== "seeded" ||
      postedReady !== null) {
    throw new Error("post-result callback did not block the ready barrier");
  }
} else {
  const expectedStatus = ordinal === 1 ? "seeded" : ordinal === 2 ? "interrupted" : "observed";
  if (rejected || result === null || result.status !== expectedStatus ||
      result.m7GateComplete !== false || postedResult?.status !== expectedStatus ||
      postedReady === null || bootstrapPosts !== 1 || bootstrapGets !== 1 ||
      root.dataset.state !== expectedStatus || result.run.settleComplete !== true ||
      result.finalQuiescence.quiet !== true || result.finalQuiescence.bridgeRecheckedImmediatelyBeforeUpload !== true) {
    throw new Error("normal diagnostic host result is invalid");
  }
  if (ordinal === 2 && (!result.run.abortObserved || !result.run.phaseObserved ||
      result.run.processExitCount !== 0 || result.run.onExitCount !== 0 ||
      result.run.factoryResolved !== true || result.run.factoryRejected !== false ||
      result.run.factorySettled !== true ||
      result.run.controlledAbortWindowErrorCount !== 2)) {
    throw new Error("interruption observation is invalid");
  }
}
"""


class M7ProfileDatabaseWriteInterruptionHostTest(unittest.TestCase):
    def setUp(self) -> None:
        self.host = source(
            "tools/wasm/host/chrome_wasm_profile_database_write_interruption_smoke.js"
        )

    def run_node(self, ordinal: int, scenario: str) -> None:
        completed = subprocess.run(
            [
                str(NODE),
                "--experimental-default-type=module",
                "--eval",
                _NODE_HARNESS,
                HOST_PATH.resolve().as_uri(),
                str(ordinal),
                scenario,
            ],
            capture_output=True,
            check=False,
            cwd=ROOT_DIR,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")

    def test_host_accepts_all_three_fixed_modes(self) -> None:
        for ordinal in (1, 2, 3):
            with self.subTest(ordinal=ordinal):
                self.run_node(ordinal, "normal")

    def test_post_sync_phase_and_abort_have_no_arrival_order_dependency(self) -> None:
        self.run_node(2, "abort-first")

    def test_split_opaque_token_is_redacted_and_fails_closed(self) -> None:
        self.run_node(2, "split-token")

    def test_split_maximum_length_capability_is_redacted_and_fails_closed(self) -> None:
        self.run_node(2, "split-capability")
        self.run_node(2, "split-session-capability")

    def test_late_clean_callback_during_final_quiescence_fails_closed(self) -> None:
        self.run_node(2, "late-clean")

    def test_interrupted_document_rejects_extra_callbacks(self) -> None:
        self.run_node(2, "extra-phase")
        self.run_node(2, "extra-abort-error")

    def test_interrupted_document_requires_exact_abort_error_sequence(self) -> None:
        self.run_node(2, "wrong-abort-wrapper")
        self.run_node(2, "direct-before-wrapper")
        self.run_node(2, "abort-error-before-phase")

    def test_callback_after_result_blocks_ready_barrier(self) -> None:
        self.run_node(1, "after-result-callback")

    def test_source_has_a_bounded_barrier_and_no_pass_result(self) -> None:
        for token in (
            "MAX_OPAQUE_SECRET_CHARS = 128",
            "this.#opaqueTail = text.slice(-(MAX_OPAQUE_SECRET_CHARS - 1));",
            "#beginFinalQuiescence(run)",
            "#finishFinalQuiescence(run)",
            "isReadyAfterResultUpload()",
            "POST_SYNC_OBSERVATION_OUTCOMES",
            "POST_SYNC_SQLITE_REOPEN_INTEGRITY_MARKER",
            "DIAGNOSTIC_DATABASES_CLOSED",
            "DIAGNOSTIC_FENCE_OK",
            "DIAGNOSTIC_LEASE_RELEASED",
            "m7GateComplete: false",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.host)
        self.assertNotIn('status: "pass"', self.host)
        self.assertIn("diagnostic post-Sync value observation complete", self.host)


if __name__ == "__main__":
    unittest.main()

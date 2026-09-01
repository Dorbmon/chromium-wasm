#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Node contracts for the M7 two-outer-document database witness host."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
HOST_URI = (
    TOOLS_DIR / "host" / "chrome_wasm_profile_database_outer_reload_smoke.js"
).as_uri()


def fake_host_script() -> str:
    loader_source = r'''
export default async function(options) {
  if (globalThis.__expectNoLoader) {
    throw new Error("loader invoked");
  }
  const rawA = options.arguments.find((argument) =>
      argument.startsWith("--wasm-profile-database-token-a=")).split("=")[1];
  const rawBArgument = options.arguments.find((argument) =>
      argument.startsWith("--wasm-profile-database-token-b="));
  const rawB = rawBArgument ? rawBArgument.split("=")[1] : null;
  if (globalThis.__scenario === "leak") {
    options.print(rawA.slice(0, 31));
    options.printErr(rawA.slice(31));
    return {};
  }
  const digest = async (value) => Array.from(new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))),
      (byte) => byte.toString(16).padStart(2, "0")).join("");
  const digestA = await digest(rawA);
  const digestB = rawB === null ? null : await digest(rawB);
  const marker = "CHROMIUM_WASM_M7_DATABASE:";
  const phase = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
  const module = {};
  options.onRuntimeInitialized.call(module);
  options.printErr(phase + "task-post");
  // The actual pthread bridge can receive the synchronous process-exit import
  // before its queued printErr marker messages.  Model that ordering here.
  globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({protocol: 1, exitCode: 0});
  options.onExit(0);
  options.printErr(marker + "READY");
  if (rawB === null) {
    options.printErr(marker + "SQLITE_WRITE_ACCEPTED sha256=" + digestA);
    options.printErr(marker + "LEVELDB_WRITE_ACCEPTED sha256=" + digestA);
    options.printErr(marker + "DATABASES_CLOSED sha256=" + digestA);
    options.printErr(marker + "FENCE_OK sha256=" + digestA);
  } else {
    options.printErr(marker + "SQLITE_READ_A_OK sha256=" + digestA);
    options.printErr(marker + "LEVELDB_READ_A_OK sha256=" + digestA);
    options.printErr(marker + "SQLITE_WRITE_ACCEPTED sha256=" + digestB);
    options.printErr(marker + "LEVELDB_WRITE_ACCEPTED sha256=" + digestB);
    options.printErr(marker + "DATABASES_CLOSED sha256=" + digestB);
    options.printErr(marker + "FENCE_OK sha256=" + digestB);
  }
  options.printErr(marker + "LEASE_RELEASED");
  options.printErr(phase + "task-complete");
  return module;
}
'''
    return (
        "import {runChromeWasmProfileDatabaseOuterReloadFromQuery} from "
        + json.dumps(HOST_URI)
        + ";\n"
        + "const loaderSource = "
        + json.dumps(loader_source)
        + ";\n"
        + r'''
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  const {webcrypto} = await import("node:crypto");
  globalThis.crypto = webcrypto;
}
const ordinal = Number(process.argv[1]);
const scenario = process.argv[2];
const phaseTwoNavigationType = process.argv[3];
const bootstrapNavigationMode = process.argv[4];
if ((ordinal !== 1 && ordinal !== 2) ||
    (scenario !== "pass" && scenario !== "leak") ||
    (phaseTwoNavigationType !== "navigate" &&
     phaseTwoNavigationType !== "reload") ||
    !["match", "navigate", "reload", "omit", "invalid"].includes(
        bootstrapNavigationMode)) {
  throw new Error("test input is invalid");
}
globalThis.__scenario = scenario;
const expectedNavigationType = ordinal === 1 ? "navigate" :
    phaseTwoNavigationType;
const bootstrapExpectedNavigationType =
    bootstrapNavigationMode === "match" ? expectedNavigationType :
    bootstrapNavigationMode === "invalid" ? "back_forward" :
    bootstrapNavigationMode === "omit" ? null : bootstrapNavigationMode;
globalThis.__expectNoLoader = bootstrapNavigationMode !== "match";
let tick = 0;
Object.defineProperty(globalThis, "performance", {
  configurable: true,
  value: {
    timeOrigin: 1700000000000 + ordinal,
    now() { return ++tick; },
    getEntriesByType(name) {
      return name === "navigation" ? [{
        type: expectedNavigationType,
      }] : [];
    },
  },
});
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
const versionsElement = new FakeElement();
globalThis.document = {
  activeElement: null,
  createElement() { return new FakeElement(); },
  querySelector(selector) {
    return new Map([
      ["#m7-profile-database-outer-reload-root", root],
      ["#m7-profile-database-outer-reload-canvas", canvas],
      ["#m7-profile-database-outer-reload-status", status],
      ["#m7-profile-database-outer-reload-versions", versionsElement],
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
const rawA = "a".repeat(64);
const rawB = "b".repeat(64);
async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (byte) => byte.toString(16).padStart(2, "0")).join("");
}
const loaderBytes = new TextEncoder().encode(loaderSource);
const wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
const artifact = {
  artifact_delivery: "immutable-in-memory-server-snapshot",
  artifact_source_provenance: "unverified",
  build_config: {bytes: 1, sha256: "c".repeat(64)},
  build_config_provenance: "selected-out-dir-args-gn-immutable-snapshot",
  loader: {bytes: loaderBytes.byteLength, sha256: await digest(loaderBytes)},
  module_name: "chrome_wasm_m7_profile_database_test",
  wasm: {bytes: wasmBytes.byteLength, sha256: await digest(wasmBytes)},
};
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
  resultToken: "fake-outer-reload-result-capability-123456",
  session: "fake-outer-reload-session-capability-123456",
  module: artifact.module_name,
  timeoutMs: "2000",
  versions: JSON.stringify({
    chromium: "0".repeat(40),
    v8: "1".repeat(40),
    emscripten: "2".repeat(40),
  }),
  artifact: JSON.stringify(artifact),
  captureHarness: JSON.stringify(captureHarness),
});
globalThis.location = new URL(
    "https://m7.test/__m7_chrome_profile_database_outer_reload__/" +
    "?" + query);
if (location.href.includes(rawA) || location.href.includes(rawB)) {
  throw new Error("raw database token escaped into test URL");
}
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
  case: "chrome_profile_database_outer_document_persistence_m7",
  scope:
      "same-origin-two-outer-documents-chrome-wasm-m7-profile-database-test-modules-orderly-handoff-only",
  ordinal,
  mode: ordinal === 1 ? "write-a" : "verify-a-write-b",
  ...(bootstrapExpectedNavigationType === null ? {} : {
    expectedNavigationType: bootstrapExpectedNavigationType,
  }),
  tokenA: rawA,
  tokenB: ordinal === 1 ? null : rawB,
  tokenADigest: await digest(new TextEncoder().encode(rawA)),
  tokenBDigest: ordinal === 1 ? null :
      await digest(new TextEncoder().encode(rawB)),
};
let postedResult = null;
let postedReady = null;
let bootstrapRequests = 0;
let bootstrapEvidenceRequests = 0;
globalThis.fetch = async (url, options = {}) => {
  const href = String(url);
  if (href.includes("/bootstrap/")) {
    if (options.method === "POST") {
      const documentReceipt = JSON.parse(options.body ?? "null");
      if (
        JSON.stringify(Object.keys(documentReceipt).sort()) !== JSON.stringify(
            ["case", "navigationType", "protocol", "scope", "timeOrigin"]) ||
        documentReceipt.protocol !== 1 ||
        documentReceipt.case !== bootstrap.case ||
        documentReceipt.scope !== bootstrap.scope ||
        documentReceipt.navigationType !== expectedNavigationType ||
        documentReceipt.timeOrigin !== 1700000000000 + ordinal) {
        throw new Error("host bootstrap document evidence is invalid");
      }
      ++bootstrapEvidenceRequests;
      return {status: 204, url: href, headers: headers()};
    }
    if (options.method !== undefined) {
      throw new Error("host bootstrap method is invalid");
    }
    ++bootstrapRequests;
    return {
      status: 200,
      url: href,
      headers: headers("application/json"),
      async json() { return bootstrap; },
    };
  }
  if (href.endsWith(".js")) {
    return {
      ok: true,
      url: href,
      headers: headers("text/javascript"),
      async arrayBuffer() {
        return loaderBytes.buffer.slice(
            loaderBytes.byteOffset, loaderBytes.byteOffset + loaderBytes.byteLength);
      },
    };
  }
  if (href.endsWith(".wasm")) {
    return {
      ok: true,
      url: href,
      headers: headers("application/wasm"),
      async arrayBuffer() {
        return wasmBytes.buffer.slice(
            wasmBytes.byteOffset, wasmBytes.byteOffset + wasmBytes.byteLength);
      },
    };
  }
  if (options.method === "POST" && href.includes("/result/")) {
    postedResult = JSON.parse(options.body);
    return {status: 204, url: href, headers: headers()};
  }
  if (options.method === "POST" && href.includes("/ready/")) {
    postedReady = JSON.parse(options.body);
    return {status: 204, url: href, headers: headers()};
  }
  throw new Error("unexpected fetch");
};
let rejected = false;
let result = null;
try {
  result = await runChromeWasmProfileDatabaseOuterReloadFromQuery();
} catch {
  rejected = true;
}
const serializedResult = postedResult === null ? "" : JSON.stringify(postedResult);
if (scenario === "leak") {
  if (!rejected || postedResult === null || postedResult.status !== "fail" ||
      postedReady !== null || serializedResult.includes(rawA) ||
      serializedResult.includes(rawB) || status.textContent.includes(rawA) ||
      status.textContent.includes(rawB) || root.dataset.state !== "fail") {
    throw new Error("outer-reload token leak was not fail-closed and redacted");
  }
} else {
  if (rejected || result === null || result.status !== "pass" ||
      postedResult === null || postedResult.status !== "pass" ||
      postedReady === null || bootstrapEvidenceRequests !== 1 ||
      bootstrapRequests !== 1 ||
      postedResult.ordinal !== ordinal || postedReady.ordinal !== ordinal ||
      postedResult.mode !== bootstrap.mode ||
      postedResult.document.navigationType !== expectedNavigationType ||
      postedResult.tokenEvidence.tokenA !== bootstrap.tokenADigest ||
      postedResult.tokenEvidence.tokenB !== bootstrap.tokenBDigest ||
      postedResult.tokenEvidence.distinct !== (ordinal === 1 ? null : true) ||
      postedResult.run.markerDeliveryCompleteAtProcessExit !== false ||
      postedResult.hostBoundary.sessionStorageAccessAttempted !== false ||
      postedResult.hostBoundary.localStorageAccessAttempted !== false ||
      postedResult.hostBoundary.indexedDbAccessAttempted !== false ||
      postedResult.hostBoundary.cookieAccessAttempted !== false ||
      postedResult.hostBoundary.historyStateAccessAttempted !== false ||
      postedResult.hostBoundary.windowNameAccessAttempted !== false ||
      serializedResult.includes(rawA) || serializedResult.includes(rawB) ||
      status.textContent.includes(rawA) || status.textContent.includes(rawB) ||
      root.dataset.state !== "pass") {
    throw new Error("outer-reload fake host did not preserve the protocol");
  }
}
'''
    )


class OuterReloadHostTest(unittest.TestCase):
    def run_fake_host(
        self,
        ordinal: int,
        scenario: str,
        phase_two_navigation_type: str = "reload",
        bootstrap_navigation_mode: str = "match",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "node",
                "--input-type=module",
                "--eval",
                fake_host_script(),
                str(ordinal),
                scenario,
                phase_two_navigation_type,
                bootstrap_navigation_mode,
            ],
            cwd=TOOLS_DIR.parents[1],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )

    def test_fake_host_runs_both_outer_document_ordinals(self) -> None:
        for ordinal in (1, 2):
            with self.subTest(ordinal=ordinal):
                completed = self.run_fake_host(ordinal, "pass")
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_accepts_fresh_outer_browser_verify_and_write_document(self) -> None:
        completed = self.run_fake_host(
            2, "pass", phase_two_navigation_type="navigate"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_mismatched_or_invalid_bootstrap_navigation_type(self) -> None:
        for bootstrap_navigation_mode in ("reload", "omit", "invalid"):
            with self.subTest(bootstrap_navigation_mode=bootstrap_navigation_mode):
                completed = self.run_fake_host(
                    2,
                    "pass",
                    phase_two_navigation_type="navigate",
                    bootstrap_navigation_mode=bootstrap_navigation_mode,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("loader invoked", completed.stderr)

    def test_fake_host_scrubs_cross_callback_token_leak(self) -> None:
        completed = self.run_fake_host(1, "leak")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_host_uses_only_runner_bootstrap_for_the_outer_handoff(self) -> None:
        host_source = Path(HOST_URI.removeprefix("file://")).read_text(
            encoding="utf-8"
        )
        self.assertIn("./bootstrap/${encodeURIComponent(context.session)}", host_source)
        self.assertIn("method: \"POST\"", host_source)
        self.assertIn("expectedNavigationType", host_source)
        self.assertIn(
            "documentReceipt.navigationType !== bootstrap.expectedNavigationType",
            host_source,
        )
        self.assertIn("./result/${encodeURIComponent(context.resultToken)}/${ordinal}",
                      host_source)
        self.assertIn("./ready/${encodeURIComponent(context.resultToken)}/${ordinal}",
                      host_source)
        for forbidden in (
            "sessionStorage.",
            "localStorage.",
            "indexedDB",
            "document.cookie",
            "history.",
            "window.name",
            "location.reload",
            "location.replace",
            "location.assign",
            "Runtime.evaluate",
            "Page.reload",
            "Page.navigate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, host_source)


if __name__ == "__main__":
    unittest.main()

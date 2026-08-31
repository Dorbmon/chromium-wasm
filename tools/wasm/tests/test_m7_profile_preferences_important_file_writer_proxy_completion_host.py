#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Node contracts for the four-document Preferences replacement host."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
HOST_PATH = (
    TOOLS_DIR
    / "host"
    / "chrome_wasm_profile_preferences_important_file_writer_proxy_completion_smoke.js"
)
HOST_URI = HOST_PATH.as_uri()


def fake_host_script() -> str:
    loader_source = r'''
export default async function(options) {
  const ordinal = globalThis.__ordinal;
  const scenario = globalThis.__scenario;
  const fault = options.arguments.includes(
      "--wasm-profile-preferences-important-file-writer-proxy-completion");
  if ((ordinal === 2) !== fault) throw new Error("fault switch is invalid");
  if (options.arguments.some((arg) => arg.includes("browser-smoke") ||
      arg.includes("history-smoke") || arg.includes("cookie-smoke") ||
      arg.includes("bookmark-smoke"))) {
    throw new Error("unrelated profile witness switch is present");
  }
  const aArg = options.arguments.find((arg) =>
      arg.startsWith("--wasm-profile-preferences-token-a="));
  const bArg = options.arguments.find((arg) =>
      arg.startsWith("--wasm-profile-preferences-token-b="));
  const rawA = aArg ? aArg.slice(aArg.indexOf("=") + 1) : null;
  const rawB = bArg ? bArg.slice(bArg.indexOf("=") + 1) : null;
  if ((ordinal === 4) !== (rawA === null) || (ordinal === 1) !== (rawB === null)) {
    throw new Error("token argument shape is invalid");
  }
  const hash = async (raw) => Array.from(new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw))),
      (byte) => byte.toString(16).padStart(2, "0")).join("");
  const digestA = rawA === null ? null : await hash(rawA);
  const digestB = rawB === null ? null : await hash(rawB);
  const marker = "CHROMIUM_WASM_M7_PREFS:";
  const module = {};
  options.onRuntimeInitialized.call(module);
  if (scenario === "leak") {
    options.printErr(rawA.slice(0, 31));
    options.printErr(rawA.slice(31));
  } else if (ordinal === 1) {
    options.printErr(marker + "READY");
    options.printErr(marker + "WRITE_ACCEPTED sha256=" + digestA);
    options.printErr(marker + "FENCE_OK sha256=" + digestA);
    options.printErr(marker + "LEASE_RELEASED");
  } else if (ordinal === 2) {
    options.printErr(marker + "READY");
    options.printErr(marker + "READ_A_OK sha256=" + digestA);
    options.printErr(marker + "IMPORTANT_FILE_WRITER_REPLACE_EIO_POST_FLUSH_UNPUBLISHED");
    options.printErr(marker + "FAIL stage=fence");
    options.printErr("CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED");
  } else if (ordinal === 3) {
    options.printErr(marker + "READY");
    options.printErr(marker + "LEASE_REACQUIRED");
    options.printErr(marker + "READ_A_OK sha256=" + digestA);
    options.printErr(marker + "WRITE_ACCEPTED sha256=" + digestB);
    options.printErr(marker + "FENCE_OK sha256=" + digestB);
    options.printErr(marker + "LEASE_RELEASED");
  } else {
    options.printErr(marker + "READY");
    options.printErr(marker + "READ_B_OK sha256=" + digestB);
    options.printErr(marker + "FENCE_OK sha256=" + digestB);
    options.printErr(marker + "LEASE_RELEASED");
  }
  const exitCode = ordinal === 2 ? 19 : 0;
  globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({
    protocol: 1, exitCode,
  });
  if (scenario === "abort") options.onAbort("controlled abort is prohibited");
  options.onExit(exitCode);
  if (ordinal === 2 && scenario === "reject") {
    return Promise.reject({
      name: "ExitStatus", status: exitCode,
      message: `Program terminated with exit(${exitCode})`,
    });
  }
  return module;
}
'''
    return (
        "import {runChromeWasmProfilePreferencesImportantFileWriterProxyCompletionFromQuery} from "
        + json.dumps(HOST_URI)
        + ";\nconst loaderSource = "
        + json.dumps(loader_source)
        + ";\n"
        + r'''
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  const {webcrypto} = await import("node:crypto");
  globalThis.crypto = webcrypto;
}
const ordinal = Number(process.argv[1]);
const scenario = process.argv[2];
if (![1, 2, 3, 4].includes(ordinal) ||
    !["resolve", "reject", "abort", "leak"].includes(scenario) ||
    (scenario === "reject" && ordinal !== 2)) {
  throw new Error("test input is invalid");
}
globalThis.__ordinal = ordinal;
globalThis.__scenario = scenario;
let tick = 0;
Object.defineProperty(globalThis, "performance", {
  configurable: true,
  value: {
    timeOrigin: 1700000000000 + ordinal,
    now() { return ++tick; },
    getEntriesByType(name) {
      return name === "navigation" ? [{type: ordinal === 1 ? "navigate" : "reload"}] : [];
    },
  },
});
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
      ["#m7-profile-preferences-important-file-writer-proxy-completion-root", root],
      ["#m7-profile-preferences-important-file-writer-proxy-completion-canvas", canvas],
      ["#m7-profile-preferences-important-file-writer-proxy-completion-status", status],
      ["#m7-profile-preferences-important-file-writer-proxy-completion-versions", versionsElement],
    ]).get(selector) ?? null;
  },
};
const listeners = new Map();
globalThis.addEventListener = (name, callback) => {
  const callbacks = listeners.get(name) ?? [];
  callbacks.push(callback);
  listeners.set(name, callbacks);
};
globalThis.removeEventListener = (name, callback) => listeners.set(
    name, (listeners.get(name) ?? []).filter((candidate) => candidate !== callback));
const rawA = "a".repeat(64);
const rawB = "b".repeat(64);
const rawC = "c".repeat(64);
async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (byte) => byte.toString(16).padStart(2, "0")).join("");
}
const loaderBytes = new TextEncoder().encode(loaderSource);
const wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
const artifact = {
  artifact_delivery: "immutable-in-memory-server-snapshot",
  artifact_source_provenance: "unverified",
  build_config: {bytes: 1, sha256: "d".repeat(64)},
  build_config_provenance: "selected-out-dir-args-gn-immutable-snapshot",
  loader: {bytes: loaderBytes.byteLength, sha256: await digest(loaderBytes)},
  module_name:
      "chrome_wasm_m7_profile_preferences_important_file_writer_proxy_completion_test",
  wasm: {bytes: wasmBytes.byteLength, sha256: await digest(wasmBytes)},
};
const captureHarness = {
  host_html: {bytes: 1, sha256: "e".repeat(64)},
  host_js: {bytes: 1, sha256: "f".repeat(64)},
  runner_source: {bytes: 1, sha256: "0".repeat(64)},
  source_snapshot_provenance:
      "on-disk-byte-snapshots-at-server-startup-not-commit-provenance",
  version_provenance:
      "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance",
};
const query = new URLSearchParams({
  resultToken: "fake-result-capability-abcdefghijklmnopqrstuvwxyz",
  session: "fake-session-capability-abcdefghijklmnopqrstuvwxyz",
  module: artifact.module_name,
  timeoutMs: "2000",
  versions: JSON.stringify({
    chromium: "0".repeat(40), v8: "1".repeat(40), emscripten: "2".repeat(40),
  }),
  artifact: JSON.stringify(artifact),
  captureHarness: JSON.stringify(captureHarness),
});
globalThis.location = new URL(
    "https://m7.test/__m7_chrome_profile_preferences_important_file_writer_proxy_completion__/" +
    "?" + query);
if (location.href.includes(rawA) || location.href.includes(rawB) ||
    location.href.includes(rawC)) {
  throw new Error("raw preference token escaped into URL");
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
const tokenA = ordinal === 4 ? null : rawA;
const tokenB = ordinal === 1 ? null : ordinal === 2 ? rawB : rawC;
const bootstrap = {
  protocol: 1,
  case:
      "chrome_profile_preferences_important_file_writer_proxy_completion_four_outer_document_reload_m7",
  scope:
      "same-origin-four-outer-documents-canonical-chrome-preferences-important-file-writer-post-flush-v4-proxy-completion-failure-and-fresh-document-recovery-only",
  ordinal,
  mode: ordinal === 1 ? "write" : ordinal === 4 ? "verify-b" : "verify-and-write",
  faultProxyCompletion: ordinal === 2,
  tokenA,
  tokenB,
  tokenADigest: tokenA === null ? null : await digest(new TextEncoder().encode(tokenA)),
  tokenBDigest: tokenB === null ? null : await digest(new TextEncoder().encode(tokenB)),
};
let bootstrapPosts = 0;
let bootstrapGets = 0;
let result = null;
let ready = null;
globalThis.fetch = async (url, options = {}) => {
  const href = String(url);
  if (href.includes("/bootstrap/")) {
    if (options.method === "POST") {
      const evidence = JSON.parse(options.body);
      const expectedNavigation = ordinal === 1 ? "navigate" : "reload";
      if (JSON.stringify(Object.keys(evidence).sort()) !== JSON.stringify(
          ["case", "navigationType", "protocol", "scope", "timeOrigin"]) ||
          evidence.protocol !== 1 || evidence.case !== bootstrap.case ||
          evidence.scope !== bootstrap.scope || evidence.navigationType !== expectedNavigation ||
          evidence.timeOrigin !== 1700000000000 + ordinal) {
        throw new Error("document evidence is invalid");
      }
      ++bootstrapPosts;
      return {status: 204, url: href, headers: headers()};
    }
    if (options.method !== undefined || bootstrapPosts !== 1) {
      throw new Error("bootstrap request order is invalid");
    }
    ++bootstrapGets;
    return {ok: true, status: 200, url: href, headers: headers("application/json"),
      async json() { return bootstrap; }};
  }
  if (href.endsWith(".js")) {
    return {ok: true, status: 200, url: href, headers: headers("text/javascript"),
      async arrayBuffer() { return loaderBytes.buffer.slice(
          loaderBytes.byteOffset, loaderBytes.byteOffset + loaderBytes.byteLength); }};
  }
  if (href.endsWith(".wasm")) {
    return {ok: true, status: 200, url: href, headers: headers("application/wasm"),
      async arrayBuffer() { return wasmBytes.buffer.slice(
          wasmBytes.byteOffset, wasmBytes.byteOffset + wasmBytes.byteLength); }};
  }
  if (options.method === "POST" && href.includes("/result/")) {
    result = JSON.parse(options.body);
    return {status: 204, url: href, headers: headers()};
  }
  if (options.method === "POST" && href.includes("/ready/")) {
    ready = JSON.parse(options.body);
    return {status: 204, url: href, headers: headers()};
  }
  throw new Error("unexpected fetch");
};
globalThis.crossOriginIsolated = true;
const completed = await runChromeWasmProfilePreferencesImportantFileWriterProxyCompletionFromQuery();
if (scenario === "abort" || scenario === "leak") {
  throw new Error("prohibited scenario was accepted");
}
if (bootstrapPosts !== 1 || bootstrapGets !== 1 || result === null || ready === null ||
    completed.status !== result.status || result.status === "fail" ||
    result.ordinal !== ordinal || result.run.abortObserved !== false ||
    result.run.processExitCount !== 1 || result.run.onExitCount !== 1 ||
    result.tokenEvidence.rawTokenLeakDetected !== false ||
    JSON.stringify(result).includes(rawA) || JSON.stringify(result).includes(rawB) ||
    JSON.stringify(result).includes(rawC)) {
  throw new Error("host receipt is invalid");
}
if (ordinal === 2) {
  if (result.run.processExitCode !== 19 || result.run.runtimeExitCode !== 19 ||
      result.run.leaseReleasedMarkerObserved ||
      !result.run.importantFileWriterEioObserved ||
      !result.run.failureRetirementMarkerObserved ||
      result.run.factoryRejectedExpectedExitStatus !== (scenario === "reject")) {
    throw new Error("clean nonzero failure receipt is invalid");
  }
} else if (result.run.processExitCode !== 0 || result.run.runtimeExitCode !== 0 ||
           !result.run.leaseReleasedMarkerObserved ||
           result.run.failureRetirementMarkerObserved) {
  throw new Error("clean normal receipt is invalid");
}
process.stdout.write("pass\n");
'''
    )


class M7PreferencesImportantFileWriterProxyCompletionHostTest(unittest.TestCase):
    def run_fake_host(self, ordinal: int, scenario: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "node",
                "--input-type=module",
                "--eval",
                fake_host_script(),
                str(ordinal),
                scenario,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_accepts_seed_recovery_and_final_verification_documents(self) -> None:
        for ordinal, scenario in ((1, "resolve"), (2, "resolve"), (2, "reject"),
                                  (3, "resolve"), (4, "resolve")):
            with self.subTest(ordinal=ordinal, scenario=scenario):
                completed = self.run_fake_host(ordinal, scenario)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout, "pass\n")

    def test_rejects_abort_and_cross_callback_raw_token_leak_without_echo(self) -> None:
        for scenario in ("abort", "leak"):
            with self.subTest(scenario=scenario):
                completed = self.run_fake_host(2 if scenario == "abort" else 3, scenario)
                self.assertNotEqual(completed.returncode, 0)
                for token in ("a" * 64, "b" * 64, "c" * 64):
                    self.assertNotIn(token, completed.stdout)
                    self.assertNotIn(token, completed.stderr)


if __name__ == "__main__":
    unittest.main()

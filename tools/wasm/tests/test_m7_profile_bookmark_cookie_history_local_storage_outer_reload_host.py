#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Node contracts for the M7 Bookmark + Cookie + History + renderer LocalStorage host."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
HOST_PATH = (
    TOOLS_DIR / "host" / "chrome_wasm_profile_bookmark_cookie_history_local_storage_outer_reload_smoke.js"
)
HOST_URI = HOST_PATH.as_uri()


def fake_host_script() -> str:
    loader_source = r'''
export default async function(options) {
  const required = [
    "--wasm-profile-preferences-browser-smoke",
    "--wasm-profile-preferences-bookmark-smoke",
    "--disable-features=SyncEnableBookmarksInTransportMode",
    "--wasm-profile-preferences-cookie-smoke",
    "--wasm-profile-preferences-history-smoke",
  ];
  if (!required.every((argument) => options.arguments.includes(argument))) {
    throw new Error(
        "aggregate Preferences/Bookmark/Cookie/History capability is missing");
  }
  if (options.arguments.filter((argument) =>
      argument === "--disable-features=SyncEnableBookmarksInTransportMode")
          .length !== 1) {
    throw new Error("Bookmark transport-mode disablement is ambiguous");
  }
  const argumentValue = (prefix) => {
    const argument = options.arguments.find((value) => value.startsWith(prefix));
    return argument === undefined ? null : argument.slice(prefix.length);
  };
  const preferenceA = argumentValue("--wasm-profile-preferences-token-a=");
  const preferenceB = argumentValue("--wasm-profile-preferences-token-b=");
  const localStorage = argumentValue("--wasm-profile-local-storage-token=");
  const expectedPreferenceMode = globalThis.__ordinal === 1 ?
      "--wasm-profile-preferences-smoke=write" :
      (globalThis.__ordinal === 2 ?
       "--wasm-profile-preferences-smoke=verify-and-write" :
       "--wasm-profile-preferences-smoke=verify-b");
  const expectedLocalStorageMode = globalThis.__ordinal === 1 ?
      "--wasm-profile-local-storage-smoke=renderer-write" :
      "--wasm-profile-local-storage-smoke=renderer-verify";
  if (!options.arguments.includes(expectedPreferenceMode) ||
      !options.arguments.includes(expectedLocalStorageMode) ||
      localStorage === null ||
      (globalThis.__ordinal === 1 &&
       (preferenceA === null || preferenceB !== null)) ||
      (globalThis.__ordinal === 2 &&
       (preferenceA === null || preferenceB === null)) ||
      (globalThis.__ordinal === 3 &&
       (preferenceA !== null || preferenceB === null))) {
    throw new Error("aggregate module arguments are invalid");
  }
  if (globalThis.__scenario === "leak") {
    options.printErr(localStorage);
    return {};
  }
  const digest = async (token) => Array.from(new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token))),
      (byte) => byte.toString(16).padStart(2, "0")).join("");
  const preferenceADigest =
      preferenceA === null ? null : await digest(preferenceA);
  const preferenceBDigest =
      preferenceB === null ? null : await digest(preferenceB);
  const localStorageDigest = await digest(localStorage);
  const prefs = "CHROMIUM_WASM_M7_PREFS:";
  const storage = "CHROMIUM_WASM_M7_LOCAL_STORAGE:";
  const module = {};
  options.onRuntimeInitialized.call(module);
  // Exercise the real host's accepted pthread ordering: process exit and
  // onExit may arrive before queued stderr markers.
  globalThis.__chromiumWasmHostBridgeV1.reportProcessExit(
      {protocol: 1, exitCode: 0});
  options.onExit(0);
  options.printErr(prefs + "READY");
  if (globalThis.__ordinal === 1) {
    options.printErr(prefs + "WRITE_ACCEPTED sha256=" + preferenceADigest);
    options.printErr(prefs + "BROWSER_SMOKE_CLOSED");
    options.printErr(
        prefs + "BOOKMARK_A_WRITE_FLUSHED sha256=" + preferenceADigest);
    options.printErr(prefs + "BOOKMARK_MODEL_CLOSED");
    options.printErr(
        prefs + "COOKIE_A_WRITE_FLUSHED sha256=" + preferenceADigest);
  } else if (globalThis.__ordinal === 2) {
    options.printErr(prefs + "READ_A_OK sha256=" + preferenceADigest);
    options.printErr(prefs + "WRITE_ACCEPTED sha256=" + preferenceBDigest);
    options.printErr(prefs + "BROWSER_SMOKE_CLOSED");
    options.printErr(
        prefs + "BOOKMARK_A_READ_OK sha256=" + preferenceADigest);
    options.printErr(
        prefs + "BOOKMARK_B_WRITE_FLUSHED sha256=" + preferenceBDigest);
    options.printErr(prefs + "BOOKMARK_MODEL_CLOSED");
    options.printErr(prefs + "COOKIE_A_READ_OK sha256=" + preferenceADigest);
    options.printErr(
        prefs + "COOKIE_B_WRITE_FLUSHED sha256=" + preferenceBDigest);
  } else {
    options.printErr(prefs + "READ_B_OK sha256=" + preferenceBDigest);
    options.printErr(prefs + "BROWSER_SMOKE_CLOSED");
    options.printErr(
        prefs + "BOOKMARK_B_READ_OK sha256=" + preferenceBDigest);
    options.printErr(prefs + "BOOKMARK_CLEANUP_FLUSHED");
    options.printErr(prefs + "BOOKMARK_MODEL_CLOSED");
    options.printErr(prefs + "COOKIE_B_READ_OK sha256=" + preferenceBDigest);
  }
  options.printErr(prefs + "COOKIE_BACKEND_CLOSED");
  if (globalThis.__ordinal === 1) {
    options.printErr(prefs + "HISTORY_A_WRITE_ACCEPTED");
  } else if (globalThis.__ordinal === 2) {
    options.printErr(prefs + "HISTORY_A_READ_OK");
    options.printErr(prefs + "HISTORY_B_WRITE_ACCEPTED");
  } else {
    options.printErr(prefs + "HISTORY_A_READ_OK");
    options.printErr(prefs + "HISTORY_B_READ_OK");
  }
  options.printErr(prefs + "HISTORY_BACKEND_CLOSED");
  options.printErr(storage + "READY");
  options.printErr(storage +
      (globalThis.__ordinal === 1 ?
       "RENDERER_WRITE_OK sha256=" :
       "RENDERER_REOPEN_READ_OK sha256=") + localStorageDigest);
  options.printErr(storage + "ON_DISK_COMMIT_OK sha256=" + localStorageDigest);
  options.printErr(storage + "DB_CLOSE_OK sha256=" + localStorageDigest);
  options.printErr(prefs + "FENCE_OK sha256=" +
      (globalThis.__ordinal === 1 ? preferenceADigest : preferenceBDigest));
  options.printErr(storage + "FENCE_OK sha256=" + localStorageDigest);
  options.printErr(prefs + "LEASE_RELEASED");
  options.printErr(storage + "LEASE_RELEASED");
  return module;
}
'''
    return (
        "import {runChromeWasmProfileBookmarkCookieHistoryLocalStorageOuterReloadFromQuery} from "
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
const timeoutMs = process.argv[3];
if ((ordinal !== 1 && ordinal !== 2 && ordinal !== 3) ||
    (scenario !== "pass" && scenario !== "leak") ||
    !/^(?:2000|600000|600001)$/.test(timeoutMs)) {
  throw new Error("test input is invalid");
}
globalThis.__scenario = scenario;
globalThis.__ordinal = ordinal;
let tick = 0;
Object.defineProperty(globalThis, "performance", {
  configurable: true,
  value: {
    timeOrigin: 1700000000000 + ordinal,
    now() { return scenario === "leak" ? ++tick * 2000 : ++tick; },
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
      ["#m7-profile-bookmark-cookie-history-local-storage-outer-reload-root", root],
      ["#m7-profile-bookmark-cookie-history-local-storage-outer-reload-canvas", canvas],
      ["#m7-profile-bookmark-cookie-history-local-storage-outer-reload-status", status],
      ["#m7-profile-bookmark-cookie-history-local-storage-outer-reload-versions", versionsElement],
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
const rawLocalStorage = "9".repeat(64);
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
  module_name: "chrome_wasm_m7_profile_bookmark_cookie_history_local_storage_test",
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
  timeoutMs,
  versions: JSON.stringify({
    chromium: "0".repeat(40), v8: "1".repeat(40), emscripten: "2".repeat(40),
  }),
  artifact: JSON.stringify(artifact),
  captureHarness: JSON.stringify(captureHarness),
});
globalThis.location = new URL(
    "https://m7.test/__m7_chrome_profile_bookmark_cookie_history_local_storage_outer_reload__/?" + query);
if (location.href.includes(rawA) || location.href.includes(rawB) ||
    location.href.includes(rawLocalStorage)) {
  throw new Error("raw escrow token escaped into URL");
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
  case: "chrome_profile_bookmark_cookie_history_local_storage_three_outer_document_reload_m7",
  scope:
      "same-origin-three-outer-documents-chrome-wasm-m7-preferences-bookmark-" +
      "model-cookie-manager-history-service-renderer-local-storage-one-" +
      "shared-drain-per-module-orderly-reload-only",
  ordinal,
  mode: ordinal === 1 ? "write" :
      (ordinal === 2 ? "verify-and-write" : "verify-b"),
  preferenceTokenA: ordinal === 3 ? null : rawA,
  preferenceTokenB: ordinal === 1 ? null : rawB,
  localStorageToken: rawLocalStorage,
  preferenceTokenADigest:
      ordinal === 3 ? null : await digest(new TextEncoder().encode(rawA)),
  preferenceTokenBDigest:
      ordinal === 1 ? null : await digest(new TextEncoder().encode(rawB)),
  localStorageTokenDigest:
      await digest(new TextEncoder().encode(rawLocalStorage)),
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
      const expectedType = ordinal === 1 ? "navigate" : "reload";
      if (JSON.stringify(Object.keys(evidence).sort()) !== JSON.stringify(
          ["case", "navigationType", "protocol", "scope", "timeOrigin"]) ||
          evidence.protocol !== 1 || evidence.case !== bootstrap.case ||
          evidence.scope !== bootstrap.scope || evidence.navigationType !== expectedType ||
          evidence.timeOrigin !== 1700000000000 + ordinal) {
        throw new Error("document evidence invalid");
      }
      ++bootstrapPosts;
      return {status: 204, url: href, headers: headers()};
    }
    if (options.method !== undefined || bootstrapPosts !== 1) {
      throw new Error("bootstrap request order invalid");
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
const completed = await runChromeWasmProfileBookmarkCookieHistoryLocalStorageOuterReloadFromQuery();
if (scenario === "pass") {
  if (bootstrapPosts !== 1 || bootstrapGets !== 1 || result === null || ready === null ||
      completed.status !== "pass" || result.status !== "pass" ||
      result.run.freshLoaderImport !== true ||
      result.run.bookmarkTransportModeFeatureDisabled !== true ||
      result.run.preferenceLeaseReleasedMarkerObserved !== true ||
      result.run.localStorageLeaseReleasedMarkerObserved !== true ||
      result.run.sharedDrainReceiptsAccepted !== true ||
      result.tokenEvidence.rawTokenLeakDetected !== false ||
      JSON.stringify(result).includes(rawA) || JSON.stringify(result).includes(rawB) ||
      JSON.stringify(result).includes(rawLocalStorage)) {
    throw new Error("passing host evidence is invalid");
  }
  process.stdout.write("pass\n");
} else {
  throw new Error("raw escrow token leak was not rejected");
}
'''
    )


class M7ProfileBookmarkCookieHistoryLocalStorageOuterReloadHostTest(unittest.TestCase):
    def run_fake_host(
        self, ordinal: int, scenario: str, timeout_ms: str = "2000"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", "--input-type=module", "--eval", fake_host_script(),
             str(ordinal), scenario, timeout_ms],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_accepts_write_document(self) -> None:
        completed = self.run_fake_host(1, "pass")
        self.assertTrue(completed.returncode == 0, "write fake host failed")
        self.assertEqual(completed.stdout, "pass\n")

    def test_accepts_verify_and_write_document(self) -> None:
        completed = self.run_fake_host(2, "pass")
        self.assertTrue(completed.returncode == 0, "verify fake host failed")
        self.assertEqual(completed.stdout, "pass\n")

    def test_accepts_verify_b_cleanup_document(self) -> None:
        completed = self.run_fake_host(3, "pass")
        self.assertTrue(completed.returncode == 0, "verify-b fake host failed")
        self.assertEqual(completed.stdout, "pass\n")

    def test_rejects_raw_local_storage_leak_without_echo(self) -> None:
        completed = self.run_fake_host(1, "leak")
        self.assertNotEqual(completed.returncode, 0)
        opaque = "9" * 64
        self.assertFalse(opaque in completed.stdout, "raw token reached stdout")
        self.assertFalse(opaque in completed.stderr, "raw token reached stderr")

    def test_accepts_cold_start_timeout_and_rejects_a_larger_timeout(self) -> None:
        accepted = self.run_fake_host(1, "pass", "600000")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        rejected = self.run_fake_host(1, "pass", "600001")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("outer-reload timeout is invalid", rejected.stderr)

    def test_host_neither_uses_outer_storage_nor_self_navigates(self) -> None:
        source = HOST_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "sessionStorage.",
            "localStorage.",
            "indexedDB.",
            "document.cookie",
            "window.name",
            "location.reload(",
            "location.replace(",
            "location.assign(",
            "Page.reload",
            "Page.navigate",
            "Runtime.evaluate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertTrue(forbidden not in source, "forbidden host API found")
        self.assertIn("postBootstrapDocumentEvidence", source)
        self.assertIn("await fetchBootstrap(context)", source)
        self.assertIn("--wasm-profile-preferences-smoke=write", source)
        self.assertIn("--wasm-profile-preferences-smoke=verify-and-write", source)
        self.assertIn("--wasm-profile-preferences-smoke=verify-b", source)
        self.assertIn("--wasm-profile-preferences-browser-smoke", source)
        self.assertIn("--wasm-profile-preferences-bookmark-smoke", source)
        self.assertIn(
            "--disable-features=SyncEnableBookmarksInTransportMode", source
        )
        self.assertIn("--wasm-profile-preferences-cookie-smoke", source)
        self.assertIn("--wasm-profile-preferences-history-smoke", source)
        self.assertIn("--wasm-profile-local-storage-smoke=renderer-write", source)
        self.assertIn("--wasm-profile-local-storage-smoke=renderer-verify", source)
        self.assertIn("--wasm-profile-local-storage-token=", source)
        self.assertIn("BROWSER_SMOKE_CLOSED", source)
        self.assertIn("BOOKMARK_A_WRITE_FLUSHED", source)
        self.assertIn("BOOKMARK_A_READ_OK", source)
        self.assertIn("BOOKMARK_B_WRITE_FLUSHED", source)
        self.assertIn("BOOKMARK_B_READ_OK", source)
        self.assertIn("BOOKMARK_CLEANUP_FLUSHED", source)
        self.assertIn("BOOKMARK_MODEL_CLOSED", source)
        self.assertIn("COOKIE_A_WRITE_FLUSHED", source)
        self.assertIn("COOKIE_A_READ_OK", source)
        self.assertIn("COOKIE_B_WRITE_FLUSHED", source)
        self.assertIn("COOKIE_B_READ_OK", source)
        self.assertIn("COOKIE_BACKEND_CLOSED", source)
        self.assertIn("HISTORY_A_WRITE_ACCEPTED", source)
        self.assertIn("HISTORY_A_READ_OK", source)
        self.assertIn("HISTORY_B_WRITE_ACCEPTED", source)
        self.assertIn("HISTORY_B_READ_OK", source)
        self.assertIn("HISTORY_BACKEND_CLOSED", source)
        self.assertIn("RENDERER_WRITE_OK", source)
        self.assertIn("RENDERER_REOPEN_READ_OK", source)
        self.assertIn("ON_DISK_COMMIT_OK", source)
        self.assertIn("DB_CLOSE_OK", source)
        self.assertIn("sharedDrainReceiptsAccepted", source)
        self.assertNotIn("BOOKMARK_A_WRITE_ACCEPTED", source)
        self.assertNotIn("BOOKMARK_B_WRITE_ACCEPTED", source)
        self.assertNotIn("BOOKMARK_BACKEND_CLOSED", source)
        self.assertIn("<suppressed-native-output>", source)


if __name__ == "__main__":
    unittest.main()

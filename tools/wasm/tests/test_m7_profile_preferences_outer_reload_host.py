#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Node contracts for the M7 Preferences/Bookmark/Cookie/History host."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
HOST_PATH = (
    TOOLS_DIR / "host" / "chrome_wasm_profile_preferences_outer_reload_smoke.js"
)
HOST_URI = HOST_PATH.as_uri()


def fake_host_script() -> str:
    loader_source = r'''
export default async function(options) {
  if (globalThis.__expectNoLoader) {
    throw new Error("loader invoked");
  }
  if (!options.arguments.includes(
      "--wasm-profile-preferences-browser-smoke")) {
    throw new Error("Browser smoke capability is missing");
  }
  if (!options.arguments.includes(
      "--wasm-profile-preferences-history-smoke")) {
    throw new Error("History smoke capability is missing");
  }
  if (!options.arguments.includes(
      "--wasm-profile-preferences-cookie-smoke")) {
    throw new Error("CookieManager smoke capability is missing");
  }
  if (!options.arguments.includes(
      "--wasm-profile-preferences-bookmark-smoke")) {
    throw new Error("BookmarkModel smoke capability is missing");
  }
  if (!options.arguments.includes(
      "--disable-features=SyncEnableBookmarksInTransportMode")) {
    throw new Error("Bookmark transport-mode disablement is missing");
  }
  const tokenAArgument = options.arguments.find((argument) =>
      argument.startsWith("--wasm-profile-preferences-token-a="));
  const tokenA = tokenAArgument ? tokenAArgument.split("=")[1] : null;
  const tokenBArgument = options.arguments.find((argument) =>
      argument.startsWith("--wasm-profile-preferences-token-b="));
  const tokenB = tokenBArgument ? tokenBArgument.split("=")[1] : null;
  if (globalThis.__scenario === "leak") {
    options.print((tokenA ?? tokenB).slice(0, 31));
    options.printErr((tokenA ?? tokenB).slice(31));
    return {};
  }
  const digest = async (token) => Array.from(new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token))),
      (byte) => byte.toString(16).padStart(2, "0")).join("");
  const digestA = tokenA === null ? null : await digest(tokenA);
  const digestB = tokenB === null ? null : await digest(tokenB);
  const marker = "CHROMIUM_WASM_M7_PREFS:";
  const module = {};
  options.onRuntimeInitialized.call(module);
  // Model the real pthread bridge's possible synchronous-exit / queued-output
  // ordering, which means marker delivery need not precede process exit.
  globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({protocol: 1, exitCode: 0});
  options.onExit(0);
  options.printErr(marker + "READY");
  if (globalThis.__ordinal === 1) {
    options.printErr(marker + "WRITE_ACCEPTED sha256=" + digestA);
    options.printErr(marker + "BROWSER_SMOKE_CLOSED");
    options.printErr(marker + "BOOKMARK_A_WRITE_FLUSHED sha256=" + digestA);
    options.printErr(marker + "BOOKMARK_MODEL_CLOSED");
    options.printErr(marker + "COOKIE_A_WRITE_FLUSHED sha256=" + digestA);
    options.printErr(marker + "COOKIE_BACKEND_CLOSED");
    options.printErr(marker + "HISTORY_A_WRITE_ACCEPTED");
    options.printErr(marker + "HISTORY_BACKEND_CLOSED");
    options.printErr(marker + "FENCE_OK sha256=" + digestA);
  } else if (globalThis.__ordinal === 2) {
    options.printErr(marker + "READ_A_OK sha256=" + digestA);
    options.printErr(marker + "WRITE_ACCEPTED sha256=" + digestB);
    options.printErr(marker + "BROWSER_SMOKE_CLOSED");
    options.printErr(marker + "BOOKMARK_A_READ_OK sha256=" + digestA);
    options.printErr(marker + "BOOKMARK_B_WRITE_FLUSHED sha256=" + digestB);
    options.printErr(marker + "BOOKMARK_MODEL_CLOSED");
    options.printErr(marker + "COOKIE_A_READ_OK sha256=" + digestA);
    options.printErr(marker + "COOKIE_B_WRITE_FLUSHED sha256=" + digestB);
    options.printErr(marker + "COOKIE_BACKEND_CLOSED");
    options.printErr(marker + "HISTORY_A_READ_OK");
    options.printErr(marker + "HISTORY_B_WRITE_ACCEPTED");
    options.printErr(marker + "HISTORY_BACKEND_CLOSED");
    options.printErr(marker + "FENCE_OK sha256=" + digestB);
  } else {
    options.printErr(marker + "READ_B_OK sha256=" + digestB);
    options.printErr(marker + "BROWSER_SMOKE_CLOSED");
    options.printErr(marker + "BOOKMARK_B_READ_OK sha256=" + digestB);
    options.printErr(marker + "BOOKMARK_CLEANUP_FLUSHED");
    options.printErr(marker + "BOOKMARK_MODEL_CLOSED");
    options.printErr(marker + "COOKIE_B_READ_OK sha256=" + digestB);
    options.printErr(marker + "COOKIE_BACKEND_CLOSED");
    options.printErr(marker + "HISTORY_A_READ_OK");
    options.printErr(marker + "HISTORY_B_READ_OK");
    options.printErr(marker + "HISTORY_BACKEND_CLOSED");
    options.printErr(marker + "FENCE_OK sha256=" + digestB);
  }
  options.printErr(marker + "LEASE_RELEASED");
  return module;
}
'''
    return (
        "import {runChromeWasmProfilePreferencesOuterReloadFromQuery} from "
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
const phaseTwoNavigationType = process.argv[4];
const bootstrapNavigationMode = process.argv[5];
if ((ordinal !== 1 && ordinal !== 2 && ordinal !== 3) ||
    (scenario !== "pass" && scenario !== "leak") ||
    !/^(?:2000|300000|300001)$/.test(timeoutMs) ||
    (phaseTwoNavigationType !== "navigate" &&
     phaseTwoNavigationType !== "reload") ||
    !["match", "navigate", "reload", "omit", "invalid"].includes(
        bootstrapNavigationMode)) {
  throw new Error("test input is invalid");
}
globalThis.__scenario = scenario;
globalThis.__ordinal = ordinal;
const expectedNavigationType = ordinal === 1 ? "navigate" :
    ordinal === 2 ? phaseTwoNavigationType : "reload";
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
      return name === "navigation" ? [{type: expectedNavigationType}] : [];
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
      ["#m7-profile-preferences-outer-reload-root", root],
      ["#m7-profile-preferences-outer-reload-canvas", canvas],
      ["#m7-profile-preferences-outer-reload-status", status],
      ["#m7-profile-preferences-outer-reload-versions", versionsElement],
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
  module_name: "chrome_wasm_m7_profile_preferences_test",
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
    "https://m7.test/__m7_chrome_profile_preferences_outer_reload__/?" + query);
if (location.href.includes(rawA) || location.href.includes(rawB)) {
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
const bootstrap = {
  protocol: 1,
  case: "chrome_profile_preferences_three_outer_document_persistence_m7",
  scope:
      "same-origin-three-outer-documents-chrome-wasm-m7-profile-preferences-bookmark-model-cookie-manager-and-history-test-modules-orderly-handoff-only",
  ordinal,
  mode: ordinal === 1 ? "write" : ordinal === 2 ? "verify-and-write" : "verify-b",
  ...(bootstrapExpectedNavigationType === null ? {} : {
    expectedNavigationType: bootstrapExpectedNavigationType,
  }),
  tokenA: ordinal === 3 ? null : rawA,
  tokenB: ordinal === 1 ? null : rawB,
  tokenADigest: ordinal === 3 ? null : await digest(new TextEncoder().encode(rawA)),
  tokenBDigest: ordinal === 1 ? null : await digest(new TextEncoder().encode(rawB)),
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
      const expectedType = expectedNavigationType;
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
const completed = await runChromeWasmProfilePreferencesOuterReloadFromQuery();
if (scenario === "pass") {
  if (bootstrapPosts !== 1 || bootstrapGets !== 1 || result === null || ready === null ||
      completed.status !== "pass" || result.status !== "pass" ||
      result.tokenEvidence.rawTokenLeakDetected !== false ||
      JSON.stringify(result).includes(rawA) || JSON.stringify(result).includes(rawB)) {
    throw new Error("passing host evidence is invalid");
  }
  process.stdout.write("pass\n");
} else {
  throw new Error("raw preference token leak was not rejected");
}
'''
    )


class M7ProfilePreferencesOuterReloadHostTest(unittest.TestCase):
    def run_fake_host(
        self,
        ordinal: int,
        scenario: str,
        timeout_ms: str = "2000",
        phase_two_navigation_type: str = "reload",
        bootstrap_navigation_mode: str = "match",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", "--input-type=module", "--eval", fake_host_script(),
             str(ordinal), scenario, timeout_ms, phase_two_navigation_type,
             bootstrap_navigation_mode],
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

    def test_accepts_fresh_outer_browser_verify_and_write_document(self) -> None:
        completed = self.run_fake_host(
            2, "pass", phase_two_navigation_type="navigate"
        )
        self.assertTrue(
            completed.returncode == 0,
            "fresh-outer-browser verify fake host failed",
        )
        self.assertEqual(completed.stdout, "pass\n")

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

    def test_accepts_verify_b_document(self) -> None:
        completed = self.run_fake_host(3, "pass")
        self.assertTrue(completed.returncode == 0, "verify-B fake host failed")
        self.assertEqual(completed.stdout, "pass\n")

    def test_rejects_cross_callback_raw_preference_leak_without_echo(self) -> None:
        completed = self.run_fake_host(1, "leak")
        self.assertNotEqual(completed.returncode, 0)
        opaque = "a" * 64
        self.assertFalse(opaque in completed.stdout, "raw token reached stdout")
        self.assertFalse(opaque in completed.stderr, "raw token reached stderr")

    def test_accepts_cold_start_timeout_and_rejects_a_larger_timeout(self) -> None:
        accepted = self.run_fake_host(1, "pass", "300000")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        rejected = self.run_fake_host(1, "pass", "300001")
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
        self.assertIn("HISTORY_BACKEND_CLOSED", source)
        self.assertIn("HISTORY_A_READ_OK", source)
        self.assertIn("HISTORY_B_READ_OK", source)
        self.assertIn("READ_B_OK", source)
        self.assertIn("<suppressed-native-output>", source)


if __name__ == "__main__":
    unittest.main()

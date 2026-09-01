#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Node contracts for the M7 selected-owner/default-partition shutdown host."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
HOST_URI = (
    TOOLS_DIR
    / "host"
    / "chrome_wasm_persistent_default_partition_shutdown_probe_smoke.js"
).as_uri()


def fake_host_script() -> str:
    loader_source = r'''
export default function(options) {
  const expected = "--wasm-persistent-default-partition-shutdown-probe=";
  if (!Array.isArray(options.arguments) || options.arguments.length !== 1 ||
      options.arguments[0] !== expected) {
    throw new Error("shutdown probe did not receive its exact empty switch");
  }
  // Emscripten prepends the program name to Module.arguments. Model that
  // behavior so this contract rejects a frozen or broadened argument array.
  options.arguments.unshift("chrome_wasm");
  if (options.arguments.length !== 2 || options.arguments[1] !== expected) {
    throw new Error("shutdown probe argument copy was not mutable and exact");
  }
  const module = {};
  options.onRuntimeInitialized.call(module);
  const shutdown = "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:";
  const retirement = "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:";
  options.printErr(shutdown + "DEFAULT_PARTITION_CREATED");
  if (globalThis.__scenario === "lease-release") {
    options.printErr(retirement + "LEASE_RELEASED");
  } else {
    if (globalThis.__scenario !== "missing-local-storage-map-update-close") {
      options.printErr(
          shutdown + "PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK");
    }
    if (globalThis.__scenario !== "missing-renderer-config-reuse") {
      options.printErr(
          shutdown + "RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK");
    }
    if (globalThis.__scenario !== "missing-indexed-db-close") {
      options.printErr(
          shutdown + "PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK");
    }
    options.printErr(shutdown + "PERSISTENT_COOKIE_WRITE_ACCEPTED");
    options.printErr(shutdown + "PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED");
    if (globalThis.__scenario !== "missing-cookie-sqlite-row-readback") {
      options.printErr(shutdown + "PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK");
    }
    if (globalThis.__scenario !== "missing-cookie-close") {
      options.printErr(shutdown + "PERSISTENT_COOKIE_STORE_CLOSED");
    }
    options.printErr(shutdown + "PARTITION_CREATION_SEALED");
    options.printErr(shutdown + "LATE_PARTITION_CREATION_REJECTED");
    if (globalThis.__scenario !== "missing-notification") {
      options.printErr(shutdown + "PARTITION_DESTROY_NOTIFICATION_DISPATCHED");
    }
    options.printErr(shutdown + "PARTITION_MAP_DROPPED");
    options.printErr(shutdown + "PREFERENCES_FENCE_OK");
    options.printErr(retirement + "SEALED_LEASE_RETAINED");
    options.printErr(shutdown + "FAIL_CLOSED_RETIREMENT");
  }
  globalThis.__chromiumWasmHostBridgeV1.reportProcessExit(
      {protocol: 1, exitCode: 23});
  options.onExit(23);
  if (globalThis.__scenario === "exit-status") {
    return Promise.reject({
      name: "ExitStatus",
      status: 23,
      message: "Program terminated with exit(23)",
    });
  }
  return Promise.resolve(module);
}
'''
    return (
        "import {runChromeWasmPersistentDefaultPartitionShutdownProbeFromQuery} "
        "from "
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
const scenario = process.argv[1];
if (!new Set(["resolved", "exit-status", "lease-release", "missing-local-storage-map-update-close", "missing-renderer-config-reuse", "missing-indexed-db-close", "missing-cookie-close", "missing-cookie-sqlite-row-readback", "missing-notification"]).has(scenario)) {
  throw new Error("test scenario is invalid");
}
globalThis.__scenario = scenario;
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
      ["#m7-persistent-default-partition-shutdown-probe-root", root],
      ["#m7-persistent-default-partition-shutdown-probe-canvas", canvas],
      ["#m7-persistent-default-partition-shutdown-probe-status", status],
      ["#m7-persistent-default-partition-shutdown-probe-versions", versionsElement],
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
async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (byte) => byte.toString(16).padStart(2, "0")).join("");
}
const loaderBytes = new TextEncoder().encode(loaderSource);
const wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
const artifact = {
  artifact_delivery: "immutable-in-memory-server-snapshot",
  artifact_source_provenance: "unverified",
  build_config: {bytes: 1, sha256: "a".repeat(64)},
  build_config_provenance: "selected-out-dir-args-gn-immutable-snapshot",
  loader: {bytes: loaderBytes.byteLength, sha256: await digest(loaderBytes)},
  module_name: "chrome_wasm_m7_persistent_default_partition_shutdown_probe",
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
  resultToken: "fake-shutdown-probe-result-capability-123456",
  timeoutMs: "20000",
  versions: JSON.stringify({
    chromium: "0".repeat(40),
    v8: "1".repeat(40),
    emscripten: "2".repeat(40),
  }),
  artifact: JSON.stringify(artifact),
  captureHarness: JSON.stringify(captureHarness),
});
const NativeURL = URL;
globalThis.location = new NativeURL(
    "https://m7.test/__m7_persistent_default_partition_shutdown_probe__/" +
    "?" + query);
globalThis.URL = class extends NativeURL {};
URL.createObjectURL = () =>
    "data:text/javascript;base64," + Buffer.from(loaderSource).toString("base64");
URL.revokeObjectURL = () => {};
function response(bytes, contentType) {
  const headers = new Headers({
    "Cache-Control": "no-store",
    "Content-Type": contentType,
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  });
  return {
    ok: true,
    headers,
    async arrayBuffer() {
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
let postedResult = null;
let postedAcknowledgement = null;
globalThis.fetch = async (url, options = {}) => {
  const href = String(url);
  if (href.endsWith(".js")) return response(loaderBytes, "text/javascript");
  if (href.endsWith(".wasm")) return response(wasmBytes, "application/wasm");
  if (href.includes("/result/")) {
    if (options.method !== "POST") throw new Error("result method is invalid");
    postedResult = JSON.parse(options.body);
    return {ok: true};
  }
  if (href.includes("/ack/")) {
    if (options.method !== "POST") throw new Error("ack method is invalid");
    postedAcknowledgement = JSON.parse(options.body);
    return {ok: true};
  }
  throw new Error("unexpected fetch: " + href);
};
const result = await runChromeWasmPersistentDefaultPartitionShutdownProbeFromQuery();
if (postedResult === null || postedAcknowledgement === null ||
    postedAcknowledgement.protocol !== 1 ||
    postedAcknowledgement.case !== "chrome_persistent_default_partition_shutdown_probe_m7") {
  throw new Error("host did not complete the result acknowledgement protocol");
}
if (scenario === "resolved" || scenario === "exit-status") {
  if (result.status !== "pass" || result.run.arguments.length !== 1 ||
      result.run.arguments[0] !==
          "--wasm-persistent-default-partition-shutdown-probe=" ||
      result.run.markers.join(",") !== [
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:DEFAULT_PARTITION_CREATED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PERSISTENT_COOKIE_WRITE_ACCEPTED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PERSISTENT_COOKIE_STORE_CLOSED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PARTITION_CREATION_SEALED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:LATE_PARTITION_CREATION_REJECTED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PARTITION_DESTROY_NOTIFICATION_DISPATCHED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PARTITION_MAP_DROPPED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:PREFERENCES_FENCE_OK",
        "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED",
        "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:FAIL_CLOSED_RETIREMENT",
      ].join(",") || result.run.processExitCount !== 1 ||
      result.run.processExitCode !== 23 || result.run.onExitCount !== 1 ||
      result.run.runtimeExitCode !== 23 || result.creationSealProven !== true ||
      result.persistentDefaultPartitionLocalStorageMapUpdateAndCloseReceiptProven !== true ||
      result.persistentDefaultPartitionRendererConfigReuseWitnessProven !== true ||
      result.persistentDefaultPartitionIndexedDBRendererWriteAndCloseReceiptProven !== true ||
      result.persistentDefaultPartitionCookieWriteAcceptedProven !== true ||
      result.persistentDefaultPartitionCookieStoreFlushAcknowledgedProven !== true ||
      result.persistentDefaultPartitionCookieSQLiteRowReadbackProven !== true ||
      result.persistentDefaultPartitionCookieStoreCloseReceiptProven !== true ||
      result.partitionDestroyNotificationDispatchedProven !== true ||
      result.aggregatePartitionCloseProven !== false ||
      result.durableProfileFlushProven !== false ||
      result.profilePersistenceProven !== false ||
      result.freshDocumentReloadProven !== false ||
      result.crashRecoveryProven !== false) {
    throw new Error("host accepted an invalid structural shutdown receipt");
  }
  if (scenario === "exit-status" &&
      result.run.factoryOutcome !== "expected-nonzero-exit-status") {
    throw new Error("host did not accept the exact nonzero ExitStatus");
  }
  if (root.dataset.state !== "pass" || status.textContent !== "pass") {
    throw new Error("host did not publish pass state");
  }
} else if (scenario === "lease-release") {
  if (result.status !== "fail" || result.run.leaseReleasedMarkerObserved !== true ||
      result.run.markers.length !== 1 || root.dataset.state !== "fail") {
    throw new Error("host accepted a lease release marker");
  }
} else if (scenario === "missing-local-storage-map-update-close") {
  if (result.status !== "fail" || result.run.leaseReleasedMarkerObserved !== false ||
      result.run.markers.length !== 1 || root.dataset.state !== "fail") {
    throw new Error("host accepted a missing LocalStorage map-update-and-close receipt");
  }
} else if (scenario === "missing-renderer-config-reuse") {
  if (result.status !== "fail" || result.run.leaseReleasedMarkerObserved !== false ||
      result.run.markers.length !== 2 || root.dataset.state !== "fail") {
    throw new Error("host accepted a missing renderer config-reuse receipt");
  }
} else if (scenario === "missing-indexed-db-close") {
  if (result.status !== "fail" || result.run.leaseReleasedMarkerObserved !== false ||
      result.run.markers.length !== 3 || root.dataset.state !== "fail") {
    throw new Error("host accepted a missing renderer IndexedDB close receipt");
  }
} else if (scenario === "missing-cookie-close") {
  if (result.status !== "fail" || result.run.leaseReleasedMarkerObserved !== false ||
      result.run.markers.length !== 7 || root.dataset.state !== "fail") {
    throw new Error("host accepted a missing CookieManager close receipt");
  }
} else if (scenario === "missing-cookie-sqlite-row-readback") {
  if (result.status !== "fail" || result.run.leaseReleasedMarkerObserved !== false ||
      result.run.markers.length !== 6 || root.dataset.state !== "fail") {
    throw new Error("host accepted a missing network-owned SQLite row readback receipt");
  }
} else {
  if (result.status !== "fail" || result.run.leaseReleasedMarkerObserved !== false ||
      result.run.markers.length !== 10 || root.dataset.state !== "fail") {
    throw new Error("host accepted a missing destruction-notification receipt");
  }
}
'''
    )


class M7PersistentDefaultPartitionShutdownProbeHostTest(unittest.TestCase):
    def test_host_binds_each_selected_owner_and_structural_claim_to_its_named_receipt(
        self,
    ) -> None:
        source = (TOOLS_DIR / "host" / (
            "chrome_wasm_persistent_default_partition_shutdown_probe_smoke.js"
        )).read_text(encoding="utf-8")

        self.assertIn(
            "this.run.markers[0] === DEFAULT_PARTITION_CREATED_MARKER", source
        )
        self.assertIn(
            "this.run.markers[1] ===\n"
            "              PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[2] ===\n"
            "              RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[3] ===\n"
            "              PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[4] === PERSISTENT_COOKIE_WRITE_ACCEPTED_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[5] ===\n"
            "              PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[6] === PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[7] === PERSISTENT_COOKIE_STORE_CLOSED_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[8] === PARTITION_CREATION_SEALED_MARKER", source
        )
        self.assertIn(
            "this.run.markers[10] === PARTITION_DESTROY_NOTIFICATION_DISPATCHED_MARKER",
            source,
        )
        self.assertIn(
            "this.run.markers[11] === PARTITION_MAP_DROPPED_MARKER", source
        )
        self.assertIn(
            "this.run.markers[12] === PREFERENCES_FENCE_OK_MARKER", source
        )
        self.assertIn(
            "this.run.markers[13] === SEALED_LEASE_RETAINED_MARKER", source
        )
        self.assertIn(
            "this.run.markers[14] === FAIL_CLOSED_RETIREMENT_MARKER", source
        )
        self.assertIn(
            "stderr-only-fixed-selected-local-storage-renderer-indexed-db-and-cookie-shutdown-grammar",
            source,
        )

    def run_scenario(self, scenario: str) -> None:
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", fake_host_script(), scenario],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_host_accepts_the_exact_fifteen_marker_selected_owner_shutdown_receipt(
        self,
    ) -> None:
        self.run_scenario("resolved")

    def test_host_accepts_an_exact_matching_nonzero_exit_status(self) -> None:
        self.run_scenario("exit-status")

    def test_host_rejects_a_clean_lease_release_marker_but_acks_receipt(self) -> None:
        self.run_scenario("lease-release")

    def test_host_rejects_a_missing_local_storage_map_update_close_receipt(
        self,
    ) -> None:
        self.run_scenario("missing-local-storage-map-update-close")

    def test_host_rejects_a_missing_renderer_config_reuse_receipt(self) -> None:
        self.run_scenario("missing-renderer-config-reuse")

    def test_host_rejects_a_missing_renderer_indexed_db_close_receipt(self) -> None:
        self.run_scenario("missing-indexed-db-close")

    def test_host_rejects_a_missing_cookie_close_receipt(self) -> None:
        self.run_scenario("missing-cookie-close")

    def test_host_rejects_a_missing_network_owned_sqlite_row_readback_receipt(
        self,
    ) -> None:
        self.run_scenario("missing-cookie-sqlite-row-readback")

    def test_host_rejects_a_missing_destruction_notification_receipt(self) -> None:
        self.run_scenario("missing-notification")


if __name__ == "__main__":
    unittest.main()

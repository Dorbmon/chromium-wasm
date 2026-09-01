// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A one-document shutdown probe. Chromium constructs the real persistent
// default StoragePartition, receives one direct LocalStorage map-update/close
// receipt, one captured-config renderer IndexedDB write/selected-bucket-close
// receipt,
// then one selected CookieManager write/flush, network-owned SQLite
// row-readback, and backend-close receipt, then receives its real
// destruction notification return before its
// StoragePartitionImplMap is absent, fences preferences, and deliberately
// selects sealed/lease-retained failure retirement. This host verifies only
// fixed stderr receipts and the clean nonzero process-exit acknowledgement. It
// neither opens OPFS nor makes a durable profile flush, aggregate-close,
// reload, recovery, or permanent-map-absence claim.

const HOST_PROTOCOL = 1;
const CASE = "chrome_persistent_default_partition_shutdown_probe_m7";
const SCOPE =
    "one-fresh-source-selected-chrome-wasm-persistent-default-partition-" +
    "local-storage-map-update-close-renderer-indexed-db-write-close-" +
    "cookie-write-flush-sqlite-row-readback-" +
    "close-destruction-notification-" +
    "return-map-fail-closed-retirement-" +
    "observation-only-no-durable-profile-claim";
const PRODUCT_MODULE_NAME =
    "chrome_wasm_m7_persistent_default_partition_shutdown_probe";
export const EXACT_EMPTY_PROBE_SWITCH =
    "--wasm-persistent-default-partition-shutdown-probe=";
const EXACT_PROBE_ARGUMENTS = Object.freeze([EXACT_EMPTY_PROBE_SWITCH]);
const SHUTDOWN_MARKER_PREFIX =
    "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_SHUTDOWN:";
const SHUTDOWN_FAIL_PREFIX = SHUTDOWN_MARKER_PREFIX + "FAIL stage=";
const FAILURE_RETIREMENT_PREFIX = "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:";
const DEFAULT_PARTITION_CREATED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "DEFAULT_PARTITION_CREATED";
const PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK_MARKER =
    SHUTDOWN_MARKER_PREFIX +
    "PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK";
const RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK_MARKER =
    SHUTDOWN_MARKER_PREFIX +
    "RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK";
const PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK_MARKER =
    SHUTDOWN_MARKER_PREFIX +
    "PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK";
const PERSISTENT_COOKIE_WRITE_ACCEPTED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_WRITE_ACCEPTED";
const PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED";
const PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK";
const PERSISTENT_COOKIE_STORE_CLOSED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PERSISTENT_COOKIE_STORE_CLOSED";
const PARTITION_CREATION_SEALED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PARTITION_CREATION_SEALED";
const LATE_PARTITION_CREATION_REJECTED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "LATE_PARTITION_CREATION_REJECTED";
const PARTITION_DESTROY_NOTIFICATION_DISPATCHED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PARTITION_DESTROY_NOTIFICATION_DISPATCHED";
const PARTITION_MAP_DROPPED_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PARTITION_MAP_DROPPED";
const PREFERENCES_FENCE_OK_MARKER =
    SHUTDOWN_MARKER_PREFIX + "PREFERENCES_FENCE_OK";
const SEALED_LEASE_RETAINED_MARKER =
    FAILURE_RETIREMENT_PREFIX + "SEALED_LEASE_RETAINED";
const LEASE_RELEASED_MARKER = FAILURE_RETIREMENT_PREFIX + "LEASE_RELEASED";
const FAIL_CLOSED_RETIREMENT_MARKER =
    SHUTDOWN_MARKER_PREFIX + "FAIL_CLOSED_RETIREMENT";
const EXPECTED_MARKERS = Object.freeze([
  DEFAULT_PARTITION_CREATED_MARKER,
  PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK_MARKER,
  RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK_MARKER,
  PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK_MARKER,
  PERSISTENT_COOKIE_WRITE_ACCEPTED_MARKER,
  PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED_MARKER,
  PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK_MARKER,
  PERSISTENT_COOKIE_STORE_CLOSED_MARKER,
  PARTITION_CREATION_SEALED_MARKER,
  LATE_PARTITION_CREATION_REJECTED_MARKER,
  PARTITION_DESTROY_NOTIFICATION_DISPATCHED_MARKER,
  PARTITION_MAP_DROPPED_MARKER,
  PREFERENCES_FENCE_OK_MARKER,
  SEALED_LEASE_RETAINED_MARKER,
  FAIL_CLOSED_RETIREMENT_MARKER,
]);
const MAX_TIMEOUT_MS = 300000;
const FINAL_QUIESCENCE_MS = 50;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const GIT_REVISION_RE = /^[0-9a-f]{40}$/;

const RESULT_FIELDS = Object.freeze([
  "actualPersistentDefaultPartitionCreatedProven",
  "aggregatePartitionCloseProven", "artifact", "bridge", "capture_harness",
  "case", "crashRecoveryProven", "creationSealProven",
  "crossOriginIsolated", "durableProfileFlushProven", "error",
  "exactEmptyProbeSwitchPassed", "failClosedRetirementProven",
  "freshDocumentReloadProven",
  "freshSourceSelectedShutdownArtifactProven", "hostBoundary",
  "m7GateComplete", "nonzeroProcessExitAndAckProven",
  "partitionDestroyNotificationDispatchedProven", "partitionMapDroppedProven",
  "persistentDefaultPartitionCookieSQLiteRowReadbackProven",
  "persistentDefaultPartitionCookieStoreCloseReceiptProven",
  "persistentDefaultPartitionCookieStoreFlushAcknowledgedProven",
  "persistentDefaultPartitionCookieWriteAcceptedProven",
  "persistentDefaultPartitionIndexedDBRendererWriteAndCloseReceiptProven",
  "persistentDefaultPartitionLocalStorageMapUpdateAndCloseReceiptProven",
  "persistentDefaultPartitionRendererConfigReuseWitnessProven",
  "preferencesFenceProven",
  "profilePersistenceProven", "profileStorageLeaseReleasedProven", "protocol",
  "quiescence", "run", "scope", "sealedLeaseRetainedReceiptProven",
  "sharedArrayBuffer", "status", "structuralShutdownWitnessProven", "versions",
  "origin",
]);
const RUN_FIELDS = Object.freeze([
  "arguments", "abortObserved", "factoryOutcome", "factorySettled",
  "freshModuleObject", "leaseReleasedMarkerObserved", "markerCount",
  "markerSequenceAccepted", "markerSource", "markers", "noFailMarkerObserved",
  "nonzeroProcessExitAndAckReceived", "onExitCount",
  "processExitBeforeOnExit", "processExitCode", "processExitCount",
  "runtimeExitCode", "runtimeInitialized", "stdoutMarkerCount",
  "unexpectedMarkerObserved",
]);
const BRIDGE_FIELDS = Object.freeze([
  "activeAtResult", "duplicateProcessExitRejected", "frozen",
  "installedBeforeModuleFactory", "noActiveProcessExitRejected", "permanent",
  "processExitDispatches", "protocol",
]);
const QUIESCENCE_FIELDS = Object.freeze([
  "callbacksAfterQuietWindow", "callbacksAtLifecycleComplete", "quiet",
  "quietWindowMs",
]);
const HOST_BOUNDARY_FIELDS = Object.freeze([
  "hostDomStorageAccessAttempted", "hostOpfsAccessAttempted",
  "hostWebLocksAccessAttempted", "nativeCallAttempted",
  "wasmDataInspectionAttempted",
]);
const ARTIFACT_FIELDS = Object.freeze([
  "artifact_delivery", "artifact_source_provenance", "build_config",
  "build_config_provenance", "loader", "module_name", "wasm",
]);
const CAPTURE_HARNESS_FIELDS = Object.freeze([
  "host_html", "host_js", "runner_source", "source_snapshot_provenance",
  "version_provenance",
]);

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function requireExactFields(value, fields, description) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== fields.length ||
      !fields.every((field) => Object.hasOwn(value, field))) {
    throw new Error(`${description} has an invalid schema`);
  }
  return value;
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} is invalid`);
  }
  return value;
}

function parseQueryJson(value, description) {
  try {
    return JSON.parse(asNonemptyString(value, description));
  } catch (_error) {
    throw new Error(`${description} is invalid`);
  }
}

function parseTimeout(value) {
  if (typeof value !== "string" || !/^[0-9]+$/.test(value)) {
    throw new Error("structural shutdown probe timeout is invalid");
  }
  const timeout = Number(value);
  if (!Number.isSafeInteger(timeout) || timeout < 20000 ||
      timeout > MAX_TIMEOUT_MS) {
    throw new Error("structural shutdown probe timeout is invalid");
  }
  return timeout;
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, ["bytes", "sha256"], description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifact(value) {
  const artifact = requireExactFields(
      parseQueryJson(value, "structural shutdown probe artifact"), ARTIFACT_FIELDS,
      "structural shutdown probe artifact");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error("structural shutdown probe artifact is invalid");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    build_config: parseByteIdentity(artifact.build_config, "structural shutdown args"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "structural shutdown loader"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "structural shutdown Wasm"),
  });
}

function parseCaptureHarness(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "structural shutdown probe capture harness"),
      CAPTURE_HARNESS_FIELDS, "structural shutdown probe capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("structural shutdown probe capture harness is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html, "structural shutdown host HTML"),
    host_js: parseByteIdentity(harness.host_js, "structural shutdown host JavaScript"),
    runner_source: parseByteIdentity(harness.runner_source,
                                    "structural shutdown runner source"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = requireExactFields(
      parseQueryJson(value, "structural shutdown probe versions"),
      ["chromium", "v8", "emscripten"], "structural shutdown probe versions");
  if (Object.values(versions).some((revision) =>
      typeof revision !== "string" || !GIT_REVISION_RE.test(revision))) {
    throw new Error("structural shutdown probe versions are invalid");
  }
  return Object.freeze({...versions});
}

function parseContext() {
  const query = new URLSearchParams(location.search);
  const allowed = new Set([
    "resultToken", "timeoutMs", "versions", "artifact", "captureHarness",
  ]);
  for (const key of query.keys()) {
    if (!allowed.has(key) || query.getAll(key).length !== 1) {
      throw new Error("structural shutdown probe query is invalid");
    }
  }
  const resultToken = asNonemptyString(
      query.get("resultToken"), "structural shutdown probe result capability");
  if (!CAPABILITY_RE.test(resultToken)) {
    throw new Error("structural shutdown probe result capability is invalid");
  }
  return Object.freeze({
    artifact: parseArtifact(query.get("artifact")),
    captureHarness: parseCaptureHarness(query.get("captureHarness")),
    resultToken,
    timeoutMs: parseTimeout(query.get("timeoutMs")),
    versions: parseVersions(query.get("versions")),
  });
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(bytes, description) {
  if (!(bytes instanceof Uint8Array) || !globalThis.crypto?.subtle) {
    throw new Error(`${description} requires Web Crypto SHA-256`);
  }
  let digest;
  try {
    digest = await crypto.subtle.digest("SHA-256", bytes);
  } catch (_error) {
    throw new Error(`${description} SHA-256 failed`);
  }
  return hex(new Uint8Array(digest));
}

function requireResponseHeaders(response, expectedContentType, description) {
  const actualContentType = response.headers.get("Content-Type")
      ?.split(";", 1)[0].trim().toLowerCase();
  const required = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if (actualContentType !== expectedContentType || Object.entries(required).some(
      ([name, expected]) => response.headers.get(name) !== expected)) {
    throw new Error(`${description} response headers are invalid`);
  }
}

async function fetchVerifiedArtifact(url, identity, contentType, description) {
  const response = await fetch(url.href, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) throw new Error(`${description} request is invalid`);
  requireResponseHeaders(response, contentType, description);
  let buffer;
  try {
    buffer = await response.arrayBuffer();
  } catch (_error) {
    throw new Error(`${description} body is invalid`);
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} identity is invalid`);
  }
  return bytes;
}

function asReport(value, description) {
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch (_error) {
      throw new Error(`${description} is invalid`);
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${description} is invalid`);
  }
  return value;
}

// Return the exact clean nonzero exit code carried by an Emscripten
// ExitStatus object. The rejected value must consist only of ordinary own data
// fields, so a foreign rejection cannot run getters while being inspected.
function exactNonzeroExitStatus(value) {
  try {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const fields = ["name", "status", "message"];
    const keys = Reflect.ownKeys(descriptors);
    if (keys.length !== fields.length ||
        keys.some((key) => typeof key !== "string" || !fields.includes(key)) ||
        !fields.every((field) => {
          const descriptor = descriptors[field];
          return descriptor !== undefined && Object.hasOwn(descriptor, "value") &&
              !Object.hasOwn(descriptor, "get") && !Object.hasOwn(descriptor, "set");
        })) {
      return null;
    }
    const status = descriptors.status.value;
    if (!Number.isSafeInteger(status) || status <= 0 || status > 255 ||
        descriptors.name.value !== "ExitStatus" ||
        descriptors.message.value !== `Program terminated with exit(${status})`) {
      return null;
    }
    return status;
  } catch (_error) {
    return null;
  }
}

function hasExactProcessExitReport(value) {
  try {
    const report = asReport(value, "process-exit report");
    return Object.keys(report).length === 2 && report.protocol === HOST_PROTOCOL &&
        Number.isSafeInteger(report.exitCode) && report.exitCode > 0 &&
        report.exitCode <= 255 && Object.hasOwn(report, "protocol") &&
        Object.hasOwn(report, "exitCode");
  } catch (_error) {
    return false;
  }
}

function newRun() {
  return {
    abortObserved: false,
    factoryOutcome: null,
    factorySettled: false,
    freshModuleObject: false,
    leaseReleasedMarkerObserved: false,
    markerSequenceAccepted: true,
    markers: [],
    noFailMarkerObserved: true,
    onExitCount: 0,
    processExitBeforeOnExit: false,
    processExitCode: null,
    processExitCount: 0,
    runtimeExitCode: null,
    runtimeInitialized: false,
    stdoutMarkerCount: 0,
    unexpectedMarkerObserved: false,
  };
}

class PersistentDefaultPartitionShutdownProbeHost {
  constructor(canvas, context) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("structural shutdown probe requires a canvas");
    }
    this.canvas = canvas;
    this.context = context;
    this.run = newRun();
    this.active = false;
    this.lifecycleCompleted = false;
    this.bridgeInstalled = false;
    this.callbackCount = 0;
    this.failure = false;
    this.windowErrorCount = 0;
    this.unhandledRejectionCount = 0;
    this.processExitDispatches = 0;
    this.noActiveProcessExitRejected = 0;
    this.duplicateProcessExitRejected = 0;
    this.factoryExitStatusCode = null;
    this.loaderImportUrl = null;
    this.errorHandler = null;
    this.rejectionHandler = null;
  }

  noteCallback() {
    ++this.callbackCount;
  }

  fail() {
    this.failure = true;
  }

  installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("structural shutdown probe bridge is already installed");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(_message) { host.noteCallback(); host.fail(); },
      reportProcessExit(report) { host.reportProcessExit(report); },
      reportFrame(_report) { host.noteCallback(); },
      reportReadiness(_report) { host.noteCallback(); },
      reportOzoneFocusState(_report) { host.noteCallback(); },
      reportOzoneCursor(_report) { host.noteCallback(); return true; },
      reportOzoneTextInputState(_report) { host.noteCallback(); },
      reportOzoneTextInputDelivery(_report) { host.noteCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) { host.noteCallback(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) { host.noteCallback(); },
      requestOuterOriginStorageEstimate(_report) {
        host.noteCallback();
        return false;
      },
      reportAccessibilitySnapshot(_report) { host.noteCallback(); return false; },
    });
    Object.defineProperty(globalThis, "__chromiumWasmHostBridgeV1", {
      configurable: false,
      enumerable: false,
      value: bridge,
      writable: false,
    });
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge ||
        !Object.isFrozen(bridge)) {
      throw new Error("structural shutdown probe bridge is mutable");
    }
    this.bridgeInstalled = true;
  }

  installFailureObservers() {
    this.errorHandler = () => {
      this.noteCallback();
      ++this.windowErrorCount;
      this.fail();
    };
    this.rejectionHandler = (event) => {
      this.noteCallback();
      const status = exactNonzeroExitStatus(event?.reason);
      if (status !== null && this.active &&
          this.run.processExitCode === status && this.run.onExitCount === 1 &&
          typeof event?.preventDefault === "function") {
        event.preventDefault();
        return;
      }
      ++this.unhandledRejectionCount;
      this.fail();
    };
    globalThis.addEventListener("error", this.errorHandler);
    globalThis.addEventListener("unhandledrejection", this.rejectionHandler);
  }

  releaseFailureObservers() {
    if (this.errorHandler !== null) {
      globalThis.removeEventListener("error", this.errorHandler);
      this.errorHandler = null;
    }
    if (this.rejectionHandler !== null) {
      globalThis.removeEventListener("unhandledrejection", this.rejectionHandler);
      this.rejectionHandler = null;
    }
  }

  reportProcessExit(value) {
    this.noteCallback();
    if (!this.active) {
      ++this.noActiveProcessExitRejected;
      this.fail();
      return;
    }
    if (this.run.processExitCount !== 0) {
      ++this.duplicateProcessExitRejected;
      this.fail();
      return;
    }
    if (!hasExactProcessExitReport(value)) {
      this.fail();
      return;
    }
    const report = asReport(value, "process-exit report");
    this.run.processExitCount = 1;
    this.run.processExitCode = report.exitCode;
    ++this.processExitDispatches;
  }

  reportRuntimeInitialized(module) {
    this.noteCallback();
    if (!this.active || this.run.runtimeInitialized || !module ||
        (typeof module !== "object" && typeof module !== "function")) {
      this.fail();
      return;
    }
    this.run.runtimeInitialized = true;
    this.run.freshModuleObject = true;
  }

  reportRuntimeExit(code) {
    this.noteCallback();
    if (!this.active || !Number.isSafeInteger(code) || code <= 0 || code > 255 ||
        this.run.onExitCount !== 0 || this.run.processExitCount !== 1 ||
        this.run.processExitCode !== code) {
      this.fail();
      return;
    }
    this.run.processExitBeforeOnExit = true;
    this.run.onExitCount = 1;
    this.run.runtimeExitCode = code;
  }

  reportAbort(_reason) {
    this.noteCallback();
    if (this.run.abortObserved) this.fail();
    this.run.abortObserved = true;
    this.fail();
  }

  captureOutput(destination, line) {
    this.noteCallback();
    if (!this.active || typeof line !== "string") {
      this.fail();
      return;
    }
    const isShutdownMarker = line.startsWith(SHUTDOWN_MARKER_PREFIX);
    const isRetirementMarker = line.startsWith(FAILURE_RETIREMENT_PREFIX);
    if (!isShutdownMarker && !isRetirementMarker) return;
    if (destination !== "stderr") {
      ++this.run.stdoutMarkerCount;
      this.fail();
      return;
    }
    if (line.startsWith(SHUTDOWN_FAIL_PREFIX)) {
      this.run.noFailMarkerObserved = false;
      this.fail();
      return;
    }
    if (line === LEASE_RELEASED_MARKER) {
      this.run.leaseReleasedMarkerObserved = true;
      this.fail();
      return;
    }
    const index = this.run.markers.length;
    if (index >= EXPECTED_MARKERS.length || line !== EXPECTED_MARKERS[index]) {
      this.run.markerSequenceAccepted = false;
      this.run.unexpectedMarkerObserved = true;
      this.fail();
      return;
    }
    this.run.markers.push(line);
  }

  settleFactoryResolved(module) {
    this.noteCallback();
    if (!this.active || this.run.factorySettled || !module ||
        (typeof module !== "object" && typeof module !== "function")) {
      this.fail();
      return;
    }
    this.run.factorySettled = true;
    this.run.factoryOutcome = "resolved";
  }

  settleFactoryRejected(error) {
    this.noteCallback();
    if (!this.active || this.run.factorySettled) {
      this.fail();
      return;
    }
    const status = exactNonzeroExitStatus(error);
    this.run.factorySettled = true;
    if (status === null) {
      this.fail();
      return;
    }
    this.factoryExitStatusCode = status;
    this.run.factoryOutcome = "expected-nonzero-exit-status";
  }

  lifecycleReady() {
    const settledAsExpected = this.run.factoryOutcome === "resolved" ||
        (this.run.factoryOutcome === "expected-nonzero-exit-status" &&
         this.factoryExitStatusCode === this.run.processExitCode);
    return !this.failure && this.active && this.run.runtimeInitialized &&
        this.run.factorySettled && settledAsExpected &&
        this.run.markers.length === EXPECTED_MARKERS.length &&
        this.run.markers.every((marker, index) => marker === EXPECTED_MARKERS[index]) &&
        this.run.markerSequenceAccepted && this.run.noFailMarkerObserved &&
        !this.run.leaseReleasedMarkerObserved && !this.run.unexpectedMarkerObserved &&
        !this.run.abortObserved && this.run.processExitCount === 1 &&
        Number.isSafeInteger(this.run.processExitCode) && this.run.processExitCode > 0 &&
        this.run.onExitCount === 1 &&
        this.run.runtimeExitCode === this.run.processExitCode &&
        this.run.processExitBeforeOnExit && this.processExitDispatches === 1 &&
        this.windowErrorCount === 0 && this.unhandledRejectionCount === 0;
  }

  async prepareFactory() {
    const loaderUrl = new URL(
        `./artifacts/${PRODUCT_MODULE_NAME}.js`, location.href);
    const wasmUrl = new URL(
        `./artifacts/${PRODUCT_MODULE_NAME}.wasm`, location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("structural shutdown probe artifact origin is invalid");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(loaderUrl, this.context.artifact.loader,
                            "text/javascript", "structural shutdown loader"),
      fetchVerifiedArtifact(wasmUrl, this.context.artifact.wasm,
                            "application/wasm", "structural shutdown Wasm"),
    ]);
    if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("structural shutdown fresh loader import is unavailable");
    }
    this.loaderImportUrl = URL.createObjectURL(
        new Blob([loaderBytes], {type: "text/javascript"}));
    let namespace;
    try {
      namespace = await import(this.loaderImportUrl);
    } catch (error) {
      URL.revokeObjectURL(this.loaderImportUrl);
      this.loaderImportUrl = null;
      throw error;
    }
    if (typeof namespace.default !== "function") {
      URL.revokeObjectURL(this.loaderImportUrl);
      this.loaderImportUrl = null;
      throw new Error("structural shutdown loader has no default factory export");
    }
    return {factory: namespace.default, wasmBinary: wasmBytes, wasmUrl};
  }

  result(status, error, quiescence) {
    const lifecycleComplete = this.lifecycleCompleted;
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m7GateComplete: false,
      origin: location.origin,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      artifact: this.context.artifact,
      capture_harness: this.context.captureHarness,
      versions: this.context.versions,
      exactEmptyProbeSwitchPassed: true,
      freshSourceSelectedShutdownArtifactProven: true,
      actualPersistentDefaultPartitionCreatedProven:
          lifecycleComplete &&
          this.run.markers[0] === DEFAULT_PARTITION_CREATED_MARKER,
      persistentDefaultPartitionLocalStorageMapUpdateAndCloseReceiptProven:
          lifecycleComplete &&
          this.run.markers[1] ===
              PERSISTENT_LOCAL_STORAGE_ON_DISK_MAP_UPDATE_AND_CLOSE_OK_MARKER,
      persistentDefaultPartitionRendererConfigReuseWitnessProven:
          lifecycleComplete &&
          this.run.markers[2] ===
              RENDERER_DEFAULT_PARTITION_CONFIG_REUSE_WITNESS_OK_MARKER,
      persistentDefaultPartitionIndexedDBRendererWriteAndCloseReceiptProven:
          lifecycleComplete &&
          this.run.markers[3] ===
              PERSISTENT_INDEXED_DB_RENDERER_WRITE_AND_CLOSE_OK_MARKER,
      persistentDefaultPartitionCookieWriteAcceptedProven:
          lifecycleComplete &&
          this.run.markers[4] === PERSISTENT_COOKIE_WRITE_ACCEPTED_MARKER,
      persistentDefaultPartitionCookieStoreFlushAcknowledgedProven:
          lifecycleComplete &&
          this.run.markers[5] ===
              PERSISTENT_COOKIE_STORE_FLUSH_ACKNOWLEDGED_MARKER,
      persistentDefaultPartitionCookieSQLiteRowReadbackProven:
          lifecycleComplete &&
          this.run.markers[6] === PERSISTENT_COOKIE_SQLITE_ROW_READBACK_OK_MARKER,
      persistentDefaultPartitionCookieStoreCloseReceiptProven:
          lifecycleComplete &&
          this.run.markers[7] === PERSISTENT_COOKIE_STORE_CLOSED_MARKER,
      creationSealProven:
          lifecycleComplete &&
          this.run.markers[8] === PARTITION_CREATION_SEALED_MARKER,
      partitionDestroyNotificationDispatchedProven:
          lifecycleComplete &&
          this.run.markers[10] === PARTITION_DESTROY_NOTIFICATION_DISPATCHED_MARKER,
      partitionMapDroppedProven:
          lifecycleComplete &&
          this.run.markers[11] === PARTITION_MAP_DROPPED_MARKER,
      preferencesFenceProven:
          lifecycleComplete && this.run.markers[12] === PREFERENCES_FENCE_OK_MARKER,
      sealedLeaseRetainedReceiptProven:
          lifecycleComplete &&
          this.run.markers[13] === SEALED_LEASE_RETAINED_MARKER,
      failClosedRetirementProven:
          lifecycleComplete &&
          this.run.markers[14] === FAIL_CLOSED_RETIREMENT_MARKER,
      structuralShutdownWitnessProven: lifecycleComplete,
      nonzeroProcessExitAndAckProven: lifecycleComplete,
      aggregatePartitionCloseProven: false,
      durableProfileFlushProven: false,
      profilePersistenceProven: false,
      profileStorageLeaseReleasedProven: false,
      freshDocumentReloadProven: false,
      crashRecoveryProven: false,
      hostBoundary: {
        hostDomStorageAccessAttempted: false,
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        nativeCallAttempted: false,
        wasmDataInspectionAttempted: false,
      },
      run: {
        arguments: Array.from(EXACT_PROBE_ARGUMENTS),
        abortObserved: this.run.abortObserved,
        factoryOutcome: this.run.factoryOutcome,
        factorySettled: this.run.factorySettled,
        freshModuleObject: this.run.freshModuleObject,
        leaseReleasedMarkerObserved: this.run.leaseReleasedMarkerObserved,
        markerCount: this.run.markers.length,
        markerSequenceAccepted: this.run.markerSequenceAccepted,
        markerSource:
            "stderr-only-fixed-selected-local-storage-renderer-indexed-db-and-cookie-shutdown-grammar",
        markers: this.run.markers.slice(),
        noFailMarkerObserved: this.run.noFailMarkerObserved,
        nonzeroProcessExitAndAckReceived: lifecycleComplete,
        onExitCount: this.run.onExitCount,
        processExitBeforeOnExit: this.run.processExitBeforeOnExit,
        processExitCode: this.run.processExitCode,
        processExitCount: this.run.processExitCount,
        runtimeExitCode: this.run.runtimeExitCode,
        runtimeInitialized: this.run.runtimeInitialized,
        stdoutMarkerCount: this.run.stdoutMarkerCount,
        unexpectedMarkerObserved: this.run.unexpectedMarkerObserved,
      },
      bridge: {
        activeAtResult: this.active,
        duplicateProcessExitRejected: this.duplicateProcessExitRejected,
        frozen: this.bridgeInstalled &&
            Object.isFrozen(globalThis.__chromiumWasmHostBridgeV1),
        installedBeforeModuleFactory: this.bridgeInstalled,
        noActiveProcessExitRejected: this.noActiveProcessExitRejected,
        permanent: true,
        processExitDispatches: this.processExitDispatches,
        protocol: HOST_PROTOCOL,
      },
      quiescence,
      error,
    };
  }

  async runProbe() {
    let quiescence = {
      callbacksAfterQuietWindow: null,
      callbacksAtLifecycleComplete: null,
      quiet: false,
      quietWindowMs: FINAL_QUIESCENCE_MS,
    };
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function") {
        throw new Error("structural shutdown probe requires cross-origin isolation");
      }
      this.canvas.focus({preventScroll: true});
      if (document.activeElement !== this.canvas) {
        throw new Error("structural shutdown probe canvas focus failed");
      }
      this.installBridge();
      this.installFailureObservers();
      const prepared = await this.prepareFactory();
      this.active = true;
      const host = this;
      let factoryResult;
      try {
        factoryResult = prepared.factory({
          // Emscripten prepends its program name to Module.arguments. Preserve
          // the immutable one-switch contract while giving its loader a copy.
          arguments: Array.from(EXACT_PROBE_ARGUMENTS),
          canvas: this.canvas,
          locateFile(path) {
            if (path !== PRODUCT_MODULE_NAME + ".wasm") {
              throw new Error("structural shutdown loader requested an unexpected artifact");
            }
            return prepared.wasmUrl.href;
          },
          mainScriptUrlOrBlob: this.loaderImportUrl,
          noExitRuntime: false,
          onAbort(reason) { host.reportAbort(reason); },
          onExit(code) { host.reportRuntimeExit(Number(code)); },
          onRuntimeInitialized() { host.reportRuntimeInitialized(this); },
          print(line) { host.captureOutput("stdout", line); },
          printErr(line) { host.captureOutput("stderr", line); },
          wasmBinary: prepared.wasmBinary,
        });
      } catch (error) {
        this.settleFactoryRejected(error);
        factoryResult = null;
      }
      if (factoryResult !== null) {
        Promise.resolve(factoryResult).then(
            (module) => host.settleFactoryResolved(module),
            (error) => host.settleFactoryRejected(error));
      }
      const deadline = performance.now() + this.context.timeoutMs;
      while (performance.now() < deadline && !this.failure &&
             !this.lifecycleReady()) {
        await delay(10);
      }
      if (!this.lifecycleReady()) {
        this.fail();
        return this.result("fail", "details-suppressed", quiescence);
      }
      this.lifecycleCompleted = true;
      this.active = false;
      quiescence.callbacksAtLifecycleComplete = this.callbackCount;
      await delay(FINAL_QUIESCENCE_MS);
      quiescence.callbacksAfterQuietWindow = this.callbackCount;
      quiescence.quiet = !this.failure &&
          quiescence.callbacksAtLifecycleComplete ===
              quiescence.callbacksAfterQuietWindow;
      if (!quiescence.quiet) {
        this.fail();
        return this.result("fail", "details-suppressed", quiescence);
      }
      const result = this.result("pass", null, quiescence);
      validateChromeWasmPersistentDefaultPartitionShutdownProbeResult(result);
      return result;
    } catch (_error) {
      this.fail();
      return this.result("fail", "details-suppressed", quiescence);
    } finally {
      this.releaseFailureObservers();
      if (this.loaderImportUrl !== null) {
        URL.revokeObjectURL(this.loaderImportUrl);
        this.loaderImportUrl = null;
      }
    }
  }
}

function validateByteIdentity(value, description) {
  const identity = requireExactFields(value, ["bytes", "sha256"], description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
}

export function validateChromeWasmPersistentDefaultPartitionShutdownProbeResult(
    result) {
  requireExactFields(result, RESULT_FIELDS, "structural shutdown probe result");
  if (result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
      result.scope !== SCOPE || result.status !== "pass" ||
      result.m7GateComplete !== false || result.origin !== location.origin ||
      result.crossOriginIsolated !== true || result.sharedArrayBuffer !== true ||
      result.exactEmptyProbeSwitchPassed !== true ||
      result.freshSourceSelectedShutdownArtifactProven !== true ||
      result.actualPersistentDefaultPartitionCreatedProven !== true ||
      result.persistentDefaultPartitionLocalStorageMapUpdateAndCloseReceiptProven !==
          true ||
      result.persistentDefaultPartitionRendererConfigReuseWitnessProven !==
          true ||
      result.persistentDefaultPartitionIndexedDBRendererWriteAndCloseReceiptProven !==
          true ||
      result.persistentDefaultPartitionCookieWriteAcceptedProven !== true ||
      result.persistentDefaultPartitionCookieStoreFlushAcknowledgedProven !== true ||
      result.persistentDefaultPartitionCookieSQLiteRowReadbackProven !== true ||
      result.persistentDefaultPartitionCookieStoreCloseReceiptProven !== true ||
      result.creationSealProven !== true ||
      result.partitionDestroyNotificationDispatchedProven !== true ||
      result.partitionMapDroppedProven !== true ||
      result.preferencesFenceProven !== true ||
      result.sealedLeaseRetainedReceiptProven !== true ||
      result.failClosedRetirementProven !== true ||
      result.structuralShutdownWitnessProven !== true ||
      result.nonzeroProcessExitAndAckProven !== true ||
      result.aggregatePartitionCloseProven !== false ||
      result.durableProfileFlushProven !== false ||
      result.profilePersistenceProven !== false ||
      result.profileStorageLeaseReleasedProven !== false ||
      result.freshDocumentReloadProven !== false || result.crashRecoveryProven !== false ||
      result.error !== null) {
    throw new Error("structural shutdown probe result is invalid");
  }
  const artifact = requireExactFields(result.artifact, ARTIFACT_FIELDS,
                                      "structural shutdown result artifact");
  if (artifact.module_name !== PRODUCT_MODULE_NAME ||
      artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot") {
    throw new Error("structural shutdown result artifact is invalid");
  }
  for (const field of ["build_config", "loader", "wasm"]) {
    validateByteIdentity(artifact[field], `structural shutdown artifact ${field}`);
  }
  const capture = requireExactFields(result.capture_harness,
                                     CAPTURE_HARNESS_FIELDS,
                                     "structural shutdown result capture harness");
  if (capture.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      capture.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("structural shutdown result capture harness is invalid");
  }
  for (const field of ["host_html", "host_js", "runner_source"]) {
    validateByteIdentity(capture[field], `structural shutdown capture ${field}`);
  }
  requireExactFields(result.versions, ["chromium", "v8", "emscripten"],
                     "structural shutdown result versions");
  if (Object.values(result.versions).some((value) =>
      typeof value !== "string" || !GIT_REVISION_RE.test(value))) {
    throw new Error("structural shutdown result versions are invalid");
  }
  const run = requireExactFields(result.run, RUN_FIELDS, "structural shutdown run");
  if (JSON.stringify(run.arguments) !== JSON.stringify(EXACT_PROBE_ARGUMENTS) ||
      run.abortObserved !== false ||
      !["resolved", "expected-nonzero-exit-status"].includes(run.factoryOutcome) ||
      run.factorySettled !== true || run.freshModuleObject !== true ||
      run.leaseReleasedMarkerObserved !== false ||
      run.markerCount !== EXPECTED_MARKERS.length ||
      run.markerSequenceAccepted !== true ||
      run.markerSource !==
          "stderr-only-fixed-selected-local-storage-renderer-indexed-db-and-cookie-shutdown-grammar" ||
      JSON.stringify(run.markers) !== JSON.stringify(EXPECTED_MARKERS) ||
      run.noFailMarkerObserved !== true ||
      run.nonzeroProcessExitAndAckReceived !== true || run.onExitCount !== 1 ||
      run.processExitBeforeOnExit !== true || !Number.isSafeInteger(run.processExitCode) ||
      run.processExitCode <= 0 || run.processExitCode > 255 ||
      run.processExitCount !== 1 || run.runtimeExitCode !== run.processExitCode ||
      run.runtimeInitialized !== true || run.stdoutMarkerCount !== 0 ||
      run.unexpectedMarkerObserved !== false) {
    throw new Error("structural shutdown run is invalid");
  }
  const bridge = requireExactFields(result.bridge, BRIDGE_FIELDS,
                                    "structural shutdown bridge");
  if (bridge.activeAtResult !== false ||
      bridge.installedBeforeModuleFactory !== true ||
      bridge.noActiveProcessExitRejected !== 0 || bridge.permanent !== true ||
      bridge.processExitDispatches !== 1 || bridge.protocol !== HOST_PROTOCOL ||
      bridge.duplicateProcessExitRejected !== 0 || bridge.frozen !== true) {
    throw new Error("structural shutdown bridge is invalid");
  }
  const quiescence = requireExactFields(result.quiescence, QUIESCENCE_FIELDS,
                                         "structural shutdown quiescence");
  if (quiescence.quiet !== true ||
      quiescence.quietWindowMs !== FINAL_QUIESCENCE_MS ||
      !Number.isSafeInteger(quiescence.callbacksAtLifecycleComplete) ||
      !Number.isSafeInteger(quiescence.callbacksAfterQuietWindow) ||
      quiescence.callbacksAtLifecycleComplete < 0 ||
      quiescence.callbacksAfterQuietWindow !==
          quiescence.callbacksAtLifecycleComplete) {
    throw new Error("structural shutdown quiescence is invalid");
  }
  const boundary = requireExactFields(result.hostBoundary, HOST_BOUNDARY_FIELDS,
                                      "structural shutdown host boundary");
  if (Object.values(boundary).some((value) => value !== false)) {
    throw new Error("structural shutdown host crossed a prohibited boundary");
  }
  return result;
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("structural shutdown version element is missing");
  }
  element.replaceChildren();
  for (const [name, value] of Object.entries(versions)) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = value;
    element.append(term, definition);
  }
}

async function postJson(url, body, description) {
  const response = await fetch(url.href, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${description} was not acknowledged`);
}

export async function runChromeWasmPersistentDefaultPartitionShutdownProbeFromQuery() {
  const context = parseContext();
  const root = document.querySelector(
      "#m7-persistent-default-partition-shutdown-probe-root");
  const canvas = document.querySelector(
      "#m7-persistent-default-partition-shutdown-probe-canvas");
  const status = document.querySelector(
      "#m7-persistent-default-partition-shutdown-probe-status");
  const versions = document.querySelector(
      "#m7-persistent-default-partition-shutdown-probe-versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement) || !(versions instanceof HTMLElement)) {
    throw new Error("structural shutdown probe page is missing required elements");
  }
  renderVersions(versions, context.versions);
  const host = new PersistentDefaultPartitionShutdownProbeHost(canvas, context);
  const result = await host.runProbe();
  root.dataset.state = result.status;
  status.textContent = result.status === "pass" ? "pass" : "fail";
  const resultUrl = new URL(
      `./result/${encodeURIComponent(context.resultToken)}`, location.href);
  const acknowledgementUrl = new URL(
      `./ack/${encodeURIComponent(context.resultToken)}`, location.href);
  if (resultUrl.origin !== location.origin ||
      acknowledgementUrl.origin !== location.origin) {
    throw new Error("structural shutdown probe receipt endpoint is invalid");
  }
  await postJson(resultUrl, result, "structural shutdown probe result receipt");
  await postJson(acknowledgementUrl, {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
  }, "structural shutdown probe result acknowledgement");
  return result;
}

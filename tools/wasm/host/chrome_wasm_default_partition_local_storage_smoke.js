// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Same-document two-fresh-module LocalStorage acceptance. Chromium owns the
// default-partition StorageArea operation, LevelDB commit, result-bearing
// close, profile fence, V4 backend drain, and reopen. The host is only a
// lifecycle coordinator: it never accesses OPFS, Web Locks, DOM storage,
// native exports, or Wasm memory. This proves ordered graceful close/reopen
// only. It does not claim renderer JavaScript semantics, crash/power-loss
// durability, or persistence for other profile or StoragePartition services.

const HOST_PROTOCOL = 1;
const CASE = "chrome_default_partition_local_storage_two_fresh_modules_m7";
const SCOPE =
    "same-origin-same-document-two-fresh-chrome-wasm-default-partition-" +
    "local-storage-test-modules-ordered-close-reopen-only";
const PRODUCT_MODULE_NAME =
    "chrome_wasm_m7_default_partition_local_storage_test";
const MARKER_PREFIX = "CHROMIUM_WASM_M7_LOCAL_STORAGE:";
const MODES = Object.freeze(["write", "verify"]);
const MAX_TIMEOUT_MS = 300000;
const MIN_TIMEOUT_MS = 20000;
const MAX_OUTPUT_LINES_PER_MODULE = 128;
const FINAL_QUIESCENCE_MS = 50;
const SHA256_RE = /^[0-9a-f]{64}$/;
const TOKEN_RE = /^[0-9a-f]{64}$/;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;
const EXPECTED_NORMAL_EXIT_STATUS_FIELDS = Object.freeze([
  "name", "status", "message",
]);
const EXPECTED_NORMAL_EXIT_STATUS_VALUES = Object.freeze({
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
});
const BYTE_IDENTITY_FIELDS = Object.freeze(["bytes", "sha256"]);
const ARTIFACT_FIELDS = Object.freeze([
  "artifact_delivery", "artifact_source_provenance", "build_config",
  "build_config_provenance", "loader", "module_name", "wasm",
]);
const CAPTURE_HARNESS_FIELDS = Object.freeze([
  "host_html", "host_js", "runner_source", "source_snapshot_provenance",
  "version_provenance",
]);
const VERSION_FIELDS = Object.freeze(["chromium", "emscripten", "v8"]);
const TOKEN_EVIDENCE_FIELDS = Object.freeze([
  "algorithm", "digest", "rawTokenExcluded", "rawTokenLeakDetected",
  "rawTokenRedactionCount",
]);
const HOST_BOUNDARY_FIELDS = Object.freeze([
  "hostOpfsAccessAttempted", "hostWebLocksAccessAttempted",
  "hostDomStorageAccessAttempted", "nativeCallAttempted",
  "wasmDataInspectionAttempted",
]);
const RUN_FIELDS = Object.freeze([
  "abortObserved", "expectedCleanExitStatusObserved", "factoryRejected",
  "factoryResolved", "factorySettled", "freshLoaderImport",
  "freshModuleObject", "leaseReleasedMarkerObserved", "lifecycleComplete",
  "markerCount", "markerSequenceAccepted", "markerSource", "markers", "mode",
  "moduleIdentity", "onExitCount", "ordinal", "outputLineCount",
  "processExitCode", "processExitCount", "runtimeExitCode",
  "runtimeInitialized", "stdoutMarkerCount",
]);
const BRIDGE_FIELDS = Object.freeze([
  "protocol", "permanent", "frozen", "installedBeforeFirstModuleFactory",
  "processExitDispatches", "activeAtResult",
]);
const QUIESCENCE_FIELDS = Object.freeze([
  "callbacksAfterQuiescence", "callbacksAtClear", "moduleOrdinal", "quiet",
  "quietWindowMs",
]);
const RESULT_FIELDS = Object.freeze([
  "protocol", "case", "scope", "status", "m7GateComplete", "origin",
  "crossOriginIsolated", "sharedArrayBuffer", "artifact", "capture_harness",
  "versions", "tokenEvidence", "exactlyTwoFreshModulesProven",
  "orderedDefaultPartitionLocalStorageCloseReopenProven",
  "rendererJavaScriptLocalStorageProven", "crashOrPowerLossDurabilityProven",
  "fullStoragePartitionPersistenceProven", "hostBoundary", "runs", "bridge",
  "quiescence", "error",
]);

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function hasExactFields(value, fields) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === fields.length &&
      fields.every((field) => Object.hasOwn(value, field));
}

function requireExactFields(value, fields, description) {
  if (!hasExactFields(value, fields)) {
    throw new Error(description + " is invalid");
  }
  return value;
}

function parseJson(value, description) {
  if (typeof value !== "string" || value.length === 0 || value.length > 65536) {
    throw new Error(description + " is invalid");
  }
  try {
    return JSON.parse(value);
  } catch (_error) {
    throw new Error(description + " is invalid");
  }
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, BYTE_IDENTITY_FIELDS, description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(description + " is invalid");
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifact(value) {
  const artifact = requireExactFields(
      parseJson(value, "artifact"), ARTIFACT_FIELDS, "artifact");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error("artifact provenance is invalid");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    build_config: parseByteIdentity(artifact.build_config, "build config"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "loader"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "Wasm"),
  });
}

function parseCaptureHarness(value) {
  const harness = requireExactFields(
      parseJson(value, "capture harness"), CAPTURE_HARNESS_FIELDS,
      "capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("capture harness provenance is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html, "host HTML"),
    host_js: parseByteIdentity(harness.host_js, "host JavaScript"),
    runner_source: parseByteIdentity(harness.runner_source, "runner source"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = requireExactFields(
      parseJson(value, "versions"), VERSION_FIELDS, "versions");
  if (!VERSION_FIELDS.every((field) => typeof versions[field] === "string" &&
      /^[0-9a-f]{40}$/.test(versions[field]))) {
    throw new Error("versions are invalid");
  }
  return Object.freeze({...versions});
}

function parseContext() {
  const query = new URLSearchParams(location.search);
  const fields = Object.freeze([
    "resultToken", "session", "module", "timeoutMs", "versions", "artifact",
    "captureHarness",
  ]);
  if ([...query.keys()].length !== fields.length ||
      !fields.every((field) => query.getAll(field).length === 1)) {
    throw new Error("LocalStorage smoke query is invalid");
  }
  const resultToken = query.get("resultToken");
  const session = query.get("session");
  const moduleName = query.get("module");
  const timeoutText = query.get("timeoutMs");
  if (typeof resultToken !== "string" || !CAPABILITY_RE.test(resultToken) ||
      typeof session !== "string" || !CAPABILITY_RE.test(session) ||
      resultToken === session || moduleName !== PRODUCT_MODULE_NAME ||
      typeof timeoutText !== "string" || !/^[0-9]+$/.test(timeoutText)) {
    throw new Error("LocalStorage smoke query is invalid");
  }
  const timeoutMs = Number(timeoutText);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("LocalStorage smoke timeout is invalid");
  }
  return Object.freeze({
    artifact: parseArtifact(query.get("artifact")),
    captureHarness: parseCaptureHarness(query.get("captureHarness")),
    moduleName,
    resultToken,
    session,
    timeoutMs,
    versions: parseVersions(query.get("versions")),
  });
}

function hex(bytes) {
  return Array.from(
      bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function randomHex(byteLength, description) {
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 ||
      !globalThis.crypto ||
      typeof globalThis.crypto.getRandomValues !== "function") {
    throw new Error(description + " random source is unavailable");
  }
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  return hex(bytes);
}

async function sha256Hex(bytes, description) {
  if (!(bytes instanceof Uint8Array) || !globalThis.crypto ||
      !globalThis.crypto.subtle ||
      typeof globalThis.crypto.subtle.digest !== "function") {
    throw new Error(description + " hash support is unavailable");
  }
  let digest;
  try {
    digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  } catch (_error) {
    throw new Error(description + " hash failed");
  }
  return hex(new Uint8Array(digest));
}

async function fetchVerifiedArtifact(url, identity, contentType, description) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  const actualType = response.headers.get("content-type")
      ?.split(";", 1)[0].trim().toLowerCase();
  if (!response.ok || response.url !== url.href || actualType !== contentType ||
      response.headers.get("cache-control") !== "no-store" ||
      response.headers.get("cross-origin-embedder-policy") !== "require-corp" ||
      response.headers.get("cross-origin-opener-policy") !== "same-origin") {
    throw new Error(description + " response is invalid");
  }
  let buffer;
  try {
    buffer = await response.arrayBuffer();
  } catch (_error) {
    throw new Error(description + " bytes are invalid");
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(description + " differs from its snapshot");
  }
  return bytes;
}

function isExactNormalEmscriptenExitStatus(value) {
  try {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      return false;
    }
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const keys = Reflect.ownKeys(descriptors);
    if (keys.length !== EXPECTED_NORMAL_EXIT_STATUS_FIELDS.length ||
        keys.some((key) => typeof key !== "string" ||
            !EXPECTED_NORMAL_EXIT_STATUS_FIELDS.includes(key))) {
      return false;
    }
    return EXPECTED_NORMAL_EXIT_STATUS_FIELDS.every((field) => {
      const descriptor = descriptors[field];
      return descriptor !== undefined && Object.hasOwn(descriptor, "value") &&
          !Object.hasOwn(descriptor, "get") && !Object.hasOwn(descriptor, "set") &&
          descriptor.value === EXPECTED_NORMAL_EXIT_STATUS_VALUES[field];
    });
  } catch (_error) {
    return false;
  }
}

function expectedMarkers(mode, digest) {
  if (mode === "write") {
    return [
      MARKER_PREFIX + "READY",
      MARKER_PREFIX + "WRITE_ACCEPTED sha256=" + digest,
      MARKER_PREFIX + "ON_DISK_COMMIT_OK sha256=" + digest,
      MARKER_PREFIX + "DB_CLOSE_OK sha256=" + digest,
      MARKER_PREFIX + "FENCE_OK sha256=" + digest,
      MARKER_PREFIX + "LEASE_RELEASED",
    ];
  }
  if (mode === "verify") {
    return [
      MARKER_PREFIX + "READY",
      MARKER_PREFIX + "REOPEN_READ_OK sha256=" + digest,
      MARKER_PREFIX + "ON_DISK_COMMIT_OK sha256=" + digest,
      MARKER_PREFIX + "DB_CLOSE_OK sha256=" + digest,
      MARKER_PREFIX + "FENCE_OK sha256=" + digest,
      MARKER_PREFIX + "LEASE_RELEASED",
    ];
  }
  throw new Error("LocalStorage smoke mode is invalid");
}

// The Python runner independently validates the same receipt. Keeping this
// exported host validator narrow and structural makes that cross-language
// grammar check executable without running a browser or an Emscripten module.
export function validateChromeWasmDefaultPartitionLocalStorageResult(result) {
  requireExactFields(result, RESULT_FIELDS, "LocalStorage result");
  if (result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
      result.scope !== SCOPE || result.status !== "pass" ||
      result.m7GateComplete !== false || typeof result.origin !== "string" ||
      result.origin.length === 0 || result.crossOriginIsolated !== true ||
      result.sharedArrayBuffer !== true ||
      result.exactlyTwoFreshModulesProven !== true ||
      result.orderedDefaultPartitionLocalStorageCloseReopenProven !== true ||
      result.rendererJavaScriptLocalStorageProven !== false ||
      result.crashOrPowerLossDurabilityProven !== false ||
      result.fullStoragePartitionPersistenceProven !== false ||
      result.error !== null) {
    throw new Error("LocalStorage result is invalid");
  }
  const artifact = requireExactFields(result.artifact, ARTIFACT_FIELDS, "artifact");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error("LocalStorage artifact is invalid");
  }
  for (const identity of [
    artifact.build_config, artifact.loader, artifact.wasm,
    requireExactFields(result.capture_harness, CAPTURE_HARNESS_FIELDS,
                       "capture harness").host_html,
    result.capture_harness.host_js, result.capture_harness.runner_source,
  ]) {
    if (!hasExactFields(identity, BYTE_IDENTITY_FIELDS) ||
        !Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
        typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
      throw new Error("LocalStorage byte identity is invalid");
    }
  }
  const captureHarness = result.capture_harness;
  if (captureHarness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      captureHarness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("LocalStorage capture harness is invalid");
  }
  if (!hasExactFields(result.versions, VERSION_FIELDS) ||
      !VERSION_FIELDS.every((field) => typeof result.versions[field] === "string" &&
          /^[0-9a-f]{40}$/.test(result.versions[field]))) {
    throw new Error("LocalStorage versions are invalid");
  }
  const evidence = requireExactFields(
      result.tokenEvidence, TOKEN_EVIDENCE_FIELDS, "token evidence");
  if (evidence.algorithm !== "SHA-256" || typeof evidence.digest !== "string" ||
      !SHA256_RE.test(evidence.digest) || evidence.rawTokenExcluded !== true ||
      evidence.rawTokenLeakDetected !== false ||
      evidence.rawTokenRedactionCount !== 0) {
    throw new Error("LocalStorage token evidence is invalid");
  }
  const boundary = requireExactFields(
      result.hostBoundary, HOST_BOUNDARY_FIELDS, "host boundary");
  if (HOST_BOUNDARY_FIELDS.some((field) => boundary[field] !== false)) {
    throw new Error("LocalStorage host boundary is invalid");
  }
  if (!Array.isArray(result.runs) || result.runs.length !== 2) {
    throw new Error("LocalStorage module count is invalid");
  }
  const moduleIdentities = new Set();
  for (const [index, run] of result.runs.entries()) {
    requireExactFields(run, RUN_FIELDS, "run");
    const mode = MODES[index];
    const expected = expectedMarkers(mode, evidence.digest);
    if (run.mode !== mode || run.ordinal !== index + 1 ||
        typeof run.moduleIdentity !== "string" ||
        !/^[0-9a-f]{32}$/.test(run.moduleIdentity) ||
        moduleIdentities.has(run.moduleIdentity) ||
        typeof run.expectedCleanExitStatusObserved !== "boolean" ||
        run.abortObserved !== false || run.factoryRejected !== false ||
        run.factoryResolved !== true || run.factorySettled !== true ||
        run.freshLoaderImport !== true || run.freshModuleObject !== true ||
        run.leaseReleasedMarkerObserved !== true ||
        run.lifecycleComplete !== true || run.markerCount !== expected.length ||
        run.markerSequenceAccepted !== true ||
        run.markerSource !== "stderr-only-fixed-local-storage-grammar" ||
        !Array.isArray(run.markers) ||
        run.markers.length !== expected.length ||
        run.markers.some((marker, markerIndex) => marker !== expected[markerIndex]) ||
        run.onExitCount !== 1 || run.outputLineCount < expected.length ||
        run.outputLineCount > MAX_OUTPUT_LINES_PER_MODULE ||
        run.processExitCode !== 0 || run.processExitCount !== 1 ||
        run.runtimeExitCode !== 0 || run.runtimeInitialized !== true ||
        run.stdoutMarkerCount !== 0) {
      throw new Error("LocalStorage run is invalid");
    }
    moduleIdentities.add(run.moduleIdentity);
  }
  const bridge = requireExactFields(result.bridge, BRIDGE_FIELDS, "bridge");
  if (bridge.protocol !== HOST_PROTOCOL || bridge.permanent !== true ||
      bridge.frozen !== true ||
      bridge.installedBeforeFirstModuleFactory !== true ||
      bridge.processExitDispatches !== 2 || bridge.activeAtResult !== true) {
    throw new Error("LocalStorage bridge is invalid");
  }
  if (!Array.isArray(result.quiescence) || result.quiescence.length !== 2) {
    throw new Error("LocalStorage quiescence is invalid");
  }
  for (const [index, entry] of result.quiescence.entries()) {
    requireExactFields(entry, QUIESCENCE_FIELDS, "quiescence");
    if (entry.moduleOrdinal !== index + 1 || entry.quiet !== true ||
        entry.quietWindowMs !== FINAL_QUIESCENCE_MS ||
        !Number.isSafeInteger(entry.callbacksAtClear) ||
        !Number.isSafeInteger(entry.callbacksAfterQuiescence) ||
        entry.callbacksAtClear !== entry.callbacksAfterQuiescence) {
      throw new Error("LocalStorage quiescence is invalid");
    }
  }
  return result;
}

function newRun(mode, ordinal) {
  return {
    abortObserved: false,
    expectedCleanExitStatusObserved: false,
    factoryRejected: false,
    factoryResolved: false,
    factorySettled: false,
    freshLoaderImport: false,
    freshModuleObject: false,
    leaseReleasedMarkerObserved: false,
    lifecycleComplete: false,
    markerCount: 0,
    markerSequenceAccepted: true,
    markers: [],
    mode,
    moduleIdentity: randomHex(16, "module identity"),
    onExitCount: 0,
    ordinal,
    outputLineCount: 0,
    processExitCode: null,
    processExitCount: 0,
    runtimeExitCode: null,
    runtimeInitialized: false,
    stdoutMarkerCount: 0,
  };
}

class DefaultPartitionLocalStorageHost {
  constructor(canvas, status, context) {
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement)) {
      throw new Error("LocalStorage smoke page is invalid");
    }
    this.canvas = canvas;
    this.status = status;
    this.context = context;
    // One host deadline covers bootstrap, artifact verification, and both
    // fresh-module lifecycles. The Python runner applies the same one-budget
    // interpretation to the page result.
    this.deadline = performance.now() + context.timeoutMs;
    this.artifact = context.artifact;
    this.captureHarness = context.captureHarness;
    this.versions = context.versions;
    this.active = null;
    this.bridgeInstalled = false;
    this.bridgeProcessExitDispatches = 0;
    this.callbackCount = 0;
    this.failure = false;
    // Weak identity registries prove that the two factories and the two
    // returned Module objects differ without retaining a completed Chrome
    // module's linear memory through the second fresh-module run.
    this.loaderFactories = new WeakSet();
    this.loaderFactoryCount = 0;
    this.moduleObjects = new WeakSet();
    this.moduleObjectCount = 0;
    this.rawToken = null;
    this.rawTokenDigest = null;
    this.rawTokenLeakDetected = false;
    this.rawTokenRedactionCount = 0;
    this.rawTokenTail = "";
    this.runs = [];
    this.windowErrors = 0;
    this.unhandledRejections = 0;
    this.windowErrorHandler = null;
    this.unhandledRejectionHandler = null;
    this.quiescence = [];
  }

  markFailure() {
    this.failure = true;
  }

  noteCallback() {
    this.callbackCount += 1;
  }

  observeOpaqueText(value) {
    if (typeof value !== "string" || this.rawToken === null) {
      return;
    }
    const candidate = this.rawTokenTail + value;
    if (candidate.includes(this.rawToken)) {
      this.rawTokenLeakDetected = true;
      this.rawTokenRedactionCount += 1;
      this.markFailure();
    }
    this.rawTokenTail = candidate.slice(-63);
  }

  installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("LocalStorage smoke bridge is already installed");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.noteCallback();
        host.observeOpaqueText(typeof message === "string" ? message : "");
        host.markFailure();
      },
      reportProcessExit(report) {
        host.routeProcessExit(report);
      },
      reportFrame(_report) {
        host.noteCallback();
      },
      reportReadiness(_report) {
        host.noteCallback();
      },
      reportOzoneFocusState(_report) {
        host.noteCallback();
      },
      reportOzoneCursor(_report) {
        host.noteCallback();
        return true;
      },
      reportOzoneTextInputState(_report) {
        host.noteCallback();
      },
      reportOzoneTextInputDelivery(_report) {
        host.noteCallback();
      },
      reportOzoneBrowserTextInputDelivery(_report) {
        host.noteCallback();
      },
      reportOzoneBrowserClipboardPasteDelivery(_report) {
        host.noteCallback();
      },
      requestOuterOriginStorageEstimate(_report) {
        host.noteCallback();
        return false;
      },
      reportAccessibilitySnapshot(_report) {
        host.noteCallback();
        return false;
      },
    });
    Object.defineProperty(globalThis, "__chromiumWasmHostBridgeV1", {
      configurable: false,
      enumerable: false,
      value: bridge,
      writable: false,
    });
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge ||
        !Object.isFrozen(bridge)) {
      throw new Error("LocalStorage smoke bridge is mutable");
    }
    this.bridgeInstalled = true;
  }

  installFailureObservers() {
    this.windowErrorHandler = (event) => {
      this.noteCallback();
      this.windowErrors += 1;
      this.observeOpaqueText(
          event && typeof event.message === "string" ? event.message : "");
      this.markFailure();
    };
    this.unhandledRejectionHandler = (event) => {
      this.noteCallback();
      let reason = null;
      try {
        reason = event.reason;
      } catch (_error) {
        this.markFailure();
        return;
      }
      const run = this.active;
      if (run !== null && isExactNormalEmscriptenExitStatus(reason) &&
          run.processExitCode === 0 && run.onExitCount === 1 &&
          !this.failure && event && typeof event.preventDefault === "function") {
        event.preventDefault();
        run.expectedCleanExitStatusObserved = true;
        this.maybeComplete(run);
        return;
      }
      this.unhandledRejections += 1;
      this.observeOpaqueText(typeof reason === "string" ? reason : "");
      this.markFailure();
    };
    addEventListener("error", this.windowErrorHandler);
    addEventListener("unhandledrejection", this.unhandledRejectionHandler);
  }

  releaseObservers() {
    if (this.windowErrorHandler !== null) {
      removeEventListener("error", this.windowErrorHandler);
      this.windowErrorHandler = null;
    }
    if (this.unhandledRejectionHandler !== null) {
      removeEventListener("unhandledrejection", this.unhandledRejectionHandler);
      this.unhandledRejectionHandler = null;
    }
  }

  routeProcessExit(report) {
    this.noteCallback();
    const run = this.active;
    if (run === null || run.lifecycleComplete || run.processExitCount !== 0 ||
        run.onExitCount !== 0 || !hasExactFields(report, ["protocol", "exitCode"]) ||
        report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.exitCode)) {
      this.markFailure();
      return;
    }
    run.processExitCount = 1;
    run.processExitCode = report.exitCode;
    this.bridgeProcessExitDispatches += 1;
    if (report.exitCode !== 0) {
      this.markFailure();
      return;
    }
    this.maybeComplete(run);
  }

  captureOutput(run, destination, line) {
    this.noteCallback();
    run.outputLineCount += 1;
    if (run.outputLineCount > MAX_OUTPUT_LINES_PER_MODULE ||
        typeof line !== "string") {
      this.markFailure();
      return;
    }
    this.observeOpaqueText(line);
    if (!line.startsWith(MARKER_PREFIX)) {
      return;
    }
    if (destination !== "stderr") {
      run.stdoutMarkerCount += 1;
      this.markFailure();
      return;
    }
    const expected = expectedMarkers(run.mode, this.rawTokenDigest);
    const index = run.markers.length;
    if (index >= expected.length || line !== expected[index]) {
      run.markerSequenceAccepted = false;
      this.markFailure();
      return;
    }
    run.markers.push(line);
    run.markerCount = run.markers.length;
    if (line === MARKER_PREFIX + "LEASE_RELEASED") {
      run.leaseReleasedMarkerObserved = true;
    }
    this.maybeComplete(run);
  }

  reportRuntimeInitialized(run, module) {
    this.noteCallback();
    if (this.active !== run || run.lifecycleComplete || run.runtimeInitialized ||
        !module || (typeof module !== "object" && typeof module !== "function") ||
        (run.factoryModule !== undefined && run.factoryModule !== module)) {
      this.markFailure();
      return;
    }
    run.runtimeModule = module;
    run.runtimeInitialized = true;
    this.maybeComplete(run);
  }

  reportRuntimeExit(run, code) {
    this.noteCallback();
    if (this.active !== run || run.lifecycleComplete ||
        !Number.isSafeInteger(code) || run.onExitCount !== 0 ||
        run.processExitCount !== 1 || run.processExitCode !== 0) {
      this.markFailure();
      return;
    }
    run.onExitCount = 1;
    run.runtimeExitCode = code;
    if (code !== 0) {
      this.markFailure();
      return;
    }
    this.maybeComplete(run);
  }

  reportAbort(run, reason) {
    this.noteCallback();
    this.observeOpaqueText(typeof reason === "string" ? reason : "");
    if (this.active !== run || run.abortObserved) {
      this.markFailure();
      return;
    }
    run.abortObserved = true;
    this.markFailure();
  }

  factoryResolved(run, module) {
    this.noteCallback();
    if (this.active !== run || run.factorySettled || !module ||
        (typeof module !== "object" && typeof module !== "function") ||
        (run.runtimeModule !== undefined && run.runtimeModule !== module)) {
      this.markFailure();
      return;
    }
    run.factoryModule = module;
    run.factorySettled = true;
    run.factoryResolved = true;
    if (this.moduleObjects.has(module)) {
      this.markFailure();
      return;
    }
    this.moduleObjects.add(module);
    this.moduleObjectCount += 1;
    run.freshModuleObject = true;
    this.maybeComplete(run);
  }

  factoryRejected(run, reason) {
    this.noteCallback();
    this.observeOpaqueText(typeof reason === "string" ? reason : "");
    if (this.active === run && !run.factorySettled) {
      run.factorySettled = true;
      run.factoryRejected = true;
    }
    this.markFailure();
  }

  cleanLifecycleReady(run) {
    const expected = expectedMarkers(run.mode, this.rawTokenDigest);
    return !this.failure && this.active === run && run.runtimeInitialized &&
        run.factorySettled && run.factoryResolved && !run.factoryRejected &&
        run.runtimeModule === run.factoryModule && !run.abortObserved &&
        run.processExitCount === 1 && run.processExitCode === 0 &&
        run.onExitCount === 1 && run.runtimeExitCode === 0 &&
        run.freshLoaderImport && run.freshModuleObject &&
        run.markerSequenceAccepted &&
        run.markers.length === expected.length &&
        run.markers.every((marker, index) => marker === expected[index]) &&
        run.leaseReleasedMarkerObserved;
  }

  maybeComplete(run) {
    if (run.lifecycleComplete || !this.cleanLifecycleReady(run)) {
      return;
    }
    run.lifecycleComplete = true;
  }

  async fetchBootstrap() {
    const url = new URL("./bootstrap/" + this.context.session, location.href);
    if (url.origin !== location.origin) {
      throw new Error("bootstrap origin is invalid");
    }
    const response = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    if (!response.ok || response.url !== url.href ||
        response.headers.get("content-type")?.split(";", 1)[0]
            .trim().toLowerCase() !== "application/json" ||
        response.headers.get("cache-control") !== "no-store") {
      throw new Error("bootstrap response is invalid");
    }
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("bootstrap body is invalid");
    }
    requireExactFields(
        payload, ["protocol", "case", "scope", "token", "tokenDigest"],
        "bootstrap payload");
    if (payload.protocol !== HOST_PROTOCOL || payload.case !== CASE ||
        payload.scope !== SCOPE || typeof payload.token !== "string" ||
        !TOKEN_RE.test(payload.token) || typeof payload.tokenDigest !== "string" ||
        !SHA256_RE.test(payload.tokenDigest)) {
      throw new Error("bootstrap payload is invalid");
    }
    const digest = await sha256Hex(
        new TextEncoder().encode(payload.token), "LocalStorage token");
    if (digest !== payload.tokenDigest) {
      throw new Error("bootstrap digest is invalid");
    }
    this.rawToken = payload.token;
    this.rawTokenDigest = digest;
  }

  async fetchArtifacts() {
    const loaderUrl = new URL(
        "./artifacts/" + this.context.moduleName + ".js", location.href);
    const wasmUrl = new URL(
        "./artifacts/" + this.context.moduleName + ".wasm", location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("artifact origin is invalid");
    }
    const values = await Promise.all([
      fetchVerifiedArtifact(
          loaderUrl, this.artifact.loader, "text/javascript", "loader"),
      fetchVerifiedArtifact(wasmUrl, this.artifact.wasm, "application/wasm", "Wasm"),
    ]);
    this.loaderBytes = values[0];
    this.wasmBinary = values[1];
    this.wasmUrl = wasmUrl;
  }

  async importFreshFactory() {
    if (!(this.loaderBytes instanceof Uint8Array) ||
        typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("fresh loader import is unavailable");
    }
    const importUrl = URL.createObjectURL(
        new Blob([this.loaderBytes], {type: "text/javascript"}));
    try {
      const namespace = await import(importUrl);
      if (typeof namespace.default !== "function") {
        throw new Error("loader factory is invalid");
      }
      return {factory: namespace.default, importUrl};
    } catch (error) {
      URL.revokeObjectURL(importUrl);
      throw error;
    }
  }

  async runModule(mode, ordinal, deadline) {
    if (!MODES.includes(mode) || this.active !== null || this.rawToken === null ||
        this.rawTokenDigest === null || !(this.wasmBinary instanceof Uint8Array) ||
        this.wasmUrl === undefined || this.runs.length !== ordinal - 1 ||
        !Number.isFinite(deadline)) {
      throw new Error("module start is invalid");
    }
    const run = newRun(mode, ordinal);
    this.active = run;
    let importUrl = null;
    try {
      const imported = await this.importFreshFactory();
      importUrl = imported.importUrl;
      if (this.loaderFactories.has(imported.factory)) {
        this.markFailure();
        throw new Error("fresh loader factory was reused");
      }
      this.loaderFactories.add(imported.factory);
      this.loaderFactoryCount += 1;
      run.loaderFactory = imported.factory;
      run.freshLoaderImport = true;
      const host = this;
      let result;
      try {
        result = imported.factory({
          arguments: [
            "--wasm-profile-local-storage-smoke=" + mode,
            "--wasm-profile-local-storage-token=" + this.rawToken,
          ],
          canvas: this.canvas,
          locateFile(path) {
            if (path !== host.context.moduleName + ".wasm") {
              throw new Error("loader requested an unexpected artifact");
            }
            return host.wasmUrl.href;
          },
          mainScriptUrlOrBlob: importUrl,
          noExitRuntime: false,
          onAbort(reason) {
            host.reportAbort(run, reason);
          },
          onExit(code) {
            host.reportRuntimeExit(run, code);
          },
          onRuntimeInitialized() {
            host.reportRuntimeInitialized(run, this);
          },
          print(line) {
            host.captureOutput(run, "stdout", line);
          },
          printErr(line) {
            host.captureOutput(run, "stderr", line);
          },
          // Freshness is established by the distinct Blob-module imports and
          // weakly tracked returned Module identities, not by retaining an
          // extra ~211 MiB copy of the immutable, hash-checked artifact for
          // each factory.
          wasmBinary: this.wasmBinary,
        });
      } catch (error) {
        this.factoryRejected(run, error);
        result = null;
      }
      if (result !== null) {
        Promise.resolve(result).then(
            (module) => host.factoryResolved(run, module),
            (error) => host.factoryRejected(run, error));
      }
      while (performance.now() < deadline && !this.failure &&
             !run.lifecycleComplete) {
        await delay(10);
      }
      if (!run.lifecycleComplete || !this.cleanLifecycleReady(run)) {
        this.markFailure();
        throw new Error("module lifecycle did not complete");
      }
      const callbacksAtClear = this.callbackCount;
      this.active = null;
      await delay(FINAL_QUIESCENCE_MS);
      const callbacksAfterQuiescence = this.callbackCount;
      const quiet = !this.failure && callbacksAtClear === callbacksAfterQuiescence;
      this.quiescence.push({
        callbacksAfterQuiescence,
        callbacksAtClear,
        moduleOrdinal: ordinal,
        quiet,
        quietWindowMs: FINAL_QUIESCENCE_MS,
      });
      if (!quiet) {
        this.markFailure();
        throw new Error("module did not become quiescent");
      }
      const snapshot = this.snapshotRun(run);
      // The receipt has already captured every externally reported fact. Drop
      // strong references to this completed Emscripten Module before starting
      // the next fresh module; WeakSet identity tracking still rejects reuse.
      run.factoryModule = undefined;
      run.runtimeModule = undefined;
      run.loaderFactory = undefined;
      this.runs.push(snapshot);
      return snapshot;
    } catch (error) {
      this.markFailure();
      throw error;
    } finally {
      if (importUrl !== null) {
        URL.revokeObjectURL(importUrl);
      }
      if (this.active === run) {
        this.active = null;
      }
    }
  }

  snapshotRun(run) {
    return {
      abortObserved: run.abortObserved,
      expectedCleanExitStatusObserved: run.expectedCleanExitStatusObserved,
      factoryRejected: run.factoryRejected,
      factoryResolved: run.factoryResolved,
      factorySettled: run.factorySettled,
      freshLoaderImport: run.freshLoaderImport,
      freshModuleObject: run.freshModuleObject,
      leaseReleasedMarkerObserved: run.leaseReleasedMarkerObserved,
      lifecycleComplete: run.lifecycleComplete,
      markerCount: run.markerCount,
      markerSequenceAccepted: run.markerSequenceAccepted,
      markerSource: "stderr-only-fixed-local-storage-grammar",
      markers: run.markers.slice(),
      mode: run.mode,
      moduleIdentity: run.moduleIdentity,
      onExitCount: run.onExitCount,
      ordinal: run.ordinal,
      outputLineCount: run.outputLineCount,
      processExitCode: run.processExitCode,
      processExitCount: run.processExitCount,
      runtimeExitCode: run.runtimeExitCode,
      runtimeInitialized: run.runtimeInitialized,
      stdoutMarkerCount: run.stdoutMarkerCount,
    };
  }

  result(status) {
    const passed = status === "pass";
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m7GateComplete: false,
      origin: location.origin,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      artifact: this.artifact,
      capture_harness: this.captureHarness,
      versions: this.versions,
      tokenEvidence: {
        algorithm: "SHA-256",
        digest: this.rawTokenDigest,
        rawTokenExcluded: true,
        rawTokenLeakDetected: this.rawTokenLeakDetected,
        rawTokenRedactionCount: this.rawTokenRedactionCount,
      },
      exactlyTwoFreshModulesProven: passed && this.runs.length === 2,
      orderedDefaultPartitionLocalStorageCloseReopenProven: passed,
      rendererJavaScriptLocalStorageProven: false,
      crashOrPowerLossDurabilityProven: false,
      fullStoragePartitionPersistenceProven: false,
      hostBoundary: {
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        hostDomStorageAccessAttempted: false,
        nativeCallAttempted: false,
        wasmDataInspectionAttempted: false,
      },
      runs: this.runs.map((run) => ({...run, markers: run.markers.slice()})),
      bridge: {
        protocol: HOST_PROTOCOL,
        permanent: this.bridgeInstalled,
        frozen: this.bridgeInstalled &&
            Object.isFrozen(globalThis.__chromiumWasmHostBridgeV1),
        installedBeforeFirstModuleFactory: this.bridgeInstalled,
        processExitDispatches: this.bridgeProcessExitDispatches,
        activeAtResult: this.active === null,
      },
      quiescence: this.quiescence.slice(),
      error: passed ? null : "details-suppressed",
    };
  }

  async run() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function" || location.origin === "null") {
        throw new Error("host context is invalid");
      }
      this.canvas.focus({preventScroll: true});
      if (document.activeElement !== this.canvas) {
        throw new Error("canvas focus failed");
      }
      this.installFailureObservers();
      await this.fetchBootstrap();
      this.installBridge();
      await this.fetchArtifacts();
      await this.runModule("write", 1, this.deadline);
      await this.runModule("verify", 2, this.deadline);
      if (this.runs.length !== 2 || this.loaderFactoryCount !== 2 ||
          this.moduleObjectCount !== 2 || this.failure) {
        this.markFailure();
      }
    } catch (_error) {
      this.markFailure();
    }
    this.rawToken = null;
    this.rawTokenTail = "";
    this.loaderBytes = null;
    this.wasmBinary = null;
    this.wasmUrl = undefined;
    this.status.textContent = this.failure ? "failed" : "passed";
    return this.result(this.failure ? "fail" : "pass");
  }

  dispose() {
    this.releaseObservers();
    this.rawToken = null;
    this.rawTokenTail = "";
    this.loaderBytes = null;
    this.wasmBinary = null;
    this.wasmUrl = undefined;
  }
}

async function postResult(context, result) {
  const url = new URL("./result/" + context.resultToken, location.href);
  if (url.origin !== location.origin) {
    throw new Error("result origin is invalid");
  }
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
    referrerPolicy: "no-referrer",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (response.status !== 204) {
    throw new Error("result acknowledgement is invalid");
  }
}

function showVersions(element, versions) {
  element.replaceChildren();
  for (const name of VERSION_FIELDS) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = versions[name];
    element.append(term, definition);
  }
}

export async function runChromeWasmDefaultPartitionLocalStorageFromQuery() {
  let host = null;
  try {
    const context = parseContext();
    const canvas = document.querySelector(
        "#m7-default-partition-local-storage-canvas");
    const status = document.querySelector(
        "#m7-default-partition-local-storage-status");
    const versions = document.querySelector(
        "#m7-default-partition-local-storage-versions");
    const root = document.querySelector(
        "#m7-default-partition-local-storage-root");
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement) ||
        !(versions instanceof HTMLElement) || !(root instanceof HTMLElement)) {
      throw new Error("LocalStorage smoke page is invalid");
    }
    showVersions(versions, context.versions);
    host = new DefaultPartitionLocalStorageHost(canvas, status, context);
    const result = await host.run();
    root.dataset.state = result.status;
    await postResult(context, result);
  } catch (_error) {
    const root = document.querySelector(
        "#m7-default-partition-local-storage-root");
    const status = document.querySelector(
        "#m7-default-partition-local-storage-status");
    if (root instanceof HTMLElement) {
      root.dataset.state = "fail";
    }
    if (status instanceof HTMLElement) {
      status.textContent = "result delivery failed";
    }
  } finally {
    if (host !== null) {
      host.dispose();
    }
  }
}

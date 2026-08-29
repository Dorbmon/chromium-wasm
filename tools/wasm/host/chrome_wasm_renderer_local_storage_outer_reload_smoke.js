// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Two-outer-document renderer LocalStorage witness. Chromium creates the
// transient test WebContents, executes its external chrome:// script, obtains
// the committed RenderFrameHost StorageKey, and closes the actual renderer
// owner before it arms the existing close fence. The host only runs one fresh
// Emscripten module per outer document and relays fixed, redacted receipts.
// It never accesses profile storage, Web Locks, DOM storage, native exports,
// or Wasm memory. This is an orderly close/reopen test for one dedicated test
// Chrome origin, not a normal-profile or crash-recovery persistence claim.

const HOST_PROTOCOL = 1;
const CASE = "chrome_renderer_local_storage_two_outer_document_reload_m7";
const SCOPE =
    "same-origin-two-outer-documents-chrome-wasm-m7-renderer-local-storage-" +
    "test-modules-orderly-close-reopen-test-chrome-origin-only";
const PRODUCT_MODULE_NAME = "chrome_wasm_m7_default_partition_local_storage_test";
const MARKER_PREFIX = "CHROMIUM_WASM_M7_LOCAL_STORAGE:";
const MAX_TIMEOUT_MS = 300000;
const MIN_TIMEOUT_MS = 20000;
const MAX_OUTPUT_LINES = 128;
const QUIESCENCE_MS = 50;
const SHA256_RE = /^[0-9a-f]{64}$/;
const TOKEN_RE = /^[0-9a-f]{64}$/;
const MODULE_ID_RE = /^[0-9a-f]{32}$/;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;
const PHASES = Object.freeze({
  write: Object.freeze({mode: "renderer-write", ordinal: 1}),
  verify: Object.freeze({mode: "renderer-verify", ordinal: 2}),
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
const DOCUMENT_FIELDS = Object.freeze([
  "identity", "navigationType", "ordinal", "phase", "timeOrigin",
]);
const TOKEN_EVIDENCE_FIELDS = Object.freeze([
  "algorithm", "digest", "rawTokenExcluded", "rawTokenLeakDetected",
  "rawTokenRedactionCount",
]);
const RUN_FIELDS = Object.freeze([
  "abortObserved", "expectedCleanExitStatusObserved", "factoryRejected",
  "factoryResolved", "factorySettled", "freshLoaderImport",
  "freshModuleObject", "leaseReleasedMarkerObserved", "lifecycleComplete",
  "markerCount", "markerSequenceAccepted", "markerSource", "markers",
  "mode", "moduleIdentity", "onExitCount", "ordinal", "outputLineCount",
  "processExitCode", "processExitCount", "runtimeExitCode",
  "runtimeInitialized", "stdoutMarkerCount",
]);
const BRIDGE_FIELDS = Object.freeze([
  "activeAtResult", "frozen", "installedBeforeModuleFactory", "permanent",
  "processExitDispatches", "protocol",
]);
const QUIESCENCE_FIELDS = Object.freeze([
  "callbacksAfterQuiescence", "callbacksAtClear", "quiet", "quietWindowMs",
]);
const HOST_BOUNDARY_FIELDS = Object.freeze([
  "hostDomStorageAccessAttempted", "hostOpfsAccessAttempted",
  "hostWebLocksAccessAttempted", "nativeCallAttempted",
  "wasmDataInspectionAttempted",
]);
const FAILURE_RUN_FIELDS = Object.freeze([
  "abortObserved", "expectedCleanExitStatusObserved", "factoryRejected",
  "factoryResolved", "factorySettled", "freshLoaderImport",
  "freshModuleObject", "leaseReleasedMarkerObserved", "lifecycleComplete",
  "markerCount", "markerSequenceAccepted", "onExitCount", "outputLineCount",
  "nativeFailureStage", "processExitCode", "processExitCount", "runtimeExitCode",
  "runtimeInitialized", "stdoutMarkerCount",
]);
const FAILURE_RUN_BOOLEAN_FIELDS = Object.freeze([
  "abortObserved", "expectedCleanExitStatusObserved", "factoryRejected",
  "factoryResolved", "factorySettled", "freshLoaderImport",
  "freshModuleObject", "leaseReleasedMarkerObserved", "lifecycleComplete",
  "markerSequenceAccepted", "runtimeInitialized",
]);
const FAILURE_RUN_COUNT_LIMITS = Object.freeze({
  markerCount: 6,
  onExitCount: 1,
  outputLineCount: MAX_OUTPUT_LINES + 1,
  processExitCount: 1,
  stdoutMarkerCount: MAX_OUTPUT_LINES + 1,
});
const FAILURE_DIAGNOSTIC_FIELDS = Object.freeze([
  "case", "failureClass", "hostBoundary", "m7GateComplete", "phase",
  "protocol", "run", "scope", "status",
]);
const HOST_FAILURE_CLASS = "host-lifecycle";
const NATIVE_FAILURE_STAGES = Object.freeze([
  "arguments", "capability", "storage", "profile", "read", "commit",
  "close", "fence", "lifecycle", "content", "drain",
]);
const RESULT_FIELDS = Object.freeze([
  "artifact", "bridge", "capture_harness", "case", "crossOriginIsolated",
  "document", "error", "hostBoundary", "m7GateComplete", "origin",
  "phase", "protocol", "quiescence", "run", "scope", "sharedArrayBuffer",
  "status", "tokenEvidence", "versions",
]);
const NORMAL_EXIT_STATUS = Object.freeze({
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
});

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function exactFields(value, fields, description) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== fields.length ||
      !fields.every((field) => Object.hasOwn(value, field))) {
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

function parseIdentity(value, description) {
  const identity = exactFields(value, BYTE_IDENTITY_FIELDS, description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(description + " is invalid");
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifact(value) {
  const artifact = exactFields(parseJson(value, "artifact"), ARTIFACT_FIELDS,
                               "artifact");
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
    build_config: parseIdentity(artifact.build_config, "build configuration"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseIdentity(artifact.loader, "loader"),
    module_name: artifact.module_name,
    wasm: parseIdentity(artifact.wasm, "Wasm"),
  });
}

function parseCaptureHarness(value) {
  const harness = exactFields(parseJson(value, "capture harness"),
                              CAPTURE_HARNESS_FIELDS, "capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("capture harness provenance is invalid");
  }
  return Object.freeze({
    host_html: parseIdentity(harness.host_html, "host HTML"),
    host_js: parseIdentity(harness.host_js, "host JavaScript"),
    runner_source: parseIdentity(harness.runner_source, "runner source"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = exactFields(parseJson(value, "versions"),
                               ["chromium", "emscripten", "v8"], "versions");
  for (const revision of Object.values(versions)) {
    if (typeof revision !== "string" || !/^[0-9a-f]{40}$/.test(revision)) {
      throw new Error("versions are invalid");
    }
  }
  return Object.freeze({...versions});
}

function oneQueryValue(query, name) {
  const values = query.getAll(name);
  if (values.length !== 1) {
    throw new Error("renderer LocalStorage query is invalid");
  }
  return values[0];
}

function parseContext() {
  const query = new URLSearchParams(location.search);
  const fields = [
    "artifact", "captureHarness", "module", "phase", "resultToken",
    "session", "timeoutMs", "versions",
  ];
  if ([...query.keys()].length !== fields.length ||
      !fields.every((field) => query.getAll(field).length === 1)) {
    throw new Error("renderer LocalStorage query is invalid");
  }
  const phase = oneQueryValue(query, "phase");
  const resultToken = oneQueryValue(query, "resultToken");
  const session = oneQueryValue(query, "session");
  const timeoutText = oneQueryValue(query, "timeoutMs");
  if (!Object.hasOwn(PHASES, phase) ||
      oneQueryValue(query, "module") !== PRODUCT_MODULE_NAME ||
      !CAPABILITY_RE.test(resultToken) || !CAPABILITY_RE.test(session) ||
      resultToken === session || !/^[0-9]+$/.test(timeoutText)) {
    throw new Error("renderer LocalStorage query is invalid");
  }
  const timeoutMs = Number(timeoutText);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("renderer LocalStorage timeout is invalid");
  }
  return Object.freeze({
    artifact: parseArtifact(oneQueryValue(query, "artifact")),
    captureHarness: parseCaptureHarness(oneQueryValue(query, "captureHarness")),
    moduleName: PRODUCT_MODULE_NAME,
    phase,
    resultToken,
    session,
    timeoutMs,
    versions: parseVersions(oneQueryValue(query, "versions")),
  });
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function randomHex(byteLength) {
  if (!globalThis.crypto || typeof globalThis.crypto.getRandomValues !== "function") {
    throw new Error("renderer LocalStorage random source is unavailable");
  }
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  return hex(bytes);
}

async function sha256Hex(bytes, description) {
  if (!(bytes instanceof Uint8Array) || !globalThis.crypto ||
      !globalThis.crypto.subtle || typeof globalThis.crypto.subtle.digest !== "function") {
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

async function fetchVerified(url, identity, contentType, description) {
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
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(description + " differs from its snapshot");
  }
  return bytes;
}

function expectedMarkers(mode, digest) {
  if (mode === "renderer-write") {
    return [
      MARKER_PREFIX + "READY",
      MARKER_PREFIX + "RENDERER_WRITE_OK sha256=" + digest,
      MARKER_PREFIX + "ON_DISK_COMMIT_OK sha256=" + digest,
      MARKER_PREFIX + "DB_CLOSE_OK sha256=" + digest,
      MARKER_PREFIX + "FENCE_OK sha256=" + digest,
      MARKER_PREFIX + "LEASE_RELEASED",
    ];
  }
  if (mode === "renderer-verify") {
    return [
      MARKER_PREFIX + "READY",
      MARKER_PREFIX + "RENDERER_REOPEN_READ_OK sha256=" + digest,
      MARKER_PREFIX + "ON_DISK_COMMIT_OK sha256=" + digest,
      MARKER_PREFIX + "DB_CLOSE_OK sha256=" + digest,
      MARKER_PREFIX + "FENCE_OK sha256=" + digest,
      MARKER_PREFIX + "LEASE_RELEASED",
    ];
  }
  throw new Error("renderer LocalStorage mode is invalid");
}

function parseNativeFailureStage(line) {
  const prefix = MARKER_PREFIX + "FAIL stage=";
  if (typeof line !== "string" || !line.startsWith(prefix)) {
    return null;
  }
  const stage = line.slice(prefix.length);
  return NATIVE_FAILURE_STAGES.includes(stage) ? stage : null;
}

function navigationType() {
  const entries = performance.getEntriesByType("navigation");
  if (entries.length !== 1 || typeof entries[0].type !== "string") {
    throw new Error("outer document navigation evidence is invalid");
  }
  return entries[0].type;
}

function isNormalExitStatus(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Object.keys(descriptors).length === 3 &&
      Object.keys(NORMAL_EXIT_STATUS).every((key) =>
        Object.hasOwn(descriptors, key) && descriptors[key].value === NORMAL_EXIT_STATUS[key]);
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
    moduleIdentity: randomHex(16),
    nativeFailureStage: null,
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

function boundedFailureCount(value, maximum) {
  if (!Number.isSafeInteger(value) || value < 0) {
    return maximum;
  }
  return Math.min(value, maximum);
}

function failureExitCode(value) {
  return Number.isSafeInteger(value) && value >= -(2 ** 31) &&
          value <= 2 ** 31 - 1 ?
      value : null;
}

class RendererLocalStorageOuterReloadHost {
  constructor(canvas, status, context) {
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement)) {
      throw new Error("renderer LocalStorage page is invalid");
    }
    this.canvas = canvas;
    this.status = status;
    this.context = context;
    this.document = Object.freeze({
      identity: randomHex(16),
      navigationType: navigationType(),
      ordinal: PHASES[context.phase].ordinal,
      phase: context.phase,
      timeOrigin: performance.timeOrigin,
    });
    this.deadline = performance.now() + context.timeoutMs;
    this.active = null;
    this.run = null;
    this.failure = false;
    this.bridgeInstalled = false;
    this.processExitDispatches = 0;
    this.callbackCount = 0;
    this.callbacksAtClear = 0;
    this.callbacksAfterQuiescence = 0;
    this.rawToken = null;
    this.rawTokenDigest = null;
    this.rawTokenTail = "";
    this.rawTokenLeakDetected = false;
    this.rawTokenRedactionCount = 0;
    this.loaderBytes = null;
    this.wasmBinary = null;
    this.wasmUrl = null;
    this.loaderImportUrl = null;
    this.loaderFactory = null;
    this.moduleObject = null;
    this.errorListener = null;
    this.rejectionListener = null;
  }

  fail() {
    this.failure = true;
  }

  noteCallback() {
    this.callbackCount += 1;
  }

  observeText(value) {
    if (typeof value !== "string" || this.rawToken === null) {
      return;
    }
    const candidate = this.rawTokenTail + value;
    if (candidate.includes(this.rawToken)) {
      this.rawTokenLeakDetected = true;
      this.rawTokenRedactionCount += 1;
      this.fail();
    }
    this.rawTokenTail = candidate.slice(-63);
  }

  installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("renderer LocalStorage bridge already exists");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.noteCallback();
        host.observeText(message);
        host.fail();
      },
      reportProcessExit(report) { host.routeProcessExit(report); },
      reportFrame(_report) { host.noteCallback(); },
      reportReadiness(_report) { host.noteCallback(); },
      reportOzoneFocusState(_report) { host.noteCallback(); },
      reportOzoneCursor(_report) { host.noteCallback(); return true; },
      reportOzoneTextInputState(_report) { host.noteCallback(); },
      reportOzoneTextInputDelivery(_report) { host.noteCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) { host.noteCallback(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) { host.noteCallback(); },
      requestOuterOriginStorageEstimate(_report) { host.noteCallback(); return false; },
      reportAccessibilitySnapshot(_report) { host.noteCallback(); return false; },
    });
    Object.defineProperty(globalThis, "__chromiumWasmHostBridgeV1", {
      configurable: false,
      enumerable: false,
      value: bridge,
      writable: false,
    });
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge || !Object.isFrozen(bridge)) {
      throw new Error("renderer LocalStorage bridge is mutable");
    }
    this.bridgeInstalled = true;
  }

  installFailureObservers() {
    this.errorListener = (event) => {
      this.noteCallback();
      this.observeText(event && typeof event.message === "string" ? event.message : "");
      this.fail();
    };
    this.rejectionListener = (event) => {
      this.noteCallback();
      const run = this.active;
      if (run && isNormalExitStatus(event.reason) && run.processExitCode === 0 &&
          run.onExitCount === 1 && !this.failure) {
        event.preventDefault();
        run.expectedCleanExitStatusObserved = true;
        this.maybeComplete(run);
        return;
      }
      this.observeText(typeof event.reason === "string" ? event.reason : "");
      this.fail();
    };
    addEventListener("error", this.errorListener);
    addEventListener("unhandledrejection", this.rejectionListener);
  }

  removeFailureObservers() {
    if (this.errorListener !== null) {
      removeEventListener("error", this.errorListener);
    }
    if (this.rejectionListener !== null) {
      removeEventListener("unhandledrejection", this.rejectionListener);
    }
    this.errorListener = null;
    this.rejectionListener = null;
  }

  routeProcessExit(report) {
    this.noteCallback();
    const run = this.active;
    if (!run || run.processExitCount !== 0 || run.onExitCount !== 0 ||
        !report || typeof report !== "object" || Array.isArray(report) ||
        Object.keys(report).length !== 2 || report.protocol !== HOST_PROTOCOL ||
        !Number.isSafeInteger(report.exitCode)) {
      this.fail();
      return;
    }
    run.processExitCount = 1;
    run.processExitCode = report.exitCode;
    this.processExitDispatches += 1;
    if (report.exitCode !== 0) {
      this.fail();
      return;
    }
    this.maybeComplete(run);
  }

  captureOutput(run, destination, line) {
    this.noteCallback();
    run.outputLineCount += 1;
    this.observeText(line);
    if (run.outputLineCount > MAX_OUTPUT_LINES || typeof line !== "string") {
      this.fail();
      return;
    }
    if (!line.startsWith(MARKER_PREFIX)) {
      return;
    }
    if (destination !== "stderr") {
      run.stdoutMarkerCount += 1;
      this.fail();
      return;
    }
    // This retains only an exact native stage from the fixed failure grammar;
    // the marker line itself is neither persisted nor included in diagnostics.
    const nativeFailureStage = parseNativeFailureStage(line);
    if (run.nativeFailureStage === null && nativeFailureStage !== null) {
      run.nativeFailureStage = nativeFailureStage;
    }
    const expected = expectedMarkers(run.mode, this.rawTokenDigest);
    if (run.markers.length >= expected.length ||
        line !== expected[run.markers.length]) {
      run.markerSequenceAccepted = false;
      this.fail();
      return;
    }
    run.markers.push(line);
    run.markerCount = run.markers.length;
    if (line === MARKER_PREFIX + "LEASE_RELEASED") {
      run.leaseReleasedMarkerObserved = true;
    }
    this.maybeComplete(run);
  }

  runtimeInitialized(run, module) {
    this.noteCallback();
    if (this.active !== run || run.runtimeInitialized || !module ||
        (run.factoryModule !== undefined && run.factoryModule !== module)) {
      this.fail();
      return;
    }
    run.runtimeModule = module;
    run.runtimeInitialized = true;
    this.maybeComplete(run);
  }

  runtimeExited(run, code) {
    this.noteCallback();
    if (this.active !== run || run.onExitCount !== 0 ||
        run.processExitCount !== 1 || run.processExitCode !== 0 ||
        !Number.isSafeInteger(code)) {
      this.fail();
      return;
    }
    run.onExitCount = 1;
    run.runtimeExitCode = code;
    if (code !== 0) {
      this.fail();
      return;
    }
    this.maybeComplete(run);
  }

  aborted(run, reason) {
    this.noteCallback();
    this.observeText(reason);
    if (!run.abortObserved) {
      run.abortObserved = true;
    }
    this.fail();
  }

  factoryResolved(run, module) {
    this.noteCallback();
    if (this.active !== run || run.factorySettled || !module ||
        (run.runtimeModule !== undefined && run.runtimeModule !== module)) {
      this.fail();
      return;
    }
    run.factoryModule = module;
    run.factorySettled = true;
    run.factoryResolved = true;
    run.freshModuleObject = true;
    this.moduleObject = module;
    this.maybeComplete(run);
  }

  factoryRejected(run, reason) {
    this.noteCallback();
    this.observeText(reason);
    if (this.active === run && !run.factorySettled) {
      run.factorySettled = true;
      run.factoryRejected = true;
    }
    this.fail();
  }

  cleanLifecycle(run) {
    const expected = expectedMarkers(run.mode, this.rawTokenDigest);
    return !this.failure && this.active === run && run.runtimeInitialized &&
        run.factorySettled && run.factoryResolved && !run.factoryRejected &&
        run.runtimeModule === run.factoryModule && !run.abortObserved &&
        run.processExitCount === 1 && run.processExitCode === 0 &&
        run.onExitCount === 1 && run.runtimeExitCode === 0 &&
        run.freshLoaderImport && run.freshModuleObject &&
        run.markerSequenceAccepted && run.markers.length === expected.length &&
        run.markers.every((marker, index) => marker === expected[index]) &&
        run.leaseReleasedMarkerObserved;
  }

  maybeComplete(run) {
    if (!run.lifecycleComplete && this.cleanLifecycle(run)) {
      run.lifecycleComplete = true;
    }
  }

  async fetchBootstrap() {
    const endpoint = new URL("./bootstrap/" + this.context.session, location.href);
    if (endpoint.origin !== location.origin) {
      throw new Error("bootstrap origin is invalid");
    }
    const response = await fetch(endpoint, {
      cache: "no-store", credentials: "same-origin", redirect: "error",
      referrerPolicy: "no-referrer",
    });
    if (!response.ok || response.url !== endpoint.href ||
        response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
            "application/json" || response.headers.get("cache-control") !== "no-store") {
      throw new Error("bootstrap response is invalid");
    }
    const payload = exactFields(await response.json(), [
      "case", "mode", "ordinal", "protocol", "scope", "token", "tokenDigest",
    ], "bootstrap payload");
    const expected = PHASES[this.context.phase];
    if (payload.protocol !== HOST_PROTOCOL || payload.case !== CASE ||
        payload.scope !== SCOPE || payload.ordinal !== expected.ordinal ||
        payload.mode !== expected.mode || typeof payload.token !== "string" ||
        !TOKEN_RE.test(payload.token) || typeof payload.tokenDigest !== "string" ||
        !SHA256_RE.test(payload.tokenDigest)) {
      throw new Error("bootstrap payload is invalid");
    }
    const digest = await sha256Hex(new TextEncoder().encode(payload.token),
                                   "renderer LocalStorage token");
    if (digest !== payload.tokenDigest) {
      throw new Error("bootstrap token digest is invalid");
    }
    this.rawToken = payload.token;
    this.rawTokenDigest = digest;
  }

  async fetchArtifacts() {
    const loaderUrl = new URL("./artifacts/" + this.context.moduleName + ".js", location.href);
    const wasmUrl = new URL("./artifacts/" + this.context.moduleName + ".wasm", location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("artifact origin is invalid");
    }
    [this.loaderBytes, this.wasmBinary] = await Promise.all([
      fetchVerified(loaderUrl, this.context.artifact.loader, "text/javascript", "loader"),
      fetchVerified(wasmUrl, this.context.artifact.wasm, "application/wasm", "Wasm"),
    ]);
    this.wasmUrl = wasmUrl;
  }

  async importFactory() {
    if (!(this.loaderBytes instanceof Uint8Array) || typeof Blob !== "function" ||
        typeof URL.createObjectURL !== "function" || typeof URL.revokeObjectURL !== "function") {
      throw new Error("fresh loader import is unavailable");
    }
    this.loaderImportUrl = URL.createObjectURL(
        new Blob([this.loaderBytes], {type: "text/javascript"}));
    const namespace = await import(this.loaderImportUrl);
    if (typeof namespace.default !== "function") {
      throw new Error("loader factory is invalid");
    }
    this.loaderFactory = namespace.default;
  }

  async runOneModule() {
    const expected = PHASES[this.context.phase];
    const run = newRun(expected.mode, expected.ordinal);
    this.run = run;
    this.active = run;
    await this.importFactory();
    run.freshLoaderImport = true;
    const host = this;
    let factoryResult;
    try {
      factoryResult = this.loaderFactory({
        arguments: [
          "--wasm-profile-local-storage-smoke=" + expected.mode,
          "--wasm-profile-local-storage-token=" + this.rawToken,
        ],
        canvas: this.canvas,
        locateFile(path) {
          if (path !== host.context.moduleName + ".wasm") {
            throw new Error("loader requested an unexpected artifact");
          }
          return host.wasmUrl.href;
        },
        mainScriptUrlOrBlob: this.loaderImportUrl,
        noExitRuntime: false,
        onAbort(reason) { host.aborted(run, reason); },
        onExit(code) { host.runtimeExited(run, code); },
        onRuntimeInitialized() { host.runtimeInitialized(run, this); },
        print(line) { host.captureOutput(run, "stdout", line); },
        printErr(line) { host.captureOutput(run, "stderr", line); },
        wasmBinary: this.wasmBinary,
      });
    } catch (error) {
      this.factoryRejected(run, error);
      throw error;
    }
    Promise.resolve(factoryResult).then(
        (module) => host.factoryResolved(run, module),
        (error) => host.factoryRejected(run, error));
    while (performance.now() < this.deadline && !this.failure &&
           !run.lifecycleComplete) {
      await delay(10);
    }
    if (!run.lifecycleComplete || !this.cleanLifecycle(run)) {
      this.fail();
      throw new Error("module lifecycle did not complete");
    }
    this.callbacksAtClear = this.callbackCount;
    this.active = null;
    await delay(QUIESCENCE_MS);
    this.callbacksAfterQuiescence = this.callbackCount;
    if (this.callbacksAtClear !== this.callbacksAfterQuiescence) {
      this.fail();
      throw new Error("module did not become quiescent");
    }
    run.factoryModule = undefined;
    run.runtimeModule = undefined;
    return this.snapshotRun(run);
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
      markerSource: "stderr-only-fixed-renderer-local-storage-grammar",
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

  failureRunSnapshot() {
    if (this.run === null) {
      return null;
    }
    const run = this.run;
    const snapshot = {};
    for (const field of FAILURE_RUN_BOOLEAN_FIELDS) {
      snapshot[field] = run[field] === true;
    }
    for (const [field, maximum] of Object.entries(FAILURE_RUN_COUNT_LIMITS)) {
      snapshot[field] = boundedFailureCount(run[field], maximum);
    }
    snapshot.processExitCode = failureExitCode(run.processExitCode);
    snapshot.runtimeExitCode = failureExitCode(run.runtimeExitCode);
    snapshot.nativeFailureStage = NATIVE_FAILURE_STAGES.includes(
        run.nativeFailureStage) ? run.nativeFailureStage : null;
    return snapshot;
  }

  failureDiagnostic() {
    return {
      case: CASE,
      failureClass: HOST_FAILURE_CLASS,
      hostBoundary: {
        hostDomStorageAccessAttempted: false,
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        nativeCallAttempted: false,
        wasmDataInspectionAttempted: false,
      },
      m7GateComplete: false,
      phase: this.context.phase,
      protocol: HOST_PROTOCOL,
      run: this.failureRunSnapshot(),
      scope: SCOPE,
      status: "fail",
    };
  }

  result(status) {
    const passed = status === "pass";
    return {
      artifact: this.context.artifact,
      bridge: {
        activeAtResult: this.active === null,
        frozen: this.bridgeInstalled && Object.isFrozen(globalThis.__chromiumWasmHostBridgeV1),
        installedBeforeModuleFactory: this.bridgeInstalled,
        permanent: this.bridgeInstalled,
        processExitDispatches: this.processExitDispatches,
        protocol: HOST_PROTOCOL,
      },
      capture_harness: this.context.captureHarness,
      case: CASE,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      document: this.document,
      error: passed ? null : "details-suppressed",
      hostBoundary: {
        hostDomStorageAccessAttempted: false,
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        nativeCallAttempted: false,
        wasmDataInspectionAttempted: false,
      },
      m7GateComplete: false,
      origin: location.origin,
      phase: this.context.phase,
      protocol: HOST_PROTOCOL,
      quiescence: {
        callbacksAfterQuiescence: this.callbacksAfterQuiescence,
        callbacksAtClear: this.callbacksAtClear,
        quiet: passed && this.callbacksAtClear === this.callbacksAfterQuiescence,
        quietWindowMs: QUIESCENCE_MS,
      },
      run: this.run ? this.snapshotRun(this.run) : null,
      scope: SCOPE,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      status,
      tokenEvidence: {
        algorithm: "SHA-256",
        digest: this.rawTokenDigest,
        rawTokenExcluded: true,
        rawTokenLeakDetected: this.rawTokenLeakDetected,
        rawTokenRedactionCount: this.rawTokenRedactionCount,
      },
      versions: this.context.versions,
    };
  }

  async runHost() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function" || location.origin === "null" ||
          this.document.navigationType !== "navigate") {
        throw new Error("outer document context is invalid");
      }
      this.canvas.focus({preventScroll: true});
      if (document.activeElement !== this.canvas) {
        throw new Error("canvas focus failed");
      }
      this.installFailureObservers();
      await this.fetchBootstrap();
      this.installBridge();
      await this.fetchArtifacts();
      await this.runOneModule();
    } catch (_error) {
      this.fail();
    }
    this.rawToken = null;
    this.rawTokenTail = "";
    this.loaderBytes = null;
    this.wasmBinary = null;
    this.wasmUrl = null;
    this.loaderFactory = null;
    this.moduleObject = null;
    if (this.loaderImportUrl !== null) {
      URL.revokeObjectURL(this.loaderImportUrl);
      this.loaderImportUrl = null;
    }
    this.status.textContent = this.failure ? "failed" : "passed";
    return this.result(this.failure ? "fail" : "pass");
  }

  dispose() {
    this.removeFailureObservers();
    this.rawToken = null;
    this.rawTokenTail = "";
  }
}

function validateFailureRunSnapshot(run) {
  if (run === null) {
    return null;
  }
  exactFields(run, FAILURE_RUN_FIELDS, "renderer LocalStorage failure run");
  if (FAILURE_RUN_BOOLEAN_FIELDS.some((field) => typeof run[field] !== "boolean")) {
    throw new Error("renderer LocalStorage failure run is invalid");
  }
  for (const [field, maximum] of Object.entries(FAILURE_RUN_COUNT_LIMITS)) {
    if (!Number.isSafeInteger(run[field]) || run[field] < 0 ||
        run[field] > maximum) {
      throw new Error("renderer LocalStorage failure run is invalid");
    }
  }
  for (const field of ["processExitCode", "runtimeExitCode"]) {
    if (run[field] !== null && (!Number.isSafeInteger(run[field]) ||
        run[field] < -(2 ** 31) || run[field] > 2 ** 31 - 1)) {
      throw new Error("renderer LocalStorage failure run is invalid");
    }
  }
  if (run.nativeFailureStage !== null &&
      !NATIVE_FAILURE_STAGES.includes(run.nativeFailureStage)) {
    throw new Error("renderer LocalStorage failure run is invalid");
  }
  return run;
}

function validateFailureDiagnostic(diagnostic) {
  exactFields(diagnostic, FAILURE_DIAGNOSTIC_FIELDS,
              "renderer LocalStorage failure diagnostic");
  if (diagnostic.protocol !== HOST_PROTOCOL || diagnostic.case !== CASE ||
      diagnostic.scope !== SCOPE || diagnostic.status !== "fail" ||
      diagnostic.m7GateComplete !== false ||
      diagnostic.failureClass !== HOST_FAILURE_CLASS ||
      !Object.hasOwn(PHASES, diagnostic.phase)) {
    throw new Error("renderer LocalStorage failure diagnostic is invalid");
  }
  const boundary = exactFields(diagnostic.hostBoundary, HOST_BOUNDARY_FIELDS,
                               "renderer LocalStorage failure boundary");
  if (Object.values(boundary).some((value) => value !== false)) {
    throw new Error("renderer LocalStorage failure boundary is invalid");
  }
  validateFailureRunSnapshot(diagnostic.run);
  return diagnostic;
}

function validateDocument(result) {
  exactFields(result, RESULT_FIELDS, "renderer LocalStorage result");
  if (result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
      result.scope !== SCOPE || result.status !== "pass" ||
      result.m7GateComplete !== false || result.crossOriginIsolated !== true ||
      result.sharedArrayBuffer !== true || typeof result.origin !== "string" ||
      result.error !== null || !Object.hasOwn(PHASES, result.phase)) {
    throw new Error("renderer LocalStorage result is invalid");
  }
  const expected = PHASES[result.phase];
  const documentReceipt = exactFields(result.document, DOCUMENT_FIELDS,
                                      "outer document receipt");
  const run = exactFields(result.run, RUN_FIELDS, "renderer LocalStorage run");
  const evidence = exactFields(result.tokenEvidence, TOKEN_EVIDENCE_FIELDS,
                               "token evidence");
  const bridge = exactFields(result.bridge, BRIDGE_FIELDS, "host bridge");
  const quiescence = exactFields(result.quiescence, QUIESCENCE_FIELDS,
                                 "quiescence receipt");
  const boundary = exactFields(result.hostBoundary, HOST_BOUNDARY_FIELDS,
                               "host boundary");
  if (documentReceipt.phase !== result.phase || documentReceipt.ordinal !== expected.ordinal ||
      documentReceipt.navigationType !== "navigate" ||
      typeof documentReceipt.timeOrigin !== "number" ||
      !Number.isFinite(documentReceipt.timeOrigin) ||
      typeof documentReceipt.identity !== "string" ||
      !MODULE_ID_RE.test(documentReceipt.identity) || run.mode !== expected.mode ||
      run.ordinal !== expected.ordinal || !MODULE_ID_RE.test(run.moduleIdentity) ||
      run.abortObserved !== false ||
      typeof run.expectedCleanExitStatusObserved !== "boolean" ||
      run.factoryRejected !== false || run.factoryResolved !== true ||
      run.factorySettled !== true || run.freshLoaderImport !== true ||
      run.freshModuleObject !== true || run.leaseReleasedMarkerObserved !== true ||
      run.lifecycleComplete !== true || run.markerSequenceAccepted !== true ||
      run.markerSource !== "stderr-only-fixed-renderer-local-storage-grammar" ||
      run.processExitCode !== 0 || run.processExitCount !== 1 ||
      run.runtimeExitCode !== 0 || run.onExitCount !== 1 ||
      run.runtimeInitialized !== true || run.stdoutMarkerCount !== 0 ||
      !Number.isSafeInteger(run.outputLineCount) || run.outputLineCount < 1 ||
      !Array.isArray(run.markers) || run.markerCount !== run.markers.length ||
      !SHA256_RE.test(evidence.digest) || evidence.algorithm !== "SHA-256" ||
      evidence.rawTokenExcluded !== true || evidence.rawTokenLeakDetected !== false ||
      evidence.rawTokenRedactionCount !== 0 || bridge.protocol !== HOST_PROTOCOL ||
      bridge.permanent !== true || bridge.frozen !== true ||
      bridge.installedBeforeModuleFactory !== true || bridge.processExitDispatches !== 1 ||
      bridge.activeAtResult !== true || quiescence.quiet !== true ||
      quiescence.quietWindowMs !== QUIESCENCE_MS ||
      !Number.isSafeInteger(quiescence.callbacksAtClear) ||
      quiescence.callbacksAtClear !== quiescence.callbacksAfterQuiescence ||
      Object.values(boundary).some((value) => value !== false)) {
    throw new Error("renderer LocalStorage receipt is invalid");
  }
  const markers = expectedMarkers(expected.mode, evidence.digest);
  if (run.markers.length !== markers.length ||
      !run.markers.every((marker, index) => marker === markers[index])) {
    throw new Error("renderer LocalStorage marker receipt is invalid");
  }
  return result;
}

// This validator deliberately accepts one receipt only. The Python runner
// combines two independently posted documents and verifies their order,
// identity, and shared token digest without using host-side storage.
export function validateChromeWasmRendererLocalStorageOuterReloadDocumentResult(result) {
  return validateDocument(result);
}

// Failure diagnostics intentionally retain only a fixed phase and bounded
// lifecycle counters. They do not contain output text, marker strings, module
// identity, token material, or an exception message, and they never satisfy
// the success-receipt validator above.
export function validateChromeWasmRendererLocalStorageOuterReloadFailureDiagnostic(
    diagnostic) {
  return validateFailureDiagnostic(diagnostic);
}

async function postDocumentResult(context, result) {
  const endpoint = new URL("./result/" + context.resultToken + "/" + context.phase,
                           location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("result origin is invalid");
  }
  const response = await fetch(endpoint, {
    method: "POST", cache: "no-store", credentials: "same-origin",
    redirect: "error", referrerPolicy: "no-referrer",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(result),
  });
  if (context.phase === "verify") {
    if (response.status !== 204) {
      throw new Error("final result acknowledgement is invalid");
    }
    return null;
  }
  if (response.status !== 200 ||
      response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
          "application/json") {
    throw new Error("write result acknowledgement is invalid");
  }
  const value = exactFields(await response.json(), ["nextDocument"],
                            "next document acknowledgement");
  const next = new URL(value.nextDocument, location.href);
  if (next.origin !== location.origin || next.protocol !== location.protocol ||
      next.pathname !== location.pathname || next.searchParams.get("phase") !== "verify") {
    throw new Error("next document acknowledgement is invalid");
  }
  return next;
}

async function postFailureDiagnostic(context, diagnostic) {
  validateFailureDiagnostic(diagnostic);
  if (diagnostic.phase !== context.phase) {
    throw new Error("failure diagnostic phase is invalid");
  }
  const endpoint = new URL("./failure/" + context.resultToken + "/" + context.phase,
                           location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("failure diagnostic origin is invalid");
  }
  const response = await fetch(endpoint, {
    method: "POST", cache: "no-store", credentials: "same-origin",
    redirect: "error", referrerPolicy: "no-referrer",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(diagnostic),
  });
  if (response.status !== 204) {
    throw new Error("failure diagnostic acknowledgement is invalid");
  }
}

function showVersions(element, versions) {
  element.replaceChildren();
  for (const name of ["chromium", "v8", "emscripten"]) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = versions[name];
    element.append(term, definition);
  }
}

export async function runChromeWasmRendererLocalStorageOuterReloadFromQuery() {
  let host = null;
  try {
    const context = parseContext();
    const canvas = document.querySelector(
        "#m7-renderer-local-storage-outer-reload-canvas");
    const status = document.querySelector(
        "#m7-renderer-local-storage-outer-reload-status");
    const versions = document.querySelector(
        "#m7-renderer-local-storage-outer-reload-versions");
    const root = document.querySelector(
        "#m7-renderer-local-storage-outer-reload-root");
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement) ||
        !(versions instanceof HTMLElement) || !(root instanceof HTMLElement)) {
      throw new Error("renderer LocalStorage page is invalid");
    }
    showVersions(versions, context.versions);
    host = new RendererLocalStorageOuterReloadHost(canvas, status, context);
    const result = await host.runHost();
    if (result.status === "fail") {
      // A failed lifecycle is terminal. Send only the fixed redacted summary
      // so the runner can stop promptly; do not validate or post it as a
      // success receipt and do not navigate to the second outer document.
      root.dataset.state = "fail";
      await postFailureDiagnostic(context, host.failureDiagnostic());
      throw new Error("renderer LocalStorage host lifecycle failed");
    }
    validateDocument(result);
    root.dataset.state = result.status;
    const next = await postDocumentResult(context, result);
    if (next !== null) {
      // This is intentionally a navigation to a new outer host document only
      // after the server has accepted the write receipt. No DOM-storage state
      // is retained across the two documents.
      location.replace(next.href);
    }
  } finally {
    if (host !== null) {
      host.dispose();
    }
  }
}

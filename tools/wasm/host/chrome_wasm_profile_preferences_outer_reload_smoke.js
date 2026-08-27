// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Three-outer-document Preferences, CookieManager, and core HistoryService
// handoff witness. Chromium owns the profile, registered preference, fixed
// Browser close, CookieManager flush/reopen and SQLite backend close,
// History/Favicons database close, lifecycle fence, backend drain, and
// cooperative lease. The host receives one runner-escrowed argument bundle per
// document; it neither opens profile storage nor retains raw preference values
// in a receipt. This is intentionally an orderly-reload witness, not a crash
// or recovery claim. Cookie markers prove only this narrow Chromium-side
// persistence path, not full cookie-service or profile persistence.

const HOST_PROTOCOL = 1;
const CASE = "chrome_profile_preferences_three_outer_document_reload_m7";
const SCOPE =
    "same-origin-three-outer-documents-chrome-wasm-m7-profile-preferences-" +
    "cookie-manager-and-history-test-modules-orderly-reload-only";
const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_preferences_test";
const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_PREFS:";
const SUPPRESSED_NATIVE_OUTPUT = "<suppressed-native-output>";
const MAX_TIMEOUT_MS = 120000;
const MAX_OUTPUT_LINES = 128;
const MAX_ERROR_RECORDS = 16;
const TOKEN_BYTES = 32;
const MODULE_ID_BYTES = 16;
const FINAL_QUIESCENCE_MS = 50;
const SHA256_RE = /^[0-9a-f]{64}$/;
const MODULE_ID_RE = /^[0-9a-f]{32}$/;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;

const BYTE_IDENTITY_FIELDS = Object.freeze(["bytes", "sha256"]);
const ARTIFACT_FIELDS = Object.freeze([
  "artifact_delivery", "artifact_source_provenance", "build_config",
  "build_config_provenance", "loader", "module_name", "wasm",
]);
const CAPTURE_HARNESS_FIELDS = Object.freeze([
  "host_html", "host_js", "runner_source", "source_snapshot_provenance",
  "version_provenance",
]);
const BOOTSTRAP_FIELDS = Object.freeze([
  "protocol", "case", "scope", "ordinal", "mode", "tokenA", "tokenB",
  "tokenADigest", "tokenBDigest",
]);
const BOOTSTRAP_DOCUMENT_FIELDS = Object.freeze([
  "protocol", "case", "scope", "navigationType", "timeOrigin",
]);
const DOCUMENT_FIELDS = Object.freeze(["navigationType", "timeOrigin"]);
const TOKEN_EVIDENCE_FIELDS = Object.freeze([
  "algorithm", "tokenA", "tokenB", "distinct", "rawTokensExcluded",
  "rawTokenLeakDetected", "rawTokenRedactionCount",
]);
const BRIDGE_FIELDS = Object.freeze([
  "protocol", "permanent", "frozen", "installedBeforeModuleFactory",
  "processExitDispatches", "noActiveProcessExitRejected",
  "duplicateProcessExitRejected", "lateProcessExitRejected", "activeRunAtResult",
]);
const RESULT_FIELDS = Object.freeze([
  "protocol", "case", "scope", "status", "ordinal", "mode", "origin",
  "crossOriginIsolated", "sharedArrayBuffer", "document", "artifact",
  "capture_harness", "versions", "tokenEvidence", "run", "bridge",
  "finalQuiescence", "hostBoundary", "fatalErrors", "windowErrors",
  "unhandledRejections", "failedChecks", "error",
]);
const RUN_FIELDS = Object.freeze([
  "abort", "activeClearedAfterLifecycle", "expectedExitStatusObserved",
  "factoryError", "factorySettled", "freshModuleObject",
  "leaseReleasedMarkerObserved", "markerCount",
  "markerDeliveryCompleteAtProcessExit", "markerSequenceAccepted",
  "markerSource", "markers", "mode", "moduleIdentity", "onExitCount",
  "ordinal", "postLifecycleTimerObserved", "processExitBeforeOnExit",
  "processExitCode", "processExitCount", "runtimeExitCode",
  "runtimeInitialized", "stderr", "stdout",
]);
const QUIESCENCE_FIELDS = Object.freeze([
  "taskScheduledExactlyOnce", "taskMethod",
  "postLifecycleTimerObservedBeforeTask", "started", "startedAfterActiveClear",
  "completed", "quietWindowMs", "quiet", "callbacksAtActiveClear",
  "callbacksAtTaskStart", "callbacksAtTaskEnd", "callbacksAtPreUploadCheck",
  "processExitReportsAtActiveClear", "processExitReportsAtTaskStart",
  "processExitReportsAtTaskEnd", "processExitReportsAtPreUploadCheck",
  "activeRunAtActiveClear", "activeRunAtTaskStart", "activeRunAtTaskEnd",
  "activeRunAtPreUploadCheck", "bridgeRecheckedImmediatelyBeforeUpload",
]);
const HOST_BOUNDARY_FIELDS = Object.freeze([
  "hostOpfsAccessAttempted", "hostWebLocksAccessAttempted",
  "nativeCallAttempted", "wasmDataInspectionAttempted",
  "sessionStorageAccessAttempted", "localStorageAccessAttempted",
  "indexedDbAccessAttempted", "cookieAccessAttempted",
  "historyStateAccessAttempted", "windowNameAccessAttempted",
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

function parsePositiveTimeout(value) {
  if (typeof value !== "string" || !/^[0-9]+$/.test(value)) {
    throw new Error("outer-reload timeout is invalid");
  }
  const timeoutMs = Number(value);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("outer-reload timeout is invalid");
  }
  return timeoutMs;
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, BYTE_IDENTITY_FIELDS, description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifactIdentity(value) {
  const artifact = requireExactFields(
      parseQueryJson(value, "outer-reload artifact identity"), ARTIFACT_FIELDS,
      "outer-reload artifact identity");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error("outer-reload artifact identity is invalid");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    build_config: parseByteIdentity(artifact.build_config,
                                    "outer-reload build configuration"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "outer-reload loader"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "outer-reload Wasm"),
  });
}

function parseCaptureHarnessIdentity(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "outer-reload capture harness"),
      CAPTURE_HARNESS_FIELDS, "outer-reload capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("outer-reload capture harness is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html, "outer-reload host HTML"),
    host_js: parseByteIdentity(harness.host_js, "outer-reload host JavaScript"),
    runner_source: parseByteIdentity(harness.runner_source,
                                     "outer-reload runner source"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = requireExactFields(
      parseQueryJson(value, "outer-reload versions"),
      ["chromium", "v8", "emscripten"], "outer-reload versions");
  for (const revision of Object.values(versions)) {
    if (typeof revision !== "string" || !/^[0-9a-f]{40}$/.test(revision)) {
      throw new Error("outer-reload versions are invalid");
    }
  }
  return Object.freeze({...versions});
}

function parseStaticContext() {
  const query = new URLSearchParams(location.search);
  const allowed = new Set([
    "resultToken", "session", "module", "timeoutMs", "versions", "artifact",
    "captureHarness",
  ]);
  for (const name of query.keys()) {
    if (!allowed.has(name) || query.getAll(name).length !== 1) {
      throw new Error("outer-reload query is invalid");
    }
  }
  const resultToken = asNonemptyString(query.get("resultToken"),
                                       "outer-reload result capability");
  const session = asNonemptyString(query.get("session"),
                                    "outer-reload session capability");
  if (!CAPABILITY_RE.test(resultToken) || !CAPABILITY_RE.test(session) ||
      resultToken === session || query.get("module") !== PRODUCT_MODULE_NAME) {
    throw new Error("outer-reload query is invalid");
  }
  return Object.freeze({
    artifact: parseArtifactIdentity(query.get("artifact")),
    captureHarness: parseCaptureHarnessIdentity(query.get("captureHarness")),
    moduleName: PRODUCT_MODULE_NAME,
    resultToken,
    session,
    timeoutMs: parsePositiveTimeout(query.get("timeoutMs")),
    versions: parseVersions(query.get("versions")),
  });
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function randomHex(byteLength) {
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 ||
      !globalThis.crypto || typeof globalThis.crypto.getRandomValues !== "function") {
    throw new Error("outer-reload random source is unavailable");
  }
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  return hex(bytes);
}

async function sha256Hex(bytes, description) {
  if (!(bytes instanceof Uint8Array) || !globalThis.crypto ||
      !globalThis.crypto.subtle ||
      typeof globalThis.crypto.subtle.digest !== "function") {
    throw new Error(`${description} requires Web Crypto SHA-256`);
  }
  let digest;
  try {
    digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  } catch (_error) {
    throw new Error(`${description} SHA-256 failed`);
  }
  if (!(digest instanceof ArrayBuffer)) {
    throw new Error(`${description} SHA-256 is invalid`);
  }
  return hex(new Uint8Array(digest));
}

function requireResponseHeaders(response, contentType, description) {
  const actualType = response.headers.get("Content-Type")
      ?.split(";", 1)[0].trim().toLowerCase();
  const required = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if ((contentType !== null && actualType !== contentType) ||
      Object.entries(required).some(
          ([name, expected]) => response.headers.get(name) !== expected)) {
    throw new Error(`${description} response headers are invalid`);
  }
}

function appendOutput(destination, value, exactMarker) {
  if (destination.length < MAX_OUTPUT_LINES) {
    destination.push(value);
    return;
  }
  const ordinary = destination.findIndex(
      (line) => !line.startsWith(M7_MARKER_PREFIX));
  if (ordinary !== -1) {
    destination.splice(ordinary, 1);
    destination.push(value);
  } else if (exactMarker) {
    destination.shift();
    destination.push(value);
  }
}

async function fetchVerifiedArtifact(url, identity, contentType, description) {
  let response;
  try {
    response = await fetch(url.href, {
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
  } catch (_error) {
    throw new Error(`${description} request is invalid`);
  }
  if (!response.ok || response.url !== url.href) {
    throw new Error(`${description} request is invalid`);
  }
  requireResponseHeaders(response, contentType, description);
  let body;
  try {
    body = await response.arrayBuffer();
  } catch (_error) {
    throw new Error(`${description} body is invalid`);
  }
  const bytes = new Uint8Array(body);
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} identity is invalid`);
  }
  return bytes;
}

function expectedMarkers(ordinal, tokenEvidence) {
  if (ordinal === 1) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}WRITE_ACCEPTED sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}BROWSER_SMOKE_CLOSED`,
      `${M7_MARKER_PREFIX}COOKIE_A_WRITE_FLUSHED sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}COOKIE_BACKEND_CLOSED`,
      `${M7_MARKER_PREFIX}HISTORY_A_WRITE_ACCEPTED`,
      `${M7_MARKER_PREFIX}HISTORY_BACKEND_CLOSED`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  if (ordinal === 2) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}READ_A_OK sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}WRITE_ACCEPTED sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}BROWSER_SMOKE_CLOSED`,
      `${M7_MARKER_PREFIX}COOKIE_A_READ_OK sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}COOKIE_B_WRITE_FLUSHED sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}COOKIE_BACKEND_CLOSED`,
      `${M7_MARKER_PREFIX}HISTORY_A_READ_OK`,
      `${M7_MARKER_PREFIX}HISTORY_B_WRITE_ACCEPTED`,
      `${M7_MARKER_PREFIX}HISTORY_BACKEND_CLOSED`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  if (ordinal === 3) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}READ_B_OK sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}BROWSER_SMOKE_CLOSED`,
      `${M7_MARKER_PREFIX}COOKIE_B_READ_OK sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}COOKIE_BACKEND_CLOSED`,
      `${M7_MARKER_PREFIX}HISTORY_A_READ_OK`,
      `${M7_MARKER_PREFIX}HISTORY_B_READ_OK`,
      `${M7_MARKER_PREFIX}HISTORY_BACKEND_CLOSED`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  throw new Error("outer-reload ordinal is invalid");
}

function documentEvidence() {
  const navigation = performance.getEntriesByType("navigation")[0];
  const navigationType = navigation && typeof navigation === "object" ?
      navigation.type : null;
  const timeOrigin = performance.timeOrigin;
  if ((navigationType !== "navigate" && navigationType !== "reload") ||
      typeof timeOrigin !== "number" || !Number.isFinite(timeOrigin) ||
      timeOrigin <= 0) {
    throw new Error("outer-reload document evidence is invalid");
  }
  return Object.freeze({navigationType, timeOrigin});
}

function bootstrapUrl(context) {
  const endpoint = new URL(
      `./bootstrap/${encodeURIComponent(context.session)}`, location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("outer-reload bootstrap endpoint is invalid");
  }
  return endpoint;
}

async function postJson(endpoint, payload, description) {
  let response;
  try {
    response = await fetch(endpoint.href, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
  } catch (_error) {
    throw new Error(`${description} request failed`);
  }
  if (response.status !== 204 || response.url !== endpoint.href) {
    throw new Error(`${description} response is invalid`);
  }
  requireResponseHeaders(response, null, description);
}

async function postBootstrapDocumentEvidence(context, evidence) {
  requireExactFields(evidence, ["navigationType", "timeOrigin"],
                     "outer-reload document evidence");
  await postJson(bootstrapUrl(context), {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    navigationType: evidence.navigationType,
    timeOrigin: evidence.timeOrigin,
  }, "outer-reload bootstrap evidence");
}

async function fetchBootstrap(context) {
  const endpoint = bootstrapUrl(context);
  let response;
  try {
    response = await fetch(endpoint.href, {
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
  } catch (_error) {
    throw new Error("outer-reload bootstrap request failed");
  }
  if (response.status !== 200 || response.url !== endpoint.href) {
    throw new Error("outer-reload bootstrap request was rejected");
  }
  requireResponseHeaders(response, "application/json", "outer-reload bootstrap");
  let value;
  try {
    value = await response.json();
  } catch (_error) {
    throw new Error("outer-reload bootstrap is invalid");
  }
  const bootstrap = requireExactFields(value, BOOTSTRAP_FIELDS,
                                       "outer-reload bootstrap");
  const first = bootstrap.ordinal === 1;
  const second = bootstrap.ordinal === 2;
  const third = bootstrap.ordinal === 3;
  if (bootstrap.protocol !== HOST_PROTOCOL || bootstrap.case !== CASE ||
      bootstrap.scope !== SCOPE ||
      !((first && bootstrap.mode === "write") ||
        (second && bootstrap.mode === "verify-and-write") ||
        (third && bootstrap.mode === "verify-b")) ||
      ((!third && (typeof bootstrap.tokenA !== "string" ||
                   !SHA256_RE.test(bootstrap.tokenA) ||
                   typeof bootstrap.tokenADigest !== "string" ||
                   !SHA256_RE.test(bootstrap.tokenADigest))) ||
       (third && (bootstrap.tokenA !== null || bootstrap.tokenADigest !== null))) ||
      (first && (bootstrap.tokenB !== null || bootstrap.tokenBDigest !== null)) ||
      (!first && (typeof bootstrap.tokenB !== "string" ||
                  !SHA256_RE.test(bootstrap.tokenB) ||
                  typeof bootstrap.tokenBDigest !== "string" ||
                  !SHA256_RE.test(bootstrap.tokenBDigest) ||
                  (second && bootstrap.tokenA === bootstrap.tokenB)))) {
    throw new Error("outer-reload bootstrap is invalid");
  }
  const encoder = new TextEncoder();
  const tokenA = third ? null : await sha256Hex(encoder.encode(bootstrap.tokenA),
                                                "outer-reload token A");
  const tokenB = first ? null : await sha256Hex(encoder.encode(bootstrap.tokenB),
                                                "outer-reload token B");
  if ((!third && tokenA !== bootstrap.tokenADigest) ||
      (!first && tokenB !== bootstrap.tokenBDigest)) {
    throw new Error("outer-reload bootstrap token identity is invalid");
  }
  return Object.freeze({
    mode: bootstrap.mode,
    ordinal: bootstrap.ordinal,
    rawTokens: Object.freeze({tokenA: bootstrap.tokenA, tokenB: bootstrap.tokenB}),
    tokenEvidence: Object.freeze({
      algorithm: "SHA-256",
      tokenA,
      tokenB,
      distinct: second ? true : null,
      rawTokensExcluded: true,
      rawTokenLeakDetected: false,
      rawTokenRedactionCount: 0,
    }),
  });
}

function isExactNormalExitStatus(value) {
  try {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      return false;
    }
    const descriptors = Object.getOwnPropertyDescriptors(value);
    if (Reflect.ownKeys(descriptors).length !== 3 ||
        !["name", "status", "message"].every((field) =>
          Object.hasOwn(descriptors, field) &&
          Object.hasOwn(descriptors[field], "value") &&
          !Object.hasOwn(descriptors[field], "get") &&
          !Object.hasOwn(descriptors[field], "set"))) {
      return false;
    }
    return descriptors.name.value === "ExitStatus" &&
        descriptors.status.value === 0 &&
        descriptors.message.value === "Program terminated with exit(0)";
  } catch (_error) {
    return false;
  }
}

class PreferencesOuterReloadHost {
  constructor(canvas, context, bootstrap, documentReceipt) {
    this.canvas = canvas;
    this.context = context;
    this.bootstrap = bootstrap;
    this.document = Object.freeze({...documentReceipt});
    this.rawTokens = bootstrap.rawTokens;
    this.artifact = context.artifact;
    this.captureHarness = context.captureHarness;
    this.versions = context.versions;
    this.activeRun = null;
    this.run = null;
    this.factory = null;
    this.loaderImportUrl = null;
    this.mainScriptUrlOrBlob = null;
    this.wasmBinary = null;
    this.wasmUrl = null;
    this.bridgeInstalled = false;
    this.bridgeInstalledBeforeModuleFactory = false;
    this.bridgeProcessExitDispatches = 0;
    this.noActiveProcessExitRejected = 0;
    this.duplicateProcessExitRejected = 0;
    this.lateProcessExitRejected = 0;
    this.callbackCount = 0;
    this.processExitReportCount = 0;
    this.rawTokenLeakDetected = false;
    this.rawTokenRedactionCount = 0;
    this.opaqueTokenTail = "";
    this.fatalErrors = [];
    this.failedChecks = [];
    this.windowErrors = [];
    this.unhandledRejections = [];
    this.windowErrorHandler = undefined;
    this.unhandledRejectionHandler = undefined;
    this.quiescence = {
      taskScheduledExactlyOnce: false,
      taskMethod: null,
      postLifecycleTimerObservedBeforeTask: false,
      started: false,
      startedAfterActiveClear: false,
      completed: false,
      quietWindowMs: FINAL_QUIESCENCE_MS,
      quiet: false,
      callbacksAtActiveClear: null,
      callbacksAtTaskStart: null,
      callbacksAtTaskEnd: null,
      callbacksAtPreUploadCheck: null,
      processExitReportsAtActiveClear: null,
      processExitReportsAtTaskStart: null,
      processExitReportsAtTaskEnd: null,
      processExitReportsAtPreUploadCheck: null,
      activeRunAtActiveClear: null,
      activeRunAtTaskStart: null,
      activeRunAtTaskEnd: null,
      activeRunAtPreUploadCheck: null,
      bridgeRecheckedImmediatelyBeforeUpload: false,
    };
    this.completionPromise = new Promise((resolve) => {
      this.completeQuiescence = resolve;
    });
  }

  noteCallback() {
    ++this.callbackCount;
  }

  recordFailure(code) {
    if (this.failedChecks.length < MAX_ERROR_RECORDS) {
      this.failedChecks.push(code);
    }
  }

  recordFatal(code) {
    this.recordFailure(code);
    if (this.fatalErrors.length < MAX_ERROR_RECORDS) {
      this.fatalErrors.push(code);
    }
  }

  scrubCapturedFields() {
    const scrubbed = "<scrubbed-after-opaque-token-leak>";
    this.fatalErrors = this.fatalErrors.map(() => scrubbed);
    this.failedChecks = this.failedChecks.map(() => scrubbed);
    this.windowErrors = this.windowErrors.map(() => scrubbed);
    this.unhandledRejections = this.unhandledRejections.map(() => scrubbed);
    if (this.run !== null) {
      this.run.abort = this.run.abort === null ? null : scrubbed;
      this.run.factoryError = this.run.factoryError === null ? null : scrubbed;
      this.run.markers = this.run.markers.map(() => scrubbed);
      this.run.stderr = this.run.stderr.map(() => scrubbed);
      this.run.stdout = this.run.stdout.map(() => scrubbed);
      this.run.markerSequenceAccepted = false;
      this.run.leaseReleasedMarkerObserved = false;
    }
  }

  recordOpaqueTokenLeak() {
    if (this.rawTokenLeakDetected) return;
    this.rawTokenLeakDetected = true;
    ++this.rawTokenRedactionCount;
    this.opaqueTokenTail = "";
    this.scrubCapturedFields();
  }

  safeText(value, trackAcrossCallbacks) {
    if (this.rawTokenLeakDetected) return "<scrubbed-after-opaque-token-leak>";
    if (typeof value !== "string") return "<suppressed-nonstring>";
    const combined = trackAcrossCallbacks ? this.opaqueTokenTail + value : value;
    if (Object.values(this.rawTokens).some((token) =>
      typeof token === "string" && combined.includes(token))) {
      this.recordOpaqueTokenLeak();
      return "<scrubbed-after-opaque-token-leak>";
    }
    if (trackAcrossCallbacks) {
      this.opaqueTokenTail = combined.slice(-(TOKEN_BYTES * 2 - 1));
    }
    return value;
  }

  installErrorHandlers() {
    this.windowErrorHandler = (event) => {
      this.noteCallback();
      this.safeText(typeof event?.message === "string" ? event.message : "", true);
      if (this.windowErrors.length < MAX_ERROR_RECORDS) {
        this.windowErrors.push("<suppressed-window-error>");
      }
      this.recordFatal("window-error");
    };
    this.unhandledRejectionHandler = (event) => {
      this.noteCallback();
      let reason = null;
      try {
        reason = event.reason;
      } catch (_error) {
        // The fixed failure below never reflects a hostile reason.
      }
      if (this.acceptExpectedExitStatus(event, reason)) return;
      this.safeText(typeof reason === "string" ? reason : "", true);
      if (this.unhandledRejections.length < MAX_ERROR_RECORDS) {
        this.unhandledRejections.push("<suppressed-unhandled-rejection>");
      }
      this.recordFatal("unhandled-rejection");
    };
    addEventListener("error", this.windowErrorHandler);
    addEventListener("unhandledrejection", this.unhandledRejectionHandler);
  }

  releaseErrorHandlers() {
    if (this.windowErrorHandler !== undefined) {
      removeEventListener("error", this.windowErrorHandler);
      this.windowErrorHandler = undefined;
    }
    if (this.unhandledRejectionHandler !== undefined) {
      removeEventListener("unhandledrejection", this.unhandledRejectionHandler);
      this.unhandledRejectionHandler = undefined;
    }
  }

  installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("outer-reload host bridge already exists");
    }
    const host = this;
    const note = () => host.noteCallback();
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(_message) { note(); host.recordFatal("native-bridge-fatal"); },
      reportProcessExit(report) { host.routeProcessExit(report); },
      reportFrame(_report) { note(); },
      reportReadiness(_report) { note(); },
      reportOzoneFocusState(_report) { note(); },
      reportOzoneCursor(_report) { note(); return true; },
      reportOzoneTextInputState(_report) { note(); },
      reportOzoneTextInputDelivery(_report) { note(); },
      reportOzoneBrowserTextInputDelivery(_report) { note(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) { note(); },
      requestOuterOriginStorageEstimate(_report) { note(); return false; },
      reportAccessibilitySnapshot(_report) { note(); return false; },
    });
    Object.defineProperty(globalThis, "__chromiumWasmHostBridgeV1", {
      configurable: false,
      enumerable: false,
      value: bridge,
      writable: false,
    });
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge ||
        !Object.isFrozen(bridge)) {
      throw new Error("outer-reload host bridge is invalid");
    }
    this.bridgeInstalled = true;
  }

  async prepareFactory() {
    const loaderUrl = new URL(
        `./artifacts/${this.context.moduleName}.js`, location.href);
    const wasmUrl = new URL(
        `./artifacts/${this.context.moduleName}.wasm`, location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("outer-reload artifacts are not same-origin");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(loaderUrl, this.artifact.loader, "text/javascript",
                            "outer-reload loader"),
      fetchVerifiedArtifact(wasmUrl, this.artifact.wasm, "application/wasm",
                            "outer-reload Wasm"),
    ]);
    if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("outer-reload verified loader import is unavailable");
    }
    const blob = new Blob([loaderBytes], {type: "text/javascript"});
    this.loaderImportUrl = URL.createObjectURL(blob);
    const namespace = await import(this.loaderImportUrl);
    if (typeof namespace.default !== "function") {
      throw new Error("outer-reload loader has no factory");
    }
    this.factory = namespace.default;
    this.mainScriptUrlOrBlob = blob;
    this.wasmBinary = wasmBytes;
    this.wasmUrl = wasmUrl;
  }

  newRun() {
    return {
      abort: null,
      activeClearedAfterLifecycle: false,
      expectedExitStatusObserved: false,
      factoryError: null,
      factorySettled: false,
      freshModuleObject: false,
      leaseReleasedMarkerObserved: false,
      markerDeliveryCompleteAtProcessExit: null,
      markerIndex: 0,
      markerSequenceAccepted: true,
      markers: [],
      mode: this.bootstrap.mode,
      module: null,
      moduleIdentity: randomHex(MODULE_ID_BYTES),
      onExitCount: 0,
      ordinal: this.bootstrap.ordinal,
      postLifecycleTimerObserved: false,
      processExitBeforeOnExit: false,
      processExitCode: null,
      processExitCount: 0,
      runtimeExitCode: null,
      runtimeInitialized: false,
      stderr: [],
      stdout: [],
      expectedMarkers: expectedMarkers(this.bootstrap.ordinal,
                                       this.bootstrap.tokenEvidence),
    };
  }

  captureOutput(run, destination, line) {
    this.noteCallback();
    const text = this.safeText(line, true);
    const expected = destination === run.stderr && this.activeRun === run ?
        run.expectedMarkers[run.markerIndex] : null;
    const exactMarker = text === expected && text.startsWith(M7_MARKER_PREFIX);
    // Preserve this fixed failure-only History checkpoint while still
    // suppressing all native diagnostics. It contains no SQL text, path, or
    // opaque preference material and lets the runner distinguish an open
    // failure from a later fixed history failure without exposing details.
    const historyFailureCheckpoint =
        text === `${M7_MARKER_PREFIX}HISTORY_DATABASE_PROFILE_ERROR` ||
        text === `${M7_MARKER_PREFIX}HISTORY_QUERY_VALIDATION_FAILED` ||
        text === `${M7_MARKER_PREFIX}HISTORY_QUERY_NOT_FOUND` ||
        text === `${M7_MARKER_PREFIX}HISTORY_QUERY_URL_MISMATCH` ||
        text === `${M7_MARKER_PREFIX}HISTORY_QUERY_TITLE_MISMATCH` ||
        text === `${M7_MARKER_PREFIX}HISTORY_QUERY_NO_VISITS`;
    appendOutput(destination,
                 exactMarker || historyFailureCheckpoint ?
                     text : SUPPRESSED_NATIVE_OUTPUT,
                 exactMarker || historyFailureCheckpoint);
    if (!text.includes(M7_MARKER_PREFIX)) return;
    if (destination !== run.stderr || this.activeRun !== run) {
      this.recordFatal("marker-outside-active-stderr");
      return;
    }
    if (text.startsWith(`${M7_MARKER_PREFIX}FAIL stage=`)) {
      this.recordFatal("native-fixed-failure");
      return;
    }
    if (!exactMarker) {
      run.markerSequenceAccepted = false;
      this.recordFatal("marker-invalid");
      return;
    }
    run.markers.push(text);
    ++run.markerIndex;
    if (text === `${M7_MARKER_PREFIX}LEASE_RELEASED`) {
      run.leaseReleasedMarkerObserved = true;
    }
    this.maybeCompleteRun(run);
  }

  markersComplete(run) {
    return run.markerSequenceAccepted &&
        run.markerIndex === run.expectedMarkers.length &&
        run.leaseReleasedMarkerObserved;
  }

  reportRuntimeInitialized(run, module) {
    this.noteCallback();
    if (this.activeRun !== run || run.runtimeInitialized || !module ||
        (typeof module !== "object" && typeof module !== "function")) {
      this.recordFatal("runtime-initialization-invalid");
      return;
    }
    run.module = module;
    run.runtimeInitialized = true;
    run.freshModuleObject = true;
  }

  reportRuntimeExit(run, code) {
    this.noteCallback();
    if (this.activeRun !== run || !Number.isSafeInteger(code) ||
        run.onExitCount !== 0 || run.processExitCount !== 1 ||
        run.processExitCode !== 0) {
      this.recordFatal("runtime-onexit-invalid");
      return;
    }
    run.processExitBeforeOnExit = true;
    ++run.onExitCount;
    run.runtimeExitCode = code;
    this.maybeCompleteRun(run);
  }

  routeProcessExit(report) {
    this.noteCallback();
    ++this.processExitReportCount;
    const run = this.activeRun;
    if (run === null) {
      if (this.run === null) ++this.noActiveProcessExitRejected;
      else ++this.lateProcessExitRejected;
      this.recordFatal("process-exit-without-active-run");
      return;
    }
    if (!report || typeof report !== "object" || Array.isArray(report) ||
        Object.keys(report).length !== 2 || report.protocol !== HOST_PROTOCOL ||
        !Number.isSafeInteger(report.exitCode)) {
      this.recordFatal("process-exit-schema-invalid");
      return;
    }
    if (run.processExitCount !== 0 || run.onExitCount !== 0) {
      ++this.duplicateProcessExitRejected;
      this.recordFatal("process-exit-duplicate");
      return;
    }
    ++run.processExitCount;
    run.processExitCode = report.exitCode;
    run.markerDeliveryCompleteAtProcessExit = this.markersComplete(run);
    ++this.bridgeProcessExitDispatches;
    this.maybeCompleteRun(run);
  }

  acceptExpectedExitStatus(event, reason) {
    const run = this.activeRun;
    if (run === null || run.expectedExitStatusObserved ||
        !isExactNormalExitStatus(reason) || !event ||
        typeof event.preventDefault !== "function") {
      return false;
    }
    try {
      event.preventDefault();
    } catch (_error) {
      return false;
    }
    run.expectedExitStatusObserved = true;
    this.maybeCompleteRun(run);
    return true;
  }

  reportAbort(run, reason) {
    this.noteCallback();
    if (this.activeRun !== run || run.abort !== null) {
      this.recordFatal("runtime-abort-invalid");
      return;
    }
    this.safeText(typeof reason === "string" ? reason : "", true);
    run.abort = "<suppressed-abort>";
    this.recordFatal("runtime-abort");
  }

  factorySettled(run, module) {
    this.noteCallback();
    if (run.factorySettled) {
      this.recordFatal("factory-double-settle");
      return;
    }
    run.factorySettled = true;
    if (!module || (typeof module !== "object" && typeof module !== "function") ||
        (run.module !== null && run.module !== module)) {
      run.factoryError = "<suppressed-factory-error>";
      this.recordFatal("factory-module-invalid");
      return;
    }
    run.module = module;
    this.maybeCompleteRun(run);
  }

  factoryRejected(run, error) {
    this.noteCallback();
    if (run.factorySettled) {
      this.recordFatal("factory-double-settle");
      return;
    }
    run.factorySettled = true;
    this.safeText(typeof error === "string" ? error : "", true);
    run.factoryError = "<suppressed-factory-error>";
    this.recordFatal("factory-rejected");
  }

  runIsCleanlyComplete(run) {
    return this.markersComplete(run) && run.runtimeInitialized &&
        run.factorySettled && run.factoryError === null && run.abort === null &&
        typeof run.expectedExitStatusObserved === "boolean" &&
        run.runtimeExitCode === 0 && run.onExitCount === 1 &&
        run.processExitCode === 0 && run.processExitCount === 1 &&
        typeof run.markerDeliveryCompleteAtProcessExit === "boolean" &&
        run.processExitBeforeOnExit;
  }

  maybeCompleteRun(run) {
    if (this.activeRun !== run || run.activeClearedAfterLifecycle ||
        !this.runIsCleanlyComplete(run)) {
      return;
    }
    this.activeRun = null;
    run.activeClearedAfterLifecycle = true;
    this.scheduleQuiescence(run);
  }

  scheduleQuiescence(run) {
    const quiescence = this.quiescence;
    quiescence.callbacksAtActiveClear = this.callbackCount;
    quiescence.processExitReportsAtActiveClear = this.processExitReportCount;
    quiescence.activeRunAtActiveClear = null;
    setTimeout(() => {
      run.postLifecycleTimerObserved = true;
      if (quiescence.taskScheduledExactlyOnce || this.activeRun !== null) {
        this.recordFatal("quiescence-task-invalid");
        return;
      }
      quiescence.taskScheduledExactlyOnce = true;
      quiescence.taskMethod = "setTimeout(...,0)";
      quiescence.postLifecycleTimerObservedBeforeTask = true;
      setTimeout(() => this.startQuiescence(run), 0);
    }, 0);
  }

  startQuiescence(run) {
    const quiescence = this.quiescence;
    if (quiescence.started || !quiescence.taskScheduledExactlyOnce ||
        !quiescence.postLifecycleTimerObservedBeforeTask) {
      this.recordFatal("quiescence-start-invalid");
      return;
    }
    quiescence.started = true;
    quiescence.startedAfterActiveClear = run.activeClearedAfterLifecycle &&
        this.activeRun === null;
    quiescence.callbacksAtTaskStart = this.callbackCount;
    quiescence.processExitReportsAtTaskStart = this.processExitReportCount;
    quiescence.activeRunAtTaskStart = this.activeRun === null ? null :
        this.activeRun.ordinal;
    if (!quiescence.startedAfterActiveClear ||
        quiescence.callbacksAtTaskStart !== quiescence.callbacksAtActiveClear ||
        quiescence.processExitReportsAtTaskStart !==
            quiescence.processExitReportsAtActiveClear) {
      this.recordFatal("quiescence-activity-before-start");
      return;
    }
    setTimeout(() => this.finishQuiescence(run), FINAL_QUIESCENCE_MS);
  }

  finishQuiescence(run) {
    const quiescence = this.quiescence;
    if (!quiescence.started || quiescence.completed || run !== this.run) {
      this.recordFatal("quiescence-completion-invalid");
      return;
    }
    quiescence.callbacksAtTaskEnd = this.callbackCount;
    quiescence.processExitReportsAtTaskEnd = this.processExitReportCount;
    quiescence.activeRunAtTaskEnd = this.activeRun === null ? null :
        this.activeRun.ordinal;
    quiescence.quiet = quiescence.activeRunAtTaskStart === null &&
        quiescence.activeRunAtTaskEnd === null &&
        quiescence.callbacksAtActiveClear === quiescence.callbacksAtTaskStart &&
        quiescence.callbacksAtTaskStart === quiescence.callbacksAtTaskEnd &&
        quiescence.processExitReportsAtActiveClear ===
            quiescence.processExitReportsAtTaskStart &&
        quiescence.processExitReportsAtTaskStart ===
            quiescence.processExitReportsAtTaskEnd;
    quiescence.completed = true;
    if (!quiescence.quiet) this.recordFatal("quiescence-not-quiet");
    this.completeQuiescence();
  }

  locateFileForWasm(path) {
    if (typeof path !== "string" || path !== `${this.context.moduleName}.wasm`) {
      throw new Error("outer-reload loader requested an unexpected artifact");
    }
    return this.wasmUrl.href;
  }

  startRun() {
    if (this.activeRun !== null || this.run !== null || this.factory === null ||
        this.mainScriptUrlOrBlob === null || this.wasmBinary === null ||
        this.wasmUrl === null) {
      this.recordFatal("run-start-invalid");
      return;
    }
    const run = this.newRun();
    this.run = run;
    this.activeRun = run;
    let moduleArguments;
    if (run.ordinal === 1) {
      moduleArguments = [
        "--wasm-profile-preferences-smoke=write",
        `--wasm-profile-preferences-token-a=${this.rawTokens.tokenA}`,
        "--wasm-profile-preferences-browser-smoke",
        "--wasm-profile-preferences-cookie-smoke",
        "--wasm-profile-preferences-history-smoke",
      ];
    } else if (run.ordinal === 2) {
      moduleArguments = [
        "--wasm-profile-preferences-smoke=verify-and-write",
        `--wasm-profile-preferences-token-a=${this.rawTokens.tokenA}`,
        `--wasm-profile-preferences-token-b=${this.rawTokens.tokenB}`,
        "--wasm-profile-preferences-browser-smoke",
        "--wasm-profile-preferences-cookie-smoke",
        "--wasm-profile-preferences-history-smoke",
      ];
    } else if (run.ordinal === 3) {
      moduleArguments = [
        "--wasm-profile-preferences-smoke=verify-b",
        `--wasm-profile-preferences-token-b=${this.rawTokens.tokenB}`,
        "--wasm-profile-preferences-browser-smoke",
        "--wasm-profile-preferences-cookie-smoke",
        "--wasm-profile-preferences-history-smoke",
      ];
    } else {
      this.recordFatal("run-ordinal-invalid");
      return;
    }
    const host = this;
    this.bridgeInstalledBeforeModuleFactory = this.bridgeInstalled;
    try {
      const factoryResult = this.factory({
        arguments: moduleArguments,
        canvas: this.canvas,
        locateFile(path) { return host.locateFileForWasm(path); },
        mainScriptUrlOrBlob: this.mainScriptUrlOrBlob,
        noExitRuntime: false,
        onAbort(reason) { host.reportAbort(run, reason); },
        onExit(code) { host.reportRuntimeExit(run, code); },
        onRuntimeInitialized() { host.reportRuntimeInitialized(run, this); },
        print(line) { host.captureOutput(run, run.stdout, line); },
        printErr(line) { host.captureOutput(run, run.stderr, line); },
        wasmBinary: this.wasmBinary,
      });
      Promise.resolve(factoryResult).then(
          (module) => host.factorySettled(run, module),
          (error) => host.factoryRejected(run, error));
    } catch (_error) {
      this.factoryRejected(run, "");
    }
  }

  runSnapshot() {
    const run = this.run;
    if (run === null) return null;
    return {
      abort: run.abort,
      activeClearedAfterLifecycle: run.activeClearedAfterLifecycle,
      expectedExitStatusObserved: run.expectedExitStatusObserved,
      factoryError: run.factoryError,
      factorySettled: run.factorySettled,
      freshModuleObject: run.freshModuleObject,
      leaseReleasedMarkerObserved: run.leaseReleasedMarkerObserved,
      markerCount: run.markers.length,
      markerDeliveryCompleteAtProcessExit: run.markerDeliveryCompleteAtProcessExit,
      markerSequenceAccepted: run.markerSequenceAccepted,
      markerSource: "stderr-only",
      markers: run.markers.slice(),
      mode: run.mode,
      moduleIdentity: run.moduleIdentity,
      onExitCount: run.onExitCount,
      ordinal: run.ordinal,
      postLifecycleTimerObserved: run.postLifecycleTimerObserved,
      processExitBeforeOnExit: run.processExitBeforeOnExit,
      processExitCode: run.processExitCode,
      processExitCount: run.processExitCount,
      runtimeExitCode: run.runtimeExitCode,
      runtimeInitialized: run.runtimeInitialized,
      stderr: run.stderr.slice(),
      stdout: run.stdout.slice(),
    };
  }

  bridgeSnapshot() {
    return {
      protocol: HOST_PROTOCOL,
      permanent: this.bridgeInstalled,
      frozen: this.bridgeInstalled &&
          Object.isFrozen(globalThis.__chromiumWasmHostBridgeV1),
      installedBeforeModuleFactory: this.bridgeInstalledBeforeModuleFactory,
      processExitDispatches: this.bridgeProcessExitDispatches,
      noActiveProcessExitRejected: this.noActiveProcessExitRejected,
      duplicateProcessExitRejected: this.duplicateProcessExitRejected,
      lateProcessExitRejected: this.lateProcessExitRejected,
      activeRunAtResult: this.activeRun === null ? null : this.activeRun.ordinal,
    };
  }

  hostBoundary() {
    return {
      hostOpfsAccessAttempted: false,
      hostWebLocksAccessAttempted: false,
      nativeCallAttempted: false,
      wasmDataInspectionAttempted: false,
      sessionStorageAccessAttempted: false,
      localStorageAccessAttempted: false,
      indexedDbAccessAttempted: false,
      cookieAccessAttempted: false,
      historyStateAccessAttempted: false,
      windowNameAccessAttempted: false,
    };
  }

  tokenEvidence() {
    return {
      ...this.bootstrap.tokenEvidence,
      rawTokenLeakDetected: this.rawTokenLeakDetected,
      rawTokenRedactionCount: this.rawTokenRedactionCount,
    };
  }

  baseResult(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      ordinal: this.bootstrap.ordinal,
      mode: this.bootstrap.mode,
      origin: location.origin,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      document: {...this.document},
      artifact: this.artifact,
      capture_harness: this.captureHarness,
      versions: this.versions,
      tokenEvidence: this.tokenEvidence(),
      run: this.runSnapshot(),
      bridge: this.bridgeSnapshot(),
      finalQuiescence: {...this.quiescence},
      hostBoundary: this.hostBoundary(),
      fatalErrors: this.fatalErrors.slice(),
      windowErrors: this.windowErrors.slice(),
      unhandledRejections: this.unhandledRejections.slice(),
      failedChecks: this.failedChecks.slice(),
      error,
    };
  }

  resultContainsRawToken(result) {
    let serialized;
    try {
      serialized = JSON.stringify(result);
    } catch (_error) {
      return true;
    }
    return typeof serialized !== "string" || Object.values(this.rawTokens).some(
        (token) => typeof token === "string" && serialized.includes(token));
  }

  recheckBeforeUpload() {
    const quiescence = this.quiescence;
    quiescence.bridgeRecheckedImmediatelyBeforeUpload = true;
    quiescence.callbacksAtPreUploadCheck = this.callbackCount;
    quiescence.processExitReportsAtPreUploadCheck = this.processExitReportCount;
    quiescence.activeRunAtPreUploadCheck = this.activeRun === null ? null :
        this.activeRun.ordinal;
    const clean = quiescence.completed && quiescence.quiet &&
        quiescence.callbacksAtPreUploadCheck === quiescence.callbacksAtTaskEnd &&
        quiescence.processExitReportsAtPreUploadCheck ===
            quiescence.processExitReportsAtTaskEnd &&
        quiescence.activeRunAtPreUploadCheck === null &&
        this.fatalErrors.length === 0 && this.windowErrors.length === 0 &&
        this.unhandledRejections.length === 0 && !this.rawTokenLeakDetected;
    if (!clean) this.recordFatal("result-upload-recheck");
    return clean;
  }

  strictPass(result) {
    try {
      requireExactFields(result, RESULT_FIELDS, "outer-reload result");
      const expected = expectedMarkers(this.bootstrap.ordinal,
                                       this.bootstrap.tokenEvidence);
      const run = requireExactFields(result.run, RUN_FIELDS, "outer-reload run");
      const documentReceipt = requireExactFields(
          result.document, DOCUMENT_FIELDS, "outer-reload document");
      const tokenEvidence = requireExactFields(
          result.tokenEvidence, TOKEN_EVIDENCE_FIELDS,
          "outer-reload token evidence");
      const bridge = requireExactFields(result.bridge, BRIDGE_FIELDS,
                                        "outer-reload bridge");
      const quiescence = requireExactFields(result.finalQuiescence,
                                            QUIESCENCE_FIELDS,
                                            "outer-reload quiescence");
      const boundary = requireExactFields(result.hostBoundary,
                                          HOST_BOUNDARY_FIELDS,
                                          "outer-reload boundary");
      const exactStringArray = (value, maximum) => Array.isArray(value) &&
          value.length <= maximum && value.every((item) => typeof item === "string");
      const callbackFields = [
        "callbacksAtActiveClear", "callbacksAtTaskStart", "callbacksAtTaskEnd",
        "callbacksAtPreUploadCheck",
      ];
      return result.protocol === HOST_PROTOCOL && result.case === CASE &&
          result.scope === SCOPE && result.status === "pass" &&
          result.ordinal === this.bootstrap.ordinal &&
          result.mode === this.bootstrap.mode && result.origin === location.origin &&
          result.crossOriginIsolated === true && result.sharedArrayBuffer === true &&
          documentReceipt.navigationType ===
              (result.ordinal === 1 ? "navigate" : "reload") &&
          typeof documentReceipt.timeOrigin === "number" &&
          Number.isFinite(documentReceipt.timeOrigin) &&
          documentReceipt.timeOrigin > 0 &&
          documentReceipt.timeOrigin === this.document.timeOrigin &&
          result.artifact === this.artifact &&
          result.capture_harness === this.captureHarness &&
          result.versions === this.versions && result.error === null &&
          tokenEvidence.algorithm === "SHA-256" &&
          tokenEvidence.tokenA === this.bootstrap.tokenEvidence.tokenA &&
          tokenEvidence.tokenB === this.bootstrap.tokenEvidence.tokenB &&
          tokenEvidence.distinct === this.bootstrap.tokenEvidence.distinct &&
          tokenEvidence.rawTokensExcluded === true &&
          tokenEvidence.rawTokenLeakDetected === false &&
          Number.isSafeInteger(tokenEvidence.rawTokenRedactionCount) &&
          tokenEvidence.rawTokenRedactionCount === 0 &&
          run.abort === null && run.factoryError === null &&
          run.factorySettled === true && run.freshModuleObject === true &&
          run.runtimeInitialized === true && run.ordinal === result.ordinal &&
          run.mode === result.mode && typeof run.expectedExitStatusObserved === "boolean" &&
          Number.isSafeInteger(run.processExitCode) && run.processExitCode === 0 &&
          Number.isSafeInteger(run.processExitCount) && run.processExitCount === 1 &&
          Number.isSafeInteger(run.onExitCount) && run.onExitCount === 1 &&
          Number.isSafeInteger(run.runtimeExitCode) && run.runtimeExitCode === 0 &&
          run.processExitBeforeOnExit === true &&
          typeof run.markerDeliveryCompleteAtProcessExit === "boolean" &&
          run.activeClearedAfterLifecycle === true &&
          run.postLifecycleTimerObserved === true &&
          run.markerSource === "stderr-only" && run.markerSequenceAccepted === true &&
          run.leaseReleasedMarkerObserved === true &&
          run.markerCount === expected.length &&
          JSON.stringify(run.markers) === JSON.stringify(expected) &&
          run.stderr.every((line) => line === SUPPRESSED_NATIVE_OUTPUT ||
              expected.includes(line)) &&
          run.stdout.every((line) => line === SUPPRESSED_NATIVE_OUTPUT) &&
          run.stderr.filter((line) => line.startsWith(M7_MARKER_PREFIX)).length ===
              expected.length &&
          run.moduleIdentity && MODULE_ID_RE.test(run.moduleIdentity) &&
          bridge.protocol === HOST_PROTOCOL && bridge.permanent === true &&
          bridge.frozen === true && bridge.installedBeforeModuleFactory === true &&
          bridge.processExitDispatches === 1 &&
          bridge.noActiveProcessExitRejected === 0 &&
          bridge.duplicateProcessExitRejected === 0 &&
          bridge.lateProcessExitRejected === 0 && bridge.activeRunAtResult === null &&
          quiescence.completed === true && quiescence.quiet === true &&
          quiescence.quietWindowMs === FINAL_QUIESCENCE_MS &&
          quiescence.taskScheduledExactlyOnce === true &&
          quiescence.taskMethod === "setTimeout(...,0)" &&
          quiescence.postLifecycleTimerObservedBeforeTask === true &&
          quiescence.started === true && quiescence.startedAfterActiveClear === true &&
          quiescence.processExitReportsAtActiveClear === 1 &&
          quiescence.processExitReportsAtTaskStart === 1 &&
          quiescence.processExitReportsAtTaskEnd === 1 &&
          quiescence.processExitReportsAtPreUploadCheck === 1 &&
          quiescence.bridgeRecheckedImmediatelyBeforeUpload === true &&
          quiescence.activeRunAtActiveClear === null &&
          quiescence.activeRunAtTaskStart === null &&
          quiescence.activeRunAtTaskEnd === null &&
          quiescence.activeRunAtPreUploadCheck === null &&
          callbackFields.every((field) =>
            Number.isSafeInteger(quiescence[field]) && quiescence[field] >= 0) &&
          new Set(callbackFields.map((field) => quiescence[field])).size === 1 &&
          Object.values(boundary).every((value) => value === false) &&
          exactStringArray(result.fatalErrors, MAX_ERROR_RECORDS) &&
          exactStringArray(result.windowErrors, MAX_ERROR_RECORDS) &&
          exactStringArray(result.unhandledRejections, MAX_ERROR_RECORDS) &&
          exactStringArray(result.failedChecks, MAX_ERROR_RECORDS) &&
          result.fatalErrors.length === 0 && result.windowErrors.length === 0 &&
          result.unhandledRejections.length === 0 && result.failedChecks.length === 0;
    } catch (_error) {
      return false;
    }
  }

  async runHost() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function") {
        throw new Error("outer-reload requires cross-origin isolation");
      }
      if ((this.bootstrap.ordinal === 1 &&
           this.document.navigationType !== "navigate") ||
          (this.bootstrap.ordinal !== 1 &&
           this.document.navigationType !== "reload")) {
        throw new Error("outer-reload document navigation is invalid");
      }
      this.canvas.focus({preventScroll: true});
      if (document.activeElement !== this.canvas) {
        throw new Error("outer-reload canvas focus failed");
      }
      this.installBridge();
      this.installErrorHandlers();
      await this.prepareFactory();
      this.startRun();
      const deadline = performance.now() + this.context.timeoutMs;
      while (performance.now() < deadline) {
        if (this.fatalErrors.length !== 0 || this.quiescence.completed) break;
        await delay(10);
      }
      if (!this.quiescence.completed) this.recordFatal("outer-reload-host-timeout");
      let result = this.baseResult(this.fatalErrors.length === 0 ? "pass" : "fail",
                                   this.fatalErrors.length === 0 ? null :
                                       "details-suppressed");
      if (result.status === "pass") {
        if (!this.recheckBeforeUpload()) {
          result = this.baseResult("fail", "details-suppressed");
        } else {
          // Capture the post-recheck fields, rather than the pre-recheck
          // snapshot, before applying the closed passing-result grammar.
          result = this.baseResult("pass", null);
        }
      }
      if (result.status === "pass" && this.resultContainsRawToken(result)) {
        this.recordOpaqueTokenLeak();
        result = this.baseResult("fail", "details-suppressed");
      }
      if (result.status === "pass" && !this.strictPass(result)) {
        this.recordFatal("result-validation");
        result = this.baseResult("fail", "details-suppressed");
      }
      return result;
    } catch (_error) {
      this.recordFatal("outer-reload-host-exception");
      return this.baseResult("fail", "details-suppressed");
    }
  }

  readyAfterResultUpload() {
    const quiescence = this.quiescence;
    return this.fatalErrors.length === 0 && !this.rawTokenLeakDetected &&
        quiescence.completed && quiescence.quiet && this.activeRun === null &&
        this.callbackCount === quiescence.callbacksAtPreUploadCheck &&
        this.processExitReportCount ===
            quiescence.processExitReportsAtPreUploadCheck;
  }

  dispose() {
    this.releaseErrorHandlers();
    if (this.loaderImportUrl !== null) {
      URL.revokeObjectURL(this.loaderImportUrl);
      this.loaderImportUrl = null;
    }
    this.opaqueTokenTail = "";
  }
}

function endpoint(context, kind, ordinal) {
  const suffix = ordinal === undefined ?
      `./${kind}/${encodeURIComponent(context.session)}` :
      `./${kind}/${encodeURIComponent(context.resultToken)}/${ordinal}`;
  const value = new URL(suffix, location.href);
  if (value.origin !== location.origin) {
    throw new Error("outer-reload endpoint is invalid");
  }
  return value;
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("outer-reload page is missing its version element");
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

export async function runChromeWasmProfilePreferencesOuterReloadFromQuery() {
  const context = parseStaticContext();
  const root = document.querySelector("#m7-profile-preferences-outer-reload-root");
  const canvas = document.querySelector("#m7-profile-preferences-outer-reload-canvas");
  const status = document.querySelector("#m7-profile-preferences-outer-reload-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("outer-reload page is missing required elements");
  }
  renderVersions(document.querySelector(
      "#m7-profile-preferences-outer-reload-versions"), context.versions);
  const receipt = documentEvidence();
  // The server flushes this 204 before making the one raw-token bootstrap body
  // eligible. The page never self-navigates; the runner owns replacement.
  await postBootstrapDocumentEvidence(context, receipt);
  const bootstrap = await fetchBootstrap(context);
  const host = new PreferencesOuterReloadHost(canvas, context, bootstrap, receipt);
  let result;
  try {
    result = await host.runHost();
    root.dataset.state = result.status;
    status.textContent = result.status === "pass" ?
        `outer-reload phase ${result.ordinal} complete` :
        "outer-reload phase failed; details suppressed";
    await postJson(endpoint(context, "result", result.ordinal), result,
                   "outer-reload result");
    if (result.status !== "pass") {
      throw new Error("outer-reload result validation failed");
    }
    await delay(0);
    if (!host.readyAfterResultUpload()) {
      throw new Error("outer-reload host changed after result upload");
    }
    await postJson(endpoint(context, "ready", result.ordinal), {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      ordinal: result.ordinal,
      timeOrigin: result.document.timeOrigin,
    }, "outer-reload ready");
    return result;
  } finally {
    // Keep the first two phases alive until the runner performs each real
    // reload. The final phase has no successor document to retain it for.
    if (result === undefined || result.status !== "pass" || result.ordinal === 3) {
      host.dispose();
    }
  }
}

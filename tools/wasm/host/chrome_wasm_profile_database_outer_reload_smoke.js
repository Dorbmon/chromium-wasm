// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Two-outer-document SQLite/LevelDB handoff witness. Chromium owns OPFS,
// profile lifecycle, SQLite, LevelDB, the shutdown fence, and the lease.  The
// host only obtains one runner-escrowed, opaque argument bundle per document;
// it never reads profile data or retains raw database values in a result. The
// runner may make document two a fresh outer-browser navigation after a clean
// host-browser exit; the server-owned bootstrap states the exact permitted
// navigation type, so the host never infers it.

const HOST_PROTOCOL = 1;
const CASE = "chrome_profile_database_outer_document_persistence_m7";
const SCOPE =
    "same-origin-two-outer-documents-chrome-wasm-m7-profile-database-test-modules-orderly-handoff-only";
const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_test";
const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:";
const M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
const SUPPRESSED_NATIVE_OUTPUT = "<suppressed-native-output>";
const MAX_TIMEOUT_MS = 120000;
const MAX_OUTPUT_LINES = 128;
const MAX_ERROR_RECORDS = 16;
const TOKEN_BYTES = 32;
const MODULE_ID_BYTES = 16;
const FINAL_QUIESCENCE_MS = 50;
const SHA256_RE = /^[0-9a-f]{64}$/;
const MODULE_ID_RE = /^[0-9a-f]{32}$/;
const OPAQUE_CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;
const EXPECTED_NORMAL_EXIT_STATUS_FIELDS = Object.freeze([
  "name", "status", "message",
]);
const EXPECTED_NORMAL_EXIT_STATUS_VALUES = Object.freeze({
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
});
const NATIVE_FAILURE_STAGES = Object.freeze([
  "arguments", "capability", "storage", "profile", "database", "fence",
  "lifecycle", "content", "drain",
]);
const NATIVE_DATABASE_PHASES = Object.freeze([
  "task-post",
  "task-started",
  "sqlite-write",
  "sqlite-read",
  "leveldb-write",
  "leveldb-write-open",
  "leveldb-write-pre-dbimpl-construction",
  "leveldb-write-put",
  "leveldb-write-compact",
  "leveldb-write-close",
  "leveldb-write-tracker",
  "leveldb-write-env-file-exists-first-pre",
  "leveldb-write-env-file-exists-first-post",
  "leveldb-write-env-file-exists-second-pre",
  "leveldb-write-env-file-exists-second-post",
  "leveldb-write-env-file-exists-later-pre",
  "leveldb-write-env-file-exists-later-post",
  "leveldb-write-env-create-dir",
  "leveldb-write-env-rename-file",
  "leveldb-write-env-new-logger",
  "leveldb-write-logger-logv-first-pre",
  "leveldb-write-logger-logv-first-post",
  "leveldb-write-env-lock-file",
  "leveldb-write-env-new-writable-file",
  "leveldb-read",
  "leveldb-read-open",
  "leveldb-read-get",
  "leveldb-read-close",
  "task-complete",
]);

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
  "tokenADigest", "tokenBDigest", "expectedNavigationType",
]);
const BOOTSTRAP_DOCUMENT_FIELDS = Object.freeze([
  "protocol", "case", "scope", "navigationType", "timeOrigin",
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
  if (!OPAQUE_CAPABILITY_RE.test(resultToken) || !OPAQUE_CAPABILITY_RE.test(session) ||
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

function appendBounded(destination, value, maximum = MAX_OUTPUT_LINES) {
  destination.push(value);
  if (destination.length > maximum) {
    destination.splice(0, destination.length - maximum);
  }
}

function appendOutput(destination, value, isExactMarker) {
  if (destination.length < MAX_OUTPUT_LINES) {
    destination.push(value);
    return;
  }
  const ordinary = destination.findIndex(
      (line) => !line.startsWith(M7_MARKER_PREFIX));
  if (ordinary !== -1) {
    destination.splice(ordinary, 1);
    destination.push(value);
  } else if (isExactMarker) {
    destination.shift();
    destination.push(value);
  }
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
  if (actualType !== contentType || Object.entries(required).some(
      ([name, value]) => response.headers.get(name) !== value)) {
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
  if (!(body instanceof ArrayBuffer)) {
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
      `${M7_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}DATABASES_CLOSED sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  if (ordinal === 2) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}SQLITE_READ_A_OK sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}LEVELDB_READ_A_OK sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}DATABASES_CLOSED sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${tokenEvidence.tokenB}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  throw new Error("outer-reload ordinal is invalid");
}

function fixedNativeFailureStage(text) {
  const prefix = `${M7_MARKER_PREFIX}FAIL stage=`;
  if (typeof text !== "string" || !text.startsWith(prefix)) return null;
  const stage = text.slice(prefix.length);
  return NATIVE_FAILURE_STAGES.includes(stage) ? stage : null;
}

function fixedNativeDatabasePhase(text) {
  if (typeof text !== "string" || !text.startsWith(M7_DATABASE_PHASE_PREFIX)) {
    return null;
  }
  const phase = text.slice(M7_DATABASE_PHASE_PREFIX.length);
  return NATIVE_DATABASE_PHASES.includes(phase) ? phase : null;
}

export function isExactOuterReloadExitStatus(value) {
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

function bootstrapUrl(context) {
  const endpoint = new URL(
      `./bootstrap/${encodeURIComponent(context.session)}`, location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("outer-reload bootstrap endpoint is invalid");
  }
  return endpoint;
}

function bootstrapDocumentRequest(documentReceipt) {
  const documentEvidence = requireExactFields(
      documentReceipt, ["navigationType", "timeOrigin"],
      "outer-reload bootstrap document evidence");
  if ((documentEvidence.navigationType !== "navigate" &&
       documentEvidence.navigationType !== "reload") ||
      typeof documentEvidence.timeOrigin !== "number" ||
      !Number.isFinite(documentEvidence.timeOrigin) ||
      documentEvidence.timeOrigin <= 0) {
    throw new Error("outer-reload bootstrap document evidence is invalid");
  }
  return requireExactFields({
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    navigationType: documentEvidence.navigationType,
    timeOrigin: documentEvidence.timeOrigin,
  }, BOOTSTRAP_DOCUMENT_FIELDS, "outer-reload bootstrap document request");
}

async function postBootstrapDocumentEvidence(context, documentReceipt) {
  const endpoint = bootstrapUrl(context);
  const request = bootstrapDocumentRequest(documentReceipt);
  await postJson(endpoint, request, "outer-reload bootstrap evidence");
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
  return parseBootstrap(value);
}

async function parseBootstrap(value) {
  const bootstrap = requireExactFields(value, BOOTSTRAP_FIELDS,
                                       "outer-reload bootstrap");
  if (bootstrap.protocol !== HOST_PROTOCOL || bootstrap.case !== CASE ||
      bootstrap.scope !== SCOPE ||
      !Number.isSafeInteger(bootstrap.ordinal) ||
      !((bootstrap.ordinal === 1 && bootstrap.mode === "write-a") ||
        (bootstrap.ordinal === 2 && bootstrap.mode === "verify-a-write-b")) ||
      typeof bootstrap.tokenA !== "string" || !SHA256_RE.test(bootstrap.tokenA) ||
      typeof bootstrap.tokenADigest !== "string" ||
      !SHA256_RE.test(bootstrap.tokenADigest)) {
    throw new Error("outer-reload bootstrap is invalid");
  }
  const first = bootstrap.ordinal === 1;
  if ((first && (bootstrap.tokenB !== null || bootstrap.tokenBDigest !== null)) ||
      (!first && (typeof bootstrap.tokenB !== "string" ||
                  !SHA256_RE.test(bootstrap.tokenB) ||
                  typeof bootstrap.tokenBDigest !== "string" ||
                  !SHA256_RE.test(bootstrap.tokenBDigest) ||
                  bootstrap.tokenB === bootstrap.tokenA)) ||
      (bootstrap.expectedNavigationType !== "navigate" &&
       bootstrap.expectedNavigationType !== "reload")) {
    throw new Error("outer-reload bootstrap is invalid");
  }
  if (typeof TextEncoder !== "function") {
    throw new Error("outer-reload token encoder is unavailable");
  }
  const tokenADigest = await sha256Hex(
      new TextEncoder().encode(bootstrap.tokenA), "outer-reload token A");
  const tokenBDigest = first ? null : await sha256Hex(
      new TextEncoder().encode(bootstrap.tokenB), "outer-reload token B");
  if (tokenADigest !== bootstrap.tokenADigest ||
      (!first && tokenBDigest !== bootstrap.tokenBDigest)) {
    throw new Error("outer-reload bootstrap token identity is invalid");
  }
  return Object.freeze({
    expectedNavigationType: bootstrap.expectedNavigationType,
    mode: bootstrap.mode,
    ordinal: bootstrap.ordinal,
    rawTokens: Object.freeze({tokenA: bootstrap.tokenA, tokenB: bootstrap.tokenB}),
    tokenEvidence: Object.freeze({
      algorithm: "SHA-256",
      tokenA: tokenADigest,
      tokenB: tokenBDigest,
      distinct: first ? null : true,
      rawTokensExcluded: true,
      rawTokenLeakDetected: false,
      rawTokenRedactionCount: 0,
    }),
  });
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

class ChromeWasmProfileDatabaseOuterReloadHost {
  #activeRun = null;
  #artifact;
  #bootstrap;
  #bridgeInstalled = false;
  #bridgeInstalledBeforeModuleFactory = false;
  #bridgeProcessExitDispatches = 0;
  #callbackCount = 0;
  #canvas;
  #captureHarness;
  #completionResolver;
  #completionPromise;
  #context;
  #document;
  #duplicateProcessExitRejected = 0;
  #factory = null;
  #factoryCalls = 0;
  #fatalErrors = [];
  #failedChecks = [];
  #finalQuiescence = {
    activeRunAtActiveClear: null,
    activeRunAtPreUploadCheck: null,
    activeRunAtTaskEnd: null,
    activeRunAtTaskStart: null,
    bridgeRecheckedImmediatelyBeforeUpload: false,
    callbacksAtActiveClear: null,
    callbacksAtPreUploadCheck: null,
    callbacksAtTaskEnd: null,
    callbacksAtTaskStart: null,
    completed: false,
    postLifecycleTimerObservedBeforeTask: false,
    processExitReportsAtActiveClear: null,
    processExitReportsAtPreUploadCheck: null,
    processExitReportsAtTaskEnd: null,
    processExitReportsAtTaskStart: null,
    quiet: false,
    quietWindowMs: FINAL_QUIESCENCE_MS,
    started: false,
    startedAfterActiveClear: false,
    taskMethod: null,
    taskScheduledExactlyOnce: false,
  };
  #loaderImportUrl = null;
  #lateProcessExitRejected = 0;
  #mainScriptUrlOrBlob = null;
  #noActiveProcessExitRejected = 0;
  #opaqueTokenTail = "";
  #processExitReportCount = 0;
  #rawTokenLeakDetected = false;
  #rawTokenRedactionCount = 0;
  #rawTokens;
  #run = null;
  #unhandledRejections = [];
  #versions;
  #wasmBinary = null;
  #wasmUrl = null;
  #windowErrors = [];
  #windowErrorHandler;
  #unhandledRejectionHandler;

  constructor(canvas, context, bootstrap, documentReceipt) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("outer-reload canvas is unavailable");
    }
    this.#artifact = context.artifact;
    this.#bootstrap = bootstrap;
    this.#canvas = canvas;
    this.#captureHarness = context.captureHarness;
    this.#context = context;
    this.#document = Object.freeze({...documentReceipt});
    this.#rawTokens = bootstrap.rawTokens;
    this.#versions = context.versions;
    this.#completionPromise = new Promise((resolve) => {
      this.#completionResolver = resolve;
    });
  }

  #recordFailure(code) {
    if (typeof code !== "string" || code.length === 0) {
      throw new Error("outer-reload failure code is invalid");
    }
    if (this.#failedChecks.length < MAX_ERROR_RECORDS) {
      this.#failedChecks.push(code);
    }
  }

  #recordFatal(code) {
    this.#recordFailure(code);
    if (this.#fatalErrors.length < MAX_ERROR_RECORDS) {
      this.#fatalErrors.push(code);
    }
  }

  #noteExternalCallback() {
    this.#callbackCount += 1;
  }

  #scrubCapturedFields() {
    const scrubbed = "<scrubbed-after-opaque-token-leak>";
    this.#fatalErrors = this.#fatalErrors.map(() => scrubbed);
    this.#failedChecks = this.#failedChecks.map(() => scrubbed);
    this.#windowErrors = this.#windowErrors.map(() => scrubbed);
    this.#unhandledRejections = this.#unhandledRejections.map(() => scrubbed);
    if (this.#run !== null) {
      this.#run.abort = this.#run.abort === null ? null : scrubbed;
      this.#run.factoryError = this.#run.factoryError === null ? null : scrubbed;
      this.#run.markerSequenceAccepted = false;
      this.#run.leaseReleasedMarkerObserved = false;
      this.#run.markers = this.#run.markers.map(() => scrubbed);
      this.#run.stderr = this.#run.stderr.map(() => scrubbed);
      this.#run.stdout = this.#run.stdout.map(() => scrubbed);
    }
  }

  #recordOpaqueTokenLeak() {
    if (this.#rawTokenLeakDetected) return;
    this.#rawTokenLeakDetected = true;
    this.#rawTokenRedactionCount += 1;
    this.#opaqueTokenTail = "";
    this.#scrubCapturedFields();
  }

  #safeText(value, trackAcrossCallbacks = false) {
    if (this.#rawTokenLeakDetected) {
      return "<scrubbed-after-opaque-token-leak>";
    }
    if (typeof value !== "string") return "<suppressed-nonstring>";
    const combined = trackAcrossCallbacks ? this.#opaqueTokenTail + value : value;
    for (const token of Object.values(this.#rawTokens)) {
      if (typeof token === "string" && combined.includes(token)) {
        this.#recordOpaqueTokenLeak();
        return "<scrubbed-after-opaque-token-leak>";
      }
    }
    if (trackAcrossCallbacks) {
      this.#opaqueTokenTail = combined.slice(-(TOKEN_BYTES * 2 - 1));
    }
    return value;
  }

  #captureWindowErrors() {
    this.#windowErrorHandler = (event) => {
      this.#noteExternalCallback();
      this.#safeText(typeof event?.message === "string" ? event.message :
                     "<suppressed-window-error>", true);
      appendBounded(this.#windowErrors, "<suppressed-window-error>",
                    MAX_ERROR_RECORDS);
      this.#recordFatal("window-error");
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#noteExternalCallback();
      let reason = null;
      try {
        reason = event.reason;
      } catch (_error) {
        // An unreadable reason remains a fixed failure below.
      }
      if (this.#acceptExpectedNormalExitRejection(event, reason)) return;
      this.#safeText(typeof reason === "string" ? reason :
                     "<suppressed-unhandled-rejection>", true);
      appendBounded(this.#unhandledRejections, "<suppressed-unhandled-rejection>",
                    MAX_ERROR_RECORDS);
      this.#recordFatal("unhandled-rejection");
    };
    addEventListener("error", this.#windowErrorHandler);
    addEventListener("unhandledrejection", this.#unhandledRejectionHandler);
  }

  #releaseWindowErrors() {
    if (this.#windowErrorHandler !== undefined) {
      removeEventListener("error", this.#windowErrorHandler);
      this.#windowErrorHandler = undefined;
    }
    if (this.#unhandledRejectionHandler !== undefined) {
      removeEventListener("unhandledrejection", this.#unhandledRejectionHandler);
      this.#unhandledRejectionHandler = undefined;
    }
  }

  #releaseVerifiedLoader() {
    if (this.#loaderImportUrl !== null) {
      URL.revokeObjectURL(this.#loaderImportUrl);
      this.#loaderImportUrl = null;
    }
  }

  #installPermanentBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("outer-reload host bridge already exists");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(_message) {
        host.#noteExternalCallback();
        host.#recordFatal("native-bridge-fatal");
      },
      reportProcessExit(report) { host.#routeProcessExit(report); },
      reportFrame(_report) { host.#noteExternalCallback(); },
      reportReadiness(_report) { host.#noteExternalCallback(); },
      reportOzoneFocusState(_report) { host.#noteExternalCallback(); },
      reportOzoneCursor(_report) { host.#noteExternalCallback(); return true; },
      reportOzoneTextInputState(_report) { host.#noteExternalCallback(); },
      reportOzoneTextInputDelivery(_report) { host.#noteExternalCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) { host.#noteExternalCallback(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) {
        host.#noteExternalCallback();
      },
      requestOuterOriginStorageEstimate(_report) {
        host.#noteExternalCallback();
        return false;
      },
      reportAccessibilitySnapshot(_report) {
        host.#noteExternalCallback();
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
      throw new Error("outer-reload host bridge is invalid");
    }
    this.#bridgeInstalled = true;
  }

  async #prepareFactory() {
    const loaderUrl = new URL(
        `./artifacts/${this.#context.moduleName}.js`, location.href);
    const wasmUrl = new URL(
        `./artifacts/${this.#context.moduleName}.wasm`, location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("outer-reload artifacts are not same-origin");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(loaderUrl, this.#artifact.loader, "text/javascript",
                            "outer-reload loader"),
      fetchVerifiedArtifact(wasmUrl, this.#artifact.wasm, "application/wasm",
                            "outer-reload Wasm"),
    ]);
    if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("outer-reload verified loader import is unavailable");
    }
    const blob = new Blob([loaderBytes], {type: "text/javascript"});
    this.#loaderImportUrl = URL.createObjectURL(blob);
    const namespace = await import(this.#loaderImportUrl);
    if (typeof namespace.default !== "function") {
      throw new Error("outer-reload loader has no factory");
    }
    this.#factory = namespace.default;
    this.#mainScriptUrlOrBlob = blob;
    this.#wasmBinary = wasmBytes;
    this.#wasmUrl = wasmUrl;
  }

  #newRun() {
    const expected = expectedMarkers(this.#bootstrap.ordinal,
                                    this.#bootstrap.tokenEvidence);
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
      mode: this.#bootstrap.mode,
      module: null,
      moduleIdentity: randomHex(MODULE_ID_BYTES),
      onExitCount: 0,
      ordinal: this.#bootstrap.ordinal,
      postLifecycleTimerObserved: false,
      processExitBeforeOnExit: false,
      processExitCode: null,
      processExitCount: 0,
      runtimeExitCode: null,
      runtimeInitialized: false,
      stderr: [],
      stdout: [],
      taskCompletePhaseObserved: false,
      taskPostPhaseObserved: false,
      expectedMarkers: expected,
    };
  }

  #captureOutput(run, destination, line) {
    this.#noteExternalCallback();
    const text = this.#safeText(line, true);
    const expected = destination === run.stderr && this.#activeRun === run ?
        run.expectedMarkers[run.markerIndex] : null;
    const containsMarker = text.includes(M7_MARKER_PREFIX);
    const containsPhase = text.includes(M7_DATABASE_PHASE_PREFIX);
    const isExactMarker = containsMarker && text === expected;
    appendOutput(destination,
                 isExactMarker ? text : SUPPRESSED_NATIVE_OUTPUT,
                 isExactMarker);
    if (containsPhase) {
      if (destination !== run.stderr || this.#activeRun !== run) {
        this.#recordFatal("database-phase-outside-active-stderr");
        return;
      }
      const phase = fixedNativeDatabasePhase(text);
      if (phase === null) {
        this.#recordFatal("database-phase-invalid");
        return;
      }
      if (phase === "task-post") {
        if (run.taskPostPhaseObserved) {
          this.#recordFatal("database-phase-task-post-duplicate");
          return;
        }
        run.taskPostPhaseObserved = true;
      }
      if (phase === "task-complete") {
        if (run.taskCompletePhaseObserved) {
          this.#recordFatal("database-phase-task-complete-duplicate");
          return;
        }
        run.taskCompletePhaseObserved = true;
      }
      this.#maybeCompleteRun(run);
      return;
    }
    if (!containsMarker) return;
    if (destination !== run.stderr || this.#activeRun !== run) {
      this.#recordFatal("database-marker-outside-active-stderr");
      return;
    }
    if (fixedNativeFailureStage(text) !== null) {
      this.#recordFatal("database-native-fixed-failure");
      return;
    }
    if (!text.startsWith(M7_MARKER_PREFIX) || text !== expected) {
      run.markerSequenceAccepted = false;
      this.#recordFatal("database-marker-invalid");
      return;
    }
    run.markers.push(text);
    run.markerIndex += 1;
    if (text === `${M7_MARKER_PREFIX}LEASE_RELEASED`) {
      run.leaseReleasedMarkerObserved = true;
    }
    this.#maybeCompleteRun(run);
  }

  #markersComplete(run) {
    return run.markerSequenceAccepted &&
        run.markerIndex === run.expectedMarkers.length &&
        run.leaseReleasedMarkerObserved;
  }

  #reportRuntimeInitialized(run, module) {
    this.#noteExternalCallback();
    if (this.#activeRun !== run || run.runtimeInitialized || !module ||
        (typeof module !== "object" && typeof module !== "function")) {
      this.#recordFatal("runtime-initialization-invalid");
      return;
    }
    run.module = module;
    run.runtimeInitialized = true;
    run.freshModuleObject = true;
  }

  #reportRuntimeExit(run, code) {
    this.#noteExternalCallback();
    if (this.#activeRun !== run || !Number.isSafeInteger(code) ||
        run.onExitCount !== 0 || run.processExitCount !== 1 ||
        run.processExitCode !== 0) {
      this.#recordFatal("runtime-onexit-invalid");
      return;
    }
    run.processExitBeforeOnExit = true;
    run.onExitCount += 1;
    run.runtimeExitCode = code;
    this.#maybeCompleteRun(run);
  }

  #acceptExpectedNormalExitRejection(event, reason) {
    const run = this.#activeRun;
    if (run === null || run.expectedExitStatusObserved ||
        this.#fatalErrors.length !== 0 || this.#rawTokenLeakDetected ||
        this.#windowErrors.length !== 0 || this.#unhandledRejections.length !== 0 ||
        run.abort !== null || !run.runtimeInitialized || !run.factorySettled ||
        run.factoryError !== null || run.processExitCount !== 1 ||
        run.processExitCode !== 0 || run.onExitCount !== 1 ||
        run.runtimeExitCode !== 0 || !run.processExitBeforeOnExit ||
        !isExactOuterReloadExitStatus(reason) || !event ||
        typeof event.preventDefault !== "function") {
      return false;
    }
    try {
      event.preventDefault();
    } catch (_error) {
      return false;
    }
    run.expectedExitStatusObserved = true;
    this.#maybeCompleteRun(run);
    return true;
  }

  #routeProcessExit(report) {
    this.#noteExternalCallback();
    this.#processExitReportCount += 1;
    const run = this.#activeRun;
    if (run === null) {
      if (this.#run !== null) {
        this.#lateProcessExitRejected += 1;
      } else {
        this.#noActiveProcessExitRejected += 1;
      }
      this.#recordFatal("process-exit-without-active-run");
      return;
    }
    if (!requireExactProcessExitReport(report)) {
      this.#recordFatal("process-exit-schema-invalid");
      return;
    }
    if (run.processExitCount !== 0 || run.onExitCount !== 0) {
      this.#duplicateProcessExitRejected += 1;
      this.#recordFatal("process-exit-duplicate");
      return;
    }
    run.processExitCount += 1;
    run.processExitCode = report.exitCode;
    run.markerDeliveryCompleteAtProcessExit = this.#markersComplete(run);
    this.#bridgeProcessExitDispatches += 1;
    this.#maybeCompleteRun(run);
  }

  #reportAbort(run, reason) {
    this.#noteExternalCallback();
    if (this.#activeRun !== run || run.abort !== null) {
      this.#recordFatal("runtime-abort-invalid");
      return;
    }
    if (typeof reason === "string") this.#safeText(reason, true);
    run.abort = "<suppressed-abort>";
    this.#recordFatal("runtime-abort");
  }

  #factorySettled(run, module) {
    this.#noteExternalCallback();
    if (run.factorySettled) {
      this.#recordFatal("factory-double-settle");
      return;
    }
    run.factorySettled = true;
    if (!module || (typeof module !== "object" && typeof module !== "function") ||
        (run.module !== null && run.module !== module)) {
      run.factoryError = "<suppressed-factory-error>";
      this.#recordFatal("factory-module-invalid");
      return;
    }
    run.module = module;
    this.#maybeCompleteRun(run);
  }

  #factoryRejected(run, error) {
    this.#noteExternalCallback();
    if (run.factorySettled) {
      this.#recordFatal("factory-double-settle");
      return;
    }
    run.factorySettled = true;
    this.#safeText(typeof error === "string" ? error :
                   "<suppressed-factory-error>", true);
    run.factoryError = "<suppressed-factory-error>";
    this.#recordFatal("factory-rejected");
  }

  #runIsCleanlyComplete(run) {
    return this.#markersComplete(run) && run.runtimeInitialized &&
        run.factorySettled && run.factoryError === null && run.abort === null &&
        run.taskPostPhaseObserved && run.taskCompletePhaseObserved &&
        this.#factoryCalls === 1 &&
        typeof run.expectedExitStatusObserved === "boolean" &&
        run.runtimeExitCode === 0 && run.onExitCount === 1 &&
        run.processExitCode === 0 && run.processExitCount === 1 &&
        typeof run.markerDeliveryCompleteAtProcessExit === "boolean" &&
        run.processExitBeforeOnExit;
  }

  #maybeCompleteRun(run) {
    if (this.#activeRun !== run || run.activeClearedAfterLifecycle ||
        !this.#runIsCleanlyComplete(run)) {
      return;
    }
    this.#activeRun = null;
    run.activeClearedAfterLifecycle = true;
    this.#scheduleQuiescence(run);
  }

  #scheduleQuiescence(run) {
    const quiescence = this.#finalQuiescence;
    if (!run.activeClearedAfterLifecycle || this.#activeRun !== null ||
        quiescence.callbacksAtActiveClear !== null) {
      this.#recordFatal("quiescence-lifecycle-invalid");
      return;
    }
    quiescence.callbacksAtActiveClear = this.#callbackCount;
    quiescence.processExitReportsAtActiveClear = this.#processExitReportCount;
    quiescence.activeRunAtActiveClear = this.#activeRun === null ? null :
        this.#activeRun.ordinal;
    setTimeout(() => {
      run.postLifecycleTimerObserved = true;
      if (quiescence.taskScheduledExactlyOnce || this.#activeRun !== null) {
        this.#recordFatal("quiescence-task-invalid");
        return;
      }
      quiescence.taskScheduledExactlyOnce = true;
      quiescence.taskMethod = "setTimeout(...,0)";
      quiescence.postLifecycleTimerObservedBeforeTask =
          run.postLifecycleTimerObserved;
      setTimeout(() => this.#startQuiescence(run), 0);
    }, 0);
  }

  #startQuiescence(run) {
    const quiescence = this.#finalQuiescence;
    if (quiescence.started || !quiescence.taskScheduledExactlyOnce ||
        !quiescence.postLifecycleTimerObservedBeforeTask) {
      this.#recordFatal("quiescence-start-invalid");
      return;
    }
    quiescence.started = true;
    quiescence.startedAfterActiveClear = run.activeClearedAfterLifecycle &&
        this.#activeRun === null;
    quiescence.callbacksAtTaskStart = this.#callbackCount;
    quiescence.processExitReportsAtTaskStart = this.#processExitReportCount;
    quiescence.activeRunAtTaskStart = this.#activeRun === null ? null :
        this.#activeRun.ordinal;
    if (!quiescence.startedAfterActiveClear ||
        quiescence.callbacksAtTaskStart !== quiescence.callbacksAtActiveClear ||
        quiescence.processExitReportsAtTaskStart !==
            quiescence.processExitReportsAtActiveClear) {
      this.#recordFatal("quiescence-activity-before-start");
      return;
    }
    setTimeout(() => this.#finishQuiescence(run), FINAL_QUIESCENCE_MS);
  }

  #finishQuiescence(run) {
    const quiescence = this.#finalQuiescence;
    if (!quiescence.started || quiescence.completed ||
        run !== this.#run) {
      this.#recordFatal("quiescence-completion-invalid");
      return;
    }
    quiescence.callbacksAtTaskEnd = this.#callbackCount;
    quiescence.processExitReportsAtTaskEnd = this.#processExitReportCount;
    quiescence.activeRunAtTaskEnd = this.#activeRun === null ? null :
        this.#activeRun.ordinal;
    quiescence.quiet = quiescence.activeRunAtTaskStart === null &&
        quiescence.activeRunAtTaskEnd === null &&
        quiescence.callbacksAtActiveClear === quiescence.callbacksAtTaskStart &&
        quiescence.callbacksAtTaskStart === quiescence.callbacksAtTaskEnd &&
        quiescence.processExitReportsAtActiveClear ===
            quiescence.processExitReportsAtTaskStart &&
        quiescence.processExitReportsAtTaskStart ===
            quiescence.processExitReportsAtTaskEnd;
    quiescence.completed = true;
    if (!quiescence.quiet) this.#recordFatal("quiescence-not-quiet");
    this.#completionResolver();
  }

  #startRun() {
    if (this.#activeRun !== null || this.#factory === null ||
        this.#mainScriptUrlOrBlob === null || this.#wasmBinary === null ||
        this.#wasmUrl === null || this.#run !== null) {
      this.#recordFatal("run-start-invalid");
      return;
    }
    const run = this.#newRun();
    this.#run = run;
    this.#activeRun = run;
    const moduleArguments = run.ordinal === 1 ? [
      "--wasm-profile-database-smoke=write-a",
      `--wasm-profile-database-token-a=${this.#rawTokens.tokenA}`,
    ] : [
      "--wasm-profile-database-smoke=verify-a-write-b",
      `--wasm-profile-database-token-a=${this.#rawTokens.tokenA}`,
      `--wasm-profile-database-token-b=${this.#rawTokens.tokenB}`,
    ];
    const host = this;
    this.#bridgeInstalledBeforeModuleFactory = this.#bridgeInstalled;
    this.#factoryCalls += 1;
    try {
      const factoryResult = this.#factory({
        arguments: moduleArguments,
        canvas: this.#canvas,
        locateFile(path) { return host.#locateFileForWasm(path); },
        mainScriptUrlOrBlob: this.#mainScriptUrlOrBlob,
        noExitRuntime: false,
        onAbort(reason) { host.#reportAbort(run, reason); },
        onExit(code) { host.#reportRuntimeExit(run, code); },
        onRuntimeInitialized() { host.#reportRuntimeInitialized(run, this); },
        print(line) { host.#captureOutput(run, run.stdout, line); },
        printErr(line) { host.#captureOutput(run, run.stderr, line); },
        wasmBinary: this.#wasmBinary,
      });
      Promise.resolve(factoryResult).then(
          (module) => host.#factorySettled(run, module),
          (error) => host.#factoryRejected(run, error));
    } catch (_error) {
      this.#factoryRejected(run, "<suppressed-factory-error>");
    }
  }

  #locateFileForWasm(path) {
    if (typeof path !== "string" ||
        path !== `${this.#context.moduleName}.wasm`) {
      throw new Error("outer-reload loader requested an unexpected artifact");
    }
    return this.#wasmUrl.href;
  }

  #runSnapshot() {
    const run = this.#run;
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

  #bridgeSnapshot() {
    return {
      protocol: HOST_PROTOCOL,
      permanent: this.#bridgeInstalled,
      frozen: this.#bridgeInstalled &&
          Object.isFrozen(globalThis.__chromiumWasmHostBridgeV1),
      installedBeforeModuleFactory: this.#bridgeInstalledBeforeModuleFactory,
      processExitDispatches: this.#bridgeProcessExitDispatches,
      noActiveProcessExitRejected: this.#noActiveProcessExitRejected,
      duplicateProcessExitRejected: this.#duplicateProcessExitRejected,
      lateProcessExitRejected: this.#lateProcessExitRejected,
      activeRunAtResult: this.#activeRun === null ? null : this.#activeRun.ordinal,
    };
  }

  #hostBoundary() {
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

  #tokenEvidence() {
    return {
      ...this.#bootstrap.tokenEvidence,
      rawTokenLeakDetected: this.#rawTokenLeakDetected,
      rawTokenRedactionCount: this.#rawTokenRedactionCount,
    };
  }

  #containsOpaqueToken(value) {
    let serialized;
    try {
      serialized = JSON.stringify(value);
    } catch (_error) {
      return true;
    }
    return typeof serialized !== "string" || Object.values(this.#rawTokens).some(
        (token) => typeof token === "string" && serialized.includes(token));
  }

  #baseResult(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      ordinal: this.#bootstrap.ordinal,
      mode: this.#bootstrap.mode,
      origin: location.origin,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      document: {...this.#document},
      artifact: this.#artifact,
      capture_harness: this.#captureHarness,
      versions: this.#versions,
      tokenEvidence: this.#tokenEvidence(),
      run: this.#runSnapshot(),
      bridge: this.#bridgeSnapshot(),
      finalQuiescence: {...this.#finalQuiescence},
      hostBoundary: this.#hostBoundary(),
      fatalErrors: this.#fatalErrors.slice(),
      windowErrors: this.#windowErrors.slice(),
      unhandledRejections: this.#unhandledRejections.slice(),
      failedChecks: this.#failedChecks.slice(),
      error,
    };
  }

  #recheckBeforeResultUpload() {
    const quiescence = this.#finalQuiescence;
    quiescence.bridgeRecheckedImmediatelyBeforeUpload = true;
    quiescence.callbacksAtPreUploadCheck = this.#callbackCount;
    quiescence.processExitReportsAtPreUploadCheck = this.#processExitReportCount;
    quiescence.activeRunAtPreUploadCheck = this.#activeRun === null ? null :
        this.#activeRun.ordinal;
    const clean = quiescence.completed && quiescence.quiet &&
        quiescence.callbacksAtPreUploadCheck === quiescence.callbacksAtTaskEnd &&
        quiescence.processExitReportsAtPreUploadCheck ===
            quiescence.processExitReportsAtTaskEnd &&
        quiescence.activeRunAtPreUploadCheck === null &&
        this.#fatalErrors.length === 0 && this.#windowErrors.length === 0 &&
        this.#unhandledRejections.length === 0 && !this.#rawTokenLeakDetected;
    if (!clean) this.#recordFatal("result-upload-recheck");
    return clean;
  }

  async run() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function") {
        throw new Error("outer-reload requires cross-origin isolation");
      }
      if (this.#document.navigationType !==
          this.#bootstrap.expectedNavigationType) {
        throw new Error("outer-reload document navigation is invalid");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("outer-reload canvas focus failed");
      }
      this.#installPermanentBridge();
      this.#captureWindowErrors();
      await this.#prepareFactory();
      this.#startRun();
      const deadline = performance.now() + this.#context.timeoutMs;
      while (performance.now() < deadline) {
        if (this.#fatalErrors.length !== 0) break;
        if (this.#finalQuiescence.completed) {
          await this.#completionPromise;
          break;
        }
        await delay(10);
      }
      if (!this.#finalQuiescence.completed) {
        this.#recordFatal("outer-reload-host-timeout");
      }
      if (this.#fatalErrors.length !== 0) {
        return this.#baseResult("fail", "details-suppressed");
      }
      return this.#baseResult("pass", null);
    } catch (_error) {
      this.#recordFatal("outer-reload-host-exception");
      return this.#baseResult("fail", "details-suppressed");
    }
  }

  prepareResultForUpload(result) {
    if (result === null || typeof result !== "object" ||
        result.status !== "pass") {
      return result;
    }
    if (!this.#recheckBeforeResultUpload()) {
      return this.#baseResult("fail", "details-suppressed");
    }
    if (this.#containsOpaqueToken(result)) {
      this.#recordOpaqueTokenLeak();
      return this.#baseResult("fail", "details-suppressed");
    }
    return this.#baseResult("pass", null);
  }

  failureResult(code) {
    this.#recordFatal(code);
    return this.#baseResult("fail", "details-suppressed");
  }

  isReadyAfterResultUpload() {
    const quiescence = this.#finalQuiescence;
    return this.#fatalErrors.length === 0 && !this.#rawTokenLeakDetected &&
        quiescence.completed && quiescence.quiet && this.#activeRun === null &&
        this.#callbackCount === quiescence.callbacksAtPreUploadCheck &&
        this.#processExitReportCount ===
            quiescence.processExitReportsAtPreUploadCheck;
  }

  dispose() {
    this.#releaseWindowErrors();
    this.#releaseVerifiedLoader();
    this.#opaqueTokenTail = "";
  }
}

function requireExactProcessExitReport(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === 2 && Object.hasOwn(value, "protocol") &&
      Object.hasOwn(value, "exitCode") && value.protocol === HOST_PROTOCOL &&
      Number.isSafeInteger(value.exitCode);
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

function exactStringArray(value, maximum) {
  return Array.isArray(value) && value.length <= maximum &&
      value.every((entry) => typeof entry === "string");
}

function hasExactBooleanFields(value, fields) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === fields.length &&
      fields.every((field) => Object.hasOwn(value, field) &&
          value[field] === false);
}

function isValidOuterReloadSuccess(result, context, bootstrap) {
  try {
    const resultFields = [
      "protocol", "case", "scope", "status", "ordinal", "mode", "origin",
      "crossOriginIsolated", "sharedArrayBuffer", "document", "artifact",
      "capture_harness", "versions", "tokenEvidence", "run", "bridge",
      "finalQuiescence", "hostBoundary", "fatalErrors", "windowErrors",
      "unhandledRejections", "failedChecks", "error",
    ];
    requireExactFields(result, resultFields, "outer-reload result");
    if (result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
        result.scope !== SCOPE || result.status !== "pass" ||
        result.ordinal !== bootstrap.ordinal || result.mode !== bootstrap.mode ||
        result.origin !== location.origin || result.crossOriginIsolated !== true ||
        result.sharedArrayBuffer !== true || result.artifact !== context.artifact ||
        result.capture_harness !== context.captureHarness ||
        result.versions !== context.versions || result.error !== null) {
      return false;
    }

    requireExactFields(result.document, ["navigationType", "timeOrigin"],
                       "outer-reload document result");
    if (result.document.navigationType !== bootstrap.expectedNavigationType ||
        typeof result.document.timeOrigin !== "number" ||
        !Number.isFinite(result.document.timeOrigin) ||
        result.document.timeOrigin <= 0) {
      return false;
    }

    const tokenFields = [
      "algorithm", "tokenA", "tokenB", "distinct", "rawTokensExcluded",
      "rawTokenLeakDetected", "rawTokenRedactionCount",
    ];
    requireExactFields(result.tokenEvidence, tokenFields,
                       "outer-reload token evidence");
    if (result.tokenEvidence.algorithm !== "SHA-256" ||
        result.tokenEvidence.tokenA !== bootstrap.tokenEvidence.tokenA ||
        result.tokenEvidence.tokenB !== bootstrap.tokenEvidence.tokenB ||
        result.tokenEvidence.distinct !== bootstrap.tokenEvidence.distinct ||
        result.tokenEvidence.rawTokensExcluded !== true ||
        result.tokenEvidence.rawTokenLeakDetected !== false ||
        result.tokenEvidence.rawTokenRedactionCount !== 0) {
      return false;
    }

    const runFields = [
      "abort", "activeClearedAfterLifecycle", "expectedExitStatusObserved",
      "factoryError", "factorySettled", "freshModuleObject",
      "leaseReleasedMarkerObserved", "markerCount",
      "markerDeliveryCompleteAtProcessExit", "markerSequenceAccepted",
      "markerSource", "markers", "mode", "moduleIdentity", "onExitCount",
      "ordinal", "postLifecycleTimerObserved", "processExitBeforeOnExit",
      "processExitCode", "processExitCount", "runtimeExitCode",
      "runtimeInitialized", "stderr", "stdout",
    ];
    requireExactFields(result.run, runFields, "outer-reload run");
    const markers = expectedMarkers(bootstrap.ordinal, bootstrap.tokenEvidence);
    if (result.run.abort !== null ||
        result.run.activeClearedAfterLifecycle !== true ||
        typeof result.run.expectedExitStatusObserved !== "boolean" ||
        result.run.factoryError !== null || result.run.factorySettled !== true ||
        result.run.freshModuleObject !== true ||
        result.run.leaseReleasedMarkerObserved !== true ||
        result.run.markerCount !== markers.length ||
        typeof result.run.markerDeliveryCompleteAtProcessExit !== "boolean" ||
        result.run.markerSequenceAccepted !== true ||
        result.run.markerSource !== "stderr-only" ||
        !Array.isArray(result.run.markers) ||
        result.run.markers.length !== markers.length ||
        !result.run.markers.every((marker, index) => marker === markers[index]) ||
        result.run.mode !== bootstrap.mode ||
        typeof result.run.moduleIdentity !== "string" ||
        !MODULE_ID_RE.test(result.run.moduleIdentity) ||
        result.run.onExitCount !== 1 || result.run.ordinal !== bootstrap.ordinal ||
        result.run.postLifecycleTimerObserved !== true ||
        result.run.processExitBeforeOnExit !== true ||
        result.run.processExitCode !== 0 || result.run.processExitCount !== 1 ||
        result.run.runtimeExitCode !== 0 || result.run.runtimeInitialized !== true ||
        !exactStringArray(result.run.stderr, MAX_OUTPUT_LINES) ||
        !exactStringArray(result.run.stdout, MAX_OUTPUT_LINES) ||
        !result.run.stdout.every((line) => line === SUPPRESSED_NATIVE_OUTPUT) ||
        !result.run.stderr.every((line) =>
          line === SUPPRESSED_NATIVE_OUTPUT || markers.includes(line)) ||
        result.run.stdout.some((line) => line.includes(M7_MARKER_PREFIX)) ||
        result.run.stderr.some((line) => line.includes(M7_DATABASE_PHASE_PREFIX)) ||
        result.run.stdout.concat(result.run.stderr).some((line) =>
          line.includes("--wasm-profile-database-token"))) {
      return false;
    }
    const stderrMarkers = result.run.stderr.filter((line) =>
      line.startsWith(M7_MARKER_PREFIX));
    if (stderrMarkers.length !== markers.length ||
        !stderrMarkers.every((marker, index) => marker === markers[index]) ||
        result.run.stderr.some((line) => line.includes(M7_MARKER_PREFIX) &&
          !markers.includes(line))) {
      return false;
    }

    const bridgeFields = [
      "protocol", "permanent", "frozen", "installedBeforeModuleFactory",
      "processExitDispatches", "noActiveProcessExitRejected",
      "duplicateProcessExitRejected", "lateProcessExitRejected", "activeRunAtResult",
    ];
    requireExactFields(result.bridge, bridgeFields, "outer-reload bridge");
    if (result.bridge.protocol !== HOST_PROTOCOL || result.bridge.permanent !== true ||
        result.bridge.frozen !== true ||
        result.bridge.installedBeforeModuleFactory !== true ||
        result.bridge.processExitDispatches !== 1 ||
        result.bridge.noActiveProcessExitRejected !== 0 ||
        result.bridge.duplicateProcessExitRejected !== 0 ||
        result.bridge.lateProcessExitRejected !== 0 ||
        result.bridge.activeRunAtResult !== null) {
      return false;
    }

    const quiescenceFields = [
      "activeRunAtActiveClear", "activeRunAtPreUploadCheck",
      "activeRunAtTaskEnd", "activeRunAtTaskStart",
      "bridgeRecheckedImmediatelyBeforeUpload", "callbacksAtActiveClear",
      "callbacksAtPreUploadCheck", "callbacksAtTaskEnd", "callbacksAtTaskStart",
      "completed", "postLifecycleTimerObservedBeforeTask",
      "processExitReportsAtActiveClear", "processExitReportsAtPreUploadCheck",
      "processExitReportsAtTaskEnd", "processExitReportsAtTaskStart", "quiet",
      "quietWindowMs", "started", "startedAfterActiveClear", "taskMethod",
      "taskScheduledExactlyOnce",
    ];
    requireExactFields(result.finalQuiescence, quiescenceFields,
                       "outer-reload final quiescence");
    const quiescence = result.finalQuiescence;
    if (quiescence.activeRunAtActiveClear !== null ||
        quiescence.activeRunAtPreUploadCheck !== null ||
        quiescence.activeRunAtTaskEnd !== null ||
        quiescence.activeRunAtTaskStart !== null ||
        quiescence.bridgeRecheckedImmediatelyBeforeUpload !== true ||
        !Number.isSafeInteger(quiescence.callbacksAtActiveClear) ||
        quiescence.callbacksAtActiveClear < 0 ||
        quiescence.callbacksAtActiveClear !== quiescence.callbacksAtTaskStart ||
        quiescence.callbacksAtTaskStart !== quiescence.callbacksAtTaskEnd ||
        quiescence.callbacksAtTaskEnd !== quiescence.callbacksAtPreUploadCheck ||
        quiescence.completed !== true ||
        quiescence.postLifecycleTimerObservedBeforeTask !== true ||
        quiescence.processExitReportsAtActiveClear !== 1 ||
        quiescence.processExitReportsAtTaskStart !== 1 ||
        quiescence.processExitReportsAtTaskEnd !== 1 ||
        quiescence.processExitReportsAtPreUploadCheck !== 1 ||
        quiescence.quiet !== true ||
        quiescence.quietWindowMs !== FINAL_QUIESCENCE_MS ||
        quiescence.started !== true || quiescence.startedAfterActiveClear !== true ||
        quiescence.taskMethod !== "setTimeout(...,0)" ||
        quiescence.taskScheduledExactlyOnce !== true) {
      return false;
    }

    const boundaryFields = [
      "hostOpfsAccessAttempted", "hostWebLocksAccessAttempted",
      "nativeCallAttempted", "wasmDataInspectionAttempted",
      "sessionStorageAccessAttempted", "localStorageAccessAttempted",
      "indexedDbAccessAttempted", "cookieAccessAttempted",
      "historyStateAccessAttempted", "windowNameAccessAttempted",
    ];
    if (!hasExactBooleanFields(result.hostBoundary, boundaryFields) ||
        !exactStringArray(result.fatalErrors, MAX_ERROR_RECORDS) ||
        !exactStringArray(result.windowErrors, MAX_ERROR_RECORDS) ||
        !exactStringArray(result.unhandledRejections, MAX_ERROR_RECORDS) ||
        !exactStringArray(result.failedChecks, MAX_ERROR_RECORDS) ||
        result.fatalErrors.length !== 0 || result.windowErrors.length !== 0 ||
        result.unhandledRejections.length !== 0 || result.failedChecks.length !== 0) {
      return false;
    }
    return true;
  } catch (_error) {
    return false;
  }
}

function resultEndpoint(context, ordinal) {
  const endpoint = new URL(
      `./result/${encodeURIComponent(context.resultToken)}/${ordinal}`,
      location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("outer-reload result endpoint is invalid");
  }
  return endpoint;
}

function readyEndpoint(context, ordinal) {
  const endpoint = new URL(
      `./ready/${encodeURIComponent(context.resultToken)}/${ordinal}`,
      location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("outer-reload ready endpoint is invalid");
  }
  return endpoint;
}

function requireNoContentResponse(response, endpoint, description) {
  if (response.status !== 204 || response.url !== endpoint.href) {
    throw new Error(`${description} response is invalid`);
  }
  const required = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if (Object.entries(required).some(
      ([name, value]) => response.headers.get(name) !== value)) {
    throw new Error(`${description} response headers are invalid`);
  }
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
  requireNoContentResponse(response, endpoint, description);
}

async function postPhaseResult(context, result) {
  await postJson(resultEndpoint(context, result.ordinal), result,
                 "outer-reload result");
}

async function postReady(context, result) {
  const payload = {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    ordinal: result.ordinal,
    timeOrigin: result.document.timeOrigin,
  };
  await postJson(readyEndpoint(context, result.ordinal), payload,
                 "outer-reload ready");
}

export async function runChromeWasmProfileDatabaseOuterReloadFromQuery() {
  const context = parseStaticContext();
  const root = document.querySelector("#m7-profile-database-outer-reload-root");
  const canvas = document.querySelector("#m7-profile-database-outer-reload-canvas");
  const status = document.querySelector("#m7-profile-database-outer-reload-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("outer-reload page is missing required elements");
  }
  renderVersions(document.querySelector("#m7-profile-database-outer-reload-versions"),
                 context.versions);
  const documentReceipt = documentEvidence();
  await postBootstrapDocumentEvidence(context, documentReceipt);
  const bootstrap = await fetchBootstrap(context);
  if (documentReceipt.navigationType !== bootstrap.expectedNavigationType) {
    throw new Error("outer-reload document navigation is invalid");
  }
  const host = new ChromeWasmProfileDatabaseOuterReloadHost(
      canvas, context, bootstrap, documentReceipt);
  let result;
  try {
    result = host.prepareResultForUpload(await host.run());
    if (result.status === "pass" &&
        !isValidOuterReloadSuccess(result, context, bootstrap)) {
      result = host.failureResult("outer-reload-result-validation");
    }
    root.dataset.state = result.status;
    status.textContent = result.status === "pass" ?
        `outer-reload phase ${result.ordinal} complete` :
        "outer-reload phase failed; details suppressed";
    await postPhaseResult(context, result);
    if (result.status !== "pass") {
      throw new Error("outer-reload result validation failed");
    }
    await delay(0);
    if (!host.isReadyAfterResultUpload()) {
      throw new Error("outer-reload host changed after result upload");
    }
    await postReady(context, result);
    return result;
  } finally {
    // The first document must remain intact after its ready acknowledgement;
    // the runner, rather than host JavaScript, performs the next transition.
    if (result === undefined || result.status !== "pass" || result.ordinal === 2) {
      host.dispose();
    }
  }
}

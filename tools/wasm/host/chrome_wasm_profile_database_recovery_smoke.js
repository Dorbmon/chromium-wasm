// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Three fresh outer documents prove one intentionally bounded LevelDB recovery
// boundary. Chromium owns profile storage and database work; the host receives
// only runner-escrowed bootstrap values and fixed redacted receipts. It never
// reads OPFS or a database. The third module accepts only a stable A or B
// result across two checksum/paranoid close/reopen checks plus SQLite's two
// reopen/full-integrity A controls. That does not prove physical crash
// behavior, directory durability, SQLite interruption recovery, cross-store
// atomicity, general profile persistence, or M7 completion.

const HOST_PROTOCOL = 1;
const CASE = "chrome_profile_database_recovery_m7";
const SCOPE =
    "same-origin-three-outer-documents-chrome-wasm-m7-profile-database-bounded-leveldb-post-sync-recovery";
const PRODUCT_MODULE_NAME =
    "chrome_wasm_m7_profile_database_recovery_test";
const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:";
const M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
const SUPPRESSED_NATIVE_OUTPUT = "<suppressed-native-output>";
const MAX_TIMEOUT_MS = 300000;
const MAX_ERROR_RECORDS = 16;
const MAX_OPAQUE_SECRET_CHARS = 128;
const MODULE_ID_BYTES = 16;
const CLEAN_SETTLE_MS = 50;
const INTERRUPTION_SETTLE_MS = 75;
const FINAL_QUIESCENCE_MS = 50;
const SHA256_RE = /^[0-9a-f]{64}$/;
const MODULE_ID_RE = /^[0-9a-f]{32}$/;
const OPAQUE_CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;

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
const EXPECTED_EXIT_STATUS = Object.freeze({
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
});
const NATIVE_FAILURE_STAGES = Object.freeze([
  "arguments", "capability", "storage", "profile", "database", "fence",
  "lifecycle", "content", "drain",
]);
const GENERIC_DATABASE_PHASES = Object.freeze([
  "task-post", "task-started", "sqlite-write", "sqlite-read",
  "leveldb-write", "leveldb-write-open",
  "leveldb-write-pre-dbimpl-construction", "leveldb-write-put",
  "leveldb-write-compact", "leveldb-write-close", "leveldb-write-tracker",
  "leveldb-write-env-file-exists-first-pre",
  "leveldb-write-env-file-exists-first-post",
  "leveldb-write-env-file-exists-second-pre",
  "leveldb-write-env-file-exists-second-post",
  "leveldb-write-env-file-exists-later-pre",
  "leveldb-write-env-file-exists-later-post",
  "leveldb-write-env-create-dir", "leveldb-write-env-rename-file",
  "leveldb-write-env-new-logger",
  "leveldb-write-logger-logv-first-pre",
  "leveldb-write-logger-logv-first-post", "leveldb-write-env-lock-file",
  "leveldb-write-env-new-writable-file", "leveldb-read", "leveldb-read-open",
  "leveldb-read-get", "leveldb-read-close", "task-complete",
]);
const INTERRUPTION_PHASE = "leveldb-write-log-sync-returned";
const CONTROLLED_ABORT_REASON = "native code called abort()";
const CONTROLLED_ABORT_ERROR =
    `Uncaught RuntimeError: Aborted(${CONTROLLED_ABORT_REASON})`;
// Chrome's worker error wrapper preserves the exact Emscripten abort error in
// a nested ErrorEvent before the direct Emscripten error reaches the window.
const CONTROLLED_ABORT_WORKER_ERROR = "Uncaught [object ErrorEvent]";
const CONTROLLED_ABORT_WINDOW_ERROR_COUNT = 2;
const RECOVERED_LEVELDB_VALUES = Object.freeze(["a", "b"]);
const RECOVERY_LEASE_REACQUIRED_MARKER =
    `${M7_MARKER_PREFIX}RECOVERY_LEASE_REACQUIRED`;
const RECOVERY_SQLITE_A_INTEGRITY_MARKER =
    `${M7_MARKER_PREFIX}SQLITE_RECOVERY_A_INTEGRITY_OK`;
const RECOVERY_CLEAN_MARKERS = Object.freeze([
  `${M7_MARKER_PREFIX}RECOVERY_DATABASES_CLOSED`,
  `${M7_MARKER_PREFIX}RECOVERY_FENCE_OK`,
  `${M7_MARKER_PREFIX}RECOVERY_LEASE_RELEASED`,
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

function requireString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} is invalid`);
  }
  return value;
}

function parseQueryJson(value, description) {
  try {
    return JSON.parse(requireString(value, description));
  } catch (_error) {
    throw new Error(`${description} is invalid`);
  }
}

function parsePositiveTimeout(value) {
  if (typeof value !== "string" || !/^[0-9]+$/.test(value)) {
    throw new Error("recovery timeout is invalid");
  }
  const timeoutMs = Number(value);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("recovery timeout is invalid");
  }
  return timeoutMs;
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, ["bytes", "sha256"], description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifactIdentity(value) {
  const artifact = requireExactFields(
      parseQueryJson(value, "recovery artifact identity"),
      ARTIFACT_FIELDS, "recovery artifact identity");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error("recovery artifact identity is invalid");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    build_config: parseByteIdentity(artifact.build_config,
                                    "recovery build configuration"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "recovery loader"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "recovery Wasm"),
  });
}

function parseCaptureHarnessIdentity(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "recovery capture harness"),
      CAPTURE_HARNESS_FIELDS, "recovery capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("recovery capture harness is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html,
                                 "recovery host HTML"),
    host_js: parseByteIdentity(harness.host_js,
                               "recovery host JavaScript"),
    runner_source: parseByteIdentity(harness.runner_source,
                                     "recovery runner source"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = requireExactFields(
      parseQueryJson(value, "recovery versions"),
      ["chromium", "v8", "emscripten"], "recovery versions");
  for (const revision of Object.values(versions)) {
    if (typeof revision !== "string" || !/^[0-9a-f]{40}$/.test(revision)) {
      throw new Error("recovery versions are invalid");
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
      throw new Error("recovery query is invalid");
    }
  }
  const resultToken = requireString(query.get("resultToken"),
                                    "recovery result capability");
  const session = requireString(query.get("session"),
                                "recovery session capability");
  if (!OPAQUE_CAPABILITY_RE.test(resultToken) || !OPAQUE_CAPABILITY_RE.test(session) ||
      resultToken === session || query.get("module") !== PRODUCT_MODULE_NAME) {
    throw new Error("recovery query is invalid");
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
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 || !globalThis.crypto ||
      typeof globalThis.crypto.getRandomValues !== "function") {
    throw new Error("recovery random source is unavailable");
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
  if (actualType !== contentType || Object.entries(required).some(
      ([name, expected]) => response.headers.get(name) !== expected)) {
    throw new Error(`${description} response headers are invalid`);
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
    throw new Error(`${description} request failed`);
  }
  if (!response.ok || response.url !== url.href) {
    throw new Error(`${description} response is invalid`);
  }
  requireResponseHeaders(response, contentType, description);
  let bytes;
  try {
    bytes = new Uint8Array(await response.arrayBuffer());
  } catch (_error) {
    throw new Error(`${description} bytes are invalid`);
  }
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} identity is invalid`);
  }
  return bytes;
}

function modeForOrdinal(ordinal) {
  if (ordinal === 1) return "write-a";
  if (ordinal === 2) return "interrupt-leveldb-write-b";
  if (ordinal === 3) return "recover-leveldb-write-b";
  throw new Error("recovery bootstrap ordinal is invalid");
}

function expectedDocumentNavigation(ordinal) {
  return ordinal === 1 ? "navigate" : "reload";
}

function expectedCleanMarkers(ordinal, tokenEvidence) {
  if (ordinal === 1) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      RECOVERY_LEASE_REACQUIRED_MARKER,
      `${M7_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256=${tokenEvidence.tokenA}`,
      `${M7_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256=${tokenEvidence.tokenA}`,
      ...RECOVERY_CLEAN_MARKERS,
    ]);
  }
  if (ordinal === 3) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      RECOVERY_LEASE_REACQUIRED_MARKER,
      null,
      `${RECOVERY_SQLITE_A_INTEGRITY_MARKER} sha256=${tokenEvidence.tokenA}`,
      ...RECOVERY_CLEAN_MARKERS,
    ]);
  }
  throw new Error("recovery clean markers are invalid");
}

function expectedInterruptionMarkers(tokenEvidence) {
  return Object.freeze([
    `${M7_MARKER_PREFIX}READY`,
    RECOVERY_LEASE_REACQUIRED_MARKER,
    `${M7_MARKER_PREFIX}SQLITE_READ_A_OK sha256=${tokenEvidence.tokenA}`,
    `${M7_MARKER_PREFIX}LEVELDB_READ_A_OK sha256=${tokenEvidence.tokenA}`,
  ]);
}

function fixedNativeFailureStage(text) {
  const prefix = `${M7_MARKER_PREFIX}FAIL stage=`;
  if (typeof text !== "string" || !text.startsWith(prefix)) return null;
  const stage = text.slice(prefix.length);
  return NATIVE_FAILURE_STAGES.includes(stage) ? stage : null;
}

function fixedDatabasePhase(text) {
  if (typeof text !== "string" || !text.startsWith(M7_DATABASE_PHASE_PREFIX)) {
    return null;
  }
  const phase = text.slice(M7_DATABASE_PHASE_PREFIX.length);
  return phase === INTERRUPTION_PHASE || GENERIC_DATABASE_PHASES.includes(phase) ?
      phase : null;
}

function fixedRecoveredLevelDBValue(text) {
  const prefix = `${M7_MARKER_PREFIX}LEVELDB_RECOVERY_`;
  if (typeof text !== "string" || !text.startsWith(prefix)) return null;
  const suffix = "_OK sha256=";
  const valueEnd = text.indexOf(suffix, prefix.length);
  if (valueEnd < 0) return null;
  const value = text.slice(prefix.length, valueEnd).toLowerCase();
  const digest = text.slice(valueEnd + suffix.length);
  return RECOVERED_LEVELDB_VALUES.includes(value) && SHA256_RE.test(digest) ?
      Object.freeze({digest, value}) : null;
}

export function isExactRecoveryExitStatus(value) {
  try {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      return false;
    }
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const keys = Reflect.ownKeys(descriptors);
    if (keys.length !== Object.keys(EXPECTED_EXIT_STATUS).length ||
        keys.some((key) => typeof key !== "string" ||
          !Object.hasOwn(EXPECTED_EXIT_STATUS, key))) {
      return false;
    }
    return Object.entries(EXPECTED_EXIT_STATUS).every(([name, expected]) => {
      const descriptor = descriptors[name];
      return descriptor !== undefined && Object.hasOwn(descriptor, "value") &&
          !Object.hasOwn(descriptor, "get") && !Object.hasOwn(descriptor, "set") &&
          descriptor.value === expected;
    });
  } catch (_error) {
    return false;
  }
}

function documentEvidence() {
  const navigation = performance.getEntriesByType("navigation")[0];
  const navigationType = navigation && typeof navigation === "object" ?
      navigation.type : null;
  const timeOrigin = performance.timeOrigin;
  if ((navigationType !== "navigate" && navigationType !== "reload") ||
      typeof timeOrigin !== "number" || !Number.isFinite(timeOrigin) ||
      timeOrigin <= 0) {
    throw new Error("recovery document evidence is invalid");
  }
  return Object.freeze({navigationType, timeOrigin});
}

function bootstrapUrl(context) {
  const endpoint = new URL(
      `./bootstrap/${encodeURIComponent(context.session)}`, location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("recovery bootstrap endpoint is invalid");
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
  const required = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if (Object.entries(required).some(
      ([name, expected]) => response.headers.get(name) !== expected)) {
    throw new Error(`${description} response headers are invalid`);
  }
}

async function postBootstrapDocumentEvidence(context, receipt) {
  const document = requireExactFields(
      receipt, ["navigationType", "timeOrigin"],
      "recovery bootstrap document evidence");
  await postJson(bootstrapUrl(context), {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    navigationType: document.navigationType,
    timeOrigin: document.timeOrigin,
  }, "recovery bootstrap document evidence");
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
    throw new Error("recovery bootstrap request failed");
  }
  if (response.status !== 200 || response.url !== endpoint.href) {
    throw new Error("recovery bootstrap request was rejected");
  }
  requireResponseHeaders(response, "application/json", "recovery bootstrap");
  let value;
  try {
    value = await response.json();
  } catch (_error) {
    throw new Error("recovery bootstrap is invalid");
  }
  return parseBootstrap(value);
}

async function parseBootstrap(value) {
  const bootstrap = requireExactFields(value, BOOTSTRAP_FIELDS,
                                       "recovery bootstrap");
  const hasB = bootstrap.ordinal === 2 || bootstrap.ordinal === 3;
  if (bootstrap.protocol !== HOST_PROTOCOL || bootstrap.case !== CASE ||
      bootstrap.scope !== SCOPE || !Number.isSafeInteger(bootstrap.ordinal) ||
      bootstrap.mode !== modeForOrdinal(bootstrap.ordinal) ||
      typeof bootstrap.tokenA !== "string" || !SHA256_RE.test(bootstrap.tokenA) ||
      typeof bootstrap.tokenADigest !== "string" ||
      !SHA256_RE.test(bootstrap.tokenADigest) ||
      (!hasB && (bootstrap.tokenB !== null || bootstrap.tokenBDigest !== null)) ||
      (hasB && (typeof bootstrap.tokenB !== "string" ||
                !SHA256_RE.test(bootstrap.tokenB) ||
                typeof bootstrap.tokenBDigest !== "string" ||
                !SHA256_RE.test(bootstrap.tokenBDigest) ||
                bootstrap.tokenB === bootstrap.tokenA))) {
    throw new Error("recovery bootstrap is invalid");
  }
  if (typeof TextEncoder !== "function") {
    throw new Error("recovery token encoder is unavailable");
  }
  const tokenA = await sha256Hex(
      new TextEncoder().encode(bootstrap.tokenA), "recovery token A");
  const tokenB = hasB ? await sha256Hex(
      new TextEncoder().encode(bootstrap.tokenB), "recovery token B") : null;
  if (tokenA !== bootstrap.tokenADigest ||
      (hasB && tokenB !== bootstrap.tokenBDigest)) {
    throw new Error("recovery bootstrap token identity is invalid");
  }
  return Object.freeze({
    ordinal: bootstrap.ordinal,
    mode: bootstrap.mode,
    rawTokens: Object.freeze({tokenA: bootstrap.tokenA, tokenB: bootstrap.tokenB}),
    tokenEvidence: Object.freeze({
      algorithm: "SHA-256",
      tokenA,
      tokenB,
      distinct: hasB ? true : null,
      rawTokensExcluded: true,
      rawTokenLeakDetected: false,
      rawTokenRedactionCount: 0,
    }),
  });
}

class ChromeWasmProfileDatabaseRecoveryHost {
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
  #factory = null;
  #factoryCalls = 0;
  #fatalErrors = [];
  #failedChecks = [];
  #finalQuiescence = {
    activeRunAtEnd: null,
    activeRunAtStart: null,
    activeRunAtPreUploadCheck: null,
    bridgeRecheckedImmediatelyBeforeUpload: false,
    callbacksAtEnd: null,
    callbacksAtPreUploadCheck: null,
    callbacksAtStart: null,
    completed: false,
    processExitReportsAtEnd: null,
    processExitReportsAtPreUploadCheck: null,
    processExitReportsAtStart: null,
    quiet: false,
    quietWindowMs: FINAL_QUIESCENCE_MS,
    started: false,
  };
  #loaderImportUrl = null;
  #mainScriptUrlOrBlob = null;
  #opaqueTail = "";
  #processExitReportCount = 0;
  #rawTokenLeakDetected = false;
  #rawTokenRedactionCount = 0;
  #rawTokens;
  #run = null;
  #versions;
  #wasmBinary = null;
  #wasmUrl = null;
  #windowErrors = [];
  #windowErrorHandler;
  #unhandledRejections = [];
  #unhandledRejectionHandler;

  constructor(canvas, context, bootstrap, documentReceipt) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("recovery canvas is unavailable");
    }
    this.#artifact = context.artifact;
    this.#bootstrap = bootstrap;
    this.#canvas = canvas;
    this.#captureHarness = context.captureHarness;
    this.#context = context;
    this.#document = Object.freeze({...documentReceipt});
    this.#rawTokens = Object.freeze({
      tokenA: bootstrap.rawTokens.tokenA,
      tokenB: bootstrap.rawTokens.tokenB,
      resultToken: context.resultToken,
      session: context.session,
    });
    this.#versions = context.versions;
    this.#completionPromise = new Promise((resolve) => {
      this.#completionResolver = resolve;
    });
  }

  #recordFailure(code) {
    if (typeof code !== "string" || code.length === 0) {
      throw new Error("recovery failure code is invalid");
    }
    if (!this.#failedChecks.includes(code) &&
        this.#failedChecks.length < MAX_ERROR_RECORDS) {
      this.#failedChecks.push(code);
    }
  }

  #recordFatal(code) {
    this.#recordFailure(code);
    if (!this.#fatalErrors.includes(code) &&
        this.#fatalErrors.length < MAX_ERROR_RECORDS) {
      this.#fatalErrors.push(code);
    }
  }

  #noteCallback() {
    this.#callbackCount += 1;
  }

  #scrubCapturedFields() {
    const scrubbed = "<scrubbed-after-opaque-token-leak>";
    this.#fatalErrors = this.#fatalErrors.map(() => scrubbed);
    this.#failedChecks = this.#failedChecks.map(() => scrubbed);
    this.#windowErrors = this.#windowErrors.map(() => scrubbed);
    this.#unhandledRejections = this.#unhandledRejections.map(() => scrubbed);
    if (this.#run !== null) {
      this.#run.markers = this.#run.markers.map(() => scrubbed);
      this.#run.recoveredLevelDBValue = null;
    }
  }

  #observeOpaqueText(value, acrossCallbacks = false) {
    if (this.#rawTokenLeakDetected) return;
    if (typeof value !== "string") return;
    const text = acrossCallbacks ? this.#opaqueTail + value : value;
    if (Object.values(this.#rawTokens).some(
        (secret) => typeof secret === "string" && text.includes(secret))) {
      this.#rawTokenLeakDetected = true;
      this.#rawTokenRedactionCount += 1;
      this.#opaqueTail = "";
      this.#scrubCapturedFields();
      return;
    }
    if (acrossCallbacks) {
      this.#opaqueTail = text.slice(-(MAX_OPAQUE_SECRET_CHARS - 1));
    }
  }

  #captureWindowErrors() {
    this.#windowErrorHandler = (event) => {
      this.#noteCallback();
      if (this.#acceptExpectedControlledAbortWindowError(event)) return;
      if (this.#windowErrors.length < MAX_ERROR_RECORDS) {
        this.#windowErrors.push(SUPPRESSED_NATIVE_OUTPUT);
      }
      this.#recordFatal("window-error");
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#noteCallback();
      const reason = event && typeof event === "object" ? event.reason : null;
      if (this.#acceptExpectedCleanExitRejection(event, reason)) return;
      this.#observeOpaqueText(typeof reason === "string" ? reason : "", true);
      if (this.#unhandledRejections.length < MAX_ERROR_RECORDS) {
        this.#unhandledRejections.push(SUPPRESSED_NATIVE_OUTPUT);
      }
      this.#recordFatal("unhandled-rejection");
    };
    addEventListener("error", this.#windowErrorHandler);
    addEventListener("unhandledrejection", this.#unhandledRejectionHandler);
  }

  #acceptExpectedControlledAbortWindowError(event) {
    const run = this.#activeRun;
    const eventMessage = typeof event?.message === "string" ? event.message : "";
    const error = event && typeof event === "object" ? event.error : null;
    const errorMessage = error && typeof error.message === "string" ?
        error.message : "";
    const nestedError = error && typeof error === "object" ? error.error :
        undefined;
    const errorConstructorName = error && error.constructor &&
            typeof error.constructor.name === "string" ?
        error.constructor.name : "";
    this.#observeOpaqueText(eventMessage, true);
    this.#observeOpaqueText(errorMessage, true);
    if (this.#rawTokenLeakDetected || run === null || run.ordinal !== 2 ||
        !run.abortObserved || run.abortCount !== 1 || !run.phaseObserved ||
        run.phaseCount !== 1 || run.markerIndex !==
            expectedInterruptionMarkers(this.#bootstrap.tokenEvidence).length ||
        run.processExitCount !== 0 || run.onExitCount !== 0) {
      return false;
    }
    if (run.controlledAbortWindowErrorCount === 0 &&
        eventMessage === CONTROLLED_ABORT_WORKER_ERROR &&
        errorConstructorName === "ErrorEvent" &&
        nestedError === null &&
        errorMessage === CONTROLLED_ABORT_ERROR) {
      run.controlledAbortWindowErrorCount += 1;
      return true;
    }
    if (run.controlledAbortWindowErrorCount === 1 && error === null &&
        eventMessage === CONTROLLED_ABORT_ERROR) {
      run.controlledAbortWindowErrorCount += 1;
      this.#maybeCompleteInterruptedRun(run);
      return true;
    }
    return false;
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
      throw new Error("recovery host bridge already exists");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(_message) {
        host.#noteCallback();
        host.#recordFatal("native-bridge-fatal");
      },
      reportProcessExit(report) { host.#routeProcessExit(report); },
      reportFrame(_report) { host.#noteCallback(); },
      reportReadiness(_report) { host.#noteCallback(); },
      reportOzoneFocusState(_report) { host.#noteCallback(); },
      reportOzoneCursor(_report) { host.#noteCallback(); return true; },
      reportOzoneTextInputState(_report) { host.#noteCallback(); },
      reportOzoneTextInputDelivery(_report) { host.#noteCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) { host.#noteCallback(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) {
        host.#noteCallback();
      },
      requestOuterOriginStorageEstimate(_report) {
        host.#noteCallback();
        return false;
      },
      reportAccessibilitySnapshot(_report) {
        host.#noteCallback();
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
      throw new Error("recovery host bridge is invalid");
    }
    this.#bridgeInstalled = true;
  }

  async #prepareFactory() {
    const loaderUrl = new URL(
        `./artifacts/${this.#context.moduleName}.js`, location.href);
    const wasmUrl = new URL(
        `./artifacts/${this.#context.moduleName}.wasm`, location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("recovery artifacts are not same-origin");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(loaderUrl, this.#artifact.loader, "text/javascript",
                            "recovery loader"),
      fetchVerifiedArtifact(wasmUrl, this.#artifact.wasm, "application/wasm",
                            "recovery Wasm"),
    ]);
    if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("recovery verified loader import is unavailable");
    }
    const blob = new Blob([loaderBytes], {type: "text/javascript"});
    this.#loaderImportUrl = URL.createObjectURL(blob);
    const namespace = await import(this.#loaderImportUrl);
    if (typeof namespace.default !== "function") {
      throw new Error("recovery loader has no factory");
    }
    this.#factory = namespace.default;
    this.#mainScriptUrlOrBlob = blob;
    this.#wasmBinary = wasmBytes;
    this.#wasmUrl = wasmUrl;
  }

  #newRun() {
    const ordinal = this.#bootstrap.ordinal;
    return {
      abortCount: 0,
      abortObserved: false,
      cleanExitObserved: false,
      controlledAbortWindowErrorCount: 0,
      expectedCleanExitStatusObserved: false,
      factoryRejected: false,
      factoryResolved: false,
      factorySettled: false,
      markerIndex: 0,
      markerSequenceAccepted: true,
      markers: [],
      mode: this.#bootstrap.mode,
      module: null,
      moduleIdentity: randomHex(MODULE_ID_BYTES),
      onExitCount: 0,
      ordinal,
      phaseCount: 0,
      phaseObserved: false,
      processExitCode: null,
      processExitCount: 0,
      recoveredLevelDBValue: null,
      runtimeExitCode: null,
      runtimeInitialized: false,
      settleComplete: false,
      // Includes the initial settle plus the final no-callback barrier.
      settleWindowMs: ordinal === 2 ?
          INTERRUPTION_SETTLE_MS + FINAL_QUIESCENCE_MS :
          CLEAN_SETTLE_MS + FINAL_QUIESCENCE_MS,
      settling: false,
      stdoutMarkerCount: 0,
    };
  }

  #expectedMarker(run) {
    if (run.ordinal === 2) {
      return expectedInterruptionMarkers(this.#bootstrap.tokenEvidence)[run.markerIndex] ?? null;
    }
    return expectedCleanMarkers(run.ordinal, this.#bootstrap.tokenEvidence)[run.markerIndex] ?? null;
  }

  #captureOutput(run, destination, line) {
    this.#noteCallback();
    this.#observeOpaqueText(line, true);
    if (this.#activeRun !== run) {
      if (!run.settleComplete) this.#recordFatal("native-output-outside-active-run");
      return;
    }
    if (this.#rawTokenLeakDetected) return;
    const text = typeof line === "string" ? line : "";
    const containsMarker = text.includes(M7_MARKER_PREFIX);
    const containsPhase = text.includes(M7_DATABASE_PHASE_PREFIX);
    if (destination !== "stderr") {
      if (containsMarker || containsPhase) {
        run.stdoutMarkerCount += 1;
        this.#recordFatal("native-marker-on-stdout");
      }
      return;
    }
    if (containsPhase) {
      const phase = fixedDatabasePhase(text);
      if (phase === null || text !== `${M7_DATABASE_PHASE_PREFIX}${phase}`) {
        this.#recordFatal("database-phase-invalid");
        return;
      }
      if (phase === INTERRUPTION_PHASE) {
        if (run.ordinal !== 2 || run.phaseObserved || run.markerIndex !== 4) {
          this.#recordFatal("post-sync-phase-invalid");
          return;
        }
        run.phaseObserved = true;
        run.phaseCount += 1;
        this.#maybeCompleteInterruptedRun(run);
      } else if (run.ordinal !== 1) {
        // Only doc 1 preserves its regular seed phases. The interrupted and
        // strict recovery modes must expose no extra phase data that could be
        // mistaken for a clean lifecycle completion.
        this.#recordFatal("unexpected-database-phase");
      }
      return;
    }
    if (!containsMarker) return;
    if (!text.startsWith(M7_MARKER_PREFIX)) {
      this.#recordFatal("database-marker-invalid");
      return;
    }
    if (fixedNativeFailureStage(text) !== null) {
      this.#recordFatal("database-native-fixed-failure");
      return;
    }
    if (run.ordinal === 3) {
      const recovered = fixedRecoveredLevelDBValue(text);
      if (recovered !== null) {
        const expectedDigest = recovered.value === "a" ?
            this.#bootstrap.tokenEvidence.tokenA :
            this.#bootstrap.tokenEvidence.tokenB;
        if (run.markerIndex !== 2 || run.recoveredLevelDBValue !== null ||
            recovered.digest !== expectedDigest) {
          this.#recordFatal("recovery-value-invalid");
          return;
        }
        run.recoveredLevelDBValue = recovered.value;
        run.markers.push(text);
        run.markerIndex += 1;
        this.#maybeCompleteCleanRun(run);
        return;
      }
    }
    const expected = this.#expectedMarker(run);
    if (expected === null || text !== expected) {
      run.markerSequenceAccepted = false;
      this.#recordFatal("database-marker-invalid");
      return;
    }
    run.markers.push(text);
    run.markerIndex += 1;
    if (run.ordinal === 2 && run.phaseObserved) {
      this.#recordFatal("marker-after-post-sync-phase");
      return;
    }
    this.#maybeCompleteCleanRun(run);
  }

  #reportRuntimeInitialized(run, module) {
    this.#noteCallback();
    if (this.#activeRun !== run && run.settleComplete) return;
    if (this.#activeRun !== run || run.runtimeInitialized || !module ||
        (typeof module !== "object" && typeof module !== "function") ||
        (run.module !== null && run.module !== module)) {
      this.#recordFatal("runtime-initialization-invalid");
      return;
    }
    run.module = module;
    run.runtimeInitialized = true;
    if (run.ordinal === 2) {
      this.#maybeCompleteInterruptedRun(run);
      return;
    }
    this.#maybeCompleteCleanRun(run);
  }

  #reportRuntimeExit(run, code) {
    this.#noteCallback();
    if (this.#activeRun !== run && run.settleComplete) return;
    if (this.#activeRun !== run || !Number.isSafeInteger(code) ||
        run.onExitCount !== 0 || run.ordinal === 2) {
      this.#recordFatal("runtime-onexit-invalid");
      return;
    }
    run.onExitCount += 1;
    run.runtimeExitCode = code;
    run.cleanExitObserved = code === 0;
    if (code !== 0) this.#recordFatal("runtime-onexit-nonzero");
    this.#maybeCompleteCleanRun(run);
  }

  #routeProcessExit(report) {
    this.#noteCallback();
    this.#processExitReportCount += 1;
    const run = this.#activeRun;
    if (run === null && this.#run !== null && this.#run.settleComplete) return;
    if (run === null || !isExactProcessExitReport(report) ||
        run.processExitCount !== 0 || run.ordinal === 2) {
      this.#recordFatal("process-exit-invalid");
      return;
    }
    run.processExitCount += 1;
    run.processExitCode = report.exitCode;
    this.#bridgeProcessExitDispatches += 1;
    if (report.exitCode !== 0) this.#recordFatal("process-exit-nonzero");
    this.#maybeCompleteCleanRun(run);
  }

  #reportAbort(run, reason) {
    this.#noteCallback();
    const abortReason = typeof reason === "string" ? reason : "";
    this.#observeOpaqueText(abortReason, true);
    if (this.#activeRun !== run && run.settleComplete) return;
    if (this.#activeRun !== run || run.ordinal !== 2 || run.abortObserved ||
        run.processExitCount !== 0 || run.onExitCount !== 0 ||
        abortReason !== CONTROLLED_ABORT_REASON) {
      this.#recordFatal("runtime-abort-invalid");
      return;
    }
    run.abortCount += 1;
    run.abortObserved = true;
    this.#maybeCompleteInterruptedRun(run);
  }

  #factoryResolved(run, module) {
    this.#noteCallback();
    if (this.#activeRun !== run && run.settleComplete) return;
    if (run.factorySettled) {
      this.#recordFatal("factory-double-settle");
      return;
    }
    run.factorySettled = true;
    run.factoryResolved = true;
    if (!module || (typeof module !== "object" && typeof module !== "function") ||
        (run.module !== null && run.module !== module)) {
      this.#recordFatal("factory-module-invalid");
      return;
    }
    run.module = module;
    // Emscripten's factory promise signals runtime initialization, not a
    // graceful application exit.  In the interrupted document it resolves
    // before the proxied browser main reaches the deliberate post-Sync abort.
    // Keep accepting the initialized Module, while separately requiring the
    // interruption-specific phase, abort, and no-clean-exit evidence below.
    if (run.ordinal === 2) {
      this.#maybeCompleteInterruptedRun(run);
      return;
    }
    this.#maybeCompleteCleanRun(run);
  }

  #factoryRejected(run, error) {
    this.#noteCallback();
    this.#observeOpaqueText(typeof error === "string" ? error : "", true);
    if (this.#activeRun !== run && run.settleComplete) return;
    if (run.factorySettled) {
      this.#recordFatal("factory-double-settle");
      return;
    }
    run.factorySettled = true;
    run.factoryRejected = true;
    this.#recordFatal("factory-rejected");
  }

  #acceptExpectedCleanExitRejection(event, reason) {
    const run = this.#activeRun;
    if (run === null || run.ordinal === 2 || run.expectedCleanExitStatusObserved ||
        !isExactRecoveryExitStatus(reason) || !event ||
        typeof event.preventDefault !== "function") {
      return false;
    }
    try {
      event.preventDefault();
    } catch (_error) {
      return false;
    }
    run.expectedCleanExitStatusObserved = true;
    this.#maybeCompleteCleanRun(run);
    return true;
  }

  #cleanMarkersComplete(run) {
    const expected = expectedCleanMarkers(run.ordinal, this.#bootstrap.tokenEvidence);
    return run.markerSequenceAccepted && run.markerIndex === expected.length &&
        (run.ordinal !== 3 ||
         RECOVERED_LEVELDB_VALUES.includes(run.recoveredLevelDBValue));
  }

  #cleanRunComplete(run) {
    return run.ordinal !== 2 && this.#cleanMarkersComplete(run) &&
        run.runtimeInitialized && run.factorySettled && run.factoryResolved &&
        !run.factoryRejected && run.abortCount === 0 && !run.abortObserved &&
        run.controlledAbortWindowErrorCount === 0 &&
        run.processExitCount === 1 && run.processExitCode === 0 &&
        run.onExitCount === 1 && run.runtimeExitCode === 0 && run.cleanExitObserved &&
        this.#factoryCalls === 1;
  }

  #interruptedRunComplete(run) {
    return run.ordinal === 2 && run.markerSequenceAccepted &&
        run.markerIndex === expectedInterruptionMarkers(this.#bootstrap.tokenEvidence).length &&
        run.runtimeInitialized && run.phaseObserved && run.phaseCount === 1 && run.abortObserved &&
        run.abortCount === 1 && run.processExitCount === 0 && run.onExitCount === 0 &&
        !run.cleanExitObserved && run.factorySettled && run.factoryResolved &&
        !run.factoryRejected && run.controlledAbortWindowErrorCount ===
            CONTROLLED_ABORT_WINDOW_ERROR_COUNT && this.#factoryCalls === 1;
  }

  #maybeCompleteCleanRun(run) {
    if (this.#activeRun !== run || run.settling || !this.#cleanRunComplete(run)) {
      return;
    }
    run.settling = true;
    setTimeout(() => {
      if (this.#activeRun !== run || !this.#cleanRunComplete(run) ||
          this.#fatalErrors.length !== 0) {
        this.#recordFatal("clean-settle-invalid");
        return;
      }
      this.#beginFinalQuiescence(run);
    }, CLEAN_SETTLE_MS);
  }

  #maybeCompleteInterruptedRun(run) {
    // The phase and onAbort callbacks intentionally have no ordering rule.
    if (this.#activeRun !== run || run.settling || !this.#interruptedRunComplete(run)) {
      return;
    }
    run.settling = true;
    setTimeout(() => {
      if (this.#activeRun !== run || !this.#interruptedRunComplete(run) ||
          this.#fatalErrors.length !== 0) {
        this.#recordFatal("interruption-settle-invalid");
        return;
      }
      this.#beginFinalQuiescence(run);
    }, INTERRUPTION_SETTLE_MS);
  }

  #beginFinalQuiescence(run) {
    const quiescence = this.#finalQuiescence;
    if (this.#activeRun !== run || quiescence.started ||
        this.#fatalErrors.length !== 0) {
      this.#recordFatal("final-quiescence-start-invalid");
      return;
    }
    quiescence.started = true;
    quiescence.callbacksAtStart = this.#callbackCount;
    quiescence.processExitReportsAtStart = this.#processExitReportCount;
    quiescence.activeRunAtStart = run.ordinal;
    setTimeout(() => this.#finishFinalQuiescence(run), FINAL_QUIESCENCE_MS);
  }

  #finishFinalQuiescence(run) {
    const quiescence = this.#finalQuiescence;
    if (this.#activeRun !== run || !quiescence.started || quiescence.completed) {
      this.#recordFatal("final-quiescence-completion-invalid");
      return;
    }
    quiescence.callbacksAtEnd = this.#callbackCount;
    quiescence.processExitReportsAtEnd = this.#processExitReportCount;
    quiescence.activeRunAtEnd = run.ordinal;
    quiescence.quiet = this.#fatalErrors.length === 0 &&
        quiescence.callbacksAtStart === quiescence.callbacksAtEnd &&
        quiescence.processExitReportsAtStart ===
            quiescence.processExitReportsAtEnd &&
        quiescence.activeRunAtStart === run.ordinal &&
        quiescence.activeRunAtEnd === run.ordinal;
    quiescence.completed = true;
    if (!quiescence.quiet) {
      this.#recordFatal("final-quiescence-not-quiet");
      return;
    }
    run.settleComplete = true;
    this.#activeRun = null;
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
    const moduleArguments = [
      `--wasm-profile-database-smoke=${run.mode}`,
      `--wasm-profile-database-token-a=${this.#bootstrap.rawTokens.tokenA}`,
    ];
    if (this.#bootstrap.rawTokens.tokenB !== null) {
      moduleArguments.push(
          `--wasm-profile-database-token-b=${this.#bootstrap.rawTokens.tokenB}`);
    }
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
        print(line) { host.#captureOutput(run, "stdout", line); },
        printErr(line) { host.#captureOutput(run, "stderr", line); },
        wasmBinary: this.#wasmBinary,
      });
      Promise.resolve(factoryResult).then(
          (module) => host.#factoryResolved(run, module),
          (error) => host.#factoryRejected(run, error));
    } catch (_error) {
      this.#factoryRejected(run, "");
    }
  }

  #locateFileForWasm(path) {
    if (typeof path !== "string" ||
        path !== `${this.#context.moduleName}.wasm`) {
      throw new Error("recovery loader requested an unexpected artifact");
    }
    return this.#wasmUrl.href;
  }

  #runSnapshot() {
    const run = this.#run;
    if (run === null) return null;
    return {
      abortCount: run.abortCount,
      abortObserved: run.abortObserved,
      cleanExitObserved: run.cleanExitObserved,
      controlledAbortWindowErrorCount: run.controlledAbortWindowErrorCount,
      expectedCleanExitStatusObserved: run.expectedCleanExitStatusObserved,
      factoryRejected: run.factoryRejected,
      factoryResolved: run.factoryResolved,
      factorySettled: run.factorySettled,
      markerCount: run.markers.length,
      markerSequenceAccepted: run.markerSequenceAccepted,
      markerSource: "stderr-only-fixed-grammar",
      markers: run.markers.slice(),
      mode: run.mode,
      moduleIdentity: run.moduleIdentity,
      onExitCount: run.onExitCount,
      ordinal: run.ordinal,
      phaseCount: run.phaseCount,
      phaseObserved: run.phaseObserved,
      processExitCode: run.processExitCode,
      processExitCount: run.processExitCount,
      recoveredLevelDBValue: run.recoveredLevelDBValue,
      runtimeExitCode: run.runtimeExitCode,
      runtimeInitialized: run.runtimeInitialized,
      settleComplete: run.settleComplete,
      settleWindowMs: run.settleWindowMs,
      stdoutMarkerCount: run.stdoutMarkerCount,
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
      activeRunAtResult: this.#activeRun === null ? null : this.#activeRun.ordinal,
    };
  }

  #finalQuiescenceSnapshot() {
    return {...this.#finalQuiescence};
  }

  #tokenEvidence() {
    return {
      ...this.#bootstrap.tokenEvidence,
      rawTokenLeakDetected: this.#rawTokenLeakDetected,
      rawTokenRedactionCount: this.#rawTokenRedactionCount,
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

  #statusForRun() {
    if (this.#bootstrap.ordinal === 1) return "seeded";
    if (this.#bootstrap.ordinal === 2) return "interrupted";
    if (this.#bootstrap.ordinal === 3) return "recovered";
    return "fail";
  }

  #baseResult(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m7GateComplete: false,
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
      finalQuiescence: this.#finalQuiescenceSnapshot(),
      hostBoundary: this.#hostBoundary(),
      fatalErrors: this.#fatalErrors.slice(),
      windowErrors: this.#windowErrors.slice(),
      unhandledRejections: this.#unhandledRejections.slice(),
      failedChecks: this.#failedChecks.slice(),
      error,
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
        (secret) => typeof secret === "string" && serialized.includes(secret));
  }

  #resultValidBeforeUpload(result) {
    const run = this.#run;
    const quiescence = this.#finalQuiescence;
    if (run === null || result.status !== this.#statusForRun() ||
        result.m7GateComplete !== false || this.#fatalErrors.length !== 0 ||
        this.#rawTokenLeakDetected || !run.settleComplete ||
        this.#activeRun !== null || this.#windowErrors.length !== 0 ||
        this.#unhandledRejections.length !== 0 || run.stdoutMarkerCount !== 0 ||
        !quiescence.completed || !quiescence.quiet ||
        quiescence.callbacksAtStart !== quiescence.callbacksAtEnd ||
        quiescence.processExitReportsAtStart !==
            quiescence.processExitReportsAtEnd) {
      return false;
    }
    return run.ordinal === 2 ? this.#interruptedRunComplete(run) :
        this.#cleanRunComplete(run);
  }

  async run() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function" ||
          this.#document.navigationType !==
              expectedDocumentNavigation(this.#bootstrap.ordinal)) {
        throw new Error("recovery host precondition is invalid");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("recovery canvas focus failed");
      }
      this.#installPermanentBridge();
      this.#captureWindowErrors();
      await this.#prepareFactory();
      this.#startRun();
      const deadline = performance.now() + this.#context.timeoutMs;
      while (performance.now() < deadline && this.#fatalErrors.length === 0) {
        if (this.#run !== null && this.#run.settleComplete) break;
        await delay(10);
      }
      if (this.#run === null || !this.#run.settleComplete) {
        this.#recordFatal("recovery-host-timeout");
      }
      if (this.#fatalErrors.length !== 0) {
        return this.#baseResult("fail", "details-suppressed");
      }
      if (!this.#recheckBeforeUpload()) {
        return this.#baseResult("fail", "details-suppressed");
      }
      const result = this.#baseResult(this.#statusForRun(), null);
      if (!this.#resultValidBeforeUpload(result) || this.#containsOpaqueToken(result)) {
        if (this.#containsOpaqueToken(result)) {
          this.#rawTokenLeakDetected = true;
          this.#rawTokenRedactionCount += 1;
          this.#scrubCapturedFields();
        }
        this.#recordFatal("result-upload-validation");
        return this.#baseResult("fail", "details-suppressed");
      }
      return result;
    } catch (_error) {
      this.#recordFatal("recovery-host-exception");
      return this.#baseResult("fail", "details-suppressed");
    }
  }

  #recheckBeforeUpload() {
    const quiescence = this.#finalQuiescence;
    quiescence.bridgeRecheckedImmediatelyBeforeUpload = true;
    quiescence.callbacksAtPreUploadCheck = this.#callbackCount;
    quiescence.processExitReportsAtPreUploadCheck = this.#processExitReportCount;
    quiescence.activeRunAtPreUploadCheck = this.#activeRun === null ? null :
        this.#activeRun.ordinal;
    const clean = quiescence.completed && quiescence.quiet &&
        this.#activeRun === null &&
        quiescence.callbacksAtPreUploadCheck === quiescence.callbacksAtEnd &&
        quiescence.processExitReportsAtPreUploadCheck ===
            quiescence.processExitReportsAtEnd &&
        quiescence.activeRunAtPreUploadCheck === null &&
        this.#fatalErrors.length === 0 && !this.#rawTokenLeakDetected;
    if (!clean) this.#recordFatal("result-upload-recheck");
    return clean;
  }

  isReadyAfterResultUpload() {
    const quiescence = this.#finalQuiescence;
    return this.#fatalErrors.length === 0 && !this.#rawTokenLeakDetected &&
        this.#activeRun === null && quiescence.completed && quiescence.quiet &&
        this.#callbackCount === quiescence.callbacksAtPreUploadCheck &&
        this.#processExitReportCount ===
            quiescence.processExitReportsAtPreUploadCheck;
  }

  dispose() {
    this.#releaseWindowErrors();
    this.#releaseVerifiedLoader();
    this.#opaqueTail = "";
  }
}

function isExactProcessExitReport(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === 2 && Object.hasOwn(value, "protocol") &&
      Object.hasOwn(value, "exitCode") && value.protocol === HOST_PROTOCOL &&
      Number.isSafeInteger(value.exitCode);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("recovery page is missing its version element");
  }
  element.replaceChildren();
  for (const [name, revision] of Object.entries(versions)) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = revision;
    element.append(term, definition);
  }
}

function resultEndpoint(context, ordinal) {
  const endpoint = new URL(
      `./result/${encodeURIComponent(context.resultToken)}/${ordinal}`,
      location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("recovery result endpoint is invalid");
  }
  return endpoint;
}

function readyEndpoint(context, ordinal) {
  const endpoint = new URL(
      `./ready/${encodeURIComponent(context.resultToken)}/${ordinal}`,
      location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("recovery ready endpoint is invalid");
  }
  return endpoint;
}

async function postPhaseResult(context, result) {
  await postJson(resultEndpoint(context, result.ordinal), result,
                 "recovery result");
}

async function postReady(context, result) {
  await postJson(readyEndpoint(context, result.ordinal), {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    ordinal: result.ordinal,
    timeOrigin: result.document.timeOrigin,
  }, "recovery ready");
}

export async function runChromeWasmProfileDatabaseRecoveryFromQuery() {
  const context = parseStaticContext();
  const root = document.querySelector(
      "#m7-profile-database-recovery-root");
  const canvas = document.querySelector(
      "#m7-profile-database-recovery-canvas");
  const status = document.querySelector(
      "#m7-profile-database-recovery-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("recovery page is missing required elements");
  }
  renderVersions(document.querySelector(
      "#m7-profile-database-recovery-versions"), context.versions);
  const receipt = documentEvidence();
  await postBootstrapDocumentEvidence(context, receipt);
  const bootstrap = await fetchBootstrap(context);
  const host = new ChromeWasmProfileDatabaseRecoveryHost(
      canvas, context, bootstrap, receipt);
  let result;
  let readyPosted = false;
  try {
    result = await host.run();
    root.dataset.state = result.status;
    status.textContent = result.status === "seeded" ? "bounded recovery seed complete" :
        result.status === "interrupted" ? "bounded recovery interruption complete" :
        result.status === "recovered" ?
            "bounded LevelDB recovery receipt complete" :
        "profile database recovery probe failed; details suppressed";
    await postPhaseResult(context, result);
    if (result.status === "fail") {
      throw new Error("recovery result validation failed");
    }
    // This barrier is intentionally required for the interrupted document too:
    // it proves the bounded host-side settle completed before the runner's
    // actual Page.reload, not a page-script navigation.
    await delay(0);
    if (!host.isReadyAfterResultUpload()) {
      throw new Error("recovery host changed after result upload");
    }
    await postReady(context, result);
    readyPosted = true;
    return result;
  } finally {
    if (!readyPosted || result === undefined || result.status === "fail" ||
        result.ordinal === 3) {
      host.dispose();
    }
  }
}

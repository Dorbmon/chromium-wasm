// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Four top-level-document canonical Preferences ImportantFileWriter witness.
// The host owns immutable artifact delivery, redacted process observation, and
// the one-shot bootstrap/result protocol only.  Chromium owns Preferences,
// temporary-file flush/close, replacement, V4 failure injection, profile
// lifetime retirement, and every profile-storage read/write.  This file
// intentionally has no host profile-storage, lock, database, cookie, history,
// name, or Wasm-memory API.

const HOST_PROTOCOL = 1;
const CASE =
    "chrome_profile_preferences_important_file_writer_proxy_completion_four_outer_document_reload_m7";
const SCOPE =
    "same-origin-four-outer-documents-canonical-chrome-preferences-" +
    "important-file-writer-post-flush-v4-proxy-completion-failure-and-" +
    "fresh-document-recovery-only";
const PRODUCT_MODULE_NAME =
    "chrome_wasm_m7_profile_preferences_important_file_writer_proxy_completion_test";
const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_PREFS:";
const FAILURE_RETIREMENT_MARKER =
    "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED";
const IMPORTANT_FILE_WRITER_EIO_MARKER =
    `${M7_MARKER_PREFIX}IMPORTANT_FILE_WRITER_REPLACE_EIO_POST_FLUSH_UNPUBLISHED`;
const LEASE_REACQUIRED_MARKER = `${M7_MARKER_PREFIX}LEASE_REACQUIRED`;
const MAX_TIMEOUT_MS = 300000;
const MIN_TIMEOUT_MS = 1000;
const MAX_OUTPUT_LINES = 128;
const FINAL_QUIESCENCE_MS = 50;
const MODULE_ID_BYTES = 16;
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
  "protocol", "case", "scope", "ordinal", "mode", "faultProxyCompletion",
  "tokenA", "tokenB", "tokenADigest", "tokenBDigest",
]);
const DOCUMENT_FIELDS = Object.freeze(["navigationType", "timeOrigin"]);
const RESULT_FIELDS = Object.freeze([
  "protocol", "case", "scope", "status", "m7GateComplete", "ordinal",
  "mode", "origin", "crossOriginIsolated", "sharedArrayBuffer", "document",
  "artifact", "captureHarness", "versions", "tokenEvidence", "run", "bridge",
  "finalQuiescence", "hostBoundary", "fatalErrors", "windowErrors",
  "unhandledRejections", "failedChecks", "error",
]);
const RUN_FIELDS = Object.freeze([
  "abortObserved", "factoryRejectedExpectedExitStatus",
  "factoryRejectedUnexpected", "factoryResolved", "factorySettled",
  "failureRetirementMarkerObserved", "freshLeaseReacquiredMarkerObserved",
  "importantFileWriterEioObserved", "leaseReleasedMarkerObserved",
  "markerCount", "markerSequenceAccepted", "markerSource", "markers", "mode",
  "moduleIdentity", "onExitCount", "ordinal", "processExitCode",
  "processExitCount", "runtimeExitCode", "runtimeInitialized",
  "stdoutMarkerCount",
]);
const BRIDGE_FIELDS = Object.freeze([
  "protocol", "permanent", "frozen", "installedBeforeModuleFactory",
  "processExitDispatches", "activeRunAtResult",
]);
const FINAL_QUIESCENCE_FIELDS = Object.freeze([
  "started", "completed", "quiet", "quietWindowMs", "callbacksAtStart",
  "callbacksAtEnd", "callbacksAtPreUploadCheck", "processExitReportsAtStart",
  "processExitReportsAtEnd", "processExitReportsAtPreUploadCheck",
  "activeRunAtResult",
]);
const HOST_BOUNDARY_FIELDS = Object.freeze([
  "hostOpfsAccessAttempted", "hostWebLocksAccessAttempted", "nativeCallAttempted",
  "wasmProfileDataInspectionAttempted", "sessionStorageAccessAttempted",
  "localStorageAccessAttempted", "indexedDbAccessAttempted", "cookieAccessAttempted",
  "historyStateAccessAttempted", "windowNameAccessAttempted",
]);

function hasExactFields(value, fields) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === fields.length &&
      fields.every((field) => Object.hasOwn(value, field));
}

function requireExactFields(value, fields, description) {
  if (!hasExactFields(value, fields)) throw new Error(`${description} is invalid`);
  return value;
}

function parseJson(value, description) {
  if (typeof value !== "string" || value.length === 0 || value.length > 65536) {
    throw new Error(`${description} is invalid`);
  }
  try {
    return JSON.parse(value);
  } catch (_error) {
    throw new Error(`${description} is invalid`);
  }
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, BYTE_IDENTITY_FIELDS, description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifact(value) {
  const artifact = requireExactFields(parseJson(value, "artifact"), ARTIFACT_FIELDS,
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
    build_config: parseByteIdentity(artifact.build_config, "build config"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "loader"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "Wasm"),
  });
}

function parseCaptureHarness(value) {
  const harness = requireExactFields(parseJson(value, "capture harness"),
                                     CAPTURE_HARNESS_FIELDS, "capture harness");
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
  const versions = requireExactFields(parseJson(value, "versions"),
                                      ["chromium", "v8", "emscripten"], "versions");
  if (!Object.values(versions).every((revision) =>
    typeof revision === "string" && /^[0-9a-f]{40}$/.test(revision))) {
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
    throw new Error("proxy-completion query is invalid");
  }
  const resultToken = query.get("resultToken");
  const session = query.get("session");
  const timeoutText = query.get("timeoutMs");
  if (typeof resultToken !== "string" || !CAPABILITY_RE.test(resultToken) ||
      typeof session !== "string" || !CAPABILITY_RE.test(session) ||
      resultToken === session || query.get("module") !== PRODUCT_MODULE_NAME ||
      typeof timeoutText !== "string" || !/^[0-9]+$/.test(timeoutText)) {
    throw new Error("proxy-completion query is invalid");
  }
  const timeoutMs = Number(timeoutText);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("proxy-completion timeout is invalid");
  }
  return Object.freeze({
    artifact: parseArtifact(query.get("artifact")),
    captureHarness: parseCaptureHarness(query.get("captureHarness")),
    moduleName: PRODUCT_MODULE_NAME,
    resultToken,
    session,
    timeoutMs,
    versions: parseVersions(query.get("versions")),
  });
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function hex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function randomHex(byteLength, description) {
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 || !globalThis.crypto ||
      typeof globalThis.crypto.getRandomValues !== "function") {
    throw new Error(`${description} random source is unavailable`);
  }
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  return hex(bytes);
}

async function sha256Hex(bytes, description) {
  if (!(bytes instanceof Uint8Array) || !globalThis.crypto || !globalThis.crypto.subtle ||
      typeof globalThis.crypto.subtle.digest !== "function") {
    throw new Error(`${description} hash support is unavailable`);
  }
  try {
    return hex(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes)));
  } catch (_error) {
    throw new Error(`${description} hash failed`);
  }
}

function expectedHeaders(response, contentType, description) {
  if (!response || !response.ok ||
      response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
          contentType ||
      response.headers.get("cache-control") !== "no-store" ||
      response.headers.get("cross-origin-embedder-policy") !== "require-corp" ||
      response.headers.get("cross-origin-opener-policy") !== "same-origin" ||
      response.headers.get("cross-origin-resource-policy") !== "same-origin" ||
      response.headers.get("referrer-policy") !== "no-referrer" ||
      response.headers.get("x-content-type-options") !== "nosniff") {
    throw new Error(`${description} response is invalid`);
  }
}

async function fetchVerifiedArtifact(url, identity, contentType, description) {
  const response = await fetch(url, {
    cache: "no-store", credentials: "same-origin", redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (response.url !== url.href) throw new Error(`${description} response is invalid`);
  expectedHeaders(response, contentType, description);
  let bytes;
  try {
    bytes = new Uint8Array(await response.arrayBuffer());
  } catch (_error) {
    throw new Error(`${description} bytes are invalid`);
  }
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} differs from its immutable snapshot`);
  }
  return bytes;
}

function modeForOrdinal(ordinal) {
  if (ordinal === 1) return "write";
  if (ordinal === 2 || ordinal === 3) return "verify-and-write";
  if (ordinal === 4) return "verify-b";
  throw new Error("proxy-completion bootstrap ordinal is invalid");
}

function navigationForOrdinal(ordinal) {
  return ordinal === 1 ? "navigate" : "reload";
}

function statusForOrdinal(ordinal) {
  if (ordinal === 1) return "seeded";
  if (ordinal === 2) return "replacement-failed";
  if (ordinal === 3) return "recovered";
  if (ordinal === 4) return "verified";
  throw new Error("proxy-completion bootstrap ordinal is invalid");
}

function exactNonzeroExitStatus(value) {
  try {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const keys = Reflect.ownKeys(descriptors);
    const fields = ["name", "status", "message"];
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
    return Number.isSafeInteger(status) && status > 0 && status <= 255 &&
        descriptors.name.value === "ExitStatus" &&
        descriptors.message.value === `Program terminated with exit(${status})` ? status : null;
  } catch (_error) {
    return null;
  }
}

function documentEvidence() {
  const navigation = performance.getEntriesByType("navigation")[0];
  const navigationType = navigation && typeof navigation === "object" &&
      typeof navigation.type === "string" ? navigation.type : null;
  const timeOrigin = performance.timeOrigin;
  if ((navigationType !== "navigate" && navigationType !== "reload") ||
      typeof timeOrigin !== "number" || !Number.isFinite(timeOrigin) ||
      timeOrigin <= 0) {
    throw new Error("proxy-completion document evidence is invalid");
  }
  return Object.freeze({navigationType, timeOrigin});
}

async function postJson(endpoint, payload, description) {
  if (!(endpoint instanceof URL) || endpoint.origin !== location.origin) {
    throw new Error(`${description} endpoint is invalid`);
  }
  const response = await fetch(endpoint, {
    method: "POST", cache: "no-store", credentials: "same-origin", redirect: "error",
    referrerPolicy: "no-referrer", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response || response.status !== 204 || response.url !== endpoint.href ||
      response.headers.get("cache-control") !== "no-store" ||
      response.headers.get("cross-origin-embedder-policy") !== "require-corp" ||
      response.headers.get("cross-origin-opener-policy") !== "same-origin" ||
      response.headers.get("cross-origin-resource-policy") !== "same-origin" ||
      response.headers.get("referrer-policy") !== "no-referrer" ||
      response.headers.get("x-content-type-options") !== "nosniff") {
    throw new Error(`${description} acknowledgement is invalid`);
  }
}

function bootstrapEndpoint(context) {
  const endpoint = new URL(`./bootstrap/${encodeURIComponent(context.session)}`,
                           location.href);
  if (endpoint.origin !== location.origin) throw new Error("bootstrap endpoint is invalid");
  return endpoint;
}

function resultEndpoint(context, ordinal) {
  const endpoint = new URL(
      `./result/${encodeURIComponent(context.resultToken)}/${ordinal}`, location.href);
  if (endpoint.origin !== location.origin) throw new Error("result endpoint is invalid");
  return endpoint;
}

function readyEndpoint(context, ordinal) {
  const endpoint = new URL(
      `./ready/${encodeURIComponent(context.resultToken)}/${ordinal}`, location.href);
  if (endpoint.origin !== location.origin) throw new Error("ready endpoint is invalid");
  return endpoint;
}

async function postBootstrapDocumentEvidence(context, receipt) {
  const document = requireExactFields(receipt, DOCUMENT_FIELDS, "document evidence");
  await postJson(bootstrapEndpoint(context), {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    navigationType: document.navigationType,
    timeOrigin: document.timeOrigin,
  }, "document evidence");
}

async function parseBootstrap(value) {
  const bootstrap = requireExactFields(value, BOOTSTRAP_FIELDS, "bootstrap");
  const ordinal = bootstrap.ordinal;
  if (!Number.isSafeInteger(ordinal) || ordinal < 1 || ordinal > 4 ||
      bootstrap.protocol !== HOST_PROTOCOL || bootstrap.case !== CASE ||
      bootstrap.scope !== SCOPE || bootstrap.mode !== modeForOrdinal(ordinal) ||
      typeof bootstrap.faultProxyCompletion !== "boolean" ||
      bootstrap.faultProxyCompletion !== (ordinal === 2)) {
    throw new Error("bootstrap is invalid");
  }
  const expectsA = ordinal !== 4;
  const expectsB = ordinal !== 1;
  if ((expectsA && (typeof bootstrap.tokenA !== "string" ||
                    !SHA256_RE.test(bootstrap.tokenA) ||
                    typeof bootstrap.tokenADigest !== "string" ||
                    !SHA256_RE.test(bootstrap.tokenADigest))) ||
      (!expectsA && (bootstrap.tokenA !== null || bootstrap.tokenADigest !== null)) ||
      (expectsB && (typeof bootstrap.tokenB !== "string" ||
                    !SHA256_RE.test(bootstrap.tokenB) ||
                    typeof bootstrap.tokenBDigest !== "string" ||
                    !SHA256_RE.test(bootstrap.tokenBDigest))) ||
      (!expectsB && (bootstrap.tokenB !== null || bootstrap.tokenBDigest !== null)) ||
      (expectsA && expectsB && bootstrap.tokenA === bootstrap.tokenB)) {
    throw new Error("bootstrap token shape is invalid");
  }
  const digestA = expectsA ? await sha256Hex(
      new TextEncoder().encode(bootstrap.tokenA), "token A") : null;
  const digestB = expectsB ? await sha256Hex(
      new TextEncoder().encode(bootstrap.tokenB), "token B") : null;
  if ((expectsA && digestA !== bootstrap.tokenADigest) ||
      (expectsB && digestB !== bootstrap.tokenBDigest)) {
    throw new Error("bootstrap token identity is invalid");
  }
  return Object.freeze({
    ordinal,
    mode: bootstrap.mode,
    faultProxyCompletion: bootstrap.faultProxyCompletion,
    rawTokens: Object.freeze({tokenA: bootstrap.tokenA, tokenB: bootstrap.tokenB}),
    tokenEvidence: Object.freeze({
      algorithm: "SHA-256",
      tokenA: digestA,
      tokenB: digestB,
      distinct: ordinal === 2 || ordinal === 3,
      rawTokensExcluded: true,
    }),
  });
}

async function fetchBootstrap(context) {
  const endpoint = bootstrapEndpoint(context);
  const response = await fetch(endpoint, {
    cache: "no-store", credentials: "same-origin", redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response || !response.ok || response.url !== endpoint.href) {
    throw new Error("bootstrap request failed");
  }
  expectedHeaders(response, "application/json", "bootstrap");
  try {
    return await parseBootstrap(await response.json());
  } catch (error) {
    if (error instanceof Error) throw error;
    throw new Error("bootstrap body is invalid");
  }
}

function expectedMarkers(bootstrap) {
  const a = bootstrap.tokenEvidence.tokenA;
  const b = bootstrap.tokenEvidence.tokenB;
  if (bootstrap.ordinal === 1) {
    return [
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}WRITE_ACCEPTED sha256=${a}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${a}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ];
  }
  if (bootstrap.ordinal === 2) {
    return [
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}READ_A_OK sha256=${a}`,
      IMPORTANT_FILE_WRITER_EIO_MARKER,
      `${M7_MARKER_PREFIX}FAIL stage=fence`,
    ];
  }
  if (bootstrap.ordinal === 3) {
    return [
      `${M7_MARKER_PREFIX}READY`, LEASE_REACQUIRED_MARKER,
      `${M7_MARKER_PREFIX}READ_A_OK sha256=${a}`,
      `${M7_MARKER_PREFIX}WRITE_ACCEPTED sha256=${b}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${b}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ];
  }
  return [
    `${M7_MARKER_PREFIX}READY`,
    `${M7_MARKER_PREFIX}READ_B_OK sha256=${b}`,
    `${M7_MARKER_PREFIX}FENCE_OK sha256=${b}`,
    `${M7_MARKER_PREFIX}LEASE_RELEASED`,
  ];
}

class PreferencesImportantFileWriterProxyCompletionHost {
  #activeRun = false;
  #artifact;
  #bridgeInstalled = false;
  #bridgeInstalledBeforeModuleFactory = false;
  #bridgeProcessExitDispatches = 0;
  #callbackCount = 0;
  #canvas;
  #captureHarness;
  #context;
  #document;
  #factory = null;
  #factoryExitStatusCode = null;
  #factoryModule = null;
  #failure = false;
  #fatalErrors = [];
  #finalQuiescence = {
    started: false,
    completed: false,
    quiet: false,
    quietWindowMs: FINAL_QUIESCENCE_MS,
    callbacksAtStart: null,
    callbacksAtEnd: null,
    callbacksAtPreUploadCheck: null,
    processExitReportsAtStart: null,
    processExitReportsAtEnd: null,
    processExitReportsAtPreUploadCheck: null,
    activeRunAtResult: null,
  };
  #loaderImportUrl = null;
  #mainScriptUrlOrBlob = null;
  #moduleStarted = false;
  #rawTokenLeakDetected = false;
  #rawTokenRedactionCount = 0;
  #rawTokenTail = "";
  #runtimeModule = null;
  #run;
  #status;
  #unhandledRejectionCount = 0;
  #unhandledRejectionHandler;
  #versions;
  #wasmBinary = null;
  #wasmUrl = null;
  #windowErrorCount = 0;
  #windowErrorHandler;

  constructor(canvas, status, context, bootstrap, documentReceipt) {
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement) ||
        !documentReceipt || documentReceipt.navigationType !==
            navigationForOrdinal(bootstrap.ordinal)) {
      throw new Error("proxy-completion host construction is invalid");
    }
    this.#artifact = context.artifact;
    this.#canvas = canvas;
    this.#captureHarness = context.captureHarness;
    this.#context = context;
    this.#document = documentReceipt;
    this.#status = status;
    this.#versions = context.versions;
    this.#run = {
      abortObserved: false,
      factoryRejectedExpectedExitStatus: false,
      factoryRejectedUnexpected: false,
      factoryResolved: false,
      factorySettled: false,
      failureRetirementMarkerObserved: false,
      freshLeaseReacquiredMarkerObserved: false,
      importantFileWriterEioObserved: false,
      leaseReleasedMarkerObserved: false,
      markerCount: 0,
      markerSequenceAccepted: true,
      markers: [],
      mode: bootstrap.mode,
      moduleIdentity: null,
      onExitCount: 0,
      ordinal: bootstrap.ordinal,
      outputLineCount: 0,
      processExitCode: null,
      processExitCount: 0,
      runtimeExitCode: null,
      runtimeInitialized: false,
      stdoutMarkerCount: 0,
    };
    this.#bootstrap = bootstrap;
  }

  #bootstrap;

  #markFailure(fixed = "host") {
    this.#failure = true;
    if (this.#fatalErrors.length < 16 && typeof fixed === "string" &&
        /^[a-z0-9-]+$/.test(fixed)) {
      this.#fatalErrors.push(fixed);
    }
  }

  #noteCallback() {
    this.#callbackCount += 1;
  }

  #observeOpaqueText(value, acrossCallbacks = false) {
    if (typeof value !== "string") return;
    const candidate = acrossCallbacks ? this.#rawTokenTail + value : value;
    const raw = this.#bootstrap.rawTokens;
    if ((typeof raw.tokenA === "string" && candidate.includes(raw.tokenA)) ||
        (typeof raw.tokenB === "string" && candidate.includes(raw.tokenB))) {
      this.#rawTokenLeakDetected = true;
      this.#rawTokenRedactionCount += 1;
      this.#markFailure("opaque-token-leak");
    }
    if (acrossCallbacks) this.#rawTokenTail = candidate.slice(-63);
  }

  #captureExternalFailures() {
    this.#windowErrorHandler = (event) => {
      this.#noteCallback();
      this.#windowErrorCount += 1;
      this.#observeOpaqueText(typeof event.message === "string" ? event.message : "", true);
      this.#markFailure("window-error");
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#noteCallback();
      this.#unhandledRejectionCount += 1;
      let reason = null;
      try {
        reason = event.reason;
      } catch (_error) {
        // The result remains redacted even when a hostile reason is unreadable.
      }
      this.#observeOpaqueText(typeof reason === "string" ? reason : "", true);
      this.#markFailure("unhandled-rejection");
    };
    addEventListener("error", this.#windowErrorHandler);
    addEventListener("unhandledrejection", this.#unhandledRejectionHandler);
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("proxy-completion bridge already exists");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.#noteCallback();
        host.#observeOpaqueText(typeof message === "string" ? message : "", true);
        host.#markFailure("native-fatal");
      },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(_report) { host.#noteCallback(); },
      reportReadiness(_report) { host.#noteCallback(); },
      reportOzoneFocusState(_report) { host.#noteCallback(); },
      reportOzoneCursor(_report) { host.#noteCallback(); return true; },
      reportOzoneTextInputState(_report) { host.#noteCallback(); },
      reportOzoneTextInputDelivery(_report) { host.#noteCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) { host.#noteCallback(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) { host.#noteCallback(); },
      requestOuterOriginStorageEstimate(_report) { host.#noteCallback(); return false; },
      reportAccessibilitySnapshot(_report) { host.#noteCallback(); return false; },
    });
    Object.defineProperty(globalThis, "__chromiumWasmHostBridgeV1", {
      configurable: false, enumerable: false, value: bridge, writable: false,
    });
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge || !Object.isFrozen(bridge)) {
      throw new Error("proxy-completion bridge is mutable");
    }
    this.#bridgeInstalled = true;
  }

  #releaseResources() {
    if (this.#windowErrorHandler !== undefined) {
      removeEventListener("error", this.#windowErrorHandler);
      this.#windowErrorHandler = undefined;
    }
    if (this.#unhandledRejectionHandler !== undefined) {
      removeEventListener("unhandledrejection", this.#unhandledRejectionHandler);
      this.#unhandledRejectionHandler = undefined;
    }
    if (this.#loaderImportUrl !== null) {
      URL.revokeObjectURL(this.#loaderImportUrl);
      this.#loaderImportUrl = null;
    }
  }

  #expectedExitCode(code) {
    return this.#run.ordinal === 2 ?
        Number.isSafeInteger(code) && code > 0 && code <= 255 : code === 0;
  }

  #reportProcessExit(report) {
    this.#noteCallback();
    if (!this.#moduleStarted || this.#run.processExitCount !== 0 ||
        this.#run.onExitCount !== 0 || !hasExactFields(report, ["protocol", "exitCode"]) ||
        report.protocol !== HOST_PROTOCOL || !this.#expectedExitCode(report.exitCode)) {
      this.#markFailure("process-exit");
      return;
    }
    this.#run.processExitCount = 1;
    this.#run.processExitCode = report.exitCode;
    this.#bridgeProcessExitDispatches += 1;
    this.#maybeComplete();
  }

  #reportRuntimeInitialized(module) {
    this.#noteCallback();
    if (this.#run.runtimeInitialized || !module ||
        (typeof module !== "object" && typeof module !== "function") ||
        (this.#factoryModule !== null && this.#factoryModule !== module)) {
      this.#markFailure("runtime-initialized");
      return;
    }
    this.#runtimeModule = module;
    this.#run.runtimeInitialized = true;
    this.#maybeComplete();
  }

  #reportRuntimeExit(code) {
    this.#noteCallback();
    if (!this.#expectedExitCode(code) || this.#run.onExitCount !== 0 ||
        this.#run.processExitCount !== 1 || this.#run.processExitCode !== code) {
      this.#markFailure("runtime-exit");
      return;
    }
    this.#run.onExitCount = 1;
    this.#run.runtimeExitCode = code;
    this.#maybeComplete();
  }

  #reportAbort(reason) {
    this.#noteCallback();
    this.#observeOpaqueText(typeof reason === "string" ? reason : "", true);
    this.#run.abortObserved = true;
    // The V4 receipt exercises fail-closed retirement, not an abort path.
    this.#markFailure("abort");
  }

  #captureOutput(destination, line) {
    this.#noteCallback();
    this.#run.outputLineCount += 1;
    if (this.#run.outputLineCount > MAX_OUTPUT_LINES || typeof line !== "string") {
      this.#markFailure("output-shape");
      return;
    }
    this.#observeOpaqueText(line, true);
    const isPreferencesMarker = line.startsWith(M7_MARKER_PREFIX);
    const isRetirementMarker = line === FAILURE_RETIREMENT_MARKER;
    if ((isPreferencesMarker || isRetirementMarker) && destination !== "stderr") {
      this.#run.stdoutMarkerCount += 1;
      this.#markFailure("native-marker-stdout");
      return;
    }
    if (isRetirementMarker) {
      if (this.#run.ordinal !== 2 || this.#run.failureRetirementMarkerObserved ||
          this.#run.markers.length !== expectedMarkers(this.#bootstrap).length) {
        this.#markFailure("retirement-marker");
        return;
      }
      this.#run.failureRetirementMarkerObserved = true;
      this.#maybeComplete();
      return;
    }
    if (!isPreferencesMarker) return;
    const expected = expectedMarkers(this.#bootstrap);
    const index = this.#run.markers.length;
    if (index >= expected.length || line !== expected[index]) {
      this.#run.markerSequenceAccepted = false;
      if (line === `${M7_MARKER_PREFIX}LEASE_RELEASED`) {
        this.#run.leaseReleasedMarkerObserved = true;
      }
      this.#markFailure("preferences-marker");
      return;
    }
    this.#run.markers.push(line);
    this.#run.markerCount = this.#run.markers.length;
    if (line === `${M7_MARKER_PREFIX}LEASE_RELEASED`) {
      this.#run.leaseReleasedMarkerObserved = true;
    }
    if (line === IMPORTANT_FILE_WRITER_EIO_MARKER) {
      this.#run.importantFileWriterEioObserved = true;
    }
    if (line === LEASE_REACQUIRED_MARKER) {
      this.#run.freshLeaseReacquiredMarkerObserved = true;
    }
    this.#maybeComplete();
  }

  #factoryResolved(module) {
    this.#noteCallback();
    if (this.#run.factorySettled || !module ||
        (typeof module !== "object" && typeof module !== "function") ||
        (this.#runtimeModule !== null && this.#runtimeModule !== module)) {
      this.#markFailure("factory-resolved");
      return;
    }
    this.#factoryModule = module;
    this.#run.factorySettled = true;
    this.#run.factoryResolved = true;
    this.#maybeComplete();
  }

  #factoryRejected(reason) {
    this.#noteCallback();
    if (this.#run.factorySettled) {
      this.#markFailure("factory-double-settle");
      return;
    }
    const exitCode = exactNonzeroExitStatus(reason);
    this.#run.factorySettled = true;
    if (this.#run.ordinal !== 2 || exitCode === null) {
      this.#run.factoryRejectedUnexpected = true;
      this.#observeOpaqueText(typeof reason === "string" ? reason : "", true);
      this.#markFailure("factory-rejected");
      return;
    }
    this.#factoryExitStatusCode = exitCode;
    this.#run.factoryRejectedExpectedExitStatus = true;
    this.#maybeComplete();
  }

  #markerReceiptComplete() {
    const expected = expectedMarkers(this.#bootstrap);
    const normal = this.#run.ordinal !== 2;
    return this.#run.markerSequenceAccepted &&
        this.#run.markers.length === expected.length &&
        this.#run.markers.every((marker, index) => marker === expected[index]) &&
        this.#run.leaseReleasedMarkerObserved === normal &&
        this.#run.importantFileWriterEioObserved === !normal &&
        this.#run.failureRetirementMarkerObserved === !normal &&
        this.#run.freshLeaseReacquiredMarkerObserved === (this.#run.ordinal === 3);
  }

  #lifecycleReceiptComplete() {
    const failureDocument = this.#run.ordinal === 2;
    const factoryAccepted = failureDocument ?
        (this.#run.factoryResolved ||
         (this.#run.factoryRejectedExpectedExitStatus &&
          this.#factoryExitStatusCode === this.#run.processExitCode)) :
        this.#run.factoryResolved && !this.#run.factoryRejectedExpectedExitStatus;
    return !this.#failure && this.#activeRun && this.#run.runtimeInitialized &&
        this.#run.factorySettled && factoryAccepted &&
        !this.#run.factoryRejectedUnexpected && !this.#run.abortObserved &&
        this.#run.processExitCount === 1 && this.#expectedExitCode(this.#run.processExitCode) &&
        this.#run.onExitCount === 1 &&
        this.#run.runtimeExitCode === this.#run.processExitCode &&
        this.#markerReceiptComplete() && this.#run.stdoutMarkerCount === 0 &&
        this.#windowErrorCount === 0 && this.#unhandledRejectionCount === 0 &&
        !this.#rawTokenLeakDetected;
  }

  #maybeComplete() {
    if (this.#finalQuiescence.started || !this.#lifecycleReceiptComplete()) return;
    this.#startFinalQuiescence();
  }

  #startFinalQuiescence() {
    this.#finalQuiescence.started = true;
    this.#finalQuiescence.callbacksAtStart = this.#callbackCount;
    this.#finalQuiescence.processExitReportsAtStart = this.#bridgeProcessExitDispatches;
    setTimeout(() => {
      this.#finalQuiescence.callbacksAtEnd = this.#callbackCount;
      this.#finalQuiescence.processExitReportsAtEnd = this.#bridgeProcessExitDispatches;
      this.#finalQuiescence.quiet = !this.#failure &&
          this.#finalQuiescence.callbacksAtStart ===
              this.#finalQuiescence.callbacksAtEnd &&
          this.#finalQuiescence.processExitReportsAtStart ===
              this.#finalQuiescence.processExitReportsAtEnd &&
          this.#lifecycleReceiptComplete();
      this.#finalQuiescence.completed = true;
      if (!this.#finalQuiescence.quiet) {
        this.#markFailure("final-quiescence");
        return;
      }
      this.#activeRun = false;
    }, FINAL_QUIESCENCE_MS);
  }

  async #prepareFactory() {
    const loaderUrl = new URL(`./artifacts/${this.#context.moduleName}.js`, location.href);
    const wasmUrl = new URL(`./artifacts/${this.#context.moduleName}.wasm`, location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("artifact origin is invalid");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(loaderUrl, this.#artifact.loader, "text/javascript", "loader"),
      fetchVerifiedArtifact(wasmUrl, this.#artifact.wasm, "application/wasm", "Wasm"),
    ]);
    if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("verified loader import is unavailable");
    }
    this.#loaderImportUrl = URL.createObjectURL(
        new Blob([loaderBytes], {type: "text/javascript"}));
    const namespace = await import(this.#loaderImportUrl);
    if (typeof namespace.default !== "function") {
      throw new Error("loader factory is invalid");
    }
    this.#factory = namespace.default;
    this.#mainScriptUrlOrBlob = this.#loaderImportUrl;
    this.#wasmBinary = wasmBytes;
    this.#wasmUrl = wasmUrl;
  }

  #moduleArguments() {
    const raw = this.#bootstrap.rawTokens;
    const args = [`--wasm-profile-preferences-smoke=${this.#bootstrap.mode}`];
    if (typeof raw.tokenA === "string") {
      args.push(`--wasm-profile-preferences-token-a=${raw.tokenA}`);
    }
    if (typeof raw.tokenB === "string") {
      args.push(`--wasm-profile-preferences-token-b=${raw.tokenB}`);
    }
    if (this.#bootstrap.faultProxyCompletion) {
      args.push("--wasm-profile-preferences-important-file-writer-proxy-completion");
    }
    return args;
  }

  #locateFile(path) {
    if (typeof path !== "string" || path !== `${this.#context.moduleName}.wasm`) {
      throw new Error("loader requested an unexpected artifact");
    }
    return this.#wasmUrl.href;
  }

  #startModule() {
    if (this.#factory === null || this.#wasmBinary === null || this.#wasmUrl === null ||
        this.#run.moduleIdentity !== null || this.#activeRun) {
      throw new Error("module start is invalid");
    }
    this.#run.moduleIdentity = randomHex(MODULE_ID_BYTES, "module identity");
    this.#bridgeInstalledBeforeModuleFactory = this.#bridgeInstalled;
    this.#moduleStarted = true;
    this.#activeRun = true;
    const host = this;
    let result;
    try {
      result = this.#factory({
        arguments: this.#moduleArguments(),
        canvas: this.#canvas,
        locateFile(path) { return host.#locateFile(path); },
        mainScriptUrlOrBlob: this.#mainScriptUrlOrBlob,
        noExitRuntime: false,
        onAbort(reason) { host.#reportAbort(reason); },
        onExit(code) { host.#reportRuntimeExit(code); },
        onRuntimeInitialized() { host.#reportRuntimeInitialized(this); },
        print(line) { host.#captureOutput("stdout", line); },
        printErr(line) { host.#captureOutput("stderr", line); },
        wasmBinary: this.#wasmBinary,
      });
    } catch (error) {
      this.#factoryRejected(error);
      return;
    }
    Promise.resolve(result).then(
        (module) => host.#factoryResolved(module),
        (error) => host.#factoryRejected(error));
  }

  #runSnapshot() {
    const run = this.#run;
    return {
      abortObserved: run.abortObserved,
      factoryRejectedExpectedExitStatus: run.factoryRejectedExpectedExitStatus,
      factoryRejectedUnexpected: run.factoryRejectedUnexpected,
      factoryResolved: run.factoryResolved,
      factorySettled: run.factorySettled,
      failureRetirementMarkerObserved: run.failureRetirementMarkerObserved,
      freshLeaseReacquiredMarkerObserved: run.freshLeaseReacquiredMarkerObserved,
      importantFileWriterEioObserved: run.importantFileWriterEioObserved,
      leaseReleasedMarkerObserved: run.leaseReleasedMarkerObserved,
      markerCount: run.markerCount,
      markerSequenceAccepted: run.markerSequenceAccepted,
      markerSource: "stderr-only-fixed-grammar",
      markers: run.markers.slice(),
      mode: run.mode,
      moduleIdentity: run.moduleIdentity,
      onExitCount: run.onExitCount,
      ordinal: run.ordinal,
      processExitCode: run.processExitCode,
      processExitCount: run.processExitCount,
      runtimeExitCode: run.runtimeExitCode,
      runtimeInitialized: run.runtimeInitialized,
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
      activeRunAtResult: this.#activeRun ? this.#run.ordinal : null,
    };
  }

  #finalQuiescenceSnapshot() {
    return {...this.#finalQuiescence, activeRunAtResult: this.#activeRun ?
      this.#run.ordinal : null};
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
      wasmProfileDataInspectionAttempted: false,
      sessionStorageAccessAttempted: false,
      localStorageAccessAttempted: false,
      indexedDbAccessAttempted: false,
      cookieAccessAttempted: false,
      historyStateAccessAttempted: false,
      windowNameAccessAttempted: false,
    };
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
      captureHarness: this.#captureHarness,
      versions: this.#versions,
      tokenEvidence: this.#tokenEvidence(),
      run: this.#runSnapshot(),
      bridge: this.#bridgeSnapshot(),
      finalQuiescence: this.#finalQuiescenceSnapshot(),
      hostBoundary: this.#hostBoundary(),
      fatalErrors: this.#fatalErrors.slice(),
      windowErrors: [],
      unhandledRejections: [],
      failedChecks: [],
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
    const raw = this.#bootstrap.rawTokens;
    return typeof serialized !== "string" ||
        (typeof raw.tokenA === "string" && serialized.includes(raw.tokenA)) ||
        (typeof raw.tokenB === "string" && serialized.includes(raw.tokenB));
  }

  #factoryLifecycleAccepted() {
    if (this.#run.ordinal !== 2) {
      return this.#run.factoryResolved && !this.#run.factoryRejectedExpectedExitStatus;
    }
    return this.#run.factoryResolved ||
        (this.#run.factoryRejectedExpectedExitStatus &&
         this.#factoryExitStatusCode === this.#run.processExitCode);
  }

  #completedSuccessfully() {
    return !this.#failure && !this.#activeRun &&
        this.#finalQuiescence.completed && this.#finalQuiescence.quiet &&
        this.#run.runtimeInitialized && this.#run.factorySettled &&
        this.#factoryLifecycleAccepted() && !this.#run.factoryRejectedUnexpected &&
        !this.#run.abortObserved && this.#run.processExitCount === 1 &&
        this.#expectedExitCode(this.#run.processExitCode) && this.#run.onExitCount === 1 &&
        this.#run.runtimeExitCode === this.#run.processExitCode &&
        this.#markerReceiptComplete() && this.#run.stdoutMarkerCount === 0 &&
        this.#windowErrorCount === 0 && this.#unhandledRejectionCount === 0 &&
        !this.#rawTokenLeakDetected && this.#fatalErrors.length === 0;
  }

  async run() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function" || location.origin === "null") {
        throw new Error("host context is invalid");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("canvas focus failed");
      }
      this.#captureExternalFailures();
      this.#installBridge();
      await this.#prepareFactory();
      this.#startModule();
      const deadline = performance.now() + this.#context.timeoutMs;
      while (performance.now() < deadline && !this.#failure &&
             !this.#finalQuiescence.completed) {
        await delay(10);
      }
      if (!this.#completedSuccessfully()) {
        this.#markFailure("lifecycle-incomplete");
      }
    } catch (_error) {
      this.#markFailure("host-exception");
    }
    const result = this.#baseResult(
        this.#completedSuccessfully() ? statusForOrdinal(this.#bootstrap.ordinal) : "fail",
        this.#completedSuccessfully() ? null : "details-suppressed");
    if (this.#containsOpaqueToken(result)) {
      this.#rawTokenLeakDetected = true;
      this.#rawTokenRedactionCount += 1;
      this.#markFailure("result-opaque-token");
      return this.#baseResult("fail", "details-suppressed");
    }
    return result;
  }

  recheckBeforeResultUpload(result) {
    this.#finalQuiescence.callbacksAtPreUploadCheck = this.#callbackCount;
    this.#finalQuiescence.processExitReportsAtPreUploadCheck =
        this.#bridgeProcessExitDispatches;
    this.#finalQuiescence.activeRunAtResult = this.#activeRun ? this.#run.ordinal : null;
    const clean = result && result.status === statusForOrdinal(this.#bootstrap.ordinal) &&
        this.#completedSuccessfully() &&
        this.#finalQuiescence.callbacksAtPreUploadCheck ===
            this.#finalQuiescence.callbacksAtEnd &&
        this.#finalQuiescence.processExitReportsAtPreUploadCheck ===
            this.#finalQuiescence.processExitReportsAtEnd &&
        this.#finalQuiescence.activeRunAtResult === null;
    if (!clean) this.#markFailure("result-upload-recheck");
    const finalResult = this.#baseResult(clean ? statusForOrdinal(this.#bootstrap.ordinal) :
        "fail", clean ? null : "details-suppressed");
    if (this.#containsOpaqueToken(finalResult)) {
      this.#rawTokenLeakDetected = true;
      this.#rawTokenRedactionCount += 1;
      this.#markFailure("result-opaque-token");
      return this.#baseResult("fail", "details-suppressed");
    }
    return finalResult;
  }

  readyAfterResultUpload() {
    return this.#completedSuccessfully() &&
        this.#finalQuiescence.callbacksAtPreUploadCheck === this.#callbackCount &&
        this.#finalQuiescence.processExitReportsAtPreUploadCheck ===
            this.#bridgeProcessExitDispatches && !this.#activeRun;
  }

  dispose() {
    this.#releaseResources();
    this.#rawTokenTail = "";
  }
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) throw new Error("version element is missing");
  element.replaceChildren();
  for (const [name, revision] of Object.entries(versions)) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = revision;
    element.append(term, definition);
  }
}

export async function runChromeWasmProfilePreferencesImportantFileWriterProxyCompletionFromQuery() {
  let host = null;
  let result;
  try {
    const context = parseContext();
    const root = document.querySelector(
        "#m7-profile-preferences-important-file-writer-proxy-completion-root");
    const canvas = document.querySelector(
        "#m7-profile-preferences-important-file-writer-proxy-completion-canvas");
    const status = document.querySelector(
        "#m7-profile-preferences-important-file-writer-proxy-completion-status");
    const versions = document.querySelector(
        "#m7-profile-preferences-important-file-writer-proxy-completion-versions");
    if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
        !(status instanceof HTMLElement) || !(versions instanceof HTMLElement)) {
      throw new Error("proxy-completion page is missing required elements");
    }
    renderVersions(versions, context.versions);
    const receipt = documentEvidence();
    await postBootstrapDocumentEvidence(context, receipt);
    const bootstrap = await fetchBootstrap(context);
    host = new PreferencesImportantFileWriterProxyCompletionHost(
        canvas, status, context, bootstrap, receipt);
    result = await host.run();
    result = host.recheckBeforeResultUpload(result);
    root.dataset.state = result.status;
    status.textContent = result.status === "fail" ?
        "proxy-completion witness failed; details suppressed" :
        `proxy-completion document ${result.ordinal} complete`;
    await postJson(resultEndpoint(context, result.ordinal), result, "result");
    if (result.status === "fail") {
      throw new Error("proxy-completion result validation failed");
    }
    // The runner cannot arm/reload until this turn has observed that the
    // result upload itself did not awaken a callback or a late process-exit.
    await delay(0);
    if (!host.readyAfterResultUpload()) {
      throw new Error("proxy-completion host changed after result upload");
    }
    await postJson(readyEndpoint(context, result.ordinal), {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      ordinal: result.ordinal,
      timeOrigin: result.document.timeOrigin,
    }, "ready receipt");
    return result;
  } finally {
    if (host !== null) host.dispose();
  }
}

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Same-document two-factory profile Preferences acceptance. The page is a
// lifecycle coordinator only: Chromium owns the profile, the registered test
// preference, durable writes, the scoped backend drain, and the profile lease.
// In particular this host has no filesystem, lock, native-call, or Wasm-memory
// inspection authority. It passes two private opaque command-line values to
// Chromium and retains only their SHA-256 digests for redacted evidence.

const HOST_PROTOCOL = 1;
const CASE = "chrome_profile_preferences_two_fresh_modules_m7";
const SCOPE =
    "same-origin-same-document-two-fresh-chrome-wasm-m7-profile-preferences-test-modules-preferences-only";
const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_preferences_test";
const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_PREFS:";
const MAX_TIMEOUT_MS = 120000;
const MAX_OUTPUT_LINES = 128;
const MAX_ERROR_RECORDS = 32;
const MODULE_ID_BYTES = 16;
const TOKEN_BYTES = 32;
const FINAL_QUIESCENCE_MS = 50;
const MAX_FAILURE_CALLBACK_COUNT = 255;
const MAX_FAILURE_PROCESS_EXIT_REPORT_COUNT = 3;
const MAX_FAILURE_EXIT_CODE = 255;
const SHA256_RE = /^[0-9a-f]{64}$/;
const MODULE_ID_RE = /^[0-9a-f]{32}$/;
const OPAQUE_RESULT_TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
const EXPECTED_NORMAL_EXIT_STATUS_FIELDS = Object.freeze([
  "name",
  "status",
  "message",
]);
const EXPECTED_NORMAL_EXIT_STATUS_VALUES = Object.freeze({
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
});

const FAILURE_CLASSES = Object.freeze([
  "host-exception",
  "host-lifecycle",
  "host-window-error",
  "host-unhandled-rejection",
  "host-timeout",
  "opaque-token-leak",
  "native-fixed-failure",
  "host-result-validation",
]);
// Failure diagnostics export only the first fixed host lifecycle site. These
// identifiers are deliberately host-owned constants: never derive one from a
// native callback, rejection reason, marker, error, or opaque token.
const FATAL_TAG = Object.freeze({
  ABORT_INVALID: "abort-invalid",
  ABORT_REPORTED: "abort-reported",
  BRIDGE_REPORT_FATAL: "bridge-report-fatal",
  FACTORY_DOUBLE_SETTLE: "factory-double-settle",
  FACTORY_MODULE_MISMATCH: "factory-module-mismatch",
  FACTORY_NO_MODULE: "factory-no-module",
  FACTORY_REJECTED: "factory-rejected",
  MARKER_INACTIVE: "marker-inactive",
  MARKER_NATIVE_FAILURE: "marker-native-failure",
  MARKER_OUTSIDE_STDERR: "marker-outside-stderr",
  MARKER_UNEXPECTED: "marker-unexpected",
  ON_EXIT_INVALID: "on-exit-invalid",
  PROCESS_EXIT_DUPLICATE: "process-exit-duplicate",
  PROCESS_EXIT_NO_ACTIVE: "process-exit-no-active",
  PROCESS_EXIT_SCHEMA: "process-exit-schema",
  QUIESCENCE_ACTIVITY_BEFORE_START: "quiescence-activity-before-start",
  QUIESCENCE_COMPLETION: "quiescence-completion",
  QUIESCENCE_NOT_QUIET: "quiescence-not-quiet",
  QUIESCENCE_RUN_TWO_LIFECYCLE: "quiescence-run-two-lifecycle",
  QUIESCENCE_TASK_SCHEDULING: "quiescence-task-scheduling",
  QUIESCENCE_TASK_START: "quiescence-task-start",
  RESULT_UPLOAD_RECHECK: "result-upload-recheck",
  RUN_START_INVALID: "run-start-invalid",
  RUN_TWO_BEFORE_LIFECYCLE: "run-two-before-lifecycle",
  RUN_TWO_SCHEDULING: "run-two-scheduling",
  RUN_TWO_TIMER_BEFORE_CLEAR: "run-two-timer-before-clear",
  RUNTIME_INIT_INVALID: "runtime-init-invalid",
  RUNTIME_MODULE_REUSED: "runtime-module-reused",
  RUNTIME_RUN_TWO_MODULE_REUSED: "runtime-run-two-module-reused",
});
const HOST_FATAL_TAGS = Object.freeze(Object.values(FATAL_TAG));
const ABORT_REASON_KINDS = Object.freeze([
  "unreadable",
  "exact-own-data-zero-exit-status",
  "assertion-prefix",
  "native-code-abort",
  "blocking-main-thread",
  "other-primitive-string",
  "primitive-nonstring",
  "nonprimitive",
]);
const ABORT_OBSERVATION_ORDERS = Object.freeze([
  "before-process-exit",
  "after-process-exit-before-onexit",
  "after-onexit",
]);
const NATIVE_FAILURE_STAGES = Object.freeze([
  "arguments",
  "capability",
  "storage",
  "profile",
  "read",
  "fence",
  "lifecycle",
  "content",
  "drain",
]);

const LIMITATIONS = Object.freeze([
  "proves_only_registered_json_pref_round_trip_across_two_fresh_modules",
  "does_not_prove_sqlite_leveldb_or_database_recovery",
  "does_not_prove_cookies_history_bookmarks_or_sessions",
  "does_not_prove_localstorage_indexeddb_cache_or_service_workers",
  "does_not_prove_concurrent_profile_contender_semantics",
  "does_not_use_host_profile_filesystem_locks_native_calls_or_memory_inspection",
  "does_not_claim_m7_complete_or_m8_feature_compatibility",
]);

const BYTE_IDENTITY_FIELDS = Object.freeze(["bytes", "sha256"]);
const ARTIFACT_FIELDS = Object.freeze([
  "artifact_delivery",
  "artifact_source_provenance",
  "build_config",
  "build_config_provenance",
  "loader",
  "module_name",
  "wasm",
]);
const CAPTURE_HARNESS_FIELDS = Object.freeze([
  "host_html",
  "host_js",
  "runner_source",
  "source_snapshot_provenance",
  "version_provenance",
]);
const FINAL_QUIESCENCE_FIELDS = Object.freeze([
  "activeRunAtPreUploadCheck",
  "activeRunAtTaskEnd",
  "activeRunAtTaskStart",
  "bridgeRecheckedImmediatelyBeforeUpload",
  "callbacksAtPreUploadCheck",
  "callbacksAtRunTwoActiveClear",
  "callbacksAtTaskEnd",
  "callbacksAtTaskStart",
  "completed",
  "postLifecycleTimerObservedBeforeTask",
  "processExitDispatchesAtPreUploadCheck",
  "processExitReportsAtPreUploadCheck",
  "processExitReportsAtRunTwoActiveClear",
  "processExitReportsAtTaskEnd",
  "quiet",
  "quietWindowMs",
  "rejectedProcessExitReportsAtPreUploadCheck",
  "started",
  "startedAfterRunTwoActiveClear",
  "taskMethod",
  "taskScheduledExactlyOnce",
]);
const FAILURE_SUMMARY_FIELDS = Object.freeze([
  "protocol",
  "case",
  "scope",
  "status",
  "failureClass",
  "firstFatalTag",
  "abortReasonKind",
  "abortObservationOrder",
  "nativeFailureStage",
  "lifecycle",
]);
const FAILURE_LIFECYCLE_FIELDS = Object.freeze([
  "acceptedProcessExitCount",
  "activeRunPresent",
  "bridgeInstalled",
  "bridgeInstalledBeforeModuleFactory",
  "callbackCount",
  "factoryCalls",
  "finalQuiescenceCompleted",
  "lastProcessExitCode",
  "lastRuntimeExitCode",
  "leaseReleasedRunCount",
  "onExitCount",
  "processExitReportCount",
  "rawTokenLeakDetected",
  "runCount",
  "unhandledRejectionObserved",
  "windowErrorObserved",
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
    throw new Error(`${description} must be a nonempty string`);
  }
  return value;
}

function parseQueryJson(value, description) {
  try {
    return JSON.parse(asNonemptyString(value, description));
  } catch (error) {
    throw new Error(`invalid ${description}: ${String(error)}`);
  }
}

function parsePositiveTimeout(value) {
  if (typeof value !== "string" || !/^[0-9]+$/.test(value)) {
    throw new Error("timeoutMs is invalid");
  }
  const timeoutMs = Number(value);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("timeoutMs is out of range");
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
      parseQueryJson(value, "profile persistence artifact identity"),
      ARTIFACT_FIELDS, "profile persistence artifact identity");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error("profile persistence artifact identity has invalid provenance");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    build_config: parseByteIdentity(artifact.build_config,
                                    "profile persistence build config identity"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "profile persistence loader identity"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "profile persistence Wasm identity"),
  });
}

function parseCaptureHarnessIdentity(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "profile persistence capture harness"),
      CAPTURE_HARNESS_FIELDS, "profile persistence capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("profile persistence capture harness has invalid provenance");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html,
                                 "profile persistence host HTML identity"),
    host_js: parseByteIdentity(harness.host_js,
                               "profile persistence host JavaScript identity"),
    runner_source: parseByteIdentity(harness.runner_source,
                                      "profile persistence runner identity"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = requireExactFields(
      parseQueryJson(value, "profile persistence versions"),
      ["chromium", "v8", "emscripten"], "profile persistence versions");
  for (const name of ["chromium", "v8", "emscripten"]) {
    if (typeof versions[name] !== "string" || !/^[0-9a-f]{40}$/.test(versions[name])) {
      throw new Error(`profile persistence ${name} revision is invalid`);
    }
  }
  return Object.freeze({
    chromium: versions.chromium,
    v8: versions.v8,
    emscripten: versions.emscripten,
  });
}

function parseStaticContext() {
  const query = new URLSearchParams(location.search);
  const allowed = new Set([
    "token", "module", "timeoutMs", "versions", "artifact", "captureHarness",
  ]);
  for (const name of query.keys()) {
    if (!allowed.has(name) || query.getAll(name).length !== 1) {
      throw new Error("profile persistence query is invalid");
    }
  }
  const token = asNonemptyString(query.get("token"), "result token");
  if (!OPAQUE_RESULT_TOKEN_RE.test(token)) {
    throw new Error("result token is invalid");
  }
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (moduleName !== PRODUCT_MODULE_NAME) {
    throw new Error("profile persistence smoke requires the dedicated M7 product module");
  }
  return Object.freeze({
    artifact: parseArtifactIdentity(query.get("artifact")),
    captureHarness: parseCaptureHarnessIdentity(query.get("captureHarness")),
    moduleName,
    resultToken: token,
    timeoutMs: parsePositiveTimeout(query.get("timeoutMs")),
    versions: parseVersions(query.get("versions")),
  });
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function randomHex(byteLength, description) {
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 ||
      !globalThis.crypto || typeof globalThis.crypto.getRandomValues !== "function") {
    throw new Error(`${description} requires Web Crypto random values`);
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
  } catch (error) {
    throw new Error(`${description} SHA-256 failed: ${String(error)}`);
  }
  if (!(digest instanceof ArrayBuffer)) {
    throw new Error(`${description} SHA-256 returned an invalid digest`);
  }
  return hex(new Uint8Array(digest));
}

function requireArtifactResponseHeaders(response, contentType, description) {
  const actualContentType = response.headers.get("Content-Type")
      ?.split(";", 1)[0].trim().toLowerCase();
  const expectedHeaders = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
  };
  if (actualContentType !== contentType ||
      Object.entries(expectedHeaders).some(([name, value]) =>
        response.headers.get(name) !== value)) {
    throw new Error(`${description} response headers are invalid`);
  }
}

async function fetchVerifiedArtifact(url, identity, contentType, description) {
  const response = await fetch(url.href, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
  });
  if (!response.ok || response.url !== url.href) {
    throw new Error(`${description} request was not exact`);
  }
  requireArtifactResponseHeaders(response, contentType, description);
  let buffer;
  try {
    buffer = await response.arrayBuffer();
  } catch (error) {
    throw new Error(`${description} response bytes failed: ${String(error)}`);
  }
  if (!(buffer instanceof ArrayBuffer)) {
    throw new Error(`${description} response bytes are invalid`);
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} disagrees with the immutable snapshot`);
  }
  return bytes;
}

function appendBounded(destination, value, maximum = MAX_OUTPUT_LINES) {
  destination.push(value);
  if (destination.length > maximum) {
    destination.splice(0, destination.length - maximum);
  }
}

function appendOutputPreservingM7Markers(destination, value, isExactM7Marker) {
  if (destination.length < MAX_OUTPUT_LINES) {
    destination.push(value);
    return;
  }
  const ordinaryOutputIndex = destination.findIndex(
      (line) => !line.startsWith(M7_MARKER_PREFIX));
  if (ordinaryOutputIndex !== -1) {
    destination.splice(ordinaryOutputIndex, 1);
    destination.push(value);
    return;
  }
  if (isExactM7Marker) {
    // An overfull stream of marker-shaped output is already fatal. Retain the
    // newest exact line as evidence rather than allowing unbounded growth.
    destination.shift();
    destination.push(value);
  }
}

function hasExactFields(value, fields) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === fields.length &&
      fields.every((field) => Object.hasOwn(value, field));
}

// The pinned generated loader uses this object as control flow after it has
// invoked onExit(0). Do not read arbitrary properties from an untrusted
// rejection reason: accessors and reflection failures are rejected, and no
// string-only fallback is accepted on the page host.
export function isExactNormalEmscriptenExitStatus(value) {
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
      return descriptor !== undefined &&
          Object.hasOwn(descriptor, "value") &&
          !Object.hasOwn(descriptor, "get") &&
          !Object.hasOwn(descriptor, "set") &&
          descriptor.value === EXPECTED_NORMAL_EXIT_STATUS_VALUES[field];
    });
  } catch (_error) {
    return false;
  }
}

function hasBoundedFailureCount(value, maximum) {
  return Number.isSafeInteger(value) && value >= 0 && value <= maximum;
}

function hasBoundedFailureExitCode(value) {
  return value === null || (Number.isSafeInteger(value) && value >= 0 &&
      value <= MAX_FAILURE_EXIT_CODE);
}

// This classifier never serializes or converts the abort reason. The exact
// ExitStatus check uses guarded own-data descriptors; all other branches use
// only primitive type/equality checks against pinned generated-loader text.
function classifyAbortReason(reason) {
  try {
    if (isExactNormalEmscriptenExitStatus(reason)) {
      return "exact-own-data-zero-exit-status";
    }
    if (typeof reason === "string") {
      if (reason.startsWith("Assertion failed")) return "assertion-prefix";
      if (reason === "native code called abort()") return "native-code-abort";
      if (reason ===
          "Blocking on the main thread is not allowed by default. See " +
          "https://emscripten.org/docs/porting/pthreads.html#blocking-on-the-main-browser-thread") {
        return "blocking-main-thread";
      }
      return "other-primitive-string";
    }
    if (reason === undefined || reason === null ||
        typeof reason === "number" || typeof reason === "boolean" ||
        typeof reason === "bigint" || typeof reason === "symbol") {
      return "primitive-nonstring";
    }
    return "nonprimitive";
  } catch (_error) {
    return "unreadable";
  }
}

function abortObservationOrder(run) {
  if (run.processExitCount === 0) return "before-process-exit";
  if (run.onExitCount === 0) return "after-process-exit-before-onexit";
  return "after-onexit";
}

export function validateChromeWasmProfilePersistenceFailureSummary(summary) {
  if (!hasExactFields(summary, FAILURE_SUMMARY_FIELDS) ||
      summary.protocol !== HOST_PROTOCOL || summary.case !== CASE ||
      summary.scope !== SCOPE || summary.status !== "fail" ||
      !FAILURE_CLASSES.includes(summary.failureClass) ||
      !(summary.firstFatalTag === null ||
          (typeof summary.firstFatalTag === "string" &&
           HOST_FATAL_TAGS.includes(summary.firstFatalTag))) ||
      !((summary.abortReasonKind === null &&
         summary.abortObservationOrder === null) ||
        (typeof summary.abortReasonKind === "string" &&
         ABORT_REASON_KINDS.includes(summary.abortReasonKind) &&
         typeof summary.abortObservationOrder === "string" &&
         ABORT_OBSERVATION_ORDERS.includes(summary.abortObservationOrder))) ||
      !(summary.nativeFailureStage === null ||
          NATIVE_FAILURE_STAGES.includes(summary.nativeFailureStage)) ||
      (summary.failureClass === "native-fixed-failure") !==
          (summary.nativeFailureStage !== null)) {
    throw new Error("profile persistence failure summary is invalid");
  }
  const lifecycle = summary.lifecycle;
  if (!hasExactFields(lifecycle, FAILURE_LIFECYCLE_FIELDS) ||
      typeof lifecycle.activeRunPresent !== "boolean" ||
      typeof lifecycle.bridgeInstalled !== "boolean" ||
      typeof lifecycle.bridgeInstalledBeforeModuleFactory !== "boolean" ||
      typeof lifecycle.finalQuiescenceCompleted !== "boolean" ||
      typeof lifecycle.rawTokenLeakDetected !== "boolean" ||
      typeof lifecycle.unhandledRejectionObserved !== "boolean" ||
      typeof lifecycle.windowErrorObserved !== "boolean" ||
      !hasBoundedFailureCount(lifecycle.acceptedProcessExitCount, 2) ||
      !hasBoundedFailureCount(lifecycle.callbackCount,
                              MAX_FAILURE_CALLBACK_COUNT) ||
      !hasBoundedFailureCount(lifecycle.factoryCalls, 2) ||
      !hasBoundedFailureCount(lifecycle.leaseReleasedRunCount, 2) ||
      !hasBoundedFailureCount(lifecycle.onExitCount, 2) ||
      !hasBoundedFailureCount(lifecycle.processExitReportCount,
                              MAX_FAILURE_PROCESS_EXIT_REPORT_COUNT) ||
      !hasBoundedFailureCount(lifecycle.runCount, 2) ||
      !hasBoundedFailureExitCode(lifecycle.lastProcessExitCode) ||
      !hasBoundedFailureExitCode(lifecycle.lastRuntimeExitCode)) {
    throw new Error("profile persistence failure lifecycle is invalid");
  }
  return summary;
}

function expectedMarkers(ordinal, digests) {
  if (ordinal === 1) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}WRITE_ACCEPTED sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  if (ordinal === 2) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}READ_A_OK sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}WRITE_ACCEPTED sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  throw new Error("profile persistence run ordinal is invalid");
}

function markerLines(lines) {
  return lines.filter((line) => line.startsWith(M7_MARKER_PREFIX));
}

function fixedNativeFailureStage(text) {
  const prefix = `${M7_MARKER_PREFIX}FAIL stage=`;
  if (typeof text !== "string" || !text.startsWith(prefix)) return null;
  const stage = text.slice(prefix.length);
  return NATIVE_FAILURE_STAGES.includes(stage) ? stage : null;
}

function boundedFailureCount(value, maximum) {
  if (!Number.isSafeInteger(value) || value < 0) return 0;
  return Math.min(value, maximum);
}

function boundedFailureExitCode(value) {
  if (!Number.isSafeInteger(value) || value < 0 || value > MAX_FAILURE_EXIT_CODE) {
    return null;
  }
  return value;
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("profile persistence page is missing its version element");
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

class ChromeWasmProfilePersistenceHost {
  #artifact;
  #bridgeInstalled = false;
  #bridgeInstalledBeforeModuleFactory = false;
  #bridgeProcessExitDispatches = 0;
  #callbackCount = 0;
  #captureHarness;
  #canvas;
  #completionResolver;
  #completionPromise;
  #factory = null;
  #factoryCalls = 0;
  #failureClass = null;
  #firstFatalTag = null;
  #fatalErrors = [];
  #finalQuiescence = {
    activeRunAtPreUploadCheck: null,
    activeRunAtTaskEnd: null,
    activeRunAtTaskStart: null,
    bridgeRecheckedImmediatelyBeforeUpload: false,
    callbacksAtPreUploadCheck: null,
    callbacksAtRunTwoActiveClear: null,
    callbacksAtTaskEnd: null,
    callbacksAtTaskStart: null,
    completed: false,
    postLifecycleTimerObservedBeforeTask: false,
    processExitDispatchesAtPreUploadCheck: null,
    processExitReportsAtPreUploadCheck: null,
    processExitReportsAtRunTwoActiveClear: null,
    processExitReportsAtTaskEnd: null,
    quiet: false,
    quietWindowMs: FINAL_QUIESCENCE_MS,
    rejectedProcessExitReportsAtPreUploadCheck: null,
    started: false,
    startedAfterRunTwoActiveClear: false,
    taskMethod: null,
    taskScheduledExactlyOnce: false,
  };
  #loaderImportUrl = null;
  #mainScriptUrlOrBlob = null;
  #moduleObjects = [];
  #wasmBinary = null;
  #wasmUrl = null;
  #noActiveProcessExitRejected = 0;
  #nativeFailureStage = null;
  #lateProcessExitRejected = 0;
  #duplicateProcessExitRejected = 0;
  #processExitReportCount = 0;
  #opaqueTokenTail = "";
  #rawTokens = null;
  #rawTokenLeakDetected = false;
  #rawTokenRedactionCount = 0;
  #runs = [];
  #runTwoScheduledExactlyOnce = false;
  #runTwoScheduleMethod = null;
  #runTwoTimerFired = false;
  #runTwoStartedAfterRunOneActiveClear = false;
  #runTwoScheduledAfterRunOneNativeExit = false;
  #runTwoScheduledAfterRunOneOnExit = false;
  #startedAt = 0;
  #statusElement;
  #tokenDigests = null;
  #unhandledRejections = [];
  #versions;
  #windowErrors = [];
  #windowErrorHandler;
  #unhandledRejectionHandler;
  #activeRun = null;

  constructor(canvas, statusElement, context) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(statusElement instanceof HTMLElement)) {
      throw new Error("profile persistence page is missing required elements");
    }
    this.#artifact = context.artifact;
    this.#canvas = canvas;
    this.#captureHarness = context.captureHarness;
    this.#statusElement = statusElement;
    this.#versions = context.versions;
    this.#completionPromise = new Promise((resolve) => {
      this.#completionResolver = resolve;
    });
  }

  #scrubCapturedFields() {
    const scrubbed = "<scrubbed-after-opaque-token-leak>";
    this.#fatalErrors = this.#fatalErrors.map(() => scrubbed);
    this.#windowErrors = this.#windowErrors.map(() => scrubbed);
    this.#unhandledRejections = this.#unhandledRejections.map(() => scrubbed);
    for (const run of this.#runs) {
      if (run.abort !== null) run.abort = scrubbed;
      if (run.factoryError !== null) run.factoryError = scrubbed;
      run.markers = run.markers.map(() => scrubbed);
      run.markerSequenceAccepted = false;
      run.leaseReleasedMarkerObserved = false;
      run.stdout = run.stdout.map(() => scrubbed);
      run.stderr = run.stderr.map(() => scrubbed);
    }
  }

  #recordFailureClass(failureClass) {
    if (!FAILURE_CLASSES.includes(failureClass)) return;
    if (this.#failureClass === null) this.#failureClass = failureClass;
  }

  #recordNativeFailureStage(stage) {
    if (!NATIVE_FAILURE_STAGES.includes(stage)) return;
    this.#nativeFailureStage = stage;
    this.#failureClass = "native-fixed-failure";
  }

  #recordOpaqueTokenLeak() {
    this.#recordFailureClass("opaque-token-leak");
    this.#rawTokenLeakDetected = true;
    this.#rawTokenRedactionCount += 1;
    this.#opaqueTokenTail = "";
    this.#scrubCapturedFields();
  }

  #safeText(value, trackAcrossCapturedCallbacks = false) {
    const text = String(value);
    if (this.#rawTokenLeakDetected) {
      return "<scrubbed-after-opaque-token-leak>";
    }
    if (this.#rawTokens !== null) {
      const combined = trackAcrossCapturedCallbacks ?
          this.#opaqueTokenTail + text : text;
      for (const token of Object.values(this.#rawTokens)) {
        if (combined.includes(token)) {
          this.#recordOpaqueTokenLeak();
          return "<scrubbed-after-opaque-token-leak>";
        }
      }
      if (trackAcrossCapturedCallbacks) {
        this.#opaqueTokenTail = combined.slice(-(TOKEN_BYTES * 2 - 1));
      }
    }
    return text;
  }

  #recordFatal(tag, message, trackAcrossCapturedCallbacks = false) {
    if (!HOST_FATAL_TAGS.includes(tag)) {
      throw new Error("profile persistence fatal tag is invalid");
    }
    if (this.#firstFatalTag === null) this.#firstFatalTag = tag;
    this.#recordFailureClass("host-lifecycle");
    const text = this.#safeText(message, trackAcrossCapturedCallbacks);
    appendBounded(
        this.#fatalErrors,
        trackAcrossCapturedCallbacks ? "<suppressed-external-fatal>" : text,
        MAX_ERROR_RECORDS);
  }

  #noteExternalCallback() {
    this.#callbackCount += 1;
  }

  #rejectedProcessExitReportCount() {
    return this.#noActiveProcessExitRejected +
        this.#duplicateProcessExitRejected + this.#lateProcessExitRejected;
  }

  #captureWindowErrors() {
    this.#windowErrorHandler = (event) => {
      this.#noteExternalCallback();
      this.#recordFailureClass("host-window-error");
      this.#safeText(event.error || event.message || "window error", true);
      appendBounded(this.#windowErrors, "<suppressed-window-error>",
                    MAX_ERROR_RECORDS);
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#noteExternalCallback();
      let reason = null;
      try {
        reason = event.reason;
      } catch (_error) {
        // Keep the failure structural. An unreadable reason is never copied
        // into host diagnostics or result JSON.
      }
      if (this.#acceptExpectedNormalExitRejection(event, reason)) {
        return;
      }
      this.#recordFailureClass("host-unhandled-rejection");
      // Only a primitive string can safely participate in the cross-callback
      // opaque-token detector. Other reason shapes remain suppressed rather
      // than invoking arbitrary getters or conversion hooks.
      this.#safeText(typeof reason === "string" ? reason :
                         "<suppressed-unhandled-rejection>", true);
      appendBounded(this.#unhandledRejections, "<suppressed-unhandled-rejection>",
                    MAX_ERROR_RECORDS);
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
      throw new Error("profile persistence host bridge is already installed");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.#noteExternalCallback();
        host.#recordFatal(FATAL_TAG.BRIDGE_REPORT_FATAL, message, true);
      },
      reportProcessExit(report) { host.#routeProcessExit(report); },
      reportFrame(_report) { host.#noteExternalCallback(); },
      reportReadiness(_report) { host.#noteExternalCallback(); },
      reportOzoneFocusState(_report) { host.#noteExternalCallback(); },
      reportOzoneCursor(_report) {
        host.#noteExternalCallback();
        return true;
      },
      reportOzoneTextInputState(_report) { host.#noteExternalCallback(); },
      reportOzoneTextInputDelivery(_report) { host.#noteExternalCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) {
        host.#noteExternalCallback();
      },
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
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge || !Object.isFrozen(bridge)) {
      throw new Error("profile persistence host bridge did not become immutable");
    }
    this.#bridgeInstalled = true;
  }

  async #prepareTokens() {
    const runOne = randomHex(TOKEN_BYTES, "profile persistence smoke");
    let runTwo = randomHex(TOKEN_BYTES, "profile persistence smoke");
    while (runTwo === runOne) {
      runTwo = randomHex(TOKEN_BYTES, "profile persistence smoke");
    }
    if (!/^[0-9a-f]{64}$/.test(runOne) || !/^[0-9a-f]{64}$/.test(runTwo)) {
      throw new Error("profile persistence opaque token grammar is invalid");
    }
    this.#rawTokens = Object.freeze({runOne, runTwo});
    if (typeof TextEncoder !== "function") {
      throw new Error("profile persistence smoke requires TextEncoder");
    }
    const runOneDigest = await sha256Hex(
        new TextEncoder().encode(runOne), "profile persistence token");
    const runTwoDigest = await sha256Hex(
        new TextEncoder().encode(runTwo), "profile persistence token");
    if (!SHA256_RE.test(runOneDigest) || !SHA256_RE.test(runTwoDigest) ||
        runOneDigest === runTwoDigest) {
      throw new Error("profile persistence token digest generation failed");
    }
    this.#tokenDigests = Object.freeze({runOne: runOneDigest, runTwo: runTwoDigest});
  }

  async #prepareFactory(moduleName) {
    const moduleUrl = new URL(`./artifacts/${moduleName}.js`, location.href);
    const wasmUrl = new URL(`./artifacts/${moduleName}.wasm`, location.href);
    if (moduleUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("profile persistence artifacts are not same-origin");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(moduleUrl, this.#artifact.loader, "text/javascript",
                            "profile persistence loader"),
      fetchVerifiedArtifact(wasmUrl, this.#artifact.wasm, "application/wasm",
                            "profile persistence Wasm"),
    ]);
    if (typeof Blob !== "function" ||
        typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("profile persistence smoke cannot import a verified loader");
    }
    // Use only the verified loader bytes, and pass the verified Wasm bytes to
    // both factories. This avoids treating a second loader import or Wasm
    // fetch as evidence for the byte identities carried by the runner.
    const blob = new Blob([loaderBytes], {type: "text/javascript"});
    this.#loaderImportUrl = URL.createObjectURL(blob);
    const namespace = await import(this.#loaderImportUrl);
    if (typeof namespace.default !== "function") {
      throw new Error("profile persistence loader has no default factory export");
    }
    this.#factory = namespace.default;
    this.#mainScriptUrlOrBlob = blob;
    this.#wasmBinary = wasmBytes;
    this.#wasmUrl = wasmUrl;
  }

  #newRun(ordinal, startKind) {
    if (this.#tokenDigests === null) {
      throw new Error("profile persistence token digests are unavailable");
    }
    const mode = ordinal === 1 ? "write" : "verify-and-write";
    return {
      abort: null,
      abortObservationOrder: null,
      abortReasonKind: null,
      activeClearedAfterLifecycle: false,
      expectedExitStatusObserved: false,
      factoryError: null,
      factorySettled: false,
      freshModuleObject: ordinal === 1,
      leaseReleasedMarkerObserved: false,
      markerIndex: 0,
      markerSequenceAccepted: true,
      markers: [],
      markerDeliveryCompleteAtProcessExit: null,
      module: null,
      moduleIdentity: randomHex(MODULE_ID_BYTES, "profile persistence module identity"),
      mode,
      onExitCount: 0,
      ordinal,
      postLifecycleTimerObserved: false,
      processExitBeforeOnExit: false,
      processExitCode: null,
      processExitCount: 0,
      runtimeExitCode: null,
      runtimeInitialized: false,
      sameModuleAsPrior: ordinal === 1 ? null : null,
      startKind,
      stderr: [],
      stdout: [],
      expectedMarkers: expectedMarkers(ordinal, this.#tokenDigests),
    };
  }

  #captureOutput(run, destination, line) {
    this.#noteExternalCallback();
    const text = this.#safeText(line, true);
    const containsM7Marker = text.includes(M7_MARKER_PREFIX);
    const expected = destination === run.stderr && this.#activeRun === run ?
        run.expectedMarkers[run.markerIndex] : null;
    const nativeFailureStage = destination === run.stderr && this.#activeRun === run ?
        fixedNativeFailureStage(text) : null;
    // Preserve only an exact expected marker. All other native callback text
    // is deliberately suppressed so a raw token fragment cannot escape in a
    // result even if its companion fragment arrives in another callback.
    const isExactM7Marker = containsM7Marker && text === expected;
    appendOutputPreservingM7Markers(
        destination,
        isExactM7Marker ? text : "<suppressed-native-output>",
        isExactM7Marker);
    if (!containsM7Marker) {
      return;
    }
    if (destination !== run.stderr) {
      this.#recordFatal(
          FATAL_TAG.MARKER_OUTSIDE_STDERR,
          `run ${run.ordinal} emitted an M7 marker outside stderr`);
      return;
    }
    if (this.#activeRun !== run) {
      this.#recordFatal(
          FATAL_TAG.MARKER_INACTIVE,
          `run ${run.ordinal} emitted an M7 marker while inactive`);
      return;
    }
    if (nativeFailureStage !== null) {
      this.#recordNativeFailureStage(nativeFailureStage);
      this.#recordFatal(
          FATAL_TAG.MARKER_NATIVE_FAILURE,
          `run ${run.ordinal} emitted a native M7 failure marker`);
      return;
    }
    if (!text.startsWith(M7_MARKER_PREFIX) || text !== expected) {
      run.markerSequenceAccepted = false;
      this.#recordFatal(
          FATAL_TAG.MARKER_UNEXPECTED,
          `run ${run.ordinal} emitted an unexpected or duplicate M7 marker`);
      return;
    }
    run.markers.push(text);
    run.markerIndex += 1;
    if (text === `${M7_MARKER_PREFIX}LEASE_RELEASED`) {
      run.leaseReleasedMarkerObserved = true;
    }
    // Chromium emits its stderr markers before its process-exit import, but
    // this Emscripten pthread glue forwards printErr through asynchronous
    // Worker messages while that import is synchronous. Keep the active run
    // until the exact marker delivery catches up with its accepted exit.
    this.#maybeCompleteRun(run);
  }

  #markersComplete(run) {
    return run.markerSequenceAccepted &&
        run.markerIndex === run.expectedMarkers.length &&
        run.leaseReleasedMarkerObserved;
  }

  #reportRuntimeInitialized(run, module) {
    this.#noteExternalCallback();
    if (this.#activeRun !== run || run.runtimeInitialized ||
        !module || (typeof module !== "object" && typeof module !== "function")) {
      this.#recordFatal(
          FATAL_TAG.RUNTIME_INIT_INVALID,
          `run ${run.ordinal} runtime initialization is invalid or late`);
      return;
    }
    if (this.#moduleObjects.includes(module)) {
      this.#recordFatal(
          FATAL_TAG.RUNTIME_MODULE_REUSED,
          `run ${run.ordinal} did not create a fresh Module object`);
      return;
    }
    run.module = module;
    run.runtimeInitialized = true;
    run.freshModuleObject = true;
    if (run.ordinal === 2) {
      run.sameModuleAsPrior = this.#moduleObjects[0] === module;
      if (run.sameModuleAsPrior) {
        this.#recordFatal(
            FATAL_TAG.RUNTIME_RUN_TWO_MODULE_REUSED,
            "run 2 reused the first Module object");
      }
    }
    this.#moduleObjects.push(module);
  }

  #reportRuntimeExit(run, code) {
    this.#noteExternalCallback();
    if (this.#activeRun !== run || !Number.isSafeInteger(code) ||
        run.onExitCount !== 0 || run.processExitCount !== 1 ||
        run.processExitCode !== 0) {
      this.#recordFatal(
          FATAL_TAG.ON_EXIT_INVALID,
          `run ${run.ordinal} onExit is invalid, duplicate, or late`);
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
        this.#fatalErrors.length !== 0 || this.#nativeFailureStage !== null ||
        this.#rawTokenLeakDetected || this.#windowErrors.length !== 0 ||
        this.#unhandledRejections.length !== 0 || run.abort !== null ||
        !run.runtimeInitialized || !run.factorySettled ||
        run.factoryError !== null || run.processExitCount !== 1 ||
        run.processExitCode !== 0 || run.onExitCount !== 1 ||
        run.runtimeExitCode !== 0 || !run.processExitBeforeOnExit ||
        !isExactNormalEmscriptenExitStatus(reason) ||
        !event || typeof event.preventDefault !== "function") {
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

  #routeProcessExit(value) {
    this.#noteExternalCallback();
    this.#processExitReportCount += 1;
    const run = this.#activeRun;
    if (run === null) {
      if (this.#runs.length !== 0) {
        this.#lateProcessExitRejected += 1;
      } else {
        this.#noActiveProcessExitRejected += 1;
      }
      this.#recordFatal(
          FATAL_TAG.PROCESS_EXIT_NO_ACTIVE,
          "profile persistence process-exit report arrived without an active run");
      return;
    }
    if (!hasExactFields(value, ["protocol", "exitCode"]) ||
        value.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(value.exitCode)) {
      this.#recordFatal(
          FATAL_TAG.PROCESS_EXIT_SCHEMA,
          `run ${run.ordinal} process-exit report has invalid schema`);
      return;
    }
    if (run.processExitCount !== 0 || run.onExitCount !== 0) {
      this.#duplicateProcessExitRejected += 1;
      this.#recordFatal(
          FATAL_TAG.PROCESS_EXIT_DUPLICATE,
          `run ${run.ordinal} process-exit report is duplicated`);
      return;
    }
    run.processExitCount += 1;
    run.processExitCode = value.exitCode;
    run.markerDeliveryCompleteAtProcessExit = this.#markersComplete(run);
    this.#bridgeProcessExitDispatches += 1;
    this.#maybeCompleteRun(run);
  }

  #reportAbort(run, reason) {
    this.#noteExternalCallback();
    if (this.#activeRun !== run || run.abort !== null) {
      this.#recordFatal(
          FATAL_TAG.ABORT_INVALID,
          `run ${run.ordinal} abort is duplicate or late`);
      return;
    }
    run.abortReasonKind = classifyAbortReason(reason);
    run.abortObservationOrder = abortObservationOrder(run);
    // A primitive string is the only reason shape that can safely participate
    // in cross-callback opaque-token detection. Other values are never
    // converted, reflected, or preserved.
    if (typeof reason === "string") this.#safeText(reason, true);
    run.abort = "<suppressed-abort>";
    this.#recordFatal(FATAL_TAG.ABORT_REPORTED, `run ${run.ordinal} aborted`);
  }

  #factorySettled(run, module) {
    this.#noteExternalCallback();
    if (run.factorySettled) {
      this.#recordFatal(
          FATAL_TAG.FACTORY_DOUBLE_SETTLE,
          `run ${run.ordinal} module factory settled more than once`);
      return;
    }
    run.factorySettled = true;
    if (!module || (typeof module !== "object" && typeof module !== "function")) {
      run.factoryError = "module factory returned no Module";
      this.#recordFatal(
          FATAL_TAG.FACTORY_NO_MODULE,
          `run ${run.ordinal} module factory returned no Module`);
      return;
    }
    if (run.module !== null && run.module !== module) {
      run.factoryError = "module factory returned a different Module";
      this.#recordFatal(
          FATAL_TAG.FACTORY_MODULE_MISMATCH,
          `run ${run.ordinal} module factory returned a different Module`);
      return;
    }
    run.module = module;
    this.#maybeCompleteRun(run);
  }

  #factoryRejected(run, error) {
    this.#noteExternalCallback();
    if (run.factorySettled) {
      this.#recordFatal(
          FATAL_TAG.FACTORY_DOUBLE_SETTLE,
          `run ${run.ordinal} module factory settled more than once`);
      return;
    }
    run.factorySettled = true;
    this.#safeText(error, true);
    run.factoryError = "<suppressed-factory-error>";
    this.#recordFatal(
        FATAL_TAG.FACTORY_REJECTED,
        `run ${run.ordinal} module factory rejected`);
  }

  #runIsCleanlyComplete(run) {
    return this.#markersComplete(run) && run.runtimeInitialized &&
        run.factorySettled && run.factoryError === null && run.abort === null &&
        // The generated loader may catch its own ExitStatus control-flow
        // exception before it reaches the page. Retain whether the exact
        // guarded page event was observed, but do not require delivery.
        typeof run.expectedExitStatusObserved === "boolean" &&
        run.runtimeExitCode === 0 && run.onExitCount === 1 &&
        run.processExitCode === 0 && run.processExitCount === 1 &&
        typeof run.markerDeliveryCompleteAtProcessExit === "boolean" &&
        run.processExitBeforeOnExit;
  }

  #maybeCompleteRun(run) {
    if (!this.#runIsCleanlyComplete(run) || run.activeClearedAfterLifecycle ||
        this.#activeRun !== run) {
      return;
    }
    this.#activeRun = null;
    run.activeClearedAfterLifecycle = true;
    if (run.ordinal === 1) {
      this.#scheduleRunTwo(run);
      return;
    }
    // Keep the immutable dispatcher live after run 2. The first timer marks
    // the native lifecycle boundary; a second, separate task starts a bounded
    // quiet window. A callback in this bounded pre-upload phase is rejected;
    // the acceptance deliberately makes no claim about callbacks after upload.
    this.#schedulePostLifecycleQuiescence(run);
  }

  #schedulePostLifecycleQuiescence(runTwo) {
    const quiescence = this.#finalQuiescence;
    if (runTwo.ordinal !== 2 || !runTwo.activeClearedAfterLifecycle ||
        this.#activeRun !== null ||
        quiescence.callbacksAtRunTwoActiveClear !== null) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_RUN_TWO_LIFECYCLE,
          "final quiescence lacks a clean second-run lifecycle");
      return;
    }
    quiescence.callbacksAtRunTwoActiveClear = this.#callbackCount;
    quiescence.processExitReportsAtRunTwoActiveClear = this.#processExitReportCount;
    setTimeout(() => {
      runTwo.postLifecycleTimerObserved = true;
      this.#scheduleFinalQuiescenceTask(runTwo);
    }, 0);
  }

  #scheduleFinalQuiescenceTask(runTwo) {
    const quiescence = this.#finalQuiescence;
    if (quiescence.taskScheduledExactlyOnce ||
        !runTwo.postLifecycleTimerObserved || this.#activeRun !== null) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_TASK_SCHEDULING,
          "final quiescence task scheduling is invalid or duplicate");
      return;
    }
    quiescence.taskScheduledExactlyOnce = true;
    quiescence.taskMethod = "setTimeout(...,0)";
    quiescence.postLifecycleTimerObservedBeforeTask =
        runTwo.postLifecycleTimerObserved;
    setTimeout(() => this.#startFinalQuiescence(runTwo), 0);
  }

  #startFinalQuiescence(runTwo) {
    const quiescence = this.#finalQuiescence;
    if (!quiescence.taskScheduledExactlyOnce || quiescence.started ||
        !quiescence.postLifecycleTimerObservedBeforeTask) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_TASK_START,
          "final quiescence task is invalid or duplicate");
      return;
    }
    quiescence.started = true;
    quiescence.startedAfterRunTwoActiveClear =
        runTwo.activeClearedAfterLifecycle && this.#activeRun === null;
    quiescence.callbacksAtTaskStart = this.#callbackCount;
    quiescence.activeRunAtTaskStart =
        this.#activeRun === null ? null : this.#activeRun.ordinal;
    if (!quiescence.startedAfterRunTwoActiveClear ||
        quiescence.callbacksAtTaskStart !==
            quiescence.callbacksAtRunTwoActiveClear ||
        this.#processExitReportCount !==
            quiescence.processExitReportsAtRunTwoActiveClear) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_ACTIVITY_BEFORE_START,
          "activity occurred before final quiescence began");
      return;
    }
    setTimeout(() => this.#finishFinalQuiescence(runTwo), FINAL_QUIESCENCE_MS);
  }

  #finishFinalQuiescence(runTwo) {
    const quiescence = this.#finalQuiescence;
    if (!quiescence.started || quiescence.completed || runTwo.ordinal !== 2) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_COMPLETION,
          "final quiescence completion is invalid or duplicate");
      return;
    }
    quiescence.callbacksAtTaskEnd = this.#callbackCount;
    quiescence.processExitReportsAtTaskEnd = this.#processExitReportCount;
    quiescence.activeRunAtTaskEnd =
        this.#activeRun === null ? null : this.#activeRun.ordinal;
    quiescence.quiet = quiescence.activeRunAtTaskStart === null &&
        quiescence.activeRunAtTaskEnd === null &&
        quiescence.callbacksAtRunTwoActiveClear ===
            quiescence.callbacksAtTaskStart &&
        quiescence.callbacksAtTaskStart === quiescence.callbacksAtTaskEnd &&
        quiescence.processExitReportsAtRunTwoActiveClear ===
            quiescence.processExitReportsAtTaskEnd;
    quiescence.completed = true;
    if (!quiescence.quiet) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_NOT_QUIET,
          "final quiescence observed a delayed callback or output");
    }
    this.#completionResolver();
  }

  #scheduleRunTwo(runOne) {
    if (this.#runTwoScheduledExactlyOnce || runOne.ordinal !== 1 ||
        !runOne.activeClearedAfterLifecycle) {
      this.#recordFatal(
          FATAL_TAG.RUN_TWO_SCHEDULING,
          "run 2 scheduling is duplicate or lacks run 1 cleanup");
      return;
    }
    this.#runTwoScheduledExactlyOnce = true;
    this.#runTwoScheduleMethod = "setTimeout(...,0)";
    this.#runTwoScheduledAfterRunOneNativeExit =
        runOne.processExitCode === 0 && runOne.processExitCount === 1 &&
        runOne.processExitBeforeOnExit && this.#markersComplete(runOne);
    this.#runTwoScheduledAfterRunOneOnExit =
        runOne.runtimeExitCode === 0 && runOne.onExitCount === 1;
    if (!this.#runTwoScheduledAfterRunOneNativeExit ||
        !this.#runTwoScheduledAfterRunOneOnExit) {
      this.#recordFatal(
          FATAL_TAG.RUN_TWO_BEFORE_LIFECYCLE,
          "run 2 was scheduled before run 1 lifecycle completed");
      return;
    }
    setTimeout(() => {
      runOne.postLifecycleTimerObserved = true;
      this.#runTwoTimerFired = true;
      this.#runTwoStartedAfterRunOneActiveClear = this.#activeRun === null &&
          runOne.activeClearedAfterLifecycle;
      if (!this.#runTwoStartedAfterRunOneActiveClear) {
        this.#recordFatal(
            FATAL_TAG.RUN_TWO_TIMER_BEFORE_CLEAR,
            "run 2 timer fired before run 1 active state was cleared");
        return;
      }
      this.#startRun(2, "setTimeout-0");
    }, 0);
  }

  #locateFileForWasm(wasmUrl, path) {
    if (typeof path !== "string" || path !== `${PRODUCT_MODULE_NAME}.wasm`) {
      throw new Error("profile persistence loader requested an unexpected artifact");
    }
    return wasmUrl.href;
  }

  #startRun(ordinal, startKind) {
    if (this.#activeRun !== null || this.#factory === null ||
        this.#mainScriptUrlOrBlob === null || this.#wasmBinary === null ||
        this.#wasmUrl === null ||
        this.#rawTokens === null || this.#runs.length !== ordinal - 1) {
      this.#recordFatal(
          FATAL_TAG.RUN_START_INVALID,
          `run ${ordinal} cannot start from the current lifecycle state`);
      return;
    }
    const run = this.#newRun(ordinal, startKind);
    this.#runs.push(run);
    this.#activeRun = run;
    const moduleArguments = ordinal === 1 ? [
      "--wasm-profile-preferences-smoke=write",
      `--wasm-profile-preferences-token-a=${this.#rawTokens.runOne}`,
    ] : [
      "--wasm-profile-preferences-smoke=verify-and-write",
      `--wasm-profile-preferences-token-a=${this.#rawTokens.runOne}`,
      `--wasm-profile-preferences-token-b=${this.#rawTokens.runTwo}`,
    ];
    const host = this;
    if (this.#factoryCalls === 0) {
      this.#bridgeInstalledBeforeModuleFactory = this.#bridgeInstalled;
    }
    this.#factoryCalls += 1;
    try {
      const factoryResult = this.#factory({
        arguments: moduleArguments,
        canvas: this.#canvas,
        locateFile(path) { return host.#locateFileForWasm(host.#wasmUrl, path); },
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
    } catch (error) {
      this.#factoryRejected(run, error);
    }
  }

  #runSnapshot(run) {
    return {
      abort: run.abort,
      activeClearedAfterLifecycle: run.activeClearedAfterLifecycle,
      expectedExitStatusObserved: run.expectedExitStatusObserved,
      factoryError: run.factoryError,
      factorySettled: run.factorySettled,
      freshModuleObject: run.freshModuleObject,
      leaseReleasedMarkerObserved: run.leaseReleasedMarkerObserved,
      markerCount: run.markers.length,
      markerSequenceAccepted: run.markerSequenceAccepted,
      markerSource: "stderr-only",
      markers: run.markers.slice(),
      markerDeliveryCompleteAtProcessExit: run.markerDeliveryCompleteAtProcessExit,
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
      sameModuleAsPrior: run.sameModuleAsPrior,
      startKind: run.startKind,
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

  #tokenEvidenceSnapshot() {
    return {
      algorithm: "SHA-256",
      runOne: this.#tokenDigests?.runOne ?? null,
      runTwo: this.#tokenDigests?.runTwo ?? null,
      distinct: this.#tokenDigests !== null &&
          this.#tokenDigests.runOne !== this.#tokenDigests.runTwo,
      rawTokensExcluded: true,
      rawTokenLeakDetected: this.#rawTokenLeakDetected,
      rawTokenRedactionCount: this.#rawTokenRedactionCount,
    };
  }

  #finalQuiescenceSnapshot() {
    return {...this.#finalQuiescence};
  }

  #refreshDynamicResult(result) {
    result.bridge = this.#bridgeSnapshot();
    result.finalQuiescence = this.#finalQuiescenceSnapshot();
    result.tokenEvidence = this.#tokenEvidenceSnapshot();
    result.runs = this.#runs.map((run) => this.#runSnapshot(run));
    result.fatalErrors = this.#fatalErrors.slice();
    result.windowErrors = this.#windowErrors.slice();
    result.unhandledRejections = this.#unhandledRejections.slice();
    return result;
  }

  recheckBeforeResultUpload(result) {
    const quiescence = this.#finalQuiescence;
    quiescence.bridgeRecheckedImmediatelyBeforeUpload = true;
    quiescence.callbacksAtPreUploadCheck = this.#callbackCount;
    quiescence.processExitReportsAtPreUploadCheck = this.#processExitReportCount;
    quiescence.activeRunAtPreUploadCheck =
        this.#activeRun === null ? null : this.#activeRun.ordinal;
    quiescence.processExitDispatchesAtPreUploadCheck =
        this.#bridgeProcessExitDispatches;
    quiescence.rejectedProcessExitReportsAtPreUploadCheck =
        this.#rejectedProcessExitReportCount();
    const clean = result && result.status === "pass" &&
        quiescence.completed && quiescence.quiet &&
        quiescence.callbacksAtPreUploadCheck ===
            quiescence.callbacksAtTaskEnd &&
        quiescence.processExitReportsAtPreUploadCheck ===
            quiescence.processExitReportsAtTaskEnd &&
        quiescence.activeRunAtPreUploadCheck === null &&
        quiescence.processExitDispatchesAtPreUploadCheck === 2 &&
        quiescence.rejectedProcessExitReportsAtPreUploadCheck === 0 &&
        this.#fatalErrors.length === 0 && this.#windowErrors.length === 0 &&
        this.#unhandledRejections.length === 0 && !this.#rawTokenLeakDetected;
    if (!clean) {
      this.#recordFatal(
          FATAL_TAG.RESULT_UPLOAD_RECHECK,
          "final bridge recheck rejected result upload");
      result.status = "fail";
      result.preferencesRoundTripProven = false;
      result.failedChecks = ["final bridge recheck rejected result upload"];
      result.error = "final bridge recheck rejected result upload";
    }
    return this.#refreshDynamicResult(result);
  }

  // Failed pages deliberately post only fixed, structural telemetry. Never
  // serialize captured output, marker text, digests, errors, or opaque tokens.
  failureSummary(failureClass = null) {
    if (failureClass !== null) this.#recordFailureClass(failureClass);
    const latestRun = this.#runs.length === 0 ? null : this.#runs.at(-1);
    const onExitCount = this.#runs.reduce(
        (total, run) => total + run.onExitCount, 0);
    const leaseReleasedRunCount = this.#runs.reduce(
        (total, run) => total + (run.leaseReleasedMarkerObserved ? 1 : 0), 0);
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status: "fail",
      failureClass: this.#failureClass ?? "host-exception",
      firstFatalTag: this.#firstFatalTag,
      abortReasonKind: latestRun?.abortReasonKind ?? null,
      abortObservationOrder: latestRun?.abortObservationOrder ?? null,
      nativeFailureStage: this.#nativeFailureStage,
      lifecycle: {
        acceptedProcessExitCount: boundedFailureCount(
            this.#bridgeProcessExitDispatches, 2),
        activeRunPresent: this.#activeRun !== null,
        bridgeInstalled: this.#bridgeInstalled,
        bridgeInstalledBeforeModuleFactory:
            this.#bridgeInstalledBeforeModuleFactory,
        callbackCount: boundedFailureCount(
            this.#callbackCount, MAX_FAILURE_CALLBACK_COUNT),
        factoryCalls: boundedFailureCount(this.#factoryCalls, 2),
        finalQuiescenceCompleted: this.#finalQuiescence.completed,
        lastProcessExitCode: boundedFailureExitCode(
            latestRun?.processExitCode),
        lastRuntimeExitCode: boundedFailureExitCode(latestRun?.runtimeExitCode),
        leaseReleasedRunCount: boundedFailureCount(leaseReleasedRunCount, 2),
        onExitCount: boundedFailureCount(onExitCount, 2),
        processExitReportCount: boundedFailureCount(
            this.#processExitReportCount, MAX_FAILURE_PROCESS_EXIT_REPORT_COUNT),
        rawTokenLeakDetected: this.#rawTokenLeakDetected,
        runCount: boundedFailureCount(this.#runs.length, 2),
        unhandledRejectionObserved: this.#unhandledRejections.length !== 0,
        windowErrorObserved: this.#windowErrors.length !== 0,
      },
    };
  }

  #result(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m7GateComplete: false,
      limitations: [...LIMITATIONS],
      artifact: this.#artifact,
      capture_harness: this.#captureHarness,
      versions: this.#versions,
      origin: location.origin,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      sameOriginDocument: true,
      preferencesRoundTripProven: status === "pass",
      sqliteLevelDbRecoveryProven: false,
      cookiesHistoryBookmarksSessionsProven: false,
      webStorageAndServiceWorkerProven: false,
      concurrentProfileContenderProven: false,
      factoryCalls: this.#factoryCalls,
      bridge: this.#bridgeSnapshot(),
      transition: {
        runTwoScheduledExactlyOnce: this.#runTwoScheduledExactlyOnce,
        runTwoScheduleMethod: this.#runTwoScheduleMethod,
        runTwoTimerFired: this.#runTwoTimerFired,
        runTwoScheduledAfterRunOneNativeExit:
            this.#runTwoScheduledAfterRunOneNativeExit,
        runTwoScheduledAfterRunOneOnExit: this.#runTwoScheduledAfterRunOneOnExit,
        runTwoStartedAfterRunOneActiveClear:
            this.#runTwoStartedAfterRunOneActiveClear,
      },
      finalQuiescence: this.#finalQuiescenceSnapshot(),
      tokenEvidence: this.#tokenEvidenceSnapshot(),
      hostBoundary: {
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        nativeCallAttempted: false,
        wasmDataInspectionAttempted: false,
      },
      runs: this.#runs.map((run) => this.#runSnapshot(run)),
      fatalErrors: this.#fatalErrors.slice(),
      windowErrors: this.#windowErrors.slice(),
      unhandledRejections: this.#unhandledRejections.slice(),
      failedChecks: [],
      error,
    };
  }

  async run(context) {
    this.#startedAt = performance.now();
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function") {
        throw new Error("profile persistence smoke requires cross-origin isolation");
      }
      if (typeof location.origin !== "string" || location.origin === "null") {
        throw new Error("profile persistence smoke requires a concrete same-origin URL");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("profile persistence canvas did not accept focus");
      }
      await this.#prepareTokens();
      this.#installPermanentBridge();
      this.#captureWindowErrors();
      await this.#prepareFactory(context.moduleName);
      this.#startRun(1, "initial");

      const deadline = this.#startedAt + context.timeoutMs;
      while (performance.now() < deadline) {
        if (this.#fatalErrors.length !== 0) {
          throw new Error("profile persistence host recorded a lifecycle failure");
        }
        if (this.#runs.length === 2 && this.#finalQuiescence.completed) {
          await this.#completionPromise;
          break;
        }
        await delay(10);
      }
      if (this.#runs.length !== 2 || !this.#runs[1].postLifecycleTimerObserved ||
          !this.#finalQuiescence.completed || !this.#finalQuiescence.quiet) {
        this.#recordFailureClass("host-timeout");
        throw new Error("profile persistence two-module lifecycle timed out");
      }
      if (this.#fatalErrors.length !== 0 || this.#windowErrors.length !== 0 ||
          this.#unhandledRejections.length !== 0 || this.#rawTokenLeakDetected) {
        throw new Error("profile persistence host observed an error after lifecycle completion");
      }
      return this.#result("pass", null);
    } catch (error) {
      this.#recordFailureClass("host-exception");
      return this.#result("fail", this.#safeText(error));
    } finally {
      this.#releaseWindowErrors();
      this.#releaseVerifiedLoader();
    }
  }
}

function validateRun(run, ordinal, tokenEvidence, failures) {
  const require = (condition, message) => {
    if (!condition) failures.push(message);
  };
  const fields = [
    "abort", "activeClearedAfterLifecycle", "expectedExitStatusObserved",
    "factoryError", "factorySettled",
    "freshModuleObject", "leaseReleasedMarkerObserved", "markerCount",
    "markerSequenceAccepted", "markerSource", "markers",
    "markerDeliveryCompleteAtProcessExit", "mode", "moduleIdentity",
    "onExitCount", "ordinal", "postLifecycleTimerObserved",
    "processExitBeforeOnExit", "processExitCode", "processExitCount",
    "runtimeExitCode", "runtimeInitialized", "sameModuleAsPrior", "startKind",
    "stderr", "stdout",
  ];
  require(hasExactFields(run, fields), `run ${ordinal} schema is invalid`);
  if (!hasExactFields(run, fields)) return;
  const expected = expectedMarkers(ordinal, tokenEvidence);
  require(run.ordinal === ordinal, `run ${ordinal} ordinal is invalid`);
  require(run.mode === (ordinal === 1 ? "write" : "verify-and-write"),
      `run ${ordinal} mode is invalid`);
  require(typeof run.moduleIdentity === "string" && MODULE_ID_RE.test(run.moduleIdentity),
      `run ${ordinal} module identity is invalid`);
  require(run.freshModuleObject === true &&
      (ordinal === 1 ? run.sameModuleAsPrior === null : run.sameModuleAsPrior === false),
  `run ${ordinal} did not use a fresh Module object`);
  require(run.runtimeInitialized === true && run.factorySettled === true &&
      run.factoryError === null && run.abort === null,
  `run ${ordinal} runtime/factory lifecycle is invalid`);
  require(run.runtimeExitCode === 0 && run.onExitCount === 1 &&
      run.processExitCode === 0 && run.processExitCount === 1 &&
      typeof run.expectedExitStatusObserved === "boolean" &&
      typeof run.markerDeliveryCompleteAtProcessExit === "boolean" &&
      run.processExitBeforeOnExit === true,
  `run ${ordinal} exit lifecycle is invalid`);
  require(run.markerSource === "stderr-only" && run.markerCount === expected.length &&
      run.markerSequenceAccepted === true && run.leaseReleasedMarkerObserved === true &&
      Array.isArray(run.markers) && run.markers.length === expected.length &&
      run.markers.every((marker, index) => marker === expected[index]),
  `run ${ordinal} M7 marker sequence is invalid`);
  require(run.activeClearedAfterLifecycle === true &&
      run.postLifecycleTimerObserved === true,
  `run ${ordinal} cleanup lifecycle is invalid`);
  require(run.startKind === (ordinal === 1 ? "initial" : "setTimeout-0"),
      `run ${ordinal} start kind is invalid`);
  for (const [stream, lines] of [["stdout", run.stdout], ["stderr", run.stderr]]) {
    require(Array.isArray(lines) && lines.length <= MAX_OUTPUT_LINES &&
        lines.every((line) => typeof line === "string"),
    `run ${ordinal} ${stream} is invalid`);
  }
  if (Array.isArray(run.stdout) && Array.isArray(run.stderr)) {
    require(!run.stdout.some((line) => line.includes(M7_MARKER_PREFIX)),
        `run ${ordinal} emitted an M7 marker on stdout`);
    const stderrMarkers = markerLines(run.stderr);
    require(stderrMarkers.length === expected.length &&
        stderrMarkers.every((marker, index) => marker === expected[index]),
    `run ${ordinal} stderr M7 marker evidence is invalid`);
    require(!run.stderr.some((line) =>
        line.includes(M7_MARKER_PREFIX) && !expected.includes(line)),
    `run ${ordinal} stderr contains an unknown or malformed M7 marker`);
    const output = run.stdout.concat(run.stderr);
    require(!output.some((line) => line.includes(`${M7_MARKER_PREFIX}FAIL`) ||
                             line.includes("--wasm-profile-preferences-token")),
    `run ${ordinal} leaked a failure or private token switch`);
  }
}

export function validateChromeWasmProfilePersistenceResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) failures.push(message);
  };
  const fields = [
    "protocol", "case", "scope", "status", "m7GateComplete", "limitations",
    "artifact", "capture_harness", "versions", "origin", "crossOriginIsolated",
    "sharedArrayBuffer", "sameOriginDocument", "preferencesRoundTripProven",
    "sqliteLevelDbRecoveryProven", "cookiesHistoryBookmarksSessionsProven",
    "webStorageAndServiceWorkerProven", "concurrentProfileContenderProven",
    "factoryCalls", "bridge", "transition", "finalQuiescence", "tokenEvidence", "hostBoundary",
    "runs", "fatalErrors", "windowErrors", "unhandledRejections", "failedChecks",
    "error",
  ];
  require(hasExactFields(result, fields), "profile persistence result schema is invalid");
  if (!hasExactFields(result, fields)) return result;
  require(result.protocol === HOST_PROTOCOL && result.case === CASE &&
      result.scope === SCOPE && result.status === "pass" &&
      result.m7GateComplete === false,
  "profile persistence result identity is invalid");
  require(Array.isArray(result.limitations) && result.limitations.length === LIMITATIONS.length &&
      result.limitations.every((value, index) => value === LIMITATIONS[index]),
  "profile persistence limitations are invalid");
  require(result.crossOriginIsolated === true && result.sharedArrayBuffer === true &&
      result.sameOriginDocument === true && typeof result.origin === "string" &&
      result.origin === location.origin,
  "profile persistence host context is invalid");
  require(result.preferencesRoundTripProven === true &&
      result.sqliteLevelDbRecoveryProven === false &&
      result.cookiesHistoryBookmarksSessionsProven === false &&
      result.webStorageAndServiceWorkerProven === false &&
      result.concurrentProfileContenderProven === false,
  "profile persistence scope claims are invalid");
  require(result.factoryCalls === 2, "profile persistence factory call count is invalid");
  const tokenFields = ["algorithm", "runOne", "runTwo", "distinct",
                       "rawTokensExcluded", "rawTokenLeakDetected", "rawTokenRedactionCount"];
  require(hasExactFields(result.tokenEvidence, tokenFields) &&
      result.tokenEvidence.algorithm === "SHA-256" &&
      SHA256_RE.test(result.tokenEvidence.runOne) &&
      SHA256_RE.test(result.tokenEvidence.runTwo) &&
      result.tokenEvidence.runOne !== result.tokenEvidence.runTwo &&
      result.tokenEvidence.distinct === true && result.tokenEvidence.rawTokensExcluded === true &&
      result.tokenEvidence.rawTokenLeakDetected === false &&
      result.tokenEvidence.rawTokenRedactionCount === 0,
  "profile persistence token evidence is invalid");
  const bridgeFields = [
    "protocol", "permanent", "frozen", "installedBeforeModuleFactory",
    "processExitDispatches", "noActiveProcessExitRejected",
    "duplicateProcessExitRejected", "lateProcessExitRejected", "activeRunAtResult",
  ];
  require(hasExactFields(result.bridge, bridgeFields) && result.bridge.protocol === HOST_PROTOCOL &&
      result.bridge.permanent === true && result.bridge.frozen === true &&
      result.bridge.installedBeforeModuleFactory === true &&
      result.bridge.processExitDispatches === 2 &&
      result.bridge.noActiveProcessExitRejected === 0 &&
      result.bridge.duplicateProcessExitRejected === 0 &&
      result.bridge.lateProcessExitRejected === 0 && result.bridge.activeRunAtResult === null,
  "profile persistence bridge lifecycle is invalid");
  const transitionFields = [
    "runTwoScheduledExactlyOnce", "runTwoScheduleMethod", "runTwoTimerFired",
    "runTwoScheduledAfterRunOneNativeExit", "runTwoScheduledAfterRunOneOnExit",
    "runTwoStartedAfterRunOneActiveClear",
  ];
  require(hasExactFields(result.transition, transitionFields) &&
      result.transition.runTwoScheduledExactlyOnce === true &&
      result.transition.runTwoScheduleMethod === "setTimeout(...,0)" &&
      result.transition.runTwoTimerFired === true &&
      result.transition.runTwoScheduledAfterRunOneNativeExit === true &&
      result.transition.runTwoScheduledAfterRunOneOnExit === true &&
      result.transition.runTwoStartedAfterRunOneActiveClear === true,
  "profile persistence two-module transition is invalid");
  const finalQuiescence = result.finalQuiescence;
  require(hasExactFields(finalQuiescence, FINAL_QUIESCENCE_FIELDS) &&
      finalQuiescence.taskScheduledExactlyOnce === true &&
      finalQuiescence.taskMethod === "setTimeout(...,0)" &&
      finalQuiescence.postLifecycleTimerObservedBeforeTask === true &&
      finalQuiescence.started === true &&
      finalQuiescence.startedAfterRunTwoActiveClear === true &&
      finalQuiescence.completed === true &&
      finalQuiescence.quietWindowMs === FINAL_QUIESCENCE_MS &&
      finalQuiescence.quiet === true &&
      finalQuiescence.bridgeRecheckedImmediatelyBeforeUpload === true &&
      finalQuiescence.activeRunAtTaskStart === null &&
      finalQuiescence.activeRunAtTaskEnd === null &&
      finalQuiescence.activeRunAtPreUploadCheck === null &&
      Number.isSafeInteger(finalQuiescence.callbacksAtRunTwoActiveClear) &&
      finalQuiescence.callbacksAtRunTwoActiveClear >= 0 &&
      finalQuiescence.callbacksAtRunTwoActiveClear ===
          finalQuiescence.callbacksAtTaskStart &&
      finalQuiescence.callbacksAtTaskStart === finalQuiescence.callbacksAtTaskEnd &&
      finalQuiescence.callbacksAtTaskEnd ===
          finalQuiescence.callbacksAtPreUploadCheck &&
      finalQuiescence.processExitReportsAtRunTwoActiveClear === 2 &&
      finalQuiescence.processExitReportsAtTaskEnd === 2 &&
      finalQuiescence.processExitReportsAtPreUploadCheck === 2 &&
      finalQuiescence.processExitDispatchesAtPreUploadCheck === 2 &&
      finalQuiescence.rejectedProcessExitReportsAtPreUploadCheck === 0,
  "profile persistence final bridge quiescence is invalid");
  const boundaryFields = [
    "hostOpfsAccessAttempted", "hostWebLocksAccessAttempted", "nativeCallAttempted",
    "wasmDataInspectionAttempted",
  ];
  require(hasExactFields(result.hostBoundary, boundaryFields) &&
      Object.values(result.hostBoundary).every((value) => value === false),
  "profile persistence host boundary is invalid");
  require(Array.isArray(result.runs) && result.runs.length === 2,
      "profile persistence must report exactly two runs");
  if (Array.isArray(result.runs) && result.runs.length === 2 &&
      result.tokenEvidence && SHA256_RE.test(result.tokenEvidence.runOne) &&
      SHA256_RE.test(result.tokenEvidence.runTwo)) {
    validateRun(result.runs[0], 1, result.tokenEvidence, failures);
    validateRun(result.runs[1], 2, result.tokenEvidence, failures);
    require(result.runs[0].moduleIdentity !== result.runs[1].moduleIdentity,
        "profile persistence runs reused a module identity");
  }
  require(Array.isArray(result.fatalErrors) && result.fatalErrors.length === 0 &&
      Array.isArray(result.windowErrors) && result.windowErrors.length === 0 &&
      Array.isArray(result.unhandledRejections) && result.unhandledRejections.length === 0 &&
      Array.isArray(result.failedChecks) && result.failedChecks.length === 0 &&
      result.error === null,
  "profile persistence host recorded an error");
  if (failures.length !== 0) {
    result.status = "fail";
    result.failedChecks = failures;
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmProfilePersistenceFromQuery() {
  const context = parseStaticContext();
  const root = document.querySelector("#m7-profile-preferences-root");
  const canvas = document.querySelector("#m7-profile-preferences-canvas");
  const status = document.querySelector("#m7-profile-preferences-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("profile persistence page is missing required elements");
  }
  renderVersions(document.querySelector("#m7-profile-preferences-versions"),
                 context.versions);
  const host = new ChromeWasmProfilePersistenceHost(canvas, status, context);
  let result = await host.run(context);
  if (result.status === "pass") {
    // This runs synchronously in the continuation immediately before schema
    // validation and result upload, after the bounded quiet window ended.
    result = host.recheckBeforeResultUpload(result);
    result = validateChromeWasmProfilePersistenceResult(result);
    if (result.status !== "pass") {
      result = host.failureSummary("host-result-validation");
    }
  } else {
    result = host.failureSummary();
  }
  if (result.status !== "pass") {
    result = validateChromeWasmProfilePersistenceFailureSummary(result);
  }
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(
      `./result/${encodeURIComponent(context.resultToken)}`, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error(`profile persistence result upload returned HTTP ${response.status}`);
  }
  if (result.status !== "pass") {
    throw new Error("profile persistence result validation failed");
  }
  return result;
}

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Same-document three-factory profile database acceptance. The page is a
// lifecycle coordinator only: Chromium owns the profile, the SQLite and
// LevelDB operations, profile lifecycle fence, orderly lifecycle cleanup,
// scoped backend drain, and the profile lease.
// In particular this host has no filesystem, lock, native-call, or Wasm-memory
// inspection authority. It passes two private opaque command-line values to
// Chromium and retains only their SHA-256 digests for redacted evidence.

const HOST_PROTOCOL = 1;
const CASE = "chrome_profile_database_three_fresh_modules_m7";
const SCOPE =
    "same-origin-same-document-three-fresh-chrome-wasm-m7-profile-database-test-modules-graceful-close-reopen-only";
const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_test";
const ABORT_PC_DIAGNOSTIC_MODULE_NAME =
    "chrome_wasm_m7_profile_database_abort_pc_diagnostic";
const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:";
// Failure-only fixed database-task telemetry. It is never an acceptance
// marker and never appears in a successful result.
const M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
// This marker is emitted only by the distinct, default-off abort-PC artifact.
// It is failure-only telemetry: normal M7 results and run snapshots never
// retain it.
const M7_ABORT_PC_PREFIX = "CHROMIUM_WASM_M7_ABORT_PC:";
const DIAGNOSTIC_MODE_NORMAL = "normal";
const DIAGNOSTIC_MODE_ABORT_PC = "abort-pc";
const DIAGNOSTIC_MODES = Object.freeze([
  DIAGNOSTIC_MODE_NORMAL,
  DIAGNOSTIC_MODE_ABORT_PC,
]);
const ABORT_PC_CALLER_CALLER_FRAME = "caller-caller";
const MAX_ABORT_PC_FUNCTION_INDEX = 0xffffffff;
const ABORT_PC_MARKER_RE =
    /^CHROMIUM_WASM_M7_ABORT_PC:frame=caller-caller;function=(0|[1-9][0-9]{0,9});offset=(0x(?:0|[1-9a-f][0-9a-f]{0,7}))$/;
const ABORT_PC_OFFSET_RE = /^0x(?:0|[1-9a-f][0-9a-f]{0,7})$/;
// This is a deliberately narrow failure-only diagnostic. It identifies a
// pre-audited fatal *headline family*, never a source location, line, message,
// or root cause. The raw printErr line stays transient and is never serialized.
const FATAL_HEADLINE_PROVENANCE =
    "fixed-active-stderr-logger-logv-fatal-headline-v1";
const FATAL_HEADLINE_CAPTURE_PRE = "leveldb-write-logger-logv-first-pre";
const FATAL_HEADLINE_CAPTURE_POST = "leveldb-write-logger-logv-first-post";
const MAX_FATAL_HEADLINE_LINE_CODE_UNITS = 512;
const FATAL_HEADLINE_FAMILIES = Object.freeze([
  "wasm-time",
  "time-formatting",
  "leveldb",
  "base-file",
  "base-logging",
  "other-fatal",
  "ambiguous",
]);
// These are the only v1 values an untrusted page result may claim. The two
// reserved enum slots above deliberately have no v1 raw-output producer.
const EXPORTED_FATAL_HEADLINE_FAMILIES = Object.freeze([
  "wasm-time",
  "time-formatting",
  "leveldb",
  "base-file",
  "ambiguous",
]);
// Match only these complete, artifact-audited fatal headline headers. Do not
// normalize, split, parse, or retain the suffix: logging_wasm can print normal
// `file:line: message` output, so bare paths are not safe evidence.
const FATAL_HEADLINE_HEADER_FAMILIES = Object.freeze([
  Object.freeze({
    header: "../../base/time/time_wasm.cc:44: Check failed: ",
    family: "wasm-time",
  }),
  Object.freeze({
    header: "../../base/time/time_wasm.cc:50: Check failed: ",
    family: "wasm-time",
  }),
  Object.freeze({
    header: "../../base/i18n/time_formatting.cc:74: DCHECK failed: ",
    family: "time-formatting",
  }),
  Object.freeze({
    header: "../../base/i18n/time_formatting.cc:76: DCHECK failed: ",
    family: "time-formatting",
  }),
  Object.freeze({
    header: "../../base/i18n/time_formatting.cc:81: DCHECK failed: ",
    family: "time-formatting",
  }),
  Object.freeze({
    header: "../../third_party/leveldatabase/env_chromium.cc:355: DCHECK failed: ",
    family: "leveldb",
  }),
  Object.freeze({
    header: "../../third_party/leveldatabase/env_chromium.cc:1340: Check failed: ",
    family: "leveldb",
  }),
  Object.freeze({
    header: "../../base/files/file.cc:46: DCHECK failed: ",
    family: "base-file",
  }),
  Object.freeze({
    header: "../../base/files/file.cc:53: DCHECK failed: ",
    family: "base-file",
  }),
  // `ChromiumLogger::Logv()` reaches this direct File write DCHECK after the
  // active logger PRE boundary. Keep the complete header literal so ordinary
  // logging from the same source cannot become a candidate.
  Object.freeze({
    header: "../../base/files/file_posix.cc:439: DCHECK failed: ",
    family: "base-file",
  }),
]);
const MAX_TIMEOUT_MS = 120000;
const MAX_OUTPUT_LINES = 128;
const MAX_ERROR_RECORDS = 32;
const MODULE_ID_BYTES = 16;
const TOKEN_BYTES = 32;
const FINAL_QUIESCENCE_MS = 50;
const MAX_FAILURE_CALLBACK_COUNT = 255;
const MAX_FAILURE_PROCESS_EXIT_REPORT_COUNT = 4;
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
  ABORT_PC_AFTER_ABORT: "abort-pc-after-abort",
  ABORT_PC_DUPLICATE: "abort-pc-duplicate",
  ABORT_PC_INACTIVE: "abort-pc-inactive",
  ABORT_PC_INVALID: "abort-pc-invalid",
  ABORT_PC_MISSING_BEFORE_ABORT: "abort-pc-missing-before-abort",
  ABORT_PC_OUTSIDE_STDERR: "abort-pc-outside-stderr",
  ABORT_PC_UNEXPECTED: "abort-pc-unexpected",
  ABORT_PC_UNEXPECTED_CLEAN_EXIT: "abort-pc-unexpected-clean-exit",
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
  PHASE_INACTIVE: "phase-inactive",
  PHASE_OUTSIDE_STDERR: "phase-outside-stderr",
  PHASE_UNEXPECTED: "phase-unexpected",
  PROCESS_EXIT_DUPLICATE: "process-exit-duplicate",
  PROCESS_EXIT_NO_ACTIVE: "process-exit-no-active",
  PROCESS_EXIT_SCHEMA: "process-exit-schema",
  QUIESCENCE_ACTIVITY_BEFORE_START: "quiescence-activity-before-start",
  QUIESCENCE_COMPLETION: "quiescence-completion",
  QUIESCENCE_NOT_QUIET: "quiescence-not-quiet",
  QUIESCENCE_RUN_THREE_LIFECYCLE: "quiescence-run-three-lifecycle",
  QUIESCENCE_TASK_SCHEDULING: "quiescence-task-scheduling",
  QUIESCENCE_TASK_START: "quiescence-task-start",
  RESULT_UPLOAD_RECHECK: "result-upload-recheck",
  RUN_START_INVALID: "run-start-invalid",
  RUN_NEXT_BEFORE_LIFECYCLE: "run-next-before-lifecycle",
  RUN_NEXT_SCHEDULING: "run-next-scheduling",
  RUN_NEXT_TIMER_BEFORE_CLEAR: "run-next-timer-before-clear",
  RUNTIME_INIT_INVALID: "runtime-init-invalid",
  RUNTIME_MODULE_REUSED: "runtime-module-reused",
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
  "database",
  "fence",
  "lifecycle",
  "content",
  "drain",
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
  // FileExists emits bounded call-ordinal pairs. The names intentionally do
  // not carry a path, result, or other database data.
  "leveldb-write-env-file-exists-first-pre",
  "leveldb-write-env-file-exists-first-post",
  "leveldb-write-env-file-exists-second-pre",
  "leveldb-write-env-file-exists-second-post",
  "leveldb-write-env-file-exists-later-pre",
  "leveldb-write-env-file-exists-later-post",
  "leveldb-write-env-create-dir",
  "leveldb-write-env-rename-file",
  "leveldb-write-env-new-logger",
  // The diagnostic logger wrapper records only the first owner-thread Logv
  // boundary during its active interval. Neither the formatted message nor
  // any logger data leaves Chromium through this protocol.
  "leveldb-write-logger-logv-first-pre",
  "leveldb-write-logger-logv-first-post",
  // These are emitted only by the abort-PC artifact's in-process logging
  // observer. Each is a fixed source family, never a file path, line, or
  // message, and does not establish a root cause or database success.
  "leveldb-write-logger-fatal-source-wasm-time",
  "leveldb-write-logger-fatal-source-time-formatting",
  "leveldb-write-logger-fatal-source-leveldb",
  "leveldb-write-logger-fatal-source-base-file",
  "leveldb-write-env-lock-file",
  "leveldb-write-env-new-writable-file",
  "leveldb-read",
  "leveldb-read-open",
  "leveldb-read-get",
  "leveldb-read-close",
  "task-complete",
]);
// These phases are emitted only by the distinct abort-PC artifact's scoped
// source observer. They must occur exactly once within the active Logv PRE
// interval; accepting one elsewhere would falsely imply diagnostic provenance.
const FATAL_SOURCE_DATABASE_PHASES = Object.freeze([
  "leveldb-write-logger-fatal-source-wasm-time",
  "leveldb-write-logger-fatal-source-time-formatting",
  "leveldb-write-logger-fatal-source-leveldb",
  "leveldb-write-logger-fatal-source-base-file",
]);

const LIMITATIONS = Object.freeze([
  "proves_only_sqlite_and_leveldb_graceful_close_reopen_across_three_fresh_modules",
  "does_not_prove_sqlite_or_leveldb_crash_or_interrupted_write_recovery",
  "does_not_prove_directory_durability_or_page_reload_durability",
  "does_not_prove_registered_preferences_or_profile_service_persistence",
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
  "callbacksAtRunThreeActiveClear",
  "callbacksAtTaskEnd",
  "callbacksAtTaskStart",
  "completed",
  "postLifecycleTimerObservedBeforeTask",
  "processExitDispatchesAtPreUploadCheck",
  "processExitReportsAtPreUploadCheck",
  "processExitReportsAtRunThreeActiveClear",
  "processExitReportsAtTaskEnd",
  "quiet",
  "quietWindowMs",
  "rejectedProcessExitReportsAtPreUploadCheck",
  "started",
  "startedAfterRunThreeActiveClear",
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
  "abortPc",
  "fatalHeadline",
  "abortReasonKind",
  "abortObservationOrder",
  "nativeFailureStage",
  "nativeDatabasePhase",
  "preDbImplConstructionObservedBeforeSecondFileExistsPost",
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

function expectedModuleNameForDiagnosticMode(diagnosticMode) {
  if (diagnosticMode === DIAGNOSTIC_MODE_NORMAL) return PRODUCT_MODULE_NAME;
  if (diagnosticMode === DIAGNOSTIC_MODE_ABORT_PC) {
    return ABORT_PC_DIAGNOSTIC_MODULE_NAME;
  }
  throw new Error("profile database diagnostic mode is invalid");
}

function parseArtifactIdentity(value, expectedModuleName) {
  const artifact = requireExactFields(
      parseQueryJson(value, "profile database artifact identity"),
      ARTIFACT_FIELDS, "profile database artifact identity");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== expectedModuleName) {
    throw new Error("profile database artifact identity has invalid provenance");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    build_config: parseByteIdentity(artifact.build_config,
                                    "profile database build config identity"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "profile database loader identity"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "profile database Wasm identity"),
  });
}

function parseCaptureHarnessIdentity(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "profile database capture harness"),
      CAPTURE_HARNESS_FIELDS, "profile database capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("profile database capture harness has invalid provenance");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html,
                                 "profile database host HTML identity"),
    host_js: parseByteIdentity(harness.host_js,
                               "profile database host JavaScript identity"),
    runner_source: parseByteIdentity(harness.runner_source,
                                      "profile database runner identity"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = requireExactFields(
      parseQueryJson(value, "profile database versions"),
      ["chromium", "v8", "emscripten"], "profile database versions");
  for (const name of ["chromium", "v8", "emscripten"]) {
    if (typeof versions[name] !== "string" || !/^[0-9a-f]{40}$/.test(versions[name])) {
      throw new Error(`profile database ${name} revision is invalid`);
    }
  }
  return Object.freeze({
    chromium: versions.chromium,
    v8: versions.v8,
    emscripten: versions.emscripten,
  });
}

function parseDiagnosticMode(value) {
  // Older direct-host contract tests omit this query field. The runner always
  // selects a mode explicitly, while omission remains the safe default.
  if (value === null) return DIAGNOSTIC_MODE_NORMAL;
  if (typeof value !== "string" || !DIAGNOSTIC_MODES.includes(value)) {
    throw new Error("profile database diagnostic mode is invalid");
  }
  return value;
}

function parseStaticContext() {
  const query = new URLSearchParams(location.search);
  const allowed = new Set([
    "token", "module", "timeoutMs", "versions", "artifact", "captureHarness",
    "diagnosticMode",
  ]);
  for (const name of query.keys()) {
    if (!allowed.has(name) || query.getAll(name).length !== 1) {
      throw new Error("profile database query is invalid");
    }
  }
  const token = asNonemptyString(query.get("token"), "result token");
  if (!OPAQUE_RESULT_TOKEN_RE.test(token)) {
    throw new Error("result token is invalid");
  }
  const diagnosticMode = parseDiagnosticMode(query.get("diagnosticMode"));
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (moduleName !== expectedModuleNameForDiagnosticMode(diagnosticMode)) {
    throw new Error("profile database smoke requires the dedicated M7 product module");
  }
  return Object.freeze({
    artifact: parseArtifactIdentity(query.get("artifact"), moduleName),
    captureHarness: parseCaptureHarnessIdentity(query.get("captureHarness")),
    diagnosticMode,
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

function isAbortPcObservation(value) {
  return value === null ||
      (hasExactFields(value, ["frame", "function", "offset"]) &&
       value.frame === ABORT_PC_CALLER_CALLER_FRAME &&
       Number.isSafeInteger(value.function) && value.function >= 0 &&
       value.function <= MAX_ABORT_PC_FUNCTION_INDEX &&
       typeof value.offset === "string" && ABORT_PC_OFFSET_RE.test(value.offset));
}

function isFatalHeadlineObservation(value) {
  return value === null ||
      (hasExactFields(value, ["family", "provenance"]) &&
       typeof value.family === "string" &&
       EXPORTED_FATAL_HEADLINE_FAMILIES.includes(value.family) &&
       value.provenance === FATAL_HEADLINE_PROVENANCE);
}

export function validateChromeWasmProfileDatabaseFailureSummary(summary) {
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
      !isAbortPcObservation(summary.abortPc) ||
      !isFatalHeadlineObservation(summary.fatalHeadline) ||
      !(summary.nativeFailureStage === null ||
          NATIVE_FAILURE_STAGES.includes(summary.nativeFailureStage)) ||
      !(summary.nativeDatabasePhase === null ||
          NATIVE_DATABASE_PHASES.includes(summary.nativeDatabasePhase)) ||
      !(summary.preDbImplConstructionObservedBeforeSecondFileExistsPost === null ||
          typeof summary.preDbImplConstructionObservedBeforeSecondFileExistsPost ===
              "boolean") ||
      (summary.failureClass === "native-fixed-failure") !==
          (summary.nativeFailureStage !== null)) {
    throw new Error("profile database failure summary is invalid");
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
      !hasBoundedFailureCount(lifecycle.acceptedProcessExitCount, 3) ||
      !hasBoundedFailureCount(lifecycle.callbackCount,
                              MAX_FAILURE_CALLBACK_COUNT) ||
      !hasBoundedFailureCount(lifecycle.factoryCalls, 3) ||
      !hasBoundedFailureCount(lifecycle.leaseReleasedRunCount, 3) ||
      !hasBoundedFailureCount(lifecycle.onExitCount, 3) ||
      !hasBoundedFailureCount(lifecycle.processExitReportCount,
                              MAX_FAILURE_PROCESS_EXIT_REPORT_COUNT) ||
      !hasBoundedFailureCount(lifecycle.runCount, 3) ||
      !hasBoundedFailureExitCode(lifecycle.lastProcessExitCode) ||
      !hasBoundedFailureExitCode(lifecycle.lastRuntimeExitCode)) {
    throw new Error("profile database failure lifecycle is invalid");
  }
  return summary;
}

function expectedMarkers(ordinal, digests) {
  // FENCE_OK follows DATABASES_CLOSED as lifecycle sequencing evidence only.
  // It does not claim database, directory, page-reload, or power-loss
  // durability.
  if (ordinal === 1) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}DATABASES_CLOSED sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  if (ordinal === 2) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}SQLITE_READ_A_OK sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}LEVELDB_READ_A_OK sha256=${digests.runOne}`,
      `${M7_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}LEVELDB_WRITE_ACCEPTED sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}DATABASES_CLOSED sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  if (ordinal === 3) {
    return Object.freeze([
      `${M7_MARKER_PREFIX}READY`,
      `${M7_MARKER_PREFIX}SQLITE_READ_B_OK sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}LEVELDB_READ_B_OK sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}DATABASES_CLOSED sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}FENCE_OK sha256=${digests.runTwo}`,
      `${M7_MARKER_PREFIX}LEASE_RELEASED`,
    ]);
  }
  throw new Error("profile database run ordinal is invalid");
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

function fixedNativeDatabasePhase(text) {
  if (typeof text !== "string" || !text.startsWith(M7_DATABASE_PHASE_PREFIX)) {
    return null;
  }
  const phase = text.slice(M7_DATABASE_PHASE_PREFIX.length);
  return NATIVE_DATABASE_PHASES.includes(phase) ? phase : null;
}

function fixedAbortPcMarker(text) {
  if (typeof text !== "string" || !text.startsWith(M7_ABORT_PC_PREFIX)) {
    return null;
  }
  if (text === `${M7_ABORT_PC_PREFIX}unavailable`) {
    return Object.freeze({available: false, value: null});
  }
  const match = ABORT_PC_MARKER_RE.exec(text);
  if (match === null) return null;
  const functionIndex = Number(match[1]);
  if (!Number.isSafeInteger(functionIndex) || functionIndex < 0 ||
      functionIndex > MAX_ABORT_PC_FUNCTION_INDEX) {
    return null;
  }
  return Object.freeze({
    available: true,
    value: Object.freeze({
      frame: ABORT_PC_CALLER_CALLER_FRAME,
      function: functionIndex,
      offset: match[2],
    }),
  });
}

function fixedFatalHeadlineFamily(text) {
  // `text` has already passed #safeText. Bound the transient inspection
  // without truncating or normalizing it: only startsWith against the fixed
  // complete headers below is permitted, and no suffix is read or retained.
  if (typeof text !== "string" ||
      text.length > MAX_FATAL_HEADLINE_LINE_CODE_UNITS) {
    return null;
  }
  for (const candidate of FATAL_HEADLINE_HEADER_FAMILIES) {
    if (text.startsWith(candidate.header)) return candidate.family;
  }
  return null;
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
    throw new Error("profile database page is missing its version element");
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

class ChromeWasmProfileDatabaseHost {
  #artifact;
  #bridgeInstalled = false;
  #bridgeInstalledBeforeModuleFactory = false;
  #bridgeProcessExitDispatches = 0;
  #callbackCount = 0;
  #captureHarness;
  #canvas;
  #completionResolver;
  #completionPromise;
  #diagnosticMode;
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
    callbacksAtRunThreeActiveClear: null,
    callbacksAtTaskEnd: null,
    callbacksAtTaskStart: null,
    completed: false,
    postLifecycleTimerObservedBeforeTask: false,
    processExitDispatchesAtPreUploadCheck: null,
    processExitReportsAtPreUploadCheck: null,
    processExitReportsAtRunThreeActiveClear: null,
    processExitReportsAtTaskEnd: null,
    quiet: false,
    quietWindowMs: FINAL_QUIESCENCE_MS,
    rejectedProcessExitReportsAtPreUploadCheck: null,
    started: false,
    startedAfterRunThreeActiveClear: false,
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
  #runThreeScheduledExactlyOnce = false;
  #runThreeScheduleMethod = null;
  #runThreeTimerFired = false;
  #runThreeStartedAfterRunTwoActiveClear = false;
  #runThreeScheduledAfterRunTwoNativeExit = false;
  #runThreeScheduledAfterRunTwoOnExit = false;
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
      throw new Error("profile database page is missing required elements");
    }
    this.#artifact = context.artifact;
    this.#canvas = canvas;
    this.#captureHarness = context.captureHarness;
    this.#diagnosticMode = context.diagnosticMode;
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
      // A token leak makes any pending source-family candidate unusable. Keep
      // only the fixed ambiguous enum; never retain or re-inspect the line.
      run.fatalHeadlineCaptureOpen = false;
      run.fatalHeadlineFamily = "ambiguous";
      run.fatalHeadlineFinalized = true;
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
    if (this.#rawTokenLeakDetected) {
      return "<scrubbed-after-opaque-token-leak>";
    }
    // Foreign callback values can expose arbitrary conversion hooks. Preserve
    // only primitive strings; diagnostics for every other shape stay fixed.
    if (typeof value !== "string") {
      return "<suppressed-nonstring>";
    }
    const text = value;
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
      throw new Error("profile database fatal tag is invalid");
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

  #invalidateAbortPcDiagnostic(run) {
    if (this.#diagnosticMode === DIAGNOSTIC_MODE_ABORT_PC) {
      // Keep this receipt barrier private. The failure schema remains limited
      // to fixed, bounded fields. A marker protocol violation also clears a
      // pending headline family so it cannot outlive the invalid receipt.
      run.abortPcDiagnosticInvalid = true;
      run.fatalHeadlineCaptureOpen = false;
      run.fatalHeadlineFamily = null;
      run.fatalHeadlineFinalized = true;
      run.fatalHeadlineInvalidated = true;
    }
  }

  #markFatalHeadlineAmbiguous(run) {
    // This is diagnostic provenance, not attribution proof or acceptance
    // evidence. Once ambiguous, a later header must never upgrade it.
    if (this.#diagnosticMode === DIAGNOSTIC_MODE_ABORT_PC &&
        !run.fatalHeadlineInvalidated) {
      run.fatalHeadlineFamily = "ambiguous";
      run.fatalHeadlineFinalized = true;
    }
  }

  #captureFatalHeadline(run, destination, family) {
    if (family === null) return;
    // A complete fixed header is a candidate only in the narrow active
    // diagnostic interval. Do not inspect, parse, normalize, or retain the
    // raw line's suffix.
    if (this.#diagnosticMode !== DIAGNOSTIC_MODE_ABORT_PC ||
        destination !== run.stderr || this.#activeRun !== run ||
        this.#rawTokenLeakDetected || run.abort !== null ||
        run.abortPcMarkerObserved || run.abortPcDiagnosticInvalid ||
        run.fatalHeadlineInvalidated || !run.fatalHeadlineCaptureOpen) {
      this.#markFatalHeadlineAmbiguous(run);
      return;
    }
    if (run.fatalHeadlineFamily !== null || run.fatalHeadlineFinalized) {
      this.#markFatalHeadlineAmbiguous(run);
      return;
    }
    run.fatalHeadlineFamily = family;
  }

  #finalizeFatalHeadline(run) {
    if (this.#diagnosticMode !== DIAGNOSTIC_MODE_ABORT_PC ||
        run.fatalHeadlineInvalidated) {
      return;
    }
    // Exactly one eligible fixed header is required. Zero candidates retain
    // only the fixed ambiguous enum; a late valid-looking line cannot change
    // this result after onAbort.
    if (run.fatalHeadlineFamily === null) {
      run.fatalHeadlineFamily = "ambiguous";
    }
    run.fatalHeadlineFinalized = true;
  }

  #fatalHeadlineSummary(run) {
    if (this.#diagnosticMode !== DIAGNOSTIC_MODE_ABORT_PC || run === null ||
        run.abortPcDiagnosticInvalid || run.fatalHeadlineInvalidated ||
        !run.abortPcMarkerObserved || run.abort === null ||
        run.abortReasonKind !== "native-code-abort" ||
        run.abortObservationOrder !== "before-process-exit") {
      return null;
    }
    const family = run.fatalHeadlineFamily ?? "ambiguous";
    if (!EXPORTED_FATAL_HEADLINE_FAMILIES.includes(family)) return null;
    return {
      family,
      provenance: FATAL_HEADLINE_PROVENANCE,
    };
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
      throw new Error("profile database host bridge is already installed");
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
      throw new Error("profile database host bridge did not become immutable");
    }
    this.#bridgeInstalled = true;
  }

  async #prepareTokens() {
    const runOne = randomHex(TOKEN_BYTES, "profile database smoke");
    let runTwo = randomHex(TOKEN_BYTES, "profile database smoke");
    while (runTwo === runOne) {
      runTwo = randomHex(TOKEN_BYTES, "profile database smoke");
    }
    if (!/^[0-9a-f]{64}$/.test(runOne) || !/^[0-9a-f]{64}$/.test(runTwo)) {
      throw new Error("profile database opaque token grammar is invalid");
    }
    this.#rawTokens = Object.freeze({runOne, runTwo});
    if (typeof TextEncoder !== "function") {
      throw new Error("profile database smoke requires TextEncoder");
    }
    const runOneDigest = await sha256Hex(
        new TextEncoder().encode(runOne), "profile database token");
    const runTwoDigest = await sha256Hex(
        new TextEncoder().encode(runTwo), "profile database token");
    if (!SHA256_RE.test(runOneDigest) || !SHA256_RE.test(runTwoDigest) ||
        runOneDigest === runTwoDigest) {
      throw new Error("profile database token digest generation failed");
    }
    this.#tokenDigests = Object.freeze({runOne: runOneDigest, runTwo: runTwoDigest});
  }

  async #prepareFactory(moduleName) {
    const moduleUrl = new URL(`./artifacts/${moduleName}.js`, location.href);
    const wasmUrl = new URL(`./artifacts/${moduleName}.wasm`, location.href);
    if (moduleUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("profile database artifacts are not same-origin");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(moduleUrl, this.#artifact.loader, "text/javascript",
                            "profile database loader"),
      fetchVerifiedArtifact(wasmUrl, this.#artifact.wasm, "application/wasm",
                            "profile database Wasm"),
    ]);
    if (typeof Blob !== "function" ||
        typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("profile database smoke cannot import a verified loader");
    }
    // Use only the verified loader bytes, and pass the verified Wasm bytes to
    // both factories. This avoids treating a second loader import or Wasm
    // fetch as evidence for the byte identities carried by the runner.
    const blob = new Blob([loaderBytes], {type: "text/javascript"});
    this.#loaderImportUrl = URL.createObjectURL(blob);
    const namespace = await import(this.#loaderImportUrl);
    if (typeof namespace.default !== "function") {
      throw new Error("profile database loader has no default factory export");
    }
    this.#factory = namespace.default;
    this.#mainScriptUrlOrBlob = blob;
    this.#wasmBinary = wasmBytes;
    this.#wasmUrl = wasmUrl;
  }

  #newRun(ordinal, startKind) {
    if (this.#tokenDigests === null) {
      throw new Error("profile database token digests are unavailable");
    }
    const mode = ordinal === 1 ? "write-a" :
        ordinal === 2 ? "verify-a-write-b" : "verify-b";
    return {
      abort: null,
      // The exact structured value is failure-only. This private receipt bit
      // distinguishes an accepted `unavailable` marker from no marker.
      abortPc: null,
      abortPcDiagnosticInvalid: false,
      abortPcMarkerObserved: false,
      // Private failure-only state for the single headline observed between
      // the first logger Logv PRE/POST boundaries. It never enters a success
      // run snapshot and never retains source text or a suffix.
      fatalHeadlineCaptureOpen: false,
      fatalHeadlineFamily: null,
      fatalHeadlineFinalized: false,
      fatalHeadlineInvalidated: false,
      fatalSourcePhaseObserved: false,
      abortObservationOrder: null,
      abortReasonKind: null,
      activeClearedAfterLifecycle: false,
      expectedExitStatusObserved: false,
      factoryError: null,
      factorySettled: false,
      freshModuleObject: false,
      leaseReleasedMarkerObserved: false,
      markerIndex: 0,
      markerSequenceAccepted: true,
      markers: [],
      markerDeliveryCompleteAtProcessExit: null,
      module: null,
      moduleIdentity: randomHex(MODULE_ID_BYTES, "profile database module identity"),
      mode,
      nativeDatabasePhase: null,
      // These remain private per-run correlation state. Only the fixed
      // nullable snapshot reaches a failure summary, never a success result.
      preDbImplConstructionObservedBeforeSecondFileExistsPost: null,
      preDbImplConstructionPhaseObserved: false,
      onExitCount: 0,
      ordinal,
      postLifecycleTimerObserved: false,
      processExitBeforeOnExit: false,
      processExitCode: null,
      processExitCount: 0,
      runtimeExitCode: null,
      runtimeInitialized: false,
      sameModuleAsPrior: null,
      startKind,
      stderr: [],
      // These private booleans are per-sender receipt barriers for diagnostic
      // phases. They must never enter a result schema.
      secondFileExistsPostPhaseObserved: false,
      taskPostPhaseObserved: false,
      taskCompletePhaseObserved: false,
      stdout: [],
      expectedMarkers: expectedMarkers(ordinal, this.#tokenDigests),
    };
  }

  #captureOutput(run, destination, line) {
    this.#noteExternalCallback();
    const text = this.#safeText(line, true);
    // Headline inspection is deliberately before generic output suppression:
    // its result is a fixed enum only, while the raw callback text remains
    // transient and is never placed in a snapshot or failure summary.
    this.#captureFatalHeadline(
        run, destination, fixedFatalHeadlineFamily(text));
    const containsM7Marker = text.includes(M7_MARKER_PREFIX);
    const containsNativeDatabasePhase = text.includes(M7_DATABASE_PHASE_PREFIX);
    const containsAbortPcMarker = text.includes(M7_ABORT_PC_PREFIX);
    const expected = destination === run.stderr && this.#activeRun === run ?
        run.expectedMarkers[run.markerIndex] : null;
    const nativeFailureStage = destination === run.stderr && this.#activeRun === run ?
        fixedNativeFailureStage(text) : null;
    const nativeDatabasePhase =
        destination === run.stderr && this.#activeRun === run ?
        fixedNativeDatabasePhase(text) : null;
    const abortPcMarker = destination === run.stderr && this.#activeRun === run ?
        fixedAbortPcMarker(text) : null;
    // Preserve only an exact expected marker. All other native callback text
    // is deliberately suppressed so a raw token fragment cannot escape in a
    // result even if its companion fragment arrives in another callback.
    const isExactM7Marker = containsM7Marker && text === expected;
    appendOutputPreservingM7Markers(
        destination,
        isExactM7Marker ? text : "<suppressed-native-output>",
        isExactM7Marker);
    // The abort-PC marker is a separate, default-off native-library
    // diagnostic. It is never an M7 acceptance marker and its raw line never
    // enters a run snapshot. `unavailable` is a successful receipt of the
    // diagnostic marker; the private receipt bit distinguishes it from a
    // missing marker before onAbort.
    if (containsAbortPcMarker) {
      if (destination !== run.stderr) {
        this.#invalidateAbortPcDiagnostic(run);
        this.#recordFatal(
            FATAL_TAG.ABORT_PC_OUTSIDE_STDERR,
            `run ${run.ordinal} emitted an abort-PC marker outside stderr`);
        return;
      }
      if (this.#activeRun !== run) {
        this.#invalidateAbortPcDiagnostic(run);
        this.#recordFatal(
            FATAL_TAG.ABORT_PC_INACTIVE,
            `run ${run.ordinal} emitted an abort-PC marker while inactive`);
        return;
      }
      if (this.#diagnosticMode !== DIAGNOSTIC_MODE_ABORT_PC) {
        this.#invalidateAbortPcDiagnostic(run);
        this.#recordFatal(
            FATAL_TAG.ABORT_PC_UNEXPECTED,
            `run ${run.ordinal} emitted an abort-PC marker outside diagnostic mode`);
        return;
      }
      if (run.abort !== null) {
        this.#invalidateAbortPcDiagnostic(run);
        this.#recordFatal(
            FATAL_TAG.ABORT_PC_AFTER_ABORT,
            `run ${run.ordinal} emitted an abort-PC marker after onAbort`);
        return;
      }
      if (run.abortPcMarkerObserved) {
        this.#invalidateAbortPcDiagnostic(run);
        this.#recordFatal(
            FATAL_TAG.ABORT_PC_DUPLICATE,
            `run ${run.ordinal} emitted a duplicate abort-PC marker`);
        return;
      }
      if (abortPcMarker === null) {
        this.#invalidateAbortPcDiagnostic(run);
        this.#recordFatal(
            FATAL_TAG.ABORT_PC_INVALID,
            `run ${run.ordinal} emitted a malformed abort-PC marker`);
        return;
      }
      run.abortPcMarkerObserved = true;
      run.abortPc = abortPcMarker.value;
      // A PC receipt after the logger interval closed cannot safely attribute
      // a prior headline to this later abort. Preserve only ambiguity.
      if (!run.fatalHeadlineCaptureOpen) {
        this.#markFatalHeadlineAmbiguous(run);
      }
      run.fatalHeadlineCaptureOpen = false;
      return;
    }
    // A phase line is diagnostic-only. It cannot advance or satisfy the
    // acceptance marker sequence, and its callback text is never retained.
    if (containsNativeDatabasePhase) {
      if (destination !== run.stderr) {
        this.#markFatalHeadlineAmbiguous(run);
        this.#recordFatal(
            FATAL_TAG.PHASE_OUTSIDE_STDERR,
            `run ${run.ordinal} emitted a database phase outside stderr`);
        return;
      }
      if (this.#activeRun !== run) {
        this.#markFatalHeadlineAmbiguous(run);
        this.#recordFatal(
            FATAL_TAG.PHASE_INACTIVE,
            `run ${run.ordinal} emitted a database phase while inactive`);
        return;
      }
      if (nativeDatabasePhase === null) {
        this.#markFatalHeadlineAmbiguous(run);
        this.#recordFatal(
            FATAL_TAG.PHASE_UNEXPECTED,
            `run ${run.ordinal} emitted an unknown or malformed database phase`);
        return;
      }
      const isFatalSourcePhase = FATAL_SOURCE_DATABASE_PHASES.includes(
          nativeDatabasePhase);
      if (isFatalSourcePhase) {
        // The source observer executes between the outer logger PRE and the
        // unchanged fatal headline. It is not a generic phase: require the
        // exact diagnostic interval so no normal artifact or later callback
        // can claim source-local provenance.
        if (this.#diagnosticMode !== DIAGNOSTIC_MODE_ABORT_PC ||
            !run.fatalHeadlineCaptureOpen || run.fatalHeadlineFinalized ||
            run.fatalHeadlineFamily !== null || run.fatalSourcePhaseObserved ||
            run.abortPcMarkerObserved || run.abort !== null ||
            run.abortPcDiagnosticInvalid) {
          this.#markFatalHeadlineAmbiguous(run);
          this.#invalidateAbortPcDiagnostic(run);
          this.#recordFatal(
              FATAL_TAG.PHASE_UNEXPECTED,
              `run ${run.ordinal} emitted a fatal-source phase outside its diagnostic interval`);
          return;
        }
        run.fatalSourcePhaseObserved = true;
        // The fixed phase precedes Chromium's raw headline. Close the raw
        // headline window now: raw text remains transient and only the fixed
        // native phase can enter a failure result.
        run.fatalHeadlineCaptureOpen = false;
        this.#markFatalHeadlineAmbiguous(run);
      } else if (nativeDatabasePhase === "task-post") {
        if (run.taskPostPhaseObserved) {
          this.#markFatalHeadlineAmbiguous(run);
          this.#recordFatal(
              FATAL_TAG.PHASE_UNEXPECTED,
              `run ${run.ordinal} emitted a duplicate task-post database phase`);
          return;
        }
        run.taskPostPhaseObserved = true;
      }
      if (nativeDatabasePhase === "task-complete") {
        if (run.taskCompletePhaseObserved) {
          this.#markFatalHeadlineAmbiguous(run);
          this.#recordFatal(
              FATAL_TAG.PHASE_UNEXPECTED,
              `run ${run.ordinal} emitted a duplicate task-complete database phase`);
          return;
        }
        run.taskCompletePhaseObserved = true;
      }
      if (nativeDatabasePhase === "leveldb-write-pre-dbimpl-construction") {
        if (run.secondFileExistsPostPhaseObserved) {
          this.#markFatalHeadlineAmbiguous(run);
          this.#recordFatal(
              FATAL_TAG.PHASE_UNEXPECTED,
              `run ${run.ordinal} emitted a pre-DBImpl phase after second FileExists post`);
          return;
        }
        if (run.preDbImplConstructionPhaseObserved) {
          this.#markFatalHeadlineAmbiguous(run);
          this.#recordFatal(
              FATAL_TAG.PHASE_UNEXPECTED,
              `run ${run.ordinal} emitted a duplicate pre-DBImpl phase`);
          return;
        }
        run.preDbImplConstructionPhaseObserved = true;
      }
      if (nativeDatabasePhase ===
          "leveldb-write-env-file-exists-second-post") {
        if (run.secondFileExistsPostPhaseObserved) {
          this.#markFatalHeadlineAmbiguous(run);
          this.#recordFatal(
              FATAL_TAG.PHASE_UNEXPECTED,
              `run ${run.ordinal} emitted a duplicate second FileExists post phase`);
          return;
        }
        run.secondFileExistsPostPhaseObserved = true;
        run.preDbImplConstructionObservedBeforeSecondFileExistsPost =
            run.preDbImplConstructionPhaseObserved;
      }
      if (nativeDatabasePhase === FATAL_HEADLINE_CAPTURE_PRE) {
        if (run.fatalHeadlineCaptureOpen || run.fatalHeadlineFinalized ||
            run.abortPcMarkerObserved || run.abort !== null ||
            run.abortPcDiagnosticInvalid) {
          this.#markFatalHeadlineAmbiguous(run);
        }
        run.fatalHeadlineCaptureOpen = !run.fatalHeadlineFinalized &&
            !run.abortPcMarkerObserved && run.abort === null &&
            !run.abortPcDiagnosticInvalid;
      } else if (nativeDatabasePhase === FATAL_HEADLINE_CAPTURE_POST) {
        if (!run.fatalHeadlineCaptureOpen) {
          this.#markFatalHeadlineAmbiguous(run);
        }
        // The wrapper is one-shot. A true CHECK/DCHECK abort cannot return to
        // emit its matching POST, so the first POST permanently makes every
        // present, absent, or later candidate non-attributable.
        this.#markFatalHeadlineAmbiguous(run);
        run.fatalHeadlineCaptureOpen = false;
      } else if (run.fatalHeadlineCaptureOpen) {
        // A different bounded phase ended the PRE interval without its
        // matching POST boundary. This is structural ambiguity only.
        run.fatalHeadlineCaptureOpen = false;
        this.#markFatalHeadlineAmbiguous(run);
      }
      // Keep one fixed enum only. It is exported solely through the exact
      // failure summary, never as successful-run evidence.
      run.nativeDatabasePhase = nativeDatabasePhase;
      if (nativeDatabasePhase === "task-post" ||
          nativeDatabasePhase === "task-complete") {
        // task-post is the UI/app sender's barrier; task-complete drains the
        // MayBlock sender. Both must arrive before lifecycle completion.
        this.#maybeCompleteRun(run);
      }
      return;
    }
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
    run.sameModuleAsPrior = run.ordinal === 1 ? null :
        this.#moduleObjects.at(-1) === module;
    if (run.sameModuleAsPrior) {
      this.#recordFatal(
          FATAL_TAG.RUNTIME_MODULE_REUSED,
          `run ${run.ordinal} reused its prior Module object`);
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
          "profile database process-exit report arrived without an active run");
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
      this.#invalidateAbortPcDiagnostic(run);
      this.#recordFatal(
          FATAL_TAG.ABORT_INVALID,
          `run ${run.ordinal} abort is duplicate or late`);
      return;
    }
    if (this.#diagnosticMode === DIAGNOSTIC_MODE_ABORT_PC &&
        !run.abortPcMarkerObserved) {
      this.#invalidateAbortPcDiagnostic(run);
      this.#recordFatal(
          FATAL_TAG.ABORT_PC_MISSING_BEFORE_ABORT,
          `run ${run.ordinal} aborted before its abort-PC marker`);
    }
    this.#finalizeFatalHeadline(run);
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
        run.taskPostPhaseObserved === true &&
        run.taskCompletePhaseObserved === true &&
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
    if (this.#diagnosticMode === DIAGNOSTIC_MODE_ABORT_PC &&
        this.#runIsCleanlyComplete(run) && this.#activeRun === run) {
      // This artifact is linked specifically to observe a native abort. A
      // clean three-module result would mean the diagnostic was never
      // exercised, so it must not be mistaken for the ordinary M7 acceptance.
      this.#recordFatal(
          FATAL_TAG.ABORT_PC_UNEXPECTED_CLEAN_EXIT,
          `run ${run.ordinal} exited cleanly in abort-PC diagnostic mode`);
      return;
    }
    if (!this.#runIsCleanlyComplete(run) || run.activeClearedAfterLifecycle ||
        this.#activeRun !== run) {
      return;
    }
    this.#activeRun = null;
    run.activeClearedAfterLifecycle = true;
    if (run.ordinal < 3) {
      this.#scheduleNextRun(run);
      return;
    }
    // Keep the immutable dispatcher live after run 3. The first timer marks
    // the native lifecycle boundary; a second, separate task starts a bounded
    // quiet window. A callback in this bounded pre-upload phase is rejected;
    // the acceptance deliberately makes no claim about callbacks after upload.
    this.#schedulePostLifecycleQuiescence(run);
  }

  #schedulePostLifecycleQuiescence(runThree) {
    const quiescence = this.#finalQuiescence;
    if (runThree.ordinal !== 3 || !runThree.activeClearedAfterLifecycle ||
        this.#activeRun !== null ||
        quiescence.callbacksAtRunThreeActiveClear !== null) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_RUN_THREE_LIFECYCLE,
          "final quiescence lacks a clean third-run lifecycle");
      return;
    }
    quiescence.callbacksAtRunThreeActiveClear = this.#callbackCount;
    quiescence.processExitReportsAtRunThreeActiveClear =
        this.#processExitReportCount;
    setTimeout(() => {
      runThree.postLifecycleTimerObserved = true;
      this.#scheduleFinalQuiescenceTask(runThree);
    }, 0);
  }

  #scheduleFinalQuiescenceTask(runThree) {
    const quiescence = this.#finalQuiescence;
    if (quiescence.taskScheduledExactlyOnce ||
        !runThree.postLifecycleTimerObserved || this.#activeRun !== null) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_TASK_SCHEDULING,
          "final quiescence task scheduling is invalid or duplicate");
      return;
    }
    quiescence.taskScheduledExactlyOnce = true;
    quiescence.taskMethod = "setTimeout(...,0)";
    quiescence.postLifecycleTimerObservedBeforeTask =
        runThree.postLifecycleTimerObserved;
    setTimeout(() => this.#startFinalQuiescence(runThree), 0);
  }

  #startFinalQuiescence(runThree) {
    const quiescence = this.#finalQuiescence;
    if (!quiescence.taskScheduledExactlyOnce || quiescence.started ||
        !quiescence.postLifecycleTimerObservedBeforeTask) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_TASK_START,
          "final quiescence task is invalid or duplicate");
      return;
    }
    quiescence.started = true;
    quiescence.startedAfterRunThreeActiveClear =
        runThree.activeClearedAfterLifecycle && this.#activeRun === null;
    quiescence.callbacksAtTaskStart = this.#callbackCount;
    quiescence.activeRunAtTaskStart =
        this.#activeRun === null ? null : this.#activeRun.ordinal;
    if (!quiescence.startedAfterRunThreeActiveClear ||
        quiescence.callbacksAtTaskStart !==
            quiescence.callbacksAtRunThreeActiveClear ||
        this.#processExitReportCount !==
            quiescence.processExitReportsAtRunThreeActiveClear) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_ACTIVITY_BEFORE_START,
          "activity occurred before final quiescence began");
      return;
    }
    setTimeout(() => this.#finishFinalQuiescence(runThree), FINAL_QUIESCENCE_MS);
  }

  #finishFinalQuiescence(runThree) {
    const quiescence = this.#finalQuiescence;
    if (!quiescence.started || quiescence.completed || runThree.ordinal !== 3) {
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
        quiescence.callbacksAtRunThreeActiveClear ===
            quiescence.callbacksAtTaskStart &&
        quiescence.callbacksAtTaskStart === quiescence.callbacksAtTaskEnd &&
        quiescence.processExitReportsAtRunThreeActiveClear ===
            quiescence.processExitReportsAtTaskEnd;
    quiescence.completed = true;
    if (!quiescence.quiet) {
      this.#recordFatal(
          FATAL_TAG.QUIESCENCE_NOT_QUIET,
          "final quiescence observed a delayed callback or output");
    }
    this.#completionResolver();
  }

  #scheduleNextRun(previousRun) {
    const nextOrdinal = previousRun.ordinal + 1;
    if (nextOrdinal !== 2 && nextOrdinal !== 3) {
      this.#recordFatal(
          FATAL_TAG.RUN_NEXT_SCHEDULING,
          "next run ordinal is invalid");
      return;
    }
    const scheduled = nextOrdinal === 2 ?
        this.#runTwoScheduledExactlyOnce : this.#runThreeScheduledExactlyOnce;
    if (scheduled || !previousRun.activeClearedAfterLifecycle) {
      this.#recordFatal(
          FATAL_TAG.RUN_NEXT_SCHEDULING,
          `run ${nextOrdinal} scheduling is duplicate or lacks prior cleanup`);
      return;
    }
    const afterNativeExit = previousRun.processExitCode === 0 &&
        previousRun.processExitCount === 1 && previousRun.processExitBeforeOnExit &&
        this.#markersComplete(previousRun);
    const afterOnExit = previousRun.runtimeExitCode === 0 &&
        previousRun.onExitCount === 1;
    if (nextOrdinal === 2) {
      this.#runTwoScheduledExactlyOnce = true;
      this.#runTwoScheduleMethod = "setTimeout(...,0)";
      this.#runTwoScheduledAfterRunOneNativeExit = afterNativeExit;
      this.#runTwoScheduledAfterRunOneOnExit = afterOnExit;
    } else {
      this.#runThreeScheduledExactlyOnce = true;
      this.#runThreeScheduleMethod = "setTimeout(...,0)";
      this.#runThreeScheduledAfterRunTwoNativeExit = afterNativeExit;
      this.#runThreeScheduledAfterRunTwoOnExit = afterOnExit;
    }
    if (!afterNativeExit || !afterOnExit) {
      this.#recordFatal(
          FATAL_TAG.RUN_NEXT_BEFORE_LIFECYCLE,
          `run ${nextOrdinal} was scheduled before prior lifecycle completed`);
      return;
    }
    setTimeout(() => {
      previousRun.postLifecycleTimerObserved = true;
      const startedAfterActiveClear = this.#activeRun === null &&
          previousRun.activeClearedAfterLifecycle;
      if (nextOrdinal === 2) {
        this.#runTwoTimerFired = true;
        this.#runTwoStartedAfterRunOneActiveClear = startedAfterActiveClear;
      } else {
        this.#runThreeTimerFired = true;
        this.#runThreeStartedAfterRunTwoActiveClear = startedAfterActiveClear;
      }
      if (!startedAfterActiveClear) {
        this.#recordFatal(
            FATAL_TAG.RUN_NEXT_TIMER_BEFORE_CLEAR,
            `run ${nextOrdinal} timer fired before prior active state cleared`);
        return;
      }
      this.#startRun(nextOrdinal, "setTimeout-0");
    }, 0);
  }

  #locateFileForWasm(wasmUrl, path) {
    if (typeof path !== "string" ||
        path !== `${this.#artifact.module_name}.wasm`) {
      throw new Error("profile database loader requested an unexpected artifact");
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
      "--wasm-profile-database-smoke=write-a",
      `--wasm-profile-database-token-a=${this.#rawTokens.runOne}`,
    ] : ordinal === 2 ? [
      "--wasm-profile-database-smoke=verify-a-write-b",
      `--wasm-profile-database-token-a=${this.#rawTokens.runOne}`,
      `--wasm-profile-database-token-b=${this.#rawTokens.runTwo}`,
    ] : [
      "--wasm-profile-database-smoke=verify-b",
      `--wasm-profile-database-token-b=${this.#rawTokens.runTwo}`,
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
        quiescence.processExitDispatchesAtPreUploadCheck === 3 &&
        quiescence.rejectedProcessExitReportsAtPreUploadCheck === 0 &&
        this.#fatalErrors.length === 0 && this.#windowErrors.length === 0 &&
        this.#unhandledRejections.length === 0 && !this.#rawTokenLeakDetected;
    if (!clean) {
      this.#recordFatal(
          FATAL_TAG.RESULT_UPLOAD_RECHECK,
          "final bridge recheck rejected result upload");
      result.status = "fail";
      result.sqliteLevelDbGracefulCloseReopenProven = false;
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
    // This is a private receipt barrier only. Keep the public schema limited
    // to its existing nullable structural fields: invalid marker/onAbort
    // traffic cannot retain a believable native-abort observation.
    const acceptedAbortPcDiagnostic =
        latestRun?.abortPcDiagnosticInvalid !== true;
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status: "fail",
      failureClass: this.#failureClass ?? "host-exception",
      firstFatalTag: this.#firstFatalTag,
      // `null` is the accepted native `unavailable` outcome (or no valid
      // marker on an already-invalid failure). The private receipt bit is
      // intentionally not serialized.
      abortPc: latestRun?.abortPc ?? null,
      // This records only a fixed headline family after an accepted abort-PC
      // receipt. It is diagnostic provenance, not source attribution or
      // acceptance evidence; raw source, line, suffix, and message are never
      // retained in this schema.
      fatalHeadline: this.#fatalHeadlineSummary(latestRun),
      abortReasonKind: acceptedAbortPcDiagnostic ?
          latestRun?.abortReasonKind ?? null : null,
      abortObservationOrder: acceptedAbortPcDiagnostic ?
          latestRun?.abortObservationOrder ?? null : null,
      nativeFailureStage: this.#nativeFailureStage,
      // This is a validated fixed enum, not native callback text. Successful
      // snapshots intentionally omit it.
      nativeDatabasePhase: latestRun?.nativeDatabasePhase ?? null,
      // This fixed nullable boolean captures only phase ordering; it never
      // exposes a path, a FileExists result, or native callback text.
      preDbImplConstructionObservedBeforeSecondFileExistsPost:
          latestRun?.preDbImplConstructionObservedBeforeSecondFileExistsPost ??
          null,
      lifecycle: {
        acceptedProcessExitCount: boundedFailureCount(
            this.#bridgeProcessExitDispatches, 3),
        activeRunPresent: this.#activeRun !== null,
        bridgeInstalled: this.#bridgeInstalled,
        bridgeInstalledBeforeModuleFactory:
            this.#bridgeInstalledBeforeModuleFactory,
        callbackCount: boundedFailureCount(
            this.#callbackCount, MAX_FAILURE_CALLBACK_COUNT),
        factoryCalls: boundedFailureCount(this.#factoryCalls, 3),
        finalQuiescenceCompleted: this.#finalQuiescence.completed,
        lastProcessExitCode: boundedFailureExitCode(
            latestRun?.processExitCode),
        lastRuntimeExitCode: boundedFailureExitCode(latestRun?.runtimeExitCode),
        leaseReleasedRunCount: boundedFailureCount(leaseReleasedRunCount, 3),
        onExitCount: boundedFailureCount(onExitCount, 3),
        processExitReportCount: boundedFailureCount(
            this.#processExitReportCount, MAX_FAILURE_PROCESS_EXIT_REPORT_COUNT),
        rawTokenLeakDetected: this.#rawTokenLeakDetected,
        runCount: boundedFailureCount(this.#runs.length, 3),
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
      preferencesRoundTripProven: false,
      sqliteLevelDbGracefulCloseReopenProven: status === "pass",
      sqliteLevelDbCrashRecoveryProven: false,
      directoryDurabilityProven: false,
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
        runThreeScheduledExactlyOnce: this.#runThreeScheduledExactlyOnce,
        runThreeScheduleMethod: this.#runThreeScheduleMethod,
        runThreeTimerFired: this.#runThreeTimerFired,
        runThreeScheduledAfterRunTwoNativeExit:
            this.#runThreeScheduledAfterRunTwoNativeExit,
        runThreeScheduledAfterRunTwoOnExit:
            this.#runThreeScheduledAfterRunTwoOnExit,
        runThreeStartedAfterRunTwoActiveClear:
            this.#runThreeStartedAfterRunTwoActiveClear,
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
        throw new Error("profile database smoke requires cross-origin isolation");
      }
      if (typeof location.origin !== "string" || location.origin === "null") {
        throw new Error("profile database smoke requires a concrete same-origin URL");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("profile database canvas did not accept focus");
      }
      await this.#prepareTokens();
      this.#installPermanentBridge();
      this.#captureWindowErrors();
      await this.#prepareFactory(context.moduleName);
      this.#startRun(1, "initial");

      const deadline = this.#startedAt + context.timeoutMs;
      while (performance.now() < deadline) {
        if (this.#fatalErrors.length !== 0) {
          throw new Error("profile database host recorded a lifecycle failure");
        }
        if (this.#runs.length === 3 && this.#finalQuiescence.completed) {
          await this.#completionPromise;
          break;
        }
        await delay(10);
      }
      if (this.#runs.length !== 3 || !this.#runs[2].postLifecycleTimerObserved ||
          !this.#finalQuiescence.completed || !this.#finalQuiescence.quiet) {
        this.#recordFailureClass("host-timeout");
        throw new Error("profile database three-module lifecycle timed out");
      }
      if (this.#fatalErrors.length !== 0 || this.#windowErrors.length !== 0 ||
          this.#unhandledRejections.length !== 0 || this.#rawTokenLeakDetected) {
        throw new Error("profile database host observed an error after lifecycle completion");
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
  require(run.mode === (["write-a", "verify-a-write-b", "verify-b"][ordinal - 1]),
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
    require(!run.stdout.concat(run.stderr).some((line) =>
        line.includes(M7_DATABASE_PHASE_PREFIX)),
    `run ${ordinal} serialized database phase telemetry`);
    require(!run.stdout.concat(run.stderr).some((line) =>
        line.includes(M7_ABORT_PC_PREFIX)),
    `run ${ordinal} serialized abort-PC telemetry`);
    const stderrMarkers = markerLines(run.stderr);
    require(stderrMarkers.length === expected.length &&
        stderrMarkers.every((marker, index) => marker === expected[index]),
    `run ${ordinal} stderr M7 marker evidence is invalid`);
    require(!run.stderr.some((line) =>
        line.includes(M7_MARKER_PREFIX) && !expected.includes(line)),
    `run ${ordinal} stderr contains an unknown or malformed M7 marker`);
    const output = run.stdout.concat(run.stderr);
    require(!output.some((line) => line.includes(`${M7_MARKER_PREFIX}FAIL`) ||
                             line.includes("--wasm-profile-database-token")),
    `run ${ordinal} leaked a failure or private token switch`);
  }
}

export function validateChromeWasmProfileDatabaseResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) failures.push(message);
  };
  const fields = [
    "protocol", "case", "scope", "status", "m7GateComplete", "limitations",
    "artifact", "capture_harness", "versions", "origin", "crossOriginIsolated",
    "sharedArrayBuffer", "sameOriginDocument", "preferencesRoundTripProven",
    "sqliteLevelDbGracefulCloseReopenProven", "sqliteLevelDbCrashRecoveryProven",
    "directoryDurabilityProven", "cookiesHistoryBookmarksSessionsProven",
    "webStorageAndServiceWorkerProven", "concurrentProfileContenderProven",
    "factoryCalls", "bridge", "transition", "finalQuiescence", "tokenEvidence", "hostBoundary",
    "runs", "fatalErrors", "windowErrors", "unhandledRejections", "failedChecks",
    "error",
  ];
  require(hasExactFields(result, fields), "profile database result schema is invalid");
  if (!hasExactFields(result, fields)) return result;
  require(result.protocol === HOST_PROTOCOL && result.case === CASE &&
      result.scope === SCOPE && result.status === "pass" &&
      result.m7GateComplete === false,
  "profile database result identity is invalid");
  require(Array.isArray(result.limitations) && result.limitations.length === LIMITATIONS.length &&
      result.limitations.every((value, index) => value === LIMITATIONS[index]),
  "profile database limitations are invalid");
  require(result.crossOriginIsolated === true && result.sharedArrayBuffer === true &&
      result.sameOriginDocument === true && typeof result.origin === "string" &&
      result.origin === location.origin,
  "profile database host context is invalid");
  require(result.preferencesRoundTripProven === false &&
      result.sqliteLevelDbGracefulCloseReopenProven === true &&
      result.sqliteLevelDbCrashRecoveryProven === false &&
      result.directoryDurabilityProven === false &&
      result.cookiesHistoryBookmarksSessionsProven === false &&
      result.webStorageAndServiceWorkerProven === false &&
      result.concurrentProfileContenderProven === false,
  "profile database scope claims are invalid");
  require(result.factoryCalls === 3, "profile database factory call count is invalid");
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
  "profile database token evidence is invalid");
  const bridgeFields = [
    "protocol", "permanent", "frozen", "installedBeforeModuleFactory",
    "processExitDispatches", "noActiveProcessExitRejected",
    "duplicateProcessExitRejected", "lateProcessExitRejected", "activeRunAtResult",
  ];
  require(hasExactFields(result.bridge, bridgeFields) && result.bridge.protocol === HOST_PROTOCOL &&
      result.bridge.permanent === true && result.bridge.frozen === true &&
      result.bridge.installedBeforeModuleFactory === true &&
      result.bridge.processExitDispatches === 3 &&
      result.bridge.noActiveProcessExitRejected === 0 &&
      result.bridge.duplicateProcessExitRejected === 0 &&
      result.bridge.lateProcessExitRejected === 0 && result.bridge.activeRunAtResult === null,
  "profile database bridge lifecycle is invalid");
  const transitionFields = [
    "runTwoScheduledExactlyOnce", "runTwoScheduleMethod", "runTwoTimerFired",
    "runTwoScheduledAfterRunOneNativeExit", "runTwoScheduledAfterRunOneOnExit",
    "runTwoStartedAfterRunOneActiveClear",
    "runThreeScheduledExactlyOnce", "runThreeScheduleMethod", "runThreeTimerFired",
    "runThreeScheduledAfterRunTwoNativeExit", "runThreeScheduledAfterRunTwoOnExit",
    "runThreeStartedAfterRunTwoActiveClear",
  ];
  require(hasExactFields(result.transition, transitionFields) &&
      result.transition.runTwoScheduledExactlyOnce === true &&
      result.transition.runTwoScheduleMethod === "setTimeout(...,0)" &&
      result.transition.runTwoTimerFired === true &&
      result.transition.runTwoScheduledAfterRunOneNativeExit === true &&
      result.transition.runTwoScheduledAfterRunOneOnExit === true &&
      result.transition.runTwoStartedAfterRunOneActiveClear === true &&
      result.transition.runThreeScheduledExactlyOnce === true &&
      result.transition.runThreeScheduleMethod === "setTimeout(...,0)" &&
      result.transition.runThreeTimerFired === true &&
      result.transition.runThreeScheduledAfterRunTwoNativeExit === true &&
      result.transition.runThreeScheduledAfterRunTwoOnExit === true &&
      result.transition.runThreeStartedAfterRunTwoActiveClear === true,
  "profile database three-module transition is invalid");
  const finalQuiescence = result.finalQuiescence;
  require(hasExactFields(finalQuiescence, FINAL_QUIESCENCE_FIELDS) &&
      finalQuiescence.taskScheduledExactlyOnce === true &&
      finalQuiescence.taskMethod === "setTimeout(...,0)" &&
      finalQuiescence.postLifecycleTimerObservedBeforeTask === true &&
      finalQuiescence.started === true &&
      finalQuiescence.startedAfterRunThreeActiveClear === true &&
      finalQuiescence.completed === true &&
      finalQuiescence.quietWindowMs === FINAL_QUIESCENCE_MS &&
      finalQuiescence.quiet === true &&
      finalQuiescence.bridgeRecheckedImmediatelyBeforeUpload === true &&
      finalQuiescence.activeRunAtTaskStart === null &&
      finalQuiescence.activeRunAtTaskEnd === null &&
      finalQuiescence.activeRunAtPreUploadCheck === null &&
      Number.isSafeInteger(finalQuiescence.callbacksAtRunThreeActiveClear) &&
      finalQuiescence.callbacksAtRunThreeActiveClear >= 0 &&
      finalQuiescence.callbacksAtRunThreeActiveClear ===
          finalQuiescence.callbacksAtTaskStart &&
      finalQuiescence.callbacksAtTaskStart === finalQuiescence.callbacksAtTaskEnd &&
      finalQuiescence.callbacksAtTaskEnd ===
          finalQuiescence.callbacksAtPreUploadCheck &&
      finalQuiescence.processExitReportsAtRunThreeActiveClear === 3 &&
      finalQuiescence.processExitReportsAtTaskEnd === 3 &&
      finalQuiescence.processExitReportsAtPreUploadCheck === 3 &&
      finalQuiescence.processExitDispatchesAtPreUploadCheck === 3 &&
      finalQuiescence.rejectedProcessExitReportsAtPreUploadCheck === 0,
  "profile database final bridge quiescence is invalid");
  const boundaryFields = [
    "hostOpfsAccessAttempted", "hostWebLocksAccessAttempted", "nativeCallAttempted",
    "wasmDataInspectionAttempted",
  ];
  require(hasExactFields(result.hostBoundary, boundaryFields) &&
      Object.values(result.hostBoundary).every((value) => value === false),
  "profile database host boundary is invalid");
  require(Array.isArray(result.runs) && result.runs.length === 3,
      "profile database must report exactly three runs");
  if (Array.isArray(result.runs) && result.runs.length === 3 &&
      result.tokenEvidence && SHA256_RE.test(result.tokenEvidence.runOne) &&
      SHA256_RE.test(result.tokenEvidence.runTwo)) {
    validateRun(result.runs[0], 1, result.tokenEvidence, failures);
    validateRun(result.runs[1], 2, result.tokenEvidence, failures);
    validateRun(result.runs[2], 3, result.tokenEvidence, failures);
    require(new Set(result.runs.map((run) => run.moduleIdentity)).size === 3,
        "profile database runs reused a module identity");
  }
  require(Array.isArray(result.fatalErrors) && result.fatalErrors.length === 0 &&
      Array.isArray(result.windowErrors) && result.windowErrors.length === 0 &&
      Array.isArray(result.unhandledRejections) && result.unhandledRejections.length === 0 &&
      Array.isArray(result.failedChecks) && result.failedChecks.length === 0 &&
      result.error === null,
  "profile database host recorded an error");
  if (failures.length !== 0) {
    result.status = "fail";
    result.failedChecks = failures;
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmProfileDatabaseFromQuery() {
  const context = parseStaticContext();
  const root = document.querySelector("#m7-profile-database-root");
  const canvas = document.querySelector("#m7-profile-database-canvas");
  const status = document.querySelector("#m7-profile-database-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("profile database page is missing required elements");
  }
  renderVersions(document.querySelector("#m7-profile-database-versions"),
                 context.versions);
  const host = new ChromeWasmProfileDatabaseHost(canvas, status, context);
  let result = await host.run(context);
  if (result.status === "pass") {
    // This runs synchronously in the continuation immediately before schema
    // validation and result upload, after the bounded quiet window ended.
    result = host.recheckBeforeResultUpload(result);
    result = validateChromeWasmProfileDatabaseResult(result);
    if (result.status !== "pass") {
      result = host.failureSummary("host-result-validation");
    }
  } else {
    result = host.failureSummary();
  }
  if (result.status !== "pass") {
    result = validateChromeWasmProfileDatabaseFailureSummary(result);
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
    throw new Error(`profile database result upload returned HTTP ${response.status}`);
  }
  if (result.status !== "pass") {
    throw new Error("profile database result validation failed");
  }
  return result;
}

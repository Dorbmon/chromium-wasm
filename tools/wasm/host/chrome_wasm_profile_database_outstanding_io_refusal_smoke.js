// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Observe the source-selected M7 control-plane refusal that occurs when an
// admitted profile-I/O hold remains live after ContentMain, followed by its
// separate explicit fail-closed cleanup. The host only delivers immutable
// artifacts and records a redacted receipt. It never opens OPFS, requests a
// Web Lock, calls native code, or reads Wasm memory.

const HOST_PROTOCOL = 1;
const CASE = "chrome_profile_database_outstanding_io_refusal_m7";
const SCOPE =
    "same-origin-same-document-one-fresh-chrome-wasm-m7-profile-database-outstanding-io-refusal-verify-b-outstanding-profile-io-refusal-then-fail-closed-cleanup";
const PRODUCT_MODULE_NAME =
    "chrome_wasm_m7_profile_database_outstanding_io_refusal_test";
const M7_DATABASE_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:";
const M7_DATABASE_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
const FAILURE_RETIREMENT_MARKER_PREFIX =
    "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:";
const FAILURE_RETIREMENT_MARKER =
    "CHROMIUM_WASM_M7_PROFILE_FAILURE_RETIREMENT:SEALED_LEASE_RETAINED";
const DRAIN_REFUSAL_MARKER =
    "CHROMIUM_WASM_M7_PROFILE_DRAIN_REFUSED:OUTSTANDING_IO";
const EXPECTED_DATABASE_MARKERS = Object.freeze([
  `${M7_DATABASE_MARKER_PREFIX}READY`,
  `${M7_DATABASE_MARKER_PREFIX}FAIL stage=database`,
]);
const EXPECTED_DATABASE_PHASES = Object.freeze([
  "task-post", "task-started", "sqlite-read", "task-complete",
]);
const EXPECTED_EVENT_SEQUENCE = Object.freeze([
  EXPECTED_DATABASE_MARKERS[0],
  ...EXPECTED_DATABASE_PHASES.map((phase) => `${M7_DATABASE_PHASE_PREFIX}${phase}`),
  EXPECTED_DATABASE_MARKERS[1],
  DRAIN_REFUSAL_MARKER,
  FAILURE_RETIREMENT_MARKER,
]);
const MAX_TIMEOUT_MS = 300000;
const MIN_TIMEOUT_MS = 20000;
const MAX_OUTPUT_LINES = 128;
const FINAL_QUIESCENCE_MS = 50;
const MAX_BUILD_CONFIG_BYTES = 64 * 1024;
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
const VERSION_FIELDS = Object.freeze(["chromium", "emscripten", "v8"]);
const PARENT_PRODUCT_GN_ENABLE_ASSIGNMENT =
    "enable_chromium_wasm_m7_profile_database_test";
const PRODUCT_GN_ENABLE_ASSIGNMENT =
    "enable_chromium_wasm_m7_profile_database_outstanding_io_refusal_test";

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

function parseVersions(value) {
  const versions = requireExactFields(parseJson(value, "versions"), VERSION_FIELDS,
                                      "versions");
  if (!VERSION_FIELDS.every((field) => typeof versions[field] === "string" &&
      /^[0-9a-f]{40}$/.test(versions[field]))) {
    throw new Error("versions are invalid");
  }
  return Object.freeze({...versions});
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
    host_js: parseByteIdentity(harness.host_js, "host JS"),
    runner_source: parseByteIdentity(harness.runner_source, "runner source"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseBuildConfig(value) {
  if (typeof value !== "string" || value.length === 0 ||
      value.length > Math.ceil(MAX_BUILD_CONFIG_BYTES * 4 / 3) + 4 ||
      !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error("build config is invalid");
  }
  let binary;
  try {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + padding);
  } catch (_error) {
    throw new Error("build config is invalid");
  }
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_BUILD_CONFIG_BYTES) {
    throw new Error("build config is invalid");
  }
  let text;
  try {
    text = new TextDecoder("utf-8", {fatal: true, ignoreBOM: true}).decode(bytes);
  } catch (_error) {
    throw new Error("build config is invalid");
  }
  return {bytes, text};
}

function hasEnabledGnAssignment(text, assignment) {
  const expression = new RegExp(
      `^[\\t ]*${assignment}[\\t ]*=[\\t ]*(true|false)[\\t ]*(?:#.*)?$`, "gm");
  let found = false;
  for (const match of text.matchAll(expression)) {
    if (match[1] !== "true") return false;
    found = true;
  }
  return found;
}

function parseContext() {
  const query = new URLSearchParams(location.search);
  const fields = Object.freeze([
    "resultToken", "session", "module", "timeoutMs", "versions", "artifact",
    "captureHarness", "buildConfig",
  ]);
  if ([...query.keys()].length !== fields.length ||
      !fields.every((field) => query.getAll(field).length === 1)) {
    throw new Error("outstanding-I/O refusal query is invalid");
  }
  const resultToken = query.get("resultToken");
  const session = query.get("session");
  const moduleName = query.get("module");
  const timeoutText = query.get("timeoutMs");
  if (typeof resultToken !== "string" || !CAPABILITY_RE.test(resultToken) ||
      typeof session !== "string" || !CAPABILITY_RE.test(session) ||
      resultToken === session || moduleName !== PRODUCT_MODULE_NAME ||
      typeof timeoutText !== "string" || !/^[0-9]+$/.test(timeoutText)) {
    throw new Error("outstanding-I/O refusal query is invalid");
  }
  const timeoutMs = Number(timeoutText);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("outstanding-I/O refusal timeout is invalid");
  }
  const artifact = parseArtifact(query.get("artifact"));
  return Object.freeze({
    artifact,
    buildConfig: parseBuildConfig(query.get("buildConfig")),
    captureHarness: parseCaptureHarness(query.get("captureHarness")),
    moduleName,
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
  let digest;
  try {
    digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  } catch (_error) {
    throw new Error(`${description} hash failed`);
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
  if (!response.ok || response.url !== url.href ||
      response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
          contentType || response.headers.get("cache-control") !== "no-store" ||
      response.headers.get("cross-origin-embedder-policy") !== "require-corp" ||
      response.headers.get("cross-origin-opener-policy") !== "same-origin" ||
      response.headers.get("cross-origin-resource-policy") !== "same-origin" ||
      response.headers.get("referrer-policy") !== "no-referrer" ||
      response.headers.get("x-content-type-options") !== "nosniff") {
    throw new Error(`${description} response is invalid`);
  }
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

function exactNonzeroExitStatus(value) {
  try {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const fields = Object.freeze(["name", "status", "message"]);
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

class ChromeWasmProfileDatabaseOutstandingIORefusalHost {
  #artifact;
  #bridgeInstalled = false;
  #bridgeInstalledBeforeModuleFactory = false;
  #bridgeProcessExitDispatches = 0;
  #buildConfigValidated = false;
  #callbackCount = 0;
  #canvas;
  #captureHarness;
  #context;
  #factory = null;
  #factoryExitStatusCode = null;
  #factoryModule = null;
  #failure = false;
  #finalQuiescence = {
    callbacksAtEnd: null,
    callbacksAtPreUploadCheck: null,
    callbacksAtStart: null,
    completed: false,
    quiet: false,
    quietWindowMs: FINAL_QUIESCENCE_MS,
    started: false,
  };
  #loaderImportUrl = null;
  #mainScriptUrlOrBlob = null;
  #moduleStarted = false;
  #rawToken = null;
  #rawTokenLeakDetected = false;
  #rawTokenRedactionCount = 0;
  #rawTokenTail = "";
  #runtimeModule = null;
  #run = {
    abortObserved: false,
    databaseFailureMarkerObserved: false,
    drainRefusalMarkerCount: 0,
    drainRefusalMarkerObserved: false,
    eventSequence: [],
    factoryRejectedExpectedExitStatus: false,
    factoryRejectedUnexpected: false,
    factoryResolved: false,
    factorySettled: false,
    leaseReleasedMarkerObserved: false,
    markerSequenceAccepted: true,
    markers: [],
    mode: "verify-b",
    moduleIdentity: null,
    onExitCount: 0,
    outputLineCount: 0,
    phases: [],
    processExitCode: null,
    processExitCount: 0,
    retirementMarkerCount: 0,
    retirementMarkerObserved: false,
    runtimeExitCode: null,
    runtimeInitialized: false,
    stdoutMarkerCount: 0,
  };
  #status;
  #tokenDigest = null;
  #unhandledRejectionCount = 0;
  #unhandledRejectionHandler;
  #versions;
  #wasmBinary = null;
  #wasmUrl = null;
  #windowErrorCount = 0;
  #windowErrorHandler;
  #fatalCallbackCount = 0;

  constructor(canvas, status, context) {
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement)) {
      throw new Error("outstanding-I/O refusal page is invalid");
    }
    this.#artifact = context.artifact;
    this.#canvas = canvas;
    this.#captureHarness = context.captureHarness;
    this.#context = context;
    this.#status = status;
    this.#versions = context.versions;
  }

  #markFailure() { this.#failure = true; }

  #noteCallback() { this.#callbackCount += 1; }

  #observeText(value, trackAcrossCallbacks = false) {
    if (typeof value !== "string" || this.#rawToken === null) return;
    const candidate = trackAcrossCallbacks ? this.#rawTokenTail + value : value;
    if (candidate.includes(this.#rawToken)) {
      this.#rawTokenLeakDetected = true;
      this.#rawTokenRedactionCount += 1;
      this.#markFailure();
    }
    if (trackAcrossCallbacks) this.#rawTokenTail = candidate.slice(-63);
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("outstanding-I/O refusal bridge is already installed");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.#noteCallback();
        host.#fatalCallbackCount += 1;
        host.#observeText(message, true);
        host.#markFailure();
      },
      reportProcessExit(report) { host.#routeProcessExit(report); },
      reportFrame(_report) { host.#noteCallback(); },
      reportReadiness(_report) { host.#noteCallback(); },
      reportOzoneFocusState(_report) { host.#noteCallback(); },
      reportOzoneCursor(_report) {
        host.#noteCallback();
        return true;
      },
      reportOzoneTextInputState(_report) { host.#noteCallback(); },
      reportOzoneTextInputDelivery(_report) { host.#noteCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) { host.#noteCallback(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) { host.#noteCallback(); },
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
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge || !Object.isFrozen(bridge)) {
      throw new Error("outstanding-I/O refusal bridge is mutable");
    }
    this.#bridgeInstalled = true;
  }

  #captureExternalFailures() {
    this.#windowErrorHandler = (event) => {
      this.#noteCallback();
      this.#windowErrorCount += 1;
      this.#observeText(typeof event.message === "string" ? event.message : "", true);
      this.#markFailure();
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#noteCallback();
      this.#unhandledRejectionCount += 1;
      let reason = null;
      try {
        reason = event.reason;
      } catch (_error) {}
      this.#observeText(typeof reason === "string" ? reason : "", true);
      this.#markFailure();
    };
    addEventListener("error", this.#windowErrorHandler);
    addEventListener("unhandledrejection", this.#unhandledRejectionHandler);
  }

  async #validateBuildConfig() {
    const buildConfig = this.#context.buildConfig;
    if (buildConfig.bytes.byteLength !== this.#artifact.build_config.bytes ||
        await sha256Hex(buildConfig.bytes, "build config") !==
            this.#artifact.build_config.sha256 ||
        !hasEnabledGnAssignment(
            buildConfig.text, PARENT_PRODUCT_GN_ENABLE_ASSIGNMENT) ||
        !hasEnabledGnAssignment(buildConfig.text, PRODUCT_GN_ENABLE_ASSIGNMENT)) {
      throw new Error("build config is invalid");
    }
    this.#buildConfigValidated = true;
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

  #acceptExpectedEvent(line) {
    const expected = EXPECTED_EVENT_SEQUENCE[this.#run.eventSequence.length];
    if (line !== expected) {
      this.#run.markerSequenceAccepted = false;
      this.#markFailure();
      return false;
    }
    this.#run.eventSequence.push(line);
    return true;
  }

  #captureOutput(destination, line) {
    this.#noteCallback();
    this.#run.outputLineCount += 1;
    if (this.#run.outputLineCount > MAX_OUTPUT_LINES || typeof line !== "string") {
      this.#markFailure();
      return;
    }
    this.#observeText(line, true);
    const isRelevant = line.startsWith(M7_DATABASE_MARKER_PREFIX) ||
        line.startsWith(M7_DATABASE_PHASE_PREFIX) ||
        line.startsWith(FAILURE_RETIREMENT_MARKER_PREFIX) ||
        line.startsWith("CHROMIUM_WASM_M7_PROFILE_DRAIN_REFUSED:");
    if (destination !== "stderr") {
      if (isRelevant) {
        this.#run.stdoutMarkerCount += 1;
        this.#markFailure();
      }
      return;
    }
    if (line.startsWith(FAILURE_RETIREMENT_MARKER_PREFIX)) {
      if (line !== FAILURE_RETIREMENT_MARKER || this.#run.retirementMarkerObserved ||
          !this.#acceptExpectedEvent(line)) {
        this.#markFailure();
        return;
      }
      this.#run.retirementMarkerCount += 1;
      this.#run.retirementMarkerObserved = true;
      this.#maybeComplete();
      return;
    }
    if (line.startsWith("CHROMIUM_WASM_M7_PROFILE_DRAIN_REFUSED:")) {
      if (line !== DRAIN_REFUSAL_MARKER || this.#run.drainRefusalMarkerObserved ||
          !this.#acceptExpectedEvent(line)) {
        this.#markFailure();
        return;
      }
      this.#run.drainRefusalMarkerObserved = true;
      this.#run.drainRefusalMarkerCount += 1;
      this.#maybeComplete();
      return;
    }
    if (line.startsWith(M7_DATABASE_PHASE_PREFIX)) {
      const phase = line.slice(M7_DATABASE_PHASE_PREFIX.length);
      const expected = EXPECTED_DATABASE_PHASES[this.#run.phases.length];
      if (phase !== expected || !this.#acceptExpectedEvent(line)) {
        this.#markFailure();
        return;
      }
      this.#run.phases.push(phase);
      this.#maybeComplete();
      return;
    }
    if (line.startsWith(M7_DATABASE_MARKER_PREFIX)) {
      if (line === `${M7_DATABASE_MARKER_PREFIX}LEASE_RELEASED`) {
        this.#run.leaseReleasedMarkerObserved = true;
        this.#markFailure();
        return;
      }
      const expected = EXPECTED_DATABASE_MARKERS[this.#run.markers.length];
      if (line !== expected || !this.#acceptExpectedEvent(line)) {
        this.#run.markerSequenceAccepted = false;
        this.#markFailure();
        return;
      }
      this.#run.markers.push(line);
      if (line === EXPECTED_DATABASE_MARKERS[1]) {
        this.#run.databaseFailureMarkerObserved = true;
      }
      this.#maybeComplete();
      return;
    }
  }

  #routeProcessExit(report) {
    this.#noteCallback();
    if (!this.#moduleStarted || this.#run.processExitCount !== 0 ||
        this.#run.onExitCount !== 0 || !hasExactFields(report, ["protocol", "exitCode"]) ||
        report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.exitCode) ||
        report.exitCode <= 0 || report.exitCode > 255) {
      this.#markFailure();
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
      this.#markFailure();
      return;
    }
    this.#runtimeModule = module;
    this.#run.runtimeInitialized = true;
    this.#maybeComplete();
  }

  #reportRuntimeExit(code) {
    this.#noteCallback();
    if (!Number.isSafeInteger(code) || code <= 0 || code > 255 ||
        this.#run.onExitCount !== 0 || this.#run.processExitCount !== 1 ||
        this.#run.processExitCode !== code) {
      this.#markFailure();
      return;
    }
    this.#run.onExitCount = 1;
    this.#run.runtimeExitCode = code;
    this.#maybeComplete();
  }

  #reportAbort(reason) {
    this.#noteCallback();
    this.#observeText(typeof reason === "string" ? reason : "", true);
    this.#run.abortObserved = true;
    this.#markFailure();
  }

  #factoryResolved(module) {
    this.#noteCallback();
    if (this.#run.factorySettled || !module ||
        (typeof module !== "object" && typeof module !== "function") ||
        (this.#runtimeModule !== null && this.#runtimeModule !== module)) {
      this.#markFailure();
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
      this.#markFailure();
      return;
    }
    const exitCode = exactNonzeroExitStatus(reason);
    this.#run.factorySettled = true;
    if (exitCode === null) {
      this.#run.factoryRejectedUnexpected = true;
      this.#observeText(typeof reason === "string" ? reason : "", true);
      this.#markFailure();
      return;
    }
    this.#factoryExitStatusCode = exitCode;
    this.#run.factoryRejectedExpectedExitStatus = true;
    this.#maybeComplete();
  }

  #expectedTwoPhaseLifecycleReady() {
    const settledAsExpected = this.#run.factoryResolved ||
        (this.#run.factoryRejectedExpectedExitStatus &&
         this.#factoryExitStatusCode === this.#run.processExitCode);
    return !this.#failure && this.#buildConfigValidated && this.#run.runtimeInitialized &&
        this.#run.factorySettled && settledAsExpected &&
        !this.#run.factoryRejectedUnexpected && !this.#run.abortObserved &&
        this.#run.processExitCount === 1 && this.#run.processExitCode !== null &&
        this.#run.onExitCount === 1 &&
        this.#run.runtimeExitCode === this.#run.processExitCode &&
        this.#run.markers.length === EXPECTED_DATABASE_MARKERS.length &&
        this.#run.markers.every((marker, index) =>
          marker === EXPECTED_DATABASE_MARKERS[index]) &&
        this.#run.phases.length === EXPECTED_DATABASE_PHASES.length &&
        this.#run.phases.every((phase, index) => phase === EXPECTED_DATABASE_PHASES[index]) &&
        this.#run.eventSequence.length === EXPECTED_EVENT_SEQUENCE.length &&
        this.#run.eventSequence.every((event, index) =>
          event === EXPECTED_EVENT_SEQUENCE[index]) &&
        this.#run.markerSequenceAccepted && this.#run.databaseFailureMarkerObserved &&
        this.#run.drainRefusalMarkerObserved && this.#run.drainRefusalMarkerCount === 1 &&
        this.#run.retirementMarkerObserved && this.#run.retirementMarkerCount === 1 &&
        !this.#run.leaseReleasedMarkerObserved && this.#run.stdoutMarkerCount === 0 &&
        this.#windowErrorCount === 0 && this.#unhandledRejectionCount === 0 &&
        this.#fatalCallbackCount === 0 && !this.#rawTokenLeakDetected;
  }

  #maybeComplete() {
    if (this.#finalQuiescence.started || !this.#expectedTwoPhaseLifecycleReady()) return;
    this.#finalQuiescence.started = true;
    this.#finalQuiescence.callbacksAtStart = this.#callbackCount;
    setTimeout(() => {
      this.#finalQuiescence.callbacksAtEnd = this.#callbackCount;
      this.#finalQuiescence.quiet = !this.#failure &&
          this.#finalQuiescence.callbacksAtStart ===
              this.#finalQuiescence.callbacksAtEnd;
      this.#finalQuiescence.completed = true;
      if (!this.#finalQuiescence.quiet) this.#markFailure();
    }, FINAL_QUIESCENCE_MS);
  }

  async #prepareBootstrap() {
    const url = new URL(`./bootstrap/${this.#context.session}`, location.href);
    if (url.origin !== location.origin) throw new Error("bootstrap origin is invalid");
    const response = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    if (!response.ok || response.url !== url.href ||
        response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
            "application/json" || response.headers.get("cache-control") !== "no-store" ||
        response.headers.get("cross-origin-embedder-policy") !== "require-corp" ||
        response.headers.get("cross-origin-opener-policy") !== "same-origin" ||
        response.headers.get("cross-origin-resource-policy") !== "same-origin" ||
        response.headers.get("referrer-policy") !== "no-referrer" ||
        response.headers.get("x-content-type-options") !== "nosniff") {
      throw new Error("bootstrap response is invalid");
    }
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("bootstrap body is invalid");
    }
    if (!hasExactFields(payload, ["protocol", "case", "scope", "tokenB", "tokenBDigest"]) ||
        payload.protocol !== HOST_PROTOCOL || payload.case !== CASE ||
        payload.scope !== SCOPE || typeof payload.tokenB !== "string" ||
        !SHA256_RE.test(payload.tokenB) || typeof payload.tokenBDigest !== "string" ||
        !SHA256_RE.test(payload.tokenBDigest)) {
      throw new Error("bootstrap payload is invalid");
    }
    const digest = await sha256Hex(new TextEncoder().encode(payload.tokenB),
                                   "database token");
    if (digest !== payload.tokenBDigest) throw new Error("bootstrap digest is invalid");
    this.#rawToken = payload.tokenB;
    this.#tokenDigest = digest;
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
    if (typeof namespace.default !== "function") throw new Error("loader factory is invalid");
    this.#factory = namespace.default;
    this.#mainScriptUrlOrBlob = this.#loaderImportUrl;
    this.#wasmBinary = wasmBytes;
    this.#wasmUrl = wasmUrl;
  }

  #startModule() {
    if (this.#factory === null || this.#rawToken === null || this.#wasmBinary === null ||
        this.#wasmUrl === null || this.#run.moduleIdentity !== null) {
      throw new Error("module start is invalid");
    }
    this.#run.moduleIdentity = randomHex(16, "module identity");
    this.#bridgeInstalledBeforeModuleFactory = this.#bridgeInstalled;
    this.#moduleStarted = true;
    const host = this;
    let result;
    try {
      result = this.#factory({
        arguments: [
          "--wasm-profile-database-smoke=verify-b",
          `--wasm-profile-database-token-b=${this.#rawToken}`,
        ],
        canvas: this.#canvas,
        locateFile(path) {
          if (path !== `${host.#context.moduleName}.wasm`) {
            throw new Error("loader requested an unexpected artifact");
          }
          return host.#wasmUrl.href;
        },
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
    return {
      abortObserved: this.#run.abortObserved,
      databaseFailureMarkerObserved: this.#run.databaseFailureMarkerObserved,
      drainRefusalMarkerCount: this.#run.drainRefusalMarkerCount,
      drainRefusalMarkerObserved: this.#run.drainRefusalMarkerObserved,
      eventCount: this.#run.eventSequence.length,
      eventSequence: this.#run.eventSequence.slice(),
      factoryRejectedExpectedExitStatus: this.#run.factoryRejectedExpectedExitStatus,
      factoryRejectedUnexpected: this.#run.factoryRejectedUnexpected,
      factoryResolved: this.#run.factoryResolved,
      factorySettled: this.#run.factorySettled,
      leaseReleasedMarkerObserved: this.#run.leaseReleasedMarkerObserved,
      markerCount: this.#run.markers.length,
      markerSequenceAccepted: this.#run.markerSequenceAccepted,
      markerSource: "stderr-only-fixed-grammar",
      markers: this.#run.markers.slice(),
      mode: this.#run.mode,
      moduleIdentity: this.#run.moduleIdentity,
      onExitCount: this.#run.onExitCount,
      outputLineCount: this.#run.outputLineCount,
      phaseCount: this.#run.phases.length,
      phases: this.#run.phases.slice(),
      processExitCode: this.#run.processExitCode,
      processExitCount: this.#run.processExitCount,
      retirementMarkerCount: this.#run.retirementMarkerCount,
      retirementMarkerObserved: this.#run.retirementMarkerObserved,
      runtimeExitCode: this.#run.runtimeExitCode,
      runtimeInitialized: this.#run.runtimeInitialized,
      stdoutMarkerCount: this.#run.stdoutMarkerCount,
    };
  }

  #result(status) {
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
      buildConfigSnapshotValidated: passed && this.#buildConfigValidated,
      artifact: this.#artifact,
      capture_harness: this.#captureHarness,
      versions: this.#versions,
      tokenEvidence: {
        algorithm: "SHA-256",
        tokenB: this.#tokenDigest,
        rawTokensExcluded: true,
        rawTokenLeakDetected: this.#rawTokenLeakDetected,
        rawTokenRedactionCount: this.#rawTokenRedactionCount,
      },
      fixedDatabaseFailureObserved: passed,
      outstandingProfileIORefusalObserved: passed,
      firstRefusalPrecededOuterBackendTransaction: passed,
      failClosedCleanupAfterRefusalObserved: passed,
      safeFailClosedRuntimeExitObserved: passed,
      normalProfilePersistenceProven: false,
      databaseDurabilityProven: false,
      physicalCrashBehaviorProven: false,
      fullStoragePartitionPersistenceProven: false,
      hostBoundary: {
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        nativeCallAttempted: false,
        wasmDataInspectionAttempted: false,
      },
      run: this.#runSnapshot(),
      bridge: {
        protocol: HOST_PROTOCOL,
        permanent: this.#bridgeInstalled,
        frozen: this.#bridgeInstalled &&
            Object.isFrozen(globalThis.__chromiumWasmHostBridgeV1),
        installedBeforeModuleFactory: this.#bridgeInstalledBeforeModuleFactory,
        processExitDispatches: this.#bridgeProcessExitDispatches,
      },
      finalQuiescence: {...this.#finalQuiescence},
      fatalCallbackCount: this.#fatalCallbackCount,
      windowErrorCount: this.#windowErrorCount,
      unhandledRejectionCount: this.#unhandledRejectionCount,
      error: passed ? null : "details-suppressed",
    };
  }

  async run() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function" || location.origin === "null") {
        throw new Error("host context is invalid");
      }
      await this.#validateBuildConfig();
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) throw new Error("canvas focus failed");
      this.#captureExternalFailures();
      await this.#prepareBootstrap();
      this.#installBridge();
      await this.#prepareFactory();
      this.#startModule();
      const deadline = performance.now() + this.#context.timeoutMs;
      while (performance.now() < deadline && !this.#failure &&
             !this.#finalQuiescence.completed) {
        await delay(10);
      }
      if (!this.#finalQuiescence.completed || !this.#finalQuiescence.quiet ||
          !this.#expectedTwoPhaseLifecycleReady()) {
        this.#markFailure();
      }
    } catch (_error) {
      this.#markFailure();
    }
    this.#status.textContent = this.#failure ? "failed" : "passed";
    return this.#result(this.#failure ? "fail" : "pass");
  }

  recheckBeforeResultUpload(result) {
    this.#finalQuiescence.callbacksAtPreUploadCheck = this.#callbackCount;
    const clean = result.status === "pass" && !this.#failure &&
        this.#finalQuiescence.completed && this.#finalQuiescence.quiet &&
        this.#finalQuiescence.callbacksAtPreUploadCheck ===
            this.#finalQuiescence.callbacksAtEnd &&
        this.#expectedTwoPhaseLifecycleReady() && this.#windowErrorCount === 0 &&
        this.#unhandledRejectionCount === 0 && !this.#rawTokenLeakDetected;
    if (!clean) this.#markFailure();
    return this.#result(this.#failure ? "fail" : "pass");
  }

  dispose() {
    this.#releaseResources();
    this.#rawToken = null;
  }
}

async function postResult(context, result) {
  const url = new URL(`./result/${context.resultToken}`, location.href);
  if (url.origin !== location.origin) throw new Error("result origin is invalid");
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok || response.url !== url.href || response.status !== 204 ||
      response.headers.get("cache-control") !== "no-store" ||
      response.headers.get("cross-origin-embedder-policy") !== "require-corp" ||
      response.headers.get("cross-origin-opener-policy") !== "same-origin" ||
      response.headers.get("cross-origin-resource-policy") !== "same-origin" ||
      response.headers.get("referrer-policy") !== "no-referrer" ||
      response.headers.get("x-content-type-options") !== "nosniff") {
    throw new Error("result response is invalid");
  }
}

export async function runChromeWasmProfileDatabaseOutstandingIORefusalFromQuery() {
  const context = parseContext();
  const canvas = document.querySelector(
      "#m7-profile-database-outstanding-io-refusal-canvas");
  const status = document.querySelector(
      "#m7-profile-database-outstanding-io-refusal-status");
  const host = new ChromeWasmProfileDatabaseOutstandingIORefusalHost(canvas, status, context);
  try {
    let result = await host.run();
    result = host.recheckBeforeResultUpload(result);
    await postResult(context, result);
  } finally {
    host.dispose();
  }
}

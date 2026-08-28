// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// One-module Chromium LevelDB holder/contender/release receipt. Chromium owns
// the database, its profile test lifecycle, the fcntl-backed filesystem, and
// LevelDB's lock acquisition. This page verifies immutable delivery and
// lifecycle only; it has no storage, lock, native-call, or Wasm-data access.

const HOST_PROTOCOL = 1;
const CASE = "chrome_profile_database_leveldb_lock_m7";
const SCOPE =
    "same-origin-same-document-one-chrome-wasm-m7-profile-database-lock-test-module";
const PRODUCT_MODULE_NAME = "chrome_wasm_m7_profile_database_lock_test";
const M7_MARKER_PREFIX = "CHROMIUM_WASM_M7_DATABASE:";
const M7_PHASE_PREFIX = "CHROMIUM_WASM_M7_DATABASE_PHASE:";
const MAX_TIMEOUT_MS = 300000;
const MIN_TIMEOUT_MS = 20000;
const MAX_OUTPUT_LINES = 128;
const FINAL_QUIESCENCE_MS = 50;
const SHA256_RE = /^[0-9a-f]{64}$/;
const MODULE_ID_RE = /^[0-9a-f]{32}$/;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;
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
const VERSION_FIELDS = Object.freeze(["chromium", "emscripten", "v8"]);
const EXPECTED_MARKER_PREFIXES = Object.freeze([
  `${M7_MARKER_PREFIX}READY`,
  `${M7_MARKER_PREFIX}SQLITE_WRITE_ACCEPTED sha256=`,
  `${M7_MARKER_PREFIX}LEVELDB_LOCK_CONTENDER_REJECTED`,
  `${M7_MARKER_PREFIX}LEVELDB_LOCK_RELEASE_REOPEN_OK sha256=`,
  `${M7_MARKER_PREFIX}DATABASES_CLOSED sha256=`,
  `${M7_MARKER_PREFIX}FENCE_OK sha256=`,
  `${M7_MARKER_PREFIX}LEASE_RELEASED`,
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

function parseJson(text, description) {
  if (typeof text !== "string" || text.length === 0 || text.length > 65536) {
    throw new Error(`${description} is invalid`);
  }
  try {
    return JSON.parse(text);
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
  const captureHarness = requireExactFields(
      parseJson(value, "capture harness"), CAPTURE_HARNESS_FIELDS,
      "capture harness");
  if (captureHarness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      captureHarness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("capture harness provenance is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(captureHarness.host_html, "host HTML"),
    host_js: parseByteIdentity(captureHarness.host_js, "host JS"),
    runner_source: parseByteIdentity(captureHarness.runner_source, "runner source"),
    source_snapshot_provenance: captureHarness.source_snapshot_provenance,
    version_provenance: captureHarness.version_provenance,
  });
}

function parseContext() {
  const query = new URLSearchParams(location.search);
  const fields = Object.freeze([
    "resultToken", "session", "module", "timeoutMs", "versions", "artifact",
    "captureHarness",
  ]);
  if ([...query.keys()].length !== fields.length ||
      !fields.every((field) => query.getAll(field).length === 1)) {
    throw new Error("lock smoke query is invalid");
  }
  const resultToken = query.get("resultToken");
  const session = query.get("session");
  const moduleName = query.get("module");
  const timeoutText = query.get("timeoutMs");
  if (typeof resultToken !== "string" || !CAPABILITY_RE.test(resultToken) ||
      typeof session !== "string" || !CAPABILITY_RE.test(session) ||
      resultToken === session || moduleName !== PRODUCT_MODULE_NAME ||
      typeof timeoutText !== "string" || !/^[0-9]+$/.test(timeoutText)) {
    throw new Error("lock smoke query is invalid");
  }
  const timeoutMs = Number(timeoutText);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("lock smoke timeout is invalid");
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
  if (!(bytes instanceof Uint8Array) || !globalThis.crypto ||
      !globalThis.crypto.subtle ||
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
  });
  if (!response.ok || response.url !== url.href ||
      response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
          contentType) {
    throw new Error(`${description} response is invalid`);
  }
  let buffer;
  try {
    buffer = await response.arrayBuffer();
  } catch (_error) {
    throw new Error(`${description} bytes are invalid`);
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} differs from its snapshot`);
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

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

class ChromeWasmProfileDatabaseLockHost {
  #artifact;
  #bridgeInstalled = false;
  #bridgeInstalledBeforeModuleFactory = false;
  #bridgeProcessExitDispatches = 0;
  #callbackCount = 0;
  #canvas;
  #captureHarness;
  #context;
  #factory = null;
  #factoryModule = null;
  #failure = false;
  #finalQuiescence = {
    activeAtEnd: null,
    activeAtPreUploadCheck: null,
    activeAtStart: null,
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
  #moduleStarted = false;
  #rawToken = null;
  #rawTokenLeakDetected = false;
  #rawTokenRedactionCount = 0;
  #rawTokenTail = "";
  #runtimeModule = null;
  #run = {
    abortObserved: false,
    expectedCleanExitStatusObserved: false,
    factoryRejected: false,
    factoryResolved: false,
    factorySettled: false,
    leaseReleasedMarkerObserved: false,
    lifecycleComplete: false,
    markerCount: 0,
    markerSequenceAccepted: true,
    markers: [],
    mode: "lock-contention",
    moduleIdentity: null,
    onExitCount: 0,
    outputLineCount: 0,
    processExitCode: null,
    processExitCount: 0,
    runtimeExitCode: null,
    runtimeInitialized: false,
    stdoutMarkerCount: 0,
  };
  #status;
  #tokenDigest = null;
  #unhandledRejectionHandler;
  #unhandledRejections = 0;
  #versions;
  #wasmBinary = null;
  #wasmUrl = null;
  #windowErrorHandler;
  #windowErrors = 0;

  constructor(canvas, status, context) {
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement)) {
      throw new Error("lock smoke page is invalid");
    }
    this.#artifact = context.artifact;
    this.#canvas = canvas;
    this.#captureHarness = context.captureHarness;
    this.#context = context;
    this.#status = status;
    this.#versions = context.versions;
  }

  #markFailure() {
    this.#failure = true;
  }

  #noteCallback() {
    this.#callbackCount += 1;
  }

  #observeText(value, trackAcrossCallbacks = false) {
    if (typeof value !== "string" || this.#rawToken === null) return;
    const candidate = trackAcrossCallbacks ? this.#rawTokenTail + value : value;
    if (candidate.includes(this.#rawToken)) {
      this.#rawTokenLeakDetected = true;
      this.#rawTokenRedactionCount += 1;
      this.#markFailure();
    }
    if (trackAcrossCallbacks) {
      this.#rawTokenTail = candidate.slice(-63);
    }
  }

  #expectedMarkers() {
    if (this.#tokenDigest === null) return [];
    return [
      EXPECTED_MARKER_PREFIXES[0],
      `${EXPECTED_MARKER_PREFIXES[1]}${this.#tokenDigest}`,
      EXPECTED_MARKER_PREFIXES[2],
      `${EXPECTED_MARKER_PREFIXES[3]}${this.#tokenDigest}`,
      `${EXPECTED_MARKER_PREFIXES[4]}${this.#tokenDigest}`,
      `${EXPECTED_MARKER_PREFIXES[5]}${this.#tokenDigest}`,
      EXPECTED_MARKER_PREFIXES[6],
    ];
  }

  #markersComplete() {
    const expected = this.#expectedMarkers();
    return this.#run.markerSequenceAccepted && expected.length !== 0 &&
        this.#run.markers.length === expected.length &&
        this.#run.markers.every((marker, index) => marker === expected[index]) &&
        this.#run.leaseReleasedMarkerObserved;
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("lock smoke bridge is already installed");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.#noteCallback();
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
      throw new Error("lock smoke bridge is mutable");
    }
    this.#bridgeInstalled = true;
  }

  #captureExternalFailures() {
    this.#windowErrorHandler = (event) => {
      this.#noteCallback();
      this.#windowErrors += 1;
      this.#observeText(typeof event.message === "string" ? event.message : "", true);
      this.#markFailure();
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#noteCallback();
      let reason = null;
      try {
        reason = event.reason;
      } catch (_error) {
        this.#markFailure();
        return;
      }
      if (isExactNormalEmscriptenExitStatus(reason) && !this.#failure &&
          this.#run.factoryResolved && this.#run.processExitCode === 0 &&
          this.#run.onExitCount === 1 &&
          event && typeof event.preventDefault === "function") {
        event.preventDefault();
        this.#run.expectedCleanExitStatusObserved = true;
        this.#maybeComplete();
        return;
      }
      this.#unhandledRejections += 1;
      this.#observeText(typeof reason === "string" ? reason : "", true);
      this.#markFailure();
    };
    addEventListener("error", this.#windowErrorHandler);
    addEventListener("unhandledrejection", this.#unhandledRejectionHandler);
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

  #routeProcessExit(report) {
    this.#noteCallback();
    if (!this.#moduleStarted || this.#run.lifecycleComplete ||
        this.#run.processExitCount !== 0 ||
        this.#run.onExitCount !== 0 || !hasExactFields(report, ["protocol", "exitCode"]) ||
        report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.exitCode)) {
      this.#markFailure();
      return;
    }
    this.#run.processExitCount = 1;
    this.#run.processExitCode = report.exitCode;
    this.#bridgeProcessExitDispatches += 1;
    this.#maybeComplete();
  }

  #captureOutput(destination, line) {
    this.#noteCallback();
    this.#run.outputLineCount += 1;
    if (this.#run.outputLineCount > MAX_OUTPUT_LINES || typeof line !== "string") {
      this.#markFailure();
      return;
    }
    this.#observeText(line, true);
    if (line.startsWith(M7_PHASE_PREFIX)) {
      this.#markFailure();
      return;
    }
    if (!line.startsWith(M7_MARKER_PREFIX)) return;
    if (destination !== "stderr") {
      this.#run.stdoutMarkerCount += 1;
      this.#markFailure();
      return;
    }
    const expected = this.#expectedMarkers();
    const index = this.#run.markers.length;
    if (index >= expected.length || line !== expected[index]) {
      this.#run.markerSequenceAccepted = false;
      this.#markFailure();
      return;
    }
    this.#run.markers.push(line);
    this.#run.markerCount = this.#run.markers.length;
    if (line === `${M7_MARKER_PREFIX}LEASE_RELEASED`) {
      this.#run.leaseReleasedMarkerObserved = true;
    }
    this.#maybeComplete();
  }

  #reportRuntimeInitialized(module) {
    this.#noteCallback();
    if (this.#run.lifecycleComplete || this.#run.runtimeInitialized || !module ||
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
    if (this.#run.lifecycleComplete || !Number.isSafeInteger(code) ||
        this.#run.onExitCount !== 0 || this.#run.processExitCount !== 1 ||
        this.#run.processExitCode !== 0) {
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
    if (this.#run.abortObserved) {
      this.#markFailure();
      return;
    }
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
    this.#observeText(typeof reason === "string" ? reason : "", true);
    if (this.#run.factorySettled) {
      this.#markFailure();
      return;
    }
    this.#run.factorySettled = true;
    this.#run.factoryRejected = true;
    this.#markFailure();
  }

  #cleanLifecycleReady() {
    return !this.#failure && this.#runtimeModule !== null &&
        this.#runtimeModule === this.#factoryModule && this.#run.runtimeInitialized &&
        this.#run.factorySettled && this.#run.factoryResolved &&
        !this.#run.factoryRejected && !this.#run.abortObserved &&
        this.#run.processExitCount === 1 && this.#run.processExitCode === 0 &&
        this.#run.onExitCount === 1 && this.#run.runtimeExitCode === 0 &&
        this.#markersComplete() && this.#windowErrors === 0 &&
        this.#unhandledRejections === 0 && !this.#rawTokenLeakDetected;
  }

  #maybeComplete() {
    if (this.#run.lifecycleComplete || !this.#cleanLifecycleReady()) return;
    this.#run.lifecycleComplete = true;
    this.#startFinalQuiescence();
  }

  #startFinalQuiescence() {
    if (this.#finalQuiescence.started) {
      this.#markFailure();
      return;
    }
    this.#finalQuiescence.started = true;
    this.#finalQuiescence.activeAtStart = null;
    this.#finalQuiescence.callbacksAtStart = this.#callbackCount;
    this.#finalQuiescence.processExitReportsAtStart = this.#bridgeProcessExitDispatches;
    setTimeout(() => {
      this.#finalQuiescence.activeAtEnd = null;
      this.#finalQuiescence.callbacksAtEnd = this.#callbackCount;
      this.#finalQuiescence.processExitReportsAtEnd = this.#bridgeProcessExitDispatches;
      this.#finalQuiescence.quiet = !this.#failure &&
          this.#finalQuiescence.callbacksAtStart ===
              this.#finalQuiescence.callbacksAtEnd &&
          this.#finalQuiescence.processExitReportsAtStart ===
              this.#finalQuiescence.processExitReportsAtEnd;
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
    });
    if (!response.ok || response.url !== url.href ||
        response.headers.get("content-type")?.split(";", 1)[0]
        .trim().toLowerCase() !== "application/json") {
      throw new Error("bootstrap response is invalid");
    }
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("bootstrap body is invalid");
    }
    if (!hasExactFields(payload, ["protocol", "case", "scope", "tokenA", "tokenADigest"]) ||
        payload.protocol !== HOST_PROTOCOL || payload.case !== CASE ||
        payload.scope !== SCOPE || typeof payload.tokenA !== "string" ||
        !SHA256_RE.test(payload.tokenA) || typeof payload.tokenADigest !== "string" ||
        !SHA256_RE.test(payload.tokenADigest)) {
      throw new Error("bootstrap payload is invalid");
    }
    const digest = await sha256Hex(new TextEncoder().encode(payload.tokenA),
                                   "database token");
    if (digest !== payload.tokenADigest) throw new Error("bootstrap digest is invalid");
    this.#rawToken = payload.tokenA;
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
    if (typeof namespace.default !== "function") {
      throw new Error("loader factory is invalid");
    }
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
          "--wasm-profile-database-smoke=lock-contention",
          `--wasm-profile-database-token-a=${this.#rawToken}`,
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
      expectedCleanExitStatusObserved: this.#run.expectedCleanExitStatusObserved,
      factoryRejected: this.#run.factoryRejected,
      factoryResolved: this.#run.factoryResolved,
      factorySettled: this.#run.factorySettled,
      leaseReleasedMarkerObserved: this.#run.leaseReleasedMarkerObserved,
      lifecycleComplete: this.#run.lifecycleComplete,
      markerCount: this.#run.markerCount,
      markerSequenceAccepted: this.#run.markerSequenceAccepted,
      markerSource: "stderr-only-fixed-grammar",
      markers: this.#run.markers.slice(),
      mode: this.#run.mode,
      moduleIdentity: this.#run.moduleIdentity,
      onExitCount: this.#run.onExitCount,
      outputLineCount: this.#run.outputLineCount,
      processExitCode: this.#run.processExitCode,
      processExitCount: this.#run.processExitCount,
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
      artifact: this.#artifact,
      capture_harness: this.#captureHarness,
      versions: this.#versions,
      tokenEvidence: {
        algorithm: "SHA-256",
        tokenA: this.#tokenDigest,
        rawTokensExcluded: true,
        rawTokenLeakDetected: this.#rawTokenLeakDetected,
        rawTokenRedactionCount: this.#rawTokenRedactionCount,
      },
      sameProcessLevelDbLockContentionReleaseProven: passed,
      concurrentProfileContenderProven: false,
      sqliteLockingProven: false,
      normalProfilePersistenceProven: false,
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
        activeAtResult: null,
      },
      finalQuiescence: {...this.#finalQuiescence},
      fatalErrors: [],
      windowErrors: [],
      unhandledRejections: [],
      failedChecks: [],
      error: passed ? null : "details-suppressed",
    };
  }

  async run() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function" || location.origin === "null") {
        throw new Error("host context is invalid");
      }
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
          !this.#cleanLifecycleReady()) {
        this.#markFailure();
      }
    } catch (_error) {
      this.#markFailure();
    }
    this.#status.textContent = this.#failure ? "failed" : "passed";
    return this.#result(this.#failure ? "fail" : "pass");
  }

  recheckBeforeResultUpload(result) {
    this.#finalQuiescence.bridgeRecheckedImmediatelyBeforeUpload = true;
    this.#finalQuiescence.activeAtPreUploadCheck = null;
    this.#finalQuiescence.callbacksAtPreUploadCheck = this.#callbackCount;
    this.#finalQuiescence.processExitReportsAtPreUploadCheck =
        this.#bridgeProcessExitDispatches;
    const clean = result.status === "pass" && !this.#failure &&
        this.#finalQuiescence.completed && this.#finalQuiescence.quiet &&
        this.#finalQuiescence.callbacksAtPreUploadCheck ===
            this.#finalQuiescence.callbacksAtEnd &&
        this.#finalQuiescence.processExitReportsAtPreUploadCheck ===
            this.#finalQuiescence.processExitReportsAtEnd &&
        this.#windowErrors === 0 && this.#unhandledRejections === 0 &&
        !this.#rawTokenLeakDetected;
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
    redirect: "error",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (response.status !== 204) throw new Error("result acknowledgement is invalid");
}

export async function runChromeWasmProfileDatabaseLockFromQuery() {
  let host = null;
  try {
    const context = parseContext();
    const canvas = document.querySelector("#m7-profile-database-lock-canvas");
    const status = document.querySelector("#m7-profile-database-lock-status");
    const versions = document.querySelector("#m7-profile-database-lock-versions");
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement) ||
        !(versions instanceof HTMLElement)) {
      return;
    }
    versions.replaceChildren();
    for (const [name, revision] of Object.entries(context.versions)) {
      const term = document.createElement("dt");
      const definition = document.createElement("dd");
      term.textContent = name;
      definition.textContent = revision;
      versions.append(term, definition);
    }
    host = new ChromeWasmProfileDatabaseLockHost(canvas, status, context);
    const initialResult = await host.run();
    const result = host.recheckBeforeResultUpload(initialResult);
    try {
      await postResult(context, result);
    } catch (_error) {
      status.textContent = "result delivery failed";
    }
  } catch (_error) {
    const status = document.querySelector("#m7-profile-database-lock-status");
    if (status instanceof HTMLElement) status.textContent = "failed";
  } finally {
    if (host !== null) host.dispose();
  }
}

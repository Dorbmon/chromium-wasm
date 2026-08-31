// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Three-document renderer database witness. The browser-owned chrome:// test
// page performs the persistent-data operation. This outer document loads one
// fresh Emscripten module, passes only the server-escrowed argv values, and
// relays fixed stderr receipts. It deliberately has no profile-data API,
// lock API, native-export, or Wasm-memory access.

const HOST_PROTOCOL = 1;
const CASE = "chrome_renderer_indexed_db_three_outer_document_reload_m7";
const SCOPE =
    "same-origin-three-outer-documents-chrome-wasm-m7-renderer-database-" +
    "test-modules-orderly-close-reopen-only";
const MODULE_NAME = "chrome_wasm_m7_profile_indexed_db_test";
const MARKER_PREFIX = "CHROMIUM_WASM_M7_INDEXED_DB:";
const MAX_TIMEOUT_MS = 300000;
const MIN_TIMEOUT_MS = 20000;
const MAX_OUTPUT_LINES = 128;
const QUIESCENCE_MS = 50;
const TOKEN_RE = /^[0-9a-f]{64}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const ID_RE = /^[0-9a-f]{32}$/;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;
const PHASES = Object.freeze({
  1: Object.freeze({phase: "write-a", mode: "renderer-write"}),
  2: Object.freeze({
    phase: "verify-a-write-b", mode: "renderer-verify-a-write-b"}),
  3: Object.freeze({phase: "verify-b", mode: "renderer-verify-b"}),
});
const ARTIFACT_FIELDS = Object.freeze([
  "artifact_delivery", "artifact_source_provenance", "build_config",
  "build_config_provenance", "loader", "module_name", "wasm",
]);
const HARNESS_FIELDS = Object.freeze([
  "host_html", "host_js", "runner_source", "source_snapshot_provenance",
  "version_provenance",
]);
const RESULT_FIELDS = Object.freeze([
  "artifact", "bridge", "captureHarness", "case", "document",
  "hostBoundary", "m7GateComplete", "mode", "ordinal", "origin", "phase",
  "protocol", "quiescence", "run", "scope", "sharedArrayBuffer", "status",
  "tokenEvidence", "versions",
]);
const RUN_FIELDS = Object.freeze([
  "abortObserved", "expectedCleanExitStatusObserved", "factoryRejected",
  "factoryResolved", "factorySettled", "freshLoaderImport", "freshModuleObject",
  "lifecycleComplete", "markerCount", "markerSequenceAccepted", "markerSource",
  "markers", "moduleIdentity", "onExitCount", "ordinal", "outputLineCount",
  "processExitCode", "processExitCount", "runtimeExitCode", "runtimeInitialized",
  "stdoutMarkerCount",
]);
const BRIDGE_FIELDS = Object.freeze([
  "activeAtResult", "frozen", "installedBeforeModuleFactory", "permanent",
  "processExitDispatches", "protocol",
]);
const TOKEN_EVIDENCE_FIELDS = Object.freeze([
  "algorithm", "rawTokensExcluded", "rawTokenLeakDetected",
  "rawTokenRedactionCount", "tokenADigest", "tokenBDigest",
]);
const BOUNDARY_FIELDS = Object.freeze([
  "hostDatabaseAccessAttempted", "hostOpfsAccessAttempted",
  "hostWebLocksAccessAttempted", "nativeCallAttempted",
  "wasmMemoryInspectionAttempted",
]);
const NORMAL_EXIT_STATUS = Object.freeze({
  name: "ExitStatus", status: 0, message: "Program terminated with exit(0)",
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
  const identity = exactFields(value, ["bytes", "sha256"], description);
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
      artifact.module_name !== MODULE_NAME) {
    throw new Error("artifact is invalid");
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
                              HARNESS_FIELDS, "capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("capture harness is invalid");
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
  if (!Object.values(versions).every(
      (revision) => typeof revision === "string" && /^[0-9a-f]{40}$/.test(revision))) {
    throw new Error("versions are invalid");
  }
  return Object.freeze({...versions});
}

function oneQueryValue(query, name) {
  const values = query.getAll(name);
  if (values.length !== 1) {
    throw new Error("renderer database query is invalid");
  }
  return values[0];
}

function parseContext() {
  const query = new URLSearchParams(globalThis.location.search);
  const fields = [
    "artifact", "captureHarness", "module", "resultToken", "session",
    "timeoutMs", "versions",
  ];
  if ([...query.keys()].length !== fields.length ||
      !fields.every((field) => query.getAll(field).length === 1) ||
      oneQueryValue(query, "module") !== MODULE_NAME ||
      !CAPABILITY_RE.test(oneQueryValue(query, "resultToken")) ||
      !CAPABILITY_RE.test(oneQueryValue(query, "session")) ||
      oneQueryValue(query, "resultToken") === oneQueryValue(query, "session")) {
    throw new Error("renderer database query is invalid");
  }
  const timeoutText = oneQueryValue(query, "timeoutMs");
  if (!/^[0-9]+$/.test(timeoutText)) {
    throw new Error("renderer database timeout is invalid");
  }
  const timeoutMs = Number(timeoutText);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("renderer database timeout is invalid");
  }
  return Object.freeze({
    artifact: parseArtifact(oneQueryValue(query, "artifact")),
    captureHarness: parseCaptureHarness(oneQueryValue(query, "captureHarness")),
    resultToken: oneQueryValue(query, "resultToken"),
    session: oneQueryValue(query, "session"),
    timeoutMs,
    versions: parseVersions(oneQueryValue(query, "versions")),
  });
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function randomHex(byteLength) {
  if (!globalThis.crypto || typeof globalThis.crypto.getRandomValues !== "function") {
    throw new Error("renderer database random source is unavailable");
  }
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  return hex(bytes);
}

async function sha256Text(value, description) {
  if (typeof value !== "string" || !globalThis.crypto ||
      !globalThis.crypto.subtle || typeof globalThis.crypto.subtle.digest !== "function") {
    throw new Error(description + " hash support is unavailable");
  }
  const digest = await globalThis.crypto.subtle.digest(
      "SHA-256", new TextEncoder().encode(value));
  return hex(new Uint8Array(digest));
}

async function fetchVerified(url, identity, contentType, description) {
  const response = await fetch(url, {
    cache: "no-store", credentials: "same-origin", redirect: "error",
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
  if (bytes.byteLength !== identity.bytes) {
    throw new Error(description + " identity is invalid");
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  if (hex(new Uint8Array(digest)) !== identity.sha256) {
    throw new Error(description + " differs from its snapshot");
  }
  return bytes;
}

function expectedMarkers(payload) {
  if (payload.ordinal === 1) {
    return [
      MARKER_PREFIX + "READY",
      MARKER_PREFIX + "RENDERER_WRITE_OK sha256=" + payload.tokenADigest,
      MARKER_PREFIX + "BACKING_STORES_CLOSED sha256=" + payload.tokenADigest,
      MARKER_PREFIX + "FENCE_OK sha256=" + payload.tokenADigest,
      MARKER_PREFIX + "LEASE_RELEASED",
    ];
  }
  if (payload.ordinal === 2) {
    return [
      MARKER_PREFIX + "READY",
      MARKER_PREFIX + "RENDERER_REOPEN_READ_A_OK sha256=" + payload.tokenADigest,
      MARKER_PREFIX + "RENDERER_WRITE_B_OK sha256=" + payload.tokenBDigest,
      MARKER_PREFIX + "BACKING_STORES_CLOSED sha256=" + payload.tokenBDigest,
      MARKER_PREFIX + "FENCE_OK sha256=" + payload.tokenBDigest,
      MARKER_PREFIX + "LEASE_RELEASED",
    ];
  }
  if (payload.ordinal === 3) {
    return [
      MARKER_PREFIX + "READY",
      MARKER_PREFIX + "RENDERER_REOPEN_READ_B_OK sha256=" + payload.tokenBDigest,
      MARKER_PREFIX + "BACKING_STORES_CLOSED sha256=" + payload.tokenBDigest,
      MARKER_PREFIX + "FENCE_OK sha256=" + payload.tokenBDigest,
      MARKER_PREFIX + "LEASE_RELEASED",
    ];
  }
  throw new Error("renderer database ordinal is invalid");
}

function isNormalExitStatus(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Object.keys(descriptors).length === 3 &&
      Object.keys(NORMAL_EXIT_STATUS).every((key) =>
        Object.hasOwn(descriptors, key) &&
        descriptors[key].value === NORMAL_EXIT_STATUS[key]);
}

function newRun(payload) {
  return {
    abortObserved: false,
    expectedCleanExitStatusObserved: false,
    factoryRejected: false,
    factoryResolved: false,
    factorySettled: false,
    freshLoaderImport: false,
    freshModuleObject: false,
    lifecycleComplete: false,
    markerSequenceAccepted: true,
    markers: [],
    moduleIdentity: randomHex(16),
    onExitCount: 0,
    ordinal: payload.ordinal,
    outputLineCount: 0,
    processExitCode: null,
    processExitCount: 0,
    runtimeExitCode: null,
    runtimeInitialized: false,
    stdoutMarkerCount: 0,
  };
}

class RendererDatabaseOuterReloadHost {
  constructor(canvas, status, context) {
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement)) {
      throw new Error("renderer database page is invalid");
    }
    this.canvas = canvas;
    this.status = status;
    this.context = context;
    this.deadline = performance.now() + context.timeoutMs;
    this.payload = null;
    this.documentEvidence = null;
    this.moduleRun = null;
    this.active = null;
    this.failed = false;
    this.bridgeInstalled = false;
    this.processExitDispatches = 0;
    this.callbackCount = 0;
    this.callbacksAtClear = 0;
    this.callbacksAfterQuiescence = 0;
    this.rawTokens = [];
    this.rawTails = [];
    this.rawTokenLeakDetected = false;
    this.rawTokenRedactionCount = 0;
    this.loaderBytes = null;
    this.wasmBinary = null;
    this.wasmUrl = null;
    this.loaderImportUrl = null;
    this.loaderFactory = null;
    this.errorListener = null;
    this.rejectionListener = null;
  }

  fail() {
    this.failed = true;
  }

  noteCallback() {
    this.callbackCount += 1;
  }

  observeText(value) {
    if (typeof value !== "string") {
      return;
    }
    for (let index = 0; index < this.rawTokens.length; ++index) {
      const token = this.rawTokens[index];
      const candidate = this.rawTails[index] + value;
      if (candidate.includes(token)) {
        this.rawTokenLeakDetected = true;
        this.rawTokenRedactionCount += 1;
        this.fail();
      }
      this.rawTails[index] = candidate.slice(-63);
    }
  }

  installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("renderer database bridge already exists");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.noteCallback(); host.observeText(message); host.fail(); },
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
      configurable: false, enumerable: false, value: bridge, writable: false,
    });
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge || !Object.isFrozen(bridge)) {
      throw new Error("renderer database bridge is mutable");
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
          run.onExitCount === 1 && !this.failed) {
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

  dispose() {
    if (this.errorListener !== null) {
      removeEventListener("error", this.errorListener);
    }
    if (this.rejectionListener !== null) {
      removeEventListener("unhandledrejection", this.rejectionListener);
    }
    this.rawTokens = [];
    this.rawTails = [];
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
    const expected = expectedMarkers(this.payload);
    if (run.markers.length >= expected.length ||
        line !== expected[run.markers.length]) {
      run.markerSequenceAccepted = false;
      this.fail();
      return;
    }
    run.markers.push(line);
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
    run.abortObserved = true;
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
    const expected = expectedMarkers(this.payload);
    return !this.failed && this.active === run && run.runtimeInitialized &&
        run.factorySettled && run.factoryResolved && !run.factoryRejected &&
        run.runtimeModule === run.factoryModule && !run.abortObserved &&
        run.processExitCount === 1 && run.processExitCode === 0 &&
        run.onExitCount === 1 && run.runtimeExitCode === 0 &&
        run.freshLoaderImport && run.freshModuleObject &&
        run.markerSequenceAccepted && run.markers.length === expected.length &&
        run.markers.every((marker, index) => marker === expected[index]);
  }

  maybeComplete(run) {
    if (!run.lifecycleComplete && this.cleanLifecycle(run)) {
      run.lifecycleComplete = true;
    }
  }

  async fetchBootstrap() {
    const endpoint = new URL("./bootstrap/" + this.context.session, location.href);
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
      "case", "mode", "ordinal", "phase", "protocol", "scope", "tokenA",
      "tokenADigest", "tokenB", "tokenBDigest",
    ], "bootstrap payload");
    const expected = PHASES[payload.ordinal];
    if (!expected || payload.protocol !== HOST_PROTOCOL || payload.case !== CASE ||
        payload.scope !== SCOPE || payload.phase !== expected.phase ||
        payload.mode !== expected.mode ||
        ![payload.tokenA, payload.tokenB].every((token) =>
          token === null || (typeof token === "string" && TOKEN_RE.test(token))) ||
        ![payload.tokenADigest, payload.tokenBDigest].every((digest) =>
          digest === null || (typeof digest === "string" && SHA256_RE.test(digest)))) {
      throw new Error("bootstrap payload is invalid");
    }
    const expectedTokens = {
      1: [true, false], 2: [true, true], 3: [false, true],
    }[payload.ordinal];
    if ((payload.tokenA !== null) !== expectedTokens[0] ||
        (payload.tokenB !== null) !== expectedTokens[1] ||
        (payload.tokenADigest !== null) !== expectedTokens[0] ||
        (payload.tokenBDigest !== null) !== expectedTokens[1] ||
        (payload.ordinal === 2 && payload.tokenA === payload.tokenB)) {
      throw new Error("bootstrap token shape is invalid");
    }
    for (const [token, digest] of [[payload.tokenA, payload.tokenADigest],
                                  [payload.tokenB, payload.tokenBDigest]]) {
      if (token !== null && await sha256Text(token, "bootstrap token") !== digest) {
        throw new Error("bootstrap token digest is invalid");
      }
    }
    return Object.freeze({...payload});
  }

  async postDocumentEvidence() {
    const endpoint = new URL("./bootstrap/" + this.context.session, location.href);
    const response = await fetch(endpoint, {
      method: "POST", cache: "no-store", credentials: "same-origin",
      redirect: "error", referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        case: CASE,
        navigationType: this.documentEvidence.navigationType,
        protocol: HOST_PROTOCOL,
        scope: SCOPE,
        timeOrigin: this.documentEvidence.timeOrigin,
      }),
    });
    if (response.status !== 204) {
      throw new Error("outer document acknowledgement is invalid");
    }
  }

  async fetchArtifacts() {
    const loaderUrl = new URL("./artifacts/" + MODULE_NAME + ".js", location.href);
    const wasmUrl = new URL("./artifacts/" + MODULE_NAME + ".wasm", location.href);
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

  moduleArguments() {
    const args = ["--wasm-profile-indexed-db-smoke=" + this.payload.mode];
    if (this.payload.tokenA !== null) {
      args.push("--wasm-profile-indexed-db-token-a=" + this.payload.tokenA);
    }
    if (this.payload.tokenB !== null) {
      args.push("--wasm-profile-indexed-db-token-b=" + this.payload.tokenB);
    }
    return args;
  }

  async runOneModule() {
    const run = newRun(this.payload);
    this.moduleRun = run;
    this.active = run;
    await this.importFactory();
    run.freshLoaderImport = true;
    const host = this;
    let factoryResult;
    try {
      factoryResult = this.loaderFactory({
        arguments: this.moduleArguments(),
        canvas: this.canvas,
        locateFile(path) {
          if (path !== MODULE_NAME + ".wasm") {
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
    while (performance.now() < this.deadline && !this.failed && !run.lifecycleComplete) {
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
  }

  snapshotRun() {
    const run = this.moduleRun;
    return {
      abortObserved: run.abortObserved,
      expectedCleanExitStatusObserved: run.expectedCleanExitStatusObserved,
      factoryRejected: run.factoryRejected,
      factoryResolved: run.factoryResolved,
      factorySettled: run.factorySettled,
      freshLoaderImport: run.freshLoaderImport,
      freshModuleObject: run.freshModuleObject,
      lifecycleComplete: run.lifecycleComplete,
      markerCount: run.markers.length,
      markerSequenceAccepted: run.markerSequenceAccepted,
      markerSource: "stderr-only-fixed-renderer-database-grammar",
      markers: run.markers.slice(),
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

  result() {
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
      captureHarness: this.context.captureHarness,
      case: CASE,
      document: this.documentEvidence,
      hostBoundary: {
        hostDatabaseAccessAttempted: false,
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        nativeCallAttempted: false,
        wasmMemoryInspectionAttempted: false,
      },
      m7GateComplete: false,
      mode: this.payload.mode,
      ordinal: this.payload.ordinal,
      origin: location.origin,
      phase: this.payload.phase,
      protocol: HOST_PROTOCOL,
      quiescence: {
        callbacksAfterQuiescence: this.callbacksAfterQuiescence,
        callbacksAtClear: this.callbacksAtClear,
        quiet: this.callbacksAtClear === this.callbacksAfterQuiescence,
        quietWindowMs: QUIESCENCE_MS,
      },
      run: this.snapshotRun(),
      scope: SCOPE,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      status: "pass",
      tokenEvidence: {
        algorithm: "SHA-256",
        rawTokensExcluded: true,
        rawTokenLeakDetected: this.rawTokenLeakDetected,
        rawTokenRedactionCount: this.rawTokenRedactionCount,
        tokenADigest: this.payload.tokenADigest,
        tokenBDigest: this.payload.tokenBDigest,
      },
      versions: this.context.versions,
    };
  }

  async postResult(result) {
    const endpoint = new URL(
        "./result/" + this.context.resultToken + "/" + this.payload.ordinal,
        location.href);
    const response = await fetch(endpoint, {
      method: "POST", cache: "no-store", credentials: "same-origin",
      redirect: "error", referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(result),
    });
    if (response.status !== 204) {
      throw new Error("result acknowledgement is invalid");
    }
  }

  async postReady() {
    const endpoint = new URL(
        "./ready/" + this.context.resultToken + "/" + this.payload.ordinal,
        location.href);
    const response = await fetch(endpoint, {
      method: "POST", cache: "no-store", credentials: "same-origin",
      redirect: "error", referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        case: CASE,
        ordinal: this.payload.ordinal,
        protocol: HOST_PROTOCOL,
        scope: SCOPE,
        timeOrigin: this.documentEvidence.timeOrigin,
      }),
    });
    if (response.status !== 204) {
      throw new Error("ready acknowledgement is invalid");
    }
  }

  async postFailure() {
    if (this.payload === null) {
      return;
    }
    const endpoint = new URL(
        "./failure/" + this.context.resultToken + "/" + this.payload.ordinal,
        location.href);
    await fetch(endpoint, {
      method: "POST", cache: "no-store", credentials: "same-origin",
      redirect: "error", referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({case: CASE, ordinal: this.payload.ordinal,
                            protocol: HOST_PROTOCOL, status: "fail"}),
    });
  }

  async run() {
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function" || location.origin === "null") {
        throw new Error("outer document context is invalid");
      }
      this.installFailureObservers();
      const navigation = performance.getEntriesByType("navigation");
      if (navigation.length !== 1 ||
          !["navigate", "reload"].includes(navigation[0].type)) {
        throw new Error("outer document navigation is invalid");
      }
      this.documentEvidence = {
        identity: randomHex(16), navigationType: navigation[0].type,
        timeOrigin: performance.timeOrigin,
      };
      await this.postDocumentEvidence();
      this.payload = await this.fetchBootstrap();
      const expectedNavigation = this.payload.ordinal === 1 ? "navigate" : "reload";
      if (this.documentEvidence.navigationType !== expectedNavigation) {
        throw new Error("outer document navigation ordinal is invalid");
      }
      this.rawTokens = [this.payload.tokenA, this.payload.tokenB].filter(
          (token) => token !== null);
      this.rawTails = this.rawTokens.map(() => "");
      this.canvas.focus({preventScroll: true});
      if (document.activeElement !== this.canvas) {
        throw new Error("canvas focus failed");
      }
      this.installBridge();
      await this.fetchArtifacts();
      await this.runOneModule();
      const result = this.result();
      validateChromeWasmRendererIndexedDBOuterReloadDocumentResult(result);
      await this.postResult(result);
      await this.postReady();
      this.status.textContent = "passed";
      return true;
    } catch (_error) {
      this.fail();
      this.status.textContent = "failed";
      try {
        await this.postFailure();
      } catch (_ignored) {
      }
      return false;
    } finally {
      this.rawTokens = [];
      this.rawTails = [];
      this.loaderBytes = null;
      this.wasmBinary = null;
      this.wasmUrl = null;
      this.loaderFactory = null;
      if (this.loaderImportUrl !== null) {
        URL.revokeObjectURL(this.loaderImportUrl);
        this.loaderImportUrl = null;
      }
    }
  }
}

export function validateChromeWasmRendererIndexedDBOuterReloadDocumentResult(result) {
  exactFields(result, RESULT_FIELDS, "renderer database result");
  const phase = PHASES[result.ordinal];
  if (!phase || result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
      result.scope !== SCOPE || result.status !== "pass" ||
      result.m7GateComplete !== false || result.mode !== phase.mode ||
      result.phase !== phase.phase || result.sharedArrayBuffer !== true ||
      typeof result.origin !== "string") {
    throw new Error("renderer database result is invalid");
  }
  const run = exactFields(result.run, RUN_FIELDS, "renderer database run");
  const evidence = exactFields(result.tokenEvidence, TOKEN_EVIDENCE_FIELDS,
                               "renderer database token evidence");
  if (evidence.algorithm !== "SHA-256" || evidence.rawTokensExcluded !== true ||
      evidence.rawTokenLeakDetected !== false ||
      !Number.isSafeInteger(evidence.rawTokenRedactionCount) ||
      evidence.rawTokenRedactionCount !== 0 ||
      ![evidence.tokenADigest, evidence.tokenBDigest].every((digest) =>
        digest === null || (typeof digest === "string" && SHA256_RE.test(digest)))) {
    throw new Error("renderer database token evidence is invalid");
  }
  const markers = expectedMarkers({
    ordinal: result.ordinal,
    tokenADigest: evidence.tokenADigest,
    tokenBDigest: evidence.tokenBDigest,
  });
  if (run.ordinal !== result.ordinal || run.markers.length !== markers.length ||
      !run.markers.every((marker, index) => marker === markers[index])) {
    throw new Error("renderer database markers are invalid");
  }
  return result;
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

export async function runChromeWasmRendererIndexedDBOuterReloadFromQuery() {
  let host = null;
  try {
    const context = parseContext();
    const canvas = document.querySelector(
        "#m7-renderer-indexed-db-outer-reload-canvas");
    const status = document.querySelector(
        "#m7-renderer-indexed-db-outer-reload-status");
    const versions = document.querySelector(
        "#m7-renderer-indexed-db-outer-reload-versions");
    const root = document.querySelector(
        "#m7-renderer-indexed-db-outer-reload-root");
    if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement) ||
        !(versions instanceof HTMLElement) || !(root instanceof HTMLElement)) {
      throw new Error("renderer database page is invalid");
    }
    showVersions(versions, context.versions);
    host = new RendererDatabaseOuterReloadHost(canvas, status, context);
    root.dataset.state = await host.run() ? "pass" : "fail";
  } finally {
    if (host !== null) {
      host.dispose();
    }
  }
}

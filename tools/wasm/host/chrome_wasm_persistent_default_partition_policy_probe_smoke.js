// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A one-document policy/configuration probe. Chromium owns profile creation,
// CreateDefault(), the ordered drain fence, and process exit. This host only
// verifies the fixed stderr marker grammar and the normal exit receipts. It
// does not instantiate or inspect a StoragePartition, OPFS, Web Locks, or
// profile data, and it makes no persistence/reload/crash claim.

const HOST_PROTOCOL = 1;
const CASE = "chrome_persistent_default_partition_policy_probe_m7";
const SCOPE =
    "one-fresh-source-selected-chrome-wasm-policy-configuration-observation-" +
    "only-no-storagepartition-or-persistence-claim";
const PRODUCT_MODULE_NAME =
    "chrome_wasm_m7_persistent_default_partition_policy_probe";
export const EXACT_EMPTY_PROBE_SWITCH =
    "--wasm-persistent-default-partition-policy-probe=";
const EXACT_PROBE_ARGUMENTS = Object.freeze([EXACT_EMPTY_PROBE_SWITCH]);
const MARKER_PREFIX = "CHROMIUM_WASM_M7_PERSISTENT_DEFAULT_PARTITION_POLICY:";
const FAIL_PREFIX = MARKER_PREFIX + "FAIL stage=";
const EXPECTED_MARKERS = Object.freeze([
  MARKER_PREFIX + "DEFAULT_CONFIG_DEFAULT_NOT_IN_MEMORY",
  MARKER_PREFIX + "FENCE_OK",
  MARKER_PREFIX + "POLICY_PROBE_COMPLETE",
]);
const MAX_TIMEOUT_MS = 300000;
const FINAL_QUIESCENCE_MS = 50;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{16,128}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const GIT_REVISION_RE = /^[0-9a-f]{40}$/;
const EXPECTED_NORMAL_EXIT_STATUS = Object.freeze({
  name: "ExitStatus",
  status: 0,
  message: "Program terminated with exit(0)",
});

const RESULT_FIELDS = Object.freeze([
  "artifact", "actualStoragePartitionProven", "bridge", "capture_harness",
  "case", "crashRecoveryProven", "crossOriginIsolated",
  "defaultConfigDefaultNotInMemoryProven", "error",
  "exactEmptyProbeSwitchPassed", "freshDocumentReloadProven",
  "freshSourceSelectedPolicyArtifactProven", "hostBoundary", "m7GateComplete",
  "normalProcessExitAndAckProven", "policyFenceProven",
  "policyProbeCompleteProven", "profilePersistenceProven", "protocol",
  "quiescence", "run", "scope", "sharedArrayBuffer", "status", "versions",
  "origin",
]);
const RUN_FIELDS = Object.freeze([
  "arguments", "abortObserved", "factoryOutcome", "factorySettled",
  "freshModuleObject", "markerCount", "markerSequenceAccepted",
  "markerSource", "markers", "noFailMarkerObserved",
  "normalProcessExitAndAckReceived", "onExitCount",
  "processExitBeforeOnExit", "processExitCode", "processExitCount",
  "runtimeExitCode", "runtimeInitialized", "stdoutMarkerCount",
  "unexpectedMarkerObserved",
]);
const BRIDGE_FIELDS = Object.freeze([
  "activeAtResult", "installedBeforeModuleFactory",
  "noActiveProcessExitRejected", "permanent", "processExitDispatches",
  "protocol", "duplicateProcessExitRejected", "frozen",
]);
const QUIESCENCE_FIELDS = Object.freeze([
  "callbacksAfterQuietWindow", "callbacksAtLifecycleComplete", "quiet",
  "quietWindowMs",
]);
const HOST_BOUNDARY_FIELDS = Object.freeze([
  "hostDomStorageAccessAttempted", "hostOpfsAccessAttempted",
  "hostWebLocksAccessAttempted", "nativeCallAttempted",
  "wasmDataInspectionAttempted",
]);
const ARTIFACT_FIELDS = Object.freeze([
  "artifact_delivery", "artifact_source_provenance", "build_config",
  "build_config_provenance", "loader", "module_name", "wasm",
]);
const CAPTURE_HARNESS_FIELDS = Object.freeze([
  "host_html", "host_js", "runner_source", "source_snapshot_provenance",
  "version_provenance",
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

function parseTimeout(value) {
  if (typeof value !== "string" || !/^[0-9]+$/.test(value)) {
    throw new Error("policy probe timeout is invalid");
  }
  const timeout = Number(value);
  if (!Number.isSafeInteger(timeout) || timeout < 20000 ||
      timeout > MAX_TIMEOUT_MS) {
    throw new Error("policy probe timeout is invalid");
  }
  return timeout;
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, ["bytes", "sha256"], description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifact(value) {
  const artifact = requireExactFields(
      parseQueryJson(value, "policy probe artifact"), ARTIFACT_FIELDS,
      "policy probe artifact");
  if (artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error("policy probe artifact is invalid");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    build_config: parseByteIdentity(artifact.build_config, "policy probe args"),
    build_config_provenance: artifact.build_config_provenance,
    loader: parseByteIdentity(artifact.loader, "policy probe loader"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "policy probe Wasm"),
  });
}

function parseCaptureHarness(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "policy probe capture harness"),
      CAPTURE_HARNESS_FIELDS, "policy probe capture harness");
  if (harness.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      harness.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("policy probe capture harness is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html, "policy probe host HTML"),
    host_js: parseByteIdentity(harness.host_js, "policy probe host JavaScript"),
    runner_source: parseByteIdentity(harness.runner_source,
                                    "policy probe runner source"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function parseVersions(value) {
  const versions = requireExactFields(
      parseQueryJson(value, "policy probe versions"),
      ["chromium", "v8", "emscripten"], "policy probe versions");
  for (const revision of Object.values(versions)) {
    if (typeof revision !== "string" || !GIT_REVISION_RE.test(revision)) {
      throw new Error("policy probe versions are invalid");
    }
  }
  return Object.freeze({...versions});
}

function parseContext() {
  const query = new URLSearchParams(location.search);
  const allowed = new Set([
    "resultToken", "timeoutMs", "versions", "artifact", "captureHarness",
  ]);
  for (const key of query.keys()) {
    if (!allowed.has(key) || query.getAll(key).length !== 1) {
      throw new Error("policy probe query is invalid");
    }
  }
  const resultToken = asNonemptyString(query.get("resultToken"),
                                       "policy probe result capability");
  if (!CAPABILITY_RE.test(resultToken)) {
    throw new Error("policy probe result capability is invalid");
  }
  return Object.freeze({
    artifact: parseArtifact(query.get("artifact")),
    captureHarness: parseCaptureHarness(query.get("captureHarness")),
    resultToken,
    timeoutMs: parseTimeout(query.get("timeoutMs")),
    versions: parseVersions(query.get("versions")),
  });
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(bytes, description) {
  if (!(bytes instanceof Uint8Array) || !globalThis.crypto?.subtle) {
    throw new Error(`${description} requires Web Crypto SHA-256`);
  }
  let digest;
  try {
    digest = await crypto.subtle.digest("SHA-256", bytes);
  } catch (_error) {
    throw new Error(`${description} SHA-256 failed`);
  }
  return hex(new Uint8Array(digest));
}

function requireResponseHeaders(response, expectedContentType, description) {
  const actualContentType = response.headers.get("Content-Type")
      ?.split(";", 1)[0].trim().toLowerCase();
  const required = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if (actualContentType !== expectedContentType || Object.entries(required).some(
      ([name, expected]) => response.headers.get(name) !== expected)) {
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
  if (!response.ok) throw new Error(`${description} request is invalid`);
  requireResponseHeaders(response, contentType, description);
  let buffer;
  try {
    buffer = await response.arrayBuffer();
  } catch (_error) {
    throw new Error(`${description} body is invalid`);
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} identity is invalid`);
  }
  return bytes;
}

function asReport(value, description) {
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch (_error) {
      throw new Error(`${description} is invalid`);
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${description} is invalid`);
  }
  return value;
}

function isExactNormalExitStatus(value) {
  try {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const keys = Reflect.ownKeys(descriptors);
    if (keys.length !== 3 || keys.some((key) => typeof key !== "string" ||
        !Object.hasOwn(EXPECTED_NORMAL_EXIT_STATUS, key))) {
      return false;
    }
    return Object.entries(EXPECTED_NORMAL_EXIT_STATUS).every(([name, expected]) => {
      const descriptor = descriptors[name];
      return descriptor !== undefined && Object.hasOwn(descriptor, "value") &&
          !Object.hasOwn(descriptor, "get") && !Object.hasOwn(descriptor, "set") &&
          descriptor.value === expected;
    });
  } catch (_error) {
    return false;
  }
}

function hasExactProcessExitReport(value) {
  try {
    const report = asReport(value, "process-exit report");
    return Object.keys(report).length === 2 && report.protocol === HOST_PROTOCOL &&
        Number.isSafeInteger(report.exitCode) &&
        Object.hasOwn(report, "protocol") && Object.hasOwn(report, "exitCode");
  } catch (_error) {
    return false;
  }
}

function newRun() {
  return {
    abortObserved: false,
    factoryOutcome: null,
    factorySettled: false,
    freshModuleObject: false,
    markerSequenceAccepted: true,
    markers: [],
    noFailMarkerObserved: true,
    onExitCount: 0,
    processExitBeforeOnExit: false,
    processExitCode: null,
    processExitCount: 0,
    runtimeExitCode: null,
    runtimeInitialized: false,
    stdoutMarkerCount: 0,
    unexpectedMarkerObserved: false,
  };
}

class PersistentDefaultPartitionPolicyProbeHost {
  constructor(canvas, context) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("policy probe requires a canvas");
    }
    this.canvas = canvas;
    this.context = context;
    this.run = newRun();
    this.active = false;
    this.lifecycleCompleted = false;
    this.bridgeInstalled = false;
    this.callbackCount = 0;
    this.failure = false;
    this.windowErrorCount = 0;
    this.unhandledRejectionCount = 0;
    this.processExitDispatches = 0;
    this.noActiveProcessExitRejected = 0;
    this.duplicateProcessExitRejected = 0;
    this.loaderImportUrl = null;
    this.errorHandler = null;
    this.rejectionHandler = null;
  }

  noteCallback() {
    ++this.callbackCount;
  }

  fail() {
    this.failure = true;
  }

  installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("policy probe bridge is already installed");
    }
    const host = this;
    const bridge = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(_message) { host.noteCallback(); host.fail(); },
      reportProcessExit(report) { host.reportProcessExit(report); },
      reportFrame(_report) { host.noteCallback(); },
      reportReadiness(_report) { host.noteCallback(); },
      reportOzoneFocusState(_report) { host.noteCallback(); },
      reportOzoneCursor(_report) { host.noteCallback(); return true; },
      reportOzoneTextInputState(_report) { host.noteCallback(); },
      reportOzoneTextInputDelivery(_report) { host.noteCallback(); },
      reportOzoneBrowserTextInputDelivery(_report) { host.noteCallback(); },
      reportOzoneBrowserClipboardPasteDelivery(_report) { host.noteCallback(); },
      requestOuterOriginStorageEstimate(_report) {
        host.noteCallback();
        return false;
      },
      reportAccessibilitySnapshot(_report) { host.noteCallback(); return false; },
    });
    Object.defineProperty(globalThis, "__chromiumWasmHostBridgeV1", {
      configurable: false,
      enumerable: false,
      value: bridge,
      writable: false,
    });
    if (globalThis.__chromiumWasmHostBridgeV1 !== bridge ||
        !Object.isFrozen(bridge)) {
      throw new Error("policy probe bridge is mutable");
    }
    this.bridgeInstalled = true;
  }

  installFailureObservers() {
    this.errorHandler = () => {
      this.noteCallback();
      ++this.windowErrorCount;
      this.fail();
    };
    this.rejectionHandler = (event) => {
      this.noteCallback();
      if (isExactNormalExitStatus(event?.reason) && this.active &&
          this.run.processExitCode === 0 && this.run.onExitCount === 1 &&
          typeof event?.preventDefault === "function") {
        event.preventDefault();
        return;
      }
      ++this.unhandledRejectionCount;
      this.fail();
    };
    globalThis.addEventListener("error", this.errorHandler);
    globalThis.addEventListener("unhandledrejection", this.rejectionHandler);
  }

  releaseFailureObservers() {
    if (this.errorHandler !== null) {
      globalThis.removeEventListener("error", this.errorHandler);
      this.errorHandler = null;
    }
    if (this.rejectionHandler !== null) {
      globalThis.removeEventListener("unhandledrejection", this.rejectionHandler);
      this.rejectionHandler = null;
    }
  }

  reportProcessExit(value) {
    this.noteCallback();
    if (!this.active) {
      ++this.noActiveProcessExitRejected;
      this.fail();
      return;
    }
    if (this.run.processExitCount !== 0) {
      ++this.duplicateProcessExitRejected;
      this.fail();
      return;
    }
    if (!hasExactProcessExitReport(value)) {
      this.fail();
      return;
    }
    const report = asReport(value, "process-exit report");
    this.run.processExitCount = 1;
    this.run.processExitCode = report.exitCode;
    ++this.processExitDispatches;
    if (report.exitCode !== 0) this.fail();
  }

  reportRuntimeInitialized(module) {
    this.noteCallback();
    if (!this.active || this.run.runtimeInitialized ||
        !module || (typeof module !== "object" && typeof module !== "function")) {
      this.fail();
      return;
    }
    this.run.runtimeInitialized = true;
    this.run.freshModuleObject = true;
  }

  reportRuntimeExit(code) {
    this.noteCallback();
    if (!this.active || !Number.isSafeInteger(code) || this.run.onExitCount !== 0 ||
        this.run.processExitCount !== 1 || this.run.processExitCode !== 0) {
      this.fail();
      return;
    }
    this.run.processExitBeforeOnExit = true;
    this.run.onExitCount = 1;
    this.run.runtimeExitCode = code;
    if (code !== 0) this.fail();
  }

  reportAbort(_reason) {
    this.noteCallback();
    if (this.run.abortObserved) this.fail();
    this.run.abortObserved = true;
    this.fail();
  }

  captureOutput(destination, line) {
    this.noteCallback();
    if (!this.active || typeof line !== "string") {
      this.fail();
      return;
    }
    if (!line.startsWith(MARKER_PREFIX)) return;
    if (destination !== "stderr") {
      ++this.run.stdoutMarkerCount;
      this.fail();
      return;
    }
    if (line.startsWith(FAIL_PREFIX)) {
      this.run.noFailMarkerObserved = false;
      this.fail();
      return;
    }
    const index = this.run.markers.length;
    if (index >= EXPECTED_MARKERS.length || line !== EXPECTED_MARKERS[index]) {
      this.run.markerSequenceAccepted = false;
      this.run.unexpectedMarkerObserved = true;
      this.fail();
      return;
    }
    this.run.markers.push(line);
  }

  settleFactoryResolved(module) {
    this.noteCallback();
    if (!this.active || this.run.factorySettled || !module ||
        (typeof module !== "object" && typeof module !== "function")) {
      this.fail();
      return;
    }
    this.run.factorySettled = true;
    this.run.factoryOutcome = "resolved";
  }

  settleFactoryRejected(error) {
    this.noteCallback();
    if (!this.active || this.run.factorySettled) {
      this.fail();
      return;
    }
    this.run.factorySettled = true;
    if (isExactNormalExitStatus(error)) {
      this.run.factoryOutcome = "expected-normal-exit-status";
      return;
    }
    this.fail();
  }

  lifecycleReady() {
    return !this.failure && this.active && this.run.runtimeInitialized &&
        this.run.factorySettled &&
        (this.run.factoryOutcome === "resolved" ||
         this.run.factoryOutcome === "expected-normal-exit-status") &&
        this.run.markers.length === EXPECTED_MARKERS.length &&
        this.run.markers.every((marker, index) => marker === EXPECTED_MARKERS[index]) &&
        this.run.markerSequenceAccepted && this.run.noFailMarkerObserved &&
        !this.run.unexpectedMarkerObserved && !this.run.abortObserved &&
        this.run.processExitCount === 1 && this.run.processExitCode === 0 &&
        this.run.onExitCount === 1 && this.run.runtimeExitCode === 0 &&
        this.run.processExitBeforeOnExit && this.processExitDispatches === 1;
  }

  async prepareFactory() {
    const loaderUrl = new URL(
        `./artifacts/${PRODUCT_MODULE_NAME}.js`, location.href);
    const wasmUrl = new URL(
        `./artifacts/${PRODUCT_MODULE_NAME}.wasm`, location.href);
    if (loaderUrl.origin !== location.origin || wasmUrl.origin !== location.origin) {
      throw new Error("policy probe artifact origin is invalid");
    }
    const [loaderBytes, wasmBytes] = await Promise.all([
      fetchVerifiedArtifact(loaderUrl, this.context.artifact.loader,
                            "text/javascript", "policy probe loader"),
      fetchVerifiedArtifact(wasmUrl, this.context.artifact.wasm,
                            "application/wasm", "policy probe Wasm"),
    ]);
    if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("policy probe fresh loader import is unavailable");
    }
    this.loaderImportUrl = URL.createObjectURL(
        new Blob([loaderBytes], {type: "text/javascript"}));
    let namespace;
    try {
      namespace = await import(this.loaderImportUrl);
    } catch (error) {
      URL.revokeObjectURL(this.loaderImportUrl);
      this.loaderImportUrl = null;
      throw error;
    }
    if (typeof namespace.default !== "function") {
      URL.revokeObjectURL(this.loaderImportUrl);
      this.loaderImportUrl = null;
      throw new Error("policy probe loader has no default factory export");
    }
    return {factory: namespace.default, wasmBinary: wasmBytes, wasmUrl};
  }

  result(status, error, quiescence) {
    const lifecycleComplete = this.lifecycleCompleted;
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m7GateComplete: false,
      origin: location.origin,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      artifact: this.context.artifact,
      capture_harness: this.context.captureHarness,
      versions: this.context.versions,
      exactEmptyProbeSwitchPassed: true,
      freshSourceSelectedPolicyArtifactProven: true,
      defaultConfigDefaultNotInMemoryProven:
          lifecycleComplete && this.run.markers[0] === EXPECTED_MARKERS[0],
      policyFenceProven:
          lifecycleComplete && this.run.markers[1] === EXPECTED_MARKERS[1],
      policyProbeCompleteProven:
          lifecycleComplete && this.run.markers[2] === EXPECTED_MARKERS[2],
      normalProcessExitAndAckProven: lifecycleComplete,
      actualStoragePartitionProven: false,
      profilePersistenceProven: false,
      freshDocumentReloadProven: false,
      crashRecoveryProven: false,
      hostBoundary: {
        hostDomStorageAccessAttempted: false,
        hostOpfsAccessAttempted: false,
        hostWebLocksAccessAttempted: false,
        nativeCallAttempted: false,
        wasmDataInspectionAttempted: false,
      },
      run: {
        arguments: Array.from(EXACT_PROBE_ARGUMENTS),
        abortObserved: this.run.abortObserved,
        factoryOutcome: this.run.factoryOutcome,
        factorySettled: this.run.factorySettled,
        freshModuleObject: this.run.freshModuleObject,
        markerCount: this.run.markers.length,
        markerSequenceAccepted: this.run.markerSequenceAccepted,
        markerSource: "stderr-only-fixed-policy-probe-grammar",
        markers: this.run.markers.slice(),
        noFailMarkerObserved: this.run.noFailMarkerObserved,
        normalProcessExitAndAckReceived: lifecycleComplete,
        onExitCount: this.run.onExitCount,
        processExitBeforeOnExit: this.run.processExitBeforeOnExit,
        processExitCode: this.run.processExitCode,
        processExitCount: this.run.processExitCount,
        runtimeExitCode: this.run.runtimeExitCode,
        runtimeInitialized: this.run.runtimeInitialized,
        stdoutMarkerCount: this.run.stdoutMarkerCount,
        unexpectedMarkerObserved: this.run.unexpectedMarkerObserved,
      },
      bridge: {
        activeAtResult: this.active,
        installedBeforeModuleFactory: this.bridgeInstalled,
        noActiveProcessExitRejected: this.noActiveProcessExitRejected,
        permanent: true,
        processExitDispatches: this.processExitDispatches,
        protocol: HOST_PROTOCOL,
        duplicateProcessExitRejected: this.duplicateProcessExitRejected,
        frozen: this.bridgeInstalled &&
            Object.isFrozen(globalThis.__chromiumWasmHostBridgeV1),
      },
      quiescence,
      error,
    };
  }

  async runProbe() {
    let quiescence = {
      callbacksAfterQuietWindow: null,
      callbacksAtLifecycleComplete: null,
      quiet: false,
      quietWindowMs: FINAL_QUIESCENCE_MS,
    };
    try {
      if (globalThis.crossOriginIsolated !== true ||
          typeof SharedArrayBuffer !== "function") {
        throw new Error("policy probe requires cross-origin isolation");
      }
      this.canvas.focus({preventScroll: true});
      if (document.activeElement !== this.canvas) {
        throw new Error("policy probe canvas focus failed");
      }
      this.installBridge();
      this.installFailureObservers();
      const prepared = await this.prepareFactory();
      this.active = true;
      const host = this;
      let factoryResult;
      try {
        factoryResult = prepared.factory({
          // Emscripten prepends its program name to Module.arguments during
          // startup. Preserve the immutable one-switch contract separately,
          // but give the generated loader an isolated mutable copy.
          arguments: Array.from(EXACT_PROBE_ARGUMENTS),
          canvas: this.canvas,
          locateFile(path) {
            if (path !== PRODUCT_MODULE_NAME + ".wasm") {
              throw new Error("policy probe loader requested an unexpected artifact");
            }
            return prepared.wasmUrl.href;
          },
          mainScriptUrlOrBlob: this.loaderImportUrl,
          noExitRuntime: false,
          onAbort(reason) { host.reportAbort(reason); },
          onExit(code) { host.reportRuntimeExit(Number(code)); },
          onRuntimeInitialized() { host.reportRuntimeInitialized(this); },
          print(line) { host.captureOutput("stdout", line); },
          printErr(line) { host.captureOutput("stderr", line); },
          wasmBinary: prepared.wasmBinary,
        });
      } catch (error) {
        this.settleFactoryRejected(error);
        factoryResult = null;
      }
      if (factoryResult !== null) {
        Promise.resolve(factoryResult).then(
            (module) => host.settleFactoryResolved(module),
            (error) => host.settleFactoryRejected(error));
      }
      const deadline = performance.now() + this.context.timeoutMs;
      while (performance.now() < deadline && !this.failure &&
             !this.lifecycleReady()) {
        await delay(10);
      }
      if (!this.lifecycleReady()) {
        this.fail();
        return this.result("fail", "details-suppressed", quiescence);
      }
      this.lifecycleCompleted = true;
      this.active = false;
      quiescence.callbacksAtLifecycleComplete = this.callbackCount;
      await delay(FINAL_QUIESCENCE_MS);
      quiescence.callbacksAfterQuietWindow = this.callbackCount;
      quiescence.quiet = !this.failure &&
          quiescence.callbacksAtLifecycleComplete ===
              quiescence.callbacksAfterQuietWindow;
      if (!quiescence.quiet) {
        this.fail();
        return this.result("fail", "details-suppressed", quiescence);
      }
      const result = this.result("pass", null, quiescence);
      validateChromeWasmPersistentDefaultPartitionPolicyProbeResult(result);
      return result;
    } catch (_error) {
      this.fail();
      return this.result("fail", "details-suppressed", quiescence);
    } finally {
      this.releaseFailureObservers();
      if (this.loaderImportUrl !== null) {
        URL.revokeObjectURL(this.loaderImportUrl);
        this.loaderImportUrl = null;
      }
    }
  }
}

function validateByteIdentity(value, description) {
  const identity = requireExactFields(value, ["bytes", "sha256"], description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" || !SHA256_RE.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
}

export function validateChromeWasmPersistentDefaultPartitionPolicyProbeResult(result) {
  requireExactFields(result, RESULT_FIELDS, "policy probe result");
  if (result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
      result.scope !== SCOPE || result.status !== "pass" ||
      result.m7GateComplete !== false || result.origin !== location.origin ||
      result.crossOriginIsolated !== true || result.sharedArrayBuffer !== true ||
      result.exactEmptyProbeSwitchPassed !== true ||
      result.freshSourceSelectedPolicyArtifactProven !== true ||
      result.defaultConfigDefaultNotInMemoryProven !== true ||
      result.policyFenceProven !== true || result.policyProbeCompleteProven !== true ||
      result.normalProcessExitAndAckProven !== true ||
      result.actualStoragePartitionProven !== false ||
      result.profilePersistenceProven !== false ||
      result.freshDocumentReloadProven !== false ||
      result.crashRecoveryProven !== false || result.error !== null) {
    throw new Error("policy probe result is invalid");
  }
  const artifact = requireExactFields(result.artifact, ARTIFACT_FIELDS,
                                      "policy probe result artifact");
  if (artifact.module_name !== PRODUCT_MODULE_NAME ||
      artifact.artifact_delivery !== "immutable-in-memory-server-snapshot" ||
      artifact.artifact_source_provenance !== "unverified" ||
      artifact.build_config_provenance !==
          "selected-out-dir-args-gn-immutable-snapshot") {
    throw new Error("policy probe result artifact is invalid");
  }
  for (const field of ["build_config", "loader", "wasm"]) {
    validateByteIdentity(artifact[field], `policy probe artifact ${field}`);
  }
  const capture = requireExactFields(result.capture_harness,
                                     CAPTURE_HARNESS_FIELDS,
                                     "policy probe result capture harness");
  if (capture.source_snapshot_provenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      capture.version_provenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    throw new Error("policy probe result capture harness is invalid");
  }
  for (const field of ["host_html", "host_js", "runner_source"]) {
    validateByteIdentity(capture[field], `policy probe capture ${field}`);
  }
  requireExactFields(result.versions, ["chromium", "v8", "emscripten"],
                     "policy probe result versions");
  if (Object.values(result.versions).some((value) =>
      typeof value !== "string" || !GIT_REVISION_RE.test(value))) {
    throw new Error("policy probe result versions are invalid");
  }
  const run = requireExactFields(result.run, RUN_FIELDS, "policy probe run");
  if (JSON.stringify(run.arguments) !== JSON.stringify(EXACT_PROBE_ARGUMENTS) ||
      run.abortObserved !== false ||
      !["resolved", "expected-normal-exit-status"].includes(run.factoryOutcome) ||
      run.factorySettled !== true || run.freshModuleObject !== true ||
      run.markerCount !== EXPECTED_MARKERS.length ||
      run.markerSequenceAccepted !== true ||
      run.markerSource !== "stderr-only-fixed-policy-probe-grammar" ||
      JSON.stringify(run.markers) !== JSON.stringify(EXPECTED_MARKERS) ||
      run.noFailMarkerObserved !== true ||
      run.normalProcessExitAndAckReceived !== true || run.onExitCount !== 1 ||
      run.processExitBeforeOnExit !== true || run.processExitCode !== 0 ||
      run.processExitCount !== 1 || run.runtimeExitCode !== 0 ||
      run.runtimeInitialized !== true || run.stdoutMarkerCount !== 0 ||
      run.unexpectedMarkerObserved !== false) {
    throw new Error("policy probe run is invalid");
  }
  const bridge = requireExactFields(result.bridge, BRIDGE_FIELDS,
                                    "policy probe bridge");
  if (bridge.activeAtResult !== false ||
      bridge.installedBeforeModuleFactory !== true ||
      bridge.noActiveProcessExitRejected !== 0 || bridge.permanent !== true ||
      bridge.processExitDispatches !== 1 || bridge.protocol !== HOST_PROTOCOL ||
      bridge.duplicateProcessExitRejected !== 0 || bridge.frozen !== true) {
    throw new Error("policy probe bridge is invalid");
  }
  const quiescence = requireExactFields(result.quiescence, QUIESCENCE_FIELDS,
                                         "policy probe quiescence");
  if (quiescence.quiet !== true ||
      quiescence.quietWindowMs !== FINAL_QUIESCENCE_MS ||
      !Number.isSafeInteger(quiescence.callbacksAtLifecycleComplete) ||
      !Number.isSafeInteger(quiescence.callbacksAfterQuietWindow) ||
      quiescence.callbacksAtLifecycleComplete < 0 ||
      quiescence.callbacksAfterQuietWindow !==
          quiescence.callbacksAtLifecycleComplete) {
    throw new Error("policy probe quiescence is invalid");
  }
  const boundary = requireExactFields(result.hostBoundary, HOST_BOUNDARY_FIELDS,
                                      "policy probe host boundary");
  if (Object.values(boundary).some((value) => value !== false)) {
    throw new Error("policy probe host boundary is invalid");
  }
  return result;
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("policy probe version element is missing");
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

async function postJson(url, body, description) {
  const response = await fetch(url.href, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${description} was not acknowledged`);
}

export async function runChromeWasmPersistentDefaultPartitionPolicyProbeFromQuery() {
  const context = parseContext();
  const root = document.querySelector(
      "#m7-persistent-default-partition-policy-probe-root");
  const canvas = document.querySelector(
      "#m7-persistent-default-partition-policy-probe-canvas");
  const status = document.querySelector(
      "#m7-persistent-default-partition-policy-probe-status");
  const versions = document.querySelector(
      "#m7-persistent-default-partition-policy-probe-versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("policy probe page is missing required elements");
  }
  renderVersions(versions, context.versions);
  const host = new PersistentDefaultPartitionPolicyProbeHost(canvas, context);
  const result = await host.runProbe();
  root.dataset.state = result.status;
  status.textContent = result.status === "pass" ? "pass" : "fail";
  const resultUrl = new URL(
      `./result/${encodeURIComponent(context.resultToken)}`, location.href);
  const acknowledgementUrl = new URL(
      `./ack/${encodeURIComponent(context.resultToken)}`, location.href);
  if (resultUrl.origin !== location.origin ||
      acknowledgementUrl.origin !== location.origin) {
    throw new Error("policy probe receipt endpoint is invalid");
  }
  await postJson(resultUrl, result, "policy probe result receipt");
  await postJson(acknowledgementUrl, {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
  }, "policy probe result acknowledgement");
  return result;
}

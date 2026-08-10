// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Two-document, same-origin OPFS/WasmFS feasibility host. It deliberately
// owns no persistent state: OPFS operations belong exclusively to the WasmFS
// C++ smoke. The only OPFS-related JavaScript work here is a capability
// inspection; it never invokes the OPFS directory method.

const HOST_PROTOCOL = 1;
const CASE = "m7_wasmfs_opfs_outer_reload";
const SCOPE = "isolated-wasmfs-opfs-two-document-same-origin";
const PERSISTENCE_SCOPE = "primitive-opfs-persistence-only";
const MODULE_NAME = "m7_wasmfs_opfs_smoke";
const WRITE_PHASE = "write";
const VERIFY_PHASE = "verify";
const PHASE_SWITCH = "--m7-opfs-phase=";
const RUN_SWITCH = "--m7-opfs-run=";
const WRITE_READY_MARKER = "CHROMIUM_WASM_M7_OPFS:WRITE_READY";
const VERIFY_STARTED_MARKER = "CHROMIUM_WASM_M7_OPFS:VERIFY_STARTED";
const PASS_MARKER = "CHROMIUM_WASM_M7_OPFS:PASS";
const FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS:FAIL";
const MAX_TIMEOUT_MS = 180000;
const MAX_OUTPUT_LINES = 128;
const CAPABILITY_PROBE_TIMEOUT_MS = 5000;
const CAPABILITY_PROBE_PROTOCOL = 1;
// A native PASS is sent from an application pthread. Give an immediately
// proxied abort or onExit callback one event-loop turn to arrive before we
// claim that this document is keeping its runtime alive for outer teardown.
const COMPLETION_SETTLE_MS = 25;
const RUN_NAMESPACE_RE = /^[A-Za-z0-9_-]{16,128}$/;
const MODULE_ID_RE = /^[a-f0-9]{32}$/;

// Sync access handles are exposed only inside a dedicated worker. This worker
// inspects API shapes only: it must not acquire the OPFS root, a file handle,
// or an access handle. The C++ WasmFS executable remains the only code that
// performs OPFS operations for this smoke.
const CAPABILITY_PROBE_SOURCE = `
const capability = self.isSecureContext === true &&
    self.crossOriginIsolated === true &&
    typeof SharedArrayBuffer === "function" &&
    typeof navigator === "object" && navigator !== null &&
    typeof navigator.storage === "object" && navigator.storage !== null &&
    typeof navigator.storage.getDirectory === "function" &&
    typeof FileSystemFileHandle === "function" &&
    typeof FileSystemFileHandle.prototype.createSyncAccessHandle === "function";
self.postMessage({protocol: ${CAPABILITY_PROBE_PROTOCOL}, capability});
`;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function redactRunNamespace(value, runNamespace) {
  return String(value).split(runNamespace).join("<run-namespace>");
}

function appendBounded(values, value, runNamespace) {
  const redactedValue = redactRunNamespace(value, runNamespace);
  values.push(redactedValue);
  if (values.length > MAX_OUTPUT_LINES) {
    values.splice(0, values.length - MAX_OUTPUT_LINES);
  }
  return redactedValue;
}

function oneQueryValue(query, name) {
  const values = query.getAll(name);
  if (values.length !== 1 || values[0] === "") {
    throw new Error("query parameter " + name + " must occur exactly once");
  }
  return values[0];
}

function requireOnlyQueryParameters(query, allowedNames) {
  for (const name of query.keys()) {
    if (!allowedNames.has(name)) {
      throw new Error("unexpected M7 OPFS query parameter: " + name);
    }
  }
}

function parseTimeout(value) {
  if (!/^[0-9]+$/.test(value)) {
    throw new Error("timeoutMs is invalid");
  }
  const timeout = Number(value);
  if (!Number.isSafeInteger(timeout) || timeout < 1000 || timeout > MAX_TIMEOUT_MS) {
    throw new Error("timeoutMs is out of range");
  }
  return timeout;
}

function parseTimeOrigin(value) {
  if (!/^[0-9]+(?:\.[0-9]+)?$/.test(value)) {
    throw new Error("priorTimeOrigin is invalid");
  }
  const origin = Number(value);
  if (!Number.isFinite(origin) || origin <= 0) {
    throw new Error("priorTimeOrigin is out of range");
  }
  return origin;
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function createModuleIdentity() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return hex(bytes);
}

function hasRequiredDocumentPrerequisites() {
  // Do not invoke the directory method here. Calling it would read or
  // initialize the host origin's OPFS, which this host must never do.
  return globalThis.isSecureContext === true &&
      globalThis.crossOriginIsolated === true &&
      typeof SharedArrayBuffer === "function" &&
      typeof navigator === "object" && navigator !== null &&
      typeof navigator.storage === "object" && navigator.storage !== null &&
      typeof navigator.storage.getDirectory === "function";
}

async function probeRequiredOpfsCapability() {
  if (!hasRequiredDocumentPrerequisites() || typeof Worker !== "function" ||
      typeof Blob !== "function" || typeof URL.createObjectURL !== "function") {
    return false;
  }
  const workerUrl = URL.createObjectURL(new Blob([CAPABILITY_PROBE_SOURCE], {
    type: "text/javascript",
  }));
  return new Promise((resolve) => {
    let finished = false;
    let probeWorker = null;
    let timeoutId = null;
    const finish = (capability) => {
      if (finished) {
        return;
      }
      finished = true;
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
      }
      probeWorker?.terminate();
      URL.revokeObjectURL(workerUrl);
      resolve(capability === true);
    };
    try {
      probeWorker = new Worker(workerUrl, {
        name: "chromium-wasm-m7-opfs-capability",
        type: "module",
      });
    } catch {
      URL.revokeObjectURL(workerUrl);
      resolve(false);
      return;
    }
    timeoutId = setTimeout(() => finish(false), CAPABILITY_PROBE_TIMEOUT_MS);
    probeWorker.onmessage = (event) => {
      const payload = event.data;
      finish(payload !== null && typeof payload === "object" &&
          payload.protocol === CAPABILITY_PROBE_PROTOCOL &&
          payload.capability === true);
    };
    probeWorker.onmessageerror = () => finish(false);
    probeWorker.onerror = (event) => {
      event.preventDefault();
      finish(false);
    };
  });
}

function staticContext(query) {
  const token = oneQueryValue(query, "token");
  const phase = oneQueryValue(query, "phase");
  const runNamespace = oneQueryValue(query, "run");
  const timeoutMs = parseTimeout(oneQueryValue(query, "timeoutMs"));
  if (!RUN_NAMESPACE_RE.test(token) || !RUN_NAMESPACE_RE.test(runNamespace) ||
      (phase !== WRITE_PHASE && phase !== VERIFY_PHASE)) {
    throw new Error("M7 OPFS smoke query is invalid");
  }

  let priorTimeOrigin = null;
  let priorModuleIdentity = null;
  let outerReload = false;
  if (phase === VERIFY_PHASE) {
    requireOnlyQueryParameters(query, new Set([
      "token", "phase", "run", "timeoutMs", "priorTimeOrigin",
      "priorModuleIdentity", "outerReload",
    ]));
    priorTimeOrigin = parseTimeOrigin(oneQueryValue(query, "priorTimeOrigin"));
    priorModuleIdentity = oneQueryValue(query, "priorModuleIdentity");
    outerReload = oneQueryValue(query, "outerReload") === "1";
    if (!MODULE_ID_RE.test(priorModuleIdentity) || !outerReload) {
      throw new Error("M7 OPFS verify query lacks a fresh outer reload witness");
    }
  } else if (query.has("priorTimeOrigin") || query.has("priorModuleIdentity") ||
             query.has("outerReload")) {
    throw new Error("M7 OPFS write query contains reload-only state");
  } else {
    requireOnlyQueryParameters(query, new Set([
      "token", "phase", "run", "timeoutMs",
    ]));
  }

  return {
    token,
    phase,
    runNamespace,
    timeoutMs,
    priorTimeOrigin,
    priorModuleIdentity,
    outerReload,
  };
}

function formatError(error) {
  return error instanceof Error ? error.message : String(error);
}

function outputContains(output, marker) {
  return output.stdout.some((line) => line.includes(marker)) ||
      output.stderr.some((line) => line.includes(marker));
}

function outputContainsExact(output, marker) {
  return output.stdout.some((line) => line === marker) ||
      output.stderr.some((line) => line === marker);
}

function expectedPassMarker(phase) {
  return PASS_MARKER + " phase=" + phase;
}

function nativeMarkerFailure(context, output) {
  if (outputContains(output, FAIL_MARKER)) {
    return "native WasmFS OPFS smoke emitted FAIL";
  }
  if (!outputContainsExact(output, expectedPassMarker(context.phase))) {
    return "native WasmFS OPFS smoke did not emit its exact PASS marker";
  }
  const expected = context.phase === WRITE_PHASE ?
      WRITE_READY_MARKER : VERIFY_STARTED_MARKER;
  if (!outputContains(output, expected)) {
    return "native WasmFS OPFS smoke did not emit its phase marker";
  }
  return null;
}

function updateVisibleState(result) {
  const root = document.querySelector("#m7-opfs-root");
  const status = document.querySelector("#m7-opfs-status");
  if (root instanceof HTMLElement) {
    root.dataset.state = result.status;
  }
  if (status instanceof HTMLElement) {
    const display = {
      ...result,
      // The server needs the opaque namespace to authenticate the result, but
      // the browser-visible diagnostic must not disclose it.
      runNamespace: "<redacted>",
    };
    status.textContent = JSON.stringify(display, null, 2);
  }
  globalThis.__chromiumWasmM7WasmfsOpfsState = Object.freeze({
    protocol: HOST_PROTOCOL,
    case: CASE,
    phase: result.phase,
    status: result.status,
    timeOrigin: result.timeOrigin,
    freshOuterDocument: result.freshOuterDocument,
    freshModuleIdentity: result.freshModuleIdentity,
  });
}

function waitForRuntimeCompletion(runtimeCompletion, timeoutMs) {
  let timeoutId = null;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error("M7 OPFS runtime did not report exact PASS before timeout"));
    }, timeoutMs);
  });
  return Promise.race([runtimeCompletion, timeout]).finally(() => {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  });
}

function bindModuleIdentity(module, moduleIdentity) {
  const identityProperty = "__chromiumWasmM7WasmfsOpfsModuleIdentity";
  if (Object.prototype.hasOwnProperty.call(module, identityProperty)) {
    throw new Error("M7 OPFS Module identity property already exists");
  }
  Object.defineProperty(module, identityProperty, {
    configurable: false,
    enumerable: false,
    value: moduleIdentity,
    writable: false,
  });
  if (module[identityProperty] !== moduleIdentity) {
    throw new Error("M7 OPFS Module identity was not retained");
  }
}

async function runRuntime(context) {
  const output = {stdout: [], stderr: []};
  let module = null;
  let runtimeExitCode = null;
  let factorySettled = false;
  let runtimeInitialized = false;
  let factoryError = null;
  let abort = null;
  let completionObserved = false;
  let completionMarker = null;
  let completionError = null;
  let reportCompletion = null;
  let reportExit = null;
  const runtimeCompletion = new Promise((resolve) => {
    reportCompletion = (marker, error) => {
      if (completionObserved || completionError !== null) {
        return;
      }
      if (error !== null) {
        completionError = error;
      } else {
        completionObserved = true;
        completionMarker = marker;
      }
      resolve();
    };
    reportExit = (code) => {
      if (runtimeExitCode === null) {
        runtimeExitCode = Number(code);
      }
      if (!completionObserved) {
        reportCompletion(null, "M7 OPFS runtime exited before exact PASS");
      }
    };
  });
  const expectedCompletionMarker = expectedPassMarker(context.phase);
  const captureNativeOutput = (destination, line) => {
    const capturedLine = appendBounded(destination, line, context.runNamespace);
    if (capturedLine.startsWith(FAIL_MARKER)) {
      reportCompletion(null, "native WasmFS OPFS smoke emitted FAIL");
    } else if (capturedLine === expectedCompletionMarker) {
      reportCompletion(capturedLine, null);
    }
  };

  const moduleUrl = new URL("./artifacts/" + MODULE_NAME + ".js", location.href);
  if (moduleUrl.origin !== location.origin) {
    throw new Error("M7 OPFS module is not same-origin");
  }
  const moduleResponse = await fetch(moduleUrl.href, {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!moduleResponse.ok) {
    throw new Error("M7 OPFS module request returned HTTP " + moduleResponse.status);
  }
  const mainScriptUrlOrBlob = await moduleResponse.blob();
  if (mainScriptUrlOrBlob.size === 0) {
    throw new Error("M7 OPFS module loader is empty");
  }
  const namespace = await import(moduleUrl.href);
  if (typeof namespace.default !== "function") {
    throw new Error("M7 OPFS module loader has no default factory");
  }

  const factory = namespace.default({
    arguments: [
      PHASE_SWITCH + context.phase,
      RUN_SWITCH + context.runNamespace,
    ],
    noExitRuntime: false,
    mainScriptUrlOrBlob,
    locateFile: (path) => new URL(path, moduleUrl).href,
    print(line) { captureNativeOutput(output.stdout, line); },
    printErr(line) { captureNativeOutput(output.stderr, line); },
    onRuntimeInitialized() { runtimeInitialized = true; },
    onAbort(reason) {
      abort = String(reason);
      reportCompletion(null, "M7 OPFS runtime aborted before exact PASS");
    },
    onExit(code) { reportExit(code); },
  });
  const factoryPromise = Promise.resolve(factory).then((runtimeModule) => {
    module = runtimeModule;
    factorySettled = true;
    return runtimeModule;
  }).catch((error) => {
    factorySettled = true;
    factoryError = formatError(error);
    return null;
  });

  await factoryPromise;
  if (factoryError !== null) {
    throw new Error("M7 OPFS module factory rejected: " + factoryError);
  }
  if (!module || (typeof module !== "object" && typeof module !== "function")) {
    throw new Error("M7 OPFS module factory returned no Module identity");
  }
  const moduleIdentity = createModuleIdentity();
  bindModuleIdentity(module, moduleIdentity);
  await waitForRuntimeCompletion(runtimeCompletion, context.timeoutMs);
  await delay(COMPLETION_SETTLE_MS);
  if (completionError !== null) {
    throw new Error(completionError);
  }
  return {
    output,
    runtimeExitCode,
    factorySettled,
    runtimeInitialized,
    abort,
    completionObserved,
    completionMarker,
    moduleIdentity,
  };
}

function baseResult(context) {
  const timeOrigin = performance.timeOrigin;
  const freshOuterDocument = context.phase === VERIFY_PHASE &&
      context.outerReload && context.priorTimeOrigin !== null &&
      timeOrigin > context.priorTimeOrigin;
  return {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    phase: context.phase,
    runNamespace: context.runNamespace,
    status: "fail",
    origin: location.origin,
    crossOriginIsolated: globalThis.crossOriginIsolated === true,
    sharedArrayBuffer: typeof SharedArrayBuffer === "function",
    opfsCapability: false,
    opfsFallbackUsed: false,
    // This feasibility lane intentionally proves only primitive durable file
    // behavior. WasmFS currently shares an OPFS OpenState inside one module,
    // so it must not be represented as cross-module access-handle or Chromium
    // file-lock evidence.
    persistenceScope: PERSISTENCE_SCOPE,
    fileLockSemanticsProven: false,
    concurrentAccessHandleSemanticsProven: false,
    outerReload: context.outerReload,
    timeOrigin,
    priorTimeOrigin: context.priorTimeOrigin,
    moduleIdentity: null,
    priorModuleIdentity: context.priorModuleIdentity,
    freshOuterDocument,
    freshModuleIdentity: false,
    runtimeExitCode: null,
    completionObserved: false,
    completionMarker: null,
    runtimeLifecycle: "not-observed",
    // The target intentionally retains its live runtime after the exact PASS
    // marker. The following location.replace() destroys this isolated outer
    // document; it is not a graceful WasmFS/backend/thread shutdown claim.
    teardownMode: "outer-document",
    factorySettled: false,
    runtimeInitialized: false,
    abort: null,
    stdout: [],
    stderr: [],
    error: null,
  };
}

async function executePhase(context) {
  const result = baseResult(context);
  result.opfsCapability = await probeRequiredOpfsCapability();
  if (!result.opfsCapability) {
    result.error = "required OPFS synchronous-access capability is unavailable";
    return result;
  }
  if (context.phase === VERIFY_PHASE && !result.freshOuterDocument) {
    result.error = "verify phase did not start in a fresh outer document";
    return result;
  }

  try {
    const runtime = await runRuntime(context);
    result.runtimeExitCode = runtime.runtimeExitCode;
    result.completionObserved = runtime.completionObserved;
    result.completionMarker = runtime.completionMarker;
    result.factorySettled = runtime.factorySettled;
    result.runtimeInitialized = runtime.runtimeInitialized;
    result.abort = runtime.abort;
    result.stdout = runtime.output.stdout;
    result.stderr = runtime.output.stderr;
    result.moduleIdentity = runtime.moduleIdentity;
    result.freshModuleIdentity = context.phase === VERIFY_PHASE &&
        context.priorModuleIdentity !== null &&
        result.moduleIdentity !== context.priorModuleIdentity;
    const markerFailure = nativeMarkerFailure(context, runtime.output);
    result.runtimeLifecycle = runtime.completionObserved &&
        runtime.runtimeExitCode === null && runtime.abort === null ?
        "live-runtime" : "not-live-runtime";
    if (runtime.runtimeExitCode !== null) {
      result.error = "M7 OPFS runtime exited instead of remaining live";
    } else if (runtime.abort !== null) {
      result.error = "M7 OPFS runtime aborted";
    } else if (!runtime.completionObserved ||
               runtime.completionMarker !== expectedPassMarker(context.phase)) {
      result.error = "M7 OPFS runtime did not report exact PASS completion";
    } else if (!runtime.runtimeInitialized) {
      result.error = "M7 OPFS runtime never initialized";
    } else if (context.phase === VERIFY_PHASE && !result.freshModuleIdentity) {
      result.error = "verify phase did not create a fresh Module";
    } else if (markerFailure !== null) {
      result.error = markerFailure;
    } else {
      result.status = "pass";
    }
  } catch (error) {
    result.error = formatError(error);
  }
  return result;
}

async function postResult(context, result) {
  const endpoint = new URL(
      "./result/" + encodeURIComponent(context.token) + "/" + context.phase,
      location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("M7 OPFS result endpoint is not same-origin");
  }
  const response = await fetch(endpoint.href, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (response.status !== 204) {
    throw new Error("M7 OPFS result upload returned HTTP " + response.status);
  }
}

function verifyResultShape(result) {
  if (result.status !== "pass" || result.opfsFallbackUsed !== false ||
      result.crossOriginIsolated !== true || result.sharedArrayBuffer !== true ||
      result.opfsCapability !== true || result.origin !== location.origin ||
      result.persistenceScope !== PERSISTENCE_SCOPE ||
      result.fileLockSemanticsProven !== false ||
      result.concurrentAccessHandleSemanticsProven !== false ||
      result.runtimeInitialized !== true ||
      result.factorySettled !== true || result.runtimeExitCode !== null ||
      result.completionObserved !== true ||
      result.completionMarker !== expectedPassMarker(result.phase) ||
      result.runtimeLifecycle !== "live-runtime" ||
      result.teardownMode !== "outer-document" ||
      result.abort !== null || result.error !== null) {
    throw new Error("M7 OPFS runtime result is incomplete");
  }
  if (result.phase === VERIFY_PHASE &&
      (!result.outerReload || !result.freshOuterDocument || !result.freshModuleIdentity)) {
    throw new Error("M7 OPFS verify result lacks fresh outer-reload proof");
  }
  if (result.phase === WRITE_PHASE &&
      (result.outerReload || result.freshOuterDocument || result.freshModuleIdentity)) {
    throw new Error("M7 OPFS write result contains outer-reload evidence");
  }
}

export async function runM7WasmfsOpfsSmokeFromQuery() {
  const context = staticContext(new URLSearchParams(location.search));
  const result = await executePhase(context);
  updateVisibleState(result);
  await postResult(context, result);
  verifyResultShape(result);

  if (context.phase === WRITE_PHASE) {
    // This is intentionally a whole-document navigation. The verify phase has
    // a new JavaScript realm, a new Emscripten factory, and a new Wasm Module.
    // It is the intentional teardown boundary for the write runtime, which
    // remains live after its exact PASS marker; no graceful runtime shutdown
    // is exercised or claimed by this smoke.
    const verifyUrl = new URL(location.href);
    verifyUrl.searchParams.set("phase", VERIFY_PHASE);
    verifyUrl.searchParams.set("outerReload", "1");
    verifyUrl.searchParams.set("priorTimeOrigin", String(result.timeOrigin));
    verifyUrl.searchParams.set("priorModuleIdentity", result.moduleIdentity);
    location.replace(verifyUrl.href);
  }
  return result;
}

export const m7WasmfsOpfsSmokeContract = Object.freeze({
  protocol: HOST_PROTOCOL,
  case: CASE,
  scope: SCOPE,
  phases: Object.freeze([WRITE_PHASE, VERIFY_PHASE]),
  nativeMarkers: Object.freeze([
    WRITE_READY_MARKER,
    VERIFY_STARTED_MARKER,
    PASS_MARKER,
    FAIL_MARKER,
  ]),
});

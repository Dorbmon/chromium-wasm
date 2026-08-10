// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Same-document, two-Wasm-module OPFS writer-exclusivity probe. The host never
// acquires an OPFS root, file, or access handle. All filesystem operations are
// confined to the C++ WasmFS target; this page only coordinates independent
// Emscripten Module factories and reports their trusted native markers.

const HOST_PROTOCOL = 1;
const CASE = "m7_wasmfs_opfs_writer_exclusivity";
const SCOPE = "isolated-wasmfs-opfs-two-live-modules-same-document";
const EXCLUSIVITY_SCOPE = "opfs-sync-access-handle-writer-exclusivity-only";
const MODULE_NAME = "m7_wasmfs_opfs_exclusivity_smoke";
const CONTENTION_PHASE = "contention";
const REOPEN_PHASE = "reopen";
const HOLDER_ROLE = "holder";
const CONTENDER_ROLE = "contender";
const REOPEN_ROLE = "reopen";
const ROLE_SWITCH = "--m7-opfs-role=";
const RUN_SWITCH = "--m7-opfs-run=";
const HOLDER_READY_MARKER =
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:HOLDER_READY access_fd_held=1 fdatasync=ok";
const CONTENDER_OPEN_BEGIN_MARKER =
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:CONTENDER_OPEN_BEGIN mode=O_RDWR";
const CONTENDER_EACCES_MARKER =
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:CONTENDER_EACCES errno=eacces";
const REOPEN_OK_MARKER =
    "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:REOPEN_OK cleanup=ok";
const FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:FAIL";
const MAX_TIMEOUT_MS = 180000;
const MAX_OUTPUT_LINES = 128;
const CAPABILITY_PROBE_TIMEOUT_MS = 5000;
const CAPABILITY_PROBE_PROTOCOL = 1;
const COMPLETION_SETTLE_MS = 25;
const RUN_NAMESPACE_RE = /^[A-Za-z0-9_-]{16,128}$/;
const MODULE_ID_RE = /^[a-f0-9]{32}$/;
const ACTIVE_RUNTIMES_PROPERTY =
    "__chromiumWasmM7WasmfsOpfsExclusivityActiveRuntimes";

// Sync access handles are available only in a dedicated worker. This probe
// checks API shape only and never calls getDirectory(), gets a file handle, or
// creates an access handle. The C++ WasmFS target remains the sole OPFS user.
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
      throw new Error("unexpected M7 OPFS exclusivity query parameter: " + name);
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
  // This must remain a shape check. Calling getDirectory() here would touch
  // OPFS outside the WasmFS executable and invalidate the probe's boundary.
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
        name: "chromium-wasm-m7-opfs-exclusivity-capability",
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
      (phase !== CONTENTION_PHASE && phase !== REOPEN_PHASE)) {
    throw new Error("M7 OPFS exclusivity query is invalid");
  }

  let priorTimeOrigin = null;
  let priorHolderModuleIdentity = null;
  let priorContenderModuleIdentity = null;
  let outerReload = false;
  if (phase === REOPEN_PHASE) {
    requireOnlyQueryParameters(query, new Set([
      "token", "phase", "run", "timeoutMs", "priorTimeOrigin",
      "priorHolderModuleIdentity", "priorContenderModuleIdentity", "outerReload",
    ]));
    priorTimeOrigin = parseTimeOrigin(oneQueryValue(query, "priorTimeOrigin"));
    priorHolderModuleIdentity = oneQueryValue(query, "priorHolderModuleIdentity");
    priorContenderModuleIdentity = oneQueryValue(
        query, "priorContenderModuleIdentity");
    outerReload = oneQueryValue(query, "outerReload") === "1";
    if (!MODULE_ID_RE.test(priorHolderModuleIdentity) ||
        !MODULE_ID_RE.test(priorContenderModuleIdentity) || !outerReload) {
      throw new Error("M7 OPFS reopen query lacks outer-reload witnesses");
    }
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
    priorHolderModuleIdentity,
    priorContenderModuleIdentity,
    outerReload,
  };
}

function formatError(error) {
  return error instanceof Error ? error.message : String(error);
}

function redactedError(error, runNamespace) {
  return error === null ? null : redactRunNamespace(error, runNamespace);
}

function outputContainsExact(output, marker) {
  return output.stdout.some((line) => line === marker) ||
      output.stderr.some((line) => line === marker);
}

function outputContains(output, marker) {
  return output.stdout.some((line) => line.includes(marker)) ||
      output.stderr.some((line) => line.includes(marker));
}

function markerForRole(role) {
  if (role === HOLDER_ROLE) {
    return HOLDER_READY_MARKER;
  }
  if (role === CONTENDER_ROLE) {
    return CONTENDER_EACCES_MARKER;
  }
  if (role === REOPEN_ROLE) {
    return REOPEN_OK_MARKER;
  }
  throw new Error("M7 OPFS exclusivity role is invalid");
}

function runtimeStartMarker(role) {
  return "CHROMIUM_WASM_M7_OPFS_EXCLUSIVITY:RUNTIME_START role=" + role +
      " run_id=redacted";
}

function bindModuleIdentity(module, moduleIdentity) {
  const property = "__chromiumWasmM7OpfsExclusivityModuleIdentity";
  if (Object.prototype.hasOwnProperty.call(module, property)) {
    throw new Error("M7 OPFS exclusivity Module identity property already exists");
  }
  Object.defineProperty(module, property, {
    configurable: false,
    enumerable: false,
    value: moduleIdentity,
    writable: false,
  });
  if (module[property] !== moduleIdentity) {
    throw new Error("M7 OPFS exclusivity Module identity was not retained");
  }
}

function retainLiveRuntime(runtime) {
  if (!Object.prototype.hasOwnProperty.call(globalThis, ACTIVE_RUNTIMES_PROPERTY)) {
    Object.defineProperty(globalThis, ACTIVE_RUNTIMES_PROPERTY, {
      configurable: false,
      enumerable: false,
      value: [],
      writable: false,
    });
  }
  const activeRuntimes = globalThis[ACTIVE_RUNTIMES_PROPERTY];
  if (!Array.isArray(activeRuntimes)) {
    throw new Error("M7 OPFS exclusivity live runtime registry is invalid");
  }
  activeRuntimes.push(runtime);
}

function createPhaseDeadline(context) {
  return {expiresAt: performance.now() + context.timeoutMs};
}

async function awaitBeforeDeadline(value, deadline, stage, progress) {
  progress.stage = stage;
  const remainingMs = deadline.expiresAt - performance.now();
  if (remainingMs <= 0) {
    progress.timedOut = true;
    throw new Error("M7 OPFS " + stage + " exceeded its shared phase deadline");
  }
  let timeoutId = null;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      progress.timedOut = true;
      reject(new Error("M7 OPFS " + stage +
          " exceeded its shared phase deadline"));
    }, remainingMs);
  });
  return Promise.race([Promise.resolve(value), timeout]).finally(() => {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  });
}

function liveRuntimeFailure(runtime) {
  if (runtime.factoryError !== null) {
    return "M7 OPFS " + runtime.role + " module factory rejected: " +
        runtime.factoryError;
  }
  if (!runtime.factorySettled || !runtime.runtimeInitialized) {
    return "M7 OPFS " + runtime.role + " runtime never initialized";
  }
  if (runtime.runtimeExitCode !== null) {
    return "M7 OPFS " + runtime.role + " runtime exited instead of remaining live";
  }
  if (runtime.abort !== null) {
    return "M7 OPFS " + runtime.role + " runtime aborted";
  }
  if (runtime.completionError !== null || !runtime.completionObserved ||
      runtime.completionMarker !== markerForRole(runtime.role)) {
    return "M7 OPFS " + runtime.role + " runtime did not report its exact marker";
  }
  if (!outputContainsExact(runtime.output, markerForRole(runtime.role)) ||
      outputContains(runtime.output, FAIL_MARKER)) {
    return "M7 OPFS " + runtime.role + " native output is incomplete";
  }
  return null;
}

async function requireLiveCompletion(runtime, deadline, stage, progress) {
  await awaitBeforeDeadline(runtime.completion, deadline, stage, progress);
  await awaitBeforeDeadline(delay(COMPLETION_SETTLE_MS), deadline, stage, progress);
  const failure = liveRuntimeFailure(runtime);
  if (failure !== null) {
    throw new Error(failure);
  }
}

async function loadModuleFactory() {
  const moduleUrl = new URL("./artifacts/" + MODULE_NAME + ".js", location.href);
  if (moduleUrl.origin !== location.origin) {
    throw new Error("M7 OPFS exclusivity module is not same-origin");
  }
  const response = await fetch(moduleUrl.href, {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error("M7 OPFS exclusivity module request returned HTTP " +
        response.status);
  }
  const mainScriptUrlOrBlob = await response.blob();
  if (mainScriptUrlOrBlob.size === 0) {
    throw new Error("M7 OPFS exclusivity module loader is empty");
  }
  const namespace = await import(moduleUrl.href);
  if (typeof namespace.default !== "function") {
    throw new Error("M7 OPFS exclusivity module loader has no default factory");
  }
  return {moduleUrl, namespace, mainScriptUrlOrBlob};
}

function startRuntime(context, role, loader, onRuntimeCreated) {
  const output = {stdout: [], stderr: []};
  const runtime = {
    role,
    module: null,
    moduleIdentity: null,
    output,
    runtimeExitCode: null,
    factorySettled: false,
    factoryError: null,
    runtimeInitialized: false,
    abort: null,
    completionObserved: false,
    completionMarker: null,
    completionError: null,
    completion: null,
    factoryPromise: null,
  };
  let reportCompletion = null;
  runtime.completion = new Promise((resolve) => {
    reportCompletion = (marker, error) => {
      if (runtime.completionObserved || runtime.completionError !== null) {
        return;
      }
      if (error !== null) {
        runtime.completionError = error;
      } else {
        runtime.completionObserved = true;
        runtime.completionMarker = marker;
      }
      resolve();
    };
  });
  const expectedMarker = markerForRole(role);
  const captureNativeOutput = (destination, line) => {
    const capturedLine = appendBounded(destination, line, context.runNamespace);
    if (capturedLine.startsWith(FAIL_MARKER)) {
      reportCompletion(null, "native WasmFS exclusivity smoke emitted FAIL");
    } else if (capturedLine === expectedMarker) {
      reportCompletion(capturedLine, null);
    }
  };

  // Register before factory activation so a pending factory or native main
  // still appears in the bounded failure report.
  onRuntimeCreated(runtime);
  try {
    const factory = loader.namespace.default({
      arguments: [ROLE_SWITCH + role, RUN_SWITCH + context.runNamespace],
      noExitRuntime: false,
      mainScriptUrlOrBlob: loader.mainScriptUrlOrBlob,
      locateFile: (path) => new URL(path, loader.moduleUrl).href,
      print(line) { captureNativeOutput(output.stdout, line); },
      printErr(line) { captureNativeOutput(output.stderr, line); },
      onRuntimeInitialized() { runtime.runtimeInitialized = true; },
      onAbort(reason) {
        runtime.abort = redactRunNamespace(reason, context.runNamespace);
        reportCompletion(null, "M7 OPFS " + role + " runtime aborted before marker");
      },
      onExit(code) {
        if (runtime.runtimeExitCode === null) {
          runtime.runtimeExitCode = Number(code);
        }
        if (!runtime.completionObserved) {
          reportCompletion(null, "M7 OPFS " + role + " runtime exited before marker");
        }
      },
    });
    runtime.factoryPromise = Promise.resolve(factory).then((module) => {
      if (!module ||
          (typeof module !== "object" && typeof module !== "function")) {
        throw new Error("M7 OPFS " + role + " module factory returned no Module");
      }
      runtime.module = module;
      runtime.moduleIdentity = createModuleIdentity();
      bindModuleIdentity(runtime.module, runtime.moduleIdentity);
      runtime.factorySettled = true;
      return runtime;
    }).catch((error) => {
      runtime.factorySettled = true;
      runtime.factoryError = redactedError(formatError(error), context.runNamespace);
      throw new Error("M7 OPFS " + role + " module factory rejected: " +
          runtime.factoryError);
    });
  } catch (error) {
    runtime.factorySettled = true;
    runtime.factoryError = redactedError(formatError(error), context.runNamespace);
    runtime.factoryPromise = Promise.resolve().then(() => {
      throw new Error("M7 OPFS " + role + " module factory threw: " +
          runtime.factoryError);
    });
  }
  return runtime;
}

function snapshotRuntime(runtime, context) {
  return {
    role: runtime.role,
    moduleIdentity: runtime.moduleIdentity,
    factorySettled: runtime.factorySettled,
    runtimeInitialized: runtime.runtimeInitialized,
    runtimeExitCode: runtime.runtimeExitCode,
    abort: runtime.abort,
    completionObserved: runtime.completionObserved,
    completionMarker: runtime.completionMarker,
    factoryError: redactedError(runtime.factoryError, context.runNamespace),
    completionError: redactedError(runtime.completionError, context.runNamespace),
    nativeStartObserved: outputContainsExact(runtime.output,
                                              runtimeStartMarker(runtime.role)),
    contenderOpenBeginObserved: runtime.role === CONTENDER_ROLE &&
        outputContainsExact(runtime.output, CONTENDER_OPEN_BEGIN_MARKER),
    runtimeLifecycle: liveRuntimeFailure(runtime) === null ?
        "live-runtime" : "not-live-runtime",
    stdout: runtime.output.stdout.slice(),
    stderr: runtime.output.stderr.slice(),
  };
}

function failureDiagnostics(progress, context) {
  const holder = progress.holder === null ? null :
      snapshotRuntime(progress.holder, context);
  const contender = progress.contender === null ? null :
      snapshotRuntime(progress.contender, context);
  return {
    stage: progress.stage,
    timedOut: progress.timedOut,
    holder,
    contender,
    reopen: progress.reopen === null ? null :
        snapshotRuntime(progress.reopen, context),
    nativeStartObserved: contender !== null && contender.nativeStartObserved,
    contenderOpenBeginObserved: contender !== null &&
        contender.contenderOpenBeginObserved,
  };
}

function baseResult(context) {
  const timeOrigin = performance.timeOrigin;
  const freshOuterDocument = context.phase === REOPEN_PHASE &&
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
    exclusivityScope: EXCLUSIVITY_SCOPE,
    syncAccessHandleWriterExclusivityProven: false,
    independentModuleInstancesProven: false,
    holderLiveAfterContender: false,
    releaseAfterOuterDocumentTeardownProven: false,
    sqliteLeveldbLockSemanticsProven: false,
    atomicRecoveryProven: false,
    gracefulRuntimeShutdownProven: false,
    teardownMode: "outer-document",
    timeOrigin,
    outerReload: context.outerReload,
    priorTimeOrigin: context.priorTimeOrigin,
    priorHolderModuleIdentity: context.priorHolderModuleIdentity,
    priorContenderModuleIdentity: context.priorContenderModuleIdentity,
    freshOuterDocument,
    holder: null,
    contender: null,
    reopen: null,
    failureDiagnostics: null,
    error: null,
  };
}

async function runContentionPhase(context, result, deadline, progress) {
  const loader = await awaitBeforeDeadline(loadModuleFactory(), deadline,
                                            "contention-loader", progress);
  const holder = startRuntime(context, HOLDER_ROLE, loader, (runtime) => {
    progress.holder = runtime;
    retainLiveRuntime(runtime);
  });
  await awaitBeforeDeadline(holder.factoryPromise, deadline, "holder-factory",
                            progress);
  await requireLiveCompletion(holder, deadline, "holder-marker", progress);
  result.holder = snapshotRuntime(holder, context);

  // The contender factory is intentionally not started until the native
  // holder has fdatasync'd and reported that its RW descriptor remains open.
  const contender = startRuntime(context, CONTENDER_ROLE, loader, (runtime) => {
    progress.contender = runtime;
    retainLiveRuntime(runtime);
  });
  await awaitBeforeDeadline(contender.factoryPromise, deadline,
                            "contender-factory", progress);
  await requireLiveCompletion(contender, deadline, "contender-marker", progress);
  result.contender = snapshotRuntime(contender, context);
  await awaitBeforeDeadline(delay(COMPLETION_SETTLE_MS), deadline,
                            "holder-liveness", progress);
  const holderFailure = liveRuntimeFailure(holder);
  if (holderFailure !== null) {
    throw new Error(holderFailure);
  }
  if (holder.module === contender.module ||
      holder.moduleIdentity === contender.moduleIdentity) {
    throw new Error("M7 OPFS holder and contender did not create independent Modules");
  }
  result.independentModuleInstancesProven = true;
  result.holderLiveAfterContender = true;
  result.syncAccessHandleWriterExclusivityProven = true;
}

async function runReopenPhase(context, result, deadline, progress) {
  const loader = await awaitBeforeDeadline(loadModuleFactory(), deadline,
                                            "reopen-loader", progress);
  const reopen = startRuntime(context, REOPEN_ROLE, loader, (runtime) => {
    progress.reopen = runtime;
    retainLiveRuntime(runtime);
  });
  await awaitBeforeDeadline(reopen.factoryPromise, deadline, "reopen-factory",
                            progress);
  await requireLiveCompletion(reopen, deadline, "reopen-marker", progress);
  if (reopen.moduleIdentity === context.priorHolderModuleIdentity ||
      reopen.moduleIdentity === context.priorContenderModuleIdentity) {
    throw new Error("M7 OPFS reopen reused a prior Module identity");
  }
  result.reopen = snapshotRuntime(reopen, context);
  result.releaseAfterOuterDocumentTeardownProven = true;
}

async function executePhase(context) {
  const result = baseResult(context);
  const deadline = createPhaseDeadline(context);
  const progress = {
    stage: "capability",
    timedOut: false,
    holder: null,
    contender: null,
    reopen: null,
  };
  try {
    result.opfsCapability = await awaitBeforeDeadline(
        probeRequiredOpfsCapability(), deadline, "capability", progress);
    if (!result.opfsCapability) {
      result.error = "required OPFS synchronous-access capability is unavailable";
      return result;
    }
    if (context.phase === REOPEN_PHASE && !result.freshOuterDocument) {
      result.error = "reopen phase did not start in a fresh outer document";
      return result;
    }
    if (context.phase === CONTENTION_PHASE) {
      await runContentionPhase(context, result, deadline, progress);
    } else {
      await runReopenPhase(context, result, deadline, progress);
    }
    result.status = "pass";
  } catch (error) {
    result.error = redactedError(formatError(error), context.runNamespace);
    result.failureDiagnostics = failureDiagnostics(progress, context);
  }
  return result;
}

function updateVisibleState(result) {
  const root = document.querySelector("#m7-opfs-exclusivity-root");
  const status = document.querySelector("#m7-opfs-exclusivity-status");
  if (root instanceof HTMLElement) {
    root.dataset.state = result.status;
  }
  if (status instanceof HTMLElement) {
    status.textContent = JSON.stringify({
      ...result,
      runNamespace: "<redacted>",
    }, null, 2);
  }
  globalThis.__chromiumWasmM7WasmfsOpfsExclusivityState = Object.freeze({
    protocol: HOST_PROTOCOL,
    case: CASE,
    phase: result.phase,
    status: result.status,
    timeOrigin: result.timeOrigin,
    freshOuterDocument: result.freshOuterDocument,
  });
}

async function postResult(context, result) {
  const endpoint = new URL(
      "./result/" + encodeURIComponent(context.token) + "/" + context.phase,
      location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("M7 OPFS exclusivity result endpoint is not same-origin");
  }
  const response = await fetch(endpoint.href, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (response.status !== 204) {
    throw new Error("M7 OPFS exclusivity result upload returned HTTP " +
        response.status);
  }
}

function validRuntimeSnapshot(snapshot, role, marker) {
  return snapshot !== null && typeof snapshot === "object" &&
      snapshot.role === role && typeof snapshot.moduleIdentity === "string" &&
      MODULE_ID_RE.test(snapshot.moduleIdentity) && snapshot.factorySettled === true &&
      snapshot.runtimeInitialized === true && snapshot.runtimeExitCode === null &&
      snapshot.abort === null && snapshot.completionObserved === true &&
      snapshot.completionMarker === marker && snapshot.runtimeLifecycle === "live-runtime" &&
      Array.isArray(snapshot.stdout) && Array.isArray(snapshot.stderr) &&
      outputContainsExact(snapshot, marker) && !outputContains(snapshot, FAIL_MARKER);
}

function verifyResultShape(result) {
  if (result.status !== "pass" || result.opfsFallbackUsed !== false ||
      result.crossOriginIsolated !== true || result.sharedArrayBuffer !== true ||
      result.opfsCapability !== true || result.origin !== location.origin ||
      result.exclusivityScope !== EXCLUSIVITY_SCOPE ||
      result.sqliteLeveldbLockSemanticsProven !== false ||
      result.atomicRecoveryProven !== false ||
      result.gracefulRuntimeShutdownProven !== false ||
      result.teardownMode !== "outer-document" || result.failureDiagnostics !== null ||
      result.error !== null) {
    throw new Error("M7 OPFS exclusivity result is incomplete");
  }
  if (result.phase === CONTENTION_PHASE) {
    if (!result.syncAccessHandleWriterExclusivityProven ||
        !result.independentModuleInstancesProven || !result.holderLiveAfterContender ||
        result.releaseAfterOuterDocumentTeardownProven ||
        !validRuntimeSnapshot(result.holder, HOLDER_ROLE, HOLDER_READY_MARKER) ||
        !validRuntimeSnapshot(result.contender, CONTENDER_ROLE,
                              CONTENDER_EACCES_MARKER) ||
        result.holder.moduleIdentity === result.contender.moduleIdentity ||
        result.outerReload || result.freshOuterDocument || result.reopen !== null) {
      throw new Error("M7 OPFS contention result is incomplete");
    }
  } else if (result.phase === REOPEN_PHASE) {
    if (result.syncAccessHandleWriterExclusivityProven ||
        result.independentModuleInstancesProven || result.holderLiveAfterContender ||
        !result.releaseAfterOuterDocumentTeardownProven ||
        !result.outerReload || !result.freshOuterDocument ||
        !validRuntimeSnapshot(result.reopen, REOPEN_ROLE, REOPEN_OK_MARKER) ||
        result.holder !== null || result.contender !== null ||
        result.reopen.moduleIdentity === result.priorHolderModuleIdentity ||
        result.reopen.moduleIdentity === result.priorContenderModuleIdentity) {
      throw new Error("M7 OPFS reopen result is incomplete");
    }
  } else {
    throw new Error("M7 OPFS exclusivity result has an invalid phase");
  }
}

export async function runM7WasmfsOpfsExclusivitySmokeFromQuery() {
  const context = staticContext(new URLSearchParams(location.search));
  const result = await executePhase(context);
  updateVisibleState(result);
  await postResult(context, result);
  verifyResultShape(result);

  if (context.phase === CONTENTION_PHASE) {
    // Holder and contender deliberately remain live here. Do not invoke normal
    // Emscripten teardown: location.replace() is the only lifecycle boundary
    // exercised by this target, and the reopen phase verifies release after it.
    const reopenUrl = new URL(location.href);
    reopenUrl.searchParams.set("phase", REOPEN_PHASE);
    reopenUrl.searchParams.set("outerReload", "1");
    reopenUrl.searchParams.set("priorTimeOrigin", String(result.timeOrigin));
    reopenUrl.searchParams.set(
        "priorHolderModuleIdentity", result.holder.moduleIdentity);
    reopenUrl.searchParams.set(
        "priorContenderModuleIdentity", result.contender.moduleIdentity);
    location.replace(reopenUrl.href);
  }
  return result;
}

export const m7WasmfsOpfsExclusivitySmokeContract = Object.freeze({
  protocol: HOST_PROTOCOL,
  case: CASE,
  scope: SCOPE,
  phases: Object.freeze([CONTENTION_PHASE, REOPEN_PHASE]),
  roles: Object.freeze([HOLDER_ROLE, CONTENDER_ROLE, REOPEN_ROLE]),
  nativeMarkers: Object.freeze([
    HOLDER_READY_MARKER,
    CONTENDER_OPEN_BEGIN_MARKER,
    CONTENDER_EACCES_MARKER,
    REOPEN_OK_MARKER,
    FAIL_MARKER,
  ]),
});

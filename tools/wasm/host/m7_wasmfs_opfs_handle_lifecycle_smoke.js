// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Same-document, two-Wasm-module bounded OPFS access-handle lifecycle probe.
// The host never acquires an OPFS root, file, or access handle. All filesystem
// operations are confined to the C++ WasmFS target; this page only coordinates
// independent Emscripten Module factories and reports trusted native markers.

const HOST_PROTOCOL = 1;
const CASE = "m7_wasmfs_opfs_bounded_handle_lifecycle";
const SCOPE = "isolated-wasmfs-opfs-bounded-32-path-handle-lifecycle";
const LIFECYCLE_SCOPE =
    "bounded-direct-close-and-fresh-document-fixture-reap-only";
const MODULE_NAME = "m7_wasmfs_opfs_handle_lifecycle_smoke";
const EXERCISE_PHASE = "exercise";
const VERIFY_PHASE = "verify";
const HOLDER_ROLE = "holder";
const REOPEN_ROLE = "reopen";
const VERIFY_ROLE = "verify";
const ROLE_SWITCH = "--m7-opfs-role=";
const RUN_SWITCH = "--m7-opfs-run=";
const PATH_COUNT = 32;
const HOLDER_CLOSED_MARKER =
    "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:" +
    "HOLDER_CLOSED_32 files=32 write=ok fdatasync=ok close=ok";
const REOPEN_CLOSED_MARKER =
    "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:" +
    "REOPEN_CLOSED_32 files=32 read=ok fdatasync=ok close=ok";
const VERIFY_REAP_MARKER =
    "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:" +
    "VERIFY_REAP_32 files=32 read=ok close=ok cleanup=ok";
const FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:FAIL";
const MAX_TIMEOUT_MS = 180000;
const MAX_OUTPUT_LINES = 128;
const CAPABILITY_PROBE_PROTOCOL = 1;
const COMPLETION_SETTLE_MS = 25;
const RUN_NAMESPACE_RE = /^[A-Za-z0-9_-]{16,128}$/;
const MODULE_ID_RE = /^[a-f0-9]{32}$/;
const ACTIVE_RUNTIMES_PROPERTY =
    "__chromiumWasmM7WasmfsOpfsHandleLifecycleActiveRuntimes";

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
      throw new Error("unexpected M7 OPFS lifecycle query parameter: " + name);
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

function staticContext(query) {
  const token = oneQueryValue(query, "token");
  const phase = oneQueryValue(query, "phase");
  const runNamespace = oneQueryValue(query, "run");
  const timeoutMs = parseTimeout(oneQueryValue(query, "timeoutMs"));
  if (!RUN_NAMESPACE_RE.test(token) || !RUN_NAMESPACE_RE.test(runNamespace) ||
      (phase !== EXERCISE_PHASE && phase !== VERIFY_PHASE)) {
    throw new Error("M7 OPFS lifecycle query is invalid");
  }

  let priorTimeOrigin = null;
  let priorHolderModuleIdentity = null;
  let priorReopenModuleIdentity = null;
  let outerReload = false;
  if (phase === VERIFY_PHASE) {
    requireOnlyQueryParameters(query, new Set([
      "token", "phase", "run", "timeoutMs", "priorTimeOrigin",
      "priorHolderModuleIdentity", "priorReopenModuleIdentity", "outerReload",
    ]));
    priorTimeOrigin = parseTimeOrigin(oneQueryValue(query, "priorTimeOrigin"));
    priorHolderModuleIdentity = oneQueryValue(query, "priorHolderModuleIdentity");
    priorReopenModuleIdentity = oneQueryValue(query, "priorReopenModuleIdentity");
    outerReload = oneQueryValue(query, "outerReload") === "1";
    if (!MODULE_ID_RE.test(priorHolderModuleIdentity) ||
        !MODULE_ID_RE.test(priorReopenModuleIdentity) || !outerReload) {
      throw new Error("M7 OPFS lifecycle verifier query lacks outer-reload witnesses");
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
    priorReopenModuleIdentity,
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
    return HOLDER_CLOSED_MARKER;
  }
  if (role === REOPEN_ROLE) {
    return REOPEN_CLOSED_MARKER;
  }
  if (role === VERIFY_ROLE) {
    return VERIFY_REAP_MARKER;
  }
  throw new Error("M7 OPFS lifecycle role is invalid");
}

function runtimeStartMarker(role) {
  return "CHROMIUM_WASM_M7_OPFS_HANDLE_LIFECYCLE:RUNTIME_START role=" + role +
      " run_id=redacted";
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

function createPhaseDeadline(context) {
  return {expiresAt: performance.now() + context.timeoutMs};
}

function deadlineError(stage, progress) {
  progress.stage = stage;
  progress.timedOut = true;
  return new Error("M7 OPFS " + stage + " exceeded its shared phase deadline");
}

function remainingDeadlineMs(deadline, stage, progress) {
  progress.stage = stage;
  const remainingMs = deadline.expiresAt - performance.now();
  if (remainingMs <= 0) {
    throw deadlineError(stage, progress);
  }
  return Math.ceil(remainingMs);
}

async function awaitBeforeDeadline(value, deadline, stage, progress) {
  const remainingMs = remainingDeadlineMs(deadline, stage, progress);
  let timeoutId = null;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(
        () => reject(deadlineError(stage, progress)), remainingMs);
  });
  return Promise.race([Promise.resolve(value), timeout]).finally(() => {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  });
}

async function probeRequiredOpfsCapability(deadline, progress) {
  const stage = "capability";
  const remainingMs = remainingDeadlineMs(deadline, stage, progress);
  if (!hasRequiredDocumentPrerequisites() || typeof Worker !== "function" ||
      typeof Blob !== "function" || typeof URL.createObjectURL !== "function") {
    return false;
  }
  const workerUrl = URL.createObjectURL(new Blob([CAPABILITY_PROBE_SOURCE], {
    type: "text/javascript",
  }));
  return new Promise((resolve, reject) => {
    let finished = false;
    let probeWorker = null;
    let timeoutId = null;
    const finish = (capability, error = null) => {
      if (finished) {
        return;
      }
      finished = true;
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
      }
      probeWorker?.terminate();
      URL.revokeObjectURL(workerUrl);
      if (error !== null) {
        reject(error);
      } else {
        resolve(capability === true);
      }
    };
    try {
      probeWorker = new Worker(workerUrl, {
        name: "chromium-wasm-m7-opfs-handle-lifecycle-capability",
        type: "module",
      });
    } catch {
      URL.revokeObjectURL(workerUrl);
      resolve(false);
      return;
    }
    timeoutId = setTimeout(
        () => finish(false, deadlineError(stage, progress)), remainingMs);
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

function bindModuleIdentity(module, moduleIdentity) {
  const property = "__chromiumWasmM7WasmfsOpfsHandleLifecycleModuleIdentity";
  if (Object.prototype.hasOwnProperty.call(module, property)) {
    throw new Error("M7 OPFS lifecycle Module identity property already exists");
  }
  Object.defineProperty(module, property, {
    configurable: false,
    enumerable: false,
    value: moduleIdentity,
    writable: false,
  });
  if (module[property] !== moduleIdentity) {
    throw new Error("M7 OPFS lifecycle Module identity was not retained");
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
    throw new Error("M7 OPFS lifecycle live runtime registry is invalid");
  }
  activeRuntimes.push(runtime);
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
    throw new Error("M7 OPFS lifecycle module is not same-origin");
  }
  const response = await fetch(moduleUrl.href, {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error("M7 OPFS lifecycle module request returned HTTP " +
        response.status);
  }
  const mainScriptUrlOrBlob = await response.blob();
  if (mainScriptUrlOrBlob.size === 0) {
    throw new Error("M7 OPFS lifecycle module loader is empty");
  }
  const namespace = await import(moduleUrl.href);
  if (typeof namespace.default !== "function") {
    throw new Error("M7 OPFS lifecycle module loader has no default factory");
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
      reportCompletion(null, "native WasmFS lifecycle smoke emitted FAIL");
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
    runtimeLifecycle: liveRuntimeFailure(runtime) === null ?
        "live-runtime" : "not-live-runtime",
    stdout: runtime.output.stdout.slice(),
    stderr: runtime.output.stderr.slice(),
  };
}

function failureDiagnostics(progress, context) {
  const holder = progress.holder === null ? null :
      snapshotRuntime(progress.holder, context);
  const reopen = progress.reopen === null ? null :
      snapshotRuntime(progress.reopen, context);
  const verify = progress.verify === null ? null :
      snapshotRuntime(progress.verify, context);
  return {
    stage: progress.stage,
    timedOut: progress.timedOut,
    holder,
    reopen,
    verify,
    holderRegistered: holder !== null,
    reopenRegistered: reopen !== null,
    verifyRegistered: verify !== null,
    holderNativeStartObserved: holder !== null && holder.nativeStartObserved,
    holderClosedObserved: holder !== null &&
        outputContainsExact(holder, HOLDER_CLOSED_MARKER),
    reopenNativeStartObserved: reopen !== null && reopen.nativeStartObserved,
    reopenClosedObserved: reopen !== null &&
        outputContainsExact(reopen, REOPEN_CLOSED_MARKER),
    verifyNativeStartObserved: verify !== null && verify.nativeStartObserved,
    verifyReapObserved: verify !== null &&
        outputContainsExact(verify, VERIFY_REAP_MARKER),
  };
}

function copyPartialRuntimeSnapshots(result, progress, context) {
  for (const field of ["holder", "reopen", "verify"]) {
    if (progress[field] !== null) {
      result[field] = snapshotRuntime(progress[field], context);
    }
  }
}

function recordFailure(result, progress, context, error) {
  copyPartialRuntimeSnapshots(result, progress, context);
  result.failureDiagnostics = failureDiagnostics(progress, context);
  result.error = redactedError(formatError(error), context.runNamespace);
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
    lifecycleScope: LIFECYCLE_SCOPE,
    boundedDistinctPathCount: PATH_COUNT,
    holderClosedAllPathsProven: false,
    sameDocumentReopenClosedAllPathsProven: false,
    independentModuleInstancesProven: false,
    holderLiveAfterSameDocumentReopen: false,
    freshDocumentFixtureReapProven: false,
    browserHandleLimitObserved: false,
    handleExhaustionProven: false,
    allocatorReuseObservable: false,
    profilePersistenceProven: false,
    persistentProfileIntegrationProven: false,
    sqliteLeveldbLockSemanticsProven: false,
    atomicRecoveryProven: false,
    crashRecoveryProven: false,
    gracefulRuntimeShutdownProven: false,
    teardownMode: "outer-document",
    timeOrigin,
    outerReload: context.outerReload,
    priorTimeOrigin: context.priorTimeOrigin,
    priorHolderModuleIdentity: context.priorHolderModuleIdentity,
    priorReopenModuleIdentity: context.priorReopenModuleIdentity,
    freshOuterDocument,
    holder: null,
    reopen: null,
    verify: null,
    failureDiagnostics: null,
    error: null,
  };
}

async function runExercisePhase(context, result, deadline, progress) {
  const loader = await awaitBeforeDeadline(loadModuleFactory(), deadline,
                                            "exercise-loader", progress);
  const holder = startRuntime(context, HOLDER_ROLE, loader, (runtime) => {
    progress.holder = runtime;
    retainLiveRuntime(runtime);
  });
  await awaitBeforeDeadline(holder.factoryPromise, deadline, "holder-factory",
                            progress);
  await requireLiveCompletion(holder, deadline, "holder-marker", progress);
  result.holder = snapshotRuntime(holder, context);

  // Start a separate Module only after the holder has closed every native
  // descriptor. This distinguishes last-close release from outer-document
  // teardown without asking the host to perform any filesystem operation.
  const reopen = startRuntime(context, REOPEN_ROLE, loader, (runtime) => {
    progress.reopen = runtime;
    retainLiveRuntime(runtime);
  });
  await awaitBeforeDeadline(reopen.factoryPromise, deadline, "reopen-factory",
                            progress);
  await requireLiveCompletion(reopen, deadline, "reopen-marker", progress);
  result.reopen = snapshotRuntime(reopen, context);
  await awaitBeforeDeadline(delay(COMPLETION_SETTLE_MS), deadline,
                            "holder-liveness", progress);
  const holderFailure = liveRuntimeFailure(holder);
  if (holderFailure !== null) {
    throw new Error(holderFailure);
  }
  if (holder.module === reopen.module ||
      holder.moduleIdentity === reopen.moduleIdentity) {
    throw new Error("M7 OPFS holder and reopen did not create independent Modules");
  }
  result.holderClosedAllPathsProven = true;
  result.sameDocumentReopenClosedAllPathsProven = true;
  result.independentModuleInstancesProven = true;
  result.holderLiveAfterSameDocumentReopen = true;
}

async function runVerifyPhase(context, result, deadline, progress) {
  const loader = await awaitBeforeDeadline(loadModuleFactory(), deadline,
                                            "verify-loader", progress);
  const verify = startRuntime(context, VERIFY_ROLE, loader, (runtime) => {
    progress.verify = runtime;
    retainLiveRuntime(runtime);
  });
  await awaitBeforeDeadline(verify.factoryPromise, deadline, "verify-factory",
                            progress);
  await requireLiveCompletion(verify, deadline, "verify-marker", progress);
  if (verify.moduleIdentity === context.priorHolderModuleIdentity ||
      verify.moduleIdentity === context.priorReopenModuleIdentity) {
    throw new Error("M7 OPFS verifier reused a prior Module identity");
  }
  result.verify = snapshotRuntime(verify, context);
  result.freshDocumentFixtureReapProven = true;
}

async function executePhase(context) {
  const deadline = createPhaseDeadline(context);
  const result = baseResult(context);
  const progress = {
    stage: "capability",
    timedOut: false,
    holder: null,
    reopen: null,
    verify: null,
  };
  try {
    result.opfsCapability = await probeRequiredOpfsCapability(deadline, progress);
    if (!result.opfsCapability) {
      throw new Error("required OPFS synchronous-access capability is unavailable");
    }
    if (context.phase === VERIFY_PHASE && !result.freshOuterDocument) {
      throw new Error("verifier did not start in a fresh outer document");
    }
    if (context.phase === EXERCISE_PHASE) {
      await runExercisePhase(context, result, deadline, progress);
    } else {
      await runVerifyPhase(context, result, deadline, progress);
    }
    result.status = "pass";
  } catch (error) {
    recordFailure(result, progress, context, error);
  }
  return result;
}

function updateVisibleState(result) {
  const root = document.querySelector("#m7-opfs-handle-lifecycle-root");
  const status = document.querySelector("#m7-opfs-handle-lifecycle-status");
  if (root instanceof HTMLElement) {
    root.dataset.state = result.status;
  }
  if (status instanceof HTMLElement) {
    status.textContent = JSON.stringify({
      ...result,
      runNamespace: "<redacted>",
    }, null, 2);
  }
  globalThis.__chromiumWasmM7WasmfsOpfsHandleLifecycleState = Object.freeze({
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
    throw new Error("M7 OPFS lifecycle result endpoint is not same-origin");
  }
  const response = await fetch(endpoint.href, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (response.status !== 204) {
    throw new Error("M7 OPFS lifecycle result upload returned HTTP " +
        response.status);
  }
}

function validRuntimeSnapshot(snapshot, role, marker) {
  return snapshot !== null && typeof snapshot === "object" &&
      snapshot.role === role && typeof snapshot.moduleIdentity === "string" &&
      MODULE_ID_RE.test(snapshot.moduleIdentity) && snapshot.factorySettled === true &&
      snapshot.runtimeInitialized === true && snapshot.runtimeExitCode === null &&
      snapshot.abort === null && snapshot.completionObserved === true &&
      snapshot.completionMarker === marker && snapshot.factoryError === null &&
      snapshot.completionError === null && snapshot.nativeStartObserved === true &&
      snapshot.runtimeLifecycle === "live-runtime" &&
      Array.isArray(snapshot.stdout) && Array.isArray(snapshot.stderr) &&
      outputContainsExact(snapshot, marker) && !outputContains(snapshot, FAIL_MARKER);
}

function verifyResultShape(result) {
  if (result.status !== "pass" || result.opfsFallbackUsed !== false ||
      result.crossOriginIsolated !== true || result.sharedArrayBuffer !== true ||
      result.opfsCapability !== true || result.origin !== location.origin ||
      result.lifecycleScope !== LIFECYCLE_SCOPE ||
      result.boundedDistinctPathCount !== PATH_COUNT ||
      result.browserHandleLimitObserved !== false ||
      result.handleExhaustionProven !== false ||
      result.allocatorReuseObservable !== false ||
      result.profilePersistenceProven !== false ||
      result.persistentProfileIntegrationProven !== false ||
      result.sqliteLeveldbLockSemanticsProven !== false ||
      result.atomicRecoveryProven !== false ||
      result.crashRecoveryProven !== false ||
      result.gracefulRuntimeShutdownProven !== false ||
      result.teardownMode !== "outer-document" || result.failureDiagnostics !== null ||
      result.error !== null) {
    throw new Error("M7 OPFS lifecycle result is incomplete");
  }
  if (result.phase === EXERCISE_PHASE) {
    if (!result.holderClosedAllPathsProven ||
        !result.sameDocumentReopenClosedAllPathsProven ||
        !result.independentModuleInstancesProven ||
        !result.holderLiveAfterSameDocumentReopen ||
        result.freshDocumentFixtureReapProven ||
        !validRuntimeSnapshot(result.holder, HOLDER_ROLE, HOLDER_CLOSED_MARKER) ||
        !validRuntimeSnapshot(result.reopen, REOPEN_ROLE, REOPEN_CLOSED_MARKER) ||
        result.holder.moduleIdentity === result.reopen.moduleIdentity ||
        result.outerReload || result.freshOuterDocument || result.verify !== null) {
      throw new Error("M7 OPFS lifecycle exercise result is incomplete");
    }
  } else if (result.phase === VERIFY_PHASE) {
    if (result.holderClosedAllPathsProven ||
        result.sameDocumentReopenClosedAllPathsProven ||
        result.independentModuleInstancesProven ||
        result.holderLiveAfterSameDocumentReopen ||
        !result.freshDocumentFixtureReapProven || !result.outerReload ||
        !result.freshOuterDocument ||
        !validRuntimeSnapshot(result.verify, VERIFY_ROLE, VERIFY_REAP_MARKER) ||
        result.holder !== null || result.reopen !== null ||
        result.verify.moduleIdentity === result.priorHolderModuleIdentity ||
        result.verify.moduleIdentity === result.priorReopenModuleIdentity) {
      throw new Error("M7 OPFS lifecycle verifier result is incomplete");
    }
  } else {
    throw new Error("M7 OPFS lifecycle result has an invalid phase");
  }
}

export async function runM7WasmfsOpfsHandleLifecycleSmokeFromQuery() {
  const context = staticContext(new URLSearchParams(location.search));
  const result = await executePhase(context);
  updateVisibleState(result);
  await postResult(context, result);
  verifyResultShape(result);

  if (context.phase === EXERCISE_PHASE) {
    // Holder and reopen deliberately remain live here. Do not invoke normal
    // Emscripten teardown: location.replace() is the only lifecycle boundary
    // exercised by this target, and the verifier phase reopens and reaps the
    // bounded fixture after that fresh document starts.
    const verifyUrl = new URL(location.href);
    verifyUrl.searchParams.set("phase", VERIFY_PHASE);
    verifyUrl.searchParams.set("outerReload", "1");
    verifyUrl.searchParams.set("priorTimeOrigin", String(result.timeOrigin));
    verifyUrl.searchParams.set(
        "priorHolderModuleIdentity", result.holder.moduleIdentity);
    verifyUrl.searchParams.set(
        "priorReopenModuleIdentity", result.reopen.moduleIdentity);
    location.replace(verifyUrl.href);
  }
}

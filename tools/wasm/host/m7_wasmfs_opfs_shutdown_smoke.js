// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A normal-return WasmFS/OPFS shutdown smoke. The page owns only Worker
// lifecycle and result transport; it never opens OPFS. The generated Wasm
// module instead runs inside one dedicated module Worker so Emscripten's
// normal global teardown cannot block the page's browser-main thread.

const HOST_PROTOCOL = 1;
const CASE = "m7_wasmfs_opfs_normal_shutdown";
const SCOPE = "isolated-wasmfs-opfs-dedicated-worker-normal-shutdown";
const SHUTDOWN_SCOPE =
    "wasmfs-opfs-backend-cleanup-and-normal-runtime-exit-only";
const MODULE_NAME = "m7_wasmfs_opfs_shutdown_smoke";
const WORKER_NAME = "chromium-wasm-m7-opfs-normal-shutdown";
const COMPLETION_MARKER =
    "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:NATIVE_COMPLETE " +
    "rw=ok fdatasync=ok close=ok cleanup=ok";
const ATEXIT_MARKER = "CHROMIUM_WASM_M7_OPFS_ATEXIT:after-native-complete";
const RUNTIME_START_MARKER =
    "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:RUNTIME_START run_id=redacted";
const FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:FAIL";
const MAX_TIMEOUT_MS = 180000;
const MAX_OUTPUT_LINES = 128;
const MAX_ERROR_CHARS = 2048;
// This follows the bounded host-heartbeat policy used by the existing Wasm
// browser smokes. It is deliberately much smaller than the overall test
// deadline: a page-main stall while the Worker tears down must not be hidden
// by eventual timer progress.
const MAX_PAGE_HEARTBEAT_GAP_MS = 250;
const POST_EXIT_PAGE_BARRIER_TURNS = 1;
// The Worker itself owns the terminal window. It waits before it publishes its
// terminal snapshot, then uses one final microtask in that same Worker turn
// before it emits a close confirmation and requests self-close.
const PRE_TERMINAL_WORKER_SETTLEMENT_TURNS = 2;
const NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS = 2;
const NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS = 1;
const TEST_FAULT_DELAYED_POST_TERMINAL_ERROR =
    "delayed-post-terminal-error";
const TEST_FAULT_NO_EXIT_RUNTIME = "no-exit-runtime";
const NO_EXIT_RUNTIME_LIFECYCLE = "no-exit-runtime-negative-control";
const RUN_NAMESPACE_RE = /^[A-Za-z0-9_-]{16,128}$/;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function formatError(error) {
  return error instanceof Error ? error.message : String(error);
}

function redactRunNamespace(value, runNamespace) {
  return String(value).split(runNamespace).join("<run-namespace>");
}

function boundedError(value, runNamespace) {
  return redactRunNamespace(value, runNamespace).slice(0, MAX_ERROR_CHARS);
}

function oneQueryValue(query, name) {
  const values = query.getAll(name);
  if (values.length !== 1 || values[0] === "") {
    throw new Error("query parameter " + name + " must occur exactly once");
  }
  return values[0];
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

function staticContext(query) {
  for (const name of query.keys()) {
    if (name !== "token" && name !== "run" && name !== "timeoutMs" &&
        name !== "testFault") {
      throw new Error("unexpected M7 OPFS shutdown query parameter: " + name);
    }
  }
  const token = oneQueryValue(query, "token");
  const runNamespace = oneQueryValue(query, "run");
  if (!RUN_NAMESPACE_RE.test(token) || !RUN_NAMESPACE_RE.test(runNamespace)) {
    throw new Error("M7 OPFS shutdown query is invalid");
  }
  return {
    token,
    runNamespace,
    timeoutMs: parseTimeout(oneQueryValue(query, "timeoutMs")),
    testFault: parseTestFault(query),
  };
}

function parseTestFault(query) {
  const values = query.getAll("testFault");
  if (values.length === 0) {
    return null;
  }
  if (values.length !== 1 ||
      (values[0] !== TEST_FAULT_DELAYED_POST_TERMINAL_ERROR &&
       values[0] !== TEST_FAULT_NO_EXIT_RUNTIME)) {
    throw new Error("M7 OPFS shutdown test fault is invalid");
  }
  return values[0];
}

function hasDocumentPrerequisites() {
  return globalThis.isSecureContext === true &&
      globalThis.crossOriginIsolated === true &&
      typeof SharedArrayBuffer === "function" && typeof Worker === "function" &&
      typeof requestAnimationFrame === "function";
}

function createDeadline(context) {
  return performance.now() + context.timeoutMs;
}

function remainingDeadlineMs(deadline, stage, progress) {
  const remaining = Math.floor(deadline - performance.now());
  if (remaining <= 0) {
    progress.timedOut = true;
    throw new Error("M7 OPFS shutdown deadline expired at " + stage);
  }
  return remaining;
}

async function awaitBeforeDeadline(value, deadline, stage, progress) {
  const remaining = remainingDeadlineMs(deadline, stage, progress);
  let timeoutId = null;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      progress.timedOut = true;
      reject(new Error("M7 OPFS shutdown deadline expired at " + stage));
    }, remaining);
  });
  return Promise.race([Promise.resolve(value), timeout]).finally(() => {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  });
}

function beginResponsivenessProbe() {
  const startedAt = performance.now();
  const state = {
    ticks: 0,
    frames: 0,
    frameId: null,
    stopped: false,
    lastTimerAt: startedAt,
    lastFrameAt: startedAt,
    maxTimerGapMs: 0,
    maxFrameGapMs: 0,
    terminalHeartbeat: null,
  };
  const recordGap = (field, previousField, now) => {
    const gap = Math.max(0, Math.ceil(now - state[previousField]));
    state[field] = Math.max(state[field], gap);
    state[previousField] = now;
  };
  const intervalId = setInterval(() => {
    recordGap("maxTimerGapMs", "lastTimerAt", performance.now());
    state.ticks += 1;
  }, 10);
  const onFrame = () => {
    if (state.stopped) {
      return;
    }
    recordGap("maxFrameGapMs", "lastFrameAt", performance.now());
    state.frames += 1;
    state.frameId = requestAnimationFrame(onFrame);
  };
  state.frameId = requestAnimationFrame(onFrame);
  return {
    baseline() { return {ticks: state.ticks, frames: state.frames}; },
    deltas(baseline) {
      return {
        ticks: state.ticks - baseline.ticks,
        frames: state.frames - baseline.frames,
      };
    },
    observeTerminal() {
      if (state.terminalHeartbeat !== null) {
        throw new Error("M7 OPFS shutdown Worker terminal heartbeat was duplicated");
      }
      // Browser main-thread work can delay both callback kinds. Sampling at the
      // terminal delivery itself includes a final stall in the measurement even
      // when no timer or animation-frame callback was able to run during it.
      const terminalAt = performance.now();
      recordGap("maxTimerGapMs", "lastTimerAt", terminalAt);
      recordGap("maxFrameGapMs", "lastFrameAt", terminalAt);
      state.terminalHeartbeat = Object.freeze({
        anchor: "before-worker-launch-through-terminal",
        timerMaxGapMs: state.maxTimerGapMs,
        frameMaxGapMs: state.maxFrameGapMs,
        maxGapMs: Math.max(state.maxTimerGapMs, state.maxFrameGapMs),
        gapLimitMs: MAX_PAGE_HEARTBEAT_GAP_MS,
      });
      return state.terminalHeartbeat;
    },
    stop() {
      state.stopped = true;
      clearInterval(intervalId);
      if (state.frameId !== null) {
        cancelAnimationFrame(state.frameId);
      }
    },
  };
}

function terminalHeartbeatFailure(heartbeat) {
  if (heartbeat === null || typeof heartbeat !== "object" ||
      heartbeat.anchor !== "before-worker-launch-through-terminal" ||
      heartbeat.gapLimitMs !== MAX_PAGE_HEARTBEAT_GAP_MS) {
    return "page heartbeat terminal record is invalid";
  }
  for (const field of ["timerMaxGapMs", "frameMaxGapMs", "maxGapMs"]) {
    if (!Number.isSafeInteger(heartbeat[field]) || heartbeat[field] < 0 ||
        heartbeat[field] > MAX_PAGE_HEARTBEAT_GAP_MS) {
      return "page heartbeat " + field + "=" + String(heartbeat[field]) +
          "ms exceeded the bounded terminal window of " +
          String(MAX_PAGE_HEARTBEAT_GAP_MS) + "ms";
    }
  }
  if (heartbeat.maxGapMs !== Math.max(
      heartbeat.timerMaxGapMs, heartbeat.frameMaxGapMs)) {
    return "page heartbeat maximum gap is inconsistent";
  }
  return null;
}

async function requirePageResponsiveness(activity, baseline, deadline, progress) {
  while (true) {
    const deltas = activity.deltas(baseline);
    if (deltas.ticks >= 1 && deltas.frames >= 1) {
      return deltas;
    }
    const remaining = remainingDeadlineMs(deadline, "page-responsiveness", progress);
    await delay(Math.min(16, remaining));
  }
}

function validTerminalMessage(value, context) {
  return value !== null && typeof value === "object" &&
      value.protocol === HOST_PROTOCOL && value.type === "terminal" &&
      value.runNamespace === context.runNamespace && value.snapshot !== null &&
      typeof value.snapshot === "object";
}

function validPostTerminalError(value, context) {
  return value !== null && typeof value === "object" &&
      value.protocol === HOST_PROTOCOL && value.type === "post-terminal-error" &&
      value.runNamespace === context.runNamespace &&
      typeof value.error === "string" && value.error.length > 0 &&
      value.error.length <= MAX_ERROR_CHARS;
}

function validWorkerCloseConfirmation(value, context) {
  return value !== null && typeof value === "object" &&
      value.protocol === HOST_PROTOCOL &&
      value.type === "terminal-close-confirmed" &&
      value.runNamespace === context.runNamespace &&
      value.preTerminalSettlementTurns ===
          PRE_TERMINAL_WORKER_SETTLEMENT_TURNS &&
      value.postTerminalMicrotaskObserved === true &&
      value.workerCloseInitiated === true;
}

function startRuntimeWorker(context, activity) {
  const workerUrl = new URL("./m7_wasmfs_opfs_shutdown_smoke_worker.js", location.href);
  const moduleUrl = new URL("./artifacts/" + MODULE_NAME + ".js", location.href);
  if (workerUrl.origin !== location.origin || moduleUrl.origin !== location.origin) {
    throw new Error("M7 OPFS shutdown Worker or module is not same-origin");
  }
  const worker = new Worker(workerUrl, {name: WORKER_NAME, type: "module"});
  const runtime = {
    worker,
    terminal: null,
    closeConfirmation: null,
    terminalReceived: false,
    snapshot: null,
    pageWorkerError: null,
    terminalHeartbeat: null,
    workerPreTerminalSettlementObserved: false,
    workerPreTerminalSettlementTurns: 0,
    workerPostTerminalMicrotaskObserved: false,
    workerSelfCloseInitiated: false,
    workerSelfCloseInitiatedBeforeDisposal: false,
    postExitPageBarrierObserved: false,
    noExitRuntimeWorkerObservationObserved: false,
    noExitRuntimeWorkerObservationTurns: 0,
    noExitRuntimePageObservationObserved: false,
    noExitRuntimePageObservationTurns: 0,
    terminationRequested: false,
    terminationRequestedAfterCleanResult: false,
    terminationRequestedForNoExitRuntimeControl: false,
  };
  let resolveTerminal;
  let rejectTerminal;
  let resolveCloseConfirmation;
  let rejectCloseConfirmation;
  runtime.terminal = new Promise((resolve, reject) => {
    resolveTerminal = resolve;
    rejectTerminal = reject;
  });
  runtime.closeConfirmation = new Promise((resolve, reject) => {
    resolveCloseConfirmation = resolve;
    rejectCloseConfirmation = reject;
  });
  // Errors before this stage is awaited still need to reject the pending close
  // confirmation. Mark it handled here; execute() awaits it before success.
  void runtime.closeConfirmation.catch(() => {});
  const recordPageWorkerError = (message) => {
    if (runtime.pageWorkerError === null) {
      runtime.pageWorkerError = redactRunNamespace(message, context.runNamespace);
    }
    const failure = new Error(runtime.pageWorkerError);
    if (!runtime.terminalReceived) {
      rejectTerminal(failure);
    }
    if (!runtime.workerSelfCloseInitiated) {
      rejectCloseConfirmation(failure);
    }
  };
  worker.onmessage = (event) => {
    const payload = event.data;
    if (validTerminalMessage(payload, context)) {
      if (runtime.terminalReceived) {
        recordPageWorkerError(
            "M7 OPFS shutdown Worker posted duplicate terminal result");
        return;
      }
      try {
        runtime.terminalHeartbeat = activity.observeTerminal();
      } catch (error) {
        recordPageWorkerError(formatError(error));
        return;
      }
      runtime.terminalReceived = true;
      runtime.snapshot = payload.snapshot;
      if (context.testFault === TEST_FAULT_NO_EXIT_RUNTIME) {
        runtime.noExitRuntimeWorkerObservationObserved =
            payload.snapshot.noExitRuntimeWorkerObservationObserved === true;
        runtime.noExitRuntimeWorkerObservationTurns =
            payload.snapshot.noExitRuntimeWorkerObservationTurns;
      } else {
        runtime.workerPreTerminalSettlementObserved = true;
        runtime.workerPreTerminalSettlementTurns =
            payload.snapshot.postExitBarrierTurns;
      }
      resolveTerminal(runtime.snapshot);
      return;
    }
    if (validWorkerCloseConfirmation(payload, context)) {
      if (!runtime.terminalReceived || runtime.workerSelfCloseInitiated) {
        recordPageWorkerError(
            "M7 OPFS shutdown Worker posted an invalid close confirmation");
        return;
      }
      runtime.workerPostTerminalMicrotaskObserved = true;
      runtime.workerSelfCloseInitiated = true;
      resolveCloseConfirmation(payload);
      return;
    }
    if (validPostTerminalError(payload, context)) {
      recordPageWorkerError(
          "M7 OPFS shutdown Worker reported a post-terminal error: " +
          payload.error);
      return;
    }
    if (payload !== null && typeof payload === "object" &&
        payload.protocol === HOST_PROTOCOL && payload.type === "protocol-error") {
      recordPageWorkerError("M7 OPFS shutdown Worker protocol error: " +
                            String(payload.error));
      return;
    }
    recordPageWorkerError("M7 OPFS shutdown Worker posted an invalid message");
  };
  worker.onmessageerror = () => {
    recordPageWorkerError("Worker message could not be deserialized");
  };
  worker.onerror = (event) => {
    event.preventDefault();
    recordPageWorkerError(event.message || "Worker error");
  }
  worker.postMessage({
    protocol: HOST_PROTOCOL,
    type: "start",
    moduleUrl: moduleUrl.href,
    runNamespace: context.runNamespace,
    testFault: context.testFault,
  });
  return runtime;
}

function disposeWorker(runtime, afterCleanResult, noExitRuntimeNegativeControl = false) {
  if (runtime.terminationRequested) {
    return;
  }
  if (afterCleanResult && !runtime.workerSelfCloseInitiated) {
    throw new Error(
        "M7 OPFS shutdown Worker did not initiate self-close before successful disposal");
  }
  runtime.worker.terminate();
  // Web Workers do not provide a synchronous termination acknowledgement.
  // The completed native onExit(0) record is the shutdown evidence; this is
  // deliberately recorded as a disposal request rather than a proof that every
  // implementation Worker has stopped at this instant.
  runtime.terminationRequested = true;
  runtime.terminationRequestedAfterCleanResult = afterCleanResult;
  runtime.terminationRequestedForNoExitRuntimeControl =
      noExitRuntimeNegativeControl;
  runtime.workerSelfCloseInitiatedBeforeDisposal =
      afterCleanResult && runtime.workerSelfCloseInitiated;
}

function outputLines(snapshot) {
  if (!Array.isArray(snapshot.stdout) || !Array.isArray(snapshot.stderr) ||
      snapshot.stdout.length > MAX_OUTPUT_LINES ||
      snapshot.stderr.length > MAX_OUTPUT_LINES ||
      snapshot.stdout.some((line) => typeof line !== "string") ||
      snapshot.stderr.some((line) => typeof line !== "string")) {
    return null;
  }
  return snapshot.stdout.concat(snapshot.stderr);
}

function normalRuntimeFailure(snapshot) {
  if (snapshot === null || typeof snapshot !== "object") {
    return "Worker supplied no runtime snapshot";
  }
  const output = outputLines(snapshot);
  if (output === null) {
    return "Worker runtime output is invalid";
  }
  for (const [field, expected] of Object.entries({
    factorySettled: true,
    runtimeInitialized: true,
    runtimeExitCode: 0,
    onExitObserved: true,
    abort: null,
    onAbortObserved: false,
    factoryError: null,
    workerError: null,
    workerHosted: true,
    opfsCapability: true,
    nativeStartObserved: true,
    completionObserved: true,
    completionMarker: COMPLETION_MARKER,
    completionError: null,
    atexitObserved: true,
    atexitMarker: ATEXIT_MARKER,
    atexitError: null,
    terminalReason: "on-exit",
    postExitBarrierObserved: true,
    postExitBarrierTurns: PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
    postExitError: null,
    noExitRuntimeRequested: false,
    noExitRuntimeWorkerObservationObserved: false,
    noExitRuntimeWorkerObservationTurns: 0,
    runtimeLifecycle: "normal-exit",
  })) {
    if (snapshot[field] !== expected) {
      return "Worker runtime " + field + " is not " + String(expected);
    }
  }
  const completionIndex = snapshot.stdout.indexOf(COMPLETION_MARKER);
  const atexitIndex = snapshot.stdout.indexOf(ATEXIT_MARKER);
  if (!output.includes(RUNTIME_START_MARKER) || completionIndex < 0 ||
      atexitIndex <= completionIndex ||
      output.some((line) => line.includes(FAIL_MARKER))) {
    return "Worker native output lacks exact normal-exit markers";
  }
  return null;
}

function noExitRuntimeNegativeControlFailure(snapshot) {
  if (snapshot === null || typeof snapshot !== "object") {
    return "Worker supplied no runtime snapshot";
  }
  const output = outputLines(snapshot);
  if (output === null) {
    return "Worker runtime output is invalid";
  }
  for (const [field, expected] of Object.entries({
    factorySettled: true,
    runtimeInitialized: true,
    runtimeExitCode: null,
    onExitObserved: false,
    abort: null,
    onAbortObserved: false,
    factoryError: null,
    workerError: null,
    workerHosted: true,
    opfsCapability: true,
    nativeStartObserved: true,
    completionObserved: true,
    completionMarker: COMPLETION_MARKER,
    completionError: null,
    atexitObserved: false,
    atexitMarker: null,
    atexitError: null,
    terminalReason: NO_EXIT_RUNTIME_LIFECYCLE,
    postExitBarrierObserved: false,
    postExitBarrierTurns: 0,
    postExitError: null,
    expectedExitStatusObserved: false,
    noExitRuntimeRequested: true,
    noExitRuntimeWorkerObservationObserved: true,
    noExitRuntimeWorkerObservationTurns:
        NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS,
    runtimeLifecycle: NO_EXIT_RUNTIME_LIFECYCLE,
  })) {
    if (snapshot[field] !== expected) {
      return "Worker runtime " + field + " is not " + String(expected);
    }
  }
  const completionIndex = snapshot.stdout.indexOf(COMPLETION_MARKER);
  if (!output.includes(RUNTIME_START_MARKER) || completionIndex < 0 ||
      output.includes(ATEXIT_MARKER) ||
      output.some((line) => line.includes(FAIL_MARKER))) {
    return "Worker native output lacks exact noExitRuntime markers";
  }
  return null;
}

async function requirePostExitPageBarrier(runtime, deadline, progress) {
  if (!runtime.workerSelfCloseInitiated) {
    throw new Error(
        "M7 OPFS shutdown Worker did not initiate self-close before page barrier");
  }
  // The Worker has completed its final post-terminal microtask and requested
  // self-close. Keep the page alive for one more task before disposal/upload
  // so a queued Worker delivery cannot race the terminal boundary.
  await awaitBeforeDeadline(
      delay(0), deadline, "post-terminal-page-error-barrier", progress);
  runtime.postExitPageBarrierObserved = true;
  if (runtime.pageWorkerError !== null) {
    throw new Error("M7 OPFS shutdown Worker reported a post-exit error: " +
                    runtime.pageWorkerError);
  }
}

async function requireNoExitRuntimePageObservation(runtime, deadline, progress) {
  if (runtime.workerSelfCloseInitiated) {
    throw new Error(
        "M7 OPFS noExitRuntime negative-control Worker unexpectedly self-closed");
  }
  // The exact native-completion marker has already gated the Worker-side
  // observation. Retain both the page and the live outer Worker for one more
  // page task before the test explicitly terminates that Worker.
  for (let turn = 0; turn < NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS; ++turn) {
    await awaitBeforeDeadline(
        delay(0), deadline, "no-exit-runtime-page-observation", progress);
  }
  runtime.noExitRuntimePageObservationObserved = true;
  runtime.noExitRuntimePageObservationTurns =
      NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS;
  if (runtime.workerSelfCloseInitiated) {
    throw new Error(
        "M7 OPFS noExitRuntime negative-control Worker unexpectedly self-closed");
  }
  if (runtime.pageWorkerError !== null) {
    throw new Error("M7 OPFS noExitRuntime negative-control Worker reported an error: " +
                    runtime.pageWorkerError);
  }
}

function runtimeSnapshotForResult(runtime) {
  if (runtime === null || runtime.snapshot === null) {
    return null;
  }
  return runtime.snapshot;
}

function failureDiagnostics(progress, context) {
  const runtime = progress.runtime;
  return {
    stage: progress.stage,
    timedOut: progress.timedOut,
    workerCreated: runtime !== null,
    terminalReceived: runtime !== null && runtime.terminalReceived,
    cleanResultReceived: progress.cleanResultReceived,
    terminalHeartbeat: runtime === null ? null : runtime.terminalHeartbeat,
    workerPreTerminalSettlementObserved: runtime !== null &&
        runtime.workerPreTerminalSettlementObserved,
    workerPreTerminalSettlementTurns: runtime === null ? 0 :
        runtime.workerPreTerminalSettlementTurns,
    workerPostTerminalMicrotaskObserved: runtime !== null &&
        runtime.workerPostTerminalMicrotaskObserved,
    workerSelfCloseInitiated: runtime !== null && runtime.workerSelfCloseInitiated,
    workerSelfCloseInitiatedBeforeDisposal: runtime !== null &&
        runtime.workerSelfCloseInitiatedBeforeDisposal,
    postExitPageBarrierObserved: runtime !== null &&
        runtime.postExitPageBarrierObserved,
    noExitRuntimeWorkerObservationObserved: runtime !== null &&
        runtime.noExitRuntimeWorkerObservationObserved,
    noExitRuntimeWorkerObservationTurns: runtime === null ? 0 :
        runtime.noExitRuntimeWorkerObservationTurns,
    noExitRuntimePageObservationObserved: runtime !== null &&
        runtime.noExitRuntimePageObservationObserved,
    noExitRuntimePageObservationTurns: runtime === null ? 0 :
        runtime.noExitRuntimePageObservationTurns,
    workerTerminationRequested: runtime !== null && runtime.terminationRequested,
    workerTerminationRequestedAfterCleanResult: runtime !== null &&
        runtime.terminationRequestedAfterCleanResult,
    workerTerminationRequestedForNoExitRuntimeControl: runtime !== null &&
        runtime.terminationRequestedForNoExitRuntimeControl,
    pageWorkerError: runtime === null ? null : runtime.pageWorkerError,
    runtime: runtimeSnapshotForResult(runtime),
    runNamespaceRedacted: context.runNamespace.length > 0,
  };
}

function recordFailure(result, progress, context, error) {
  result.runtime = runtimeSnapshotForResult(progress.runtime);
  result.failureDiagnostics = failureDiagnostics(progress, context);
  result.error = boundedError(formatError(error), context.runNamespace);
}

function baseResult(context) {
  return {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    shutdownScope: SHUTDOWN_SCOPE,
    runNamespace: context.runNamespace,
    status: "fail",
    origin: location.origin,
    crossOriginIsolated: globalThis.crossOriginIsolated === true,
    sharedArrayBuffer: typeof SharedArrayBuffer === "function",
    opfsCapability: false,
    opfsFallbackUsed: false,
    normalRuntimeShutdownProven: false,
    runtimeLifecycle: "not-observed",
    outerPageResponsive: false,
    pageTickDelta: 0,
    pageFrameDelta: 0,
    pageHeartbeatAnchor: null,
    pageTimerMaxGapMs: 0,
    pageFrameMaxGapMs: 0,
    pageHeartbeatMaxGapMs: 0,
    pageHeartbeatGapLimitMs: MAX_PAGE_HEARTBEAT_GAP_MS,
    pageHeartbeatTerminalObserved: false,
    workerPreTerminalSettlementObserved: false,
    workerPreTerminalSettlementTurns: 0,
    workerPostTerminalMicrotaskObserved: false,
    workerSelfCloseInitiated: false,
    workerSelfCloseInitiatedBeforeDisposal: false,
    postExitPageBarrierObserved: false,
    postExitPageBarrierTurns: 0,
    noExitRuntimeNegativeControlProven: false,
    noExitRuntimeWorkerObservationObserved: false,
    noExitRuntimeWorkerObservationTurns: 0,
    noExitRuntimePageObservationObserved: false,
    noExitRuntimePageObservationTurns: 0,
    workerTerminationRequested: false,
    workerTerminationRequestedAfterCleanResult: false,
    workerTerminationRequestedForNoExitRuntimeControl: false,
    profilePersistenceProven: false,
    fileLockSemanticsProven: false,
    atomicRecoveryProven: false,
    databaseRecoveryProven: false,
    runtime: null,
    failureDiagnostics: null,
    error: null,
  };
}

async function executeNormalShutdown(context) {
  const deadline = createDeadline(context);
  const result = baseResult(context);
  const activity = beginResponsivenessProbe();
  const progress = {
    stage: "document-prerequisites",
    timedOut: false,
    runtime: null,
    cleanResultReceived: false,
  };
  try {
    if (!hasDocumentPrerequisites()) {
      throw new Error("required dedicated-Worker document prerequisites are unavailable");
    }
    progress.stage = "start-runtime-worker";
    const baseline = activity.baseline();
    progress.runtime = startRuntimeWorker(context, activity);
    progress.stage = "wait-for-normal-exit";
    const snapshot = await awaitBeforeDeadline(
        progress.runtime.terminal, deadline, progress.stage, progress);
    result.runtime = snapshot;
    result.opfsCapability = snapshot.opfsCapability === true;
    const heartbeat = progress.runtime.terminalHeartbeat;
    const heartbeatFailure = terminalHeartbeatFailure(heartbeat);
    if (heartbeatFailure !== null) {
      throw new Error(heartbeatFailure);
    }
    result.pageHeartbeatAnchor = heartbeat.anchor;
    result.pageTimerMaxGapMs = heartbeat.timerMaxGapMs;
    result.pageFrameMaxGapMs = heartbeat.frameMaxGapMs;
    result.pageHeartbeatMaxGapMs = heartbeat.maxGapMs;
    result.pageHeartbeatGapLimitMs = heartbeat.gapLimitMs;
    result.pageHeartbeatTerminalObserved = true;
    result.workerPreTerminalSettlementObserved =
        progress.runtime.workerPreTerminalSettlementObserved;
    result.workerPreTerminalSettlementTurns =
        progress.runtime.workerPreTerminalSettlementTurns;
    const runtimeFailure = normalRuntimeFailure(snapshot);
    if (runtimeFailure !== null) {
      throw new Error(runtimeFailure);
    }
    progress.stage = "wait-for-worker-close-confirmation";
    const closeConfirmation = await awaitBeforeDeadline(
        progress.runtime.closeConfirmation, deadline, progress.stage, progress);
    if (closeConfirmation.preTerminalSettlementTurns !==
            PRE_TERMINAL_WORKER_SETTLEMENT_TURNS ||
        closeConfirmation.postTerminalMicrotaskObserved !== true ||
        closeConfirmation.workerCloseInitiated !== true ||
        progress.runtime.pageWorkerError !== null) {
      throw new Error("M7 OPFS shutdown Worker close confirmation is invalid");
    }
    result.workerPostTerminalMicrotaskObserved =
        progress.runtime.workerPostTerminalMicrotaskObserved;
    result.workerSelfCloseInitiated = progress.runtime.workerSelfCloseInitiated;
    progress.stage = "post-terminal-page-error-barrier";
    await requirePostExitPageBarrier(progress.runtime, deadline, progress);
    result.postExitPageBarrierObserved = true;
    result.postExitPageBarrierTurns = POST_EXIT_PAGE_BARRIER_TURNS;
    progress.cleanResultReceived = true;
    result.runtimeLifecycle = "normal-exit";
    progress.stage = "page-responsiveness";
    const deltas = await requirePageResponsiveness(
        activity, baseline, deadline, progress);
    result.pageTickDelta = deltas.ticks;
    result.pageFrameDelta = deltas.frames;
    result.outerPageResponsive = true;

    // Do not dispose this outer Worker until its native onExit(0) snapshot
    // establishes that normal Emscripten teardown has run inside it.
    progress.stage = "dispose-worker-after-clean-result";
    disposeWorker(progress.runtime, /*afterCleanResult=*/true);
    result.workerTerminationRequested = progress.runtime.terminationRequested;
    result.workerTerminationRequestedAfterCleanResult =
        progress.runtime.terminationRequestedAfterCleanResult;
    result.workerSelfCloseInitiatedBeforeDisposal =
        progress.runtime.workerSelfCloseInitiatedBeforeDisposal;
    result.normalRuntimeShutdownProven = true;
    result.status = "pass";
  } catch (error) {
    recordFailure(result, progress, context, error);
    if (progress.runtime !== null && !progress.runtime.terminationRequested) {
      // Failure cleanup is intentionally distinct from the successful lifecycle
      // assertion above. It prevents a timed-out test Worker from leaking.
      disposeWorker(progress.runtime, /*afterCleanResult=*/false);
      result.workerTerminationRequested = true;
    }
    // Refresh the diagnostic snapshot after failure cleanup so its lifecycle
    // fields describe the posted result rather than the pre-disposal state.
    result.failureDiagnostics = failureDiagnostics(progress, context);
  } finally {
    activity.stop();
  }
  return result;
}

async function executeNoExitRuntimeNegativeControl(context) {
  const deadline = createDeadline(context);
  const result = baseResult(context);
  const activity = beginResponsivenessProbe();
  const progress = {
    stage: "document-prerequisites",
    timedOut: false,
    runtime: null,
    cleanResultReceived: false,
  };
  try {
    if (!hasDocumentPrerequisites()) {
      throw new Error("required dedicated-Worker document prerequisites are unavailable");
    }
    progress.stage = "start-no-exit-runtime-worker";
    const baseline = activity.baseline();
    progress.runtime = startRuntimeWorker(context, activity);
    progress.stage = "wait-for-no-exit-runtime-observation";
    const snapshot = await awaitBeforeDeadline(
        progress.runtime.terminal, deadline, progress.stage, progress);
    result.runtime = snapshot;
    result.opfsCapability = snapshot.opfsCapability === true;
    const heartbeat = progress.runtime.terminalHeartbeat;
    const heartbeatFailure = terminalHeartbeatFailure(heartbeat);
    if (heartbeatFailure !== null) {
      throw new Error(heartbeatFailure);
    }
    result.pageHeartbeatAnchor = heartbeat.anchor;
    result.pageTimerMaxGapMs = heartbeat.timerMaxGapMs;
    result.pageFrameMaxGapMs = heartbeat.frameMaxGapMs;
    result.pageHeartbeatMaxGapMs = heartbeat.maxGapMs;
    result.pageHeartbeatGapLimitMs = heartbeat.gapLimitMs;
    result.pageHeartbeatTerminalObserved = true;
    result.noExitRuntimeWorkerObservationObserved =
        progress.runtime.noExitRuntimeWorkerObservationObserved;
    result.noExitRuntimeWorkerObservationTurns =
        progress.runtime.noExitRuntimeWorkerObservationTurns;
    const runtimeFailure = noExitRuntimeNegativeControlFailure(snapshot);
    if (runtimeFailure !== null) {
      throw new Error(runtimeFailure);
    }
    progress.stage = "no-exit-runtime-page-observation";
    await requireNoExitRuntimePageObservation(
        progress.runtime, deadline, progress);
    result.noExitRuntimePageObservationObserved =
        progress.runtime.noExitRuntimePageObservationObserved;
    result.noExitRuntimePageObservationTurns =
        progress.runtime.noExitRuntimePageObservationTurns;
    progress.stage = "page-responsiveness";
    const deltas = await requirePageResponsiveness(
        activity, baseline, deadline, progress);
    result.pageTickDelta = deltas.ticks;
    result.pageFrameDelta = deltas.frames;
    result.outerPageResponsive = true;

    // noExitRuntime intentionally leaves Emscripten's outer Worker alive.
    // This negative control must therefore terminate it explicitly only after
    // the bounded Worker and page observations have demonstrated the absence
    // of normal runtime teardown.
    progress.stage = "terminate-no-exit-runtime-worker";
    disposeWorker(progress.runtime, /*afterCleanResult=*/false,
                  /*noExitRuntimeNegativeControl=*/true);
    result.workerTerminationRequested = progress.runtime.terminationRequested;
    result.workerTerminationRequestedAfterCleanResult =
        progress.runtime.terminationRequestedAfterCleanResult;
    result.workerTerminationRequestedForNoExitRuntimeControl =
        progress.runtime.terminationRequestedForNoExitRuntimeControl;
    result.runtimeLifecycle = NO_EXIT_RUNTIME_LIFECYCLE;
    result.noExitRuntimeNegativeControlProven = true;
    result.status = "pass";
  } catch (error) {
    recordFailure(result, progress, context, error);
    if (progress.runtime !== null && !progress.runtime.terminationRequested) {
      // A failed negative control must not leak a deliberately live Worker.
      disposeWorker(progress.runtime, /*afterCleanResult=*/false);
      result.workerTerminationRequested = true;
    }
    result.failureDiagnostics = failureDiagnostics(progress, context);
  } finally {
    activity.stop();
  }
  return result;
}

async function execute(context) {
  if (context.testFault === TEST_FAULT_NO_EXIT_RUNTIME) {
    return executeNoExitRuntimeNegativeControl(context);
  }
  return executeNormalShutdown(context);
}

function updateVisibleState(result) {
  const root = document.querySelector("#m7-opfs-shutdown-root");
  const status = document.querySelector("#m7-opfs-shutdown-status");
  if (root instanceof HTMLElement) {
    root.dataset.state = result.status;
  }
  if (status instanceof HTMLElement) {
    status.textContent = JSON.stringify({
      ...result,
      runNamespace: "<redacted>",
    }, null, 2);
  }
  globalThis.__chromiumWasmM7WasmfsOpfsShutdownState = Object.freeze({
    protocol: HOST_PROTOCOL,
    case: CASE,
    status: result.status,
    runtimeLifecycle: result.runtimeLifecycle,
  });
}

async function postResult(context, result) {
  const endpoint = new URL(
      "./result/" + encodeURIComponent(context.token), location.href);
  if (endpoint.origin !== location.origin) {
    throw new Error("M7 OPFS shutdown result endpoint is not same-origin");
  }
  const response = await fetch(endpoint.href, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (response.status !== 204) {
    throw new Error("M7 OPFS shutdown result upload returned HTTP " +
                    response.status);
  }
}

function verifyNormalResultShape(result) {
  const failure = normalRuntimeFailure(result.runtime);
  if (result.status !== "pass" || result.origin !== location.origin ||
      result.crossOriginIsolated !== true || result.sharedArrayBuffer !== true ||
      result.opfsCapability !== true || result.opfsFallbackUsed !== false ||
      result.normalRuntimeShutdownProven !== true ||
      result.runtimeLifecycle !== "normal-exit" ||
      result.outerPageResponsive !== true || result.pageTickDelta < 1 ||
      result.pageFrameDelta < 1 ||
      result.pageHeartbeatAnchor !== "before-worker-launch-through-terminal" ||
      !Number.isSafeInteger(result.pageTimerMaxGapMs) ||
      !Number.isSafeInteger(result.pageFrameMaxGapMs) ||
      !Number.isSafeInteger(result.pageHeartbeatMaxGapMs) ||
      result.pageHeartbeatGapLimitMs !== MAX_PAGE_HEARTBEAT_GAP_MS ||
      result.pageHeartbeatTerminalObserved !== true ||
      result.pageTimerMaxGapMs < 0 || result.pageFrameMaxGapMs < 0 ||
      result.pageHeartbeatMaxGapMs !== Math.max(
          result.pageTimerMaxGapMs, result.pageFrameMaxGapMs) ||
      result.pageHeartbeatMaxGapMs > MAX_PAGE_HEARTBEAT_GAP_MS ||
      result.workerPreTerminalSettlementObserved !== true ||
      result.workerPreTerminalSettlementTurns !==
          PRE_TERMINAL_WORKER_SETTLEMENT_TURNS ||
      result.workerPostTerminalMicrotaskObserved !== true ||
      result.workerSelfCloseInitiated !== true ||
      result.workerSelfCloseInitiatedBeforeDisposal !== true ||
      result.postExitPageBarrierObserved !== true ||
      result.postExitPageBarrierTurns !== POST_EXIT_PAGE_BARRIER_TURNS ||
      result.noExitRuntimeNegativeControlProven !== false ||
      result.noExitRuntimeWorkerObservationObserved !== false ||
      result.noExitRuntimeWorkerObservationTurns !== 0 ||
      result.noExitRuntimePageObservationObserved !== false ||
      result.noExitRuntimePageObservationTurns !== 0 ||
      result.workerTerminationRequested !== true ||
      result.workerTerminationRequestedAfterCleanResult !== true ||
      result.workerTerminationRequestedForNoExitRuntimeControl !== false ||
      result.profilePersistenceProven !== false ||
      result.fileLockSemanticsProven !== false || result.atomicRecoveryProven !== false ||
      result.databaseRecoveryProven !== false || result.failureDiagnostics !== null ||
      result.error !== null || failure !== null) {
    throw new Error("M7 OPFS normal-shutdown result is incomplete");
  }
}

function verifyNoExitRuntimeNegativeControlResultShape(result) {
  const failure = noExitRuntimeNegativeControlFailure(result.runtime);
  if (result.status !== "pass" || result.origin !== location.origin ||
      result.crossOriginIsolated !== true || result.sharedArrayBuffer !== true ||
      result.opfsCapability !== true || result.opfsFallbackUsed !== false ||
      result.normalRuntimeShutdownProven !== false ||
      result.noExitRuntimeNegativeControlProven !== true ||
      result.runtimeLifecycle !== NO_EXIT_RUNTIME_LIFECYCLE ||
      result.outerPageResponsive !== true || result.pageTickDelta < 1 ||
      result.pageFrameDelta < 1 ||
      result.pageHeartbeatAnchor !== "before-worker-launch-through-terminal" ||
      !Number.isSafeInteger(result.pageTimerMaxGapMs) ||
      !Number.isSafeInteger(result.pageFrameMaxGapMs) ||
      !Number.isSafeInteger(result.pageHeartbeatMaxGapMs) ||
      result.pageHeartbeatGapLimitMs !== MAX_PAGE_HEARTBEAT_GAP_MS ||
      result.pageHeartbeatTerminalObserved !== true ||
      result.pageTimerMaxGapMs < 0 || result.pageFrameMaxGapMs < 0 ||
      result.pageHeartbeatMaxGapMs !== Math.max(
          result.pageTimerMaxGapMs, result.pageFrameMaxGapMs) ||
      result.pageHeartbeatMaxGapMs > MAX_PAGE_HEARTBEAT_GAP_MS ||
      result.workerPreTerminalSettlementObserved !== false ||
      result.workerPreTerminalSettlementTurns !== 0 ||
      result.workerPostTerminalMicrotaskObserved !== false ||
      result.workerSelfCloseInitiated !== false ||
      result.workerSelfCloseInitiatedBeforeDisposal !== false ||
      result.postExitPageBarrierObserved !== false ||
      result.postExitPageBarrierTurns !== 0 ||
      result.noExitRuntimeWorkerObservationObserved !== true ||
      result.noExitRuntimeWorkerObservationTurns !==
          NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS ||
      result.noExitRuntimePageObservationObserved !== true ||
      result.noExitRuntimePageObservationTurns !==
          NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS ||
      result.workerTerminationRequested !== true ||
      result.workerTerminationRequestedAfterCleanResult !== false ||
      result.workerTerminationRequestedForNoExitRuntimeControl !== true ||
      result.profilePersistenceProven !== false ||
      result.fileLockSemanticsProven !== false || result.atomicRecoveryProven !== false ||
      result.databaseRecoveryProven !== false || result.failureDiagnostics !== null ||
      result.error !== null || failure !== null) {
    throw new Error("M7 OPFS noExitRuntime negative-control result is incomplete");
  }
}

function verifyResultShape(result, context) {
  if (context.testFault === TEST_FAULT_NO_EXIT_RUNTIME) {
    verifyNoExitRuntimeNegativeControlResultShape(result);
    return;
  }
  verifyNormalResultShape(result);
}

export async function runM7WasmfsOpfsShutdownSmokeFromQuery() {
  const context = staticContext(new URLSearchParams(location.search));
  const result = await execute(context);
  updateVisibleState(result);
  await postResult(context, result);
  verifyResultShape(result, context);
  return result;
}

export const m7WasmfsOpfsShutdownSmokeContract = Object.freeze({
  protocol: HOST_PROTOCOL,
  case: CASE,
  scope: SCOPE,
  completionMarker: COMPLETION_MARKER,
  atexitMarker: ATEXIT_MARKER,
  preTerminalWorkerSettlementTurns: PRE_TERMINAL_WORKER_SETTLEMENT_TURNS,
  postTerminalMicrotaskObserved: true,
  noExitRuntimeWorkerObservationTurns:
      NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS,
  noExitRuntimePageObservationTurns: NO_EXIT_RUNTIME_PAGE_OBSERVATION_TURNS,
});

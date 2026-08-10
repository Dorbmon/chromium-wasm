// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// The normal-exit WasmFS target is intentionally instantiated in this outer
// dedicated Worker. Emscripten then executes its global atexit callbacks here,
// rather than on the page's browser-main thread. This file performs no OPFS
// operation: the C++ WasmFS target is the sole OPFS user.

const HOST_PROTOCOL = 1;
const MODULE_NAME = "m7_wasmfs_opfs_shutdown_smoke";
const RUN_SWITCH = "--m7-opfs-run=";
const RUNTIME_START_MARKER =
    "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:RUNTIME_START run_id=redacted";
const COMPLETION_MARKER =
    "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:NATIVE_COMPLETE " +
    "rw=ok fdatasync=ok close=ok cleanup=ok";
const ATEXIT_MARKER = "CHROMIUM_WASM_M7_OPFS_ATEXIT:after-native-complete";
const FAIL_MARKER = "CHROMIUM_WASM_M7_OPFS_SHUTDOWN:FAIL";
const MAX_OUTPUT_LINES = 128;
const MAX_OUTPUT_CHARS = 512;
const PRE_TERMINAL_SETTLEMENT_TURNS = 2;
const NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS = 2;
const TEST_FAULT_DELAYED_POST_TERMINAL_ERROR =
    "delayed-post-terminal-error";
const TEST_FAULT_NO_EXIT_RUNTIME = "no-exit-runtime";
const NO_EXIT_RUNTIME_TERMINAL_REASON = "no-exit-runtime-negative-control";
const RUN_NAMESPACE_RE = /^[A-Za-z0-9_-]{16,128}$/;

let started = false;
let activeState = null;

function formatError(error) {
  return error instanceof Error ? error.message : String(error);
}

function redactRunNamespace(value, runNamespace) {
  return String(value).split(runNamespace).join("<run-namespace>");
}

function boundedText(value, runNamespace) {
  return redactRunNamespace(value, runNamespace).slice(0, MAX_OUTPUT_CHARS);
}

function appendBounded(values, value, runNamespace) {
  const captured = boundedText(value, runNamespace);
  values.push(captured);
  if (values.length > MAX_OUTPUT_LINES) {
    values.splice(0, values.length - MAX_OUTPUT_LINES);
  }
  return captured;
}

function outputContainsExact(output, marker) {
  return output.stdout.includes(marker) || output.stderr.includes(marker);
}

function outputContains(output, fragment) {
  return output.stdout.some((line) => line.includes(fragment)) ||
      output.stderr.some((line) => line.includes(fragment));
}

function hasOpfsApiShape() {
  // This is an API-shape check only. Do not call getDirectory() or otherwise
  // acquire an OPFS object from the host worker.
  return self.isSecureContext === true && self.crossOriginIsolated === true &&
      typeof SharedArrayBuffer === "function" &&
      typeof navigator === "object" && navigator !== null &&
      typeof navigator.storage === "object" && navigator.storage !== null &&
      typeof navigator.storage.getDirectory === "function" &&
      typeof FileSystemFileHandle === "function" &&
      typeof FileSystemFileHandle.prototype.createSyncAccessHandle === "function";
}

function isNoExitRuntimeNegativeControl(state) {
  return state.testFault === TEST_FAULT_NO_EXIT_RUNTIME;
}

function normalExitFailure(state) {
  if (!state.factorySettled || !state.runtimeInitialized) {
    return "runtime never initialized";
  }
  if (!state.onExitObserved || state.runtimeExitCode !== 0) {
    return "runtime did not report onExit(0)";
  }
  if (state.onAbortObserved || state.abort !== null) {
    return "runtime aborted";
  }
  if (state.factoryError !== null || state.workerError !== null) {
    return "runtime or worker reported an error";
  }
  if (!state.postExitBarrierObserved ||
      state.postExitBarrierTurns !== PRE_TERMINAL_SETTLEMENT_TURNS ||
      state.postExitError !== null) {
    return "post-onExit error barrier is incomplete";
  }
  if (!state.completionObserved || state.completionMarker !== COMPLETION_MARKER ||
      state.completionError !== null) {
    return "native completion marker is incomplete";
  }
  if (!state.atexitObserved || state.atexitMarker !== ATEXIT_MARKER ||
      state.atexitError !== null) {
    return "native atexit marker is incomplete";
  }
  const completionIndex = state.output.stdout.indexOf(COMPLETION_MARKER);
  const atexitIndex = state.output.stdout.indexOf(ATEXIT_MARKER);
  if (completionIndex < 0 || atexitIndex <= completionIndex ||
      outputContains(state.output, FAIL_MARKER)) {
    return "native output is incomplete";
  }
  return null;
}

function noExitRuntimeNegativeControlFailure(state) {
  if (!isNoExitRuntimeNegativeControl(state)) {
    return "noExitRuntime negative control was not requested";
  }
  if (!state.factorySettled || !state.runtimeInitialized) {
    return "runtime never initialized";
  }
  if (state.onExitObserved || state.runtimeExitCode !== null ||
      state.expectedExitStatusObserved) {
    return "runtime unexpectedly entered normal exit";
  }
  if (state.onAbortObserved || state.abort !== null) {
    return "runtime aborted";
  }
  if (state.factoryError !== null || state.workerError !== null ||
      state.postExitError !== null) {
    return "runtime or worker reported an error";
  }
  if (!state.noExitRuntimeWorkerObservationObserved ||
      state.noExitRuntimeWorkerObservationTurns !==
          NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS) {
    return "bounded noExitRuntime Worker observation is incomplete";
  }
  if (!state.completionObserved || state.completionMarker !== COMPLETION_MARKER ||
      state.completionError !== null) {
    return "native completion marker is incomplete";
  }
  if (state.atexitObserved || state.atexitMarker !== null ||
      state.atexitError !== null) {
    return "native atexit unexpectedly ran";
  }
  const completionIndex = state.output.stdout.indexOf(COMPLETION_MARKER);
  if (completionIndex < 0 || !outputContainsExact(
          state.output, RUNTIME_START_MARKER) ||
      outputContainsExact(state.output, ATEXIT_MARKER) ||
      outputContains(state.output, FAIL_MARKER)) {
    return "native output is incomplete";
  }
  return null;
}

function snapshot(state) {
  const normalFailure = normalExitFailure(state);
  const noExitRuntimeFailure = noExitRuntimeNegativeControlFailure(state);
  let runtimeLifecycle = "not-normal-exit";
  if (state.terminalReason === "on-exit" && normalFailure === null) {
    runtimeLifecycle = "normal-exit";
  } else if (state.terminalReason === NO_EXIT_RUNTIME_TERMINAL_REASON &&
             noExitRuntimeFailure === null) {
    runtimeLifecycle = NO_EXIT_RUNTIME_TERMINAL_REASON;
  }
  return {
    factorySettled: state.factorySettled,
    runtimeInitialized: state.runtimeInitialized,
    runtimeExitCode: state.runtimeExitCode,
    onExitObserved: state.onExitObserved,
    abort: state.abort,
    onAbortObserved: state.onAbortObserved,
    factoryError: state.factoryError,
    workerError: state.workerError,
    workerHosted: typeof WorkerGlobalScope !== "undefined" &&
        self instanceof WorkerGlobalScope,
    opfsCapability: state.opfsCapability,
    nativeStartObserved: outputContainsExact(state.output, RUNTIME_START_MARKER),
    completionObserved: state.completionObserved,
    completionMarker: state.completionMarker,
    completionError: state.completionError,
    atexitObserved: state.atexitObserved,
    atexitMarker: state.atexitMarker,
    atexitError: state.atexitError,
    terminalReason: state.terminalReason,
    postExitBarrierObserved: state.postExitBarrierObserved,
    postExitBarrierTurns: state.postExitBarrierTurns,
    postExitError: state.postExitError,
    expectedExitStatusObserved: state.expectedExitStatusObserved,
    noExitRuntimeRequested: isNoExitRuntimeNegativeControl(state),
    noExitRuntimeWorkerObservationObserved:
        state.noExitRuntimeWorkerObservationObserved,
    noExitRuntimeWorkerObservationTurns:
        state.noExitRuntimeWorkerObservationTurns,
    runtimeLifecycle,
    stdout: state.output.stdout.slice(),
    stderr: state.output.stderr.slice(),
  };
}

function isExpectedNormalEmscriptenExitStatus(state, error) {
  if (!state.onExitObserved || state.runtimeExitCode !== 0) {
    return false;
  }
  // The pinned generated loader throws this internal control-flow object from
  // quit_() after it has called onExit(0). Do not treat a nonzero status as
  // clean shutdown. When the Worker error event retains the object, require
  // its exact name, status, and message; browsers that retain only its message
  // are accepted only for the exact generated zero-exit string.
  if (error === "Program terminated with exit(0)") {
    // Some Worker error events expose only the generated object's message.
    return true;
  }
  return error !== null && typeof error === "object" &&
      error.name === "ExitStatus" && error.status === 0 &&
      error.message === "Program terminated with exit(0)";
}

function recordExpectedExitStatus(state) {
  state.expectedExitStatusObserved = true;
}

function recordPostExitError(state, error) {
  const captured = boundedText(formatError(error), state.runNamespace);
  if (state.onExitObserved && state.postExitError === null) {
    state.postExitError = captured;
  }
  return captured;
}

function postTerminalError(state, error) {
  if (state.postTerminalErrorReported) {
    return;
  }
  // A terminal snapshot cannot be mutated after it is posted. Preserve a real
  // late error as a separate, authenticated protocol record. The host accepts
  // success only after this Worker has completed its bounded final turn and
  // sent a close confirmation.
  state.postTerminalErrorReported = true;
  const captured = recordPostExitError(state, error);
  self.postMessage({
    protocol: HOST_PROTOCOL,
    type: "post-terminal-error",
    runNamespace: state.runNamespace,
    error: captured,
  });
}

function postTerminal(state, reason) {
  if (state.terminalSent) {
    return;
  }
  state.terminalReason = reason;
  state.terminalSent = true;
  self.postMessage({
    protocol: HOST_PROTOCOL,
    type: "terminal",
    runNamespace: state.runNamespace,
    snapshot: snapshot(state),
  });
}

function setWorkerFailure(state, field, error, reason) {
  if (state.terminalSent) {
    postTerminalError(state, error);
    return;
  }
  const captured = recordPostExitError(state, error);
  state[field] = captured;
  state.factorySettled = true;
  postTerminal(state, reason);
}

function waitForWorkerTurn() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function reportTestDelayedPostTerminalError(state) {
  postTerminalError(
      state,
      new Error("M7 OPFS shutdown adversarial delayed post-terminal error"));
}

function closeAfterTerminal(state) {
  if (!state.terminalSent || state.terminalReason !== "on-exit" ||
      state.postTerminalCloseScheduled) {
    return;
  }
  state.postTerminalCloseScheduled = true;
  // Emscripten's generated normal-exit path can close this outer Worker before
  // a later task runs. A microtask is the final observable boundary that is
  // guaranteed to run in this same turn after the terminal snapshot.
  queueMicrotask(() => {
    if (state.testFault === TEST_FAULT_DELAYED_POST_TERMINAL_ERROR) {
      reportTestDelayedPostTerminalError(state);
      return;
    }
    if (state.postExitError !== null) {
      return;
    }
    if (typeof self.close !== "function") {
      postTerminalError(state, "M7 OPFS shutdown Worker cannot self-close");
      return;
    }
    state.closeConfirmationSent = true;
    self.postMessage({
      protocol: HOST_PROTOCOL,
      type: "terminal-close-confirmed",
      runNamespace: state.runNamespace,
      preTerminalSettlementTurns: state.postExitBarrierTurns,
      postTerminalMicrotaskObserved: true,
      workerCloseInitiated: true,
    });
    // This is the Worker's final protocol record. It requests closure of this
    // outer Worker after the bounded error-observation microtask; the page
    // treats the request as a disposal precondition, rather than assuming a
    // synchronous browser acknowledgement for every implementation worker.
    self.close();
  });
}

async function settleBeforeTerminal(state) {
  if (state.terminalSent || state.preTerminalSettlementScheduled) {
    return;
  }
  state.preTerminalSettlementScheduled = true;
  // The generated normal exit has already delivered onExit(0). Retain the
  // outer Worker for two task turns so a trailing error is observable before
  // any success snapshot can be published.
  for (let turn = 0; turn < PRE_TERMINAL_SETTLEMENT_TURNS; ++turn) {
    await waitForWorkerTurn();
    if (state.postExitError !== null) {
      return;
    }
  }
  state.postExitBarrierObserved = true;
  state.postExitBarrierTurns = PRE_TERMINAL_SETTLEMENT_TURNS;
  postTerminal(state, "on-exit");
  closeAfterTerminal(state);
}

function schedulePreTerminalSettlement(state) {
  void settleBeforeTerminal(state).catch((error) => {
    if (state.terminalSent) {
      postTerminalError(state, error);
    } else {
      setWorkerFailure(state, "workerError", error, "post-exit-barrier-error");
    }
  });
}

async function observeNoExitRuntimeBeforeTerminal(state) {
  if (state.terminalSent || state.noExitRuntimeWorkerObservationScheduled) {
    return;
  }
  state.noExitRuntimeWorkerObservationScheduled = true;
  // This path begins only after C++ has emitted its exact completion marker.
  // It deliberately does not use factory settlement as a proxy for main()
  // completion: the modularized loader may settle before or around callMain().
  for (let turn = 0; turn < NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS; ++turn) {
    await waitForWorkerTurn();
    if (state.terminalSent) {
      return;
    }
  }
  state.noExitRuntimeWorkerObservationObserved = true;
  state.noExitRuntimeWorkerObservationTurns =
      NO_EXIT_RUNTIME_WORKER_OBSERVATION_TURNS;
  postTerminal(state, NO_EXIT_RUNTIME_TERMINAL_REASON);
}

function scheduleNoExitRuntimeObservation(state) {
  if (!isNoExitRuntimeNegativeControl(state)) {
    return;
  }
  void observeNoExitRuntimeBeforeTerminal(state).catch((error) => {
    if (state.terminalSent) {
      postTerminalError(state, error);
    } else {
      setWorkerFailure(state, "workerError", error,
                       "no-exit-runtime-observation-error");
    }
  });
}

function captureNativeOutput(state, destination, line) {
  const captured = appendBounded(destination, line, state.runNamespace);
  if (captured === COMPLETION_MARKER) {
    if (state.completionObserved && state.completionError === null) {
      state.completionError = "native completion marker was duplicated";
      return;
    }
    state.completionObserved = true;
    state.completionMarker = captured;
    scheduleNoExitRuntimeObservation(state);
  } else if (captured === ATEXIT_MARKER) {
    if (!state.completionObserved) {
      state.atexitError = "native atexit marker preceded native completion";
    } else if (state.atexitObserved) {
      state.atexitError = "native atexit marker was duplicated";
    } else {
      state.atexitObserved = true;
      state.atexitMarker = captured;
    }
    if (isNoExitRuntimeNegativeControl(state) && state.terminalSent) {
      postTerminalError(
          state, "noExitRuntime negative control observed native atexit");
    }
  } else if (captured.includes(FAIL_MARKER) && state.completionError === null) {
    state.completionError = "native WasmFS OPFS shutdown smoke emitted FAIL";
  }
}

function parseStartMessage(value) {
  if (value === null || typeof value !== "object" ||
      value.protocol !== HOST_PROTOCOL || value.type !== "start" ||
      typeof value.moduleUrl !== "string" ||
      typeof value.runNamespace !== "string" ||
      !RUN_NAMESPACE_RE.test(value.runNamespace)) {
    throw new Error("M7 OPFS shutdown worker start message is invalid");
  }
  const testFault = value.testFault === null ? null : value.testFault;
  if (testFault !== null &&
      testFault !== TEST_FAULT_DELAYED_POST_TERMINAL_ERROR &&
      testFault !== TEST_FAULT_NO_EXIT_RUNTIME) {
    throw new Error("M7 OPFS shutdown worker test fault is invalid");
  }
  const moduleUrl = new URL(value.moduleUrl, self.location.href);
  if (moduleUrl.origin !== self.location.origin ||
      !moduleUrl.pathname.endsWith("/artifacts/" + MODULE_NAME + ".js")) {
    throw new Error("M7 OPFS shutdown module URL is invalid");
  }
  return {moduleUrl, runNamespace: value.runNamespace, testFault};
}

function postProtocolError(error) {
  self.postMessage({
    protocol: HOST_PROTOCOL,
    type: "protocol-error",
    error: String(error).slice(0, MAX_OUTPUT_CHARS),
  });
}

async function startRuntime(config) {
  const state = {
    runNamespace: config.runNamespace,
    testFault: config.testFault,
    output: {stdout: [], stderr: []},
    factorySettled: false,
    runtimeInitialized: false,
    runtimeExitCode: null,
    onExitObserved: false,
    abort: null,
    onAbortObserved: false,
    factoryError: null,
    workerError: null,
    opfsCapability: hasOpfsApiShape(),
    completionObserved: false,
    completionMarker: null,
    completionError: null,
    atexitObserved: false,
    atexitMarker: null,
    atexitError: null,
    terminalReason: null,
    terminalSent: false,
    preTerminalSettlementScheduled: false,
    postTerminalCloseScheduled: false,
    noExitRuntimeWorkerObservationScheduled: false,
    noExitRuntimeWorkerObservationObserved: false,
    noExitRuntimeWorkerObservationTurns: 0,
    postExitBarrierObserved: false,
    postExitBarrierTurns: 0,
    postExitError: null,
    expectedExitStatusObserved: false,
    postTerminalErrorReported: false,
    closeConfirmationSent: false,
  };
  activeState = state;
  if (!state.opfsCapability) {
    setWorkerFailure(state, "factoryError",
                     "required OPFS synchronous-access API shape is unavailable",
                     "capability");
    return;
  }

  try {
    const response = await fetch(config.moduleUrl.href, {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error("M7 OPFS shutdown module request returned HTTP " +
                      response.status);
    }
    const mainScriptUrlOrBlob = await response.blob();
    if (mainScriptUrlOrBlob.size === 0) {
      throw new Error("M7 OPFS shutdown module loader is empty");
    }
    const namespace = await import(config.moduleUrl.href);
    if (typeof namespace.default !== "function") {
      throw new Error("M7 OPFS shutdown module loader has no default factory");
    }

    const factory = namespace.default({
      arguments: [RUN_SWITCH + state.runNamespace],
      // This test-only negative control changes only the outer module
      // factory. The Wasm target and its EXIT_RUNTIME link settings remain
      // exactly the normal smoke's settings.
      noExitRuntime: state.testFault === TEST_FAULT_NO_EXIT_RUNTIME,
      mainScriptUrlOrBlob,
      locateFile: (path) => new URL(path, config.moduleUrl).href,
      print(line) { captureNativeOutput(state, state.output.stdout, line); },
      printErr(line) { captureNativeOutput(state, state.output.stderr, line); },
      onRuntimeInitialized() {
        // The generated factory resolves immediately before it invokes main.
        // Record this synchronously so an immediately-returning main cannot
        // race the Worker snapshot.
        state.runtimeInitialized = true;
        state.factorySettled = true;
      },
      onAbort(reason) {
        state.onAbortObserved = true;
        state.abort = boundedText(reason, state.runNamespace);
        if (state.terminalSent) {
          postTerminalError(state, "runtime aborted after terminal: " + state.abort);
        } else {
          postTerminal(state, "abort");
        }
      },
      onExit(code) {
        state.onExitObserved = true;
        state.runtimeExitCode = Number(code);
        if (isNoExitRuntimeNegativeControl(state)) {
          if (state.terminalSent) {
            postTerminalError(
                state,
                "noExitRuntime negative control unexpectedly received onExit(" +
                    String(state.runtimeExitCode) + ")");
          } else if (state.completionObserved) {
            // Never route this mode through the normal-exit terminal path.
            // Its terminal snapshot must expose the unexpected callback.
            scheduleNoExitRuntimeObservation(state);
          }
          return;
        }
        schedulePreTerminalSettlement(state);
      },
    });
    const module = await Promise.resolve(factory);
    if (!module || (typeof module !== "object" && typeof module !== "function")) {
      throw new Error("M7 OPFS shutdown factory returned no Module");
    }
    state.factorySettled = true;
  } catch (error) {
    if (isExpectedNormalEmscriptenExitStatus(state, error)) {
      recordExpectedExitStatus(state);
      state.factorySettled = true;
      if (isNoExitRuntimeNegativeControl(state) && state.terminalSent) {
        postTerminalError(
            state,
            "noExitRuntime negative control unexpectedly received exit status");
      }
      return;
    }
    setWorkerFailure(state, "factoryError", error, "factory-error");
  }
}

self.addEventListener("message", (event) => {
  if (!started) {
    started = true;
    try {
      const config = parseStartMessage(event.data);
      void startRuntime(config);
    } catch (error) {
      postProtocolError(formatError(error));
    }
    return;
  }

  const state = activeState;
  if (state === null) {
    postProtocolError("M7 OPFS shutdown worker received control before start");
    return;
  }
  postProtocolError(
      "M7 OPFS shutdown worker received an unexpected post-start message");
});

self.addEventListener("error", (event) => {
  const state = activeState;
  if (state !== null && isExpectedNormalEmscriptenExitStatus(state, event.error)) {
    recordExpectedExitStatus(state);
    event.preventDefault();
    return;
  }
  if (state !== null && !state.terminalSent) {
    setWorkerFailure(state, "workerError", event.error || event.message || "worker error",
                     state.onExitObserved ? "post-exit-error" : "worker-error");
    event.preventDefault();
    return;
  }
  if (state !== null) {
    postTerminalError(state, event.error || event.message || "worker error");
    event.preventDefault();
  }
});

self.addEventListener("unhandledrejection", (event) => {
  const state = activeState;
  if (state !== null && isExpectedNormalEmscriptenExitStatus(state, event.reason)) {
    recordExpectedExitStatus(state);
    event.preventDefault();
    return;
  }
  if (state !== null && !state.terminalSent) {
    setWorkerFailure(state, "workerError", event.reason,
                     state.onExitObserved ? "post-exit-rejection" :
                         "worker-rejection");
    event.preventDefault();
    return;
  }
  if (state !== null) {
    postTerminalError(state, event.reason);
    event.preventDefault();
  }
});

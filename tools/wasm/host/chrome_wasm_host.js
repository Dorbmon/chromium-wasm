// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const HOST_PROTOCOL = 1;
const FOUNDATION_CASE = "chrome_foundation_m6";
const FOUNDATION_SCOPE = "foundation-only";
const FOUNDATION_EXIT_CODE = 13;
const FOUNDATION_MARKER =
  "chrome_wasm M6 foundation initialized, but the source-selected Chrome " +
  "Views browser lifecycle is not available yet";
const MIN_HEARTBEAT_ELAPSED_MS = 100;
const MIN_HEARTBEAT_TICKS = 2;
const MAX_TIMER_GAP_MS = 250;
const MAX_FOUNDATION_TIMEOUT_MS = 120000;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} must be a nonempty string`);
  }
  return value;
}

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error(`invalid Chrome foundation versions: ${String(error)}`);
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  element.replaceChildren();
  for (const [name, value] of Object.entries(versions)) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = value;
    element.append(term, definition);
  }
}

class ChromiumWasmChromeHost {
  #canvas;
  #versions;
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #runtimeInitialized = false;
  #runtimeExitCode = null;
  #processExitCode = null;
  #abort = null;
  #timerTicks = 0;
  #animationFrameTicks = 0;
  #timerHandle = null;
  #animationFrameHandle = null;
  #lastTimerTime = 0;
  #maxTimerGapMs = 0;
  #runtimeInitializedAt = null;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #errorHandler;
  #rejectionHandler;

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("Chrome foundation host requires a canvas");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
  }

  #startHeartbeat() {
    this.#timerTicks = 0;
    this.#animationFrameTicks = 0;
    this.#maxTimerGapMs = 0;
    this.#lastTimerTime = performance.now();
    this.#timerHandle = setInterval(() => {
      const now = performance.now();
      this.#maxTimerGapMs = Math.max(
        this.#maxTimerGapMs, now - this.#lastTimerTime);
      this.#lastTimerTime = now;
      this.#timerTicks += 1;
    }, 25);
    const onAnimationFrame = () => {
      this.#animationFrameTicks += 1;
      this.#animationFrameHandle = requestAnimationFrame(onAnimationFrame);
    };
    this.#animationFrameHandle = requestAnimationFrame(onAnimationFrame);
  }

  #stopHeartbeat() {
    if (this.#timerHandle !== null) {
      clearInterval(this.#timerHandle);
      this.#timerHandle = null;
    }
    if (this.#animationFrameHandle !== null) {
      cancelAnimationFrame(this.#animationFrameHandle);
      this.#animationFrameHandle = null;
    }
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      this.#windowErrors.push(message);
    };
    this.#rejectionHandler = (event) => {
      this.#unhandledRejections.push(String(event.reason));
    };
    addEventListener("error", this.#errorHandler);
    addEventListener("unhandledrejection", this.#rejectionHandler);
  }

  #releaseWindowErrors() {
    if (this.#errorHandler) {
      removeEventListener("error", this.#errorHandler);
      this.#errorHandler = undefined;
    }
    if (this.#rejectionHandler) {
      removeEventListener("unhandledrejection", this.#rejectionHandler);
      this.#rejectionHandler = undefined;
    }
  }

  #reportFatal(message) {
    this.#fatalErrors.push(String(message));
  }

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code)) {
      this.#reportFatal(`runtime exit is not an integer: ${String(code)}`);
      return;
    }
    if (this.#runtimeExitCode !== null) {
      this.#reportFatal(`runtime reported multiple exits: ${code}`);
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(report) {
    const exitCode = report?.exitCode;
    if (!Number.isSafeInteger(exitCode)) {
      this.#reportFatal("invalid bridge process-exit report");
      return;
    }
    if (this.#processExitCode !== null) {
      this.#reportFatal("bridge reported multiple process exits");
      return;
    }
    this.#processExitCode = exitCode;
  }

  #installBridge() {
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.#reportFatal(message);
      },
      reportProcessExit(report) {
        host.#reportProcessExit(report);
      },
    });
  }

  #markRuntimeInitialized() {
    if (this.#runtimeInitialized) {
      return;
    }
    this.#runtimeInitialized = true;
    this.#runtimeInitializedAt = performance.now();
    // The heartbeat proves that the host main thread remains responsive after
    // the Wasm runtime is available.  Do not charge module fetch/compile time
    // to this post-runtime measurement.
    this.#startHeartbeat();
  }

  async run(modulePath, timeoutMs) {
    const runStartedAt = performance.now();
    try {
      if (!crossOriginIsolated) {
        throw new Error("Chrome foundation host is not cross-origin isolated");
      }
      if (typeof SharedArrayBuffer !== "function") {
        throw new Error("SharedArrayBuffer is unavailable");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_FOUNDATION_TIMEOUT_MS) {
        throw new Error("Chrome foundation timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("Chrome foundation module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("Chrome foundation canvas did not accept focus");
      }

      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("Chrome foundation module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("Chrome foundation loader has no default factory export");
      }
      const module = await namespace.default({
        canvas: this.#canvas,
        noExitRuntime: false,
        mainScriptUrlOrBlob,
        locateFile: (path) => new URL(path, moduleUrl).href,
        print: (line) => this.#stdout.push(String(line)),
        printErr: (line) => this.#stderr.push(String(line)),
        onRuntimeInitialized: () => {
          this.#markRuntimeInitialized();
        },
        onAbort: (reason) => {
          this.#abort = String(reason);
          this.#reportFatal(`abort: ${this.#abort}`);
        },
        onExit: (code) => this.#reportRuntimeExit(code),
      });
      // The factory resolving is also a runtime-ready point for pinned
      // Emscripten. Preserve an explicit callback signal when it is available.
      this.#markRuntimeInitialized();
      module.chromiumWasmHostBridge = globalThis.__chromiumWasmHostBridgeV1;

      const deadline = runStartedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("Chrome foundation did not exit before timeout");
      }

      while (performance.now() - this.#runtimeInitializedAt <
             MIN_HEARTBEAT_ELAPSED_MS) {
        await delay(1);
      }
      const heartbeatElapsedMs = performance.now() - this.#runtimeInitializedAt;
      const timerEndTicks = this.#timerTicks;
      const animationFrameEndTicks = this.#animationFrameTicks;
      return {
        protocol: HOST_PROTOCOL,
        case: FOUNDATION_CASE,
        scope: FOUNDATION_SCOPE,
        status: "pass",
        m6GateComplete: false,
        runtimeExitCode: this.#runtimeExitCode,
        processExitCode: this.#processExitCode,
        runtimeInitialized: this.#runtimeInitialized,
        crossOriginIsolated,
        sharedArrayBuffer: typeof SharedArrayBuffer === "function",
        canvasFocused: document.activeElement === this.#canvas,
        foundationMarkerObserved: this.#stderr.some(
          (line) => line.includes(FOUNDATION_MARKER)),
        abort: this.#abort,
        fatalErrors: this.#fatalErrors,
        windowErrors: this.#windowErrors,
        unhandledRejections: this.#unhandledRejections,
        versions: this.#versions,
        heartbeat: {
          anchor: "runtime-initialized",
          elapsedMs: heartbeatElapsedMs,
          timerStartTicks: 0,
          timerEndTicks,
          timerDelta: timerEndTicks,
          animationFrameStartTicks: 0,
          animationFrameEndTicks,
          animationFrameDelta: animationFrameEndTicks,
          maxTimerGapMs: this.#maxTimerGapMs,
        },
        stdout: this.#stdout,
        stderr: this.#stderr,
        failedChecks: [],
        error: null,
      };
    } catch (error) {
      return {
        protocol: HOST_PROTOCOL,
        case: FOUNDATION_CASE,
        scope: FOUNDATION_SCOPE,
        status: "fail",
        m6GateComplete: false,
        runtimeExitCode: this.#runtimeExitCode,
        processExitCode: this.#processExitCode,
        runtimeInitialized: this.#runtimeInitialized,
        crossOriginIsolated,
        sharedArrayBuffer: typeof SharedArrayBuffer === "function",
        canvasFocused: document.activeElement === this.#canvas,
        foundationMarkerObserved: this.#stderr.some(
          (line) => line.includes(FOUNDATION_MARKER)),
        abort: this.#abort,
        fatalErrors: this.#fatalErrors,
        windowErrors: this.#windowErrors,
        unhandledRejections: this.#unhandledRejections,
        versions: this.#versions,
        heartbeat: null,
        stdout: this.#stdout,
        stderr: this.#stderr,
        failedChecks: [],
        error: String(error),
      };
    } finally {
      this.#stopHeartbeat();
      this.#releaseWindowErrors();
    }
  }
}

function validateFoundationResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.runtimeExitCode === FOUNDATION_EXIT_CODE,
          `unexpected runtime exit ${String(result.runtimeExitCode)}`);
  require(result.processExitCode === null ||
              result.processExitCode === FOUNDATION_EXIT_CODE,
          "bridge process exit disagrees with runtime exit");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocused === true, "canvas focus was lost");
  require(result.foundationMarkerObserved === true,
          "foundation lifecycle marker is absent");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
          "host recorded an unhandled rejection");
  const heartbeat = result.heartbeat;
  require(heartbeat && heartbeat.anchor === "runtime-initialized",
          "heartbeat anchor is invalid");
  require(Number.isFinite(heartbeat?.elapsedMs) &&
              heartbeat.elapsedMs >= MIN_HEARTBEAT_ELAPSED_MS,
          "heartbeat interval is too short");
  require(Number.isSafeInteger(heartbeat?.timerDelta) &&
              heartbeat.timerDelta >= MIN_HEARTBEAT_TICKS,
          "timer heartbeat did not advance");
  require(Number.isSafeInteger(heartbeat?.animationFrameDelta) &&
              heartbeat.animationFrameDelta >= MIN_HEARTBEAT_TICKS,
          "animation-frame heartbeat did not advance");
  require(Number.isFinite(heartbeat?.maxTimerGapMs) &&
              heartbeat.maxTimerGapMs <= MAX_TIMER_GAP_MS,
          "timer heartbeat gap exceeded the bound");
  result.failedChecks = failures;
  if (failures.length > 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmFoundationFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#chrome-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#chrome-status");
  renderVersions(document.querySelector("#versions"), versions);

  const host = new ChromiumWasmChromeHost(canvas, versions);
  const result = validateFoundationResult(await host.run(
    `/__m6__/artifacts/${moduleName}.js`, timeoutMs));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(`/__m6__/result/${encodeURIComponent(token)}`, {
    method: "POST",
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (!response.ok) {
    throw new Error(`result upload returned HTTP ${response.status}`);
  }
  return result;
}

export const chromeWasmFoundationContract = Object.freeze({
  FOUNDATION_CASE,
  FOUNDATION_EXIT_CODE,
  FOUNDATION_MARKER,
  FOUNDATION_SCOPE,
  HOST_PROTOCOL,
});

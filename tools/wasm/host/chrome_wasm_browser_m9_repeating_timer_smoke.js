// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This is a bounded outer-page witness for a native Browser UI-sequence
// RepeatingTimer. It does not claim long-run timer reliability, worker drain,
// memory-leak freedom, persistence, a visually non-empty Chrome shell, or a
// release-ready M9 gate.
const HOST_PROTOCOL = 1;
const CASE = "browser_repeating_timer_m9";
const SCOPE = "fixed-three-native-ui-repeating-timer-ticks-with-pre-shutdown-quiescence-and-post-shutdown-quiet-observation";
const SWITCH = "--wasm-browser-m9-repeating-timer-smoke";
const HOST_ROOT = "/__m9_repeating_timer__";
const PRODUCT_MODULE_NAME = "chrome_wasm";
const READY_MARKER = "CHROMIUM_WASM_M9_REPEATING_TIMER:READY ticks=3 interval_ms=50";
const TICK_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:TICK ordinal=";
const QUIESCENCE_DURATION_MS = 200;
const QUIESCENT_MARKER = "CHROMIUM_WASM_M9_REPEATING_TIMER:QUIESCENT ticks=3 duration_ms=200";
const PASS_MARKER = "CHROMIUM_WASM_M9_REPEATING_TIMER:PASS ticks=3";
const TIMEOUT_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:TIMEOUT";
const LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS";
const TIMER_MARKER_PREFIX = "CHROMIUM_WASM_M9_REPEATING_TIMER:";
const TICK_COUNT = 3;
const HEARTBEAT_INTERVAL_MS = 20;
const POST_EXIT_GRACE_MS = 100;
const MAX_TIMEOUT_MS = 120000;
const MAX_RECORD_HISTORY = 128;
const MAX_FRAME_DIMENSION = 16384;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) {
    records.shift();
  }
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} must be a nonempty string`);
  }
  return value;
}

function asReport(value, description) {
  let report = value;
  if (typeof report === "string") {
    try {
      report = JSON.parse(report);
    } catch (error) {
      throw new Error(`${description} is not valid JSON: ${String(error)}`);
    }
  }
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    throw new Error(`${description} must be an object`);
  }
  return report;
}

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error(`invalid repeating-timer versions: ${String(error)}`);
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

function isFrameReport(value) {
  return value && typeof value === "object" &&
      Number.isSafeInteger(value.id) && value.id >= 1 &&
      Number.isSafeInteger(value.width) && value.width >= 1 &&
      value.width <= MAX_FRAME_DIMENSION &&
      Number.isSafeInteger(value.height) && value.height >= 1 &&
      value.height <= MAX_FRAME_DIMENSION &&
      Number.isFinite(value.timestampMs) && value.timestampMs >= 0;
}

function isReadinessReport(value) {
  return value && typeof value === "object" &&
      typeof value.shellReady === "boolean" &&
      typeof value.surfaceReady === "boolean" &&
      typeof value.firstVisuallyNonEmptyPaint === "boolean";
}

function isFocusReport(value) {
  return value && typeof value === "object" &&
      typeof value.active === "boolean" &&
      typeof value.keyboardTargetPresent === "boolean";
}

function countExact(records, marker) {
  return records.filter((record) => record === marker).length;
}

function countTimerMarkers(records) {
  return records.filter((record) => record.startsWith(TIMER_MARKER_PREFIX)).length;
}

function eventLoopSnapshot(heartbeatCount, animationFrameCount) {
  return Object.freeze({heartbeatCount, animationFrameCount});
}

function validateResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };

  require(result.runtimeExitCode === 0, "runtime did not close normally");
  require(result.processExitCode === 0, "process did not report normal close");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.factorySettled === true, "module factory did not settle");
  require(result.factoryRejected === false, "module factory rejected");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
      "host recorded an unhandled rejection");
  require(result.readyObserved === true, "native timer smoke was not ready");
  require(result.quiescentObserved === true,
      "native timer smoke did not reach its pre-shutdown quiescence window");
  require(result.passObserved === true, "native timer smoke did not pass");
  require(result.lifecyclePassObserved === true,
      "Browser lifecycle did not close after timer smoke");
  require(result.ozoneFocusObserved === true,
      "host did not observe active Ozone keyboard focus");
  require(Array.isArray(result.frameReports) && result.frameReports.length >= 1,
      "host did not record a compositor frame");
  require(result.readiness?.surfaceReady === true,
      "host did not observe a ready canvas surface");
  require(result.responsivenessAtPass?.heartbeatCount >= 2,
      "host interval did not advance before native timer pass");
  require(result.responsivenessAtPass?.animationFrameCount >= 1,
      "host animation frame did not advance before native timer pass");
  require(result.responsivenessAtQuiescent?.heartbeatCount >= 2,
      "host interval did not advance before native timer quiescence");
  require(result.responsivenessAtQuiescent?.animationFrameCount >= 1,
      "host animation frame did not advance before native timer quiescence");
  require(result.postExitObservation?.timerMarkersQuiet === true,
      "native timer output changed after runtime exit");
  require(result.postExitObservation?.framesQuiet === true,
      "compositor frames changed during the post-exit grace");
  require(result.postExitObservation?.errorsQuiet === true,
      "host errors changed during the post-exit grace");
  require(result.postExitObservation?.heartbeatAdvanced === true,
      "host interval did not advance during the post-exit grace");
  require(result.postExitObservation?.animationFrameAdvanced === true,
      "host animation frame did not advance during the post-exit grace");

  const stderr = result.stderr;
  require(Array.isArray(stderr), "native stderr is not a list");
  if (Array.isArray(stderr)) {
    require(countExact(stderr, READY_MARKER) === 1,
        "native READY marker is missing or duplicated");
    require(countExact(stderr, PASS_MARKER) === 1,
        "native PASS marker is missing or duplicated");
    require(countExact(stderr, LIFECYCLE_PASS_MARKER) === 1,
        "Browser lifecycle PASS marker is missing or duplicated");
    require(stderr.every((line) => !line.startsWith(TIMEOUT_MARKER_PREFIX)),
        "native timer watchdog timed out");

    const timerLines = stderr.filter((line) =>
      line.startsWith(TIMER_MARKER_PREFIX));
    const expectedTimerLines = [
      READY_MARKER,
      `${TICK_MARKER_PREFIX}1`,
      `${TICK_MARKER_PREFIX}2`,
      `${TICK_MARKER_PREFIX}3`,
      QUIESCENT_MARKER,
      PASS_MARKER,
    ];
    require(JSON.stringify(timerLines) === JSON.stringify(expectedTimerLines),
        "native timer markers are malformed, duplicated, or out of order");
    const lifecycleIndex = stderr.indexOf(LIFECYCLE_PASS_MARKER);
    const passIndex = stderr.indexOf(PASS_MARKER);
    require(passIndex >= 0 && lifecycleIndex > passIndex,
        "Browser lifecycle did not drain after native timer pass");
  }

  const ticks = result.ticks;
  require(Array.isArray(ticks) && ticks.length === TICK_COUNT,
      "host did not observe exactly three native timer ticks");
  if (Array.isArray(ticks)) {
    require(ticks.every((tick, index) => tick?.ordinal === index + 1),
        "native timer tick ordinals are invalid");
    const lastTick = ticks.at(-1);
    require(result.responsivenessAtQuiescent?.heartbeatCount >
            lastTick?.heartbeatCount,
        "host interval did not advance during native timer quiescence");
    require(result.responsivenessAtQuiescent?.animationFrameCount >
            lastTick?.animationFrameCount,
        "host animation frame did not advance during native timer quiescence");
  }

  if (failures.length !== 0) {
    result.status = "fail";
    result.failedChecks = failures;
  }
  return result;
}

class ChromiumWasmBrowserM9RepeatingTimerSmokeHost {
  #canvas;
  #versions;
  #artifact;
  #captureHarness;
  #module = null;
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #runtimeInitialized = false;
  #runtimeExitCode = null;
  #processExitCode = null;
  #factorySettled = false;
  #factoryRejected = false;
  #abort = null;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #processExitResolver;
  #processExitPromise;
  #frameReports = [];
  #readiness = null;
  #readinessReports = [];
  #readyObserved = false;
  #quiescentObserved = false;
  #passObserved = false;
  #lifecyclePassObserved = false;
  #ozoneFocusObserved = false;
  #ticks = [];
  #responsivenessAtQuiescent = null;
  #responsivenessAtPass = null;
  #postExitObservation = null;
  #heartbeatHandle = null;
  #animationFrameHandle = null;
  #heartbeatCount = 0;
  #animationFrameCount = 0;
  #errorHandler;
  #rejectionHandler;

  constructor(canvas, versions, artifact, captureHarness) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("repeating-timer smoke requires a canvas");
    }
    if (!artifact || typeof artifact !== "object" || Array.isArray(artifact) ||
        !captureHarness || typeof captureHarness !== "object" ||
        Array.isArray(captureHarness)) {
      throw new Error("repeating-timer identity reports are invalid");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#artifact = Object.freeze({...artifact});
    this.#captureHarness = Object.freeze({...captureHarness});
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
    this.#processExitPromise = new Promise((resolve) => {
      this.#processExitResolver = resolve;
    });
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      appendBounded(this.#windowErrors, message);
      this.#recordFatal(`window error: ${message}`);
    };
    this.#rejectionHandler = (event) => {
      appendBounded(this.#unhandledRejections, String(event.reason));
    };
    window.addEventListener("error", this.#errorHandler);
    window.addEventListener("unhandledrejection", this.#rejectionHandler);
  }

  #releaseWindowErrors() {
    if (this.#errorHandler) {
      window.removeEventListener("error", this.#errorHandler);
      this.#errorHandler = undefined;
    }
    if (this.#rejectionHandler) {
      window.removeEventListener("unhandledrejection", this.#rejectionHandler);
      this.#rejectionHandler = undefined;
    }
  }

  #startEventLoopWitness() {
    if (this.#heartbeatHandle !== null || this.#animationFrameHandle !== null) {
      throw new Error("repeating-timer host event-loop witness started twice");
    }
    this.#heartbeatHandle = setInterval(() => {
      this.#heartbeatCount += 1;
    }, HEARTBEAT_INTERVAL_MS);
    const animate = () => {
      this.#animationFrameCount += 1;
      this.#animationFrameHandle = requestAnimationFrame(animate);
    };
    this.#animationFrameHandle = requestAnimationFrame(animate);
  }

  #stopEventLoopWitness() {
    if (this.#heartbeatHandle !== null) {
      clearInterval(this.#heartbeatHandle);
      this.#heartbeatHandle = null;
    }
    if (this.#animationFrameHandle !== null) {
      cancelAnimationFrame(this.#animationFrameHandle);
      this.#animationFrameHandle = null;
    }
  }

  #recordOutput(text) {
    if (text === READY_MARKER) {
      this.#readyObserved = true;
      return;
    }
    if (text.startsWith(TICK_MARKER_PREFIX)) {
      const ordinal = Number(text.slice(TICK_MARKER_PREFIX.length));
      appendBounded(this.#ticks, Object.freeze({
        ordinal,
        ...eventLoopSnapshot(this.#heartbeatCount, this.#animationFrameCount),
      }));
      return;
    }
    if (text === QUIESCENT_MARKER) {
      this.#quiescentObserved = true;
      this.#responsivenessAtQuiescent = eventLoopSnapshot(
          this.#heartbeatCount, this.#animationFrameCount);
      return;
    }
    if (text === PASS_MARKER) {
      this.#passObserved = true;
      this.#responsivenessAtPass = eventLoopSnapshot(
          this.#heartbeatCount, this.#animationFrameCount);
      return;
    }
    if (text === LIFECYCLE_PASS_MARKER) {
      this.#lifecyclePassObserved = true;
      return;
    }
    if (text.startsWith(TIMEOUT_MARKER_PREFIX)) {
      this.#recordFatal(`native timer watchdog output: ${text}`);
    }
  }

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code) || this.#runtimeExitCode !== null) {
      this.#recordFatal(`invalid runtime exit: ${String(code)}`);
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process-exit report");
      if (report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.exitCode) ||
          this.#processExitCode !== null) {
        throw new Error("process exit report is invalid or duplicated");
      }
      this.#processExitCode = report.exitCode;
      this.#processExitResolver(report.exitCode);
    } catch (error) {
      this.#recordFatal(`invalid process-exit report: ${String(error)}`);
    }
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL || !isFrameReport(report)) {
        throw new Error("frame metadata is invalid");
      }
      const previous = this.#frameReports.at(-1);
      if ((previous && report.id <= previous.id) ||
          this.#canvas.width !== report.width || this.#canvas.height !== report.height) {
        throw new Error("frame sequence or canvas dimensions are invalid");
      }
      appendBounded(this.#frameReports, {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      });
    } catch (error) {
      this.#recordFatal(`invalid frame report: ${String(error)}`);
    }
  }

  #reportReadiness(value) {
    try {
      const report = asReport(value, "readiness report");
      if (report.protocol !== HOST_PROTOCOL || !isReadinessReport(report)) {
        throw new Error("readiness metadata is invalid");
      }
      this.#readiness = Object.freeze({
        shellReady: report.shellReady,
        surfaceReady: report.surfaceReady,
        firstVisuallyNonEmptyPaint: report.firstVisuallyNonEmptyPaint,
      });
      appendBounded(this.#readinessReports, this.#readiness);
    } catch (error) {
      this.#recordFatal(`invalid readiness report: ${String(error)}`);
    }
  }

  #reportOzoneFocus(value) {
    try {
      const report = asReport(value, "Ozone focus report");
      if (report.protocol !== HOST_PROTOCOL || !isFocusReport(report)) {
        throw new Error("Ozone focus metadata is invalid");
      }
      this.#ozoneFocusObserved ||=
          report.active === true && report.keyboardTargetPresent === true;
    } catch (error) {
      this.#recordFatal(`invalid Ozone focus report: ${String(error)}`);
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("repeating-timer host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportOzoneFocusState(report) { host.#reportOzoneFocus(report); },
      reportOzoneCursor(report) {
        if (report?.protocol !== HOST_PROTOCOL ||
            (report.cursorType !== -1 && report.cursorType !== 0)) {
          return false;
        }
        host.#canvas.style.cursor = "default";
        return host.#canvas.style.cursor === "default";
      },
      reportOzoneTextInputState() {},
      reportOzoneTextInputDelivery() {},
      reportOzoneBrowserTextInputDelivery() {},
      reportOzoneBrowserClipboardPasteDelivery() {},
      requestOuterOriginStorageEstimate() { return false; },
      reportAccessibilitySnapshot() { return false; },
    });
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied an invalid Module object");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
  }

  #terminalCounts() {
    return Object.freeze({
      animationFrameCount: this.#animationFrameCount,
      fatalErrors: this.#fatalErrors.length,
      frameReports: this.#frameReports.length,
      heartbeatCount: this.#heartbeatCount,
      timerMarkers: countTimerMarkers(this.#stderr),
      unhandledRejections: this.#unhandledRejections.length,
      windowErrors: this.#windowErrors.length,
    });
  }

  async #observePostExitQuietness() {
    const before = this.#terminalCounts();
    await delay(POST_EXIT_GRACE_MS);
    const after = this.#terminalCounts();
    this.#postExitObservation = Object.freeze({
      after,
      before,
      graceMs: POST_EXIT_GRACE_MS,
      animationFrameAdvanced:
          after.animationFrameCount > before.animationFrameCount,
      errorsQuiet: after.fatalErrors === before.fatalErrors &&
          after.unhandledRejections === before.unhandledRejections &&
          after.windowErrors === before.windowErrors,
      framesQuiet: after.frameReports === before.frameReports,
      heartbeatAdvanced: after.heartbeatCount > before.heartbeatCount,
      timerMarkersQuiet: after.timerMarkers === before.timerMarkers,
    });
  }

  #result(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m9GateComplete: false,
      m9TimerSmokeOnly: true,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      factorySettled: this.#factorySettled,
      factoryRejected: this.#factoryRejected,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      readyObserved: this.#readyObserved,
      quiescentObserved: this.#quiescentObserved,
      passObserved: this.#passObserved,
      lifecyclePassObserved: this.#lifecyclePassObserved,
      ozoneFocusObserved: this.#ozoneFocusObserved,
      ticks: this.#ticks,
      responsivenessAtQuiescent: this.#responsivenessAtQuiescent,
      responsivenessAtPass: this.#responsivenessAtPass,
      postExitObservation: this.#postExitObservation,
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      artifact: this.#artifact,
      captureHarness: this.#captureHarness,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      stdout: this.#stdout,
      stderr: this.#stderr,
      failedChecks: [],
      error,
    };
  }

  async run(modulePath, timeoutMs) {
    const startedAt = performance.now();
    try {
      if (!crossOriginIsolated || typeof SharedArrayBuffer !== "function") {
        throw new Error("repeating-timer smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 2000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("repeating-timer timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("repeating-timer module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("repeating-timer canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      this.#startEventLoopWitness();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("repeating-timer module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("repeating-timer loader has no default factory export");
      }
      const host = this;
      Promise.resolve(namespace.default({
        arguments: [SWITCH],
        canvas: this.#canvas,
        noExitRuntime: false,
        mainScriptUrlOrBlob,
        locateFile: (path) => new URL(path, moduleUrl).href,
        print(line) {
          const text = String(line);
          appendBounded(host.#stdout, text);
          host.#recordOutput(text);
        },
        printErr(line) {
          const text = String(line);
          appendBounded(host.#stderr, text);
          host.#recordOutput(text);
        },
        onRuntimeInitialized() { host.#setModule(this); },
        onAbort(reason) {
          host.#abort = String(reason);
          host.#recordFatal(`abort: ${host.#abort}`);
        },
        onExit(code) { host.#reportRuntimeExit(Number(code)); },
      })).then(() => {
        host.#factorySettled = true;
      }).catch((error) => {
        host.#factorySettled = true;
        host.#factoryRejected = true;
        host.#recordFatal(`module factory rejected: ${String(error)}`);
      });

      const deadline = startedAt + timeoutMs;
      while ((this.#runtimeExitCode === null ||
              this.#processExitCode === null || !this.#factorySettled) &&
             performance.now() < deadline) {
        const waits = [delay(20)];
        if (this.#runtimeExitCode === null) {
          waits.push(this.#runtimeExitPromise);
        }
        if (this.#processExitCode === null) {
          waits.push(this.#processExitPromise);
        }
        await Promise.race(waits);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("repeating-timer smoke did not exit before timeout");
      }
      if (this.#processExitCode === null) {
        throw new Error("repeating-timer smoke did not report process exit before timeout");
      }
      if (!this.#factorySettled) {
        throw new Error("repeating-timer module factory did not settle before timeout");
      }
      await this.#observePostExitQuietness();
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#stopEventLoopWitness();
      this.#releaseWindowErrors();
    }
  }
}

export async function runChromeWasmBrowserM9RepeatingTimerSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  if (moduleName !== PRODUCT_MODULE_NAME) {
    throw new Error("repeating-timer smoke must select the chrome_wasm product module");
  }
  const timeoutMs = Number(query.get("timeoutMs"));
  const versions = parseVersions(query.get("versions"));
  const artifact = asReport(query.get("artifact"), "artifact identity");
  const captureHarness = asReport(
      query.get("captureHarness"), "capture-harness identity");
  const root = document.querySelector("#browser-m9-repeating-timer-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-m9-repeating-timer-status");
  const versionElement = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement) || !(versionElement instanceof HTMLElement)) {
    throw new Error("repeating-timer page is missing required elements");
  }
  renderVersions(versionElement, versions);
  const host = new ChromiumWasmBrowserM9RepeatingTimerSmokeHost(
      canvas, versions, artifact, captureHarness);
  const result = validateResult(await host.run(
      `${HOST_ROOT}/artifacts/${moduleName}.js`, timeoutMs));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(
      `${HOST_ROOT}/result/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error(`repeating-timer result POST returned HTTP ${response.status}`);
  }
  return result;
}

export const chromeWasmBrowserM9RepeatingTimerSmokeContract = Object.freeze({
  CASE,
  HEARTBEAT_INTERVAL_MS,
  HOST_PROTOCOL,
  POST_EXIT_GRACE_MS,
  PRODUCT_MODULE_NAME,
  QUIESCENCE_DURATION_MS,
  SCOPE,
  SWITCH,
  TICK_COUNT,
});

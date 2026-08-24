// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";
import {ChromiumWasmTrustedClipboardInput} from "./chrome_wasm_clipboard_input.js";
import {ChromiumWasmOuterOriginStorageEstimate} from "./chrome_wasm_storage_estimate.js";
import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";

// This is the ordinary, no-command-line-switch Chrome Wasm host lane.  It
// proves a bounded normal Browser lifecycle and clean host-driven shutdown;
// it is not the complete M6 browser-UI acceptance gate.
const HOST_PROTOCOL = 1;
const NORMAL_BROWSER_CASE = "chrome_normal_browser_m6";
const NORMAL_BROWSER_SCOPE = "ordinary-launch-visible-host-shutdown-reload";
const NORMAL_BROWSER_READY_MARKER = "CHROMIUM_WASM_M6_NORMAL_BROWSER:READY";
const NORMAL_BROWSER_PASS_MARKER = "CHROMIUM_WASM_M6_NORMAL_BROWSER:PASS";
const NORMAL_BROWSER_EXIT_CODE = 0;
const MIN_HEARTBEAT_ELAPSED_MS = 100;
const MIN_HEARTBEAT_TICKS = 2;
const MAX_TIMER_GAP_MS = 250;
const MAX_NORMAL_BROWSER_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_REPORT_HISTORY = 64;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} must be a nonempty string`);
  }
  return value;
}

function asPositiveInteger(value, description) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`${description} must be a positive integer`);
  }
  return value;
}

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error(`invalid normal-browser versions: ${String(error)}`);
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

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_REPORT_HISTORY) {
    records.shift();
  }
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
      typeof value.keyboardTargetPresent === "boolean" &&
      typeof value.active === "boolean";
}

function ozoneCursorDescriptor(cursorType) {
  // Only acknowledge a cursor after its CSS representation was installed.
  // The descriptor retains whether that representation is exact; the
  // Emscripten bridge uses that bit to reject an approximation as a C++
  // platform capability while allowing the host to expose a visual fallback.
  switch (cursorType) {
    case -1:  // kNull
    case 0:   // kPointer
      return {cssCursor: "default", exact: true};
    case 1:
      return {cssCursor: "crosshair", exact: true};
    case 2:
      return {cssCursor: "pointer", exact: true};
    case 3:
      return {cssCursor: "text", exact: true};
    case 4:
      return {cssCursor: "wait", exact: true};
    case 5:
      return {cssCursor: "help", exact: true};
    case 6:
      return {cssCursor: "e-resize", exact: true};
    case 7:
      return {cssCursor: "n-resize", exact: true};
    case 8:
      return {cssCursor: "ne-resize", exact: true};
    case 9:
      return {cssCursor: "nw-resize", exact: true};
    case 10:
      return {cssCursor: "s-resize", exact: true};
    case 11:
      return {cssCursor: "se-resize", exact: true};
    case 12:
      return {cssCursor: "sw-resize", exact: true};
    case 13:
      return {cssCursor: "w-resize", exact: true};
    case 14:
      return {cssCursor: "ns-resize", exact: true};
    case 15:
      return {cssCursor: "ew-resize", exact: true};
    case 16:
      return {cssCursor: "nesw-resize", exact: true};
    case 17:
      return {cssCursor: "nwse-resize", exact: true};
    case 18:
      return {cssCursor: "col-resize", exact: true};
    case 19:
      return {cssCursor: "row-resize", exact: true};
    case 20:
    case 21:
    case 22:
    case 23:
    case 24:
    case 25:
    case 26:
    case 27:
    case 28:
    case 43:
    case 44:
      return {cssCursor: "all-scroll", exact: false};
    case 29:
      return {cssCursor: "move", exact: true};
    case 30:
      return {cssCursor: "vertical-text", exact: true};
    case 31:
      return {cssCursor: "cell", exact: true};
    case 32:
      return {cssCursor: "context-menu", exact: true};
    case 33:
      return {cssCursor: "alias", exact: true};
    case 34:
      return {cssCursor: "progress", exact: true};
    case 35:
      return {cssCursor: "no-drop", exact: true};
    case 36:
      return {cssCursor: "copy", exact: true};
    case 37:
      return {cssCursor: "none", exact: true};
    case 38:
      return {cssCursor: "not-allowed", exact: true};
    case 39:
      return {cssCursor: "zoom-in", exact: true};
    case 40:
      return {cssCursor: "zoom-out", exact: true};
    case 41:
      return {cssCursor: "grab", exact: true};
    case 42:
      return {cssCursor: "grabbing", exact: true};
    case 45:
      return {cssCursor: "default", exact: false};
    case 46:
      return {cssCursor: "no-drop", exact: false};
    case 47:
      return {cssCursor: "move", exact: false};
    case 48:
      return {cssCursor: "copy", exact: false};
    case 49:
      return {cssCursor: "alias", exact: false};
    case 50:
    case 51:
    case 52:
    case 53:
      return {cssCursor: "not-allowed", exact: false};
    default:
      return null;
  }
}

function navigationType() {
  const navigation = performance.getEntriesByType("navigation").at(0);
  return typeof navigation?.type === "string" ? navigation.type : "unknown";
}

class ChromiumWasmNormalBrowserHost {
  #canvas;
  #textProxy;
  #versions;
  #restart;
  #module = null;
  #factorySettled = false;
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #runtimeInitialized = false;
  #runtimeInitializedAt = null;
  #runtimeExitCode = null;
  #processExitCode = null;
  #abort = null;
  #timerTicks = 0;
  #animationFrameTicks = 0;
  #timerHandle = null;
  #animationFrameHandle = null;
  #lastTimerTime = 0;
  #maxTimerGapMs = 0;
  #frameReports = [];
  #readinessReports = [];
  #readiness = null;
  #ozoneFocusReports = [];
  #ozoneCursorReports = [];
  #ozoneTextInputStates = [];
  #ozoneTextInputDeliveries = [];
  #ozoneBrowserTextInputDeliveries = [];
  #ozoneBrowserClipboardPasteDeliveries = [];
  #outerOriginStorageEstimateReports = [];
  #normalBrowserReadyMarkerObserved = false;
  #normalBrowserPassMarkerObserved = false;
  #shutdownResults = [];
  #visibleEvidenceAtShutdown = null;
  #pointerInput = null;
  #textInput = null;
  #clipboardInput = null;
  #storageEstimate = null;
  #errorHandler;
  #rejectionHandler;

  constructor(canvas, textProxy, versions, restart) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("normal-browser host requires a canvas");
    }
    if (!(textProxy instanceof HTMLTextAreaElement)) {
      throw new Error("normal-browser host requires a text proxy");
    }
    this.#canvas = canvas;
    this.#textProxy = textProxy;
    this.#versions = versions;
    this.#restart = restart;
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      appendBounded(this.#windowErrors, message);
    };
    this.#rejectionHandler = (event) => {
      appendBounded(this.#unhandledRejections, String(event.reason));
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

  #startHeartbeat() {
    if (this.#timerHandle !== null || this.#animationFrameHandle !== null) {
      return;
    }
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

  #heartbeatSnapshot() {
    if (this.#runtimeInitializedAt === null) {
      return null;
    }
    return {
      anchor: "runtime-initialized",
      elapsedMs: performance.now() - this.#runtimeInitializedAt,
      timerTicks: this.#timerTicks,
      animationFrameTicks: this.#animationFrameTicks,
      maxTimerGapMs: this.#maxTimerGapMs,
    };
  }

  #recordOutput(line) {
    if (line.includes(NORMAL_BROWSER_READY_MARKER)) {
      this.#normalBrowserReadyMarkerObserved = true;
    }
    if (line.includes(NORMAL_BROWSER_PASS_MARKER)) {
      this.#normalBrowserPassMarkerObserved = true;
    }
  }

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code)) {
      this.#recordFatal(`runtime exit is not an integer: ${String(code)}`);
      return;
    }
    if (this.#runtimeExitCode !== null) {
      this.#recordFatal(`runtime reported multiple exits: ${code}`);
      return;
    }
    this.#runtimeExitCode = code;
    // A delayed navigator.storage.estimate() completion has no authority
    // after Emscripten's runtime exits. Make it inert before the clean-exit
    // observer's deliberate post-exit delay.
    this.#storageEstimate?.dispose();
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process-exit report");
      if (!Number.isSafeInteger(report.exitCode)) {
        throw new Error("exitCode is not an integer");
      }
      if (this.#processExitCode !== null) {
        throw new Error("bridge reported multiple process exits");
      }
      this.#processExitCode = report.exitCode;
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
      if (previous && report.id <= previous.id) {
        throw new Error("frame IDs must increase monotonically");
      }
      // chromium_wasm_present_frame copies into the host canvas before the
      // bridge callback.  The backing-store check rejects metadata-only
      // presentation claims.
      if (this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
        throw new Error("canvas backing dimensions differ from frame metadata");
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
      this.#readiness = {
        shellReady: report.shellReady,
        surfaceReady: report.surfaceReady,
        firstVisuallyNonEmptyPaint: report.firstVisuallyNonEmptyPaint,
      };
      appendBounded(this.#readinessReports, this.#readiness);
    } catch (error) {
      this.#recordFatal(`invalid readiness report: ${String(error)}`);
    }
  }

  #reportOzoneFocusState(value) {
    try {
      const report = asReport(value, "Ozone focus-state report");
      if (report.protocol !== HOST_PROTOCOL || !isFocusReport(report)) {
        throw new Error("Ozone focus-state metadata is invalid");
      }
      appendBounded(this.#ozoneFocusReports, {
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      });
    } catch (error) {
      this.#recordFatal(`invalid Ozone focus-state report: ${String(error)}`);
    }
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType)) {
        throw new Error("Ozone cursor metadata is invalid");
      }
      const descriptor = ozoneCursorDescriptor(report.cursorType);
      if (!descriptor) {
        throw new Error("Ozone cursor type has no exact web representation");
      }
      this.#canvas.style.cursor = descriptor.cssCursor;
      if (this.#canvas.style.cursor !== descriptor.cssCursor) {
        throw new Error("host canvas rejected the Ozone cursor style");
      }
      appendBounded(this.#ozoneCursorReports, {
        cursorType: report.cursorType,
        cssCursor: descriptor.cssCursor,
        exact: descriptor.exact,
      });
      // The Emscripten bridge applies the stricter exactness policy after the
      // host has installed this CSS representation. Returning true here
      // therefore acknowledges only the recorded host presentation, never an
      // unsupported cursor as an exact C++ platform capability.
      return true;
    } catch (error) {
      this.#recordFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  #reportOzoneTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state report");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.focusedClientPresent !== "boolean" ||
          typeof report.editable !== "boolean" ||
          typeof report.canComposeInline !== "boolean" ||
          (report.editable && !report.focusedClientPresent) ||
          (report.canComposeInline && !report.editable)) {
        throw new Error("Ozone text-input state metadata is invalid");
      }
      appendBounded(this.#ozoneTextInputStates, {
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      });
      this.#textInput?.handleOzoneTextInputState(report);
      this.#clipboardInput?.handleOzoneTextInputState(report);
    } catch (error) {
      this.#recordFatal(`invalid Ozone text-input state report: ${String(error)}`);
    }
  }

  #reportOzoneTextInputDelivery(value) {
    try {
      const report = asReport(value, "Ozone text-input delivery report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.action) || report.action < 1 ||
          report.action > 3 || !Number.isSafeInteger(report.sessionId) ||
          report.sessionId < 1 || !Number.isSafeInteger(report.sequence) ||
          report.sequence < 1 || typeof report.accepted !== "boolean") {
        throw new Error("Ozone text-input delivery metadata is invalid");
      }
      appendBounded(this.#ozoneTextInputDeliveries, {
        action: report.action,
        sessionId: report.sessionId,
        sequence: report.sequence,
        accepted: report.accepted,
      });
    } catch (error) {
      this.#recordFatal(
          `invalid Ozone text-input delivery report: ${String(error)}`);
    }
  }

  #reportOzoneBrowserTextInputDelivery(value) {
    try {
      const report = asReport(value, "browser text-input delivery report");
      if (report.protocol !== HOST_PROTOCOL || report.action !== 4 ||
          report.sessionId !== 0 || !Number.isSafeInteger(report.sequence) ||
          report.sequence < 1 || typeof report.accepted !== "boolean") {
        throw new Error("browser text-input delivery metadata is invalid");
      }
      appendBounded(this.#ozoneBrowserTextInputDeliveries, {
        action: report.action,
        sessionId: report.sessionId,
        sequence: report.sequence,
        accepted: report.accepted,
      });
      this.#textInput?.handleOzoneBrowserTextInputDelivery(report);
    } catch (error) {
      this.#recordFatal(
          `invalid browser text-input delivery report: ${String(error)}`);
    }
  }

  #reportOzoneBrowserClipboardPasteDelivery(value) {
    try {
      const report = asReport(value, "browser clipboard-paste delivery report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.requestId) || report.requestId < 1 ||
          typeof report.accepted !== "boolean") {
        throw new Error("browser clipboard-paste delivery metadata is invalid");
      }
      appendBounded(this.#ozoneBrowserClipboardPasteDeliveries, {
        requestId: report.requestId,
        accepted: report.accepted,
      });
      this.#clipboardInput?.handleOzoneBrowserClipboardPasteDelivery(report);
    } catch (error) {
      this.#recordFatal(
          `invalid browser clipboard-paste delivery report: ${String(error)}`);
    }
  }

  #reportOuterOriginStorageEstimate(value) {
    try {
      const report = asReport(value, "outer-origin storage-estimate report");
      if (!Number.isSafeInteger(report.generation) || report.generation < 1 ||
          report.generation > 0x7fffffff ||
          !["available", "unavailable", "error"].includes(report.status) ||
          typeof report.delivered !== "boolean") {
        throw new Error("outer-origin storage-estimate metadata is invalid");
      }
      appendBounded(this.#outerOriginStorageEstimateReports, {
        generation: report.generation,
        status: report.status,
        delivered: report.delivered,
      });
    } catch (error) {
      this.#recordFatal(
          `invalid outer-origin storage-estimate report: ${String(error)}`);
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("normal-browser host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.#recordFatal(message);
      },
      reportProcessExit(report) {
        host.#reportProcessExit(report);
      },
      reportFrame(report) {
        host.#reportFrame(report);
      },
      reportReadiness(report) {
        host.#reportReadiness(report);
      },
      reportOzoneFocusState(report) {
        host.#reportOzoneFocusState(report);
      },
      reportOzoneCursor(report) {
        return host.#reportOzoneCursor(report);
      },
      reportOzoneTextInputState(report) {
        host.#reportOzoneTextInputState(report);
      },
      reportOzoneTextInputDelivery(report) {
        host.#reportOzoneTextInputDelivery(report);
      },
      reportOzoneBrowserTextInputDelivery(report) {
        host.#reportOzoneBrowserTextInputDelivery(report);
      },
      reportOzoneBrowserClipboardPasteDelivery(report) {
        host.#reportOzoneBrowserClipboardPasteDelivery(report);
      },
      requestOuterOriginStorageEstimate(report) {
        return host.#storageEstimate?.request(report) === true;
      },
    });
  }

  #setModule(module) {
    if (!module || typeof module !== "object") {
      this.#recordFatal("onRuntimeInitialized did not supply a Module object");
      return;
    }
    if (this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied multiple Module objects");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#runtimeInitializedAt = performance.now();
    this.#pointerInput = new ChromiumWasmTrustedPointerInput(this.#canvas, {
      getModule: () => this.#module,
      recordFatal: (message) => this.#recordFatal(message),
      maximumFrameDimension: MAX_FRAME_DIMENSION,
    });
    this.#pointerInput.attach();
    this.#textInput = new ChromiumWasmTrustedTextInput(
        this.#canvas, this.#textProxy, {
          getModule: () => this.#module,
          reportFatal: (message) => this.#recordFatal(message),
        });
    this.#textInput.attach();
    this.#clipboardInput = new ChromiumWasmTrustedClipboardInput(
        this.#textProxy, {
          getModule: () => this.#module,
          reportFatal: (message) => this.#recordFatal(message),
        });
    this.#clipboardInput.attach();
    this.#storageEstimate = new ChromiumWasmOuterOriginStorageEstimate({
      getModule: () => this.#module,
      recordFatal: (message) => this.#recordFatal(message),
      onResult: (report) => this.#reportOuterOriginStorageEstimate(report),
    });
    const latest_text_state = this.#ozoneTextInputStates.at(-1);
    if (latest_text_state) {
      this.#textInput.handleOzoneTextInputState(latest_text_state);
      this.#clipboardInput.handleOzoneTextInputState(latest_text_state);
    }
    this.#startHeartbeat();
  }

  #hasActiveOzoneFocus() {
    return this.#ozoneFocusReports.some((report) =>
      report.keyboardTargetPresent === true && report.active === true);
  }

  #visibleEvidence() {
    const heartbeat = this.#heartbeatSnapshot();
    if (!heartbeat) {
      return null;
    }
    const visible = this.#normalBrowserReadyMarkerObserved &&
        this.#frameReports.length >= 1 &&
        this.#readiness?.shellReady === true &&
        this.#readiness?.surfaceReady === true &&
        this.#readiness?.firstVisuallyNonEmptyPaint === false &&
        this.#hasActiveOzoneFocus() &&
        document.activeElement === this.#canvas &&
        heartbeat.elapsedMs >= MIN_HEARTBEAT_ELAPSED_MS &&
        heartbeat.timerTicks >= MIN_HEARTBEAT_TICKS &&
        heartbeat.animationFrameTicks >= MIN_HEARTBEAT_TICKS &&
        heartbeat.maxTimerGapMs <= MAX_TIMER_GAP_MS;
    if (!visible) {
      return null;
    }
    return {
      frameCount: this.#frameReports.length,
      shellReady: this.#readiness.shellReady,
      surfaceReady: this.#readiness.surfaceReady,
      firstVisuallyNonEmptyPaint: this.#readiness.firstVisuallyNonEmptyPaint,
      activeOzoneFocus: true,
      canvasFocused: true,
      heartbeat,
    };
  }

  async #waitForVisibleBrowser(deadline) {
    while (performance.now() < deadline) {
      if (this.#runtimeExitCode !== null) {
        throw new Error("normal browser exited before visible readiness");
      }
      if (this.#abort !== null || this.#fatalErrors.length !== 0) {
        throw new Error("normal browser recorded an error before visible readiness");
      }
      const evidence = this.#visibleEvidence();
      if (evidence) {
        return evidence;
      }
      await delay(10);
    }
    throw new Error("normal browser did not become visibly ready before timeout");
  }

  #requestHostShutdown(evidence) {
    if (!this.#module || typeof this.#module.ccall !== "function") {
      throw new Error("normal browser Module has no ccall shutdown ABI");
    }
    if (this.#shutdownResults.length !== 0) {
      throw new Error("normal browser host shutdown was already requested");
    }
    this.#visibleEvidenceAtShutdown = evidence;
    this.#pointerInput?.releaseActivePointer("host-shutdown");
    this.#textInput?.releaseActiveInput("host-shutdown");
    let first;
    let second;
    try {
      first = this.#module.ccall(
          "chromium_wasm_browser_host_request_shutdown", "number", [], []);
      second = this.#module.ccall(
          "chromium_wasm_browser_host_request_shutdown", "number", [], []);
    } catch (error) {
      throw new Error(`normal browser host shutdown ABI failed: ${String(error)}`);
    }
    this.#shutdownResults = [first, second];
    if (first !== 1 || second !== 0) {
      throw new Error(
          "normal browser host shutdown ABI did not return the required [1, 0]");
    }
  }

  async #waitForCleanExit(deadline) {
    while (performance.now() < deadline) {
      if (this.#abort !== null || this.#fatalErrors.length !== 0) {
        throw new Error("normal browser recorded an error during shutdown");
      }
      if (this.#runtimeExitCode !== null &&
          this.#normalBrowserPassMarkerObserved) {
        return;
      }
      await delay(10);
    }
    if (this.#runtimeExitCode === null) {
      throw new Error("normal browser did not exit after host shutdown");
    }
    throw new Error("normal browser exited without its physical-close marker");
  }

  #result(status, error) {
    const heartbeat = this.#heartbeatSnapshot();
    return {
      protocol: HOST_PROTOCOL,
      case: NORMAL_BROWSER_CASE,
      scope: NORMAL_BROWSER_SCOPE,
      status,
      m6GateComplete: false,
      attempt: this.#restart.attempt,
      restart: {
        attempts: this.#restart.attempts,
        navigationType: this.#restart.navigationType,
        reloadScheduled: status === "pass" &&
            this.#restart.attempt < this.#restart.attempts,
      },
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      factorySettled: this.#factorySettled,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === this.#canvas,
      normalBrowserReadyMarkerObserved: this.#normalBrowserReadyMarkerObserved,
      normalBrowserPassMarkerObserved: this.#normalBrowserPassMarkerObserved,
      hostShutdown: {
        moduleCapturedOnRuntimeInitialized: this.#module !== null,
        requestedAfterVisibleEvidence: this.#visibleEvidenceAtShutdown !== null,
        results: this.#shutdownResults,
        visibleEvidence: this.#visibleEvidenceAtShutdown,
      },
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      ozoneFocusReports: this.#ozoneFocusReports,
      ozoneCursorReports: this.#ozoneCursorReports,
      ozoneTextInputStates: this.#ozoneTextInputStates,
      ozoneTextInputDeliveries: this.#ozoneTextInputDeliveries,
      ozoneBrowserTextInputDeliveries: this.#ozoneBrowserTextInputDeliveries,
      ozoneBrowserClipboardPasteDeliveries:
          this.#ozoneBrowserClipboardPasteDeliveries,
      outerOriginStorageEstimateReports: this.#outerOriginStorageEstimateReports,
      trustedTextInput: this.#textInput?.snapshot() || null,
      trustedClipboardInput: this.#clipboardInput?.snapshot() || null,
      canvasBackingStore: {
        width: this.#canvas.width,
        height: this.#canvas.height,
      },
      heartbeat,
      stdout: this.#stdout,
      stderr: this.#stderr,
      failedChecks: [],
      error,
    };
  }

  async run(modulePath, timeoutMs) {
    const startedAt = performance.now();
    try {
      if (!crossOriginIsolated) {
        throw new Error("normal-browser host is not cross-origin isolated");
      }
      if (typeof SharedArrayBuffer !== "function") {
        throw new Error("SharedArrayBuffer is unavailable");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_NORMAL_BROWSER_TIMEOUT_MS) {
        throw new Error("normal-browser timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("normal-browser module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("normal-browser canvas did not accept focus");
      }

      // This must happen before importing the loader because Ozone can report
      // the first canvas frame synchronously from Chromium's application
      // pthread. Capture Module in onRuntimeInitialized and do not treat the
      // generated factory promise as browser-visible readiness: its resolution
      // is a loader milestone, not evidence that Browser/View startup ran.
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("normal-browser module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("normal-browser loader has no default factory export");
      }
      const host = this;
      const moduleOptions = {
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
        onRuntimeInitialized() {
          host.#setModule(this);
        },
        onAbort(reason) {
          host.#abort = String(reason);
          host.#recordFatal(`abort: ${host.#abort}`);
        },
        onExit(code) {
          host.#reportRuntimeExit(Number(code));
        },
      };
      Promise.resolve(namespace.default(moduleOptions)).then(
          () => {
            host.#factorySettled = true;
          },
          (error) => {
            host.#factorySettled = true;
            host.#recordFatal(`module factory rejected: ${String(error)}`);
          });

      const deadline = startedAt + timeoutMs;
      const visibleEvidence = await this.#waitForVisibleBrowser(deadline);
      this.#requestHostShutdown(visibleEvidence);
      await this.#waitForCleanExit(deadline);
      // Let browser-main event delivery expose a trailing host error before a
      // clean result is accepted, without treating factory settlement as the
      // normal readiness mechanism.
      await delay(25);
      if (this.#abort !== null || this.#fatalErrors.length !== 0) {
        throw new Error("normal browser recorded an error after clean exit");
      }
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#pointerInput?.detach();
      this.#pointerInput = null;
      this.#textInput?.detach();
      this.#textInput = null;
      this.#clipboardInput?.detach();
      this.#clipboardInput = null;
      this.#storageEstimate?.dispose();
      this.#storageEstimate = null;
      this.#stopHeartbeat();
      this.#releaseWindowErrors();
    }
  }
}

function validateNormalBrowserResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.m6GateComplete === false,
      "normal-browser lifecycle claims M6 complete");
  require(result.runtimeExitCode === NORMAL_BROWSER_EXIT_CODE,
      `unexpected runtime exit ${String(result.runtimeExitCode)}`);
  require(result.processExitCode === null ||
              result.processExitCode === NORMAL_BROWSER_EXIT_CODE,
          "bridge process exit disagrees with runtime exit");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocused === true, "canvas focus was lost");
  require(result.normalBrowserReadyMarkerObserved === true,
      "normal-browser ready marker is absent");
  require(result.normalBrowserPassMarkerObserved === true,
      "normal-browser physical-close marker is absent");
  require(result.abort === null, "runtime aborted");
  require(Array.isArray(result.fatalErrors) && result.fatalErrors.length === 0,
      "host recorded a fatal error");
  require(Array.isArray(result.windowErrors) && result.windowErrors.length === 0,
      "host recorded a window error");
  require(Array.isArray(result.unhandledRejections) &&
              result.unhandledRejections.length === 0,
          "host recorded an unhandled rejection");

  const frames = result.frameReports;
  require(Array.isArray(frames) && frames.length >= 1,
      "no host-canvas frame was reported");
  let previousFrameId = 0;
  if (Array.isArray(frames)) {
    for (const frame of frames) {
      require(isFrameReport(frame), "frame metadata is invalid");
      require(frame?.id > previousFrameId, "frame IDs are not monotonic");
      previousFrameId = frame?.id || previousFrameId;
    }
  }
  require(isReadinessReport(result.readiness), "readiness metadata is invalid");
  require(result.readiness?.shellReady === true,
      "shell readiness was not reported");
  require(result.readiness?.surfaceReady === true,
      "surface readiness was not reported");
  require(result.readiness?.firstVisuallyNonEmptyPaint === false,
      "blank normal browser reported a visually non-empty paint");
  require(Array.isArray(result.readinessReports) &&
              result.readinessReports.some((report) =>
                isReadinessReport(report) && report.shellReady === true),
          "shell readiness was never reported");
  require(Array.isArray(result.readinessReports) &&
              result.readinessReports.some((report) =>
                isReadinessReport(report) && report.surfaceReady === true),
          "surface readiness was never reported");
  require(Array.isArray(result.readinessReports) &&
              result.readinessReports.every((report) =>
                isReadinessReport(report) &&
                report.firstVisuallyNonEmptyPaint === false),
          "blank normal browser readiness history reported a visually non-empty paint");
  require(Array.isArray(result.ozoneFocusReports) &&
              result.ozoneFocusReports.some((report) =>
                isFocusReport(report) && report.keyboardTargetPresent === true &&
                report.active === true),
          "no active Ozone keyboard target was observed");

  const shutdown = result.hostShutdown;
  require(shutdown && shutdown.moduleCapturedOnRuntimeInitialized === true,
      "Module was not captured in onRuntimeInitialized");
  require(shutdown?.requestedAfterVisibleEvidence === true,
      "host shutdown was not gated on visible browser evidence");
  require(Array.isArray(shutdown?.results) &&
              shutdown.results.length === 2 && shutdown.results[0] === 1 &&
              shutdown.results[1] === 0,
          "host shutdown ABI did not return exactly [1, 0]");
  const visibleEvidence = shutdown?.visibleEvidence;
  require(visibleEvidence && visibleEvidence.frameCount >= 1 &&
              visibleEvidence.shellReady === true &&
              visibleEvidence.surfaceReady === true &&
              visibleEvidence.firstVisuallyNonEmptyPaint === false &&
              visibleEvidence.activeOzoneFocus === true &&
              visibleEvidence.canvasFocused === true,
          "host shutdown lacks visible browser evidence");

  const heartbeat = result.heartbeat;
  require(heartbeat?.anchor === "runtime-initialized",
      "heartbeat anchor is invalid");
  require(Number.isFinite(heartbeat?.elapsedMs) &&
              heartbeat.elapsedMs >= MIN_HEARTBEAT_ELAPSED_MS,
          "heartbeat interval is too short");
  require(Number.isSafeInteger(heartbeat?.timerTicks) &&
              heartbeat.timerTicks >= MIN_HEARTBEAT_TICKS,
          "timer heartbeat did not advance");
  require(Number.isSafeInteger(heartbeat?.animationFrameTicks) &&
              heartbeat.animationFrameTicks >= MIN_HEARTBEAT_TICKS,
          "animation-frame heartbeat did not advance");
  require(Number.isFinite(heartbeat?.maxTimerGapMs) &&
              heartbeat.maxTimerGapMs <= MAX_TIMER_GAP_MS,
          "timer heartbeat gap exceeded the bound");

  require(Number.isSafeInteger(result.attempt) && result.attempt >= 1,
      "restart attempt is invalid");
  const restart = result.restart;
  require(restart && Number.isSafeInteger(restart.attempts) &&
              restart.attempts >= 2 && result.attempt <= restart.attempts,
          "restart attempt count is invalid");
  require(typeof restart?.navigationType === "string" &&
              restart.navigationType.length > 0,
          "restart navigation type is missing");
  require(restart?.reloadScheduled === (result.attempt < restart?.attempts),
      "restart scheduling does not match the attempt");

  result.failedChecks = failures;
  if (failures.length > 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

function restartStorageKey(token) {
  return `chromium-wasm-normal-browser-restart:${token}`;
}

function nextRestartAttempt(token, attempts) {
  const key = restartStorageKey(token);
  const value = sessionStorage.getItem(key);
  const previousAttempt = value === null ? 0 : Number(value);
  if (!Number.isSafeInteger(previousAttempt) || previousAttempt < 0 ||
      previousAttempt >= attempts) {
    throw new Error("normal-browser restart state is invalid");
  }
  return {attempt: previousAttempt + 1, key};
}

export async function runChromeWasmNormalBrowserFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const restartAttempts = asPositiveInteger(
      Number(query.get("restartAttempts") || "2"), "restart attempt count");
  if (restartAttempts < 2) {
    throw new Error("normal-browser lane requires at least one page reload");
  }
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#chrome-root");
  const canvas = document.querySelector("#browser-canvas");
  const textProxy = document.querySelector("#browser-text-proxy");
  const status = document.querySelector("#chrome-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(textProxy instanceof HTMLTextAreaElement) || !(status instanceof HTMLElement)) {
    throw new Error("normal-browser page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const {attempt, key} = nextRestartAttempt(token, restartAttempts);
  const host = new ChromiumWasmNormalBrowserHost(canvas, textProxy, versions, {
    attempt,
    attempts: restartAttempts,
    navigationType: navigationType(),
  });
  const result = validateNormalBrowserResult(await host.run(
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
  if (result.status === "pass" && attempt < restartAttempts) {
    sessionStorage.setItem(key, String(attempt));
    // Reloading, rather than constructing a second Module in this page,
    // proves the host can discard one completed browser process and create a
    // fresh one from a clean outer-page lifetime.
    location.reload();
  } else if (attempt === restartAttempts) {
    sessionStorage.removeItem(key);
  }
  return result;
}

export const chromeWasmNormalBrowserContract = Object.freeze({
  HOST_PROTOCOL,
  NORMAL_BROWSER_CASE,
  NORMAL_BROWSER_EXIT_CODE,
  NORMAL_BROWSER_PASS_MARKER,
  NORMAL_BROWSER_READY_MARKER,
  NORMAL_BROWSER_SCOPE,
});

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This lane proves the product trusted-DOM pointer adapter, not a bespoke test
// listener. The outer browser supplies physical mouse input; this host merely
// observes the shared adapter's accepted records and asks a C++ verifier to
// inspect the resulting real tab model and presentation ordering.

import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";

const HOST_PROTOCOL = 1;
const CASE = "browser_host_pointer_tabs_m6";
const SCOPE = "trusted-dom-pointer-ozone-aura-views-tab-flow";
const SWITCH = "--wasm-browser-host-pointer-tab-smoke";
const READY_MARKER = "CHROMIUM_WASM_M6_HOST_POINTER_TABS:READY";
const INSERTED_MARKER = "CHROMIUM_WASM_M6_HOST_POINTER_TABS:INSERTED";
const CLOSED_MARKER = "CHROMIUM_WASM_M6_HOST_POINTER_TABS:CLOSED";
const PASS_MARKER = "CHROMIUM_WASM_M6_HOST_POINTER_TABS:PASS";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 64;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
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
    throw new Error(`invalid host-pointer-tab versions: ${String(error)}`);
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("host-pointer-tab page is missing its version element");
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

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) {
    records.shift();
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
      typeof value.keyboardTargetPresent === "boolean" &&
      typeof value.active === "boolean";
}

function ozoneCursorDescriptor(cursorType) {
  const exact = new Map([
    [-1, "default"], [0, "default"], [1, "crosshair"], [2, "pointer"],
    [3, "text"], [4, "wait"], [5, "help"], [6, "e-resize"],
    [7, "n-resize"], [8, "ne-resize"], [9, "nw-resize"],
    [10, "s-resize"], [11, "se-resize"], [12, "sw-resize"],
    [13, "w-resize"], [14, "ns-resize"], [15, "ew-resize"],
    [16, "nesw-resize"], [17, "nwse-resize"], [18, "col-resize"],
    [19, "row-resize"], [29, "move"], [30, "vertical-text"],
    [31, "cell"], [32, "context-menu"], [33, "alias"],
    [34, "progress"], [35, "no-drop"], [36, "copy"], [37, "none"],
    [38, "not-allowed"], [39, "zoom-in"], [40, "zoom-out"],
    [41, "grab"], [42, "grabbing"],
  ]);
  if (exact.has(cursorType)) {
    return {cssCursor: exact.get(cursorType), exact: true};
  }
  if ([20, 21, 22, 23, 24, 25, 26, 27, 28, 43, 44].includes(cursorType)) {
    return {cssCursor: "all-scroll", exact: false};
  }
  if (cursorType === 45) {
    return {cssCursor: "default", exact: false};
  }
  if (cursorType === 46) {
    return {cssCursor: "no-drop", exact: false};
  }
  if (cursorType === 47) {
    return {cssCursor: "move", exact: false};
  }
  if (cursorType === 48) {
    return {cssCursor: "copy", exact: false};
  }
  if (cursorType === 49) {
    return {cssCursor: "alias", exact: false};
  }
  if ([50, 51, 52, 53].includes(cursorType)) {
    return {cssCursor: "not-allowed", exact: false};
  }
  return null;
}

function parseTargetMarker(line, marker) {
  const match = new RegExp(`${marker} x=(\\d+) y=(\\d+)`).exec(line);
  if (!match) {
    return null;
  }
  const x = Number(match[1]);
  const y = Number(match[2]);
  if (!Number.isSafeInteger(x) || !Number.isSafeInteger(y) || x < 0 || y < 0 ||
      x >= MAX_FRAME_DIMENSION || y >= MAX_FRAME_DIMENSION) {
    throw new Error(`invalid pointer target in ${marker}`);
  }
  return {x, y};
}

class ChromiumWasmBrowserHostPointerTabsSmokeHost {
  #canvas;
  #versions;
  #module = null;
  #pointerInput = null;
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #runtimeInitialized = false;
  #runtimeExitCode = null;
  #processExitCode = null;
  #abort = null;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #frameReports = [];
  #readinessReports = [];
  #readiness = null;
  #focusReports = [];
  #cursorReports = [];
  #errorHandler;
  #rejectionHandler;
  #input = {
    attached: false,
    readyObserved: false,
    insertedObserved: false,
    closedObserved: false,
    passObserved: false,
    newTabTarget: null,
    closeTabTarget: null,
    frameIdAtInsertedMarker: null,
    frameIdAfterInsert: null,
    frameIdAtClosedMarker: null,
    frameIdAfterClose: null,
    insertCheckQueued: false,
    closeCheckQueued: false,
    presentationQueued: false,
    pointerRecords: [],
  };

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("host-pointer-tab smoke requires a canvas");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
    this.#publishState("starting");
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      this.#recordFatal(`window error: ${message}`);
      appendBounded(this.#windowErrors, message);
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
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process-exit report");
      if (!Number.isSafeInteger(report.exitCode) || this.#processExitCode !== null) {
        throw new Error("process exit report is invalid or duplicated");
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
      if (this.#canvas.width !== report.width || this.#canvas.height !== report.height) {
        throw new Error("canvas dimensions differ from frame metadata");
      }
      appendBounded(this.#frameReports, {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      });
      this.#advancePresentationState();
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

  #reportFocus(value) {
    try {
      const report = asReport(value, "Ozone focus report");
      if (report.protocol !== HOST_PROTOCOL || !isFocusReport(report)) {
        throw new Error("focus metadata is invalid");
      }
      appendBounded(this.#focusReports, {
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      });
    } catch (error) {
      this.#recordFatal(`invalid Ozone focus report: ${String(error)}`);
    }
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType)) {
        throw new Error("cursor report is invalid");
      }
      const descriptor = ozoneCursorDescriptor(report.cursorType);
      if (!descriptor) {
        throw new Error("cursor type is unsupported");
      }
      this.#canvas.style.cursor = descriptor.cssCursor;
      if (this.#canvas.style.cursor !== descriptor.cssCursor) {
        throw new Error("host canvas rejected the cursor style");
      }
      appendBounded(this.#cursorReports, {
        cursorType: report.cursorType,
        cssCursor: descriptor.cssCursor,
        exact: descriptor.exact,
      });
      return true;
    } catch (error) {
      this.#recordFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("host-pointer-tab bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportOzoneFocusState(report) { host.#reportFocus(report); },
      reportOzoneCursor(report) { return host.#reportOzoneCursor(report); },
      reportOzoneTextInputDelivery() {},
      reportOzoneTextInputState() {},
    });
  }

  #currentFrameId() {
    return this.#frameReports.at(-1)?.id ?? 0;
  }

  #targetForClientPoint(point) {
    if (!point || this.#canvas.width < 1 || this.#canvas.height < 1 ||
        this.#canvas.clientWidth < 1 || this.#canvas.clientHeight < 1) {
      return null;
    }
    const rect = this.#canvas.getBoundingClientRect();
    const clientX = rect.left + this.#canvas.clientLeft +
        ((point.x + 0.5) * this.#canvas.clientWidth) / this.#canvas.width;
    const clientY = rect.top + this.#canvas.clientTop +
        ((point.y + 0.5) * this.#canvas.clientHeight) / this.#canvas.height;
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) {
      return null;
    }
    return {x: point.x, y: point.y, clientX, clientY};
  }

  #publishState(state) {
    const input = this.#input;
    globalThis.__chromiumWasmM6HostPointerTabsState = Object.freeze({
      state,
      attached: input.attached,
      readyObserved: input.readyObserved,
      insertedObserved: input.insertedObserved,
      closedObserved: input.closedObserved,
      passObserved: input.passObserved,
      newTabTarget: input.newTabTarget,
      closeTabTarget: input.closeTabTarget,
      frameIdAtInsertedMarker: input.frameIdAtInsertedMarker,
      frameIdAfterInsert: input.frameIdAfterInsert,
      frameIdAtClosedMarker: input.frameIdAtClosedMarker,
      frameIdAfterClose: input.frameIdAfterClose,
      insertCheckQueued: input.insertCheckQueued,
      closeCheckQueued: input.closeCheckQueued,
      presentationQueued: input.presentationQueued,
    });
  }

  #firstFrameAfter(frameId) {
    return this.#frameReports.find((frame) => frame.id > frameId) ?? null;
  }

  #advancePresentationState() {
    if (this.#input.insertedObserved && this.#input.frameIdAfterInsert === null &&
        this.#input.frameIdAtInsertedMarker !== null) {
      const frame = this.#firstFrameAfter(this.#input.frameIdAtInsertedMarker);
      if (frame) {
        this.#input.frameIdAfterInsert = frame.id;
      }
    }
    if (this.#input.closedObserved && this.#input.frameIdAfterClose === null &&
        this.#input.frameIdAtClosedMarker !== null) {
      const frame = this.#firstFrameAfter(this.#input.frameIdAtClosedMarker);
      if (frame) {
        this.#input.frameIdAfterClose = frame.id;
      }
    }
    if (this.#input.closedObserved && this.#input.frameIdAfterClose !== null &&
        !this.#input.presentationQueued) {
      const queued = this.#callSmokeVerifier(
          "chromium_wasm_browser_host_pointer_tab_presented", 2);
      if (queued) {
        this.#input.presentationQueued = true;
      }
    }
    this.#updateState();
  }

  #updateState() {
    if (this.#input.passObserved) {
      this.#publishState("pass-observed");
      return;
    }
    if (this.#input.closedObserved) {
      this.#publishState(this.#input.presentationQueued ?
          "awaiting-orderly-shutdown" : "awaiting-post-close-frame");
      return;
    }
    if (this.#input.insertedObserved) {
      this.#publishState(this.#input.frameIdAfterInsert !== null ?
          "awaiting-trusted-dom-close-tab" : "awaiting-post-insert-frame");
      return;
    }
    if (this.#module && this.#input.attached && this.#input.readyObserved) {
      this.#publishState("awaiting-trusted-dom-new-tab");
    }
  }

  #recordOutput(text) {
    try {
      const ready = parseTargetMarker(text, READY_MARKER);
      if (ready) {
        if (this.#input.readyObserved) {
          throw new Error("received a duplicate tab-flow READY marker");
        }
        const target = this.#targetForClientPoint(ready);
        if (!target) {
          throw new Error("tab-flow READY target cannot map to the canvas");
        }
        this.#input.readyObserved = true;
        this.#input.newTabTarget = target;
      }
      const inserted = parseTargetMarker(text, INSERTED_MARKER);
      if (inserted) {
        if (!this.#input.insertCheckQueued || this.#input.insertedObserved) {
          throw new Error("tab-flow INSERTED marker is out of order");
        }
        const target = this.#targetForClientPoint(inserted);
        if (!target) {
          throw new Error("tab-flow INSERTED target cannot map to the canvas");
        }
        this.#input.insertedObserved = true;
        this.#input.closeTabTarget = target;
        // C++ has just verified the real 1→2 model transition. The smoke
        // requires a frame reported strictly after this marker, rather than a
        // frame that happened while its verification task was merely queued.
        this.#input.frameIdAtInsertedMarker = this.#currentFrameId();
      }
      if (text.includes(CLOSED_MARKER)) {
        if (!this.#input.closeCheckQueued || this.#input.closedObserved) {
          throw new Error("tab-flow CLOSED marker is out of order");
        }
        this.#input.closedObserved = true;
        // Likewise, baseline the required post-close presentation only after
        // C++ verified the real 2→1 model transition.
        this.#input.frameIdAtClosedMarker = this.#currentFrameId();
      }
      if (text.includes(PASS_MARKER)) {
        if (!this.#input.presentationQueued || this.#input.passObserved) {
          throw new Error("tab-flow PASS marker is out of order");
        }
        this.#input.passObserved = true;
      }
      this.#advancePresentationState();
    } catch (error) {
      this.#recordFatal(`invalid tab-flow output: ${String(error)}`);
    }
  }

  #callSmokeVerifier(exportName, stage) {
    if (!this.#module || typeof this.#module.ccall !== "function") {
      this.#recordFatal("tab-flow verifier ran without a Module ccall");
      return false;
    }
    try {
      const result = this.#module.ccall(
          exportName, "number", ["number"], [stage]);
      if (result !== 1) {
        this.#recordFatal(`${exportName} rejected stage ${stage}`);
        return false;
      }
      return true;
    } catch (error) {
      this.#recordFatal(`${exportName} failed: ${String(error)}`);
      return false;
    }
  }

  #acceptedActionPairForTarget(target) {
    if (!target) {
      return false;
    }
    const actions = this.#input.pointerRecords.filter((record) =>
      record.type === "down" || record.type === "up");
    if (actions.length < 2) {
      return false;
    }
    const [down, up] = actions.slice(-2);
    for (const record of [down, up]) {
      if (record.trusted !== true || record.cancelable !== true ||
          record.pointerType !== "mouse" || record.primary !== true ||
          record.accepted !== true || record.defaultPrevented !== true ||
          record.x !== target.x || record.y !== target.y) {
        return false;
      }
    }
    return down.type === "down" && down.button === 0 && down.buttons === 1 &&
        up.type === "up" && up.button === 0 && (up.buttons & 1) === 0;
  }

  #maybeRequestModelCheck() {
    let stage = 0;
    let target = null;
    if (!this.#input.insertCheckQueued) {
      stage = 1;
      target = this.#input.newTabTarget;
    } else if (this.#input.insertedObserved &&
               this.#input.frameIdAfterInsert !== null &&
               !this.#input.closeCheckQueued) {
      stage = 2;
      target = this.#input.closeTabTarget;
    }
    if (stage === 0 || !this.#acceptedActionPairForTarget(target)) {
      return;
    }
    if (!this.#callSmokeVerifier(
            "chromium_wasm_browser_host_pointer_tab_check", stage)) {
      return;
    }
    if (stage === 1) {
      this.#input.insertCheckQueued = true;
    } else {
      this.#input.closeCheckQueued = true;
    }
    this.#updateState();
  }

  #recordPointer(record) {
    appendBounded(this.#input.pointerRecords, record);
    this.#maybeRequestModelCheck();
    this.#updateState();
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied an invalid Module");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#pointerInput = new ChromiumWasmTrustedPointerInput(this.#canvas, {
      getModule: () => this.#module,
      recordFatal: (message) => this.#recordFatal(message),
      record: (record) => this.#recordPointer(record),
      maximumFrameDimension: MAX_FRAME_DIMENSION,
    });
    this.#pointerInput.attach();
    this.#input.attached = this.#pointerInput.attached;
    this.#updateState();
  }

  #result(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m6GateComplete: false,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === this.#canvas,
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      ozoneFocusReports: this.#focusReports,
      ozoneCursorReports: this.#cursorReports,
      hostInput: {
        attached: this.#input.attached,
        readyObserved: this.#input.readyObserved,
        insertedObserved: this.#input.insertedObserved,
        closedObserved: this.#input.closedObserved,
        passObserved: this.#input.passObserved,
        newTabTarget: this.#input.newTabTarget,
        closeTabTarget: this.#input.closeTabTarget,
        frameIdAtInsertedMarker: this.#input.frameIdAtInsertedMarker,
        frameIdAfterInsert: this.#input.frameIdAfterInsert,
        frameIdAtClosedMarker: this.#input.frameIdAtClosedMarker,
        frameIdAfterClose: this.#input.frameIdAfterClose,
        insertCheckQueued: this.#input.insertCheckQueued,
        closeCheckQueued: this.#input.closeCheckQueued,
        presentationQueued: this.#input.presentationQueued,
        pointerRecords: this.#input.pointerRecords,
      },
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
        throw new Error("host-pointer-tab smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("host-pointer-tab timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("host-pointer-tab module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("host-pointer-tab canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("host-pointer-tab module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("host-pointer-tab loader has no default factory export");
      }
      const host = this;
      namespace.default({
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
      }).catch((error) => {
        host.#recordFatal(`module factory rejected: ${String(error)}`);
      });

      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("host-pointer-tab smoke did not exit before timeout");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#pointerInput?.detach();
      this.#input.attached = false;
      this.#releaseWindowErrors();
    }
  }
}

function validateResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.runtimeExitCode === 0, "runtime did not exit zero");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocused === true, "canvas focus was lost");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
      "host recorded an unhandled rejection");
  require(result.frameReports.length >= 3, "too few host-canvas frames");
  require(result.readiness?.surfaceReady === true,
      "surface readiness was not reported");
  require(result.ozoneFocusReports.some((report) =>
    report.keyboardTargetPresent === true && report.active === true),
  "no active Ozone keyboard target was observed");
  const input = result.hostInput;
  for (const field of [
    "attached", "readyObserved", "insertedObserved", "closedObserved",
    "passObserved", "insertCheckQueued", "closeCheckQueued",
    "presentationQueued",
  ]) {
    require(input?.[field] === true, `host input ${field} is not true`);
  }
  require(input?.frameIdAfterInsert > input?.frameIdAtInsertedMarker,
      "insert action has no later presented frame");
  require(input?.frameIdAfterClose > input?.frameIdAtClosedMarker,
      "close action has no later presented frame");
  result.failedChecks = failures;
  if (failures.length) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserHostPointerTabsSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-host-pointer-tabs-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-host-pointer-tabs-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("host-pointer-tab page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserHostPointerTabsSmokeHost(canvas, versions);
  const result = validateResult(await host.run(
      `${location.pathname.replace(/\/$/, "")}/artifacts/${moduleName}.js`,
      timeoutMs));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(
      `${location.pathname.replace(/\/$/, "")}/result/${encodeURIComponent(token)}`,
      {
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

export const chromeWasmBrowserHostPointerTabsSmokeContract = Object.freeze({
  CASE,
  CLOSED_MARKER,
  HOST_PROTOCOL,
  INSERTED_MARKER,
  PASS_MARKER,
  READY_MARKER,
  SCOPE,
  SWITCH,
});

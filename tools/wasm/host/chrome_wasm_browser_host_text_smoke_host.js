// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";

// This host specializes the shared production trusted-text adapter with three
// observer-only C++ checks. It never writes a Chrome Textfield or requests a
// page navigation; the actual input sequence is Ctrl+L, trusted beforeinput,
// then unmodified physical Enter.
const HOST_PROTOCOL = 1;
const CASE = "browser_host_text_m6";
const SCOPE = "trusted-dom-beforeinput-ozone-textinputclient-navigation";
const SWITCH = "--wasm-browser-host-text-smoke";
const ADDRESS_TEXT_CHUNKS = Object.freeze(["chrome://", "version/"]);
const ADDRESS_TEXT = ADDRESS_TEXT_CHUNKS.join("");
const BURST_ARMED_MARKER = "CHROMIUM_WASM_M6_HOST_TEXT:BURST_ARMED";
const READY_MARKER = "CHROMIUM_WASM_M6_HOST_TEXT:READY";
const FOCUSED_MARKER = "CHROMIUM_WASM_M6_HOST_TEXT:FOCUSED";
const INSERTED_MARKER = "CHROMIUM_WASM_M6_HOST_TEXT:TEXT_INSERTED";
const NAVIGATED_MARKER = "CHROMIUM_WASM_M6_HOST_TEXT:NAVIGATED";
const PASS_MARKER = "CHROMIUM_WASM_M6_HOST_TEXT:PASS";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 64;

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
    throw new Error(`invalid host-text versions: ${String(error)}`);
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("host-text page is missing its version element");
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

function isTextInputStateReport(value) {
  return value && typeof value === "object" &&
      typeof value.focusedClientPresent === "boolean" &&
      typeof value.editable === "boolean" &&
      typeof value.canComposeInline === "boolean" &&
      (!value.editable || value.focusedClientPresent) &&
      (!value.canComposeInline || value.editable);
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

class ChromiumWasmBrowserHostTextSmokeHost {
  #canvas;
  #proxy;
  #versions;
  #module = null;
  #textInput = null;
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
  #readiness = null;
  #readinessReports = [];
  #focusReports = [];
  #textInputStates = [];
  #cursorReports = [];
  #errorHandler;
  #rejectionHandler;
  #state = "starting";
  #input = {
    readyObserved: false,
    burstArmedObserved: false,
    nativeBurstAdmissionsObserved: false,
    nativeTextAdmissionCount: 0,
    nativeTextDeliveryCountAtAdmission: [],
    nativeTextDeliveryCount: 0,
    nativeTextDeliverySequences: [],
    focusObserved: false,
    focusPresentationObserved: false,
    insertedObserved: false,
    insertedPresentationObserved: false,
    navigatedObserved: false,
    navigationPresentationObserved: false,
    passObserved: false,
    focusCheckQueued: false,
    textCheckQueued: false,
    navigationCheckQueued: false,
    focusMarkerFrameId: null,
    frameIdAfterFocus: null,
    insertedMarkerFrameId: null,
    frameIdAfterInsert: null,
    navigationMarkerFrameId: null,
    frameIdAfterNavigation: null,
  };

  constructor(canvas, proxy, versions) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(proxy instanceof HTMLTextAreaElement)) {
      throw new Error("host-text smoke requires a canvas and textarea proxy");
    }
    this.#canvas = canvas;
    this.#proxy = proxy;
    this.#versions = versions;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
    this.#publishState();
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
      if (!Number.isSafeInteger(report.exitCode) ||
          this.#processExitCode !== null) {
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
      if (this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
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
        throw new Error("Ozone focus report is invalid");
      }
      appendBounded(this.#focusReports, {
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      });
    } catch (error) {
      this.#recordFatal(`invalid Ozone focus report: ${String(error)}`);
    }
  }

  #reportTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state report");
      if (report.protocol !== HOST_PROTOCOL || !isTextInputStateReport(report)) {
        throw new Error("Ozone text-input state report is invalid");
      }
      appendBounded(this.#textInputStates, {
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      });
      this.#textInput?.handleOzoneTextInputState(report);
    } catch (error) {
      this.#recordFatal(`invalid Ozone text-input state report: ${String(error)}`);
    }
  }

  #reportBrowserTextDelivery(value) {
    if (!this.#textInput) {
      this.#recordFatal("browser text delivery arrived before trusted adapter");
      return;
    }
    this.#textInput.handleOzoneBrowserTextInputDelivery(value);
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType)) {
        throw new Error("Ozone cursor report is invalid");
      }
      const descriptor = ozoneCursorDescriptor(report.cursorType);
      if (!descriptor) {
        throw new Error("Ozone cursor type is unsupported");
      }
      this.#canvas.style.cursor = descriptor.cssCursor;
      if (this.#canvas.style.cursor !== descriptor.cssCursor) {
        throw new Error("host canvas rejected the Ozone cursor style");
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
      throw new Error("host-text bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportOzoneFocusState(report) { host.#reportFocus(report); },
      reportOzoneTextInputState(report) { host.#reportTextInputState(report); },
      reportOzoneBrowserTextInputDelivery(report) {
        host.#reportBrowserTextDelivery(report);
      },
      reportOzoneCursor(report) { return host.#reportOzoneCursor(report); },
      // M4 composition delivery remains a separate protocol.
      reportOzoneTextInputDelivery() {},
    });
  }

  #textSnapshot() {
    return this.#textInput?.snapshot() || {
      attached: false,
      deliveryAccepted: false,
      deliveryRejected: false,
      proxyFocused: false,
      ctrlLRecords: [],
      beforeInputRecords: [],
      browserTextDeliveryReports: [],
      enterRecords: [],
      rejectedRecords: [],
      cleanupRecords: [],
    };
  }

  #publishState() {
    const text = this.#textSnapshot();
    globalThis.__chromiumWasmM6HostTextState = Object.freeze({
      state: this.#state,
      attached: text.attached,
      readyObserved: this.#input.readyObserved,
      focusPresentationObserved: this.#input.focusPresentationObserved,
      deliveryAccepted: text.deliveryAccepted,
      insertedPresentationObserved: this.#input.insertedPresentationObserved,
      navigationPresentationObserved: this.#input.navigationPresentationObserved,
      proxyFocused: text.proxyFocused,
      passObserved: this.#input.passObserved,
    });
  }

  #setState(state) {
    this.#state = state;
    this.#publishState();
  }

  #currentFrameId() {
    return this.#frameReports.at(-1)?.id || 0;
  }

  #updateReadyState() {
    if (this.#textInput?.snapshot().attached && this.#input.readyObserved &&
        this.#input.burstArmedObserved &&
        !this.#input.focusCheckQueued && !this.#input.passObserved) {
      this.#setState("awaiting-trusted-dom-ctrl-l");
    }
  }

  #recordOutput(text) {
    if (text.includes(BURST_ARMED_MARKER)) {
      if (this.#input.burstArmedObserved) {
        this.#recordFatal("duplicate native text burst barrier marker");
      }
      this.#input.burstArmedObserved = true;
      this.#updateReadyState();
    }
    if (text.includes(READY_MARKER)) {
      this.#input.readyObserved = true;
      this.#updateReadyState();
    }
    if (text.includes(FOCUSED_MARKER)) {
      if (!this.#input.focusCheckQueued || this.#input.focusObserved) {
        this.#recordFatal("unexpected address-focus marker");
      } else {
        this.#input.focusObserved = true;
        this.#input.focusMarkerFrameId = this.#currentFrameId();
        this.#advancePresentationState();
      }
    }
    if (text.includes(INSERTED_MARKER)) {
      if (!this.#input.textCheckQueued || this.#input.insertedObserved) {
        this.#recordFatal("unexpected address-text marker");
      } else {
        this.#input.insertedObserved = true;
        this.#input.insertedMarkerFrameId = this.#currentFrameId();
        this.#advancePresentationState();
      }
    }
    if (text.includes(NAVIGATED_MARKER)) {
      if (this.#input.navigatedObserved) {
        this.#recordFatal("duplicate navigation observer marker");
      } else {
        this.#input.navigatedObserved = true;
        this.#input.navigationMarkerFrameId = this.#currentFrameId();
        this.#advancePresentationState();
      }
    }
    if (text.includes(PASS_MARKER)) {
      this.#input.passObserved = true;
      this.#setState("pass-observed");
    }
  }

  #advancePresentationState() {
    const frameId = this.#currentFrameId();
    if (this.#input.focusObserved && !this.#input.focusPresentationObserved &&
        frameId > this.#input.focusMarkerFrameId) {
      if (!this.#textInput?.activateProxy()) {
        this.#recordFatal("trusted textarea was not ready after address focus");
      } else {
        this.#input.focusPresentationObserved = true;
        this.#input.frameIdAfterFocus = frameId;
        this.#setState("awaiting-trusted-dom-insert-text");
      }
    }
    if (this.#input.insertedObserved &&
        !this.#input.insertedPresentationObserved &&
        frameId > this.#input.insertedMarkerFrameId) {
      this.#input.insertedPresentationObserved = true;
      this.#input.frameIdAfterInsert = frameId;
      this.#setState("awaiting-trusted-dom-enter");
    }
    const enterComplete = this.#textSnapshot().enterRecords.length === 2;
    if (this.#input.navigatedObserved && enterComplete &&
        !this.#input.navigationPresentationObserved &&
        frameId > this.#input.navigationMarkerFrameId) {
      this.#input.navigationPresentationObserved = true;
      this.#input.frameIdAfterNavigation = frameId;
      this.#queueNavigationCheckAfterPresentation();
    }
  }

  #callSmokeCheck(stage) {
    if (!this.#module) {
      return 0;
    }
    try {
      return this.#module.ccall(
          "chromium_wasm_browser_host_text_smoke_check", "number", ["number"],
          [stage]);
    } catch (error) {
      this.#recordFatal(`host text observer ABI call failed: ${String(error)}`);
      return 0;
    }
  }

  #queueFocusCheck() {
    if (this.#input.focusCheckQueued) {
      return;
    }
    if (this.#callSmokeCheck(1) !== 1) {
      this.#recordFatal("address-focus observer check was not accepted");
      return;
    }
    this.#input.focusCheckQueued = true;
  }

  #recordNativeTextAdmission(record) {
    const expectedIndex = this.#input.nativeTextAdmissionCount;
    if (record.action !== undefined || record.sessionId !== undefined ||
        record.sequence !== expectedIndex + 1 ||
        record.dataUtf8Bytes !== ADDRESS_TEXT_CHUNKS[expectedIndex]?.length) {
      this.#recordFatal("native text admission did not match the burst request");
      return;
    }
    this.#input.nativeTextDeliveryCountAtAdmission.push(
        this.#input.nativeTextDeliveryCount);
    ++this.#input.nativeTextAdmissionCount;
    if (this.#input.nativeTextAdmissionCount === ADDRESS_TEXT_CHUNKS.length) {
      this.#input.nativeBurstAdmissionsObserved = true;
    }
    this.#maybeQueueTextCheckAfterNativeDelivery();
  }

  #recordNativeTextDelivery(report) {
    const expectedIndex = this.#input.nativeTextDeliveryCount;
    if (report.action !== 4 || report.sessionId !== 0 ||
        report.sequence !== expectedIndex + 1 ||
        report.text !== ADDRESS_TEXT_CHUNKS[expectedIndex]) {
      this.#recordFatal("native delivery did not match the smoke text burst");
      return;
    }
    ++this.#input.nativeTextDeliveryCount;
    this.#input.nativeTextDeliverySequences.push(report.sequence);
    this.#maybeQueueTextCheckAfterNativeDelivery();
  }

  #maybeQueueTextCheckAfterNativeDelivery() {
    if (this.#input.textCheckQueued ||
        !this.#input.nativeBurstAdmissionsObserved ||
        this.#input.nativeTextDeliveryCount !== ADDRESS_TEXT_CHUNKS.length) {
      return;
    }
    this.#input.textCheckQueued = true;
    // This callback originates in a synchronous UI->JS bridge import. Defer
    // Wasm export re-entry until that import has returned to the UI worker.
    setTimeout(() => {
      const text = this.#textSnapshot();
      if (text.deliveryAccepted && text.pendingDeliveryCount === 0 &&
          this.#input.nativeTextAdmissionCount === ADDRESS_TEXT_CHUNKS.length &&
          this.#input.nativeTextDeliveryCount === ADDRESS_TEXT_CHUNKS.length &&
          this.#callSmokeCheck(2) !== 1) {
        this.#recordFatal("address-text observer check was not accepted");
      }
    }, 0);
  }

  #queueNavigationCheckAfterPresentation() {
    if (this.#input.navigationCheckQueued) {
      return;
    }
    this.#input.navigationCheckQueued = true;
    // Frame reports also cross the asynchronous application boundary; defer
    // the observer export rather than re-entering while a report is active.
    setTimeout(() => {
      if (this.#input.navigationPresentationObserved &&
          this.#callSmokeCheck(3) !== 1) {
        this.#recordFatal("navigation observer check was not accepted");
      }
    }, 0);
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied an invalid Module object");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#textInput = new ChromiumWasmTrustedTextInput(this.#canvas, this.#proxy, {
      getModule: () => this.#module,
      reportFatal: (message) => this.#recordFatal(message),
      autoFocusProxy: false,
      canAcceptBeforeInput: () => this.#input.focusPresentationObserved,
      validateBeforeInput: (event) =>
        event.data === ADDRESS_TEXT_CHUNKS[this.#input.nativeTextAdmissionCount] ?
          null : "smoke requires ordered chrome://version/ text chunks",
      canSubmitEnter: () => this.#input.insertedPresentationObserved,
      onCtrlLComplete: () => this.#queueFocusCheck(),
      onBeforeInputQueued: (record) => this.#recordNativeTextAdmission(record),
      onNativeDelivery: (report) => this.#recordNativeTextDelivery(report),
      onNativeDeliveryRejected: () => this.#setState("native-text-delivery-rejected"),
      onEnterComplete: () => {
        this.#setState("awaiting-native-navigation");
        this.#advancePresentationState();
      },
      onStateChange: () => this.#publishState(),
    });
    this.#textInput.attach();
    const latestState = this.#textInputStates.at(-1);
    if (latestState) {
      this.#textInput.handleOzoneTextInputState(latestState);
    }
    this.#updateReadyState();
  }

  #result(status, error) {
    const text = this.#textSnapshot();
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
      canvasFocusedAtStart: text.ctrlLRecords[0]?.canvasFocused === true,
      proxyFocused: text.proxyFocused,
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      ozoneFocusReports: this.#focusReports,
      ozoneTextInputStates: this.#textInputStates,
      hostInput: {
        ...this.#input,
        ...text,
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
        throw new Error("host-text smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("host-text timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("host-text module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("host-text canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("host-text module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("host-text loader has no default factory export");
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
        throw new Error("host-text smoke did not exit before timeout");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#textInput?.detach();
      this.#textInput = null;
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
  require(result.canvasFocusedAtStart === true, "canvas was not focused for Ctrl+L");
  require(result.proxyFocused === true, "textarea proxy lost focus before exit");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
      "host recorded an unhandled rejection");
  require(result.hostInput.readyObserved === true,
      "native host-text smoke ready marker is absent");
  require(result.hostInput.burstArmedObserved === true,
      "native host-text burst barrier marker is absent");
  require(result.hostInput.nativeBurstAdmissionsObserved === true,
      "two native text reservations were not observed before delivery");
  require(result.hostInput.nativeTextAdmissionCount === ADDRESS_TEXT_CHUNKS.length,
      "native text burst did not admit both chunks");
  require(JSON.stringify(result.hostInput.nativeTextDeliveryCountAtAdmission) ===
      JSON.stringify([0, 0]),
  "native text acknowledgement arrived before burst admission completed");
  require(result.hostInput.nativeTextDeliveryCount === ADDRESS_TEXT_CHUNKS.length,
      "native text burst did not deliver both chunks");
  require(result.hostInput.deliveryAccepted === true,
      "native browser text delivery was not accepted");
  require(result.hostInput.deliveryRejected === false,
      "native browser text delivery was rejected");
  require(result.hostInput.passObserved === true, "pass marker is absent");
  result.failedChecks = failures;
  if (failures.length) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserHostTextSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-host-text-root");
  const canvas = document.querySelector("#browser-canvas");
  const proxy = document.querySelector("#browser-text-proxy");
  const status = document.querySelector("#browser-host-text-status");
  const versionsElement = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(proxy instanceof HTMLTextAreaElement) || !(status instanceof HTMLElement)) {
    throw new Error("host-text page is missing required elements");
  }
  renderVersions(versionsElement, versions);
  const host = new ChromiumWasmBrowserHostTextSmokeHost(canvas, proxy, versions);
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

export const chromeWasmBrowserHostTextSmokeContract = Object.freeze({
  ADDRESS_TEXT,
  ADDRESS_TEXT_CHUNKS,
  BURST_ARMED_MARKER,
  CASE,
  FOCUSED_MARKER,
  HOST_PROTOCOL,
  INSERTED_MARKER,
  NAVIGATED_MARKER,
  PASS_MARKER,
  READY_MARKER,
  SCOPE,
  SWITCH,
});

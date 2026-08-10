// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {ChromiumWasmTrustedClipboardInput} from "./chrome_wasm_clipboard_input.js";

// This controlled M7 host uses the production one-way clipboard adapter. The
// only special test capability is a visible button whose trusted click seeds
// a fixed outer-browser clipboard value. The actual import remains a trusted
// DOM paste and normal native Ozone Ctrl+V chord; this file never writes a
// Chrome Textfield or invokes a Browser command/navigation API.
const HOST_PROTOCOL = 1;
const CASE = "browser_host_clipboard_m7";
const SCOPE = "trusted-dom-paste-volatile-copy-paste-ozone-navigation";
const SWITCH = "--wasm-browser-host-clipboard-smoke";
const ADDRESS_TEXT = "chrome://version/";
const READY_MARKER = "CHROMIUM_WASM_M7_HOST_CLIPBOARD:READY";
const FOCUSED_MARKER = "CHROMIUM_WASM_M7_HOST_CLIPBOARD:FOCUSED";
const PASTED_MARKER = "CHROMIUM_WASM_M7_HOST_CLIPBOARD:PASTED";
const NAVIGATED_MARKER = "CHROMIUM_WASM_M7_HOST_CLIPBOARD:NAVIGATED";
const PASS_MARKER = "CHROMIUM_WASM_M7_HOST_CLIPBOARD:PASS";
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
    throw new Error(`invalid host-clipboard versions: ${String(error)}`);
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("host-clipboard page is missing its version element");
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

function isClipboardDeliveryReport(value) {
  return value && typeof value === "object" &&
      Number.isSafeInteger(value.requestId) && value.requestId >= 1 &&
      typeof value.accepted === "boolean";
}

const CURSOR_BY_TYPE = new Map([
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
  [20, "all-scroll"], [21, "all-scroll"], [22, "all-scroll"],
  [23, "all-scroll"], [24, "all-scroll"], [25, "all-scroll"],
  [26, "all-scroll"], [27, "all-scroll"], [28, "all-scroll"],
  [43, "all-scroll"], [44, "all-scroll"], [45, "default"],
  [46, "no-drop"], [47, "move"], [48, "copy"], [49, "alias"],
  [50, "not-allowed"], [51, "not-allowed"], [52, "not-allowed"],
  [53, "not-allowed"],
]);

class ChromiumWasmBrowserHostClipboardSmokeHost {
  #canvas;
  #proxy;
  #seedButton;
  #versions;
  #module = null;
  #clipboardInput = null;
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
  #onCanvasKeyDown;
  #onCanvasKeyUp;
  #onProxyKeyDown;
  #onProxyKeyUp;
  #onCanvasBlur;
  #onProxyBlur;
  #onWindowBlur;
  #onVisibilityChange;
  #onSeedClick;
  #state = "starting";
  #input = {
    readyObserved: false,
    focusCheckQueued: false,
    focusObserved: false,
    focusPresentationObserved: false,
    seedButtonTrustedClicked: false,
    seedButtonClickCancelable: false,
    seedButtonDefaultPrevented: false,
    seedWriteRequested: false,
    seedWriteSucceeded: false,
    seedWriteFailed: false,
    proxyFocusedAfterSeed: false,
    clipboardDeliveryObserved: false,
    clipboardDeliveryAccepted: false,
    clipboardDeliveryRequestId: null,
    pasteCheckQueued: false,
    pastedObserved: false,
    pastedPresentationObserved: false,
    enterDispatchStarted: false,
    enterHeld: false,
    enterComplete: false,
    navigatedObserved: false,
    navigationPresentationObserved: false,
    navigationCheckQueued: false,
    passObserved: false,
    ctrlLIndex: 0,
    ctrlLComplete: false,
    ctrlLRecords: [],
    seedRecords: [],
    enterRecords: [],
    rejectedKeyRecords: [],
    keyCleanupRecords: [],
    ordinalChecks: [],
    focusMarkerFrameId: null,
    frameIdAfterFocus: null,
    pastedMarkerFrameId: null,
    frameIdAfterPaste: null,
    navigationMarkerFrameId: null,
    frameIdAfterNavigation: null,
  };

  constructor(canvas, proxy, seedButton, versions) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(proxy instanceof HTMLTextAreaElement) ||
        !(seedButton instanceof HTMLButtonElement)) {
      throw new Error("host-clipboard smoke requires canvas, proxy, and seed button");
    }
    this.#canvas = canvas;
    this.#proxy = proxy;
    this.#seedButton = seedButton;
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
      this.#clipboardInput?.handleOzoneTextInputState(report);
    } catch (error) {
      this.#recordFatal(`invalid Ozone text-input state report: ${String(error)}`);
    }
  }

  #reportClipboardDelivery(value) {
    try {
      const report = asReport(value, "clipboard paste delivery report");
      if (report.protocol !== HOST_PROTOCOL || !isClipboardDeliveryReport(report)) {
        throw new Error("clipboard paste delivery is invalid");
      }
      if (!this.#clipboardInput) {
        throw new Error("clipboard paste delivery arrived before adapter");
      }
      this.#clipboardInput.handleOzoneBrowserClipboardPasteDelivery(report);
    } catch (error) {
      this.#recordFatal(`invalid clipboard paste delivery: ${String(error)}`);
    }
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType)) {
        throw new Error("Ozone cursor report is invalid");
      }
      const cursor = CURSOR_BY_TYPE.get(report.cursorType);
      if (!cursor) {
        throw new Error("Ozone cursor type is unsupported by this smoke host");
      }
      this.#canvas.style.cursor = cursor;
      if (this.#canvas.style.cursor !== cursor) {
        throw new Error("host canvas rejected the Ozone cursor style");
      }
      appendBounded(this.#cursorReports, {cursorType: report.cursorType, cursor});
      return true;
    } catch (error) {
      this.#recordFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("host-clipboard bridge is already installed");
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
      reportOzoneBrowserClipboardPasteDelivery(report) {
        host.#reportClipboardDelivery(report);
      },
      reportOzoneCursor(report) { return host.#reportOzoneCursor(report); },
      // This M7 route is deliberately separate from M4 composition and M6
      // committed-text acknowledgement protocols.
      reportOzoneTextInputDelivery() {},
      reportOzoneBrowserTextInputDelivery() {},
    });
  }

  #clipboardSnapshot() {
    return this.#clipboardInput?.snapshot() || {
      attached: false,
      editable: false,
      proxyFocused: false,
      focusGeneration: 0,
      pendingRequestId: null,
      tombstonedRequestCount: 0,
      proxyTextEmpty: true,
      pasteRecords: [],
      deliveryReports: [],
      rejectedRecords: [],
      cleanupRecords: [],
    };
  }

  #seedButtonCenter() {
    const rect = this.#seedButton.getBoundingClientRect();
    if (!Number.isFinite(rect.left) || !Number.isFinite(rect.top) ||
        !Number.isFinite(rect.width) || !Number.isFinite(rect.height) ||
        rect.width <= 0 || rect.height <= 0) {
      return null;
    }
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };
  }

  #publishState() {
    const clipboard = this.#clipboardSnapshot();
    globalThis.__chromiumWasmM7HostClipboardState = Object.freeze({
      state: this.#state,
      attached: clipboard.attached,
      editable: clipboard.editable,
      proxyFocused: clipboard.proxyFocused,
      readyObserved: this.#input.readyObserved,
      focusPresentationObserved: this.#input.focusPresentationObserved,
      seedWriteSucceeded: this.#input.seedWriteSucceeded,
      clipboardDeliveryObserved: this.#input.clipboardDeliveryObserved,
      pastedPresentationObserved: this.#input.pastedPresentationObserved,
      navigationPresentationObserved: this.#input.navigationPresentationObserved,
      passObserved: this.#input.passObserved,
      seedButtonDisabled: this.#seedButton.disabled,
      seedButtonCenter: this.#seedButtonCenter(),
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
    if (this.#clipboardSnapshot().attached && this.#input.readyObserved &&
        !this.#input.focusCheckQueued && !this.#input.passObserved) {
      this.#setState("awaiting-trusted-dom-ctrl-l");
    }
  }

  #recordOutput(text) {
    if (text.includes(READY_MARKER)) {
      if (this.#input.readyObserved) {
        this.#recordFatal("duplicate native clipboard ready marker");
      }
      this.#input.readyObserved = true;
      this.#updateReadyState();
    }
    if (text.includes(FOCUSED_MARKER)) {
      if (!this.#input.focusCheckQueued || this.#input.focusObserved) {
        this.#recordFatal("unexpected clipboard address-focus marker");
      } else {
        this.#input.focusObserved = true;
        this.#input.focusMarkerFrameId = this.#currentFrameId();
        this.#advancePresentationState();
      }
    }
    if (text.includes(PASTED_MARKER)) {
      if (!this.#input.pasteCheckQueued || !this.#input.clipboardDeliveryAccepted ||
          this.#input.pastedObserved) {
        this.#recordFatal("unexpected clipboard pasted-text marker");
      } else {
        this.#input.pastedObserved = true;
        this.#input.pastedMarkerFrameId = this.#currentFrameId();
        this.#advancePresentationState();
      }
    }
    if (text.includes(NAVIGATED_MARKER)) {
      // A local chrome:// commit can race the outer physical key-up report.
      // Record the native observation, but do not issue ordinal 3 until both
      // the complete Enter transaction and a later compositor frame exist.
      // |enterDispatchStarted| is set before the outbound native key ABI, so
      // it still admits that legitimate fast-marker ordering while excluding
      // an unrelated or automatic navigation before this tested Enter route.
      if (!this.#input.enterDispatchStarted ||
          !this.#input.pastedPresentationObserved || this.#input.navigatedObserved) {
        this.#recordFatal("unexpected clipboard navigation marker");
      } else {
        this.#input.navigatedObserved = true;
        this.#input.navigationMarkerFrameId = this.#currentFrameId();
        this.#advancePresentationState();
      }
    }
    if (text.includes(PASS_MARKER)) {
      if (!this.#input.navigationCheckQueued || this.#input.passObserved) {
        this.#recordFatal("unexpected clipboard pass marker");
      }
      this.#input.passObserved = true;
      this.#setState("pass-observed");
    }
  }

  #advancePresentationState() {
    const frameId = this.#currentFrameId();
    const clipboard = this.#clipboardSnapshot();
    if (this.#input.focusObserved && !this.#input.focusPresentationObserved &&
        frameId > this.#input.focusMarkerFrameId) {
      if (!clipboard.attached || !clipboard.editable) {
        this.#recordFatal("clipboard adapter was not editable after native focus");
      } else {
        this.#proxy.focus({preventScroll: true});
        if (document.activeElement !== this.#proxy) {
          this.#recordFatal("clipboard proxy did not accept focus after native focus");
        } else {
          this.#input.focusPresentationObserved = true;
          this.#input.frameIdAfterFocus = frameId;
          this.#seedButton.disabled = false;
          this.#setState("awaiting-trusted-dom-clipboard-seed");
        }
      }
    }
    if (this.#input.pastedObserved && !this.#input.pastedPresentationObserved &&
        frameId > this.#input.pastedMarkerFrameId) {
      this.#input.pastedPresentationObserved = true;
      this.#input.frameIdAfterPaste = frameId;
      this.#setState("awaiting-trusted-dom-enter");
    }
    if (this.#input.navigatedObserved && this.#input.enterComplete &&
        !this.#input.navigationPresentationObserved &&
        frameId > this.#input.navigationMarkerFrameId) {
      this.#input.navigationPresentationObserved = true;
      this.#input.frameIdAfterNavigation = frameId;
      this.#queueNavigationCheckAfterPresentation();
    }
  }

  #callHostKey(code, down) {
    if (!this.#module) {
      return 0;
    }
    try {
      return this.#module.ccall(
          "chromium_wasm_browser_host_key", "number", ["string", "number"],
          [code, down ? 1 : 0]);
    } catch (error) {
      this.#recordFatal(`clipboard host key ABI call failed: ${String(error)}`);
      return 0;
    }
  }

  #callSmokeCheck(stage) {
    if (!this.#module) {
      return 0;
    }
    try {
      const accepted = this.#module.ccall(
          "chromium_wasm_browser_host_clipboard_smoke_check", "number",
          ["number"], [stage]);
      if (accepted === 1) {
        this.#input.ordinalChecks.push(stage);
      }
      return accepted;
    } catch (error) {
      this.#recordFatal(`clipboard observer ABI call failed: ${String(error)}`);
      return 0;
    }
  }

  #queueFocusCheck() {
    if (this.#input.focusCheckQueued) {
      return;
    }
    // This is the fixed observer ordinal, not an address-field or Browser
    // command. The native lifecycle verifies focus/selection on its UI task.
    this.#input.focusCheckQueued = true;
    if (this.#callSmokeCheck(1) !== 1) {
      this.#recordFatal("clipboard focus observer check was not accepted");
    }
  }

  #queuePasteCheckAfterNativeDelivery() {
    if (this.#input.pasteCheckQueued) {
      return;
    }
    this.#input.pasteCheckQueued = true;
    // The adapter callback is already deferred from a synchronous UI->JS
    // import. Defer again before re-entering the fixed observer export.
    setTimeout(() => {
      if (this.#input.clipboardDeliveryAccepted &&
          this.#clipboardSnapshot().pendingRequestId === null &&
          this.#callSmokeCheck(2) !== 1) {
        this.#recordFatal("clipboard pasted-text observer check was not accepted");
      }
    }, 0);
  }

  #queueNavigationCheckAfterPresentation() {
    if (this.#input.navigationCheckQueued) {
      return;
    }
    this.#input.navigationCheckQueued = true;
    // A frame report crosses the same asynchronous application boundary.
    setTimeout(() => {
      if (this.#input.navigationPresentationObserved &&
          this.#callSmokeCheck(3) !== 1) {
        this.#recordFatal("clipboard navigation observer check was not accepted");
      }
    }, 0);
  }

  #ctrlLRejectionReason(event, down) {
    const expected = [
      ["keydown", "ControlLeft"],
      ["keydown", "KeyL"],
      ["keyup", "KeyL"],
      ["keyup", "ControlLeft"],
    ];
    if (!this.#module || !this.#input.readyObserved || this.#input.ctrlLComplete) {
      return "trusted clipboard Ctrl+L bridge is not ready";
    }
    const next = expected[this.#input.ctrlLIndex];
    if (!next || next[0] !== (down ? "keydown" : "keyup") ||
        next[1] !== event.code) {
      return "DOM key is outside the bounded clipboard Ctrl+L transaction";
    }
    if (event.isTrusted !== true || event.cancelable !== true ||
        document.activeElement !== this.#canvas || event.isComposing || event.repeat ||
        event.key === "Dead" || event.key === "Process" || event.metaKey ||
        event.altKey || event.shiftKey || event.getModifierState("AltGraph")) {
      return "DOM Ctrl+L key has unsupported trust, target, or modifier state";
    }
    if (event.code === "KeyL" && !event.ctrlKey) {
      return "DOM KeyL event lacks ControlLeft";
    }
    return null;
  }

  #handleCanvasKey(event, down) {
    const record = {
      type: down ? "keydown" : "keyup",
      code: event.code,
      trusted: event.isTrusted,
      cancelable: event.cancelable,
      canvasFocused: document.activeElement === this.#canvas,
      accepted: false,
      defaultPrevented: false,
    };
    const reason = this.#ctrlLRejectionReason(event, down);
    if (reason !== null || this.#callHostKey(event.code, down) !== 1) {
      record.reason = reason || "Chrome rejected a clipboard Ctrl+L transition";
      appendBounded(this.#input.rejectedKeyRecords, record);
      return;
    }
    event.preventDefault();
    record.accepted = true;
    record.defaultPrevented = event.defaultPrevented;
    appendBounded(this.#input.ctrlLRecords, record);
    ++this.#input.ctrlLIndex;
    if (this.#input.ctrlLIndex === 4) {
      this.#input.ctrlLComplete = true;
      this.#queueFocusCheck();
    }
    this.#publishState();
  }

  #enterRejectionReason(event, down) {
    if (!this.#module || !this.#input.pastedPresentationObserved ||
        !this.#input.clipboardDeliveryAccepted ||
        document.activeElement !== this.#proxy) {
      return "trusted clipboard Enter bridge is not ready";
    }
    if (event.isTrusted !== true || event.cancelable !== true ||
        event.code !== "Enter" || event.key !== "Enter" || event.isComposing ||
        event.repeat || event.ctrlKey || event.shiftKey || event.altKey ||
        event.metaKey || event.getModifierState("AltGraph")) {
      return "clipboard Enter has unsupported trust, physical, or modifier state";
    }
    if (down === this.#input.enterHeld) {
      return down ? "clipboard Enter is already held" : "clipboard Enter was not held";
    }
    return null;
  }

  #handleProxyEnter(event, down) {
    const record = {
      type: down ? "keydown" : "keyup",
      code: event.code,
      key: event.key,
      trusted: event.isTrusted,
      cancelable: event.cancelable,
      proxyFocused: document.activeElement === this.#proxy,
      accepted: false,
      defaultPrevented: false,
    };
    const reason = this.#enterRejectionReason(event, down);
    if (reason !== null) {
      record.reason = reason;
      appendBounded(this.#input.rejectedKeyRecords, record);
      return;
    }
    // C++ can observe a chrome:// commit while this synchronous host export is
    // still active. Arm the ordering witness before the ABI, then roll it
    // back if Chrome rejects the physical key transition.
    if (down) {
      this.#input.enterDispatchStarted = true;
    }
    if (this.#callHostKey("Enter", down) !== 1) {
      if (down) {
        this.#input.enterDispatchStarted = false;
      }
      record.reason = "Chrome rejected a clipboard Enter transition";
      appendBounded(this.#input.rejectedKeyRecords, record);
      this.#publishState();
      return;
    }
    event.preventDefault();
    this.#input.enterHeld = down;
    record.accepted = true;
    record.defaultPrevented = event.defaultPrevented;
    appendBounded(this.#input.enterRecords, record);
    if (!down) {
      this.#input.enterComplete = true;
      this.#setState("awaiting-native-navigation");
      this.#advancePresentationState();
    } else {
      this.#publishState();
    }
  }

  #releaseHeldEnter(reason) {
    if (!this.#input.enterHeld) {
      return;
    }
    const accepted = this.#callHostKey("Enter", false) === 1;
    appendBounded(this.#input.keyCleanupRecords, {reason, code: "Enter", accepted});
    this.#input.enterHeld = false;
    this.#publishState();
  }

  #handleSeedClick(event) {
    const record = {
      trusted: event.isTrusted === true,
      cancelable: event.cancelable === true,
      state: this.#state,
      defaultPrevented: false,
      writeRequested: false,
      writeSucceeded: false,
      reason: null,
    };
    if (!record.trusted || !record.cancelable ||
        this.#state !== "awaiting-trusted-dom-clipboard-seed" ||
        !this.#input.focusPresentationObserved || this.#seedButton.disabled ||
        !this.#clipboardSnapshot().attached) {
      record.reason = "test-clipboard seed click is not a fresh trusted gate";
      appendBounded(this.#input.seedRecords, record);
      this.#publishState();
      return;
    }
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
      record.reason = "test-clipboard write API is unavailable";
      appendBounded(this.#input.seedRecords, record);
      this.#input.seedWriteFailed = true;
      this.#recordFatal(record.reason);
      this.#setState("test-clipboard-seed-failed");
      return;
    }

    this.#input.seedButtonTrustedClicked = true;
    this.#input.seedButtonClickCancelable = true;
    this.#input.seedWriteRequested = true;
    this.#seedButton.disabled = true;
    // The test-only clipboard write happens synchronously inside the trusted
    // button event. Production adapters never call navigator.clipboard.
    let writePromise;
    try {
      writePromise = navigator.clipboard.writeText(ADDRESS_TEXT);
      record.writeRequested = true;
      event.preventDefault();
      record.defaultPrevented = event.defaultPrevented;
      this.#input.seedButtonDefaultPrevented = record.defaultPrevented;
    } catch (error) {
      record.reason = `test-clipboard write threw: ${String(error)}`;
      appendBounded(this.#input.seedRecords, record);
      this.#input.seedWriteFailed = true;
      this.#recordFatal(record.reason);
      this.#setState("test-clipboard-seed-failed");
      return;
    }

    this.#setState("test-clipboard-seed-writing");
    Promise.resolve(writePromise).then(
        () => {
          if (this.#state !== "test-clipboard-seed-writing" || document.hidden) {
            record.reason = "test clipboard seed lost its active host lifetime";
            appendBounded(this.#input.seedRecords, record);
            this.#input.seedWriteFailed = true;
            this.#recordFatal(record.reason);
            this.#setState("test-clipboard-seed-failed");
            return;
          }
          this.#proxy.focus({preventScroll: true});
          if (document.activeElement !== this.#proxy) {
            record.reason = "clipboard proxy did not regain focus after seed";
            appendBounded(this.#input.seedRecords, record);
            this.#input.seedWriteFailed = true;
            this.#recordFatal(record.reason);
            this.#setState("test-clipboard-seed-failed");
            return;
          }
          record.writeSucceeded = true;
          this.#input.seedWriteSucceeded = true;
          this.#input.proxyFocusedAfterSeed = true;
          appendBounded(this.#input.seedRecords, record);
          this.#setState("awaiting-trusted-dom-clipboard-paste");
        },
        (error) => {
          record.reason = `test-clipboard write rejected: ${String(error)}`;
          appendBounded(this.#input.seedRecords, record);
          this.#input.seedWriteFailed = true;
          this.#recordFatal(record.reason);
          this.#setState("test-clipboard-seed-failed");
        });
  }

  #recordNativeClipboardDelivery(report) {
    if (!this.#input.seedWriteSucceeded || this.#input.clipboardDeliveryObserved ||
        report.requestId !== 1 || report.accepted !== true) {
      this.#recordFatal("clipboard native delivery did not match the trusted paste");
      return;
    }
    this.#input.clipboardDeliveryObserved = true;
    this.#input.clipboardDeliveryAccepted = true;
    this.#input.clipboardDeliveryRequestId = report.requestId;
    this.#queuePasteCheckAfterNativeDelivery();
    this.#setState("awaiting-native-clipboard-paste-verification");
  }

  #attachDomInput() {
    this.#onCanvasKeyDown = (event) => this.#handleCanvasKey(event, true);
    this.#onCanvasKeyUp = (event) => this.#handleCanvasKey(event, false);
    this.#onProxyKeyDown = (event) => {
      if (event.code === "Enter") {
        this.#handleProxyEnter(event, true);
      }
    };
    this.#onProxyKeyUp = (event) => {
      if (event.code === "Enter") {
        this.#handleProxyEnter(event, false);
      }
    };
    this.#onCanvasBlur = () => {
      if (!this.#input.ctrlLComplete && this.#input.ctrlLIndex !== 0) {
        this.#recordFatal("canvas lost focus during the bounded Ctrl+L transaction");
      }
    };
    this.#onProxyBlur = () => this.#releaseHeldEnter("clipboard-proxy-blur");
    this.#onWindowBlur = () => this.#releaseHeldEnter("window-blur");
    this.#onVisibilityChange = () => {
      if (document.hidden) {
        this.#releaseHeldEnter("document-hidden");
      }
    };
    this.#onSeedClick = (event) => this.#handleSeedClick(event);
    this.#canvas.addEventListener("keydown", this.#onCanvasKeyDown);
    this.#canvas.addEventListener("keyup", this.#onCanvasKeyUp);
    this.#canvas.addEventListener("blur", this.#onCanvasBlur);
    this.#proxy.addEventListener("keydown", this.#onProxyKeyDown);
    this.#proxy.addEventListener("keyup", this.#onProxyKeyUp);
    this.#proxy.addEventListener("blur", this.#onProxyBlur);
    window.addEventListener("blur", this.#onWindowBlur);
    document.addEventListener("visibilitychange", this.#onVisibilityChange);
    this.#seedButton.addEventListener("click", this.#onSeedClick);
  }

  #detachDomInput() {
    this.#releaseHeldEnter("teardown");
    if (!this.#onCanvasKeyDown) {
      return;
    }
    this.#canvas.removeEventListener("keydown", this.#onCanvasKeyDown);
    this.#canvas.removeEventListener("keyup", this.#onCanvasKeyUp);
    this.#canvas.removeEventListener("blur", this.#onCanvasBlur);
    this.#proxy.removeEventListener("keydown", this.#onProxyKeyDown);
    this.#proxy.removeEventListener("keyup", this.#onProxyKeyUp);
    this.#proxy.removeEventListener("blur", this.#onProxyBlur);
    window.removeEventListener("blur", this.#onWindowBlur);
    document.removeEventListener("visibilitychange", this.#onVisibilityChange);
    this.#seedButton.removeEventListener("click", this.#onSeedClick);
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied an invalid Module object");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#clipboardInput = new ChromiumWasmTrustedClipboardInput(this.#proxy, {
      getModule: () => this.#module,
      reportFatal: (message) => this.#recordFatal(message),
      onStateChange: () => this.#publishState(),
      onNativeDelivery: (report) => this.#recordNativeClipboardDelivery(report),
    });
    this.#clipboardInput.attach();
    const latestState = this.#textInputStates.at(-1);
    if (latestState) {
      this.#clipboardInput.handleOzoneTextInputState(latestState);
    }
    this.#updateReadyState();
  }

  #result(status, error) {
    const clipboard = this.#clipboardSnapshot();
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m7GateComplete: false,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocusedAtStart: this.#input.ctrlLRecords[0]?.canvasFocused === true,
      proxyFocused: clipboard.proxyFocused,
      normalCloseObserved: this.#runtimeExitCode === 0 && this.#input.passObserved,
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
      ozoneCursorReports: this.#cursorReports,
      hostInput: {
        ...this.#input,
        ...clipboard,
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
        throw new Error("host-clipboard smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("host-clipboard timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("host-clipboard module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("host-clipboard canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      this.#attachDomInput();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("host-clipboard module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("host-clipboard loader has no default factory export");
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
        throw new Error("host-clipboard smoke did not exit before timeout");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#clipboardInput?.detach();
      this.#clipboardInput = null;
      this.#detachDomInput();
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
  require(result.runtimeExitCode === 0, "runtime did not close normally");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocusedAtStart === true, "canvas was not focused for Ctrl+L");
  require(result.proxyFocused === true, "clipboard proxy lost focus before close");
  require(result.normalCloseObserved === true, "normal native close was not observed");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
      "host recorded an unhandled rejection");
  const input = result.hostInput;
  for (const field of [
    "readyObserved", "focusCheckQueued", "focusObserved",
    "focusPresentationObserved", "seedButtonTrustedClicked",
    "seedWriteRequested", "seedWriteSucceeded", "proxyFocusedAfterSeed",
    "clipboardDeliveryObserved", "clipboardDeliveryAccepted", "pasteCheckQueued",
    "pastedObserved", "pastedPresentationObserved", "enterDispatchStarted",
    "enterComplete",
    "navigatedObserved", "navigationPresentationObserved",
    "navigationCheckQueued", "passObserved",
  ]) {
    require(input?.[field] === true, `host clipboard ${field} is not true`);
  }
  require(input?.seedWriteFailed === false, "test clipboard seed failed");
  require(input?.clipboardDeliveryRequestId === 1,
      "clipboard delivery request ID is invalid");
  require(JSON.stringify(input?.ordinalChecks) === JSON.stringify([1, 2, 3]),
      "clipboard observer ordinals are not exactly ordered");
  require(Array.isArray(input?.pasteRecords) && input.pasteRecords.length === 1,
      "trusted DOM paste record is absent");
  require(input?.pasteRecords?.[0]?.trusted === true &&
      input?.pasteRecords?.[0]?.cancelable === true &&
      input?.pasteRecords?.[0]?.admitted === true &&
      input?.pasteRecords?.[0]?.defaultPrevented === true,
  "trusted DOM paste was not admitted and prevented");
  require(input?.proxyTextEmpty === true,
      "clipboard proxy retained pasted DOM text");
  require(input?.pendingRequestId === null,
      "clipboard adapter retained a pending request at close");
  require(input?.rejectedRecords?.length === 0,
      "clipboard adapter rejected the tested paste");
  require(input?.cleanupRecords?.length === 0,
      "clipboard adapter unexpectedly cleaned up the tested paste");
  require(input?.rejectedKeyRecords?.length === 0,
      "host rejected a tested physical key");
  for (const [marker, frame] of [
    [input?.focusMarkerFrameId, input?.frameIdAfterFocus],
    [input?.pastedMarkerFrameId, input?.frameIdAfterPaste],
    [input?.navigationMarkerFrameId, input?.frameIdAfterNavigation],
  ]) {
    require(Number.isSafeInteger(marker) && Number.isSafeInteger(frame) && frame > marker,
        "marker lacks a later compositor frame");
  }
  const stderr = Array.isArray(result.stderr) ? result.stderr.join("\n") : "";
  for (const marker of [READY_MARKER, FOCUSED_MARKER, PASTED_MARKER,
    NAVIGATED_MARKER, PASS_MARKER]) {
    require(stderr.includes(marker), `stderr is missing ${marker}`);
  }
  result.failedChecks = failures;
  if (failures.length > 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserHostClipboardSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-host-clipboard-root");
  const canvas = document.querySelector("#browser-canvas");
  const proxy = document.querySelector("#browser-clipboard-proxy");
  const seedButton = document.querySelector("#clipboard-seed");
  const status = document.querySelector("#browser-host-clipboard-status");
  const versionsElement = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(proxy instanceof HTMLTextAreaElement) ||
      !(seedButton instanceof HTMLButtonElement) || !(status instanceof HTMLElement)) {
    throw new Error("host-clipboard page is missing required elements");
  }
  renderVersions(versionsElement, versions);
  const host = new ChromiumWasmBrowserHostClipboardSmokeHost(
      canvas, proxy, seedButton, versions);
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

export const chromeWasmBrowserHostClipboardSmokeContract = Object.freeze({
  ADDRESS_TEXT,
  CASE,
  FOCUSED_MARKER,
  HOST_PROTOCOL,
  NAVIGATED_MARKER,
  PASTED_MARKER,
  PASS_MARKER,
  READY_MARKER,
  SCOPE,
  SWITCH,
});

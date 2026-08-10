// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This lane proves the product trusted-DOM pointer adapter, not a host-side
// dialog. The outer browser sends physical mouse records only. C++ owns the
// actual BrowserView menu, WCMDM constrained child Widget, blocked tab state,
// dismissal, and ordinary Browser shutdown.

import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";

const HOST_PROTOCOL = 1;
const CASE = "browser_host_security_warning_m6";
const SCOPE =
    "trusted-dom-pointer-ozone-aura-views-constrained-security-warning";
const SWITCH = "--wasm-browser-host-security-warning-smoke";
const READY_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:READY";
const MENU_OPEN_MARKER =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:MENU_OPEN";
const MENU_PRESENTED_MARKER =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:MENU_PRESENTED";
const DIALOG_OPEN_MARKER =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_OPEN";
const DIALOG_INTERACTION_READY_MARKER =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_INTERACTION_READY";
const DIALOG_DISMISSED_MARKER =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:DIALOG_DISMISSED";
const OBSERVATION_FAILED_MARKER =
    "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:OBSERVATION_FAILED";
const PASS_MARKER = "CHROMIUM_WASM_M6_HOST_SECURITY_WARNING:PASS";
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
    throw new Error(`invalid security-warning versions: ${String(error)}`);
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("security-warning page is missing its version element");
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

class ChromiumWasmBrowserHostSecurityWarningSmokeHost {
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
  #runtimeExitPromise;
  #runtimeExitResolver;
  #frameReports = [];
  #readinessReports = [];
  #readiness = null;
  #focusReports = [];
  #errorHandler;
  #rejectionHandler;
  #input = {
    attached: false,
    readyObserved: false,
    menuOpenedObserved: false,
    menuPresentedObserved: false,
    dialogOpenedObserved: false,
    dialogInteractionReadyObserved: false,
    dialogDismissedObserved: false,
    passObserved: false,
    menuTarget: null,
    warningTarget: null,
    dismissTarget: null,
    frameIdAtMenuOpenedMarker: null,
    frameIdAfterMenuOpen: null,
    frameIdAtWarningAction: null,
    frameIdAfterWarningAction: null,
    frameIdAtDialogOpenedMarker: null,
    frameIdAfterDialogOpen: null,
    frameIdAtDialogInteractionReadyMarker: null,
    frameIdAfterDialogInteractionReady: null,
    frameIdAtDismissAction: null,
    frameIdAfterDismissAction: null,
    frameIdAtDialogDismissedMarker: null,
    frameIdAfterDialogDismiss: null,
    menuCheckQueued: false,
    menuPresentationQueued: false,
    dialogCheckQueued: false,
    dismissCheckQueued: false,
    presentationQueued: false,
    pointerRecords: [],
  };

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("security-warning smoke requires a canvas");
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

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code) || this.#runtimeExitCode !== null) {
      this.#recordFatal(`invalid or duplicate runtime exit: ${String(code)}`);
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
      // The present import can be synchronous from C++. Only schedule an
      // ordinal after it returns; never re-enter Wasm from this callback.
      this.#advancePresentationState();
      this.#maybeRequestChecks();
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
        throw new Error("focus report is invalid");
      }
      appendBounded(this.#focusReports, {
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      });
    } catch (error) {
      this.#recordFatal(`invalid Ozone focus report: ${String(error)}`);
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("security-warning bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportOzoneFocusState(report) { host.#reportFocus(report); },
      reportOzoneCursor() { return true; },
      reportOzoneTextInputDelivery() {},
      reportOzoneTextInputState() {},
      reportOzoneBrowserTextInputDelivery() {},
    });
  }

  #currentFrameId() {
    return this.#frameReports.at(-1)?.id ?? 0;
  }

  #firstFrameAfter(frameId) {
    return this.#frameReports.find((frame) => frame.id > frameId) ?? null;
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
    globalThis.__chromiumWasmM6HostSecurityWarningState = Object.freeze({
      state,
      attached: input.attached,
      readyObserved: input.readyObserved,
      menuOpenedObserved: input.menuOpenedObserved,
      menuPresentedObserved: input.menuPresentedObserved,
      dialogOpenedObserved: input.dialogOpenedObserved,
      dialogInteractionReadyObserved: input.dialogInteractionReadyObserved,
      dialogDismissedObserved: input.dialogDismissedObserved,
      passObserved: input.passObserved,
      menuTarget: input.menuTarget,
      warningTarget: input.warningTarget,
      dismissTarget: input.dismissTarget,
      frameIdAtMenuOpenedMarker: input.frameIdAtMenuOpenedMarker,
      frameIdAfterMenuOpen: input.frameIdAfterMenuOpen,
      frameIdAtWarningAction: input.frameIdAtWarningAction,
      frameIdAfterWarningAction: input.frameIdAfterWarningAction,
      frameIdAtDialogOpenedMarker: input.frameIdAtDialogOpenedMarker,
      frameIdAfterDialogOpen: input.frameIdAfterDialogOpen,
      frameIdAtDialogInteractionReadyMarker:
          input.frameIdAtDialogInteractionReadyMarker,
      frameIdAfterDialogInteractionReady:
          input.frameIdAfterDialogInteractionReady,
      frameIdAtDismissAction: input.frameIdAtDismissAction,
      frameIdAfterDismissAction: input.frameIdAfterDismissAction,
      frameIdAtDialogDismissedMarker: input.frameIdAtDialogDismissedMarker,
      frameIdAfterDialogDismiss: input.frameIdAfterDialogDismiss,
      menuCheckQueued: input.menuCheckQueued,
      menuPresentationQueued: input.menuPresentationQueued,
      dialogCheckQueued: input.dialogCheckQueued,
      dismissCheckQueued: input.dismissCheckQueued,
      presentationQueued: input.presentationQueued,
    });
  }

  #deferVerifier(exportName, stage, queuedField) {
    if (this.#input[queuedField]) {
      return;
    }
    this.#input[queuedField] = true;
    this.#publishState("verifier-callback-deferred");
    setTimeout(() => {
      if (!this.#module || !this.#input.attached ||
          typeof this.#module.ccall !== "function") {
        this.#recordFatal(`${exportName} ran without an attached Module ccall`);
        return;
      }
      try {
        const result = this.#module.ccall(
            exportName, "number", ["number"], [stage]);
        if (result !== 1) {
          this.#recordFatal(`${exportName} rejected stage ${stage}`);
        }
      } catch (error) {
        this.#recordFatal(`${exportName} failed: ${String(error)}`);
      }
      this.#advancePresentationState();
      this.#maybeRequestChecks();
      this.#updateState();
    }, 0);
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

  #maybeRequestChecks() {
    if (!this.#input.menuCheckQueued &&
        this.#acceptedActionPairForTarget(this.#input.menuTarget)) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_security_warning_check", 1,
          "menuCheckQueued");
      return;
    }
    if (this.#input.menuPresentedObserved &&
        this.#input.frameIdAfterMenuOpen !== null &&
        !this.#input.dialogCheckQueued &&
        this.#acceptedActionPairForTarget(this.#input.warningTarget)) {
      if (this.#input.frameIdAtWarningAction === null) {
        this.#input.frameIdAtWarningAction = this.#currentFrameId();
        this.#updateState();
        return;
      }
      if (this.#input.frameIdAfterWarningAction === null) {
        return;
      }
      this.#deferVerifier(
          "chromium_wasm_browser_host_security_warning_check", 2,
          "dialogCheckQueued");
      return;
    }
    if (this.#input.dialogOpenedObserved &&
        this.#input.frameIdAfterDialogOpen !== null &&
        this.#input.dialogInteractionReadyObserved &&
        this.#input.frameIdAfterDialogInteractionReady !== null &&
        !this.#input.dismissCheckQueued &&
        this.#acceptedActionPairForTarget(this.#input.dismissTarget)) {
      if (this.#input.frameIdAtDismissAction === null) {
        this.#input.frameIdAtDismissAction = this.#currentFrameId();
        this.#updateState();
        return;
      }
      if (this.#input.frameIdAfterDismissAction === null) {
        return;
      }
      this.#deferVerifier(
          "chromium_wasm_browser_host_security_warning_check", 3,
          "dismissCheckQueued");
    }
  }

  #advancePresentationState() {
    if (this.#input.menuOpenedObserved &&
        this.#input.frameIdAfterMenuOpen === null &&
        this.#input.frameIdAtMenuOpenedMarker !== null) {
      const frame = this.#firstFrameAfter(this.#input.frameIdAtMenuOpenedMarker);
      if (frame) {
        this.#input.frameIdAfterMenuOpen = frame.id;
      }
    }
    if (this.#input.dialogOpenedObserved &&
        this.#input.frameIdAfterDialogOpen === null &&
        this.#input.frameIdAtDialogOpenedMarker !== null) {
      const frame = this.#firstFrameAfter(
          this.#input.frameIdAtDialogOpenedMarker);
      if (frame) {
        this.#input.frameIdAfterDialogOpen = frame.id;
      }
    }
    if (this.#input.dialogInteractionReadyObserved &&
        this.#input.frameIdAfterDialogInteractionReady === null &&
        this.#input.frameIdAtDialogInteractionReadyMarker !== null) {
      const frame = this.#firstFrameAfter(
          this.#input.frameIdAtDialogInteractionReadyMarker);
      if (frame) {
        this.#input.frameIdAfterDialogInteractionReady = frame.id;
      }
    }
    if (this.#input.frameIdAtWarningAction !== null &&
        this.#input.frameIdAfterWarningAction === null) {
      const frame = this.#firstFrameAfter(this.#input.frameIdAtWarningAction);
      if (frame) {
        this.#input.frameIdAfterWarningAction = frame.id;
      }
    }
    if (this.#input.frameIdAtDismissAction !== null &&
        this.#input.frameIdAfterDismissAction === null) {
      const frame = this.#firstFrameAfter(this.#input.frameIdAtDismissAction);
      if (frame) {
        this.#input.frameIdAfterDismissAction = frame.id;
      }
    }
    if (this.#input.dialogDismissedObserved &&
        this.#input.frameIdAfterDialogDismiss === null &&
        this.#input.frameIdAtDialogDismissedMarker !== null) {
      const frame = this.#firstFrameAfter(
          this.#input.frameIdAtDialogDismissedMarker);
      if (frame) {
        this.#input.frameIdAfterDialogDismiss = frame.id;
      }
    }
    if (this.#input.menuOpenedObserved &&
        this.#input.frameIdAfterMenuOpen !== null &&
        !this.#input.menuPresentationQueued) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_security_warning_presented", 1,
          "menuPresentationQueued");
    }
    if (this.#input.dialogDismissedObserved &&
        this.#input.frameIdAfterDialogDismiss !== null &&
        !this.#input.presentationQueued) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_security_warning_presented", 2,
          "presentationQueued");
    }
    this.#updateState();
  }

  #updateState() {
    if (this.#input.passObserved) {
      this.#publishState("pass-observed");
      return;
    }
    if (this.#input.dialogDismissedObserved) {
      this.#publishState(this.#input.presentationQueued ?
          "awaiting-orderly-shutdown" : "awaiting-post-dismiss-frame");
      return;
    }
    if (this.#input.dialogOpenedObserved) {
      if (this.#input.frameIdAfterDialogOpen === null) {
        this.#publishState("awaiting-post-dialog-frame");
        return;
      }
      if (!this.#input.dialogInteractionReadyObserved) {
        this.#publishState("awaiting-dialog-interaction-ready");
        return;
      }
      if (this.#input.frameIdAfterDialogInteractionReady === null) {
        this.#publishState("awaiting-post-dialog-interaction-ready-frame");
        return;
      }
      if (this.#input.frameIdAtDismissAction !== null &&
          this.#input.frameIdAfterDismissAction === null) {
        this.#publishState("awaiting-post-dismiss-action-frame");
        return;
      }
      this.#publishState("awaiting-trusted-dom-dismiss");
      return;
    }
    if (this.#input.menuOpenedObserved) {
      if (!this.#input.menuPresentationQueued ||
          !this.#input.menuPresentedObserved) {
        this.#publishState(this.#input.frameIdAfterMenuOpen !== null ?
            "awaiting-menu-presentation" : "awaiting-post-menu-frame");
        return;
      }
      if (this.#input.frameIdAtWarningAction !== null &&
          this.#input.frameIdAfterWarningAction === null) {
        this.#publishState("awaiting-post-security-warning-action-frame");
        return;
      }
      this.#publishState(this.#input.frameIdAfterMenuOpen !== null ?
          "awaiting-trusted-dom-security-warning" :
          "awaiting-post-menu-frame");
      return;
    }
    if (this.#module && this.#input.attached && this.#input.readyObserved) {
      this.#publishState("awaiting-trusted-dom-menu");
    }
  }

  #recordOutput(text) {
    try {
      if (text.includes(OBSERVATION_FAILED_MARKER)) {
        throw new Error(`bounded post-input observation failed: ${text}`);
      }
      const ready = parseTargetMarker(text, READY_MARKER);
      if (ready) {
        if (this.#input.readyObserved) {
          throw new Error("received duplicate security-warning READY marker");
        }
        const target = this.#targetForClientPoint(ready);
        if (!target) {
          throw new Error("security-warning Menu target cannot map to canvas");
        }
        this.#input.readyObserved = true;
        this.#input.menuTarget = target;
      }
      const warning = parseTargetMarker(text, MENU_OPEN_MARKER);
      if (warning) {
        if (!this.#input.menuCheckQueued || this.#input.menuOpenedObserved) {
          throw new Error("security-warning Menu-open marker is out of order");
        }
        const target = this.#targetForClientPoint(warning);
        if (!target) {
          throw new Error("security-warning target cannot map to canvas");
        }
        this.#input.menuOpenedObserved = true;
        this.#input.warningTarget = target;
        this.#input.frameIdAtMenuOpenedMarker = this.#currentFrameId();
      }
      if (text.includes(MENU_PRESENTED_MARKER)) {
        if (!this.#input.menuPresentationQueued ||
            this.#input.menuPresentedObserved) {
          throw new Error("security-warning Menu presentation is out of order");
        }
        this.#input.menuPresentedObserved = true;
      }
      const dismiss = parseTargetMarker(text, DIALOG_OPEN_MARKER);
      if (dismiss) {
        if (!this.#input.dialogCheckQueued || this.#input.dialogOpenedObserved) {
          throw new Error("security-warning Dialog-open marker is out of order");
        }
        if (!this.#targetForClientPoint(dismiss)) {
          throw new Error("Dismiss target cannot map to canvas");
        }
        this.#input.dialogOpenedObserved = true;
        this.#input.frameIdAtDialogOpenedMarker = this.#currentFrameId();
      }
      const interactionReady = parseTargetMarker(
          text, DIALOG_INTERACTION_READY_MARKER);
      if (interactionReady) {
        if (!this.#input.dialogOpenedObserved ||
            this.#input.dialogInteractionReadyObserved ||
            this.#input.dialogDismissedObserved) {
          throw new Error("security-warning dialog interaction readiness is out of order");
        }
        const target = this.#targetForClientPoint(interactionReady);
        if (!target) {
          throw new Error("fresh Dismiss target cannot map to canvas");
        }
        this.#input.dialogInteractionReadyObserved = true;
        this.#input.dismissTarget = target;
        this.#input.frameIdAtDialogInteractionReadyMarker =
            this.#currentFrameId();
      }
      if (text.includes(DIALOG_DISMISSED_MARKER)) {
        if (!this.#input.dialogInteractionReadyObserved ||
            !this.#input.dismissCheckQueued ||
            this.#input.dialogDismissedObserved) {
          throw new Error("security-warning dismissal marker is out of order");
        }
        this.#input.dialogDismissedObserved = true;
        this.#input.frameIdAtDialogDismissedMarker = this.#currentFrameId();
      }
      if (text.includes(PASS_MARKER)) {
        if (!this.#input.presentationQueued || this.#input.passObserved) {
          throw new Error("security-warning PASS marker is out of order");
        }
        this.#input.passObserved = true;
      }
      this.#advancePresentationState();
      this.#maybeRequestChecks();
      this.#updateState();
    } catch (error) {
      this.#recordFatal(`invalid security-warning output: ${String(error)}`);
    }
  }

  #recordPointer(record) {
    appendBounded(this.#input.pointerRecords, record);
    this.#maybeRequestChecks();
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
      hostInput: {...this.#input},
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
        throw new Error("security-warning smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("security-warning timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("security-warning module must use host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("security-warning canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("security-warning module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("security-warning loader has no default factory export");
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
        throw new Error("security-warning smoke did not exit before timeout");
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

function acceptedPointerPair(records, target, offset) {
  const pair = records.filter((record) =>
    record.type === "down" || record.type === "up").slice(offset, offset + 2);
  if (pair.length !== 2 || !target) {
    return false;
  }
  const [down, up] = pair;
  const exact = (record) => record.trusted === true &&
      record.cancelable === true && record.pointerType === "mouse" &&
      record.primary === true && record.accepted === true &&
      record.defaultPrevented === true && record.x === target.x &&
      record.y === target.y;
  return exact(down) && exact(up) && down.type === "down" &&
      down.button === 0 && down.buttons === 1 && up.type === "up" &&
      up.button === 0 && (up.buttons & 1) === 0;
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
  require(result.frameReports.length >= 4, "too few host-canvas frames");
  require(result.readiness?.surfaceReady === true,
      "surface readiness was not reported");
  require(result.ozoneFocusReports.some((report) =>
    report.keyboardTargetPresent === true && report.active === true),
  "no active Ozone keyboard target was observed");
  const input = result.hostInput;
  for (const field of [
    "attached", "readyObserved", "menuOpenedObserved", "menuPresentedObserved",
    "dialogOpenedObserved", "dialogInteractionReadyObserved",
    "dialogDismissedObserved", "passObserved",
    "menuCheckQueued", "menuPresentationQueued", "dialogCheckQueued",
    "dismissCheckQueued", "presentationQueued",
  ]) {
    require(input?.[field] === true, `host input ${field} is not true`);
  }
  require(input?.frameIdAfterMenuOpen > input?.frameIdAtMenuOpenedMarker,
      "menu open has no later presented frame");
  require(input?.frameIdAfterWarningAction > input?.frameIdAtWarningAction,
      "security-warning action has no later presented frame");
  require(input?.frameIdAfterDialogOpen > input?.frameIdAtDialogOpenedMarker,
      "dialog open has no later presented frame");
  require(input?.frameIdAfterDialogInteractionReady >
      input?.frameIdAtDialogInteractionReadyMarker,
  "dialog interaction readiness has no later presented frame");
  require(input?.frameIdAfterDismissAction > input?.frameIdAtDismissAction,
      "Dismiss action has no later presented frame");
  require(input?.frameIdAfterDialogDismiss >
      input?.frameIdAtDialogDismissedMarker,
  "dialog dismissal has no later presented frame");
  // The action is dispatched after the host has consumed the prior frame, so
  // it may retain that frame's ID. The independently recorded post-action
  // frame above remains strictly later.
  require(input?.frameIdAtWarningAction >= input?.frameIdAfterMenuOpen,
      "security-warning click did not wait for menu presentation");
  require(input?.frameIdAtDialogOpenedMarker >=
      input?.frameIdAfterWarningAction,
  "dialog check did not wait for security-warning action presentation");
  require(input?.frameIdAtDismissAction >= input?.frameIdAfterDialogOpen,
      "Dismiss click did not wait for dialog presentation");
  require(input?.frameIdAtDismissAction >=
      input?.frameIdAfterDialogInteractionReady,
  "Dismiss click did not wait for interaction readiness presentation");
  require(input?.frameIdAtDialogDismissedMarker >=
      input?.frameIdAfterDismissAction,
  "dismiss check did not wait for Dismiss action presentation");
  const records = input?.pointerRecords;
  require(Array.isArray(records), "pointer records are missing");
  if (Array.isArray(records)) {
    require(!records.some((record) => record.accepted !== true),
        "host rejected an outer trusted pointer record");
    const actions = records.filter((record) =>
      record.type === "down" || record.type === "up");
    require(actions.length === 6, "host did not record exactly three pointer clicks");
    require(acceptedPointerPair(records, input?.menuTarget, 0),
        "trusted Menu pointer pair is invalid");
    require(acceptedPointerPair(records, input?.warningTarget, 2),
        "trusted Security warning pointer pair is invalid");
    require(acceptedPointerPair(records, input?.dismissTarget, 4),
        "trusted Dismiss pointer pair is invalid");
  }
  result.failedChecks = failures;
  if (failures.length) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserHostSecurityWarningSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-host-security-warning-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-host-security-warning-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("security-warning page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserHostSecurityWarningSmokeHost(
      canvas, versions);
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

export const chromeWasmBrowserHostSecurityWarningSmokeContract = Object.freeze({
  CASE,
  DIALOG_DISMISSED_MARKER,
  DIALOG_OPEN_MARKER,
  HOST_PROTOCOL,
  MENU_OPEN_MARKER,
  MENU_PRESENTED_MARKER,
  OBSERVATION_FAILED_MARKER,
  PASS_MARKER,
  READY_MARKER,
  SCOPE,
  SWITCH,
});

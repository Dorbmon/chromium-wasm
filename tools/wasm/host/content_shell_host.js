// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const HOST_PROTOCOL = 1;
const M3_CASE = "content_shell_m3";
const M4_CASE = "ozone_pointer_m4";
const M4_WHEEL_CASE = "ozone_wheel_m4";
const M4_KEYBOARD_CASE = "ozone_keyboard_m4";
const M4_PRINTABLE_KEY_CASE = "ozone_printable_key_m4";
const M4_FOCUS_CASE = "ozone_focus_m4";
const M4_IME_BRIDGE_CASE = "ozone_ime_bridge_m4";
const M4_FIXTURE = "chromium-wasm-m4-ozone-pointer-v1";
const M4_WHEEL_FIXTURE = "chromium-wasm-m4-ozone-wheel-v1";
const M4_KEYBOARD_FIXTURE = "chromium-wasm-m4-ozone-keyboard-v1";
const M4_PRINTABLE_KEY_FIXTURE =
  "chromium-wasm-m4-ozone-printable-key-v1";
const M4_FOCUS_FIXTURE = "chromium-wasm-m4-ozone-focus-v1";
const M4_IME_BRIDGE_FIXTURE = "chromium-wasm-m4-ozone-ime-bridge-v1";
const M4_KEYBOARD_DOM_CODE = "ArrowDown";
const M4_PRINTABLE_KEY_DOM_CODE = "KeyA";
const M4_PRINTABLE_KEY_DOM_KEY = "a";
const FIXTURE_FONT_MARKER = "__M3_AHEM_WOFF2_BASE64__";
const REQUIRED_RUNTIME_MS = 3000;
const REQUIRED_TIMER_TICKS = 60;
const REQUIRED_ANIMATION_FRAMES = 30;
const MAXIMUM_TIMER_GAP_MS = 250;
const DEFAULT_RUNTIME_REGISTRATION_TIMEOUT_MS = 15000;
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 15000;
const DEFAULT_WIDTH = 800;
const DEFAULT_HEIGHT = 600;
const POST_INPUT_REDRAW_WIDTH = DEFAULT_WIDTH - 1;
const WASM_PAGE_BYTES = 64 * 1024;
const MAXIMUM_WHEEL_DELTA = 0x7fffffff;
const MAXIMUM_IME_PROXY_TEXT_UNITS = 64 * 1024;
const MAXIMUM_IME_PROXY_TEXT_BYTES = MAXIMUM_IME_PROXY_TEXT_UNITS * 3;
const M4_IME_TEXT_ACTION = Object.freeze({
  setComposition: 1,
  confirmComposition: 2,
  clearComposition: 3,
});
const UTF8_ENCODER = new TextEncoder();

let activeHost = null;
const pendingBridgeReports = [];

function expectedM4KeyboardKey(code) {
  switch (code) {
    case M4_KEYBOARD_DOM_CODE:
      return M4_KEYBOARD_DOM_CODE;
    case M4_PRINTABLE_KEY_DOM_CODE:
      return M4_PRINTABLE_KEY_DOM_KEY;
    default:
      return null;
  }
}

function isWellFormedUtf16(value) {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) {
        return false;
      }
      index += 1;
      continue;
    }
    if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return false;
    }
  }
  return true;
}

function imeProxyTextSummary(value) {
  return {
    utf16Length: value.length,
    utf8Bytes: UTF8_ENCODER.encode(value).byteLength,
    codePointCount: Array.from(value).length,
  };
}

// The IME smoke deliberately verifies the non-BMP candidate by shape rather
// than placing user-entered text in host diagnostics.
function isM4ImeSmokeTextSummary(value) {
  return value?.utf16Length === 2 &&
      value?.utf8Bytes === 4 && value?.codePointCount === 1;
}

function isEmptyM4ImeTextSummary(value) {
  return value?.utf16Length === 0 &&
      value?.utf8Bytes === 0 && value?.codePointCount === 0;
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

function deliverBridgeReport(method, args) {
  if (activeHost) {
    activeHost[method](...args);
  } else {
    pendingBridgeReports.push({method, args});
  }
}

// The Ozone and Content JS libraries call this versioned bridge. Reports are
// queued until initialize() owns the single M3 host instance.
globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
  protocol: HOST_PROTOCOL,
  reportFrame(report) {
    deliverBridgeReport("_reportFrame", [report]);
  },
  reportReadiness(report) {
    deliverBridgeReport("_reportReadiness", [report]);
  },
  reportNavigation(report) {
    deliverBridgeReport("_reportNavigation", [report]);
  },
  reportPageProbe(report) {
    deliverBridgeReport("_reportPageProbe", [report]);
  },
  reportOzoneFocusState(report) {
    deliverBridgeReport("_reportOzoneFocusState", [report]);
  },
  reportOzoneTextInputState(report) {
    deliverBridgeReport("_reportOzoneTextInputState", [report]);
  },
  reportOzoneTextInputDelivery(report) {
    deliverBridgeReport("_reportOzoneTextInputDelivery", [report]);
  },
  reportFatal(message) {
    deliverBridgeReport("_reportFatal", [message]);
  },
  reportProcessExit(report) {
    deliverBridgeReport("_reportProcessExit", [report]);
  },
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function encodeBytesBase64(bytes) {
  let binary = "";
  const chunkSize = 0x4000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(
      ...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
  }
  return btoa(binary);
}

async function buildFixtureDataURL(fixturePath, fontPath) {
  const [fixtureResponse, fontResponse] = await Promise.all([
    fetch(fixturePath, {cache: "no-store"}),
    fetch(fontPath, {cache: "no-store"}),
  ]);
  if (!fixtureResponse.ok) {
    throw new Error(`fixture request returned HTTP ${fixtureResponse.status}`);
  }
  if (!fontResponse.ok) {
    throw new Error(`font request returned HTTP ${fontResponse.status}`);
  }
  const template = await fixtureResponse.text();
  if (template.split(FIXTURE_FONT_MARKER).length !== 2) {
    throw new Error("fixture must contain exactly one Ahem marker");
  }
  const font = new Uint8Array(await fontResponse.arrayBuffer());
  if (font.length === 0) {
    throw new Error("fixture Ahem font is empty");
  }
  const expanded = template.replace(
    FIXTURE_FONT_MARKER, encodeBytesBase64(font));
  return `data:text/html;charset=utf-8;base64,${
    encodeBytesBase64(new TextEncoder().encode(expanded))}`;
}

function normalizeVersion(value) {
  return typeof value === "string" && value.length > 0 ? value : "missing";
}

function renderVersions(versions) {
  const container = document.querySelector("#versions");
  container.replaceChildren();
  for (const [name, value] of [
    ["Chromium", versions.chromium],
    ["V8", versions.v8],
    ["Emscripten", versions.emscripten],
    ["Port", versions.port],
  ]) {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = name;
    description.textContent = normalizeVersion(value);
    container.append(term, description);
  }
}

function checkInteger(value, description, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(
      `${description} must be an integer in [${minimum}, ${maximum}]`);
  }
  return value;
}

export class ChromiumWasmM3Host {
  #canvas;
  #imeProxy;
  #fixture;
  #module = null;
  #lifecycle = "new";
  #runtimeInitialized = false;
  #fatalErrors = [];
  #reportedReadiness = {};
  #navigation = {};
  #pageProbe = {};
  #ozoneFocusState = null;
  #ozoneFocusReportSequence = 0;
  #ozoneTextInputState = null;
  #ozoneTextInputReportSequence = 0;
  #frame = null;
  #inputPostedAtFrameId = null;
  #interactionObservedAtFrameId = null;
  #processExit = null;
  #processExitPromise;
  #resolveProcessExit;
  #runtimeExit = null;
  #runtimeExitPromise;
  #resolveRuntimeExit;
  #exitReportSequence = 0;
  #initialLinearMemoryBytes = null;
  #versions;
  #logs = {host: [], stdout: [], stderr: []};
  #heartbeatAnchor = null;
  #heartbeatStartTime = null;
  #heartbeatStartTimerTicks = 0;
  #heartbeatStartAnimationFrameTicks = 0;
  #timerTicks = 0;
  #animationFrameTicks = 0;
  #maximumTimerGapMs = 0;
  #lastTimerTime;
  #timerHandle;
  #animationFrameHandle;
  #errorHandler;
  #rejectionHandler;
  #pointerInputEnabled = false;
  #pointerListeners = [];
  #pointerSequence = 0;
  #pointerRecords = [];
  #lastQueuedPointer = null;
  #activeM4PointerId = null;
  #lastM4PointerPoint = null;
  #wheelInputEnabled = false;
  #wheelListeners = [];
  #wheelSequence = 0;
  #wheelRecords = [];
  #lastQueuedWheel = null;
  #wheelResidualX = 0;
  #wheelResidualY = 0;
  #keyboardInputEnabled = false;
  #keyboardListeners = [];
  #keyboardSequence = 0;
  #keyboardRecords = [];
  #lastQueuedKeyDown = null;
  #lastQueuedKeyUp = null;
  #keyboardActivated = false;
  #keyboardCodesDown = new Set();
  #focusInputEnabled = false;
  #focusListeners = [];
  #focusSequence = 0;
  #focusRecords = [];
  #lastQueuedFocusLoss = null;
  #hostWindowActive = false;
  #imeProxyInputEnabled = false;
  #imeProxyListeners = [];
  #imeProxySequence = 0;
  #imeProxyRecords = [];
  #imeProxySessionId = 0;
  #imeProxyCompositionActive = false;
  #imeProxyLastCompositionText = null;
  #imeProxyPendingTransaction = null;
  #imeProxyLastConfirmedTransaction = null;
  #imeProxyLastConfirmedText = null;
  #imeProxyTerminalCancellationPending = false;
  #imeProxyExpectedTerminalAction = null;
  #imeProxyNativeRequests = [];
  #imeProxyNativeComposition = null;
  #imeProxyNativeTerminalAction = null;
  #imeProxyFailure = null;
  #imeProxyActivationRequest = null;
  #imeProxyExpectedFocusTransfer = null;
  #imeProxyFocusCount = 0;
  #imeProxyBlurCount = 0;

  constructor(
    canvas,
    versions,
    {
      fixture = "chromium-wasm-m3-static-v1",
      imeProxy = null,
    } = {},
  ) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("M3 host requires a canvas");
    }
    if (activeHost) {
      throw new Error("only one M3 host instance may be active");
    }
    this.#canvas = canvas;
    if (imeProxy !== null && !(imeProxy instanceof HTMLTextAreaElement)) {
      throw new Error("M4 IME proxy must be a textarea when supplied");
    }
    this.#imeProxy = imeProxy;
    if (typeof fixture !== "string" || fixture.length === 0) {
      throw new Error("host fixture identifier must be a nonempty string");
    }
    this.#fixture = fixture;
    this.#versions = Object.freeze({
      chromium: normalizeVersion(versions.chromium),
      v8: normalizeVersion(versions.v8),
      emscripten: normalizeVersion(versions.emscripten),
      port: normalizeVersion(versions.port),
    });
    this.#processExitPromise = new Promise((resolve) => {
      this.#resolveProcessExit = resolve;
    });
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#resolveRuntimeExit = resolve;
    });
    activeHost = this;

    this.#lastTimerTime = performance.now();
    this.#timerHandle = setInterval(() => {
      const now = performance.now();
      if (this.#heartbeatAnchor !== null) {
        this.#maximumTimerGapMs = Math.max(
          this.#maximumTimerGapMs, now - this.#lastTimerTime);
      }
      this.#lastTimerTime = now;
      this.#timerTicks += 1;
    }, 25);
    const tickAnimationFrame = () => {
      this.#animationFrameTicks += 1;
      this.#animationFrameHandle = requestAnimationFrame(tickAnimationFrame);
    };
    this.#animationFrameHandle = requestAnimationFrame(tickAnimationFrame);

    this.#errorHandler = (event) => {
      const message = event.error || event.message || "window error";
      this._reportFatal(`uncaught exception: ${String(message)}`);
    };
    this.#rejectionHandler = (event) => {
      this._reportFatal(`unhandled rejection: ${String(event.reason)}`);
    };
    addEventListener("error", this.#errorHandler);
    addEventListener("unhandledrejection", this.#rejectionHandler);

    for (const pending of pendingBridgeReports.splice(0)) {
      this[pending.method](...pending.args);
    }
  }

  #recordHost(message) {
    this.#logs.host.push(String(message));
  }

  #stopHeartbeat() {
    clearInterval(this.#timerHandle);
    cancelAnimationFrame(this.#animationFrameHandle);
  }

  #releaseHost() {
    this.#stopHeartbeat();
    this.#disableM4PointerInput();
    this.#disableM4KeyboardInput();
    this.#disableM4ImeProxyInput();
    this.#disableM4FocusInput();
    this.#disableM4WheelInput();
    removeEventListener("error", this.#errorHandler);
    removeEventListener("unhandledrejection", this.#rejectionHandler);
    if (activeHost === this) {
      activeHost = null;
    }
  }

  #resetHeartbeatWindow(anchor) {
    const now = performance.now();
    this.#heartbeatAnchor = anchor;
    this.#heartbeatStartTime = now;
    this.#heartbeatStartTimerTicks = this.#timerTicks;
    this.#heartbeatStartAnimationFrameTicks = this.#animationFrameTicks;
    this.#maximumTimerGapMs = 0;
    this.#lastTimerTime = now;
  }

  #recordPointer(record) {
    this.#pointerRecords.push(record);
    if (this.#pointerRecords.length > 32) {
      this.#pointerRecords.shift();
    }
  }

  #pointerInputStatus() {
    const queuedCount = this.#pointerRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#pointerRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#pointerInputEnabled,
      receivedCount: this.#pointerRecords.length,
      trustedCount,
      queuedCount,
      lastQueued: this.#lastQueuedPointer
        ? clone(this.#lastQueuedPointer)
        : null,
    };
  }

  #recordWheel(record) {
    this.#wheelRecords.push(record);
    if (this.#wheelRecords.length > 32) {
      this.#wheelRecords.shift();
    }
  }

  #wheelInputStatus() {
    const queuedCount = this.#wheelRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#wheelRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#wheelInputEnabled,
      receivedCount: this.#wheelRecords.length,
      trustedCount,
      queuedCount,
      lastQueued: this.#lastQueuedWheel ? clone(this.#lastQueuedWheel) : null,
    };
  }

  #recordKeyboard(record) {
    this.#keyboardRecords.push(record);
    if (this.#keyboardRecords.length > 32) {
      this.#keyboardRecords.shift();
    }
  }

  #keyboardInputStatus() {
    const queuedCount = this.#keyboardRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#keyboardRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#keyboardInputEnabled,
      activated: this.#keyboardActivated,
      receivedCount: this.#keyboardRecords.length,
      trustedCount,
      queuedCount,
      pressedCodes: Array.from(this.#keyboardCodesDown).sort(),
      lastQueuedDown: this.#lastQueuedKeyDown
        ? clone(this.#lastQueuedKeyDown)
        : null,
      lastQueuedUp: this.#lastQueuedKeyUp
        ? clone(this.#lastQueuedKeyUp)
        : null,
    };
  }

  #hasM4EditableTextInputAcknowledgement() {
    const state = this.#ozoneTextInputState;
    return state !== null && state.focusedClientPresent === true &&
      state.editable === true && state.canComposeInline === true;
  }

  #consumeM4ExpectedProxyFocusTransfer(target) {
    const transfer = this.#imeProxyExpectedFocusTransfer;
    if (!transfer || target !== this.#imeProxy) {
      return false;
    }
    this.#imeProxyExpectedFocusTransfer = null;
    return true;
  }

  #cancelM4ImeProxyActivation(reason) {
    if (
      this.#imeProxyActivationRequest === null &&
      this.#imeProxyExpectedFocusTransfer === null
    ) {
      return;
    }
    this.#imeProxyActivationRequest = null;
    this.#imeProxyExpectedFocusTransfer = null;
    this.#recordHost(`m4:ime-proxy:${reason}:activation-cancelled`);
  }

  #armM4ImeProxyActivation(record) {
    if (!this.#imeProxyInputEnabled || !this.#imeProxy) {
      return;
    }
    if (!record.trusted || !record.queued || !this.#hostWindowActive) {
      this.#recordHost("m4:ime-proxy:pointer-arm-rejected");
      return;
    }
    this.#cancelM4ImeProxyActivation("pointer-rearm");
    this.#clearM4ImeProxyState("pointer-rearm");
    this.#imeProxyFailure = null;
    this.#imeProxyActivationRequest = {
      pointerDownSequence: record.sequence,
      pointerUpQueued: false,
      ozoneFocusReportSequenceBefore: this.#ozoneFocusReportSequence,
      ozoneTextInputReportSequenceBefore: this.#ozoneTextInputReportSequence,
    };
    this.#recordHost("m4:ime-proxy:pointer-arm-awaiting-native-editable");
  }

  #markM4ImeProxyPointerUp(record) {
    const request = this.#imeProxyActivationRequest;
    if (!request || !record.trusted || !record.queued) {
      return;
    }
    request.pointerUpQueued = true;
    request.pointerUpSequence = record.sequence;
    this.#recordHost("m4:ime-proxy:pointer-up-awaiting-native-editable");
    this.#maybeActivateM4ImeProxy();
  }

  #maybeActivateM4ImeProxy() {
    const request = this.#imeProxyActivationRequest;
    const focusState = this.#ozoneFocusState;
    const textInputState = this.#ozoneTextInputState;
    if (
      !request || !request.pointerUpQueued || !this.#imeProxyInputEnabled ||
      !this.#imeProxy || !this.#hostWindowActive ||
      document.activeElement !== this.#canvas ||
      !focusState ||
      focusState.sequence <= request.ozoneFocusReportSequenceBefore ||
      focusState.keyboardTargetPresent !== true || focusState.active !== true ||
      !textInputState ||
      textInputState.sequence <= request.ozoneTextInputReportSequenceBefore ||
      !this.#hasM4EditableTextInputAcknowledgement()
    ) {
      return false;
    }

    this.#imeProxyActivationRequest = null;
    this.#resetM4ImeProxySession();
    this.#imeProxyExpectedFocusTransfer = {
      sessionId: this.#imeProxySessionId,
      pointerDownSequence: request.pointerDownSequence,
      pointerUpSequence: request.pointerUpSequence,
    };
    this.#imeProxy.focus({preventScroll: true});
    if (document.activeElement !== this.#imeProxy) {
      this.#imeProxyExpectedFocusTransfer = null;
      this.#imeProxyFailure = "PROXY_FOCUS_FAILED";
      this.#recordHost("m4:ime-proxy:native-editable-focus-failed");
      this.#deactivateM4HostWindow("ime-proxy-focus-failed");
      return false;
    }
    this.#recordHost("m4:ime-proxy:native-editable-focus");
    return true;
  }

  #recordImeProxy(record) {
    this.#imeProxyRecords.push(record);
    if (this.#imeProxyRecords.length > 64) {
      this.#imeProxyRecords.shift();
    }
  }

  #imeProxySelection() {
    if (!this.#imeProxy) {
      return null;
    }
    const start = this.#imeProxy.selectionStart;
    const end = this.#imeProxy.selectionEnd;
    if (
      !Number.isSafeInteger(start) ||
      !Number.isSafeInteger(end) ||
      start < 0 ||
      end < start ||
      end > this.#imeProxy.value.length
    ) {
      return null;
    }
    return {start, end};
  }

  #imeProxyActionName(action) {
    switch (action) {
      case M4_IME_TEXT_ACTION.setComposition:
        return "set-composition";
      case M4_IME_TEXT_ACTION.confirmComposition:
        return "confirm-composition";
      case M4_IME_TEXT_ACTION.clearComposition:
        return "clear-composition";
      default:
        return null;
    }
  }

  #recordM4ImeProxyNativeRequest(request) {
    if (this.#imeProxyNativeRequests.length >= 64) {
      const completed = this.#imeProxyNativeRequests.findIndex(
        (candidate) => candidate.deliveryAccepted !== null);
      if (completed < 0) {
        return false;
      }
      this.#imeProxyNativeRequests.splice(completed, 1);
    }
    this.#imeProxyNativeRequests.push(request);
    return true;
  }

  #queueM4ImeProxyTextInput(action, sessionId, sequence, text, selection) {
    const actionName = this.#imeProxyActionName(action);
    if (
      actionName === null || !Number.isSafeInteger(sessionId) ||
      sessionId < 1 || sessionId > 0x7fffffff ||
      !Number.isSafeInteger(sequence) || sequence < 1 ||
      sequence > 0x7fffffff || typeof text !== "string" ||
      !isWellFormedUtf16(text) || !selection ||
      !Number.isSafeInteger(selection.start) ||
      !Number.isSafeInteger(selection.end) || selection.start < 0 ||
      selection.end < selection.start || selection.end > text.length
    ) {
      return null;
    }
    const utf8 = UTF8_ENCODER.encode(text);
    if (utf8.byteLength > MAXIMUM_IME_PROXY_TEXT_BYTES) {
      return null;
    }
    if (
      action === M4_IME_TEXT_ACTION.setComposition &&
      (text.length === 0 || selection.start !== selection.end ||
        selection.end !== text.length)
    ) {
      return null;
    }
    if (
      action !== M4_IME_TEXT_ACTION.setComposition &&
      (text.length !== 0 || selection.start !== 0 || selection.end !== 0)
    ) {
      return null;
    }

    const request = {
      action,
      actionName,
      sessionId,
      sequence,
      queued: true,
      deliveryAccepted: null,
      text: action === M4_IME_TEXT_ACTION.setComposition
        ? imeProxyTextSummary(text)
        : null,
      selection: {start: selection.start, end: selection.end},
    };
    if (!this.#recordM4ImeProxyNativeRequest(request)) {
      return null;
    }
    try {
      const result = this.#callExport(
        "chromium_wasm_host_text_input",
        "number",
        ["number", "number", "number", "array", "number", "number", "number"],
        [
          action,
          sessionId,
          sequence,
          utf8,
          utf8.byteLength,
          selection.start,
          selection.end,
        ],
      );
      request.queued = result === 1;
      if (!request.queued) {
        request.deliveryAccepted = false;
        request.reason = "QUEUE_REJECTED";
        return null;
      }
      return request;
    } catch (error) {
      request.queued = false;
      request.deliveryAccepted = false;
      request.reason = `EXPORT_ERROR:${String(error)}`;
      return null;
    }
  }

  #queueM4ImeProxyClear(reason) {
    const composition = this.#imeProxyNativeComposition;
    if (
      !composition || this.#imeProxyNativeTerminalAction !== null ||
      this.#lifecycle !== "running"
    ) {
      return;
    }
    const sequence = ++this.#imeProxySequence;
    const request = this.#queueM4ImeProxyTextInput(
      M4_IME_TEXT_ACTION.clearComposition,
      composition.sessionId,
      sequence,
      "",
      {start: 0, end: 0},
    );
    if (!request) {
      if (this.#imeProxyFailure === null) {
        this.#imeProxyFailure = "NATIVE_CLEAR_QUEUE_REJECTED";
      }
      this.#recordHost(`m4:ime-proxy:${reason}:native-clear-rejected`);
      return;
    }
    this.#imeProxyNativeTerminalAction = request;
    this.#recordHost(`m4:ime-proxy:${reason}:native-clear-queued`);
  }

  #imeProxyInputStatus() {
    const eventCount = (type) => this.#imeProxyRecords.filter(
      (record) => record.type === type).length;
    const trustedCount = this.#imeProxyRecords.filter(
      (record) => record.trusted === true).length;
    const acceptedCount = this.#imeProxyRecords.filter(
      (record) => record.accepted === true).length;
    const derivedTerminalCount = this.#imeProxyRecords.filter(
      (record) => record.terminalDerivedFromTrustedTransaction === true).length;
    const observedClearTerminalCount = this.#imeProxyRecords.filter(
      (record) => record.terminalObservedAfterClear === true).length;
    const nativeRequests = this.#imeProxyNativeRequests.filter(
      (record) => record.sessionId === this.#imeProxySessionId);
    const nativeDeliveryCount = (action) => nativeRequests.filter(
      (record) => record.action === action &&
        record.deliveryAccepted === true).length;
    const nativePendingDelivery = nativeRequests.some(
      (record) => record.queued === true && record.deliveryAccepted === null);
    const lastNativeDelivery = nativeRequests.findLast(
      (record) => record.deliveryAccepted !== null);
    const proxyText = this.#imeProxy ? {
      ...imeProxyTextSummary(this.#imeProxy.value),
      selection: this.#imeProxySelection(),
    } : null;
    return {
      enabled: this.#imeProxyInputEnabled,
      present: this.#imeProxy !== null,
      focused: document.activeElement === this.#imeProxy,
      hostWindowActive: this.#hostWindowActive,
      sessionId: this.#imeProxySessionId,
      receivedCount: this.#imeProxyRecords.length,
      trustedCount,
      acceptedCount,
      derivedTerminalCount,
      observedClearTerminalCount,
      focusCount: this.#imeProxyFocusCount,
      blurCount: this.#imeProxyBlurCount,
      compositionStartCount: eventCount("compositionstart"),
      compositionUpdateCount: eventCount("compositionupdate"),
      compositionEndCount: eventCount("compositionend"),
      beforeinputCount: eventCount("beforeinput"),
      inputCount: eventCount("input"),
      compositionActive: this.#imeProxyCompositionActive,
      terminalCancellationPending: this.#imeProxyTerminalCancellationPending,
      pendingTransaction: this.#imeProxyPendingTransaction !== null,
      activationPending: this.#imeProxyActivationRequest !== null,
      nativeTextInputReady: this.#hasM4EditableTextInputAcknowledgement(),
      nativeQueuedCount: nativeRequests.filter(
        (record) => record.queued === true).length,
      nativeSetDeliveryCount: nativeDeliveryCount(
        M4_IME_TEXT_ACTION.setComposition),
      nativeConfirmDeliveryCount: nativeDeliveryCount(
        M4_IME_TEXT_ACTION.confirmComposition),
      nativeClearDeliveryCount: nativeDeliveryCount(
        M4_IME_TEXT_ACTION.clearComposition),
      nativePendingDelivery,
      nativeCompositionActive: this.#imeProxyNativeComposition !== null,
      nativeTerminalAction: this.#imeProxyNativeTerminalAction
        ? this.#imeProxyNativeTerminalAction.actionName
        : null,
      lastNativeDelivery: lastNativeDelivery ? clone(lastNativeDelivery) : null,
      lastConfirmedTransaction: this.#imeProxyLastConfirmedTransaction
        ? clone(this.#imeProxyLastConfirmedTransaction)
        : null,
      failure: this.#imeProxyFailure,
      proxyText,
    };
  }

  #resetM4ImeProxySession() {
    if (!this.#imeProxy) {
      return;
    }
    this.#imeProxySessionId += 1;
    this.#imeProxyRecords = [];
    this.#imeProxyCompositionActive = false;
    this.#imeProxyLastCompositionText = null;
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedTransaction = null;
    this.#imeProxyLastConfirmedText = null;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyExpectedTerminalAction = null;
    this.#imeProxyNativeComposition = null;
    this.#imeProxyNativeTerminalAction = null;
    this.#imeProxyFailure = null;
    this.#imeProxy.value = "";
    this.#imeProxy.setSelectionRange(0, 0);
  }

  #clearM4ImeProxyState(reason, {queueNativeClear = true} = {}) {
    if (!this.#imeProxy || !this.#imeProxyInputEnabled) {
      return;
    }
    if (queueNativeClear) {
      this.#queueM4ImeProxyClear(reason);
    }
    this.#imeProxyCompositionActive = false;
    this.#imeProxyLastCompositionText = null;
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedTransaction = null;
    this.#imeProxyLastConfirmedText = null;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyExpectedTerminalAction = null;
    this.#imeProxyNativeComposition = null;
    this.#imeProxyNativeTerminalAction = null;
    this.#imeProxy.value = "";
    this.#imeProxy.setSelectionRange(0, 0);
    this.#recordHost(`m4:ime-proxy:${reason}:cleared`);
  }

  #rejectM4ImeProxyRecord(record, reason) {
    record.reason = reason;
    if (this.#imeProxyFailure === null) {
      this.#imeProxyFailure = reason;
    }
    this.#recordImeProxy(record);
    this.#recordHost(`m4:ime-proxy:${record.type}:rejected:${reason}`);
  }

  #makeImeProxyRecord(type, event) {
    const record = {
      sequence: ++this.#imeProxySequence,
      sessionId: this.#imeProxySessionId,
      type,
      trusted: event.isTrusted === true,
      accepted: false,
      proxyFocused: document.activeElement === this.#imeProxy,
      hostWindowActive: this.#hostWindowActive,
    };
    if (typeof event.inputType === "string") {
      record.inputType = event.inputType;
    }
    if (typeof event.isComposing === "boolean") {
      record.isComposing = event.isComposing;
    }
    if (typeof event.data === "string") {
      record.text = imeProxyTextSummary(event.data);
    }
    return record;
  }

  #validateM4ImeProxyContext(record) {
    if (!record.proxyFocused) {
      this.#rejectM4ImeProxyRecord(record, "PROXY_NOT_FOCUSED");
      return false;
    }
    if (!record.hostWindowActive) {
      this.#rejectM4ImeProxyRecord(record, "OZONE_WINDOW_INACTIVE");
      return false;
    }
    if (!this.#hasM4EditableTextInputAcknowledgement()) {
      this.#rejectM4ImeProxyRecord(record, "NATIVE_TEXT_INPUT_NOT_EDITABLE");
      return false;
    }
    if (record.sessionId <= 0) {
      this.#rejectM4ImeProxyRecord(record, "NO_ACTIVE_SESSION");
      return false;
    }
    if (this.#imeProxyFailure !== null) {
      this.#rejectM4ImeProxyRecord(record, "SESSION_FAILED");
      return false;
    }
    return true;
  }

  #validateM4ImeProxyEvent(record) {
    if (!record.trusted) {
      this.#rejectM4ImeProxyRecord(record, "UNTRUSTED_DOM_EVENT");
      return false;
    }
    return this.#validateM4ImeProxyContext(record);
  }

  #validateM4ImeProxyTerminal(record) {
    // Blink intentionally dispatches compositionend through its scoped event
    // queue, which does not mark the DOM event trusted. A terminal has no
    // authority to introduce text: the caller below additionally requires the
    // exact private candidate created by prior trusted source events.
    return this.#validateM4ImeProxyContext(record);
  }

  #handleM4ImeProxyCompositionStart(event) {
    const record = this.#makeImeProxyRecord("compositionstart", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    if (this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "DUPLICATE_COMPOSITION_START");
      return;
    }
    this.#imeProxyCompositionActive = true;
    this.#imeProxyTerminalCancellationPending = false;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:compositionstart:accepted");
  }

  #handleM4ImeProxyCompositionUpdate(event) {
    const record = this.#makeImeProxyRecord("compositionupdate", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    if (!this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_UPDATE_WITHOUT_START");
      return;
    }
    if (data === "") {
      if (!this.#imeProxyNativeComposition ||
          this.#imeProxyPendingTransaction !== null ||
          this.#imeProxyLastConfirmedText !==
            this.#imeProxyNativeComposition.text) {
        this.#rejectM4ImeProxyRecord(
          record, "CANCELLATION_UPDATE_WITHOUT_CONFIRMED_COMPOSITION");
        return;
      }
      this.#imeProxyTerminalCancellationPending = true;
      record.accepted = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:compositionupdate:cancellation-pending");
      return;
    }
    if (
      data === null || data.length === 0 ||
      data.length > MAXIMUM_IME_PROXY_TEXT_UNITS ||
      !isWellFormedUtf16(data)
    ) {
      this.#rejectM4ImeProxyRecord(record, "INVALID_COMPOSITION_TEXT");
      return;
    }
    // Keep the exact browser-produced UTF-16 candidate private for the later
    // Ozone InputMethod bridge. Diagnostics expose only its bounded summary.
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyLastCompositionText = data;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:compositionupdate:accepted");
  }

  #handleM4ImeProxyBeforeInput(event) {
    const record = this.#makeImeProxyRecord("beforeinput", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    const summary = data === null ? null : imeProxyTextSummary(data);
    if (event.inputType !== "insertCompositionText") {
      this.#rejectM4ImeProxyRecord(record, "UNSUPPORTED_INPUT_TYPE");
      return;
    }
    if (event.isComposing !== true) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_FLAG_MISMATCH");
      return;
    }
    if (!this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "BEFOREINPUT_WITHOUT_COMPOSITION");
      return;
    }
    if ((data === "" || data === null) &&
        this.#imeProxyTerminalCancellationPending) {
      if (!this.#imeProxyNativeComposition ||
          this.#imeProxyPendingTransaction !== null ||
          this.#imeProxyNativeTerminalAction !== null) {
        this.#rejectM4ImeProxyRecord(
          record, "CANCELLATION_BEFOREINPUT_WITHOUT_COMPOSITION");
        return;
      }
      record.accepted = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:beforeinput:cancellation-pending");
      return;
    }
    if (this.#imeProxyPendingTransaction !== null) {
      this.#rejectM4ImeProxyRecord(record, "PENDING_TRANSACTION_EXISTS");
      return;
    }
    if (
      data === null || data.length === 0 ||
      data.length > MAXIMUM_IME_PROXY_TEXT_UNITS ||
      !isWellFormedUtf16(data) || data !== this.#imeProxyLastCompositionText
    ) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_TEXT_MISMATCH");
      return;
    }
    const transaction = {
      sessionId: this.#imeProxySessionId,
      sequence: record.sequence,
      opcode: "set-composition",
      text: data,
      textSummary: summary,
    };
    const request = this.#queueM4ImeProxyTextInput(
      M4_IME_TEXT_ACTION.setComposition,
      transaction.sessionId,
      transaction.sequence,
      transaction.text,
      {start: transaction.text.length, end: transaction.text.length},
    );
    if (!request) {
      this.#rejectM4ImeProxyRecord(record, "NATIVE_SET_QUEUE_REJECTED");
      return;
    }
    this.#imeProxyPendingTransaction = transaction;
    this.#imeProxyNativeComposition = {
      sessionId: transaction.sessionId,
      sequence: transaction.sequence,
      text: transaction.text,
      textSummary: transaction.textSummary,
    };
    this.#imeProxyNativeTerminalAction = null;
    record.nativeQueued = true;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:beforeinput:native-set-queued");
  }

  #handleM4ImeProxyInput(event) {
    const record = this.#makeImeProxyRecord("input", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    const summary = data === null ? null : imeProxyTextSummary(data);
    const pending = this.#imeProxyPendingTransaction;
    const selection = this.#imeProxySelection();
    if (event.inputType !== "insertCompositionText") {
      this.#rejectM4ImeProxyRecord(record, "UNSUPPORTED_INPUT_TYPE");
      return;
    }
    if (event.isComposing !== true) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_FLAG_MISMATCH");
      return;
    }
    if (this.#imeProxyTerminalCancellationPending) {
      const composition = this.#imeProxyNativeComposition;
      if (
        (data !== null && data !== "") || !composition || !this.#imeProxy ||
        this.#imeProxyPendingTransaction !== null ||
        this.#imeProxyNativeTerminalAction !== null ||
        this.#imeProxy.value !== "" || !selection ||
        selection.start !== 0 || selection.end !== 0
      ) {
        this.#rejectM4ImeProxyRecord(
          record, "CANCELLATION_INPUT_TRANSACTION_MISMATCH");
        return;
      }
      const request = this.#queueM4ImeProxyTextInput(
        M4_IME_TEXT_ACTION.clearComposition,
        composition.sessionId,
        record.sequence,
        "",
        {start: 0, end: 0},
      );
      if (!request) {
        this.#rejectM4ImeProxyRecord(record, "NATIVE_CLEAR_QUEUE_REJECTED");
        return;
      }
      this.#imeProxyNativeTerminalAction = request;
      this.#imeProxyExpectedTerminalAction =
        M4_IME_TEXT_ACTION.clearComposition;
      this.#imeProxyCompositionActive = false;
      this.#imeProxyTerminalCancellationPending = false;
      this.#imeProxyLastCompositionText = null;
      record.nativeQueued = true;
      record.accepted = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:input:native-clear-queued");
      return;
    }
    if (!pending || pending.sessionId !== this.#imeProxySessionId) {
      this.#rejectM4ImeProxyRecord(record, "INPUT_WITHOUT_PENDING_TRANSACTION");
      return;
    }
    if (
      data === null || data !== pending.text || !this.#imeProxy ||
      this.#imeProxy.value !== data ||
      !selection || selection.start !== data.length || selection.end !== data.length
    ) {
      this.#rejectM4ImeProxyRecord(record, "INPUT_TRANSACTION_MISMATCH");
      return;
    }
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedText = pending.text;
    this.#imeProxyLastConfirmedTransaction = {
      sessionId: pending.sessionId,
      sequence: pending.sequence,
      opcode: pending.opcode,
      text: pending.textSummary,
      rangeStart: 0,
      rangeEnd: data.length,
      selection,
    };
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:input:confirmed-native-set");
  }

  #handleM4ImeProxyCompositionEnd(event) {
    const record = this.#makeImeProxyRecord("compositionend", event);
    if (!this.#validateM4ImeProxyTerminal(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    if (
      this.#imeProxyExpectedTerminalAction ===
        M4_IME_TEXT_ACTION.clearComposition &&
      data === ""
    ) {
      // Empty source records already queued ClearCompositionText. Blink's
      // following terminal event is an observation only and cannot issue a
      // second native action.
      this.#imeProxyExpectedTerminalAction = null;
      record.terminalObservedAfterClear = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:compositionend:clear-observed");
      return;
    }
    const composition = this.#imeProxyNativeComposition;
    if (!this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_WITHOUT_START");
      return;
    }
    if (this.#imeProxyPendingTransaction !== null) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_WITH_PENDING_INPUT");
      return;
    }
    if (!composition || composition.sessionId !== this.#imeProxySessionId ||
        this.#imeProxyNativeTerminalAction !== null ||
        this.#imeProxyLastConfirmedText !== composition.text) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_TRANSACTION_MISMATCH");
      return;
    }
    if (data !== composition.text) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_TRANSACTION_MISMATCH");
      return;
    }
    record.terminalDerivedFromTrustedTransaction = !record.trusted;
    const request = this.#queueM4ImeProxyTextInput(
      M4_IME_TEXT_ACTION.confirmComposition,
      composition.sessionId,
      record.sequence,
      "",
      {start: 0, end: 0},
    );
    if (!request) {
      this.#rejectM4ImeProxyRecord(record, "NATIVE_CONFIRM_QUEUE_REJECTED");
      return;
    }
    this.#imeProxyNativeTerminalAction = request;
    this.#imeProxyCompositionActive = false;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyLastCompositionText = null;
    record.nativeQueued = true;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:compositionend:native-confirm-queued");
  }

  #disableM4ImeProxyInput() {
    for (const {target, type, listener} of this.#imeProxyListeners) {
      target.removeEventListener(type, listener);
    }
    this.#imeProxyListeners = [];
    this.#cancelM4ImeProxyActivation("teardown");
    this.#clearM4ImeProxyState("teardown");
    this.#imeProxyInputEnabled = false;
  }

  enableM4ImeProxyInput() {
    this.#requireRunning("enableM4ImeProxyInput");
    if (!this.#imeProxy) {
      throw new Error("M4 IME proxy is unavailable");
    }
    if (this.#imeProxyInputEnabled) {
      return this.#imeProxyInputStatus();
    }
    this.#imeProxyInputEnabled = true;
    this.#imeProxySessionId = 0;
    this.#imeProxySequence = 0;
    this.#imeProxyRecords = [];
    this.#imeProxyCompositionActive = false;
    this.#imeProxyLastCompositionText = null;
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedTransaction = null;
    this.#imeProxyLastConfirmedText = null;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyExpectedTerminalAction = null;
    this.#imeProxyNativeRequests = [];
    this.#imeProxyNativeComposition = null;
    this.#imeProxyNativeTerminalAction = null;
    this.#imeProxyFailure = null;
    this.#imeProxyFocusCount = 0;
    this.#imeProxyBlurCount = 0;
    this.#imeProxyActivationRequest = null;
    this.#imeProxyExpectedFocusTransfer = null;
    this.#imeProxy.value = "";
    this.#imeProxy.setSelectionRange(0, 0);
    for (const [type, handler] of [
      ["compositionstart", (event) => this.#handleM4ImeProxyCompositionStart(event)],
      ["compositionupdate", (event) => this.#handleM4ImeProxyCompositionUpdate(event)],
      ["compositionend", (event) => this.#handleM4ImeProxyCompositionEnd(event)],
      ["beforeinput", (event) => this.#handleM4ImeProxyBeforeInput(event)],
      ["input", (event) => this.#handleM4ImeProxyInput(event)],
    ]) {
      this.#imeProxy.addEventListener(type, handler);
      this.#imeProxyListeners.push({target: this.#imeProxy, type, listener: handler});
    }
    const focusListener = () => {
      this.#imeProxyFocusCount += 1;
      this.#recordHost("m4:ime-proxy:focus");
    };
    this.#imeProxy.addEventListener("focus", focusListener);
    this.#imeProxyListeners.push({
      target: this.#imeProxy,
      type: "focus",
      listener: focusListener,
    });
    const blurListener = (event) => {
      this.#imeProxyBlurCount += 1;
      // Returning to the canvas must invalidate the browser-owned DOM IME
      // session even though Aura/Ozone remains active. The next click earns a
      // new native editable acknowledgement and a new proxy session.
      this.#cancelM4ImeProxyActivation("blur");
      this.#clearM4ImeProxyState("blur");
      if (event.relatedTarget === this.#canvas) {
        this.#recordHost("m4:ime-proxy:blur:canvas-return");
        return;
      }
      this.#deactivateM4HostWindow("ime-proxy-blur", event);
    };
    this.#imeProxy.addEventListener("blur", blurListener);
    this.#imeProxyListeners.push({
      target: this.#imeProxy,
      type: "blur",
      listener: blurListener,
    });
    this.#recordHost("m4:ime-proxy:listeners-attached");
    return this.#imeProxyInputStatus();
  }

  #recordFocus(record) {
    this.#focusRecords.push(record);
    if (this.#focusRecords.length > 32) {
      this.#focusRecords.shift();
    }
  }

  #focusInputStatus() {
    const queuedCount = this.#focusRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#focusRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#focusInputEnabled,
      hostWindowActive: this.#hostWindowActive,
      receivedCount: this.#focusRecords.length,
      trustedCount,
      queuedCount,
      lastQueuedFocusLoss: this.#lastQueuedFocusLoss
        ? clone(this.#lastQueuedFocusLoss)
        : null,
    };
  }

  #canvasPointForPointerEvent(event) {
    const rect = this.#canvas.getBoundingClientRect();
    const contentWidth = this.#canvas.clientWidth;
    const contentHeight = this.#canvas.clientHeight;
    if (
      !Number.isFinite(event.clientX) ||
      !Number.isFinite(event.clientY) ||
      !Number.isFinite(rect.left) ||
      !Number.isFinite(rect.top) ||
      !Number.isFinite(contentWidth) ||
      !Number.isFinite(contentHeight) ||
      contentWidth <= 0 ||
      contentHeight <= 0
    ) {
      return null;
    }
    const cssX = event.clientX - rect.left - this.#canvas.clientLeft;
    const cssY = event.clientY - rect.top - this.#canvas.clientTop;
    if (
      cssX < 0 ||
      cssY < 0 ||
      cssX >= contentWidth ||
      cssY >= contentHeight
    ) {
      return null;
    }
    const x = Math.floor((cssX * this.#canvas.width) / contentWidth);
    const y = Math.floor((cssY * this.#canvas.height) / contentHeight);
    if (
      !Number.isSafeInteger(x) ||
      !Number.isSafeInteger(y) ||
      x < 0 || y < 0 || x >= this.#canvas.width || y >= this.#canvas.height
    ) {
      return null;
    }
    return {x, y};
  }

  #releaseM4PointerCapture(pointerId) {
    if (
      typeof this.#canvas.hasPointerCapture !== "function" ||
      typeof this.#canvas.releasePointerCapture !== "function"
    ) {
      return;
    }
    try {
      if (this.#canvas.hasPointerCapture(pointerId)) {
        this.#canvas.releasePointerCapture(pointerId);
      }
    } catch (error) {
      this.#recordHost("m4:pointer:capture-release-failed");
    }
  }

  #cancelActiveM4Pointer(reason) {
    const pointerId = this.#activeM4PointerId;
    const point = this.#lastM4PointerPoint;
    if (pointerId === null) {
      return;
    }
    this.#activeM4PointerId = null;
    this.#lastM4PointerPoint = null;
    this.#releaseM4PointerCapture(pointerId);
    if (this.#lifecycle !== "running" || !point) {
      this.#recordHost(`m4:pointer:${reason}:release-skipped`);
      return;
    }
    try {
      const result = this.#callExport(
        "chromium_wasm_host_pointer",
        "number",
        ["number", "number", "number", "number"],
        [2, point.x, point.y, 0],
      );
      this.#recordHost(
        `m4:pointer:${reason}:${result === 1 ? "release-queued" : "rejected"}`);
    } catch (error) {
      this.#recordHost(`m4:pointer:${reason}:release-failed`);
    }
  }

  #handleM4PointerEvent(type, event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const pointerId = Number(event.pointerId);
    const record = {
      sequence: ++this.#pointerSequence,
      type,
      pointerId,
      trusted: event.isTrusted === true,
      queued: false,
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
    };
    if (!record.trusted) {
      record.reason = "UNTRUSTED_DOM_EVENT";
      this.#recordPointer(record);
      this.#recordHost(`m4:pointer:${type}:untrusted`);
      return;
    }
    if (
      event.pointerType !== "mouse" ||
      event.isPrimary !== true ||
      !Number.isSafeInteger(pointerId)
    ) {
      record.reason = "UNSUPPORTED_POINTER";
      this.#recordPointer(record);
      this.#recordHost(`m4:pointer:${type}:unsupported-pointer`);
      return;
    }
    if ((type === "down" || type === "up") && event.button !== 0) {
      record.reason = "UNSUPPORTED_BUTTON";
      this.#recordPointer(record);
      this.#recordHost(`m4:pointer:${type}:unsupported-button`);
      return;
    }
    const captured = this.#activeM4PointerId === pointerId;
    let point = this.#canvasPointForPointerEvent(event);
    if (!point && (type === "up" || type === "cancel") && captured) {
      point = this.#lastM4PointerPoint;
      record.usedCapturedPoint = point !== null;
    }
    if (!point) {
      record.reason = "OUTSIDE_CANVAS";
      this.#recordPointer(record);
      this.#recordHost(`m4:pointer:${type}:outside-canvas`);
      return;
    }
    if (type === "down") {
      this.#canvas.focus({preventScroll: true});
      if (typeof this.#canvas.setPointerCapture !== "function") {
        record.reason = "HOST_CAPTURE_UNSUPPORTED";
        this.#recordPointer(record);
        this.#recordHost(`m4:pointer:${type}:capture-unsupported`);
        return;
      }
      try {
        this.#canvas.setPointerCapture(pointerId);
      } catch (error) {
        record.reason = "HOST_CAPTURE_FAILED";
        this.#recordPointer(record);
        this.#recordHost(`m4:pointer:${type}:capture-failed`);
        return;
      }
      this.#activeM4PointerId = pointerId;
      this.#lastM4PointerPoint = point;
    } else if (captured) {
      this.#lastM4PointerPoint = point;
    }
    try {
      const eventType = {move: 0, down: 1, up: 2, cancel: 2}[type];
      const result = this.#callExport(
        "chromium_wasm_host_pointer",
        "number",
        ["number", "number", "number", "number"],
        [eventType, point.x, point.y, 0],
      );
      record.x = point.x;
      record.y = point.y;
      record.queued = result === 1;
      record.canvasFocused = document.activeElement === this.#canvas;
      if (!record.queued) {
        record.reason = "QUEUE_REJECTED";
      } else {
        this.#lastQueuedPointer = record;
        if (type === "down" && this.#keyboardInputEnabled) {
          this.#keyboardActivated = true;
          this.#recordHost("m4:keyboard:pointer-activation");
        }
        if (type === "down" && this.#focusInputEnabled) {
          this.#hostWindowActive = true;
          this.#recordFocus({
            sequence: ++this.#focusSequence,
            type: "pointer-activation",
            trusted: record.trusted,
            queued: true,
            frameIdBefore: record.frameIdBefore,
            canvasFocused: record.canvasFocused,
            relatedTargetId: null,
          });
          this.#recordHost("m4:focus:pointer-activation");
        }
        if (type === "down") {
          this.#armM4ImeProxyActivation(record);
        }
      }
    } catch (error) {
      record.reason = `EXPORT_ERROR:${String(error)}`;
    }
    if (type === "up" || type === "cancel") {
      this.#releaseM4PointerCapture(pointerId);
      if (this.#activeM4PointerId === pointerId) {
        this.#activeM4PointerId = null;
        this.#lastM4PointerPoint = null;
      }
    }
    if (type === "up" && record.queued) {
      this.#markM4ImeProxyPointerUp(record);
    }
    this.#recordPointer(record);
    this.#recordHost(
      `m4:pointer:${type}:${record.queued ? "queued" : "rejected"}`);
  }

  #disableM4PointerInput() {
    for (const {target, type, listener} of this.#pointerListeners) {
      target.removeEventListener(type, listener);
    }
    this.#cancelActiveM4Pointer("teardown");
    this.#pointerListeners = [];
    this.#pointerInputEnabled = false;
  }

  enableM4PointerInput() {
    this.#requireRunning("enableM4PointerInput");
    if (this.#pointerInputEnabled) {
      return this.#pointerInputStatus();
    }
    for (const [domType, type] of [
      ["pointermove", "move"],
      ["pointerdown", "down"],
      ["pointerup", "up"],
      ["pointercancel", "cancel"],
    ]) {
      const listener = (event) => this.#handleM4PointerEvent(type, event);
      this.#canvas.addEventListener(domType, listener);
      this.#pointerListeners.push({
        target: this.#canvas,
        type: domType,
        listener,
      });
    }
    const lostCaptureListener = (event) => {
      if (this.#activeM4PointerId === Number(event.pointerId)) {
        this.#handleM4PointerEvent("cancel", event);
      }
    };
    this.#canvas.addEventListener("lostpointercapture", lostCaptureListener);
    this.#pointerListeners.push({
      target: this.#canvas,
      type: "lostpointercapture",
      listener: lostCaptureListener,
    });
    const cancelOnBlur = () => this.#cancelActiveM4Pointer("blur");
    addEventListener("blur", cancelOnBlur);
    this.#pointerListeners.push({
      target: window,
      type: "blur",
      listener: cancelOnBlur,
    });
    this.#pointerInputEnabled = true;
    this.#recordHost("m4:pointer:listeners-attached");
    const cancelWhenHidden = () => {
      if (document.visibilityState !== "visible") {
        this.#cancelActiveM4Pointer("visibility-loss");
      }
    };
    document.addEventListener("visibilitychange", cancelWhenHidden);
    this.#pointerListeners.push({
      target: document,
      type: "visibilitychange",
      listener: cancelWhenHidden,
    });
    return this.#pointerInputStatus();
  }

  #handleM4WheelEvent(event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const record = {
      sequence: ++this.#wheelSequence,
      type: "wheel",
      trusted: event.isTrusted === true,
      queued: false,
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
    };
    if (!record.trusted) {
      record.reason = "UNTRUSTED_DOM_EVENT";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:untrusted");
      return;
    }
    if (!event.cancelable) {
      record.reason = "NONCANCELABLE_DOM_EVENT";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:noncancelable");
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      record.reason = "UNSUPPORTED_MODIFIERS";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:unsupported-modifiers");
      return;
    }
    if (event.deltaMode !== 0) {
      record.reason = "UNSUPPORTED_DELTA_MODE";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:unsupported-delta-mode");
      return;
    }
    const point = this.#canvasPointForPointerEvent(event);
    if (!point) {
      record.reason = "OUTSIDE_CANVAS";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:outside-canvas");
      return;
    }
    const domDeltaX = Number(event.deltaX);
    const domDeltaY = Number(event.deltaY);
    const scaleX = this.#canvas.width / this.#canvas.clientWidth;
    const scaleY = this.#canvas.height / this.#canvas.clientHeight;
    if (
      !Number.isFinite(domDeltaX) ||
      !Number.isFinite(domDeltaY) ||
      !Number.isFinite(scaleX) ||
      !Number.isFinite(scaleY) ||
      scaleX <= 0 || scaleY <= 0
    ) {
      record.reason = "INVALID_DELTA";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:invalid-delta");
      return;
    }
    const accumulatedX = domDeltaX * scaleX + this.#wheelResidualX;
    const accumulatedY = domDeltaY * scaleY + this.#wheelResidualY;
    const deltaX = Math.trunc(accumulatedX);
    const deltaY = Math.trunc(accumulatedY);
    if (
      !Number.isSafeInteger(deltaX) ||
      !Number.isSafeInteger(deltaY) ||
      deltaX < -MAXIMUM_WHEEL_DELTA ||
      deltaX > MAXIMUM_WHEEL_DELTA ||
      deltaY < -MAXIMUM_WHEEL_DELTA ||
      deltaY > MAXIMUM_WHEEL_DELTA
    ) {
      record.reason = "OUT_OF_RANGE_DELTA";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:out-of-range-delta");
      return;
    }
    record.x = point.x;
    record.y = point.y;
    record.deltaMode = event.deltaMode;
    record.domDeltaX = domDeltaX;
    record.domDeltaY = domDeltaY;
    record.deltaX = deltaX;
    record.deltaY = deltaY;
    record.canvasFocused = document.activeElement === this.#canvas;
    if (deltaX === 0 && deltaY === 0) {
      this.#wheelResidualX = accumulatedX;
      this.#wheelResidualY = accumulatedY;
      event.preventDefault();
      record.defaultPrevented = event.defaultPrevented;
      record.reason = "FRACTIONAL_DELTA_BUFFERED";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:fractional-buffered");
      return;
    }
    this.#canvas.focus({preventScroll: true});
    try {
      const result = this.#callExport(
        "chromium_wasm_host_wheel",
        "number",
        ["number", "number", "number", "number"],
        [point.x, point.y, deltaX, deltaY],
      );
      record.queued = result === 1;
      record.canvasFocused = document.activeElement === this.#canvas;
      if (record.queued) {
        this.#wheelResidualX = accumulatedX - deltaX;
        this.#wheelResidualY = accumulatedY - deltaY;
        event.preventDefault();
        record.defaultPrevented = event.defaultPrevented;
        this.#lastQueuedWheel = record;
      } else {
        record.reason = "QUEUE_REJECTED";
      }
    } catch (error) {
      record.reason = `EXPORT_ERROR:${String(error)}`;
    }
    this.#recordWheel(record);
    this.#recordHost(
      `m4:wheel:${record.queued ? "queued" : "rejected"}`);
  }

  #disableM4WheelInput() {
    for (const {target, type, listener} of this.#wheelListeners) {
      target.removeEventListener(type, listener);
    }
    this.#wheelListeners = [];
    this.#wheelInputEnabled = false;
    this.#wheelResidualX = 0;
    this.#wheelResidualY = 0;
  }

  enableM4WheelInput() {
    this.#requireRunning("enableM4WheelInput");
    if (this.#wheelInputEnabled) {
      return this.#wheelInputStatus();
    }
    const listener = (event) => this.#handleM4WheelEvent(event);
    this.#canvas.addEventListener("wheel", listener, {passive: false});
    this.#wheelListeners.push({
      target: this.#canvas,
      type: "wheel",
      listener,
    });
    this.#wheelInputEnabled = true;
    this.#recordHost("m4:wheel:listeners-attached");
    return this.#wheelInputStatus();
  }

  #releaseM4KeyboardKeys(reason, triggerEvent = null) {
    const codes = Array.from(this.#keyboardCodesDown);
    this.#keyboardCodesDown.clear();
    this.#keyboardActivated = false;
    if (codes.length === 0) {
      return;
    }
    if (this.#lifecycle !== "running") {
      this.#recordHost("m4:keyboard:" + reason + ":release-skipped");
      return;
    }
    for (const code of codes) {
      const relatedTarget = triggerEvent?.relatedTarget;
      const relatedTargetId =
        typeof Element !== "undefined" &&
        relatedTarget instanceof Element && relatedTarget.id
          ? relatedTarget.id
          : null;
      const record = {
        sequence: ++this.#keyboardSequence,
        type: "up",
        code,
        key: expectedM4KeyboardKey(code) ?? "",
        trusted: false,
        queued: false,
        generated: true,
        trigger: reason,
        triggerTrusted: triggerEvent?.isTrusted === true,
        relatedTargetId,
        repeat: false,
        isComposing: false,
        modifiers: {
          alt: false,
          control: false,
          meta: false,
          shift: false,
        },
        frameIdBefore: this.#frame?.id ?? 0,
        canvasFocused: document.activeElement === this.#canvas,
        pointerActivated: false,
      };
      try {
        const result = this.#callExport(
          "chromium_wasm_host_key",
          "number",
          ["string", "number"],
          [code, 0],
        );
        record.queued = result === 1;
        if (record.queued) {
          this.#lastQueuedKeyUp = record;
        } else {
          record.reason = "QUEUE_REJECTED";
        }
        this.#recordHost(
          "m4:keyboard:" + reason + ":" +
          (record.queued ? "release-queued" : "release-rejected"));
      } catch (error) {
        record.reason = "EXPORT_ERROR:" + String(error);
        this.#recordHost("m4:keyboard:" + reason + ":release-failed");
      }
      this.#recordKeyboard(record);
    }
  }

  #handleM4KeyboardEvent(type, event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const code = typeof event.code === "string" ? event.code : "";
    const key = typeof event.key === "string" ? event.key : "";
    const record = {
      sequence: ++this.#keyboardSequence,
      type,
      code,
      key,
      trusted: event.isTrusted === true,
      queued: false,
      repeat: event.repeat === true,
      isComposing: event.isComposing === true,
      modifiers: {
        alt: event.altKey === true,
        control: event.ctrlKey === true,
        meta: event.metaKey === true,
        shift: event.shiftKey === true,
      },
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
      pointerActivated: this.#keyboardActivated,
    };
    if (!record.trusted) {
      record.reason = "UNTRUSTED_DOM_EVENT";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":untrusted");
      return;
    }
    if (!event.cancelable) {
      record.reason = "NONCANCELABLE_DOM_EVENT";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":noncancelable");
      return;
    }
    if (!record.canvasFocused) {
      record.reason = "CANVAS_NOT_FOCUSED";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":canvas-not-focused");
      return;
    }
    if (!record.pointerActivated) {
      record.reason = "NO_POINTER_ACTIVATION";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":no-pointer-activation");
      return;
    }
    if (
      record.modifiers.alt ||
      record.modifiers.control ||
      record.modifiers.meta ||
      record.modifiers.shift
    ) {
      record.reason = "UNSUPPORTED_MODIFIERS";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-modifiers");
      return;
    }
    if (record.repeat) {
      record.reason = "UNSUPPORTED_REPEAT";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-repeat");
      return;
    }
    if (
      record.isComposing ||
      record.key === "Dead" ||
      record.key === "Process"
    ) {
      record.reason = "UNSUPPORTED_COMPOSITION";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-composition");
      return;
    }
    const expectedKey = expectedM4KeyboardKey(record.code);
    if (expectedKey === null) {
      record.reason = "UNSUPPORTED_DOM_CODE";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-code");
      return;
    }
    if (record.key !== expectedKey) {
      record.reason = "UNSUPPORTED_DOM_KEY";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-key");
      return;
    }
    if (type === "down" && this.#keyboardCodesDown.has(record.code)) {
      record.reason = "DUPLICATE_DOWN";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:down:duplicate");
      return;
    }
    if (type === "up" && !this.#keyboardCodesDown.has(record.code)) {
      record.reason = "UNMATCHED_UP";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:up:unmatched");
      return;
    }
    try {
      const result = this.#callExport(
        "chromium_wasm_host_key",
        "number",
        ["string", "number"],
        [record.code, type === "down" ? 1 : 0],
      );
      record.queued = result === 1;
      if (record.queued) {
        if (type === "down") {
          this.#keyboardCodesDown.add(record.code);
          this.#lastQueuedKeyDown = record;
        } else {
          this.#keyboardCodesDown.delete(record.code);
          this.#lastQueuedKeyUp = record;
        }
        event.preventDefault();
        record.defaultPrevented = event.defaultPrevented;
      } else {
        record.reason = "QUEUE_REJECTED";
      }
    } catch (error) {
      record.reason = "EXPORT_ERROR:" + String(error);
    }
    this.#recordKeyboard(record);
    this.#recordHost(
      "m4:keyboard:" + type + ":" +
      (record.queued ? "queued" : "rejected"));
  }

  #disableM4KeyboardInput() {
    for (const {target, type, listener} of this.#keyboardListeners) {
      target.removeEventListener(type, listener);
    }
    this.#keyboardListeners = [];
    this.#releaseM4KeyboardKeys("teardown");
    this.#keyboardInputEnabled = false;
  }

  enableM4KeyboardInput() {
    this.#requireRunning("enableM4KeyboardInput");
    if (this.#keyboardInputEnabled) {
      return this.#keyboardInputStatus();
    }
    for (const [domType, type] of [["keydown", "down"], ["keyup", "up"]]) {
      const listener = (event) => this.#handleM4KeyboardEvent(type, event);
      this.#canvas.addEventListener(domType, listener);
      this.#keyboardListeners.push({
        target: this.#canvas,
        type: domType,
        listener,
      });
    }
    this.#keyboardInputEnabled = true;
    this.#recordHost("m4:keyboard:listeners-attached");
    return this.#keyboardInputStatus();
  }

  #deactivateM4HostWindow(reason, event = null) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const relatedTarget = event?.relatedTarget;
    const relatedTargetId =
      typeof Element !== "undefined" &&
      relatedTarget instanceof Element && relatedTarget.id
        ? relatedTarget.id
        : null;
    const record = {
      sequence: ++this.#focusSequence,
      type: reason,
      trusted: event?.isTrusted === true,
      queued: false,
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
      relatedTargetId,
    };

    if (this.#consumeM4ExpectedProxyFocusTransfer(relatedTarget)) {
      record.internalTransfer = true;
      record.reason = "EXPECTED_PROXY_FOCUS_TRANSFER";
      this.#recordFocus(record);
      this.#recordHost(`m4:focus:${reason}:expected-proxy-transfer`);
      return;
    }

    // Releases must run while ozone_wasm still has its keyboard target. The
    // UI task queue preserves this ordering before the later deactivation.
    this.#cancelM4ImeProxyActivation(reason);
    this.#clearM4ImeProxyState(reason);
    this.#cancelActiveM4Pointer(reason);
    this.#releaseM4KeyboardKeys(reason, event);
    if (!this.#focusInputEnabled) {
      record.reason = "FOCUS_INPUT_DISABLED";
      this.#recordFocus(record);
      return;
    }
    if (!this.#hostWindowActive) {
      record.reason = "DUPLICATE_FOCUS_LOSS";
      this.#recordFocus(record);
      this.#recordHost("m4:focus:" + reason + ":duplicate");
      return;
    }
    record.ozoneFocusReportSequenceBefore = this.#ozoneFocusReportSequence;
    this.#ozoneFocusState = null;
    try {
      const result = this.#callExport(
        "chromium_wasm_host_deactivate", "number", [], []);
      record.queued = result === 1;
      if (record.queued) {
        this.#hostWindowActive = false;
        this.#lastQueuedFocusLoss = record;
      } else {
        record.reason = "QUEUE_REJECTED";
      }
    } catch (error) {
      record.reason = "EXPORT_ERROR:" + String(error);
    }
    this.#recordFocus(record);
    this.#recordHost(
      "m4:focus:" + reason + ":" +
      (record.queued ? "deactivate-queued" : "deactivate-rejected"));
  }

  #disableM4FocusInput() {
    for (const {target, type, listener} of this.#focusListeners) {
      target.removeEventListener(type, listener);
    }
    this.#focusListeners = [];
    this.#deactivateM4HostWindow("teardown");
    this.#focusInputEnabled = false;
  }

  enableM4FocusInput() {
    this.#requireRunning("enableM4FocusInput");
    if (this.#focusInputEnabled) {
      return this.#focusInputStatus();
    }
    this.#focusInputEnabled = true;
    this.#hostWindowActive = document.activeElement === this.#canvas;
    const canvasBlurListener = (event) => {
      this.#deactivateM4HostWindow("canvas-blur", event);
    };
    this.#canvas.addEventListener("blur", canvasBlurListener);
    this.#focusListeners.push({
      target: this.#canvas,
      type: "blur",
      listener: canvasBlurListener,
    });
    const windowBlurListener = (event) => {
      this.#deactivateM4HostWindow("window-blur", event);
    };
    addEventListener("blur", windowBlurListener);
    this.#focusListeners.push({
      target: window,
      type: "blur",
      listener: windowBlurListener,
    });
    const visibilityListener = (event) => {
      if (document.visibilityState !== "visible") {
        this.#deactivateM4HostWindow("visibility-loss", event);
      }
    };
    document.addEventListener("visibilitychange", visibilityListener);
    this.#focusListeners.push({
      target: document,
      type: "visibilitychange",
      listener: visibilityListener,
    });
    this.#recordHost("m4:focus:listeners-attached");
    return this.#focusInputStatus();
  }

  #heartbeat() {
    if (this.#heartbeatAnchor === null) {
      return {
        anchor: null,
        elapsedMs: 0,
        timerStartTicks: this.#timerTicks,
        timerEndTicks: this.#timerTicks,
        timerDelta: 0,
        animationFrameStartTicks: this.#animationFrameTicks,
        animationFrameEndTicks: this.#animationFrameTicks,
        animationFrameDelta: 0,
        maxTimerGapMs: 0,
      };
    }
    return {
      anchor: this.#heartbeatAnchor,
      elapsedMs: performance.now() - this.#heartbeatStartTime,
      timerStartTicks: this.#heartbeatStartTimerTicks,
      timerEndTicks: this.#timerTicks,
      timerDelta: this.#timerTicks - this.#heartbeatStartTimerTicks,
      animationFrameStartTicks: this.#heartbeatStartAnimationFrameTicks,
      animationFrameEndTicks: this.#animationFrameTicks,
      animationFrameDelta:
        this.#animationFrameTicks - this.#heartbeatStartAnimationFrameTicks,
      maxTimerGapMs: this.#maximumTimerGapMs,
    };
  }

  #requireRunning(operation) {
    if (this.#lifecycle !== "running" || !this.#module) {
      throw new Error(`${operation} requires an initialized M3 runtime`);
    }
  }

  #sampleLinearMemoryBytes(description) {
    const byteLength = this.#module?.HEAPU8?.buffer?.byteLength;
    if (!Number.isSafeInteger(byteLength) || byteLength <= 0) {
      throw new Error(
        `${description} linear memory must have a positive safe byte length`);
    }
    if (byteLength % WASM_PAGE_BYTES !== 0) {
      throw new Error(
        `${description} linear memory must be aligned to 64 KiB pages`);
    }
    return byteLength;
  }

  #findCommand(name) {
    const commands = this.#module?.chromiumWasmHostCommands;
    if (commands && typeof commands[name] === "function") {
      return (...args) => commands[name](...args);
    }
    return null;
  }

  #callExport(name, returnType, argumentTypes, args) {
    const command = this.#findCommand(name);
    if (command) {
      return command(...args);
    }
    if (typeof this.#module?.ccall === "function") {
      return this.#module.ccall(name, returnType, argumentTypes, args);
    }
    const direct = this.#module?.[`_${name}`];
    if (typeof direct !== "function") {
      throw new Error(`required runtime export is missing: ${name}`);
    }
    if (
      !argumentTypes.includes("string") &&
      !argumentTypes.includes("array")
    ) {
      return direct(...args);
    }
    if (
      typeof this.#module._malloc !== "function" ||
      typeof this.#module._free !== "function" ||
      !this.#module.HEAPU8
    ) {
      throw new Error(
        `runtime export ${name} needs ccall or malloc string/array support`);
    }
    const allocated = [];
    try {
      const converted = args.map((value, index) => {
        const argumentType = argumentTypes[index];
        if (argumentType !== "string" && argumentType !== "array") {
          return value;
        }
        const encoded = argumentType === "string"
          ? UTF8_ENCODER.encode(`${value}\0`)
          : value instanceof Uint8Array
            ? value
            : null;
        if (encoded === null) {
          throw new Error(`runtime export ${name} needs a Uint8Array argument`);
        }
        if (encoded.byteLength === 0) {
          return 0;
        }
        const pointer = this.#module._malloc(encoded.length);
        if (!pointer) {
          throw new Error(`allocation failed while calling ${name}`);
        }
        allocated.push(pointer);
        // Fetch HEAPU8 after malloc because memory growth invalidates old views.
        const heap = this.#module.HEAPU8;
        if (!(heap instanceof Uint8Array) || pointer + encoded.length > heap.length) {
          throw new Error(`runtime heap changed while calling ${name}`);
        }
        heap.set(encoded, pointer);
        return pointer;
      });
      return direct(...converted);
    } finally {
      for (const pointer of allocated) {
        this.#module._free(pointer);
      }
    }
  }

  async initialize({
    modulePath,
    readyTimeoutMs = DEFAULT_RUNTIME_REGISTRATION_TIMEOUT_MS,
  }) {
    if (this.#lifecycle !== "new") {
      throw new Error("initialize may only be called once");
    }
    if (!crossOriginIsolated) {
      throw new Error("M3 host is not cross-origin isolated");
    }
    if (typeof SharedArrayBuffer !== "function") {
      throw new Error("SharedArrayBuffer is unavailable");
    }
    if (
      !Number.isFinite(readyTimeoutMs) ||
      readyTimeoutMs < 1000 ||
      readyTimeoutMs > 60000
    ) {
      throw new Error("initialize readyTimeoutMs is out of range");
    }
    const resolvedModule = new URL(modulePath, document.baseURI);
    if (resolvedModule.origin !== location.origin) {
      throw new Error("M3 module must be served from the host origin");
    }
    this.#lifecycle = "initializing";
    this.#canvas.focus();
    if (document.activeElement !== this.#canvas) {
      throw new Error("M3 canvas did not accept focus");
    }
    this.#recordHost("initialize:start");

    let moduleScriptBlob = null;
    if (resolvedModule.protocol !== "file:") {
      const moduleResponse = await fetch(
        resolvedModule.href, {cache: "no-store"});
      if (!moduleResponse.ok) {
        throw new Error(
          `M3 module request returned HTTP ${moduleResponse.status}`);
      }
      moduleScriptBlob = await moduleResponse.blob();
      if (moduleScriptBlob.size === 0) {
        throw new Error("M3 module loader is empty");
      }
    }
    const moduleOptions = {
      canvas: this.#canvas,
      // EXIT_RUNTIME tears down the prewarmed pthread pool after main returns.
      // Keep this false so shutdown can require Emscripten's final onExit.
      noExitRuntime: false,
      locateFile: (path) => new URL(path, resolvedModule).href,
      print: (line) => this.#logs.stdout.push(String(line)),
      printErr: (line) => this.#logs.stderr.push(String(line)),
      onRuntimeInitialized: () => {
        this.#runtimeInitialized = true;
        this.#recordHost("runtime:initialized");
      },
      onAbort: (reason) => {
        this._reportFatal(`abort: ${String(reason)}`);
      },
      onExit: (code) => {
        this._reportRuntimeExit(code);
      },
    };
    if (moduleScriptBlob) {
      // Pinned Emscripten's ES-module pthread path consumes this Blob when it
      // creates each worker. Reusing the already-fetched source avoids a burst
      // of independent worker-module requests and their unresolved
      // loading-workers dependencies.
      moduleOptions.mainScriptUrlOrBlob = moduleScriptBlob;
    }
    // Keep the main module on its original URL so Emscripten resolves and
    // streams the large Wasm binary with the same origin and base URL. Only
    // pthread workers consume the Blob above.
    const namespace = await import(resolvedModule.href);
    if (typeof namespace.default !== "function") {
      throw new Error("M3 module loader has no default factory export");
    }
    this.#module = await namespace.default(moduleOptions);
    this.#initialLinearMemoryBytes =
      this.#sampleLinearMemoryBytes("initial");
    this.#module.chromiumWasmHostBridge =
      globalThis.__chromiumWasmHostBridgeV1;
    this.#runtimeInitialized = true;
    const registrationDeadline = performance.now() + readyTimeoutMs;
    while (this.#reportedReadiness.shellReady !== true) {
      if (this.#fatalErrors.length > 0) {
        throw new Error(
          `runtime failed before shell registration: ${
            this.#fatalErrors.join("; ")}`);
      }
      if (performance.now() >= registrationDeadline) {
        throw new Error(
          "runtime did not register the Chromium UI runner before timeout");
      }
      await delay(25);
    }
    this.#lifecycle = "running";
    this.#recordHost("initialize:complete");
    return {
      ok: true,
      protocol: HOST_PROTOCOL,
      runtimeInitialized: true,
      shellReady: true,
      canvasFocused: document.activeElement === this.#canvas,
      versions: clone(this.#versions),
    };
  }

  async resize(width, height, devicePixelRatio = 1) {
    this.#requireRunning("resize");
    checkInteger(width, "width", 1, 16384);
    checkInteger(height, "height", 1, 16384);
    if (devicePixelRatio !== 1) {
      throw new Error("M3 only supports devicePixelRatio 1");
    }
    const result = this.#callExport(
      "chromium_wasm_host_resize",
      "number",
      ["number", "number", "number"],
      [width, height, devicePixelRatio],
    );
    if (result !== 1) {
      throw new Error(`runtime rejected resize with status ${String(result)}`);
    }
    this.#canvas.width = width;
    this.#canvas.height = height;
    this.#canvas.style.width = `${width}px`;
    this.#canvas.style.height = `${height}px`;
    this.#recordHost(`resize:${width}x${height}@${devicePixelRatio}`);
    return {ok: true, width, height, devicePixelRatio};
  }

  async loadURL(url) {
    this.#requireRunning("loadURL");
    const parsed = new URL(url);
    if (parsed.protocol !== "data:") {
      throw new Error("M3 only permits a deterministic data: navigation");
    }
    const result = this.#callExport(
      "chromium_wasm_host_load_url",
      "number",
      ["string"],
      [url],
    );
    if (result !== 1) {
      throw new Error(
        `runtime rejected data: navigation with status ${String(result)}`);
    }
    this.#recordHost("navigation:requested:data");
    return {ok: true, scheme: "data"};
  }

  async injectInput(event) {
    this.#requireRunning("injectInput");
    if (
      !event ||
      event.type !== "click" ||
      event.button !== 0
    ) {
      throw new Error("M3 input only supports a primary-button click");
    }
    const x = checkInteger(event.x, "input x", 0, DEFAULT_WIDTH - 1);
    const y = checkInteger(event.y, "input y", 0, DEFAULT_HEIGHT - 1);
    if (
      this.#pageProbe.inputClicks !== 0 ||
      this.#pageProbe.inputTrusted !== false ||
      this.#pageProbe.buttonText !== "READY"
    ) {
      throw new Error(
        "M3 input requires a pristine READY fixture probe");
    }
    const previousInputPostedAtFrameId = this.#inputPostedAtFrameId;
    const previousInteractionObservedAtFrameId =
      this.#interactionObservedAtFrameId;
    this.#inputPostedAtFrameId = this.#frame?.id ?? 0;
    this.#interactionObservedAtFrameId = null;
    let result;
    try {
      result = this.#callExport(
        "chromium_wasm_host_click",
        "number",
        ["number", "number", "number"],
        [x, y, event.button],
      );
    } catch (error) {
      this.#inputPostedAtFrameId = previousInputPostedAtFrameId;
      this.#interactionObservedAtFrameId =
        previousInteractionObservedAtFrameId;
      throw error;
    }
    if (result !== 1) {
      this.#inputPostedAtFrameId = previousInputPostedAtFrameId;
      this.#interactionObservedAtFrameId =
        previousInteractionObservedAtFrameId;
      throw new Error(
        `runtime rejected primary click with status ${String(result)}`);
    }
    this.#recordHost(`input:click:${x},${y}`);
    return {
      ok: true,
      accepted: true,
      code: "CLICK_POSTED",
      eventType: "click",
      x,
      y,
      button: 0,
    };
  }

  async requestScreenshot() {
    this.#requireRunning("requestScreenshot");
    if (!this.#frame) {
      throw new Error("cannot capture before the first compositor frame");
    }
    const dataURL = this.#canvas.toDataURL("image/png");
    const prefix = "data:image/png;base64,";
    if (!dataURL.startsWith(prefix)) {
      throw new Error("canvas did not produce a PNG screenshot");
    }
    return {
      ok: true,
      mimeType: "image/png",
      width: this.#canvas.width,
      height: this.#canvas.height,
      frame: clone(this.#frame),
      dataBase64: dataURL.slice(prefix.length),
    };
  }

  async readiness() {
    this.#requireRunning("readiness");
    const heartbeat = this.#heartbeat();
    const frameMatchesCanvas =
      this.#frame &&
      this.#frame.width === this.#canvas.width &&
      this.#frame.height === this.#canvas.height;
    const pageTimerTicks = Number(this.#pageProbe.timerTicks);
    const baseReady =
      this.#runtimeInitialized &&
      this.#reportedReadiness.shellReady === true &&
      this.#reportedReadiness.surfaceReady === true &&
      this.#navigation.committed === true &&
      this.#reportedReadiness.firstVisuallyNonEmptyPaint === true &&
      this.#pageProbe.ready === true &&
      Number.isFinite(pageTimerTicks) &&
      pageTimerTicks >= 3 &&
      Boolean(frameMatchesCanvas);
    const interactionReady =
      this.#pageProbe.inputClicks === 1 &&
      this.#pageProbe.inputTrusted === true &&
      this.#pageProbe.buttonText === "CLICKED" &&
      Number.isSafeInteger(this.#inputPostedAtFrameId) &&
      Number.isSafeInteger(this.#interactionObservedAtFrameId) &&
      Boolean(this.#frame) &&
      this.#frame.id > this.#interactionObservedAtFrameId;
    const ready =
      baseReady &&
      interactionReady &&
      heartbeat.elapsedMs >= REQUIRED_RUNTIME_MS &&
      heartbeat.timerDelta >= REQUIRED_TIMER_TICKS &&
      heartbeat.animationFrameDelta >= REQUIRED_ANIMATION_FRAMES &&
      heartbeat.maxTimerGapMs <= MAXIMUM_TIMER_GAP_MS &&
      this.#fatalErrors.length === 0;
    return {
      protocol: HOST_PROTOCOL,
      ready,
      baseReady,
      interactionReady,
      runtimeInitialized: this.#runtimeInitialized,
      shellReady: this.#reportedReadiness.shellReady === true,
      surfaceReady: this.#reportedReadiness.surfaceReady === true,
      navigationCommitted: this.#navigation.committed === true,
      firstVisuallyNonEmptyPaint:
        this.#reportedReadiness.firstVisuallyNonEmptyPaint === true,
      pageReady: this.#pageProbe.ready === true,
      navigation: clone(this.#navigation),
      pageProbe: clone(this.#pageProbe),
      ozoneFocusState: this.#ozoneFocusState
        ? clone(this.#ozoneFocusState)
        : null,
      ozoneTextInputState: this.#ozoneTextInputState
        ? clone(this.#ozoneTextInputState)
        : null,
      frame: this.#frame ? clone(this.#frame) : null,
      inputPostedAtFrameId: this.#inputPostedAtFrameId,
      interactionObservedAtFrameId: this.#interactionObservedAtFrameId,
      fatalErrors: clone(this.#fatalErrors),
      heartbeat,
      pointerInput: this.#pointerInputStatus(),
      wheelInput: this.#wheelInputStatus(),
      keyboardInput: this.#keyboardInputStatus(),
      focusInput: this.#focusInputStatus(),
      imeProxyInput: this.#imeProxyInputStatus(),
    };
  }

  async logs() {
    return clone(this.#logs);
  }

  async shutdown(timeoutMs = DEFAULT_SHUTDOWN_TIMEOUT_MS) {
    this.#requireRunning("shutdown");
    if (
      !Number.isFinite(timeoutMs) ||
      timeoutMs < 1000 ||
      timeoutMs > 60000
    ) {
      throw new Error("shutdown timeoutMs is out of range");
    }
    this.#cancelActiveM4Pointer("shutdown");
    this.#releaseM4KeyboardKeys("shutdown");
    this.#deactivateM4HostWindow("shutdown");
    this.#lifecycle = "shutting-down";
    let result;
    try {
      result = this.#callExport(
        "chromium_wasm_host_shutdown", "number", [], []);
    } catch (error) {
      this.#lifecycle = "running";
      throw error;
    }
    if (result !== 1) {
      this.#lifecycle = "running";
      throw new Error(
        `runtime rejected shutdown with status ${String(result)}`);
    }
    this.#recordHost("shutdown:accepted");
    let timeoutHandle;
    const timeout = new Promise((_, reject) => {
      timeoutHandle = setTimeout(() => {
        reject(
          new Error(
            "Content Shell did not complete shutdown before timeout"));
      }, timeoutMs);
    });
    try {
      const [processExit, runtimeExit] = await Promise.race([
        Promise.all([
          this.#processExitPromise,
          this.#runtimeExitPromise,
        ]),
        timeout,
      ]);
      if (processExit.exitCode !== 0) {
        throw new Error(
          `Content Shell exited with status ${processExit.exitCode}`);
      }
      if (runtimeExit.exitCode !== processExit.exitCode) {
        throw new Error(
          "Emscripten runtime exit did not match Content Shell exit");
      }
      if (runtimeExit.sequence <= processExit.sequence) {
        throw new Error(
          "Emscripten runtime exited before Content Shell completed");
      }
      // Emscripten calls onExit only after requesting termination of every
      // running and prewarmed pthread worker. Let those asynchronous browser
      // worker terminations and any trailing rejection surface before
      // certifying teardown.
      await delay(25);
      if (this.#fatalErrors.length > 0) {
        throw new Error(
          `Content Shell teardown reported: ${this.#fatalErrors.join("; ")}`);
      }
      // WebAssembly linear memory cannot shrink, so a fresh post-teardown
      // view reports the peak byte length reached during this lifecycle.
      const peakLinearMemoryBytes =
        this.#sampleLinearMemoryBytes("post-shutdown");
      if (peakLinearMemoryBytes < this.#initialLinearMemoryBytes) {
        throw new Error(
          "post-shutdown linear memory is smaller than its initial size");
      }
      this.#lifecycle = "shutdown";
      this.#recordHost("shutdown:complete");
      return {
        ok: true,
        accepted: true,
        complete: true,
        exitCode: processExit.exitCode,
        runtimeExitCode: runtimeExit.exitCode,
        linearMemory: {
          initialBytes: this.#initialLinearMemoryBytes,
          peakBytes: peakLinearMemoryBytes,
        },
      };
    } catch (error) {
      this.#lifecycle = "failed";
      this.#recordHost(`shutdown:failed:${String(error)}`);
      throw error;
    } finally {
      clearTimeout(timeoutHandle);
      this.#releaseHost();
    }
  }

  _reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL) {
        throw new Error("frame report protocol mismatch");
      }
      const id = Number(report.id);
      const width = Number(report.width);
      const height = Number(report.height);
      const timestampMs = Number(report.timestampMs);
      if (
        !Number.isSafeInteger(id) ||
        id < 1 ||
        !Number.isInteger(width) ||
        width < 1 ||
        !Number.isInteger(height) ||
        height < 1 ||
        !Number.isFinite(timestampMs) ||
        timestampMs < 0
      ) {
        throw new Error("frame report contains invalid metadata");
      }
      if (this.#frame && id <= this.#frame.id) {
        throw new Error("frame IDs must increase monotonically");
      }
      this.#frame = {id, width, height, timestampMs};
    } catch (error) {
      this._reportFatal(`invalid frame report: ${String(error)}`);
    }
  }

  _reportReadiness(value) {
    try {
      const report = asReport(value, "readiness report");
      if (report.protocol !== HOST_PROTOCOL) {
        throw new Error("readiness report protocol mismatch");
      }
      this.#reportedReadiness = {
        shellReady: report.shellReady === true,
        surfaceReady: report.surfaceReady === true,
        firstVisuallyNonEmptyPaint:
          report.firstVisuallyNonEmptyPaint === true,
      };
    } catch (error) {
      this._reportFatal(`invalid readiness report: ${String(error)}`);
    }
  }

  _reportNavigation(value) {
    try {
      const report = asReport(value, "navigation report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.committed !== true ||
        report.scheme !== "data"
      ) {
        throw new Error("navigation report must commit a data: URL");
      }
      this.#navigation = {committed: true, scheme: "data"};
      this.#resetHeartbeatWindow("data-navigation-committed");
    } catch (error) {
      this._reportFatal(`invalid navigation report: ${String(error)}`);
    }
  }

  _reportPageProbe(value) {
    try {
      const report = asReport(value, "page probe");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.fixture !== this.#fixture
      ) {
        throw new Error("page probe identity mismatch");
      }
      this.#pageProbe = clone(report);
      if (
        this.#interactionObservedAtFrameId === null &&
        Number.isSafeInteger(this.#inputPostedAtFrameId) &&
        report.inputClicks === 1 &&
        report.inputTrusted === true &&
        report.buttonText === "CLICKED"
      ) {
        this.#interactionObservedAtFrameId = this.#frame?.id ?? 0;
      }
    } catch (error) {
      this._reportFatal(`invalid page probe: ${String(error)}`);
    }
  }

  _reportOzoneFocusState(value) {
    try {
      const report = asReport(value, "Ozone focus-state report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        typeof report.keyboardTargetPresent !== "boolean" ||
        typeof report.active !== "boolean"
      ) {
        throw new Error("Ozone focus-state report is invalid");
      }
      this.#ozoneFocusState = {
        sequence: ++this.#ozoneFocusReportSequence,
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      };
      this.#recordHost(
        "ozone:focus:" +
        (report.keyboardTargetPresent ? "keyboard-target-present" :
          "keyboard-target-absent") + ":" +
        (report.active ? "active" : "inactive"));
      this.#maybeActivateM4ImeProxy();
    } catch (error) {
      this._reportFatal(
        `invalid Ozone focus-state report: ${String(error)}`);
    }
  }

  _reportOzoneTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        typeof report.focusedClientPresent !== "boolean" ||
        typeof report.editable !== "boolean" ||
        typeof report.canComposeInline !== "boolean" ||
        (report.editable === true && report.focusedClientPresent !== true) ||
        (report.canComposeInline === true && report.editable !== true)
      ) {
        throw new Error("Ozone text-input state report is invalid");
      }
      this.#ozoneTextInputState = {
        sequence: ++this.#ozoneTextInputReportSequence,
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      };
      this.#recordHost(
        "ozone:text-input:" +
        (report.focusedClientPresent ? "client-present" : "client-absent") +
        ":" + (report.editable ? "editable" : "noneditable") +
        ":" + (report.canComposeInline ? "inline" : "no-inline"));
      this.#maybeActivateM4ImeProxy();
      if (
        this.#imeProxyInputEnabled &&
        document.activeElement === this.#imeProxy &&
        !this.#hasM4EditableTextInputAcknowledgement()
      ) {
        // WasmInputMethod clears its active composition before publishing this
        // noneditable/focus-loss state. Reset the host mirror only: a second
        // ClearCompositionText would be correctly rejected by the now-empty
        // native state and would turn a normal focus change into a failure.
        this.#clearM4ImeProxyState("native-text-input-lost", {
          queueNativeClear: false,
        });
        this.#canvas.focus({preventScroll: true});
      }
    } catch (error) {
      this._reportFatal(
        `invalid Ozone text-input state report: ${String(error)}`);
    }
  }

  _reportOzoneTextInputDelivery(value) {
    try {
      const report = asReport(value, "Ozone text-input delivery report");
      const actionName = this.#imeProxyActionName(report.action);
      if (
        report.protocol !== HOST_PROTOCOL || actionName === null ||
        !Number.isSafeInteger(report.sessionId) || report.sessionId < 1 ||
        !Number.isSafeInteger(report.sequence) || report.sequence < 1 ||
        typeof report.accepted !== "boolean"
      ) {
        throw new Error("Ozone text-input delivery report is invalid");
      }
      const request = this.#imeProxyNativeRequests.find(
        (candidate) => candidate.action === report.action &&
          candidate.sessionId === report.sessionId &&
          candidate.sequence === report.sequence);
      if (!request || request.queued !== true ||
          request.deliveryAccepted !== null) {
        throw new Error("Ozone text-input delivery does not match a queue");
      }
      request.deliveryAccepted = report.accepted;
      this.#recordHost(
        `ozone:text-input-delivery:${actionName}:` +
        (report.accepted ? "accepted" : "rejected"));
      if (!report.accepted) {
        if (this.#imeProxyFailure === null &&
            request.sessionId === this.#imeProxySessionId) {
          this.#imeProxyFailure = "NATIVE_TEXT_INPUT_DELIVERY_REJECTED";
        }
        return;
      }
      if (
        request.sessionId === this.#imeProxySessionId &&
        this.#imeProxyNativeTerminalAction?.sequence === request.sequence &&
        request.action !== M4_IME_TEXT_ACTION.setComposition
      ) {
        this.#imeProxyNativeComposition = null;
        this.#imeProxyNativeTerminalAction = null;
      }
    } catch (error) {
      this._reportFatal(
        `invalid Ozone text-input delivery report: ${String(error)}`);
    }
  }

  _reportProcessExit(value) {
    try {
      const report = asReport(value, "process exit report");
      const exitCode = report.exitCode;
      if (
        report.protocol !== HOST_PROTOCOL ||
        !Number.isSafeInteger(exitCode) ||
        this.#processExit
      ) {
        throw new Error("process exit report is invalid or duplicated");
      }
      this.#processExit = {
        exitCode,
        sequence: ++this.#exitReportSequence,
      };
      this.#recordHost(`process:exit:${exitCode}`);
      if (exitCode !== 0) {
        this._reportFatal(`Content Shell exited with status ${exitCode}`);
      } else if (this.#lifecycle !== "shutting-down") {
        this._reportFatal("Content Shell exited before shutdown was requested");
      }
      this.#resolveProcessExit(this.#processExit);
    } catch (error) {
      this._reportFatal(`invalid process exit report: ${String(error)}`);
    }
  }

  _reportRuntimeExit(value) {
    try {
      const exitCode = value;
      if (!Number.isSafeInteger(exitCode) || this.#runtimeExit) {
        throw new Error("runtime exit report is invalid or duplicated");
      }
      this.#runtimeExit = {
        exitCode,
        sequence: ++this.#exitReportSequence,
      };
      this.#recordHost(`runtime:exit:${exitCode}`);
      if (exitCode !== 0) {
        this._reportFatal(`Emscripten runtime exited with status ${exitCode}`);
      } else if (this.#lifecycle !== "shutting-down") {
        this._reportFatal(
          "Emscripten runtime exited before shutdown was requested");
      }
      this.#resolveRuntimeExit(this.#runtimeExit);
    } catch (error) {
      this._reportFatal(`invalid runtime exit report: ${String(error)}`);
    }
  }

  _reportFatal(message) {
    const text = String(message);
    this.#fatalErrors.push(text);
    this.#logs.stderr.push(`HOST_FATAL: ${text}`);
  }
}

function failureResult(versions, host, error) {
  return {
    protocol: HOST_PROTOCOL,
    case: M3_CASE,
    status: "fail",
    crossOriginIsolated,
    sharedArrayBuffer: typeof SharedArrayBuffer === "function",
    canvasFocused:
      document.activeElement === document.querySelector("#browser-canvas"),
    versions,
    readiness: null,
    heartbeat: null,
    inputResult: null,
    screenshot: null,
    logs: host ? {host: [], stdout: [], stderr: []} : null,
    shutdown: null,
    failedChecks: ["exception"],
    error: String(error),
  };
}

async function postResult(token, result) {
  const response = await fetch(
    `/__m3__/result/${encodeURIComponent(token)}`,
    {
      method: "POST",
      cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(result),
    });
  if (!response.ok) {
    throw new Error(`result endpoint returned HTTP ${response.status}`);
  }
}

export async function runM3SmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M3_CASE) {
      throw new Error("M3 case query mismatch");
    }
    if (!token) {
      throw new Error("missing M3 result token");
    }
    host = new ChromiumWasmM3Host(canvas, versions);
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;

    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(640, 480, 1);
    let resizedFrame = null;
    while (performance.now() < deadline) {
      const resizeReadiness = await host.readiness();
      if (
        resizeReadiness.frame?.width === 640 &&
        resizeReadiness.frame?.height === 480
      ) {
        resizedFrame = resizeReadiness.frame;
        break;
      }
      await delay(25);
    }
    if (!resizedFrame) {
      throw new Error("M3 runtime did not present the 640x480 resize probe");
    }
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    let restoredFrame = null;
    while (performance.now() < deadline) {
      const resizeReadiness = await host.readiness();
      if (
        resizeReadiness.frame?.id > resizedFrame.id &&
        resizeReadiness.frame?.width === DEFAULT_WIDTH &&
        resizeReadiness.frame?.height === DEFAULT_HEIGHT
      ) {
        restoredFrame = resizeReadiness.frame;
        break;
      }
      await delay(25);
    }
    if (!restoredFrame) {
      throw new Error("M3 runtime did not restore the 800x600 surface");
    }
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        `M3 base readiness timeout: ${JSON.stringify(readiness)}`);
    }

    const buttonCenterX = Number(readiness.pageProbe.buttonCenterX);
    const buttonCenterY = Number(readiness.pageProbe.buttonCenterY);
    const inputResult = await host.injectInput({
      type: "click",
      x: buttonCenterX,
      y: buttonCenterY,
      button: 0,
    });
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        readiness.pageProbe.inputClicks === 1 &&
        readiness.pageProbe.inputTrusted === true &&
        readiness.pageProbe.buttonText === "CLICKED" &&
        Number.isSafeInteger(readiness.interactionObservedAtFrameId)
      ) {
        break;
      }
      await delay(50);
    }
    if (!Number.isSafeInteger(readiness?.interactionObservedAtFrameId)) {
      throw new Error(
        `M3 trusted input observation timeout: ${JSON.stringify(readiness)}`);
    }
    const interactionObservedAtFrameId =
      readiness.interactionObservedAtFrameId;

    // The CLICKED paint can already be the current compositor frame when the
    // periodic page probe observes it. Force and prove a later runtime redraw
    // so the screenshot cannot be backed only by a pre-observation frame.
    await host.resize(POST_INPUT_REDRAW_WIDTH, DEFAULT_HEIGHT, 1);
    let redrawFrame = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        readiness.frame?.id > interactionObservedAtFrameId &&
        readiness.frame?.width === POST_INPUT_REDRAW_WIDTH &&
        readiness.frame?.height === DEFAULT_HEIGHT
      ) {
        redrawFrame = readiness.frame;
        break;
      }
      await delay(25);
    }
    if (!redrawFrame) {
      throw new Error("M3 runtime did not present the post-input redraw");
    }
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    let postInputRestoredFrame = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        readiness.frame?.id > redrawFrame.id &&
        readiness.frame?.width === DEFAULT_WIDTH &&
        readiness.frame?.height === DEFAULT_HEIGHT
      ) {
        postInputRestoredFrame = readiness.frame;
        break;
      }
      await delay(25);
    }
    if (!postInputRestoredFrame) {
      throw new Error(
        "M3 runtime did not restore the surface after the post-input redraw");
    }
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.ready) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.ready) {
      throw new Error(
        `M3 post-input readiness timeout: ${JSON.stringify(readiness)}`);
    }

    const screenshot = await host.requestScreenshot();
    const heartbeat = readiness.heartbeat;
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logsAfterShutdown = await host.logs();
    const logs = logsAfterShutdown;

    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      readiness: readiness.ready === true,
      inputDelivered:
        inputResult.ok === true &&
        inputResult.accepted === true &&
        inputResult.code === "CLICK_POSTED" &&
        readiness.pageProbe.inputClicks === 1 &&
        readiness.pageProbe.inputTrusted === true &&
        readiness.pageProbe.buttonText === "CLICKED" &&
        readiness.interactionReady === true,
      screenshot:
        screenshot.mimeType === "image/png" &&
        screenshot.width === DEFAULT_WIDTH &&
        screenshot.height === DEFAULT_HEIGHT &&
        screenshot.dataBase64.length > 0,
      shutdown:
        shutdown.ok === true &&
        shutdown.complete === true &&
        shutdown.exitCode === 0 &&
        shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M3_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      heartbeat,
      inputResult,
      screenshot,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = failureResult(versions, host, error);
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
      }
      try {
        result.readiness = await host.readiness();
        result.heartbeat = result.readiness.heartbeat;
      } catch (diagnosticError) {
        result.error += `; readiness diagnostics: ${String(diagnosticError)}`;
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(
    {...result, screenshot: result.screenshot
      ? {...result.screenshot, dataBase64: "<omitted>"}
      : null},
    null,
    2);
  await postResult(token, result);
  return result;
}

async function runM4OzonePointerSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_CASE) {
      throw new Error("M4 case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 result token");
    }
    host = new ChromiumWasmM3Host(canvas, versions, {fixture: M4_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        `M4 base readiness timeout: ${JSON.stringify(readiness)}`);
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 target y", 0, DEFAULT_HEIGHT - 1);
    const listeners = host.enableM4PointerInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4State = {
      state: "awaiting-dom-pointer",
      targetX,
      targetY,
      listeners,
      focusListeners,
    };
    statusElement.textContent = "M4 ready for trusted canvas pointer input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        readiness.pageProbe.activationCount === 1 &&
        readiness.pageProbe.clickTrusted === true &&
        readiness.pageProbe.resultText === "ACTIVATED" &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueued = pointer?.lastQueued;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueued?.type !== "up" ||
      readiness.pageProbe.activationCount !== 1 ||
      readiness.pageProbe.clickTrusted !== true ||
      readiness.pageProbe.resultText !== "ACTIVATED" ||
      !(readiness.frame?.id > lastQueued.frameIdBefore)
    ) {
      throw new Error(
        `M4 trusted Ozone pointer timeout: ${JSON.stringify(readiness)}`);
    }
    window.__chromiumWasmM4State = {
      state: "input-delivered",
      targetX,
      targetY,
      pointer: clone(pointer),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      trustedDomInput:
        pointer.trustedCount >= 2 && pointer.queuedCount >= 2,
      ozoneDelivered:
        readiness.pageProbe.activationCount === 1 &&
        readiness.pageProbe.clickTrusted === true &&
        readiness.pageProbe.resultText === "ACTIVATED" &&
        readiness.frame.id > lastQueued.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
      } catch (diagnosticError) {
        result.error += `; readiness diagnostics: ${String(diagnosticError)}`;
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneWheelSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_WHEEL_CASE) {
      throw new Error("M4 wheel case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 wheel result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_WHEEL_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        `M4 wheel base readiness timeout: ${JSON.stringify(readiness)}`);
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 wheel target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 wheel target y", 0, DEFAULT_HEIGHT - 1);
    const listeners = host.enableM4WheelInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4WheelState = {
      state: "awaiting-dom-wheel",
      targetX,
      targetY,
      listeners,
      focusListeners,
    };
    statusElement.textContent = "M4 ready for trusted canvas wheel input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const wheel = readiness.wheelInput;
      const lastQueued = wheel.lastQueued;
      const pageWheel = readiness.pageProbe.wheelEvents;
      if (
        wheel.queuedCount >= 1 &&
        lastQueued?.type === "wheel" &&
        lastQueued?.defaultPrevented === true &&
        pageWheel?.count >= 1 &&
        pageWheel?.trusted === true &&
        pageWheel?.deltaMode === 0 &&
        pageWheel?.deltaX === 0 &&
        pageWheel?.deltaY === 160 &&
        readiness.pageProbe.innerScrollTop > 0 &&
        readiness.pageProbe.outerScrollTop === 0 &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const wheel = readiness?.wheelInput;
    const lastQueued = wheel?.lastQueued;
    const pageWheel = readiness?.pageProbe?.wheelEvents;
    if (
      !readiness ||
      wheel?.queuedCount < 1 ||
      lastQueued?.type !== "wheel" ||
      lastQueued?.defaultPrevented !== true ||
      pageWheel?.count < 1 ||
      pageWheel?.trusted !== true ||
      pageWheel?.deltaMode !== 0 ||
      pageWheel?.deltaX !== 0 ||
      pageWheel?.deltaY !== 160 ||
      !(readiness.pageProbe.innerScrollTop > 0) ||
      readiness.pageProbe.outerScrollTop !== 0 ||
      !(readiness.frame?.id > lastQueued.frameIdBefore)
    ) {
      throw new Error(
        `M4 trusted Ozone wheel timeout: ${JSON.stringify(readiness)}`);
    }
    window.__chromiumWasmM4WheelState = {
      state: "input-delivered",
      targetX,
      targetY,
      wheel: clone(wheel),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      trustedDomInput:
        wheel.trustedCount >= 1 && wheel.queuedCount >= 1 &&
        lastQueued.trusted === true && lastQueued.defaultPrevented === true,
      ozoneDelivered:
        pageWheel.count >= 1 &&
        pageWheel.trusted === true &&
        pageWheel.deltaMode === 0 &&
        pageWheel.deltaX === 0 &&
        pageWheel.deltaY === 160 &&
        readiness.pageProbe.innerScrollTop > 0 &&
        readiness.pageProbe.outerScrollTop === 0 &&
        readiness.frame.id > lastQueued.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_WHEEL_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      wheelInput: wheel,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_WHEEL_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      wheelInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
      }
      try {
        result.readiness = await host.readiness();
        result.wheelInput = result.readiness.wheelInput;
      } catch (diagnosticError) {
        result.error += `; readiness diagnostics: ${String(diagnosticError)}`;
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneKeyboardSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_KEYBOARD_CASE) {
      throw new Error("M4 keyboard case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 keyboard result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_KEYBOARD_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 keyboard base readiness timeout: " + JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 keyboard target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 keyboard target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4KeyboardState = {
      state: "awaiting-dom-keyboard-activation",
      targetX,
      targetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click and raw ArrowDown input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "keyboard-target" &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueuedPointer = pointer?.lastQueued;
    const pageAfterActivation = readiness?.pageProbe;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueuedPointer?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "keyboard-target" ||
      !(readiness.frame?.id > lastQueuedPointer.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone keyboard activation timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4KeyboardState = {
      state: "awaiting-dom-key",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(readiness.keyboardInput),
    };
    statusElement.textContent =
      "M4 ready for trusted canvas raw ArrowDown input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const keyDown = keyboard.lastQueuedDown;
      const keyUp = keyboard.lastQueuedUp;
      const pageProbe = readiness.pageProbe;
      const keyEvents = pageProbe?.keyEvents;
      const textInputEvents = pageProbe?.textInputEvents;
      if (
        keyboard.queuedCount >= 2 &&
        keyboard.pressedCodes.length === 0 &&
        keyDown?.type === "down" &&
        keyDown?.defaultPrevented === true &&
        keyUp?.type === "up" &&
        keyUp?.defaultPrevented === true &&
        keyEvents?.keydownCount === 1 &&
        keyEvents?.keyupCount === 1 &&
        keyEvents?.keydownTrusted === true &&
        keyEvents?.keyupTrusted === true &&
        keyEvents?.keydownCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keyupCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keydownKey === "ArrowDown" &&
        keyEvents?.keyupKey === "ArrowDown" &&
        keyEvents?.keydownRepeat === false &&
        keyEvents?.keyupRepeat === false &&
        keyEvents?.keydownComposing === false &&
        keyEvents?.keyupComposing === false &&
        keyEvents?.keydownDefaultPrevented === false &&
        keyEvents?.keyupDefaultPrevented === false &&
        keyEvents?.keydownTargetId === "keyboard-target" &&
        keyEvents?.keyupTargetId === "keyboard-target" &&
        textInputEvents?.beforeinputCount === 0 &&
        textInputEvents?.inputCount === 0 &&
        textInputEvents?.compositionstartCount === 0 &&
        textInputEvents?.compositionupdateCount === 0 &&
        textInputEvents?.compositionendCount === 0 &&
        pageProbe?.activeElementId === "keyboard-target" &&
        pageProbe?.scrollTop > 0 &&
        pageProbe?.resultText === "ARROW DOWN RECEIVED" &&
        readiness.frame?.id > keyDown.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboard = readiness?.keyboardInput;
    const lastQueuedDown = keyboard?.lastQueuedDown;
    const lastQueuedUp = keyboard?.lastQueuedUp;
    const pageProbe = readiness?.pageProbe;
    const keyEvents = pageProbe?.keyEvents;
    const textInputEvents = pageProbe?.textInputEvents;
    if (
      !readiness ||
      keyboard?.queuedCount < 2 ||
      keyboard?.pressedCodes?.length !== 0 ||
      lastQueuedDown?.type !== "down" ||
      lastQueuedDown?.defaultPrevented !== true ||
      lastQueuedUp?.type !== "up" ||
      lastQueuedUp?.defaultPrevented !== true ||
      keyEvents?.keydownCount !== 1 ||
      keyEvents?.keyupCount !== 1 ||
      keyEvents?.keydownTrusted !== true ||
      keyEvents?.keyupTrusted !== true ||
      keyEvents?.keydownCode !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keyupCode !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keydownKey !== "ArrowDown" ||
      keyEvents?.keyupKey !== "ArrowDown" ||
      keyEvents?.keydownRepeat !== false ||
      keyEvents?.keyupRepeat !== false ||
      keyEvents?.keydownComposing !== false ||
      keyEvents?.keyupComposing !== false ||
      keyEvents?.keydownDefaultPrevented !== false ||
      keyEvents?.keyupDefaultPrevented !== false ||
      keyEvents?.keydownTargetId !== "keyboard-target" ||
      keyEvents?.keyupTargetId !== "keyboard-target" ||
      textInputEvents?.beforeinputCount !== 0 ||
      textInputEvents?.inputCount !== 0 ||
      textInputEvents?.compositionstartCount !== 0 ||
      textInputEvents?.compositionupdateCount !== 0 ||
      textInputEvents?.compositionendCount !== 0 ||
      pageProbe?.activeElementId !== "keyboard-target" ||
      !(pageProbe?.scrollTop > 0) ||
      pageProbe?.resultText !== "ARROW DOWN RECEIVED" ||
      !(readiness.frame?.id > lastQueuedDown.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone keyboard timeout: " + JSON.stringify(readiness));
    }
    window.__chromiumWasmM4KeyboardState = {
      state: "input-delivered",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboard),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      pointerActivation:
        pointer.trustedCount >= 2 &&
        pointer.queuedCount >= 2 &&
        lastQueuedPointer.trusted === true &&
        lastQueuedPointer.queued === true,
      trustedDomInput:
        keyboard.trustedCount >= 2 &&
        keyboard.queuedCount >= 2 &&
        lastQueuedDown.trusted === true &&
        lastQueuedDown.queued === true &&
        lastQueuedDown.defaultPrevented === true &&
        lastQueuedUp.trusted === true &&
        lastQueuedUp.queued === true &&
        lastQueuedUp.defaultPrevented === true,
      ozoneDelivered:
        pageProbe.activationCount === 1 &&
        pageProbe.clickTrusted === true &&
        pageProbe.focusCount >= 1 &&
        pageProbe.focusTrusted === true &&
        pageProbe.activeElementId === "keyboard-target" &&
        keyEvents.keydownCount === 1 &&
        keyEvents.keyupCount === 1 &&
        keyEvents.keydownTrusted === true &&
        keyEvents.keyupTrusted === true &&
        keyEvents.keydownCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents.keyupCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents.keydownKey === "ArrowDown" &&
        keyEvents.keyupKey === "ArrowDown" &&
        keyEvents.keydownRepeat === false &&
        keyEvents.keyupRepeat === false &&
        keyEvents.keydownComposing === false &&
        keyEvents.keyupComposing === false &&
        keyEvents.keydownDefaultPrevented === false &&
        keyEvents.keyupDefaultPrevented === false &&
        keyEvents.keydownTargetId === "keyboard-target" &&
        keyEvents.keyupTargetId === "keyboard-target" &&
        textInputEvents.beforeinputCount === 0 &&
        textInputEvents.inputCount === 0 &&
        textInputEvents.compositionstartCount === 0 &&
        textInputEvents.compositionupdateCount === 0 &&
        textInputEvents.compositionendCount === 0 &&
        pageProbe.scrollTop > 0 &&
        pageProbe.resultText === "ARROW DOWN RECEIVED" &&
        readiness.frame.id > lastQueuedDown.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_KEYBOARD_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_KEYBOARD_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzonePrintableKeySmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_PRINTABLE_KEY_CASE) {
      throw new Error("M4 printable-key case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 printable-key result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_PRINTABLE_KEY_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 printable-key base readiness timeout: " +
        JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 printable-key target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 printable-key target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4PrintableKeyState = {
      state: "awaiting-dom-printable-key-activation",
      targetX,
      targetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click and raw KeyA input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "" &&
        pageProbe?.selectionStart === 0 &&
        pageProbe?.selectionEnd === 0 &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueuedPointer = pointer?.lastQueued;
    const pageAfterActivation = readiness?.pageProbe;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueuedPointer?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "editable-target" ||
      pageAfterActivation?.value !== "" ||
      pageAfterActivation?.selectionStart !== 0 ||
      pageAfterActivation?.selectionEnd !== 0 ||
      !(readiness.frame?.id > lastQueuedPointer.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone printable-key activation timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4PrintableKeyState = {
      state: "awaiting-dom-printable-key",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(readiness.keyboardInput),
    };
    statusElement.textContent =
      "M4 ready for trusted canvas raw KeyA input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const keyDown = keyboard.lastQueuedDown;
      const keyUp = keyboard.lastQueuedUp;
      const pageProbe = readiness.pageProbe;
      const keyEvents = pageProbe?.keyEvents;
      const textInputEvents = pageProbe?.textInputEvents;
      if (
        keyboard.receivedCount === 2 &&
        keyboard.trustedCount === 2 &&
        keyboard.queuedCount === 2 &&
        keyboard.pressedCodes.length === 0 &&
        keyDown?.type === "down" &&
        keyDown?.code === M4_PRINTABLE_KEY_DOM_CODE &&
        keyDown?.key === M4_PRINTABLE_KEY_DOM_KEY &&
        keyDown?.defaultPrevented === true &&
        keyUp?.type === "up" &&
        keyUp?.code === M4_PRINTABLE_KEY_DOM_CODE &&
        keyUp?.key === M4_PRINTABLE_KEY_DOM_KEY &&
        keyUp?.defaultPrevented === true &&
        keyEvents?.keydownCount === 1 &&
        keyEvents?.keyupCount === 1 &&
        keyEvents?.keydownTrusted === true &&
        keyEvents?.keyupTrusted === true &&
        keyEvents?.keydownCode === M4_PRINTABLE_KEY_DOM_CODE &&
        keyEvents?.keyupCode === M4_PRINTABLE_KEY_DOM_CODE &&
        keyEvents?.keydownKey === M4_PRINTABLE_KEY_DOM_KEY &&
        keyEvents?.keyupKey === M4_PRINTABLE_KEY_DOM_KEY &&
        keyEvents?.keydownRepeat === false &&
        keyEvents?.keyupRepeat === false &&
        keyEvents?.keydownComposing === false &&
        keyEvents?.keyupComposing === false &&
        keyEvents?.keydownDefaultPrevented === false &&
        keyEvents?.keyupDefaultPrevented === false &&
        keyEvents?.keydownTargetId === "editable-target" &&
        keyEvents?.keyupTargetId === "editable-target" &&
        textInputEvents?.beforeinputCount === 1 &&
        textInputEvents?.inputCount === 1 &&
        textInputEvents?.beforeinputTrusted === true &&
        textInputEvents?.inputTrusted === true &&
        textInputEvents?.beforeinputInputType === "insertText" &&
        textInputEvents?.inputInputType === "insertText" &&
        textInputEvents?.beforeinputData === M4_PRINTABLE_KEY_DOM_KEY &&
        textInputEvents?.inputData === M4_PRINTABLE_KEY_DOM_KEY &&
        textInputEvents?.beforeinputTargetId === "editable-target" &&
        textInputEvents?.inputTargetId === "editable-target" &&
        textInputEvents?.compositionstartCount === 0 &&
        textInputEvents?.compositionupdateCount === 0 &&
        textInputEvents?.compositionendCount === 0 &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === M4_PRINTABLE_KEY_DOM_KEY &&
        pageProbe?.selectionStart === 1 &&
        pageProbe?.selectionEnd === 1 &&
        pageProbe?.resultText === "TEXT INPUT RECEIVED" &&
        readiness.frame?.id > keyDown.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboard = readiness?.keyboardInput;
    const lastQueuedDown = keyboard?.lastQueuedDown;
    const lastQueuedUp = keyboard?.lastQueuedUp;
    const pageProbe = readiness?.pageProbe;
    const keyEvents = pageProbe?.keyEvents;
    const textInputEvents = pageProbe?.textInputEvents;
    if (
      !readiness ||
      keyboard?.receivedCount !== 2 ||
      keyboard?.trustedCount !== 2 ||
      keyboard?.queuedCount !== 2 ||
      keyboard?.pressedCodes?.length !== 0 ||
      lastQueuedDown?.type !== "down" ||
      lastQueuedDown?.code !== M4_PRINTABLE_KEY_DOM_CODE ||
      lastQueuedDown?.key !== M4_PRINTABLE_KEY_DOM_KEY ||
      lastQueuedDown?.defaultPrevented !== true ||
      lastQueuedUp?.type !== "up" ||
      lastQueuedUp?.code !== M4_PRINTABLE_KEY_DOM_CODE ||
      lastQueuedUp?.key !== M4_PRINTABLE_KEY_DOM_KEY ||
      lastQueuedUp?.defaultPrevented !== true ||
      keyEvents?.keydownCount !== 1 ||
      keyEvents?.keyupCount !== 1 ||
      keyEvents?.keydownTrusted !== true ||
      keyEvents?.keyupTrusted !== true ||
      keyEvents?.keydownCode !== M4_PRINTABLE_KEY_DOM_CODE ||
      keyEvents?.keyupCode !== M4_PRINTABLE_KEY_DOM_CODE ||
      keyEvents?.keydownKey !== M4_PRINTABLE_KEY_DOM_KEY ||
      keyEvents?.keyupKey !== M4_PRINTABLE_KEY_DOM_KEY ||
      keyEvents?.keydownRepeat !== false ||
      keyEvents?.keyupRepeat !== false ||
      keyEvents?.keydownComposing !== false ||
      keyEvents?.keyupComposing !== false ||
      keyEvents?.keydownDefaultPrevented !== false ||
      keyEvents?.keyupDefaultPrevented !== false ||
      keyEvents?.keydownTargetId !== "editable-target" ||
      keyEvents?.keyupTargetId !== "editable-target" ||
      textInputEvents?.beforeinputCount !== 1 ||
      textInputEvents?.inputCount !== 1 ||
      textInputEvents?.beforeinputTrusted !== true ||
      textInputEvents?.inputTrusted !== true ||
      textInputEvents?.beforeinputInputType !== "insertText" ||
      textInputEvents?.inputInputType !== "insertText" ||
      textInputEvents?.beforeinputData !== M4_PRINTABLE_KEY_DOM_KEY ||
      textInputEvents?.inputData !== M4_PRINTABLE_KEY_DOM_KEY ||
      textInputEvents?.beforeinputTargetId !== "editable-target" ||
      textInputEvents?.inputTargetId !== "editable-target" ||
      textInputEvents?.compositionstartCount !== 0 ||
      textInputEvents?.compositionupdateCount !== 0 ||
      textInputEvents?.compositionendCount !== 0 ||
      pageProbe?.activeElementId !== "editable-target" ||
      pageProbe?.value !== M4_PRINTABLE_KEY_DOM_KEY ||
      pageProbe?.selectionStart !== 1 ||
      pageProbe?.selectionEnd !== 1 ||
      pageProbe?.resultText !== "TEXT INPUT RECEIVED" ||
      !(readiness.frame?.id > lastQueuedDown.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone printable-key timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4PrintableKeyState = {
      state: "input-delivered",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboard),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      pointerActivation:
        pointer.trustedCount >= 2 &&
        pointer.queuedCount >= 2 &&
        lastQueuedPointer.trusted === true &&
        lastQueuedPointer.queued === true,
      trustedDomInput:
        keyboard.receivedCount === 2 &&
        keyboard.trustedCount === 2 &&
        keyboard.queuedCount === 2 &&
        lastQueuedDown.trusted === true &&
        lastQueuedDown.queued === true &&
        lastQueuedDown.defaultPrevented === true &&
        lastQueuedUp.trusted === true &&
        lastQueuedUp.queued === true &&
        lastQueuedUp.defaultPrevented === true,
      ozoneDelivered:
        pageProbe.activationCount === 1 &&
        pageProbe.clickTrusted === true &&
        pageProbe.focusCount >= 1 &&
        pageProbe.focusTrusted === true &&
        pageProbe.activeElementId === "editable-target" &&
        keyEvents.keydownCount === 1 &&
        keyEvents.keyupCount === 1 &&
        keyEvents.keydownTrusted === true &&
        keyEvents.keyupTrusted === true &&
        keyEvents.keydownCode === M4_PRINTABLE_KEY_DOM_CODE &&
        keyEvents.keyupCode === M4_PRINTABLE_KEY_DOM_CODE &&
        keyEvents.keydownKey === M4_PRINTABLE_KEY_DOM_KEY &&
        keyEvents.keyupKey === M4_PRINTABLE_KEY_DOM_KEY &&
        keyEvents.keydownRepeat === false &&
        keyEvents.keyupRepeat === false &&
        keyEvents.keydownComposing === false &&
        keyEvents.keyupComposing === false &&
        keyEvents.keydownDefaultPrevented === false &&
        keyEvents.keyupDefaultPrevented === false &&
        keyEvents.keydownTargetId === "editable-target" &&
        keyEvents.keyupTargetId === "editable-target" &&
        textInputEvents.beforeinputCount === 1 &&
        textInputEvents.inputCount === 1 &&
        textInputEvents.beforeinputTrusted === true &&
        textInputEvents.inputTrusted === true &&
        textInputEvents.beforeinputInputType === "insertText" &&
        textInputEvents.inputInputType === "insertText" &&
        textInputEvents.beforeinputData === M4_PRINTABLE_KEY_DOM_KEY &&
        textInputEvents.inputData === M4_PRINTABLE_KEY_DOM_KEY &&
        textInputEvents.beforeinputTargetId === "editable-target" &&
        textInputEvents.inputTargetId === "editable-target" &&
        textInputEvents.compositionstartCount === 0 &&
        textInputEvents.compositionupdateCount === 0 &&
        textInputEvents.compositionendCount === 0 &&
        pageProbe.value === M4_PRINTABLE_KEY_DOM_KEY &&
        pageProbe.selectionStart === 1 &&
        pageProbe.selectionEnd === 1 &&
        pageProbe.resultText === "TEXT INPUT RECEIVED" &&
        readiness.frame.id > lastQueuedDown.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_PRINTABLE_KEY_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_PRINTABLE_KEY_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneImeBridgeSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const imeProxy = document.querySelector("#m4-ime-proxy");
  const token = parameters.get("token") || "";
  const terminalMode = parameters.get("ime_terminal") || "commit";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_IME_BRIDGE_CASE) {
      throw new Error("M4 IME bridge case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 IME bridge result token");
    }
    if (terminalMode !== "commit" && terminalMode !== "cancel") {
      throw new Error("M4 IME bridge terminal mode is invalid");
    }
    if (!(imeProxy instanceof HTMLTextAreaElement)) {
      throw new Error("M4 IME bridge proxy textarea is unavailable");
    }
    host = new ChromiumWasmM3Host(canvas, versions, {
      fixture: M4_IME_BRIDGE_FIXTURE,
      imeProxy,
    });
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 IME bridge base readiness timeout: " +
        JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 IME bridge target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 IME bridge target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const focusListeners = host.enableM4FocusInput();
    const imeProxyListeners = host.enableM4ImeProxyInput();
    window.__chromiumWasmM4ImeBridgeState = {
      state: "awaiting-dom-ime-bridge-activation",
      targetX,
      targetY,
      pointerListeners,
      focusListeners,
      imeProxyListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted Ozone click and IME proxy preedit";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const pageProbe = readiness.pageProbe;
      const proxy = readiness.imeProxyInput;
      const ozoneFocusState = readiness.ozoneFocusState;
      const ozoneTextInputState = readiness.ozoneTextInputState;
      if (
        pointer.queuedCount >= 2 &&
        pointer.lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "editable-target" &&
        isEmptyM4ImeTextSummary(pageProbe?.value) &&
        pageProbe?.valueMatchesExpected === false &&
        pageProbe?.selectionStart === 0 &&
        pageProbe?.selectionEnd === 0 &&
        proxy?.sessionId === 1 &&
        proxy?.focused === true &&
        proxy?.focusCount >= 1 &&
        proxy?.hostWindowActive === true &&
        proxy?.activationPending === false &&
        proxy?.nativeTextInputReady === true &&
        proxy?.failure === null &&
        ozoneFocusState?.keyboardTargetPresent === true &&
        ozoneFocusState?.active === true &&
        ozoneTextInputState?.focusedClientPresent === true &&
        ozoneTextInputState?.editable === true &&
        ozoneTextInputState?.canComposeInline === true
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const pageAfterActivation = readiness?.pageProbe;
    const proxyAfterActivation = readiness?.imeProxyInput;
    const ozoneFocusAfterActivation = readiness?.ozoneFocusState;
    const ozoneTextInputAfterActivation = readiness?.ozoneTextInputState;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      pointer?.lastQueued?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "editable-target" ||
      !isEmptyM4ImeTextSummary(pageAfterActivation?.value) ||
      pageAfterActivation?.valueMatchesExpected !== false ||
      pageAfterActivation?.selectionStart !== 0 ||
      pageAfterActivation?.selectionEnd !== 0 ||
      proxyAfterActivation?.sessionId !== 1 ||
      proxyAfterActivation?.focused !== true ||
      proxyAfterActivation?.focusCount < 1 ||
      proxyAfterActivation?.hostWindowActive !== true ||
      proxyAfterActivation?.activationPending !== false ||
      proxyAfterActivation?.nativeTextInputReady !== true ||
      ozoneFocusAfterActivation?.keyboardTargetPresent !== true ||
      ozoneFocusAfterActivation?.active !== true ||
      ozoneTextInputAfterActivation?.focusedClientPresent !== true ||
      ozoneTextInputAfterActivation?.editable !== true ||
      ozoneTextInputAfterActivation?.canComposeInline !== true ||
      proxyAfterActivation?.failure !== null
    ) {
      throw new Error(
        "M4 IME bridge activation timeout: " + JSON.stringify(readiness));
    }
    window.__chromiumWasmM4ImeBridgeState = {
      state: "awaiting-dom-ime-preedit",
      targetX,
      targetY,
      pointer: clone(pointer),
      imeProxy: clone(proxyAfterActivation),
    };
    statusElement.textContent =
      "M4 ready for trusted outer IME composition preedit";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const proxy = readiness.imeProxyInput;
      const pageProbe = readiness.pageProbe;
      const transaction = proxy?.lastConfirmedTransaction;
      const proxyText = proxy?.proxyText;
      const selection = proxyText?.selection;
      if (
        proxy?.receivedCount === 4 &&
        proxy?.trustedCount === 4 &&
        proxy?.acceptedCount === 4 &&
        proxy?.compositionStartCount === 1 &&
        proxy?.compositionUpdateCount === 1 &&
        proxy?.compositionEndCount === 0 &&
        proxy?.beforeinputCount === 1 &&
        proxy?.inputCount === 1 &&
        proxy?.compositionActive === true &&
        proxy?.pendingTransaction === false &&
        proxy?.failure === null &&
        proxy?.focused === true &&
        proxy?.activationPending === false &&
        proxy?.nativeTextInputReady === true &&
        proxy?.nativeQueuedCount === 1 &&
        proxy?.nativeSetDeliveryCount === 1 &&
        proxy?.nativeConfirmDeliveryCount === 0 &&
        proxy?.nativeClearDeliveryCount === 0 &&
        proxy?.nativePendingDelivery === false &&
        proxy?.nativeCompositionActive === true &&
        proxy?.nativeTerminalAction === null &&
        transaction?.sessionId === 1 &&
        transaction?.opcode === "set-composition" &&
        transaction?.rangeStart === 0 &&
        transaction?.rangeEnd === 2 &&
        transaction?.selection?.start === 2 &&
        transaction?.selection?.end === 2 &&
        isM4ImeSmokeTextSummary(transaction?.text) &&
        isM4ImeSmokeTextSummary(proxyText) &&
        selection?.start === 2 &&
        selection?.end === 2 &&
        pageProbe?.activeElementId === "editable-target" &&
        isM4ImeSmokeTextSummary(pageProbe?.value) &&
        pageProbe?.valueMatchesExpected === true &&
        pageProbe?.selectionStart === 2 &&
        pageProbe?.selectionEnd === 2 &&
        pageProbe?.textInputEvents?.beforeinputCount >= 1 &&
        pageProbe?.textInputEvents?.inputCount >= 1 &&
        pageProbe?.textInputEvents?.compositionstartCount === 1 &&
        pageProbe?.textInputEvents?.compositionupdateCount >= 1 &&
        pageProbe?.textInputEvents?.compositionendCount === 0 &&
        pageProbe?.textInputTrace?.[0]?.type === "compositionstart" &&
        pageProbe?.resultText === "INNER EDITOR COMPOSING"
      ) {
        break;
      }
      await delay(50);
    }
    const imeProxyInput = readiness?.imeProxyInput;
    const pageProbe = readiness?.pageProbe;
    const transaction = imeProxyInput?.lastConfirmedTransaction;
    const proxyText = imeProxyInput?.proxyText;
    if (
      !readiness ||
      imeProxyInput?.receivedCount !== 4 ||
      imeProxyInput?.trustedCount !== 4 ||
      imeProxyInput?.acceptedCount !== 4 ||
      imeProxyInput?.compositionStartCount !== 1 ||
      imeProxyInput?.compositionUpdateCount !== 1 ||
      imeProxyInput?.compositionEndCount !== 0 ||
      imeProxyInput?.beforeinputCount !== 1 ||
      imeProxyInput?.inputCount !== 1 ||
      imeProxyInput?.compositionActive !== true ||
      imeProxyInput?.pendingTransaction !== false ||
      imeProxyInput?.failure !== null ||
      imeProxyInput?.focused !== true ||
      imeProxyInput?.activationPending !== false ||
      imeProxyInput?.nativeTextInputReady !== true ||
      imeProxyInput?.nativeQueuedCount !== 1 ||
      imeProxyInput?.nativeSetDeliveryCount !== 1 ||
      imeProxyInput?.nativeConfirmDeliveryCount !== 0 ||
      imeProxyInput?.nativeClearDeliveryCount !== 0 ||
      imeProxyInput?.nativePendingDelivery !== false ||
      imeProxyInput?.nativeCompositionActive !== true ||
      imeProxyInput?.nativeTerminalAction !== null ||
      transaction?.sessionId !== 1 ||
      transaction?.opcode !== "set-composition" ||
      transaction?.rangeStart !== 0 ||
      transaction?.rangeEnd !== 2 ||
      transaction?.selection?.start !== 2 ||
      transaction?.selection?.end !== 2 ||
      !isM4ImeSmokeTextSummary(transaction?.text) ||
      !isM4ImeSmokeTextSummary(proxyText) ||
      proxyText?.selection?.start !== 2 ||
      proxyText?.selection?.end !== 2 ||
      pageProbe?.activeElementId !== "editable-target" ||
      !isM4ImeSmokeTextSummary(pageProbe?.value) ||
      pageProbe?.valueMatchesExpected !== true ||
      pageProbe?.selectionStart !== 2 ||
      pageProbe?.selectionEnd !== 2 ||
      pageProbe?.textInputEvents?.beforeinputCount < 1 ||
      pageProbe?.textInputEvents?.inputCount < 1 ||
      pageProbe?.textInputEvents?.compositionstartCount !== 1 ||
      pageProbe?.textInputEvents?.compositionupdateCount < 1 ||
      pageProbe?.textInputEvents?.compositionendCount !== 0 ||
      pageProbe?.textInputTrace?.[0]?.type !== "compositionstart" ||
      pageProbe?.resultText !== "INNER EDITOR COMPOSING"
    ) {
      throw new Error(
        "M4 IME bridge preedit timeout: " + JSON.stringify(readiness));
    }
    const isCancellation = terminalMode === "cancel";
    const terminalActionName = isCancellation
      ? "clear-composition"
      : "confirm-composition";
    const terminalResultText = isCancellation
      ? "INNER EDITOR COMPOSITION ENDED"
      : "INNER EDITOR COMMITTED";
    const terminalSelection = isCancellation ? 0 : 2;
    const terminalTextMatches = isCancellation
      ? isEmptyM4ImeTextSummary
      : isM4ImeSmokeTextSummary;
    // Both terminal modes produce a second update/beforeinput/input group in
    // the inner editor. For cancellation, Blink reports the final |input|
    // event's data as null rather than the empty string; the trace check below
    // binds that browser behavior before accepting the clear result.
    const terminalEventCount = 2;
    const terminalDerivedCount = isCancellation ? 0 : 1;
    const terminalObservedClearCount = isCancellation ? 1 : 0;
    const terminalAcceptedCount = isCancellation ? 7 : 8;
    const terminalNativeQueuedCount = isCancellation ? 2 : 3;
    const terminalSetDeliveryCount = isCancellation ? 1 : 2;
    const terminalConfirmDeliveryCount = isCancellation ? 0 : 1;
    const terminalClearDeliveryCount = isCancellation ? 1 : 0;
    const terminalNativeSequence = isCancellation ? 7 : 8;
    const terminalValueMatchesExpected = !isCancellation;
    const matchesConfirmedTransaction = (proxy) => {
      const candidate = proxy?.lastConfirmedTransaction;
      return candidate?.sessionId === 1 &&
          candidate?.opcode === "set-composition" &&
          candidate?.rangeStart === 0 && candidate?.rangeEnd === 2 &&
          candidate?.selection?.start === 2 && candidate?.selection?.end === 2 &&
          isM4ImeSmokeTextSummary(candidate?.text);
    };
    const matchesTerminalProxy = (proxy) => {
      const proxyCandidate = proxy?.proxyText;
      return proxy?.receivedCount === 8 && proxy?.trustedCount === 7 &&
          proxy?.acceptedCount === terminalAcceptedCount &&
          proxy?.derivedTerminalCount === terminalDerivedCount &&
          proxy?.observedClearTerminalCount === terminalObservedClearCount &&
          proxy?.compositionStartCount === 1 &&
          proxy?.compositionUpdateCount === 2 &&
          proxy?.compositionEndCount === 1 && proxy?.beforeinputCount === 2 &&
          proxy?.inputCount === 2 && proxy?.compositionActive === false &&
          proxy?.terminalCancellationPending === false &&
          proxy?.pendingTransaction === false && proxy?.failure === null &&
          proxy?.focused === true && proxy?.activationPending === false &&
          proxy?.nativeTextInputReady === true &&
          terminalTextMatches(proxyCandidate) &&
          proxyCandidate?.selection?.start === terminalSelection &&
          proxyCandidate?.selection?.end === terminalSelection &&
          matchesConfirmedTransaction(proxy);
    };
    const matchesTerminalDelivery = (proxy) =>
      proxy?.nativeQueuedCount === terminalNativeQueuedCount &&
      proxy?.nativeSetDeliveryCount === terminalSetDeliveryCount &&
      proxy?.nativeConfirmDeliveryCount === terminalConfirmDeliveryCount &&
      proxy?.nativeClearDeliveryCount === terminalClearDeliveryCount &&
      proxy?.nativePendingDelivery === false &&
      proxy?.nativeCompositionActive === false &&
      proxy?.nativeTerminalAction === null &&
      proxy?.lastNativeDelivery?.actionName === terminalActionName &&
      proxy?.lastNativeDelivery?.sequence === terminalNativeSequence &&
      proxy?.lastNativeDelivery?.deliveryAccepted === true;
    const matchesTerminalBlinkTrace = (page) => {
      const trace = page?.textInputTrace;
      const expectedTypes = [
        "compositionstart", "compositionupdate", "beforeinput", "input",
        "compositionupdate", "beforeinput", "input", "compositionend",
      ];
      if (!Array.isArray(trace) || trace.length !== expectedTypes.length ||
          !trace.every((record, index) =>
            record?.type === expectedTypes[index])) {
        return false;
      }
      // Chromium's direct composition-end dispatch deliberately preserves the
      // scoped queue's untrusted terminal. Every source event that carries
      // composition state must still be a native trusted Blink event.
      if (!trace.slice(0, -1).every((record) => record?.trusted === true) ||
          trace.at(-1)?.trusted !== false) {
        return false;
      }
      const start = trace[0];
      const candidateUpdate = trace[1];
      const candidateBeforeInput = trace[2];
      const candidateInput = trace[3];
      if (!isEmptyM4ImeTextSummary(start?.data) ||
          start?.dataMatchesExpected !== false ||
          !isM4ImeSmokeTextSummary(candidateUpdate?.data) ||
          candidateUpdate?.dataMatchesExpected !== true ||
          !isM4ImeSmokeTextSummary(candidateBeforeInput?.data) ||
          candidateBeforeInput?.inputType !== "insertCompositionText" ||
          candidateBeforeInput?.isComposing !== true ||
          candidateBeforeInput?.dataMatchesExpected !== true ||
          !isM4ImeSmokeTextSummary(candidateInput?.data) ||
          candidateInput?.inputType !== "insertCompositionText" ||
          candidateInput?.isComposing !== true ||
          candidateInput?.dataMatchesExpected !== true) {
        return false;
      }
      const terminalUpdate = trace[4];
      const terminalBeforeInput = trace[5];
      const terminalInput = trace[6];
      const terminalEnd = trace[7];
      if (!isCancellation) {
        return [terminalUpdate, terminalBeforeInput, terminalInput, terminalEnd]
            .every((record) => isM4ImeSmokeTextSummary(record?.data) &&
              record?.dataMatchesExpected === true) &&
            terminalBeforeInput?.inputType === "insertCompositionText" &&
            terminalBeforeInput?.isComposing === true &&
            terminalInput?.inputType === "insertCompositionText" &&
            terminalInput?.isComposing === true;
      }
      return isEmptyM4ImeTextSummary(terminalUpdate?.data) &&
          terminalUpdate?.dataMatchesExpected === false &&
          isEmptyM4ImeTextSummary(terminalBeforeInput?.data) &&
          terminalBeforeInput?.inputType === "insertCompositionText" &&
          terminalBeforeInput?.isComposing === true &&
          terminalBeforeInput?.dataMatchesExpected === false &&
          terminalInput?.data === null &&
          terminalInput?.inputType === "insertCompositionText" &&
          terminalInput?.isComposing === true &&
          terminalInput?.dataMatchesExpected === false &&
          isEmptyM4ImeTextSummary(terminalEnd?.data) &&
          terminalEnd?.dataMatchesExpected === false;
    };
    const matchesTerminalBlink = (page) =>
      page?.activeElementId === "editable-target" &&
      terminalTextMatches(page?.value) &&
      page?.valueMatchesExpected === terminalValueMatchesExpected &&
      page?.selectionStart === terminalSelection &&
      page?.selectionEnd === terminalSelection &&
      page?.textInputEvents?.beforeinputCount === terminalEventCount &&
      page?.textInputEvents?.inputCount === terminalEventCount &&
      page?.textInputEvents?.compositionstartCount === 1 &&
      page?.textInputEvents?.compositionupdateCount === terminalEventCount &&
      page?.textInputEvents?.compositionendCount === 1 &&
      matchesTerminalBlinkTrace(page) &&
      page?.resultText === terminalResultText;
    window.__chromiumWasmM4ImeBridgeState = {
      state: "awaiting-dom-ime-terminal",
      terminalMode,
      targetX,
      targetY,
      pointer: clone(pointer),
      imeProxy: clone(imeProxyInput),
    };
    statusElement.textContent =
      "M4 preedit reached Blink; ready for outer IME " + terminalMode;

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        matchesTerminalProxy(readiness.imeProxyInput) &&
        matchesTerminalDelivery(readiness.imeProxyInput) &&
        matchesTerminalBlink(readiness.pageProbe)
      ) {
        break;
      }
      await delay(50);
    }
    const terminalReadiness = readiness;
    const terminalImeProxyInput = terminalReadiness?.imeProxyInput;
    const terminalPageProbe = terminalReadiness?.pageProbe;
    if (
      !terminalReadiness || !matchesTerminalProxy(terminalImeProxyInput) ||
      !matchesTerminalDelivery(terminalImeProxyInput) ||
      !matchesTerminalBlink(terminalPageProbe)
    ) {
      throw new Error(
        "M4 IME bridge " + terminalMode + " timeout: " +
        JSON.stringify(terminalReadiness));
    }
    const focusSnapshot = {
      canvasFocused: document.activeElement === canvas,
      proxyFocused: document.activeElement === imeProxy,
    };
    window.__chromiumWasmM4ImeBridgeState = {
      state: isCancellation
        ? "native-composition-cancelled"
        : "native-composition-committed",
      terminalMode,
      targetX,
      targetY,
      pointer: clone(pointer),
      imeProxy: clone(terminalImeProxyInput),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      baseReady: terminalReadiness.baseReady === true,
      proxyFocus:
        focusSnapshot.canvasFocused === false &&
        focusSnapshot.proxyFocused === true &&
        terminalImeProxyInput.focused === true &&
        terminalImeProxyInput.hostWindowActive === true &&
        terminalImeProxyInput.activationPending === false &&
        terminalImeProxyInput.nativeTextInputReady === true &&
        ozoneFocusAfterActivation.keyboardTargetPresent === true &&
        ozoneFocusAfterActivation.active === true &&
        ozoneTextInputAfterActivation.focusedClientPresent === true &&
        ozoneTextInputAfterActivation.editable === true &&
        ozoneTextInputAfterActivation.canComposeInline === true,
      proxyComposition: matchesTerminalProxy(terminalImeProxyInput),
      nativeDelivery: matchesTerminalDelivery(terminalImeProxyInput),
      innerBlinkComposition: matchesTerminalBlink(terminalPageProbe),
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_IME_BRIDGE_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: focusSnapshot.canvasFocused,
      proxyFocused: focusSnapshot.proxyFocused,
      terminalMode,
      versions,
      readiness: terminalReadiness,
      pointerInput: pointer,
      focusInput: terminalReadiness.focusInput,
      imeProxyInput: terminalImeProxyInput,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_IME_BRIDGE_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      proxyFocused: document.activeElement === imeProxy,
      versions,
      readiness: null,
      pointerInput: null,
      focusInput: null,
      imeProxyInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.focusInput = result.readiness.focusInput;
        result.imeProxyInput = result.readiness.imeProxyInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneFocusSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const focusSink = document.querySelector("#m4-focus-sink");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;
  let focusSinkClick = null;
  let focusSinkListener = null;

  try {
    if (parameters.get("case") !== M4_FOCUS_CASE) {
      throw new Error("M4 focus case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 focus result token");
    }
    if (!(focusSink instanceof HTMLButtonElement)) {
      throw new Error("M4 focus host sink is missing");
    }
    focusSink.hidden = false;
    focusSinkListener = (event) => {
      focusSinkClick = {
        trusted: event.isTrusted === true,
        defaultPrevented: event.defaultPrevented === true,
      };
    };
    focusSink.addEventListener("click", focusSinkListener);
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_FOCUS_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 focus base readiness timeout: " + JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 focus target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 focus target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4FocusState = {
      state: "awaiting-dom-focus-activation",
      targetX,
      targetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click before host focus loss";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "focus-target" &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueuedPointer = pointer?.lastQueued;
    const pageAfterActivation = readiness?.pageProbe;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueuedPointer?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "focus-target" ||
      !(readiness.frame?.id > lastQueuedPointer.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone focus activation timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4FocusState = {
      state: "awaiting-dom-focus-key-down",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(readiness.keyboardInput),
      focus: clone(readiness.focusInput),
    };
    statusElement.textContent =
      "M4 ready for a trusted raw ArrowDown keydown";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const keyDown = keyboard.lastQueuedDown;
      const pageProbe = readiness.pageProbe;
      const keyEvents = pageProbe?.keyEvents;
      if (
        keyboard.queuedCount >= 1 &&
        keyboard.pressedCodes?.length === 1 &&
        keyboard.pressedCodes[0] === M4_KEYBOARD_DOM_CODE &&
        keyDown?.type === "down" &&
        keyDown?.trusted === true &&
        keyDown?.queued === true &&
        keyDown?.defaultPrevented === true &&
        keyEvents?.keydownCount === 1 &&
        keyEvents?.keydownTrusted === true &&
        keyEvents?.keydownCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keydownKey === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keydownTargetId === "focus-target"
      ) {
        break;
      }
      await delay(50);
    }
    const keyboardBeforeFocusLoss = readiness?.keyboardInput;
    const keyDown = keyboardBeforeFocusLoss?.lastQueuedDown;
    const pageBeforeFocusLoss = readiness?.pageProbe;
    const keyEventsBeforeFocusLoss = pageBeforeFocusLoss?.keyEvents;
    if (
      !readiness ||
      keyboardBeforeFocusLoss?.queuedCount < 1 ||
      keyboardBeforeFocusLoss?.pressedCodes?.length !== 1 ||
      keyboardBeforeFocusLoss.pressedCodes[0] !== M4_KEYBOARD_DOM_CODE ||
      keyDown?.type !== "down" ||
      keyDown?.trusted !== true ||
      keyDown?.queued !== true ||
      keyDown?.defaultPrevented !== true ||
      keyEventsBeforeFocusLoss?.keydownCount !== 1 ||
      keyEventsBeforeFocusLoss?.keydownTrusted !== true ||
      keyEventsBeforeFocusLoss?.keydownCode !== M4_KEYBOARD_DOM_CODE ||
      keyEventsBeforeFocusLoss?.keydownKey !== M4_KEYBOARD_DOM_CODE ||
      keyEventsBeforeFocusLoss?.keydownTargetId !== "focus-target"
    ) {
      throw new Error(
        "M4 trusted Ozone focus keydown timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4FocusState = {
      state: "awaiting-dom-focus-loss",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboardBeforeFocusLoss),
      focus: clone(readiness.focusInput),
    };
    statusElement.textContent =
      "M4 ready for trusted host focus loss with a held ArrowDown key";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const focus = readiness.focusInput;
      const focusLoss = focus.lastQueuedFocusLoss;
      const ozoneFocusState = readiness.ozoneFocusState;
      const keyUp = keyboard.lastQueuedUp;
      const pageProbe = readiness.pageProbe;
      const keyEvents = pageProbe?.keyEvents;
      if (
        focus.hostWindowActive === false &&
        focusLoss?.type === "canvas-blur" &&
        focusLoss?.trusted === true &&
        focusLoss?.queued === true &&
        focusLoss?.canvasFocused === false &&
        focusLoss?.relatedTargetId === "m4-focus-sink" &&
        ozoneFocusState?.sequence >
          focusLoss?.ozoneFocusReportSequenceBefore &&
        ozoneFocusState?.keyboardTargetPresent === false &&
        ozoneFocusState?.active === false &&
        focusSinkClick?.trusted === true &&
        focusSinkClick?.defaultPrevented === false &&
        document.activeElement === focusSink &&
        keyboard.activated === false &&
        keyboard.pressedCodes?.length === 0 &&
        keyUp?.type === "up" &&
        keyUp?.generated === true &&
        keyUp?.trigger === "canvas-blur" &&
        keyUp?.triggerTrusted === true &&
        keyUp?.queued === true &&
        keyUp?.code === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keyupCount === 1 &&
        keyEvents?.keyupTrusted === true &&
        keyEvents?.keyupCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keyupKey === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keyupTargetId === "focus-target" &&
        pageProbe?.windowBlurCount >= 1 &&
        pageProbe?.windowBlurTrusted === true &&
        pageProbe?.documentHasFocus === false &&
        pageProbe?.activeElementId === "focus-target" &&
        pageProbe?.resultText === "WINDOW BLURRED" &&
        readiness.frame?.id > focusLoss.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboard = readiness?.keyboardInput;
    const focus = readiness?.focusInput;
    const focusLoss = focus?.lastQueuedFocusLoss;
    const ozoneFocusState = readiness?.ozoneFocusState;
    const keyUp = keyboard?.lastQueuedUp;
    const pageProbe = readiness?.pageProbe;
    const keyEvents = pageProbe?.keyEvents;
    if (
      !readiness ||
      focus?.hostWindowActive !== false ||
      focusLoss?.type !== "canvas-blur" ||
      focusLoss?.trusted !== true ||
      focusLoss?.queued !== true ||
      focusLoss?.canvasFocused !== false ||
      focusLoss?.relatedTargetId !== "m4-focus-sink" ||
      !(ozoneFocusState?.sequence >
        focusLoss?.ozoneFocusReportSequenceBefore) ||
      ozoneFocusState?.keyboardTargetPresent !== false ||
      ozoneFocusState?.active !== false ||
      focusSinkClick?.trusted !== true ||
      focusSinkClick?.defaultPrevented !== false ||
      document.activeElement !== focusSink ||
      keyboard?.activated !== false ||
      keyboard?.pressedCodes?.length !== 0 ||
      keyUp?.type !== "up" ||
      keyUp?.generated !== true ||
      keyUp?.trigger !== "canvas-blur" ||
      keyUp?.triggerTrusted !== true ||
      keyUp?.queued !== true ||
      keyUp?.code !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keyupCount !== 1 ||
      keyEvents?.keyupTrusted !== true ||
      keyEvents?.keyupCode !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keyupKey !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keyupTargetId !== "focus-target" ||
      pageProbe?.windowBlurCount < 1 ||
      pageProbe?.windowBlurTrusted !== true ||
      pageProbe?.documentHasFocus !== false ||
      pageProbe?.activeElementId !== "focus-target" ||
      pageProbe?.resultText !== "WINDOW BLURRED" ||
      !(readiness.frame?.id > focusLoss.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone focus loss timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4FocusState = {
      state: "focus-loss-delivered",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboard),
      focus: clone(focus),
      ozoneFocusState: clone(ozoneFocusState),
      focusSinkClick: clone(focusSinkClick),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasUnfocused: document.activeElement === focusSink,
      baseReady: readiness.baseReady === true,
      pointerActivation:
        pointer.trustedCount >= 2 &&
        pointer.queuedCount >= 2 &&
        lastQueuedPointer.trusted === true &&
        lastQueuedPointer.queued === true,
      heldKeyDelivered:
        keyDown.trusted === true &&
        keyDown.queued === true &&
        keyEvents.keydownCount === 1 &&
        keyEvents.keydownTrusted === true,
      trustedHostFocusLoss:
        focusLoss.trusted === true &&
        focusLoss.queued === true &&
        focusLoss.relatedTargetId === "m4-focus-sink" &&
        focusSinkClick.trusted === true &&
        focusSinkClick.defaultPrevented === false,
      ozoneKeyboardTargetCleared:
        ozoneFocusState.sequence > focusLoss.ozoneFocusReportSequenceBefore &&
        ozoneFocusState.keyboardTargetPresent === false &&
        ozoneFocusState.active === false,
      auraAndBlinkDeactivated:
        keyboard.activated === false &&
        keyboard.pressedCodes.length === 0 &&
        keyUp.generated === true &&
        keyUp.queued === true &&
        keyEvents.keyupCount === 1 &&
        keyEvents.keyupTrusted === true &&
        pageProbe.windowBlurCount >= 1 &&
        pageProbe.windowBlurTrusted === true &&
        pageProbe.documentHasFocus === false &&
        pageProbe.activeElementId === "focus-target" &&
        pageProbe.resultText === "WINDOW BLURRED" &&
        readiness.frame.id > focusLoss.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_FOCUS_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      focusInput: focus,
      ozoneFocusState,
      focusSinkClick,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_FOCUS_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      focusInput: null,
      ozoneFocusState: null,
      focusSinkClick,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
        result.focusInput = result.readiness.focusInput;
        result.ozoneFocusState = result.readiness.ozoneFocusState;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  if (focusSink instanceof HTMLButtonElement && focusSinkListener) {
    focusSink.removeEventListener("click", focusSinkListener);
  }
  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

export async function runContentShellSmokeFromQuery() {
  const selectedCase = new URLSearchParams(location.search).get("case");
  if (selectedCase === M3_CASE) {
    return runM3SmokeFromQuery();
  }
  if (selectedCase === M4_CASE) {
    return runM4OzonePointerSmokeFromQuery();
  }
  if (selectedCase === M4_WHEEL_CASE) {
    return runM4OzoneWheelSmokeFromQuery();
  }
  if (selectedCase === M4_KEYBOARD_CASE) {
    return runM4OzoneKeyboardSmokeFromQuery();
  }
  if (selectedCase === M4_PRINTABLE_KEY_CASE) {
    return runM4OzonePrintableKeySmokeFromQuery();
  }
  if (selectedCase === M4_IME_BRIDGE_CASE) {
    return runM4OzoneImeBridgeSmokeFromQuery();
  }
  if (selectedCase === M4_FOCUS_CASE) {
    return runM4OzoneFocusSmokeFromQuery();
  }
  throw new Error("unknown Content Shell Wasm smoke case");
}

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";

// This host configures only the local WISP carrier before the Emscripten
// factory starts. The canonical browser URL reaches Chrome only through the
// trusted DOM -> Ozone Ctrl+L, text, and Enter path driven by the outer test
// browser's physical-input DevTools domain. There is no page navigation or
// script-command bridge to the inner Chrome tab.
const HOST_PROTOCOL = 1;
const CASE = "browser_m9_wisp_carrier_close_recovery";
const SCOPE = "same-instance-chrome-ozone-wisp-carrier-close-recovery";
const SWITCH = "--wasm-browser-m9-wisp-recovery-smoke";
const URL_SWITCH = "--wasm-browser-m9-wisp-recovery-url";
const FIXTURE_HOSTNAME = "a.test";
const FIXTURE_PATH = "/m5/m9-wisp-recovery";
const FIXTURE_URL = "https://a.test/m5/m9-wisp-recovery";
const ADDRESS_TEXT = FIXTURE_URL;
const READY_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:READY";
const NAVIGATED_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:NAVIGATED";
const NATIVE_DISCONNECT_MARKER =
    "CHROMIUM_WASM_M9_WISP_RECOVERY:NATIVE_ERR_INTERNET_DISCONNECTED";
const H2_RECOVERED_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:H2_RECOVERED";
const SAME_INSTANCE_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:SAME_INSTANCE";
const PASS_MARKER = "CHROMIUM_WASM_M9_WISP_RECOVERY:PASS";
const CDP_SIGNAL_PREFIX = "CHROMIUM_WASM_M9_WISP_RECOVERY_HOST";
const CDP_CTRL_L_READY = `${CDP_SIGNAL_PREFIX}:CTRL_L_READY`;
const CDP_INSERT_TEXT_READY = `${CDP_SIGNAL_PREFIX}:INSERT_TEXT_READY`;
const CDP_ENTER_READY = `${CDP_SIGNAL_PREFIX}:ENTER_READY`;
const WISP_CONFIGURATION_VERSION = 1;
const WISP_SUBPROTOCOL = "wisp";
const MAX_TIMEOUT_MS = 180000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_REPORT_HISTORY = 128;
const MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024;
const MAX_SCREENSHOT_BASE64_LENGTH =
    Math.ceil(MAX_SCREENSHOT_BYTES / 3) * 4;
const PNG_DATA_URL_PREFIX = "data:image/png;base64,";
const BASE64_PATTERN = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function appendBounded(records, value) {
  records.push(value);
  if (records.length > MAX_REPORT_HISTORY) {
    records.shift();
  }
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(description + " must be a nonempty string");
  }
  return value;
}

function asReport(value, description) {
  let report = value;
  if (typeof report === "string") {
    try {
      report = JSON.parse(report);
    } catch (error) {
      throw new Error(description + " is not valid JSON: " + String(error));
    }
  }
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    throw new Error(description + " must be an object");
  }
  return report;
}

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(asNonemptyString(value, "M9 versions"));
  } catch (error) {
    throw new Error("invalid M9 versions: " + String(error));
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], "version " + field);
  }
  return Object.freeze(versions);
}

function isLoopbackHostname(hostname) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (normalized === "localhost" || normalized === "::1") {
    return true;
  }
  const octets = normalized.split(".");
  return octets.length === 4 && octets.every((octet) =>
    /^\d{1,3}$/.test(octet) && Number(octet) <= 255) &&
      Number(octets[0]) === 127;
}

function parseWispConfiguration(value) {
  let endpoint;
  try {
    endpoint = new URL(asNonemptyString(value, "M9 WISP endpoint"));
  } catch (_) {
    throw new Error("M9 WISP endpoint is invalid");
  }
  const port = Number(endpoint.port);
  if ((endpoint.protocol !== "ws:" && endpoint.protocol !== "wss:") ||
      !isLoopbackHostname(endpoint.hostname) || endpoint.username ||
      endpoint.password || endpoint.search || endpoint.hash ||
      endpoint.pathname !== "/wisp/" || endpoint.port === "" ||
      !Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("M9 WISP endpoint violates the local transport policy");
  }
  return Object.freeze({
    version: WISP_CONFIGURATION_VERSION,
    endpoint: endpoint.href,
    subprotocol: WISP_SUBPROTOCOL,
  });
}

function parseFixtureUrl(value) {
  let url;
  try {
    url = new URL(asNonemptyString(value, "M9 fixture URL"));
  } catch (_) {
    throw new Error("M9 fixture URL is invalid");
  }
  if (url.protocol !== "https:" || url.hostname !== FIXTURE_HOSTNAME ||
      url.pathname !== FIXTURE_PATH || url.port !== "" || url.username ||
      url.password || url.search || url.hash || url.href !== FIXTURE_URL) {
    throw new Error("M9 fixture URL violates the canonical gateway policy");
  }
  return url;
}

function isFrameReport(report) {
  return report && typeof report === "object" &&
      Number.isSafeInteger(report.id) && report.id >= 1 &&
      Number.isSafeInteger(report.width) && report.width >= 1 &&
      report.width <= MAX_FRAME_DIMENSION &&
      Number.isSafeInteger(report.height) && report.height >= 1 &&
      report.height <= MAX_FRAME_DIMENSION &&
      Number.isFinite(report.timestampMs) && report.timestampMs >= 0;
}

function isReadinessReport(report) {
  return report && typeof report === "object" &&
      typeof report.shellReady === "boolean" &&
      typeof report.surfaceReady === "boolean" &&
      typeof report.firstVisuallyNonEmptyPaint === "boolean";
}

function decodePngDataUrl(dataUrl) {
  if (typeof dataUrl !== "string" || !dataUrl.startsWith(PNG_DATA_URL_PREFIX)) {
    throw new Error("canvas did not produce a PNG data URL");
  }
  const base64 = dataUrl.slice(PNG_DATA_URL_PREFIX.length);
  if (!base64 || base64.length > MAX_SCREENSHOT_BASE64_LENGTH ||
      !BASE64_PATTERN.test(base64)) {
    throw new Error("canvas PNG is outside the bounded base64 policy");
  }
  const bytes = atob(base64);
  if (bytes.length < 8 || bytes.length > MAX_SCREENSHOT_BYTES ||
      bytes.charCodeAt(0) !== 0x89 || bytes.charCodeAt(1) !== 0x50 ||
      bytes.charCodeAt(2) !== 0x4e || bytes.charCodeAt(3) !== 0x47 ||
      bytes.charCodeAt(4) !== 0x0d || bytes.charCodeAt(5) !== 0x0a ||
      bytes.charCodeAt(6) !== 0x1a || bytes.charCodeAt(7) !== 0x0a) {
    throw new Error("canvas PNG is invalid");
  }
  return base64;
}

class ChromiumWasmBrowserM9WispRecoverySmokeHost {
  #canvas;
  #proxy;
  #versions;
  #module = null;
  #textInput = null;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #runtimeExitCode = null;
  #processExitCode = null;
  #runtimeInitialized = false;
  #factorySettled = false;
  #wispConfigured = false;
  #runtimeArgumentsConfigured = false;
  #configurationPrecededFactory = false;
  #abort = null;
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #frameReports = [];
  #readinessReports = [];
  #readiness = null;
  #focusReports = [];
  #textInputStates = [];
  #textInputDeliveries = [];
  #observationSequence = 0;
  #readyMarkerObserved = false;
  #navigatedMarkerObserved = false;
  #nativeDisconnectMarkerObserved = false;
  #h2RecoveredMarkerObserved = false;
  #sameInstanceMarkerObserved = false;
  #passMarkerObserved = false;
  #frameIdAtH2Recovered = 0;
  #h2RecoveredObservationSequence = 0;
  #sameInstanceObservationSequence = 0;
  #recoveryFrame = null;
  #signal = null;
  #signalTimer = null;
  #errorHandler;
  #rejectionHandler;
  #input = {
    readyObserved: false,
    ctrlLComplete: false,
    proxyFocusedAfterCtrlL: false,
    nativeTextAdmissionCount: 0,
    nativeTextDeliveryCount: 0,
    nativeTextDeliverySequences: [],
    textDeliveryAccepted: false,
    enterComplete: false,
  };

  constructor(canvas, proxy, versions) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(proxy instanceof HTMLTextAreaElement)) {
      throw new Error("M9 host requires a canvas and textarea proxy");
    }
    this.#canvas = canvas;
    this.#proxy = proxy;
    this.#versions = versions;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
  }

  #setSignal(signal) {
    if (this.#signal === signal) {
      return;
    }
    if (this.#signalTimer !== null) {
      clearInterval(this.#signalTimer);
      this.#signalTimer = null;
    }
    this.#signal = signal;
    if (signal === null) {
      return;
    }
    const emit = () => console.log(signal);
    emit();
    // CDP Runtime.enable cannot replay a message emitted before the runner
    // attaches, so repeat just this bounded host-control witness. The runner
    // only consumes it to dispatch the next physical input record.
    this.#signalTimer = setInterval(emit, 500);
  }

  #recordOutput(value) {
    const text = String(value);
    if (text.includes(READY_MARKER)) {
      if (this.#readyMarkerObserved || this.#navigatedMarkerObserved ||
          this.#passMarkerObserved) {
        this.#recordFatal("M9 READY marker is out of order");
      } else {
        this.#readyMarkerObserved = true;
        this.#input.readyObserved = true;
        this.#advanceTrustedInputSignal();
      }
    }
    if (text.includes(NAVIGATED_MARKER)) {
      if (!this.#readyMarkerObserved || !this.#input.enterComplete ||
          this.#navigatedMarkerObserved || this.#nativeDisconnectMarkerObserved ||
          this.#passMarkerObserved) {
        this.#recordFatal("M9 NAVIGATED marker is out of order");
      } else {
        this.#navigatedMarkerObserved = true;
        this.#setSignal(null);
      }
    }
    if (text.includes(NATIVE_DISCONNECT_MARKER)) {
      if (!this.#navigatedMarkerObserved || this.#nativeDisconnectMarkerObserved ||
          this.#h2RecoveredMarkerObserved || this.#passMarkerObserved) {
        this.#recordFatal("M9 native-disconnect marker is out of order");
      } else {
        this.#nativeDisconnectMarkerObserved = true;
      }
    }
    if (text.includes(H2_RECOVERED_MARKER)) {
      if (!this.#nativeDisconnectMarkerObserved || this.#h2RecoveredMarkerObserved ||
          this.#sameInstanceMarkerObserved || this.#passMarkerObserved) {
        this.#recordFatal("M9 H2-recovered marker is out of order");
      } else {
        this.#h2RecoveredMarkerObserved = true;
        this.#frameIdAtH2Recovered = this.#frameReports.at(-1)?.id || 0;
        this.#h2RecoveredObservationSequence = ++this.#observationSequence;
      }
    }
    if (text.includes(SAME_INSTANCE_MARKER)) {
      if (!this.#h2RecoveredMarkerObserved || !this.#recoveryFrame ||
          this.#sameInstanceMarkerObserved || this.#passMarkerObserved) {
        this.#recordFatal("M9 same-instance marker is out of order");
      } else {
        this.#sameInstanceMarkerObserved = true;
        this.#sameInstanceObservationSequence = ++this.#observationSequence;
      }
    }
    if (text.includes(PASS_MARKER)) {
      if (!this.#sameInstanceMarkerObserved || !this.#recoveryFrame ||
          this.#passMarkerObserved) {
        this.#recordFatal("M9 PASS marker is out of order");
      } else {
        this.#passMarkerObserved = true;
      }
    }
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      appendBounded(this.#windowErrors, message);
      this.#recordFatal("window error: " + message);
    };
    this.#rejectionHandler = (event) => {
      appendBounded(this.#unhandledRejections, String(event.reason));
      this.#recordFatal("unhandled rejection: " + String(event.reason));
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
      this.#recordFatal("M9 runtime exit report is invalid");
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "M9 process-exit report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.exitCode) ||
          this.#processExitCode !== null) {
        throw new Error("process exit shape is invalid");
      }
      this.#processExitCode = report.exitCode;
    } catch (error) {
      this.#recordFatal("invalid M9 process-exit report: " + String(error));
    }
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "M9 frame report");
      if (report.protocol !== HOST_PROTOCOL || !isFrameReport(report)) {
        throw new Error("frame metadata is invalid");
      }
      const previous = this.#frameReports.at(-1);
      if (previous && report.id <= previous.id) {
        throw new Error("frame IDs must increase");
      }
      if (this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
        throw new Error("canvas backing store differs from frame report");
      }
      const observationSequence = ++this.#observationSequence;
      const compact = {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      };
      appendBounded(this.#frameReports, compact);
      if (this.#h2RecoveredMarkerObserved && !this.#recoveryFrame &&
          report.id > this.#frameIdAtH2Recovered &&
          observationSequence > this.#h2RecoveredObservationSequence) {
        this.#recoveryFrame = {
          ...compact,
          observationSequence,
          mimeType: "image/png",
          dataBase64: decodePngDataUrl(this.#canvas.toDataURL("image/png")),
        };
      }
    } catch (error) {
      this.#recordFatal("invalid M9 frame report: " + String(error));
    }
  }

  #reportReadiness(value) {
    try {
      const report = asReport(value, "M9 readiness report");
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
      this.#recordFatal("invalid M9 readiness report: " + String(error));
    }
  }

  #reportFocus(value) {
    try {
      const report = asReport(value, "M9 Ozone focus report");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.keyboardTargetPresent !== "boolean" ||
          typeof report.active !== "boolean") {
        throw new Error("focus metadata is invalid");
      }
      appendBounded(this.#focusReports, {
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      });
    } catch (error) {
      this.#recordFatal("invalid M9 Ozone focus report: " + String(error));
    }
  }

  #reportTextInputState(value) {
    try {
      const report = asReport(value, "M9 Ozone text-input state");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.focusedClientPresent !== "boolean" ||
          typeof report.editable !== "boolean" ||
          typeof report.canComposeInline !== "boolean") {
        throw new Error("text-input state is invalid");
      }
      appendBounded(this.#textInputStates, {
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      });
      this.#textInput?.handleOzoneTextInputState(report);
    } catch (error) {
      this.#recordFatal("invalid M9 Ozone text-input state: " + String(error));
    }
  }

  #reportTextInputDelivery(value) {
    try {
      const report = asReport(value, "M9 Ozone text-input delivery");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.action) || report.action < 1 ||
          report.action > 3 || !Number.isSafeInteger(report.sessionId) ||
          report.sessionId < 1 || !Number.isSafeInteger(report.sequence) ||
          report.sequence < 1 || typeof report.accepted !== "boolean") {
        throw new Error("text-input delivery is invalid");
      }
      appendBounded(this.#textInputDeliveries, {
        action: report.action,
        sessionId: report.sessionId,
        sequence: report.sequence,
        accepted: report.accepted,
      });
    } catch (error) {
      this.#recordFatal("invalid M9 text-input delivery: " + String(error));
    }
  }

  #reportBrowserTextDelivery(value) {
    if (!this.#textInput) {
      this.#recordFatal("M9 browser text delivery arrived before adapter");
      return;
    }
    this.#textInput.handleOzoneBrowserTextInputDelivery(value);
  }

  #reportCursor(value) {
    try {
      const report = asReport(value, "M9 Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType) ||
          report.cursorType < -1 || report.cursorType > 53) {
        throw new Error("cursor metadata is invalid");
      }
      this.#canvas.style.cursor = report.cursorType === 3 ? "text" : "default";
      return true;
    } catch (error) {
      this.#recordFatal("invalid M9 Ozone cursor report: " + String(error));
      return false;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("M9 host bridge is already installed");
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
      reportOzoneTextInputDelivery(report) {
        host.#reportTextInputDelivery(report);
      },
      reportOzoneBrowserTextInputDelivery(report) {
        host.#reportBrowserTextDelivery(report);
      },
      reportOzoneCursor(report) { return host.#reportCursor(report); },
    });
  }

  #advanceTrustedInputSignal() {
    if (!this.#textInput || !this.#readyMarkerObserved ||
        this.#input.textDeliveryAccepted === false &&
            this.#input.nativeTextDeliveryCount > 0) {
      return;
    }
    const snapshot = this.#textInput.snapshot();
    if (!snapshot.attached || snapshot.deliveryRejected) {
      return;
    }
    if (!this.#input.ctrlLComplete) {
      this.#setSignal(CDP_CTRL_L_READY);
      return;
    }
    if (!this.#input.proxyFocusedAfterCtrlL || !snapshot.proxyFocused) {
      return;
    }
    if (this.#input.nativeTextAdmissionCount === 0) {
      this.#setSignal(CDP_INSERT_TEXT_READY);
      return;
    }
    if (!this.#input.textDeliveryAccepted || snapshot.pendingDeliveryCount !== 0) {
      return;
    }
    if (!this.#input.enterComplete) {
      this.#setSignal(CDP_ENTER_READY);
      return;
    }
    this.#setSignal(null);
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null ||
        typeof module.ccall !== "function" ||
        typeof module._chromium_wasm_browser_host_key !== "function" ||
        typeof module._chromium_wasm_browser_host_text !== "function" ||
        typeof module._malloc !== "function" || typeof module._free !== "function" ||
        !(module.HEAPU8 instanceof Uint8Array)) {
      this.#recordFatal("M9 module lacks required trusted-input exports");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#textInput = new ChromiumWasmTrustedTextInput(this.#canvas, this.#proxy, {
      getModule: () => this.#module,
      reportFatal: (message) => this.#recordFatal(message),
      validateBeforeInput: (event) => {
        if (this.#input.nativeTextAdmissionCount !== 0 ||
            event.data !== ADDRESS_TEXT) {
          return "M9 smoke accepts exactly one canonical address transaction";
        }
        return null;
      },
      canSubmitEnter: () => this.#input.textDeliveryAccepted,
      onCtrlLComplete: () => {
        if (!this.#readyMarkerObserved) {
          this.#recordFatal("M9 Ctrl+L arrived before native READY");
        }
        this.#input.ctrlLComplete = true;
        this.#advanceTrustedInputSignal();
      },
      onProxyFocused: () => {
        this.#input.proxyFocusedAfterCtrlL = true;
        this.#advanceTrustedInputSignal();
      },
      onBeforeInputQueued: (record) => {
        if (record.sequence !== 1 || record.dataUtf8Bytes !== ADDRESS_TEXT.length) {
          this.#recordFatal("M9 text admission did not match canonical input");
          return;
        }
        ++this.#input.nativeTextAdmissionCount;
        this.#advanceTrustedInputSignal();
      },
      onNativeDelivery: (report) => {
        if (report.action !== 4 || report.sessionId !== 0 ||
            report.sequence !== 1 || report.text !== ADDRESS_TEXT ||
            this.#input.nativeTextDeliveryCount !== 0) {
          this.#recordFatal("M9 native text delivery did not match canonical input");
          return;
        }
        ++this.#input.nativeTextDeliveryCount;
        this.#input.nativeTextDeliverySequences.push(report.sequence);
        this.#input.textDeliveryAccepted = true;
        this.#advanceTrustedInputSignal();
      },
      onNativeDeliveryRejected: () =>
        this.#recordFatal("M9 native text delivery was rejected"),
      onEnterComplete: () => {
        this.#input.enterComplete = true;
        this.#advanceTrustedInputSignal();
      },
      onStateChange: () => this.#advanceTrustedInputSignal(),
    });
    this.#textInput.attach();
    const state = this.#textInputStates.at(-1);
    if (state) {
      this.#textInput.handleOzoneTextInputState(state);
    }
    this.#advanceTrustedInputSignal();
  }

  #result(status, error) {
    const text = this.#textInput?.snapshot() || {
      attached: false,
      ctrlLRecords: [],
      beforeInputRecords: [],
      browserTextDeliveryReports: [],
      enterRecords: [],
      rejectedRecords: [],
      cleanupRecords: [],
      pendingDeliveryCount: 0,
      pendingTextUtf8Bytes: 0,
      tombstonedDeliveryCount: 0,
      deliveryAccepted: false,
      deliveryRejected: false,
      proxyFocused: false,
      textareaValue: "",
    };
    const {textareaValue, ...textMetadata} = text;
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m9GateComplete: false,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      factorySettled: this.#factorySettled,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      m9WispRecovery: {
        wispConfigured: this.#wispConfigured,
        runtimeArgumentsConfigured: this.#runtimeArgumentsConfigured,
        configurationPrecededFactory: this.#configurationPrecededFactory,
        readyMarkerObserved: this.#readyMarkerObserved,
        navigatedMarkerObserved: this.#navigatedMarkerObserved,
        nativeDisconnectMarkerObserved: this.#nativeDisconnectMarkerObserved,
        h2RecoveredMarkerObserved: this.#h2RecoveredMarkerObserved,
        sameInstanceMarkerObserved: this.#sameInstanceMarkerObserved,
        passMarkerObserved: this.#passMarkerObserved,
        frameIdAtH2Recovered: this.#frameIdAtH2Recovered,
        h2RecoveredObservationSequence: this.#h2RecoveredObservationSequence,
        sameInstanceObservationSequence:
            this.#sameInstanceObservationSequence,
        recoveryFrameObserved: this.#recoveryFrame !== null,
        recoveryFrameId: this.#recoveryFrame?.id || 0,
      },
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      ozoneFocusReports: this.#focusReports,
      ozoneTextInputStates: this.#textInputStates,
      ozoneTextInputDeliveries: this.#textInputDeliveries,
      hostInput: {
        ...this.#input,
        ...textMetadata,
        proxyTextEmpty: textareaValue === "",
      },
      recoveryScreenshot: this.#recoveryFrame,
      canvasBackingStore: {width: this.#canvas.width, height: this.#canvas.height},
      stdout: this.#stdout,
      stderr: this.#stderr,
      failedChecks: [],
      error,
    };
  }

  async run(modulePath, timeoutMs, wispEndpoint, fixtureUrl) {
    const startedAt = performance.now();
    try {
      if (!crossOriginIsolated || typeof SharedArrayBuffer !== "function") {
        throw new Error("M9 host requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("M9 timeout is outside the bounded policy");
      }
      const fixture = parseFixtureUrl(fixtureUrl);
      const wispConfiguration = parseWispConfiguration(wispEndpoint);
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("M9 module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("M9 canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();

      // This loads only the immutable module artifact served by this outer
      // host. It never requests the canonical inner Chrome fixture URL.
      const loaderResponse = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!loaderResponse.ok) {
        throw new Error("M9 module request returned HTTP " + loaderResponse.status);
      }
      const mainScriptUrlOrBlob = await loaderResponse.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("M9 module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("M9 module loader has no default factory");
      }

      const host = this;
      const moduleOptions = {
        arguments: [SWITCH, URL_SWITCH + "=" + fixture.href],
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
          host.#recordFatal("M9 abort: " + host.#abort);
        },
        onExit(code) { host.#reportRuntimeExit(Number(code)); },
      };
      moduleOptions.chromiumWasmWisp = wispConfiguration;
      this.#wispConfigured = true;
      this.#runtimeArgumentsConfigured = true;
      this.#configurationPrecededFactory =
          this.#wispConfigured && this.#runtimeArgumentsConfigured;
      const factoryPromise = namespace.default(moduleOptions).then((module) => {
        this.#factorySettled = true;
        module.chromiumWasmHostBridge = globalThis.__chromiumWasmHostBridgeV1;
        if (this.#module === null) {
          this.#setModule(module);
        }
      }).catch((error) => {
        this.#factorySettled = true;
        this.#recordFatal("M9 module factory rejected: " + String(error));
      });

      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("M9 runtime did not exit before timeout");
      }
      await Promise.race([factoryPromise, delay(250)]);
      if (!this.#factorySettled) {
        throw new Error("M9 factory did not settle after exit");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#setSignal(null);
      this.#textInput?.detach();
      this.#textInput = null;
      this.#releaseWindowErrors();
    }
  }
}

function isCapturedRecoveryScreenshot(value) {
  if (!value || typeof value !== "object" || value.mimeType !== "image/png" ||
      typeof value.dataBase64 !== "string" || !Number.isSafeInteger(value.id) ||
      value.id < 1 || !Number.isSafeInteger(value.width) || value.width < 1 ||
      !Number.isSafeInteger(value.height) || value.height < 1 ||
      !Number.isSafeInteger(value.observationSequence) ||
      value.observationSequence < 1) {
    return false;
  }
  try {
    decodePngDataUrl(PNG_DATA_URL_PREFIX + value.dataBase64);
    return true;
  } catch (_) {
    return false;
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
  require(result.m9GateComplete === false, "M9 smoke claims a gate completion");
  require(result.runtimeExitCode === 0, "runtime did not exit zero");
  require(result.processExitCode === null || result.processExitCode === 0,
      "process exit disagrees with runtime exit");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.factorySettled === true, "factory did not settle");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.abort === null, "runtime aborted");
  for (const field of ["fatalErrors", "windowErrors", "unhandledRejections"]) {
    require(Array.isArray(result[field]) && result[field].length === 0,
        field + " is not empty");
  }
  const recovery = result.m9WispRecovery;
  require(recovery && typeof recovery === "object", "M9 recovery evidence absent");
  for (const field of [
    "wispConfigured", "runtimeArgumentsConfigured",
    "configurationPrecededFactory", "readyMarkerObserved",
    "navigatedMarkerObserved", "nativeDisconnectMarkerObserved",
    "h2RecoveredMarkerObserved", "sameInstanceMarkerObserved",
    "passMarkerObserved", "recoveryFrameObserved",
  ]) {
    require(recovery?.[field] === true, "M9 recovery " + field + " is absent");
  }
  require(Number.isSafeInteger(recovery?.frameIdAtH2Recovered) &&
      Number.isSafeInteger(recovery?.h2RecoveredObservationSequence) &&
      Number.isSafeInteger(recovery?.sameInstanceObservationSequence) &&
      Number.isSafeInteger(recovery?.recoveryFrameId) &&
      recovery.recoveryFrameId > recovery.frameIdAtH2Recovered,
      "M9 recovery frame did not follow H2 marker");
  require(isCapturedRecoveryScreenshot(result.recoveryScreenshot),
      "M9 recovery screenshot is invalid");
  require(result.recoveryScreenshot?.id === recovery?.recoveryFrameId,
      "M9 screenshot frame does not match recovery evidence");
  require(result.recoveryScreenshot?.observationSequence >
          recovery?.h2RecoveredObservationSequence &&
      result.recoveryScreenshot?.observationSequence <
          recovery?.sameInstanceObservationSequence,
      "M9 recovery screenshot is not between H2 and same-instance evidence");
  require(Array.isArray(result.readinessReports) && result.readinessReports.some(
      (report) => isReadinessReport(report) &&
          report.firstVisuallyNonEmptyPaint === true),
      "M9 first visually non-empty paint was not reported");
  require(Array.isArray(result.ozoneFocusReports) && result.ozoneFocusReports.some(
      (report) => report.keyboardTargetPresent === true && report.active === true),
      "M9 active Ozone keyboard target was not reported");
  const input = result.hostInput;
  require(input && input.readyObserved === true && input.ctrlLComplete === true &&
      input.proxyFocusedAfterCtrlL === true && input.textDeliveryAccepted === true &&
      input.enterComplete === true, "M9 trusted input transaction is incomplete");
  require(input?.nativeTextAdmissionCount === 1 &&
      input?.nativeTextDeliveryCount === 1 &&
      JSON.stringify(input?.nativeTextDeliverySequences) === "[1]" &&
      input?.deliveryAccepted === true && input?.deliveryRejected === false &&
      input?.pendingDeliveryCount === 0 && input?.pendingTextUtf8Bytes === 0 &&
      input?.proxyTextEmpty === true && input?.tombstonedDeliveryCount === 0,
      "M9 canonical text delivery is invalid");
  require(Array.isArray(input?.ctrlLRecords) && input.ctrlLRecords.length === 4 &&
      input.ctrlLRecords.every((record, index) => {
        const expected = [
          ["keydown", "ControlLeft"], ["keydown", "KeyL"],
          ["keyup", "KeyL"], ["keyup", "ControlLeft"],
        ][index];
        return record?.type === expected[0] && record.code === expected[1] &&
            record.trusted === true && record.cancelable === true &&
            record.canvasFocused === true && record.accepted === true &&
            record.defaultPrevented === true;
      }),
      "M9 Ctrl+L trusted evidence is invalid");
  require(Array.isArray(input?.beforeInputRecords) &&
      input.beforeInputRecords.length === 1 &&
      input.beforeInputRecords[0]?.dataOmitted === true &&
      !Object.hasOwn(input.beforeInputRecords[0] || {}, "data") &&
      input.beforeInputRecords[0]?.inputType === "insertText" &&
      input.beforeInputRecords[0]?.dataUtf16Units === ADDRESS_TEXT.length &&
      input.beforeInputRecords[0]?.dataUtf8Bytes === ADDRESS_TEXT.length &&
      input.beforeInputRecords[0]?.sequence === 1 &&
      input.beforeInputRecords[0]?.nativeDispatched === true &&
      input.beforeInputRecords[0]?.trusted === true &&
      input.beforeInputRecords[0]?.cancelable === true &&
      input.beforeInputRecords[0]?.isComposing === false &&
      input.beforeInputRecords[0]?.proxyFocused === true &&
      input.beforeInputRecords[0]?.queued === true &&
      input.beforeInputRecords[0]?.defaultPrevented === true &&
      input.beforeInputRecords[0]?.nativeAccepted === true,
      "M9 trusted beforeinput evidence is invalid");
  require(Array.isArray(input?.browserTextDeliveryReports) &&
      input.browserTextDeliveryReports.length === 1 &&
      input.browserTextDeliveryReports[0]?.action === 4 &&
      input.browserTextDeliveryReports[0]?.sessionId === 0 &&
      input.browserTextDeliveryReports[0]?.sequence === 1 &&
      input.browserTextDeliveryReports[0]?.accepted === true,
      "M9 browser action-4 delivery evidence is invalid");
  require(Array.isArray(input?.enterRecords) && input.enterRecords.length === 2 &&
      input.enterRecords.every((record, index) =>
          record?.type === (index === 0 ? "keydown" : "keyup") &&
          record.code === "Enter" && record.key === "Enter" &&
          record.trusted === true &&
          record.cancelable === true && record.proxyFocused === true &&
          record.accepted === true && record.defaultPrevented === true),
      "M9 trusted Enter evidence is invalid");
  for (const field of ["rejectedRecords", "cleanupRecords"]) {
    require(Array.isArray(input?.[field]) && input[field].length === 0,
        "M9 trusted input has unexpected " + field);
  }
  const stdoutLines = Array.isArray(result.stdout) ? result.stdout.map(String) : [];
  const stderrLines = Array.isArray(result.stderr) ? result.stderr.map(String) : [];
  let previousMarkerLine = -1;
  for (const marker of [
    READY_MARKER, NAVIGATED_MARKER, NATIVE_DISCONNECT_MARKER,
    H2_RECOVERED_MARKER, SAME_INSTANCE_MARKER, PASS_MARKER,
  ]) {
    const exactLines = stdoutLines.filter((line) => line === marker);
    const occurrences = stdoutLines.reduce(
        (count, line) => count + line.split(marker).length - 1, 0);
    const stderrOccurrences = stderrLines.reduce(
        (count, line) => count + line.split(marker).length - 1, 0);
    const lineIndex = stdoutLines.indexOf(marker);
    require(exactLines.length === 1 && occurrences === 1 && stderrOccurrences === 0,
        "M9 output does not contain exactly one " + marker);
    require(lineIndex > previousMarkerLine,
        "M9 output marker order is invalid at " + marker);
    previousMarkerLine = lineIndex;
  }
  result.failedChecks = failures;
  if (failures.length > 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

function displayResult(result) {
  if (!result?.recoveryScreenshot ||
      typeof result.recoveryScreenshot.dataBase64 !== "string") {
    return result;
  }
  return {
    ...result,
    recoveryScreenshot: {...result.recoveryScreenshot, dataBase64: "<omitted>"},
  };
}

export async function runChromeWasmBrowserM9WispRecoverySmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "M9 result token");
  const moduleName = asNonemptyString(query.get("module"), "M9 module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("M9 module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "60000");
  const root = document.querySelector("#m9-wisp-recovery-root");
  const canvas = document.querySelector("#browser-canvas");
  const proxy = document.querySelector("#browser-text-proxy");
  const status = document.querySelector("#m9-wisp-recovery-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(proxy instanceof HTMLTextAreaElement) || !(status instanceof HTMLElement)) {
    throw new Error("M9 host page is missing required elements");
  }
  const host = new ChromiumWasmBrowserM9WispRecoverySmokeHost(
      canvas, proxy, parseVersions(query.get("versions")));
  const result = validateResult(await host.run(
      location.pathname.replace(/\/$/, "") + "/artifacts/" + moduleName + ".js",
      timeoutMs, query.get("wispEndpoint"), query.get("fixtureUrl")));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(displayResult(result), null, 2);
  const response = await fetch(
      location.pathname.replace(/\/$/, "") + "/result/" +
          encodeURIComponent(token),
      {
        method: "POST",
        cache: "no-store",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error("M9 result upload returned HTTP " + response.status);
  }
  return result;
}

export const chromeWasmBrowserM9WispRecoverySmokeContract = Object.freeze({
  CASE,
  CDP_CTRL_L_READY,
  CDP_ENTER_READY,
  CDP_INSERT_TEXT_READY,
  FIXTURE_PATH,
  FIXTURE_URL,
  H2_RECOVERED_MARKER,
  HOST_PROTOCOL,
  NATIVE_DISCONNECT_MARKER,
  NAVIGATED_MARKER,
  PASS_MARKER,
  READY_MARKER,
  SAME_INSTANCE_MARKER,
  SCOPE,
  SWITCH,
  URL_SWITCH,
});

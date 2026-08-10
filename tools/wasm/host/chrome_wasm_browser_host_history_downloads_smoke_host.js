// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This host proves the product trusted-DOM text and pointer adapters. Two
// HTTPS visits enter Chrome through Ctrl+L, beforeinput, and physical Enter.
// History and Downloads are selected through real BrowserView menu targets.
// The C++ lifecycle owns Browser, WebContents, WebUI, journal, FVP, and every
// ordinal decision; this file never exposes a host navigation command.

import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";
import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";

const HOST_PROTOCOL = 1;
const CASE = "browser_host_history_downloads_m6";
const SCOPE =
    "trusted-dom-text-pointer-ozone-aura-views-history-downloads-volatile";
const SWITCH = "--wasm-browser-host-history-downloads-smoke";
const URL_SWITCH = "--wasm-browser-controlled-https-url";
const FIRST_ADDRESS_TEXT = "https://a.test/m5/m6-ui#wasm_journal=1";
const SECOND_ADDRESS_TEXT = "https://a.test/m5/m6-ui";
const CONTROLLED_ROOT_URL = SECOND_ADDRESS_TEXT;
const FIXTURE_HOSTNAME = "a.test";
const FIXTURE_PATH = "/m5/m6-ui";
const WISP_CONFIGURATION_VERSION = 1;
const WISP_SUBPROTOCOL = "wisp";
const MAX_TIMEOUT_MS = 180000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 128;

const READY_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:READY";
const FIRST_NAVIGATED_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:FIRST_NAVIGATED";
const SECOND_TAB_READY_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:SECOND_TAB_READY";
const SECOND_NAVIGATED_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:SECOND_NAVIGATED";
const MENU_OPEN_HISTORY_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_OPEN_HISTORY";
const MENU_CLOSED_HISTORY_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_CLOSED_HISTORY";
const HISTORY_NAVIGATED_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:HISTORY_NAVIGATED";
const MENU_OPEN_DOWNLOADS_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_OPEN_DOWNLOADS";
const MENU_CLOSED_DOWNLOADS_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:MENU_CLOSED_DOWNLOADS";
const DOWNLOADS_NAVIGATED_MARKER =
    "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:DOWNLOADS_NAVIGATED";
const PASS_MARKER = "CHROMIUM_WASM_M6_HOST_HISTORY_DOWNLOADS:PASS";

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
  if (typeof value !== "string" || !value) {
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
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error("invalid History/Downloads versions: " + String(error));
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], "version " + field);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("History/Downloads host has no versions element");
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

function parseControlledRootUrl(value) {
  const raw = asNonemptyString(value, "controlled HTTPS root URL");
  let url;
  try {
    url = new URL(raw);
  } catch (_) {
    throw new Error("controlled HTTPS root URL is invalid");
  }
  if (url.protocol !== "https:" || url.hostname !== FIXTURE_HOSTNAME ||
      url.pathname !== FIXTURE_PATH || url.search || url.hash ||
      url.username || url.password || url.port !== "" ||
      url.href !== CONTROLLED_ROOT_URL) {
    throw new Error("controlled HTTPS root URL violates fixed policy");
  }
  return url;
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
  const endpointText = asNonemptyString(value, "History/Downloads WISP endpoint");
  let endpoint;
  try {
    endpoint = new URL(endpointText);
  } catch (_) {
    throw new Error("History/Downloads WISP endpoint is invalid");
  }
  const port = Number(endpoint.port);
  if ((endpoint.protocol !== "ws:" && endpoint.protocol !== "wss:") ||
      !isLoopbackHostname(endpoint.hostname) || endpoint.username ||
      endpoint.password || endpoint.search || endpoint.hash ||
      endpoint.pathname !== "/wisp/" || endpoint.port === "" ||
      !Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("History/Downloads WISP endpoint violates transport policy");
  }
  return Object.freeze({
    version: WISP_CONFIGURATION_VERSION,
    endpoint: endpoint.href,
    subprotocol: WISP_SUBPROTOCOL,
  });
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
  // All marker names are fixed product constants and contain no regex syntax.
  const match = new RegExp(marker + " x=(\\d+) y=(\\d+)").exec(line);
  if (!match) {
    return null;
  }
  const x = Number(match[1]);
  const y = Number(match[2]);
  if (!Number.isSafeInteger(x) || !Number.isSafeInteger(y) || x < 0 || y < 0 ||
      x >= MAX_FRAME_DIMENSION || y >= MAX_FRAME_DIMENSION) {
    throw new Error("invalid marker target");
  }
  return {x, y};
}

function redactDiagnostic(value) {
  let text = String(value);
  for (const raw of [FIRST_ADDRESS_TEXT, SECOND_ADDRESS_TEXT]) {
    text = text.replaceAll(raw, "<redacted-url>");
  }
  // Result and state JSON must never retain raw typed browser URLs.
  text = text.replace(/(?:https?|chrome):\/\/[^\s"'<>]+/g, "<redacted-url>");
  return text.slice(0, 1024);
}

function expectedTextByteLength(phase) {
  return new TextEncoder().encode(
      phase === "first" ? FIRST_ADDRESS_TEXT : SECOND_ADDRESS_TEXT).byteLength;
}

function snapshotMetadata(snapshot) {
  const {textareaValue, ...metadata} = snapshot;
  return metadata;
}

class ChromiumWasmBrowserHostHistoryDownloadsSmokeHost {
  #canvas;
  #proxy;
  #versions;
  #module = null;
  #pointerInput = null;
  #textInput = null;
  #activeText = null;
  #completedText = [];
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #frameReports = [];
  #readinessReports = [];
  #focusReports = [];
  #textInputStates = [];
  #textInputDeliveries = [];
  #cursorReports = [];
  #readiness = null;
  #runtimeInitialized = false;
  #factorySettled = false;
  #runtimeExitCode = null;
  #processExitCode = null;
  #abort = null;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #errorHandler;
  #rejectionHandler;
  #state = "starting";
  #wispConfigured = false;
  #runtimeArgumentsConfigured = false;
  #configurationPrecededFactory = false;
  #proof = {
    readyObserved: false,
    firstNavigatedObserved: false,
    secondTabReadyObserved: false,
    secondNavigatedObserved: false,
    menuOpenHistoryObserved: false,
    menuClosedHistoryObserved: false,
    historyNavigatedObserved: false,
    menuOpenDownloadsObserved: false,
    menuClosedDownloadsObserved: false,
    downloadsNavigatedObserved: false,
    passObserved: false,
    newTabTarget: null,
    firstMenuTarget: null,
    historyTarget: null,
    secondMenuTarget: null,
    downloadsTarget: null,
    frameIdAtFirstNavigatedMarker: null,
    frameIdAfterFirstNavigatedMarker: null,
    frameIdAtSecondTabReadyMarker: null,
    frameIdAfterSecondTabReadyMarker: null,
    frameIdAtSecondNavigatedMarker: null,
    frameIdAfterSecondNavigatedMarker: null,
    frameIdAtMenuOpenHistoryMarker: null,
    frameIdAfterMenuOpenHistoryMarker: null,
    frameIdAtMenuClosedHistoryMarker: null,
    frameIdAfterMenuClosedHistoryMarker: null,
    frameIdAtHistoryNavigatedMarker: null,
    frameIdAfterHistoryNavigatedMarker: null,
    frameIdAtMenuOpenDownloadsMarker: null,
    frameIdAfterMenuOpenDownloadsMarker: null,
    frameIdAtMenuClosedDownloadsMarker: null,
    frameIdAfterMenuClosedDownloadsMarker: null,
    frameIdAtDownloadsNavigatedMarker: null,
    frameIdAfterDownloadsNavigatedMarker: null,
    newTabCheckQueued: false,
    historyMenuOpenCheckQueued: false,
    historyMenuClosedCheckQueued: false,
    downloadsMenuOpenCheckQueued: false,
    downloadsMenuClosedCheckQueued: false,
    finalPresentationQueued: false,
    newTabActionOffset: null,
    firstMenuActionOffset: null,
    historyActionOffset: null,
    secondMenuActionOffset: null,
    downloadsActionOffset: null,
    pointerRecords: [],
  };

  constructor(canvas, proxy, versions) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(proxy instanceof HTMLTextAreaElement)) {
      throw new Error("History/Downloads host requires canvas and textarea");
    }
    this.#canvas = canvas;
    this.#proxy = proxy;
    this.#versions = versions;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
    this.#publishState();
  }

  #recordFatal(value) {
    appendBounded(this.#fatalErrors, redactDiagnostic(value));
  }

  #currentFrameId() {
    return this.#frameReports.at(-1)?.id ?? 0;
  }

  #firstFrameAfter(frameId) {
    return this.#frameReports.find((frame) => frame.id > frameId) ?? null;
  }

  #setState(state) {
    this.#state = state;
    this.#publishState();
  }

  #actionRecords() {
    return this.#proof.pointerRecords.filter((record) =>
      record.type === "down" || record.type === "up");
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

  #setTarget(field, offsetField, target) {
    const clientTarget = this.#targetForClientPoint(target);
    if (!clientTarget) {
      throw new Error("marker target cannot map to canvas");
    }
    this.#proof[field] = clientTarget;
    this.#proof[offsetField] = this.#actionRecords().length;
  }

  #setFirstFrameAfter(markerField, frameField) {
    if (this.#proof[frameField] !== null || this.#proof[markerField] === null) {
      return;
    }
    const frame = this.#firstFrameAfter(this.#proof[markerField]);
    if (frame) {
      this.#proof[frameField] = frame.id;
    }
  }

  #recordMarkerFrame(markerField) {
    this.#proof[markerField] = this.#currentFrameId();
  }

  #updatePostMarkerFrames() {
    this.#setFirstFrameAfter(
        "frameIdAtFirstNavigatedMarker", "frameIdAfterFirstNavigatedMarker");
    this.#setFirstFrameAfter(
        "frameIdAtSecondTabReadyMarker", "frameIdAfterSecondTabReadyMarker");
    this.#setFirstFrameAfter(
        "frameIdAtSecondNavigatedMarker", "frameIdAfterSecondNavigatedMarker");
    this.#setFirstFrameAfter(
        "frameIdAtMenuOpenHistoryMarker",
        "frameIdAfterMenuOpenHistoryMarker");
    this.#setFirstFrameAfter(
        "frameIdAtMenuClosedHistoryMarker",
        "frameIdAfterMenuClosedHistoryMarker");
    this.#setFirstFrameAfter(
        "frameIdAtHistoryNavigatedMarker",
        "frameIdAfterHistoryNavigatedMarker");
    this.#setFirstFrameAfter(
        "frameIdAtMenuOpenDownloadsMarker",
        "frameIdAfterMenuOpenDownloadsMarker");
    this.#setFirstFrameAfter(
        "frameIdAtMenuClosedDownloadsMarker",
        "frameIdAfterMenuClosedDownloadsMarker");
    this.#setFirstFrameAfter(
        "frameIdAtDownloadsNavigatedMarker",
        "frameIdAfterDownloadsNavigatedMarker");
  }

  #recordOutput(line) {
    const text = String(line);
    try {
      if (text.includes(READY_MARKER)) {
        if (this.#proof.readyObserved || this.#proof.firstNavigatedObserved) {
          throw new Error("History/Downloads READY marker is out of order");
        }
        this.#proof.readyObserved = true;
      }
      const firstNavigated = parseTargetMarker(text, FIRST_NAVIGATED_MARKER);
      if (firstNavigated) {
        if (!this.#proof.readyObserved || this.#proof.firstNavigatedObserved ||
            this.#proof.secondTabReadyObserved) {
          throw new Error("FIRST_NAVIGATED marker is out of order");
        }
        this.#proof.firstNavigatedObserved = true;
        this.#recordMarkerFrame("frameIdAtFirstNavigatedMarker");
        this.#setTarget("newTabTarget", "newTabActionOffset", firstNavigated);
      }
      if (text.includes(SECOND_TAB_READY_MARKER)) {
        if (!this.#proof.newTabCheckQueued ||
            this.#proof.secondTabReadyObserved ||
            !this.#proof.firstNavigatedObserved) {
          throw new Error("SECOND_TAB_READY marker is out of order");
        }
        this.#proof.secondTabReadyObserved = true;
        this.#recordMarkerFrame("frameIdAtSecondTabReadyMarker");
      }
      const secondNavigated = parseTargetMarker(text, SECOND_NAVIGATED_MARKER);
      if (secondNavigated) {
        if (!this.#proof.secondTabReadyObserved ||
            this.#proof.secondNavigatedObserved ||
            this.#proof.historyNavigatedObserved) {
          throw new Error("SECOND_NAVIGATED marker is out of order");
        }
        this.#proof.secondNavigatedObserved = true;
        this.#recordMarkerFrame("frameIdAtSecondNavigatedMarker");
        this.#setTarget("firstMenuTarget", "firstMenuActionOffset", secondNavigated);
      }
      const menuOpenHistory = parseTargetMarker(text, MENU_OPEN_HISTORY_MARKER);
      if (menuOpenHistory) {
        if (!this.#proof.historyMenuOpenCheckQueued ||
            this.#proof.menuOpenHistoryObserved ||
            !this.#proof.secondNavigatedObserved) {
          throw new Error("MENU_OPEN_HISTORY marker is out of order");
        }
        this.#proof.menuOpenHistoryObserved = true;
        this.#recordMarkerFrame("frameIdAtMenuOpenHistoryMarker");
        this.#setTarget("historyTarget", "historyActionOffset", menuOpenHistory);
      }
      if (text.includes(MENU_CLOSED_HISTORY_MARKER)) {
        if (!this.#proof.historyMenuClosedCheckQueued ||
            this.#proof.menuClosedHistoryObserved ||
            !this.#proof.menuOpenHistoryObserved) {
          throw new Error("MENU_CLOSED_HISTORY marker is out of order");
        }
        this.#proof.menuClosedHistoryObserved = true;
        this.#recordMarkerFrame("frameIdAtMenuClosedHistoryMarker");
      }
      const historyNavigated = parseTargetMarker(text, HISTORY_NAVIGATED_MARKER);
      if (historyNavigated) {
        if (!this.#proof.menuClosedHistoryObserved ||
            this.#proof.historyNavigatedObserved) {
          throw new Error("HISTORY_NAVIGATED marker is out of order");
        }
        this.#proof.historyNavigatedObserved = true;
        this.#recordMarkerFrame("frameIdAtHistoryNavigatedMarker");
        this.#setTarget("secondMenuTarget", "secondMenuActionOffset", historyNavigated);
      }
      const menuOpenDownloads = parseTargetMarker(
          text, MENU_OPEN_DOWNLOADS_MARKER);
      if (menuOpenDownloads) {
        if (!this.#proof.downloadsMenuOpenCheckQueued ||
            this.#proof.menuOpenDownloadsObserved ||
            !this.#proof.historyNavigatedObserved) {
          throw new Error("MENU_OPEN_DOWNLOADS marker is out of order");
        }
        this.#proof.menuOpenDownloadsObserved = true;
        this.#recordMarkerFrame("frameIdAtMenuOpenDownloadsMarker");
        this.#setTarget(
            "downloadsTarget", "downloadsActionOffset", menuOpenDownloads);
      }
      if (text.includes(MENU_CLOSED_DOWNLOADS_MARKER)) {
        if (!this.#proof.downloadsMenuClosedCheckQueued ||
            this.#proof.menuClosedDownloadsObserved ||
            !this.#proof.menuOpenDownloadsObserved) {
          throw new Error("MENU_CLOSED_DOWNLOADS marker is out of order");
        }
        this.#proof.menuClosedDownloadsObserved = true;
        this.#recordMarkerFrame("frameIdAtMenuClosedDownloadsMarker");
      }
      if (text.includes(DOWNLOADS_NAVIGATED_MARKER)) {
        if (!this.#proof.menuClosedDownloadsObserved ||
            this.#proof.downloadsNavigatedObserved) {
          throw new Error("DOWNLOADS_NAVIGATED marker is out of order");
        }
        this.#proof.downloadsNavigatedObserved = true;
        this.#recordMarkerFrame("frameIdAtDownloadsNavigatedMarker");
      }
      if (text.includes(PASS_MARKER)) {
        if (!this.#proof.finalPresentationQueued || this.#proof.passObserved ||
            !this.#proof.downloadsNavigatedObserved ||
            this.#proof.frameIdAfterDownloadsNavigatedMarker === null) {
          throw new Error("History/Downloads PASS marker is out of order");
        }
        this.#proof.passObserved = true;
      }
      this.#advance();
    } catch (error) {
      this.#recordFatal("invalid History/Downloads output: " + String(error));
    }
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL || !isFrameReport(report)) {
        throw new Error("frame report metadata is invalid");
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
      this.#updatePostMarkerFrames();
      // This import can run synchronously from the proxied UI thread. Any
      // verifier export requested by its fresh-frame evidence is deferred.
      this.#advance();
    } catch (error) {
      this.#recordFatal("invalid frame report: " + String(error));
    }
  }

  #reportReadiness(value) {
    try {
      const report = asReport(value, "readiness report");
      if (report.protocol !== HOST_PROTOCOL || !isReadinessReport(report)) {
        throw new Error("readiness report is invalid");
      }
      this.#readiness = {
        shellReady: report.shellReady,
        surfaceReady: report.surfaceReady,
        firstVisuallyNonEmptyPaint: report.firstVisuallyNonEmptyPaint,
      };
      appendBounded(this.#readinessReports, this.#readiness);
    } catch (error) {
      this.#recordFatal("invalid readiness report: " + String(error));
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
      this.#recordFatal("invalid Ozone focus report: " + String(error));
    }
  }

  #reportTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.focusedClientPresent !== "boolean" ||
          typeof report.editable !== "boolean" ||
          typeof report.canComposeInline !== "boolean") {
        throw new Error("Ozone text-input state is invalid");
      }
      const state = {
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      };
      appendBounded(this.#textInputStates, state);
      this.#textInput?.handleOzoneTextInputState(state);
    } catch (error) {
      this.#recordFatal("invalid Ozone text-input state: " + String(error));
    }
  }

  #reportTextInputDelivery(value) {
    try {
      const report = asReport(value, "Ozone text-input delivery");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.action) || report.action < 1 ||
          report.action > 3 || !Number.isSafeInteger(report.sessionId) ||
          report.sessionId < 1 || !Number.isSafeInteger(report.sequence) ||
          report.sequence < 1 || typeof report.accepted !== "boolean") {
        throw new Error("Ozone text-input delivery is invalid");
      }
      appendBounded(this.#textInputDeliveries, {
        action: report.action,
        sessionId: report.sessionId,
        sequence: report.sequence,
        accepted: report.accepted,
      });
    } catch (error) {
      this.#recordFatal("invalid Ozone text-input delivery: " + String(error));
    }
  }

  #reportBrowserTextDelivery(value) {
    if (!this.#textInput) {
      this.#recordFatal("browser text delivery arrived before the text adapter");
      return;
    }
    this.#textInput.handleOzoneBrowserTextInputDelivery(value);
  }

  #reportCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType) ||
          report.cursorType < -1 || report.cursorType > 53) {
        throw new Error("Ozone cursor report is invalid");
      }
      appendBounded(this.#cursorReports, {cursorType: report.cursorType});
      return true;
    } catch (error) {
      this.#recordFatal("invalid Ozone cursor report: " + String(error));
      return false;
    }
  }

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code) || this.#runtimeExitCode !== null) {
      this.#recordFatal("runtime exit is invalid or duplicated");
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process exit report");
      if (!Number.isSafeInteger(report.exitCode) ||
          this.#processExitCode !== null) {
        throw new Error("process exit report is invalid or duplicated");
      }
      this.#processExitCode = report.exitCode;
    } catch (error) {
      this.#recordFatal("invalid process exit report: " + String(error));
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("History/Downloads host bridge is already installed");
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

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = redactDiagnostic(
          event.error || event.message || "window error");
      appendBounded(this.#windowErrors, message);
      this.#recordFatal("window error: " + message);
    };
    this.#rejectionHandler = (event) => {
      appendBounded(this.#unhandledRejections, redactDiagnostic(event.reason));
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

  #textSnapshot() {
    return this.#textInput?.snapshot() || {
      attached: false,
      editable: false,
      shortcutComplete: false,
      proxyFocused: false,
      textQueued: false,
      deliveryAccepted: false,
      deliveryRejected: false,
      focusGeneration: 0,
      acceptedDeliveryFocusGeneration: null,
      proxySessionCleared: false,
      pendingDeliveryCount: 0,
      pendingTextUtf8Bytes: 0,
      tombstonedDeliveryCount: 0,
      textareaValue: "",
      ctrlLRecords: [],
      beforeInputRecords: [],
      browserTextDeliveryReports: [],
      enterRecords: [],
      rejectedRecords: [],
      cleanupRecords: [],
    };
  }

  #completedTransaction(phase) {
    return this.#completedText.find((transaction) =>
      transaction.phase === phase) || null;
  }

  #beginTextTransaction(phase) {
    if (this.#activeText || this.#completedTransaction(phase) ||
        !this.#textInput) {
      return;
    }
    const snapshot = this.#textSnapshot();
    this.#activeText = {
      phase,
      adapterId: 1,
      expectedText: phase === "first" ? FIRST_ADDRESS_TEXT : SECOND_ADDRESS_TEXT,
      expectedSequence: phase === "first" ? 1 : 2,
      starts: {
        ctrlL: snapshot.ctrlLRecords.length,
        beforeInput: snapshot.beforeInputRecords.length,
        delivery: snapshot.browserTextDeliveryReports.length,
        enter: snapshot.enterRecords.length,
        rejected: snapshot.rejectedRecords.length,
        cleanup: snapshot.cleanupRecords.length,
      },
      ctrlLComplete: false,
      proxyFocusedAfterCtrlL: false,
      nativeTextAdmissionCount: 0,
      nativeTextDeliveryCount: 0,
      nativeTextDeliverySequences: [],
      textDeliveryAccepted: false,
      enterComplete: false,
      rejected: false,
    };
  }

  #transactionAdapterMetadata(transaction, snapshot) {
    const starts = transaction.starts;
    return snapshotMetadata({
      ...snapshot,
      ctrlLRecords: snapshot.ctrlLRecords.slice(starts.ctrlL),
      beforeInputRecords: snapshot.beforeInputRecords.slice(starts.beforeInput),
      browserTextDeliveryReports:
          snapshot.browserTextDeliveryReports.slice(starts.delivery),
      enterRecords: snapshot.enterRecords.slice(starts.enter),
      rejectedRecords: snapshot.rejectedRecords.slice(starts.rejected),
      cleanupRecords: snapshot.cleanupRecords.slice(starts.cleanup),
    });
  }

  #finishTextTransaction() {
    const transaction = this.#activeText;
    if (!transaction || !transaction.enterComplete) {
      return;
    }
    const snapshot = this.#textSnapshot();
    const complete = {
      phase: transaction.phase,
      adapterId: transaction.adapterId,
      ctrlLComplete: transaction.ctrlLComplete,
      proxyFocusedAfterCtrlL: transaction.proxyFocusedAfterCtrlL,
      nativeTextAdmissionCount: transaction.nativeTextAdmissionCount,
      nativeTextDeliveryCount: transaction.nativeTextDeliveryCount,
      nativeTextDeliverySequences: [...transaction.nativeTextDeliverySequences],
      textDeliveryAccepted: transaction.textDeliveryAccepted,
      enterComplete: transaction.enterComplete,
      rejected: transaction.rejected,
      adapter: this.#transactionAdapterMetadata(transaction, snapshot),
    };
    this.#completedText.push(complete);
    this.#activeText = null;
  }

  #recordTextAdmission(record) {
    const transaction = this.#activeText;
    if (!transaction || record.sequence !== transaction.expectedSequence ||
        record.dataUtf8Bytes !== expectedTextByteLength(transaction.phase) ||
        record.queued !== true || record.nativeDispatched !== true) {
      this.#recordFatal("History/Downloads native text admission is invalid");
      return;
    }
    ++transaction.nativeTextAdmissionCount;
    this.#advance();
  }

  #recordTextDelivery(report) {
    const transaction = this.#activeText;
    if (!transaction || report.action !== 4 || report.sessionId !== 0 ||
        report.sequence !== transaction.expectedSequence ||
        report.accepted !== true || report.text !== transaction.expectedText) {
      this.#recordFatal("History/Downloads native text delivery is invalid");
      return;
    }
    ++transaction.nativeTextDeliveryCount;
    transaction.nativeTextDeliverySequences.push(report.sequence);
    transaction.textDeliveryAccepted = true;
    // This callback arrives inside the synchronous UI-to-JS acknowledgement.
    // It intentionally updates only transient local evidence and never calls
    // an export; all ordinal exports are deferred below.
    this.#advance();
  }

  #recordTextDeliveryRejected() {
    if (this.#activeText) {
      this.#activeText.rejected = true;
    }
    this.#recordFatal("History/Downloads native text delivery was rejected");
    this.#advance();
  }

  #recordTextCtrlLComplete() {
    if (!this.#activeText) {
      this.#recordFatal("History/Downloads Ctrl+L has no active transaction");
      return;
    }
    this.#activeText.ctrlLComplete = true;
    this.#advance();
  }

  #recordTextProxyFocused() {
    if (!this.#activeText) {
      this.#recordFatal(
          "History/Downloads textarea proxy focused without a transaction");
      return;
    }
    this.#activeText.proxyFocusedAfterCtrlL = true;
    this.#advance();
  }

  #recordTextEnterComplete() {
    if (!this.#activeText) {
      this.#recordFatal("History/Downloads Enter has no active transaction");
      return;
    }
    this.#activeText.enterComplete = true;
    this.#finishTextTransaction();
    this.#advance();
  }

  #canAcceptTextBeforeInput(event) {
    const transaction = this.#activeText;
    return !!transaction && transaction.ctrlLComplete &&
        !transaction.rejected && transaction.nativeTextAdmissionCount === 0 &&
        event.data === transaction.expectedText;
  }

  #canSubmitTextEnter() {
    const transaction = this.#activeText;
    const snapshot = this.#textSnapshot();
    return !!transaction && transaction.ctrlLComplete &&
        transaction.proxyFocusedAfterCtrlL &&
        transaction.nativeTextAdmissionCount === 1 &&
        transaction.nativeTextDeliveryCount === 1 &&
        transaction.textDeliveryAccepted && !transaction.rejected &&
        snapshot.pendingDeliveryCount === 0 && !snapshot.deliveryRejected;
  }

  #recordPointer(record) {
    appendBounded(this.#proof.pointerRecords, record);
    this.#maybeRequestChecks();
    this.#updateState();
  }

  #acceptedPointerPair(target, offset) {
    if (!target || !Number.isSafeInteger(offset)) {
      return false;
    }
    const actions = this.#actionRecords().slice(offset, offset + 2);
    if (actions.length !== 2) {
      return false;
    }
    const [down, up] = actions;
    const exact = (record) => record.trusted === true &&
        record.cancelable === true && record.pointerType === "mouse" &&
        record.primary === true && record.accepted === true &&
        record.defaultPrevented === true && record.reason === null &&
        record.x === target.x && record.y === target.y;
    return exact(down) && exact(up) && down.type === "down" &&
        down.button === 0 && down.buttons === 1 && up.type === "up" &&
        up.button === 0 && up.buttons === 0;
  }

  #deferVerifier(exportName, stage, queuedField) {
    if (this.#proof[queuedField]) {
      return;
    }
    this.#proof[queuedField] = true;
    this.#publishState();
    setTimeout(() => {
      if (!this.#module || typeof this.#module.ccall !== "function") {
        this.#recordFatal(exportName + " ran without an attached Module ccall");
        return;
      }
      try {
        const result = this.#module.ccall(
            exportName, "number", ["number"], [stage]);
        if (result !== 1) {
          this.#recordFatal(exportName + " rejected stage " + stage);
        }
      } catch (error) {
        this.#recordFatal(exportName + " failed: " + String(error));
      }
      // The observer may have completed before this asynchronous ordinal
      // arrives. Re-evaluate the joined proof after it returns.
      this.#advance();
    }, 0);
  }

  #maybeRequestChecks() {
    if (!this.#proof.newTabCheckQueued &&
        this.#proof.frameIdAfterFirstNavigatedMarker !== null &&
        this.#acceptedPointerPair(
            this.#proof.newTabTarget, this.#proof.newTabActionOffset)) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_history_downloads_check", 1,
          "newTabCheckQueued");
      return;
    }
    if (!this.#proof.historyMenuOpenCheckQueued &&
        this.#proof.frameIdAfterSecondNavigatedMarker !== null &&
        this.#acceptedPointerPair(
            this.#proof.firstMenuTarget, this.#proof.firstMenuActionOffset)) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_history_downloads_check", 2,
          "historyMenuOpenCheckQueued");
      return;
    }
    if (!this.#proof.historyMenuClosedCheckQueued &&
        this.#proof.frameIdAfterMenuOpenHistoryMarker !== null &&
        this.#acceptedPointerPair(
            this.#proof.historyTarget, this.#proof.historyActionOffset)) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_history_downloads_check", 3,
          "historyMenuClosedCheckQueued");
      return;
    }
    if (!this.#proof.downloadsMenuOpenCheckQueued &&
        this.#proof.frameIdAfterHistoryNavigatedMarker !== null &&
        this.#proof.frameIdAfterMenuClosedHistoryMarker !== null &&
        this.#acceptedPointerPair(
            this.#proof.secondMenuTarget, this.#proof.secondMenuActionOffset)) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_history_downloads_check", 4,
          "downloadsMenuOpenCheckQueued");
      return;
    }
    if (!this.#proof.downloadsMenuClosedCheckQueued &&
        this.#proof.frameIdAfterMenuOpenDownloadsMarker !== null &&
        this.#acceptedPointerPair(
            this.#proof.downloadsTarget, this.#proof.downloadsActionOffset)) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_history_downloads_check", 5,
          "downloadsMenuClosedCheckQueued");
      return;
    }
    if (!this.#proof.finalPresentationQueued &&
        this.#proof.frameIdAfterDownloadsNavigatedMarker !== null &&
        this.#proof.frameIdAfterMenuClosedDownloadsMarker !== null &&
        this.#proof.downloadsNavigatedObserved &&
        this.#proof.downloadsMenuClosedCheckQueued) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_history_downloads_presented", 6,
          "finalPresentationQueued");
    }
  }

  #textPhaseState(phase) {
    this.#beginTextTransaction(phase);
    const transaction = this.#activeText;
    if (!transaction || transaction.phase !== phase) {
      return "awaiting-native-navigation";
    }
    if (!transaction.ctrlLComplete) {
      return "awaiting-" + phase + "-https-ctrl-l";
    }
    if (!transaction.proxyFocusedAfterCtrlL) {
      return "awaiting-" + phase + "-https-insert-text";
    }
    if (transaction.nativeTextAdmissionCount === 0) {
      return "awaiting-" + phase + "-https-insert-text";
    }
    if (!transaction.textDeliveryAccepted ||
        this.#textSnapshot().pendingDeliveryCount !== 0) {
      return "awaiting-native-text-delivery";
    }
    if (!transaction.enterComplete) {
      return "awaiting-" + phase + "-https-enter";
    }
    return "awaiting-native-navigation";
  }

  #updateState() {
    this.#updatePostMarkerFrames();
    this.#maybeRequestChecks();
    if (this.#proof.passObserved) {
      this.#setState("pass-observed");
      return;
    }
    if (!this.#module || !this.#textInput || !this.#proof.readyObserved) {
      this.#setState("starting");
      return;
    }
    if (!this.#proof.firstNavigatedObserved) {
      this.#setState(this.#textPhaseState("first"));
      return;
    }
    if (!this.#proof.secondTabReadyObserved) {
      this.#setState(
          this.#proof.frameIdAfterFirstNavigatedMarker !== null ?
              "awaiting-trusted-dom-new-tab" :
              "awaiting-post-first-navigation-frame");
      return;
    }
    if (!this.#proof.secondNavigatedObserved) {
      this.#setState(
          this.#proof.frameIdAfterSecondTabReadyMarker !== null ?
              this.#textPhaseState("second") :
              "awaiting-post-second-tab-frame");
      return;
    }
    if (!this.#proof.menuOpenHistoryObserved) {
      this.#setState(
          this.#proof.frameIdAfterSecondNavigatedMarker !== null ?
              "awaiting-trusted-dom-menu-history" :
              "awaiting-post-second-navigation-frame");
      return;
    }
    if (!this.#proof.historyNavigatedObserved) {
      this.#setState(
          this.#proof.frameIdAfterMenuOpenHistoryMarker !== null ?
              "awaiting-trusted-dom-history" : "awaiting-post-history-menu-frame");
      return;
    }
    if (!this.#proof.menuOpenDownloadsObserved) {
      const historyFramesReady =
          this.#proof.frameIdAfterHistoryNavigatedMarker !== null &&
          this.#proof.frameIdAfterMenuClosedHistoryMarker !== null;
      this.#setState(historyFramesReady ?
          "awaiting-trusted-dom-menu-downloads" :
          "awaiting-post-history-navigation-frame");
      return;
    }
    if (!this.#proof.downloadsNavigatedObserved) {
      this.#setState(
          this.#proof.frameIdAfterMenuOpenDownloadsMarker !== null ?
              "awaiting-trusted-dom-downloads" :
              "awaiting-post-downloads-menu-frame");
      return;
    }
    this.#setState(this.#proof.finalPresentationQueued ?
        "awaiting-orderly-shutdown" : "awaiting-post-downloads-frame");
  }

  #advance() {
    this.#updateState();
    this.#publishState();
  }

  #hostInputResult() {
    return {
      singleAdapterRetained: this.#textInput !== null,
      textTransactions: [...this.#completedText],
      pointerRecords: [...this.#proof.pointerRecords],
      newTabTarget: this.#proof.newTabTarget,
      firstMenuTarget: this.#proof.firstMenuTarget,
      historyTarget: this.#proof.historyTarget,
      secondMenuTarget: this.#proof.secondMenuTarget,
      downloadsTarget: this.#proof.downloadsTarget,
      newTabActionOffset: this.#proof.newTabActionOffset,
      firstMenuActionOffset: this.#proof.firstMenuActionOffset,
      historyActionOffset: this.#proof.historyActionOffset,
      secondMenuActionOffset: this.#proof.secondMenuActionOffset,
      downloadsActionOffset: this.#proof.downloadsActionOffset,
      newTabCheckQueued: this.#proof.newTabCheckQueued,
      historyMenuOpenCheckQueued: this.#proof.historyMenuOpenCheckQueued,
      historyMenuClosedCheckQueued:
          this.#proof.historyMenuClosedCheckQueued,
      downloadsMenuOpenCheckQueued:
          this.#proof.downloadsMenuOpenCheckQueued,
      downloadsMenuClosedCheckQueued:
          this.#proof.downloadsMenuClosedCheckQueued,
      finalPresentationQueued: this.#proof.finalPresentationQueued,
      proxyTextEmpty: this.#proxy.value === "",
    };
  }

  #publishState() {
    const text = this.#textSnapshot();
    globalThis.__chromiumWasmM6HostHistoryDownloadsState = Object.freeze({
      state: this.#state,
      attached: this.#textInput !== null && text.attached,
      readyObserved: this.#proof.readyObserved,
      singleAdapterRetained: this.#textInput !== null,
      activeTextPhase: this.#activeText?.phase || null,
      completedTextTransactionCount: this.#completedText.length,
      pendingDeliveryCount: text.pendingDeliveryCount,
      newTabTarget: this.#proof.newTabTarget,
      firstMenuTarget: this.#proof.firstMenuTarget,
      historyTarget: this.#proof.historyTarget,
      secondMenuTarget: this.#proof.secondMenuTarget,
      downloadsTarget: this.#proof.downloadsTarget,
      historyDownloads: {
        firstNavigatedObserved: this.#proof.firstNavigatedObserved,
        secondTabReadyObserved: this.#proof.secondTabReadyObserved,
        secondNavigatedObserved: this.#proof.secondNavigatedObserved,
        menuOpenHistoryObserved: this.#proof.menuOpenHistoryObserved,
        menuClosedHistoryObserved: this.#proof.menuClosedHistoryObserved,
        historyNavigatedObserved: this.#proof.historyNavigatedObserved,
        menuOpenDownloadsObserved: this.#proof.menuOpenDownloadsObserved,
        menuClosedDownloadsObserved: this.#proof.menuClosedDownloadsObserved,
        downloadsNavigatedObserved: this.#proof.downloadsNavigatedObserved,
      },
    });
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied an invalid Module");
      return;
    }
    if (typeof module.ccall !== "function" ||
        typeof module._chromium_wasm_browser_host_key !== "function" ||
        typeof module._chromium_wasm_browser_host_pointer !== "function" ||
        typeof module._chromium_wasm_browser_host_pointer_exit !== "function" ||
        typeof module._chromium_wasm_browser_host_text !== "function" ||
        typeof module._malloc !== "function" || typeof module._free !== "function" ||
        !(module.HEAPU8 instanceof Uint8Array)) {
      this.#recordFatal(
          "History/Downloads Module lacks trusted text or pointer exports");
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
    this.#textInput = new ChromiumWasmTrustedTextInput(this.#canvas, this.#proxy, {
      getModule: () => this.#module,
      reportFatal: (message) => this.#recordFatal(message),
      canAcceptBeforeInput: () => !!this.#activeText &&
          !this.#activeText.rejected &&
          this.#activeText.nativeTextAdmissionCount === 0,
      validateBeforeInput: (event) => this.#canAcceptTextBeforeInput(event) ?
          null : "History/Downloads smoke requires its exact current address",
      canSubmitEnter: () => this.#canSubmitTextEnter(),
      onCtrlLComplete: () => this.#recordTextCtrlLComplete(),
      onProxyFocused: () => this.#recordTextProxyFocused(),
      onBeforeInputQueued: (record) => this.#recordTextAdmission(record),
      onNativeDelivery: (report) => this.#recordTextDelivery(report),
      onNativeDeliveryRejected: () => this.#recordTextDeliveryRejected(),
      onEnterComplete: () => this.#recordTextEnterComplete(),
      onStateChange: () => this.#advance(),
    });
    this.#textInput.attach();
    const latestState = this.#textInputStates.at(-1);
    if (latestState) {
      this.#textInput.handleOzoneTextInputState(latestState);
    }
    this.#advance();
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
      factorySettled: this.#factorySettled,
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
      ozoneTextInputStates: this.#textInputStates,
      ozoneTextInputDeliveries: this.#textInputDeliveries,
      ozoneCursorReports: this.#cursorReports,
      historyDownloads: {
        wispConfigured: this.#wispConfigured,
        runtimeArgumentsConfigured: this.#runtimeArgumentsConfigured,
        configurationPrecededFactory: this.#configurationPrecededFactory,
        readyObserved: this.#proof.readyObserved,
        firstNavigatedObserved: this.#proof.firstNavigatedObserved,
        secondTabReadyObserved: this.#proof.secondTabReadyObserved,
        secondNavigatedObserved: this.#proof.secondNavigatedObserved,
        menuOpenHistoryObserved: this.#proof.menuOpenHistoryObserved,
        menuClosedHistoryObserved: this.#proof.menuClosedHistoryObserved,
        historyNavigatedObserved: this.#proof.historyNavigatedObserved,
        menuOpenDownloadsObserved: this.#proof.menuOpenDownloadsObserved,
        menuClosedDownloadsObserved: this.#proof.menuClosedDownloadsObserved,
        downloadsNavigatedObserved: this.#proof.downloadsNavigatedObserved,
        passObserved: this.#proof.passObserved,
        frameIdAtFirstNavigatedMarker:
            this.#proof.frameIdAtFirstNavigatedMarker,
        frameIdAfterFirstNavigatedMarker:
            this.#proof.frameIdAfterFirstNavigatedMarker,
        frameIdAtSecondTabReadyMarker:
            this.#proof.frameIdAtSecondTabReadyMarker,
        frameIdAfterSecondTabReadyMarker:
            this.#proof.frameIdAfterSecondTabReadyMarker,
        frameIdAtSecondNavigatedMarker:
            this.#proof.frameIdAtSecondNavigatedMarker,
        frameIdAfterSecondNavigatedMarker:
            this.#proof.frameIdAfterSecondNavigatedMarker,
        frameIdAtMenuOpenHistoryMarker:
            this.#proof.frameIdAtMenuOpenHistoryMarker,
        frameIdAfterMenuOpenHistoryMarker:
            this.#proof.frameIdAfterMenuOpenHistoryMarker,
        frameIdAtMenuClosedHistoryMarker:
            this.#proof.frameIdAtMenuClosedHistoryMarker,
        frameIdAfterMenuClosedHistoryMarker:
            this.#proof.frameIdAfterMenuClosedHistoryMarker,
        frameIdAtHistoryNavigatedMarker:
            this.#proof.frameIdAtHistoryNavigatedMarker,
        frameIdAfterHistoryNavigatedMarker:
            this.#proof.frameIdAfterHistoryNavigatedMarker,
        frameIdAtMenuOpenDownloadsMarker:
            this.#proof.frameIdAtMenuOpenDownloadsMarker,
        frameIdAfterMenuOpenDownloadsMarker:
            this.#proof.frameIdAfterMenuOpenDownloadsMarker,
        frameIdAtMenuClosedDownloadsMarker:
            this.#proof.frameIdAtMenuClosedDownloadsMarker,
        frameIdAfterMenuClosedDownloadsMarker:
            this.#proof.frameIdAfterMenuClosedDownloadsMarker,
        frameIdAtDownloadsNavigatedMarker:
            this.#proof.frameIdAtDownloadsNavigatedMarker,
        frameIdAfterDownloadsNavigatedMarker:
            this.#proof.frameIdAfterDownloadsNavigatedMarker,
      },
      hostInput: this.#hostInputResult(),
      canvasBackingStore: {
        width: this.#canvas.width,
        height: this.#canvas.height,
      },
      stdout: this.#stdout,
      stderr: this.#stderr,
      failedChecks: [],
      error: error === null ? null : redactDiagnostic(error),
    };
  }

  async run(modulePath, timeoutMs, wispEndpoint, fixtureUrl) {
    const startedAt = performance.now();
    try {
      if (!crossOriginIsolated || typeof SharedArrayBuffer !== "function") {
        throw new Error("History/Downloads host requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("History/Downloads timeout is out of range");
      }
      const controlledUrl = parseControlledRootUrl(fixtureUrl);
      const wispConfiguration = parseWispConfiguration(wispEndpoint);
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("History/Downloads Module must use host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("History/Downloads canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error("History/Downloads module request returned HTTP " +
            response.status);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("History/Downloads module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("History/Downloads loader has no default factory");
      }
      const host = this;
      const moduleOptions = {
        arguments: [SWITCH, URL_SWITCH + "=" + controlledUrl.href],
        canvas: this.#canvas,
        noExitRuntime: false,
        mainScriptUrlOrBlob,
        locateFile: (path) => new URL(path, moduleUrl).href,
        print(line) {
          const text = String(line);
          appendBounded(host.#stdout, redactDiagnostic(text));
          host.#recordOutput(text);
        },
        printErr(line) {
          const text = String(line);
          appendBounded(host.#stderr, redactDiagnostic(text));
          host.#recordOutput(text);
        },
        onRuntimeInitialized() {
          host.#setModule(this);
        },
        onAbort(reason) {
          host.#abort = redactDiagnostic(reason);
          host.#recordFatal("abort: " + host.#abort);
        },
        onExit(code) {
          host.#reportRuntimeExit(Number(code));
        },
      };
      // Chromium reads this configuration while it creates its network
      // bridge, so it is deliberately installed before the factory starts.
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
        return module;
      }).catch((error) => {
        this.#factorySettled = true;
        this.#recordFatal("History/Downloads module factory rejected: " +
            String(error));
      });
      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("History/Downloads smoke did not exit before timeout");
      }
      await Promise.race([factoryPromise, delay(250)]);
      if (!this.#factorySettled) {
        throw new Error("History/Downloads factory did not settle after exit");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#pointerInput?.detach();
      this.#textInput?.detach();
      this.#releaseWindowErrors();
      this.#publishState();
    }
  }
}

function acceptedPointerPair(records, target, offset) {
  if (!Array.isArray(records) || !target || !Number.isSafeInteger(offset)) {
    return false;
  }
  const actions = records.filter((record) =>
    record?.type === "down" || record?.type === "up").slice(offset, offset + 2);
  if (actions.length !== 2) {
    return false;
  }
  const [down, up] = actions;
  const exact = (record) => record?.trusted === true &&
      record.cancelable === true && record.pointerType === "mouse" &&
      record.primary === true && record.accepted === true &&
      record.defaultPrevented === true && record.reason === null &&
      record.x === target.x && record.y === target.y;
  return exact(down) && exact(up) && down.type === "down" &&
      down.button === 0 && down.buttons === 1 && up.type === "up" &&
      up.button === 0 && up.buttons === 0;
}

function orderedFrame(proof, beforeField, afterField) {
  return Number.isSafeInteger(proof?.[beforeField]) &&
      Number.isSafeInteger(proof?.[afterField]) &&
      proof[afterField] > proof[beforeField];
}

function validTransaction(transaction, phase) {
  const sequence = phase === "first" ? 1 : 2;
  const expectedBytes = expectedTextByteLength(phase);
  const adapter = transaction?.adapter;
  if (!transaction || transaction.phase !== phase || transaction.adapterId !== 1 ||
      transaction.ctrlLComplete !== true ||
      transaction.proxyFocusedAfterCtrlL !== true ||
      transaction.nativeTextAdmissionCount !== 1 ||
      transaction.nativeTextDeliveryCount !== 1 ||
      transaction.textDeliveryAccepted !== true ||
      transaction.enterComplete !== true || transaction.rejected !== false ||
      !Array.isArray(transaction.nativeTextDeliverySequences) ||
      transaction.nativeTextDeliverySequences.length !== 1 ||
      transaction.nativeTextDeliverySequences[0] !== sequence ||
      !adapter || Object.hasOwn(adapter, "textareaValue") ||
      adapter.deliveryAccepted !== true || adapter.deliveryRejected !== false ||
      adapter.pendingDeliveryCount !== 0 ||
      adapter.pendingTextUtf8Bytes !== 0 ||
      adapter.tombstonedDeliveryCount !== 0 ||
      adapter.proxySessionCleared !== false ||
      !Array.isArray(adapter.beforeInputRecords) ||
      adapter.beforeInputRecords.length !== 1 ||
      !Array.isArray(adapter.browserTextDeliveryReports) ||
      adapter.browserTextDeliveryReports.length !== 1 ||
      !Array.isArray(adapter.ctrlLRecords) ||
      adapter.ctrlLRecords.length !== 4 ||
      !Array.isArray(adapter.enterRecords) ||
      adapter.enterRecords.length !== 2 ||
      !Array.isArray(adapter.rejectedRecords) ||
      adapter.rejectedRecords.length !== 0 ||
      !Array.isArray(adapter.cleanupRecords) ||
      adapter.cleanupRecords.length !== 0) {
    return false;
  }
  const beforeInput = adapter.beforeInputRecords[0];
  if (!beforeInput || Object.hasOwn(beforeInput, "data") ||
      beforeInput.inputType !== "insertText" ||
      beforeInput.dataOmitted !== true ||
      beforeInput.dataUtf16Units !==
          (phase === "first" ? FIRST_ADDRESS_TEXT.length :
              SECOND_ADDRESS_TEXT.length) ||
      beforeInput.dataUtf8Bytes !== expectedBytes ||
      beforeInput.trusted !== true || beforeInput.cancelable !== true ||
      beforeInput.isComposing !== false || beforeInput.proxyFocused !== true ||
      beforeInput.queued !== true || beforeInput.defaultPrevented !== true ||
      beforeInput.sequence !== sequence || beforeInput.nativeDispatched !== true ||
      beforeInput.nativeAccepted !== true) {
    return false;
  }
  const delivery = adapter.browserTextDeliveryReports[0];
  if (!delivery || delivery.action !== 4 || delivery.sessionId !== 0 ||
      delivery.sequence !== sequence || delivery.accepted !== true) {
    return false;
  }
  const ctrlLExpected = [
    ["keydown", "ControlLeft"],
    ["keydown", "KeyL"],
    ["keyup", "KeyL"],
    ["keyup", "ControlLeft"],
  ];
  for (let index = 0; index < ctrlLExpected.length; ++index) {
    const [type, code] = ctrlLExpected[index];
    const record = adapter.ctrlLRecords[index];
    if (!record || record.type !== type || record.code !== code ||
        record.trusted !== true || record.cancelable !== true ||
        record.canvasFocused !== true || record.accepted !== true ||
        record.defaultPrevented !== true) {
      return false;
    }
  }
  for (let index = 0; index < 2; ++index) {
    const record = adapter.enterRecords[index];
    if (!record || record.type !== (index === 0 ? "keydown" : "keyup") ||
        record.code !== "Enter" || record.key !== "Enter" ||
        record.trusted !== true || record.cancelable !== true ||
        record.proxyFocused !== true || record.accepted !== true ||
        record.defaultPrevented !== true) {
      return false;
    }
  }
  return true;
}

function validateResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.m6GateComplete === false,
      "History/Downloads smoke claims the M6 gate is complete");
  require(result.runtimeExitCode === 0, "runtime did not exit zero");
  require(result.processExitCode === null || result.processExitCode === 0,
      "bridge process exit disagrees with runtime");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.factorySettled === true, "factory did not settle");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocused === true, "canvas focus was lost");
  require(result.abort === null, "runtime aborted");
  for (const field of ["fatalErrors", "windowErrors", "unhandledRejections"]) {
    require(Array.isArray(result[field]) && result[field].length === 0,
        "host has " + field);
  }
  const proof = result.historyDownloads;
  for (const field of [
    "wispConfigured", "runtimeArgumentsConfigured",
    "configurationPrecededFactory", "readyObserved",
    "firstNavigatedObserved", "secondTabReadyObserved",
    "secondNavigatedObserved", "menuOpenHistoryObserved",
    "menuClosedHistoryObserved", "historyNavigatedObserved",
    "menuOpenDownloadsObserved", "menuClosedDownloadsObserved",
    "downloadsNavigatedObserved", "passObserved",
  ]) {
    require(proof?.[field] === true, "History/Downloads proof " + field);
  }
  for (const [before, after] of [
    ["frameIdAtFirstNavigatedMarker", "frameIdAfterFirstNavigatedMarker"],
    ["frameIdAtSecondTabReadyMarker", "frameIdAfterSecondTabReadyMarker"],
    ["frameIdAtSecondNavigatedMarker", "frameIdAfterSecondNavigatedMarker"],
    ["frameIdAtMenuOpenHistoryMarker", "frameIdAfterMenuOpenHistoryMarker"],
    ["frameIdAtMenuClosedHistoryMarker", "frameIdAfterMenuClosedHistoryMarker"],
    ["frameIdAtHistoryNavigatedMarker", "frameIdAfterHistoryNavigatedMarker"],
    ["frameIdAtMenuOpenDownloadsMarker", "frameIdAfterMenuOpenDownloadsMarker"],
    ["frameIdAtMenuClosedDownloadsMarker",
      "frameIdAfterMenuClosedDownloadsMarker"],
    ["frameIdAtDownloadsNavigatedMarker",
      "frameIdAfterDownloadsNavigatedMarker"],
  ]) {
    require(orderedFrame(proof, before, after),
        "History/Downloads lacks ordered frame " + after);
  }
  const input = result.hostInput;
  require(input?.singleAdapterRetained === true,
      "History/Downloads did not retain one adapter");
  require(input?.proxyTextEmpty === true,
      "History/Downloads proxy retained DOM text");
  for (const field of [
    "newTabCheckQueued", "historyMenuOpenCheckQueued",
    "historyMenuClosedCheckQueued", "downloadsMenuOpenCheckQueued",
    "downloadsMenuClosedCheckQueued", "finalPresentationQueued",
  ]) {
    require(input?.[field] === true, "History/Downloads input " + field);
  }
  require(Array.isArray(input?.textTransactions) &&
      input.textTransactions.length === 2 &&
      validTransaction(input.textTransactions[0], "first") &&
      validTransaction(input.textTransactions[1], "second"),
  "History/Downloads text transactions are invalid");
  const targetFields = [
    ["newTabTarget", "newTabActionOffset"],
    ["firstMenuTarget", "firstMenuActionOffset"],
    ["historyTarget", "historyActionOffset"],
    ["secondMenuTarget", "secondMenuActionOffset"],
    ["downloadsTarget", "downloadsActionOffset"],
  ];
  for (const [field, offset] of targetFields) {
    const target = input?.[field];
    require(target && Number.isSafeInteger(target.x) &&
        Number.isSafeInteger(target.y) && Number.isFinite(target.clientX) &&
        Number.isFinite(target.clientY),
    "History/Downloads target " + field + " is invalid");
    require(acceptedPointerPair(
        input?.pointerRecords, target, input?.[offset]),
    "History/Downloads pointer target " + field + " is invalid");
  }
  require(Array.isArray(input?.pointerRecords) &&
      input.pointerRecords.filter((record) =>
        record?.type === "down" || record?.type === "up").length === 10,
  "History/Downloads does not have five trusted pointer clicks");
  const serialized = JSON.stringify(result);
  require(!serialized.includes(FIRST_ADDRESS_TEXT) &&
      !serialized.includes(SECOND_ADDRESS_TEXT),
  "History/Downloads result retains raw typed browser text");
  result.failedChecks = failures;
  if (failures.length) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

function resultForDisplay(result) {
  return {
    ...result,
    stdout: result.stdout.map(redactDiagnostic),
    stderr: result.stderr.map(redactDiagnostic),
  };
}

export async function runChromeWasmBrowserHostHistoryDownloadsSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "120000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-history-downloads-root");
  const canvas = document.querySelector("#browser-canvas");
  const proxy = document.querySelector("#browser-text-proxy");
  const status = document.querySelector("#browser-history-downloads-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(proxy instanceof HTMLTextAreaElement) || !(status instanceof HTMLElement)) {
    throw new Error("History/Downloads page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserHostHistoryDownloadsSmokeHost(
      canvas, proxy, versions);
  const basePath = location.pathname.replace(/\/$/, "");
  const result = validateResult(await host.run(
      basePath + "/artifacts/" + moduleName + ".js", timeoutMs,
      query.get("wispEndpoint"), query.get("fixtureUrl")));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(resultForDisplay(result), null, 2);
  const response = await fetch(
      basePath + "/result/" + encodeURIComponent(token),
      {
        method: "POST",
        cache: "no-store",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error("History/Downloads result upload returned HTTP " +
        response.status);
  }
  return result;
}

export const chromeWasmBrowserHostHistoryDownloadsSmokeContract = Object.freeze({
  CASE,
  CONTROLLED_ROOT_URL,
  FIRST_ADDRESS_TEXT,
  HOST_PROTOCOL,
  READY_MARKER,
  SCOPE,
  SECOND_ADDRESS_TEXT,
  SWITCH,
  URL_SWITCH,
  WISP_CONFIGURATION_VERSION,
});

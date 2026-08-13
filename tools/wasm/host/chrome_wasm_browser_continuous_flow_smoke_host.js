// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Formal Target-6 acceptance-flow host. It keeps one Chrome Browser alive for
// the complete first phase, and supplies only ordinary trusted DOM keyboard,
// text, and pointer records to the existing Ozone adapters. The fixed C++
// ordinal exports below are evidence checks, never browser commands.

import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";
import {ChromiumWasmTrustedTextInput} from "./chrome_wasm_text_input.js";

const HOST_PROTOCOL = 1;
const CASE = "browser_continuous_flow_target6_m6";
const SCOPE = "formal-target-6-trusted-dom-one-browser-lifetime";
const FLOW_PHASE = "flow";
const RESTART_PHASE = "restart";
const FLOW_SWITCH = "--wasm-browser-host-continuous-flow-smoke";
const RESTART_SWITCH = "--wasm-browser-host-continuous-flow-restart-smoke";
const URL_SWITCH = "--wasm-browser-controlled-https-url";
const HTTPS_TEXT = "https://a.test/m5/m6-ui";
const VERSION_TEXT = "chrome://version/";
const MAX_TIMEOUT_MS = 180000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 128;
const PNG_DATA_URL_PREFIX = "data:image/png;base64,";
const MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024;
const MAX_SCREENSHOT_BASE64_LENGTH = Math.ceil(MAX_SCREENSHOT_BYTES / 3) * 4;
const MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024;
const BASE64_PATTERN = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
const ARTIFACT_SOURCE_PROVENANCE = "unverified";
const ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot";

const MARKERS = Object.freeze({
  ready: "CHROMIUM_WASM_M6_CONTINUOUS:READY",
  httpsNavigated: "CHROMIUM_WASM_M6_CONTINUOUS:HTTPS_NAVIGATED",
  versionReady: "CHROMIUM_WASM_M6_CONTINUOUS:VERSION_READY",
  versionNavigated: "CHROMIUM_WASM_M6_CONTINUOUS:VERSION_NAVIGATED",
  firstTabSelected: "CHROMIUM_WASM_M6_CONTINUOUS:FIRST_TAB_SELECTED",
  menuReady: "CHROMIUM_WASM_M6_CONTINUOUS:MENU_READY",
  menuOpened: "CHROMIUM_WASM_M6_CONTINUOUS:MENU_OPENED",
  settingsNavigated: "CHROMIUM_WASM_M6_CONTINUOUS:SETTINGS_NAVIGATED",
  firstTabReturned: "CHROMIUM_WASM_M6_CONTINUOUS:FIRST_TAB_RETURNED",
  secondTabClosed: "CHROMIUM_WASM_M6_CONTINUOUS:SECOND_TAB_CLOSED",
  reloadReady: "CHROMIUM_WASM_M6_CONTINUOUS:RELOAD_READY",
  reloaded: "CHROMIUM_WASM_M6_CONTINUOUS:RELOADED",
  pass: "CHROMIUM_WASM_M6_CONTINUOUS:PASS",
  timeout: "CHROMIUM_WASM_M6_CONTINUOUS:TIMEOUT",
  restartReady: "CHROMIUM_WASM_M6_CONTINUOUS:RESTART_READY",
  restartClosing: "CHROMIUM_WASM_M6_CONTINUOUS:RESTART_CLOSING",
});

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function appendBounded(records, value) {
  records.push(value);
  if (records.length > MAX_RECORD_HISTORY) {
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
    report = JSON.parse(report);
  }
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    throw new Error(description + " must be an object");
  }
  return report;
}

function parseVersions(value) {
  const parsed = JSON.parse(value);
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], "version " + field);
  }
  return Object.freeze(versions);
}

function parseQueryJson(value, description) {
  try {
    return JSON.parse(asNonemptyString(value, description));
  } catch (error) {
    throw new Error(`invalid ${description}: ${String(error)}`);
  }
}

function requireExactFields(value, fields, description) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== fields.length ||
      !fields.every((field) => Object.hasOwn(value, field))) {
    throw new Error(`${description} has an invalid schema`);
  }
  return value;
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, ["bytes", "sha256"], description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      identity.bytes > MAX_ARTIFACT_BYTES ||
      typeof identity.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifactIdentity(value) {
  const artifact = requireExactFields(
      parseQueryJson(value, "continuous-flow artifact identity"),
      ["artifact_delivery", "artifact_source_provenance", "loader",
        "module_name", "wasm"], "continuous-flow artifact identity");
  if (artifact.artifact_delivery !== ARTIFACT_DELIVERY ||
      artifact.artifact_source_provenance !== ARTIFACT_SOURCE_PROVENANCE ||
      typeof artifact.module_name !== "string" ||
      !/^[A-Za-z0-9_]+$/.test(artifact.module_name)) {
    throw new Error("continuous-flow artifact identity has invalid provenance");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    loader: parseByteIdentity(artifact.loader, "continuous-flow loader identity"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "continuous-flow Wasm identity"),
  });
}

async function sha256Hex(bytes, description) {
  if (!(bytes instanceof Uint8Array)) {
    throw new Error(`${description} bytes are invalid`);
  }
  const subtle = globalThis.crypto?.subtle;
  if (!subtle || typeof subtle.digest !== "function") {
    throw new Error(`${description} requires WebCrypto SHA-256`);
  }
  let digest;
  try {
    digest = await subtle.digest("SHA-256", bytes);
  } catch (error) {
    throw new Error(`${description} SHA-256 failed: ${String(error)}`);
  }
  if (!(digest instanceof ArrayBuffer)) {
    throw new Error(`${description} SHA-256 returned an invalid digest`);
  }
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0")).join("");
}

export async function fetchVerifiedArtifact(url, identity, description) {
  const response = await fetch(url, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`${description} request returned HTTP ${response.status}`);
  }
  let buffer;
  try {
    buffer = await response.arrayBuffer();
  } catch (error) {
    throw new Error(`${description} response bytes failed: ${String(error)}`);
  }
  if (!(buffer instanceof ArrayBuffer)) {
    throw new Error(`${description} response bytes are invalid`);
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== identity.bytes) {
    throw new Error(`${description} byte length disagrees with artifact identity`);
  }
  if (await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} SHA-256 disagrees with artifact identity`);
  }
  return bytes;
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("continuous-flow host has no versions element");
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

function parseFixtureUrl(value) {
  const text = asNonemptyString(value, "controlled HTTPS fixture URL");
  const url = new URL(text);
  if (url.href !== HTTPS_TEXT || url.protocol !== "https:" ||
      url.hostname !== "a.test" || url.pathname !== "/m5/m6-ui" ||
      url.search || url.hash || url.username || url.password || url.port) {
    throw new Error("controlled HTTPS fixture URL violates fixed policy");
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
  const endpoint = new URL(asNonemptyString(value, "WISP endpoint"));
  const port = Number(endpoint.port);
  if ((endpoint.protocol !== "ws:" && endpoint.protocol !== "wss:") ||
      !isLoopbackHostname(endpoint.hostname) || endpoint.username ||
      endpoint.password || endpoint.search || endpoint.hash ||
      endpoint.pathname !== "/wisp/" || endpoint.port === "" ||
      !Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("WISP endpoint violates fixed transport policy");
  }
  return Object.freeze({version: 1, endpoint: endpoint.href, subprotocol: "wisp"});
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

function decodePngDataUrl(dataUrl) {
  if (typeof dataUrl !== "string" || !dataUrl.startsWith(PNG_DATA_URL_PREFIX)) {
    throw new Error("canvas did not produce a PNG data URL");
  }
  const dataBase64 = dataUrl.slice(PNG_DATA_URL_PREFIX.length);
  if (!dataBase64 || dataBase64.length > MAX_SCREENSHOT_BASE64_LENGTH ||
      !BASE64_PATTERN.test(dataBase64)) {
    throw new Error("canvas PNG data is out of bounds");
  }
  const binary = atob(dataBase64);
  if (binary.length < 8 || binary.length > MAX_SCREENSHOT_BYTES ||
      binary.charCodeAt(0) !== 0x89 || binary.charCodeAt(1) !== 0x50 ||
      binary.charCodeAt(2) !== 0x4e || binary.charCodeAt(3) !== 0x47 ||
      binary.charCodeAt(4) !== 0x0d || binary.charCodeAt(5) !== 0x0a ||
      binary.charCodeAt(6) !== 0x1a || binary.charCodeAt(7) !== 0x0a) {
    throw new Error("canvas PNG data is invalid");
  }
  return dataBase64;
}

function parseTargetMarker(line, marker) {
  const match = new RegExp(marker + " x=(\\d+) y=(\\d+)").exec(line);
  if (!match) {
    return null;
  }
  const x = Number(match[1]);
  const y = Number(match[2]);
  if (!Number.isSafeInteger(x) || !Number.isSafeInteger(y) || x < 0 || y < 0 ||
      x >= MAX_FRAME_DIMENSION || y >= MAX_FRAME_DIMENSION) {
    throw new Error("native target marker is invalid");
  }
  return {x, y};
}

function redactDiagnostic(value) {
  return String(value).replaceAll(HTTPS_TEXT, "<redacted-url>")
      .replaceAll(VERSION_TEXT, "<redacted-url>")
      .replace(/(?:https?|chrome):\/\/[^\s"'<>]+/g, "<redacted-url>")
      .slice(0, 1024);
}

function snapshotMetadata(snapshot) {
  const {textareaValue, ...metadata} = snapshot;
  return metadata;
}

// A post-marker frame is not enough: reportControlledHttpsTargetFvp can be
// delivered after an already-presented retained frame. The target-FVP import
// snapshots its own frame boundary, and only a strictly later presentation is
// eligible for the next host ordinal or final screenshot.
export function isStrictPostTargetFvpFrameForTesting(
    markerFrameId, targetFvpFrameId, candidateFrameId) {
  return Number.isSafeInteger(markerFrameId) && Number.isSafeInteger(targetFvpFrameId) &&
      Number.isSafeInteger(candidateFrameId) && candidateFrameId > markerFrameId &&
      candidateFrameId > targetFvpFrameId;
}

class ChromiumWasmBrowserContinuousFlowHost {
  #canvas;
  #proxy;
  #versions;
  #phase;
  #artifact;
  #module = null;
  #pointerInput = null;
  #textInput = null;
  #activeText = null;
  #completedText = [];
  #textAdapterInstances = 0;
  #textDetachedAfterSecondSequence = false;
  #reloadTextSnapshot = null;
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
  #observationSequence = 0;
  #verifierGeneration = 1;
  #reloadInputAttached = false;
  #reloadHeldCodes = [];
  #onReloadKeyDown = null;
  #onReloadKeyUp = null;
  #onReloadCanvasBlur = null;
  #onReloadWindowBlur = null;
  #onReloadVisibilityChange = null;
  #proof = {
    wispConfigured: false,
    runtimeArgumentsConfigured: false,
    configurationPrecededFactory: false,
    readyObserved: false,
    httpsNavigatedObserved: false,
    versionReadyObserved: false,
    versionNavigatedObserved: false,
    firstTabSelectedObserved: false,
    menuReadyObserved: false,
    menuOpenedObserved: false,
    settingsNavigatedObserved: false,
    firstTabReturnedObserved: false,
    secondTabClosedObserved: false,
    reloadReadyObserved: false,
    reloadedObserved: false,
    passObserved: false,
    timeoutObserved: false,
    restartReadyObserved: false,
    restartClosingObserved: false,
    firstFvpObserved: false,
    secondFvpObserved: false,
    firstFvpObservationSequence: null,
    secondFvpObservationSequence: null,
    httpsNavigatedObservationSequence: null,
    reloadedObservationSequence: null,
    newTabTarget: null,
    switchFirstTarget: null,
    switchSecondTarget: null,
    menuTarget: null,
    settingsTarget: null,
    returnFirstTarget: null,
    closeSecondTarget: null,
    frameAtHttpsNavigated: null,
    frameAfterHttpsNavigated: null,
    frameAtVersionReady: null,
    frameAfterVersionReady: null,
    frameAtVersionNavigated: null,
    frameAfterVersionNavigated: null,
    frameAtFirstTabSelected: null,
    frameAfterFirstTabSelected: null,
    frameAtMenuReady: null,
    frameAfterMenuReady: null,
    frameAtMenuOpened: null,
    frameAfterMenuOpened: null,
    frameAtSettingsNavigated: null,
    frameAfterSettingsNavigated: null,
    frameAtFirstTabReturned: null,
    frameAfterFirstTabReturned: null,
    frameAtReloadReady: null,
    frameAfterReloadReady: null,
    frameAtReloaded: null,
    frameAfterReloaded: null,
    frameAtFirstFvp: null,
    frameAfterFirstFvp: null,
    frameAtSecondFvp: null,
    frameAfterSecondFvp: null,
    frameAtRestartReady: null,
    frameAfterRestartReady: null,
    newTabActionOffset: null,
    switchFirstActionOffset: null,
    switchSecondActionOffset: null,
    menuActionOffset: null,
    settingsActionOffset: null,
    returnFirstActionOffset: null,
    closeSecondActionOffset: null,
    check1Queued: false,
    check2Queued: false,
    check3Queued: false,
    check4Queued: false,
    check5Queued: false,
    check6Queued: false,
    finalPresentationQueued: false,
    restartPresentationQueued: false,
    pointerRecords: [],
    ctrlRRecords: [],
    reloadRejectedRecords: [],
    reloadCleanupRecords: [],
    screenshot: null,
  };

  constructor(canvas, proxy, versions, phase, artifact) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(proxy instanceof HTMLTextAreaElement)) {
      throw new Error("continuous-flow host requires a canvas and textarea");
    }
    this.#canvas = canvas;
    this.#proxy = proxy;
    this.#versions = versions;
    this.#phase = phase;
    this.#artifact = artifact;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
    this.#publishState();
  }

  #recordFatal(value) {
    appendBounded(this.#fatalErrors, redactDiagnostic(value));
    ++this.#verifierGeneration;
    this.#publishState();
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

  #setTarget(field, offsetField, point) {
    const target = this.#targetForClientPoint(point);
    if (!target) {
      throw new Error("native target cannot map into the visible canvas");
    }
    this.#proof[field] = target;
    this.#proof[offsetField] = this.#actionRecords().length;
  }

  #recordMarker(frameField, observationField = null) {
    this.#proof[frameField] = this.#currentFrameId();
    if (observationField) {
      this.#proof[observationField] = ++this.#observationSequence;
    }
  }

  #setFreshFrame(beforeField, afterField) {
    if (this.#proof[afterField] !== null || this.#proof[beforeField] === null) {
      return;
    }
    const frame = this.#firstFrameAfter(this.#proof[beforeField]);
    if (frame) {
      this.#proof[afterField] = frame.id;
    }
  }

  #updatePostMarkerFrames() {
    for (const [before, after] of [
      ["frameAtHttpsNavigated", "frameAfterHttpsNavigated"],
      ["frameAtVersionReady", "frameAfterVersionReady"],
      ["frameAtVersionNavigated", "frameAfterVersionNavigated"],
      ["frameAtFirstTabSelected", "frameAfterFirstTabSelected"],
      ["frameAtMenuReady", "frameAfterMenuReady"],
      ["frameAtMenuOpened", "frameAfterMenuOpened"],
      ["frameAtSettingsNavigated", "frameAfterSettingsNavigated"],
      ["frameAtFirstTabReturned", "frameAfterFirstTabReturned"],
      ["frameAtReloadReady", "frameAfterReloadReady"],
      ["frameAtReloaded", "frameAfterReloaded"],
      ["frameAtFirstFvp", "frameAfterFirstFvp"],
      ["frameAtSecondFvp", "frameAfterSecondFvp"],
      ["frameAtRestartReady", "frameAfterRestartReady"],
    ]) {
      this.#setFreshFrame(before, after);
    }
  }

  #acceptedPointerPair(target, offset) {
    if (!target || !Number.isSafeInteger(offset)) {
      return false;
    }
    const [down, up] = this.#actionRecords().slice(offset, offset + 2);
    const exact = (record) => record && record.trusted === true &&
        record.cancelable === true && record.pointerType === "mouse" &&
        record.primary === true && record.accepted === true &&
        record.defaultPrevented === true && record.reason === null &&
        record.x === target.x && record.y === target.y;
    return exact(down) && exact(up) && down.type === "down" &&
        down.button === 0 && down.buttons === 1 && up.type === "up" &&
        up.button === 0 && up.buttons === 0;
  }

  #recordOutput(value) {
    const line = String(value);
    try {
      if (line.includes(MARKERS.timeout)) {
        this.#proof.timeoutObserved = true;
        throw new Error("native Target-6 flow timed out");
      }
      if (this.#phase === RESTART_PHASE) {
        this.#recordRestartOutput(line);
      } else {
        this.#recordFlowOutput(line);
      }
      this.#advance();
    } catch (error) {
      this.#recordFatal("invalid continuous-flow output: " + String(error));
    }
  }

  #recordRestartOutput(line) {
    if (line.includes(MARKERS.restartReady)) {
      if (this.#proof.restartReadyObserved || this.#proof.restartClosingObserved) {
        throw new Error("RESTART_READY marker is out of order");
      }
      this.#proof.restartReadyObserved = true;
      this.#recordMarker("frameAtRestartReady");
    }
    if (line.includes(MARKERS.restartClosing)) {
      if (!this.#proof.restartReadyObserved ||
          !this.#proof.restartPresentationQueued ||
          this.#proof.restartClosingObserved) {
        throw new Error("RESTART_CLOSING marker is out of order");
      }
      this.#proof.restartClosingObserved = true;
    }
  }

  #recordFlowOutput(line) {
    if (line.includes(MARKERS.ready)) {
      if (this.#proof.readyObserved || this.#proof.httpsNavigatedObserved) {
        throw new Error("READY marker is out of order");
      }
      this.#proof.readyObserved = true;
    }
    const httpsTarget = parseTargetMarker(line, MARKERS.httpsNavigated);
    if (httpsTarget) {
      if (!this.#proof.readyObserved || this.#proof.httpsNavigatedObserved ||
          this.#proof.versionReadyObserved) {
        throw new Error("HTTPS_NAVIGATED marker is out of order");
      }
      this.#proof.httpsNavigatedObserved = true;
      this.#recordMarker(
          "frameAtHttpsNavigated", "httpsNavigatedObservationSequence");
      this.#setTarget("newTabTarget", "newTabActionOffset", httpsTarget);
    }
    if (line.includes(MARKERS.versionReady)) {
      if (!this.#proof.check1Queued || !this.#proof.httpsNavigatedObserved ||
          this.#proof.versionReadyObserved) {
        throw new Error("VERSION_READY marker is out of order");
      }
      this.#proof.versionReadyObserved = true;
      this.#recordMarker("frameAtVersionReady");
    }
    const versionTarget = parseTargetMarker(line, MARKERS.versionNavigated);
    if (versionTarget) {
      if (!this.#proof.versionReadyObserved ||
          this.#proof.versionNavigatedObserved) {
        throw new Error("VERSION_NAVIGATED marker is out of order");
      }
      this.#proof.versionNavigatedObserved = true;
      this.#recordMarker("frameAtVersionNavigated");
      this.#setTarget("switchFirstTarget", "switchFirstActionOffset", versionTarget);
    }
    const firstTabTarget = parseTargetMarker(line, MARKERS.firstTabSelected);
    if (firstTabTarget) {
      if (!this.#proof.check2Queued || !this.#proof.versionNavigatedObserved ||
          this.#proof.firstTabSelectedObserved) {
        throw new Error("FIRST_TAB_SELECTED marker is out of order");
      }
      this.#proof.firstTabSelectedObserved = true;
      this.#recordMarker("frameAtFirstTabSelected");
      this.#setTarget("switchSecondTarget", "switchSecondActionOffset", firstTabTarget);
    }
    const menuTarget = parseTargetMarker(line, MARKERS.menuReady);
    if (menuTarget) {
      if (!this.#proof.check3Queued || !this.#proof.firstTabSelectedObserved ||
          this.#proof.menuReadyObserved) {
        throw new Error("MENU_READY marker is out of order");
      }
      this.#proof.menuReadyObserved = true;
      this.#recordMarker("frameAtMenuReady");
      this.#setTarget("menuTarget", "menuActionOffset", menuTarget);
    }
    const settingsTarget = parseTargetMarker(line, MARKERS.menuOpened);
    if (settingsTarget) {
      if (!this.#proof.check4Queued || !this.#proof.menuReadyObserved ||
          this.#proof.menuOpenedObserved) {
        throw new Error("MENU_OPENED marker is out of order");
      }
      this.#proof.menuOpenedObserved = true;
      this.#recordMarker("frameAtMenuOpened");
      this.#setTarget("settingsTarget", "settingsActionOffset", settingsTarget);
    }
    const returnFirstTarget = parseTargetMarker(line, MARKERS.settingsNavigated);
    if (returnFirstTarget) {
      if (!this.#proof.menuOpenedObserved ||
          this.#proof.settingsNavigatedObserved) {
        throw new Error("SETTINGS_NAVIGATED marker is out of order");
      }
      this.#proof.settingsNavigatedObserved = true;
      this.#recordMarker("frameAtSettingsNavigated");
      this.#setTarget(
          "returnFirstTarget", "returnFirstActionOffset", returnFirstTarget);
    }
    const closeSecondTarget = parseTargetMarker(line, MARKERS.firstTabReturned);
    if (closeSecondTarget) {
      if (!this.#proof.check5Queued ||
          !this.#proof.settingsNavigatedObserved ||
          this.#proof.firstTabReturnedObserved) {
        throw new Error("FIRST_TAB_RETURNED marker is out of order");
      }
      this.#proof.firstTabReturnedObserved = true;
      this.#recordMarker("frameAtFirstTabReturned");
      this.#setTarget(
          "closeSecondTarget", "closeSecondActionOffset", closeSecondTarget);
    }
    if (line.includes(MARKERS.secondTabClosed)) {
      if (!this.#proof.check6Queued || !this.#proof.firstTabReturnedObserved ||
          this.#proof.secondTabClosedObserved) {
        throw new Error("SECOND_TAB_CLOSED marker is out of order");
      }
      this.#proof.secondTabClosedObserved = true;
    }
    if (line.includes(MARKERS.reloadReady)) {
      if (!this.#proof.secondTabClosedObserved || this.#proof.reloadReadyObserved) {
        throw new Error("RELOAD_READY marker is out of order");
      }
      this.#proof.reloadReadyObserved = true;
      this.#recordMarker("frameAtReloadReady");
    }
    if (line.includes(MARKERS.reloaded)) {
      if (!this.#proof.reloadReadyObserved || this.#proof.ctrlRRecords.length !== 4 ||
          this.#proof.reloadedObserved) {
        throw new Error("RELOADED marker is out of order");
      }
      this.#proof.reloadedObserved = true;
      this.#recordMarker("frameAtReloaded", "reloadedObservationSequence");
    }
    if (line.includes(MARKERS.pass)) {
      if (!this.#proof.finalPresentationQueued || !this.#proof.reloadedObserved ||
          !this.#proof.secondFvpObserved || !this.#proof.screenshot ||
          this.#proof.passObserved) {
        throw new Error("PASS marker is out of order");
      }
      this.#proof.passObserved = true;
    }
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL || !isFrameReport(report) ||
          this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
        throw new Error("frame report does not match the canvas");
      }
      const previous = this.#frameReports.at(-1);
      if (previous && report.id <= previous.id) {
        throw new Error("frame IDs are not monotonic");
      }
      appendBounded(this.#frameReports, {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      });
      ++this.#observationSequence;
      this.#updatePostMarkerFrames();
      // This import can execute on a proxied Wasm/UI stack. #advance only
      // queues the fixed ordinal callback through setTimeout; it never
      // re-enters a verifier C ABI from reportFrame.
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

  #reportTargetFvp(value) {
    try {
      const report = asReport(value, "controlled target FVP report");
      if (report.protocol !== HOST_PROTOCOL || Object.keys(report).length !== 2 ||
          !Number.isSafeInteger(report.phase) ||
          (report.phase !== 1 && report.phase !== 2)) {
        throw new Error("target FVP report is invalid");
      }
      const observationSequence = ++this.#observationSequence;
      if (report.phase === 1) {
        if (!this.#proof.httpsNavigatedObserved || this.#proof.firstFvpObserved ||
            this.#proof.reloadedObserved ||
            observationSequence <= this.#proof.httpsNavigatedObservationSequence) {
          throw new Error("phase-1 target FVP is out of order");
        }
        this.#proof.firstFvpObserved = true;
        this.#proof.firstFvpObservationSequence = observationSequence;
        this.#proof.frameAtFirstFvp = this.#currentFrameId();
      } else {
        if (!this.#proof.reloadedObserved || this.#proof.secondFvpObserved ||
            observationSequence <= this.#proof.reloadedObservationSequence) {
          throw new Error("phase-2 target FVP is out of order");
        }
        this.#proof.secondFvpObserved = true;
        this.#proof.secondFvpObservationSequence = observationSequence;
        this.#proof.frameAtSecondFvp = this.#currentFrameId();
      }
      this.#advance();
      return true;
    } catch (error) {
      this.#recordFatal("invalid controlled target FVP: " + String(error));
      return false;
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
      if (report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.action) ||
          !Number.isSafeInteger(report.sessionId) ||
          !Number.isSafeInteger(report.sequence) ||
          typeof report.accepted !== "boolean") {
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
      this.#recordFatal("browser text delivery arrived before text adapter");
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
      const cursor = report.cursorType === 2 ? "pointer" :
        report.cursorType === 3 ? "text" : "default";
      this.#canvas.style.cursor = cursor;
      appendBounded(this.#cursorReports, {cursorType: report.cursorType, cursor});
      return true;
    } catch (error) {
      this.#recordFatal("invalid Ozone cursor report: " + String(error));
      return false;
    }
  }

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code) || this.#runtimeExitCode !== null) {
      this.#recordFatal("runtime exit report is invalid");
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process exit report");
      if (!Number.isSafeInteger(report.exitCode) || this.#processExitCode !== null) {
        throw new Error("process exit report is invalid");
      }
      this.#processExitCode = report.exitCode;
    } catch (error) {
      this.#recordFatal("invalid process exit report: " + String(error));
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("continuous-flow host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportControlledHttpsTargetFvp(report) { return host.#reportTargetFvp(report); },
      reportOzoneFocusState(report) { host.#reportFocus(report); },
      reportOzoneTextInputState(report) { host.#reportTextInputState(report); },
      reportOzoneTextInputDelivery(report) { host.#reportTextInputDelivery(report); },
      reportOzoneBrowserTextInputDelivery(report) {
        host.#reportBrowserTextDelivery(report);
      },
      reportOzoneCursor(report) { return host.#reportCursor(report); },
    });
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = redactDiagnostic(event.error || event.message || "window error");
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
    return this.#textInput?.snapshot() || this.#reloadTextSnapshot || {
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
    return this.#completedText.find((transaction) => transaction.phase === phase) ||
        null;
  }

  #beginTextTransaction(phase) {
    if (this.#activeText || this.#completedTransaction(phase) || !this.#textInput) {
      return;
    }
    const snapshot = this.#textSnapshot();
    this.#activeText = {
      phase,
      adapterId: 1,
      expectedText: phase === "https" ? HTTPS_TEXT : VERSION_TEXT,
      expectedSequence: phase === "https" ? 1 : 2,
      starts: {
        ctrlL: snapshot.ctrlLRecords.length,
        beforeInput: snapshot.beforeInputRecords.length,
        delivery: snapshot.browserTextDeliveryReports.length,
        enter: snapshot.enterRecords.length,
        rejected: snapshot.rejectedRecords.length,
        cleanup: snapshot.cleanupRecords.length,
      },
      ctrlLComplete: false,
      proxyFocused: false,
      admissionCount: 0,
      deliveryCount: 0,
      deliverySequences: [],
      deliveryAccepted: false,
      enterComplete: false,
      rejected: false,
    };
  }

  #transactionMetadata(transaction, snapshot) {
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
    this.#completedText.push({
      phase: transaction.phase,
      adapterId: transaction.adapterId,
      expectedSequence: transaction.expectedSequence,
      ctrlLComplete: transaction.ctrlLComplete,
      proxyFocused: transaction.proxyFocused,
      admissionCount: transaction.admissionCount,
      deliveryCount: transaction.deliveryCount,
      deliverySequences: [...transaction.deliverySequences],
      deliveryAccepted: transaction.deliveryAccepted,
      enterComplete: transaction.enterComplete,
      rejected: transaction.rejected,
      adapter: this.#transactionMetadata(transaction, snapshot),
    });
    this.#activeText = null;
  }

  #recordTextAdmission(record) {
    const transaction = this.#activeText;
    if (!transaction || record.sequence !== transaction.expectedSequence ||
        record.dataUtf8Bytes !== new TextEncoder().encode(transaction.expectedText).byteLength ||
        record.queued !== true || record.nativeDispatched !== true) {
      this.#recordFatal("trusted text admission does not match its transaction");
      return;
    }
    ++transaction.admissionCount;
    this.#advance();
  }

  #recordTextDelivery(report) {
    const transaction = this.#activeText;
    if (!transaction || report.action !== 4 || report.sessionId !== 0 ||
        report.sequence !== transaction.expectedSequence || report.accepted !== true ||
        report.text !== transaction.expectedText) {
      this.#recordFatal("trusted action-4 delivery does not match its transaction");
      return;
    }
    ++transaction.deliveryCount;
    transaction.deliverySequences.push(report.sequence);
    transaction.deliveryAccepted = true;
    // This is a synchronous UI-to-JS import. It records only local evidence;
    // the verifier exports remain deferred through #queueVerifier.
    this.#advance();
  }

  #recordTextRejected() {
    if (this.#activeText) {
      this.#activeText.rejected = true;
    }
    this.#recordFatal("trusted action-4 delivery was rejected");
  }

  #recordCtrlLComplete() {
    if (!this.#activeText) {
      this.#recordFatal("Ctrl+L has no active text transaction");
      return;
    }
    this.#activeText.ctrlLComplete = true;
    this.#advance();
  }

  #recordProxyFocused() {
    if (!this.#activeText) {
      this.#recordFatal("textarea focus has no active text transaction");
      return;
    }
    this.#activeText.proxyFocused = true;
    this.#advance();
  }

  #recordEnterComplete() {
    if (!this.#activeText) {
      this.#recordFatal("Enter has no active text transaction");
      return;
    }
    this.#activeText.enterComplete = true;
    this.#finishTextTransaction();
    this.#advance();
  }

  #canAcceptBeforeInput(event) {
    const transaction = this.#activeText;
    return !!transaction && transaction.ctrlLComplete && !transaction.rejected &&
        transaction.admissionCount === 0 && event.data === transaction.expectedText;
  }

  #canSubmitTextEnter() {
    const transaction = this.#activeText;
    const snapshot = this.#textSnapshot();
    return !!transaction && transaction.ctrlLComplete && transaction.proxyFocused &&
        transaction.admissionCount === 1 && transaction.deliveryCount === 1 &&
        transaction.deliveryAccepted && !transaction.rejected &&
        snapshot.pendingDeliveryCount === 0 && !snapshot.deliveryRejected;
  }

  #recordPointer(record) {
    appendBounded(this.#proof.pointerRecords, record);
    this.#advance();
  }

  #canQueueCheck(stage) {
    if (this.#phase !== FLOW_PHASE || this.#fatalErrors.length !== 0) {
      return false;
    }
    switch (stage) {
      case 1:
        return this.#proof.httpsNavigatedObserved && this.#proof.firstFvpObserved &&
            this.#proof.frameAfterHttpsNavigated !== null &&
            this.#proof.frameAfterFirstFvp !== null &&
            isStrictPostTargetFvpFrameForTesting(
                this.#proof.frameAtHttpsNavigated, this.#proof.frameAtFirstFvp,
                this.#proof.frameAfterFirstFvp) &&
            this.#acceptedPointerPair(
                this.#proof.newTabTarget, this.#proof.newTabActionOffset);
      case 2:
        return this.#proof.versionNavigatedObserved &&
            this.#proof.frameAfterVersionNavigated !== null &&
            this.#acceptedPointerPair(
                this.#proof.switchFirstTarget, this.#proof.switchFirstActionOffset);
      case 3:
        return this.#proof.firstTabSelectedObserved &&
            this.#proof.frameAfterFirstTabSelected !== null &&
            this.#acceptedPointerPair(
                this.#proof.switchSecondTarget, this.#proof.switchSecondActionOffset);
      case 4:
        return this.#proof.menuReadyObserved && this.#proof.frameAfterMenuReady !== null &&
            this.#acceptedPointerPair(this.#proof.menuTarget, this.#proof.menuActionOffset);
      case 5:
        return this.#proof.settingsNavigatedObserved &&
            this.#proof.frameAfterSettingsNavigated !== null &&
            this.#acceptedPointerPair(
                this.#proof.returnFirstTarget, this.#proof.returnFirstActionOffset);
      case 6:
        return this.#proof.firstTabReturnedObserved &&
            this.#proof.frameAfterFirstTabReturned !== null &&
            this.#acceptedPointerPair(
                this.#proof.closeSecondTarget, this.#proof.closeSecondActionOffset);
      default:
        return false;
    }
  }

  #canQueuePresentation(stage) {
    if (this.#fatalErrors.length !== 0) {
      return false;
    }
    if (this.#phase === RESTART_PHASE) {
      return stage === 1 && this.#proof.restartReadyObserved &&
          this.#proof.frameAfterRestartReady !== null &&
          !this.#proof.restartClosingObserved;
    }
    return stage === 7 && this.#proof.reloadedObserved &&
        this.#proof.secondFvpObserved && this.#proof.frameAfterReloaded !== null &&
        this.#proof.frameAfterSecondFvp !== null && this.#proof.screenshot !== null &&
        isStrictPostTargetFvpFrameForTesting(
            this.#proof.frameAtReloaded, this.#proof.frameAtSecondFvp,
            this.#proof.frameAfterSecondFvp) &&
        this.#proof.ctrlRRecords.length === 4;
  }

  #queueVerifier(exportName, stage, queuedField, canRun) {
    if (this.#proof[queuedField]) {
      return;
    }
    this.#proof[queuedField] = true;
    const generation = this.#verifierGeneration;
    this.#publishState();
    setTimeout(() => {
      // Recheck generation plus the exact ordinal evidence after the JS import
      // stack has unwound. A stale reportFrame/pointer callback cannot turn
      // this narrow verifier ABI into a generic browser command surface.
      if (generation !== this.#verifierGeneration || !canRun()) {
        this.#recordFatal(exportName + " lost its deferred ordinal evidence");
        return;
      }
      if (!this.#module || typeof this.#module.ccall !== "function") {
        this.#recordFatal(exportName + " ran without Module.ccall");
        return;
      }
      try {
        const result = this.#module.ccall(exportName, "number", ["number"], [stage]);
        if (result !== 1) {
          this.#recordFatal(exportName + " rejected ordinal " + stage);
        }
      } catch (error) {
        this.#recordFatal(exportName + " failed: " + String(error));
      }
      this.#advance();
    }, 0);
  }

  #captureFinalScreenshot() {
    if (this.#proof.screenshot || !this.#proof.reloadedObserved ||
        !this.#proof.secondFvpObserved ||
        this.#proof.frameAfterSecondFvp === null ||
        !isStrictPostTargetFvpFrameForTesting(
            this.#proof.frameAtReloaded, this.#proof.frameAtSecondFvp,
            this.#proof.frameAfterSecondFvp)) {
      return;
    }
    const frame = this.#frameReports.find(
        (entry) => entry.id === this.#proof.frameAfterSecondFvp);
    if (!frame) {
      return;
    }
    try {
      this.#proof.screenshot = {
        mimeType: "image/png",
        dataBase64: decodePngDataUrl(this.#canvas.toDataURL("image/png")),
        width: frame.width,
        height: frame.height,
        frameId: frame.id,
        timestampMs: frame.timestampMs,
        observationSequence: this.#observationSequence,
      };
    } catch (error) {
      this.#recordFatal("failed to capture final single-A screenshot: " +
          String(error));
    }
  }

  #maybeQueueVerifiers() {
    if (this.#phase === RESTART_PHASE) {
      if (!this.#proof.restartPresentationQueued && this.#canQueuePresentation(1)) {
        this.#queueVerifier(
            "chromium_wasm_browser_host_continuous_flow_presented", 1,
            "restartPresentationQueued", () => this.#canQueuePresentation(1));
      }
      return;
    }
    for (const [stage, field] of [
      [1, "check1Queued"], [2, "check2Queued"], [3, "check3Queued"],
      [4, "check4Queued"], [5, "check5Queued"], [6, "check6Queued"],
    ]) {
      if (!this.#proof[field] && this.#canQueueCheck(stage)) {
        this.#queueVerifier(
            "chromium_wasm_browser_host_continuous_flow_check", stage, field,
            () => this.#canQueueCheck(stage));
        return;
      }
    }
    this.#captureFinalScreenshot();
    if (!this.#proof.finalPresentationQueued && this.#canQueuePresentation(7)) {
      this.#queueVerifier(
          "chromium_wasm_browser_host_continuous_flow_presented", 7,
          "finalPresentationQueued", () => this.#canQueuePresentation(7));
    }
  }

  #textState(phase) {
    this.#beginTextTransaction(phase);
    const transaction = this.#activeText;
    if (!transaction || transaction.phase !== phase) {
      return "awaiting-native-" + phase + "-navigation";
    }
    if (!transaction.ctrlLComplete) {
      return "awaiting-trusted-dom-" + phase + "-ctrl-l";
    }
    if (!transaction.proxyFocused || transaction.admissionCount === 0) {
      return "awaiting-trusted-dom-" + phase + "-insert-text";
    }
    if (!transaction.deliveryAccepted || this.#textSnapshot().pendingDeliveryCount !== 0) {
      return "awaiting-native-" + phase + "-text-delivery";
    }
    if (!transaction.enterComplete) {
      return "awaiting-trusted-dom-" + phase + "-enter";
    }
    return "awaiting-native-" + phase + "-navigation";
  }

  #callHostKey(code, down) {
    if (!this.#module || typeof this.#module.ccall !== "function") {
      return 0;
    }
    try {
      return this.#module.ccall(
          "chromium_wasm_browser_host_key", "number", ["string", "number"],
          [code, down ? 1 : 0]);
    } catch (error) {
      this.#recordFatal("reload key ABI failed: " + String(error));
      return 0;
    }
  }

  #releaseReloadHeldKeys(reason) {
    for (const code of [...this.#reloadHeldCodes].reverse()) {
      appendBounded(this.#proof.reloadCleanupRecords, {
        reason,
        code,
        accepted: this.#callHostKey(code, false) === 1,
      });
    }
    this.#reloadHeldCodes = [];
  }

  #detachReloadInput() {
    if (!this.#reloadInputAttached) {
      return;
    }
    this.#canvas.removeEventListener("keydown", this.#onReloadKeyDown);
    this.#canvas.removeEventListener("keyup", this.#onReloadKeyUp);
    this.#canvas.removeEventListener("blur", this.#onReloadCanvasBlur);
    window.removeEventListener("blur", this.#onReloadWindowBlur);
    document.removeEventListener("visibilitychange", this.#onReloadVisibilityChange);
    this.#reloadInputAttached = false;
  }

  #reloadRejectionReason(event, down) {
    const expected = [
      ["keydown", "ControlLeft"], ["keydown", "KeyR"],
      ["keyup", "KeyR"], ["keyup", "ControlLeft"],
    ];
    const expectedEvent = expected[this.#proof.ctrlRRecords.length];
    if (!this.#reloadInputAttached || !expectedEvent ||
        expectedEvent[0] !== (down ? "keydown" : "keyup") ||
        expectedEvent[1] !== event.code || event.isTrusted !== true ||
        event.cancelable !== true || document.activeElement !== this.#canvas ||
        event.isComposing || event.repeat || event.metaKey || event.altKey ||
        event.shiftKey || event.getModifierState("AltGraph") ||
        (event.code === "KeyR" && !event.ctrlKey)) {
      return "outside the fixed trusted Ctrl+R transaction";
    }
    return null;
  }

  #handleReloadKey(event, down) {
    const record = {
      type: down ? "keydown" : "keyup",
      code: event.code,
      key: event.key,
      trusted: event.isTrusted,
      cancelable: event.cancelable,
      canvasFocused: document.activeElement === this.#canvas,
      accepted: false,
      defaultPrevented: false,
    };
    const reason = this.#reloadRejectionReason(event, down);
    if (event.cancelable) {
      event.preventDefault();
    }
    record.defaultPrevented = event.defaultPrevented === true;
    if (reason || this.#callHostKey(event.code, down) !== 1) {
      record.reason = reason || "Chrome rejected a reload key";
      appendBounded(this.#proof.reloadRejectedRecords, record);
      this.#recordFatal("trusted Ctrl+R was rejected: " + record.reason);
      return;
    }
    record.accepted = true;
    appendBounded(this.#proof.ctrlRRecords, record);
    if (down) {
      this.#reloadHeldCodes.push(event.code);
    } else {
      this.#reloadHeldCodes = this.#reloadHeldCodes.filter((code) => code !== event.code);
    }
    if (this.#proof.ctrlRRecords.length === 4) {
      this.#detachReloadInput();
      this.#setState("awaiting-native-reload");
    } else {
      this.#publishState();
    }
  }

  #armReloadInput() {
    if (this.#phase !== FLOW_PHASE || !this.#proof.reloadReadyObserved ||
        this.#reloadInputAttached || this.#proof.ctrlRRecords.length !== 0 ||
        this.#proof.frameAfterReloadReady === null ||
        !this.#completedTransaction("version") || !this.#textInput ||
        this.#textDetachedAfterSecondSequence) {
      return;
    }
    const snapshot = this.#textSnapshot();
    if (snapshot.pendingDeliveryCount !== 0 || snapshot.pendingTextUtf8Bytes !== 0 ||
        snapshot.deliveryRejected || snapshot.textareaValue !== "") {
      this.#recordFatal("action-4 text adapter did not drain before Ctrl+R");
      return;
    }
    // The one action-4/session-0 adapter remains attached through both
    // sequences [1, 2]. Only now, after B is closed and no future text
    // transaction exists, preserve its evidence and install the distinct
    // generic physical-key reload lane.
    this.#textDetachedAfterSecondSequence = true;
    this.#reloadTextSnapshot = snapshot;
    this.#textInput.detach();
    this.#proxy.value = "";
    this.#proxy.setSelectionRange(0, 0);
    this.#canvas.focus({preventScroll: true});
    if (document.activeElement !== this.#canvas) {
      this.#recordFatal("canvas did not accept focus for Ctrl+R");
      return;
    }
    this.#onReloadKeyDown = (event) => this.#handleReloadKey(event, true);
    this.#onReloadKeyUp = (event) => this.#handleReloadKey(event, false);
    this.#onReloadCanvasBlur = () => this.#releaseReloadHeldKeys("canvas-blur");
    this.#onReloadWindowBlur = () => this.#releaseReloadHeldKeys("window-blur");
    this.#onReloadVisibilityChange = () => {
      if (document.hidden) {
        this.#releaseReloadHeldKeys("document-hidden");
      }
    };
    this.#canvas.addEventListener("keydown", this.#onReloadKeyDown);
    this.#canvas.addEventListener("keyup", this.#onReloadKeyUp);
    this.#canvas.addEventListener("blur", this.#onReloadCanvasBlur);
    window.addEventListener("blur", this.#onReloadWindowBlur);
    document.addEventListener("visibilitychange", this.#onReloadVisibilityChange);
    this.#reloadInputAttached = true;
  }

  #updateState() {
    this.#updatePostMarkerFrames();
    this.#maybeQueueVerifiers();
    this.#armReloadInput();
    if (this.#fatalErrors.length !== 0) {
      this.#setState("failed");
      return;
    }
    if (this.#phase === RESTART_PHASE) {
      if (!this.#proof.restartReadyObserved) {
        this.#setState("starting");
      } else if (!this.#proof.frameAfterRestartReady) {
        this.#setState("awaiting-post-restart-ready-frame");
      } else if (!this.#proof.restartPresentationQueued) {
        this.#setState("awaiting-restart-presentation");
      } else if (!this.#proof.restartClosingObserved) {
        this.#setState("awaiting-orderly-restart-close");
      } else {
        this.#setState("restart-close-observed");
      }
      return;
    }
    if (this.#proof.passObserved) {
      this.#setState("pass-observed");
      return;
    }
    if (!this.#module || !this.#textInput || !this.#proof.readyObserved) {
      this.#setState("starting");
      return;
    }
    if (!this.#proof.httpsNavigatedObserved) {
      this.#setState(this.#textState("https"));
      return;
    }
    if (!this.#proof.versionReadyObserved) {
      this.#setState(this.#proof.frameAfterHttpsNavigated !== null ?
          "awaiting-trusted-dom-new-tab" : "awaiting-post-https-frame");
      return;
    }
    if (!this.#proof.versionNavigatedObserved) {
      this.#setState(this.#proof.frameAfterVersionReady !== null ?
          this.#textState("version") : "awaiting-post-version-ready-frame");
      return;
    }
    if (!this.#proof.firstTabSelectedObserved) {
      this.#setState(this.#proof.frameAfterVersionNavigated !== null ?
          "awaiting-trusted-dom-switch-a" : "awaiting-post-version-frame");
      return;
    }
    if (!this.#proof.menuReadyObserved) {
      this.#setState(this.#proof.frameAfterFirstTabSelected !== null ?
          "awaiting-trusted-dom-switch-b" : "awaiting-post-first-switch-frame");
      return;
    }
    if (!this.#proof.menuOpenedObserved) {
      this.#setState(this.#proof.frameAfterMenuReady !== null ?
          "awaiting-trusted-dom-menu" : "awaiting-post-menu-ready-frame");
      return;
    }
    if (!this.#proof.settingsNavigatedObserved) {
      this.#setState(this.#proof.frameAfterMenuOpened !== null ?
          "awaiting-trusted-dom-settings" : "awaiting-post-menu-open-frame");
      return;
    }
    if (!this.#proof.firstTabReturnedObserved) {
      this.#setState(this.#proof.frameAfterSettingsNavigated !== null ?
          "awaiting-trusted-dom-return-a" : "awaiting-post-settings-frame");
      return;
    }
    if (!this.#proof.reloadReadyObserved) {
      this.#setState(this.#proof.frameAfterFirstTabReturned !== null ?
          "awaiting-trusted-dom-close-b" : "awaiting-post-return-a-frame");
      return;
    }
    if (!this.#reloadInputAttached && this.#proof.ctrlRRecords.length === 0) {
      this.#setState("awaiting-post-close-frame");
      return;
    }
    if (this.#proof.ctrlRRecords.length !== 4) {
      this.#setState("awaiting-trusted-dom-ctrl-r");
      return;
    }
    if (!this.#proof.reloadedObserved || !this.#proof.secondFvpObserved ||
        this.#proof.frameAfterSecondFvp === null) {
      this.#setState("awaiting-final-reload-frame");
      return;
    }
    this.#setState(this.#proof.finalPresentationQueued ?
        "awaiting-orderly-close" : "awaiting-final-presentation");
  }

  #advance() {
    this.#updateState();
    this.#publishState();
  }

  #publishState() {
    const text = this.#textSnapshot();
    globalThis.__chromiumWasmM6ContinuousFlowState = Object.freeze({
      phase: this.#phase,
      state: this.#state,
      attached: this.#textInput !== null && text.attached,
      readyObserved: this.#proof.readyObserved,
      activeTextPhase: this.#activeText?.phase || null,
      completedTextTransactionCount: this.#completedText.length,
      textAdapterInstances: this.#textAdapterInstances,
      pendingDeliveryCount: text.pendingDeliveryCount,
      newTabTarget: this.#proof.newTabTarget,
      switchFirstTarget: this.#proof.switchFirstTarget,
      switchSecondTarget: this.#proof.switchSecondTarget,
      menuTarget: this.#proof.menuTarget,
      settingsTarget: this.#proof.settingsTarget,
      returnFirstTarget: this.#proof.returnFirstTarget,
      closeSecondTarget: this.#proof.closeSecondTarget,
      ctrlRRecordCount: this.#proof.ctrlRRecords.length,
      passObserved: this.#proof.passObserved,
      restartClosingObserved: this.#proof.restartClosingObserved,
    });
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null ||
        typeof module.ccall !== "function" ||
        typeof module._chromium_wasm_browser_host_key !== "function" ||
        typeof module._chromium_wasm_browser_host_text !== "function" ||
        typeof module._chromium_wasm_browser_host_pointer !== "function" ||
        typeof module._chromium_wasm_browser_host_pointer_exit !== "function" ||
        typeof module._malloc !== "function" || typeof module._free !== "function" ||
        !(module.HEAPU8 instanceof Uint8Array)) {
      this.#recordFatal("Module lacks required trusted Ozone exports");
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
    if (this.#phase === FLOW_PHASE) {
      ++this.#textAdapterInstances;
      this.#textInput = new ChromiumWasmTrustedTextInput(this.#canvas, this.#proxy, {
        getModule: () => this.#module,
        reportFatal: (message) => this.#recordFatal(message),
        canAcceptBeforeInput: () => !!this.#activeText &&
            !this.#activeText.rejected && this.#activeText.admissionCount === 0,
        validateBeforeInput: (event) => this.#canAcceptBeforeInput(event) ? null :
            "continuous-flow text must exactly match its fixed transaction",
        canSubmitEnter: () => this.#canSubmitTextEnter(),
        onCtrlLComplete: () => this.#recordCtrlLComplete(),
        onProxyFocused: () => this.#recordProxyFocused(),
        onBeforeInputQueued: (record) => this.#recordTextAdmission(record),
        onNativeDelivery: (report) => this.#recordTextDelivery(report),
        onNativeDeliveryRejected: () => this.#recordTextRejected(),
        onEnterComplete: () => this.#recordEnterComplete(),
        onStateChange: () => this.#advance(),
      });
      this.#textInput.attach();
      const latestState = this.#textInputStates.at(-1);
      if (latestState) {
        this.#textInput.handleOzoneTextInputState(latestState);
      }
    }
    this.#advance();
  }

  #result(status, error) {
    const text = this.#textSnapshot();
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      phase: this.#phase,
      status,
      formalTarget6AcceptanceFlow: this.#phase === FLOW_PHASE,
      m6ProductBreadthComplete: false,
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
      artifact: this.#artifact,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      ozoneFocusReports: this.#focusReports,
      ozoneTextInputStates: this.#textInputStates,
      ozoneTextInputDeliveries: this.#textInputDeliveries,
      ozoneCursorReports: this.#cursorReports,
      continuousFlow: {...this.#proof, screenshot: undefined},
      hostInput: {
        singlePersistentAction4Adapter: this.#textAdapterInstances === 1,
        action4SessionId: 0,
        textTransactions: this.#completedText,
        textAdapterDetachedAfterSecondSequence: this.#textDetachedAfterSecondSequence,
        proxyTextEmpty: this.#proxy.value === "",
        pointerRecords: this.#proof.pointerRecords,
        ctrlRRecords: this.#proof.ctrlRRecords,
        reloadRejectedRecords: this.#proof.reloadRejectedRecords,
        reloadCleanupRecords: this.#proof.reloadCleanupRecords,
        adapter: snapshotMetadata(text),
      },
      screenshot: this.#proof.screenshot,
      canvasBackingStore: {width: this.#canvas.width, height: this.#canvas.height},
      stdout: this.#stdout,
      stderr: this.#stderr,
      error: error === null ? null : redactDiagnostic(error),
    };
  }

  async run(modulePath, timeoutMs, wispEndpoint, fixtureUrl) {
    const startedAt = performance.now();
    let loaderImportUrl = null;
    try {
      if (!crossOriginIsolated || typeof SharedArrayBuffer !== "function") {
        throw new Error("continuous-flow host requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 || timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("continuous-flow timeout is out of range");
      }
      const fixture = parseFixtureUrl(fixtureUrl);
      const wispConfiguration = parseWispConfiguration(wispEndpoint);
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("continuous-flow module must use the host origin");
      }
      const wasmUrl = new URL(`${this.#artifact.module_name}.wasm`, moduleUrl);
      if (wasmUrl.origin !== location.origin) {
        throw new Error("continuous-flow Wasm must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("continuous-flow canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const [loaderBytes, wasmBytes] = await Promise.all([
        fetchVerifiedArtifact(
            moduleUrl.href, this.#artifact.loader, "continuous-flow module loader"),
        fetchVerifiedArtifact(
            wasmUrl.href, this.#artifact.wasm, "continuous-flow Wasm"),
      ]);
      if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function") {
        throw new Error("continuous-flow host cannot import a verified module loader");
      }
      // Import and pass the exact verified loader bytes. The verified Wasm
      // bytes are supplied through Emscripten's wasmBinary option below, so
      // this flow never treats an unverified second network fetch as evidence.
      const mainScriptUrlOrBlob = new Blob([loaderBytes], {type: "text/javascript"});
      loaderImportUrl = URL.createObjectURL(mainScriptUrlOrBlob);
      const namespace = await import(loaderImportUrl);
      if (typeof namespace.default !== "function") {
        throw new Error("module loader has no default factory");
      }
      const host = this;
      const moduleOptions = {
        arguments: this.#phase === FLOW_PHASE ? [
          FLOW_SWITCH, URL_SWITCH + "=" + fixture.href,
        ] : [RESTART_SWITCH],
        canvas: this.#canvas,
        noExitRuntime: false,
        mainScriptUrlOrBlob,
        wasmBinary: wasmBytes,
        locateFile: (path) => path === `${this.#artifact.module_name}.wasm` ?
            wasmUrl.href : new URL(path, moduleUrl).href,
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
          host.#abort = redactDiagnostic(reason);
          host.#recordFatal("abort: " + host.#abort);
        },
        onExit(code) { host.#reportRuntimeExit(Number(code)); },
      };
      moduleOptions.chromiumWasmWisp = wispConfiguration;
      this.#proof.wispConfigured = true;
      this.#proof.runtimeArgumentsConfigured = true;
      this.#proof.configurationPrecededFactory = true;
      const factoryPromise = namespace.default(moduleOptions).then((module) => {
        this.#factorySettled = true;
        module.chromiumWasmHostBridge = globalThis.__chromiumWasmHostBridgeV1;
        if (this.#module === null) {
          this.#setModule(module);
        }
        return module;
      }).catch((error) => {
        this.#factorySettled = true;
        this.#recordFatal("module factory rejected: " + String(error));
      });
      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("continuous-flow runtime did not exit before timeout");
      }
      await Promise.race([factoryPromise, delay(250)]);
      if (!this.#factorySettled) {
        throw new Error("continuous-flow factory did not settle after exit");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      if (loaderImportUrl !== null) {
        URL.revokeObjectURL(loaderImportUrl);
      }
      ++this.#verifierGeneration;
      this.#releaseReloadHeldKeys("teardown");
      this.#detachReloadInput();
      this.#pointerInput?.releaseActivePointer("teardown");
      this.#pointerInput?.detach();
      this.#textInput?.detach();
      this.#releaseWindowErrors();
    }
  }
}

function requireResult(condition, failures, message) {
  if (!condition) {
    failures.push(message);
  }
}

function validateResult(result) {
  const failures = [];
  requireResult(result.status === "pass", failures, "runtime status is not pass");
  requireResult(result.runtimeExitCode === 0, failures, "runtime did not exit zero");
  requireResult(result.processExitCode === null || result.processExitCode === 0,
      failures, "bridge process exit disagrees with runtime");
  requireResult(result.runtimeInitialized === true && result.factorySettled === true,
      failures, "runtime/factory did not initialize and settle");
  requireResult(result.crossOriginIsolated === true && result.sharedArrayBuffer === true,
      failures, "host isolation is incomplete");
  requireResult(result.abort === null, failures, "runtime aborted");
  requireResult(Array.isArray(result.fatalErrors) && result.fatalErrors.length === 0,
      failures, "host recorded fatal errors");
  requireResult(Array.isArray(result.windowErrors) && result.windowErrors.length === 0,
      failures, "host recorded window errors");
  requireResult(Array.isArray(result.unhandledRejections) &&
      result.unhandledRejections.length === 0, failures,
      "host recorded unhandled rejections");
  requireResult(result.artifact?.artifact_delivery === ARTIFACT_DELIVERY &&
      result.artifact?.artifact_source_provenance === ARTIFACT_SOURCE_PROVENANCE,
  failures, "artifact identity has invalid delivery provenance");
  requireResult(/^[A-Za-z0-9_]+$/.test(result.artifact?.module_name || ""), failures,
  "artifact identity has an invalid module name");
  // Generic Ozone readiness FVP is a shell-level diagnostic and can remain
  // false for the running Chrome Browser. The acceptance proof uses the two
  // dedicated C++ target-FVP imports plus strictly later canvas frames.
  requireResult(isReadinessReport(result.readiness) &&
      result.readiness.surfaceReady === true &&
      Array.isArray(result.readinessReports) && result.readinessReports.some(
          (report) => isReadinessReport(report) && report.surfaceReady === true),
      failures, "surface readiness is absent");
  const proof = result.continuousFlow;
  if (result.phase === RESTART_PHASE) {
    for (const field of [
      "restartReadyObserved", "restartPresentationQueued", "restartClosingObserved",
    ]) {
      requireResult(proof?.[field] === true, failures,
          "restart proof lacks " + field);
    }
    requireResult(proof?.frameAfterRestartReady > proof?.frameAtRestartReady,
        failures, "restart has no post-ready frame");
  } else {
    for (const field of [
      "readyObserved", "httpsNavigatedObserved", "versionReadyObserved",
      "versionNavigatedObserved", "firstTabSelectedObserved", "menuReadyObserved",
      "menuOpenedObserved", "settingsNavigatedObserved", "firstTabReturnedObserved",
      "secondTabClosedObserved", "reloadReadyObserved", "reloadedObserved",
      "firstFvpObserved", "secondFvpObserved", "check1Queued", "check2Queued",
      "check3Queued", "check4Queued", "check5Queued", "check6Queued",
      "finalPresentationQueued", "passObserved",
    ]) {
      requireResult(proof?.[field] === true, failures, "flow proof lacks " + field);
    }
    requireResult(result.hostInput?.singlePersistentAction4Adapter === true &&
        result.hostInput?.action4SessionId === 0 &&
        result.hostInput?.textAdapterDetachedAfterSecondSequence === true,
        failures, "one persistent action-4 adapter was not retained through [1,2]");
    requireResult(Array.isArray(result.hostInput?.textTransactions) &&
        result.hostInput.textTransactions.length === 2 &&
        result.hostInput.textTransactions[0]?.expectedSequence === 1 &&
        result.hostInput.textTransactions[1]?.expectedSequence === 2,
        failures, "trusted text transactions do not prove sequences [1,2]");
    requireResult(result.screenshot?.mimeType === "image/png" &&
        result.screenshot?.frameId === proof?.frameAfterSecondFvp &&
        isStrictPostTargetFvpFrameForTesting(
            proof?.frameAtReloaded, proof?.frameAtSecondFvp,
            result.screenshot?.frameId), failures,
        "final screenshot is not strictly after RELOADED and phase-2 FVP");
  }
  if (failures.length !== 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

function resultForDisplay(result) {
  if (!result?.screenshot?.dataBase64) {
    return result;
  }
  return {...result, screenshot: {...result.screenshot, dataBase64: "<omitted>"}};
}

export async function runChromeWasmBrowserContinuousFlowSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  const phase = query.get("phase") || FLOW_PHASE;
  if (!/^[A-Za-z0-9_]+$/.test(moduleName) ||
      (phase !== FLOW_PHASE && phase !== RESTART_PHASE)) {
    throw new Error("continuous-flow query is invalid");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "60000");
  const versions = parseVersions(query.get("versions"));
  const artifact = parseArtifactIdentity(query.get("artifact"));
  if (artifact.module_name !== moduleName) {
    throw new Error("continuous-flow artifact module name disagrees with query");
  }
  const root = document.querySelector("#browser-continuous-flow-root");
  const canvas = document.querySelector("#browser-canvas");
  const proxy = document.querySelector("#browser-text-proxy");
  const status = document.querySelector("#browser-continuous-flow-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(proxy instanceof HTMLTextAreaElement) || !(status instanceof HTMLElement)) {
    throw new Error("continuous-flow page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserContinuousFlowHost(
      canvas, proxy, versions, phase, artifact);
  const result = validateResult(await host.run(
      location.pathname.replace(/\/$/, "") + "/artifacts/" + moduleName + ".js",
      timeoutMs, query.get("wispEndpoint"), query.get("fixtureUrl")));
  result.outerPageFreshRestart = phase === RESTART_PHASE &&
      query.get("outerRestart") === "1";
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(resultForDisplay(result), null, 2);
  const response = await fetch(
      location.pathname.replace(/\/$/, "") + "/result/" +
          encodeURIComponent(token) + "/" + phase,
      {
        method: "POST",
        cache: "no-store",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error("continuous-flow result upload returned HTTP " + response.status);
  }
  if (phase === FLOW_PHASE && result.status === "pass") {
    // This is a full outer-document navigation, so the restart phase creates a
    // fresh Emscripten/Chrome Browser lifetime rather than reusing a READY
    // marker or a prior JS Module.
    const restart = new URL(location.href);
    restart.searchParams.set("phase", RESTART_PHASE);
    restart.searchParams.set("outerRestart", "1");
    location.replace(restart.href);
  }
  return result;
}

export const chromeWasmBrowserContinuousFlowSmokeContract = Object.freeze({
  ARTIFACT_DELIVERY,
  ARTIFACT_SOURCE_PROVENANCE,
  protocol: HOST_PROTOCOL,
  case: CASE,
  scope: SCOPE,
  phases: Object.freeze([FLOW_PHASE, RESTART_PHASE]),
  action4Sequences: Object.freeze([1, 2]),
  verifierOrdinals: Object.freeze([1, 2, 3, 4, 5, 6, 7]),
});

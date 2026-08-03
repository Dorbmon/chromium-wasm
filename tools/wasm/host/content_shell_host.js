// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const HOST_PROTOCOL = 1;
const M3_CASE = "content_shell_m3";
const M4_CASE = "ozone_pointer_m4";
const M4_WHEEL_CASE = "ozone_wheel_m4";
const M4_FIXTURE = "chromium-wasm-m4-ozone-pointer-v1";
const M4_WHEEL_FIXTURE = "chromium-wasm-m4-ozone-wheel-v1";
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

let activeHost = null;
const pendingBridgeReports = [];

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
  #fixture;
  #module = null;
  #lifecycle = "new";
  #runtimeInitialized = false;
  #fatalErrors = [];
  #reportedReadiness = {};
  #navigation = {};
  #pageProbe = {};
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

  constructor(
    canvas,
    versions,
    {fixture = "chromium-wasm-m3-static-v1"} = {},
  ) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("M3 host requires a canvas");
    }
    if (activeHost) {
      throw new Error("only one M3 host instance may be active");
    }
    this.#canvas = canvas;
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
    if (!argumentTypes.includes("string")) {
      return direct(...args);
    }
    if (
      typeof this.#module._malloc !== "function" ||
      typeof this.#module._free !== "function" ||
      !this.#module.HEAPU8
    ) {
      throw new Error(
        `runtime export ${name} needs ccall or malloc/string support`);
    }
    const allocated = [];
    try {
      const converted = args.map((value, index) => {
        if (argumentTypes[index] !== "string") {
          return value;
        }
        const encoded = new TextEncoder().encode(`${value}\0`);
        const pointer = this.#module._malloc(encoded.length);
        if (!pointer) {
          throw new Error(`allocation failed while calling ${name}`);
        }
        allocated.push(pointer);
        // Fetch HEAPU8 after malloc because memory growth invalidates old views.
        this.#module.HEAPU8.set(encoded, pointer);
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
      frame: this.#frame ? clone(this.#frame) : null,
      inputPostedAtFrameId: this.#inputPostedAtFrameId,
      interactionObservedAtFrameId: this.#interactionObservedAtFrameId,
      fatalErrors: clone(this.#fatalErrors),
      heartbeat,
      pointerInput: this.#pointerInputStatus(),
      wheelInput: this.#wheelInputStatus(),
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
    window.__chromiumWasmM4State = {
      state: "awaiting-dom-pointer",
      targetX,
      targetY,
      listeners,
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
    window.__chromiumWasmM4WheelState = {
      state: "awaiting-dom-wheel",
      targetX,
      targetY,
      listeners,
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
  throw new Error("unknown Content Shell Wasm smoke case");
}

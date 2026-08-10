// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This lane proves the product trusted-DOM pointer adapter, not a host menu
// implementation. The outer browser emits physical mouse events; this host
// observes the shared adapter and asks a C++ verifier to inspect the real
// BrowserView menu, NavigationController, and limited Settings bootstrap.

import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";

const HOST_PROTOCOL = 1;
const CASE = "browser_host_pointer_menu_settings_m6";
const SCOPE = "trusted-dom-pointer-ozone-aura-views-menu-settings-bootstrap";
const SWITCH = "--wasm-browser-host-pointer-menu-smoke";
const READY_MARKER = "CHROMIUM_WASM_M6_HOST_POINTER_MENU:READY";
const MENU_OPEN_MARKER = "CHROMIUM_WASM_M6_HOST_POINTER_MENU:MENU_OPEN";
const MENU_PRESENTED_MARKER =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:MENU_PRESENTED";
const MENU_CLOSED_MARKER =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:MENU_CLOSED";
const SETTINGS_NAVIGATED_MARKER =
    "CHROMIUM_WASM_M6_HOST_POINTER_MENU:SETTINGS_NAVIGATED";
const PASS_MARKER = "CHROMIUM_WASM_M6_HOST_POINTER_MENU:PASS";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 64;
const LIMITED_SETTINGS_BOOTSTRAP =
    "limited-m6-bootstrap-read-only-volatile";

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
    throw new Error(`invalid host-pointer-menu versions: ${String(error)}`);
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("host-pointer-menu page is missing its version element");
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

class ChromiumWasmBrowserHostPointerMenuSmokeHost {
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
    menuClosedObserved: false,
    settingsNavigatedObserved: false,
    passObserved: false,
    menuTarget: null,
    settingsTarget: null,
    frameIdAtMenuOpenedMarker: null,
    frameIdAfterMenuOpen: null,
    frameIdAtMenuClosedMarker: null,
    frameIdAfterSettingsClick: null,
    frameIdAtSettingsNavigatedMarker: null,
    frameIdAfterSettingsNavigation: null,
    menuCheckQueued: false,
    menuPresentationQueued: false,
    settingsCheckQueued: false,
    settingsPresentationQueued: false,
    pointerRecords: [],
  };

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("host-pointer-menu smoke requires a canvas");
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
      // Frame imports can run synchronously from C++ on the proxied UI path.
      // Any verifier ccall requested by presentation evidence is deferred.
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
        throw new Error("focus report is invalid");
      }
      appendBounded(this.#focusReports, {
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      });
    } catch (error) {
      this.#recordFatal(`invalid focus report: ${String(error)}`);
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("host-pointer-menu bridge is already installed");
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
    globalThis.__chromiumWasmM6HostPointerMenuState = Object.freeze({
      state,
      attached: input.attached,
      readyObserved: input.readyObserved,
      menuOpenedObserved: input.menuOpenedObserved,
      menuPresentedObserved: input.menuPresentedObserved,
      menuClosedObserved: input.menuClosedObserved,
      settingsNavigatedObserved: input.settingsNavigatedObserved,
      passObserved: input.passObserved,
      menuTarget: input.menuTarget,
      settingsTarget: input.settingsTarget,
      frameIdAtMenuOpenedMarker: input.frameIdAtMenuOpenedMarker,
      frameIdAfterMenuOpen: input.frameIdAfterMenuOpen,
      frameIdAtMenuClosedMarker: input.frameIdAtMenuClosedMarker,
      frameIdAfterSettingsClick: input.frameIdAfterSettingsClick,
      frameIdAtSettingsNavigatedMarker: input.frameIdAtSettingsNavigatedMarker,
      frameIdAfterSettingsNavigation: input.frameIdAfterSettingsNavigation,
      menuCheckQueued: input.menuCheckQueued,
      menuPresentationQueued: input.menuPresentationQueued,
      settingsCheckQueued: input.settingsCheckQueued,
      settingsPresentationQueued: input.settingsPresentationQueued,
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
      // The settings WebUI observer can report its target FVP while the
      // stage-two ordinal is still queued. Re-evaluate the joined proof after
      // this deferred call so that ordering does not strand the final
      // presentation acknowledgement.
      this.#advancePresentationState();
      this.#maybeRequestChecks();
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
          "chromium_wasm_browser_host_pointer_menu_check", 1,
          "menuCheckQueued");
      return;
    }
    if (this.#input.menuPresentedObserved && !this.#input.settingsCheckQueued &&
        this.#acceptedActionPairForTarget(this.#input.settingsTarget)) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_pointer_menu_check", 2,
          "settingsCheckQueued");
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
    if (this.#input.menuClosedObserved &&
        this.#input.frameIdAfterSettingsClick === null &&
        this.#input.frameIdAtMenuClosedMarker !== null) {
      const frame = this.#firstFrameAfter(this.#input.frameIdAtMenuClosedMarker);
      if (frame) {
        this.#input.frameIdAfterSettingsClick = frame.id;
      }
    }
    if (this.#input.settingsNavigatedObserved &&
        this.#input.frameIdAfterSettingsNavigation === null &&
        this.#input.frameIdAtSettingsNavigatedMarker !== null) {
      const frame = this.#firstFrameAfter(
          this.#input.frameIdAtSettingsNavigatedMarker);
      if (frame) {
        this.#input.frameIdAfterSettingsNavigation = frame.id;
      }
    }
    if (this.#input.menuOpenedObserved &&
        this.#input.frameIdAfterMenuOpen !== null &&
        !this.#input.menuPresentationQueued) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_pointer_menu_presented", 1,
          "menuPresentationQueued");
    }
    if (this.#input.settingsNavigatedObserved &&
        this.#input.frameIdAfterSettingsNavigation !== null &&
        this.#input.settingsCheckQueued &&
        !this.#input.settingsPresentationQueued) {
      this.#deferVerifier(
          "chromium_wasm_browser_host_pointer_menu_presented", 2,
          "settingsPresentationQueued");
    }
    this.#updateState();
  }

  #updateState() {
    if (this.#input.passObserved) {
      this.#publishState("pass-observed");
      return;
    }
    if (this.#input.settingsNavigatedObserved) {
      this.#publishState(this.#input.settingsPresentationQueued ?
          "awaiting-orderly-shutdown" : "awaiting-post-settings-frame");
      return;
    }
    if (this.#input.menuClosedObserved) {
      this.#publishState("awaiting-settings-navigation");
      return;
    }
    if (this.#input.menuPresentedObserved) {
      this.#publishState("awaiting-trusted-dom-settings");
      return;
    }
    if (this.#input.menuOpenedObserved) {
      this.#publishState(this.#input.menuPresentationQueued ?
          "awaiting-menu-presentation" : "awaiting-post-menu-frame");
      return;
    }
    if (this.#module && this.#input.attached && this.#input.readyObserved) {
      this.#publishState("awaiting-trusted-dom-menu");
    }
  }

  #recordOutput(text) {
    try {
      const ready = parseTargetMarker(text, READY_MARKER);
      if (ready) {
        if (this.#input.readyObserved) {
          throw new Error("received duplicate Menu READY marker");
        }
        const target = this.#targetForClientPoint(ready);
        if (!target) {
          throw new Error("Menu READY target cannot map to canvas");
        }
        this.#input.readyObserved = true;
        this.#input.menuTarget = target;
      }
      const settings = parseTargetMarker(text, MENU_OPEN_MARKER);
      if (settings) {
        if (!this.#input.menuCheckQueued || this.#input.menuOpenedObserved) {
          throw new Error("Menu-open target marker is out of order");
        }
        const target = this.#targetForClientPoint(settings);
        if (!target) {
          throw new Error("Settings target cannot map to canvas");
        }
        this.#input.menuOpenedObserved = true;
        this.#input.settingsTarget = target;
        this.#input.frameIdAtMenuOpenedMarker = this.#currentFrameId();
      }
      if (text.includes(MENU_PRESENTED_MARKER)) {
        if (!this.#input.menuPresentationQueued ||
            this.#input.menuPresentedObserved) {
          throw new Error("Menu presentation marker is out of order");
        }
        this.#input.menuPresentedObserved = true;
      }
      if (text.includes(MENU_CLOSED_MARKER)) {
        if (!this.#input.settingsCheckQueued || this.#input.menuClosedObserved) {
          throw new Error("Menu-close marker is out of order");
        }
        this.#input.menuClosedObserved = true;
        this.#input.frameIdAtMenuClosedMarker = this.#currentFrameId();
      }
      if (text.includes(SETTINGS_NAVIGATED_MARKER)) {
        if (this.#input.settingsNavigatedObserved) {
          throw new Error("Settings navigation marker is duplicated");
        }
        // The observer is intentionally independent from queued stage 2: a
        // fast local WebUI may complete before the ordinal verifier task.
        this.#input.settingsNavigatedObserved = true;
        this.#input.frameIdAtSettingsNavigatedMarker = this.#currentFrameId();
      }
      if (text.includes(PASS_MARKER)) {
        if (!this.#input.settingsPresentationQueued || this.#input.passObserved) {
          throw new Error("Menu Settings PASS marker is out of order");
        }
        this.#input.passObserved = true;
      }
      // stdout can be a synchronous C++ -> JS import. This only schedules
      // work through #advancePresentationState; it never re-enters Wasm here.
      this.#advancePresentationState();
      this.#maybeRequestChecks();
    } catch (error) {
      this.#recordFatal(`invalid Menu Settings output: ${String(error)}`);
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
      hostInput: {
        ...this.#input,
        settingsBootstrap: LIMITED_SETTINGS_BOOTSTRAP,
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
        throw new Error("host-pointer-menu smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("host-pointer-menu timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("host-pointer-menu module must use host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("host-pointer-menu canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("host-pointer-menu module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("host-pointer-menu loader has no default factory export");
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
        throw new Error("host-pointer-menu smoke did not exit before timeout");
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
    "readyObserved", "menuOpenedObserved", "menuPresentedObserved",
    "menuClosedObserved", "settingsNavigatedObserved", "passObserved",
    "menuCheckQueued", "menuPresentationQueued", "settingsCheckQueued",
    "settingsPresentationQueued",
  ]) {
    require(input?.[field] === true, `host input ${field} is not true`);
  }
  require(input?.settingsBootstrap === LIMITED_SETTINGS_BOOTSTRAP,
      "Settings result does not describe the limited bootstrap");
  require(input?.menuTarget?.x !== input?.settingsTarget?.x ||
      input?.menuTarget?.y !== input?.settingsTarget?.y,
  "Menu and Settings targets are not distinct");
  require(input?.frameIdAfterMenuOpen > input?.frameIdAtMenuOpenedMarker,
      "menu open has no later presented frame");
  require(input?.frameIdAfterSettingsClick > input?.frameIdAtMenuClosedMarker,
      "settings action has no later presented frame");
  require(input?.frameIdAfterSettingsNavigation >
      input?.frameIdAtSettingsNavigatedMarker,
  "Settings FVP navigation has no later presented frame");
  const records = input?.pointerRecords;
  require(Array.isArray(records), "pointer records are missing");
  if (Array.isArray(records)) {
    require(!records.some((record) => record.accepted !== true),
        "host rejected an outer trusted pointer record");
    const actions = records.filter((record) =>
      record.type === "down" || record.type === "up");
    require(actions.length === 4, "host did not record exactly two pointer clicks");
    require(acceptedPointerPair(records, input?.menuTarget, 0),
        "trusted Menu pointer pair is invalid");
    require(acceptedPointerPair(records, input?.settingsTarget, 2),
        "trusted Settings pointer pair is invalid");
  }
  result.failedChecks = failures;
  if (failures.length) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserHostPointerMenuSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-host-pointer-menu-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-host-pointer-menu-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("host-pointer-menu page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserHostPointerMenuSmokeHost(canvas, versions);
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

export const chromeWasmBrowserHostPointerMenuSmokeContract = Object.freeze({
  CASE,
  HOST_PROTOCOL,
  LIMITED_SETTINGS_BOOTSTRAP,
  MENU_CLOSED_MARKER,
  MENU_OPEN_MARKER,
  MENU_PRESENTED_MARKER,
  PASS_MARKER,
  READY_MARKER,
  SCOPE,
  SETTINGS_NAVIGATED_MARKER,
  SWITCH,
});

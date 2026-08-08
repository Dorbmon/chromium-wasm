// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This host proves only that the bounded BrowserView smoke reaches a real
// Ozone canvas. It is not a Chrome browser UI host and must not be used as an
// M6 completion signal.
const HOST_PROTOCOL = 1;
const BROWSER_VIEW_CASE = "browser_view_structural_m6";
const BROWSER_VIEW_SCOPE = "structural-frame-presentation";
const BROWSER_VIEW_EXIT_CODE = 0;
const BROWSER_VIEW_SWITCH = "--wasm-browser-view-smoke";
const BROWSER_VIEW_MARKER = "CHROMIUM_WASM_M6_BROWSER_VIEW:PASS";
const MAX_BROWSER_VIEW_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_REPORT_HISTORY = 64;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} must be a nonempty string`);
  }
  return value;
}

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error(
        `invalid BrowserView structural smoke versions: ${String(error)}`);
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  element.replaceChildren();
  for (const [name, value] of Object.entries(versions)) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = value;
    element.append(term, definition);
  }
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

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_REPORT_HISTORY) {
    records.shift();
  }
}

function ozoneCursorDescriptor(cursorType) {
  // Values intentionally mirror ui::mojom::CursorType. The C++ bridge sends a
  // scalar and this host applies the browser-native CSS representation.
  switch (cursorType) {
    case -1:  // kNull
    case 0:   // kPointer
      return {cssCursor: "default", exact: true};
    case 1:
      return {cssCursor: "crosshair", exact: true};
    case 2:
      return {cssCursor: "pointer", exact: true};
    case 3:
      return {cssCursor: "text", exact: true};
    case 4:
      return {cssCursor: "wait", exact: true};
    case 5:
      return {cssCursor: "help", exact: true};
    case 6:
      return {cssCursor: "e-resize", exact: true};
    case 7:
      return {cssCursor: "n-resize", exact: true};
    case 8:
      return {cssCursor: "ne-resize", exact: true};
    case 9:
      return {cssCursor: "nw-resize", exact: true};
    case 10:
      return {cssCursor: "s-resize", exact: true};
    case 11:
      return {cssCursor: "se-resize", exact: true};
    case 12:
      return {cssCursor: "sw-resize", exact: true};
    case 13:
      return {cssCursor: "w-resize", exact: true};
    case 14:
      return {cssCursor: "ns-resize", exact: true};
    case 15:
      return {cssCursor: "ew-resize", exact: true};
    case 16:
      return {cssCursor: "nesw-resize", exact: true};
    case 17:
      return {cssCursor: "nwse-resize", exact: true};
    case 18:
      return {cssCursor: "col-resize", exact: true};
    case 19:
      return {cssCursor: "row-resize", exact: true};
    case 20:
    case 21:
    case 22:
    case 23:
    case 24:
    case 25:
    case 26:
    case 27:
    case 28:
    case 43:
    case 44:
      return {cssCursor: "all-scroll", exact: false};
    case 29:
      return {cssCursor: "move", exact: true};
    case 30:
      return {cssCursor: "vertical-text", exact: true};
    case 31:
      return {cssCursor: "cell", exact: true};
    case 32:
      return {cssCursor: "context-menu", exact: true};
    case 33:
      return {cssCursor: "alias", exact: true};
    case 34:
      return {cssCursor: "progress", exact: true};
    case 35:
      return {cssCursor: "no-drop", exact: true};
    case 36:
      return {cssCursor: "copy", exact: true};
    case 37:
      return {cssCursor: "none", exact: true};
    case 38:
      return {cssCursor: "not-allowed", exact: true};
    case 39:
      return {cssCursor: "zoom-in", exact: true};
    case 40:
      return {cssCursor: "zoom-out", exact: true};
    case 41:
      return {cssCursor: "grab", exact: true};
    case 42:
      return {cssCursor: "grabbing", exact: true};
    case 45:
      return {cssCursor: "default", exact: false};
    case 46:
      return {cssCursor: "no-drop", exact: false};
    case 47:
      return {cssCursor: "move", exact: false};
    case 48:
      return {cssCursor: "copy", exact: false};
    case 49:
      return {cssCursor: "alias", exact: false};
    case 50:
    case 51:
    case 52:
    case 53:
      return {cssCursor: "not-allowed", exact: false};
    default:
      return null;
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

class ChromiumWasmBrowserViewSmokeHost {
  #canvas;
  #versions;
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
  #ozoneFocusReports = [];
  #ozoneTextInputStates = [];
  #ozoneTextInputDeliveries = [];
  #ozoneCursorReports = [];
  #errorHandler;
  #rejectionHandler;

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("BrowserView structural smoke host requires a canvas");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
  }

  #recordFatal(message) {
    this.#fatalErrors.push(String(message));
  }

  #invalidBridgeReport(description, error) {
    const message = `${description}: ${String(error)}`;
    this.#recordFatal(message);
    throw new Error(message);
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      this.#windowErrors.push(message);
    };
    this.#rejectionHandler = (event) => {
      this.#unhandledRejections.push(String(event.reason));
    };
    addEventListener("error", this.#errorHandler);
    addEventListener("unhandledrejection", this.#rejectionHandler);
  }

  #releaseWindowErrors() {
    if (this.#errorHandler) {
      removeEventListener("error", this.#errorHandler);
      this.#errorHandler = undefined;
    }
    if (this.#rejectionHandler) {
      removeEventListener("unhandledrejection", this.#rejectionHandler);
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
      if (!Number.isSafeInteger(report.exitCode)) {
        throw new Error("exitCode is not an integer");
      }
      if (this.#processExitCode !== null) {
        throw new Error("bridge reported multiple process exits");
      }
      this.#processExitCode = report.exitCode;
    } catch (error) {
      this.#invalidBridgeReport("invalid bridge process-exit report", error);
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
      // chromium_wasm_present_frame copies into the host canvas before it
      // calls this callback. Checking the backing store here means a report
      // cannot stand in for a real host-canvas presentation.
      if (this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
        throw new Error("canvas backing dimensions do not match frame metadata");
      }
      appendBounded(this.#frameReports, {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      });
    } catch (error) {
      this.#invalidBridgeReport("invalid frame report", error);
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
      this.#invalidBridgeReport("invalid readiness report", error);
    }
  }

  #reportOzoneFocusState(value) {
    try {
      const report = asReport(value, "Ozone focus-state report");
      if (report.protocol !== HOST_PROTOCOL || !isFocusReport(report)) {
        throw new Error("Ozone focus-state report is invalid");
      }
      appendBounded(this.#ozoneFocusReports, {
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      });
    } catch (error) {
      this.#invalidBridgeReport("invalid Ozone focus-state report", error);
    }
  }

  #reportOzoneTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        typeof report.focusedClientPresent !== "boolean" ||
        typeof report.editable !== "boolean" ||
        typeof report.canComposeInline !== "boolean" ||
        (report.editable && !report.focusedClientPresent) ||
        (report.canComposeInline && !report.editable)
      ) {
        throw new Error("Ozone text-input state report is invalid");
      }
      appendBounded(this.#ozoneTextInputStates, {
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      });
    } catch (error) {
      this.#invalidBridgeReport("invalid Ozone text-input state report", error);
    }
  }

  #reportOzoneTextInputDelivery(value) {
    try {
      const report = asReport(value, "Ozone text-input delivery report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        !Number.isSafeInteger(report.action) || report.action < 1 ||
        report.action > 3 || !Number.isSafeInteger(report.sessionId) ||
        report.sessionId < 1 || !Number.isSafeInteger(report.sequence) ||
        report.sequence < 1 || typeof report.accepted !== "boolean"
      ) {
        throw new Error("Ozone text-input delivery report is invalid");
      }
      appendBounded(this.#ozoneTextInputDeliveries, {
        action: report.action,
        sessionId: report.sessionId,
        sequence: report.sequence,
        accepted: report.accepted,
      });
    } catch (error) {
      this.#invalidBridgeReport(
          "invalid Ozone text-input delivery report", error);
    }
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        !Number.isSafeInteger(report.cursorType)
      ) {
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
      appendBounded(this.#ozoneCursorReports, {
        cursorType: report.cursorType,
        cssCursor: descriptor.cssCursor,
        exact: descriptor.exact,
      });
      // The Wasm bridge applies the stricter exactness policy after this
      // delivery result. Returning true says only that this host installed the
      // CSS representation it just recorded.
      return true;
    } catch (error) {
      this.#recordFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("BrowserView smoke host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) {
        host.#recordFatal(message);
      },
      reportProcessExit(report) {
        host.#reportProcessExit(report);
      },
      reportFrame(report) {
        host.#reportFrame(report);
      },
      reportReadiness(report) {
        host.#reportReadiness(report);
      },
      reportOzoneFocusState(report) {
        host.#reportOzoneFocusState(report);
      },
      reportOzoneTextInputState(report) {
        host.#reportOzoneTextInputState(report);
      },
      reportOzoneTextInputDelivery(report) {
        host.#reportOzoneTextInputDelivery(report);
      },
      reportOzoneCursor(report) {
        return host.#reportOzoneCursor(report);
      },
    });
  }

  #markRuntimeInitialized() {
    this.#runtimeInitialized = true;
  }

  #result(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: BROWSER_VIEW_CASE,
      scope: BROWSER_VIEW_SCOPE,
      status,
      m6GateComplete: false,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === this.#canvas,
      browserViewMarkerObserved: this.#stderr.some(
          (line) => line.includes(BROWSER_VIEW_MARKER)),
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      ozoneFocusReports: this.#ozoneFocusReports,
      ozoneTextInputStates: this.#ozoneTextInputStates,
      ozoneTextInputDeliveries: this.#ozoneTextInputDeliveries,
      ozoneCursorReports: this.#ozoneCursorReports,
      canvasBackingStore: {
        width: this.#canvas.width,
        height: this.#canvas.height,
      },
      stdout: this.#stdout,
      stderr: this.#stderr,
      failedChecks: [],
      error,
    };
  }

  async run(modulePath, timeoutMs) {
    const runStartedAt = performance.now();
    try {
      if (!crossOriginIsolated) {
        throw new Error("BrowserView structural smoke host is not isolated");
      }
      if (typeof SharedArrayBuffer !== "function") {
        throw new Error("SharedArrayBuffer is unavailable");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_BROWSER_VIEW_TIMEOUT_MS) {
        throw new Error("BrowserView structural smoke timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("BrowserView structural smoke module must use host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("BrowserView structural smoke canvas did not accept focus");
      }

      // This must precede importing the Emscripten loader. BrowserWidget's
      // first Aura/Ozone callback is synchronous from the application pthread.
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("BrowserView structural smoke module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("BrowserView structural smoke loader has no factory");
      }
      const module = await namespace.default({
        canvas: this.#canvas,
        arguments: [BROWSER_VIEW_SWITCH],
        noExitRuntime: false,
        mainScriptUrlOrBlob,
        locateFile: (path) => new URL(path, moduleUrl).href,
        print: (line) => this.#stdout.push(String(line)),
        printErr: (line) => this.#stderr.push(String(line)),
        onRuntimeInitialized: () => this.#markRuntimeInitialized(),
        onAbort: (reason) => {
          this.#abort = String(reason);
          this.#recordFatal(`abort: ${this.#abort}`);
        },
        onExit: (code) => this.#reportRuntimeExit(code),
      });
      // Emscripten's resolved factory is also a runtime-ready point. Retain
      // the callback signal above where the generated loader exposes it.
      this.#markRuntimeInitialized();
      module.chromiumWasmHostBridge = globalThis.__chromiumWasmHostBridgeV1;

      const deadline = runStartedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("BrowserView structural smoke did not exit before timeout");
      }
      // Let the host event queue surface any trailing canvas or worker error
      // before a clean browser result is accepted.
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#releaseWindowErrors();
    }
  }
}

function validateBrowserViewSmokeResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.m6GateComplete === false, "structural smoke claims M6 complete");
  require(result.runtimeExitCode === BROWSER_VIEW_EXIT_CODE,
          `unexpected runtime exit ${String(result.runtimeExitCode)}`);
  require(result.processExitCode === null ||
              result.processExitCode === BROWSER_VIEW_EXIT_CODE,
          "bridge process exit disagrees with runtime exit");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocused === true, "canvas focus was lost");
  require(result.browserViewMarkerObserved === true,
          "BrowserView smoke marker is absent");
  require(result.abort === null, "runtime aborted");
  require(Array.isArray(result.fatalErrors) && result.fatalErrors.length === 0,
          "host recorded a fatal error");
  require(Array.isArray(result.windowErrors) && result.windowErrors.length === 0,
          "host recorded a window error");
  require(Array.isArray(result.unhandledRejections) &&
              result.unhandledRejections.length === 0,
          "host recorded an unhandled rejection");

  const frames = result.frameReports;
  require(Array.isArray(frames) && frames.length >= 1,
          "no BrowserView canvas frame was reported");
  let previousId = 0;
  let lastFrame = null;
  if (Array.isArray(frames)) {
    for (const frame of frames) {
      require(isFrameReport(frame), "frame metadata is invalid");
      require(frame?.id > previousId, "frame IDs are not monotonic");
      previousId = frame?.id || previousId;
      lastFrame = frame;
    }
  }
  const readinessReports = result.readinessReports;
  require(Array.isArray(readinessReports) && readinessReports.length >= 1,
          "no readiness report was delivered");
  require(Array.isArray(readinessReports) &&
              readinessReports.every(isReadinessReport),
          "readiness report metadata is invalid");
  require(isReadinessReport(result.readiness), "readiness metadata is invalid");
  require(result.readiness?.surfaceReady === true,
          "surface readiness was not reported");
  require(Array.isArray(readinessReports) &&
              readinessReports.some((report) => report.surfaceReady === true),
          "surface readiness was never reported");
  const lastReadiness = Array.isArray(readinessReports) ?
      readinessReports.at(-1) : null;
  require(lastReadiness?.shellReady === result.readiness?.shellReady &&
              lastReadiness?.surfaceReady === result.readiness?.surfaceReady &&
              lastReadiness?.firstVisuallyNonEmptyPaint ===
                  result.readiness?.firstVisuallyNonEmptyPaint,
          "readiness does not match its last report");
  const focusReports = result.ozoneFocusReports;
  require(Array.isArray(focusReports), "Ozone focus history is missing");
  if (Array.isArray(focusReports)) {
    require(focusReports.every(isFocusReport), "Ozone focus metadata is invalid");
    require(focusReports.some((report) =>
      report.keyboardTargetPresent === true && report.active === true),
    "no active Ozone keyboard target was observed");
  }
  const backingStore = result.canvasBackingStore;
  require(backingStore && Number.isSafeInteger(backingStore.width) &&
              Number.isSafeInteger(backingStore.height),
          "canvas backing-store metadata is invalid");
  require(lastFrame !== null && backingStore?.width === lastFrame?.width &&
              backingStore?.height === lastFrame?.height,
          "canvas backing store does not match the last frame");

  result.failedChecks = failures;
  if (failures.length > 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserViewSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-view-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-view-status");
  renderVersions(document.querySelector("#versions"), versions);

  const host = new ChromiumWasmBrowserViewSmokeHost(canvas, versions);
  const result = validateBrowserViewSmokeResult(await host.run(
      `/__m6_browser_view__/artifacts/${moduleName}.js`, timeoutMs));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(
      `/__m6_browser_view__/result/${encodeURIComponent(token)}`, {
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

export const chromeWasmBrowserViewSmokeContract = Object.freeze({
  BROWSER_VIEW_CASE,
  BROWSER_VIEW_EXIT_CODE,
  BROWSER_VIEW_MARKER,
  BROWSER_VIEW_SCOPE,
  BROWSER_VIEW_SWITCH,
  HOST_PROTOCOL,
});

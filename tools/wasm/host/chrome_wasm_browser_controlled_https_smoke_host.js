// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This host starts the dedicated controlled-HTTPS Chrome executable.  The
// fixture URL reaches Chromium only through the browser's restricted address
// field, while this outer page supplies only the WISP transport configuration
// before Emscripten creates the application.
const HOST_PROTOCOL = 1;
const CASE = "browser_controlled_https_m6";
const SCOPE = "chrome-views-wisp-controlled-https";
const SWITCH = "--wasm-browser-controlled-https-smoke";
const URL_SWITCH = "--wasm-browser-controlled-https-url";
const READY_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:READY";
const NAVIGATED_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:NAVIGATED";
const PASS_MARKER = "CHROMIUM_WASM_M6_CONTROLLED_HTTPS:PASS";
const WISP_CONFIGURATION_VERSION = 1;
const WISP_SUBPROTOCOL = "wisp";
const FIXTURE_HOSTNAME = "a.test";
const FIXTURE_PATH = "/m5/m6-ui";
// This is intentionally the canonical default-HTTPS authority. The relay
// maps only the corresponding WISP CONNECT for a.test:443 to its private H2
// listener, leaving the visible browser address and screenshot deterministic.
const FIXTURE_URL = "https://a.test/m5/m6-ui";
const MAX_TIMEOUT_MS = 180000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_REPORT_HISTORY = 128;
const PNG_DATA_URL_PREFIX = "data:image/png;base64,";
const MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024;
const MAX_SCREENSHOT_BASE64_LENGTH =
    Math.ceil(MAX_SCREENSHOT_BYTES / 3) * 4;
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

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error("invalid controlled-HTTPS versions: " + String(error));
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], "version " + field);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("controlled-HTTPS host has no versions element");
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
  const raw = asNonemptyString(value, "controlled-HTTPS fixture URL");
  let url;
  try {
    url = new URL(raw);
  } catch (_) {
    throw new Error("controlled-HTTPS fixture URL is invalid");
  }
  if (url.protocol !== "https:" || url.hostname !== FIXTURE_HOSTNAME ||
      url.pathname !== FIXTURE_PATH || url.search || url.hash ||
      url.username || url.password || url.port !== "" ||
      url.href !== FIXTURE_URL) {
    throw new Error("controlled-HTTPS fixture URL violates the fixture policy");
  }
  return url;
}

function decodePngDataUrl(dataUrl) {
  if (typeof dataUrl !== "string" || !dataUrl.startsWith(PNG_DATA_URL_PREFIX)) {
    throw new Error("canvas did not produce a PNG data URL");
  }
  const dataBase64 = dataUrl.slice(PNG_DATA_URL_PREFIX.length);
  if (!dataBase64 || dataBase64.length > MAX_SCREENSHOT_BASE64_LENGTH ||
      !BASE64_PATTERN.test(dataBase64)) {
    throw new Error("canvas PNG data URL is outside the bounded base64 contract");
  }
  const binary = atob(dataBase64);
  if (binary.length < 8 || binary.length > MAX_SCREENSHOT_BYTES ||
      binary.charCodeAt(0) !== 0x89 || binary.charCodeAt(1) !== 0x50 ||
      binary.charCodeAt(2) !== 0x4e || binary.charCodeAt(3) !== 0x47 ||
      binary.charCodeAt(4) !== 0x0d || binary.charCodeAt(5) !== 0x0a ||
      binary.charCodeAt(6) !== 0x1a || binary.charCodeAt(7) !== 0x0a) {
    throw new Error("canvas PNG data URL is invalid");
  }
  return dataBase64;
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
  const endpointText = asNonemptyString(value, "controlled-HTTPS WISP endpoint");
  let endpoint;
  try {
    endpoint = new URL(endpointText);
  } catch (_) {
    throw new Error("controlled-HTTPS WISP endpoint is invalid");
  }
  const port = Number(endpoint.port);
  if ((endpoint.protocol !== "ws:" && endpoint.protocol !== "wss:") ||
      !isLoopbackHostname(endpoint.hostname) || endpoint.username ||
      endpoint.password || endpoint.search || endpoint.hash ||
      endpoint.pathname !== "/wisp/" || endpoint.port === "" ||
      !Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("controlled-HTTPS WISP endpoint violates the transport policy");
  }
  return Object.freeze({
    version: WISP_CONFIGURATION_VERSION,
    endpoint: endpoint.href,
    subprotocol: WISP_SUBPROTOCOL,
  });
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

function isCapturedPngScreenshot(value) {
  if (!value || typeof value !== "object" ||
      value.mimeType !== "image/png" ||
      typeof value.dataBase64 !== "string" ||
      !Number.isSafeInteger(value.width) || value.width < 1 ||
      value.width > MAX_FRAME_DIMENSION || !Number.isSafeInteger(value.height) ||
      value.height < 1 || value.height > MAX_FRAME_DIMENSION ||
      !Number.isSafeInteger(value.frameId) || value.frameId < 1 ||
      !Number.isFinite(value.timestampMs) || value.timestampMs < 0 ||
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

class ChromiumWasmBrowserControlledHttpsSmokeHost {
  #canvas;
  #versions;
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
  #runtimeExitCode = null;
  #processExitCode = null;
  #abort = null;
  #factorySettled = false;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #errorHandler;
  #rejectionHandler;
  #readyMarkerObserved = false;
  #navigatedMarkerObserved = false;
  #frameIdAtNavigatedMarker = 0;
  #navigatedMarkerObservationSequence = 0;
  #postNavigatedFrameObserved = false;
  #firstVisuallyNonEmptyPaintReportObserved = false;
  #firstVisuallyNonEmptyPaintObservationSequence = 0;
  #targetFirstVisuallyNonEmptyPaintSignalObserved = false;
  #targetFirstVisuallyNonEmptyPaintSignalObservationSequence = 0;
  #postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved = false;
  #firstEligibleScreenshotFrameId = 0;
  #screenshotCaptureAttempted = false;
  #screenshot = null;
  #observationSequence = 0;
  #passMarkerObserved = false;
  #wispConfigured = false;
  #runtimeArgumentsConfigured = false;
  #configurationPrecededFactory = false;

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("controlled-HTTPS smoke requires a canvas");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
  }

  #recordOutput(value) {
    const text = String(value);
    if (text.includes(READY_MARKER)) {
      this.#readyMarkerObserved = true;
    }
    if (text.includes(NAVIGATED_MARKER)) {
      if (this.#navigatedMarkerObserved) {
        this.#recordFatal("controlled-HTTPS NAVIGATED marker was reported twice");
      } else {
        this.#navigatedMarkerObserved = true;
        this.#frameIdAtNavigatedMarker = this.#frameReports.at(-1)?.id || 0;
        this.#navigatedMarkerObservationSequence =
            ++this.#observationSequence;
      }
    }
    if (text.includes(PASS_MARKER)) {
      this.#passMarkerObserved = true;
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
    if (!Number.isSafeInteger(code)) {
      this.#recordFatal("runtime exit is not an integer");
      return;
    }
    if (this.#runtimeExitCode !== null) {
      this.#recordFatal("runtime reported multiple exits");
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
        throw new Error("process exit was reported more than once");
      }
      this.#processExitCode = report.exitCode;
    } catch (error) {
      this.#recordFatal("invalid process-exit report: " + String(error));
    }
  }

  #captureScreenshotForFirstEligibleFrame(report, observationSequence) {
    if (this.#screenshotCaptureAttempted) {
      return;
    }
    this.#screenshotCaptureAttempted = true;
    this.#firstEligibleScreenshotFrameId = report.id;
    try {
      // chromium_wasm_present_frame copies the compositor pixels into this
      // canvas before reportFrame runs. Take the synchronous snapshot here so
      // it is exactly the first presented frame observed after both the C++
      // NAVIGATED marker and the verified target-FVP protocol signal.
      const dataBase64 = decodePngDataUrl(this.#canvas.toDataURL("image/png"));
      this.#screenshot = {
        mimeType: "image/png",
        dataBase64,
        width: report.width,
        height: report.height,
        frameId: report.id,
        timestampMs: report.timestampMs,
        observationSequence,
      };
    } catch (error) {
      this.#recordFatal("failed to capture controlled-HTTPS screenshot: " +
          String(error));
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
        throw new Error("frame IDs must increase");
      }
      // chromium_wasm_present_frame copies into the host canvas before this
      // callback. This check rejects a metadata-only presentation claim before
      // the screenshot capture below reads the canvas.
      if (this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
        throw new Error("canvas backing store differs from the frame report");
      }
      const observationSequence = ++this.#observationSequence;
      appendBounded(this.#frameReports, {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      });
      const isPostNavigatedFrame = this.#navigatedMarkerObserved &&
          report.id > this.#frameIdAtNavigatedMarker &&
          observationSequence > this.#navigatedMarkerObservationSequence;
      if (isPostNavigatedFrame) {
        this.#postNavigatedFrameObserved = true;
      }
      const isFirstEligibleScreenshotFrame = isPostNavigatedFrame &&
          this.#targetFirstVisuallyNonEmptyPaintSignalObserved &&
          observationSequence >
              this.#targetFirstVisuallyNonEmptyPaintSignalObservationSequence;
      if (isFirstEligibleScreenshotFrame) {
        this.#postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved = true;
        this.#captureScreenshotForFirstEligibleFrame(report, observationSequence);
      }
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
      const observationSequence = ++this.#observationSequence;
      this.#readiness = {
        shellReady: report.shellReady,
        surfaceReady: report.surfaceReady,
        firstVisuallyNonEmptyPaint: report.firstVisuallyNonEmptyPaint,
      };
      if (report.firstVisuallyNonEmptyPaint &&
          !this.#firstVisuallyNonEmptyPaintReportObserved) {
        this.#firstVisuallyNonEmptyPaintReportObserved = true;
        this.#firstVisuallyNonEmptyPaintObservationSequence =
            observationSequence;
      }
      appendBounded(this.#readinessReports, this.#readiness);
    } catch (error) {
      this.#recordFatal("invalid readiness report: " + String(error));
    }
  }

  #reportControlledHttpsTargetFvp(value) {
    try {
      const report = asReport(value, "controlled-HTTPS target FVP report");
      if (report.protocol !== HOST_PROTOCOL ||
          Object.keys(report).length !== 1) {
        throw new Error("controlled-HTTPS target FVP report is invalid");
      }
      if (this.#targetFirstVisuallyNonEmptyPaintSignalObserved) {
        throw new Error("controlled-HTTPS target FVP was reported twice");
      }
      const observationSequence = ++this.#observationSequence;
      if (!this.#navigatedMarkerObserved ||
          observationSequence <= this.#navigatedMarkerObservationSequence) {
        throw new Error("controlled-HTTPS target FVP preceded NAVIGATED");
      }
      this.#targetFirstVisuallyNonEmptyPaintSignalObserved = true;
      this.#targetFirstVisuallyNonEmptyPaintSignalObservationSequence =
          observationSequence;
    } catch (error) {
      this.#recordFatal("invalid controlled-HTTPS target FVP report: " +
          String(error));
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
        throw new Error("text-input state is invalid");
      }
      appendBounded(this.#textInputStates, {
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      });
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
        throw new Error("text-input delivery is invalid");
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

  #reportCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType) ||
          report.cursorType < -1 || report.cursorType > 53) {
        throw new Error("cursor report is invalid");
      }
      const cursor = report.cursorType === 2 ? "pointer" :
        report.cursorType === 3 ? "text" : "default";
      this.#canvas.style.cursor = cursor;
      if (this.#canvas.style.cursor !== cursor) {
        throw new Error("canvas rejected the cursor style");
      }
      appendBounded(this.#cursorReports, {
        cursorType: report.cursorType,
        cssCursor: cursor,
      });
      return true;
    } catch (error) {
      this.#recordFatal("invalid Ozone cursor report: " + String(error));
      return false;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("controlled-HTTPS host bridge is already installed");
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
      reportControlledHttpsTargetFvp(report) {
        host.#reportControlledHttpsTargetFvp(report);
      },
      reportOzoneFocusState(report) {
        host.#reportFocus(report);
      },
      reportOzoneTextInputState(report) {
        host.#reportTextInputState(report);
      },
      reportOzoneTextInputDelivery(report) {
        host.#reportTextInputDelivery(report);
      },
      reportOzoneCursor(report) {
        return host.#reportCursor(report);
      },
    });
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
      controlledHttps: {
        wispConfigured: this.#wispConfigured,
        runtimeArgumentsConfigured: this.#runtimeArgumentsConfigured,
        configurationPrecededFactory: this.#configurationPrecededFactory,
        readyMarkerObserved: this.#readyMarkerObserved,
        navigatedMarkerObserved: this.#navigatedMarkerObserved,
        frameIdAtNavigatedMarker: this.#frameIdAtNavigatedMarker,
        navigatedMarkerObservationSequence:
            this.#navigatedMarkerObservationSequence,
        postNavigatedFrameObserved: this.#postNavigatedFrameObserved,
        firstVisuallyNonEmptyPaintReportObserved:
            this.#firstVisuallyNonEmptyPaintReportObserved,
        firstVisuallyNonEmptyPaintObservationSequence:
            this.#firstVisuallyNonEmptyPaintObservationSequence,
        targetFirstVisuallyNonEmptyPaintSignalObserved:
            this.#targetFirstVisuallyNonEmptyPaintSignalObserved,
        targetFirstVisuallyNonEmptyPaintSignalObservationSequence:
            this.#targetFirstVisuallyNonEmptyPaintSignalObservationSequence,
        postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved:
            this.#postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved,
        firstEligibleScreenshotFrameId: this.#firstEligibleScreenshotFrameId,
        screenshotCaptureAttempted: this.#screenshotCaptureAttempted,
        screenshotFrameId: this.#screenshot?.frameId || 0,
        screenshotObservationSequence:
            this.#screenshot?.observationSequence || 0,
        passMarkerObserved: this.#passMarkerObserved,
      },
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
      screenshot: this.#screenshot,
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

  async run(modulePath, timeoutMs, wispEndpoint, fixtureUrl) {
    const startedAt = performance.now();
    try {
      if (!crossOriginIsolated || typeof SharedArrayBuffer !== "function") {
        throw new Error("controlled-HTTPS host requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("controlled-HTTPS timeout is out of range");
      }
      const controlledUrl = parseFixtureUrl(fixtureUrl);
      const wispConfiguration = parseWispConfiguration(wispEndpoint);
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("controlled-HTTPS module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("controlled-HTTPS canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();

      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error("module request returned HTTP " + response.status);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("controlled-HTTPS module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("controlled-HTTPS loader has no default factory");
      }

      const host = this;
      const moduleOptions = {
        arguments: [
          SWITCH,
          URL_SWITCH + "=" + controlledUrl.href,
        ],
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
        onRuntimeInitialized() {
          host.#runtimeInitialized = true;
        },
        onAbort(reason) {
          host.#abort = String(reason);
          host.#recordFatal("abort: " + host.#abort);
        },
        onExit(code) {
          host.#reportRuntimeExit(Number(code));
        },
      };
      // The network bridge reads this option while Chromium starts.  It must
      // be present before the Emscripten factory creates the application.
      moduleOptions.chromiumWasmWisp = wispConfiguration;
      this.#wispConfigured = true;
      this.#runtimeArgumentsConfigured = true;
      this.#configurationPrecededFactory =
          this.#wispConfigured && this.#runtimeArgumentsConfigured;
      const factoryPromise = namespace.default(moduleOptions).then((module) => {
        this.#factorySettled = true;
        this.#runtimeInitialized = true;
        module.chromiumWasmHostBridge = globalThis.__chromiumWasmHostBridgeV1;
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
        throw new Error("controlled-HTTPS smoke did not exit before timeout");
      }
      await Promise.race([factoryPromise, delay(250)]);
      if (!this.#factorySettled) {
        throw new Error("controlled-HTTPS factory did not settle after exit");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
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
  require(result.m6GateComplete === false,
      "controlled-HTTPS smoke claims the M6 gate is complete");
  require(result.runtimeExitCode === 0, "runtime did not exit zero");
  require(result.processExitCode === null || result.processExitCode === 0,
      "bridge process exit disagrees with the runtime");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.factorySettled === true, "factory did not settle");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocused === true, "canvas focus was lost");
  require(result.abort === null, "runtime aborted");
  require(Array.isArray(result.fatalErrors) && result.fatalErrors.length === 0,
      "host recorded a fatal error");
  require(Array.isArray(result.windowErrors) && result.windowErrors.length === 0,
      "host recorded a window error");
  require(Array.isArray(result.unhandledRejections) &&
              result.unhandledRejections.length === 0,
          "host recorded an unhandled rejection");
  require(result.controlledHttps?.wispConfigured === true,
      "WISP was not configured");
  require(result.controlledHttps?.runtimeArgumentsConfigured === true,
      "controlled-HTTPS runtime arguments were not configured");
  require(result.controlledHttps?.configurationPrecededFactory === true,
      "WISP configuration did not precede the module factory");
  require(result.controlledHttps?.readyMarkerObserved === true,
      "controlled-HTTPS READY marker is absent");
  require(result.controlledHttps?.navigatedMarkerObserved === true,
      "controlled-HTTPS NAVIGATED marker is absent");
  require(result.controlledHttps?.postNavigatedFrameObserved === true,
      "no canvas frame followed the controlled-HTTPS NAVIGATED marker");
  require(result.controlledHttps?.firstVisuallyNonEmptyPaintReportObserved ===
              true,
          "controlled-HTTPS first visually non-empty paint report is absent");
  require(result.controlledHttps
              ?.targetFirstVisuallyNonEmptyPaintSignalObserved === true,
          "controlled-HTTPS target first visually non-empty paint signal is " +
              "absent");
  require(result.controlledHttps
              ?.postNavigatedFrameAfterFirstVisuallyNonEmptyPaintObserved ===
              true,
          "no post-NAVIGATED canvas frame followed the first visually non-empty " +
              "paint report");
  require(result.controlledHttps?.screenshotCaptureAttempted === true,
      "the first eligible screenshot capture was not attempted");
  require(Number.isSafeInteger(result.controlledHttps
              ?.firstEligibleScreenshotFrameId) &&
              result.controlledHttps.firstEligibleScreenshotFrameId >
                  result.controlledHttps.frameIdAtNavigatedMarker,
          "the first eligible screenshot frame is invalid");
  require(result.controlledHttps?.screenshotFrameId ===
              result.controlledHttps?.firstEligibleScreenshotFrameId,
          "the screenshot was not captured from the first eligible frame");
  require(Number.isSafeInteger(result.controlledHttps
              ?.navigatedMarkerObservationSequence) &&
              Number.isSafeInteger(result.controlledHttps
                  ?.targetFirstVisuallyNonEmptyPaintSignalObservationSequence) &&
              result.controlledHttps
                      .targetFirstVisuallyNonEmptyPaintSignalObservationSequence >
                  result.controlledHttps.navigatedMarkerObservationSequence,
          "the target first visually non-empty paint signal was not observed " +
              "after NAVIGATED");
  require(Number.isSafeInteger(result.controlledHttps
              ?.screenshotObservationSequence) &&
              result.controlledHttps.screenshotObservationSequence >
                  result.controlledHttps.navigatedMarkerObservationSequence &&
              result.controlledHttps.screenshotObservationSequence >
                  result.controlledHttps
                      .targetFirstVisuallyNonEmptyPaintSignalObservationSequence,
          "the screenshot was not observed after NAVIGATED and target FVP " +
              "signal");
  require(isCapturedPngScreenshot(result.screenshot),
      "controlled-HTTPS PNG screenshot evidence is invalid");
  require(result.screenshot?.frameId === result.controlledHttps?.screenshotFrameId,
      "screenshot frame ID does not match capture evidence");
  require(result.screenshot?.observationSequence ===
              result.controlledHttps?.screenshotObservationSequence,
          "screenshot observation sequence does not match capture evidence");
  require(result.controlledHttps?.passMarkerObserved === true,
      "controlled-HTTPS PASS marker is absent");
  require(Array.isArray(result.frameReports) && result.frameReports.length >= 1,
      "no canvas frame was reported");
  require(isReadinessReport(result.readiness),
      "readiness metadata is invalid");
  require(result.readiness?.surfaceReady === true,
      "surface readiness was not reported");
  require(result.readiness?.firstVisuallyNonEmptyPaint === true,
      "first visually non-empty paint was not reported");
  require(Array.isArray(result.readinessReports) &&
              result.readinessReports.some((report) =>
                isReadinessReport(report) && report.surfaceReady === true),
          "surface readiness was never reported");
  require(Array.isArray(result.readinessReports) &&
              result.readinessReports.some((report) =>
                isReadinessReport(report) &&
                report.firstVisuallyNonEmptyPaint === true),
          "first visually non-empty paint was never reported");
  require(Array.isArray(result.ozoneFocusReports) &&
              result.ozoneFocusReports.some((report) =>
                isFocusReport(report) && report.keyboardTargetPresent === true &&
                report.active === true),
          "no active Ozone keyboard target was observed");
  result.failedChecks = failures;
  if (failures.length > 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

function resultForDisplay(result) {
  if (!result?.screenshot || typeof result.screenshot !== "object" ||
      typeof result.screenshot.dataBase64 !== "string") {
    return result;
  }
  return {
    ...result,
    screenshot: {
      ...result.screenshot,
      dataBase64: "<omitted from host diagnostics>",
    },
  };
}

export async function runChromeWasmBrowserControlledHttpsSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "60000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-controlled-https-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-controlled-https-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("controlled-HTTPS page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserControlledHttpsSmokeHost(canvas, versions);
  const result = validateResult(await host.run(
      location.pathname.replace(/\/$/, "") + "/artifacts/" + moduleName + ".js",
      timeoutMs, query.get("wispEndpoint"), query.get("fixtureUrl")));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(resultForDisplay(result), null, 2);
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
    throw new Error("result upload returned HTTP " + response.status);
  }
  return result;
}

export const chromeWasmBrowserControlledHttpsSmokeContract = Object.freeze({
  CASE,
  FIXTURE_PATH,
  FIXTURE_URL,
  HOST_PROTOCOL,
  NAVIGATED_MARKER,
  PASS_MARKER,
  READY_MARKER,
  SCOPE,
  SWITCH,
  URL_SWITCH,
  WISP_CONFIGURATION_VERSION,
});

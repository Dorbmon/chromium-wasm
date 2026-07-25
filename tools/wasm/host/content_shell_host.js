// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const HOST_PROTOCOL = 1;
const M3_CASE = "content_shell_m3";
const FIXTURE_FONT_MARKER = "__M3_AHEM_WOFF2_BASE64__";
const REQUIRED_RUNTIME_MS = 3000;
const REQUIRED_TIMER_TICKS = 60;
const REQUIRED_ANIMATION_FRAMES = 30;
const MAXIMUM_TIMER_GAP_MS = 250;
const DEFAULT_RUNTIME_REGISTRATION_TIMEOUT_MS = 15000;
const DEFAULT_WIDTH = 800;
const DEFAULT_HEIGHT = 600;

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
  #module = null;
  #lifecycle = "new";
  #runtimeInitialized = false;
  #fatalErrors = [];
  #reportedReadiness = {};
  #navigation = {};
  #pageProbe = {};
  #frame = null;
  #versions;
  #logs = {host: [], stdout: [], stderr: []};
  #heartbeatStartTime;
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

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("M3 host requires a canvas");
    }
    if (activeHost) {
      throw new Error("only one M3 host instance may be active");
    }
    this.#canvas = canvas;
    this.#versions = Object.freeze({
      chromium: normalizeVersion(versions.chromium),
      v8: normalizeVersion(versions.v8),
      emscripten: normalizeVersion(versions.emscripten),
      port: normalizeVersion(versions.port),
    });
    activeHost = this;

    this.#heartbeatStartTime = performance.now();
    this.#lastTimerTime = this.#heartbeatStartTime;
    this.#timerHandle = setInterval(() => {
      const now = performance.now();
      this.#maximumTimerGapMs = Math.max(
        this.#maximumTimerGapMs, now - this.#lastTimerTime);
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

  #heartbeat() {
    return {
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

    const namespace = await import(resolvedModule.href);
    if (typeof namespace.default !== "function") {
      throw new Error("M3 module loader has no default factory export");
    }
    const moduleOptions = {
      canvas: this.#canvas,
      noExitRuntime: true,
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
        this.#recordHost(`runtime:exit:${Number(code)}`);
      },
    };
    this.#module = await namespace.default(moduleOptions);
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
    if (
      !Number.isFinite(devicePixelRatio) ||
      devicePixelRatio <= 0 ||
      devicePixelRatio > 8
    ) {
      throw new Error("devicePixelRatio is out of range");
    }
    this.#canvas.width = width;
    this.#canvas.height = height;
    this.#canvas.style.width = `${width}px`;
    this.#canvas.style.height = `${height}px`;
    const result = this.#callExport(
      "chromium_wasm_host_resize",
      "number",
      ["number", "number", "number"],
      [width, height, devicePixelRatio],
    );
    if (Number(result) !== 1) {
      throw new Error(`runtime rejected resize with status ${String(result)}`);
    }
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
    if (Number(result) !== 1) {
      throw new Error(
        `runtime rejected data: navigation with status ${String(result)}`);
    }
    this.#recordHost("navigation:requested:data");
    return {ok: true, scheme: "data"};
  }

  async injectInput(event) {
    // M3 proves presentation and liveness. Event forwarding is the M4 gate.
    return {
      ok: false,
      code: "INPUT_UNSUPPORTED_UNTIL_M4",
      milestone: "M4",
      eventType:
        event && typeof event.type === "string" ? event.type : "unknown",
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
    const ready =
      this.#runtimeInitialized &&
      this.#reportedReadiness.shellReady === true &&
      this.#reportedReadiness.surfaceReady === true &&
      this.#navigation.committed === true &&
      this.#reportedReadiness.firstVisuallyNonEmptyPaint === true &&
      this.#pageProbe.ready === true &&
      Number.isFinite(pageTimerTicks) &&
      pageTimerTicks >= 3 &&
      Boolean(frameMatchesCanvas) &&
      heartbeat.elapsedMs >= REQUIRED_RUNTIME_MS &&
      heartbeat.timerDelta >= REQUIRED_TIMER_TICKS &&
      heartbeat.animationFrameDelta >= REQUIRED_ANIMATION_FRAMES &&
      heartbeat.maxTimerGapMs <= MAXIMUM_TIMER_GAP_MS &&
      this.#fatalErrors.length === 0;
    return {
      protocol: HOST_PROTOCOL,
      ready,
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
      fatalErrors: clone(this.#fatalErrors),
      heartbeat,
    };
  }

  async logs() {
    return clone(this.#logs);
  }

  async shutdown() {
    this.#requireRunning("shutdown");
    const result = this.#callExport(
      "chromium_wasm_host_shutdown", "number", [], []);
    if (Number(result) !== 1) {
      throw new Error(
        `runtime rejected shutdown with status ${String(result)}`);
    }
    this.#lifecycle = "shutdown";
    this.#recordHost("shutdown:accepted");
    this.#stopHeartbeat();
    removeEventListener("error", this.#errorHandler);
    removeEventListener("unhandledrejection", this.#rejectionHandler);
    activeHost = null;
    return {ok: true, accepted: true};
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
    } catch (error) {
      this._reportFatal(`invalid navigation report: ${String(error)}`);
    }
  }

  _reportPageProbe(value) {
    try {
      const report = asReport(value, "page probe");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.fixture !== "chromium-wasm-m3-static-v1"
      ) {
        throw new Error("page probe identity mismatch");
      }
      this.#pageProbe = clone(report);
    } catch (error) {
      this._reportFatal(`invalid page probe: ${String(error)}`);
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
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.ready) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.ready) {
      throw new Error(
        `M3 readiness timeout: ${JSON.stringify(readiness)}`);
    }

    const screenshot = await host.requestScreenshot();
    const inputResult = await host.injectInput({
      type: "pointerDown",
      x: 16,
      y: 16,
      button: 0,
    });
    const heartbeat = readiness.heartbeat;
    const logsBeforeShutdown = await host.logs();
    const shutdown = await host.shutdown();
    const logsAfterShutdown = await host.logs();
    const logs = {
      host: logsAfterShutdown.host,
      stdout: logsBeforeShutdown.stdout,
      stderr: logsBeforeShutdown.stderr,
    };

    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      readiness: readiness.ready === true,
      inputUnsupported:
        inputResult.ok === false &&
        inputResult.code === "INPUT_UNSUPPORTED_UNTIL_M4" &&
        inputResult.milestone === "M4",
      screenshot:
        screenshot.mimeType === "image/png" &&
        screenshot.width === DEFAULT_WIDTH &&
        screenshot.height === DEFAULT_HEIGHT &&
        screenshot.dataBase64.length > 0,
      shutdown: shutdown.ok === true,
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
        result.readiness = await host.readiness();
        result.heartbeat = result.readiness.heartbeat;
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
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

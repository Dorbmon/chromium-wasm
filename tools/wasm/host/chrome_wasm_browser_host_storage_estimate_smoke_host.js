// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {ChromiumWasmOuterOriginStorageEstimate} from "./chrome_wasm_storage_estimate.js";

// This host owns only the outer page's async navigator.storage.estimate()
// call and fixed smoke acknowledgements. The C++ lifecycle owns the fixed
// chrome://settings URL, WebUI inspection, snapshot comparison, and shutdown.
const HOST_PROTOCOL = 1;
const CASE = "browser_host_storage_estimate_m7";
const SCOPE = "outer-origin-estimate-native-settings-webui-later-frame";
const SWITCH = "--wasm-browser-host-storage-estimate-smoke";
const READY_MARKER = "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:READY";
const NAVIGATED_MARKER =
    "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:SETTINGS_NAVIGATED";
const PASS_MARKER = "CHROMIUM_WASM_M7_HOST_STORAGE_ESTIMATE:PASS";
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
    throw new Error(`invalid storage-estimate versions: ${String(error)}`);
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

function validateResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.runtimeExitCode === 0, "runtime did not close normally");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
      "host recorded an unhandled rejection");
  require(result.readyObserved === true, "native storage smoke was not ready");
  require(result.storageResult?.status === "available",
      "outer-origin estimate was not available");
  require(result.storageResult?.delivered === true,
      "outer-origin estimate was not accepted by C++");
  require(result.storageCheckQueued === true,
      "fixed storage-result check was not queued");
  require(result.storageCheckAccepted === true,
      "fixed storage-result check was not accepted");
  require(result.settingsNavigatedObserved === true,
      "native Settings navigation was not observed");
  require(result.settingsPresentationQueued === true,
      "later-frame presentation acknowledgement was not queued");
  require(result.settingsPresentationAccepted === true,
      "later-frame presentation acknowledgement was not accepted");
  require(result.passObserved === true, "native storage smoke did not pass");
  require(result.fixedOrdinals.join(",") === "1,2",
      "fixed smoke ordinals are not exactly 1,2");
  require(Number.isInteger(result.navigationMarkerFrameId) &&
      Number.isInteger(result.frameIdAfterNavigation) &&
      result.frameIdAfterNavigation > result.navigationMarkerFrameId,
  "Settings presentation lacks a strictly later canvas frame");
  require(result.frameReports.length >= 2,
      "host did not record enough compositor frames");
  if (failures.length !== 0) {
    result.status = "fail";
    result.failedChecks = failures;
  }
  return result;
}

class ChromiumWasmBrowserHostStorageEstimateSmokeHost {
  #canvas;
  #versions;
  #module = null;
  #storageEstimate = null;
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
  #readiness = null;
  #readinessReports = [];
  #readyObserved = false;
  #settingsNavigatedObserved = false;
  #passObserved = false;
  #storageResult = null;
  #storageCheckQueued = false;
  #storageCheckAccepted = false;
  #settingsPresentationQueued = false;
  #settingsPresentationAccepted = false;
  #fixedOrdinals = [];
  #navigationMarkerFrameId = null;
  #frameIdAfterNavigation = null;
  #errorHandler;
  #rejectionHandler;

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("storage-estimate smoke requires a canvas");
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
      this.#recordFatal(`invalid runtime exit: ${String(code)}`);
      return;
    }
    this.#runtimeExitCode = code;
    this.#storageEstimate?.dispose();
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process-exit report");
      if (!Number.isSafeInteger(report.exitCode) ||
          this.#processExitCode !== null) {
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
      this.#maybeQueueSettingsPresentation(report.id);
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

  #recordOutput(line) {
    if (line.includes(READY_MARKER)) {
      this.#readyObserved = true;
      this.#maybeQueueStorageCheck();
    }
    if (line.includes(NAVIGATED_MARKER)) {
      if (this.#settingsNavigatedObserved) {
        this.#recordFatal("storage smoke emitted Settings navigation twice");
        return;
      }
      this.#settingsNavigatedObserved = true;
      this.#navigationMarkerFrameId = this.#frameReports.at(-1)?.id ?? 0;
    }
    if (line.includes(PASS_MARKER)) {
      this.#passObserved = true;
    }
  }

  #recordStorageResult(report) {
    if (!report || !Number.isSafeInteger(report.generation) ||
        !["available", "unavailable", "error"].includes(report.status) ||
        typeof report.delivered !== "boolean" || this.#storageResult !== null) {
      this.#recordFatal("outer-origin storage result is invalid or duplicated");
      return;
    }
    this.#storageResult = {
      generation: report.generation,
      status: report.status,
      delivered: report.delivered,
    };
    this.#maybeQueueStorageCheck();
  }

  #maybeQueueStorageCheck() {
    if (!this.#readyObserved || !this.#storageResult ||
        this.#storageCheckQueued || this.#runtimeExitCode !== null) {
      return;
    }
    if (this.#storageResult.status !== "available" ||
        this.#storageResult.delivered !== true) {
      this.#recordFatal("outer-origin estimate was not accepted and available");
      return;
    }
    // `delivered` means C++ accepted and posted its immutable-state update to
    // the UI runner. This stage is posted only after that terminal callback;
    // FIFO on that same runner therefore makes the snapshot update precede
    // lifecycle's fixed Settings-navigation check. Defer the exported C ABI
    // call too: READY/storage reports can be observed while another sync host
    // import is active, and a nested reentry into Wasm would violate that ABI.
    this.#storageCheckQueued = true;
    setTimeout(() => {
      if (!this.#readyObserved || !this.#storageResult ||
          this.#storageResult.status !== "available" ||
          this.#storageResult.delivered !== true ||
          this.#runtimeExitCode !== null) {
        return;
      }
      try {
        const accepted = this.#module?.ccall(
            "chromium_wasm_browser_host_storage_estimate_check", "number",
            ["number"], [1]);
        this.#storageCheckAccepted = accepted === 1;
        this.#fixedOrdinals.push(1);
        if (!this.#storageCheckAccepted) {
          this.#recordFatal("storage-estimate fixed check was rejected");
        }
      } catch (_error) {
        this.#recordFatal("storage-estimate fixed check ABI failed");
      }
    }, 0);
  }

  #maybeQueueSettingsPresentation(frameId) {
    if (!this.#settingsNavigatedObserved ||
        this.#settingsPresentationQueued ||
        !Number.isInteger(this.#navigationMarkerFrameId) ||
        frameId <= this.#navigationMarkerFrameId || this.#runtimeExitCode !== null) {
      return;
    }
    // `reportFrame` is called by the synchronous present-frame host import.
    // Record admission now, then leave that import before reentering Wasm for
    // the fixed stage-two acknowledgement.
    this.#settingsPresentationQueued = true;
    setTimeout(() => {
      if (!this.#settingsNavigatedObserved ||
          !Number.isInteger(this.#navigationMarkerFrameId) ||
          frameId <= this.#navigationMarkerFrameId ||
          this.#runtimeExitCode !== null) {
        return;
      }
      try {
        const accepted = this.#module?.ccall(
            "chromium_wasm_browser_host_storage_estimate_presented", "number",
            ["number"], [2]);
        this.#settingsPresentationAccepted = accepted === 1;
        this.#frameIdAfterNavigation = frameId;
        this.#fixedOrdinals.push(2);
        if (!this.#settingsPresentationAccepted) {
          this.#recordFatal("storage-estimate presentation ABI was rejected");
        }
      } catch (_error) {
        this.#recordFatal("storage-estimate presentation ABI failed");
      }
    }, 0);
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("storage-estimate host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportOzoneFocusState(_report) {},
      reportOzoneCursor(_report) { return true; },
      reportOzoneTextInputState(_report) {},
      reportOzoneTextInputDelivery(_report) {},
      reportOzoneBrowserTextInputDelivery(_report) {},
      reportOzoneBrowserClipboardPasteDelivery(_report) {},
      requestOuterOriginStorageEstimate(report) {
        return host.#storageEstimate?.request(report) === true;
      },
    });
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied an invalid Module object");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#storageEstimate = new ChromiumWasmOuterOriginStorageEstimate({
      getModule: () => this.#module,
      recordFatal: (message) => this.#recordFatal(message),
      onResult: (report) => this.#recordStorageResult(report),
    });
  }

  #result(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m7GateComplete: false,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      readyObserved: this.#readyObserved,
      settingsNavigatedObserved: this.#settingsNavigatedObserved,
      passObserved: this.#passObserved,
      storageResult: this.#storageResult,
      storageCheckQueued: this.#storageCheckQueued,
      storageCheckAccepted: this.#storageCheckAccepted,
      settingsPresentationQueued: this.#settingsPresentationQueued,
      settingsPresentationAccepted: this.#settingsPresentationAccepted,
      fixedOrdinals: this.#fixedOrdinals,
      navigationMarkerFrameId: this.#navigationMarkerFrameId,
      frameIdAfterNavigation: this.#frameIdAfterNavigation,
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
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
        throw new Error("storage-estimate smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("storage-estimate timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("storage-estimate module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("storage-estimate canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("storage-estimate module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("storage-estimate loader has no default factory export");
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
      }).catch((_error) => {
        host.#recordFatal("storage-estimate module factory rejected");
      });

      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("storage-estimate smoke did not exit before timeout");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#storageEstimate?.dispose();
      this.#storageEstimate = null;
      this.#releaseWindowErrors();
    }
  }
}

export async function runChromeWasmBrowserHostStorageEstimateSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs"));
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-host-storage-estimate-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-host-storage-estimate-status");
  const versionElement = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement) || !(versionElement instanceof HTMLElement)) {
    throw new Error("storage-estimate smoke page is missing required elements");
  }
  renderVersions(versionElement, versions);
  const host = new ChromiumWasmBrowserHostStorageEstimateSmokeHost(canvas, versions);
  const result = validateResult(await host.run(
      `/__m7_browser_host_storage_estimate__/artifacts/${moduleName}.js`, timeoutMs));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(
      `/__m7_browser_host_storage_estimate__/result/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error(`storage-estimate result POST returned HTTP ${response.status}`);
  }
  return result;
}

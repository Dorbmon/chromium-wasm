// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This host is intentionally a one-shot semantic-DOM witness for one fixed
// Chromium WebContents AX snapshot. It reflects one fixed toggle's role,
// pressed state, and geometry, but does not receive updates, accept host
// input, retain arbitrary page text, synchronize focus, or route AX actions.
// It is not an accessibility implementation or a replacement for page
// semantics.
const HOST_PROTOCOL = 1;
const CASE = "browser_accessibility_snapshot_m8";
const SCOPE =
    "fixed-webcontents-ax-snapshot-passive-semantic-dom-with-toggle-state-and-bounds";
const SWITCH = "--wasm-browser-accessibility-snapshot-smoke";
const READY_MARKER = "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:READY";
const NAVIGATED_MARKER = "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:NAVIGATED";
const DELIVERED_MARKER = "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:DELIVERED";
const PASS_MARKER = "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:PASS";
const LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 64;
const EXPECTED_HEADING = "Chromium Wasm AX snapshot";
const EXPECTED_TEXT = "Static semantic text.";
const EXPECTED_CONTROL_NAME = "Chromium Wasm AX control";
const EXPECTED_CONTROL_BOUNDS = Object.freeze({
  height: 48,
  left: 64,
  top: 128,
  width: 192,
});
const EXPECTED_ROLE_MASK = 0xf;

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

function exactJsonEqual(left, right) {
  if (typeof left !== typeof right || left === null || right === null) {
    return left === right;
  }
  if (Array.isArray(left)) {
    return Array.isArray(right) && left.length === right.length &&
        left.every((value, index) => exactJsonEqual(value, right[index]));
  }
  if (typeof left === "object") {
    if (Array.isArray(right)) {
      return false;
    }
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return leftKeys.length === rightKeys.length &&
        leftKeys.every((key, index) => key === rightKeys[index] &&
            exactJsonEqual(left[key], right[key]));
  }
  return left === right;
}

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error(`invalid accessibility-snapshot versions: ${String(error)}`);
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

function countMarker(records, marker) {
  return records.filter((record) => record.includes(marker)).length;
}

function markerIndex(records, marker) {
  return records.findIndex((record) => record.includes(marker));
}

function validateResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.runtimeExitCode === 0, "runtime did not close normally");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
      "host recorded an unhandled rejection");
  require(result.readyObserved === true, "native accessibility smoke was not ready");
  require(result.navigatedObserved === true,
      "fixed accessibility document did not reach painted navigation");
  require(result.snapshotDelivered === true,
      "native AX snapshot was not delivered to the host");
  require(result.passObserved === true, "native accessibility smoke did not pass");
  require(result.lifecyclePassObserved === true,
      "Browser lifecycle did not close normally after the snapshot");
  require(result.semanticMirror?.heading === EXPECTED_HEADING,
      "semantic mirror heading is not the fixed AX value");
  require(result.semanticMirror?.text === EXPECTED_TEXT,
      "semantic mirror text is not the fixed AX value");
  require(result.semanticMirror?.roleMask === EXPECTED_ROLE_MASK,
      "semantic mirror role mask is invalid");
  require(result.semanticMirror?.controlName === EXPECTED_CONTROL_NAME,
      "semantic mirror control name is not the fixed AX value");
  require(result.semanticMirror?.controlPressed === true,
      "semantic mirror control pressed state is invalid");
  require(exactJsonEqual(result.semanticMirror?.controlBounds,
                         EXPECTED_CONTROL_BOUNDS),
      "semantic mirror control bounds are invalid");
  require(result.semanticMirror?.controlGeometryMatchesCanvas === true,
      "semantic mirror control geometry does not match the canvas");
  require(result.semanticMirror?.connected === true,
      "semantic mirror is not connected outside the canvas");
  require(result.semanticMirror?.passive === true,
      "semantic mirror unexpectedly accepts focus or input");
  require(Array.isArray(result.frameReports) && result.frameReports.length >= 1,
      "host did not record a compositor frame");
  require(result.readiness?.surfaceReady === true,
      "host did not observe a ready canvas surface");

  const stderr = result.stderr;
  const orderedMarkers = [
    READY_MARKER,
    NAVIGATED_MARKER,
    DELIVERED_MARKER,
    PASS_MARKER,
    LIFECYCLE_PASS_MARKER,
  ];
  const positions = [];
  for (const marker of orderedMarkers) {
    require(countMarker(stderr, marker) === 1,
        `native marker is not unique: ${marker}`);
    positions.push(markerIndex(stderr, marker));
  }
  require(positions.every((position) => position >= 0) &&
      positions.every((position, index) => index === 0 ||
          positions[index - 1] < position),
  "native accessibility markers are not ordered");

  if (failures.length !== 0) {
    result.status = "fail";
    result.failedChecks = failures;
  }
  return result;
}

class ChromiumWasmBrowserAccessibilitySnapshotSmokeHost {
  #canvas;
  #mirrorRoot;
  #versions;
  #module = null;
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
  #navigatedObserved = false;
  #snapshotDelivered = false;
  #passObserved = false;
  #lifecyclePassObserved = false;
  #semanticMirror = null;
  #errorHandler;
  #rejectionHandler;

  constructor(canvas, mirrorRoot, versions) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(mirrorRoot instanceof HTMLElement)) {
      throw new Error("accessibility snapshot smoke requires canvas and mirror root");
    }
    this.#canvas = canvas;
    this.#mirrorRoot = mirrorRoot;
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

  #recordOutput(text) {
    if (text.includes(READY_MARKER)) this.#readyObserved = true;
    if (text.includes(NAVIGATED_MARKER)) this.#navigatedObserved = true;
    if (text.includes(DELIVERED_MARKER)) this.#snapshotDelivered = true;
    if (text.includes(PASS_MARKER)) this.#passObserved = true;
    if (text.includes(LIFECYCLE_PASS_MARKER)) this.#lifecyclePassObserved = true;
  }

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code) || this.#runtimeExitCode !== null) {
      this.#recordFatal(`invalid runtime exit: ${String(code)}`);
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process-exit report");
      if (report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.exitCode) ||
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
      if ((previous && report.id <= previous.id) ||
          this.#canvas.width !== report.width || this.#canvas.height !== report.height) {
        throw new Error("frame sequence or canvas dimensions are invalid");
      }
      appendBounded(this.#frameReports, {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      });
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

  #reportAccessibilitySnapshot(value) {
    try {
      const report = asReport(value, "accessibility snapshot report");
      if (this.#semanticMirror !== null || report.protocol !== HOST_PROTOCOL ||
          report.source !== "fixed-webcontents-ax-snapshot" ||
          report.heading !== EXPECTED_HEADING || report.text !== EXPECTED_TEXT ||
          report.roleMask !== EXPECTED_ROLE_MASK ||
          !exactJsonEqual(report.control, {
            bounds: EXPECTED_CONTROL_BOUNDS,
            name: EXPECTED_CONTROL_NAME,
            pressed: true,
          })) {
        throw new Error("accessibility snapshot report is outside the fixed contract");
      }
      const surface = document.querySelector("#browser-surface");
      if (!(surface instanceof HTMLElement)) {
        throw new Error("accessibility snapshot surface is missing");
      }
      // This is the canvas drawing area, rather than its CSS border box. AX
      // bounds are in the Chromium surface coordinate system, so the mirror
      // must agree with this content origin before it can be reported as a
      // valid host-vs-AX geometry witness.
      const canvasBounds = this.#canvas.getBoundingClientRect();
      const canvasContentLeft = canvasBounds.left + this.#canvas.clientLeft;
      const canvasContentTop = canvasBounds.top + this.#canvas.clientTop;
      const controlBoundsAreWithinCanvas =
          report.control.bounds.left >= 0 && report.control.bounds.top >= 0 &&
          report.control.bounds.left + report.control.bounds.width <=
              this.#canvas.clientWidth &&
          report.control.bounds.top + report.control.bounds.height <=
              this.#canvas.clientHeight;
      if (!controlBoundsAreWithinCanvas) {
        throw new Error("validated AX bounds are outside the canvas content box");
      }
      this.#mirrorRoot.replaceChildren();
      const section = document.createElement("section");
      section.id = "chromium-wasm-ax-snapshot";
      section.dataset.source = report.source;
      section.setAttribute("aria-label", "Chromium Wasm accessibility snapshot mirror");
      const heading = document.createElement("h1");
      heading.textContent = report.heading;
      const text = document.createElement("p");
      text.textContent = report.text;
      const control = document.createElement("button");
      control.id = "chromium-wasm-ax-snapshot-toggle";
      control.type = "button";
      control.tabIndex = -1;
      control.setAttribute("aria-label", report.control.name);
      control.setAttribute("aria-pressed", "true");
      control.textContent = report.control.name;
      Object.assign(control.style, {
        height: `${report.control.bounds.height}px`,
        left: `${report.control.bounds.left + this.#canvas.clientLeft}px`,
        pointerEvents: "none",
        top: `${report.control.bounds.top + this.#canvas.clientTop}px`,
        width: `${report.control.bounds.width}px`,
      });
      section.append(heading, text, control);
      this.#mirrorRoot.append(section);
      const controlBounds = control.getBoundingClientRect();
      const controlGeometryMatchesCanvas =
          Math.abs(controlBounds.left - canvasContentLeft -
                   report.control.bounds.left) < 0.01 &&
          Math.abs(controlBounds.top - canvasContentTop -
                   report.control.bounds.top) < 0.01 &&
          Math.abs(controlBounds.width - report.control.bounds.width) < 0.01 &&
          Math.abs(controlBounds.height - report.control.bounds.height) < 0.01;
      const passive = !section.hasAttribute("tabindex") &&
          !heading.hasAttribute("tabindex") && !text.hasAttribute("tabindex") &&
          control.tabIndex === -1 && control.style.pointerEvents === "none" &&
          !control.disabled && control.parentElement === section &&
          this.#mirrorRoot.parentElement === surface &&
          section.parentElement === this.#mirrorRoot &&
          !this.#canvas.contains(section);
      this.#semanticMirror = {
        heading: heading.textContent,
        text: text.textContent,
        roleMask: report.roleMask,
        controlName: control.getAttribute("aria-label"),
        controlPressed: control.getAttribute("aria-pressed") === "true",
        controlBounds: report.control.bounds,
        controlGeometryMatchesCanvas,
        connected: section.isConnected,
        passive,
      };
      if (!this.#semanticMirror.connected || !this.#semanticMirror.passive ||
          !this.#semanticMirror.controlGeometryMatchesCanvas) {
        throw new Error("host semantic mirror did not remain passive outside canvas");
      }
      return true;
    } catch (error) {
      this.#recordFatal(`invalid accessibility snapshot: ${String(error)}`);
      return false;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("accessibility snapshot host bridge is already installed");
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
      requestOuterOriginStorageEstimate(_report) { return false; },
      reportAccessibilitySnapshot(report) {
        return host.#reportAccessibilitySnapshot(report);
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
  }

  #result(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m8GateComplete: false,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      readyObserved: this.#readyObserved,
      navigatedObserved: this.#navigatedObserved,
      snapshotDelivered: this.#snapshotDelivered,
      passObserved: this.#passObserved,
      lifecyclePassObserved: this.#lifecyclePassObserved,
      semanticMirror: this.#semanticMirror,
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
        throw new Error("accessibility snapshot smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("accessibility snapshot timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("accessibility snapshot module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("accessibility snapshot canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("accessibility snapshot module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("accessibility snapshot loader has no default factory export");
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
        host.#recordFatal("accessibility snapshot module factory rejected");
      });

      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("accessibility snapshot smoke did not exit before timeout");
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

export async function runChromeWasmBrowserAccessibilitySnapshotSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs"));
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-accessibility-snapshot-root");
  const canvas = document.querySelector("#browser-canvas");
  const mirrorRoot = document.querySelector("#accessibility-mirror");
  const status = document.querySelector("#browser-accessibility-snapshot-status");
  const versionElement = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(mirrorRoot instanceof HTMLElement) || !(status instanceof HTMLElement) ||
      !(versionElement instanceof HTMLElement)) {
    throw new Error("accessibility snapshot page is missing required elements");
  }
  renderVersions(versionElement, versions);
  const host = new ChromiumWasmBrowserAccessibilitySnapshotSmokeHost(
      canvas, mirrorRoot, versions);
  const result = validateResult(await host.run(
      `/__m8_browser_accessibility_snapshot__/artifacts/${moduleName}.js`, timeoutMs));
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(
      `/__m8_browser_accessibility_snapshot__/result/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error(`accessibility snapshot result POST returned HTTP ${response.status}`);
  }
  return result;
}

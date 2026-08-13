// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// The package host is intentionally only a loader and narrow Ozone bridge. It
// does not synthesize browser UI, open a debugging protocol, or paper over an
// unavailable platform feature. VERSION.json marks the resulting package as
// pre-release until M7/M8/M9 have their own evidence.

import {ChromiumWasmTrustedPointerInput} from "./chromium-wasm-pointer-input.js";
import {ChromiumWasmTrustedClipboardInput} from "./chromium-wasm-clipboard-input.js";
import {ChromiumWasmOuterOriginStorageEstimate} from "./chromium-wasm-storage-estimate.js";
import {ChromiumWasmTrustedTextInput} from "./chromium-wasm-text-input.js";

const HOST_PROTOCOL = 1;
const MAX_FRAME_DIMENSION = 16384;
const MAX_LOG_LINES = 32;
const MAX_LOG_LINE_CHARS = 512;
const MAX_STATUS_BYTES = 64 * 1024;
const PACKAGE_SCHEMA_VERSION = 3;
const RELEASE_STATUS = "pre_m7_m8_not_releasable";
const ALLOWED_ARTIFACT_SOURCE_PROVENANCE = new Set([
  "unverified",
  "local_clean_build_attested",
]);
const EXPECTED_GATE_STATE = Object.freeze({
  persistent_profile_complete: false,
  page_webassembly_enabled: false,
  m8_complete: false,
  m9_release_complete: false,
});

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_LOG_LINES) {
    records.shift();
  }
}

function asReport(value, description) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${description} must be an object`);
  }
  return value;
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} must be a nonempty string`);
  }
  return value;
}

function validateGateState(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("VERSION.json gate_state must be an object");
  }
  const expectedKeys = Object.keys(EXPECTED_GATE_STATE);
  const observedKeys = Object.keys(value);
  if (observedKeys.length !== expectedKeys.length ||
      !expectedKeys.every((key) => Object.hasOwn(value, key))) {
    throw new Error("VERSION.json gate_state keys are invalid");
  }
  for (const key of expectedKeys) {
    if (typeof value[key] !== "boolean") {
      throw new Error("VERSION.json gate_state values must be booleans");
    }
    if (value[key] !== EXPECTED_GATE_STATE[key]) {
      throw new Error("VERSION.json gate_state must retain false values");
    }
  }
  // Do not retain untrusted metadata objects after validation. The rendered
  // release-state section is always the canonical false-only declaration.
  return EXPECTED_GATE_STATE;
}

function isReadinessReport(value) {
  return value && typeof value === "object" &&
      typeof value.shellReady === "boolean" &&
      typeof value.surfaceReady === "boolean" &&
      typeof value.firstVisuallyNonEmptyPaint === "boolean";
}

function cursorDescriptor(cursorType) {
  switch (cursorType) {
    case -1:
    case 0:
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

class ChromiumWasmPreReleaseHost {
  #canvas;
  #textProxy;
  #root;
  #status;
  #versionsElement;
  #gateStateElement;
  #shutdownButton;
  #module = null;
  #pointerInput = null;
  #textInput = null;
  #clipboardInput = null;
  #storageEstimate = null;
  #latestTextInputState = null;
  #records = [];
  #readiness = null;
  #frameCount = 0;
  #processExitCode = null;
  #shutdownRequested = false;
  #gateState = null;
  #windowErrorHandler = null;
  #unhandledRejectionHandler = null;

  constructor(canvas, textProxy, root, status, versionsElement, gateStateElement,
      shutdownButton) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(textProxy instanceof HTMLTextAreaElement) ||
        !(root instanceof HTMLElement) || !(status instanceof HTMLElement) ||
        !(versionsElement instanceof HTMLElement) ||
        !(gateStateElement instanceof HTMLElement) ||
        !(shutdownButton instanceof HTMLButtonElement)) {
      throw new Error("pre-release host page is missing a required element");
    }
    this.#canvas = canvas;
    this.#textProxy = textProxy;
    this.#root = root;
    this.#status = status;
    this.#versionsElement = versionsElement;
    this.#gateStateElement = gateStateElement;
    this.#shutdownButton = shutdownButton;
  }

  #record(kind, value) {
    appendBounded(this.#records, {
      kind,
      value: String(value).slice(0, MAX_LOG_LINE_CHARS),
    });
    this.#renderStatus();
  }

  #renderStatus() {
    const summary = {
      releaseStatus: RELEASE_STATUS,
      gateState: this.#gateState,
      runtimeInitialized: this.#module !== null,
      framesPresented: this.#frameCount,
      readiness: this.#readiness,
      processExitCode: this.#processExitCode,
      shutdownRequested: this.#shutdownRequested,
      records: this.#records,
    };
    const text = JSON.stringify(summary, null, 2);
    this.#status.textContent = text.slice(0, MAX_STATUS_BYTES);
  }

  #renderVersions(version) {
    const versions = version?.versions;
    const build = version?.build;
    if (!versions || typeof versions !== "object" ||
        !build || typeof build !== "object") {
      throw new Error("VERSION.json does not contain revisions");
    }
    if (!ALLOWED_ARTIFACT_SOURCE_PROVENANCE.has(
        build.artifact_source_provenance)) {
      throw new Error(
          "VERSION.json has unsupported artifact source provenance");
    }
    this.#versionsElement.replaceChildren();
    const displayedValues = [
      ["chromium", versions.chromium],
      ["v8", versions.v8],
      ["emscripten", versions.emscripten],
      ["staging checkout", build.staging_checkout],
      ["artifact source provenance", build.artifact_source_provenance],
    ];
    for (const [name, value] of displayedValues) {
      const term = document.createElement("dt");
      const definition = document.createElement("dd");
      term.textContent = name;
      definition.textContent = asNonemptyString(value, `version ${name}`);
      this.#versionsElement.append(term, definition);
    }
  }

  #renderGateState(gateState) {
    this.#gateStateElement.replaceChildren();
    for (const [name, value] of Object.entries(gateState)) {
      const term = document.createElement("dt");
      const definition = document.createElement("dd");
      term.textContent = name;
      definition.textContent = String(value);
      this.#gateStateElement.append(term, definition);
    }
  }

  #reportFatal(value) {
    this.#root.dataset.state = "failed";
    this.#record("fatal", value);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process-exit report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.exitCode)) {
        throw new Error("process-exit report is invalid");
      }
      this.#processExitCode = report.exitCode;
      this.#shutdownButton.disabled = true;
      this.#record("process-exit", report.exitCode);
    } catch (error) {
      this.#reportFatal(`invalid process-exit report: ${String(error)}`);
    }
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.id) ||
          report.id < 1 || !Number.isSafeInteger(report.width) ||
          report.width < 1 || report.width > MAX_FRAME_DIMENSION ||
          !Number.isSafeInteger(report.height) || report.height < 1 ||
          report.height > MAX_FRAME_DIMENSION ||
          !Number.isFinite(report.timestampMs) || report.timestampMs < 0) {
        throw new Error("frame report is invalid");
      }
      this.#frameCount += 1;
      this.#renderStatus();
    } catch (error) {
      this.#reportFatal(`invalid frame report: ${String(error)}`);
    }
  }

  #reportReadiness(value) {
    if (!isReadinessReport(value) || value.protocol !== HOST_PROTOCOL) {
      this.#reportFatal("invalid readiness report");
      return;
    }
    this.#readiness = {
      shellReady: value.shellReady,
      surfaceReady: value.surfaceReady,
      firstVisuallyNonEmptyPaint: value.firstVisuallyNonEmptyPaint,
    };
    this.#root.dataset.state = value.surfaceReady ? "running" : "starting";
    this.#renderStatus();
  }

  #reportOzoneFocusState(value) {
    try {
      const report = asReport(value, "Ozone focus report");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.keyboardTargetPresent !== "boolean" ||
          typeof report.active !== "boolean") {
        throw new Error("focus state is invalid");
      }
      this.#record("ozone-focus", `${report.keyboardTargetPresent}:${report.active}`);
    } catch (error) {
      this.#reportFatal(`invalid Ozone focus report: ${String(error)}`);
    }
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType)) {
        throw new Error("cursor type is invalid");
      }
      const descriptor = cursorDescriptor(report.cursorType);
      if (!descriptor) {
        return false;
      }
      this.#canvas.style.cursor = descriptor.cssCursor;
      return descriptor.exact;
    } catch (error) {
      this.#reportFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  #reportOzoneTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.focusedClientPresent !== "boolean" ||
          typeof report.editable !== "boolean" ||
          typeof report.canComposeInline !== "boolean") {
        throw new Error("text-input state is invalid");
      }
      this.#latestTextInputState = report;
      this.#textInput?.handleOzoneTextInputState(report);
      this.#clipboardInput?.handleOzoneTextInputState(report);
    } catch (error) {
      this.#reportFatal(`invalid Ozone text-input state: ${String(error)}`);
    }
  }

  #reportOzoneTextInputDelivery(value) {
    // The common text adapter only needs this generic state in its test lane.
    // The regular browser-owned delivery below is the production bridge.
    try {
      const report = asReport(value, "Ozone text-input delivery");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.sequence) ||
          typeof report.accepted !== "boolean") {
        throw new Error("text-input delivery is invalid");
      }
      this.#record("ozone-text-delivery", report.sequence);
    } catch (error) {
      this.#reportFatal(`invalid Ozone text-input delivery: ${String(error)}`);
    }
  }

  #reportOzoneBrowserTextInputDelivery(value) {
    try {
      const report = asReport(value, "browser text-input delivery");
      if (report.protocol !== HOST_PROTOCOL || report.action !== 4 ||
          report.sessionId !== 0 || !Number.isSafeInteger(report.sequence) ||
          report.sequence < 1 || typeof report.accepted !== "boolean") {
        throw new Error("browser text-input delivery is invalid");
      }
      this.#textInput?.handleOzoneBrowserTextInputDelivery(report);
    } catch (error) {
      this.#reportFatal(`invalid browser text delivery: ${String(error)}`);
    }
  }

  #reportOzoneBrowserClipboardPasteDelivery(value) {
    try {
      const report = asReport(value, "browser clipboard-paste delivery");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.requestId) || report.requestId < 1 ||
          typeof report.accepted !== "boolean") {
        throw new Error("browser clipboard-paste delivery is invalid");
      }
      this.#clipboardInput?.handleOzoneBrowserClipboardPasteDelivery(report);
    } catch (error) {
      this.#reportFatal(`invalid browser clipboard delivery: ${String(error)}`);
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("a Chromium Wasm host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(value) {
        host.#reportFatal(value);
      },
      reportProcessExit(value) {
        host.#reportProcessExit(value);
      },
      reportFrame(value) {
        host.#reportFrame(value);
      },
      reportReadiness(value) {
        host.#reportReadiness(value);
      },
      reportOzoneFocusState(value) {
        host.#reportOzoneFocusState(value);
      },
      reportOzoneCursor(value) {
        return host.#reportOzoneCursor(value);
      },
      reportOzoneTextInputState(value) {
        host.#reportOzoneTextInputState(value);
      },
      reportOzoneTextInputDelivery(value) {
        host.#reportOzoneTextInputDelivery(value);
      },
      reportOzoneBrowserTextInputDelivery(value) {
        host.#reportOzoneBrowserTextInputDelivery(value);
      },
      reportOzoneBrowserClipboardPasteDelivery(value) {
        host.#reportOzoneBrowserClipboardPasteDelivery(value);
      },
      requestOuterOriginStorageEstimate(value) {
        return host.#storageEstimate?.request(value) === true;
      },
    });
  }

  #capturePageErrors() {
    this.#windowErrorHandler = (event) => {
      this.#reportFatal(String(event.error || event.message || "window error"));
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#reportFatal(`unhandled rejection: ${String(event.reason)}`);
    };
    addEventListener("error", this.#windowErrorHandler);
    addEventListener("unhandledrejection", this.#unhandledRejectionHandler);
  }

  #setModule(module) {
    if (!module || typeof module !== "object" ||
        typeof module.ccall !== "function") {
      this.#reportFatal("onRuntimeInitialized did not supply a callable Module");
      return;
    }
    if (this.#module !== null) {
      this.#reportFatal("onRuntimeInitialized supplied multiple Module objects");
      return;
    }
    this.#module = module;
    this.#pointerInput = new ChromiumWasmTrustedPointerInput(this.#canvas, {
      getModule: () => this.#module,
      recordFatal: (message) => this.#reportFatal(message),
      maximumFrameDimension: MAX_FRAME_DIMENSION,
    });
    this.#pointerInput.attach();
    this.#textInput = new ChromiumWasmTrustedTextInput(
        this.#canvas, this.#textProxy, {
          getModule: () => this.#module,
          reportFatal: (message) => this.#reportFatal(message),
        });
    this.#textInput.attach();
    this.#clipboardInput = new ChromiumWasmTrustedClipboardInput(
        this.#textProxy, {
          getModule: () => this.#module,
          reportFatal: (message) => this.#reportFatal(message),
        });
    this.#clipboardInput.attach();
    this.#storageEstimate = new ChromiumWasmOuterOriginStorageEstimate({
      getModule: () => this.#module,
      recordFatal: (message) => this.#reportFatal(message),
      onResult: (report) => this.#record("storage-estimate", report.status),
    });
    if (this.#latestTextInputState) {
      this.#textInput.handleOzoneTextInputState(this.#latestTextInputState);
      this.#clipboardInput.handleOzoneTextInputState(this.#latestTextInputState);
    }
    this.#shutdownButton.disabled = false;
    this.#record("runtime", "initialized");
  }

  #requestShutdown() {
    if (this.#shutdownRequested || !this.#module ||
        typeof this.#module.ccall !== "function") {
      return;
    }
    try {
      const accepted = this.#module.ccall(
          "chromium_wasm_browser_host_request_shutdown", "number", [], []);
      if (accepted !== 1) {
        throw new Error(`shutdown ABI returned ${String(accepted)}`);
      }
      this.#shutdownRequested = true;
      this.#shutdownButton.disabled = true;
      this.#pointerInput?.releaseActivePointer("host-shutdown");
      this.#textInput?.releaseActiveInput("host-shutdown");
      this.#record("shutdown", "accepted");
    } catch (error) {
      this.#reportFatal(`shutdown ABI failed: ${String(error)}`);
    }
  }

  async run(version) {
    if (version?.schema_version !== PACKAGE_SCHEMA_VERSION) {
      throw new Error("VERSION.json has an unsupported package schema version");
    }
    if (version?.release_status !== RELEASE_STATUS) {
      throw new Error("VERSION.json does not declare this pre-release package");
    }
    const gateState = validateGateState(version?.gate_state);
    const inputModuleName = version?.build?.input_module_name;
    if (typeof inputModuleName !== "string" ||
        !/^[A-Za-z0-9_]+$/.test(inputModuleName)) {
      throw new Error("VERSION.json has an invalid input module name");
    }
    if (globalThis.crossOriginIsolated !== true ||
        typeof SharedArrayBuffer !== "function") {
      throw new Error("this package requires COOP/COEP cross-origin isolation");
    }
    this.#gateState = gateState;
    this.#renderVersions(version);
    this.#renderGateState(gateState);
    this.#capturePageErrors();
    this.#installBridge();
    this.#shutdownButton.addEventListener("click", () => this.#requestShutdown());
    this.#canvas.focus({preventScroll: true});
    if (document.activeElement !== this.#canvas) {
      throw new Error("browser canvas did not accept focus");
    }

    const loaderUrl = new URL("./chromium-wasm.js", import.meta.url);
    const [response, namespace] = await Promise.all([
      fetch(loaderUrl, {cache: "no-store"}),
      import(loaderUrl.href),
    ]);
    if (!response.ok) {
      throw new Error(`generated loader request returned HTTP ${response.status}`);
    }
    if (typeof namespace.default !== "function") {
      throw new Error("generated loader has no default factory export");
    }
    const mainScriptUrlOrBlob = await response.blob();
    if (mainScriptUrlOrBlob.size === 0) {
      throw new Error("generated loader is empty");
    }
    const host = this;
    const moduleOptions = {
      canvas: this.#canvas,
      noExitRuntime: false,
      mainScriptUrlOrBlob,
      locateFile(path) {
        if (path !== `${inputModuleName}.wasm` && path !== "chromium-wasm.wasm") {
          throw new Error(`unexpected generated sidecar ${String(path)}`);
        }
        return new URL("./chromium-wasm.wasm", loaderUrl).href;
      },
      print(line) {
        host.#record("stdout", line);
      },
      printErr(line) {
        host.#record("stderr", line);
      },
      onRuntimeInitialized() {
        host.#setModule(this);
      },
      onAbort(reason) {
        host.#reportFatal(`Wasm abort: ${String(reason)}`);
      },
      onExit(code) {
        host.#reportProcessExit({protocol: HOST_PROTOCOL, exitCode: Number(code)});
      },
    };
    Promise.resolve(namespace.default(moduleOptions)).catch((error) => {
      host.#reportFatal(`generated loader rejected: ${String(error)}`);
    });
    this.#record("loader", "started");
  }
}

async function loadVersion() {
  const response = await fetch("./VERSION.json", {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`VERSION.json request returned HTTP ${response.status}`);
  }
  return response.json();
}

export async function runChromiumWasmPreRelease() {
  const root = document.querySelector("#chrome-root");
  const canvas = document.querySelector("#browser-canvas");
  const textProxy = document.querySelector("#browser-text-proxy");
  const status = document.querySelector("#chrome-status");
  const versions = document.querySelector("#versions");
  const gateState = document.querySelector("#gate-state");
  const shutdownButton = document.querySelector("#shutdown");
  const host = new ChromiumWasmPreReleaseHost(
      canvas, textProxy, root, status, versions, gateState, shutdownButton);
  await host.run(await loadVersion());
}

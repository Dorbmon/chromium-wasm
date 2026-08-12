// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This M9 preparation lane is intentionally narrow. The outer browser supplies
// only physical pointer records to the shared Ozone adapter. C++ owns the one
// Browser, native Views targets, tab model checks, and shutdown. A later
// Canvas2D backing-store-copy report orders host copy observation only; it does
// not establish raster, compositor, display, or vsync presentation. This host
// has no navigation, persistence, WISP, page-Wasm, or worker-control API.

import {ChromiumWasmTrustedPointerInput} from "./chrome_wasm_pointer_input.js";

const HOST_PROTOCOL = 1;
const CASE = "browser_same_instance_tab_churn_m9";
const SCOPE = "fixed-three-cycle-same-instance-tab-churn-with-later-" +
    "backing-store-copy-observation-only";
const SWITCH = "--wasm-browser-host-tab-churn-smoke";
const READY_MARKER = "CHROMIUM_WASM_M9_TAB_CHURN:READY";
const VERIFIED_MARKER = "CHROMIUM_WASM_M9_TAB_CHURN:VERIFIED";
const PASS_MARKER = "CHROMIUM_WASM_M9_TAB_CHURN:PASS";
const TIMEOUT_MARKER = "CHROMIUM_WASM_M9_TAB_CHURN:TIMEOUT";
const CYCLE_COUNT = 3;
const ACTIONS = Object.freeze([
  "new-tab", "select-first", "select-second", "close-second",
]);
const STAGE_COUNT = CYCLE_COUNT * ACTIONS.length;
// The accepted later copy for one stage can also be the current host copy
// when C++ synchronously publishes the next READY target from that callback.
// Equality is therefore allowed at a stage boundary; reverse copy order is
// not. This records host Canvas2D backing-store-copy order only.
const FRAME_TRANSITION_POLICY =
    "previous-backing-store-copy-may-share-next-ready-frame";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 96;
const ARTIFACT_SOURCE_PROVENANCE = "unverified";
const ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot";
const SOURCE_SNAPSHOT_PROVENANCE =
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance";
const VERSION_PROVENANCE =
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance";
const LIMITATIONS = Object.freeze([
  "does_not_exercise_navigation_or_page_javascript",
  "does_not_exercise_page_webassembly",
  "does_not_exercise_wisp_or_network_reconnect",
  "does_not_prove_opfs_persistence_or_recovery",
  "does_not_measure_memory_growth_or_address_space_pressure",
  "does_not_measure_or_exhaust_the_pthread_pool",
  "does_not_prove_raster_compositor_display_or_vsync_presentation",
  "does_not_claim_m8_feature_compatibility",
]);

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
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

function parseQueryJson(value, description) {
  const text = asNonemptyString(value, description);
  try {
    return JSON.parse(text);
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

function parseVersions(value) {
  const parsed = requireExactFields(parseQueryJson(value, "tab-churn versions"),
      ["chromium", "v8", "emscripten"], "tab-churn versions");
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten"]) {
    versions[field] = asNonemptyString(parsed?.[field], `version ${field}`);
  }
  return Object.freeze(versions);
}

function parseByteIdentity(value, description) {
  const identity = requireExactFields(value, ["bytes", "sha256"], description);
  if (!Number.isSafeInteger(identity.bytes) || identity.bytes < 1 ||
      typeof identity.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(identity.sha256)) {
    throw new Error(`${description} is invalid`);
  }
  return Object.freeze({bytes: identity.bytes, sha256: identity.sha256});
}

function parseArtifactIdentity(value) {
  const artifact = requireExactFields(
      parseQueryJson(value, "tab-churn artifact identity"),
      ["artifact_delivery", "artifact_source_provenance", "loader",
        "module_name", "wasm"], "tab-churn artifact identity");
  if (artifact.artifact_source_provenance !== ARTIFACT_SOURCE_PROVENANCE ||
      artifact.artifact_delivery !== ARTIFACT_DELIVERY ||
      typeof artifact.module_name !== "string" ||
      !/^[A-Za-z0-9_]+$/.test(artifact.module_name)) {
    throw new Error("tab-churn artifact identity has invalid provenance");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    loader: parseByteIdentity(artifact.loader, "tab-churn loader identity"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "tab-churn Wasm identity"),
  });
}

function parseCaptureHarnessIdentity(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "tab-churn capture harness"),
      ["host_html", "host_js", "pointer_input_js", "runner_source",
        "source_snapshot_provenance", "version_provenance"],
      "tab-churn capture harness");
  if (harness.source_snapshot_provenance !== SOURCE_SNAPSHOT_PROVENANCE ||
      harness.version_provenance !== VERSION_PROVENANCE) {
    throw new Error("tab-churn capture harness provenance is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html, "tab-churn host HTML identity"),
    host_js: parseByteIdentity(harness.host_js, "tab-churn host JavaScript identity"),
    pointer_input_js: parseByteIdentity(
        harness.pointer_input_js, "tab-churn pointer-input identity"),
    runner_source: parseByteIdentity(
        harness.runner_source, "tab-churn runner-source identity"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("tab-churn page is missing its version element");
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

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) {
    records.shift();
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

function ozoneCursorDescriptor(cursorType) {
  const exact = new Map([
    [-1, "default"], [0, "default"], [1, "crosshair"], [2, "pointer"],
    [3, "text"], [4, "wait"], [5, "help"], [6, "e-resize"],
    [7, "n-resize"], [8, "ne-resize"], [9, "nw-resize"],
    [10, "s-resize"], [11, "se-resize"], [12, "sw-resize"],
    [13, "w-resize"], [14, "ns-resize"], [15, "ew-resize"],
    [16, "nesw-resize"], [17, "nwse-resize"], [18, "col-resize"],
    [19, "row-resize"], [29, "move"], [30, "vertical-text"],
    [31, "cell"], [32, "context-menu"], [33, "alias"],
    [34, "progress"], [35, "no-drop"], [36, "copy"], [37, "none"],
    [38, "not-allowed"], [39, "zoom-in"], [40, "zoom-out"],
    [41, "grab"], [42, "grabbing"],
  ]);
  if (exact.has(cursorType)) {
    return {cssCursor: exact.get(cursorType), exact: true};
  }
  if ([20, 21, 22, 23, 24, 25, 26, 27, 28, 43, 44].includes(cursorType)) {
    return {cssCursor: "all-scroll", exact: false};
  }
  if (cursorType === 45) return {cssCursor: "default", exact: false};
  if (cursorType === 46) return {cssCursor: "no-drop", exact: false};
  if (cursorType === 47) return {cssCursor: "move", exact: false};
  if (cursorType === 48) return {cssCursor: "copy", exact: false};
  if (cursorType === 49) return {cssCursor: "alias", exact: false};
  if ([50, 51, 52, 53].includes(cursorType)) {
    return {cssCursor: "not-allowed", exact: false};
  }
  return null;
}

function stageInfo(stage) {
  if (!Number.isSafeInteger(stage) || stage < 1 || stage > STAGE_COUNT) {
    return null;
  }
  return Object.freeze({
    cycle: Math.floor((stage - 1) / ACTIONS.length) + 1,
    stage,
    action: ACTIONS[(stage - 1) % ACTIONS.length],
  });
}

function parseTargetMarker(line) {
  const match = new RegExp(
      `^${READY_MARKER} cycle=(\\d+) stage=(\\d+) ` +
      "action=(new-tab|select-first|select-second|close-second) " +
      "x=(\\d+) y=(\\d+)$").exec(line);
  if (!match) return null;
  const cycle = Number(match[1]);
  const stage = Number(match[2]);
  const x = Number(match[4]);
  const y = Number(match[5]);
  const info = stageInfo(stage);
  if (!info || cycle !== info.cycle || match[3] !== info.action ||
      !Number.isSafeInteger(x) || !Number.isSafeInteger(y) || x < 0 || y < 0 ||
      x >= MAX_FRAME_DIMENSION || y >= MAX_FRAME_DIMENSION) {
    throw new Error("tab-churn READY marker is invalid");
  }
  return {info, x, y};
}

function parseVerifiedMarker(line) {
  const match = new RegExp(
      `^${VERIFIED_MARKER} cycle=(\\d+) stage=(\\d+) ` +
      "action=(new-tab|select-first|select-second|close-second)$").exec(line);
  if (!match) return null;
  const cycle = Number(match[1]);
  const stage = Number(match[2]);
  const info = stageInfo(stage);
  if (!info || cycle !== info.cycle || match[3] !== info.action) {
    throw new Error("tab-churn VERIFIED marker is invalid");
  }
  return info;
}

class ChromiumWasmBrowserTabChurnSmokeHost {
  #canvas;
  #versions;
  #artifact;
  #captureHarness;
  #module = null;
  #pointerInput = null;
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #runtimeInitialized = false;
  #factorySettled = false;
  #runtimeExitCode = null;
  #processExitCode = null;
  #abort = null;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #frameReports = [];
  #readinessReports = [];
  #readiness = null;
  #focusReports = [];
  #cursorReports = [];
  #errorHandler;
  #rejectionHandler;
  #generation = 1;
  #stages = [];
  #pointerRecords = [];

  constructor(canvas, versions, artifact, captureHarness) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("tab-churn smoke requires a canvas");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#artifact = artifact;
    this.#captureHarness = captureHarness;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
    this.#publishState("starting");
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
    ++this.#generation;
    this.#updateState();
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      appendBounded(this.#windowErrors, message);
      this.#recordFatal(`window error: ${message}`);
    };
    this.#rejectionHandler = (event) => {
      const message = String(event.reason);
      appendBounded(this.#unhandledRejections, message);
      this.#recordFatal(`unhandled rejection: ${message}`);
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
      this.#recordFatal(`runtime exit is not an integer: ${String(code)}`);
      return;
    }
    if (this.#runtimeExitCode !== null) {
      this.#recordFatal(`runtime reported multiple exits: ${code}`);
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
    this.#updateState();
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

  #currentFrameId() {
    return this.#frameReports.at(-1)?.id ?? 0;
  }

  #firstFrameAfter(frameId) {
    return this.#frameReports.find((frame) => frame.id > frameId) ?? null;
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL || !isFrameReport(report) ||
          this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
        throw new Error("frame report is invalid or does not match the canvas");
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
      this.#maybeQueueBackingStoreCopy();
      this.#updateState();
    } catch (error) {
      this.#recordFatal(`invalid frame report: ${String(error)}`);
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
      this.#recordFatal(`invalid Ozone focus report: ${String(error)}`);
    }
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType)) {
        throw new Error("cursor report is invalid");
      }
      const descriptor = ozoneCursorDescriptor(report.cursorType);
      if (!descriptor) throw new Error("cursor type is unsupported");
      this.#canvas.style.cursor = descriptor.cssCursor;
      if (this.#canvas.style.cursor !== descriptor.cssCursor) {
        throw new Error("host canvas rejected the cursor style");
      }
      appendBounded(this.#cursorReports, {
        cursorType: report.cursorType,
        cssCursor: descriptor.cssCursor,
        exact: descriptor.exact,
      });
      return true;
    } catch (error) {
      this.#recordFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("tab-churn bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportOzoneFocusState(report) { host.#reportFocus(report); },
      reportOzoneCursor(report) { return host.#reportOzoneCursor(report); },
      reportOzoneTextInputDelivery() {},
      reportOzoneTextInputState() {},
    });
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
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return null;
    return {x: point.x, y: point.y, clientX, clientY};
  }

  #activeStage() {
    return this.#stages.at(-1) ?? null;
  }

  #stageSnapshot(stage) {
    return {
      cycle: stage.cycle,
      stage: stage.stage,
      action: stage.action,
      target: stage.target,
      readyFrameId: stage.readyFrameId,
      checkQueued: stage.checkQueued,
      verified: stage.verified,
      verifiedFrameId: stage.verifiedFrameId,
      backingStoreCopyFrameId: stage.backingStoreCopyFrameId,
      backingStoreCopyQueued: stage.backingStoreCopyQueued,
      passObserved: stage.passObserved === true,
    };
  }

  #publishState(state) {
    const active = this.#activeStage();
    globalThis.__chromiumWasmM9TabChurnState = Object.freeze({
      state,
      attached: this.#pointerInput?.attached === true,
      stage: active?.stage ?? null,
      cycle: active?.cycle ?? null,
      action: active?.action ?? null,
      target: active?.target ?? null,
      completedStageCount: this.#stages.filter((entry) =>
        entry.backingStoreCopyQueued).length,
      passObserved: this.#stages.length === STAGE_COUNT &&
          active?.backingStoreCopyQueued === true,
      fatalErrorCount: this.#fatalErrors.length,
    });
  }

  #updateState() {
    if (this.#fatalErrors.length !== 0) {
      this.#publishState("failed");
      return;
    }
    const active = this.#activeStage();
    if (!this.#module || this.#pointerInput?.attached !== true) {
      this.#publishState("awaiting-runtime");
      return;
    }
    if (!active) {
      this.#publishState("awaiting-native-target");
      return;
    }
    if (!active.checkQueued) {
      this.#publishState("awaiting-trusted-dom-action");
      return;
    }
    if (!active.verified) {
      this.#publishState("awaiting-native-model-check");
      return;
    }
    if (active.backingStoreCopyFrameId === null) {
      this.#publishState("awaiting-post-action-backing-store-copy");
      return;
    }
    if (!active.backingStoreCopyQueued) {
      this.#publishState("awaiting-native-backing-store-copy-check");
      return;
    }
    if (active.stage === STAGE_COUNT) {
      this.#publishState("awaiting-orderly-shutdown");
      return;
    }
    this.#publishState("awaiting-next-native-target");
  }

  #acceptedActionPairForStage(stage) {
    const actions = this.#pointerRecords.filter((record) =>
      record.type === "down" || record.type === "up");
    if (actions.length < 2 || !stage?.target) return false;
    const [down, up] = actions.slice(-2);
    const exact = (record) => record && record.trusted === true &&
        record.cancelable === true && record.pointerType === "mouse" &&
        record.primary === true && record.button === 0 &&
        record.accepted === true && record.defaultPrevented === true &&
        record.reason === null && record.x === stage.target.x &&
        record.y === stage.target.y;
    return exact(down) && exact(up) && down.type === "down" &&
        down.buttons === 1 && up.type === "up" && up.buttons === 0;
  }

  #queueVerifier(name, stage, field, condition) {
    if (stage[field]) return;
    stage[field] = true;
    const generation = this.#generation;
    this.#updateState();
    setTimeout(() => {
      if (generation !== this.#generation || !condition()) {
        this.#recordFatal(`${name} lost its deferred ordinal evidence`);
        return;
      }
      if (!this.#module || typeof this.#module.ccall !== "function") {
        this.#recordFatal(`${name} ran without Module.ccall`);
        return;
      }
      try {
        const result = this.#module.ccall(name, "number", ["number"],
            [stage.stage]);
        if (result !== 1) {
          this.#recordFatal(`${name} rejected ordinal ${stage.stage}`);
        }
      } catch (error) {
        this.#recordFatal(`${name} failed: ${String(error)}`);
      }
      this.#updateState();
    }, 0);
  }

  #maybeQueueCheck() {
    const active = this.#activeStage();
    if (!active || active.checkQueued || active.verified ||
        !this.#acceptedActionPairForStage(active) || this.#fatalErrors.length) {
      return;
    }
    this.#queueVerifier(
        "chromium_wasm_browser_host_tab_churn_check", active, "checkQueued",
        () => this.#activeStage() === active && !active.verified &&
            this.#acceptedActionPairForStage(active));
  }

  #maybeQueueBackingStoreCopy() {
    const active = this.#activeStage();
    if (!active || !active.verified || active.backingStoreCopyQueued ||
        active.verifiedFrameId === null || this.#fatalErrors.length) {
      return;
    }
    const frame = this.#firstFrameAfter(active.verifiedFrameId);
    if (!frame) return;
    active.backingStoreCopyFrameId = frame.id;
    this.#queueVerifier(
        "chromium_wasm_browser_host_tab_churn_presented", active,
        "backingStoreCopyQueued", () => this.#activeStage() === active &&
            active.verified && active.backingStoreCopyFrameId !== null &&
            active.backingStoreCopyFrameId > active.verifiedFrameId);
  }

  #recordPointer(record) {
    appendBounded(this.#pointerRecords, record);
    this.#maybeQueueCheck();
    this.#updateState();
  }

  #recordOutput(value) {
    const line = String(value);
    try {
      if (line.startsWith(TIMEOUT_MARKER)) {
        throw new Error("native tab-churn smoke timed out");
      }
      const targetMarker = parseTargetMarker(line);
      if (targetMarker) {
        const previous = this.#activeStage();
        if ((previous && (!previous.backingStoreCopyQueued ||
                          targetMarker.info.stage !== previous.stage + 1)) ||
            (!previous && targetMarker.info.stage !== 1) ||
            this.#stages.length !== targetMarker.info.stage - 1) {
          throw new Error("tab-churn READY marker is out of order");
        }
        const target = this.#targetForClientPoint(targetMarker);
        if (!target) throw new Error("tab-churn target cannot map to canvas");
        const readyFrameId = this.#currentFrameId();
        if (readyFrameId < 1) {
          throw new Error("tab-churn READY marker has no backing-store copy");
        }
        this.#stages.push({
          ...targetMarker.info,
          target,
          readyFrameId,
          checkQueued: false,
          verified: false,
          verifiedFrameId: null,
          backingStoreCopyFrameId: null,
          backingStoreCopyQueued: false,
          passObserved: false,
        });
      }
      const verifiedMarker = parseVerifiedMarker(line);
      if (verifiedMarker) {
        const active = this.#activeStage();
        if (!active || !active.checkQueued || active.verified ||
            verifiedMarker.stage !== active.stage) {
          throw new Error("tab-churn VERIFIED marker is out of order");
        }
        active.verified = true;
        active.verifiedFrameId = this.#currentFrameId();
        if (active.verifiedFrameId < active.readyFrameId) {
          throw new Error("tab-churn VERIFIED marker predates READY copy");
        }
        this.#maybeQueueBackingStoreCopy();
      }
      if (line === `${PASS_MARKER} cycles=${CYCLE_COUNT}`) {
        const active = this.#activeStage();
        if (!active || active.stage !== STAGE_COUNT ||
            !active.backingStoreCopyQueued) {
          throw new Error("tab-churn PASS marker is out of order");
        }
        active.passObserved = true;
      }
      this.#updateState();
    } catch (error) {
      this.#recordFatal(`invalid tab-churn output: ${String(error)}`);
    }
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null ||
        typeof module.ccall !== "function" ||
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
    this.#updateState();
  }

  #result(status, error) {
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status,
      m9GateComplete: false,
      limitations: [...LIMITATIONS],
      artifact: this.#artifact,
      capture_harness: this.#captureHarness,
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
      ozoneCursorReports: this.#cursorReports,
      tabChurn: {
        cycleCount: CYCLE_COUNT,
        frameTransitionPolicy: FRAME_TRANSITION_POLICY,
        stageCount: STAGE_COUNT,
        stages: this.#stages.map((stage) => this.#stageSnapshot(stage)),
        pointerRecords: this.#pointerRecords,
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
        throw new Error("tab-churn smoke requires cross-origin isolation");
      }
      if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("tab-churn timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("tab-churn module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("tab-churn canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("tab-churn module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("tab-churn module loader has no default factory export");
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
      }).then(() => {
        host.#factorySettled = true;
        host.#updateState();
      }).catch((error) => {
        host.#factorySettled = true;
        host.#recordFatal(`module factory rejected: ${String(error)}`);
      });

      const deadline = startedAt + timeoutMs;
      while ((this.#runtimeExitCode === null || !this.#factorySettled) &&
             performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("tab-churn smoke did not exit before timeout");
      }
      if (!this.#factorySettled) {
        throw new Error("tab-churn module factory did not settle before timeout");
      }
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#pointerInput?.detach();
      this.#releaseWindowErrors();
    }
  }
}

function validateResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) failures.push(message);
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.runtimeExitCode === 0, "runtime did not exit zero");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.factorySettled === true, "module factory did not settle");
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
  require(result.readiness?.surfaceReady === true,
      "surface readiness was not reported");
  require(result.ozoneFocusReports?.some((report) =>
    report.keyboardTargetPresent === true && report.active === true),
  "no active Ozone keyboard target was observed");

  const churn = result.tabChurn;
  require(churn?.cycleCount === CYCLE_COUNT, "wrong tab-churn cycle count");
  require(churn?.frameTransitionPolicy === FRAME_TRANSITION_POLICY,
      "wrong tab-churn frame transition policy");
  require(churn?.stageCount === STAGE_COUNT, "wrong tab-churn stage count");
  require(Array.isArray(churn?.stages) && churn.stages.length === STAGE_COUNT,
      "wrong tab-churn stage evidence count");
  for (let index = 0; index < (churn?.stages?.length || 0); ++index) {
    const stage = churn.stages[index];
    const expected = stageInfo(index + 1);
    require(stage?.cycle === expected.cycle && stage?.stage === expected.stage &&
        stage?.action === expected.action,
    `tab-churn stage ${index + 1} has an invalid identity`);
    require(stage?.checkQueued === true && stage?.verified === true &&
        stage?.backingStoreCopyQueued === true,
    `tab-churn stage ${index + 1} lacks native verification`);
    require(Number.isSafeInteger(stage?.readyFrameId) &&
        Number.isSafeInteger(stage?.verifiedFrameId) &&
        Number.isSafeInteger(stage?.backingStoreCopyFrameId) &&
        stage.readyFrameId <= stage.verifiedFrameId &&
        stage.backingStoreCopyFrameId > stage.verifiedFrameId,
    `tab-churn stage ${index + 1} lacks ordered Canvas2D copy evidence`);
  }
  const actions = (churn?.pointerRecords || []).filter((record) =>
    record && (record.type === "down" || record.type === "up"));
  require(actions.length === STAGE_COUNT * 2,
      "tab-churn did not record exactly one trusted click per stage");
  for (let index = 0; index < Math.min(STAGE_COUNT, churn?.stages?.length || 0);
       ++index) {
    const target = churn.stages[index].target;
    const down = actions[index * 2];
    const up = actions[index * 2 + 1];
    for (const [record, type, buttons] of [[down, "down", 1], [up, "up", 0]]) {
      require(record?.type === type && record?.trusted === true &&
          record?.cancelable === true && record?.pointerType === "mouse" &&
          record?.primary === true && record?.button === 0 &&
          record?.buttons === buttons && record?.accepted === true &&
          record?.defaultPrevented === true && record?.reason === null &&
          record?.x === target?.x && record?.y === target?.y,
      `tab-churn stage ${index + 1} pointer ${type} is invalid`);
    }
  }
  require(result.frameReports?.length >= STAGE_COUNT,
      "tab-churn has too few frame reports");
  const frameIds = new Set((result.frameReports || []).map((frame) => frame?.id));
  for (let index = 0; index < (churn?.stages?.length || 0); ++index) {
    const stage = churn.stages[index];
    for (const field of ["readyFrameId", "verifiedFrameId",
      "backingStoreCopyFrameId"]) {
      require(frameIds.has(stage?.[field]),
          `tab-churn stage ${index + 1} ${field} is not an observed copy`);
    }
    if (index > 0) {
      const previous = churn.stages[index - 1];
      require(previous?.backingStoreCopyFrameId <= stage?.readyFrameId,
          `tab-churn stages ${index}/${index + 1} have reverse copy order`);
    }
  }
  require(result.artifact?.artifact_source_provenance ===
      ARTIFACT_SOURCE_PROVENANCE,
  "tab-churn artifact source provenance is not unverified");
  require(result.artifact?.artifact_delivery === ARTIFACT_DELIVERY,
      "tab-churn artifact delivery is not an immutable snapshot");
  require(result.capture_harness?.source_snapshot_provenance ===
      SOURCE_SNAPSHOT_PROVENANCE,
  "tab-churn harness source provenance is invalid");
  require(result.capture_harness?.version_provenance === VERSION_PROVENANCE,
      "tab-churn version provenance is invalid");
  const finalStage = churn?.stages?.at(-1);
  require(finalStage?.passObserved === true,
      "tab-churn final PASS marker was not observed");
  result.failedChecks = failures;
  if (failures.length) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserTabChurnSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "90000");
  const versions = parseVersions(query.get("versions"));
  const artifact = parseArtifactIdentity(query.get("artifact"));
  if (artifact.module_name !== moduleName) {
    throw new Error("tab-churn artifact module name disagrees with query");
  }
  const captureHarness = parseCaptureHarnessIdentity(query.get("captureHarness"));
  const root = document.querySelector("#browser-tab-churn-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-tab-churn-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("tab-churn page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserTabChurnSmokeHost(
      canvas, versions, artifact, captureHarness);
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

export const chromeWasmBrowserTabChurnSmokeContract = Object.freeze({
  ACTIONS,
  ARTIFACT_DELIVERY,
  ARTIFACT_SOURCE_PROVENANCE,
  CASE,
  FRAME_TRANSITION_POLICY,
  SOURCE_SNAPSHOT_PROVENANCE,
  CYCLE_COUNT,
  HOST_PROTOCOL,
  LIMITATIONS,
  PASS_MARKER,
  READY_MARKER,
  SCOPE,
  STAGE_COUNT,
  SWITCH,
  VERSION_PROVENANCE,
  VERIFIED_MARKER,
});

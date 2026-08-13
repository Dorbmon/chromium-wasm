// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This M9 preparation lane is intentionally narrow. Native C++ owns the
// Browser, the original WebContents, all six fixed data: URLs, navigation,
// history checks, and shutdown. The outer host can only report one later
// Canvas2D backing-store copy for each native-completed navigation. That copy
// orders host observation only; it does not establish raster, compositor,
// display, or vsync presentation. There is no host URL, input, navigation,
// persistence, WISP, page-Wasm, or worker-control API here.

const HOST_PROTOCOL = 1;
const CASE = "browser_same_instance_navigation_churn_m9";
const PRODUCT_MODULE_NAME = "chrome_wasm";
const SCOPE = "fixed-three-cycle-same-instance-local-data-navigation-churn-" +
    "with-later-backing-store-copy-observation-only";
const SWITCH = "--wasm-browser-host-navigation-churn-smoke";
const READY_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:READY";
const NAVIGATED_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:NAVIGATED";
const PRESENTED_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:PRESENTED";
const PASS_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:PASS";
const FAILURE_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:FAIL";
const TIMEOUT_MARKER = "CHROMIUM_WASM_M9_NAVIGATION_CHURN:TIMEOUT";
const LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS";
const CYCLE_COUNT = 3;
const NAVIGATIONS_PER_CYCLE = 2;
const NAVIGATION_NAMES = Object.freeze(["first", "second"]);
const STAGE_COUNT = CYCLE_COUNT * NAVIGATIONS_PER_CYCLE;
// A navigation marker for the next stage may use the previous stage's copy as
// its snapshot because C++ emits it while accepting the previous deferred
// acknowledgement. Each individual stage still requires a strictly later
// copy, and reverse copy order is never accepted.
const FRAME_TRANSITION_POLICY =
    "previous-backing-store-copy-may-share-next-navigation-marker-frame";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 128;
const WASM_PAGE_SIZE_BYTES = 64 * 1024;
const WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT = STAGE_COUNT + 2;
const WASM_HEAP_BUFFER_CAPACITY_DEFINITION =
    "Module.HEAPU8.buffer.byteLength capacity observed at runtime initialization, " +
    "each stage's later Canvas2D backing-store-copy observation, and runtime " +
    "exit; not allocated or resident memory usage";
const WASM_HEAP_BUFFER_CAPACITY_LIMITATION =
    "Module.HEAPU8.buffer.byteLength capacity is not allocations, residency, " +
    "address-space headroom, a leak, out-of-memory, or drain proof";
const ARTIFACT_SOURCE_PROVENANCE = "unverified";
const ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot";
const SOURCE_SNAPSHOT_PROVENANCE =
    "on-disk-byte-snapshots-at-server-startup-not-commit-provenance";
const VERSION_PROVENANCE =
    "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance";
const LIMITATIONS = Object.freeze([
  "does_not_exercise_omnibox_or_trusted_dom_navigation_input",
  "does_not_exercise_page_javascript",
  "does_not_exercise_page_webassembly",
  "does_not_exercise_wisp_or_network_reconnect",
  "does_not_prove_opfs_persistence_or_recovery",
  "does_not_claim_m7_profile_persistence",
  WASM_HEAP_BUFFER_CAPACITY_LIMITATION,
  "does_not_measure_or_exhaust_the_pthread_pool",
  "does_not_prove_raster_compositor_display_or_vsync_presentation",
  "does_not_claim_m8_feature_compatibility",
]);

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) records.shift();
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

function parseVersions(value) {
  const parsed = requireExactFields(
      parseQueryJson(value, "navigation-churn versions"),
      ["chromium", "v8", "emscripten"], "navigation-churn versions");
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten"]) {
    versions[field] = asNonemptyString(parsed[field], `version ${field}`);
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
      parseQueryJson(value, "navigation-churn artifact identity"),
      ["artifact_delivery", "artifact_source_provenance", "loader",
        "module_name", "wasm"], "navigation-churn artifact identity");
  if (artifact.artifact_delivery !== ARTIFACT_DELIVERY ||
      artifact.artifact_source_provenance !== ARTIFACT_SOURCE_PROVENANCE ||
      typeof artifact.module_name !== "string" ||
      !/^[A-Za-z0-9_]+$/.test(artifact.module_name)) {
    throw new Error("navigation-churn artifact identity has invalid provenance");
  }
  if (artifact.module_name !== PRODUCT_MODULE_NAME) {
    throw new Error(
        "navigation-churn artifact identity must select the chrome_wasm product module");
  }
  return Object.freeze({
    artifact_delivery: artifact.artifact_delivery,
    artifact_source_provenance: artifact.artifact_source_provenance,
    loader: parseByteIdentity(artifact.loader, "navigation-churn loader identity"),
    module_name: artifact.module_name,
    wasm: parseByteIdentity(artifact.wasm, "navigation-churn Wasm identity"),
  });
}

function parseCaptureHarnessIdentity(value) {
  const harness = requireExactFields(
      parseQueryJson(value, "navigation-churn capture harness"),
      ["host_html", "host_js", "runner_source", "source_snapshot_provenance",
        "version_provenance"], "navigation-churn capture harness");
  if (harness.source_snapshot_provenance !== SOURCE_SNAPSHOT_PROVENANCE ||
      harness.version_provenance !== VERSION_PROVENANCE) {
    throw new Error("navigation-churn capture harness provenance is invalid");
  }
  return Object.freeze({
    host_html: parseByteIdentity(harness.host_html, "navigation-churn host HTML identity"),
    host_js: parseByteIdentity(harness.host_js, "navigation-churn host JavaScript identity"),
    runner_source: parseByteIdentity(
        harness.runner_source, "navigation-churn runner-source identity"),
    source_snapshot_provenance: harness.source_snapshot_provenance,
    version_provenance: harness.version_provenance,
  });
}

function renderVersions(element, versions) {
  if (!(element instanceof HTMLElement)) {
    throw new Error("navigation-churn page is missing its version element");
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

function wasmHeapBufferCapacitySample(module, observation, stage, frameId) {
  // Reacquire HEAPU8 and its buffer for every observation. Emscripten may
  // replace typed-array views after Wasm memory growth, so this host never
  // retains a buffer or view between observations.
  const heap = module?.HEAPU8;
  if (!(heap instanceof Uint8Array)) {
    throw new Error("navigation-churn Module.HEAPU8 is not a Uint8Array");
  }
  const buffer = heap.buffer;
  if (typeof SharedArrayBuffer !== "function" ||
      !(buffer instanceof SharedArrayBuffer)) {
    throw new Error("navigation-churn Module.HEAPU8 is not backed by SharedArrayBuffer");
  }
  const capacityBytes = buffer.byteLength;
  if (!Number.isSafeInteger(capacityBytes) || capacityBytes <= 0 ||
      capacityBytes % WASM_PAGE_SIZE_BYTES !== 0) {
    throw new Error("navigation-churn Wasm heap capacity is not a positive page multiple");
  }
  return Object.freeze({
    bufferKind: "SharedArrayBuffer",
    capacityBytes,
    frameId,
    heapU8Exported: true,
    observation,
    stage,
  });
}

function stageInfo(stage) {
  if (!Number.isSafeInteger(stage) || stage < 1 || stage > STAGE_COUNT) {
    return null;
  }
  return Object.freeze({
    cycle: Math.floor((stage - 1) / NAVIGATIONS_PER_CYCLE) + 1,
    stage,
    navigation: NAVIGATION_NAMES[(stage - 1) % NAVIGATIONS_PER_CYCLE],
  });
}

function parsePresentedMarker(line) {
  const match = new RegExp(
      `^${PRESENTED_MARKER} cycle=(\\d+) stage=(\\d+) ` +
      "navigation=(first|second)$").exec(line);
  if (!match) return null;
  const cycle = Number(match[1]);
  const stage = Number(match[2]);
  const info = stageInfo(stage);
  if (!info || info.cycle !== cycle || info.navigation !== match[3]) {
    throw new Error("navigation-churn stage marker is invalid");
  }
  return info;
}

function parseNavigatedMarker(line) {
  const match = new RegExp(
      `^${NAVIGATED_MARKER} cycle=(\\d+) stage=(\\d+) ` +
      "navigation=(first|second) historyEntries=(\\d+) historyIndex=(\\d+) " +
      "historyBaselineEntries=(\\d+) historyBaselineIndex=(\\d+) " +
      "historyAppendVerified=(0|1) forwardHistory=(0|1) backHistory=(0|1) " +
      "historyExact=(0|1) titleExact=(0|1) rfhLive=(0|1) fvp=(0|1)$").exec(line);
  if (!match) return null;
  const cycle = Number(match[1]);
  const stage = Number(match[2]);
  const historyEntries = Number(match[4]);
  const historyIndex = Number(match[5]);
  const historyBaselineEntries = Number(match[6]);
  const historyBaselineIndex = Number(match[7]);
  const historyAppendVerified = match[8] === "1";
  const backHistory = match[10] === "1";
  const info = stageInfo(stage);
  const isFirstStage = stage === 1;
  if (!info || info.cycle !== cycle || info.navigation !== match[3] ||
      !Number.isSafeInteger(historyEntries) ||
      !Number.isSafeInteger(historyIndex) ||
      !Number.isSafeInteger(historyBaselineEntries) ||
      !Number.isSafeInteger(historyBaselineIndex) || historyEntries < 1 ||
      historyIndex < 0 || historyIndex >= historyEntries ||
      historyBaselineEntries < 1 || historyBaselineIndex < 0 ||
      historyBaselineIndex >= historyBaselineEntries ||
      (isFirstStage &&
       (historyBaselineEntries !== historyEntries ||
        historyBaselineIndex !== historyIndex || historyAppendVerified)) ||
      (!isFirstStage &&
       (historyEntries !== historyBaselineEntries + 1 ||
        historyIndex !== historyBaselineIndex + 1 ||
        !historyAppendVerified)) ||
      match[9] !== "0" || (!isFirstStage && !backHistory) ||
      match[11] !== "1" || match[12] !== "1" || match[13] !== "1" ||
      match[14] !== "1") {
    throw new Error("navigation-churn NAVIGATED marker is invalid");
  }
  return Object.freeze({
    ...info,
    historyEntries,
    historyIndex,
    historyBaselineEntries,
    historyBaselineIndex,
    historyAppendVerified,
    forwardHistory: false,
    backHistory,
    historyExact: true,
    titleExact: true,
    rfhLive: true,
    fvp: true,
  });
}

class ChromiumWasmBrowserNavigationChurnSmokeHost {
  #canvas;
  #versions;
  #artifact;
  #captureHarness;
  #module = null;
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
  #processExitResolver;
  #processExitPromise;
  #frameReports = [];
  #readiness = null;
  #readinessReports = [];
  #errorHandler;
  #rejectionHandler;
  #generation = 1;
  #readyObserved = false;
  #passObserved = false;
  #lifecyclePassObserved = false;
  #stages = [];
  #wasmHeapBufferCapacitySamples = [];

  constructor(canvas, versions, artifact, captureHarness) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("navigation-churn smoke requires a canvas");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#artifact = artifact;
    this.#captureHarness = captureHarness;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
    this.#processExitPromise = new Promise((resolve) => {
      this.#processExitResolver = resolve;
    });
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
    ++this.#generation;
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
    // This only records current Wasm linear-memory capacity. It does not
    // establish allocation, residency, headroom, leak, OOM, or drain state.
    this.#recordWasmHeapBufferCapacity("runtime_exit", null, null);
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
      this.#processExitResolver(report.exitCode);
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

  #recordWasmHeapBufferCapacity(observation, stage, frameId) {
    try {
      if (this.#wasmHeapBufferCapacitySamples.length >=
          WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT) {
        throw new Error("navigation-churn recorded too many Wasm capacity samples");
      }
      const sample = wasmHeapBufferCapacitySample(
          this.#module, observation, stage, frameId);
      this.#wasmHeapBufferCapacitySamples.push(sample);
      return true;
    } catch (error) {
      this.#recordFatal(`invalid navigation-churn Wasm capacity sample: ${String(error)}`);
      return false;
    }
  }

  #wasmHeapBufferCapacitySnapshot() {
    const samples = this.#wasmHeapBufferCapacitySamples.map((sample) => ({...sample}));
    const capacities = samples.map((sample) => sample.capacityBytes);
    const highWaterBytes = capacities.length === 0 ? null : Math.max(...capacities);
    return {
      definition: WASM_HEAP_BUFFER_CAPACITY_DEFINITION,
      grew: capacities.length !== 0 && highWaterBytes > capacities[0],
      highWaterBytes,
      nondecreasing: capacities.length !== 0 &&
          capacities.every((capacity, index) =>
            index === 0 || capacity >= capacities[index - 1]),
      sampleCount: samples.length,
      samples,
    };
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

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("navigation-churn host bridge is already installed");
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
      reportAccessibilitySnapshot(_report) { return false; },
    });
  }

  #activeStage() {
    return this.#stages.at(-1) ?? null;
  }

  #queueBackingStoreCopy(stage) {
    if (stage.presentationQueued) return;
    stage.presentationQueued = true;
    const generation = this.#generation;
    setTimeout(() => {
      if (generation !== this.#generation || this.#activeStage() !== stage ||
          stage.presentedObserved || stage.backingStoreCopyFrameId === null) {
        this.#recordFatal("navigation-churn deferred copy acknowledgement lost order");
        return;
      }
      if (!this.#module || typeof this.#module.ccall !== "function") {
        this.#recordFatal("navigation-churn acknowledgement ran without Module.ccall");
        return;
      }
      try {
        const accepted = this.#module.ccall(
            "chromium_wasm_browser_host_navigation_churn_presented", "number",
            ["number"], [stage.stage]);
        if (accepted !== 1) {
          this.#recordFatal(
              `navigation-churn acknowledgement rejected stage ${stage.stage}`);
        }
      } catch (error) {
        this.#recordFatal(
            `navigation-churn acknowledgement failed: ${String(error)}`);
      }
    }, 0);
  }

  #maybeQueueBackingStoreCopy() {
    const active = this.#activeStage();
    if (!active || active.presentationQueued || active.presentedObserved ||
        active.backingStoreCopyFrameId !== null || this.#fatalErrors.length !== 0) {
      return;
    }
    const frame = this.#firstFrameAfter(active.navigationMarkerFrameId);
    if (!frame) return;
    active.backingStoreCopyFrameId = frame.id;
    // This is the fixed stage/frame-bound later Canvas2D-copy observation
    // already used to acknowledge each native navigation stage.
    if (!this.#recordWasmHeapBufferCapacity(
        "stage_backing_store_copy", active.stage, frame.id)) {
      return;
    }
    this.#queueBackingStoreCopy(active);
  }

  #recordOutput(value) {
    const line = String(value);
    try {
      if (line.startsWith(FAILURE_MARKER) || line.startsWith(TIMEOUT_MARKER)) {
        throw new Error(`native navigation churn failed: ${line}`);
      }
      if (line === `${READY_MARKER} cycles=${CYCLE_COUNT} navigations=${STAGE_COUNT}`) {
        if (this.#readyObserved || this.#stages.length !== 0) {
          throw new Error("navigation-churn READY marker is duplicated or late");
        }
        this.#readyObserved = true;
        return;
      }
      const navigated = parseNavigatedMarker(line);
      if (navigated) {
        const previous = this.#activeStage();
        if (!this.#readyObserved ||
            (previous && (!previous.presentationQueued ||
                          !previous.presentedObserved ||
                          navigated.stage !== previous.stage + 1)) ||
            (!previous && navigated.stage !== 1) ||
            this.#stages.length !== navigated.stage - 1) {
          throw new Error("navigation-churn NAVIGATED marker is out of order");
        }
        this.#stages.push({
          ...navigated,
          navigationMarkerFrameId: this.#currentFrameId(),
          backingStoreCopyFrameId: null,
          presentationQueued: false,
          presentedObserved: false,
        });
        this.#maybeQueueBackingStoreCopy();
        return;
      }
      const presented = parsePresentedMarker(line);
      if (presented) {
        const active = this.#activeStage();
        if (!active || active.stage !== presented.stage ||
            !active.presentationQueued || active.presentedObserved ||
            active.backingStoreCopyFrameId === null) {
          throw new Error("navigation-churn PRESENTED marker is out of order");
        }
        active.presentedObserved = true;
        return;
      }
      if (line === `${PASS_MARKER} cycles=${CYCLE_COUNT} navigations=${STAGE_COUNT}`) {
        const active = this.#activeStage();
        if (!active || active.stage !== STAGE_COUNT ||
            !active.presentedObserved || this.#passObserved) {
          throw new Error("navigation-churn PASS marker is out of order");
        }
        this.#passObserved = true;
        return;
      }
      if (line === LIFECYCLE_PASS_MARKER) {
        if (this.#lifecyclePassObserved) {
          throw new Error("navigation-churn lifecycle marker is duplicated");
        }
        this.#lifecyclePassObserved = true;
        return;
      }
      if (line.startsWith(READY_MARKER) || line.startsWith(NAVIGATED_MARKER) ||
          line.startsWith(PRESENTED_MARKER) || line.startsWith(PASS_MARKER) ||
          line.startsWith(LIFECYCLE_PASS_MARKER)) {
        throw new Error(`malformed navigation-churn marker: ${line}`);
      }
    } catch (error) {
      this.#recordFatal(`invalid navigation-churn output: ${String(error)}`);
    }
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null ||
        typeof module.ccall !== "function" ||
        typeof module._chromium_wasm_browser_host_navigation_churn_presented !==
            "function") {
      this.#recordFatal("Module lacks the narrow navigation-churn acknowledgement export");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#recordWasmHeapBufferCapacity("runtime_initialized", null, null);
  }

  #stageSnapshot(stage) {
    return {
      cycle: stage.cycle,
      stage: stage.stage,
      navigation: stage.navigation,
      historyEntries: stage.historyEntries,
      historyIndex: stage.historyIndex,
      historyBaselineEntries: stage.historyBaselineEntries,
      historyBaselineIndex: stage.historyBaselineIndex,
      historyAppendVerified: stage.historyAppendVerified,
      forwardHistory: stage.forwardHistory,
      backHistory: stage.backHistory,
      historyExact: stage.historyExact,
      titleExact: stage.titleExact,
      rfhLive: stage.rfhLive,
      fvp: stage.fvp,
      navigationMarkerFrameId: stage.navigationMarkerFrameId,
      backingStoreCopyFrameId: stage.backingStoreCopyFrameId,
      presentationQueued: stage.presentationQueued,
      presentedObserved: stage.presentedObserved,
    };
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
      navigationChurn: {
        cycleCount: CYCLE_COUNT,
        navigationsPerCycle: NAVIGATIONS_PER_CYCLE,
        stageCount: STAGE_COUNT,
        frameTransitionPolicy: FRAME_TRANSITION_POLICY,
        readyObserved: this.#readyObserved,
        passObserved: this.#passObserved,
        lifecyclePassObserved: this.#lifecyclePassObserved,
        stages: this.#stages.map((stage) => this.#stageSnapshot(stage)),
      },
      wasmHeapBufferCapacity: this.#wasmHeapBufferCapacitySnapshot(),
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
        throw new Error("navigation-churn smoke requires cross-origin isolation");
      }
      if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("navigation-churn timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("navigation-churn module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("navigation-churn canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("navigation-churn module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("navigation-churn loader has no default factory export");
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
      }).catch((error) => {
        host.#factorySettled = true;
        host.#recordFatal(`module factory rejected: ${String(error)}`);
      });

      const deadline = startedAt + timeoutMs;
      while ((this.#runtimeExitCode === null ||
              this.#processExitCode === null || !this.#factorySettled) &&
             performance.now() < deadline) {
        const waits = [delay(25)];
        if (this.#runtimeExitCode === null) {
          waits.push(this.#runtimeExitPromise);
        }
        if (this.#processExitCode === null) {
          waits.push(this.#processExitPromise);
        }
        await Promise.race(waits);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("navigation-churn smoke did not exit before timeout");
      }
      if (this.#processExitCode === null) {
        throw new Error(
            "navigation-churn smoke did not report process exit before timeout");
      }
      if (!this.#factorySettled) {
        throw new Error("navigation-churn module factory did not settle before timeout");
      }
      // This is a bounded queued-error observation window, not a thread or
      // resource quiescence/drain proof.
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#releaseWindowErrors();
    }
  }
}

function countMarker(records, marker) {
  return records.filter((record) => record === marker).length;
}

function navigatedMarker(info) {
  return `${NAVIGATED_MARKER} cycle=${info.cycle} stage=${info.stage} ` +
      `navigation=${info.navigation} historyEntries=${info.historyEntries} ` +
      `historyIndex=${info.historyIndex} historyBaselineEntries=` +
      `${info.historyBaselineEntries} historyBaselineIndex=` +
      `${info.historyBaselineIndex} historyAppendVerified=` +
      `${info.historyAppendVerified ? 1 : 0} forwardHistory=0 backHistory=` +
      `${info.backHistory ? 1 : 0} historyExact=1 titleExact=1 ` +
      "rfhLive=1 fvp=1";
}

function presentedMarker(info) {
  return `${PRESENTED_MARKER} cycle=${info.cycle} stage=${info.stage} ` +
      `navigation=${info.navigation}`;
}

function frameIds(result) {
  return new Set((result.frameReports || []).map((frame) => frame?.id));
}

function hasExactFields(value, fields) {
  return value && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === fields.length &&
      fields.every((field) => Object.hasOwn(value, field));
}

function validateWasmHeapBufferCapacity(result, churn, require) {
  const capacity = result.wasmHeapBufferCapacity;
  const capacityFields = [
    "definition", "grew", "highWaterBytes", "nondecreasing", "sampleCount",
    "samples",
  ];
  const sampleFields = [
    "bufferKind", "capacityBytes", "frameId", "heapU8Exported",
    "observation", "stage",
  ];
  require(hasExactFields(capacity, capacityFields),
      "navigation-churn Wasm capacity evidence schema is invalid");
  if (!hasExactFields(capacity, capacityFields)) return;
  require(capacity.definition === WASM_HEAP_BUFFER_CAPACITY_DEFINITION,
      "navigation-churn Wasm capacity definition is invalid");
  require(capacity.sampleCount === WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT &&
      Array.isArray(capacity.samples) &&
      capacity.samples.length === WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT,
  "navigation-churn Wasm capacity sample count is invalid");
  if (!Array.isArray(capacity.samples) ||
      capacity.samples.length !== WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT) {
    return;
  }

  const capacities = [];
  for (let index = 0; index < capacity.samples.length; ++index) {
    const sample = capacity.samples[index];
    let expectedObservation = "stage_backing_store_copy";
    let expectedStage = null;
    let expectedFrameId = null;
    if (index === 0) {
      expectedObservation = "runtime_initialized";
    } else if (index === capacity.samples.length - 1) {
      expectedObservation = "runtime_exit";
    } else {
      const observedStage = churn?.stages?.[index - 1];
      expectedStage = index;
      expectedFrameId = observedStage?.backingStoreCopyFrameId;
    }
    require(hasExactFields(sample, sampleFields),
        `navigation-churn Wasm capacity sample ${index} schema is invalid`);
    if (!hasExactFields(sample, sampleFields)) continue;
    require(sample.bufferKind === "SharedArrayBuffer" &&
        sample.heapU8Exported === true,
    `navigation-churn Wasm capacity sample ${index} lacks shared Uint8Array evidence`);
    require(Number.isSafeInteger(sample.capacityBytes) && sample.capacityBytes > 0 &&
        sample.capacityBytes % WASM_PAGE_SIZE_BYTES === 0,
    `navigation-churn Wasm capacity sample ${index} is not a positive page multiple`);
    require(sample.observation === expectedObservation &&
        sample.stage === expectedStage && sample.frameId === expectedFrameId,
    `navigation-churn Wasm capacity sample ${index} is not bound to its observation`);
    if (Number.isSafeInteger(sample.capacityBytes) && sample.capacityBytes > 0 &&
        sample.capacityBytes % WASM_PAGE_SIZE_BYTES === 0) {
      capacities.push(sample.capacityBytes);
    }
  }
  if (capacities.length !== WASM_HEAP_BUFFER_CAPACITY_SAMPLE_COUNT) return;
  const nondecreasing = capacities.every((value, index) =>
    index === 0 || value >= capacities[index - 1]);
  const highWaterBytes = Math.max(...capacities);
  require(capacity.nondecreasing === true && capacity.nondecreasing === nondecreasing,
      "navigation-churn Wasm capacity is not nondecreasing");
  require(capacity.highWaterBytes === highWaterBytes,
      "navigation-churn Wasm capacity high water is invalid");
  require(typeof capacity.grew === "boolean" &&
      capacity.grew === (highWaterBytes > capacities[0]),
  "navigation-churn Wasm capacity growth flag is invalid");
}

function validateResult(result) {
  const failures = [];
  const require = (condition, message) => {
    if (!condition) failures.push(message);
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.runtimeExitCode === 0, "runtime did not exit zero");
  require(result.processExitCode === 0,
      "bridge process exit did not report zero");
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

  const churn = result.navigationChurn;
  require(churn?.cycleCount === CYCLE_COUNT, "wrong navigation-churn cycle count");
  require(churn?.navigationsPerCycle === NAVIGATIONS_PER_CYCLE,
      "wrong navigation-churn cycle width");
  require(churn?.stageCount === STAGE_COUNT, "wrong navigation-churn stage count");
  require(churn?.frameTransitionPolicy === FRAME_TRANSITION_POLICY,
      "wrong navigation-churn frame-transition policy");
  require(churn?.readyObserved === true, "native navigation churn was not ready");
  require(churn?.passObserved === true, "native navigation churn did not pass");
  require(churn?.lifecyclePassObserved === true,
      "Browser lifecycle did not close after navigation churn");
  require(Array.isArray(churn?.stages) && churn.stages.length === STAGE_COUNT,
      "wrong navigation-churn stage evidence count");

  const observedFrameIds = frameIds(result);
  for (let index = 0; index < (churn?.stages?.length || 0); ++index) {
    const stage = churn.stages[index];
    const expected = stageInfo(index + 1);
    require(stage?.cycle === expected.cycle && stage?.stage === expected.stage &&
        stage?.navigation === expected.navigation,
    `navigation-churn stage ${index + 1} has an invalid identity`);
    require(Number.isSafeInteger(stage?.historyEntries) &&
        Number.isSafeInteger(stage?.historyIndex) &&
        Number.isSafeInteger(stage?.historyBaselineEntries) &&
        Number.isSafeInteger(stage?.historyBaselineIndex) &&
        stage.historyEntries >= 1 && stage.historyIndex >= 0 &&
        stage.historyIndex < stage.historyEntries &&
        stage.historyBaselineEntries >= 1 && stage.historyBaselineIndex >= 0 &&
        stage.historyBaselineIndex < stage.historyBaselineEntries &&
        stage.forwardHistory === false &&
        typeof stage.backHistory === "boolean" &&
        stage.historyExact === true &&
        stage?.titleExact === true && stage?.rfhLive === true &&
        stage?.fvp === true,
    `navigation-churn stage ${index + 1} lacks native history/title/RFH/FVP evidence`);
    require(Number.isSafeInteger(stage?.navigationMarkerFrameId) &&
        stage.navigationMarkerFrameId >= 0 &&
        Number.isSafeInteger(stage?.backingStoreCopyFrameId) &&
        stage.backingStoreCopyFrameId > stage.navigationMarkerFrameId &&
        stage?.presentationQueued === true && stage?.presentedObserved === true,
    `navigation-churn stage ${index + 1} lacks ordered native/copy evidence`);
    require(observedFrameIds.has(stage?.backingStoreCopyFrameId),
        `navigation-churn stage ${index + 1} copy is not an observed frame`);
    if (stage?.navigationMarkerFrameId > 0) {
      require(observedFrameIds.has(stage.navigationMarkerFrameId),
          `navigation-churn stage ${index + 1} marker frame is not observed`);
    }
    if (index > 0) {
      const previous = churn.stages[index - 1];
      require(stage?.historyAppendVerified === true &&
          stage?.backHistory === true &&
          stage?.historyBaselineEntries === previous?.historyEntries &&
          stage?.historyBaselineIndex === previous?.historyIndex &&
          stage?.historyEntries === stage?.historyBaselineEntries + 1 &&
          stage?.historyIndex === stage?.historyBaselineIndex + 1,
      `navigation-churn stage ${index + 1} history did not append from stage ${index}`);
      require(previous?.backingStoreCopyFrameId <= stage?.navigationMarkerFrameId,
          `navigation-churn stages ${index}/${index + 1} have reverse copy order`);
    } else {
      require(stage?.historyAppendVerified === false &&
          stage?.historyBaselineEntries === stage?.historyEntries &&
          stage?.historyBaselineIndex === stage?.historyIndex,
      "navigation-churn stage one did not capture its post-navigation baseline");
    }
  }
  require(Array.isArray(result.frameReports) && result.frameReports.length >= STAGE_COUNT,
      "navigation churn has too few frame reports");
  validateWasmHeapBufferCapacity(result, churn, require);
  require(result.artifact?.artifact_source_provenance ===
      ARTIFACT_SOURCE_PROVENANCE,
  "navigation-churn artifact source provenance is not unverified");
  require(result.artifact?.artifact_delivery === ARTIFACT_DELIVERY,
      "navigation-churn artifact delivery is not an immutable snapshot");
  require(result.artifact?.module_name === PRODUCT_MODULE_NAME,
      "navigation-churn artifact module is not chrome_wasm");
  require(result.capture_harness?.source_snapshot_provenance ===
      SOURCE_SNAPSHOT_PROVENANCE,
  "navigation-churn harness source provenance is invalid");
  require(result.capture_harness?.version_provenance === VERSION_PROVENANCE,
      "navigation-churn version provenance is invalid");

  const stderr = Array.isArray(result.stderr) ? result.stderr : [];
  const readyMarker = `${READY_MARKER} cycles=${CYCLE_COUNT} navigations=${STAGE_COUNT}`;
  const passMarker = `${PASS_MARKER} cycles=${CYCLE_COUNT} navigations=${STAGE_COUNT}`;
  require(countMarker(stderr, readyMarker) === 1,
      "navigation-churn READY marker is not unique");
  require(countMarker(stderr, passMarker) === 1,
      "navigation-churn PASS marker is not unique");
  require(countMarker(stderr, LIFECYCLE_PASS_MARKER) === 1,
      "navigation-churn lifecycle marker is not unique");
  for (let stage = 1; stage <= STAGE_COUNT; ++stage) {
    const observedStage = churn.stages[stage - 1];
    require(countMarker(stderr, navigatedMarker(observedStage)) === 1,
        `navigation-churn stage ${stage} NAVIGATED marker is not unique`);
    require(countMarker(stderr, presentedMarker(observedStage)) === 1,
        `navigation-churn stage ${stage} PRESENTED marker is not unique`);
  }
  const orderedMarkers = [readyMarker];
  for (let stage = 1; stage <= STAGE_COUNT; ++stage) {
    const observedStage = churn.stages[stage - 1];
    orderedMarkers.push(navigatedMarker(observedStage), presentedMarker(observedStage));
  }
  orderedMarkers.push(passMarker, LIFECYCLE_PASS_MARKER);
  let previousMarkerIndex = -1;
  for (const marker of orderedMarkers) {
    const markerIndex = stderr.indexOf(marker);
    require(markerIndex > previousMarkerIndex,
        `navigation-churn marker order is invalid at ${marker}`);
    previousMarkerIndex = markerIndex;
  }

  result.failedChecks = failures;
  if (failures.length !== 0) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserNavigationChurnSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  if (moduleName !== PRODUCT_MODULE_NAME) {
    throw new Error(
        "navigation-churn query must select the chrome_wasm product module");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "90000");
  const versions = parseVersions(query.get("versions"));
  const artifact = parseArtifactIdentity(query.get("artifact"));
  if (artifact.module_name !== moduleName) {
    throw new Error("navigation-churn artifact module name disagrees with query");
  }
  const captureHarness = parseCaptureHarnessIdentity(query.get("captureHarness"));
  const root = document.querySelector("#browser-navigation-churn-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-navigation-churn-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("navigation-churn page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserNavigationChurnSmokeHost(
      canvas, versions, artifact, captureHarness);
  const result = validateResult(await host.run(
      `${location.pathname.replace(/\/$/, "")}/artifacts/${PRODUCT_MODULE_NAME}.js`,
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

export const chromeWasmBrowserNavigationChurnSmokeContract = Object.freeze({
  ARTIFACT_DELIVERY,
  ARTIFACT_SOURCE_PROVENANCE,
  CASE,
  CYCLE_COUNT,
  PRODUCT_MODULE_NAME,
  FRAME_TRANSITION_POLICY,
  HOST_PROTOCOL,
  LIMITATIONS,
  NAVIGATIONS_PER_CYCLE,
  PASS_MARKER,
  PRESENTED_MARKER,
  READY_MARKER,
  SCOPE,
  STAGE_COUNT,
  SWITCH,
  VERSION_PROVENANCE,
  NAVIGATED_MARKER,
});

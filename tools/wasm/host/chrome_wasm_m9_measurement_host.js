// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This is an observational M9 baseline, not a benchmark or a release gate.
// It starts one normal chrome_wasm instance in a fresh outer-page lifetime,
// records host-visible phase boundaries, then lets the runner request the
// existing one-shot host shutdown ABI. It intentionally does not compare
// runs, claim persistence, infer Wasm residency from a HEAP buffer capacity,
// or infer worker utilization, saturation, or long-run behavior.

const HOST_PROTOCOL = 1;
const SCHEMA_VERSION = 4;
const CASE = "chrome_wasm_m9_measurement_baseline";
const PRODUCT_MODULE_NAME = "chrome_wasm";
const SCOPE = "one-fresh-host-run-cold-loader-runtime-frame-wasm-buffer-capacity-" +
    "native-memory-snapshot-first-pthread-worker-bootstrap-event-delivery-" +
    "canvas2d-pixel-witness";
const RELEASE_STATUS = "pre_m7_m8_not_releasable";
const MAX_TIMEOUT_MS = 120000;
const MIN_TIMEOUT_MS = 10000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_FAILURE_TEXT = 512;
const TERMINAL_GRACE_OBSERVATION_MS = 25;
const WASM_MEMORY_PAGE_BYTES = 64 * 1024;
const COLD_START_DEFINITION =
    "one outer-page navigation in a fresh host-browser profile; " +
    "no OS cache eviction or cross-run comparison";
const WASM_HEAP_BUFFER_CAPACITY_DEFINITION =
    "HEAPU8.buffer.byteLength capacity; not allocated or resident memory usage";
const NATIVE_MEMORY_SNAPSHOT_DEFINITION =
    "exact native counters: current and configured-maximum Emscripten Wasm " +
    "linear-memory capacity plus derived headroom; PageAllocator total logical " +
    "mappings across clients may be uncommitted; none is RSS, committed-memory, " +
    "allocation, or leak evidence";
const WORKER_OBSERVATION_DEFINITION =
    "host Worker construction and loader loaded-control messages plus one first " +
    "matched pthread Worker main-thread observed construction-to-loaded-control-" +
    "message bootstrap/event-delivery latency; not worker CPU utilization, " +
    "saturation, drain, or internal execution";
const CANVAS_PIXEL_WITNESS_GRID_COLUMNS = 8;
const CANVAS_PIXEL_WITNESS_GRID_ROWS = 8;
const CANVAS_PIXEL_WITNESS_DEFINITION =
    "fixed 8x8 Canvas2D backing-store RGB sampling after the first reportFrame " +
    "following its synchronous ImageData copy; visible_pixels_observed means " +
    "at least one nonblack sampled RGB value, not first visually nonempty " +
    "paint, raster, compositor, display, or vsync evidence";
const MEASUREMENT_LIMITS = Object.freeze([
  "observational pre-release baseline only; not a performance gate",
  "one sample only; no cross-run performance inference or benchmark claim",
  "frame timing is the host callback after synchronous Canvas2D " +
      "ImageData copy; not raster, compositor, or vsync presentation timing",
  "Canvas2D pixel witness samples only a fixed backing-store RGB grid after " +
      "the first frame copy; it is not first visually nonempty paint, raster, " +
      "compositor, display, or vsync evidence",
  "HEAPU8.buffer.byteLength is Wasm buffer capacity, not allocated or " +
      "resident memory usage",
  "native memory counters distinguish Wasm capacity/maximum/headroom from " +
      "PageAllocator logical mappings; none measures RSS, committed memory, " +
      "allocations, or leaks",
  "terminal 25 ms grace observes queued host errors only; it does not " +
      "prove worker drain, utilization, or saturation",
  "worker evidence counts host Worker construction and loader " +
      "loaded-control messages and records only the first matched pthread " +
      "Worker main-thread construction-to-loaded-control-message bootstrap/event-" +
      "delivery latency; it does not measure CPU utilization, saturation, drain, " +
      "or internal execution",
  "does not measure V8, layout, raster, network, OPFS, persistence, or " +
      "long-run reliability",
]);
const HOST_MODULE_EVALUATED_MS = performance.now();

function boundedFailure(value) {
  return String(value).slice(0, MAX_FAILURE_TEXT);
}

function finiteTimestamp(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function positiveInteger(value) {
  return Number.isSafeInteger(value) && value >= 1;
}

function frameReport(value) {
  return value && typeof value === "object" &&
      value.protocol === HOST_PROTOCOL && positiveInteger(value.id) &&
      positiveInteger(value.width) && value.width <= MAX_FRAME_DIMENSION &&
      positiveInteger(value.height) && value.height <= MAX_FRAME_DIMENSION &&
      finiteTimestamp(value.timestampMs);
}

function readinessReport(value) {
  return value && typeof value === "object" &&
      value.protocol === HOST_PROTOCOL &&
      typeof value.shellReady === "boolean" &&
      typeof value.surfaceReady === "boolean" &&
      typeof value.firstVisuallyNonEmptyPaint === "boolean";
}

function focusReport(value) {
  return value && typeof value === "object" &&
      value.protocol === HOST_PROTOCOL &&
      typeof value.keyboardTargetPresent === "boolean" &&
      typeof value.active === "boolean";
}

// Samples the Canvas2D backing store after the platform's synchronous frame
// copy. This intentionally retains only bounded aggregate RGB evidence: it
// does not retain page pixels or infer what the browser compositor displayed.
export function canvasPixelWitness(canvas) {
  if (!canvas || !positiveInteger(canvas.width) ||
      !positiveInteger(canvas.height) ||
      canvas.width > MAX_FRAME_DIMENSION ||
      canvas.height > MAX_FRAME_DIMENSION ||
      typeof canvas.getContext !== "function") {
    throw new Error("Canvas2D pixel witness requires a bounded canvas");
  }
  const context = canvas.getContext("2d", {willReadFrequently: true});
  if (!context || typeof context.getImageData !== "function") {
    throw new Error("Canvas2D pixel witness requires a readable 2D context");
  }

  const distinctRgbValues = new Set();
  let nonblackRgbSampleCount = 0;
  for (let row = 0; row < CANVAS_PIXEL_WITNESS_GRID_ROWS; ++row) {
    const y = Math.min(canvas.height - 1, Math.floor(
        (row + 0.5) * canvas.height / CANVAS_PIXEL_WITNESS_GRID_ROWS));
    for (let column = 0; column < CANVAS_PIXEL_WITNESS_GRID_COLUMNS; ++column) {
      const x = Math.min(canvas.width - 1, Math.floor(
          (column + 0.5) * canvas.width / CANVAS_PIXEL_WITNESS_GRID_COLUMNS));
      const imageData = context.getImageData(x, y, 1, 1);
      if (!imageData || !(imageData.data instanceof Uint8ClampedArray) ||
          imageData.data.length !== 4) {
        throw new Error("Canvas2D pixel witness returned malformed pixel data");
      }
      const rgb = (imageData.data[0] << 16) |
          (imageData.data[1] << 8) | imageData.data[2];
      distinctRgbValues.add(rgb);
      if (rgb !== 0) {
        nonblackRgbSampleCount += 1;
      }
    }
  }
  const sampleCount = CANVAS_PIXEL_WITNESS_GRID_COLUMNS *
      CANVAS_PIXEL_WITNESS_GRID_ROWS;
  return Object.freeze({
    definition: CANVAS_PIXEL_WITNESS_DEFINITION,
    distinct_rgb_value_count: distinctRgbValues.size,
    non_black_rgb_sample_count: nonblackRgbSampleCount,
    sample_count: sampleCount,
    sample_grid_columns: CANVAS_PIXEL_WITNESS_GRID_COLUMNS,
    sample_grid_rows: CANVAS_PIXEL_WITNESS_GRID_ROWS,
    visible_pixels_observed: nonblackRgbSampleCount !== 0,
  });
}

function wasmHeapBufferCapacitySnapshot(module) {
  const heap = module?.HEAPU8;
  const buffer = heap instanceof Uint8Array ? heap.buffer : null;
  const shared = typeof SharedArrayBuffer === "function" &&
      buffer instanceof SharedArrayBuffer;
  return Object.freeze({
    buffer_kind: buffer === null ? "unavailable" :
        shared ? "SharedArrayBuffer" : "ArrayBuffer",
    wasm_heap_buffer_capacity_bytes:
        buffer !== null && Number.isSafeInteger(buffer.byteLength) ?
        buffer.byteLength : null,
    heap_u8_exported: heap instanceof Uint8Array,
    shared: shared,
  });
}

const NATIVE_MEMORY_METRICS = Object.freeze({
  page_allocator_total_mapped_bytes:
      "chromium_wasm_browser_host_memory_page_allocator_total_mapped_bytes",
  wasm_linear_memory_capacity_bytes:
      "chromium_wasm_browser_host_memory_linear_capacity_bytes",
  wasm_linear_memory_maximum_bytes:
      "chromium_wasm_browser_host_memory_linear_maximum_bytes",
});

// Captures exact byte counters from the Wasm module without deriving process
// memory use. The output remains intentionally narrower than RSS, committed
// memory, individual allocations, or leak diagnosis.
export function nativeMemorySnapshot(module) {
  if (!module || typeof module.ccall !== "function") {
    throw new Error("native memory metrics require Module.ccall");
  }

  const metrics = {};
  for (const [field, exportName] of Object.entries(NATIVE_MEMORY_METRICS)) {
    let value;
    try {
      value = module.ccall(exportName, "number", [], []);
    } catch (error) {
      throw new Error(`native memory metric export ${exportName} is unavailable: ` +
          boundedFailure(error));
    }
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new Error(`native memory metric ${field} is not an exact nonnegative ` +
          "byte count");
    }
    metrics[field] = value;
  }

  const capacity = metrics.wasm_linear_memory_capacity_bytes;
  const maximum = metrics.wasm_linear_memory_maximum_bytes;
  const mapped = metrics.page_allocator_total_mapped_bytes;
  if (capacity < WASM_MEMORY_PAGE_BYTES ||
      maximum < WASM_MEMORY_PAGE_BYTES) {
    throw new Error("native Wasm linear-memory capacity is below one page");
  }
  for (const [field, value] of Object.entries({
    page_allocator_total_mapped_bytes: mapped,
    wasm_linear_memory_capacity_bytes: capacity,
    wasm_linear_memory_maximum_bytes: maximum,
  })) {
    if (value % WASM_MEMORY_PAGE_BYTES !== 0) {
      throw new Error(`native memory metric ${field} is not Wasm-page aligned`);
    }
  }
  if (maximum < capacity) {
    throw new Error("native Wasm linear-memory maximum is below current capacity");
  }
  const headroom = maximum - capacity;
  if (!Number.isSafeInteger(headroom) || headroom < 0 ||
      headroom % WASM_MEMORY_PAGE_BYTES !== 0) {
    throw new Error("native Wasm linear-memory headroom is invalid");
  }

  return Object.freeze({
    page_allocator_total_mapped_bytes: mapped,
    wasm_linear_memory_capacity_bytes: capacity,
    wasm_linear_memory_headroom_bytes: headroom,
    wasm_linear_memory_maximum_bytes: maximum,
  });
}

function timingDelta(timing, start, end) {
  const started = timing[start];
  const finished = timing[end];
  if (!finiteTimestamp(started) || !finiteTimestamp(finished) ||
      finished < started) {
    return null;
  }
  return Number((finished - started).toFixed(3));
}

class WorkerObservation {
  #constructionAttempts = 0;
  #workersConstructed = 0;
  #loadedMessages = 0;
  #errorEvents = 0;
  #messageErrorEvents = 0;
  #loadedWorkers = new WeakSet();
  #firstMatchedPthreadWorkerStartup = null;
  #nativeWorker = null;
  #wrappedWorker = null;

  install() {
    const nativeWorker = globalThis.Worker;
    if (typeof nativeWorker !== "function") {
      throw new Error("Worker is unavailable for pthread observation");
    }
    const observation = this;
    const wrappedWorker = new Proxy(nativeWorker, {
      construct(target, argumentsList) {
        observation.#constructionAttempts += 1;
        // Preserve the platform Worker constructor exactly. The observer adds
        // passive event listeners only; it neither owns nor intercepts the
        // Emscripten worker's onmessage handler.
        //
        // This is a main-thread timestamp immediately before constructor
        // entry, not a worker CPU, scheduling, or internal-execution measure.
        const constructionTimeMs = performance.now();
        const worker = Reflect.construct(target, argumentsList);
        observation.#workersConstructed += 1;
        worker.addEventListener("message", (event) => {
          if (event?.data?.cmd === "loaded" &&
              !observation.#loadedWorkers.has(worker)) {
            // Emscripten's pthread loader emits this control message. Record
            // only the first matching arrival, passively, on the host main
            // thread. This neither sends to nor controls the worker.
            const loadedControlMessageArrivalTimeMs = performance.now();
            observation.#loadedWorkers.add(worker);
            observation.#loadedMessages += 1;
            if (observation.#firstMatchedPthreadWorkerStartup === null) {
              const durationMs = loadedControlMessageArrivalTimeMs -
                  constructionTimeMs;
              if (!finiteTimestamp(constructionTimeMs) ||
                  !finiteTimestamp(loadedControlMessageArrivalTimeMs) ||
                  !Number.isFinite(durationMs) || durationMs < 0) {
                throw new Error("invalid pthread Worker bootstrap observation");
              }
              observation.#firstMatchedPthreadWorkerStartup = Object.freeze({
                construction_time_ms: constructionTimeMs,
                loaded_control_message_arrival_time_ms:
                    loadedControlMessageArrivalTimeMs,
                construction_to_loaded_control_message_arrival_ms:
                    Number(durationMs.toFixed(3)),
              });
            }
          }
        });
        worker.addEventListener("error", () => {
          observation.#errorEvents += 1;
        });
        worker.addEventListener("messageerror", () => {
          observation.#messageErrorEvents += 1;
        });
        return worker;
      },
    });
    globalThis.Worker = wrappedWorker;
    this.#nativeWorker = nativeWorker;
    this.#wrappedWorker = wrappedWorker;
  }

  dispose() {
    if (this.#wrappedWorker !== null && globalThis.Worker === this.#wrappedWorker) {
      globalThis.Worker = this.#nativeWorker;
    }
    this.#nativeWorker = null;
    this.#wrappedWorker = null;
  }

  snapshot() {
    return Object.freeze({
      construction_attempts: this.#constructionAttempts,
      error_events: this.#errorEvents,
      loaded_control_messages: this.#loadedMessages,
      message_error_events: this.#messageErrorEvents,
      workers_constructed: this.#workersConstructed,
    });
  }

  firstMatchedPthreadWorkerStartup() {
    return this.#firstMatchedPthreadWorkerStartup;
  }
}

class ChromiumWasmM9MeasurementHost {
  #canvas;
  #statusElement;
  #workerObservation = new WorkerObservation();
  #module = null;
  #firstFrame = null;
  #canvasPixelWitness = null;
  #readiness = {
    firstVisuallyNonEmptyPaint: false,
    shellReady: false,
    surfaceReady: false,
  };
  #activeOzoneFocus = false;
  #runtimeExitCode = null;
  #processExitCode = null;
  #shutdownResults = null;
  #factorySettled = false;
  #factoryRejected = false;
  #fatalErrorCount = 0;
  #windowErrorCount = 0;
  #unhandledRejectionCount = 0;
  #failure = null;
  #state = "starting";
  #stateSequence = ["starting"];
  #terminalGraceObserved = false;
  #timerHandle = null;
  #errorHandler;
  #rejectionHandler;
  #wasmHeapBufferCapacityAtRuntimeInitialized = null;
  #wasmHeapBufferCapacityAtFirstFrame = null;
  #wasmHeapBufferCapacityAtRuntimeExit = null;
  #nativeMemoryAtRuntimeInitialized = null;
  #nativeMemoryAtFirstFrame = null;
  #nativeMemoryAtPreShutdown = null;
  #workersAtRuntimeInitialized = null;
  #workersAtFirstFrame = null;
  #workersAtRuntimeExit = null;
  #timing = {
    factory_call_started: null,
    host_module_evaluated: HOST_MODULE_EVALUATED_MS,
    host_run_started: null,
    loader_blob_ready: null,
    loader_fetch_started: null,
    loader_response_ready: null,
    module_factory_export_ready: null,
    module_import_started: null,
    ready: null,
    runtime_exit: null,
    runtime_initialized: null,
    shutdown_requested: null,
    surface_ready_callback: null,
    first_frame_callback_after_canvas_copy: null,
  };

  constructor(canvas, statusElement) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("M9 measurement host requires a canvas");
    }
    if (!(statusElement instanceof HTMLElement)) {
      throw new Error("M9 measurement host requires a status element");
    }
    this.#canvas = canvas;
    this.#statusElement = statusElement;
  }

  #now() {
    return performance.now();
  }

  #setTiming(name) {
    if (this.#timing[name] === null) {
      this.#timing[name] = this.#now();
    }
  }

  #setState(state) {
    if (this.#state === state) {
      return;
    }
    this.#state = state;
    this.#stateSequence.push(state);
    document.querySelector("#measurement-root").dataset.state = state;
    this.#statusElement.textContent = JSON.stringify(this.snapshot(), null, 2);
  }

  #fail(error) {
    if (this.#state === "failed") {
      return;
    }
    this.#failure = boundedFailure(error);
    this.#setState("failed");
  }

  #installErrorObservers() {
    this.#errorHandler = () => {
      this.#windowErrorCount += 1;
      this.#fail("host observed a window error");
    };
    this.#rejectionHandler = () => {
      this.#unhandledRejectionCount += 1;
      this.#fail("host observed an unhandled rejection");
    };
    addEventListener("error", this.#errorHandler);
    addEventListener("unhandledrejection", this.#rejectionHandler);
  }

  #releaseErrorObservers() {
    if (this.#errorHandler) {
      removeEventListener("error", this.#errorHandler);
      this.#errorHandler = undefined;
    }
    if (this.#rejectionHandler) {
      removeEventListener("unhandledrejection", this.#rejectionHandler);
      this.#rejectionHandler = undefined;
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("M9 measurement bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal() {
        host.#fatalErrorCount += 1;
        host.#fail("runtime reported a fatal error");
      },
      reportProcessExit(report) {
        if (report?.protocol !== HOST_PROTOCOL ||
            !Number.isSafeInteger(report.exitCode)) {
          host.#fail("invalid process-exit report");
          return false;
        }
        if (host.#processExitCode !== null) {
          host.#fail("duplicate process-exit report");
          return false;
        }
        host.#processExitCode = report.exitCode;
        // ChromeMain reports this independently of Emscripten's onExit.
        // Re-evaluate completion here because it may be the final terminal
        // observation after the runtime, factory, and grace conditions hold.
        host.#completeIfPossible();
        return true;
      },
      reportFrame(report) {
        host.#reportFrame(report);
      },
      reportReadiness(report) {
        host.#reportReadiness(report);
      },
      reportOzoneFocusState(report) {
        host.#reportOzoneFocus(report);
      },
      reportOzoneCursor(report) {
        // This diagnostics-only host supports only the startup default cursor.
        // Other cursor types remain explicitly unsupported rather than being
        // claimed as exact visual platform behavior.
        if (report?.protocol !== HOST_PROTOCOL ||
            (report.cursorType !== -1 && report.cursorType !== 0)) {
          return false;
        }
        host.#canvas.style.cursor = "default";
        return host.#canvas.style.cursor === "default";
      },
      reportOzoneTextInputState() {},
      reportOzoneTextInputDelivery() {},
      reportOzoneBrowserTextInputDelivery() {},
      reportOzoneBrowserClipboardPasteDelivery() {},
      requestOuterOriginStorageEstimate() {
        return false;
      },
      reportAccessibilitySnapshot() {
        return false;
      },
    });
  }

  #reportFrame(report) {
    if (!frameReport(report)) {
      this.#fail("invalid frame report");
      return;
    }
    if (this.#canvas.width !== report.width || this.#canvas.height !== report.height) {
      this.#fail("frame report does not match the host canvas backing store");
      return;
    }
    if (this.#firstFrame !== null) {
      return;
    }
    if (this.#module === null) {
      this.#fail("first frame arrived before runtime initialization");
      return;
    }
    let nativeMemory;
    try {
      nativeMemory = nativeMemorySnapshot(this.#module);
    } catch (error) {
      this.#fail(`native memory snapshot at first frame failed: ` +
          boundedFailure(error));
      return;
    }
    // The canonical ozone_wasm bridge invokes reportFrame only after its
    // synchronous Canvas2D ImageData copy/putImageData work has returned.
    // This is not a claim about raster, compositor, display, or vsync timing.
    this.#setTiming("first_frame_callback_after_canvas_copy");
    try {
      this.#canvasPixelWitness = canvasPixelWitness(this.#canvas);
    } catch (error) {
      this.#fail(`Canvas2D pixel witness after first frame copy failed: ` +
          boundedFailure(error));
      return;
    }
    this.#firstFrame = Object.freeze({
      chromium_timestamp_ms: report.timestampMs,
      height: report.height,
      host_callback_after_canvas_copy_ms:
          this.#timing.first_frame_callback_after_canvas_copy,
      id: report.id,
      width: report.width,
    });
    this.#wasmHeapBufferCapacityAtFirstFrame =
        wasmHeapBufferCapacitySnapshot(this.#module);
    this.#nativeMemoryAtFirstFrame = nativeMemory;
    this.#workersAtFirstFrame = this.#workerObservation.snapshot();
    this.#maybeReady();
  }

  #reportReadiness(report) {
    if (!readinessReport(report)) {
      this.#fail("invalid readiness report");
      return;
    }
    this.#readiness = Object.freeze({
      firstVisuallyNonEmptyPaint: report.firstVisuallyNonEmptyPaint,
      shellReady: report.shellReady,
      surfaceReady: report.surfaceReady,
    });
    if (report.surfaceReady) {
      this.#setTiming("surface_ready_callback");
    }
    this.#maybeReady();
  }

  #reportOzoneFocus(report) {
    if (!focusReport(report)) {
      this.#fail("invalid Ozone focus report");
      return;
    }
    this.#activeOzoneFocus ||= report.keyboardTargetPresent && report.active;
    this.#maybeReady();
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || typeof module.ccall !== "function") {
      this.#fail("runtime initialization did not supply a callable Module");
      return;
    }
    if (this.#module !== null) {
      this.#fail("runtime initialized more than once");
      return;
    }
    let nativeMemory;
    try {
      nativeMemory = nativeMemorySnapshot(module);
    } catch (error) {
      this.#fail(`native memory snapshot at runtime initialization failed: ` +
          boundedFailure(error));
      return;
    }
    this.#module = module;
    this.#setTiming("runtime_initialized");
    this.#wasmHeapBufferCapacityAtRuntimeInitialized =
        wasmHeapBufferCapacitySnapshot(module);
    this.#nativeMemoryAtRuntimeInitialized = nativeMemory;
    this.#workersAtRuntimeInitialized = this.#workerObservation.snapshot();
    this.#maybeReady();
  }

  #maybeReady() {
    if (this.#state !== "loading") {
      return;
    }
    if (this.#fatalErrorCount !== 0 || this.#windowErrorCount !== 0 ||
        this.#unhandledRejectionCount !== 0) {
      this.#fail("host observed an error before measurement readiness");
      return;
    }
    if (this.#module === null || this.#firstFrame === null ||
        !this.#readiness.surfaceReady || !this.#activeOzoneFocus ||
        this.#wasmHeapBufferCapacityAtRuntimeInitialized?.shared !== true ||
        this.#wasmHeapBufferCapacityAtFirstFrame?.shared !== true ||
        this.#nativeMemoryAtRuntimeInitialized === null ||
        this.#nativeMemoryAtFirstFrame === null ||
        this.#workersAtFirstFrame === null ||
        this.#workerObservation.firstMatchedPthreadWorkerStartup() === null ||
        this.#workersAtFirstFrame.workers_constructed < 1 ||
        this.#workersAtFirstFrame.loaded_control_messages < 1 ||
        this.#workersAtFirstFrame.error_events !== 0 ||
        this.#workersAtFirstFrame.message_error_events !== 0) {
      return;
    }
    this.#setTiming("ready");
    this.#setState("ready");
  }

  #completeIfPossible() {
    if (this.#state !== "shutting_down" || this.#runtimeExitCode === null ||
        this.#processExitCode === null || !this.#terminalGraceObserved ||
        !this.#factorySettled) {
      return;
    }
    if (this.#shutdownResults?.[0] !== 1 || this.#shutdownResults?.[1] !== 0) {
      this.#fail("host shutdown ABI did not complete exactly once");
      return;
    }
    const terminalWorkers = this.#workerObservation.snapshot();
    if (this.#runtimeExitCode !== 0 || this.#processExitCode !== 0 ||
        this.#fatalErrorCount !== 0 || this.#windowErrorCount !== 0 ||
        this.#unhandledRejectionCount !== 0 || !this.#factorySettled ||
        terminalWorkers.error_events !== 0 ||
        terminalWorkers.message_error_events !== 0) {
      this.#fail("runtime or host errors prevented a clean measurement shutdown");
      return;
    }
    this.#setState("complete");
  }

  #onRuntimeExit(code) {
    if (!Number.isSafeInteger(code)) {
      this.#fail("runtime exit code is invalid");
      return;
    }
    if (this.#runtimeExitCode !== null) {
      this.#fail("runtime exited more than once");
      return;
    }
    this.#runtimeExitCode = code;
    this.#setTiming("runtime_exit");
    // This endpoint records HEAPU8.buffer capacity, not allocated or resident
    // memory use. It neither waits for nor proves worker drain, utilization,
    // or saturation. The short grace below only lets queued host errors appear.
    this.#wasmHeapBufferCapacityAtRuntimeExit =
        wasmHeapBufferCapacitySnapshot(this.#module);
    this.#workersAtRuntimeExit = this.#workerObservation.snapshot();
    setTimeout(() => {
      this.#terminalGraceObserved = true;
      this.#completeIfPossible();
    }, TERMINAL_GRACE_OBSERVATION_MS);
  }

  #armTimeout(timeoutMs) {
    this.#timerHandle = setTimeout(() => {
      if (this.#state !== "complete" && this.#state !== "failed") {
        this.#fail("measurement host timed out before completion");
      }
    }, timeoutMs);
  }

  async start(moduleName, timeoutMs) {
    try {
      if (!crossOriginIsolated) {
        throw new Error("host is not cross-origin isolated");
      }
      if (typeof SharedArrayBuffer !== "function") {
        throw new Error("SharedArrayBuffer is unavailable");
      }
      if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("measurement timeout is out of range");
      }
      if (moduleName !== PRODUCT_MODULE_NAME) {
        throw new Error(
            "M9 measurement host only supports the chrome_wasm product module");
      }
      this.#timing.host_run_started = this.#now();
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("measurement canvas did not accept focus");
      }
      this.#installBridge();
      this.#installErrorObservers();
      this.#workerObservation.install();
      this.#armTimeout(timeoutMs);
      this.#setState("loading");

      const moduleUrl = new URL(
          `./artifacts/${PRODUCT_MODULE_NAME}.js`, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("measurement module must use the host origin");
      }
      // Match the normal Chrome host's Blob-backed pthread loader path. The
      // server provides immutable captured bytes and no-store responses.
      this.#setTiming("loader_fetch_started");
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      this.#setTiming("loader_response_ready");
      if (!response.ok) {
        throw new Error(`measurement loader returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      this.#setTiming("loader_blob_ready");
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("measurement loader is empty");
      }
      this.#setTiming("module_import_started");
      const namespace = await import(moduleUrl.href);
      this.#setTiming("module_factory_export_ready");
      if (typeof namespace.default !== "function") {
        throw new Error("measurement loader has no default factory export");
      }
      const host = this;
      this.#setTiming("factory_call_started");
      Promise.resolve(namespace.default({
        canvas: this.#canvas,
        locateFile(path) {
          return new URL(path, moduleUrl).href;
        },
        mainScriptUrlOrBlob,
        noExitRuntime: false,
        onAbort(reason) {
          host.#fail(`runtime abort: ${boundedFailure(reason)}`);
        },
        onExit(code) {
          host.#onRuntimeExit(Number(code));
        },
        onRuntimeInitialized() {
          host.#setModule(this);
        },
        print() {},
        printErr() {},
      })).then(
          () => {
            host.#factorySettled = true;
            host.#completeIfPossible();
          },
          (error) => {
            host.#factorySettled = true;
            host.#factoryRejected = true;
            host.#fail(`module factory rejected: ${boundedFailure(error)}`);
          });
    } catch (error) {
      this.#fail(error);
    }
  }

  requestShutdown() {
    if (this.#state !== "ready" || this.#module === null ||
        this.#shutdownResults !== null) {
      return false;
    }
    try {
      // Capture this before the normal native shutdown ABI can invalidate the
      // module's process state. This is an observation, not a drain or leak
      // check, and it cannot request any browser action itself.
      this.#nativeMemoryAtPreShutdown = nativeMemorySnapshot(this.#module);
      this.#setTiming("shutdown_requested");
      const first = this.#module.ccall(
          "chromium_wasm_browser_host_request_shutdown", "number", [], []);
      const second = this.#module.ccall(
          "chromium_wasm_browser_host_request_shutdown", "number", [], []);
      this.#shutdownResults = [first, second];
      if (first !== 1 || second !== 0) {
        this.#fail("host shutdown ABI did not return exactly [1, 0]");
        return false;
      }
      this.#setState("shutting_down");
      this.#completeIfPossible();
      return true;
    } catch (error) {
      this.#fail(`host shutdown ABI failed: ${boundedFailure(error)}`);
      return false;
    }
  }

  snapshot() {
    const runtimeCapacity = this.#wasmHeapBufferCapacityAtRuntimeInitialized;
    const frameCapacity = this.#wasmHeapBufferCapacityAtFirstFrame;
    const exitCapacity = this.#wasmHeapBufferCapacityAtRuntimeExit;
    const capacityGrewBeforeFrame = runtimeCapacity !== null &&
        frameCapacity !== null &&
        runtimeCapacity.wasm_heap_buffer_capacity_bytes !== null &&
        frameCapacity.wasm_heap_buffer_capacity_bytes !== null ?
        frameCapacity.wasm_heap_buffer_capacity_bytes >
            runtimeCapacity.wasm_heap_buffer_capacity_bytes : null;
    const capacityGrewByExit = runtimeCapacity !== null && exitCapacity !== null &&
        runtimeCapacity.wasm_heap_buffer_capacity_bytes !== null &&
        exitCapacity.wasm_heap_buffer_capacity_bytes !== null ?
        exitCapacity.wasm_heap_buffer_capacity_bytes >
            runtimeCapacity.wasm_heap_buffer_capacity_bytes : null;
    return {
      case: CASE,
      canvas_pixel_witness: this.#canvasPixelWitness,
      cold_start_definition: COLD_START_DEFINITION,
      durations_ms: {
        factory_call_to_runtime_initialized: timingDelta(
            this.#timing, "factory_call_started", "runtime_initialized"),
        first_frame_callback_after_canvas_copy_to_surface_ready_callback:
            timingDelta(this.#timing, "first_frame_callback_after_canvas_copy",
                "surface_ready_callback"),
        host_module_evaluated_to_loader_fetch_started: timingDelta(
            this.#timing, "host_module_evaluated", "loader_fetch_started"),
        loader_blob_to_module_import_started: timingDelta(
            this.#timing, "loader_blob_ready", "module_import_started"),
        loader_fetch_to_loader_response: timingDelta(
            this.#timing, "loader_fetch_started", "loader_response_ready"),
        loader_response_to_loader_blob: timingDelta(
            this.#timing, "loader_response_ready", "loader_blob_ready"),
        module_import_to_factory_export: timingDelta(
            this.#timing, "module_import_started", "module_factory_export_ready"),
        navigation_to_first_frame_callback_after_canvas_copy: timingDelta(
            {navigation_start: 0, ...this.#timing}, "navigation_start",
            "first_frame_callback_after_canvas_copy"),
        ready_to_shutdown_request: timingDelta(
            this.#timing, "ready", "shutdown_requested"),
        runtime_initialized_to_first_frame_callback_after_canvas_copy:
            timingDelta(this.#timing, "runtime_initialized",
                "first_frame_callback_after_canvas_copy"),
        shutdown_request_to_runtime_exit: timingDelta(
            this.#timing, "shutdown_requested", "runtime_exit"),
      },
      first_frame: this.#firstFrame,
      host: {
        canvas_focused: document.activeElement === this.#canvas,
        cross_origin_isolated: crossOriginIsolated === true,
        shared_array_buffer_available: typeof SharedArrayBuffer === "function",
      },
      lifecycle: {
        active_ozone_focus_observed: this.#activeOzoneFocus,
        factory_rejected: this.#factoryRejected,
        factory_settled: this.#factorySettled,
        fatal_error_count: this.#fatalErrorCount,
        process_exit_code: this.#processExitCode,
        readiness: this.#readiness,
        runtime_exit_code: this.#runtimeExitCode,
        runtime_initialized: this.#module !== null,
        shutdown_results: this.#shutdownResults,
        status_sequence: this.#stateSequence.slice(),
        unhandled_rejection_count: this.#unhandledRejectionCount,
        window_error_count: this.#windowErrorCount,
      },
      m9_gate_complete: false,
      native_memory_snapshot: {
        at_first_frame: this.#nativeMemoryAtFirstFrame,
        at_pre_shutdown: this.#nativeMemoryAtPreShutdown,
        at_runtime_initialized: this.#nativeMemoryAtRuntimeInitialized,
        definition: NATIVE_MEMORY_SNAPSHOT_DEFINITION,
      },
      wasm_heap_buffer_capacity: {
        at_first_frame: frameCapacity,
        at_runtime_initialized: runtimeCapacity,
        at_runtime_exit: exitCapacity,
        definition: WASM_HEAP_BUFFER_CAPACITY_DEFINITION,
        grew_before_first_frame_callback: capacityGrewBeforeFrame,
        grew_by_runtime_exit: capacityGrewByExit,
      },
      measurement_limits: MEASUREMENT_LIMITS.slice(),
      performance_gate: false,
      release_status: RELEASE_STATUS,
      schema_version: SCHEMA_VERSION,
      scope: SCOPE,
      status: this.#state,
      timing_ms: this.#timing,
      worker_observation: {
        at_first_frame: this.#workersAtFirstFrame,
        at_runtime_initialized: this.#workersAtRuntimeInitialized,
        at_runtime_exit: this.#workersAtRuntimeExit,
        definition: WORKER_OBSERVATION_DEFINITION,
        first_matched_pthread_worker_startup:
            this.#workerObservation.firstMatchedPthreadWorkerStartup(),
      },
      failure: this.#failure,
    };
  }

  dispose() {
    if (this.#timerHandle !== null) {
      clearTimeout(this.#timerHandle);
      this.#timerHandle = null;
    }
    this.#workerObservation.dispose();
    this.#releaseErrorObservers();
  }

  recordStartupFailure(error) {
    this.#fail(error);
  }
}

function parseQuery() {
  const parameters = new URLSearchParams(location.search);
  const moduleName = parameters.get("module");
  const timeoutText = parameters.get("timeout_ms");
  if (parameters.size !== 2) {
    throw new Error("M9 measurement query is invalid");
  }
  if (moduleName !== PRODUCT_MODULE_NAME) {
    throw new Error(
        "M9 measurement query must select the chrome_wasm product module");
  }
  if (!/^\d+$/.test(timeoutText || "")) {
    throw new Error("M9 measurement timeout is invalid");
  }
  const timeoutMs = Number(timeoutText);
  if (!Number.isSafeInteger(timeoutMs)) {
    throw new Error("M9 measurement timeout is unsafe");
  }
  return {moduleName, timeoutMs};
}

export async function runChromeWasmM9MeasurementFromQuery() {
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#measurement-status");
  const host = new ChromiumWasmM9MeasurementHost(canvas, status);
  globalThis.__chromiumWasmM9MeasurementV1 = Object.freeze({
    requestShutdown() {
      return host.requestShutdown();
    },
    snapshot() {
      return host.snapshot();
    },
  });
  try {
    const {moduleName, timeoutMs} = parseQuery();
    await host.start(moduleName, timeoutMs);
  } catch (error) {
    // Keep malformed query and pre-start failures visible to CDP through the
    // same state object; otherwise a runner would only see an opaque timeout.
    host.recordStartupFailure(error);
  }
}

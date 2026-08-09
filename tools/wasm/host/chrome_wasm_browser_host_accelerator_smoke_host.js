// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This lane proves trusted outer-DOM key delivery to the bounded Chrome Wasm
// accelerator ABI. It is not a general keyboard implementation: browser
// reserved shortcuts can be intercepted before they reach page DOM.
const HOST_PROTOCOL = 1;
const CASE = "browser_host_accelerators_m6";
const SCOPE = "trusted-dom-physical-key-ozone-aura-views";
const SWITCH = "--wasm-browser-host-accelerator-smoke";
const READY_MARKER = "CHROMIUM_WASM_M6_HOST_ACCELERATORS:READY";
const PASS_MARKER = "CHROMIUM_WASM_M6_HOST_ACCELERATORS:PASS";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 64;
const RESERVED_SHORTCUT_LIMITATION =
    "reserved outer-browser shortcuts may be intercepted before page DOM";
const HOST_ACCELERATOR_CODES = new Set([
  "ControlLeft",
  "ShiftLeft",
  "AltLeft",
  "KeyL",
  "KeyR",
  "ArrowLeft",
  "ArrowRight",
  "Tab",
]);
const HOST_ACCELERATOR_MODIFIER_CODES = new Set([
  "ControlLeft",
  "ShiftLeft",
  "AltLeft",
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

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error(`invalid host-accelerator versions: ${String(error)}`);
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

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) {
    records.shift();
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

class ChromiumWasmBrowserHostAcceleratorSmokeHost {
  #canvas;
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
  #readinessReports = [];
  #readiness = null;
  #focusReports = [];
  #cursorReports = [];
  #errorHandler;
  #rejectionHandler;
  #onKeyDown;
  #onKeyUp;
  #onCanvasBlur;
  #onWindowBlur;
  #onVisibilityChange;
  #input = {
    attached: false,
    readyObserved: false,
    passObserved: false,
    verificationQueued: false,
    receivedRecords: [],
    acceptedRecords: [],
    rejectedRecords: [],
    heldCodes: [],
    cleanupRecords: [],
  };

  constructor(canvas, versions) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("host-accelerator smoke requires a canvas");
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
      this.#recordFatal(`window error: ${String(event.error || event.message)}`);
      appendBounded(this.#windowErrors, String(event.error || event.message));
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
      // The Wasm bridge copies into the canvas before this report. Dimensions
      // here therefore reject a metadata-only presentation claim.
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
        throw new Error("focus metadata is invalid");
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
      appendBounded(this.#cursorReports, {
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
      throw new Error("host accelerator bridge is already installed");
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
        host.#reportFocus(report);
      },
      reportOzoneCursor(report) {
        return host.#reportOzoneCursor(report);
      },
      reportOzoneTextInputDelivery() {},
      reportOzoneTextInputState() {},
    });
  }

  #publishState(state) {
    window.__chromiumWasmM6HostAcceleratorsState = Object.freeze({
      state,
      attached: this.#input.attached,
      readyObserved: this.#input.readyObserved,
      passObserved: this.#input.passObserved,
      heldCodes: [...this.#input.heldCodes],
    });
  }

  #updateReadinessState() {
    if (this.#module && this.#input.attached && this.#input.readyObserved &&
        !this.#input.passObserved) {
      this.#publishState("awaiting-trusted-dom-ctrl-l");
    }
  }

  #recordOutput(text) {
    if (text.includes(READY_MARKER)) {
      this.#input.readyObserved = true;
      this.#updateReadinessState();
    }
    if (text.includes(PASS_MARKER)) {
      this.#input.passObserved = true;
      this.#publishState("pass-observed");
    }
  }

  #callHostKey(code, down) {
    if (!this.#module) {
      return 0;
    }
    try {
      return this.#module.ccall(
          "chromium_wasm_browser_host_key", "number", ["string", "number"],
          [code, down ? 1 : 0]);
    } catch (error) {
      this.#recordFatal(`host key ABI call failed: ${String(error)}`);
      return 0;
    }
  }

  #isCodeHeld(code) {
    return this.#input.heldCodes.includes(code);
  }

  #hasExactAcceptedModifierState(event) {
    return event.ctrlKey === this.#isCodeHeld("ControlLeft") &&
        event.shiftKey === this.#isCodeHeld("ShiftLeft") &&
        event.altKey === this.#isCodeHeld("AltLeft") && !event.metaKey &&
        !event.getModifierState("AltGraph");
  }

  #rejectionReason(event, down) {
    if (!this.#input.readyObserved || this.#input.passObserved || !this.#module) {
      return "C++ accelerator verifier is not ready";
    }
    if (event.isTrusted !== true) {
      return "DOM keyboard event is not trusted";
    }
    if (event.cancelable !== true) {
      return "DOM keyboard event is not cancelable";
    }
    if (document.activeElement !== this.#canvas) {
      return "DOM keyboard event is not targeted at the focused canvas";
    }
    if (event.isComposing || event.key === "Dead" || event.key === "Process") {
      return "DOM keyboard composition input is unsupported";
    }
    if (event.repeat) {
      return "DOM keyboard repeats are unsupported";
    }
    if (!HOST_ACCELERATOR_CODES.has(event.code)) {
      return "DOM keyboard code is outside the bounded accelerator allowlist";
    }
    if (event.metaKey || event.getModifierState("AltGraph")) {
      return "DOM keyboard modifier state is unsupported";
    }

    const held = this.#isCodeHeld(event.code);
    if (down === held) {
      return down ? "DOM keyboard key is already held" :
                    "DOM keyboard key was not held";
    }

    // Action keydown must exactly match the locally accepted left-modifier
    // state. This rejects right/unrepresented modifiers rather than treating
    // browser-provided `ctrlKey`/`shiftKey`/`altKey` as authority to inject.
    // Keyup deliberately stays releasable after a modifier keyup, matching
    // the bounded C++ ABI's anti-stuck-key cleanup policy.
    if (down && !HOST_ACCELERATOR_MODIFIER_CODES.has(event.code) &&
        !this.#hasExactAcceptedModifierState(event)) {
      return "DOM keyboard modifier state does not match accepted left modifiers";
    }

    if (!down || HOST_ACCELERATOR_MODIFIER_CODES.has(event.code)) {
      return null;
    }
    switch (event.code) {
      case "KeyL":
        return this.#isCodeHeld("ControlLeft") && !this.#isCodeHeld("ShiftLeft") &&
                !this.#isCodeHeld("AltLeft") ? null :
                                             "Ctrl+L chord is not satisfied";
      case "KeyR":
      case "Tab":
        return this.#isCodeHeld("ControlLeft") && !this.#isCodeHeld("AltLeft") ?
            null : "Ctrl+R/Tab chord is not satisfied";
      case "ArrowLeft":
      case "ArrowRight":
        return this.#isCodeHeld("AltLeft") && !this.#isCodeHeld("ControlLeft") &&
                !this.#isCodeHeld("ShiftLeft") ? null :
                                             "Alt+Arrow chord is not satisfied";
      default:
        return "DOM keyboard code is outside the bounded accelerator allowlist";
    }
  }

  #handleKeyEvent(event, down) {
    const rejectionReason = this.#rejectionReason(event, down);
    const accepted = rejectionReason === null &&
        this.#callHostKey(event.code, down) === 1;
    if (accepted) {
      event.preventDefault();
      if (down) {
        if (!this.#input.heldCodes.includes(event.code)) {
          this.#input.heldCodes.push(event.code);
        }
      } else {
        this.#input.heldCodes = this.#input.heldCodes.filter(
            (code) => code !== event.code);
      }
    }
    const record = {
      type: down ? "keydown" : "keyup",
      code: event.code,
      trusted: event.isTrusted,
      accepted,
      defaultPrevented: event.defaultPrevented,
      canvasFocused: document.activeElement === this.#canvas,
    };
    if (!accepted) {
      record.rejectionReason = rejectionReason || "Chrome rejected key transition";
    }
    appendBounded(this.#input.receivedRecords, record);
    appendBounded(
        accepted ? this.#input.acceptedRecords : this.#input.rejectedRecords,
        record);
    this.#maybeRequestVerification();
    this.#updateReadinessState();
  }

  #maybeRequestVerification() {
    const expected = [
      ["keydown", "ControlLeft"],
      ["keydown", "KeyL"],
      ["keyup", "KeyL"],
      ["keyup", "ControlLeft"],
    ];
    if (this.#input.verificationQueued ||
        this.#input.acceptedRecords.length !== expected.length) {
      return;
    }
    for (let index = 0; index < expected.length; ++index) {
      const record = this.#input.acceptedRecords[index];
      if (record.type !== expected[index][0] || record.code !== expected[index][1]) {
        return;
      }
    }
    try {
      const queued = this.#module.ccall(
          "chromium_wasm_browser_host_accelerator_check", "number", [], []);
      if (queued !== 1) {
        throw new Error("accelerator verification was not accepted");
      }
      this.#input.verificationQueued = true;
    } catch (error) {
      this.#recordFatal(`host accelerator verification failed: ${String(error)}`);
    }
  }

  #releaseHeldKeys(reason) {
    // Reverse release preserves action-before-modifier ordering if focus is
    // lost mid-chord. These synthetic cleanup calls intentionally cannot
    // prevent a default because they have no DOM Event.
    for (const code of [...this.#input.heldCodes].reverse()) {
      const accepted = this.#callHostKey(code, false) === 1;
      appendBounded(this.#input.cleanupRecords, {reason, code, accepted});
    }
    this.#input.heldCodes = [];
    this.#updateReadinessState();
  }

  #attachInput() {
    if (this.#input.attached) {
      return;
    }
    this.#onKeyDown = (event) => this.#handleKeyEvent(event, true);
    this.#onKeyUp = (event) => this.#handleKeyEvent(event, false);
    this.#onCanvasBlur = () => this.#releaseHeldKeys("canvas-blur");
    this.#onWindowBlur = () => this.#releaseHeldKeys("window-blur");
    this.#onVisibilityChange = () => {
      if (document.hidden) {
        this.#releaseHeldKeys("document-hidden");
      }
    };
    this.#canvas.addEventListener("keydown", this.#onKeyDown);
    this.#canvas.addEventListener("keyup", this.#onKeyUp);
    this.#canvas.addEventListener("blur", this.#onCanvasBlur);
    window.addEventListener("blur", this.#onWindowBlur);
    document.addEventListener("visibilitychange", this.#onVisibilityChange);
    this.#input.attached = true;
    this.#updateReadinessState();
  }

  #detachInput() {
    if (!this.#input.attached) {
      return;
    }
    this.#releaseHeldKeys("teardown");
    this.#canvas.removeEventListener("keydown", this.#onKeyDown);
    this.#canvas.removeEventListener("keyup", this.#onKeyUp);
    this.#canvas.removeEventListener("blur", this.#onCanvasBlur);
    window.removeEventListener("blur", this.#onWindowBlur);
    document.removeEventListener("visibilitychange", this.#onVisibilityChange);
    this.#input.attached = false;
  }

  #setModule(module) {
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#attachInput();
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
        attached: this.#input.attached,
        readyObserved: this.#input.readyObserved,
        passObserved: this.#input.passObserved,
        verificationQueued: this.#input.verificationQueued,
        reservedShortcutLimitation: RESERVED_SHORTCUT_LIMITATION,
        receivedRecords: this.#input.receivedRecords,
        acceptedRecords: this.#input.acceptedRecords,
        rejectedRecords: this.#input.rejectedRecords,
        heldCodes: this.#input.heldCodes,
        cleanupRecords: this.#input.cleanupRecords,
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
        throw new Error("host accelerator smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("host accelerator timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("host accelerator module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas) {
        throw new Error("host accelerator canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(`module request returned HTTP ${response.status}`);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("host accelerator module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("host accelerator loader has no default factory export");
      }
      const host = this;
      const moduleOptions = {
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
        onRuntimeInitialized() {
          host.#setModule(this);
        },
        onAbort(reason) {
          host.#abort = String(reason);
          host.#recordFatal(`abort: ${host.#abort}`);
        },
        onExit(code) {
          host.#reportRuntimeExit(Number(code));
        },
      };
      // The factory resolves after this live C++ smoke exits. Keep the module
      // captured from onRuntimeInitialized so DOM listeners can forward keys.
      namespace.default(moduleOptions).catch((error) => {
        host.#recordFatal(`module factory rejected: ${String(error)}`);
      });

      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("host accelerator smoke did not exit before timeout");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#detachInput();
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
  require(result.hostInput.readyObserved === true, "ready marker is absent");
  require(result.hostInput.passObserved === true, "pass marker is absent");
  require(result.hostInput.heldCodes.length === 0, "a DOM key remains held");
  require(result.frameReports.length >= 1, "no canvas frame was reported");
  require(result.readiness?.surfaceReady === true,
      "surface readiness was not reported");
  require(result.ozoneFocusReports.some((report) =>
    report.keyboardTargetPresent === true && report.active === true),
  "no active Ozone keyboard target was observed");
  result.failedChecks = failures;
  if (failures.length) {
    result.status = "fail";
    result.error = failures.join("; ");
  }
  return result;
}

export async function runChromeWasmBrowserHostAcceleratorSmokeFromQuery() {
  const query = new URLSearchParams(location.search);
  const token = asNonemptyString(query.get("token"), "result token");
  const moduleName = asNonemptyString(query.get("module"), "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(query.get("timeoutMs") || "30000");
  const versions = parseVersions(query.get("versions"));
  const root = document.querySelector("#browser-host-accelerator-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-host-accelerator-status");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement)) {
    throw new Error("host accelerator page is missing required elements");
  }
  renderVersions(document.querySelector("#versions"), versions);
  const host = new ChromiumWasmBrowserHostAcceleratorSmokeHost(canvas, versions);
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

export const chromeWasmBrowserHostAcceleratorSmokeContract = Object.freeze({
  CASE,
  HOST_PROTOCOL,
  PASS_MARKER,
  READY_MARKER,
  RESERVED_SHORTCUT_LIMITATION,
  SCOPE,
  SWITCH,
});

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Shared trusted-DOM committed-text adapter for the ordinary Chrome host and
// the focused M6 proof. It owns only a hidden, focusable DOM textarea and the
// bounded Chrome C ABI; it cannot choose a widget, mutate a Views Textfield,
// or navigate. Ozone remains the authority for the focused TextInputClient.

const ACTION_INSERT_TEXT = 4;
const SESSION_ID = 0;
const MAX_RECORD_HISTORY = 64;
const MAX_UTF8_BYTES = 192 * 1024;
const MAX_UTF16_UNITS = 64 * 1024;
// The Chrome-owned bridge immediately captures an Ozone focus token for each
// admission, then serializes its bounded native FIFO on the UI sequence.
// Mirror that reservation budget here so ordinary physical typing is never
// silently converted into an unbounded DOM proxy queue.
const MAX_NATIVE_PENDING_DELIVERIES = 16;
const MAX_NATIVE_PENDING_UTF8_BYTES = 192 * 1024;

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) {
    records.shift();
  }
}

function isValidTextInputState(report) {
  return report && typeof report === "object" &&
      typeof report.focusedClientPresent === "boolean" &&
      typeof report.editable === "boolean" &&
      typeof report.canComposeInline === "boolean" &&
      (!report.editable || report.focusedClientPresent) &&
      (!report.canComposeInline || report.editable);
}

function isValidBrowserTextDelivery(report) {
  return report && typeof report === "object" && report.action === ACTION_INSERT_TEXT &&
      report.sessionId === SESSION_ID && Number.isSafeInteger(report.sequence) &&
      report.sequence >= 1 && typeof report.accepted === "boolean";
}

function isWellFormedUtf16(text) {
  if (typeof text.isWellFormed === "function") {
    return text.isWellFormed();
  }
  for (let index = 0; index < text.length; ++index) {
    const codeUnit = text.charCodeAt(index);
    if (codeUnit >= 0xD800 && codeUnit <= 0xDBFF) {
      const next = text.charCodeAt(index + 1);
      if (next < 0xDC00 || next > 0xDFFF) {
        return false;
      }
      ++index;
    } else if (codeUnit >= 0xDC00 && codeUnit <= 0xDFFF) {
      return false;
    }
  }
  return true;
}

// The adapter deliberately has no generic keyboard surface. Its sole canvas
// shortcut is Ctrl+L, which selects Chrome's existing address field through
// the bounded physical-key bridge; its sole proxy shortcut is unmodified
// Enter, which follows the same physical-key path.
export class ChromiumWasmTrustedTextInput {
  #canvas;
  #proxy;
  #getModule;
  #reportFatal;
  #autoFocusProxy;
  #canAcceptBeforeInput;
  #validateBeforeInput;
  #canSubmitEnter;
  #onCtrlLComplete;
  #onProxyFocused;
  #onBeforeInputQueued;
  #onNativeDelivery;
  #onNativeDeliveryRejected;
  #onEnterComplete;
  #onStateChange;
  #encoder = new TextEncoder();
  #attached = false;
  #editable = false;
  #shortcutIndex = 0;
  #shortcutComplete = false;
  #canvasHeldCodes = [];
  #enterHeld = false;
  #nextSequence = 1;
  #pendingDeliveries = new Map();
  #pendingTextUtf8Bytes = 0;
  #tombstonedDeliverySequences = new Set();
  #deliveryAccepted = false;
  #deliveryRejected = false;
  #focusGeneration = 0;
  #acceptedDeliveryFocusGeneration = null;
  #proxySessionCleared = false;
  #ctrlLRecords = [];
  #beforeInputRecords = [];
  #browserTextDeliveryReports = [];
  #enterRecords = [];
  #rejectedRecords = [];
  #cleanupRecords = [];
  #onCanvasFocus;
  #onCanvasBlur;
  #onCanvasKeyDown;
  #onCanvasKeyUp;
  #onProxyBeforeInput;
  #onProxyInput;
  #onProxyKeyDown;
  #onProxyKeyUp;
  #onProxyBlur;
  #onWindowBlur;
  #onVisibilityChange;

  constructor(canvas, proxy, options) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("trusted text adapter requires a canvas");
    }
    if (!(proxy instanceof HTMLTextAreaElement)) {
      throw new Error("trusted text adapter requires a textarea proxy");
    }
    if (!options || typeof options.getModule !== "function" ||
        typeof options.reportFatal !== "function") {
      throw new Error("trusted text adapter options are invalid");
    }
    this.#canvas = canvas;
    this.#proxy = proxy;
    this.#getModule = options.getModule;
    this.#reportFatal = options.reportFatal;
    this.#autoFocusProxy = options.autoFocusProxy !== false;
    this.#canAcceptBeforeInput = options.canAcceptBeforeInput || (() => true);
    this.#validateBeforeInput = options.validateBeforeInput || (() => null);
    this.#canSubmitEnter = options.canSubmitEnter || (() =>
      this.#deliveryAccepted && !this.#deliveryRejected &&
      this.#pendingDeliveries.size === 0 &&
      this.#acceptedDeliveryFocusGeneration === this.#focusGeneration &&
      this.#editable);
    this.#onCtrlLComplete = options.onCtrlLComplete || (() => {});
    this.#onProxyFocused = options.onProxyFocused || (() => {});
    this.#onBeforeInputQueued = options.onBeforeInputQueued || (() => {});
    this.#onNativeDelivery = options.onNativeDelivery || (() => {});
    this.#onNativeDeliveryRejected = options.onNativeDeliveryRejected || (() => {});
    this.#onEnterComplete = options.onEnterComplete || (() => {});
    this.#onStateChange = options.onStateChange || (() => {});
  }

  attach() {
    if (this.#attached) {
      return;
    }
    this.#onCanvasFocus = () => this.#resetShortcutForCanvasFocus();
    this.#onCanvasBlur = () => this.#releaseCanvasKeys("canvas-blur");
    this.#onCanvasKeyDown = (event) => this.#handleCanvasKey(event, true);
    this.#onCanvasKeyUp = (event) => this.#handleCanvasKey(event, false);
    this.#onProxyBeforeInput = (event) => this.#handleBeforeInput(event);
    this.#onProxyInput = (event) => this.#handleProxyInput(event);
    this.#onProxyKeyDown = (event) => this.#handleProxyEnter(event, true);
    this.#onProxyKeyUp = (event) => this.#handleProxyEnter(event, false);
    this.#onProxyBlur = () => this.#releaseHeldEnter("textarea-blur");
    this.#onWindowBlur = () => {
      this.#releaseCanvasKeys("window-blur");
      this.#releaseHeldEnter("window-blur");
    };
    this.#onVisibilityChange = () => {
      if (document.hidden) {
        this.#releaseCanvasKeys("document-hidden");
        this.#releaseHeldEnter("document-hidden");
      }
    };
    this.#canvas.addEventListener("focus", this.#onCanvasFocus);
    this.#canvas.addEventListener("blur", this.#onCanvasBlur);
    this.#canvas.addEventListener("keydown", this.#onCanvasKeyDown);
    this.#canvas.addEventListener("keyup", this.#onCanvasKeyUp);
    this.#proxy.addEventListener("beforeinput", this.#onProxyBeforeInput);
    this.#proxy.addEventListener("input", this.#onProxyInput);
    this.#proxy.addEventListener("keydown", this.#onProxyKeyDown);
    this.#proxy.addEventListener("keyup", this.#onProxyKeyUp);
    this.#proxy.addEventListener("blur", this.#onProxyBlur);
    window.addEventListener("blur", this.#onWindowBlur);
    document.addEventListener("visibilitychange", this.#onVisibilityChange);
    this.#attached = true;
    this.#publishState();
  }

  detach() {
    if (!this.#attached) {
      return;
    }
    this.#releaseCanvasKeys("teardown");
    this.#releaseHeldEnter("teardown");
    this.#canvas.removeEventListener("focus", this.#onCanvasFocus);
    this.#canvas.removeEventListener("blur", this.#onCanvasBlur);
    this.#canvas.removeEventListener("keydown", this.#onCanvasKeyDown);
    this.#canvas.removeEventListener("keyup", this.#onCanvasKeyUp);
    this.#proxy.removeEventListener("beforeinput", this.#onProxyBeforeInput);
    this.#proxy.removeEventListener("input", this.#onProxyInput);
    this.#proxy.removeEventListener("keydown", this.#onProxyKeyDown);
    this.#proxy.removeEventListener("keyup", this.#onProxyKeyUp);
    this.#proxy.removeEventListener("blur", this.#onProxyBlur);
    window.removeEventListener("blur", this.#onWindowBlur);
    document.removeEventListener("visibilitychange", this.#onVisibilityChange);
    this.#tombstonePendingDeliveries();
    this.#attached = false;
    this.#publishState();
  }

  // Call this only after a host-specific readiness condition (the dedicated
  // smoke waits for its C++ focus observation plus a fresh paint). The normal
  // host uses auto focus after its Ozone editable-state acknowledgement.
  activateProxy() {
    if (!this.#attached || !this.#shortcutComplete || !this.#editable ||
        this.#deliveryRejected) {
      return false;
    }
    this.#proxy.focus({preventScroll: true});
    const focused = document.activeElement === this.#proxy;
    if (!focused) {
      this.#reportFatal("trusted text textarea did not accept focus");
      return false;
    }
    this.#onProxyFocused();
    this.#publishState();
    return true;
  }

  handleOzoneTextInputState(report) {
    if (!isValidTextInputState(report)) {
      this.#reportFatal("trusted text adapter received invalid Ozone state");
      return;
    }
    this.#editable = report.editable;
    ++this.#focusGeneration;
    this.#maybeAutoFocusProxy();
    this.#publishState();
  }

  handleOzoneBrowserTextInputDelivery(report) {
    if (!isValidBrowserTextDelivery(report)) {
      this.#reportFatal("trusted text adapter received invalid browser delivery");
      return;
    }
    appendBounded(this.#browserTextDeliveryReports, {
      action: report.action,
      sessionId: report.sessionId,
      sequence: report.sequence,
      accepted: report.accepted,
    });
    const pending = this.#pendingDeliveries.get(report.sequence);
    if (!pending) {
      if (this.#tombstonedDeliverySequences.delete(report.sequence)) {
        // Detach cleared the transient text buffer. Consume the matching late
        // acknowledgement inertly, without invoking any host callback or
        // treating it as a protocol error.
        return;
      }
      this.#reportFatal("browser text delivery has no pending request");
      return;
    }
    this.#pendingDeliveries.delete(report.sequence);
    this.#releasePendingTextBytes(pending.bytes.byteLength);
    if (!report.accepted || pending.focusGeneration !== this.#focusGeneration) {
      this.#rejectNativeTextTransaction(pending, report,
          report.accepted ?
              "browser text crossed an Ozone focus transition before acknowledgement" :
              "Ozone rejected queued browser text");
      return;
    }
    this.#deliveryAccepted = true;
    this.#acceptedDeliveryFocusGeneration = this.#focusGeneration;
    // Raw text is intentionally transient: the callback can validate it, but
    // result histories retain only bounded metadata even after acceptance.
    pending.record.nativeAccepted = true;
    // This callback runs on the host side of a synchronous UI->JS report.
    // Consumers must schedule, never synchronously re-enter a Wasm export.
    this.#onNativeDelivery({...report, text: pending.text});
    this.#publishState();
  }

  releaseActiveInput(reason) {
    this.#releaseCanvasKeys(reason);
    this.#releaseHeldEnter(reason);
  }

  snapshot() {
    return {
      attached: this.#attached,
      editable: this.#editable,
      shortcutComplete: this.#shortcutComplete,
      proxyFocused: document.activeElement === this.#proxy,
      textQueued: this.#nextSequence > 1,
      deliveryAccepted: this.#deliveryAccepted,
      deliveryRejected: this.#deliveryRejected,
      focusGeneration: this.#focusGeneration,
      acceptedDeliveryFocusGeneration: this.#acceptedDeliveryFocusGeneration,
      proxySessionCleared: this.#proxySessionCleared,
      pendingDeliveryCount: this.#pendingDeliveries.size,
      pendingTextUtf8Bytes: this.#pendingTextUtf8Bytes,
      tombstonedDeliveryCount: this.#tombstonedDeliverySequences.size,
      textareaValue: this.#proxy.value,
      ctrlLRecords: [...this.#ctrlLRecords],
      beforeInputRecords: [...this.#beforeInputRecords],
      browserTextDeliveryReports: [...this.#browserTextDeliveryReports],
      enterRecords: [...this.#enterRecords],
      rejectedRecords: [...this.#rejectedRecords],
      cleanupRecords: [...this.#cleanupRecords],
    };
  }

  #publishState() {
    this.#onStateChange(this.snapshot());
  }

  #module() {
    const module = this.#getModule();
    return module && typeof module.ccall === "function" ? module : null;
  }

  #callHostKey(code, down) {
    const module = this.#module();
    if (!module) {
      return 0;
    }
    try {
      return module.ccall(
          "chromium_wasm_browser_host_key", "number", ["string", "number"],
          [code, down ? 1 : 0]);
    } catch (error) {
      this.#reportFatal(`trusted text key ABI call failed: ${String(error)}`);
      return 0;
    }
  }

  #callHostTextBytes(bytes) {
    const module = this.#module();
    if (!module || typeof module._malloc !== "function" ||
        typeof module._free !== "function" || !(module.HEAPU8 instanceof Uint8Array)) {
      this.#reportFatal("trusted text module lacks explicit UTF-8 allocation ABI");
      return 0;
    }
    if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0 ||
        bytes.byteLength > MAX_UTF8_BYTES) {
      return 0;
    }
    let pointer = 0;
    try {
      pointer = module._malloc(bytes.byteLength);
      if (!Number.isSafeInteger(pointer) || pointer <= 0 ||
          pointer + bytes.byteLength > module.HEAPU8.byteLength) {
        throw new Error("Wasm UTF-8 allocation is outside the current heap");
      }
      // C++ copies this explicit byte range before it posts to the UI task.
      // It therefore never retains a view that memory growth can invalidate.
      module.HEAPU8.set(bytes, pointer);
      return module.ccall(
          "chromium_wasm_browser_host_text", "number", ["number", "number"],
          [pointer, bytes.byteLength]);
    } catch (error) {
      this.#reportFatal(`trusted text ABI call failed: ${String(error)}`);
      return 0;
    } finally {
      if (pointer > 0) {
        module._free(pointer);
      }
    }
  }

  #makeBeforeInputRecord(event) {
    const dataLength = typeof event.data === "string" ?
      Math.min(event.data.length, MAX_UTF16_UNITS + 1) : null;
    return {
      inputType: event.inputType,
      // Do not retain raw rejected text. A bounded successful native delivery
      // records only metadata; the actual text remains callback-transient.
      dataOmitted: true,
      dataUtf16Units: dataLength,
      trusted: event.isTrusted,
      cancelable: event.cancelable,
      isComposing: event.isComposing,
      proxyFocused: document.activeElement === this.#proxy,
      queued: false,
      defaultPrevented: false,
    };
  }

  #clearProxyText() {
    this.#proxy.value = "";
    this.#proxy.setSelectionRange(0, 0);
  }

  #rejectBeforeInput(event, record, reason) {
    // This is a no-text proxy. Rejecting a cancelable event must still
    // suppress its DOM editing default, including quota/native failures.
    if (event.cancelable) {
      event.preventDefault();
    }
    record.defaultPrevented = event.defaultPrevented;
    if (this.#proxy.value !== "" || this.#proxy.selectionStart !== 0 ||
        this.#proxy.selectionEnd !== 0) {
      this.#clearProxyText();
      this.#reportFatal("textarea proxy retained DOM text after rejected beforeinput");
    }
    this.#reject(this.#beforeInputRecords, record, reason);
  }

  #releasePendingTextBytes(bytes) {
    if (!Number.isSafeInteger(bytes) || bytes < 0 ||
        bytes > this.#pendingTextUtf8Bytes) {
      this.#pendingTextUtf8Bytes = 0;
      this.#reportFatal("trusted text pending-byte accounting is invalid");
      return;
    }
    this.#pendingTextUtf8Bytes -= bytes;
  }

  #tombstonePendingDeliveries() {
    for (const sequence of this.#pendingDeliveries.keys()) {
      this.#tombstonedDeliverySequences.add(sequence);
    }
    this.#pendingDeliveries.clear();
    this.#pendingTextUtf8Bytes = 0;
  }

  #rejectNativeTextTransaction(request, report, reason) {
    request.record.queued = false;
    request.record.nativeAccepted = false;
    request.record.rejectionReason = reason;
    appendBounded(this.#rejectedRecords, {
      ...request.record,
      accepted: false,
      action: report.action,
      sessionId: report.sessionId,
      sequence: report.sequence,
    });
    this.#deliveryRejected = true;
    this.#proxySessionCleared = true;
    this.#proxy.blur();
    this.#onNativeDeliveryRejected({...report});
    this.#publishState();
  }

  #rejectNativeTextAdmission(request, sequence) {
    request.record.queued = false;
    request.record.nativeAccepted = false;
    request.record.rejectionReason = "Chrome did not admit copied beforeinput text";
    appendBounded(this.#rejectedRecords, {
      ...request.record,
      accepted: false,
      action: ACTION_INSERT_TEXT,
      sessionId: SESSION_ID,
      sequence,
    });
    this.#deliveryRejected = true;
    this.#proxySessionCleared = true;
    this.#proxy.blur();
    this.#onNativeDeliveryRejected({
      action: ACTION_INSERT_TEXT,
      sessionId: SESSION_ID,
      sequence,
      accepted: false,
    });
    this.#publishState();
  }

  #resetShortcutForCanvasFocus() {
    if (this.#canvasHeldCodes.length === 0) {
      this.#shortcutIndex = 0;
      this.#shortcutComplete = false;
      this.#publishState();
    }
  }

  #canvasKeyRejectionReason(event, down) {
    const expected = [
      ["keydown", "ControlLeft"],
      ["keydown", "KeyL"],
      ["keyup", "KeyL"],
      ["keyup", "ControlLeft"],
    ];
    if (!this.#module() || this.#shortcutComplete) {
      return "trusted address shortcut is not ready";
    }
    const expectedEvent = expected[this.#shortcutIndex];
    if (!expectedEvent || expectedEvent[0] !== (down ? "keydown" : "keyup") ||
        expectedEvent[1] !== event.code) {
      return "DOM key is outside the bounded Ctrl+L transaction";
    }
    if (event.isTrusted !== true || event.cancelable !== true ||
        document.activeElement !== this.#canvas || event.isComposing ||
        event.repeat || event.key === "Dead" || event.key === "Process" ||
        event.metaKey || event.altKey || event.shiftKey ||
        event.getModifierState("AltGraph")) {
      return "DOM Ctrl+L key has unsupported trust, target, or modifier state";
    }
    if (event.code === "KeyL" && !event.ctrlKey) {
      return "DOM KeyL event lacks ControlLeft";
    }
    return null;
  }

  #handleCanvasKey(event, down) {
    const record = {
      type: down ? "keydown" : "keyup",
      code: event.code,
      trusted: event.isTrusted,
      cancelable: event.cancelable,
      canvasFocused: document.activeElement === this.#canvas,
      accepted: false,
      defaultPrevented: false,
    };
    const reason = this.#canvasKeyRejectionReason(event, down);
    if (reason !== null || this.#callHostKey(event.code, down) !== 1) {
      this.#reject(this.#ctrlLRecords, record,
          reason || "Chrome rejected a Ctrl+L key transition");
      return;
    }
    event.preventDefault();
    record.accepted = true;
    record.defaultPrevented = event.defaultPrevented;
    appendBounded(this.#ctrlLRecords, record);
    if (down) {
      this.#canvasHeldCodes.push(event.code);
    } else {
      this.#canvasHeldCodes = this.#canvasHeldCodes.filter((code) => code !== event.code);
    }
    ++this.#shortcutIndex;
    if (this.#shortcutIndex === 4) {
      this.#shortcutComplete = true;
      this.#onCtrlLComplete();
      this.#maybeAutoFocusProxy();
    }
    this.#publishState();
  }

  #beforeInputRejectionReason(event) {
    if (!this.#module() || !this.#shortcutComplete || this.#deliveryRejected ||
        !this.#editable || document.activeElement !== this.#proxy ||
        !this.#canAcceptBeforeInput()) {
      return "trusted browser text bridge is not ready";
    }
    if (this.#pendingDeliveries.size >= MAX_NATIVE_PENDING_DELIVERIES) {
      return "trusted browser text bridge is at its bounded native record limit";
    }
    if (event.isTrusted !== true || event.cancelable !== true ||
        event.isComposing || event.inputType !== "insertText" ||
        typeof event.data !== "string" || event.data.length === 0) {
      return "beforeinput is not trusted non-composing insertText";
    }
    // The three-byte-per-code-unit bound is conservative for UTF-8 and keeps
    // both resource caps in force before TextEncoder or _malloc can run.
    if (event.data.length > MAX_UTF16_UNITS ||
        event.data.length * 3 > MAX_UTF8_BYTES ||
        !isWellFormedUtf16(event.data)) {
      return "beforeinput text is outside the bounded well-formed UTF-16 policy";
    }
    if (this.#proxy.value !== "" || this.#proxy.selectionStart !== 0 ||
        this.#proxy.selectionEnd !== 0) {
      return "textarea proxy has pre-existing DOM text or selection";
    }
    const validation = this.#validateBeforeInput(event);
    if (typeof validation === "string" && validation.length > 0) {
      return validation;
    }
    return null;
  }

  #handleBeforeInput(event) {
    const record = this.#makeBeforeInputRecord(event);
    const reason = this.#beforeInputRejectionReason(event);
    if (reason !== null) {
      this.#rejectBeforeInput(event, record, reason);
      return;
    }
    // The conservative UTF-16 policy above runs before TextEncoder. This
    // makes the concrete UTF-8 aggregate check safe without allocating for an
    // unbounded paste or malformed DOM string.
    const bytes = this.#encoder.encode(event.data);
    if (bytes.byteLength === 0 || bytes.byteLength > MAX_UTF8_BYTES ||
        this.#pendingTextUtf8Bytes + bytes.byteLength >
            MAX_NATIVE_PENDING_UTF8_BYTES) {
      this.#rejectBeforeInput(event, record,
          "trusted browser text bridge is at its bounded native UTF-8 limit");
      return;
    }
    // The private proxy must never receive DOM text. Suppress its default
    // before immediate native admission captures the exact Ozone token.
    event.preventDefault();
    record.defaultPrevented = event.defaultPrevented;
    record.dataUtf8Bytes = bytes.byteLength;
    appendBounded(this.#beforeInputRecords, record);
    const sequence = this.#nextSequence;
    // Register before ccall: a worker can synchronously report delivery
    // before the C ABI invocation returns.
    const pending = {
      bytes,
      focusGeneration: this.#focusGeneration,
      record,
      text: event.data,
    };
    this.#pendingDeliveries.set(sequence, pending);
    this.#pendingTextUtf8Bytes += bytes.byteLength;
    if (this.#callHostTextBytes(bytes) !== 1) {
      this.#pendingDeliveries.delete(sequence);
      this.#releasePendingTextBytes(bytes.byteLength);
      this.#rejectNativeTextAdmission(pending, sequence);
      return;
    }
    ++this.#nextSequence;
    record.queued = true;
    record.sequence = sequence;
    record.nativeDispatched = true;
    this.#onBeforeInputQueued({...record, sequence});
    this.#publishState();
  }

  #handleProxyInput(event) {
    this.#clearProxyText();
    this.#reportFatal(
        `textarea proxy unexpectedly mutated after ${String(event.inputType || "input")}`);
  }

  #enterRejectionReason(event, down) {
    if (!this.#module() || !this.#shortcutComplete || this.#deliveryRejected ||
        !this.#editable || this.#pendingDeliveries.size !== 0 ||
        this.#acceptedDeliveryFocusGeneration !== this.#focusGeneration ||
        document.activeElement !== this.#proxy || !this.#canSubmitEnter()) {
      return "trusted physical Enter bridge is not ready";
    }
    if (event.isTrusted !== true || event.cancelable !== true ||
        event.code !== "Enter" || event.key !== "Enter" || event.isComposing ||
        event.repeat || event.ctrlKey || event.shiftKey || event.altKey ||
        event.metaKey || event.getModifierState("AltGraph")) {
      return "Enter has unsupported trust, physical, or modifier state";
    }
    if (down === this.#enterHeld) {
      return down ? "Enter is already held" : "Enter was not held";
    }
    return null;
  }

  #handleProxyEnter(event, down) {
    const record = {
      type: down ? "keydown" : "keyup",
      code: event.code,
      key: event.key,
      trusted: event.isTrusted,
      cancelable: event.cancelable,
      proxyFocused: document.activeElement === this.#proxy,
      accepted: false,
      defaultPrevented: false,
    };
    const reason = this.#enterRejectionReason(event, down);
    if (reason !== null || this.#callHostKey("Enter", down) !== 1) {
      this.#reject(this.#enterRecords, record,
          reason || "Chrome rejected an Enter key transition");
      return;
    }
    event.preventDefault();
    this.#enterHeld = down;
    record.accepted = true;
    record.defaultPrevented = event.defaultPrevented;
    appendBounded(this.#enterRecords, record);
    if (!down) {
      this.#onEnterComplete();
    }
    this.#publishState();
  }

  #releaseCanvasKeys(reason) {
    for (const code of [...this.#canvasHeldCodes].reverse()) {
      const accepted = this.#callHostKey(code, false) === 1;
      appendBounded(this.#cleanupRecords, {reason, code, accepted});
    }
    this.#canvasHeldCodes = [];
  }

  #releaseHeldEnter(reason) {
    if (!this.#enterHeld) {
      return;
    }
    const accepted = this.#callHostKey("Enter", false) === 1;
    appendBounded(this.#cleanupRecords, {reason, code: "Enter", accepted});
    this.#enterHeld = false;
  }

  #maybeAutoFocusProxy() {
    if (this.#autoFocusProxy && this.#shortcutComplete && this.#editable &&
        document.activeElement !== this.#proxy && !this.#deliveryRejected) {
      this.activateProxy();
    }
  }

  #reject(records, record, reason) {
    const rejected = {...record, accepted: false, rejectionReason: reason};
    appendBounded(records, rejected);
    appendBounded(this.#rejectedRecords, rejected);
    this.#publishState();
  }
}

export const chromeWasmTrustedTextInputContract = Object.freeze({
  ACTION_INSERT_TEXT,
  MAX_NATIVE_PENDING_DELIVERIES,
  MAX_NATIVE_PENDING_UTF8_BYTES,
  MAX_UTF8_BYTES,
  MAX_UTF16_UNITS,
  SESSION_ID,
});

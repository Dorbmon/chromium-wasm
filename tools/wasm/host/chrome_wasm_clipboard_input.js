// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// One-way trusted-DOM system-paste import for the normal Chrome Wasm host.
// This is deliberately not a replacement PlatformClipboard: it accepts only
// text/plain carried synchronously by a real paste event, copies it into the
// Wasm process-local clipboard, and leaves actual editing to native Ozone
// Ctrl+V handling. Production code never calls navigator.clipboard here.

const MAX_RECORD_HISTORY = 64;
const MAX_UTF8_BYTES = 192 * 1024;
const MAX_UTF16_UNITS = 64 * 1024;
const MAX_REQUEST_ID = 0x7fffffff;

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) {
    records.shift();
  }
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

function hasPlainText(clipboardData) {
  const types = clipboardData?.types;
  return types !== null && types !== undefined &&
      typeof types.length === "number" &&
      Array.prototype.includes.call(types, "text/plain");
}

function isValidOzoneTextInputState(report) {
  return report && typeof report === "object" &&
      typeof report.focusedClientPresent === "boolean" &&
      typeof report.editable === "boolean" &&
      typeof report.canComposeInline === "boolean" &&
      (!report.editable || report.focusedClientPresent) &&
      (!report.canComposeInline || report.editable);
}

function isValidClipboardPasteDelivery(report) {
  return report && typeof report === "object" &&
      Number.isSafeInteger(report.requestId) && report.requestId >= 1 &&
      report.requestId <= MAX_REQUEST_ID && typeof report.accepted === "boolean";
}

// Maps one trusted DOM paste event into exactly one C++ import. It never
// accepts a host-selected widget, MIME type, URL, or Browser command.
export class ChromiumWasmTrustedClipboardInput {
  #proxy;
  #getModule;
  #reportFatal;
  #onStateChange;
  #onNativeDelivery;
  #encoder = new TextEncoder();
  #attached = false;
  #editable = false;
  #focusGeneration = 0;
  #adapterGeneration = 0;
  #nextRequestId = 1;
  #pending = null;
  #tombstonedRequestIds = new Set();
  #pasteRecords = [];
  #deliveryReports = [];
  #rejectedRecords = [];
  #cleanupRecords = [];
  #onPaste;
  #onProxyBlur;
  #onWindowBlur;
  #onVisibilityChange;

  constructor(proxy, {
    getModule,
    reportFatal,
    onStateChange = () => {},
    onNativeDelivery = () => {},
  }) {
    if (!(proxy instanceof HTMLTextAreaElement)) {
      throw new Error("trusted clipboard adapter requires a textarea proxy");
    }
    if (typeof getModule !== "function" || typeof reportFatal !== "function" ||
        typeof onStateChange !== "function" || typeof onNativeDelivery !== "function") {
      throw new Error("trusted clipboard adapter options are invalid");
    }
    this.#proxy = proxy;
    this.#getModule = getModule;
    this.#reportFatal = reportFatal;
    this.#onStateChange = onStateChange;
    this.#onNativeDelivery = onNativeDelivery;
  }

  attach() {
    if (this.#attached) {
      return;
    }
    ++this.#adapterGeneration;
    this.#onPaste = (event) => this.#handlePaste(event);
    this.#onProxyBlur = () => this.#clearPending("proxy-blur");
    this.#onWindowBlur = () => this.#clearPending("window-blur");
    this.#onVisibilityChange = () => {
      if (document.hidden) {
        this.#clearPending("document-hidden");
      }
    };
    this.#proxy.addEventListener("paste", this.#onPaste);
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
    this.#clearPending("teardown");
    this.#proxy.removeEventListener("paste", this.#onPaste);
    this.#proxy.removeEventListener("blur", this.#onProxyBlur);
    window.removeEventListener("blur", this.#onWindowBlur);
    document.removeEventListener("visibilitychange", this.#onVisibilityChange);
    ++this.#adapterGeneration;
    this.#attached = false;
    this.#editable = false;
    this.#clearProxyText();
    this.#publishState();
  }

  handleOzoneTextInputState(report) {
    if (!isValidOzoneTextInputState(report)) {
      this.#reportFatal("trusted clipboard adapter received invalid Ozone state");
      return;
    }
    // An Ozone client/type transition invalidates the exact C++ focus epoch
    // captured for any pending paste. Cancel before recording the new state.
    this.#clearPending("ozone-text-input-state-transition",
                       /*deferNativeCancel=*/true);
    this.#editable = report.editable;
    ++this.#focusGeneration;
    this.#publishState();
  }

  handleOzoneBrowserClipboardPasteDelivery(report) {
    if (!isValidClipboardPasteDelivery(report)) {
      this.#reportFatal("trusted clipboard adapter received invalid delivery");
      return;
    }
    const pending = this.#pending;
    if (!pending || pending.requestId !== report.requestId) {
      if (this.#tombstonedRequestIds.delete(report.requestId)) {
        // Blur, hide, teardown, and exact C++ cancellation intentionally make
        // a late terminal report inert. No raw clipboard text is retained.
        return;
      }
      this.#reportFatal("clipboard paste delivery has no pending request");
      return;
    }

    // Drop the only request state and clear the otherwise inert textarea
    // before any callback is deferred. Consumers observe metadata only.
    this.#pending = null;
    this.#clearProxyText();
    const accepted = report.accepted && this.#attached && this.#editable &&
        document.activeElement === this.#proxy &&
        pending.focusGeneration === this.#focusGeneration;
    appendBounded(this.#deliveryReports, {
      requestId: report.requestId,
      nativeAccepted: report.accepted,
      accepted,
    });
    if (!accepted) {
      appendBounded(this.#rejectedRecords, {
        requestId: report.requestId,
        reason: report.accepted ? "focus-transition-before-delivery" :
          "native-clipboard-import-rejected",
      });
      this.#publishState();
      return;
    }

    const adapterGeneration = this.#adapterGeneration;
    this.#publishState();
    // This report is the host side of a synchronous UI->JS import. Never
    // reenter a Wasm export here; C++ smoke observations are scheduled later.
    setTimeout(() => {
      if (!this.#attached || adapterGeneration !== this.#adapterGeneration) {
        return;
      }
      try {
        this.#onNativeDelivery(Object.freeze({
          requestId: report.requestId,
          accepted: true,
        }));
      } catch (error) {
        this.#reportFatal(
            `trusted clipboard delivery callback failed: ${String(error)}`);
      }
    }, 0);
  }

  snapshot() {
    return {
      attached: this.#attached,
      editable: this.#editable,
      proxyFocused: document.activeElement === this.#proxy,
      focusGeneration: this.#focusGeneration,
      pendingRequestId: this.#pending?.requestId ?? null,
      tombstonedRequestCount: this.#tombstonedRequestIds.size,
      // Clipboard text is never diagnostics data.  A rejected or otherwise
      // unexpected paste can leave a browser-default value here briefly, so
      // expose only this boolean to callers rather than serializing host
      // clipboard contents into a normal-host result or failure report.
      proxyTextEmpty: this.#proxy.value === "",
      pasteRecords: [...this.#pasteRecords],
      deliveryReports: [...this.#deliveryReports],
      rejectedRecords: [...this.#rejectedRecords],
      cleanupRecords: [...this.#cleanupRecords],
    };
  }

  #publishState() {
    try {
      this.#onStateChange(this.snapshot());
    } catch (error) {
      this.#reportFatal(`trusted clipboard state callback failed: ${String(error)}`);
    }
  }

  #module() {
    const module = this.#getModule();
    return module && typeof module.ccall === "function" ? module : null;
  }

  #clearProxyText() {
    this.#proxy.value = "";
    this.#proxy.setSelectionRange(0, 0);
  }

  #tombstoneRequest(requestId) {
    if (!Number.isSafeInteger(requestId) || requestId < 1) {
      return;
    }
    if (this.#tombstonedRequestIds.size >= MAX_RECORD_HISTORY) {
      const oldest = this.#tombstonedRequestIds.values().next().value;
      this.#tombstonedRequestIds.delete(oldest);
    }
    this.#tombstonedRequestIds.add(requestId);
  }

  #callHostCancel(requestId) {
    const module = this.#module();
    if (!module) {
      return false;
    }
    try {
      return module.ccall(
          "chromium_wasm_browser_host_clipboard_cancel", "number", ["number"],
          [requestId]) === 1;
    } catch (error) {
      this.#reportFatal(`trusted clipboard cancel ABI call failed: ${String(error)}`);
      return false;
    }
  }

  #clearPending(reason, deferNativeCancel = false) {
    const pending = this.#pending;
    this.#clearProxyText();
    if (!pending) {
      return;
    }
    // Tombstone before cancellation: a synchronous C++ false report must not
    // find an active request or expose a stale callback.
    this.#pending = null;
    this.#tombstoneRequest(pending.requestId);
    const cleanup = {
      requestId: pending.requestId,
      reason,
      canceled: null,
      deferredNativeCancel: deferNativeCancel,
    };
    appendBounded(this.#cleanupRecords, cleanup);
    if (deferNativeCancel) {
      // Ozone text-state reports arrive through a synchronous UI->JS import.
      // The report already advanced the native focus epoch, so this exact
      // request cannot pass C++ validation; defer the optional cancellation
      // rather than reentering a Wasm export from that import.
      const adapterGeneration = this.#adapterGeneration;
      setTimeout(() => {
        if (adapterGeneration !== this.#adapterGeneration) {
          return;
        }
        cleanup.canceled = this.#callHostCancel(pending.requestId);
        this.#publishState();
      }, 0);
    } else {
      cleanup.canceled = this.#callHostCancel(pending.requestId);
    }
    this.#publishState();
  }

  #callHostPasteBytes(bytes, requestId) {
    const module = this.#module();
    if (!module || typeof module._malloc !== "function" ||
        typeof module._free !== "function" ||
        !(module.HEAPU8 instanceof Uint8Array)) {
      this.#reportFatal("trusted clipboard module lacks explicit UTF-8 allocation ABI");
      return false;
    }
    if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0 ||
        bytes.byteLength > MAX_UTF8_BYTES || !Number.isSafeInteger(requestId) ||
        requestId < 1 || requestId > MAX_REQUEST_ID) {
      return false;
    }
    let pointer = 0;
    try {
      pointer = module._malloc(bytes.byteLength);
      if (!Number.isSafeInteger(pointer) || pointer <= 0 ||
          pointer + bytes.byteLength > module.HEAPU8.byteLength) {
        throw new Error("Wasm clipboard allocation is outside the current heap");
      }
      // C++ copies this range before it posts a UI task. Never retain the
      // view, which can be invalidated if Wasm memory grows after this call.
      module.HEAPU8.set(bytes, pointer);
      return module.ccall(
          "chromium_wasm_browser_host_clipboard_paste", "number",
          ["number", "number", "number"],
          [pointer, bytes.byteLength, requestId]) === 1;
    } catch (error) {
      this.#reportFatal(`trusted clipboard ABI call failed: ${String(error)}`);
      return false;
    } finally {
      if (pointer > 0) {
        module._free(pointer);
      }
      bytes.fill(0);
    }
  }

  #rejectPaste(record, reason, preventDefault) {
    if (preventDefault && record.cancelable) {
      record.event.preventDefault();
    }
    record.defaultPrevented = record.event.defaultPrevented;
    delete record.event;
    record.reason = reason;
    appendBounded(this.#pasteRecords, record);
    appendBounded(this.#rejectedRecords, {
      requestId: null,
      reason,
    });
    this.#clearProxyText();
    this.#publishState();
  }

  #handlePaste(event) {
    const record = {
      event,
      trusted: event.isTrusted === true,
      cancelable: event.cancelable === true,
      proxyFocused: document.activeElement === this.#proxy,
      containsPlainText: false,
      textUtf16Units: null,
      textUtf8Bytes: null,
      requestId: null,
      admitted: false,
      defaultPrevented: false,
      reason: null,
    };
    if (!this.#attached || !this.#module() || !this.#editable ||
        !record.proxyFocused) {
      this.#rejectPaste(record, "clipboard-bridge-not-ready", record.trusted);
      return;
    }
    if (!record.trusted) {
      this.#rejectPaste(record, "untrusted-dom-paste", false);
      return;
    }
    if (!record.cancelable) {
      this.#rejectPaste(record, "noncancelable-dom-paste", false);
      return;
    }
    if (event.defaultPrevented) {
      this.#rejectPaste(record, "paste-default-already-prevented", true);
      return;
    }
    if (this.#pending) {
      this.#rejectPaste(record, "duplicate-pending-paste", true);
      return;
    }
    if (!event.clipboardData || typeof event.clipboardData.getData !== "function" ||
        !hasPlainText(event.clipboardData)) {
      this.#rejectPaste(record, "missing-text-plain-clipboard-data", true);
      return;
    }

    let text;
    try {
      // Cache the trusted clipboard payload synchronously before preventing
      // the outer DOM default or allowing C++ to schedule native Ctrl+V.
      text = event.clipboardData.getData("text/plain");
    } catch (error) {
      this.#rejectPaste(record, `clipboard-read-failed:${String(error)}`, true);
      return;
    }
    record.containsPlainText = true;
    record.textUtf16Units = typeof text === "string" ?
      Math.min(text.length, MAX_UTF16_UNITS + 1) : null;
    if (typeof text !== "string" || text.length === 0 ||
        text.length > MAX_UTF16_UNITS || text.length * 3 > MAX_UTF8_BYTES ||
        !isWellFormedUtf16(text)) {
      this.#rejectPaste(record, "clipboard-text-is-empty-or-outside-bounds", true);
      return;
    }

    let bytes;
    try {
      bytes = this.#encoder.encode(text);
    } catch (error) {
      this.#rejectPaste(record, `clipboard-utf8-encode-failed:${String(error)}`, true);
      return;
    }
    // Do not retain the raw DOM clipboard string beyond the synchronous copy.
    text = "";
    record.textUtf8Bytes = bytes.byteLength;
    if (bytes.byteLength === 0 || bytes.byteLength > MAX_UTF8_BYTES) {
      bytes.fill(0);
      this.#rejectPaste(record, "clipboard-utf8-is-outside-bounds", true);
      return;
    }
    if (this.#nextRequestId > MAX_REQUEST_ID) {
      bytes.fill(0);
      this.#rejectPaste(record, "clipboard-request-id-space-exhausted", true);
      return;
    }

    const requestId = this.#nextRequestId++;
    record.requestId = requestId;
    // Register the one pending request before the C ABI. A shutdown may emit
    // a synchronous terminal false acknowledgement while this call is active.
    this.#pending = {
      requestId,
      focusGeneration: this.#focusGeneration,
    };
    event.preventDefault();
    record.defaultPrevented = event.defaultPrevented;
    const admitted = this.#callHostPasteBytes(bytes, requestId);
    if (!admitted && this.#pending?.requestId === requestId) {
      this.#pending = null;
      record.reason = "native-clipboard-import-not-admitted";
      appendBounded(this.#rejectedRecords, {
        requestId,
        reason: record.reason,
      });
    } else if (admitted) {
      record.admitted = true;
    }
    delete record.event;
    appendBounded(this.#pasteRecords, record);
    this.#clearProxyText();
    this.#publishState();
  }
}

export const chromeWasmTrustedClipboardInputContract = Object.freeze({
  MAX_UTF8_BYTES,
  MAX_UTF16_UNITS,
  MAX_REQUEST_ID,
});

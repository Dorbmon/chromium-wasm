// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// One-way trusted-DOM import for a page's ordinary <input type=file>. This is
// deliberately not a File System Access API adapter, an OPFS bridge, or a
// general filesystem facade. It copies at most one user-selected regular file
// into a Browser-owned volatile Wasm vault and exposes no outer-host path,
// handle, URL, MIME type, or file name to host diagnostics.

const FILE_PICKER_PROTOCOL = 1;
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_FILE_NAME_BYTES = 255;
const FILE_CHUNK_BYTES = 64 * 1024;
const MAX_REQUEST_ID = 0x7fffffff;
const MAX_RECORD_HISTORY = 64;
const PICKER_TIMEOUT_MS = 120000;

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

function isValidFilePickerRequest(report) {
  return report && typeof report === "object" &&
      report.protocol === FILE_PICKER_PROTOCOL &&
      Number.isSafeInteger(report.requestId) && report.requestId >= 1 &&
      report.requestId <= MAX_REQUEST_ID;
}

function isValidFilePickerDelivery(report) {
  return report && typeof report === "object" &&
      report.protocol === FILE_PICKER_PROTOCOL &&
      Number.isSafeInteger(report.requestId) && report.requestId >= 1 &&
      report.requestId <= MAX_REQUEST_ID && typeof report.accepted === "boolean";
}

// Maps one Chromium-owned opaque picker request to one user-activated DOM
// input. It intentionally retains no selected File, filename, heap view, or
// outer DOM element after a terminal native acknowledgement.
export class ChromiumWasmTrustedFilePicker {
  #getModule;
  #reportFatal;
  #encoder = new TextEncoder();
  #attached = false;
  #adapterGeneration = 0;
  #lastRequestId = 0;
  #pending = null;
  #tombstonedRequestIds = new Set();
  #deliveryReports = [];
  #cleanupRecords = [];
  #rejectedRecords = [];

  constructor({getModule, reportFatal}) {
    if (typeof getModule !== "function" || typeof reportFatal !== "function") {
      throw new Error("trusted file picker adapter options are invalid");
    }
    this.#getModule = getModule;
    this.#reportFatal = reportFatal;
  }

  attach() {
    if (this.#attached) {
      return;
    }
    ++this.#adapterGeneration;
    this.#attached = true;
  }

  detach() {
    if (!this.#attached) {
      return;
    }
    this.#cancelPending("teardown");
    ++this.#adapterGeneration;
    this.#attached = false;
  }

  request(report) {
    if (!isValidFilePickerRequest(report)) {
      this.#reportFatal("trusted file picker received an invalid request");
      return false;
    }
    if (!this.#attached || this.#pending || report.requestId <= this.#lastRequestId ||
        !this.#module()) {
      this.#reject(report.requestId, "picker-bridge-not-ready");
      return false;
    }
    if (document.visibilityState !== "visible" ||
        navigator.userActivation?.isActive !== true ||
        typeof HTMLInputElement.prototype.showPicker !== "function" ||
        !document.body) {
      this.#reject(report.requestId, "picker-user-activation-unavailable");
      return false;
    }

    let input;
    try {
      input = document.createElement("input");
      input.type = "file";
      input.multiple = false;
      input.tabIndex = -1;
      input.autocomplete = "off";
      input.setAttribute("aria-hidden", "true");
      // The control must remain enabled and rendered for showPicker(), but it
      // is not an alternate visible browser UI or an independently focusable
      // outer-page target.
      input.style.cssText = [
        "position:fixed",
        "left:-10000px",
        "top:0",
        "width:1px",
        "height:1px",
        "opacity:0",
        "pointer-events:none",
      ].join(";");
    } catch (_) {
      this.#reject(report.requestId, "picker-control-creation-failed");
      return false;
    }

    const pending = {
      requestId: report.requestId,
      input,
      generation: this.#adapterGeneration,
      phase: "awaiting-selection",
      timeout: null,
      onChange: null,
      onCancel: null,
      onVisibilityChange: null,
    };
    pending.onChange = () => {
      // showPicker() is specified to complete asynchronously, but defer the
      // byte-transfer ABI even if a test DOM dispatches change synchronously:
      // C++ marks this request admitted only after this import returns.
      queueMicrotask(() => {
        if (this.#isCurrentPending(pending.requestId)) {
          void this.#handleChange(pending.requestId).catch(() => {
            // Keep an unexpected async adapter failure from becoming an
            // unhandled rejection or leaving the Chromium chooser pending.
            // The diagnostic intentionally carries no selected-file detail.
            this.#reportFatal("trusted file picker selection dispatch failed");
            this.#cancelPendingFor(
                pending.requestId, "file-selection-dispatch-failed");
          });
        }
      });
    };
    pending.onCancel = () => {
      this.#cancelPendingFor(pending.requestId, "picker-cancelled");
    };
    pending.onVisibilityChange = () => {
      if (document.hidden) {
        this.#cancelPendingFor(pending.requestId, "document-hidden");
      }
    };
    input.addEventListener("change", pending.onChange, {once: true});
    input.addEventListener("cancel", pending.onCancel, {once: true});
    document.addEventListener("visibilitychange", pending.onVisibilityChange);
    this.#pending = pending;
    this.#lastRequestId = report.requestId;

    try {
      document.body.append(input);
      // Do not fall back to input.click(): an unavailable or consumed
      // transient activation must cancel the Chromium chooser explicitly.
      input.showPicker();
      pending.timeout = setTimeout(() => {
        this.#cancelPendingFor(pending.requestId, "picker-timeout");
      }, PICKER_TIMEOUT_MS);
      return true;
    } catch (_) {
      this.#discardPending(pending);
      this.#reject(report.requestId, "picker-show-failed");
      return false;
    }
  }

  handleOzoneBrowserFilePickerDelivery(report) {
    if (!isValidFilePickerDelivery(report)) {
      this.#reportFatal("trusted file picker received an invalid delivery");
      return;
    }
    const pending = this.#pending;
    if (!pending || pending.requestId !== report.requestId) {
      if (this.#tombstonedRequestIds.delete(report.requestId)) {
        return;
      }
      this.#reportFatal("file picker delivery has no pending request");
      return;
    }

    this.#pending = null;
    this.#disposePendingDom(pending);
    appendBounded(this.#deliveryReports, {
      requestId: report.requestId,
      accepted: report.accepted,
    });
  }

  snapshot() {
    return {
      attached: this.#attached,
      pendingRequestId: this.#pending?.requestId ?? null,
      pendingPhase: this.#pending?.phase ?? null,
      lastRequestId: this.#lastRequestId,
      tombstonedRequestCount: this.#tombstonedRequestIds.size,
      deliveryReports: [...this.#deliveryReports],
      cleanupRecords: [...this.#cleanupRecords],
      rejectedRecords: [...this.#rejectedRecords],
    };
  }

  #module() {
    const module = this.#getModule();
    if (!module || typeof module.ccall !== "function" ||
        typeof module._malloc !== "function" || typeof module._free !== "function" ||
        !(module.HEAPU8 instanceof Uint8Array)) {
      return null;
    }
    return module;
  }

  #reject(requestId, reason) {
    appendBounded(this.#rejectedRecords, {requestId, reason});
  }

  #tombstoneRequest(requestId) {
    if (this.#tombstonedRequestIds.size >= MAX_RECORD_HISTORY) {
      const oldest = this.#tombstonedRequestIds.values().next().value;
      this.#tombstonedRequestIds.delete(oldest);
    }
    this.#tombstonedRequestIds.add(requestId);
  }

  #disposePendingDom(pending) {
    if (pending.timeout !== null) {
      clearTimeout(pending.timeout);
      pending.timeout = null;
    }
    document.removeEventListener("visibilitychange", pending.onVisibilityChange);
    const input = pending.input;
    if (!input) {
      return;
    }
    input.removeEventListener("change", pending.onChange);
    input.removeEventListener("cancel", pending.onCancel);
    // Clear before removing so a retained outer DOM reference cannot retain a
    // chosen File after the native transfer reaches a terminal state.
    input.value = "";
    input.remove();
    pending.input = null;
  }

  #discardPending(pending) {
    if (this.#pending === pending) {
      this.#pending = null;
    }
    this.#disposePendingDom(pending);
  }

  #callCancel(requestId) {
    const module = this.#module();
    if (!module) {
      return false;
    }
    try {
      return module.ccall(
          "chromium_wasm_browser_host_file_picker_cancel", "number", ["number"],
          [requestId]) === 1;
    } catch (_) {
      this.#reportFatal("trusted file picker cancel ABI call failed");
      return false;
    }
  }

  #cancelPending(reason) {
    if (this.#pending) {
      this.#cancelPendingFor(this.#pending.requestId, reason);
    }
  }

  #cancelPendingFor(requestId, reason) {
    const pending = this.#pending;
    if (!pending || pending.requestId !== requestId) {
      return;
    }
    // Tombstone before this C ABI call: cancellation can synchronously report
    // native delivery back through the Emscripten import.
    this.#pending = null;
    this.#tombstoneRequest(requestId);
    this.#disposePendingDom(pending);
    const canceled = this.#callCancel(requestId);
    appendBounded(this.#cleanupRecords, {requestId, reason, canceled});
  }

  #callWithCopiedHeapBytes(bytes, callback) {
    const module = this.#module();
    if (!module || !(bytes instanceof Uint8Array) || bytes.byteLength === 0) {
      bytes?.fill?.(0);
      return false;
    }
    let pointer = 0;
    try {
      pointer = module._malloc(bytes.byteLength);
      const heap = module.HEAPU8;
      if (!Number.isSafeInteger(pointer) || pointer <= 0 ||
          pointer + bytes.byteLength > heap.byteLength) {
        throw new Error("Wasm file-picker allocation is outside the current heap");
      }
      // C++ copies every import range before returning. Do not retain this
      // typed-array view across an await or any later C ABI call.
      heap.set(bytes, pointer);
      return callback(module, pointer);
    } catch (_) {
      this.#reportFatal("trusted file picker ABI call failed");
      return false;
    } finally {
      if (pointer > 0) {
        const heap = module.HEAPU8;
        if (heap instanceof Uint8Array && pointer + bytes.byteLength <= heap.byteLength) {
          heap.fill(0, pointer, pointer + bytes.byteLength);
        }
        module._free(pointer);
      }
      bytes.fill(0);
    }
  }

  #callBegin(fileNameBytes, fileSize, requestId) {
    return this.#callWithCopiedHeapBytes(fileNameBytes, (module, pointer) =>
      module.ccall(
          "chromium_wasm_browser_host_file_picker_begin", "number",
          ["number", "number", "number", "number"],
          [pointer, fileNameBytes.byteLength, fileSize, requestId]) === 1);
  }

  #callChunk(bytes, sequence, requestId) {
    return this.#callWithCopiedHeapBytes(bytes, (module, pointer) =>
      module.ccall(
          "chromium_wasm_browser_host_file_picker_chunk", "number",
          ["number", "number", "number", "number"],
          [pointer, bytes.byteLength, sequence, requestId]) === 1);
  }

  #callComplete(requestId) {
    const module = this.#module();
    if (!module) {
      return false;
    }
    try {
      return module.ccall(
          "chromium_wasm_browser_host_file_picker_complete", "number", ["number"],
          [requestId]) === 1;
    } catch (_) {
      this.#reportFatal("trusted file picker complete ABI call failed");
      return false;
    }
  }

  #isCurrentPending(requestId) {
    const pending = this.#pending;
    return pending && pending.requestId === requestId && this.#attached &&
        pending.generation === this.#adapterGeneration;
  }

  async #handleChange(requestId) {
    const pending = this.#pending;
    if (!pending || pending.requestId !== requestId ||
        pending.phase !== "awaiting-selection") {
      return;
    }
    const files = pending.input?.files;
    const file = files?.length === 1 ? files.item(0) : null;
    if (!file || typeof file.arrayBuffer !== "function" ||
        !Number.isSafeInteger(file.size) || file.size < 0 ||
        file.size > MAX_FILE_BYTES || typeof file.name !== "string" ||
        file.name.length === 0 || file.name.includes("\0") ||
        file.name.includes("/") || file.name.includes("\\") ||
        file.name === "." || file.name === ".." ||
        !isWellFormedUtf16(file.name)) {
      this.#cancelPendingFor(requestId, "selected-file-is-unsupported");
      return;
    }

    let fileNameBytes = this.#encoder.encode(file.name);
    if (fileNameBytes.byteLength === 0 ||
        fileNameBytes.byteLength > MAX_FILE_NAME_BYTES) {
      fileNameBytes.fill(0);
      this.#cancelPendingFor(requestId, "selected-file-name-is-unsupported");
      return;
    }

    pending.phase = "copying";
    if (!this.#callBegin(fileNameBytes, file.size, requestId)) {
      this.#cancelPendingFor(requestId, "native-file-import-not-admitted");
      return;
    }

    try {
      let sequence = 0;
      for (let offset = 0; offset < file.size; offset += FILE_CHUNK_BYTES) {
        const end = Math.min(offset + FILE_CHUNK_BYTES, file.size);
        const bytes = new Uint8Array(await file.slice(offset, end).arrayBuffer());
        if (!this.#isCurrentPending(requestId)) {
          bytes.fill(0);
          return;
        }
        if (bytes.byteLength !== end - offset ||
            !this.#callChunk(bytes, sequence, requestId)) {
          this.#cancelPendingFor(requestId, "native-file-chunk-rejected");
          return;
        }
        ++sequence;
      }
      if (!this.#isCurrentPending(requestId) || !this.#callComplete(requestId)) {
        this.#cancelPendingFor(requestId, "native-file-complete-rejected");
        return;
      }
      // The input File is no longer needed after C++ copied the final chunk.
      // Retain only the opaque pending ID until Chromium acknowledges whether
      // it materialized that copied file into its volatile vault.
      pending.phase = "awaiting-native-delivery";
      this.#disposePendingDom(pending);
    } catch (_) {
      this.#reportFatal("trusted file picker file-read failed");
      this.#cancelPendingFor(requestId, "file-read-failed");
    }
  }
}

export const chromeWasmTrustedFilePickerContract = Object.freeze({
  FILE_CHUNK_BYTES,
  MAX_FILE_BYTES,
  MAX_FILE_NAME_BYTES,
  MAX_REQUEST_ID,
  PICKER_TIMEOUT_MS,
});

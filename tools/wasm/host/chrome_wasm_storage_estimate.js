// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A narrow, read-only adapter for the outer page's storage estimate. It does
// not open OPFS, request persistence, expose the host origin, or infer a
// Chromium Wasm profile quota. The C++ owner assigns and validates the opaque
// generation; this adapter only returns aggregate byte scalars after the
// synchronous UI-thread-to-JavaScript import has returned.
const HOST_PROTOCOL = 1;
const OUTCOME_AVAILABLE = 1;
const OUTCOME_UNAVAILABLE = 2;
const OUTCOME_ERROR = 3;
const MAX_EXACT_STORAGE_BYTES = Number.MAX_SAFE_INTEGER;

function isGeneration(value) {
  return Number.isSafeInteger(value) && value >= 1 &&
      value <= 0x7fffffff;
}

function isExactStorageBytes(value) {
  return Number.isSafeInteger(value) && value >= 0 &&
      value <= MAX_EXACT_STORAGE_BYTES;
}

function validateRequest(value) {
  return value && typeof value === "object" &&
      value.protocol === HOST_PROTOCOL && isGeneration(value.generation);
}

// The host creates this before Chromium application code can call the bridge.
// Its one terminal C ABI call is always deferred through a Promise turn: a
// synchronous `ccall` here would re-enter C++ while its sync proxy import is
// still on the stack.
export class ChromiumWasmOuterOriginStorageEstimate {
  #getModule;
  #recordFatal;
  #onResult;
  #pendingGenerations = new Set();
  #acceptedGenerations = new Set();
  #disposed = false;

  constructor({getModule, recordFatal, onResult}) {
    if (typeof getModule !== "function" ||
        typeof recordFatal !== "function" || typeof onResult !== "function") {
      throw new TypeError("storage-estimate adapter callbacks are invalid");
    }
    this.#getModule = getModule;
    this.#recordFatal = recordFatal;
    this.#onResult = onResult;
  }

  request(value) {
    if (this.#disposed || !validateRequest(value) ||
        this.#acceptedGenerations.has(value.generation)) {
      return false;
    }
    const module = this.#getModule();
    if (!module || typeof module.ccall !== "function") {
      return false;
    }
    this.#acceptedGenerations.add(value.generation);
    this.#pendingGenerations.add(value.generation);

    // Do not turn this into an async IIFE invoked on the import stack. The
    // first callback must run after the synchronous proxy has returned.
    Promise.resolve()
        .then(() => this.#collectEstimate())
        .then(
            (result) => this.#deliver(value.generation, result),
            () => this.#deliver(value.generation, {
              outcome: OUTCOME_ERROR,
              usageBytes: 0,
              quotaBytes: 0,
            }));
    return true;
  }

  dispose() {
    this.#disposed = true;
    this.#pendingGenerations.clear();
    this.#acceptedGenerations.clear();
  }

  async #collectEstimate() {
    try {
      const storage = globalThis.navigator?.storage;
      if (!storage || typeof storage.estimate !== "function") {
        return {
          outcome: OUTCOME_UNAVAILABLE,
          usageBytes: 0,
          quotaBytes: 0,
        };
      }
      const estimate = await storage.estimate();
      const usageBytes = estimate?.usage;
      const quotaBytes = estimate?.quota;
      if (!isExactStorageBytes(usageBytes) ||
          !isExactStorageBytes(quotaBytes) || usageBytes > quotaBytes) {
        return {
          outcome: OUTCOME_ERROR,
          usageBytes: 0,
          quotaBytes: 0,
        };
      }
      return {
        outcome: OUTCOME_AVAILABLE,
        usageBytes,
        quotaBytes,
      };
    } catch (_error) {
      // A rejected estimate has its own bounded error state. No host exception
      // text crosses into Chromium or results.
      return {
        outcome: OUTCOME_ERROR,
        usageBytes: 0,
        quotaBytes: 0,
      };
    }
  }

  #deliver(generation, result) {
    if (this.#disposed || !this.#pendingGenerations.delete(generation)) {
      return;
    }

    let accepted = false;
    try {
      const module = this.#getModule();
      if (!module || typeof module.ccall !== "function") {
        throw new Error("storage-estimate completion ABI is unavailable");
      }
      accepted = module.ccall(
          "chromium_wasm_browser_host_storage_estimate_complete", "number",
          ["number", "number", "number", "number"],
          [generation, result.outcome, result.usageBytes, result.quotaBytes]) === 1;
    } catch (_error) {
      // This is a host plumbing failure, not an unavailable storage estimate.
      // Keep the message fixed so outer-page exception text is not retained.
      this.#recordFatal("outer-origin storage-estimate completion ABI failed");
    }
    this.#onResult({
      generation,
      status: result.outcome === OUTCOME_AVAILABLE ? "available" :
          result.outcome === OUTCOME_UNAVAILABLE ? "unavailable" : "error",
      delivered: accepted,
    });
  }
}

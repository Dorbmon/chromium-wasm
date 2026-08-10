// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// The ordinary Chrome Wasm host and its real-browser tab-flow smoke share
// this exact adapter. It is deliberately narrower than a general DOM input
// bridge: only trusted, cancelable primary mouse records whose coordinates are
// inside the displayed canvas may reach Chrome's bounded Ozone ABI.

const POINTER_MOVE = 0;
const POINTER_DOWN = 1;
const POINTER_UP = 2;

function asPositiveInteger(value, description) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`${description} must be a positive integer`);
  }
  return value;
}

function noOp() {}

// Maps trusted host-canvas PointerEvents to the Chrome-owned C ABI. This
// adapter does not expose an arbitrary export call: its only outbound records
// are bounded mouse move/down/up and an unpressed hover exit.
export class ChromiumWasmTrustedPointerInput {
  #canvas;
  #getModule;
  #recordFatal;
  #record;
  #maximumFrameDimension;
  #attached = false;
  #activePointerId = null;
  #lastPoint = null;
  #hoverActive = false;
  #onPointerDown;
  #onPointerMove;
  #onPointerUp;
  #onPointerCancel;
  #onPointerLeave;
  #onCanvasBlur;
  #onWindowBlur;
  #onVisibilityChange;
  #onLostPointerCapture;

  constructor(canvas, {
    getModule,
    recordFatal = noOp,
    record = noOp,
    maximumFrameDimension = 16384,
  }) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("trusted pointer input requires a canvas");
    }
    if (typeof getModule !== "function") {
      throw new Error("trusted pointer input requires a Module getter");
    }
    if (typeof recordFatal !== "function" || typeof record !== "function") {
      throw new Error("trusted pointer input callbacks must be functions");
    }
    this.#canvas = canvas;
    this.#getModule = getModule;
    this.#recordFatal = recordFatal;
    this.#record = record;
    this.#maximumFrameDimension = asPositiveInteger(
        maximumFrameDimension, "maximum frame dimension");
  }

  get attached() {
    return this.#attached;
  }

  #recordEvent(record) {
    try {
      this.#record(Object.freeze({...record}));
    } catch (error) {
      this.#recordFatal(`host pointer record callback failed: ${String(error)}`);
    }
  }

  #eventRecord(type, event) {
    return {
      type,
      trusted: event.isTrusted === true,
      cancelable: event.cancelable === true,
      pointerType: event.pointerType,
      primary: event.isPrimary === true,
      pointerId: Number(event.pointerId),
      button: Number(event.button),
      buttons: Number(event.buttons),
      accepted: false,
      defaultPrevented: false,
      x: null,
      y: null,
      reason: null,
    };
  }

  #reject(record, reason) {
    record.reason = reason;
    record.defaultPrevented = false;
    this.#recordEvent(record);
  }

  #canvasPointForPointerEvent(event) {
    const rect = this.#canvas.getBoundingClientRect();
    const contentWidth = this.#canvas.clientWidth;
    const contentHeight = this.#canvas.clientHeight;
    if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY) ||
        !Number.isFinite(rect.left) || !Number.isFinite(rect.top) ||
        !Number.isFinite(contentWidth) || !Number.isFinite(contentHeight) ||
        contentWidth <= 0 || contentHeight <= 0) {
      return null;
    }

    const cssX = event.clientX - rect.left - this.#canvas.clientLeft;
    const cssY = event.clientY - rect.top - this.#canvas.clientTop;
    if (cssX < 0 || cssY < 0 || cssX >= contentWidth ||
        cssY >= contentHeight) {
      return null;
    }

    // Ozone's SystemInputInjector consumes physical display pixels. A frame
    // can resize the canvas backing store independently from CSS layout, so
    // make this conversion at the DOM boundary rather than in Chrome UI.
    const x = Math.floor((cssX * this.#canvas.width) / contentWidth);
    const y = Math.floor((cssY * this.#canvas.height) / contentHeight);
    if (!Number.isSafeInteger(x) || !Number.isSafeInteger(y) || x < 0 ||
        y < 0 || x >= this.#canvas.width || y >= this.#canvas.height ||
        x >= this.#maximumFrameDimension ||
        y >= this.#maximumFrameDimension) {
      return null;
    }
    return {x, y};
  }

  #callPointer(type, point) {
    const module = this.#getModule();
    if (!module || typeof module.ccall !== "function" || !point) {
      return false;
    }
    try {
      return module.ccall(
          "chromium_wasm_browser_host_pointer", "number",
          ["number", "number", "number", "number"],
          [type, point.x, point.y, 0]) === 1;
    } catch (error) {
      this.#recordFatal(`host pointer ABI call failed: ${String(error)}`);
      return false;
    }
  }

  #callPointerExit() {
    const module = this.#getModule();
    if (!module || typeof module.ccall !== "function") {
      return false;
    }
    try {
      return module.ccall(
          "chromium_wasm_browser_host_pointer_exit", "number", [], []) === 1;
    } catch (error) {
      this.#recordFatal(`host pointer-exit ABI call failed: ${String(error)}`);
      return false;
    }
  }

  #releasePointerCapture(pointerId) {
    if (typeof this.#canvas.hasPointerCapture !== "function" ||
        typeof this.#canvas.releasePointerCapture !== "function") {
      return;
    }
    try {
      if (this.#canvas.hasPointerCapture(pointerId)) {
        this.#canvas.releasePointerCapture(pointerId);
      }
    } catch (_) {
      // A browser can implicitly release capture during blur or pointerup.
      // The native Ozone release remains the authoritative cleanup action.
    }
  }

  // Releases only an already accepted trusted primary press. It is not a
  // host-generated Chrome command and never invents a coordinate.
  releaseActivePointer(reason = "cleanup") {
    const pointerId = this.#activePointerId;
    const point = this.#lastPoint;
    this.#activePointerId = null;
    this.#lastPoint = null;
    this.#hoverActive = false;
    if (pointerId === null) {
      return false;
    }

    let accepted = false;
    if (point) {
      accepted = this.#callPointer(POINTER_UP, point);
    }
    this.#releasePointerCapture(pointerId);
    this.#recordEvent({
      type: "cleanup",
      trusted: true,
      cancelable: false,
      pointerType: "mouse",
      primary: true,
      pointerId,
      button: 0,
      buttons: 0,
      accepted,
      defaultPrevented: false,
      x: point?.x ?? null,
      y: point?.y ?? null,
      reason,
    });
    return accepted;
  }

  #handlePointerEvent(type, event) {
    const record = this.#eventRecord(type, event);
    if (!record.trusted) {
      this.#reject(record, "untrusted-dom-event");
      return;
    }
    // These PointerEvents are consumed only when their outer-page default can
    // be suppressed after Chrome accepted the same record. Non-cancelable
    // records cannot meet that ownership rule.
    if (!record.cancelable) {
      this.#reject(record, "noncancelable-dom-event");
      return;
    }
    if (record.pointerType !== "mouse" || !record.primary ||
        event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      this.#reject(record, "unsupported-pointer");
      return;
    }
    if (!Number.isSafeInteger(record.pointerId)) {
      this.#reject(record, "invalid-pointer-id");
      return;
    }

    const activePointerId = this.#activePointerId;
    if (type === "down") {
      if (activePointerId !== null || record.button !== 0 ||
          record.buttons !== 1) {
        this.#reject(record, "invalid-button-state");
        return;
      }
    } else if (type === "move") {
      if (activePointerId === null) {
        if (record.buttons !== 0) {
          this.#reject(record, "invalid-button-state");
          return;
        }
      } else if (record.pointerId !== activePointerId ||
                 record.buttons !== 1) {
        this.#reject(record, "invalid-active-pointer");
        return;
      }
    } else if (type === "up") {
      if (record.pointerId !== activePointerId || record.button !== 0 ||
          (record.buttons & 1) !== 0) {
        this.#reject(record, "invalid-active-pointer");
        return;
      }
    } else {
      this.#reject(record, "unsupported-pointer-event");
      return;
    }

    const point = this.#canvasPointForPointerEvent(event);
    if (!point) {
      this.#reject(record, "outside-canvas-bounds");
      return;
    }
    record.x = point.x;
    record.y = point.y;
    if (type === "down") {
      this.#canvas.focus({preventScroll: true});
      if (document.activeElement !== this.#canvas ||
          typeof this.#canvas.setPointerCapture !== "function") {
        this.#reject(record, "canvas-capture-unavailable");
        return;
      }
      try {
        this.#canvas.setPointerCapture(record.pointerId);
      } catch (_) {
        this.#reject(record, "canvas-capture-rejected");
        return;
      }
    }

    const abiType = type === "move" ? POINTER_MOVE :
        type === "down" ? POINTER_DOWN : POINTER_UP;
    if (!this.#callPointer(abiType, point)) {
      if (type === "down") {
        this.#releasePointerCapture(record.pointerId);
      }
      this.#reject(record, "chrome-abi-rejected");
      return;
    }

    if (type === "down") {
      this.#activePointerId = record.pointerId;
      this.#lastPoint = point;
      this.#hoverActive = false;
    } else if (type === "move") {
      this.#lastPoint = point;
      this.#hoverActive = this.#activePointerId === null;
    } else {
      this.#activePointerId = null;
      this.#lastPoint = point;
      // A completed primary press leaves Ozone at an in-canvas, unpressed
      // point. A following trusted pointerleave must be allowed to clear its
      // hover target even if the outer browser emitted no separate move.
      this.#hoverActive = true;
      this.#releasePointerCapture(record.pointerId);
    }

    // This prevents outer-page selection and context handling only after an
    // exact trusted primary record was accepted by the Chrome-owned bridge.
    event.preventDefault();
    record.accepted = true;
    record.defaultPrevented = event.defaultPrevented === true;
    if (!record.defaultPrevented) {
      record.reason = "default-prevention-failed";
    }
    this.#recordEvent(record);
  }

  #handlePointerLeave(event) {
    const record = this.#eventRecord("exit", event);
    if (!record.trusted) {
      this.#reject(record, "untrusted-dom-event");
      return;
    }
    // PointerEvent `pointerleave` is intentionally non-cancelable in web
    // browsers. Unlike down/move/up it has no outer-page action to suppress,
    // so accepting a trusted native exit does not weaken the cancelable-event
    // ownership rule above.
    if (record.pointerType !== "mouse" || !record.primary ||
        event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
        !Number.isSafeInteger(record.pointerId) || record.button !== -1 ||
        record.buttons !== 0) {
      this.#reject(record, "unsupported-pointer-exit");
      return;
    }
    if (this.#activePointerId !== null || !this.#hoverActive ||
        typeof this.#canvas.hasPointerCapture !== "function") {
      this.#reject(record, "no-unpressed-hover");
      return;
    }
    try {
      if (this.#canvas.hasPointerCapture(record.pointerId)) {
        this.#reject(record, "captured-pointer");
        return;
      }
    } catch (_) {
      this.#reject(record, "capture-state-unavailable");
      return;
    }
    if (!this.#callPointerExit()) {
      this.#reject(record, "chrome-exit-abi-rejected");
      return;
    }
    this.#hoverActive = false;
    this.#lastPoint = null;
    record.accepted = true;
    this.#recordEvent(record);
  }

  #isTrustedActivePointerCleanupEvent(event) {
    return event?.isTrusted === true && event.pointerType === "mouse" &&
        event.isPrimary === true && Number.isSafeInteger(Number(event.pointerId)) &&
        Number(event.pointerId) === this.#activePointerId;
  }

  attach() {
    if (this.#attached) {
      return;
    }
    this.#onPointerDown = (event) => this.#handlePointerEvent("down", event);
    this.#onPointerMove = (event) => this.#handlePointerEvent("move", event);
    this.#onPointerUp = (event) => this.#handlePointerEvent("up", event);
    this.#onPointerCancel = (event) => {
      if (this.#isTrustedActivePointerCleanupEvent(event)) {
        this.releaseActivePointer("pointer-cancel");
      }
    };
    this.#onPointerLeave = (event) => this.#handlePointerLeave(event);
    this.#onCanvasBlur = () => this.releaseActivePointer("canvas-blur");
    this.#onWindowBlur = () => this.releaseActivePointer("window-blur");
    this.#onVisibilityChange = () => {
      if (document.hidden) {
        this.releaseActivePointer("document-hidden");
      }
    };
    this.#onLostPointerCapture = (event) => {
      if (this.#isTrustedActivePointerCleanupEvent(event)) {
        this.releaseActivePointer("lost-pointer-capture");
      }
    };
    this.#canvas.addEventListener("pointerdown", this.#onPointerDown);
    this.#canvas.addEventListener("pointermove", this.#onPointerMove);
    this.#canvas.addEventListener("pointerup", this.#onPointerUp);
    this.#canvas.addEventListener("pointercancel", this.#onPointerCancel);
    this.#canvas.addEventListener("pointerleave", this.#onPointerLeave);
    this.#canvas.addEventListener("blur", this.#onCanvasBlur);
    this.#canvas.addEventListener(
        "lostpointercapture", this.#onLostPointerCapture);
    window.addEventListener("blur", this.#onWindowBlur);
    document.addEventListener("visibilitychange", this.#onVisibilityChange);
    this.#attached = true;
  }

  detach() {
    if (!this.#attached) {
      return;
    }
    this.releaseActivePointer("teardown");
    this.#canvas.removeEventListener("pointerdown", this.#onPointerDown);
    this.#canvas.removeEventListener("pointermove", this.#onPointerMove);
    this.#canvas.removeEventListener("pointerup", this.#onPointerUp);
    this.#canvas.removeEventListener("pointercancel", this.#onPointerCancel);
    this.#canvas.removeEventListener("pointerleave", this.#onPointerLeave);
    this.#canvas.removeEventListener("blur", this.#onCanvasBlur);
    this.#canvas.removeEventListener(
        "lostpointercapture", this.#onLostPointerCapture);
    window.removeEventListener("blur", this.#onWindowBlur);
    document.removeEventListener("visibilitychange", this.#onVisibilityChange);
    this.#attached = false;
  }
}

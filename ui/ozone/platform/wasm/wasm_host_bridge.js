// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Emscripten proxies this import synchronously from Chromium's application
// pthread to the browser main thread. Never retain a HEAPU8 view: memory growth
// can replace it after this call returns.
mergeInto(LibraryManager.library, {
  $ChromiumWasmHostBridge: {
    version: 1,
    maximumCanvasDimension: 16384,
    maximumFrameBytes: 64 * 1024 * 1024,
    imageData: null,
    context: null,
    readiness: {
      shellReady: false,
      surfaceReady: false,
      firstVisuallyNonEmptyPaint: false,
    },
    bridge() {
      const bridge = globalThis['__chromiumWasmHostBridgeV1'];
      if (!bridge || bridge.protocol !== 1) {
        return null;
      }
      return bridge;
    },
    reportReadiness(update) {
      Object.assign(this.readiness, update);
      const bridge = this.bridge();
      if (!bridge || typeof bridge.reportReadiness !== 'function') {
        return false;
      }
      bridge.reportReadiness({
        protocol: this.version,
        ...this.readiness,
      });
      return true;
    },
  },

  chromium_wasm_present_frame__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_present_frame__proxy: 'sync',
  chromium_wasm_present_frame: (
      bridgeVersion, pixels, width, height, stride, frameId, timestampMs) => {
    try {
      if (bridgeVersion !== ChromiumWasmHostBridge.version ||
          !Number.isSafeInteger(pixels) || pixels < 0 ||
          !Number.isSafeInteger(width) || width <= 0 ||
          width > ChromiumWasmHostBridge.maximumCanvasDimension ||
          !Number.isSafeInteger(height) || height <= 0 ||
          height > ChromiumWasmHostBridge.maximumCanvasDimension ||
          !Number.isSafeInteger(stride) || stride !== width * 4 ||
          !Number.isSafeInteger(frameId) || frameId <= 0 ||
          !Number.isFinite(timestampMs) || timestampMs < 0) {
        return 0;
      }

      const byteLength = stride * height;
      const end = pixels + byteLength;
      if (!Number.isSafeInteger(byteLength) ||
          byteLength > ChromiumWasmHostBridge.maximumFrameBytes ||
          !Number.isSafeInteger(end) || end < pixels || end > HEAPU8.length) {
        return 0;
      }

      const canvas = Module['canvas'];
      if (!(canvas instanceof HTMLCanvasElement)) {
        return 0;
      }

      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        ChromiumWasmHostBridge.context = null;
        ChromiumWasmHostBridge.imageData = null;
      }

      if (!ChromiumWasmHostBridge.context) {
        ChromiumWasmHostBridge.context =
            canvas.getContext('2d', {alpha: false});
      }
      const context = ChromiumWasmHostBridge.context;
      if (!context) {
        return 0;
      }

      if (!ChromiumWasmHostBridge.imageData ||
          ChromiumWasmHostBridge.imageData.width !== width ||
          ChromiumWasmHostBridge.imageData.height !== height) {
        ChromiumWasmHostBridge.imageData =
            context.createImageData(width, height);
      }

      // This copies into JavaScript-owned storage before returning.
      ChromiumWasmHostBridge.imageData.data.set(
          HEAPU8.subarray(pixels, end));
      context.putImageData(ChromiumWasmHostBridge.imageData, 0, 0);

      const detail = {
        bridgeVersion,
        frameId,
        timestampMs,
        width,
        height,
        stride,
      };
      Module['chromiumWasmLastFrame'] = detail;
      const onFrame = Module['onChromiumWasmFrame'];
      if (typeof onFrame === 'function') {
        onFrame(detail);
      }
      const hostBridge = ChromiumWasmHostBridge.bridge();
      if (!hostBridge || typeof hostBridge.reportFrame !== 'function') {
        return 0;
      }
      hostBridge.reportFrame({
        protocol: ChromiumWasmHostBridge.version,
        id: frameId,
        width,
        height,
        timestampMs,
      });
      if (!ChromiumWasmHostBridge.reportReadiness({surfaceReady: true})) {
        return 0;
      }
      globalThis.dispatchEvent(
          new CustomEvent('chromium-wasm-frame', {detail}));
      return 1;
    } catch (error) {
      console.error('CHROMIUM_WASM_M3:PRESENT_FAILED', error);
      return 0;
    }
  },

  chromium_wasm_report_readiness__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_report_readiness__proxy: 'sync',
  chromium_wasm_report_readiness: (
      shellReady, surfaceReady, firstVisuallyNonEmptyPaint) => {
    const update = {};
    if (shellReady >= 0) {
      update.shellReady = shellReady === 1;
    }
    if (surfaceReady >= 0) {
      update.surfaceReady = surfaceReady === 1;
    }
    if (firstVisuallyNonEmptyPaint >= 0) {
      update.firstVisuallyNonEmptyPaint =
          firstVisuallyNonEmptyPaint === 1;
    }
    return ChromiumWasmHostBridge.reportReadiness(update) ? 1 : 0;
  },

  chromium_wasm_report_ozone_focus_state__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_report_ozone_focus_state__proxy: 'sync',
  chromium_wasm_report_ozone_focus_state: (
      keyboardTargetPresent, active) => {
    if ((keyboardTargetPresent !== 0 && keyboardTargetPresent !== 1) ||
        (active !== 0 && active !== 1)) {
      return 0;
    }
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportOzoneFocusState !== 'function') {
      return 0;
    }
    bridge.reportOzoneFocusState({
      protocol: ChromiumWasmHostBridge.version,
      keyboardTargetPresent: keyboardTargetPresent === 1,
      active: active === 1,
    });
    return 1;
  },

  chromium_wasm_report_ozone_text_input_state__deps: [
    '$ChromiumWasmHostBridge',
  ],
  chromium_wasm_report_ozone_text_input_state__proxy: 'sync',
  chromium_wasm_report_ozone_text_input_state: (
      focusedClientPresent, editable, canComposeInline) => {
    if ((focusedClientPresent !== 0 && focusedClientPresent !== 1) ||
        (editable !== 0 && editable !== 1) ||
        (canComposeInline !== 0 && canComposeInline !== 1) ||
        (canComposeInline === 1 && editable !== 1) ||
        (editable === 1 && focusedClientPresent !== 1)) {
      return 0;
    }
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportOzoneTextInputState !== 'function') {
      return 0;
    }
    bridge.reportOzoneTextInputState({
      protocol: ChromiumWasmHostBridge.version,
      focusedClientPresent: focusedClientPresent === 1,
      editable: editable === 1,
      canComposeInline: canComposeInline === 1,
    });
    return 1;
  },

  chromium_wasm_report_ozone_text_input_delivery__deps: [
    '$ChromiumWasmHostBridge',
  ],
  chromium_wasm_report_ozone_text_input_delivery__proxy: 'sync',
  chromium_wasm_report_ozone_text_input_delivery: (
      action, sessionId, sequence, accepted) => {
    if (!Number.isSafeInteger(action) || action < 1 || action > 3 ||
        !Number.isSafeInteger(sessionId) || sessionId < 1 ||
        !Number.isSafeInteger(sequence) || sequence < 1 ||
        (accepted !== 0 && accepted !== 1)) {
      return 0;
    }
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportOzoneTextInputDelivery !== 'function') {
      return 0;
    }
    bridge.reportOzoneTextInputDelivery({
      protocol: ChromiumWasmHostBridge.version,
      action,
      sessionId,
      sequence,
      accepted: accepted === 1,
    });
    return 1;
  },

  chromium_wasm_report_navigation__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_report_navigation__proxy: 'sync',
  chromium_wasm_report_navigation: () => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportNavigation !== 'function') {
      return 0;
    }
    bridge.reportNavigation({
      protocol: ChromiumWasmHostBridge.version,
      committed: true,
      scheme: 'data',
    });
    return 1;
  },

  chromium_wasm_report_page_probe__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_page_probe__proxy: 'sync',
  chromium_wasm_report_page_probe: (probe) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportPageProbe !== 'function') {
      return 0;
    }
    bridge.reportPageProbe(UTF8ToString(probe));
    return 1;
  },

  chromium_wasm_report_fatal__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_fatal__proxy: 'sync',
  chromium_wasm_report_fatal: (message) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportFatal !== 'function') {
      return 0;
    }
    bridge.reportFatal(UTF8ToString(message));
    return 1;
  },

  chromium_wasm_report_process_exit__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_report_process_exit__proxy: 'sync',
  chromium_wasm_report_process_exit: (exitCode) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportProcessExit !== 'function') {
      return 0;
    }
    bridge.reportProcessExit({
      protocol: ChromiumWasmHostBridge.version,
      exitCode,
    });
    return 1;
  },
});

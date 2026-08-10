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
    isExactCursorType(cursorType) {
      // CSS has no exact analogue for directional panning, DnD decoration,
      // or no-resize cursor families. The host may expose a diagnostic
      // fallback, but C++ must not treat that visual approximation as success.
      return !(
        (cursorType >= 20 && cursorType <= 28) || cursorType >= 43
      );
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

  // This one-shot test-only witness is deliberately separate from readiness:
  // readiness FVP is sticky, while the controlled HTTPS smoke emits this only
  // from its observer after the exact target document has committed and
  // reached first visually non-empty paint.
  chromium_wasm_report_controlled_https_target_fvp__deps: [
    '$ChromiumWasmHostBridge',
  ],
  chromium_wasm_report_controlled_https_target_fvp__proxy: 'sync',
  chromium_wasm_report_controlled_https_target_fvp: () => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportControlledHttpsTargetFvp !== 'function') {
      return 0;
    }
    bridge.reportControlledHttpsTargetFvp({
      protocol: ChromiumWasmHostBridge.version,
    });
    return 1;
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

  chromium_wasm_report_ozone_cursor__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_report_ozone_cursor__proxy: 'sync',
  chromium_wasm_report_ozone_cursor: (cursorType) => {
    // CursorType is a stable mojom enum. Do not accept an arbitrary host
    // string: Wasm only transfers the native cursor type and the host owns the
    // CSS mapping.
    if (!Number.isSafeInteger(cursorType) || cursorType < -1 ||
        cursorType > 53) {
      return 0;
    }
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportOzoneCursor !== 'function') {
      return 0;
    }
    const delivered = bridge.reportOzoneCursor({
      protocol: ChromiumWasmHostBridge.version,
      cursorType,
    });
    return delivered === true &&
        ChromiumWasmHostBridge.isExactCursorType(cursorType) ? 1 : 0;
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

  // Chrome's address-field committed-text ABI is intentionally not folded
  // into M4's composition delivery protocol. It uses one fixed action/session
  // and reports only the opaque request key plus native acceptance; the host
  // never receives the focused client, focus token, text, or selection.
  chromium_wasm_report_ozone_browser_text_input_delivery__deps: [
    '$ChromiumWasmHostBridge',
  ],
  chromium_wasm_report_ozone_browser_text_input_delivery__proxy: 'sync',
  chromium_wasm_report_ozone_browser_text_input_delivery: (
      action, sessionId, sequence, accepted) => {
    if (action !== 4 || sessionId !== 0 ||
        !Number.isSafeInteger(sequence) || sequence < 1 ||
        (accepted !== 0 && accepted !== 1)) {
      return 0;
    }
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportOzoneBrowserTextInputDelivery !== 'function') {
      return 0;
    }
    bridge.reportOzoneBrowserTextInputDelivery({
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

  // The dedicated M5 test executable reports its fixed HTTPS fixture through
  // a separate bridge entry. Keeping this distinct from the production
  // data:-navigation reports makes the test-only trust and navigation lane
  // auditable at the host boundary.
  chromium_wasm_report_m5_navigation__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_report_m5_navigation__proxy: 'sync',
  chromium_wasm_report_m5_navigation: () => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportM5Navigation !== 'function') {
      return 0;
    }
    bridge.reportM5Navigation({
      protocol: ChromiumWasmHostBridge.version,
      committed: true,
      scheme: 'https',
    });
    return 1;
  },

  chromium_wasm_report_m5_navigation_error__deps: ['$ChromiumWasmHostBridge'],
  chromium_wasm_report_m5_navigation_error__proxy: 'sync',
  chromium_wasm_report_m5_navigation_error: (netError) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportM5NavigationError !== 'function') {
      return 0;
    }
    bridge.reportM5NavigationError({
      protocol: ChromiumWasmHostBridge.version,
      committed: false,
      scheme: 'https',
      netError,
    });
    return 1;
  },

  // The controlled M5 executable owns an in-process DevToolsAgentHost client.
  // It reports a bounded, parsed Network-domain summary rather than exposing
  // raw CDP frames to the page or opening an unsupported debugging socket.
  chromium_wasm_report_m5_devtools_network__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_devtools_network__proxy: 'sync',
  chromium_wasm_report_m5_devtools_network: (report) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportM5DevToolsNetwork !== 'function') {
      return 0;
    }
    bridge.reportM5DevToolsNetwork(UTF8ToString(report));
    return 1;
  },

  // Attachment downloads have a browser-owned completion path. The native
  // recorder emits only its fixed, redacted DownloadManager summary here;
  // never let a URL, filesystem path, GUID, or raw response header cross the
  // Wasm host boundary.
  chromium_wasm_report_m5_download__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_download__proxy: 'sync',
  chromium_wasm_report_m5_download: (report) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportM5Download !== 'function') {
      return 0;
    }
    bridge.reportM5Download(UTF8ToString(report));
    return 1;
  },

  // The local controlled preflight lane is separate from both the broad M5
  // fixture and the external/public probe. Its native side owns the fixed
  // document destination, so no URL crosses this bridge.
  chromium_wasm_report_m5_controlled_preflight_devtools_network__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_controlled_preflight_devtools_network__proxy: 'sync',
  chromium_wasm_report_m5_controlled_preflight_devtools_network: (report) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportM5ControlledPreflightDevToolsNetwork !== 'function') {
      return 0;
    }
    bridge.reportM5ControlledPreflightDevToolsNetwork(UTF8ToString(report));
    return 1;
  },

  chromium_wasm_report_m5_controlled_preflight_navigation__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_controlled_preflight_navigation__proxy: 'sync',
  chromium_wasm_report_m5_controlled_preflight_navigation: (
      responseCode, protocol, protocolLength) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportM5ControlledPreflightNavigation !== 'function' ||
        !Number.isSafeInteger(protocolLength) || protocolLength < 0 ||
        protocolLength > 128) {
      return 0;
    }
    bridge.reportM5ControlledPreflightNavigation({
      protocol: ChromiumWasmHostBridge.version,
      committed: true,
      scheme: 'https',
      responseCode,
      connectionProtocol: UTF8ToString(protocol, protocolLength),
    });
    return 1;
  },

  chromium_wasm_report_m5_controlled_preflight_navigation_error__deps: [
    '$ChromiumWasmHostBridge',
  ],
  chromium_wasm_report_m5_controlled_preflight_navigation_error__proxy: 'sync',
  chromium_wasm_report_m5_controlled_preflight_navigation_error: (netError) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportM5ControlledPreflightNavigationError !== 'function') {
      return 0;
    }
    bridge.reportM5ControlledPreflightNavigationError({
      protocol: ChromiumWasmHostBridge.version,
      committed: false,
      scheme: 'https',
      netError,
    });
    return 1;
  },

  // The external/public M5 lane uses the same in-process protocol boundary,
  // but exposes only a fixed, redacted document and WISP-completion summary.
  chromium_wasm_report_m5_public_devtools_network__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_public_devtools_network__proxy: 'sync',
  chromium_wasm_report_m5_public_devtools_network: (report) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportM5PublicDevToolsNetwork !== 'function') {
      return 0;
    }
    bridge.reportM5PublicDevToolsNetwork(UTF8ToString(report));
    return 1;
  },

  // The opt-in public M5 lane is distinct from the controlled fixture: its
  // test-only C++ target supplies a canonical URL at runtime and reports the
  // resulting navigation metadata. The host compares that URL internally and
  // never puts it into the result or diagnostics payload.
  chromium_wasm_report_m5_public_navigation__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_public_navigation__proxy: 'sync',
  chromium_wasm_report_m5_public_navigation: (
      url, responseCode, protocol, protocolLength) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportM5PublicNavigation !== 'function' ||
        !Number.isSafeInteger(protocolLength) || protocolLength < 0 ||
        protocolLength > 128) {
      return 0;
    }
    bridge.reportM5PublicNavigation({
      protocol: ChromiumWasmHostBridge.version,
      committed: true,
      scheme: 'https',
      url: UTF8ToString(url),
      responseCode,
      connectionProtocol: UTF8ToString(protocol, protocolLength),
    });
    return 1;
  },

  chromium_wasm_report_m5_public_navigation_error__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_public_navigation_error__proxy: 'sync',
  chromium_wasm_report_m5_public_navigation_error: (url, netError) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportM5PublicNavigationError !== 'function') {
      return 0;
    }
    bridge.reportM5PublicNavigationError({
      protocol: ChromiumWasmHostBridge.version,
      committed: false,
      scheme: 'https',
      url: UTF8ToString(url),
      netError,
    });
    return 1;
  },

  // The M5 active mixed-content proof first commits a single exact HTTP
  // control page. Keep its reports separate from both the HTTPS M5 fixture
  // and normal data: navigation so it cannot broaden the host boundary.
  chromium_wasm_report_m5_plaintext_http_control_navigation__deps: [
    '$ChromiumWasmHostBridge',
  ],
  chromium_wasm_report_m5_plaintext_http_control_navigation__proxy: 'sync',
  chromium_wasm_report_m5_plaintext_http_control_navigation: () => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportM5PlaintextHttpControlNavigation !== 'function') {
      return 0;
    }
    bridge.reportM5PlaintextHttpControlNavigation({
      protocol: ChromiumWasmHostBridge.version,
      committed: true,
      scheme: 'http',
    });
    return 1;
  },

  chromium_wasm_report_m5_plaintext_http_control_navigation_error__deps: [
    '$ChromiumWasmHostBridge',
  ],
  chromium_wasm_report_m5_plaintext_http_control_navigation_error__proxy:
      'sync',
  chromium_wasm_report_m5_plaintext_http_control_navigation_error:
      (netError) => {
        const bridge = ChromiumWasmHostBridge.bridge();
        if (!bridge || typeof bridge.reportM5PlaintextHttpControlNavigationError !==
            'function') {
          return 0;
        }
        bridge.reportM5PlaintextHttpControlNavigationError({
          protocol: ChromiumWasmHostBridge.version,
          committed: false,
          scheme: 'http',
          netError,
        });
        return 1;
      },

  chromium_wasm_report_m5_page_probe__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_page_probe__proxy: 'sync',
  chromium_wasm_report_m5_page_probe: (probe) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge || typeof bridge.reportM5PageProbe !== 'function') {
      return 0;
    }
    bridge.reportM5PageProbe(UTF8ToString(probe));
    return 1;
  },

  chromium_wasm_report_m5_plaintext_http_control_page_probe__deps: [
    '$ChromiumWasmHostBridge',
    '$UTF8ToString',
  ],
  chromium_wasm_report_m5_plaintext_http_control_page_probe__proxy: 'sync',
  chromium_wasm_report_m5_plaintext_http_control_page_probe: (probe) => {
    const bridge = ChromiumWasmHostBridge.bridge();
    if (!bridge ||
        typeof bridge.reportM5PlaintextHttpControlPageProbe !== 'function') {
      return 0;
    }
    bridge.reportM5PlaintextHttpControlPageProbe(UTF8ToString(probe));
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

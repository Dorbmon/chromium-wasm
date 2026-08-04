// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const HOST_PROTOCOL = 1;
const M3_CASE = "content_shell_m3";
const M4_CASE = "ozone_pointer_m4";
const M4_SELECT_CASE = "ozone_select_m4";
const M4_RESIZE_CASE = "ozone_resize_m4";
const M4_DPR_CASE = "ozone_dpr_m4";
const M4_CONTEXT_MENU_CASE = "ozone_context_menu_m4";
const M4_TOOLTIP_CASE = "ozone_tooltip_m4";
const M4_WHEEL_CASE = "ozone_wheel_m4";
const M4_KEYBOARD_CASE = "ozone_keyboard_m4";
const M4_PRINTABLE_KEY_CASE = "ozone_printable_key_m4";
const M4_BACKSPACE_CASE = "ozone_backspace_m4";
const M4_SELECTION_CASE = "ozone_selection_m4";
const M4_PRIMARY_PASTE_CASE = "ozone_primary_paste_m4";
const M4_COPY_PASTE_CASE = "ozone_copy_paste_m4";
const M4_FOCUS_CASE = "ozone_focus_m4";
const M4_FOCUS_RETENTION_CASE = "ozone_focus_retention_m4";
const M4_IME_BRIDGE_CASE = "ozone_ime_bridge_m4";
const M5_NETWORK_CASE = "wisp_network_m5";
const M4_FIXTURE = "chromium-wasm-m4-ozone-pointer-v2";
const M4_SELECT_FIXTURE = "chromium-wasm-m4-ozone-select-v1";
const M4_RESIZE_FIXTURE = "chromium-wasm-m4-ozone-resize-v1";
const M4_DPR_FIXTURE = "chromium-wasm-m4-ozone-pointer-v2";
const M4_CONTEXT_MENU_FIXTURE =
  "chromium-wasm-m4-ozone-context-menu-v1";
const M4_TOOLTIP_FIXTURE = "chromium-wasm-m4-ozone-tooltip-v1";
const M4_WHEEL_FIXTURE = "chromium-wasm-m4-ozone-wheel-v1";
const M4_KEYBOARD_FIXTURE = "chromium-wasm-m4-ozone-keyboard-v2";
const M4_PRINTABLE_KEY_FIXTURE =
  "chromium-wasm-m4-ozone-printable-key-v2";
const M4_BACKSPACE_FIXTURE = "chromium-wasm-m4-ozone-backspace-v2";
const M4_SELECTION_FIXTURE = "chromium-wasm-m4-ozone-selection-v1";
const M4_PRIMARY_PASTE_FIXTURE =
  "chromium-wasm-m4-ozone-primary-paste-v1";
const M4_COPY_PASTE_FIXTURE = "chromium-wasm-m4-ozone-copy-paste-v1";
const M4_FOCUS_FIXTURE = "chromium-wasm-m4-ozone-focus-v1";
const M4_FOCUS_RETENTION_FIXTURE =
  "chromium-wasm-m4-ozone-focus-retention-v1";
const M4_IME_BRIDGE_FIXTURE = "chromium-wasm-m4-ozone-ime-bridge-v1";
const M5_NETWORK_FIXTURE = "chromium-wasm-m5-network-v1";
const M5_NETWORK_TEST_HOSTNAME = "a.test";
const M5_NETWORK_TEST_PATH_PREFIX = "/m5/";
const M5_PLAINTEXT_HTTP_CONTROL_PATH = "/m5/plaintext-control";
const M5_NAVIGATION_PHASE = Object.freeze({
  NONE: "none",
  PLAINTEXT_HTTP_CONTROL: "plaintext-http-control",
  HTTPS_FIXTURE: "https-fixture",
  TLS_NAME_MISMATCH: "tls-name-mismatch",
});
// net::ERR_CERT_COMMON_NAME_INVALID. Keep the test evidence tied to
// Chromium's native certificate verifier, not a JavaScript fetch failure.
const M5_TLS_NAME_MISMATCH_NET_ERROR = -200;
const M4_KEYBOARD_DOM_CODE = "ArrowDown";
const M4_PRINTABLE_KEY_DOM_CODE = "KeyA";
const M4_PRINTABLE_KEY_DOM_KEY = "a";
const M4_PRINTABLE_KEY_B_DOM_CODE = "KeyB";
const M4_PRINTABLE_KEY_B_DOM_KEY = "b";
const M4_BACKSPACE_DOM_CODE = "Backspace";
const M4_BACKSPACE_DOM_KEY = "Backspace";
const M4_CONTROL_LEFT_DOM_CODE = "ControlLeft";
const M4_CONTROL_LEFT_DOM_KEY = "Control";
const M4_COPY_DOM_CODE = "KeyC";
const M4_COPY_DOM_KEY = "c";
const M4_PASTE_DOM_CODE = "KeyV";
const M4_PASTE_DOM_KEY = "v";
const M4_COPY_PASTE_SOURCE_VALUE = "COPY";
const M4_COPY_PASTE_DECOY_VALUE = "DECOY";
const M4_CURSOR_TYPE_HAND = 2;
const M4_SELECT_OPTION_RGBA = Object.freeze([250, 0, 250, 255]);
const M4_SELECT_MINIMUM_POPUP_PIXELS = 4096;
// This is the opaque row painted by WasmContextMenuOverlay.  It is a stable
// visual protocol between the small native overlay and its browser smoke; the
// smoke derives the Copy click point from the resulting compositor pixels.
const M4_CONTEXT_MENU_COPY_ROW_RGBA = Object.freeze([0, 87, 184, 255]);
const M4_CONTEXT_MENU_COPY_ROW_WIDTH = 160;
const M4_CONTEXT_MENU_COPY_ROW_HEIGHT = 40;
const M4_CONTEXT_MENU_MINIMUM_COPY_ROW_PIXELS = 5000;
// This is the complete opaque native tooltip visual protocol. It is painted
// by WasmTooltipController, rather than by a host-page DOM overlay. The smoke
// scans every expected pixel so the title path proves both presence and
// disappearance of the Aura child surface.
const M4_TOOLTIP_BACKGROUND_RGBA = Object.freeze([32, 33, 36, 255]);
const M4_TOOLTIP_BORDER_RGBA = Object.freeze([95, 99, 104, 255]);
const M4_TOOLTIP_INK_RGBA = Object.freeze([255, 255, 255, 255]);
const M4_TOOLTIP_WIDTH = 110;
const M4_TOOLTIP_HEIGHT = 24;
const M4_TOOLTIP_BACKGROUND_PIXELS = 1952;
const M4_TOOLTIP_BORDER_PIXELS = 264;
const M4_TOOLTIP_INK_PIXELS = 424;
const M4_TOOLTIP_CURSOR_OFFSET_X = 12;
const M4_TOOLTIP_CURSOR_OFFSET_Y = 18;
const M4_TOOLTIP_CLEAR_QUIESCENCE_MS = 750;
const M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS = 250;
const M4_RESIZE_NARROW_WIDTH = 640;
const M4_RESIZE_NARROW_HEIGHT = 480;
const M4_DPR_SCALE = 2;
const FIXTURE_FONT_MARKER = "__M3_AHEM_WOFF2_BASE64__";
const REQUIRED_RUNTIME_MS = 3000;
const REQUIRED_TIMER_TICKS = 60;
const REQUIRED_ANIMATION_FRAMES = 30;
const MAXIMUM_TIMER_GAP_MS = 250;
const DEFAULT_RUNTIME_REGISTRATION_TIMEOUT_MS = 15000;
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 15000;
const DEFAULT_WIDTH = 800;
const DEFAULT_HEIGHT = 600;
const POST_INPUT_REDRAW_WIDTH = DEFAULT_WIDTH - 1;
const WASM_PAGE_BYTES = 64 * 1024;
const MAXIMUM_WHEEL_DELTA = 0x7fffffff;
const MAXIMUM_IME_PROXY_TEXT_UNITS = 64 * 1024;
const MAXIMUM_IME_PROXY_TEXT_BYTES = MAXIMUM_IME_PROXY_TEXT_UNITS * 3;
const WISP_CONFIGURATION_VERSION = 1;
const WISP_OPTION_RANGES = Object.freeze({
  maxStreams: Object.freeze([1, 4096, 1024]),
  maxHostnameBytes: Object.freeze([1, 253, 253]),
  maxDataFrameBytes: Object.freeze([1, 1024 * 1024, 16 * 1024]),
  maxInboundStreamBytes: Object.freeze([1, 64 * 1024 * 1024, 1024 * 1024]),
  maxOutboundStreamBytes: Object.freeze([1, 64 * 1024 * 1024, 1024 * 1024]),
  maxInboundBytes: Object.freeze([1, 256 * 1024 * 1024, 16 * 1024 * 1024]),
  maxOutboundBytes: Object.freeze([1, 256 * 1024 * 1024, 16 * 1024 * 1024]),
  maxWebSocketBufferedBytes: Object.freeze([
    6, 64 * 1024 * 1024, 4 * 1024 * 1024,
  ]),
  maxIncomingPacketBytes: Object.freeze([
    5, 64 * 1024 * 1024, 1024 * 1024 + 5,
  ]),
  handshakeTimeoutMs: Object.freeze([1000, 120 * 1000, 15 * 1000]),
  streamOpenTimeoutMs: Object.freeze([1000, 120 * 1000, 30 * 1000]),
});
const M4_IME_TEXT_ACTION = Object.freeze({
  setComposition: 1,
  confirmComposition: 2,
  clearComposition: 3,
});
const UTF8_ENCODER = new TextEncoder();

let activeHost = null;
const pendingBridgeReports = [];

function expectedM4KeyboardKey(code) {
  switch (code) {
    case M4_KEYBOARD_DOM_CODE:
      return M4_KEYBOARD_DOM_CODE;
    case M4_PRINTABLE_KEY_DOM_CODE:
      return M4_PRINTABLE_KEY_DOM_KEY;
    case M4_PRINTABLE_KEY_B_DOM_CODE:
      return M4_PRINTABLE_KEY_B_DOM_KEY;
    case M4_BACKSPACE_DOM_CODE:
      return M4_BACKSPACE_DOM_KEY;
    case M4_CONTROL_LEFT_DOM_CODE:
      return M4_CONTROL_LEFT_DOM_KEY;
    case M4_COPY_DOM_CODE:
      return M4_COPY_DOM_KEY;
    case M4_PASTE_DOM_CODE:
      return M4_PASTE_DOM_KEY;
    default:
      return null;
  }
}

function ozoneCursorDescriptor(cursorType) {
  // Values intentionally mirror ui::mojom::CursorType. The C++ bridge only
  // sends this scalar; JavaScript owns the browser-native CSS representation.
  switch (cursorType) {
    case -1:  // kNull
    case 0:   // kPointer
      return {cssCursor: "default", exact: true};
    case 1:   // kCross
      return {cssCursor: "crosshair", exact: true};
    case 2:   // kHand
      return {cssCursor: "pointer", exact: true};
    case 3:   // kIBeam
      return {cssCursor: "text", exact: true};
    case 4:   // kWait
      return {cssCursor: "wait", exact: true};
    case 5:   // kHelp
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
    case 20:  // kMiddlePanning
    case 21:  // kEastPanning
    case 22:  // kNorthPanning
    case 23:  // kNorthEastPanning
    case 24:  // kNorthWestPanning
    case 25:  // kSouthPanning
    case 26:  // kSouthEastPanning
    case 27:  // kSouthWestPanning
    case 28:  // kWestPanning
    case 43:  // kMiddlePanningVertical
    case 44:  // kMiddlePanningHorizontal
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
    case 45:  // kCustom
      // A custom Blink cursor includes a bitmap and hotspot. The scalar bridge
      // cannot preserve that data, so make the fallback visible in diagnostics
      // instead of claiming that the custom image was rendered.
      return {cssCursor: "default", exact: false};
    case 46:  // kDndNone
      return {cssCursor: "no-drop", exact: false};
    case 47:  // kDndMove
      return {cssCursor: "move", exact: false};
    case 48:  // kDndCopy
      return {cssCursor: "copy", exact: false};
    case 49:  // kDndLink
      return {cssCursor: "alias", exact: false};
    case 50:  // kEastWestNoResize
    case 51:  // kNorthSouthNoResize
    case 52:  // kNorthEastSouthWestNoResize
    case 53:  // kNorthWestSouthEastNoResize
      return {cssCursor: "not-allowed", exact: false};
    default:
      return null;
  }
}

function hasM4PointerLinkHover(pageProbe, x, y) {
  const trace = pageProbe?.pointerMoveTrace;
  return Array.isArray(trace) && trace.some((record) =>
    record?.type === "pointermove" && record?.trusted === true &&
    record?.targetId === "m4-link" && record?.clientX === x &&
    record?.clientY === y);
}

function hasM4NativeLinkNavigation(pageProbe) {
  const loadCountBefore = pageProbe?.navigationFrameLoadCountBeforeActivation;
  return pageProbe?.clickDefaultPrevented === false &&
    Number.isSafeInteger(loadCountBefore) && loadCountBefore >= 1 &&
    pageProbe?.navigationFrameLoadCount === loadCountBefore + 1 &&
    pageProbe?.navigationFrameLastLoadTrusted === true;
}

function hasM4SelectOpenerTrace(pageProbe, x, y) {
  const trace = pageProbe?.openerEventTrace;
  if (!Array.isArray(trace)) {
    return false;
  }
  return ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].every(
      (type) => trace.some((record) =>
        record?.type === type && record?.trusted === true &&
        record?.targetId === "select-target" && record?.clientX === x &&
        record?.clientY === y));
}

function scanM4SelectPopupOption(canvas, selectBounds) {
  if (!(canvas instanceof HTMLCanvasElement) || !selectBounds) {
    throw new Error("M4 select popup scan requires a canvas and select bounds");
  }
  for (const field of ["left", "top", "right", "bottom"]) {
    if (!Number.isSafeInteger(selectBounds[field])) {
      throw new Error("M4 select bounds are invalid");
    }
  }
  const context = globalThis.ChromiumWasmHostBridge?.context ??
      canvas.getContext("2d", {alpha: false});
  if (!context || typeof context.getImageData !== "function") {
    throw new Error("M4 select popup scan has no 2D canvas context");
  }
  const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
  const pixels = imageData.data;
  let pixelCount = 0;
  let minX = canvas.width;
  let minY = canvas.height;
  let maxX = -1;
  let maxY = -1;
  const [red, green, blue, alpha] = M4_SELECT_OPTION_RGBA;
  for (let y = 0; y < canvas.height; ++y) {
    for (let x = 0; x < canvas.width; ++x) {
      const offset = (y * canvas.width + x) * 4;
      if (pixels[offset] !== red || pixels[offset + 1] !== green ||
          pixels[offset + 2] !== blue || pixels[offset + 3] !== alpha) {
        continue;
      }
      ++pixelCount;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  const width = maxX - minX + 1;
  const height = maxY - minY + 1;
  if (
    pixelCount < M4_SELECT_MINIMUM_POPUP_PIXELS ||
    width < selectBounds.right - selectBounds.left - 8 || height < 36 ||
    minY <= selectBounds.bottom || minX > selectBounds.left + 8 ||
    maxX < selectBounds.right - 8
  ) {
    return null;
  }
  return {
    rgba: Array.from(M4_SELECT_OPTION_RGBA),
    pixelCount,
    minX,
    minY,
    maxX,
    maxY,
    targetX: Math.floor((minX + maxX) / 2),
    // The fixture has exactly three options. The midpoint of the rendered
    // option stack is the second option and is derived from actual pixels.
    targetY: Math.floor((minY + maxY) / 2),
  };
}

function scanM4ContextMenuCopyRow(canvas) {
  if (!(canvas instanceof HTMLCanvasElement)) {
    throw new Error("M4 context-menu scan requires a canvas");
  }
  const context = globalThis.ChromiumWasmHostBridge?.context ??
      canvas.getContext("2d", {alpha: false});
  if (!context || typeof context.getImageData !== "function") {
    throw new Error("M4 context-menu scan has no 2D canvas context");
  }
  const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
  const pixels = imageData.data;
  const [red, green, blue, alpha] = M4_CONTEXT_MENU_COPY_ROW_RGBA;
  let pixelCount = 0;
  let minX = canvas.width;
  let minY = canvas.height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < canvas.height; ++y) {
    for (let x = 0; x < canvas.width; ++x) {
      const offset = (y * canvas.width + x) * 4;
      if (pixels[offset] !== red || pixels[offset + 1] !== green ||
          pixels[offset + 2] !== blue || pixels[offset + 3] !== alpha) {
        continue;
      }
      ++pixelCount;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  const width = maxX - minX + 1;
  const height = maxY - minY + 1;
  if (
    pixelCount < M4_CONTEXT_MENU_MINIMUM_COPY_ROW_PIXELS ||
    width !== M4_CONTEXT_MENU_COPY_ROW_WIDTH ||
    height !== M4_CONTEXT_MENU_COPY_ROW_HEIGHT
  ) {
    return null;
  }
  return {
    rgba: Array.from(M4_CONTEXT_MENU_COPY_ROW_RGBA),
    pixelCount,
    minX,
    minY,
    maxX,
    maxY,
    targetX: Math.floor((minX + maxX) / 2),
    targetY: Math.floor((minY + maxY) / 2),
  };
}

const M4_TOOLTIP_GLYPHS = Object.freeze({
  A: "010101111101101",
  I: "111010010010111",
  L: "100100100100111",
  M: "101111111101101",
  O: "111101101101111",
  P: "110101110100100",
  S: "111100111001111",
  T: "111010010010010",
  W: "101101101111101",
});

function matchesM4TooltipRgba(pixels, offset, rgba) {
  return pixels[offset] === rgba[0] && pixels[offset + 1] === rgba[1] &&
    pixels[offset + 2] === rgba[2] && pixels[offset + 3] === rgba[3];
}

function m4TooltipInkMask(label) {
  const inkPixels = new Set();
  const originX = 8;
  const originY = 7;
  const glyphScale = 2;
  const glyphWidth = 3;
  const glyphHeight = 5;
  const glyphSpacing = 2;
  for (let glyphIndex = 0; glyphIndex < label.length; ++glyphIndex) {
    const glyph = M4_TOOLTIP_GLYPHS[label[glyphIndex]];
    if (!glyph) {
      continue;
    }
    for (let row = 0; row < glyphHeight; ++row) {
      for (let column = 0; column < glyphWidth; ++column) {
        if (glyph[row * glyphWidth + column] !== "1") {
          continue;
        }
        const x = originX +
          glyphIndex * (glyphWidth * glyphScale + glyphSpacing) +
          column * glyphScale;
        const y = originY + row * glyphScale;
        for (let scaledY = 0; scaledY < glyphScale; ++scaledY) {
          for (let scaledX = 0; scaledX < glyphScale; ++scaledX) {
            inkPixels.add(`${x + scaledX},${y + scaledY}`);
          }
        }
      }
    }
  }
  return inkPixels;
}

function m4TooltipCanvasPixels(canvas) {
  if (!(canvas instanceof HTMLCanvasElement)) {
    throw new Error("M4 tooltip scan requires a canvas");
  }
  const context = globalThis.ChromiumWasmHostBridge?.context ??
      canvas.getContext("2d", {alpha: false});
  if (!context || typeof context.getImageData !== "function") {
    throw new Error("M4 tooltip scan has no 2D canvas context");
  }
  return context.getImageData(0, 0, canvas.width, canvas.height).data;
}

function countM4TooltipBackgroundPixels(canvas) {
  const pixels = m4TooltipCanvasPixels(canvas);
  let count = 0;
  for (let offset = 0; offset < pixels.length; offset += 4) {
    if (matchesM4TooltipRgba(pixels, offset, M4_TOOLTIP_BACKGROUND_RGBA)) {
      ++count;
    }
  }
  return count;
}

function scanM4TooltipOverlay(canvas, anchorX, anchorY, label) {
  const inkMask = m4TooltipInkMask(label);
  const pixels = m4TooltipCanvasPixels(canvas);
  let backgroundPixels = 0;
  let minX = canvas.width;
  let minY = canvas.height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < canvas.height; ++y) {
    for (let x = 0; x < canvas.width; ++x) {
      const offset = (y * canvas.width + x) * 4;
      if (!matchesM4TooltipRgba(
          pixels, offset, M4_TOOLTIP_BACKGROUND_RGBA)) {
        continue;
      }
      ++backgroundPixels;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (backgroundPixels !== M4_TOOLTIP_BACKGROUND_PIXELS) {
    return null;
  }
  const expectedMinX = anchorX + M4_TOOLTIP_CURSOR_OFFSET_X;
  const expectedMinY = anchorY + M4_TOOLTIP_CURSOR_OFFSET_Y;
  const width = M4_TOOLTIP_WIDTH;
  const height = M4_TOOLTIP_HEIGHT;
  const expectedMaxX = expectedMinX + width - 1;
  const expectedMaxY = expectedMinY + height - 1;
  // The scan above locates only the interior background. The one-pixel
  // native border is deliberately a different color, so validate the
  // background's interior bounds before scanning the complete overlay.
  if (
    minX !== expectedMinX + 1 || minY !== expectedMinY + 1 ||
    maxX !== expectedMaxX - 1 || maxY !== expectedMaxY - 1
  ) {
    return null;
  }

  let borderPixels = 0;
  let inkPixels = 0;
  for (let localY = 0; localY < height; ++localY) {
    for (let localX = 0; localX < width; ++localX) {
      const offset = ((expectedMinY + localY) * canvas.width +
                      expectedMinX + localX) * 4;
      const isBorder = localX === 0 || localY === 0 ||
        localX === width - 1 || localY === height - 1;
      const isInk = inkMask.has(`${localX},${localY}`);
      if (isBorder) {
        if (!matchesM4TooltipRgba(pixels, offset, M4_TOOLTIP_BORDER_RGBA)) {
          return null;
        }
        ++borderPixels;
      } else if (isInk) {
        if (!matchesM4TooltipRgba(pixels, offset, M4_TOOLTIP_INK_RGBA)) {
          return null;
        }
        ++inkPixels;
      } else if (!matchesM4TooltipRgba(
          pixels, offset, M4_TOOLTIP_BACKGROUND_RGBA)) {
        return null;
      }
    }
  }
  if (
    borderPixels !== M4_TOOLTIP_BORDER_PIXELS ||
    inkPixels !== M4_TOOLTIP_INK_PIXELS ||
    inkMask.size !== M4_TOOLTIP_INK_PIXELS
  ) {
    return null;
  }
  return {
    backgroundRgba: Array.from(M4_TOOLTIP_BACKGROUND_RGBA),
    borderRgba: Array.from(M4_TOOLTIP_BORDER_RGBA),
    inkRgba: Array.from(M4_TOOLTIP_INK_RGBA),
    backgroundPixels,
    borderPixels,
    inkPixels,
    minX: expectedMinX,
    minY: expectedMinY,
    maxX: expectedMaxX,
    maxY: expectedMaxY,
    width,
    height,
    anchorX: expectedMinX,
    anchorY: expectedMinY,
    label,
  };
}

function isM4ResizeCardRect(rect) {
  return rect &&
    ["left", "top", "width", "height"].every((field) =>
      Number.isSafeInteger(rect[field])) &&
    rect.width > 0 && rect.height > 0;
}

function hasM4ResizeGeometry(geometry, width, height, layoutMode) {
  if (!geometry || typeof geometry !== "object") {
    return false;
  }
  const expectedGridWidth = width - 64;
  if (
    geometry.innerWidth !== width || geometry.innerHeight !== height ||
    geometry.documentClientWidth !== width ||
    geometry.documentClientHeight !== height ||
    geometry.screenWidth !== width || geometry.screenHeight !== height ||
    geometry.screenAvailWidth !== width ||
    geometry.screenAvailHeight !== height || geometry.devicePixelRatio !== 1 ||
    geometry.narrowMedia !== (layoutMode === "narrow") ||
    geometry.layoutMode !== layoutMode || geometry.gridWidth !== expectedGridWidth
  ) {
    return false;
  }
  const first = geometry.firstCard;
  const second = geometry.secondCard;
  if (!isM4ResizeCardRect(first) || !isM4ResizeCardRect(second) ||
      first.left !== 32 || second.left < first.left ||
      first.height !== 120 || second.height !== 120) {
    return false;
  }
  if (layoutMode === "wide") {
    return geometry.gridColumns === 2 && first.top === second.top &&
      first.width === second.width &&
      first.width * 2 + 16 === expectedGridWidth &&
      second.left === first.left + first.width + 16;
  }
  return geometry.gridColumns === 1 && second.left === first.left &&
    first.width === expectedGridWidth && second.width === expectedGridWidth &&
    second.top === first.top + first.height + 16;
}

function hasM4ResizeEvent(event, sequence, width, height, layoutMode) {
  return event?.sequence === sequence && event?.type === "resize" &&
    event?.trusted === true &&
    hasM4ResizeGeometry(event?.geometry, width, height, layoutMode);
}

function hasM4ResizeCall(call, width, height) {
  return call?.ok === true && call?.width === width &&
    call?.height === height && call?.devicePixelRatio === 1;
}

function hasM4DprGeometry(geometry, width, height, devicePixelRatio) {
  if (!geometry || typeof geometry !== "object") {
    return false;
  }
  return geometry.innerWidth === width && geometry.innerHeight === height &&
    geometry.documentClientWidth === width &&
    geometry.documentClientHeight === height &&
    geometry.screenWidth === width && geometry.screenHeight === height &&
    geometry.screenAvailWidth === width && geometry.screenAvailHeight === height &&
    geometry.devicePixelRatio === devicePixelRatio &&
    geometry.twoDppx === (devicePixelRatio === M4_DPR_SCALE);
}

function m4DprCanvasSnapshot(canvas) {
  return {
    clientWidth: canvas.clientWidth,
    clientHeight: canvas.clientHeight,
    width: canvas.width,
    height: canvas.height,
    styleWidth: canvas.style.width,
    styleHeight: canvas.style.height,
  };
}

function hasM4DprCanvasSnapshot(snapshot, width, height, devicePixelRatio) {
  return snapshot?.clientWidth === width &&
    snapshot?.clientHeight === height &&
    snapshot?.width === width * devicePixelRatio &&
    snapshot?.height === height * devicePixelRatio &&
    snapshot?.styleWidth === `${width}px` &&
    snapshot?.styleHeight === `${height}px`;
}

function hasM4DprResizeCall(call, width, height, devicePixelRatio) {
  return call?.ok === true && call?.width === width &&
    call?.height === height && call?.devicePixelRatio === devicePixelRatio &&
    call?.physicalWidth === width * devicePixelRatio &&
    call?.physicalHeight === height * devicePixelRatio;
}

function isM4CopyPasteShortcutCode(code) {
  return code === M4_COPY_DOM_CODE || code === M4_PASTE_DOM_CODE;
}

function matchesM4BackspaceOuterKeyRecord(
    record, type, code, key, repeat = false) {
  const modifiers = record?.modifiers;
  return record?.type === type &&
    record?.code === code &&
    record?.key === key &&
    record?.trusted === true &&
    record?.queued === true &&
    record?.repeat === repeat &&
    record?.isComposing === false &&
    record?.canvasFocused === true &&
    record?.pointerActivated === true &&
    record?.defaultPrevented === true &&
    modifiers?.alt === false && modifiers?.control === false &&
    modifiers?.meta === false && modifiers?.shift === false &&
    Number.isSafeInteger(record?.frameIdBefore) && record.frameIdBefore >= 1;
}

function matchesM4BackspaceInnerKeyRecord(
    record, type, code, key, repeat = false) {
  return record?.type === type &&
    record?.trusted === true &&
    record?.code === code &&
    record?.key === key &&
    record?.repeat === repeat &&
    record?.isComposing === false &&
    record?.defaultPrevented === false &&
    record?.targetId === "editable-target";
}

function matchesM4BackspaceTextRecord(record, type, inputType, data) {
  return record?.type === type &&
    record?.trusted === true &&
    record?.inputType === inputType &&
    record?.data === data &&
    record?.isComposing === false &&
    record?.targetId === "editable-target";
}

function matchesM4BackspaceKeyPrefix(records, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, code, key, repeat = false], index) =>
          matchesM4BackspaceOuterKeyRecord(
              records[index], type, code, key, repeat));
}

function matchesM4BackspaceInnerKeyTrace(records, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, code, key, repeat = false], index) =>
          matchesM4BackspaceInnerKeyRecord(
              records[index], type, code, key, repeat));
}

function matchesM4BackspaceTextTrace(records, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, inputType, data], index) =>
          matchesM4BackspaceTextRecord(
              records[index], type, inputType, data));
}

function hasM4BackspaceNoComposition(pageProbe) {
  const counts = pageProbe?.compositionEventCounts;
  return counts?.compositionstart === 0 && counts?.compositionupdate === 0 &&
    counts?.compositionend === 0;
}

function hasM4BackspaceHeldCode(keyboard) {
  return Array.isArray(keyboard?.pressedCodes) &&
    keyboard.pressedCodes.length === 1 &&
    keyboard.pressedCodes[0] === M4_BACKSPACE_DOM_CODE;
}

function matchesM4SelectionQueuedPointerRecord(record, type, x, y) {
  return record?.type === type &&
    record?.trusted === true &&
    record?.queued === true &&
    Number.isSafeInteger(record?.sequence) && record.sequence >= 1 &&
    Number.isSafeInteger(record?.x) && record.x === x &&
    Number.isSafeInteger(record?.y) && record.y === y &&
    Number.isSafeInteger(record?.frameIdBefore) && record.frameIdBefore >= 1;
}

function matchesM4SelectionQueuedPointerTrace(records, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, x, y], index) =>
          matchesM4SelectionQueuedPointerRecord(records[index], type, x, y) &&
          records[index].sequence === index + 1);
}

function matchesM4SelectionInnerEvent(
    record, prefix, type, x, y, button, buttons) {
  return record?.type === `${prefix}${type}` &&
    record?.trusted === true &&
    record?.button === button &&
    record?.buttons === buttons &&
    record?.clientX === x &&
    record?.clientY === y &&
    record?.targetId === "editable-target" &&
    record?.defaultPrevented === false;
}

function matchesM4SelectionInnerTrace(records, prefix, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, x, y, button, buttons], index) =>
          matchesM4SelectionInnerEvent(
              records[index], prefix, type, x, y, button, buttons));
}

function hasM4SelectionSilentTextInputEvents(events) {
  return events?.beforeinputCount === 0 && events?.inputCount === 0 &&
    events?.compositionstartCount === 0 &&
    events?.compositionupdateCount === 0 &&
    events?.compositionendCount === 0;
}

function hasM4SelectionBasePageEvidence(pageProbe) {
  return pageProbe?.activeElementId === "editable-target" &&
    Number.isSafeInteger(pageProbe?.activationCount) &&
    pageProbe.activationCount >= 1 && pageProbe?.clickTrusted === true &&
    pageProbe?.focusCount >= 1 && pageProbe?.focusTrusted === true &&
    pageProbe?.value === "WASM" &&
    hasM4SelectionSilentTextInputEvents(pageProbe?.textInputEvents);
}

function hasM4SelectionBaseActivationEvidence(pageProbe) {
  return hasM4SelectionBasePageEvidence(pageProbe) &&
    pageProbe.activationCount === 1;
}

function hasM4SelectionCollapsedNativeSelection(pageProbe) {
  return Number.isSafeInteger(pageProbe?.selectionStart) &&
    Number.isSafeInteger(pageProbe?.selectionEnd) &&
    pageProbe.selectionStart === pageProbe.selectionEnd &&
    hasM4SelectionForwardOrNeutralDirection(pageProbe) &&
    pageProbe?.selectedText === "";
}

function hasM4SelectionActivationEvidence(pageProbe) {
  return hasM4SelectionBaseActivationEvidence(pageProbe) &&
    hasM4SelectionCollapsedNativeSelection(pageProbe);
}

function hasM4SelectionForwardOrNeutralDirection(pageProbe) {
  return pageProbe?.selectionDirection === "none" ||
    pageProbe?.selectionDirection === "forward";
}

function hasM4SelectionFinalPageEvidence(pageProbe, innerTraces) {
  const selectionActivity = pageProbe?.selectionActivity;
  return hasM4SelectionBasePageEvidence(pageProbe) &&
    pageProbe?.selectionStart === 0 && pageProbe?.selectionEnd === 4 &&
    hasM4SelectionForwardOrNeutralDirection(pageProbe) &&
    pageProbe?.selectedText === "WASM" &&
    pageProbe?.resultText === "TEXT SELECTED" &&
    selectionActivity?.count >= 1 && selectionActivity?.trusted === true &&
    selectionActivity?.nonCollapsed === true &&
    selectionActivity?.trustedNonCollapsed === true &&
    selectionActivity?.selectCount >= 1 &&
    selectionActivity?.selectTrusted === true &&
    selectionActivity?.selectionChangeCount >= 1 &&
    selectionActivity?.selectionChangeTrusted === true &&
    matchesM4SelectionInnerTrace(
        pageProbe?.mouseEventTrace, "mouse", innerTraces.mouse) &&
    matchesM4SelectionInnerTrace(
        pageProbe?.pointerEventTrace, "pointer", innerTraces.pointer);
}

function matchesM4TooltipQueuedPointerRecord(record, x, y) {
  return record?.type === "move" && record?.trusted === true &&
    record?.queued === true && record?.button === -1 &&
    record?.buttons === 0 && record?.canvasFocused === true &&
    Number.isSafeInteger(record?.sequence) && record.sequence >= 1 &&
    Number.isSafeInteger(record?.x) && record.x === x &&
    Number.isSafeInteger(record?.y) && record.y === y &&
    Number.isSafeInteger(record?.frameIdBefore) && record.frameIdBefore >= 1;
}

function matchesM4TooltipQueuedPointerTrace(records, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(([x, y], index) =>
      matchesM4TooltipQueuedPointerRecord(records[index], x, y) &&
      records[index].sequence === index + 1);
}

function matchesM4TooltipQueuedPointerExit(record, sequence) {
  return record?.type === "exit" && record?.trusted === true &&
    record?.queued === true && record?.button === -1 &&
    record?.buttons === 0 && record?.canvasFocused === true &&
    record?.sequence === sequence &&
    Number.isSafeInteger(record?.frameIdBefore) && record.frameIdBefore >= 1 &&
    !Object.hasOwn(record, "x") && !Object.hasOwn(record, "y");
}

function matchesM4TooltipInnerMove(record, prefix, targetId, x, y) {
  const button = prefix === "mouse" ? 0 : -1;
  return record?.type === `${prefix}move` && record?.trusted === true &&
    record?.button === button && record?.buttons === 0 &&
    record?.clientX === x && record?.clientY === y &&
    record?.targetId === targetId && record?.defaultPrevented === false;
}

function hasM4TooltipInnerTrace(pageProbe, expected) {
  const hasTrace = (records, prefix) => Array.isArray(records) &&
    records.length === expected.length && expected.every(
        ([targetId, x, y], index) => matchesM4TooltipInnerMove(
            records[index], prefix, targetId, x, y));
  return hasTrace(pageProbe?.mouseTrace, "mouse") &&
    hasTrace(pageProbe?.pointerTrace, "pointer");
}

function hasM4TooltipInnerMouseExit(pageProbe, targetId, x, y) {
  const trace = pageProbe?.mouseLeaveTrace;
  const record = Array.isArray(trace) && trace.length === 1 ? trace[0] : null;
  return record?.type === "mouseleave" && record?.trusted === true &&
    record?.button === 0 && record?.buttons === 0 &&
    record?.clientX === x && record?.clientY === y &&
    record?.targetId === targetId && record?.defaultPrevented === false;
}

function m4TooltipInnerTraceGapMs(pageProbe, firstIndex, secondIndex) {
  const traces = [pageProbe?.mouseTrace, pageProbe?.pointerTrace];
  let maximumGapMs = 0;
  for (const trace of traces) {
    const firstTimestamp = trace?.[firstIndex]?.observedAtMs;
    const secondTimestamp = trace?.[secondIndex]?.observedAtMs;
    if (!Number.isSafeInteger(firstTimestamp) || firstTimestamp < 0 ||
        !Number.isSafeInteger(secondTimestamp) ||
        secondTimestamp < firstTimestamp) {
      return null;
    }
    maximumGapMs = Math.max(maximumGapMs, secondTimestamp - firstTimestamp);
  }
  return maximumGapMs;
}

function hasM4TooltipPageIdentity(pageProbe) {
  return pageProbe?.protocol === HOST_PROTOCOL &&
    pageProbe?.fixture === M4_TOOLTIP_FIXTURE && pageProbe?.fontReady === true &&
    pageProbe?.ready === true && pageProbe?.tooltipTitle === "WASM TOOLTIP" &&
    pageProbe?.confirmTitle === "SWAM TOOLTIP" &&
    pageProbe?.clearTitle === null;
}

function hasM4TooltipTrustedMoveResult(pageProbe, moveCount) {
  return pageProbe?.resultText === `TRUSTED MOVE ${moveCount}`;
}

function matchesM4PrimaryPasteQueuedPointerRecord(
    record, type, x, y, button, buttons) {
  return record?.type === type &&
    record?.trusted === true &&
    record?.queued === true &&
    record?.button === button &&
    record?.buttons === buttons &&
    Number.isSafeInteger(record?.sequence) && record.sequence >= 1 &&
    Number.isSafeInteger(record?.x) && record.x === x &&
    Number.isSafeInteger(record?.y) && record.y === y &&
    Number.isSafeInteger(record?.frameIdBefore) && record.frameIdBefore >= 1;
}

function matchesM4PrimaryPasteQueuedPointerTrace(records, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, x, y, button, buttons], index) =>
          matchesM4PrimaryPasteQueuedPointerRecord(
              records[index], type, x, y, button, buttons) &&
          records[index].sequence === index + 1);
}

function matchesM4PrimaryPasteInnerEvent(
    record, prefix, type, button, buttons, targetId) {
  return record?.type === `${prefix}${type}` &&
    record?.trusted === true &&
    record?.button === button &&
    record?.buttons === buttons &&
    record?.targetId === targetId && record?.defaultPrevented === false;
}

function hasM4PrimaryPasteSourceSelection(pageProbe) {
  const selectionActivity = pageProbe?.sourceSelectionActivity;
  return pageProbe?.activeElementId === "source-target" &&
    // Selection can be observed before Blink dispatches the drag's trailing
    // click. The final paste proof below requires that exact second click.
    Number.isSafeInteger(pageProbe?.sourceActivationCount) &&
    pageProbe.sourceActivationCount >= 1 &&
    pageProbe?.sourceClickTrusted === true &&
    pageProbe?.sourceFocusCount >= 1 &&
    pageProbe?.sourceFocusTrusted === true &&
    pageProbe?.sourceValue === "WASM" &&
    pageProbe?.sourceSelectionStart === 0 &&
    pageProbe?.sourceSelectionEnd === 4 &&
    (pageProbe?.sourceSelectionDirection === "none" ||
      pageProbe?.sourceSelectionDirection === "forward") &&
    pageProbe?.sourceSelectedText === "WASM" &&
    selectionActivity?.count >= 1 && selectionActivity?.trusted === true &&
    selectionActivity?.nonCollapsed === true &&
    selectionActivity?.trustedNonCollapsed === true &&
    selectionActivity?.selectCount >= 1 &&
    selectionActivity?.selectTrusted === true &&
    selectionActivity?.selectionChangeCount >= 1 &&
    selectionActivity?.selectionChangeTrusted === true &&
    pageProbe?.sourceTextInputEvents?.beforeinputCount === 0 &&
    pageProbe?.sourceTextInputEvents?.inputCount === 0 &&
    pageProbe?.sourceTextInputEvents?.compositionstartCount === 0 &&
    pageProbe?.sourceTextInputEvents?.compositionupdateCount === 0 &&
    pageProbe?.sourceTextInputEvents?.compositionendCount === 0;
}

function hasM4PrimaryPasteInnerSourceEvents(pageProbe) {
  const mouse = pageProbe?.sourceMouseEventTrace;
  const pointer = pageProbe?.sourcePointerEventTrace;
  return Array.isArray(mouse) && Array.isArray(pointer) &&
    mouse.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "mouse", "down", 0, 1, "source-target")) &&
    mouse.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "mouse", "up", 0, 0, "source-target")) &&
    pointer.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "pointer", "down", 0, 1, "source-target")) &&
    pointer.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "pointer", "up", 0, 0, "source-target"));
}

function hasM4PrimaryPasteInnerPasteEvents(pageProbe) {
  const mouse = pageProbe?.pasteMouseEventTrace;
  const pointer = pageProbe?.pastePointerEventTrace;
  const paste = pageProbe?.pasteEventTrace;
  const text = pageProbe?.pasteTextInputTrace;
  return Array.isArray(mouse) && Array.isArray(pointer) &&
    Array.isArray(paste) && paste.length === 1 &&
    paste[0]?.type === "paste" && paste[0]?.trusted === true &&
    paste[0]?.targetId === "paste-target" &&
    paste[0]?.defaultPrevented === false && Array.isArray(text) &&
    text.length === 2 &&
    text.every((record) => record?.trusted === true &&
      record?.inputType === "insertFromPaste" && record?.data === "WASM" &&
      record?.isComposing === false && record?.targetId === "paste-target") &&
    text[0]?.type === "beforeinput" && text[1]?.type === "input" &&
    mouse.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "mouse", "down", 1, 4, "paste-target")) &&
    mouse.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "mouse", "up", 1, 0, "paste-target")) &&
    pointer.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "pointer", "down", 1, 4, "paste-target")) &&
    pointer.some((record) => matchesM4PrimaryPasteInnerEvent(
        record, "pointer", "up", 1, 0, "paste-target"));
}

function hasM4PrimaryPasteFinalPageEvidence(pageProbe) {
  return pageProbe?.activeElementId === "paste-target" &&
    pageProbe?.sourceValue === "WASM" &&
    pageProbe?.sourceActivationCount === 2 &&
    pageProbe?.pasteActivationCount === 0 &&
    pageProbe?.pasteClickTrusted === false &&
    pageProbe?.pasteAuxClickCount === 1 &&
    pageProbe?.pasteAuxClickTrusted === true &&
    pageProbe?.pasteFocusCount >= 1 &&
    pageProbe?.pasteFocusTrusted === true &&
    pageProbe?.pasteValue === "WASM" &&
    pageProbe?.pasteSelectionStart === 4 && pageProbe?.pasteSelectionEnd === 4 &&
    pageProbe?.resultText === "PRIMARY SELECTION PASTED" &&
    hasM4PrimaryPasteInnerSourceEvents(pageProbe) &&
    hasM4PrimaryPasteInnerPasteEvents(pageProbe);
}

function hasM4ContextMenuNativeSelection(pageProbe) {
  const selection = pageProbe?.sourceSelection;
  const activity = pageProbe?.selectionActivity;
  return pageProbe?.activeElementId === "context-source" &&
    pageProbe?.sourceValue === "MENU" && selection?.start === 0 &&
    selection?.end === 4 && selection?.text === "MENU" &&
    (selection?.direction === "none" || selection?.direction === "forward") &&
    activity?.count >= 1 && activity?.trusted === true &&
    activity?.nonCollapsed === true && activity?.trustedNonCollapsed === true &&
    activity?.selectCount >= 1 && activity?.selectionChangeCount >= 1;
}

function hasM4ContextMenuInnerSecondaryEvents(pageProbe, x, y) {
  const contextMenus = pageProbe?.contextMenuTrace;
  const pointer = pageProbe?.sourcePointerTrace;
  const mouse = pageProbe?.sourceMouseTrace;
  const hasSecondaryEvent = (records, prefix, type, buttons) =>
    Array.isArray(records) && records.some((record) =>
      record?.type === `${prefix}${type}` && record?.trusted === true &&
      record?.button === 2 && record?.buttons === buttons &&
      record?.clientX === x && record?.clientY === y &&
      record?.targetId === "context-source" &&
      record?.defaultPrevented === false);
  const context = Array.isArray(contextMenus) ? contextMenus[0] : null;
  const selection = context?.selection;
  return Array.isArray(contextMenus) && contextMenus.length === 1 &&
    context?.type === "contextmenu" && context?.trusted === true &&
    // Chrome reports the right-button mask on the contextmenu event emitted
    // for the trusted CDP secondary-button sequence. Preserve that observed
    // native event state rather than normalizing it in the host bridge.
    context?.button === 2 && context?.buttons === 2 &&
    context?.clientX === x && context?.clientY === y &&
    context?.targetId === "context-source" &&
    context?.defaultPrevented === false && selection?.start === 0 &&
    selection?.end === 4 && selection?.text === "MENU" &&
    hasSecondaryEvent(pointer, "pointer", "down", 2) &&
    hasSecondaryEvent(pointer, "pointer", "up", 0) &&
    hasSecondaryEvent(mouse, "mouse", "down", 2) &&
    hasSecondaryEvent(mouse, "mouse", "up", 0);
}

function hasM4ContextMenuOuterSuppression(records, x, y) {
  if (!Array.isArray(records) || records.length !== 1) {
    return false;
  }
  const record = records[0];
  return record?.sequence === 1 && record?.trusted === true &&
    record?.button === 2 && record?.buttons === 2 && record?.x === x &&
    record?.y === y && record?.acceptedPointer === true &&
    record?.defaultPrevented === true;
}

function hasM4ContextMenuCopyEvidence(pageProbe) {
  const copies = pageProbe?.copyEventTrace;
  const copy = Array.isArray(copies) ? copies[0] : null;
  const selection = copy?.selection;
  return Array.isArray(copies) && copies.length === 1 &&
    copy?.type === "copy" && copy?.trusted === true &&
    copy?.targetId === "context-source" && copy?.defaultPrevented === false &&
    selection?.start === 0 && selection?.end === 4 &&
    selection?.text === "MENU" && pageProbe?.sourceValue === "MENU";
}

function hasM4ContextMenuPasteEvidence(pageProbe) {
  const paste = pageProbe?.pasteEventTrace;
  const text = pageProbe?.pasteTextInputTrace;
  return pageProbe?.activeElementId === "context-paste" &&
    pageProbe?.pasteValue === "MENU" && pageProbe?.pasteSelectionStart === 4 &&
    pageProbe?.pasteSelectionEnd === 4 &&
    pageProbe?.resultText === "NATIVE MENU COPY PASTED" &&
    pageProbe?.contextCopied === true && Array.isArray(paste) &&
    paste.length === 1 && paste[0]?.type === "paste" &&
    paste[0]?.trusted === true && paste[0]?.targetId === "context-paste" &&
    paste[0]?.defaultPrevented === false && paste[0]?.text === "MENU" &&
    Array.isArray(text) && text.length === 2 && text[0]?.type === "beforeinput" &&
    text[1]?.type === "input" && text.every((record) =>
      record?.trusted === true && record?.inputType === "insertFromPaste" &&
      record?.data === "MENU" && record?.isComposing === false &&
      record?.targetId === "context-paste");
}

function matchesM4CopyPasteQueuedKeyRecord(
    record, type, code, key, control) {
  const modifiers = record?.modifiers;
  return record?.type === type &&
    record?.code === code &&
    record?.key === key &&
    record?.trusted === true &&
    record?.queued === true &&
    record?.repeat === false &&
    record?.isComposing === false &&
    record?.canvasFocused === true &&
    record?.pointerActivated === true &&
    record?.defaultPrevented === true &&
    modifiers?.alt === false && modifiers?.control === control &&
    modifiers?.meta === false && modifiers?.shift === false &&
    Number.isSafeInteger(record?.frameIdBefore) && record.frameIdBefore >= 1;
}

function matchesM4CopyPasteQueuedKeyTrace(
    records, expectedRecords, sequenceStart = 1) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, code, key, control], index) =>
          matchesM4CopyPasteQueuedKeyRecord(
              records[index], type, code, key, control) &&
          records[index].sequence === sequenceStart + index);
}

function matchesM4ArrowDownQueuedKeyRecord(record, type, repeat) {
  const modifiers = record?.modifiers;
  return record?.type === type && record?.code === M4_KEYBOARD_DOM_CODE &&
    record?.key === "ArrowDown" && record?.trusted === true &&
    record?.queued === true && record?.repeat === repeat &&
    record?.isComposing === false && record?.canvasFocused === true &&
    record?.pointerActivated === true && record?.defaultPrevented === true &&
    modifiers?.alt === false && modifiers?.control === false &&
    modifiers?.meta === false && modifiers?.shift === false &&
    Number.isSafeInteger(record?.frameIdBefore) && record.frameIdBefore >= 1;
}

function hasM4ArrowDownRepeatQueuedTrace(records) {
  const expected = [
    ["down", false],
    ["down", true],
    ["up", false],
  ];
  return Array.isArray(records) && records.length === expected.length &&
    expected.every(([type, repeat], index) =>
      matchesM4ArrowDownQueuedKeyRecord(records[index], type, repeat) &&
      records[index].sequence === index + 1);
}

function matchesM4ArrowDownInnerKeyRecord(record, type, repeat) {
  return record?.type === type && record?.trusted === true &&
    record?.code === M4_KEYBOARD_DOM_CODE && record?.key === "ArrowDown" &&
    record?.repeat === repeat && record?.isComposing === false &&
    record?.defaultPrevented === false &&
    record?.targetId === "keyboard-target";
}

function hasM4ArrowDownRepeatInnerTrace(records) {
  const expected = [
    ["keydown", false],
    ["keydown", true],
    ["keyup", false],
  ];
  return Array.isArray(records) && records.length === expected.length &&
    expected.every(([type, repeat], index) =>
      matchesM4ArrowDownInnerKeyRecord(records[index], type, repeat));
}

function hasM4CopyPasteBareShortcutRejection(keyboard) {
  const rejected = keyboard?.rejectedRecords;
  const expected = [
    ["down", "UNSUPPORTED_SHORTCUT_STATE"],
    ["up", "UNMATCHED_UP"],
  ];
  return keyboard?.receivedCount === expected.length &&
    keyboard?.trustedCount === expected.length &&
    keyboard?.queuedCount === 0 && keyboard?.pressedCodes?.length === 0 &&
    Array.isArray(rejected) && rejected.length === expected.length &&
    expected.every(([type, reason], index) => {
      const record = rejected[index];
      const modifiers = record?.modifiers;
      return record?.type === type && record?.code === M4_COPY_DOM_CODE &&
        record?.key === M4_COPY_DOM_KEY && record?.trusted === true &&
        record?.queued === false && record?.reason === reason &&
        record?.repeat === false && record?.isComposing === false &&
        record?.canvasFocused === true && record?.pointerActivated === true &&
        modifiers?.alt === false && modifiers?.control === false &&
        modifiers?.meta === false && modifiers?.shift === false;
    });
}

function matchesM4CopyPasteInnerKeyRecord(
    record, type, code, key, control, targetId) {
  return record?.type === type &&
    record?.trusted === true &&
    record?.code === code &&
    record?.key === key &&
    (control === null || record?.ctrlKey === control) &&
    record?.repeat === false &&
    record?.isComposing === false &&
    record?.targetId === targetId &&
    record?.defaultPrevented === false;
}

function matchesM4CopyPasteInnerKeyTrace(records, expectedRecords) {
  return Array.isArray(records) && records.length === expectedRecords.length &&
    expectedRecords.every(
        ([type, code, key, control, targetId], index) =>
          matchesM4CopyPasteInnerKeyRecord(
              records[index], type, code, key, control, targetId));
}

function hasM4CopyPasteSelection(activity, value) {
  const selection = activity?.lastNonCollapsed;
  return activity?.trusted === true && activity?.nonCollapsed === true &&
    activity?.trustedNonCollapsed === true && activity?.selectCount >= 1 &&
    activity?.selectTrusted === true && activity?.selectionChangeCount >= 1 &&
    activity?.selectionChangeTrusted === true && selection?.trusted === true &&
    selection?.start === 0 && selection?.end === value.length &&
    selection?.text === value &&
    (selection?.direction === "none" || selection?.direction === "forward");
}

function hasM4CopyPasteCopyEvidence(pageProbe) {
  const copy = pageProbe?.copyEventTrace;
  const selection = copy?.[0]?.selection;
  const sourceText = pageProbe?.sourceTextInputEvents;
  return pageProbe?.copySourceValue === M4_COPY_PASTE_SOURCE_VALUE &&
    hasM4CopyPasteSelection(
        pageProbe?.copySelectionActivity, M4_COPY_PASTE_SOURCE_VALUE) &&
    Array.isArray(copy) && copy.length === 1 &&
    copy[0]?.type === "copy" && copy[0]?.trusted === true &&
    copy[0]?.targetId === "copy-source" &&
    copy[0]?.defaultPrevented === false &&
    selection?.start === 0 &&
    selection?.end === M4_COPY_PASTE_SOURCE_VALUE.length &&
    selection?.text === M4_COPY_PASTE_SOURCE_VALUE &&
    sourceText?.beforeinputCount === 0 && sourceText?.inputCount === 0 &&
    sourceText?.compositionstartCount === 0 &&
    sourceText?.compositionupdateCount === 0 &&
    sourceText?.compositionendCount === 0;
}

function hasM4CopyPastePrimarySelectionPasteEvidence(pageProbe) {
  const paste = pageProbe?.primaryVerifyPasteEventTrace;
  const text = pageProbe?.primaryVerifyPasteTextInputTrace;
  return pageProbe?.activeElementId === "primary-verify-target" &&
    pageProbe?.copySourceValue === M4_COPY_PASTE_SOURCE_VALUE &&
    pageProbe?.decoyValue === M4_COPY_PASTE_DECOY_VALUE &&
    hasM4CopyPasteSelection(
        pageProbe?.decoySelectionActivity, M4_COPY_PASTE_DECOY_VALUE) &&
    pageProbe?.primaryVerifyAuxClickCount === 1 &&
    pageProbe?.primaryVerifyAuxClickTrusted === true &&
    pageProbe?.primaryVerifyFocusCount >= 1 &&
    pageProbe?.primaryVerifyFocusTrusted === true &&
    pageProbe?.primaryVerifyValue === M4_COPY_PASTE_DECOY_VALUE &&
    pageProbe?.primaryVerifySelectionStart === M4_COPY_PASTE_DECOY_VALUE.length &&
    pageProbe?.primaryVerifySelectionEnd === M4_COPY_PASTE_DECOY_VALUE.length &&
    Array.isArray(paste) && paste.length === 1 &&
    paste[0]?.type === "paste" && paste[0]?.trusted === true &&
    paste[0]?.targetId === "primary-verify-target" &&
    paste[0]?.defaultPrevented === false &&
    paste[0]?.text === M4_COPY_PASTE_DECOY_VALUE &&
    Array.isArray(text) && text.length === 2 &&
    text[0]?.type === "beforeinput" && text[1]?.type === "input" &&
    text.every((record) => record?.trusted === true &&
      record?.inputType === "insertFromPaste" &&
      record?.data === M4_COPY_PASTE_DECOY_VALUE &&
      record?.isComposing === false &&
      record?.targetId === "primary-verify-target");
}

function hasM4CopyPastePasteEvidence(pageProbe) {
  const paste = pageProbe?.pasteEventTrace;
  const text = pageProbe?.pasteTextInputTrace;
  const decoyText = pageProbe?.decoyTextInputEvents;
  return pageProbe?.copySourceValue === M4_COPY_PASTE_SOURCE_VALUE &&
    pageProbe?.decoyValue === M4_COPY_PASTE_DECOY_VALUE &&
    hasM4CopyPasteSelection(
        pageProbe?.decoySelectionActivity, M4_COPY_PASTE_DECOY_VALUE) &&
    decoyText?.beforeinputCount === 0 && decoyText?.inputCount === 0 &&
    decoyText?.compositionstartCount === 0 &&
    decoyText?.compositionupdateCount === 0 &&
    decoyText?.compositionendCount === 0 &&
    pageProbe?.pasteTargetActivationCount === 1 &&
    pageProbe?.pasteTargetFocusCount >= 1 &&
    pageProbe?.pasteValue === M4_COPY_PASTE_SOURCE_VALUE &&
    pageProbe?.pasteSelectionStart === M4_COPY_PASTE_SOURCE_VALUE.length &&
    pageProbe?.pasteSelectionEnd === M4_COPY_PASTE_SOURCE_VALUE.length &&
    pageProbe?.resultText === "CTRL COPY/PASTE DELIVERED" &&
    Array.isArray(paste) && paste.length === 1 &&
    paste[0]?.type === "paste" && paste[0]?.trusted === true &&
    paste[0]?.targetId === "paste-target" &&
    paste[0]?.defaultPrevented === false &&
    paste[0]?.text === M4_COPY_PASTE_SOURCE_VALUE &&
    Array.isArray(text) && text.length === 2 &&
    text[0]?.type === "beforeinput" && text[1]?.type === "input" &&
    text.every((record) => record?.trusted === true &&
      record?.inputType === "insertFromPaste" &&
      record?.data === M4_COPY_PASTE_SOURCE_VALUE &&
      record?.isComposing === false &&
      record?.targetId === "paste-target");
}

function isWellFormedUtf16(value) {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) {
        return false;
      }
      index += 1;
      continue;
    }
    if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return false;
    }
  }
  return true;
}

function imeProxyTextSummary(value) {
  return {
    utf16Length: value.length,
    utf8Bytes: UTF8_ENCODER.encode(value).byteLength,
    codePointCount: Array.from(value).length,
  };
}

// The IME smoke deliberately verifies the non-BMP candidate by shape rather
// than placing user-entered text in host diagnostics.
function isM4ImeSmokeTextSummary(value) {
  return value?.utf16Length === 2 &&
      value?.utf8Bytes === 4 && value?.codePointCount === 1;
}

function isEmptyM4ImeTextSummary(value) {
  return value?.utf16Length === 0 &&
      value?.utf8Bytes === 0 && value?.codePointCount === 0;
}

function isM5NetworkPageProbeIdentity(pageProbe) {
  return pageProbe?.protocol === HOST_PROTOCOL &&
      pageProbe?.fixture === M5_NETWORK_FIXTURE &&
      pageProbe?.phase === M5_NAVIGATION_PHASE.HTTPS_FIXTURE &&
      typeof pageProbe?.ready === "boolean" &&
      Number.isSafeInteger(pageProbe?.timerTicks) &&
      pageProbe.timerTicks >= 0 &&
      typeof pageProbe?.h2Fetch === "boolean" &&
      typeof pageProbe?.h2Protocol === "string" &&
      typeof pageProbe?.altSvcH3Advertised === "boolean" &&
      typeof pageProbe?.cacheStored === "boolean" &&
      typeof pageProbe?.cacheRevalidated === "boolean" &&
      typeof pageProbe?.cspConnectSrcBlocked === "boolean" &&
      typeof pageProbe?.activeMixedContentBlocked === "boolean" &&
      typeof pageProbe?.activeMixedContentTargetUrl === "string" &&
      typeof pageProbe?.activeMixedContentErrorName === "string" &&
      typeof pageProbe?.activeMixedContentCspAllowed === "boolean" &&
      typeof pageProbe?.corsFetch === "boolean" &&
      typeof pageProbe?.redirected === "boolean" &&
      typeof pageProbe?.webSocketEcho === "boolean" &&
      typeof pageProbe?.nonce === "string" && pageProbe.nonce.length > 0;
}

function hasM5NetworkPageProbe(pageProbe) {
  return isM5NetworkPageProbeIdentity(pageProbe) &&
      pageProbe?.ready === true &&
      pageProbe?.h2Fetch === true && pageProbe?.h2Protocol === "h2" &&
      pageProbe?.redirected === true &&
      pageProbe?.cacheStored === true && pageProbe?.cacheRevalidated === true &&
      pageProbe?.cspConnectSrcBlocked === true &&
      pageProbe?.activeMixedContentBlocked === true &&
      pageProbe.activeMixedContentTargetUrl.length > 0 &&
      pageProbe?.activeMixedContentErrorName === "TypeError" &&
      pageProbe?.activeMixedContentCspAllowed === true &&
      pageProbe?.corsFetch === true && pageProbe?.webSocketEcho === true &&
      pageProbe?.altSvcH3Advertised === true;
}

function isM5PlaintextHttpControlPageProbeIdentity(pageProbe) {
  return pageProbe?.protocol === HOST_PROTOCOL &&
      pageProbe?.fixture === M5_NETWORK_FIXTURE &&
      pageProbe?.phase === M5_NAVIGATION_PHASE.PLAINTEXT_HTTP_CONTROL &&
      typeof pageProbe?.ready === "boolean" &&
      Number.isSafeInteger(pageProbe?.timerTicks) &&
      pageProbe.timerTicks >= 0 &&
      pageProbe?.plaintextHttpControlDocument === true &&
      typeof pageProbe?.plaintextHttpControlProof === "boolean";
}

function hasM5PlaintextHttpControlPageProbe(pageProbe) {
  return isM5PlaintextHttpControlPageProbeIdentity(pageProbe) &&
      pageProbe?.ready === true &&
      pageProbe?.plaintextHttpControlProof === true;
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

function deliverBridgeReport(method, args) {
  if (activeHost) {
    return activeHost[method](...args);
  } else {
    pendingBridgeReports.push({method, args});
  }
}

// The Ozone and Content JS libraries call this versioned bridge. Reports are
// queued until initialize() owns the single M3 host instance.
globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
  protocol: HOST_PROTOCOL,
  reportFrame(report) {
    deliverBridgeReport("_reportFrame", [report]);
  },
  reportReadiness(report) {
    deliverBridgeReport("_reportReadiness", [report]);
  },
  reportNavigation(report) {
    deliverBridgeReport("_reportNavigation", [report]);
  },
  reportPageProbe(report) {
    deliverBridgeReport("_reportPageProbe", [report]);
  },
  reportM5Navigation(report) {
    deliverBridgeReport("_reportM5Navigation", [report]);
  },
  reportM5NavigationError(report) {
    deliverBridgeReport("_reportM5NavigationError", [report]);
  },
  reportM5PageProbe(report) {
    deliverBridgeReport("_reportM5PageProbe", [report]);
  },
  reportM5PlaintextHttpControlNavigation(report) {
    deliverBridgeReport("_reportM5PlaintextHttpControlNavigation", [report]);
  },
  reportM5PlaintextHttpControlNavigationError(report) {
    deliverBridgeReport(
      "_reportM5PlaintextHttpControlNavigationError", [report]);
  },
  reportM5PlaintextHttpControlPageProbe(report) {
    deliverBridgeReport("_reportM5PlaintextHttpControlPageProbe", [report]);
  },
  reportOzoneFocusState(report) {
    deliverBridgeReport("_reportOzoneFocusState", [report]);
  },
  reportOzoneCursor(report) {
    return deliverBridgeReport("_reportOzoneCursor", [report]);
  },
  reportOzoneTextInputState(report) {
    deliverBridgeReport("_reportOzoneTextInputState", [report]);
  },
  reportOzoneTextInputDelivery(report) {
    deliverBridgeReport("_reportOzoneTextInputDelivery", [report]);
  },
  reportFatal(message) {
    deliverBridgeReport("_reportFatal", [message]);
  },
  reportProcessExit(report) {
    deliverBridgeReport("_reportProcessExit", [report]);
  },
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function encodeBytesBase64(bytes) {
  let binary = "";
  const chunkSize = 0x4000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(
      ...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
  }
  return btoa(binary);
}

async function buildFixtureDataURL(fixturePath, fontPath) {
  const [fixtureResponse, fontResponse] = await Promise.all([
    fetch(fixturePath, {cache: "no-store"}),
    fetch(fontPath, {cache: "no-store"}),
  ]);
  if (!fixtureResponse.ok) {
    throw new Error(`fixture request returned HTTP ${fixtureResponse.status}`);
  }
  if (!fontResponse.ok) {
    throw new Error(`font request returned HTTP ${fontResponse.status}`);
  }
  const template = await fixtureResponse.text();
  if (template.split(FIXTURE_FONT_MARKER).length !== 2) {
    throw new Error("fixture must contain exactly one Ahem marker");
  }
  const font = new Uint8Array(await fontResponse.arrayBuffer());
  if (font.length === 0) {
    throw new Error("fixture Ahem font is empty");
  }
  const expanded = template.replace(
    FIXTURE_FONT_MARKER, encodeBytesBase64(font));
  return `data:text/html;charset=utf-8;base64,${
    encodeBytesBase64(new TextEncoder().encode(expanded))}`;
}

function normalizeVersion(value) {
  return typeof value === "string" && value.length > 0 ? value : "missing";
}

function renderVersions(versions) {
  const container = document.querySelector("#versions");
  container.replaceChildren();
  for (const [name, value] of [
    ["Chromium", versions.chromium],
    ["V8", versions.v8],
    ["Emscripten", versions.emscripten],
    ["Port", versions.port],
  ]) {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = name;
    description.textContent = normalizeVersion(value);
    container.append(term, description);
  }
}

function checkInteger(value, description, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(
      `${description} must be an integer in [${minimum}, ${maximum}]`);
  }
  return value;
}

function isWispLoopbackHost(hostname) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (normalized === "localhost" || normalized.endsWith(".localhost") ||
      normalized === "::1") {
    return true;
  }
  const octets = normalized.split(".");
  return octets.length === 4 && octets.every((octet) =>
    /^\d{1,3}$/.test(octet) && Number(octet) <= 255) &&
      Number(octets[0]) === 127;
}

// Copies a deliberately small, credential-free WISP configuration into the
// Emscripten Module before its factory runs. Web content never receives this
// object, and the bridge has no endpoint default: omitting |configuration|
// leaves Chromium networking explicitly unavailable rather than falling back
// to host fetch().
export function normalizeWispConfiguration(configuration) {
  if (configuration === undefined) {
    return undefined;
  }
  if (!configuration || typeof configuration !== "object" ||
      Array.isArray(configuration)) {
    throw new Error("WISP configuration must be an object");
  }

  const allowedFields = new Set([
    "version",
    "endpoint",
    "subprotocol",
    ...Object.keys(WISP_OPTION_RANGES),
  ]);
  for (const field of Object.getOwnPropertyNames(configuration)) {
    if (!allowedFields.has(field)) {
      throw new Error(`WISP configuration field is not allowed: ${field}`);
    }
  }
  if (configuration.version !== WISP_CONFIGURATION_VERSION) {
    throw new Error("WISP configuration version is unsupported");
  }
  if (typeof configuration.endpoint !== "string" ||
      configuration.endpoint.length === 0 ||
      configuration.endpoint.length > 2048) {
    throw new Error("WISP endpoint must be a nonempty absolute URL");
  }

  let endpoint;
  try {
    endpoint = new URL(configuration.endpoint);
  } catch (_) {
    throw new Error("WISP endpoint is not a valid absolute URL");
  }
  if ((endpoint.protocol !== "wss:" &&
       !(endpoint.protocol === "ws:" && isWispLoopbackHost(endpoint.hostname))) ||
      endpoint.username || endpoint.password || endpoint.search ||
      endpoint.hash || !endpoint.pathname.endsWith("/")) {
    throw new Error("WISP endpoint violates the transport policy");
  }

  const normalized = {
    version: WISP_CONFIGURATION_VERSION,
    endpoint: endpoint.href,
  };
  if (Object.hasOwn(configuration, "subprotocol")) {
    const {subprotocol} = configuration;
    if (typeof subprotocol !== "string" || subprotocol.length === 0 ||
        subprotocol.length > 128 ||
        !/^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(subprotocol)) {
      throw new Error("WISP subprotocol is invalid");
    }
    normalized.subprotocol = subprotocol;
  }

  const effectiveOptions = {};
  for (const [name, [minimum, maximum, fallback]] of
       Object.entries(WISP_OPTION_RANGES)) {
    const value = Object.hasOwn(configuration, name) ? configuration[name] :
      fallback;
    checkInteger(value, `WISP ${name}`, minimum, maximum);
    effectiveOptions[name] = value;
    if (Object.hasOwn(configuration, name)) {
      normalized[name] = value;
    }
  }
  if (effectiveOptions.maxWebSocketBufferedBytes <
      effectiveOptions.maxDataFrameBytes + 5) {
    throw new Error("WISP WebSocket buffer cannot hold one DATA packet");
  }

  return Object.freeze(normalized);
}

// M5 has one deliberately narrow non-data navigation lane. Its runtime test
// server chooses an ephemeral TLS port, but the hostname and fixture path are
// fixed so this cannot become a general-purpose host navigation API.
function normalizeM5NetworkTestURL(value) {
  if (
    typeof value !== "string" || value.length === 0 || value.length > 2048
  ) {
    throw new Error("M5 network test URL must be a nonempty string");
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch (_) {
    throw new Error("M5 network test URL is invalid");
  }
  if (
    parsed.protocol !== "https:" ||
    parsed.hostname !== M5_NETWORK_TEST_HOSTNAME ||
    !parsed.port ||
    parsed.username || parsed.password || parsed.search || parsed.hash ||
    !parsed.pathname.startsWith(M5_NETWORK_TEST_PATH_PREFIX)
  ) {
    throw new Error("M5 network test URL violates the fixture policy");
  }
  const port = Number(parsed.port);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("M5 network test URL has an invalid port");
  }
  return parsed.href;
}

// Active mixed-content coverage admits one exact plaintext top-level control
// document. It remains separate from the HTTPS fixture policy above and does
// not authorize HTTP navigation to arbitrary M5 paths.
function normalizeM5PlaintextHttpControlURL(value) {
  if (
    typeof value !== "string" || value.length === 0 || value.length > 2048
  ) {
    throw new Error("M5 plaintext HTTP control URL must be a nonempty string");
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch (_) {
    throw new Error("M5 plaintext HTTP control URL is invalid");
  }
  if (
    parsed.protocol !== "http:" ||
    parsed.hostname !== M5_NETWORK_TEST_HOSTNAME ||
    !parsed.port ||
    parsed.username || parsed.password || parsed.search || parsed.hash ||
    parsed.pathname !== M5_PLAINTEXT_HTTP_CONTROL_PATH
  ) {
    throw new Error("M5 plaintext HTTP control URL violates the fixture policy");
  }
  const port = Number(parsed.port);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("M5 plaintext HTTP control URL has an invalid port");
  }
  return parsed.href;
}

export class ChromiumWasmM3Host {
  #canvas;
  #imeProxy;
  #fixture;
  #wispConfigured = false;
  #m5NetworkTestActive = false;
  #m5NetworkNavigationCount = 0;
  #m5NetworkPhase = M5_NAVIGATION_PHASE.NONE;
  #module = null;
  #lifecycle = "new";
  #runtimeInitialized = false;
  #fatalErrors = [];
  #reportedReadiness = {};
  #navigation = {};
  #pageProbe = {};
  #ozoneFocusState = null;
  #ozoneFocusReportSequence = 0;
  #ozoneFocusReports = [];
  #ozoneCursor = null;
  #ozoneCursorReportSequence = 0;
  #ozoneTextInputState = null;
  #ozoneTextInputReportSequence = 0;
  #frame = null;
  #currentDevicePixelRatio = 1;
  #inputPostedAtFrameId = null;
  #interactionObservedAtFrameId = null;
  #processExit = null;
  #processExitPromise;
  #resolveProcessExit;
  #runtimeExit = null;
  #runtimeExitPromise;
  #resolveRuntimeExit;
  #exitReportSequence = 0;
  #initialLinearMemoryBytes = null;
  #versions;
  #logs = {host: [], stdout: [], stderr: []};
  #heartbeatAnchor = null;
  #heartbeatStartTime = null;
  #heartbeatStartTimerTicks = 0;
  #heartbeatStartAnimationFrameTicks = 0;
  #timerTicks = 0;
  #animationFrameTicks = 0;
  #maximumTimerGapMs = 0;
  #lastTimerTime;
  #timerHandle;
  #animationFrameHandle;
  #errorHandler;
  #rejectionHandler;
  #pointerInputEnabled = false;
  #pointerListeners = [];
  #pointerSequence = 0;
  #pointerRecords = [];
  #lastQueuedPointer = null;
  #activeM4PointerId = null;
  #activeM4PointerButton = null;
  #lastM4PointerPoint = null;
  #m4PointerHoverActive = false;
  #contextMenuSequence = 0;
  #contextMenuRecords = [];
  #pendingM4ContextMenu = null;
  #wheelInputEnabled = false;
  #wheelListeners = [];
  #wheelSequence = 0;
  #wheelRecords = [];
  #lastQueuedWheel = null;
  #wheelResidualX = 0;
  #wheelResidualY = 0;
  #keyboardInputEnabled = false;
  #keyboardListeners = [];
  #keyboardSequence = 0;
  #keyboardRecords = [];
  #lastQueuedKeyDown = null;
  #lastQueuedKeyUp = null;
  #keyboardActivated = false;
  #keyboardCodesDown = new Set();
  #focusInputEnabled = false;
  #focusListeners = [];
  #focusSequence = 0;
  #focusRecords = [];
  #lastQueuedFocusLoss = null;
  #hostWindowActive = false;
  #imeProxyInputEnabled = false;
  #imeProxyListeners = [];
  #imeProxySequence = 0;
  #imeProxyRecords = [];
  #imeProxySessionId = 0;
  #imeProxyCompositionActive = false;
  #imeProxyLastCompositionText = null;
  #imeProxyPendingTransaction = null;
  #imeProxyLastConfirmedTransaction = null;
  #imeProxyLastConfirmedText = null;
  #imeProxyTerminalCancellationPending = false;
  #imeProxyExpectedTerminalAction = null;
  #imeProxyNativeRequests = [];
  #imeProxyNativeComposition = null;
  #imeProxyNativeTerminalAction = null;
  #imeProxyFailure = null;
  #imeProxyActivationRequest = null;
  #imeProxyExpectedFocusTransfer = null;
  #imeProxyFocusCount = 0;
  #imeProxyBlurCount = 0;

  constructor(
    canvas,
    versions,
    {
      fixture = "chromium-wasm-m3-static-v1",
      imeProxy = null,
    } = {},
  ) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("M3 host requires a canvas");
    }
    if (activeHost) {
      throw new Error("only one M3 host instance may be active");
    }
    this.#canvas = canvas;
    if (imeProxy !== null && !(imeProxy instanceof HTMLTextAreaElement)) {
      throw new Error("M4 IME proxy must be a textarea when supplied");
    }
    this.#imeProxy = imeProxy;
    if (typeof fixture !== "string" || fixture.length === 0) {
      throw new Error("host fixture identifier must be a nonempty string");
    }
    this.#fixture = fixture;
    this.#versions = Object.freeze({
      chromium: normalizeVersion(versions.chromium),
      v8: normalizeVersion(versions.v8),
      emscripten: normalizeVersion(versions.emscripten),
      port: normalizeVersion(versions.port),
    });
    this.#processExitPromise = new Promise((resolve) => {
      this.#resolveProcessExit = resolve;
    });
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#resolveRuntimeExit = resolve;
    });
    activeHost = this;

    this.#lastTimerTime = performance.now();
    this.#timerHandle = setInterval(() => {
      const now = performance.now();
      if (this.#heartbeatAnchor !== null) {
        this.#maximumTimerGapMs = Math.max(
          this.#maximumTimerGapMs, now - this.#lastTimerTime);
      }
      this.#lastTimerTime = now;
      this.#timerTicks += 1;
    }, 25);
    const tickAnimationFrame = () => {
      this.#animationFrameTicks += 1;
      this.#animationFrameHandle = requestAnimationFrame(tickAnimationFrame);
    };
    this.#animationFrameHandle = requestAnimationFrame(tickAnimationFrame);

    this.#errorHandler = (event) => {
      const message = event.error || event.message || "window error";
      this._reportFatal(`uncaught exception: ${String(message)}`);
    };
    this.#rejectionHandler = (event) => {
      this._reportFatal(`unhandled rejection: ${String(event.reason)}`);
    };
    addEventListener("error", this.#errorHandler);
    addEventListener("unhandledrejection", this.#rejectionHandler);

    for (const pending of pendingBridgeReports.splice(0)) {
      this[pending.method](...pending.args);
    }
  }

  #recordHost(message) {
    this.#logs.host.push(String(message));
  }

  #stopHeartbeat() {
    clearInterval(this.#timerHandle);
    cancelAnimationFrame(this.#animationFrameHandle);
  }

  #releaseHost() {
    this.#stopHeartbeat();
    this.#disableM4PointerInput();
    this.#disableM4KeyboardInput();
    this.#disableM4ImeProxyInput();
    this.#disableM4FocusInput();
    this.#disableM4WheelInput();
    removeEventListener("error", this.#errorHandler);
    removeEventListener("unhandledrejection", this.#rejectionHandler);
    if (activeHost === this) {
      activeHost = null;
    }
  }

  #resetHeartbeatWindow(anchor) {
    const now = performance.now();
    this.#heartbeatAnchor = anchor;
    this.#heartbeatStartTime = now;
    this.#heartbeatStartTimerTicks = this.#timerTicks;
    this.#heartbeatStartAnimationFrameTicks = this.#animationFrameTicks;
    this.#maximumTimerGapMs = 0;
    this.#lastTimerTime = now;
  }

  #recordPointer(record) {
    this.#pointerRecords.push(record);
    if (this.#pointerRecords.length > 32) {
      this.#pointerRecords.shift();
    }
  }

  #pointerInputStatus() {
    const queuedCount = this.#pointerRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#pointerRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#pointerInputEnabled,
      receivedCount: this.#pointerRecords.length,
      trustedCount,
      queuedCount,
      queuedRecords: this.#pointerRecords.filter(
        (record) => record.queued === true).map((record) => clone(record)),
      lastQueued: this.#lastQueuedPointer
        ? clone(this.#lastQueuedPointer)
        : null,
      contextMenuRecords: this.#contextMenuRecords.map((record) =>
        clone(record)),
    };
  }

  #recordM4ContextMenu(record) {
    this.#contextMenuRecords.push(record);
    if (this.#contextMenuRecords.length > 16) {
      this.#contextMenuRecords.shift();
    }
  }

  #recordWheel(record) {
    this.#wheelRecords.push(record);
    if (this.#wheelRecords.length > 32) {
      this.#wheelRecords.shift();
    }
  }

  #wheelInputStatus() {
    const queuedCount = this.#wheelRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#wheelRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#wheelInputEnabled,
      receivedCount: this.#wheelRecords.length,
      trustedCount,
      queuedCount,
      lastQueued: this.#lastQueuedWheel ? clone(this.#lastQueuedWheel) : null,
    };
  }

  #recordKeyboard(record) {
    this.#keyboardRecords.push(record);
    if (this.#keyboardRecords.length > 32) {
      this.#keyboardRecords.shift();
    }
  }

  #keyboardInputStatus() {
    const queuedCount = this.#keyboardRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#keyboardRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#keyboardInputEnabled,
      activated: this.#keyboardActivated,
      receivedCount: this.#keyboardRecords.length,
      trustedCount,
      queuedCount,
      queuedRecords: this.#keyboardRecords.filter(
        (record) => record.queued === true).map((record) => clone(record)),
      rejectedRecords: this.#keyboardRecords.filter(
        (record) => record.queued !== true).map((record) => clone(record)),
      pressedCodes: Array.from(this.#keyboardCodesDown).sort(),
      lastQueuedDown: this.#lastQueuedKeyDown
        ? clone(this.#lastQueuedKeyDown)
        : null,
      lastQueuedUp: this.#lastQueuedKeyUp
        ? clone(this.#lastQueuedKeyUp)
        : null,
    };
  }

  #hasM4EditableTextInputAcknowledgement() {
    const state = this.#ozoneTextInputState;
    return state !== null && state.focusedClientPresent === true &&
      state.editable === true && state.canComposeInline === true;
  }

  #consumeM4ExpectedProxyFocusTransfer(target) {
    const transfer = this.#imeProxyExpectedFocusTransfer;
    if (!transfer || target !== this.#imeProxy) {
      return false;
    }
    this.#imeProxyExpectedFocusTransfer = null;
    return true;
  }

  #cancelM4ImeProxyActivation(reason) {
    if (
      this.#imeProxyActivationRequest === null &&
      this.#imeProxyExpectedFocusTransfer === null
    ) {
      return;
    }
    this.#imeProxyActivationRequest = null;
    this.#imeProxyExpectedFocusTransfer = null;
    this.#recordHost(`m4:ime-proxy:${reason}:activation-cancelled`);
  }

  #armM4ImeProxyActivation(record) {
    if (!this.#imeProxyInputEnabled || !this.#imeProxy) {
      return;
    }
    if (!record.trusted || !record.queued || !this.#hostWindowActive) {
      this.#recordHost("m4:ime-proxy:pointer-arm-rejected");
      return;
    }
    this.#cancelM4ImeProxyActivation("pointer-rearm");
    this.#clearM4ImeProxyState("pointer-rearm");
    this.#imeProxyFailure = null;
    this.#imeProxyActivationRequest = {
      pointerDownSequence: record.sequence,
      pointerUpQueued: false,
      ozoneFocusReportSequenceBefore: this.#ozoneFocusReportSequence,
      ozoneTextInputReportSequenceBefore: this.#ozoneTextInputReportSequence,
    };
    this.#recordHost("m4:ime-proxy:pointer-arm-awaiting-native-editable");
  }

  #markM4ImeProxyPointerUp(record) {
    const request = this.#imeProxyActivationRequest;
    if (!request || !record.trusted || !record.queued) {
      return;
    }
    request.pointerUpQueued = true;
    request.pointerUpSequence = record.sequence;
    this.#recordHost("m4:ime-proxy:pointer-up-awaiting-native-editable");
    this.#maybeActivateM4ImeProxy();
  }

  #maybeActivateM4ImeProxy() {
    const request = this.#imeProxyActivationRequest;
    const focusState = this.#ozoneFocusState;
    const textInputState = this.#ozoneTextInputState;
    if (
      !request || !request.pointerUpQueued || !this.#imeProxyInputEnabled ||
      !this.#imeProxy || !this.#hostWindowActive ||
      document.activeElement !== this.#canvas ||
      !focusState ||
      focusState.sequence <= request.ozoneFocusReportSequenceBefore ||
      focusState.keyboardTargetPresent !== true || focusState.active !== true ||
      !textInputState ||
      textInputState.sequence <= request.ozoneTextInputReportSequenceBefore ||
      !this.#hasM4EditableTextInputAcknowledgement()
    ) {
      return false;
    }

    this.#imeProxyActivationRequest = null;
    this.#resetM4ImeProxySession();
    this.#imeProxyExpectedFocusTransfer = {
      sessionId: this.#imeProxySessionId,
      pointerDownSequence: request.pointerDownSequence,
      pointerUpSequence: request.pointerUpSequence,
    };
    this.#imeProxy.focus({preventScroll: true});
    if (document.activeElement !== this.#imeProxy) {
      this.#imeProxyExpectedFocusTransfer = null;
      this.#imeProxyFailure = "PROXY_FOCUS_FAILED";
      this.#recordHost("m4:ime-proxy:native-editable-focus-failed");
      this.#deactivateM4HostWindow("ime-proxy-focus-failed");
      return false;
    }
    this.#recordHost("m4:ime-proxy:native-editable-focus");
    return true;
  }

  #recordImeProxy(record) {
    this.#imeProxyRecords.push(record);
    if (this.#imeProxyRecords.length > 64) {
      this.#imeProxyRecords.shift();
    }
  }

  #imeProxySelection() {
    if (!this.#imeProxy) {
      return null;
    }
    const start = this.#imeProxy.selectionStart;
    const end = this.#imeProxy.selectionEnd;
    if (
      !Number.isSafeInteger(start) ||
      !Number.isSafeInteger(end) ||
      start < 0 ||
      end < start ||
      end > this.#imeProxy.value.length
    ) {
      return null;
    }
    return {start, end};
  }

  #imeProxyActionName(action) {
    switch (action) {
      case M4_IME_TEXT_ACTION.setComposition:
        return "set-composition";
      case M4_IME_TEXT_ACTION.confirmComposition:
        return "confirm-composition";
      case M4_IME_TEXT_ACTION.clearComposition:
        return "clear-composition";
      default:
        return null;
    }
  }

  #recordM4ImeProxyNativeRequest(request) {
    if (this.#imeProxyNativeRequests.length >= 64) {
      const completed = this.#imeProxyNativeRequests.findIndex(
        (candidate) => candidate.deliveryAccepted !== null);
      if (completed < 0) {
        return false;
      }
      this.#imeProxyNativeRequests.splice(completed, 1);
    }
    this.#imeProxyNativeRequests.push(request);
    return true;
  }

  #queueM4ImeProxyTextInput(action, sessionId, sequence, text, selection) {
    const actionName = this.#imeProxyActionName(action);
    if (
      actionName === null || !Number.isSafeInteger(sessionId) ||
      sessionId < 1 || sessionId > 0x7fffffff ||
      !Number.isSafeInteger(sequence) || sequence < 1 ||
      sequence > 0x7fffffff || typeof text !== "string" ||
      !isWellFormedUtf16(text) || !selection ||
      !Number.isSafeInteger(selection.start) ||
      !Number.isSafeInteger(selection.end) || selection.start < 0 ||
      selection.end < selection.start || selection.end > text.length
    ) {
      return null;
    }
    const utf8 = UTF8_ENCODER.encode(text);
    if (utf8.byteLength > MAXIMUM_IME_PROXY_TEXT_BYTES) {
      return null;
    }
    if (
      action === M4_IME_TEXT_ACTION.setComposition &&
      (text.length === 0 || selection.start !== selection.end ||
        selection.end !== text.length)
    ) {
      return null;
    }
    if (
      action !== M4_IME_TEXT_ACTION.setComposition &&
      (text.length !== 0 || selection.start !== 0 || selection.end !== 0)
    ) {
      return null;
    }

    const request = {
      action,
      actionName,
      sessionId,
      sequence,
      queued: true,
      deliveryAccepted: null,
      text: action === M4_IME_TEXT_ACTION.setComposition
        ? imeProxyTextSummary(text)
        : null,
      selection: {start: selection.start, end: selection.end},
    };
    if (!this.#recordM4ImeProxyNativeRequest(request)) {
      return null;
    }
    try {
      const result = this.#callExport(
        "chromium_wasm_host_text_input",
        "number",
        ["number", "number", "number", "array", "number", "number", "number"],
        [
          action,
          sessionId,
          sequence,
          utf8,
          utf8.byteLength,
          selection.start,
          selection.end,
        ],
      );
      request.queued = result === 1;
      if (!request.queued) {
        request.deliveryAccepted = false;
        request.reason = "QUEUE_REJECTED";
        return null;
      }
      return request;
    } catch (error) {
      request.queued = false;
      request.deliveryAccepted = false;
      request.reason = `EXPORT_ERROR:${String(error)}`;
      return null;
    }
  }

  #queueM4ImeProxyClear(reason) {
    const composition = this.#imeProxyNativeComposition;
    if (
      !composition || this.#imeProxyNativeTerminalAction !== null ||
      this.#lifecycle !== "running"
    ) {
      return;
    }
    const sequence = ++this.#imeProxySequence;
    const request = this.#queueM4ImeProxyTextInput(
      M4_IME_TEXT_ACTION.clearComposition,
      composition.sessionId,
      sequence,
      "",
      {start: 0, end: 0},
    );
    if (!request) {
      if (this.#imeProxyFailure === null) {
        this.#imeProxyFailure = "NATIVE_CLEAR_QUEUE_REJECTED";
      }
      this.#recordHost(`m4:ime-proxy:${reason}:native-clear-rejected`);
      return;
    }
    this.#imeProxyNativeTerminalAction = request;
    this.#recordHost(`m4:ime-proxy:${reason}:native-clear-queued`);
  }

  #imeProxyInputStatus() {
    const eventCount = (type) => this.#imeProxyRecords.filter(
      (record) => record.type === type).length;
    const trustedCount = this.#imeProxyRecords.filter(
      (record) => record.trusted === true).length;
    const acceptedCount = this.#imeProxyRecords.filter(
      (record) => record.accepted === true).length;
    const derivedTerminalCount = this.#imeProxyRecords.filter(
      (record) => record.terminalDerivedFromTrustedTransaction === true).length;
    const observedClearTerminalCount = this.#imeProxyRecords.filter(
      (record) => record.terminalObservedAfterClear === true).length;
    const nativeRequests = this.#imeProxyNativeRequests.filter(
      (record) => record.sessionId === this.#imeProxySessionId);
    const nativeDeliveryCount = (action) => nativeRequests.filter(
      (record) => record.action === action &&
        record.deliveryAccepted === true).length;
    const nativePendingDelivery = nativeRequests.some(
      (record) => record.queued === true && record.deliveryAccepted === null);
    const lastNativeDelivery = nativeRequests.findLast(
      (record) => record.deliveryAccepted !== null);
    const proxyText = this.#imeProxy ? {
      ...imeProxyTextSummary(this.#imeProxy.value),
      selection: this.#imeProxySelection(),
    } : null;
    return {
      enabled: this.#imeProxyInputEnabled,
      present: this.#imeProxy !== null,
      focused: document.activeElement === this.#imeProxy,
      hostWindowActive: this.#hostWindowActive,
      sessionId: this.#imeProxySessionId,
      receivedCount: this.#imeProxyRecords.length,
      trustedCount,
      acceptedCount,
      derivedTerminalCount,
      observedClearTerminalCount,
      focusCount: this.#imeProxyFocusCount,
      blurCount: this.#imeProxyBlurCount,
      compositionStartCount: eventCount("compositionstart"),
      compositionUpdateCount: eventCount("compositionupdate"),
      compositionEndCount: eventCount("compositionend"),
      beforeinputCount: eventCount("beforeinput"),
      inputCount: eventCount("input"),
      compositionActive: this.#imeProxyCompositionActive,
      terminalCancellationPending: this.#imeProxyTerminalCancellationPending,
      pendingTransaction: this.#imeProxyPendingTransaction !== null,
      activationPending: this.#imeProxyActivationRequest !== null,
      nativeTextInputReady: this.#hasM4EditableTextInputAcknowledgement(),
      nativeQueuedCount: nativeRequests.filter(
        (record) => record.queued === true).length,
      nativeSetDeliveryCount: nativeDeliveryCount(
        M4_IME_TEXT_ACTION.setComposition),
      nativeConfirmDeliveryCount: nativeDeliveryCount(
        M4_IME_TEXT_ACTION.confirmComposition),
      nativeClearDeliveryCount: nativeDeliveryCount(
        M4_IME_TEXT_ACTION.clearComposition),
      nativePendingDelivery,
      nativeCompositionActive: this.#imeProxyNativeComposition !== null,
      nativeTerminalAction: this.#imeProxyNativeTerminalAction
        ? this.#imeProxyNativeTerminalAction.actionName
        : null,
      lastNativeDelivery: lastNativeDelivery ? clone(lastNativeDelivery) : null,
      lastConfirmedTransaction: this.#imeProxyLastConfirmedTransaction
        ? clone(this.#imeProxyLastConfirmedTransaction)
        : null,
      failure: this.#imeProxyFailure,
      proxyText,
    };
  }

  #resetM4ImeProxySession() {
    if (!this.#imeProxy) {
      return;
    }
    this.#imeProxySessionId += 1;
    this.#imeProxyRecords = [];
    this.#imeProxyCompositionActive = false;
    this.#imeProxyLastCompositionText = null;
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedTransaction = null;
    this.#imeProxyLastConfirmedText = null;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyExpectedTerminalAction = null;
    this.#imeProxyNativeComposition = null;
    this.#imeProxyNativeTerminalAction = null;
    this.#imeProxyFailure = null;
    this.#imeProxy.value = "";
    this.#imeProxy.setSelectionRange(0, 0);
  }

  #clearM4ImeProxyState(reason, {queueNativeClear = true} = {}) {
    if (!this.#imeProxy || !this.#imeProxyInputEnabled) {
      return;
    }
    if (queueNativeClear) {
      this.#queueM4ImeProxyClear(reason);
    }
    this.#imeProxyCompositionActive = false;
    this.#imeProxyLastCompositionText = null;
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedTransaction = null;
    this.#imeProxyLastConfirmedText = null;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyExpectedTerminalAction = null;
    this.#imeProxyNativeComposition = null;
    this.#imeProxyNativeTerminalAction = null;
    this.#imeProxy.value = "";
    this.#imeProxy.setSelectionRange(0, 0);
    this.#recordHost(`m4:ime-proxy:${reason}:cleared`);
  }

  #rejectM4ImeProxyRecord(record, reason) {
    record.reason = reason;
    if (this.#imeProxyFailure === null) {
      this.#imeProxyFailure = reason;
    }
    this.#recordImeProxy(record);
    this.#recordHost(`m4:ime-proxy:${record.type}:rejected:${reason}`);
  }

  #makeImeProxyRecord(type, event) {
    const record = {
      sequence: ++this.#imeProxySequence,
      sessionId: this.#imeProxySessionId,
      type,
      trusted: event.isTrusted === true,
      accepted: false,
      proxyFocused: document.activeElement === this.#imeProxy,
      hostWindowActive: this.#hostWindowActive,
    };
    if (typeof event.inputType === "string") {
      record.inputType = event.inputType;
    }
    if (typeof event.isComposing === "boolean") {
      record.isComposing = event.isComposing;
    }
    if (typeof event.data === "string") {
      record.text = imeProxyTextSummary(event.data);
    }
    return record;
  }

  #validateM4ImeProxyContext(record) {
    if (!record.proxyFocused) {
      this.#rejectM4ImeProxyRecord(record, "PROXY_NOT_FOCUSED");
      return false;
    }
    if (!record.hostWindowActive) {
      this.#rejectM4ImeProxyRecord(record, "OZONE_WINDOW_INACTIVE");
      return false;
    }
    if (!this.#hasM4EditableTextInputAcknowledgement()) {
      this.#rejectM4ImeProxyRecord(record, "NATIVE_TEXT_INPUT_NOT_EDITABLE");
      return false;
    }
    if (record.sessionId <= 0) {
      this.#rejectM4ImeProxyRecord(record, "NO_ACTIVE_SESSION");
      return false;
    }
    if (this.#imeProxyFailure !== null) {
      this.#rejectM4ImeProxyRecord(record, "SESSION_FAILED");
      return false;
    }
    return true;
  }

  #validateM4ImeProxyEvent(record) {
    if (!record.trusted) {
      this.#rejectM4ImeProxyRecord(record, "UNTRUSTED_DOM_EVENT");
      return false;
    }
    return this.#validateM4ImeProxyContext(record);
  }

  #validateM4ImeProxyTerminal(record) {
    // Blink intentionally dispatches compositionend through its scoped event
    // queue, which does not mark the DOM event trusted. A terminal has no
    // authority to introduce text: the caller below additionally requires the
    // exact private candidate created by prior trusted source events.
    return this.#validateM4ImeProxyContext(record);
  }

  #handleM4ImeProxyCompositionStart(event) {
    const record = this.#makeImeProxyRecord("compositionstart", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    if (this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "DUPLICATE_COMPOSITION_START");
      return;
    }
    this.#imeProxyCompositionActive = true;
    this.#imeProxyTerminalCancellationPending = false;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:compositionstart:accepted");
  }

  #handleM4ImeProxyCompositionUpdate(event) {
    const record = this.#makeImeProxyRecord("compositionupdate", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    if (!this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_UPDATE_WITHOUT_START");
      return;
    }
    if (data === "") {
      if (!this.#imeProxyNativeComposition ||
          this.#imeProxyPendingTransaction !== null ||
          this.#imeProxyLastConfirmedText !==
            this.#imeProxyNativeComposition.text) {
        this.#rejectM4ImeProxyRecord(
          record, "CANCELLATION_UPDATE_WITHOUT_CONFIRMED_COMPOSITION");
        return;
      }
      this.#imeProxyTerminalCancellationPending = true;
      record.accepted = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:compositionupdate:cancellation-pending");
      return;
    }
    if (
      data === null || data.length === 0 ||
      data.length > MAXIMUM_IME_PROXY_TEXT_UNITS ||
      !isWellFormedUtf16(data)
    ) {
      this.#rejectM4ImeProxyRecord(record, "INVALID_COMPOSITION_TEXT");
      return;
    }
    // Keep the exact browser-produced UTF-16 candidate private for the later
    // Ozone InputMethod bridge. Diagnostics expose only its bounded summary.
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyLastCompositionText = data;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:compositionupdate:accepted");
  }

  #handleM4ImeProxyBeforeInput(event) {
    const record = this.#makeImeProxyRecord("beforeinput", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    const summary = data === null ? null : imeProxyTextSummary(data);
    if (event.inputType !== "insertCompositionText") {
      this.#rejectM4ImeProxyRecord(record, "UNSUPPORTED_INPUT_TYPE");
      return;
    }
    if (event.isComposing !== true) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_FLAG_MISMATCH");
      return;
    }
    if (!this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "BEFOREINPUT_WITHOUT_COMPOSITION");
      return;
    }
    if ((data === "" || data === null) &&
        this.#imeProxyTerminalCancellationPending) {
      if (!this.#imeProxyNativeComposition ||
          this.#imeProxyPendingTransaction !== null ||
          this.#imeProxyNativeTerminalAction !== null) {
        this.#rejectM4ImeProxyRecord(
          record, "CANCELLATION_BEFOREINPUT_WITHOUT_COMPOSITION");
        return;
      }
      record.accepted = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:beforeinput:cancellation-pending");
      return;
    }
    if (this.#imeProxyPendingTransaction !== null) {
      this.#rejectM4ImeProxyRecord(record, "PENDING_TRANSACTION_EXISTS");
      return;
    }
    if (
      data === null || data.length === 0 ||
      data.length > MAXIMUM_IME_PROXY_TEXT_UNITS ||
      !isWellFormedUtf16(data) || data !== this.#imeProxyLastCompositionText
    ) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_TEXT_MISMATCH");
      return;
    }
    const transaction = {
      sessionId: this.#imeProxySessionId,
      sequence: record.sequence,
      opcode: "set-composition",
      text: data,
      textSummary: summary,
    };
    const request = this.#queueM4ImeProxyTextInput(
      M4_IME_TEXT_ACTION.setComposition,
      transaction.sessionId,
      transaction.sequence,
      transaction.text,
      {start: transaction.text.length, end: transaction.text.length},
    );
    if (!request) {
      this.#rejectM4ImeProxyRecord(record, "NATIVE_SET_QUEUE_REJECTED");
      return;
    }
    this.#imeProxyPendingTransaction = transaction;
    this.#imeProxyNativeComposition = {
      sessionId: transaction.sessionId,
      sequence: transaction.sequence,
      text: transaction.text,
      textSummary: transaction.textSummary,
    };
    this.#imeProxyNativeTerminalAction = null;
    record.nativeQueued = true;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:beforeinput:native-set-queued");
  }

  #handleM4ImeProxyInput(event) {
    const record = this.#makeImeProxyRecord("input", event);
    if (!this.#validateM4ImeProxyEvent(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    const summary = data === null ? null : imeProxyTextSummary(data);
    const pending = this.#imeProxyPendingTransaction;
    const selection = this.#imeProxySelection();
    if (event.inputType !== "insertCompositionText") {
      this.#rejectM4ImeProxyRecord(record, "UNSUPPORTED_INPUT_TYPE");
      return;
    }
    if (event.isComposing !== true) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_FLAG_MISMATCH");
      return;
    }
    if (this.#imeProxyTerminalCancellationPending) {
      const composition = this.#imeProxyNativeComposition;
      if (
        (data !== null && data !== "") || !composition || !this.#imeProxy ||
        this.#imeProxyPendingTransaction !== null ||
        this.#imeProxyNativeTerminalAction !== null ||
        this.#imeProxy.value !== "" || !selection ||
        selection.start !== 0 || selection.end !== 0
      ) {
        this.#rejectM4ImeProxyRecord(
          record, "CANCELLATION_INPUT_TRANSACTION_MISMATCH");
        return;
      }
      const request = this.#queueM4ImeProxyTextInput(
        M4_IME_TEXT_ACTION.clearComposition,
        composition.sessionId,
        record.sequence,
        "",
        {start: 0, end: 0},
      );
      if (!request) {
        this.#rejectM4ImeProxyRecord(record, "NATIVE_CLEAR_QUEUE_REJECTED");
        return;
      }
      this.#imeProxyNativeTerminalAction = request;
      this.#imeProxyExpectedTerminalAction =
        M4_IME_TEXT_ACTION.clearComposition;
      this.#imeProxyCompositionActive = false;
      this.#imeProxyTerminalCancellationPending = false;
      this.#imeProxyLastCompositionText = null;
      record.nativeQueued = true;
      record.accepted = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:input:native-clear-queued");
      return;
    }
    if (!pending || pending.sessionId !== this.#imeProxySessionId) {
      this.#rejectM4ImeProxyRecord(record, "INPUT_WITHOUT_PENDING_TRANSACTION");
      return;
    }
    if (
      data === null || data !== pending.text || !this.#imeProxy ||
      this.#imeProxy.value !== data ||
      !selection || selection.start !== data.length || selection.end !== data.length
    ) {
      this.#rejectM4ImeProxyRecord(record, "INPUT_TRANSACTION_MISMATCH");
      return;
    }
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedText = pending.text;
    this.#imeProxyLastConfirmedTransaction = {
      sessionId: pending.sessionId,
      sequence: pending.sequence,
      opcode: pending.opcode,
      text: pending.textSummary,
      rangeStart: 0,
      rangeEnd: data.length,
      selection,
    };
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:input:confirmed-native-set");
  }

  #handleM4ImeProxyCompositionEnd(event) {
    const record = this.#makeImeProxyRecord("compositionend", event);
    if (!this.#validateM4ImeProxyTerminal(record)) {
      return;
    }
    const data = typeof event.data === "string" ? event.data : null;
    if (
      this.#imeProxyExpectedTerminalAction ===
        M4_IME_TEXT_ACTION.clearComposition &&
      data === ""
    ) {
      // Empty source records already queued ClearCompositionText. Blink's
      // following terminal event is an observation only and cannot issue a
      // second native action.
      this.#imeProxyExpectedTerminalAction = null;
      record.terminalObservedAfterClear = true;
      this.#recordImeProxy(record);
      this.#recordHost("m4:ime-proxy:compositionend:clear-observed");
      return;
    }
    const composition = this.#imeProxyNativeComposition;
    if (!this.#imeProxyCompositionActive) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_WITHOUT_START");
      return;
    }
    if (this.#imeProxyPendingTransaction !== null) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_WITH_PENDING_INPUT");
      return;
    }
    if (!composition || composition.sessionId !== this.#imeProxySessionId ||
        this.#imeProxyNativeTerminalAction !== null ||
        this.#imeProxyLastConfirmedText !== composition.text) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_TRANSACTION_MISMATCH");
      return;
    }
    if (data !== composition.text) {
      this.#rejectM4ImeProxyRecord(record, "COMPOSITION_END_TRANSACTION_MISMATCH");
      return;
    }
    record.terminalDerivedFromTrustedTransaction = !record.trusted;
    const request = this.#queueM4ImeProxyTextInput(
      M4_IME_TEXT_ACTION.confirmComposition,
      composition.sessionId,
      record.sequence,
      "",
      {start: 0, end: 0},
    );
    if (!request) {
      this.#rejectM4ImeProxyRecord(record, "NATIVE_CONFIRM_QUEUE_REJECTED");
      return;
    }
    this.#imeProxyNativeTerminalAction = request;
    this.#imeProxyCompositionActive = false;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyLastCompositionText = null;
    record.nativeQueued = true;
    record.accepted = true;
    this.#recordImeProxy(record);
    this.#recordHost("m4:ime-proxy:compositionend:native-confirm-queued");
  }

  #disableM4ImeProxyInput() {
    for (const {target, type, listener} of this.#imeProxyListeners) {
      target.removeEventListener(type, listener);
    }
    this.#imeProxyListeners = [];
    this.#cancelM4ImeProxyActivation("teardown");
    this.#clearM4ImeProxyState("teardown");
    this.#imeProxyInputEnabled = false;
  }

  enableM4ImeProxyInput() {
    this.#requireRunning("enableM4ImeProxyInput");
    if (!this.#imeProxy) {
      throw new Error("M4 IME proxy is unavailable");
    }
    if (this.#imeProxyInputEnabled) {
      return this.#imeProxyInputStatus();
    }
    this.#imeProxyInputEnabled = true;
    this.#imeProxySessionId = 0;
    this.#imeProxySequence = 0;
    this.#imeProxyRecords = [];
    this.#imeProxyCompositionActive = false;
    this.#imeProxyLastCompositionText = null;
    this.#imeProxyPendingTransaction = null;
    this.#imeProxyLastConfirmedTransaction = null;
    this.#imeProxyLastConfirmedText = null;
    this.#imeProxyTerminalCancellationPending = false;
    this.#imeProxyExpectedTerminalAction = null;
    this.#imeProxyNativeRequests = [];
    this.#imeProxyNativeComposition = null;
    this.#imeProxyNativeTerminalAction = null;
    this.#imeProxyFailure = null;
    this.#imeProxyFocusCount = 0;
    this.#imeProxyBlurCount = 0;
    this.#imeProxyActivationRequest = null;
    this.#imeProxyExpectedFocusTransfer = null;
    this.#imeProxy.value = "";
    this.#imeProxy.setSelectionRange(0, 0);
    for (const [type, handler] of [
      ["compositionstart", (event) => this.#handleM4ImeProxyCompositionStart(event)],
      ["compositionupdate", (event) => this.#handleM4ImeProxyCompositionUpdate(event)],
      ["compositionend", (event) => this.#handleM4ImeProxyCompositionEnd(event)],
      ["beforeinput", (event) => this.#handleM4ImeProxyBeforeInput(event)],
      ["input", (event) => this.#handleM4ImeProxyInput(event)],
    ]) {
      this.#imeProxy.addEventListener(type, handler);
      this.#imeProxyListeners.push({target: this.#imeProxy, type, listener: handler});
    }
    const focusListener = () => {
      this.#imeProxyFocusCount += 1;
      this.#recordHost("m4:ime-proxy:focus");
    };
    this.#imeProxy.addEventListener("focus", focusListener);
    this.#imeProxyListeners.push({
      target: this.#imeProxy,
      type: "focus",
      listener: focusListener,
    });
    const blurListener = (event) => {
      this.#imeProxyBlurCount += 1;
      // Returning to the canvas must invalidate the browser-owned DOM IME
      // session even though Aura/Ozone remains active. The next click earns a
      // new native editable acknowledgement and a new proxy session.
      this.#cancelM4ImeProxyActivation("blur");
      this.#clearM4ImeProxyState("blur");
      if (event.relatedTarget === this.#canvas) {
        this.#recordHost("m4:ime-proxy:blur:canvas-return");
        return;
      }
      this.#deactivateM4HostWindow("ime-proxy-blur", event);
    };
    this.#imeProxy.addEventListener("blur", blurListener);
    this.#imeProxyListeners.push({
      target: this.#imeProxy,
      type: "blur",
      listener: blurListener,
    });
    this.#recordHost("m4:ime-proxy:listeners-attached");
    return this.#imeProxyInputStatus();
  }

  #recordFocus(record) {
    this.#focusRecords.push(record);
    if (this.#focusRecords.length > 32) {
      this.#focusRecords.shift();
    }
  }

  #focusInputStatus() {
    const queuedCount = this.#focusRecords.filter(
      (record) => record.queued === true).length;
    const trustedCount = this.#focusRecords.filter(
      (record) => record.trusted === true).length;
    return {
      enabled: this.#focusInputEnabled,
      hostWindowActive: this.#hostWindowActive,
      receivedCount: this.#focusRecords.length,
      trustedCount,
      queuedCount,
      lastQueuedFocusLoss: this.#lastQueuedFocusLoss
        ? clone(this.#lastQueuedFocusLoss)
        : null,
    };
  }

  #canvasPointForPointerEvent(event) {
    const rect = this.#canvas.getBoundingClientRect();
    const contentWidth = this.#canvas.clientWidth;
    const contentHeight = this.#canvas.clientHeight;
    if (
      !Number.isFinite(event.clientX) ||
      !Number.isFinite(event.clientY) ||
      !Number.isFinite(rect.left) ||
      !Number.isFinite(rect.top) ||
      !Number.isFinite(contentWidth) ||
      !Number.isFinite(contentHeight) ||
      contentWidth <= 0 ||
      contentHeight <= 0
    ) {
      return null;
    }
    const cssX = event.clientX - rect.left - this.#canvas.clientLeft;
    const cssY = event.clientY - rect.top - this.#canvas.clientTop;
    if (
      cssX < 0 ||
      cssY < 0 ||
      cssX >= contentWidth ||
      cssY >= contentHeight
    ) {
      return null;
    }
    const x = Math.floor((cssX * this.#canvas.width) / contentWidth);
    const y = Math.floor((cssY * this.#canvas.height) / contentHeight);
    if (
      !Number.isSafeInteger(x) ||
      !Number.isSafeInteger(y) ||
      x < 0 || y < 0 || x >= this.#canvas.width || y >= this.#canvas.height
    ) {
      return null;
    }
    return {x, y};
  }

  #releaseM4PointerCapture(pointerId) {
    if (
      typeof this.#canvas.hasPointerCapture !== "function" ||
      typeof this.#canvas.releasePointerCapture !== "function"
    ) {
      return;
    }
    try {
      if (this.#canvas.hasPointerCapture(pointerId)) {
        this.#canvas.releasePointerCapture(pointerId);
      }
    } catch (error) {
      this.#recordHost("m4:pointer:capture-release-failed");
    }
  }

  #cancelActiveM4Pointer(reason) {
    const pointerId = this.#activeM4PointerId;
    const button = this.#activeM4PointerButton;
    const point = this.#lastM4PointerPoint;
    this.#m4PointerHoverActive = false;
    if (pointerId === null || button === null) {
      return;
    }
    this.#activeM4PointerId = null;
    this.#activeM4PointerButton = null;
    this.#lastM4PointerPoint = null;
    this.#pendingM4ContextMenu = null;
    this.#releaseM4PointerCapture(pointerId);
    if (this.#lifecycle !== "running" || !point) {
      this.#recordHost(`m4:pointer:${reason}:release-skipped`);
      return;
    }
    try {
      const result = this.#callExport(
        "chromium_wasm_host_pointer",
        "number",
        ["number", "number", "number", "number"],
        [2, point.x, point.y, button],
      );
      this.#recordHost(
        `m4:pointer:${reason}:${result === 1 ? "release-queued" : "rejected"}`);
    } catch (error) {
      this.#recordHost(`m4:pointer:${reason}:release-failed`);
    }
  }

  #handleM4PointerExit(event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const pointerId = Number(event.pointerId);
    const record = {
      sequence: ++this.#pointerSequence,
      type: "exit",
      pointerId,
      trusted: event.isTrusted === true,
      queued: false,
      button: Number(event.button),
      buttons: Number(event.buttons),
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
    };
    const recordAndReject = (reason, detail) => {
      record.reason = reason;
      this.#recordPointer(record);
      this.#recordHost(`m4:pointer:exit:${detail}`);
    };
    if (!record.trusted) {
      recordAndReject("UNTRUSTED_DOM_EVENT", "untrusted");
      return;
    }
    if (
      event.pointerType !== "mouse" ||
      event.isPrimary !== true ||
      !Number.isSafeInteger(pointerId)
    ) {
      recordAndReject("UNSUPPORTED_POINTER", "unsupported-pointer");
      return;
    }
    if (
      !Number.isSafeInteger(record.button) ||
      !Number.isSafeInteger(record.buttons) ||
      record.button !== -1 ||
      record.buttons !== 0
    ) {
      recordAndReject("INVALID_BUTTON_STATE", "invalid-button-state");
      return;
    }
    // A captured drag owns its leave/release path. Only an unpressed hover
    // can yield the native host-canvas mouse exit, because its last point is
    // still inside the Wasm display.
    if (
      this.#activeM4PointerId !== null ||
      this.#activeM4PointerButton !== null ||
      !this.#m4PointerHoverActive
    ) {
      recordAndReject("NO_UNPRESSED_HOVER", "no-unpressed-hover");
      return;
    }
    try {
      const result = this.#callExport(
        "chromium_wasm_host_pointer_exit", "number", [], []);
      record.queued = result === 1;
      if (!record.queued) {
        record.reason = "QUEUE_REJECTED";
      } else {
        this.#m4PointerHoverActive = false;
        this.#lastQueuedPointer = record;
      }
    } catch (error) {
      record.reason = `EXPORT_ERROR:${String(error)}`;
    }
    this.#recordPointer(record);
    this.#recordHost(
      `m4:pointer:exit:${record.queued ? "queued" : "rejected"}`);
  }

  #handleM4PointerEvent(type, event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const pointerId = Number(event.pointerId);
    const record = {
      sequence: ++this.#pointerSequence,
      type,
      pointerId,
      trusted: event.isTrusted === true,
      queued: false,
      button: Number(event.button),
      buttons: Number(event.buttons),
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
    };
    const recordAndReject = (reason, detail) => {
      record.reason = reason;
      this.#recordPointer(record);
      this.#recordHost(`m4:pointer:${type}:${detail}`);
    };
    if (!record.trusted) {
      recordAndReject("UNTRUSTED_DOM_EVENT", "untrusted");
      return;
    }
    if (
      event.pointerType !== "mouse" ||
      event.isPrimary !== true ||
      !Number.isSafeInteger(pointerId)
    ) {
      recordAndReject("UNSUPPORTED_POINTER", "unsupported-pointer");
      return;
    }
    if (
      !Number.isSafeInteger(record.button) ||
      !Number.isSafeInteger(record.buttons) ||
      record.buttons < 0
    ) {
      recordAndReject("INVALID_BUTTON_STATE", "invalid-button-state");
      return;
    }
    if (
      (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) &&
      type !== "up" && type !== "cancel"
    ) {
      recordAndReject("UNSUPPORTED_MODIFIERS", "unsupported-modifiers");
      return;
    }
    if (
      (type === "down" || type === "up") &&
      event.button !== 0 && event.button !== 1 && event.button !== 2
    ) {
      recordAndReject("UNSUPPORTED_BUTTON", "unsupported-button");
      return;
    }
    const activePointerId = this.#activeM4PointerId;
    const activeButton = this.#activeM4PointerButton;
    if ((activePointerId === null) !== (activeButton === null)) {
      this.#cancelActiveM4Pointer("invalid-active-state");
      recordAndReject("INVALID_ACTIVE_POINTER_STATE", "invalid-active-state");
      return;
    }
    const buttonMask = (button) =>
      button === 0 ? 1 : button === 1 ? 4 : 2;
    let button;
    if (type === "down") {
      if (activePointerId !== null) {
        recordAndReject("POINTER_ALREADY_ACTIVE", "pointer-already-active");
        return;
      }
      if (record.buttons !== buttonMask(record.button)) {
        recordAndReject("INVALID_BUTTON_STATE", "invalid-button-state");
        return;
      }
      button = record.button;
    } else if (type === "move") {
      if (activePointerId === null) {
        if (record.buttons !== 0) {
          recordAndReject("UNTRACKED_BUTTON_STATE", "untracked-button-state");
          return;
        }
        button = 0;
      } else {
        if (pointerId !== activePointerId) {
          recordAndReject("POINTER_STREAM_MISMATCH", "pointer-stream-mismatch");
          return;
        }
        if (record.buttons !== buttonMask(activeButton)) {
          recordAndReject("INVALID_BUTTON_STATE", "invalid-button-state");
          return;
        }
        button = activeButton;
      }
    } else if (type === "up") {
      if (pointerId !== activePointerId) {
        recordAndReject("POINTER_STREAM_MISMATCH", "pointer-stream-mismatch");
        return;
      }
      if (record.button !== activeButton) {
        recordAndReject("POINTER_BUTTON_MISMATCH", "pointer-button-mismatch");
        return;
      }
      if ((record.buttons & buttonMask(activeButton)) !== 0) {
        recordAndReject("INVALID_POINTER_RELEASE", "invalid-pointer-release");
        return;
      }
      button = activeButton;
    } else {
      if (pointerId !== activePointerId) {
        recordAndReject("POINTER_STREAM_MISMATCH", "pointer-stream-mismatch");
        return;
      }
      button = activeButton;
    }
    const captured = activePointerId === pointerId;
    let point = this.#canvasPointForPointerEvent(event);
    if (!point && (type === "up" || type === "cancel") && captured) {
      point = this.#lastM4PointerPoint;
      record.usedCapturedPoint = point !== null;
    }
    if (!point) {
      recordAndReject("OUTSIDE_CANVAS", "outside-canvas");
      return;
    }
    let capturedOnThisEvent = false;
    if (type === "down") {
      this.#canvas.focus({preventScroll: true});
      if (typeof this.#canvas.setPointerCapture !== "function") {
        recordAndReject("HOST_CAPTURE_UNSUPPORTED", "capture-unsupported");
        return;
      }
      try {
        this.#canvas.setPointerCapture(pointerId);
        capturedOnThisEvent = true;
      } catch (error) {
        recordAndReject("HOST_CAPTURE_FAILED", "capture-failed");
        return;
      }
    } else if (captured) {
      this.#lastM4PointerPoint = point;
    }
    try {
      const eventType = {move: 0, down: 1, up: 2, cancel: 2}[type];
      const result = this.#callExport(
        "chromium_wasm_host_pointer",
        "number",
        ["number", "number", "number", "number"],
        [eventType, point.x, point.y, button],
      );
      record.x = point.x;
      record.y = point.y;
      record.queued = result === 1;
      record.canvasFocused = document.activeElement === this.#canvas;
      if (!record.queued) {
        record.reason = "QUEUE_REJECTED";
      } else {
        this.#lastQueuedPointer = record;
        if (type === "move" && activePointerId === null) {
          this.#m4PointerHoverActive = true;
        } else if (type !== "move") {
          this.#m4PointerHoverActive = false;
        }
        if (type === "down") {
          this.#activeM4PointerId = pointerId;
          this.#activeM4PointerButton = button;
          this.#lastM4PointerPoint = point;
        }
        if (type === "down" && button === 0 && this.#keyboardInputEnabled) {
          this.#keyboardActivated = true;
          this.#recordHost("m4:keyboard:pointer-activation");
        }
        if (type === "down" && button === 0 && this.#focusInputEnabled) {
          this.#hostWindowActive = true;
          this.#recordFocus({
            sequence: ++this.#focusSequence,
            type: "pointer-activation",
            trusted: record.trusted,
            queued: true,
            frameIdBefore: record.frameIdBefore,
            canvasFocused: record.canvasFocused,
            relatedTargetId: null,
          });
          this.#recordHost("m4:focus:pointer-activation");
        }
        if (type === "down" && button === 0) {
          this.#armM4ImeProxyActivation(record);
        }
        if (button === 2) {
          // A trusted, accepted secondary stream earns suppression of only
          // the embedding page's context menu. Blink receives the same native
          // Ozone mouse events and owns the in-Chromium menu transaction.
          const pending = this.#pendingM4ContextMenu;
          if (type === "up" && pending?.pointerId === pointerId &&
              pending.suppressed === true) {
            // Some browsers emit contextmenu before secondary pointerup.
            // Do not re-arm it after that one outer menu has been suppressed.
            this.#pendingM4ContextMenu = null;
          } else {
            this.#pendingM4ContextMenu = {
              pointerId,
              pointerSequence: record.sequence,
              x: point.x,
              y: point.y,
              suppressed: false,
            };
          }
        }
        if (button === 1 && event.cancelable) {
          event.preventDefault();
          record.defaultPrevented = event.defaultPrevented === true;
        }
      }
    } catch (error) {
      record.reason = `EXPORT_ERROR:${String(error)}`;
    }
    if (type === "down" && !record.queued && capturedOnThisEvent) {
      this.#releaseM4PointerCapture(pointerId);
    }
    if (type === "up" || type === "cancel") {
      if (this.#activeM4PointerId === pointerId) {
        this.#activeM4PointerId = null;
        this.#activeM4PointerButton = null;
        this.#lastM4PointerPoint = null;
      }
      this.#releaseM4PointerCapture(pointerId);
    }
    if (type === "up" && button === 0 && record.queued) {
      this.#markM4ImeProxyPointerUp(record);
    }
    this.#recordPointer(record);
    this.#recordHost(
      `m4:pointer:${type}:${record.queued ? "queued" : "rejected"}`);
  }

  #handleM4ContextMenu(event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const record = {
      sequence: ++this.#contextMenuSequence,
      trusted: event.isTrusted === true,
      button: Number(event.button),
      buttons: Number(event.buttons),
      acceptedPointer: false,
      defaultPrevented: false,
    };
    const point = this.#canvasPointForPointerEvent(event);
    if (point) {
      record.x = point.x;
      record.y = point.y;
    }
    const pending = this.#pendingM4ContextMenu;
    if (!record.trusted) {
      record.reason = "UNTRUSTED_DOM_EVENT";
    } else if (record.button !== 2 || !point || !pending ||
               pending.suppressed === true ||
               pending.x !== point.x || pending.y !== point.y) {
      record.reason = "NO_QUEUED_SECONDARY_STREAM";
    } else {
      record.acceptedPointer = true;
      if (event.cancelable) {
        event.preventDefault();
      }
      record.defaultPrevented = event.defaultPrevented === true;
      if (!record.defaultPrevented) {
        record.reason = "OUTER_CONTEXT_MENU_NOT_CANCELABLE";
      }
      this.#pendingM4ContextMenu.suppressed = true;
    }
    this.#recordM4ContextMenu(record);
    this.#recordHost(
      "m4:contextmenu:" +
      (record.acceptedPointer && record.defaultPrevented
        ? "suppressed" : "rejected"));
  }

  #disableM4PointerInput() {
    for (const {target, type, listener} of this.#pointerListeners) {
      target.removeEventListener(type, listener);
    }
    this.#cancelActiveM4Pointer("teardown");
    this.#pointerListeners = [];
    this.#pendingM4ContextMenu = null;
    this.#m4PointerHoverActive = false;
    this.#pointerInputEnabled = false;
  }

  enableM4PointerInput() {
    this.#requireRunning("enableM4PointerInput");
    if (this.#pointerInputEnabled) {
      return this.#pointerInputStatus();
    }
    for (const [domType, type] of [
      ["pointermove", "move"],
      ["pointerdown", "down"],
      ["pointerup", "up"],
      ["pointercancel", "cancel"],
    ]) {
      const listener = (event) => this.#handleM4PointerEvent(type, event);
      this.#canvas.addEventListener(domType, listener);
      this.#pointerListeners.push({
        target: this.#canvas,
        type: domType,
        listener,
      });
    }
    const lostCaptureListener = (event) => {
      if (this.#activeM4PointerId === Number(event.pointerId)) {
        this.#handleM4PointerEvent("cancel", event);
      }
    };
    this.#canvas.addEventListener("lostpointercapture", lostCaptureListener);
    this.#pointerListeners.push({
      target: this.#canvas,
      type: "lostpointercapture",
      listener: lostCaptureListener,
    });
    const pointerLeaveListener = (event) => this.#handleM4PointerExit(event);
    this.#canvas.addEventListener("pointerleave", pointerLeaveListener);
    this.#pointerListeners.push({
      target: this.#canvas,
      type: "pointerleave",
      listener: pointerLeaveListener,
    });
    const contextMenuListener = (event) => this.#handleM4ContextMenu(event);
    this.#canvas.addEventListener("contextmenu", contextMenuListener);
    this.#pointerListeners.push({
      target: this.#canvas,
      type: "contextmenu",
      listener: contextMenuListener,
    });
    const cancelOnBlur = () => this.#cancelActiveM4Pointer("blur");
    addEventListener("blur", cancelOnBlur);
    this.#pointerListeners.push({
      target: window,
      type: "blur",
      listener: cancelOnBlur,
    });
    this.#pointerInputEnabled = true;
    this.#recordHost("m4:pointer:listeners-attached");
    const cancelWhenHidden = () => {
      if (document.visibilityState !== "visible") {
        this.#cancelActiveM4Pointer("visibility-loss");
      }
    };
    document.addEventListener("visibilitychange", cancelWhenHidden);
    this.#pointerListeners.push({
      target: document,
      type: "visibilitychange",
      listener: cancelWhenHidden,
    });
    return this.#pointerInputStatus();
  }

  #handleM4WheelEvent(event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const record = {
      sequence: ++this.#wheelSequence,
      type: "wheel",
      trusted: event.isTrusted === true,
      queued: false,
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
    };
    if (!record.trusted) {
      record.reason = "UNTRUSTED_DOM_EVENT";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:untrusted");
      return;
    }
    if (!event.cancelable) {
      record.reason = "NONCANCELABLE_DOM_EVENT";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:noncancelable");
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      record.reason = "UNSUPPORTED_MODIFIERS";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:unsupported-modifiers");
      return;
    }
    if (event.deltaMode !== 0) {
      record.reason = "UNSUPPORTED_DELTA_MODE";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:unsupported-delta-mode");
      return;
    }
    const point = this.#canvasPointForPointerEvent(event);
    if (!point) {
      record.reason = "OUTSIDE_CANVAS";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:outside-canvas");
      return;
    }
    const domDeltaX = Number(event.deltaX);
    const domDeltaY = Number(event.deltaY);
    if (
      !Number.isFinite(domDeltaX) ||
      !Number.isFinite(domDeltaY)
    ) {
      record.reason = "INVALID_DELTA";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:invalid-delta");
      return;
    }
    // WheelEvent pixel deltas are CSS-DIP units. Located-event positions are
    // physical backing pixels, but Aura's root transform does not rescale
    // MouseWheelEvent offsets, so preserve DOM delta units here.
    const accumulatedX = domDeltaX + this.#wheelResidualX;
    const accumulatedY = domDeltaY + this.#wheelResidualY;
    const deltaX = Math.trunc(accumulatedX);
    const deltaY = Math.trunc(accumulatedY);
    if (
      !Number.isSafeInteger(deltaX) ||
      !Number.isSafeInteger(deltaY) ||
      deltaX < -MAXIMUM_WHEEL_DELTA ||
      deltaX > MAXIMUM_WHEEL_DELTA ||
      deltaY < -MAXIMUM_WHEEL_DELTA ||
      deltaY > MAXIMUM_WHEEL_DELTA
    ) {
      record.reason = "OUT_OF_RANGE_DELTA";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:out-of-range-delta");
      return;
    }
    record.x = point.x;
    record.y = point.y;
    record.deltaMode = event.deltaMode;
    record.domDeltaX = domDeltaX;
    record.domDeltaY = domDeltaY;
    record.deltaX = deltaX;
    record.deltaY = deltaY;
    record.canvasFocused = document.activeElement === this.#canvas;
    if (deltaX === 0 && deltaY === 0) {
      this.#wheelResidualX = accumulatedX;
      this.#wheelResidualY = accumulatedY;
      event.preventDefault();
      record.defaultPrevented = event.defaultPrevented;
      record.reason = "FRACTIONAL_DELTA_BUFFERED";
      this.#recordWheel(record);
      this.#recordHost("m4:wheel:fractional-buffered");
      return;
    }
    this.#canvas.focus({preventScroll: true});
    try {
      const result = this.#callExport(
        "chromium_wasm_host_wheel",
        "number",
        ["number", "number", "number", "number"],
        [point.x, point.y, deltaX, deltaY],
      );
      record.queued = result === 1;
      record.canvasFocused = document.activeElement === this.#canvas;
      if (record.queued) {
        this.#wheelResidualX = accumulatedX - deltaX;
        this.#wheelResidualY = accumulatedY - deltaY;
        event.preventDefault();
        record.defaultPrevented = event.defaultPrevented;
        this.#lastQueuedWheel = record;
      } else {
        record.reason = "QUEUE_REJECTED";
      }
    } catch (error) {
      record.reason = `EXPORT_ERROR:${String(error)}`;
    }
    this.#recordWheel(record);
    this.#recordHost(
      `m4:wheel:${record.queued ? "queued" : "rejected"}`);
  }

  #disableM4WheelInput() {
    for (const {target, type, listener} of this.#wheelListeners) {
      target.removeEventListener(type, listener);
    }
    this.#wheelListeners = [];
    this.#wheelInputEnabled = false;
    this.#wheelResidualX = 0;
    this.#wheelResidualY = 0;
  }

  enableM4WheelInput() {
    this.#requireRunning("enableM4WheelInput");
    if (this.#wheelInputEnabled) {
      return this.#wheelInputStatus();
    }
    const listener = (event) => this.#handleM4WheelEvent(event);
    this.#canvas.addEventListener("wheel", listener, {passive: false});
    this.#wheelListeners.push({
      target: this.#canvas,
      type: "wheel",
      listener,
    });
    this.#wheelInputEnabled = true;
    this.#recordHost("m4:wheel:listeners-attached");
    return this.#wheelInputStatus();
  }

  #releaseM4KeyboardKeys(reason, triggerEvent = null) {
    // Release non-modifier keys first, so the native Ozone state sees their
    // matching keyup while ControlLeft is still down. This is also safe for a
    // partially delivered DOM chord during blur or teardown.
    const heldCodes = Array.from(this.#keyboardCodesDown);
    const codes = [
      ...heldCodes.filter((code) => code !== M4_CONTROL_LEFT_DOM_CODE).reverse(),
      ...heldCodes.filter((code) => code === M4_CONTROL_LEFT_DOM_CODE).reverse(),
    ];
    this.#keyboardCodesDown.clear();
    this.#keyboardActivated = false;
    if (codes.length === 0) {
      return;
    }
    if (this.#lifecycle !== "running") {
      this.#recordHost("m4:keyboard:" + reason + ":release-skipped");
      return;
    }
    for (let index = 0; index < codes.length; index += 1) {
      const code = codes[index];
      const controlStillHeld =
        code !== M4_CONTROL_LEFT_DOM_CODE &&
        codes.slice(index + 1).includes(M4_CONTROL_LEFT_DOM_CODE);
      const relatedTarget = triggerEvent?.relatedTarget;
      const relatedTargetId =
        typeof Element !== "undefined" &&
        relatedTarget instanceof Element && relatedTarget.id
          ? relatedTarget.id
          : null;
      const record = {
        sequence: ++this.#keyboardSequence,
        type: "up",
        code,
        key: expectedM4KeyboardKey(code) ?? "",
        trusted: false,
        queued: false,
        generated: true,
        trigger: reason,
        triggerTrusted: triggerEvent?.isTrusted === true,
        relatedTargetId,
        repeat: false,
        isComposing: false,
        modifiers: {
          alt: false,
          control: controlStillHeld,
          meta: false,
          shift: false,
        },
        frameIdBefore: this.#frame?.id ?? 0,
        canvasFocused: document.activeElement === this.#canvas,
        pointerActivated: false,
      };
      try {
        const result = this.#callExport(
          "chromium_wasm_host_key",
          "number",
          ["string", "number"],
          [code, 0],
        );
        record.queued = result === 1;
        if (record.queued) {
          this.#lastQueuedKeyUp = record;
        } else {
          record.reason = "QUEUE_REJECTED";
        }
        this.#recordHost(
          "m4:keyboard:" + reason + ":" +
          (record.queued ? "release-queued" : "release-rejected"));
      } catch (error) {
        record.reason = "EXPORT_ERROR:" + String(error);
        this.#recordHost("m4:keyboard:" + reason + ":release-failed");
      }
      this.#recordKeyboard(record);
    }
  }

  #handleM4KeyboardEvent(type, event) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const code = typeof event.code === "string" ? event.code : "";
    const key = typeof event.key === "string" ? event.key : "";
    const record = {
      sequence: ++this.#keyboardSequence,
      type,
      code,
      key,
      trusted: event.isTrusted === true,
      queued: false,
      repeat: event.repeat === true,
      isComposing: event.isComposing === true,
      modifiers: {
        alt: event.altKey === true,
        control: event.ctrlKey === true,
        meta: event.metaKey === true,
        shift: event.shiftKey === true,
      },
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
      pointerActivated: this.#keyboardActivated,
    };
    if (!record.trusted) {
      record.reason = "UNTRUSTED_DOM_EVENT";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":untrusted");
      return;
    }
    if (!event.cancelable) {
      record.reason = "NONCANCELABLE_DOM_EVENT";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":noncancelable");
      return;
    }
    if (!record.canvasFocused) {
      record.reason = "CANVAS_NOT_FOCUSED";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":canvas-not-focused");
      return;
    }
    if (!record.pointerActivated) {
      record.reason = "NO_POINTER_ACTIVATION";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":no-pointer-activation");
      return;
    }
    if (
      record.modifiers.alt ||
      record.modifiers.meta ||
      record.modifiers.shift
    ) {
      record.reason = "UNSUPPORTED_MODIFIERS";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-modifiers");
      return;
    }
    const controlHeld = this.#keyboardCodesDown.has(
      M4_CONTROL_LEFT_DOM_CODE);
    if (record.code === M4_CONTROL_LEFT_DOM_CODE) {
      // DOM reports Control as down on its keydown and not down on its keyup.
      if (record.modifiers.control !== (type === "down")) {
        record.reason = "INVALID_CONTROL_STATE";
        this.#recordKeyboard(record);
        this.#recordHost("m4:keyboard:" + type + ":invalid-control-state");
        return;
      }
    } else if (isM4CopyPasteShortcutCode(record.code)) {
      // Admit only C/V while this bounded physical ControlLeft record is
      // active. A late C/V keyup is allowed after Control's own release so
      // focus-loss cleanup cannot leave the browser input state stuck.
      if (
        (type === "down" && !controlHeld) ||
        record.modifiers.control !== controlHeld
      ) {
        record.reason = "UNSUPPORTED_SHORTCUT_STATE";
        this.#recordKeyboard(record);
        this.#recordHost(
          "m4:keyboard:" + type + ":unsupported-shortcut-state");
        return;
      }
    } else if (record.modifiers.control) {
      record.reason = "UNSUPPORTED_MODIFIERS";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-modifiers");
      return;
    }
    if (
      record.isComposing ||
      record.key === "Dead" ||
      record.key === "Process"
    ) {
      record.reason = "UNSUPPORTED_COMPOSITION";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-composition");
      return;
    }
    const expectedKey = expectedM4KeyboardKey(record.code);
    if (expectedKey === null) {
      record.reason = "UNSUPPORTED_DOM_CODE";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-code");
      return;
    }
    if (record.key !== expectedKey) {
      record.reason = "UNSUPPORTED_DOM_KEY";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-key");
      return;
    }
    // A supplied repeat remains a physical DOM key record. The two admitted
    // repeat experiments are ArrowDown navigation and Backspace deletion;
    // each is forwarded through its own fixed-purpose C ABI rather than
    // synthesized by the host. All other repeated, unmatched, or keyup
    // records are rejected.
    const arrowDownRepeat = type === "down" && record.repeat &&
      record.code === M4_KEYBOARD_DOM_CODE &&
      this.#keyboardCodesDown.has(record.code);
    const backspaceRepeat = type === "down" && record.repeat &&
      record.code === M4_BACKSPACE_DOM_CODE &&
      this.#keyboardCodesDown.has(record.code);
    const boundedRepeat = arrowDownRepeat || backspaceRepeat;
    if (record.repeat && !boundedRepeat) {
      record.reason = "UNSUPPORTED_REPEAT";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:" + type + ":unsupported-repeat");
      return;
    }
    if (type === "down" && this.#keyboardCodesDown.has(record.code) &&
        !arrowDownRepeat && !backspaceRepeat) {
      record.reason = "DUPLICATE_DOWN";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:down:duplicate");
      return;
    }
    if (type === "up" && !this.#keyboardCodesDown.has(record.code)) {
      record.reason = "UNMATCHED_UP";
      this.#recordKeyboard(record);
      this.#recordHost("m4:keyboard:up:unmatched");
      return;
    }
    try {
      let result;
      if (arrowDownRepeat) {
        result = this.#callExport(
            "chromium_wasm_host_arrow_down_repeat", "number", [], []);
      } else if (backspaceRepeat) {
        result = this.#callExport(
            "chromium_wasm_host_backspace_repeat", "number", [], []);
      } else {
        result = this.#callExport(
            "chromium_wasm_host_key",
            "number",
            ["string", "number"],
            [record.code, type === "down" ? 1 : 0],
        );
      }
      record.queued = result === 1;
      if (record.queued) {
        if (type === "down") {
          if (!arrowDownRepeat && !backspaceRepeat) {
            this.#keyboardCodesDown.add(record.code);
          }
          this.#lastQueuedKeyDown = record;
        } else {
          this.#keyboardCodesDown.delete(record.code);
          this.#lastQueuedKeyUp = record;
        }
        event.preventDefault();
        record.defaultPrevented = event.defaultPrevented;
      } else {
        record.reason = "QUEUE_REJECTED";
      }
    } catch (error) {
      record.reason = "EXPORT_ERROR:" + String(error);
    }
    this.#recordKeyboard(record);
    this.#recordHost(
      "m4:keyboard:" + (boundedRepeat ? "repeat" : type) + ":" +
      (record.queued ? "queued" : "rejected"));
  }

  #disableM4KeyboardInput() {
    for (const {target, type, listener} of this.#keyboardListeners) {
      target.removeEventListener(type, listener);
    }
    this.#keyboardListeners = [];
    this.#releaseM4KeyboardKeys("teardown");
    this.#keyboardInputEnabled = false;
  }

  enableM4KeyboardInput() {
    this.#requireRunning("enableM4KeyboardInput");
    if (this.#keyboardInputEnabled) {
      return this.#keyboardInputStatus();
    }
    for (const [domType, type] of [["keydown", "down"], ["keyup", "up"]]) {
      const listener = (event) => this.#handleM4KeyboardEvent(type, event);
      this.#canvas.addEventListener(domType, listener);
      this.#keyboardListeners.push({
        target: this.#canvas,
        type: domType,
        listener,
      });
    }
    this.#keyboardInputEnabled = true;
    this.#recordHost("m4:keyboard:listeners-attached");
    return this.#keyboardInputStatus();
  }

  #deactivateM4HostWindow(reason, event = null) {
    if (this.#lifecycle !== "running") {
      return;
    }
    const relatedTarget = event?.relatedTarget;
    const relatedTargetId =
      typeof Element !== "undefined" &&
      relatedTarget instanceof Element && relatedTarget.id
        ? relatedTarget.id
        : null;
    const record = {
      sequence: ++this.#focusSequence,
      type: reason,
      trusted: event?.isTrusted === true,
      queued: false,
      frameIdBefore: this.#frame?.id ?? 0,
      canvasFocused: document.activeElement === this.#canvas,
      relatedTargetId,
    };

    if (this.#consumeM4ExpectedProxyFocusTransfer(relatedTarget)) {
      record.internalTransfer = true;
      record.reason = "EXPECTED_PROXY_FOCUS_TRANSFER";
      this.#recordFocus(record);
      this.#recordHost(`m4:focus:${reason}:expected-proxy-transfer`);
      return;
    }

    // Releases must run while ozone_wasm still has its keyboard target. The
    // UI task queue preserves this ordering before the later deactivation.
    this.#cancelM4ImeProxyActivation(reason);
    this.#clearM4ImeProxyState(reason);
    this.#cancelActiveM4Pointer(reason);
    this.#releaseM4KeyboardKeys(reason, event);
    if (!this.#focusInputEnabled) {
      record.reason = "FOCUS_INPUT_DISABLED";
      this.#recordFocus(record);
      return;
    }
    if (!this.#hostWindowActive) {
      record.reason = "DUPLICATE_FOCUS_LOSS";
      this.#recordFocus(record);
      this.#recordHost("m4:focus:" + reason + ":duplicate");
      return;
    }
    record.ozoneFocusReportSequenceBefore = this.#ozoneFocusReportSequence;
    this.#ozoneFocusState = null;
    try {
      const result = this.#callExport(
        "chromium_wasm_host_deactivate", "number", [], []);
      record.queued = result === 1;
      if (record.queued) {
        this.#hostWindowActive = false;
        this.#lastQueuedFocusLoss = record;
      } else {
        record.reason = "QUEUE_REJECTED";
      }
    } catch (error) {
      record.reason = "EXPORT_ERROR:" + String(error);
    }
    this.#recordFocus(record);
    this.#recordHost(
      "m4:focus:" + reason + ":" +
      (record.queued ? "deactivate-queued" : "deactivate-rejected"));
  }

  #disableM4FocusInput() {
    for (const {target, type, listener} of this.#focusListeners) {
      target.removeEventListener(type, listener);
    }
    this.#focusListeners = [];
    this.#deactivateM4HostWindow("teardown");
    this.#focusInputEnabled = false;
  }

  enableM4FocusInput() {
    this.#requireRunning("enableM4FocusInput");
    if (this.#focusInputEnabled) {
      return this.#focusInputStatus();
    }
    this.#focusInputEnabled = true;
    this.#hostWindowActive = document.activeElement === this.#canvas;
    const canvasBlurListener = (event) => {
      this.#deactivateM4HostWindow("canvas-blur", event);
    };
    this.#canvas.addEventListener("blur", canvasBlurListener);
    this.#focusListeners.push({
      target: this.#canvas,
      type: "blur",
      listener: canvasBlurListener,
    });
    const windowBlurListener = (event) => {
      this.#deactivateM4HostWindow("window-blur", event);
    };
    addEventListener("blur", windowBlurListener);
    this.#focusListeners.push({
      target: window,
      type: "blur",
      listener: windowBlurListener,
    });
    const visibilityListener = (event) => {
      if (document.visibilityState !== "visible") {
        this.#deactivateM4HostWindow("visibility-loss", event);
      }
    };
    document.addEventListener("visibilitychange", visibilityListener);
    this.#focusListeners.push({
      target: document,
      type: "visibilitychange",
      listener: visibilityListener,
    });
    this.#recordHost("m4:focus:listeners-attached");
    return this.#focusInputStatus();
  }

  #heartbeat() {
    if (this.#heartbeatAnchor === null) {
      return {
        anchor: null,
        elapsedMs: 0,
        timerStartTicks: this.#timerTicks,
        timerEndTicks: this.#timerTicks,
        timerDelta: 0,
        animationFrameStartTicks: this.#animationFrameTicks,
        animationFrameEndTicks: this.#animationFrameTicks,
        animationFrameDelta: 0,
        maxTimerGapMs: 0,
      };
    }
    return {
      anchor: this.#heartbeatAnchor,
      elapsedMs: performance.now() - this.#heartbeatStartTime,
      timerStartTicks: this.#heartbeatStartTimerTicks,
      timerEndTicks: this.#timerTicks,
      timerDelta: this.#timerTicks - this.#heartbeatStartTimerTicks,
      animationFrameStartTicks: this.#heartbeatStartAnimationFrameTicks,
      animationFrameEndTicks: this.#animationFrameTicks,
      animationFrameDelta:
        this.#animationFrameTicks - this.#heartbeatStartAnimationFrameTicks,
      maxTimerGapMs: this.#maximumTimerGapMs,
    };
  }

  #requireRunning(operation) {
    if (this.#lifecycle !== "running" || !this.#module) {
      throw new Error(`${operation} requires an initialized M3 runtime`);
    }
  }

  #sampleLinearMemoryBytes(description) {
    const byteLength = this.#module?.HEAPU8?.buffer?.byteLength;
    if (!Number.isSafeInteger(byteLength) || byteLength <= 0) {
      throw new Error(
        `${description} linear memory must have a positive safe byte length`);
    }
    if (byteLength % WASM_PAGE_BYTES !== 0) {
      throw new Error(
        `${description} linear memory must be aligned to 64 KiB pages`);
    }
    return byteLength;
  }

  #findCommand(name) {
    const commands = this.#module?.chromiumWasmHostCommands;
    if (commands && typeof commands[name] === "function") {
      return (...args) => commands[name](...args);
    }
    return null;
  }

  #callExport(name, returnType, argumentTypes, args) {
    const command = this.#findCommand(name);
    if (command) {
      return command(...args);
    }
    if (typeof this.#module?.ccall === "function") {
      return this.#module.ccall(name, returnType, argumentTypes, args);
    }
    const direct = this.#module?.[`_${name}`];
    if (typeof direct !== "function") {
      throw new Error(`required runtime export is missing: ${name}`);
    }
    if (
      !argumentTypes.includes("string") &&
      !argumentTypes.includes("array")
    ) {
      return direct(...args);
    }
    if (
      typeof this.#module._malloc !== "function" ||
      typeof this.#module._free !== "function" ||
      !this.#module.HEAPU8
    ) {
      throw new Error(
        `runtime export ${name} needs ccall or malloc string/array support`);
    }
    const allocated = [];
    try {
      const converted = args.map((value, index) => {
        const argumentType = argumentTypes[index];
        if (argumentType !== "string" && argumentType !== "array") {
          return value;
        }
        const encoded = argumentType === "string"
          ? UTF8_ENCODER.encode(`${value}\0`)
          : value instanceof Uint8Array
            ? value
            : null;
        if (encoded === null) {
          throw new Error(`runtime export ${name} needs a Uint8Array argument`);
        }
        if (encoded.byteLength === 0) {
          return 0;
        }
        const pointer = this.#module._malloc(encoded.length);
        if (!pointer) {
          throw new Error(`allocation failed while calling ${name}`);
        }
        allocated.push(pointer);
        // Fetch HEAPU8 after malloc because memory growth invalidates old views.
        const heap = this.#module.HEAPU8;
        if (!(heap instanceof Uint8Array) || pointer + encoded.length > heap.length) {
          throw new Error(`runtime heap changed while calling ${name}`);
        }
        heap.set(encoded, pointer);
        return pointer;
      });
      return direct(...converted);
    } finally {
      for (const pointer of allocated) {
        this.#module._free(pointer);
      }
    }
  }

  async initialize({
    modulePath,
    readyTimeoutMs = DEFAULT_RUNTIME_REGISTRATION_TIMEOUT_MS,
    wisp = undefined,
  }) {
    if (this.#lifecycle !== "new") {
      throw new Error("initialize may only be called once");
    }
    if (!crossOriginIsolated) {
      throw new Error("M3 host is not cross-origin isolated");
    }
    if (typeof SharedArrayBuffer !== "function") {
      throw new Error("SharedArrayBuffer is unavailable");
    }
    if (
      !Number.isFinite(readyTimeoutMs) ||
      readyTimeoutMs < 1000 ||
      readyTimeoutMs > 60000
    ) {
      throw new Error("initialize readyTimeoutMs is out of range");
    }
    const resolvedModule = new URL(modulePath, document.baseURI);
    if (resolvedModule.origin !== location.origin) {
      throw new Error("M3 module must be served from the host origin");
    }
    const wispConfiguration = normalizeWispConfiguration(wisp);
    this.#wispConfigured = Boolean(wispConfiguration);
    this.#lifecycle = "initializing";
    this.#canvas.focus();
    if (document.activeElement !== this.#canvas) {
      throw new Error("M3 canvas did not accept focus");
    }
    this.#recordHost("initialize:start");

    let moduleScriptBlob = null;
    if (resolvedModule.protocol !== "file:") {
      const moduleResponse = await fetch(
        resolvedModule.href, {cache: "no-store"});
      if (!moduleResponse.ok) {
        throw new Error(
          `M3 module request returned HTTP ${moduleResponse.status}`);
      }
      moduleScriptBlob = await moduleResponse.blob();
      if (moduleScriptBlob.size === 0) {
        throw new Error("M3 module loader is empty");
      }
    }
    const moduleOptions = {
      canvas: this.#canvas,
      // EXIT_RUNTIME tears down the prewarmed pthread pool after main returns.
      // Keep this false so shutdown can require Emscripten's final onExit.
      noExitRuntime: false,
      locateFile: (path) => new URL(path, resolvedModule).href,
      print: (line) => this.#logs.stdout.push(String(line)),
      printErr: (line) => this.#logs.stderr.push(String(line)),
      onRuntimeInitialized: () => {
        this.#runtimeInitialized = true;
        this.#recordHost("runtime:initialized");
      },
      onAbort: (reason) => {
        this._reportFatal(`abort: ${String(reason)}`);
      },
      onExit: (code) => {
        this._reportRuntimeExit(code);
      },
    };
    if (moduleScriptBlob) {
      // Pinned Emscripten's ES-module pthread path consumes this Blob when it
      // creates each worker. Reusing the already-fetched source avoids a burst
      // of independent worker-module requests and their unresolved
      // loading-workers dependencies.
      moduleOptions.mainScriptUrlOrBlob = moduleScriptBlob;
    }
    if (wispConfiguration) {
      moduleOptions.chromiumWasmWisp = wispConfiguration;
      this.#recordHost("initialize:wisp-configured");
    }
    // Keep the main module on its original URL so Emscripten resolves and
    // streams the large Wasm binary with the same origin and base URL. Only
    // pthread workers consume the Blob above.
    const namespace = await import(resolvedModule.href);
    if (typeof namespace.default !== "function") {
      throw new Error("M3 module loader has no default factory export");
    }
    this.#module = await namespace.default(moduleOptions);
    this.#initialLinearMemoryBytes =
      this.#sampleLinearMemoryBytes("initial");
    this.#module.chromiumWasmHostBridge =
      globalThis.__chromiumWasmHostBridgeV1;
    this.#runtimeInitialized = true;
    const registrationDeadline = performance.now() + readyTimeoutMs;
    while (this.#reportedReadiness.shellReady !== true) {
      if (this.#fatalErrors.length > 0) {
        throw new Error(
          `runtime failed before shell registration: ${
            this.#fatalErrors.join("; ")}`);
      }
      if (performance.now() >= registrationDeadline) {
        throw new Error(
          "runtime did not register the Chromium UI runner before timeout");
      }
      await delay(25);
    }
    this.#lifecycle = "running";
    this.#recordHost("initialize:complete");
    return {
      ok: true,
      protocol: HOST_PROTOCOL,
      runtimeInitialized: true,
      shellReady: true,
      canvasFocused: document.activeElement === this.#canvas,
      versions: clone(this.#versions),
    };
  }

  async resize(width, height, devicePixelRatio = 1) {
    this.#requireRunning("resize");
    checkInteger(width, "width", 1, 16384);
    checkInteger(height, "height", 1, 16384);
    if (devicePixelRatio !== 1 && devicePixelRatio !== 2) {
      throw new Error("host only supports devicePixelRatio 1 or 2");
    }
    const physicalWidth = width * devicePixelRatio;
    const physicalHeight = height * devicePixelRatio;
    if (
      !Number.isSafeInteger(physicalWidth) ||
      !Number.isSafeInteger(physicalHeight) ||
      physicalWidth > 16384 || physicalHeight > 16384 ||
      physicalWidth * physicalHeight * 4 * 2 > 128 * 1024 * 1024
    ) {
      throw new Error("resize physical canvas exceeds the host storage limit");
    }
    const result = this.#callExport(
      "chromium_wasm_host_resize",
      "number",
      ["number", "number", "number"],
      [width, height, devicePixelRatio],
    );
    if (result !== 1) {
      throw new Error(`runtime rejected resize with status ${String(result)}`);
    }
    // The public dimensions are CSS DIPs. The canvas backing store and all
    // Ozone input coordinates remain physical pixels at the selected scale.
    this.#canvas.width = physicalWidth;
    this.#canvas.height = physicalHeight;
    this.#canvas.style.width = `${width}px`;
    this.#canvas.style.height = `${height}px`;
    this.#currentDevicePixelRatio = devicePixelRatio;
    this.#recordHost(`resize:${width}x${height}@${devicePixelRatio}`);
    return {
      ok: true,
      width,
      height,
      devicePixelRatio,
      physicalWidth,
      physicalHeight,
    };
  }

  async loadURL(url) {
    this.#requireRunning("loadURL");
    const parsed = new URL(url);
    if (parsed.protocol !== "data:") {
      throw new Error("M3 only permits a deterministic data: navigation");
    }
    const result = this.#callExport(
      "chromium_wasm_host_load_url",
      "number",
      ["string"],
      [url],
    );
    if (result !== 1) {
      throw new Error(
        `runtime rejected data: navigation with status ${String(result)}`);
    }
    this.#recordHost("navigation:requested:data");
    return {ok: true, scheme: "data"};
  }

  async loadM5PlaintextHttpControlURL(url) {
    this.#requireRunning("loadM5PlaintextHttpControlURL");
    if (!this.#wispConfigured) {
      throw new Error("M5 network navigation requires a WISP configuration");
    }
    const testURL = normalizeM5PlaintextHttpControlURL(url);
    if (
      this.#m5NetworkNavigationCount !== 0 ||
      this.#m5NetworkPhase !== M5_NAVIGATION_PHASE.NONE
    ) {
      throw new Error("M5 plaintext HTTP control must be the first navigation");
    }
    return this.#postM5TestNavigation({
      testURL,
      exportName: "chromium_wasm_host_load_m5_plaintext_http_control_url",
      phase: M5_NAVIGATION_PHASE.PLAINTEXT_HTTP_CONTROL,
      scheme: "http",
      requestedLog: "navigation:requested:m5-plaintext-http-control",
    });
  }

  async loadM5NetworkURL(url) {
    this.#requireRunning("loadM5NetworkURL");
    if (!this.#wispConfigured) {
      throw new Error("M5 network navigation requires a WISP configuration");
    }
    const testURL = normalizeM5NetworkTestURL(url);
    let phase;
    let requestedLog;
    if (this.#m5NetworkPhase === M5_NAVIGATION_PHASE.PLAINTEXT_HTTP_CONTROL) {
      if (
        this.#m5NetworkNavigationCount !== 1 ||
        this.#navigation.committed !== true ||
        this.#navigation.scheme !== "http" ||
        !hasM5PlaintextHttpControlPageProbe(this.#pageProbe)
      ) {
        throw new Error(
          "M5 HTTPS navigation requires a committed plaintext HTTP control");
      }
      phase = M5_NAVIGATION_PHASE.HTTPS_FIXTURE;
      requestedLog = "navigation:requested:m5-https";
    } else if (this.#m5NetworkPhase === M5_NAVIGATION_PHASE.HTTPS_FIXTURE) {
      if (
        this.#m5NetworkNavigationCount !== 2 ||
        this.#navigation.committed !== true ||
        this.#navigation.scheme !== "https" ||
        !hasM5NetworkPageProbe(this.#pageProbe)
      ) {
        throw new Error(
          "M5 TLS rejection navigation requires an initial HTTPS fixture " +
          "commit");
      }
      phase = M5_NAVIGATION_PHASE.TLS_NAME_MISMATCH;
      requestedLog = "navigation:requested:m5-https-tls-failure";
    } else {
      throw new Error(
        "M5 HTTPS navigation requires the plaintext-control then HTTPS phases");
    }
    return this.#postM5TestNavigation({
      testURL,
      exportName: "chromium_wasm_host_load_m5_url",
      phase,
      scheme: "https",
      requestedLog,
    });
  }

  #postM5TestNavigation({testURL, exportName, phase, scheme, requestedLog}) {
    const previousM5NetworkTestActive = this.#m5NetworkTestActive;
    const previousM5NetworkNavigationCount = this.#m5NetworkNavigationCount;
    const previousM5NetworkPhase = this.#m5NetworkPhase;
    const previousNavigation = this.#navigation;
    const previousPageProbe = this.#pageProbe;
    // The C ABI posts work to Chromium's UI sequence. Arm the exact phase
    // before posting so a proxied report cannot race the host-side gate.
    this.#m5NetworkTestActive = true;
    ++this.#m5NetworkNavigationCount;
    this.#m5NetworkPhase = phase;
    this.#navigation = {};
    this.#pageProbe = {};
    let result;
    try {
      result = this.#callExport(exportName, "number", ["string"], [testURL]);
    } catch (error) {
      this.#restoreM5TestNavigation({
        active: previousM5NetworkTestActive,
        count: previousM5NetworkNavigationCount,
        phase: previousM5NetworkPhase,
        navigation: previousNavigation,
        pageProbe: previousPageProbe,
      });
      throw error;
    }
    if (result !== 1) {
      this.#restoreM5TestNavigation({
        active: previousM5NetworkTestActive,
        count: previousM5NetworkNavigationCount,
        phase: previousM5NetworkPhase,
        navigation: previousNavigation,
        pageProbe: previousPageProbe,
      });
      throw new Error(
        `runtime rejected M5 ${scheme.toUpperCase()} navigation with status ` +
        String(result));
    }
    this.#recordHost(requestedLog);
    return {ok: true, scheme, hostname: M5_NETWORK_TEST_HOSTNAME};
  }

  #restoreM5TestNavigation({active, count, phase, navigation, pageProbe}) {
    this.#m5NetworkTestActive = active;
    this.#m5NetworkNavigationCount = count;
    this.#m5NetworkPhase = phase;
    this.#navigation = navigation;
    this.#pageProbe = pageProbe;
  }

  async injectInput(event) {
    this.#requireRunning("injectInput");
    if (this.#currentDevicePixelRatio !== 1) {
      throw new Error("M3 input only supports devicePixelRatio 1");
    }
    if (
      !event ||
      event.type !== "click" ||
      event.button !== 0
    ) {
      throw new Error("M3 input only supports a primary-button click");
    }
    const x = checkInteger(event.x, "input x", 0, DEFAULT_WIDTH - 1);
    const y = checkInteger(event.y, "input y", 0, DEFAULT_HEIGHT - 1);
    if (
      this.#pageProbe.inputClicks !== 0 ||
      this.#pageProbe.inputTrusted !== false ||
      this.#pageProbe.buttonText !== "READY"
    ) {
      throw new Error(
        "M3 input requires a pristine READY fixture probe");
    }
    const previousInputPostedAtFrameId = this.#inputPostedAtFrameId;
    const previousInteractionObservedAtFrameId =
      this.#interactionObservedAtFrameId;
    this.#inputPostedAtFrameId = this.#frame?.id ?? 0;
    this.#interactionObservedAtFrameId = null;
    let result;
    try {
      result = this.#callExport(
        "chromium_wasm_host_click",
        "number",
        ["number", "number", "number"],
        [x, y, event.button],
      );
    } catch (error) {
      this.#inputPostedAtFrameId = previousInputPostedAtFrameId;
      this.#interactionObservedAtFrameId =
        previousInteractionObservedAtFrameId;
      throw error;
    }
    if (result !== 1) {
      this.#inputPostedAtFrameId = previousInputPostedAtFrameId;
      this.#interactionObservedAtFrameId =
        previousInteractionObservedAtFrameId;
      throw new Error(
        `runtime rejected primary click with status ${String(result)}`);
    }
    this.#recordHost(`input:click:${x},${y}`);
    return {
      ok: true,
      accepted: true,
      code: "CLICK_POSTED",
      eventType: "click",
      x,
      y,
      button: 0,
    };
  }

  async requestScreenshot() {
    this.#requireRunning("requestScreenshot");
    if (!this.#frame) {
      throw new Error("cannot capture before the first compositor frame");
    }
    const dataURL = this.#canvas.toDataURL("image/png");
    const prefix = "data:image/png;base64,";
    if (!dataURL.startsWith(prefix)) {
      throw new Error("canvas did not produce a PNG screenshot");
    }
    return {
      ok: true,
      mimeType: "image/png",
      width: this.#canvas.width,
      height: this.#canvas.height,
      frame: clone(this.#frame),
      dataBase64: dataURL.slice(prefix.length),
    };
  }

  async readiness() {
    this.#requireRunning("readiness");
    const heartbeat = this.#heartbeat();
    const frameMatchesCanvas =
      this.#frame &&
      this.#frame.width === this.#canvas.width &&
      this.#frame.height === this.#canvas.height;
    const pageTimerTicks = Number(this.#pageProbe.timerTicks);
    const baseReady =
      this.#runtimeInitialized &&
      this.#reportedReadiness.shellReady === true &&
      this.#reportedReadiness.surfaceReady === true &&
      this.#navigation.committed === true &&
      this.#reportedReadiness.firstVisuallyNonEmptyPaint === true &&
      this.#pageProbe.ready === true &&
      Number.isFinite(pageTimerTicks) &&
      pageTimerTicks >= 3 &&
      Boolean(frameMatchesCanvas);
    const interactionReady =
      this.#pageProbe.inputClicks === 1 &&
      this.#pageProbe.inputTrusted === true &&
      this.#pageProbe.buttonText === "CLICKED" &&
      Number.isSafeInteger(this.#inputPostedAtFrameId) &&
      Number.isSafeInteger(this.#interactionObservedAtFrameId) &&
      Boolean(this.#frame) &&
      this.#frame.id > this.#interactionObservedAtFrameId;
    const ready =
      baseReady &&
      interactionReady &&
      heartbeat.elapsedMs >= REQUIRED_RUNTIME_MS &&
      heartbeat.timerDelta >= REQUIRED_TIMER_TICKS &&
      heartbeat.animationFrameDelta >= REQUIRED_ANIMATION_FRAMES &&
      heartbeat.maxTimerGapMs <= MAXIMUM_TIMER_GAP_MS &&
      this.#fatalErrors.length === 0;
    return {
      protocol: HOST_PROTOCOL,
      ready,
      baseReady,
      interactionReady,
      runtimeInitialized: this.#runtimeInitialized,
      shellReady: this.#reportedReadiness.shellReady === true,
      surfaceReady: this.#reportedReadiness.surfaceReady === true,
      navigationCommitted: this.#navigation.committed === true,
      firstVisuallyNonEmptyPaint:
        this.#reportedReadiness.firstVisuallyNonEmptyPaint === true,
      pageReady: this.#pageProbe.ready === true,
      navigation: clone(this.#navigation),
      pageProbe: clone(this.#pageProbe),
      ozoneFocusState: this.#ozoneFocusState
        ? clone(this.#ozoneFocusState)
        : null,
      ozoneFocusReports: clone(this.#ozoneFocusReports),
      ozoneCursor: this.#ozoneCursor ? clone(this.#ozoneCursor) : null,
      ozoneTextInputState: this.#ozoneTextInputState
        ? clone(this.#ozoneTextInputState)
        : null,
      frame: this.#frame ? clone(this.#frame) : null,
      inputPostedAtFrameId: this.#inputPostedAtFrameId,
      interactionObservedAtFrameId: this.#interactionObservedAtFrameId,
      fatalErrors: clone(this.#fatalErrors),
      heartbeat,
      pointerInput: this.#pointerInputStatus(),
      wheelInput: this.#wheelInputStatus(),
      keyboardInput: this.#keyboardInputStatus(),
      focusInput: this.#focusInputStatus(),
      imeProxyInput: this.#imeProxyInputStatus(),
    };
  }

  async logs() {
    return clone(this.#logs);
  }

  async shutdown(timeoutMs = DEFAULT_SHUTDOWN_TIMEOUT_MS) {
    this.#requireRunning("shutdown");
    if (
      !Number.isFinite(timeoutMs) ||
      timeoutMs < 1000 ||
      timeoutMs > 60000
    ) {
      throw new Error("shutdown timeoutMs is out of range");
    }
    this.#cancelActiveM4Pointer("shutdown");
    this.#releaseM4KeyboardKeys("shutdown");
    this.#deactivateM4HostWindow("shutdown");
    this.#lifecycle = "shutting-down";
    let result;
    try {
      result = this.#callExport(
        "chromium_wasm_host_shutdown", "number", [], []);
    } catch (error) {
      this.#lifecycle = "running";
      throw error;
    }
    if (result !== 1) {
      this.#lifecycle = "running";
      throw new Error(
        `runtime rejected shutdown with status ${String(result)}`);
    }
    this.#recordHost("shutdown:accepted");
    let timeoutHandle;
    const timeout = new Promise((_, reject) => {
      timeoutHandle = setTimeout(() => {
        reject(
          new Error(
            "Content Shell did not complete shutdown before timeout"));
      }, timeoutMs);
    });
    try {
      const [processExit, runtimeExit] = await Promise.race([
        Promise.all([
          this.#processExitPromise,
          this.#runtimeExitPromise,
        ]),
        timeout,
      ]);
      if (processExit.exitCode !== 0) {
        throw new Error(
          `Content Shell exited with status ${processExit.exitCode}`);
      }
      if (runtimeExit.exitCode !== processExit.exitCode) {
        throw new Error(
          "Emscripten runtime exit did not match Content Shell exit");
      }
      if (runtimeExit.sequence <= processExit.sequence) {
        throw new Error(
          "Emscripten runtime exited before Content Shell completed");
      }
      // Emscripten calls onExit only after requesting termination of every
      // running and prewarmed pthread worker. Let those asynchronous browser
      // worker terminations and any trailing rejection surface before
      // certifying teardown.
      await delay(25);
      if (this.#fatalErrors.length > 0) {
        throw new Error(
          `Content Shell teardown reported: ${this.#fatalErrors.join("; ")}`);
      }
      // WebAssembly linear memory cannot shrink, so a fresh post-teardown
      // view reports the peak byte length reached during this lifecycle.
      const peakLinearMemoryBytes =
        this.#sampleLinearMemoryBytes("post-shutdown");
      if (peakLinearMemoryBytes < this.#initialLinearMemoryBytes) {
        throw new Error(
          "post-shutdown linear memory is smaller than its initial size");
      }
      this.#lifecycle = "shutdown";
      this.#recordHost("shutdown:complete");
      return {
        ok: true,
        accepted: true,
        complete: true,
        exitCode: processExit.exitCode,
        runtimeExitCode: runtimeExit.exitCode,
        linearMemory: {
          initialBytes: this.#initialLinearMemoryBytes,
          peakBytes: peakLinearMemoryBytes,
        },
      };
    } catch (error) {
      this.#lifecycle = "failed";
      this.#recordHost(`shutdown:failed:${String(error)}`);
      throw error;
    } finally {
      clearTimeout(timeoutHandle);
      this.#releaseHost();
    }
  }

  _reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL) {
        throw new Error("frame report protocol mismatch");
      }
      const id = Number(report.id);
      const width = Number(report.width);
      const height = Number(report.height);
      const timestampMs = Number(report.timestampMs);
      if (
        !Number.isSafeInteger(id) ||
        id < 1 ||
        !Number.isInteger(width) ||
        width < 1 ||
        !Number.isInteger(height) ||
        height < 1 ||
        !Number.isFinite(timestampMs) ||
        timestampMs < 0
      ) {
        throw new Error("frame report contains invalid metadata");
      }
      if (this.#frame && id <= this.#frame.id) {
        throw new Error("frame IDs must increase monotonically");
      }
      this.#frame = {id, width, height, timestampMs};
    } catch (error) {
      this._reportFatal(`invalid frame report: ${String(error)}`);
    }
  }

  _reportReadiness(value) {
    try {
      const report = asReport(value, "readiness report");
      if (report.protocol !== HOST_PROTOCOL) {
        throw new Error("readiness report protocol mismatch");
      }
      this.#reportedReadiness = {
        shellReady: report.shellReady === true,
        surfaceReady: report.surfaceReady === true,
        firstVisuallyNonEmptyPaint:
          report.firstVisuallyNonEmptyPaint === true,
      };
    } catch (error) {
      this._reportFatal(`invalid readiness report: ${String(error)}`);
    }
  }

  _reportNavigation(value) {
    try {
      const report = asReport(value, "navigation report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.committed !== true ||
        report.scheme !== "data"
      ) {
        throw new Error("navigation report must commit a data: URL");
      }
      this.#navigation = {committed: true, scheme: "data"};
      this.#resetHeartbeatWindow("data-navigation-committed");
    } catch (error) {
      this._reportFatal(`invalid navigation report: ${String(error)}`);
    }
  }

  _reportPageProbe(value) {
    try {
      const report = asReport(value, "page probe");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.fixture !== this.#fixture
      ) {
        throw new Error("page probe identity mismatch");
      }
      this.#pageProbe = clone(report);
      if (
        this.#interactionObservedAtFrameId === null &&
        Number.isSafeInteger(this.#inputPostedAtFrameId) &&
        report.inputClicks === 1 &&
        report.inputTrusted === true &&
        report.buttonText === "CLICKED"
      ) {
        this.#interactionObservedAtFrameId = this.#frame?.id ?? 0;
      }
    } catch (error) {
      this._reportFatal(`invalid page probe: ${String(error)}`);
    }
  }

  _reportM5Navigation(value) {
    try {
      const report = asReport(value, "M5 navigation report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.committed !== true ||
        report.scheme !== "https"
      ) {
        throw new Error("M5 navigation report identity mismatch");
      }
      if (
        this.#m5NetworkTestActive &&
        this.#m5NetworkNavigationCount === 3 &&
        this.#m5NetworkPhase === M5_NAVIGATION_PHASE.TLS_NAME_MISMATCH
      ) {
        this.#recordHost("m5:ignored-stale:https-navigation");
        return;
      }
      if (
        !this.#m5NetworkTestActive ||
        this.#m5NetworkNavigationCount !== 2 ||
        this.#m5NetworkPhase !== M5_NAVIGATION_PHASE.HTTPS_FIXTURE
      ) {
        throw new Error("M5 navigation report must commit the HTTPS fixture");
      }
      this.#navigation = {committed: true, scheme: "https"};
      this.#resetHeartbeatWindow("m5-https-navigation-committed");
    } catch (error) {
      this._reportFatal(`invalid M5 navigation report: ${String(error)}`);
    }
  }

  _reportM5NavigationError(value) {
    try {
      const report = asReport(value, "M5 navigation failure report");
      if (
        !this.#m5NetworkTestActive ||
        this.#m5NetworkNavigationCount !== 3 ||
        this.#m5NetworkPhase !== M5_NAVIGATION_PHASE.TLS_NAME_MISMATCH ||
        report.protocol !== HOST_PROTOCOL ||
        report.committed !== false ||
        report.scheme !== "https" ||
        report.netError !== M5_TLS_NAME_MISMATCH_NET_ERROR
      ) {
        throw new Error(
          "M5 navigation failure must be the TLS-name-mismatch fixture");
      }
      this.#navigation = {
        committed: false,
        scheme: "https",
        netError: M5_TLS_NAME_MISMATCH_NET_ERROR,
      };
      this.#resetHeartbeatWindow("m5-https-navigation-tls-rejected");
      this.#recordHost(
        `navigation:failed:m5-https:${M5_TLS_NAME_MISMATCH_NET_ERROR}`);
    } catch (error) {
      this._reportFatal(
        `invalid M5 navigation failure report: ${String(error)}`);
    }
  }

  _reportM5PageProbe(value) {
    try {
      const report = asReport(value, "M5 page probe");
      if (!isM5NetworkPageProbeIdentity(report)) {
        throw new Error("M5 page probe identity mismatch");
      }
      if (
        this.#m5NetworkTestActive &&
        this.#m5NetworkNavigationCount === 3 &&
        this.#m5NetworkPhase === M5_NAVIGATION_PHASE.TLS_NAME_MISMATCH
      ) {
        this.#recordHost("m5:ignored-stale:https-page-probe");
        return;
      }
      if (
        !this.#m5NetworkTestActive ||
        this.#m5NetworkNavigationCount !== 2 ||
        this.#m5NetworkPhase !== M5_NAVIGATION_PHASE.HTTPS_FIXTURE
      ) {
        throw new Error("M5 page probe is not armed for the HTTPS fixture");
      }
      this.#pageProbe = clone(report);
    } catch (error) {
      this._reportFatal(`invalid M5 page probe: ${String(error)}`);
    }
  }

  _reportM5PlaintextHttpControlNavigation(value) {
    try {
      const report = asReport(value, "M5 plaintext HTTP control navigation");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.committed !== true ||
        report.scheme !== "http"
      ) {
        throw new Error(
          "M5 plaintext HTTP control navigation identity mismatch");
      }
      if (
        this.#m5NetworkTestActive &&
        ((this.#m5NetworkNavigationCount === 2 &&
          this.#m5NetworkPhase === M5_NAVIGATION_PHASE.HTTPS_FIXTURE) ||
         (this.#m5NetworkNavigationCount === 3 &&
          this.#m5NetworkPhase === M5_NAVIGATION_PHASE.TLS_NAME_MISMATCH))
      ) {
        this.#recordHost("m5:ignored-stale:plaintext-http-control-navigation");
        return;
      }
      if (
        !this.#m5NetworkTestActive ||
        this.#m5NetworkNavigationCount !== 1 ||
        this.#m5NetworkPhase !== M5_NAVIGATION_PHASE.PLAINTEXT_HTTP_CONTROL
      ) {
        throw new Error(
          "M5 plaintext HTTP control navigation must commit the exact fixture");
      }
      this.#navigation = {committed: true, scheme: "http"};
      this.#resetHeartbeatWindow(
        "m5-plaintext-http-control-navigation-committed");
      this.#recordHost("navigation:committed:m5-plaintext-http-control");
    } catch (error) {
      this._reportFatal(
        `invalid M5 plaintext HTTP control navigation report: ${String(error)}`);
    }
  }

  _reportM5PlaintextHttpControlNavigationError(value) {
    try {
      const report = asReport(
        value, "M5 plaintext HTTP control navigation failure report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        report.committed !== false ||
        report.scheme !== "http" ||
        !Number.isSafeInteger(report.netError) || report.netError === 0
      ) {
        throw new Error(
          "M5 plaintext HTTP control navigation failure identity is invalid");
      }
      if (
        this.#m5NetworkTestActive &&
        ((this.#m5NetworkNavigationCount === 2 &&
          this.#m5NetworkPhase === M5_NAVIGATION_PHASE.HTTPS_FIXTURE) ||
         (this.#m5NetworkNavigationCount === 3 &&
          this.#m5NetworkPhase === M5_NAVIGATION_PHASE.TLS_NAME_MISMATCH))
      ) {
        this.#recordHost(
          "m5:ignored-stale:plaintext-http-control-navigation-error");
        return;
      }
      if (
        !this.#m5NetworkTestActive ||
        this.#m5NetworkNavigationCount !== 1 ||
        this.#m5NetworkPhase !== M5_NAVIGATION_PHASE.PLAINTEXT_HTTP_CONTROL
      ) {
        throw new Error(
          "M5 plaintext HTTP control navigation failure is invalid");
      }
      this.#navigation = {
        committed: false,
        scheme: "http",
        netError: report.netError,
      };
      this.#resetHeartbeatWindow(
        "m5-plaintext-http-control-navigation-failed");
      this.#recordHost(
        `navigation:failed:m5-plaintext-http-control:${report.netError}`);
    } catch (error) {
      this._reportFatal(
        "invalid M5 plaintext HTTP control navigation failure report: " +
        String(error));
    }
  }

  _reportM5PlaintextHttpControlPageProbe(value) {
    try {
      const report = asReport(value, "M5 plaintext HTTP control page probe");
      if (!isM5PlaintextHttpControlPageProbeIdentity(report)) {
        throw new Error("M5 plaintext HTTP control page probe identity mismatch");
      }
      if (
        this.#m5NetworkTestActive &&
        ((this.#m5NetworkNavigationCount === 2 &&
          this.#m5NetworkPhase === M5_NAVIGATION_PHASE.HTTPS_FIXTURE) ||
         (this.#m5NetworkNavigationCount === 3 &&
          this.#m5NetworkPhase === M5_NAVIGATION_PHASE.TLS_NAME_MISMATCH))
      ) {
        this.#recordHost("m5:ignored-stale:plaintext-http-control-page-probe");
        return;
      }
      if (
        !this.#m5NetworkTestActive ||
        this.#m5NetworkNavigationCount !== 1 ||
        this.#m5NetworkPhase !== M5_NAVIGATION_PHASE.PLAINTEXT_HTTP_CONTROL
      ) {
        throw new Error("M5 plaintext HTTP control page probe is not armed");
      }
      this.#pageProbe = clone(report);
    } catch (error) {
      this._reportFatal(
        `invalid M5 plaintext HTTP control page probe: ${String(error)}`);
    }
  }

  _reportOzoneFocusState(value) {
    try {
      const report = asReport(value, "Ozone focus-state report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        typeof report.keyboardTargetPresent !== "boolean" ||
        typeof report.active !== "boolean"
      ) {
        throw new Error("Ozone focus-state report is invalid");
      }
      this.#ozoneFocusState = {
        sequence: ++this.#ozoneFocusReportSequence,
        keyboardTargetPresent: report.keyboardTargetPresent,
        active: report.active,
      };
      this.#ozoneFocusReports.push(this.#ozoneFocusState);
      if (this.#ozoneFocusReports.length > 32) {
        this.#ozoneFocusReports.shift();
      }
      this.#recordHost(
        "ozone:focus:" +
        (report.keyboardTargetPresent ? "keyboard-target-present" :
          "keyboard-target-absent") + ":" +
        (report.active ? "active" : "inactive"));
      this.#maybeActivateM4ImeProxy();
    } catch (error) {
      this._reportFatal(
        `invalid Ozone focus-state report: ${String(error)}`);
    }
  }

  _reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        !Number.isSafeInteger(report.cursorType)
      ) {
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
      this.#ozoneCursor = {
        sequence: ++this.#ozoneCursorReportSequence,
        cursorType: report.cursorType,
        cssCursor: descriptor.cssCursor,
        exact: descriptor.exact,
      };
      this.#recordHost(
        "ozone:cursor:" + report.cursorType + ":" +
        descriptor.cssCursor + (descriptor.exact ? ":exact" : ":fallback"));
      return true;
    } catch (error) {
      this._reportFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  _reportOzoneTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state report");
      if (
        report.protocol !== HOST_PROTOCOL ||
        typeof report.focusedClientPresent !== "boolean" ||
        typeof report.editable !== "boolean" ||
        typeof report.canComposeInline !== "boolean" ||
        (report.editable === true && report.focusedClientPresent !== true) ||
        (report.canComposeInline === true && report.editable !== true)
      ) {
        throw new Error("Ozone text-input state report is invalid");
      }
      this.#ozoneTextInputState = {
        sequence: ++this.#ozoneTextInputReportSequence,
        focusedClientPresent: report.focusedClientPresent,
        editable: report.editable,
        canComposeInline: report.canComposeInline,
      };
      this.#recordHost(
        "ozone:text-input:" +
        (report.focusedClientPresent ? "client-present" : "client-absent") +
        ":" + (report.editable ? "editable" : "noneditable") +
        ":" + (report.canComposeInline ? "inline" : "no-inline"));
      this.#maybeActivateM4ImeProxy();
      if (
        this.#imeProxyInputEnabled &&
        document.activeElement === this.#imeProxy &&
        !this.#hasM4EditableTextInputAcknowledgement()
      ) {
        // WasmInputMethod clears its active composition before publishing this
        // noneditable/focus-loss state. Reset the host mirror only: a second
        // ClearCompositionText would be correctly rejected by the now-empty
        // native state and would turn a normal focus change into a failure.
        this.#clearM4ImeProxyState("native-text-input-lost", {
          queueNativeClear: false,
        });
        this.#canvas.focus({preventScroll: true});
      }
    } catch (error) {
      this._reportFatal(
        `invalid Ozone text-input state report: ${String(error)}`);
    }
  }

  _reportOzoneTextInputDelivery(value) {
    try {
      const report = asReport(value, "Ozone text-input delivery report");
      const actionName = this.#imeProxyActionName(report.action);
      if (
        report.protocol !== HOST_PROTOCOL || actionName === null ||
        !Number.isSafeInteger(report.sessionId) || report.sessionId < 1 ||
        !Number.isSafeInteger(report.sequence) || report.sequence < 1 ||
        typeof report.accepted !== "boolean"
      ) {
        throw new Error("Ozone text-input delivery report is invalid");
      }
      const request = this.#imeProxyNativeRequests.find(
        (candidate) => candidate.action === report.action &&
          candidate.sessionId === report.sessionId &&
          candidate.sequence === report.sequence);
      if (!request || request.queued !== true ||
          request.deliveryAccepted !== null) {
        throw new Error("Ozone text-input delivery does not match a queue");
      }
      request.deliveryAccepted = report.accepted;
      this.#recordHost(
        `ozone:text-input-delivery:${actionName}:` +
        (report.accepted ? "accepted" : "rejected"));
      if (!report.accepted) {
        if (this.#imeProxyFailure === null &&
            request.sessionId === this.#imeProxySessionId) {
          this.#imeProxyFailure = "NATIVE_TEXT_INPUT_DELIVERY_REJECTED";
        }
        return;
      }
      if (
        request.sessionId === this.#imeProxySessionId &&
        this.#imeProxyNativeTerminalAction?.sequence === request.sequence &&
        request.action !== M4_IME_TEXT_ACTION.setComposition
      ) {
        this.#imeProxyNativeComposition = null;
        this.#imeProxyNativeTerminalAction = null;
      }
    } catch (error) {
      this._reportFatal(
        `invalid Ozone text-input delivery report: ${String(error)}`);
    }
  }

  _reportProcessExit(value) {
    try {
      const report = asReport(value, "process exit report");
      const exitCode = report.exitCode;
      if (
        report.protocol !== HOST_PROTOCOL ||
        !Number.isSafeInteger(exitCode) ||
        this.#processExit
      ) {
        throw new Error("process exit report is invalid or duplicated");
      }
      this.#processExit = {
        exitCode,
        sequence: ++this.#exitReportSequence,
      };
      this.#recordHost(`process:exit:${exitCode}`);
      if (exitCode !== 0) {
        this._reportFatal(`Content Shell exited with status ${exitCode}`);
      } else if (this.#lifecycle !== "shutting-down") {
        this._reportFatal("Content Shell exited before shutdown was requested");
      }
      this.#resolveProcessExit(this.#processExit);
    } catch (error) {
      this._reportFatal(`invalid process exit report: ${String(error)}`);
    }
  }

  _reportRuntimeExit(value) {
    try {
      const exitCode = value;
      if (!Number.isSafeInteger(exitCode) || this.#runtimeExit) {
        throw new Error("runtime exit report is invalid or duplicated");
      }
      this.#runtimeExit = {
        exitCode,
        sequence: ++this.#exitReportSequence,
      };
      this.#recordHost(`runtime:exit:${exitCode}`);
      if (exitCode !== 0) {
        this._reportFatal(`Emscripten runtime exited with status ${exitCode}`);
      } else if (this.#lifecycle !== "shutting-down") {
        this._reportFatal(
          "Emscripten runtime exited before shutdown was requested");
      }
      this.#resolveRuntimeExit(this.#runtimeExit);
    } catch (error) {
      this._reportFatal(`invalid runtime exit report: ${String(error)}`);
    }
  }

  _reportFatal(message) {
    const text = String(message);
    this.#fatalErrors.push(text);
    this.#logs.stderr.push(`HOST_FATAL: ${text}`);
  }
}

function failureResult(versions, host, error) {
  return {
    protocol: HOST_PROTOCOL,
    case: M3_CASE,
    status: "fail",
    crossOriginIsolated,
    sharedArrayBuffer: typeof SharedArrayBuffer === "function",
    canvasFocused:
      document.activeElement === document.querySelector("#browser-canvas"),
    versions,
    readiness: null,
    heartbeat: null,
    inputResult: null,
    screenshot: null,
    logs: host ? {host: [], stdout: [], stderr: []} : null,
    shutdown: null,
    failedChecks: ["exception"],
    error: String(error),
  };
}

async function postResult(token, result) {
  const response = await fetch(
    `/__m3__/result/${encodeURIComponent(token)}`,
    {
      method: "POST",
      cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(result),
    });
  if (!response.ok) {
    throw new Error(`result endpoint returned HTTP ${response.status}`);
  }
}

export async function runM3SmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M3_CASE) {
      throw new Error("M3 case query mismatch");
    }
    if (!token) {
      throw new Error("missing M3 result token");
    }
    host = new ChromiumWasmM3Host(canvas, versions);
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;

    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(640, 480, 1);
    let resizedFrame = null;
    while (performance.now() < deadline) {
      const resizeReadiness = await host.readiness();
      if (
        resizeReadiness.frame?.width === 640 &&
        resizeReadiness.frame?.height === 480
      ) {
        resizedFrame = resizeReadiness.frame;
        break;
      }
      await delay(25);
    }
    if (!resizedFrame) {
      throw new Error("M3 runtime did not present the 640x480 resize probe");
    }
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    let restoredFrame = null;
    while (performance.now() < deadline) {
      const resizeReadiness = await host.readiness();
      if (
        resizeReadiness.frame?.id > resizedFrame.id &&
        resizeReadiness.frame?.width === DEFAULT_WIDTH &&
        resizeReadiness.frame?.height === DEFAULT_HEIGHT
      ) {
        restoredFrame = resizeReadiness.frame;
        break;
      }
      await delay(25);
    }
    if (!restoredFrame) {
      throw new Error("M3 runtime did not restore the 800x600 surface");
    }
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        `M3 base readiness timeout: ${JSON.stringify(readiness)}`);
    }

    const buttonCenterX = Number(readiness.pageProbe.buttonCenterX);
    const buttonCenterY = Number(readiness.pageProbe.buttonCenterY);
    const inputResult = await host.injectInput({
      type: "click",
      x: buttonCenterX,
      y: buttonCenterY,
      button: 0,
    });
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        readiness.pageProbe.inputClicks === 1 &&
        readiness.pageProbe.inputTrusted === true &&
        readiness.pageProbe.buttonText === "CLICKED" &&
        Number.isSafeInteger(readiness.interactionObservedAtFrameId)
      ) {
        break;
      }
      await delay(50);
    }
    if (!Number.isSafeInteger(readiness?.interactionObservedAtFrameId)) {
      throw new Error(
        `M3 trusted input observation timeout: ${JSON.stringify(readiness)}`);
    }
    const interactionObservedAtFrameId =
      readiness.interactionObservedAtFrameId;

    // The CLICKED paint can already be the current compositor frame when the
    // periodic page probe observes it. Force and prove a later runtime redraw
    // so the screenshot cannot be backed only by a pre-observation frame.
    await host.resize(POST_INPUT_REDRAW_WIDTH, DEFAULT_HEIGHT, 1);
    let redrawFrame = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        readiness.frame?.id > interactionObservedAtFrameId &&
        readiness.frame?.width === POST_INPUT_REDRAW_WIDTH &&
        readiness.frame?.height === DEFAULT_HEIGHT
      ) {
        redrawFrame = readiness.frame;
        break;
      }
      await delay(25);
    }
    if (!redrawFrame) {
      throw new Error("M3 runtime did not present the post-input redraw");
    }
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    let postInputRestoredFrame = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        readiness.frame?.id > redrawFrame.id &&
        readiness.frame?.width === DEFAULT_WIDTH &&
        readiness.frame?.height === DEFAULT_HEIGHT
      ) {
        postInputRestoredFrame = readiness.frame;
        break;
      }
      await delay(25);
    }
    if (!postInputRestoredFrame) {
      throw new Error(
        "M3 runtime did not restore the surface after the post-input redraw");
    }
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.ready) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.ready) {
      throw new Error(
        `M3 post-input readiness timeout: ${JSON.stringify(readiness)}`);
    }

    const screenshot = await host.requestScreenshot();
    const heartbeat = readiness.heartbeat;
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logsAfterShutdown = await host.logs();
    const logs = logsAfterShutdown;

    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      readiness: readiness.ready === true,
      inputDelivered:
        inputResult.ok === true &&
        inputResult.accepted === true &&
        inputResult.code === "CLICK_POSTED" &&
        readiness.pageProbe.inputClicks === 1 &&
        readiness.pageProbe.inputTrusted === true &&
        readiness.pageProbe.buttonText === "CLICKED" &&
        readiness.interactionReady === true,
      screenshot:
        screenshot.mimeType === "image/png" &&
        screenshot.width === DEFAULT_WIDTH &&
        screenshot.height === DEFAULT_HEIGHT &&
        screenshot.dataBase64.length > 0,
      shutdown:
        shutdown.ok === true &&
        shutdown.complete === true &&
        shutdown.exitCode === 0 &&
        shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M3_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      heartbeat,
      inputResult,
      screenshot,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = failureResult(versions, host, error);
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
      }
      try {
        result.readiness = await host.readiness();
        result.heartbeat = result.readiness.heartbeat;
      } catch (diagnosticError) {
        result.error += `; readiness diagnostics: ${String(diagnosticError)}`;
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(
    {...result, screenshot: result.screenshot
      ? {...result.screenshot, dataBase64: "<omitted>"}
      : null},
    null,
    2);
  await postResult(token, result);
  return result;
}

async function runM4OzonePointerSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_CASE) {
      throw new Error("M4 case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 result token");
    }
    host = new ChromiumWasmM3Host(canvas, versions, {fixture: M4_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        `M4 base readiness timeout: ${JSON.stringify(readiness)}`);
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 target y", 0, DEFAULT_HEIGHT - 1);
    const cursorReportSequenceBeforeInput =
      Number.isSafeInteger(readiness.ozoneCursor?.sequence)
        ? readiness.ozoneCursor.sequence : 0;
    const listeners = host.enableM4PointerInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4State = {
      state: "awaiting-dom-pointer",
      targetX,
      targetY,
      cursorReportSequenceBeforeInput,
      listeners,
      focusListeners,
    };
    statusElement.textContent = "M4 ready for trusted canvas pointer input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const cursor = readiness.ozoneCursor;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        readiness.pageProbe.activationCount === 1 &&
        readiness.pageProbe.clickTrusted === true &&
        hasM4NativeLinkNavigation(readiness.pageProbe) &&
        readiness.pageProbe.resultText === "ACTIVATED" &&
        readiness.frame?.id > lastQueued.frameIdBefore &&
        hasM4PointerLinkHover(readiness.pageProbe, targetX, targetY) &&
        cursor?.sequence > cursorReportSequenceBeforeInput &&
        cursor?.cursorType === M4_CURSOR_TYPE_HAND &&
        cursor?.cssCursor === "pointer" && cursor?.exact === true &&
        canvas.style.cursor === "pointer"
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueued = pointer?.lastQueued;
    const cursor = readiness?.ozoneCursor;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueued?.type !== "up" ||
      readiness.pageProbe.activationCount !== 1 ||
      readiness.pageProbe.clickTrusted !== true ||
      !hasM4NativeLinkNavigation(readiness.pageProbe) ||
      readiness.pageProbe.resultText !== "ACTIVATED" ||
      !(readiness.frame?.id > lastQueued.frameIdBefore) ||
      !hasM4PointerLinkHover(readiness.pageProbe, targetX, targetY) ||
      !(cursor?.sequence > cursorReportSequenceBeforeInput) ||
      cursor?.cursorType !== M4_CURSOR_TYPE_HAND ||
      cursor?.cssCursor !== "pointer" || cursor?.exact !== true ||
      canvas.style.cursor !== "pointer"
    ) {
      throw new Error(
        `M4 trusted Ozone pointer timeout: ${JSON.stringify(readiness)}`);
    }
    window.__chromiumWasmM4State = {
      state: "input-delivered",
      targetX,
      targetY,
      pointer: clone(pointer),
      cursor: clone(cursor),
      cursorReportSequenceBeforeInput,
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      trustedDomInput:
        pointer.trustedCount >= 2 && pointer.queuedCount >= 2,
      ozoneDelivered:
        readiness.pageProbe.activationCount === 1 &&
        readiness.pageProbe.clickTrusted === true &&
        readiness.pageProbe.resultText === "ACTIVATED" &&
        readiness.frame.id > lastQueued.frameIdBefore,
      nativeLinkActivation:
        hasM4NativeLinkNavigation(readiness.pageProbe),
      cursorDelivered:
        hasM4PointerLinkHover(readiness.pageProbe, targetX, targetY) &&
        cursor.sequence > cursorReportSequenceBeforeInput &&
        cursor.cursorType === M4_CURSOR_TYPE_HAND &&
        cursor.cssCursor === "pointer" && cursor.exact === true &&
        canvas.style.cursor === "pointer",
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      cursor: clone(cursor),
      cursorReportSequenceBeforeInput,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      cursor: null,
      cursorReportSequenceBeforeInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.cursor = result.readiness.ozoneCursor;
      } catch (diagnosticError) {
        result.error += `; readiness diagnostics: ${String(diagnosticError)}`;
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneDprSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let readiness = null;
  let dprProof = null;
  let resizeCalls = [];
  let result;

  try {
    if (parameters.get("case") !== M4_DPR_CASE) {
      throw new Error("M4 DPR case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 DPR result token");
    }
    host = new ChromiumWasmM3Host(canvas, versions, {fixture: M4_DPR_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    const initialResize = await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    resizeCalls.push(clone(initialResize));
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 DPR base readiness timeout: " + JSON.stringify(readiness));
    }
    const initialGeometry = clone(readiness.pageProbe?.displayGeometry);
    if (!hasM4DprGeometry(
        initialGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1)) {
      throw new Error(
        "M4 DPR fixture has no initial logical 800x600 geometry: " +
        JSON.stringify(initialGeometry));
    }
    const initialFrame = clone(readiness.frame);
    if (
      !Number.isSafeInteger(initialFrame?.id) || initialFrame.id < 1 ||
      initialFrame.width !== DEFAULT_WIDTH || initialFrame.height !== DEFAULT_HEIGHT
    ) {
      throw new Error("M4 DPR initial compositor frame is invalid");
    }
    const initialCanvas = m4DprCanvasSnapshot(canvas);
    if (!hasM4DprCanvasSnapshot(
        initialCanvas, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1)) {
      throw new Error("M4 DPR initial host canvas geometry is invalid");
    }
    const initialTargetX = Number(readiness.pageProbe?.targetCenterX);
    const initialTargetY = Number(readiness.pageProbe?.targetCenterY);
    checkInteger(initialTargetX, "M4 DPR initial target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(initialTargetY, "M4 DPR initial target y", 0, DEFAULT_HEIGHT - 1);

    statusElement.textContent =
      "M4 switching browser display from 800x600@1 to 800x600@2";
    const scaledResize = await host.resize(
      DEFAULT_WIDTH, DEFAULT_HEIGHT, M4_DPR_SCALE);
    resizeCalls.push(clone(scaledResize));
    let scaledGeometry = null;
    let scaledFrame = null;
    let scaledCanvas = null;
    let logicalTargetX = null;
    let logicalTargetY = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const candidateGeometry = readiness.pageProbe?.displayGeometry;
      const candidateFrame = readiness.frame;
      const candidateCanvas = m4DprCanvasSnapshot(canvas);
      if (
        candidateFrame?.id > initialFrame.id &&
        candidateFrame.width === DEFAULT_WIDTH * M4_DPR_SCALE &&
        candidateFrame.height === DEFAULT_HEIGHT * M4_DPR_SCALE &&
        hasM4DprGeometry(
            candidateGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, M4_DPR_SCALE) &&
        hasM4DprCanvasSnapshot(
            candidateCanvas, DEFAULT_WIDTH, DEFAULT_HEIGHT, M4_DPR_SCALE)
      ) {
        scaledGeometry = clone(candidateGeometry);
        scaledFrame = clone(candidateFrame);
        scaledCanvas = clone(candidateCanvas);
        logicalTargetX = Number(readiness.pageProbe?.targetCenterX);
        logicalTargetY = Number(readiness.pageProbe?.targetCenterY);
        break;
      }
      await delay(50);
    }
    if (!scaledGeometry || !scaledFrame || !scaledCanvas) {
      throw new Error(
        "M4 DPR did not reach physical 1600x1200 at logical 800x600: " +
        JSON.stringify(readiness));
    }
    checkInteger(
      logicalTargetX, "M4 DPR logical target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(
      logicalTargetY, "M4 DPR logical target y", 0, DEFAULT_HEIGHT - 1);
    if (logicalTargetX !== initialTargetX || logicalTargetY !== initialTargetY) {
      throw new Error("M4 DPR changed the fixture's logical CSS target");
    }
    const targetBackingX = logicalTargetX * M4_DPR_SCALE;
    const targetBackingY = logicalTargetY * M4_DPR_SCALE;
    checkInteger(
      targetBackingX, "M4 DPR backing target x", 0,
      DEFAULT_WIDTH * M4_DPR_SCALE - 1);
    checkInteger(
      targetBackingY, "M4 DPR backing target y", 0,
      DEFAULT_HEIGHT * M4_DPR_SCALE - 1);
    const listeners = host.enableM4PointerInput();
    window.__chromiumWasmM4DprState = {
      state: "awaiting-dom-dpr-pointer",
      targetCssX: logicalTargetX,
      targetCssY: logicalTargetY,
      targetBackingX,
      targetBackingY,
      listeners: clone(listeners),
      scaledFrame: clone(scaledFrame),
      scaledCanvas: clone(scaledCanvas),
    };
    statusElement.textContent =
      "M4 ready for trusted CSS-space pointer input at DPR 2";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer?.lastQueued;
      if (
        pointer?.queuedCount >= 2 && lastQueued?.type === "up" &&
        lastQueued.x === targetBackingX && lastQueued.y === targetBackingY &&
        readiness.pageProbe?.activationCount === 1 &&
        readiness.pageProbe?.clickTrusted === true &&
        hasM4NativeLinkNavigation(readiness.pageProbe) &&
        readiness.pageProbe?.resultText === "ACTIVATED" &&
        readiness.frame?.id > lastQueued.frameIdBefore &&
        hasM4PointerLinkHover(
            readiness.pageProbe, logicalTargetX, logicalTargetY)
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = clone(readiness?.pointerInput);
    const lastQueued = pointer?.lastQueued;
    const inputFrame = clone(readiness?.frame);
    const inputPageProbe = clone(readiness?.pageProbe);
    if (
      !pointer || pointer.queuedCount < 2 || lastQueued?.type !== "up" ||
      lastQueued.x !== targetBackingX || lastQueued.y !== targetBackingY ||
      inputPageProbe?.activationCount !== 1 ||
      inputPageProbe?.clickTrusted !== true ||
      !hasM4NativeLinkNavigation(inputPageProbe) ||
      inputPageProbe?.resultText !== "ACTIVATED" ||
      !(inputFrame?.id > lastQueued.frameIdBefore) ||
      !hasM4PointerLinkHover(
          inputPageProbe, logicalTargetX, logicalTargetY)
    ) {
      throw new Error(
        "M4 DPR trusted pointer coordinate agreement timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4DprState = {
      state: "input-delivered",
      targetCssX: logicalTargetX,
      targetCssY: logicalTargetY,
      targetBackingX,
      targetBackingY,
      pointer: clone(pointer),
      inputFrame: clone(inputFrame),
      inputPageProbe: clone(inputPageProbe),
    };

    statusElement.textContent = "M4 restoring browser display to 800x600@1";
    const restoredResize = await host.resize(
      DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    resizeCalls.push(clone(restoredResize));
    let restoredGeometry = null;
    let restoredFrame = null;
    let restoredCanvas = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const candidateGeometry = readiness.pageProbe?.displayGeometry;
      const candidateFrame = readiness.frame;
      const candidateCanvas = m4DprCanvasSnapshot(canvas);
      if (
        candidateFrame?.id > inputFrame.id &&
        candidateFrame.width === DEFAULT_WIDTH &&
        candidateFrame.height === DEFAULT_HEIGHT &&
        hasM4DprGeometry(
            candidateGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1) &&
        hasM4DprCanvasSnapshot(
            candidateCanvas, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1)
      ) {
        restoredGeometry = clone(candidateGeometry);
        restoredFrame = clone(candidateFrame);
        restoredCanvas = clone(candidateCanvas);
        break;
      }
      await delay(50);
    }
    if (!restoredGeometry || !restoredFrame || !restoredCanvas) {
      throw new Error(
        "M4 DPR did not restore physical 800x600 at logical 800x600: " +
        JSON.stringify(readiness));
    }
    dprProof = {
      initial: {
        resize: clone(initialResize),
        frame: clone(initialFrame),
        geometry: clone(initialGeometry),
        canvas: clone(initialCanvas),
      },
      scaled: {
        resize: clone(scaledResize),
        frame: clone(scaledFrame),
        geometry: clone(scaledGeometry),
        canvas: clone(scaledCanvas),
        targetCssX: logicalTargetX,
        targetCssY: logicalTargetY,
        targetBackingX,
        targetBackingY,
      },
      input: {
        pointer: clone(pointer),
        frame: clone(inputFrame),
        pageProbe: clone(inputPageProbe),
      },
      restored: {
        resize: clone(restoredResize),
        frame: clone(restoredFrame),
        geometry: clone(restoredGeometry),
        canvas: clone(restoredCanvas),
      },
    };
    window.__chromiumWasmM4DprState = {
      state: "dpr-delivered",
      dprProof: clone(dprProof),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const hostResizeLogs = logs.host.filter((line) =>
      line.startsWith("resize:"));
    const expectedResizeLogs = [
      `resize:${DEFAULT_WIDTH}x${DEFAULT_HEIGHT}@1`,
      `resize:${DEFAULT_WIDTH}x${DEFAULT_HEIGHT}@${M4_DPR_SCALE}`,
      `resize:${DEFAULT_WIDTH}x${DEFAULT_HEIGHT}@1`,
    ];
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      exactResizeCalls:
        resizeCalls.length === 3 &&
        hasM4DprResizeCall(
            resizeCalls[0], DEFAULT_WIDTH, DEFAULT_HEIGHT, 1) &&
        hasM4DprResizeCall(
            resizeCalls[1], DEFAULT_WIDTH, DEFAULT_HEIGHT, M4_DPR_SCALE) &&
        hasM4DprResizeCall(
            resizeCalls[2], DEFAULT_WIDTH, DEFAULT_HEIGHT, 1),
      logicalAndPhysicalGeometry:
        hasM4DprGeometry(
            initialGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1) &&
        hasM4DprGeometry(
            scaledGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, M4_DPR_SCALE) &&
        hasM4DprGeometry(
            restoredGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1),
      canvasBackings:
        hasM4DprCanvasSnapshot(
            initialCanvas, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1) &&
        hasM4DprCanvasSnapshot(
            scaledCanvas, DEFAULT_WIDTH, DEFAULT_HEIGHT, M4_DPR_SCALE) &&
        hasM4DprCanvasSnapshot(
            restoredCanvas, DEFAULT_WIDTH, DEFAULT_HEIGHT, 1),
      frameTransitions:
        initialFrame.id < scaledFrame.id && scaledFrame.id < inputFrame.id &&
        inputFrame.id < restoredFrame.id &&
        initialFrame.width === DEFAULT_WIDTH &&
        initialFrame.height === DEFAULT_HEIGHT &&
        scaledFrame.width === DEFAULT_WIDTH * M4_DPR_SCALE &&
        scaledFrame.height === DEFAULT_HEIGHT * M4_DPR_SCALE &&
        restoredFrame.width === DEFAULT_WIDTH &&
        restoredFrame.height === DEFAULT_HEIGHT,
      coordinateAgreement:
        pointer.trustedCount >= 2 && pointer.queuedCount >= 2 &&
        lastQueued.type === "up" && lastQueued.x === targetBackingX &&
        lastQueued.y === targetBackingY &&
        inputPageProbe.activationCount === 1 &&
        inputPageProbe.clickTrusted === true &&
        inputPageProbe.resultText === "ACTIVATED" &&
        hasM4PointerLinkHover(
            inputPageProbe, logicalTargetX, logicalTargetY),
      nativeLinkActivation:
        hasM4NativeLinkNavigation(inputPageProbe) &&
        hasM4NativeLinkNavigation(readiness.pageProbe),
      hostResizeLogs: JSON.stringify(hostResizeLogs) ===
        JSON.stringify(expectedResizeLogs),
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_DPR_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      resizeCalls,
      dprProof,
      pointerInput: pointer,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_DPR_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      resizeCalls,
      dprProof,
      pointerInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneSelectSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let readiness = null;
  let result;

  try {
    if (parameters.get("case") !== M4_SELECT_CASE) {
      throw new Error("M4 select case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 select result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_SELECT_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 select base readiness timeout: " + JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 select target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 select target y", 0, DEFAULT_HEIGHT - 1);
    const targetBounds = readiness.pageProbe.targetBounds;
    if (!targetBounds || typeof targetBounds !== "object") {
      throw new Error("M4 select fixture has no target bounds");
    }
    for (const field of ["left", "top", "right", "bottom"]) {
      checkInteger(
        Number(targetBounds[field]), `M4 select target ${field}`,
        0, field === "left" || field === "right"
          ? DEFAULT_WIDTH : DEFAULT_HEIGHT);
    }
    if (targetBounds.right <= targetBounds.left ||
        targetBounds.bottom <= targetBounds.top) {
      throw new Error("M4 select fixture target bounds are empty");
    }
    const pointerListeners = host.enableM4PointerInput();
    window.__chromiumWasmM4SelectState = {
      state: "awaiting-dom-select-open",
      targetX,
      targetY,
      targetBounds: clone(targetBounds),
      pointerListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas native select opener input";

    let popupOptionScan = null;
    let popupOpenPointer = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer?.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer?.queuedCount >= 3 && lastQueued?.type === "up" &&
        lastQueued?.button === 0 && lastQueued?.x === targetX &&
        lastQueued?.y === targetY && lastQueued?.trusted === true &&
        lastQueued?.queued === true && pageProbe?.selectValue === "one" &&
        pageProbe?.selectedIndex === 0 &&
        hasM4SelectOpenerTrace(pageProbe, targetX, targetY) &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        const candidate = scanM4SelectPopupOption(canvas, targetBounds);
        if (candidate) {
          popupOptionScan = candidate;
          popupOpenPointer = clone(lastQueued);
          break;
        }
      }
      await delay(50);
    }
    if (!popupOptionScan || !popupOpenPointer) {
      throw new Error(
        "M4 native select popup was not rendered: " +
        JSON.stringify(readiness));
    }
    checkInteger(
      popupOptionScan.targetX, "M4 select option target x", 0,
      DEFAULT_WIDTH - 1);
    checkInteger(
      popupOptionScan.targetY, "M4 select option target y", 0,
      DEFAULT_HEIGHT - 1);
    window.__chromiumWasmM4SelectState = {
      state: "awaiting-dom-select-option",
      targetX,
      targetY,
      targetBounds: clone(targetBounds),
      popupOpenPointer: clone(popupOpenPointer),
      popupOptionScan: clone(popupOptionScan),
      optionTargetX: popupOptionScan.targetX,
      optionTargetY: popupOptionScan.targetY,
    };
    statusElement.textContent =
      "M4 native select popup rendered; awaiting trusted option input";

    let optionPointer = null;
    let popupClosed = false;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer?.lastQueued;
      const pageProbe = readiness.pageProbe;
      const inputEvent = pageProbe?.inputEventTrace?.[0];
      const changeEvent = pageProbe?.changeEventTrace?.[0];
      if (
        pointer?.queuedCount === 6 && lastQueued?.type === "up" &&
        lastQueued?.button === 0 &&
        lastQueued?.x === popupOptionScan.targetX &&
        lastQueued?.y === popupOptionScan.targetY &&
        lastQueued?.trusted === true && lastQueued?.queued === true &&
        pageProbe?.selectValue === "two" && pageProbe?.selectedIndex === 1 &&
        pageProbe?.inputEventTrace?.length === 1 &&
        pageProbe?.changeEventTrace?.length === 1 &&
        inputEvent?.trusted === true && inputEvent?.value === "two" &&
        inputEvent?.selectedIndex === 1 && changeEvent?.trusted === true &&
        changeEvent?.value === "two" && changeEvent?.selectedIndex === 1 &&
        inputEvent?.sequence < changeEvent?.sequence &&
        pageProbe?.resultText === "SELECTED:two" &&
        readiness.frame?.id > lastQueued.frameIdBefore &&
        scanM4SelectPopupOption(canvas, targetBounds) === null
      ) {
        optionPointer = clone(lastQueued);
        popupClosed = true;
        break;
      }
      await delay(50);
    }
    if (!optionPointer || !popupClosed) {
      throw new Error(
        "M4 native select option was not committed: " +
        JSON.stringify(readiness));
    }
    const pointer = readiness.pointerInput;
    const pageProbe = readiness.pageProbe;
    const inputEvent = pageProbe.inputEventTrace[0];
    const changeEvent = pageProbe.changeEventTrace[0];
    window.__chromiumWasmM4SelectState = {
      state: "input-delivered",
      targetX,
      targetY,
      targetBounds: clone(targetBounds),
      popupOpenPointer: clone(popupOpenPointer),
      popupOptionScan: clone(popupOptionScan),
      optionPointer: clone(optionPointer),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      popupOpened:
        hasM4SelectOpenerTrace(pageProbe, targetX, targetY) &&
        popupOptionScan.pixelCount >= M4_SELECT_MINIMUM_POPUP_PIXELS &&
        popupOptionScan.minY > targetBounds.bottom,
      optionCommitted:
        pointer.queuedCount === 6 && pageProbe.selectValue === "two" &&
        pageProbe.selectedIndex === 1 && inputEvent.trusted === true &&
        changeEvent.trusted === true && inputEvent.sequence < changeEvent.sequence,
      popupClosed,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_SELECT_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      popupOpenPointer,
      popupOptionScan,
      optionPointer,
      popupClosed,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_SELECT_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: null,
      popupOpenPointer: null,
      popupOptionScan: null,
      optionPointer: null,
      popupClosed: false,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneResizeSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let readiness = null;
  let resizeProof = null;
  let resizeCalls = [];
  let resizeEvents = null;
  let result;

  try {
    if (parameters.get("case") !== M4_RESIZE_CASE) {
      throw new Error("M4 resize case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 resize result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_RESIZE_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    const initialResize = await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    resizeCalls.push(clone(initialResize));
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 resize base readiness timeout: " + JSON.stringify(readiness));
    }
    const initialGeometry = clone(readiness.pageProbe?.currentGeometry);
    if (!hasM4ResizeGeometry(
        initialGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, "wide")) {
      throw new Error(
        "M4 resize fixture has no initial 800x600 wide geometry: " +
        JSON.stringify(initialGeometry));
    }
    if (
      !Number.isSafeInteger(readiness.frame?.id) || readiness.frame.id < 1 ||
      readiness.frame.width !== DEFAULT_WIDTH ||
      readiness.frame.height !== DEFAULT_HEIGHT
    ) {
      throw new Error("M4 resize initial compositor frame is invalid");
    }
    const initialFrame = clone(readiness.frame);
    window.__chromiumWasmM4ResizeState = {
      state: "host-resize-running",
      initialGeometry: clone(initialGeometry),
      initialFrame: clone(initialFrame),
    };
    statusElement.textContent =
      "M4 running browser-native 800x600 to 640x480 resize";

    const narrowResize = await host.resize(
      M4_RESIZE_NARROW_WIDTH, M4_RESIZE_NARROW_HEIGHT, 1);
    resizeCalls.push(clone(narrowResize));
    let narrowGeometry = null;
    let narrowFrame = null;
    let narrowEvent = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const candidateGeometry = readiness.pageProbe?.currentGeometry;
      const candidateEvents = readiness.pageProbe?.resizeEvents;
      if (
        readiness.frame?.id > initialFrame.id &&
        readiness.frame?.width === M4_RESIZE_NARROW_WIDTH &&
        readiness.frame?.height === M4_RESIZE_NARROW_HEIGHT &&
        hasM4ResizeGeometry(
            candidateGeometry, M4_RESIZE_NARROW_WIDTH,
            M4_RESIZE_NARROW_HEIGHT, "narrow") &&
        Array.isArray(candidateEvents) && candidateEvents.length === 1 &&
        hasM4ResizeEvent(
            candidateEvents[0], 1, M4_RESIZE_NARROW_WIDTH,
            M4_RESIZE_NARROW_HEIGHT, "narrow")
      ) {
        narrowGeometry = clone(candidateGeometry);
        narrowFrame = clone(readiness.frame);
        narrowEvent = clone(candidateEvents[0]);
        break;
      }
      await delay(50);
    }
    if (!narrowGeometry || !narrowFrame || !narrowEvent) {
      throw new Error(
        "M4 resize did not reach the native 640x480 narrow layout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4ResizeState = {
      state: "host-resize-running",
      initialGeometry: clone(initialGeometry),
      initialFrame: clone(initialFrame),
      narrowGeometry: clone(narrowGeometry),
      narrowFrame: clone(narrowFrame),
      narrowEvent: clone(narrowEvent),
    };
    statusElement.textContent =
      "M4 observed native 640x480 reflow; restoring 800x600";

    const restoredResize = await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    resizeCalls.push(clone(restoredResize));
    let restoredGeometry = null;
    let restoredFrame = null;
    let restoredEvent = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const candidateGeometry = readiness.pageProbe?.currentGeometry;
      const candidateEvents = readiness.pageProbe?.resizeEvents;
      if (
        readiness.frame?.id > narrowFrame.id &&
        readiness.frame?.width === DEFAULT_WIDTH &&
        readiness.frame?.height === DEFAULT_HEIGHT &&
        hasM4ResizeGeometry(
            candidateGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, "wide") &&
        Array.isArray(candidateEvents) && candidateEvents.length === 2 &&
        hasM4ResizeEvent(
            candidateEvents[0], 1, M4_RESIZE_NARROW_WIDTH,
            M4_RESIZE_NARROW_HEIGHT, "narrow") &&
        hasM4ResizeEvent(
            candidateEvents[1], 2, DEFAULT_WIDTH, DEFAULT_HEIGHT, "wide")
      ) {
        restoredGeometry = clone(candidateGeometry);
        restoredFrame = clone(readiness.frame);
        restoredEvent = clone(candidateEvents[1]);
        resizeEvents = clone(candidateEvents);
        break;
      }
      await delay(50);
    }
    if (!restoredGeometry || !restoredFrame || !restoredEvent ||
        !resizeEvents) {
      throw new Error(
        "M4 resize did not restore the native 800x600 wide layout: " +
        JSON.stringify(readiness));
    }
    resizeProof = {
      initial: {
        resize: clone(initialResize),
        frame: clone(initialFrame),
        geometry: clone(initialGeometry),
      },
      narrow: {
        resize: clone(narrowResize),
        frame: clone(narrowFrame),
        geometry: clone(narrowGeometry),
        event: clone(narrowEvent),
      },
      restored: {
        resize: clone(restoredResize),
        frame: clone(restoredFrame),
        geometry: clone(restoredGeometry),
        event: clone(restoredEvent),
      },
    };
    window.__chromiumWasmM4ResizeState = {
      state: "resize-delivered",
      resizeProof: clone(resizeProof),
      resizeEvents: clone(resizeEvents),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const hostResizeLogs = logs.host.filter((line) =>
      line.startsWith("resize:"));
    const expectedResizeLogs = [
      `resize:${DEFAULT_WIDTH}x${DEFAULT_HEIGHT}@1`,
      `resize:${M4_RESIZE_NARROW_WIDTH}x${M4_RESIZE_NARROW_HEIGHT}@1`,
      `resize:${DEFAULT_WIDTH}x${DEFAULT_HEIGHT}@1`,
    ];
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      exactResizeCalls:
        resizeCalls.length === 3 &&
        hasM4ResizeCall(resizeCalls[0], DEFAULT_WIDTH, DEFAULT_HEIGHT) &&
        hasM4ResizeCall(
            resizeCalls[1], M4_RESIZE_NARROW_WIDTH,
            M4_RESIZE_NARROW_HEIGHT) &&
        hasM4ResizeCall(resizeCalls[2], DEFAULT_WIDTH, DEFAULT_HEIGHT),
      initialGeometry: hasM4ResizeGeometry(
          initialGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, "wide"),
      narrowGeometry: hasM4ResizeGeometry(
          narrowGeometry, M4_RESIZE_NARROW_WIDTH,
          M4_RESIZE_NARROW_HEIGHT, "narrow"),
      restoredGeometry: hasM4ResizeGeometry(
          restoredGeometry, DEFAULT_WIDTH, DEFAULT_HEIGHT, "wide"),
      trustedResizeEvents:
        Array.isArray(resizeEvents) && resizeEvents.length === 2 &&
        hasM4ResizeEvent(
            resizeEvents[0], 1, M4_RESIZE_NARROW_WIDTH,
            M4_RESIZE_NARROW_HEIGHT, "narrow") &&
        hasM4ResizeEvent(
            resizeEvents[1], 2, DEFAULT_WIDTH, DEFAULT_HEIGHT, "wide"),
      frameTransitions:
        initialFrame.id < narrowFrame.id && narrowFrame.id < restoredFrame.id &&
        initialFrame.width === DEFAULT_WIDTH &&
        initialFrame.height === DEFAULT_HEIGHT &&
        narrowFrame.width === M4_RESIZE_NARROW_WIDTH &&
        narrowFrame.height === M4_RESIZE_NARROW_HEIGHT &&
        restoredFrame.width === DEFAULT_WIDTH &&
        restoredFrame.height === DEFAULT_HEIGHT,
      hostResizeLogs: JSON.stringify(hostResizeLogs) ===
        JSON.stringify(expectedResizeLogs),
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_RESIZE_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      resizeCalls,
      resizeProof,
      resizeEvents,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_RESIZE_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      resizeCalls,
      resizeProof,
      resizeEvents,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " +
          String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneSelectionSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;
  let activationProof = null;

  try {
    if (parameters.get("case") !== M4_SELECTION_CASE) {
      throw new Error("M4 selection case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 selection result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_SELECTION_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
          "M4 selection base readiness timeout: " +
          JSON.stringify(readiness));
    }

    const targetX = Number(readiness.pageProbe.targetX);
    const targetY = Number(readiness.pageProbe.targetY);
    const drag = {
      startX: Number(readiness.pageProbe.dragStartX),
      startY: Number(readiness.pageProbe.dragStartY),
      middleX: Number(readiness.pageProbe.dragMiddleX),
      middleY: Number(readiness.pageProbe.dragMiddleY),
      endX: Number(readiness.pageProbe.dragEndX),
      endY: Number(readiness.pageProbe.dragEndY),
    };
    checkInteger(targetX, "M4 selection target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 selection target y", 0, DEFAULT_HEIGHT - 1);
    checkInteger(
        drag.startX, "M4 selection drag start x", 0, DEFAULT_WIDTH - 1);
    checkInteger(
        drag.startY, "M4 selection drag start y", 0, DEFAULT_HEIGHT - 1);
    checkInteger(
        drag.middleX, "M4 selection drag middle x", 0,
        DEFAULT_WIDTH - 1);
    checkInteger(
        drag.middleY, "M4 selection drag middle y", 0,
        DEFAULT_HEIGHT - 1);
    checkInteger(
        drag.endX, "M4 selection drag end x", 0, DEFAULT_WIDTH - 1);
    checkInteger(
        drag.endY, "M4 selection drag end y", 0, DEFAULT_HEIGHT - 1);
    if (!(drag.startX < drag.middleX && drag.middleX < drag.endX &&
          drag.startY === drag.middleY && drag.middleY === drag.endY)) {
      throw new Error("M4 selection drag geometry is not strictly forward");
    }

    const clickOuterTrace = [
      ["move", targetX, targetY],
      ["down", targetX, targetY],
      ["up", targetX, targetY],
    ];
    const outerTrace = [
      ...clickOuterTrace,
      ["move", drag.startX, drag.startY],
      ["down", drag.startX, drag.startY],
      ["move", drag.middleX, drag.middleY],
      ["move", drag.endX, drag.endY],
      ["up", drag.endX, drag.endY],
    ];
    const mouseInnerTrace = [
      ["move", targetX, targetY, 0, 0],
      ["move", targetX, targetY, 0, 0],
      ["down", targetX, targetY, 0, 1],
      ["move", targetX, targetY, 0, 1],
      ["up", targetX, targetY, 0, 0],
      ["move", drag.startX, drag.startY, 0, 0],
      ["down", drag.startX, drag.startY, 0, 1],
      ["move", drag.middleX, drag.middleY, 0, 1],
      ["move", drag.endX, drag.endY, 0, 1],
      ["up", drag.endX, drag.endY, 0, 0],
    ];
    const pointerInnerTrace = [
      ["move", targetX, targetY, -1, 0],
      ["move", targetX, targetY, -1, 0],
      ["down", targetX, targetY, 0, 1],
      ["move", targetX, targetY, -1, 1],
      ["up", targetX, targetY, 0, 0],
      ["move", drag.startX, drag.startY, -1, 0],
      ["down", drag.startX, drag.startY, 0, 1],
      ["move", drag.middleX, drag.middleY, -1, 1],
      ["move", drag.endX, drag.endY, -1, 1],
      ["up", drag.endX, drag.endY, 0, 0],
    ];
    const innerTraces = {
      mouse: mouseInnerTrace,
      pointer: pointerInnerTrace,
    };
    const pointerListeners = host.enableM4PointerInput();
    window.__chromiumWasmM4SelectionState = {
      state: "awaiting-dom-selection-activation",
      targetX,
      targetY,
      pointerListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click before text selection drag";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const queuedRecords = pointer?.queuedRecords;
      const clickRelease = queuedRecords?.[clickOuterTrace.length - 1];
      if (
        pointer?.receivedCount === clickOuterTrace.length &&
        pointer?.trustedCount === clickOuterTrace.length &&
        pointer?.queuedCount === clickOuterTrace.length &&
        matchesM4SelectionQueuedPointerTrace(queuedRecords, clickOuterTrace) &&
        hasM4SelectionActivationEvidence(readiness.pageProbe) &&
        readiness.frame?.id > clickRelease?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const activationPointer = readiness?.pointerInput;
    const activationQueuedRecords = activationPointer?.queuedRecords;
    const activationRelease =
      activationQueuedRecords?.[clickOuterTrace.length - 1];
    const activationPageProbe = readiness?.pageProbe;
    activationProof = Object.freeze({
      outerTraceExact:
        activationPointer?.receivedCount === clickOuterTrace.length &&
        activationPointer?.trustedCount === clickOuterTrace.length &&
        activationPointer?.queuedCount === clickOuterTrace.length &&
        matchesM4SelectionQueuedPointerTrace(
            activationQueuedRecords, clickOuterTrace),
      activationEvidence: hasM4SelectionActivationEvidence(
          activationPageProbe),
      selectionCollapsed: Number.isSafeInteger(
          activationPageProbe?.selectionStart) &&
        Number.isSafeInteger(activationPageProbe?.selectionEnd) &&
        activationPageProbe.selectionStart === activationPageProbe.selectionEnd,
      selectionStart: activationPageProbe?.selectionStart,
      selectionEnd: activationPageProbe?.selectionEnd,
      selectionDirectionNeutral:
        hasM4SelectionForwardOrNeutralDirection(activationPageProbe),
      selectionDirection: activationPageProbe?.selectionDirection,
      selectedTextEmpty: activationPageProbe?.selectedText === "",
      selectedText: activationPageProbe?.selectedText,
      frameAfterActivation:
        readiness?.frame?.id > activationRelease?.frameIdBefore,
    });
    const activationReady =
      activationProof.outerTraceExact &&
      activationProof.activationEvidence &&
      activationProof.selectionCollapsed &&
      activationProof.selectionDirectionNeutral &&
      activationProof.selectedTextEmpty &&
      activationProof.frameAfterActivation;
    if (!activationReady) {
      throw new Error(
          "M4 trusted Ozone selection activation timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4SelectionState = {
      state: "awaiting-dom-selection-drag",
      targetX,
      targetY,
      dragStartX: drag.startX,
      dragStartY: drag.startY,
      dragMiddleX: drag.middleX,
      dragMiddleY: drag.middleY,
      dragEndX: drag.endX,
      dragEndY: drag.endY,
      pointer: clone(activationPointer),
      activationProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas text selection drag";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const queuedRecords = pointer?.queuedRecords;
      const dragRelease = queuedRecords?.[outerTrace.length - 1];
      if (
        pointer?.receivedCount === outerTrace.length &&
        pointer?.trustedCount === outerTrace.length &&
        pointer?.queuedCount === outerTrace.length &&
        matchesM4SelectionQueuedPointerTrace(queuedRecords, outerTrace) &&
        hasM4SelectionFinalPageEvidence(readiness.pageProbe, innerTraces) &&
        readiness.frame?.id > dragRelease?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const queuedRecords = pointer?.queuedRecords;
    const dragRelease = queuedRecords?.[outerTrace.length - 1];
    const pageProbe = readiness?.pageProbe;
    const selectionProof =
      pointer?.receivedCount === outerTrace.length &&
      pointer?.trustedCount === outerTrace.length &&
      pointer?.queuedCount === outerTrace.length &&
      matchesM4SelectionQueuedPointerTrace(queuedRecords, outerTrace) &&
      hasM4SelectionFinalPageEvidence(pageProbe, innerTraces) &&
      readiness?.frame?.id > dragRelease?.frameIdBefore;
    if (!selectionProof) {
      throw new Error(
          "M4 trusted Ozone selection drag timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4SelectionState = {
      state: "input-delivered",
      targetX,
      targetY,
      dragStartX: drag.startX,
      dragStartY: drag.startY,
      dragMiddleX: drag.middleX,
      dragMiddleY: drag.middleY,
      dragEndX: drag.endX,
      dragEndY: drag.endY,
      pointer: clone(pointer),
      activationProof,
    };
    const shutdownTimeoutMs = Math.max(
        1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      pointerClickFocus: activationReady,
      trustedDomInput: selectionProof,
      ozoneDelivered: hasM4SelectionFinalPageEvidence(pageProbe, innerTraces) &&
        readiness.frame.id > dragRelease.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_SELECTION_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      activationProof: clone(activationProof),
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_SELECTION_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      activationProof: activationProof ? clone(activationProof) : null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzonePrimaryPasteSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
      1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;
  let activationProof = null;
  let selectionProof = null;

  try {
    if (parameters.get("case") !== M4_PRIMARY_PASTE_CASE) {
      throw new Error("M4 primary paste case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 primary paste result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_PRIMARY_PASTE_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
        parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
          "M4 primary paste base readiness timeout: " +
          JSON.stringify(readiness));
    }

    const source = {
      targetX: Number(readiness.pageProbe.sourceTargetX),
      targetY: Number(readiness.pageProbe.sourceTargetY),
      dragStartX: Number(readiness.pageProbe.dragStartX),
      dragStartY: Number(readiness.pageProbe.dragStartY),
      dragMiddleX: Number(readiness.pageProbe.dragMiddleX),
      dragMiddleY: Number(readiness.pageProbe.dragMiddleY),
      dragEndX: Number(readiness.pageProbe.dragEndX),
      dragEndY: Number(readiness.pageProbe.dragEndY),
    };
    const paste = {
      targetX: Number(readiness.pageProbe.pasteTargetX),
      targetY: Number(readiness.pageProbe.pasteTargetY),
    };
    for (const [name, value, maximum] of [
      ["source target x", source.targetX, DEFAULT_WIDTH - 1],
      ["source target y", source.targetY, DEFAULT_HEIGHT - 1],
      ["source drag start x", source.dragStartX, DEFAULT_WIDTH - 1],
      ["source drag start y", source.dragStartY, DEFAULT_HEIGHT - 1],
      ["source drag middle x", source.dragMiddleX, DEFAULT_WIDTH - 1],
      ["source drag middle y", source.dragMiddleY, DEFAULT_HEIGHT - 1],
      ["source drag end x", source.dragEndX, DEFAULT_WIDTH - 1],
      ["source drag end y", source.dragEndY, DEFAULT_HEIGHT - 1],
      ["paste target x", paste.targetX, DEFAULT_WIDTH - 1],
      ["paste target y", paste.targetY, DEFAULT_HEIGHT - 1],
    ]) {
      checkInteger(value, "M4 primary paste " + name, 0, maximum);
    }
    if (!(source.dragStartX < source.dragMiddleX &&
          source.dragMiddleX < source.dragEndX &&
          source.dragStartY === source.dragMiddleY &&
          source.dragMiddleY === source.dragEndY)) {
      throw new Error("M4 primary paste drag geometry is not strictly forward");
    }

    const activationTrace = [
      ["move", source.targetX, source.targetY, -1, 0],
      ["down", source.targetX, source.targetY, 0, 1],
      ["up", source.targetX, source.targetY, 0, 0],
    ];
    const sourceTrace = [
      ...activationTrace,
      ["move", source.dragStartX, source.dragStartY, -1, 0],
      ["down", source.dragStartX, source.dragStartY, 0, 1],
      ["move", source.dragMiddleX, source.dragMiddleY, -1, 1],
      ["move", source.dragEndX, source.dragEndY, -1, 1],
      ["up", source.dragEndX, source.dragEndY, 0, 0],
    ];
    const pasteTrace = [
      ["move", paste.targetX, paste.targetY, -1, 0],
      ["down", paste.targetX, paste.targetY, 1, 4],
      ["up", paste.targetX, paste.targetY, 1, 0],
    ];
    const fullTrace = [...sourceTrace, ...pasteTrace];
    const pointerListeners = host.enableM4PointerInput();
    window.__chromiumWasmM4PrimaryPasteState = {
      state: "awaiting-dom-primary-paste-activation",
      sourceTargetX: source.targetX,
      sourceTargetY: source.targetY,
      pointerListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas source activation before selection";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[activationTrace.length - 1];
      const pageProbe = readiness.pageProbe;
      if (
        pointer?.receivedCount === activationTrace.length &&
        pointer?.trustedCount === activationTrace.length &&
        pointer?.queuedCount === activationTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, activationTrace) &&
        pageProbe?.activeElementId === "source-target" &&
        pageProbe?.sourceActivationCount === 1 &&
        pageProbe?.sourceClickTrusted === true &&
        pageProbe?.sourceFocusCount >= 1 &&
        pageProbe?.sourceFocusTrusted === true &&
        pageProbe?.sourceValue === "WASM" &&
        pageProbe?.sourceSelectionStart === pageProbe?.sourceSelectionEnd &&
        pageProbe?.sourceSelectedText === "" &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const activationPointer = readiness?.pointerInput;
    const activationRecords = activationPointer?.queuedRecords;
    const activationRelease = activationRecords?.[activationTrace.length - 1];
    const activationPageProbe = readiness?.pageProbe;
    activationProof = Object.freeze({
      outerTraceExact:
        activationPointer?.receivedCount === activationTrace.length &&
        activationPointer?.trustedCount === activationTrace.length &&
        activationPointer?.queuedCount === activationTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            activationRecords, activationTrace),
      sourceActivated: activationPageProbe?.activeElementId === "source-target" &&
        activationPageProbe?.sourceActivationCount === 1 &&
        activationPageProbe?.sourceClickTrusted === true &&
        activationPageProbe?.sourceFocusCount >= 1 &&
        activationPageProbe?.sourceFocusTrusted === true,
      selectionCollapsed:
        activationPageProbe?.sourceSelectionStart ===
          activationPageProbe?.sourceSelectionEnd &&
        activationPageProbe?.sourceSelectedText === "",
      selectionStart: activationPageProbe?.sourceSelectionStart,
      selectionEnd: activationPageProbe?.sourceSelectionEnd,
      selectedText: activationPageProbe?.sourceSelectedText,
      frameAfterActivation:
        readiness?.frame?.id > activationRelease?.frameIdBefore,
    });
    if (!activationProof.outerTraceExact || !activationProof.sourceActivated ||
        !activationProof.selectionCollapsed ||
        !activationProof.frameAfterActivation) {
      throw new Error(
          "M4 primary paste source activation timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4PrimaryPasteState = {
      state: "awaiting-dom-primary-paste-drag",
      sourceTargetX: source.targetX,
      sourceTargetY: source.targetY,
      dragStartX: source.dragStartX,
      dragStartY: source.dragStartY,
      dragMiddleX: source.dragMiddleX,
      dragMiddleY: source.dragMiddleY,
      dragEndX: source.dragEndX,
      dragEndY: source.dragEndY,
      pointer: clone(activationPointer),
      activationProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas source selection drag";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[sourceTrace.length - 1];
      if (
        pointer?.receivedCount === sourceTrace.length &&
        pointer?.trustedCount === sourceTrace.length &&
        pointer?.queuedCount === sourceTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, sourceTrace) &&
        hasM4PrimaryPasteSourceSelection(readiness.pageProbe) &&
        hasM4PrimaryPasteInnerSourceEvents(readiness.pageProbe) &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const sourcePointer = readiness?.pointerInput;
    const sourceRecords = sourcePointer?.queuedRecords;
    const sourceRelease = sourceRecords?.[sourceTrace.length - 1];
    const sourcePageProbe = readiness?.pageProbe;
    selectionProof = Object.freeze({
      outerTraceExact:
        sourcePointer?.receivedCount === sourceTrace.length &&
        sourcePointer?.trustedCount === sourceTrace.length &&
        sourcePointer?.queuedCount === sourceTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(sourceRecords, sourceTrace),
      nativeSelection: hasM4PrimaryPasteSourceSelection(sourcePageProbe),
      innerSourceEvents: hasM4PrimaryPasteInnerSourceEvents(sourcePageProbe),
      frameAfterDrag: readiness?.frame?.id > sourceRelease?.frameIdBefore,
    });
    if (!selectionProof.outerTraceExact || !selectionProof.nativeSelection ||
        !selectionProof.innerSourceEvents || !selectionProof.frameAfterDrag) {
      throw new Error(
          "M4 primary paste source selection timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4PrimaryPasteState = {
      state: "awaiting-dom-primary-paste",
      pasteTargetX: paste.targetX,
      pasteTargetY: paste.targetY,
      pointer: clone(sourcePointer),
      activationProof,
      selectionProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas middle-click primary-selection paste";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[fullTrace.length - 1];
      if (
        pointer?.receivedCount === fullTrace.length &&
        pointer?.trustedCount === fullTrace.length &&
        pointer?.queuedCount === fullTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, fullTrace) &&
        hasM4PrimaryPasteFinalPageEvidence(readiness.pageProbe) &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const records = pointer?.queuedRecords;
    const pasteRelease = records?.[fullTrace.length - 1];
    const pageProbe = readiness?.pageProbe;
    const primaryPasteProof = Object.freeze({
      sourceSelection: selectionProof.nativeSelection === true,
      outerTraceExact:
        pointer?.receivedCount === fullTrace.length &&
        pointer?.trustedCount === fullTrace.length &&
        pointer?.queuedCount === fullTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, fullTrace),
      nativePaste: hasM4PrimaryPasteFinalPageEvidence(pageProbe),
      frameAfterPaste: readiness?.frame?.id > pasteRelease?.frameIdBefore,
    });
    if (!primaryPasteProof.sourceSelection ||
        !primaryPasteProof.outerTraceExact || !primaryPasteProof.nativePaste ||
        !primaryPasteProof.frameAfterPaste) {
      throw new Error(
          "M4 primary-selection paste timeout: " + JSON.stringify(readiness));
    }

    window.__chromiumWasmM4PrimaryPasteState = {
      state: "input-delivered",
      sourceTargetX: source.targetX,
      sourceTargetY: source.targetY,
      pasteTargetX: paste.targetX,
      pasteTargetY: paste.targetY,
      pointer: clone(pointer),
      activationProof,
      selectionProof,
      primaryPasteProof,
    };
    const shutdownTimeoutMs = Math.max(
        1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      sourceActivation: activationProof.sourceActivated === true,
      sourceSelection: selectionProof.nativeSelection === true,
      primarySelectionPaste: primaryPasteProof.nativePaste === true,
      trustedDomInput: primaryPasteProof.outerTraceExact === true,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_PRIMARY_PASTE_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      activationProof: clone(activationProof),
      selectionProof: clone(selectionProof),
      primaryPasteProof: clone(primaryPasteProof),
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_PRIMARY_PASTE_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      activationProof: activationProof ? clone(activationProof) : null,
      selectionProof: selectionProof ? clone(selectionProof) : null,
      primaryPasteProof: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneContextMenuSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
      1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let readiness = null;
  let result;
  let activationProof = null;
  let selectionProof = null;
  let menuOpenProof = null;
  let menuCopyProof = null;
  let pasteActivationProof = null;
  let pasteProof = null;

  try {
    if (parameters.get("case") !== M4_CONTEXT_MENU_CASE) {
      throw new Error("M4 context-menu case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 context-menu result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_CONTEXT_MENU_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
        parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
          "M4 context-menu base readiness timeout: " +
          JSON.stringify(readiness));
    }

    const source = {
      targetX: Number(readiness.pageProbe.sourceTargetX),
      targetY: Number(readiness.pageProbe.sourceTargetY),
      dragStartX: Number(readiness.pageProbe.dragStartX),
      dragStartY: Number(readiness.pageProbe.dragStartY),
      dragMiddleX: Number(readiness.pageProbe.dragMiddleX),
      dragMiddleY: Number(readiness.pageProbe.dragMiddleY),
      dragEndX: Number(readiness.pageProbe.dragEndX),
      dragEndY: Number(readiness.pageProbe.dragEndY),
    };
    const paste = {
      targetX: Number(readiness.pageProbe.pasteTargetX),
      targetY: Number(readiness.pageProbe.pasteTargetY),
    };
    for (const [name, value, maximum] of [
      ["source target x", source.targetX, DEFAULT_WIDTH - 1],
      ["source target y", source.targetY, DEFAULT_HEIGHT - 1],
      ["source drag start x", source.dragStartX, DEFAULT_WIDTH - 1],
      ["source drag start y", source.dragStartY, DEFAULT_HEIGHT - 1],
      ["source drag middle x", source.dragMiddleX, DEFAULT_WIDTH - 1],
      ["source drag middle y", source.dragMiddleY, DEFAULT_HEIGHT - 1],
      ["source drag end x", source.dragEndX, DEFAULT_WIDTH - 1],
      ["source drag end y", source.dragEndY, DEFAULT_HEIGHT - 1],
      ["paste target x", paste.targetX, DEFAULT_WIDTH - 1],
      ["paste target y", paste.targetY, DEFAULT_HEIGHT - 1],
    ]) {
      checkInteger(value, "M4 context-menu " + name, 0, maximum);
    }
    if (!(source.dragStartX < source.dragMiddleX &&
          source.dragMiddleX < source.dragEndX &&
          source.dragStartY === source.dragMiddleY &&
          source.dragMiddleY === source.dragEndY)) {
      throw new Error("M4 context-menu drag geometry is not strictly forward");
    }

    const activationTrace = [
      ["move", source.targetX, source.targetY, -1, 0],
      ["down", source.targetX, source.targetY, 0, 1],
      ["up", source.targetX, source.targetY, 0, 0],
    ];
    const dragTrace = [
      ["move", source.dragStartX, source.dragStartY, -1, 0],
      ["down", source.dragStartX, source.dragStartY, 0, 1],
      ["move", source.dragMiddleX, source.dragMiddleY, -1, 1],
      ["move", source.dragEndX, source.dragEndY, -1, 1],
      ["up", source.dragEndX, source.dragEndY, 0, 0],
    ];
    const secondaryTrace = [
      ["move", source.targetX, source.targetY, -1, 0],
      ["down", source.targetX, source.targetY, 2, 2],
      ["up", source.targetX, source.targetY, 2, 0],
    ];
    const sourceTrace = [...activationTrace, ...dragTrace];
    const menuOpenTrace = [...sourceTrace, ...secondaryTrace];
    const pasteActivationTrace = [
      ["move", paste.targetX, paste.targetY, -1, 0],
      ["down", paste.targetX, paste.targetY, 0, 1],
      ["up", paste.targetX, paste.targetY, 0, 0],
    ];
    const pasteKeyTrace = [
      ["down", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, true],
      ["down", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY, true],
      ["up", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY, true],
      ["up", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, false],
    ];
    const innerPasteKeyTrace = [
      ["keydown", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY,
       null, "context-paste"],
      ["keydown", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY,
       true, "context-paste"],
      ["keyup", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY,
       true, "context-paste"],
      ["keyup", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY,
       null, "context-paste"],
    ];

    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    window.__chromiumWasmM4ContextMenuState = {
      state: "awaiting-dom-context-menu-activation",
      sourceTargetX: source.targetX,
      sourceTargetY: source.targetY,
      pointerListeners,
      keyboardListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas context-menu source activation";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[activationTrace.length - 1];
      const pageProbe = readiness.pageProbe;
      if (
        pointer?.receivedCount === activationTrace.length &&
        pointer?.trustedCount === activationTrace.length &&
        pointer?.queuedCount === activationTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, activationTrace) &&
        pageProbe?.activeElementId === "context-source" &&
        pageProbe?.sourceFocusCount >= 1 &&
        pageProbe?.sourceSelection?.start === pageProbe?.sourceSelection?.end &&
        pageProbe?.sourceValue === "MENU" &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const activationPointer = readiness?.pointerInput;
    const activationRelease = activationPointer?.queuedRecords?.[
      activationTrace.length - 1];
    activationProof = Object.freeze({
      outerTraceExact:
        activationPointer?.receivedCount === activationTrace.length &&
        activationPointer?.trustedCount === activationTrace.length &&
        activationPointer?.queuedCount === activationTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            activationPointer?.queuedRecords, activationTrace),
      sourceFocused: readiness?.pageProbe?.activeElementId === "context-source" &&
        readiness?.pageProbe?.sourceFocusCount >= 1,
      selectionCollapsed:
        readiness?.pageProbe?.sourceSelection?.start ===
          readiness?.pageProbe?.sourceSelection?.end,
      frameAfterActivation:
        readiness?.frame?.id > activationRelease?.frameIdBefore,
    });
    if (!activationProof.outerTraceExact || !activationProof.sourceFocused ||
        !activationProof.selectionCollapsed || !activationProof.frameAfterActivation) {
      throw new Error(
          "M4 context-menu source activation timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4ContextMenuState = {
      state: "awaiting-dom-context-menu-drag",
      dragStartX: source.dragStartX,
      dragStartY: source.dragStartY,
      dragMiddleX: source.dragMiddleX,
      dragMiddleY: source.dragMiddleY,
      dragEndX: source.dragEndX,
      dragEndY: source.dragEndY,
      pointer: clone(activationPointer),
      activationProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas context-menu selection drag";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const release = pointer?.queuedRecords?.[sourceTrace.length - 1];
      if (
        pointer?.receivedCount === sourceTrace.length &&
        pointer?.trustedCount === sourceTrace.length &&
        pointer?.queuedCount === sourceTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pointer?.queuedRecords, sourceTrace) &&
        hasM4ContextMenuNativeSelection(readiness.pageProbe) &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const selectedPointer = readiness?.pointerInput;
    const selectionRelease = selectedPointer?.queuedRecords?.[
      sourceTrace.length - 1];
    selectionProof = Object.freeze({
      outerTraceExact:
        selectedPointer?.receivedCount === sourceTrace.length &&
        selectedPointer?.trustedCount === sourceTrace.length &&
        selectedPointer?.queuedCount === sourceTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            selectedPointer?.queuedRecords, sourceTrace),
      nativeSelection: hasM4ContextMenuNativeSelection(readiness?.pageProbe),
      frameAfterDrag: readiness?.frame?.id > selectionRelease?.frameIdBefore,
    });
    if (!selectionProof.outerTraceExact || !selectionProof.nativeSelection ||
        !selectionProof.frameAfterDrag) {
      throw new Error(
          "M4 context-menu source selection timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4ContextMenuState = {
      state: "awaiting-dom-context-menu-open",
      sourceTargetX: source.targetX,
      sourceTargetY: source.targetY,
      pointer: clone(selectedPointer),
      activationProof,
      selectionProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas secondary click to open Copy menu";

    let menuScan = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      menuScan = scanM4ContextMenuCopyRow(canvas);
      const pointer = readiness.pointerInput;
      const release = pointer?.queuedRecords?.[menuOpenTrace.length - 1];
      if (
        pointer?.receivedCount === menuOpenTrace.length &&
        pointer?.trustedCount === menuOpenTrace.length &&
        pointer?.queuedCount === menuOpenTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pointer?.queuedRecords, menuOpenTrace) &&
        hasM4ContextMenuNativeSelection(readiness.pageProbe) &&
        hasM4ContextMenuInnerSecondaryEvents(
            readiness.pageProbe, source.targetX, source.targetY) &&
        hasM4ContextMenuOuterSuppression(
            pointer?.contextMenuRecords, source.targetX, source.targetY) &&
        menuScan !== null && readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const menuPointer = readiness?.pointerInput;
    const menuRelease = menuPointer?.queuedRecords?.[
      menuOpenTrace.length - 1];
    menuOpenProof = Object.freeze({
      outerTraceExact:
        menuPointer?.receivedCount === menuOpenTrace.length &&
        menuPointer?.trustedCount === menuOpenTrace.length &&
        menuPointer?.queuedCount === menuOpenTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            menuPointer?.queuedRecords, menuOpenTrace),
      innerSecondary: hasM4ContextMenuInnerSecondaryEvents(
          readiness?.pageProbe, source.targetX, source.targetY),
      outerContextMenuSuppressed: hasM4ContextMenuOuterSuppression(
          menuPointer?.contextMenuRecords, source.targetX, source.targetY),
      copyRow: menuScan ? clone(menuScan) : null,
      frameAfterSecondary: readiness?.frame?.id > menuRelease?.frameIdBefore,
    });
    if (!menuOpenProof.outerTraceExact || !menuOpenProof.innerSecondary ||
        !menuOpenProof.outerContextMenuSuppressed || !menuOpenProof.copyRow ||
        !menuOpenProof.frameAfterSecondary) {
      throw new Error(
          "M4 context-menu open timeout: " + JSON.stringify(readiness));
    }

    const copyTrace = [
      ["move", menuScan.targetX, menuScan.targetY, -1, 0],
      ["down", menuScan.targetX, menuScan.targetY, 0, 1],
      ["up", menuScan.targetX, menuScan.targetY, 0, 0],
    ];
    const menuCopyTrace = [...menuOpenTrace, ...copyTrace];
    window.__chromiumWasmM4ContextMenuState = {
      state: "awaiting-dom-context-menu-copy",
      menuTargetX: menuScan.targetX,
      menuTargetY: menuScan.targetY,
      copyRow: clone(menuScan),
      pointer: clone(menuPointer),
      activationProof,
      selectionProof,
      menuOpenProof,
    };
    statusElement.textContent =
      "M4 ready for scan-derived native context-menu Copy click";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const release = pointer?.queuedRecords?.[menuCopyTrace.length - 1];
      const menuClosed = scanM4ContextMenuCopyRow(canvas) === null;
      if (
        pointer?.receivedCount === menuCopyTrace.length &&
        pointer?.trustedCount === menuCopyTrace.length &&
        pointer?.queuedCount === menuCopyTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pointer?.queuedRecords, menuCopyTrace) &&
        hasM4ContextMenuCopyEvidence(readiness.pageProbe) && menuClosed &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const copiedPointer = readiness?.pointerInput;
    const copyRelease = copiedPointer?.queuedRecords?.[
      menuCopyTrace.length - 1];
    menuCopyProof = Object.freeze({
      outerTraceExact:
        copiedPointer?.receivedCount === menuCopyTrace.length &&
        copiedPointer?.trustedCount === menuCopyTrace.length &&
        copiedPointer?.queuedCount === menuCopyTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            copiedPointer?.queuedRecords, menuCopyTrace),
      nativeCopy: hasM4ContextMenuCopyEvidence(readiness?.pageProbe),
      menuDismissed: scanM4ContextMenuCopyRow(canvas) === null,
      frameAfterCopy: readiness?.frame?.id > copyRelease?.frameIdBefore,
    });
    if (!menuCopyProof.outerTraceExact || !menuCopyProof.nativeCopy ||
        !menuCopyProof.menuDismissed || !menuCopyProof.frameAfterCopy) {
      throw new Error(
          "M4 context-menu Copy timeout: " + JSON.stringify(readiness));
    }

    const pasteTrace = [...menuCopyTrace, ...pasteActivationTrace];
    window.__chromiumWasmM4ContextMenuState = {
      state: "awaiting-dom-context-menu-paste-activation",
      pasteTargetX: paste.targetX,
      pasteTargetY: paste.targetY,
      pointer: clone(copiedPointer),
      keyboard: clone(readiness.keyboardInput),
      activationProof,
      selectionProof,
      menuOpenProof,
      menuCopyProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas context-menu paste target activation";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const release = pointer?.queuedRecords?.[pasteTrace.length - 1];
      if (
        pointer?.receivedCount === pasteTrace.length &&
        pointer?.trustedCount === pasteTrace.length &&
        pointer?.queuedCount === pasteTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pointer?.queuedRecords, pasteTrace) &&
        readiness.pageProbe?.activeElementId === "context-paste" &&
        readiness.pageProbe?.pasteFocusCount >= 1 &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pasteActivatedPointer = readiness?.pointerInput;
    const pasteActivationRelease = pasteActivatedPointer?.queuedRecords?.[
      pasteTrace.length - 1];
    pasteActivationProof = Object.freeze({
      outerTraceExact:
        pasteActivatedPointer?.receivedCount === pasteTrace.length &&
        pasteActivatedPointer?.trustedCount === pasteTrace.length &&
        pasteActivatedPointer?.queuedCount === pasteTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pasteActivatedPointer?.queuedRecords, pasteTrace),
      pasteFocused: readiness?.pageProbe?.activeElementId === "context-paste" &&
        readiness?.pageProbe?.pasteFocusCount >= 1,
      frameAfterActivation:
        readiness?.frame?.id > pasteActivationRelease?.frameIdBefore,
    });
    if (!pasteActivationProof.outerTraceExact ||
        !pasteActivationProof.pasteFocused ||
        !pasteActivationProof.frameAfterActivation) {
      throw new Error(
          "M4 context-menu paste activation timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4ContextMenuState = {
      state: "awaiting-dom-context-menu-paste",
      pointer: clone(pasteActivatedPointer),
      keyboard: clone(readiness.keyboardInput),
      activationProof,
      selectionProof,
      menuOpenProof,
      menuCopyProof,
      pasteActivationProof,
    };
    statusElement.textContent =
      "M4 ready for trusted physical ControlLeft+KeyV";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const keyboard = readiness.keyboardInput;
      const pasteKeyDown = keyboard?.queuedRecords?.[1];
      if (
        pointer?.receivedCount === pasteTrace.length &&
        pointer?.trustedCount === pasteTrace.length &&
        pointer?.queuedCount === pasteTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pointer?.queuedRecords, pasteTrace) &&
        keyboard?.receivedCount === pasteKeyTrace.length &&
        keyboard?.trustedCount === pasteKeyTrace.length &&
        keyboard?.queuedCount === pasteKeyTrace.length &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesM4CopyPasteQueuedKeyTrace(
            keyboard?.queuedRecords, pasteKeyTrace) &&
        matchesM4CopyPasteInnerKeyTrace(
            readiness.pageProbe?.pasteKeyEventTrace, innerPasteKeyTrace) &&
        hasM4ContextMenuPasteEvidence(readiness.pageProbe) &&
        readiness.frame?.id > pasteKeyDown?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const keyboard = readiness?.keyboardInput;
    const pasteKeyDown = keyboard?.queuedRecords?.[1];
    pasteProof = Object.freeze({
      outerPointerTraceExact:
        pointer?.receivedCount === pasteTrace.length &&
        pointer?.trustedCount === pasteTrace.length &&
        pointer?.queuedCount === pasteTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pointer?.queuedRecords, pasteTrace),
      outerKeyTraceExact:
        keyboard?.receivedCount === pasteKeyTrace.length &&
        keyboard?.trustedCount === pasteKeyTrace.length &&
        keyboard?.queuedCount === pasteKeyTrace.length &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesM4CopyPasteQueuedKeyTrace(
            keyboard?.queuedRecords, pasteKeyTrace),
      innerKeys: matchesM4CopyPasteInnerKeyTrace(
          readiness?.pageProbe?.pasteKeyEventTrace, innerPasteKeyTrace),
      nativePaste: hasM4ContextMenuPasteEvidence(readiness?.pageProbe),
      frameAfterPaste: readiness?.frame?.id > pasteKeyDown?.frameIdBefore,
    });
    if (!pasteProof.outerPointerTraceExact || !pasteProof.outerKeyTraceExact ||
        !pasteProof.innerKeys || !pasteProof.nativePaste ||
        !pasteProof.frameAfterPaste) {
      throw new Error(
          "M4 context-menu Ctrl+V paste timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4ContextMenuState = {
      state: "input-delivered",
      pointer: clone(pointer),
      keyboard: clone(keyboard),
      activationProof,
      selectionProof,
      menuOpenProof,
      menuCopyProof,
      pasteActivationProof,
      pasteProof,
    };
    const shutdownTimeoutMs = Math.max(
        1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      sourceSelection: selectionProof.nativeSelection === true,
      nativeMenu: menuOpenProof.innerSecondary === true &&
        menuOpenProof.outerContextMenuSuppressed === true &&
        menuOpenProof.copyRow !== null,
      nativeCopy: menuCopyProof.nativeCopy === true &&
        menuCopyProof.menuDismissed === true,
      nativePaste: pasteProof.nativePaste === true,
      trustedDomInput: pasteProof.outerPointerTraceExact === true &&
        pasteProof.outerKeyTraceExact === true,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_CONTEXT_MENU_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      activationProof: clone(activationProof),
      selectionProof: clone(selectionProof),
      menuOpenProof: clone(menuOpenProof),
      menuCopyProof: clone(menuCopyProof),
      pasteActivationProof: clone(pasteActivationProof),
      pasteProof: clone(pasteProof),
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_CONTEXT_MENU_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      activationProof: activationProof ? clone(activationProof) : null,
      selectionProof: selectionProof ? clone(selectionProof) : null,
      menuOpenProof: menuOpenProof ? clone(menuOpenProof) : null,
      menuCopyProof: menuCopyProof ? clone(menuCopyProof) : null,
      pasteActivationProof: pasteActivationProof
        ? clone(pasteActivationProof) : null,
      pasteProof: pasteProof ? clone(pasteProof) : null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneCopyPasteSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
      1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;
  let readiness = null;
  let activationProof = null;
  let bareShortcutProof = null;
  let sourceSelectionProof = null;
  let copyProof = null;
  let decoySelectionProof = null;
  let primarySelectionPasteProof = null;
  let pasteProof = null;

  try {
    if (parameters.get("case") !== M4_COPY_PASTE_CASE) {
      throw new Error("M4 copy/paste case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 copy/paste result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_COPY_PASTE_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
        parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
          "M4 copy/paste base readiness timeout: " + JSON.stringify(readiness));
    }

    const copySource = {
      targetX: Number(readiness.pageProbe.copySourceTargetX),
      targetY: Number(readiness.pageProbe.copySourceTargetY),
      dragStartX: Number(readiness.pageProbe.copyDragStartX),
      dragStartY: Number(readiness.pageProbe.copyDragStartY),
      dragMiddleX: Number(readiness.pageProbe.copyDragMiddleX),
      dragMiddleY: Number(readiness.pageProbe.copyDragMiddleY),
      dragEndX: Number(readiness.pageProbe.copyDragEndX),
      dragEndY: Number(readiness.pageProbe.copyDragEndY),
    };
    const decoy = {
      targetX: Number(readiness.pageProbe.decoyTargetX),
      targetY: Number(readiness.pageProbe.decoyTargetY),
      dragStartX: Number(readiness.pageProbe.decoyDragStartX),
      dragStartY: Number(readiness.pageProbe.decoyDragStartY),
      dragMiddleX: Number(readiness.pageProbe.decoyDragMiddleX),
      dragMiddleY: Number(readiness.pageProbe.decoyDragMiddleY),
      dragEndX: Number(readiness.pageProbe.decoyDragEndX),
      dragEndY: Number(readiness.pageProbe.decoyDragEndY),
    };
    const paste = {
      targetX: Number(readiness.pageProbe.pasteTargetX),
      targetY: Number(readiness.pageProbe.pasteTargetY),
    };
    const primaryVerify = {
      targetX: Number(readiness.pageProbe.primaryVerifyTargetX),
      targetY: Number(readiness.pageProbe.primaryVerifyTargetY),
    };
    for (const [name, value, maximum] of [
      ["copy source target x", copySource.targetX, DEFAULT_WIDTH - 1],
      ["copy source target y", copySource.targetY, DEFAULT_HEIGHT - 1],
      ["copy drag start x", copySource.dragStartX, DEFAULT_WIDTH - 1],
      ["copy drag start y", copySource.dragStartY, DEFAULT_HEIGHT - 1],
      ["copy drag middle x", copySource.dragMiddleX, DEFAULT_WIDTH - 1],
      ["copy drag middle y", copySource.dragMiddleY, DEFAULT_HEIGHT - 1],
      ["copy drag end x", copySource.dragEndX, DEFAULT_WIDTH - 1],
      ["copy drag end y", copySource.dragEndY, DEFAULT_HEIGHT - 1],
      ["decoy target x", decoy.targetX, DEFAULT_WIDTH - 1],
      ["decoy target y", decoy.targetY, DEFAULT_HEIGHT - 1],
      ["decoy drag start x", decoy.dragStartX, DEFAULT_WIDTH - 1],
      ["decoy drag start y", decoy.dragStartY, DEFAULT_HEIGHT - 1],
      ["decoy drag middle x", decoy.dragMiddleX, DEFAULT_WIDTH - 1],
      ["decoy drag middle y", decoy.dragMiddleY, DEFAULT_HEIGHT - 1],
      ["decoy drag end x", decoy.dragEndX, DEFAULT_WIDTH - 1],
      ["decoy drag end y", decoy.dragEndY, DEFAULT_HEIGHT - 1],
      ["primary verification target x", primaryVerify.targetX,
       DEFAULT_WIDTH - 1],
      ["primary verification target y", primaryVerify.targetY,
       DEFAULT_HEIGHT - 1],
      ["paste target x", paste.targetX, DEFAULT_WIDTH - 1],
      ["paste target y", paste.targetY, DEFAULT_HEIGHT - 1],
    ]) {
      checkInteger(value, "M4 copy/paste " + name, 0, maximum);
    }
    for (const [name, geometry] of [
      ["copy source", copySource],
      ["decoy", decoy],
    ]) {
      if (!(geometry.dragStartX < geometry.dragMiddleX &&
            geometry.dragMiddleX < geometry.dragEndX &&
            geometry.dragStartY === geometry.dragMiddleY &&
            geometry.dragMiddleY === geometry.dragEndY)) {
        throw new Error("M4 copy/paste " + name + " drag is not forward");
      }
    }

    const clickTrace = (point) => [
      ["move", point.targetX, point.targetY, -1, 0],
      ["down", point.targetX, point.targetY, 0, 1],
      ["up", point.targetX, point.targetY, 0, 0],
    ];
    const middleClickTrace = (point) => [
      ["move", point.targetX, point.targetY, -1, 0],
      ["down", point.targetX, point.targetY, 1, 4],
      ["up", point.targetX, point.targetY, 1, 0],
    ];
    const dragTrace = (point) => [
      ["move", point.dragStartX, point.dragStartY, -1, 0],
      ["down", point.dragStartX, point.dragStartY, 0, 1],
      ["move", point.dragMiddleX, point.dragMiddleY, -1, 1],
      ["move", point.dragEndX, point.dragEndY, -1, 1],
      ["up", point.dragEndX, point.dragEndY, 0, 0],
    ];
    const sourceActivationTrace = clickTrace(copySource);
    const sourceTrace = [...sourceActivationTrace, ...dragTrace(copySource)];
    const decoyActivationTrace = [
      ...sourceTrace,
      ...clickTrace(decoy),
    ];
    const decoyTrace = [...decoyActivationTrace, ...dragTrace(decoy)];
    const pasteTargetTrace = [
      ...decoyTrace,
      ...clickTrace(paste),
    ];
    const fullPointerTrace = [
      ...pasteTargetTrace,
      ...middleClickTrace(primaryVerify),
    ];
    const copyKeyTrace = [
      ["down", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, true],
      ["down", M4_COPY_DOM_CODE, M4_COPY_DOM_KEY, true],
      ["up", M4_COPY_DOM_CODE, M4_COPY_DOM_KEY, true],
      ["up", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, false],
    ];
    const fullKeyTrace = [
      ...copyKeyTrace,
      ["down", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, true],
      ["down", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY, true],
      ["up", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY, true],
      ["up", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, false],
    ];
    const bareShortcutRecordCount = 2;
    const innerKeyTrace = [
      ["keydown", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, null,
       "copy-source"],
      ["keydown", M4_COPY_DOM_CODE, M4_COPY_DOM_KEY, true, "copy-source"],
      ["keyup", M4_COPY_DOM_CODE, M4_COPY_DOM_KEY, true, "copy-source"],
      ["keyup", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, null,
       "copy-source"],
      ["keydown", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, null,
       "paste-target"],
      ["keydown", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY, true, "paste-target"],
      ["keyup", M4_PASTE_DOM_CODE, M4_PASTE_DOM_KEY, true, "paste-target"],
      ["keyup", M4_CONTROL_LEFT_DOM_CODE, M4_CONTROL_LEFT_DOM_KEY, null,
       "paste-target"],
    ];

    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-source-activation",
      copySourceTargetX: copySource.targetX,
      copySourceTargetY: copySource.targetY,
      pointerListeners,
      keyboardListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas source activation before Ctrl+C";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[sourceActivationTrace.length - 1];
      const pageProbe = readiness.pageProbe;
      if (
        pointer?.receivedCount === sourceActivationTrace.length &&
        pointer?.trustedCount === sourceActivationTrace.length &&
        pointer?.queuedCount === sourceActivationTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            records, sourceActivationTrace) &&
        pageProbe?.activeElementId === "copy-source" &&
        pageProbe?.copySourceActivationCount === 1 &&
        pageProbe?.copySourceFocusCount >= 1 &&
        pageProbe?.copySourceValue === M4_COPY_PASTE_SOURCE_VALUE &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const activationPointer = readiness?.pointerInput;
    const activationRecords = activationPointer?.queuedRecords;
    const activationRelease =
      activationRecords?.[sourceActivationTrace.length - 1];
    const activationPage = readiness?.pageProbe;
    activationProof = Object.freeze({
      outerTraceExact:
        activationPointer?.receivedCount === sourceActivationTrace.length &&
        activationPointer?.trustedCount === sourceActivationTrace.length &&
        activationPointer?.queuedCount === sourceActivationTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            activationRecords, sourceActivationTrace),
      sourceActivated:
        activationPage?.activeElementId === "copy-source" &&
        activationPage?.copySourceActivationCount === 1 &&
        activationPage?.copySourceFocusCount >= 1 &&
        activationPage?.copySourceValue === M4_COPY_PASTE_SOURCE_VALUE,
      frameAfterActivation:
        readiness?.frame?.id > activationRelease?.frameIdBefore,
    });
    if (!activationProof.outerTraceExact || !activationProof.sourceActivated ||
        !activationProof.frameAfterActivation) {
      throw new Error(
          "M4 copy/paste source activation timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-bare-shortcut-rejection",
      pointer: clone(activationPointer),
      keyboard: clone(readiness.keyboardInput),
      activationProof,
    };
    statusElement.textContent =
      "M4 ready to reject an unmodified physical KeyC";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (hasM4CopyPasteBareShortcutRejection(readiness.keyboardInput) &&
          readiness.pageProbe?.keyEventTrace?.length === 0 &&
          readiness.pageProbe?.copyEventTrace?.length === 0) {
        break;
      }
      await delay(50);
    }
    bareShortcutProof = Object.freeze({
      hostRejected: hasM4CopyPasteBareShortcutRejection(
          readiness?.keyboardInput),
      noBlinkDelivery:
        readiness?.pageProbe?.keyEventTrace?.length === 0 &&
        readiness?.pageProbe?.copyEventTrace?.length === 0,
    });
    if (!bareShortcutProof.hostRejected ||
        !bareShortcutProof.noBlinkDelivery) {
      throw new Error(
          "M4 bare KeyC rejection timeout: " + JSON.stringify(readiness));
    }

    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-source-drag",
      copyDragStartX: copySource.dragStartX,
      copyDragStartY: copySource.dragStartY,
      copyDragMiddleX: copySource.dragMiddleX,
      copyDragMiddleY: copySource.dragMiddleY,
      copyDragEndX: copySource.dragEndX,
      copyDragEndY: copySource.dragEndY,
      pointer: clone(activationPointer),
      keyboard: clone(readiness.keyboardInput),
      activationProof,
      bareShortcutProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas COPY selection drag";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[sourceTrace.length - 1];
      if (
        pointer?.receivedCount === sourceTrace.length &&
        pointer?.trustedCount === sourceTrace.length &&
        pointer?.queuedCount === sourceTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, sourceTrace) &&
        hasM4CopyPasteSelection(
            readiness.pageProbe?.copySelectionActivity,
            M4_COPY_PASTE_SOURCE_VALUE) &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const sourcePointer = readiness?.pointerInput;
    const sourceRecords = sourcePointer?.queuedRecords;
    const sourceRelease = sourceRecords?.[sourceTrace.length - 1];
    sourceSelectionProof = Object.freeze({
      outerTraceExact:
        sourcePointer?.receivedCount === sourceTrace.length &&
        sourcePointer?.trustedCount === sourceTrace.length &&
        sourcePointer?.queuedCount === sourceTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(sourceRecords, sourceTrace),
      nativeSelection: hasM4CopyPasteSelection(
          readiness?.pageProbe?.copySelectionActivity,
          M4_COPY_PASTE_SOURCE_VALUE),
      frameAfterDrag: readiness?.frame?.id > sourceRelease?.frameIdBefore,
    });
    if (!sourceSelectionProof.outerTraceExact ||
        !sourceSelectionProof.nativeSelection ||
        !sourceSelectionProof.frameAfterDrag) {
      throw new Error(
          "M4 copy/paste source selection timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-copy",
      keyboard: clone(readiness.keyboardInput),
      bareShortcutProof,
      sourceSelectionProof,
    };
    statusElement.textContent =
      "M4 ready for trusted physical ControlLeft+KeyC";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const records = keyboard?.queuedRecords;
      if (
        keyboard?.receivedCount ===
          copyKeyTrace.length + bareShortcutRecordCount &&
        keyboard?.trustedCount ===
          copyKeyTrace.length + bareShortcutRecordCount &&
        keyboard?.queuedCount === copyKeyTrace.length &&
        keyboard?.rejectedRecords?.length === bareShortcutRecordCount &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesM4CopyPasteQueuedKeyTrace(
            records, copyKeyTrace, bareShortcutRecordCount + 1) &&
        hasM4CopyPasteCopyEvidence(readiness.pageProbe) &&
        matchesM4CopyPasteInnerKeyTrace(
            readiness.pageProbe?.keyEventTrace,
            innerKeyTrace.slice(0, copyKeyTrace.length))
      ) {
        break;
      }
      await delay(50);
    }
    const copiedKeyboard = readiness?.keyboardInput;
    const copiedRecords = copiedKeyboard?.queuedRecords;
    copyProof = Object.freeze({
      outerTraceExact:
        copiedKeyboard?.receivedCount ===
          copyKeyTrace.length + bareShortcutRecordCount &&
        copiedKeyboard?.trustedCount ===
          copyKeyTrace.length + bareShortcutRecordCount &&
        copiedKeyboard?.queuedCount === copyKeyTrace.length &&
        copiedKeyboard?.rejectedRecords?.length === bareShortcutRecordCount &&
        copiedKeyboard?.pressedCodes?.length === 0 &&
        matchesM4CopyPasteQueuedKeyTrace(
            copiedRecords, copyKeyTrace, bareShortcutRecordCount + 1),
      nativeCopy: hasM4CopyPasteCopyEvidence(readiness?.pageProbe),
      bareShortcutRejected: bareShortcutProof.hostRejected === true &&
        bareShortcutProof.noBlinkDelivery === true,
      innerKeys: matchesM4CopyPasteInnerKeyTrace(
          readiness?.pageProbe?.keyEventTrace,
          innerKeyTrace.slice(0, copyKeyTrace.length)),
      shortcutReleased: copiedKeyboard?.pressedCodes?.length === 0,
    });
    if (!copyProof.outerTraceExact || !copyProof.nativeCopy ||
        !copyProof.bareShortcutRejected || !copyProof.innerKeys ||
        !copyProof.shortcutReleased) {
      throw new Error(
          "M4 Ctrl+C copy timeout: " + JSON.stringify(readiness));
    }

    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-decoy-activation",
      decoyTargetX: decoy.targetX,
      decoyTargetY: decoy.targetY,
      pointer: clone(sourcePointer),
      keyboard: clone(copiedKeyboard),
      sourceSelectionProof,
      copyProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas DECOY activation";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[decoyActivationTrace.length - 1];
      const pageProbe = readiness.pageProbe;
      if (
        pointer?.receivedCount === decoyActivationTrace.length &&
        pointer?.trustedCount === decoyActivationTrace.length &&
        pointer?.queuedCount === decoyActivationTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, decoyActivationTrace) &&
        pageProbe?.activeElementId === "selection-decoy" &&
        pageProbe?.selectionDecoyActivationCount === 1 &&
        pageProbe?.selectionDecoyFocusCount >= 1 &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const decoyActivatedPointer = readiness?.pointerInput;

    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-decoy-drag",
      decoyDragStartX: decoy.dragStartX,
      decoyDragStartY: decoy.dragStartY,
      decoyDragMiddleX: decoy.dragMiddleX,
      decoyDragMiddleY: decoy.dragMiddleY,
      decoyDragEndX: decoy.dragEndX,
      decoyDragEndY: decoy.dragEndY,
      pointer: clone(decoyActivatedPointer),
      copyProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas DECOY selection drag";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[decoyTrace.length - 1];
      if (
        pointer?.receivedCount === decoyTrace.length &&
        pointer?.trustedCount === decoyTrace.length &&
        pointer?.queuedCount === decoyTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, decoyTrace) &&
        hasM4CopyPasteSelection(
            readiness.pageProbe?.decoySelectionActivity,
            M4_COPY_PASTE_DECOY_VALUE) &&
        release?.queued === true
      ) {
        break;
      }
      await delay(50);
    }
    const decoyPointer = readiness?.pointerInput;
    const decoyRecords = decoyPointer?.queuedRecords;
    const decoyRelease = decoyRecords?.[decoyTrace.length - 1];
    decoySelectionProof = Object.freeze({
      outerTraceExact:
        decoyPointer?.receivedCount === decoyTrace.length &&
        decoyPointer?.trustedCount === decoyTrace.length &&
        decoyPointer?.queuedCount === decoyTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(decoyRecords, decoyTrace),
      primarySelectionOverwritten: hasM4CopyPasteSelection(
          readiness?.pageProbe?.decoySelectionActivity,
          M4_COPY_PASTE_DECOY_VALUE),
      // A second native selection may leave the compositor's visible state
      // unchanged.  Its trusted selection event and queued pointer release
      // prove delivery; the subsequent paste still requires a new frame.
      releaseQueued: decoyRelease?.queued === true,
    });
    if (!decoySelectionProof.outerTraceExact ||
        !decoySelectionProof.primarySelectionOverwritten ||
        !decoySelectionProof.releaseQueued) {
      throw new Error(
          "M4 copy/paste decoy selection timeout: " +
          JSON.stringify(readiness));
    }
    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-paste-activation",
      pasteTargetX: paste.targetX,
      pasteTargetY: paste.targetY,
      pointer: clone(decoyPointer),
      keyboard: clone(copiedKeyboard),
      copyProof,
      decoySelectionProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas paste-target activation";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const records = pointer?.queuedRecords;
      const release = records?.[pasteTargetTrace.length - 1];
      const pageProbe = readiness.pageProbe;
      if (
        pointer?.receivedCount === pasteTargetTrace.length &&
        pointer?.trustedCount === pasteTargetTrace.length &&
        pointer?.queuedCount === pasteTargetTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, pasteTargetTrace) &&
        pageProbe?.activeElementId === "paste-target" &&
        pageProbe?.pasteTargetActivationCount === 1 &&
        pageProbe?.pasteTargetFocusCount >= 1 &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pasteActivatedPointer = readiness?.pointerInput;

    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-paste",
      pointer: clone(pasteActivatedPointer),
      keyboard: clone(copiedKeyboard),
      copyProof,
      decoySelectionProof,
    };
    statusElement.textContent =
      "M4 ready for trusted physical ControlLeft+KeyV";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const keyboard = readiness.keyboardInput;
      const pointerRecords = pointer?.queuedRecords;
      const keyRecords = keyboard?.queuedRecords;
      const pasteKeyDown = keyRecords?.[copyKeyTrace.length + 1];
      if (
        pointer?.receivedCount === pasteTargetTrace.length &&
        pointer?.trustedCount === pasteTargetTrace.length &&
        pointer?.queuedCount === pasteTargetTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pointerRecords, pasteTargetTrace) &&
        keyboard?.receivedCount ===
          fullKeyTrace.length + bareShortcutRecordCount &&
        keyboard?.trustedCount ===
          fullKeyTrace.length + bareShortcutRecordCount &&
        keyboard?.queuedCount === fullKeyTrace.length &&
        keyboard?.rejectedRecords?.length === bareShortcutRecordCount &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesM4CopyPasteQueuedKeyTrace(
            keyRecords, fullKeyTrace, bareShortcutRecordCount + 1) &&
        matchesM4CopyPasteInnerKeyTrace(
            readiness.pageProbe?.keyEventTrace, innerKeyTrace) &&
        hasM4CopyPastePasteEvidence(readiness.pageProbe) &&
        readiness.frame?.id > pasteKeyDown?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pastePointer = readiness?.pointerInput;
    const pasteKeyboard = readiness?.keyboardInput;
    const keyRecords = pasteKeyboard?.queuedRecords;
    const pasteKeyDown = keyRecords?.[copyKeyTrace.length + 1];
    const pageProbe = readiness?.pageProbe;
    pasteProof = Object.freeze({
      outerPointerTraceExact:
        pastePointer?.receivedCount === pasteTargetTrace.length &&
        pastePointer?.trustedCount === pasteTargetTrace.length &&
        pastePointer?.queuedCount === pasteTargetTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            pastePointer?.queuedRecords, pasteTargetTrace),
      outerKeyTraceExact:
        pasteKeyboard?.receivedCount ===
          fullKeyTrace.length + bareShortcutRecordCount &&
        pasteKeyboard?.trustedCount ===
          fullKeyTrace.length + bareShortcutRecordCount &&
        pasteKeyboard?.queuedCount === fullKeyTrace.length &&
        pasteKeyboard?.rejectedRecords?.length === bareShortcutRecordCount &&
        pasteKeyboard?.pressedCodes?.length === 0 &&
        matchesM4CopyPasteQueuedKeyTrace(
            keyRecords, fullKeyTrace, bareShortcutRecordCount + 1),
      innerKeys: matchesM4CopyPasteInnerKeyTrace(
          pageProbe?.keyEventTrace, innerKeyTrace),
      nativePaste: hasM4CopyPastePasteEvidence(pageProbe),
      copyPasteBufferWins:
        pageProbe?.pasteValue === M4_COPY_PASTE_SOURCE_VALUE &&
        pageProbe?.pasteValue !== M4_COPY_PASTE_DECOY_VALUE,
      frameAfterPaste: readiness?.frame?.id > pasteKeyDown?.frameIdBefore,
    });
    if (!pasteProof.outerPointerTraceExact ||
        !pasteProof.outerKeyTraceExact || !pasteProof.innerKeys ||
        !pasteProof.nativePaste || !pasteProof.copyPasteBufferWins ||
        !pasteProof.frameAfterPaste) {
      throw new Error(
          "M4 Ctrl+V paste timeout: " + JSON.stringify(readiness));
    }
    window.__chromiumWasmM4CopyPasteState = {
      state: "awaiting-dom-copy-paste-primary-verify",
      primaryVerifyTargetX: primaryVerify.targetX,
      primaryVerifyTargetY: primaryVerify.targetY,
      pointer: clone(pastePointer),
      keyboard: clone(pasteKeyboard),
      copyProof,
      decoySelectionProof,
      pasteProof,
    };
    statusElement.textContent =
      "M4 ready for trusted middle-click primary-selection verification";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const candidatePointer = readiness.pointerInput;
      const records = candidatePointer?.queuedRecords;
      const release = records?.[fullPointerTrace.length - 1];
      if (
        candidatePointer?.receivedCount === fullPointerTrace.length &&
        candidatePointer?.trustedCount === fullPointerTrace.length &&
        candidatePointer?.queuedCount === fullPointerTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(records, fullPointerTrace) &&
        hasM4CopyPastePrimarySelectionPasteEvidence(readiness.pageProbe) &&
        readiness.frame?.id > release?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const keyboard = readiness?.keyboardInput;
    const primaryVerifyRecords = pointer?.queuedRecords;
    const primaryVerifyRelease =
      primaryVerifyRecords?.[fullPointerTrace.length - 1];
    primarySelectionPasteProof = Object.freeze({
      outerTraceExact:
        pointer?.receivedCount === fullPointerTrace.length &&
        pointer?.trustedCount === fullPointerTrace.length &&
        pointer?.queuedCount === fullPointerTrace.length &&
        matchesM4PrimaryPasteQueuedPointerTrace(
            primaryVerifyRecords, fullPointerTrace),
      primaryBufferContainsDecoy:
        hasM4CopyPastePrimarySelectionPasteEvidence(readiness?.pageProbe),
      frameAfterPrimaryPaste:
        readiness?.frame?.id > primaryVerifyRelease?.frameIdBefore,
    });
    if (!primarySelectionPasteProof.outerTraceExact ||
        !primarySelectionPasteProof.primaryBufferContainsDecoy ||
        !primarySelectionPasteProof.frameAfterPrimaryPaste) {
      throw new Error(
          "M4 primary-selection verification timeout: " +
          JSON.stringify(readiness));
    }

    window.__chromiumWasmM4CopyPasteState = {
      state: "input-delivered",
      pointer: clone(pointer),
      keyboard: clone(keyboard),
      activationProof,
      sourceSelectionProof,
      copyProof,
      decoySelectionProof,
      primarySelectionPasteProof,
      pasteProof,
    };
    const shutdownTimeoutMs = Math.max(
        1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      sourceSelection: sourceSelectionProof.nativeSelection === true,
      bareShortcutRejected:
        bareShortcutProof.hostRejected === true &&
        bareShortcutProof.noBlinkDelivery === true,
      nativeCopy: copyProof.nativeCopy === true,
      primarySelectionOverwritten:
        decoySelectionProof.primarySelectionOverwritten === true,
      primaryBufferContainsDecoy:
        primarySelectionPasteProof.primaryBufferContainsDecoy === true,
      nativePaste: pasteProof.nativePaste === true,
      copyPasteBufferWins: pasteProof.copyPasteBufferWins === true,
      trustedDomInput:
        pasteProof.outerPointerTraceExact === true &&
        pasteProof.outerKeyTraceExact === true,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_COPY_PASTE_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      activationProof: clone(activationProof),
      bareShortcutProof: clone(bareShortcutProof),
      sourceSelectionProof: clone(sourceSelectionProof),
      copyProof: clone(copyProof),
      decoySelectionProof: clone(decoySelectionProof),
      primarySelectionPasteProof: clone(primarySelectionPasteProof),
      pasteProof: clone(pasteProof),
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_COPY_PASTE_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      activationProof: activationProof ? clone(activationProof) : null,
      bareShortcutProof: bareShortcutProof
        ? clone(bareShortcutProof) : null,
      sourceSelectionProof: sourceSelectionProof
        ? clone(sourceSelectionProof) : null,
      copyProof: copyProof ? clone(copyProof) : null,
      decoySelectionProof: decoySelectionProof
        ? clone(decoySelectionProof) : null,
      primarySelectionPasteProof: primarySelectionPasteProof
        ? clone(primarySelectionPasteProof) : null,
      pasteProof: pasteProof ? clone(pasteProof) : null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneWheelSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_WHEEL_CASE) {
      throw new Error("M4 wheel case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 wheel result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_WHEEL_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        `M4 wheel base readiness timeout: ${JSON.stringify(readiness)}`);
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 wheel target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 wheel target y", 0, DEFAULT_HEIGHT - 1);
    const listeners = host.enableM4WheelInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4WheelState = {
      state: "awaiting-dom-wheel",
      targetX,
      targetY,
      listeners,
      focusListeners,
    };
    statusElement.textContent = "M4 ready for trusted canvas wheel input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const wheel = readiness.wheelInput;
      const lastQueued = wheel.lastQueued;
      const pageWheel = readiness.pageProbe.wheelEvents;
      if (
        wheel.queuedCount >= 1 &&
        lastQueued?.type === "wheel" &&
        lastQueued?.defaultPrevented === true &&
        pageWheel?.count >= 1 &&
        pageWheel?.trusted === true &&
        pageWheel?.deltaMode === 0 &&
        pageWheel?.deltaX === 0 &&
        pageWheel?.deltaY === 160 &&
        readiness.pageProbe.innerScrollTop > 0 &&
        readiness.pageProbe.outerScrollTop === 0 &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const wheel = readiness?.wheelInput;
    const lastQueued = wheel?.lastQueued;
    const pageWheel = readiness?.pageProbe?.wheelEvents;
    if (
      !readiness ||
      wheel?.queuedCount < 1 ||
      lastQueued?.type !== "wheel" ||
      lastQueued?.defaultPrevented !== true ||
      pageWheel?.count < 1 ||
      pageWheel?.trusted !== true ||
      pageWheel?.deltaMode !== 0 ||
      pageWheel?.deltaX !== 0 ||
      pageWheel?.deltaY !== 160 ||
      !(readiness.pageProbe.innerScrollTop > 0) ||
      readiness.pageProbe.outerScrollTop !== 0 ||
      !(readiness.frame?.id > lastQueued.frameIdBefore)
    ) {
      throw new Error(
        `M4 trusted Ozone wheel timeout: ${JSON.stringify(readiness)}`);
    }
    window.__chromiumWasmM4WheelState = {
      state: "input-delivered",
      targetX,
      targetY,
      wheel: clone(wheel),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      trustedDomInput:
        wheel.trustedCount >= 1 && wheel.queuedCount >= 1 &&
        lastQueued.trusted === true && lastQueued.defaultPrevented === true,
      ozoneDelivered:
        pageWheel.count >= 1 &&
        pageWheel.trusted === true &&
        pageWheel.deltaMode === 0 &&
        pageWheel.deltaX === 0 &&
        pageWheel.deltaY === 160 &&
        readiness.pageProbe.innerScrollTop > 0 &&
        readiness.pageProbe.outerScrollTop === 0 &&
        readiness.frame.id > lastQueued.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_WHEEL_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      wheelInput: wheel,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_WHEEL_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      wheelInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
      }
      try {
        result.readiness = await host.readiness();
        result.wheelInput = result.readiness.wheelInput;
      } catch (diagnosticError) {
        result.error += `; readiness diagnostics: ${String(diagnosticError)}`;
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneTooltipSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let readiness = null;
  let result;
  let tooltipRapidClearProof = null;
  let tooltipShowProof = null;
  let tooltipExitProof = null;

  try {
    if (parameters.get("case") !== M4_TOOLTIP_CASE) {
      throw new Error("M4 tooltip case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 tooltip result token");
    }
    host = new ChromiumWasmM3Host(
      canvas, versions, {fixture: M4_TOOLTIP_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady || !hasM4TooltipPageIdentity(
        readiness.pageProbe)) {
      throw new Error(
        `M4 tooltip base readiness timeout: ${JSON.stringify(readiness)}`);
    }

    const hoverX = Number(readiness.pageProbe.hoverTargetX);
    const hoverY = Number(readiness.pageProbe.hoverTargetY);
    const confirmX = Number(readiness.pageProbe.confirmTargetX);
    const confirmY = Number(readiness.pageProbe.confirmTargetY);
    const confirmTitle = readiness.pageProbe.confirmTitle;
    const clearX = Number(readiness.pageProbe.clearTargetX);
    const clearY = Number(readiness.pageProbe.clearTargetY);
    checkInteger(hoverX, "M4 tooltip hover x", 0, DEFAULT_WIDTH - 1);
    checkInteger(hoverY, "M4 tooltip hover y", 0, DEFAULT_HEIGHT - 1);
    checkInteger(confirmX, "M4 tooltip confirm x", 0, DEFAULT_WIDTH - 1);
    checkInteger(confirmY, "M4 tooltip confirm y", 0, DEFAULT_HEIGHT - 1);
    checkInteger(clearX, "M4 tooltip clear x", 0, DEFAULT_WIDTH - 1);
    checkInteger(clearY, "M4 tooltip clear y", 0, DEFAULT_HEIGHT - 1);
    if (confirmTitle !== "SWAM TOOLTIP") {
      throw new Error("M4 tooltip fixture confirm title mismatch");
    }
    if (
      hoverX + M4_TOOLTIP_CURSOR_OFFSET_X + M4_TOOLTIP_WIDTH >
          DEFAULT_WIDTH ||
      hoverY + M4_TOOLTIP_CURSOR_OFFSET_Y + M4_TOOLTIP_HEIGHT >
          DEFAULT_HEIGHT ||
      confirmX + M4_TOOLTIP_CURSOR_OFFSET_X + M4_TOOLTIP_WIDTH >
          DEFAULT_WIDTH ||
      confirmY + M4_TOOLTIP_CURSOR_OFFSET_Y + M4_TOOLTIP_HEIGHT >
          DEFAULT_HEIGHT ||
      (clearX >= hoverX + M4_TOOLTIP_CURSOR_OFFSET_X &&
       clearX < hoverX + M4_TOOLTIP_CURSOR_OFFSET_X + M4_TOOLTIP_WIDTH &&
       clearY >= hoverY + M4_TOOLTIP_CURSOR_OFFSET_Y &&
       clearY < hoverY + M4_TOOLTIP_CURSOR_OFFSET_Y + M4_TOOLTIP_HEIGHT) ||
      (clearX >= confirmX + M4_TOOLTIP_CURSOR_OFFSET_X &&
       clearX < confirmX + M4_TOOLTIP_CURSOR_OFFSET_X + M4_TOOLTIP_WIDTH &&
       clearY >= confirmY + M4_TOOLTIP_CURSOR_OFFSET_Y &&
       clearY < confirmY + M4_TOOLTIP_CURSOR_OFFSET_Y + M4_TOOLTIP_HEIGHT)
    ) {
      throw new Error("M4 tooltip fixture coordinates overlap the overlay");
    }

    const pointerListeners = host.enableM4PointerInput();
    canvas.focus({preventScroll: true});
    if (document.activeElement !== canvas) {
      throw new Error("M4 tooltip canvas did not retain host focus");
    }
    if (scanM4TooltipOverlay(canvas, hoverX, hoverY, "WASM TOOLTIP") !== null) {
      throw new Error("M4 tooltip overlay was visible before pointer hover");
    }
    window.__chromiumWasmM4TooltipState = {
      state: "awaiting-dom-tooltip-race",
      hoverTargetX: hoverX,
      hoverTargetY: hoverY,
      confirmTargetX: confirmX,
      confirmTargetY: confirmY,
      clearTargetX: clearX,
      clearTargetY: clearY,
      pointerListeners,
    };
    statusElement.textContent = "M4 ready for rapid trusted title clear";

    // Drive a title -> title-less transition before the hover timer can fire.
    // Both DOM elements live in the same RenderWidgetHostViewAura window, so
    // this exercises the renderer callback ordering that a window-only target
    // check cannot distinguish by itself.
    const raceTrace = [
      [hoverX, hoverY],
      [clearX, clearY],
    ];
    const raceInnerTrace = [
      ["tooltip-target", hoverX, hoverY],
      ["clear-target", clearX, clearY],
    ];
    let raceTooltipAbsent = false;
    let raceTooltipAbsenceStartedAt = null;
    let raceTooltipBackgroundPixels = null;
    let raceMoveGapMs = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const raceClearRecord = pointer?.queuedRecords?.[raceTrace.length - 1];
      raceTooltipBackgroundPixels = countM4TooltipBackgroundPixels(canvas);
      raceMoveGapMs = m4TooltipInnerTraceGapMs(readiness.pageProbe, 0, 1);
      const raceInputObserved =
        pointer?.receivedCount === raceTrace.length &&
        pointer?.trustedCount === raceTrace.length &&
        pointer?.queuedCount === raceTrace.length &&
        matchesM4TooltipQueuedPointerTrace(pointer?.queuedRecords, raceTrace) &&
        hasM4TooltipInnerTrace(readiness.pageProbe, raceInnerTrace) &&
        hasM4TooltipTrustedMoveResult(readiness.pageProbe, raceTrace.length) &&
        raceMoveGapMs !== null &&
        raceMoveGapMs <= M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS &&
        readiness.frame?.id > raceClearRecord?.frameIdBefore;
      if (raceInputObserved) {
        if (raceTooltipBackgroundPixels === 0) {
          if (raceTooltipAbsenceStartedAt === null) {
            raceTooltipAbsenceStartedAt = performance.now();
          }
          raceTooltipAbsent = performance.now() -
            raceTooltipAbsenceStartedAt >= M4_TOOLTIP_CLEAR_QUIESCENCE_MS;
        } else {
          raceTooltipAbsenceStartedAt = null;
          raceTooltipAbsent = false;
        }
      }
      if (raceInputObserved && raceTooltipAbsent) {
        break;
      }
      await delay(50);
    }
    const racePointer = readiness?.pointerInput;
    const raceClearRecord =
      racePointer?.queuedRecords?.[raceTrace.length - 1];
    if (
      !readiness || racePointer?.receivedCount !== raceTrace.length ||
      racePointer?.trustedCount !== raceTrace.length ||
      racePointer?.queuedCount !== raceTrace.length ||
      !matchesM4TooltipQueuedPointerTrace(
        racePointer?.queuedRecords, raceTrace) ||
      !hasM4TooltipInnerTrace(readiness.pageProbe, raceInnerTrace) ||
      !hasM4TooltipTrustedMoveResult(readiness.pageProbe, raceTrace.length) ||
      raceMoveGapMs === null ||
      raceMoveGapMs > M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS ||
      !(readiness.frame?.id > raceClearRecord?.frameIdBefore) ||
      !raceTooltipAbsent || raceTooltipBackgroundPixels !== 0
    ) {
      throw new Error(
        "M4 rapid native title clear did not remain absent: " +
        JSON.stringify(readiness));
    }
    tooltipRapidClearProof = {
      frameId: readiness.frame.id,
      backgroundPixels: raceTooltipBackgroundPixels,
      quietForMs: Math.floor(
        performance.now() - raceTooltipAbsenceStartedAt),
      moveGapMs: raceMoveGapMs,
    };
    window.__chromiumWasmM4TooltipState = {
      state: "awaiting-dom-tooltip-hover",
      hoverTargetX: hoverX,
      hoverTargetY: hoverY,
      confirmTargetX: confirmX,
      confirmTargetY: confirmY,
      clearTargetX: clearX,
      clearTargetY: clearY,
      pointerListeners,
      tooltipRapidClearProof: clone(tooltipRapidClearProof),
    };
    statusElement.textContent = "M4 rapid title clear proved; await title hover";

    // Blink intentionally coalesces unchanged tooltip decisions. Require two
    // trusted host moves at the same title point so the native bridge must
    // retain the one logical hover across both physical records.
    const hoverTrace = [...raceTrace, [confirmX, confirmY], [confirmX, confirmY]];
    const hoverInnerTrace = [...raceInnerTrace,
      ["confirm-target", confirmX, confirmY],
      ["confirm-target", confirmX, confirmY]];
    let tooltipOverlay = null;
    let duplicateHoverGapMs = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const hoverRecord = pointer?.queuedRecords?.[hoverTrace.length - 1];
      tooltipOverlay = scanM4TooltipOverlay(
        canvas, confirmX, confirmY, confirmTitle);
      const hasHoverInnerTrace = hasM4TooltipInnerTrace(
          readiness.pageProbe, hoverInnerTrace);
      duplicateHoverGapMs = m4TooltipInnerTraceGapMs(
          readiness.pageProbe, 2, 3);
      if (
        pointer?.receivedCount === hoverTrace.length &&
        pointer?.trustedCount === hoverTrace.length &&
        pointer?.queuedCount === hoverTrace.length &&
        matchesM4TooltipQueuedPointerTrace(pointer?.queuedRecords, hoverTrace) &&
        hasHoverInnerTrace && duplicateHoverGapMs !== null &&
        duplicateHoverGapMs <= M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS &&
        tooltipOverlay !== null &&
        readiness.frame?.id > hoverRecord?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const hoverPointer = readiness?.pointerInput;
    const hoverRecord = hoverPointer?.queuedRecords?.[hoverTrace.length - 1];
    if (
      !readiness || hoverPointer?.receivedCount !== hoverTrace.length ||
      hoverPointer?.trustedCount !== hoverTrace.length ||
      hoverPointer?.queuedCount !== hoverTrace.length ||
      !matchesM4TooltipQueuedPointerTrace(
        hoverPointer?.queuedRecords, hoverTrace) ||
      !hasM4TooltipInnerTrace(readiness.pageProbe, hoverInnerTrace) ||
      !hasM4TooltipTrustedMoveResult(readiness.pageProbe, hoverTrace.length) ||
      duplicateHoverGapMs === null ||
      duplicateHoverGapMs > M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS ||
      tooltipOverlay === null ||
      !(readiness.frame?.id > hoverRecord?.frameIdBefore)
    ) {
      throw new Error(
        `M4 native title tooltip did not appear: ${JSON.stringify(readiness)}`);
    }
    tooltipShowProof = {
      frameId: readiness.frame.id,
      overlay: clone(tooltipOverlay),
      duplicateMoveGapMs: duplicateHoverGapMs,
    };
    window.__chromiumWasmM4TooltipState = {
      state: "awaiting-dom-tooltip-exit",
      hoverTargetX: hoverX,
      hoverTargetY: hoverY,
      confirmTargetX: confirmX,
      confirmTargetY: confirmY,
      clearTargetX: clearX,
      clearTargetY: clearY,
      pointerListeners,
      tooltipShowProof: clone(tooltipShowProof),
    };
    statusElement.textContent = "M4 tooltip visible; await trusted canvas exit";

    const exitSequence = hoverTrace.length + 1;
    let tooltipAbsent = false;
    let tooltipAbsenceStartedAt = null;
    let tooltipBackgroundPixels = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const exitRecord = pointer?.queuedRecords?.[hoverTrace.length];
      // The fixture deliberately contains no tooltip background color. Count
      // it globally so a delayed title update cannot pass by reappearing.
      tooltipBackgroundPixels = countM4TooltipBackgroundPixels(canvas);
      const exitInputObserved =
        pointer?.receivedCount === exitSequence &&
        pointer?.trustedCount === exitSequence &&
        pointer?.queuedCount === exitSequence &&
        matchesM4TooltipQueuedPointerTrace(
          pointer?.queuedRecords?.slice(0, hoverTrace.length), hoverTrace) &&
        matchesM4TooltipQueuedPointerExit(exitRecord, exitSequence) &&
        hasM4TooltipInnerTrace(readiness.pageProbe, hoverInnerTrace) &&
        hasM4TooltipTrustedMoveResult(readiness.pageProbe, hoverTrace.length) &&
        hasM4TooltipInnerMouseExit(
          readiness.pageProbe, "confirm-target", confirmX, confirmY);
      const exitFramePresented = readiness.frame?.id > exitRecord?.frameIdBefore;
      if (exitInputObserved && exitFramePresented) {
        if (tooltipBackgroundPixels === 0) {
          if (tooltipAbsenceStartedAt === null) {
            tooltipAbsenceStartedAt = performance.now();
          }
          // Title updates cross the renderer/browser boundary. Stay quiet for
          // longer than the native hover delay to catch a late re-arm.
          tooltipAbsent = performance.now() - tooltipAbsenceStartedAt >=
            M4_TOOLTIP_CLEAR_QUIESCENCE_MS;
        } else {
          tooltipAbsenceStartedAt = null;
          tooltipAbsent = false;
        }
      }
      if (exitInputObserved && exitFramePresented && tooltipAbsent) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const exitRecord = pointer?.queuedRecords?.[hoverTrace.length];
    if (
      !readiness || pointer?.receivedCount !== exitSequence ||
      pointer?.trustedCount !== exitSequence ||
      pointer?.queuedCount !== exitSequence ||
      !matchesM4TooltipQueuedPointerTrace(
        pointer?.queuedRecords?.slice(0, hoverTrace.length), hoverTrace) ||
      !matchesM4TooltipQueuedPointerExit(exitRecord, exitSequence) ||
      !hasM4TooltipInnerTrace(readiness.pageProbe, hoverInnerTrace) ||
      !hasM4TooltipTrustedMoveResult(readiness.pageProbe, hoverTrace.length) ||
      !hasM4TooltipInnerMouseExit(
        readiness.pageProbe, "confirm-target", confirmX, confirmY) ||
      !tooltipAbsent || tooltipBackgroundPixels !== 0 ||
      !(readiness.frame?.id > exitRecord?.frameIdBefore)
    ) {
      throw new Error(
        `M4 native title tooltip did not exit: ${JSON.stringify(readiness)}`);
    }
    tooltipExitProof = {
      frameId: readiness.frame.id,
      overlayAbsent: true,
      backgroundPixels: tooltipBackgroundPixels,
      quietForMs: Math.floor(performance.now() - tooltipAbsenceStartedAt),
    };
    window.__chromiumWasmM4TooltipState = {
      state: "input-delivered",
      hoverTargetX: hoverX,
      hoverTargetY: hoverY,
      confirmTargetX: confirmX,
      confirmTargetY: confirmY,
      clearTargetX: clearX,
      clearTargetY: clearY,
      pointerListeners,
      tooltipShowProof: clone(tooltipShowProof),
      tooltipExitProof: clone(tooltipExitProof),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      trustedDomInput:
        matchesM4TooltipQueuedPointerTrace(
          pointer.queuedRecords.slice(0, hoverTrace.length), hoverTrace) &&
        matchesM4TooltipQueuedPointerExit(pointer.queuedRecords[hoverTrace.length],
                                          exitSequence) &&
        hasM4TooltipInnerTrace(readiness.pageProbe, hoverInnerTrace) &&
        hasM4TooltipTrustedMoveResult(readiness.pageProbe, hoverTrace.length) &&
        hasM4TooltipInnerMouseExit(
          readiness.pageProbe, "confirm-target", confirmX, confirmY),
      rapidTitleCleared:
        tooltipRapidClearProof.backgroundPixels === 0 &&
        tooltipRapidClearProof.quietForMs >= M4_TOOLTIP_CLEAR_QUIESCENCE_MS &&
        tooltipRapidClearProof.moveGapMs <= M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS,
      nativeTooltipShown:
        tooltipShowProof.overlay !== null &&
        tooltipShowProof.duplicateMoveGapMs <=
          M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS &&
        tooltipShowProof.frameId > hoverRecord.frameIdBefore,
      nativeTooltipExited:
        tooltipExitProof.overlayAbsent === true &&
        tooltipExitProof.backgroundPixels === 0 &&
        tooltipExitProof.frameId > exitRecord.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_TOOLTIP_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      tooltipRapidClearProof,
      tooltipShowProof,
      tooltipExitProof,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : `failed checks: ${failedChecks.join(", ")}`,
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_TOOLTIP_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: readiness?.pointerInput ?? null,
      tooltipRapidClearProof,
      tooltipShowProof,
      tooltipExitProof,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += `; diagnostics: ${String(diagnosticError)}`;
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
      } catch (diagnosticError) {
        result.error += `; readiness diagnostics: ${String(diagnosticError)}`;
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneKeyboardSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_KEYBOARD_CASE) {
      throw new Error("M4 keyboard case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 keyboard result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_KEYBOARD_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 keyboard base readiness timeout: " + JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 keyboard target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 keyboard target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4KeyboardState = {
      state: "awaiting-dom-keyboard-activation",
      targetX,
      targetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click and raw ArrowDown input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "keyboard-target" &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueuedPointer = pointer?.lastQueued;
    const pageAfterActivation = readiness?.pageProbe;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueuedPointer?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "keyboard-target" ||
      !(readiness.frame?.id > lastQueuedPointer.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone keyboard activation timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4KeyboardState = {
      state: "awaiting-dom-key",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(readiness.keyboardInput),
    };
    statusElement.textContent =
      "M4 ready for trusted canvas raw ArrowDown repeat input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const keyDown = keyboard.lastQueuedDown;
      const keyUp = keyboard.lastQueuedUp;
      const queuedTrace = keyboard.queuedRecords;
      const pageProbe = readiness.pageProbe;
      const keyEvents = pageProbe?.keyEvents;
      const innerTrace = keyEvents?.trace;
      const textInputEvents = pageProbe?.textInputEvents;
      if (
        keyboard.queuedCount >= 3 &&
        keyboard.pressedCodes.length === 0 &&
        keyDown?.type === "down" &&
        keyDown?.repeat === true &&
        keyDown?.defaultPrevented === true &&
        keyUp?.type === "up" &&
        keyUp?.repeat === false &&
        keyUp?.defaultPrevented === true &&
        hasM4ArrowDownRepeatQueuedTrace(queuedTrace) &&
        keyEvents?.keydownCount === 2 &&
        keyEvents?.keyupCount === 1 &&
        hasM4ArrowDownRepeatInnerTrace(innerTrace) &&
        textInputEvents?.beforeinputCount === 0 &&
        textInputEvents?.inputCount === 0 &&
        textInputEvents?.compositionstartCount === 0 &&
        textInputEvents?.compositionupdateCount === 0 &&
        textInputEvents?.compositionendCount === 0 &&
        pageProbe?.activeElementId === "keyboard-target" &&
        pageProbe?.scrollTop > 0 &&
        pageProbe?.resultText === "ARROW DOWN RECEIVED" &&
        readiness.frame?.id > keyDown.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboard = readiness?.keyboardInput;
    const lastQueuedDown = keyboard?.lastQueuedDown;
    const lastQueuedUp = keyboard?.lastQueuedUp;
    const queuedTrace = keyboard?.queuedRecords;
    const pageProbe = readiness?.pageProbe;
    const keyEvents = pageProbe?.keyEvents;
    const innerTrace = keyEvents?.trace;
    const textInputEvents = pageProbe?.textInputEvents;
    if (
      !readiness ||
      keyboard?.queuedCount < 3 ||
      keyboard?.pressedCodes?.length !== 0 ||
      lastQueuedDown?.type !== "down" ||
      lastQueuedDown?.repeat !== true ||
      lastQueuedDown?.defaultPrevented !== true ||
      lastQueuedUp?.type !== "up" ||
      lastQueuedUp?.repeat !== false ||
      lastQueuedUp?.defaultPrevented !== true ||
      !hasM4ArrowDownRepeatQueuedTrace(queuedTrace) ||
      keyEvents?.keydownCount !== 2 ||
      keyEvents?.keyupCount !== 1 ||
      !hasM4ArrowDownRepeatInnerTrace(innerTrace) ||
      textInputEvents?.beforeinputCount !== 0 ||
      textInputEvents?.inputCount !== 0 ||
      textInputEvents?.compositionstartCount !== 0 ||
      textInputEvents?.compositionupdateCount !== 0 ||
      textInputEvents?.compositionendCount !== 0 ||
      pageProbe?.activeElementId !== "keyboard-target" ||
      !(pageProbe?.scrollTop > 0) ||
      pageProbe?.resultText !== "ARROW DOWN RECEIVED" ||
      !(readiness.frame?.id > lastQueuedDown.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone keyboard timeout: " + JSON.stringify(readiness));
    }
    window.__chromiumWasmM4KeyboardState = {
      state: "input-delivered",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboard),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      pointerActivation:
        pointer.trustedCount >= 2 &&
        pointer.queuedCount >= 2 &&
        lastQueuedPointer.trusted === true &&
        lastQueuedPointer.queued === true,
      trustedDomInput:
        keyboard.trustedCount >= 3 &&
        keyboard.queuedCount >= 3 &&
        lastQueuedDown.trusted === true &&
        lastQueuedDown.queued === true &&
        lastQueuedDown.repeat === true &&
        lastQueuedDown.defaultPrevented === true &&
        lastQueuedUp.trusted === true &&
        lastQueuedUp.queued === true &&
        lastQueuedUp.repeat === false &&
        lastQueuedUp.defaultPrevented === true,
      ozoneDelivered:
        pageProbe.activationCount === 1 &&
        pageProbe.clickTrusted === true &&
        pageProbe.focusCount >= 1 &&
        pageProbe.focusTrusted === true &&
        pageProbe.activeElementId === "keyboard-target" &&
        hasM4ArrowDownRepeatQueuedTrace(queuedTrace) &&
        keyEvents.keydownCount === 2 &&
        keyEvents.keyupCount === 1 &&
        hasM4ArrowDownRepeatInnerTrace(innerTrace) &&
        textInputEvents.beforeinputCount === 0 &&
        textInputEvents.inputCount === 0 &&
        textInputEvents.compositionstartCount === 0 &&
        textInputEvents.compositionupdateCount === 0 &&
        textInputEvents.compositionendCount === 0 &&
        pageProbe.scrollTop > 0 &&
        pageProbe.resultText === "ARROW DOWN RECEIVED" &&
        readiness.frame.id > lastQueuedDown.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_KEYBOARD_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_KEYBOARD_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzonePrintableKeySmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  const keyAQueue = [
    ["down", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
    ["up", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const keyBQueue = [
    ["down", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
    ["up", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
  ];
  const fullKeyQueue = [...keyAQueue, ...keyBQueue];
  const keyATrace = [
    ["keydown", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
    ["keyup", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const keyBTrace = [
    ["keydown", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
    ["keyup", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
  ];
  const fullKeyTrace = [...keyATrace, ...keyBTrace];
  const keyATextTrace = [
    ["beforeinput", M4_PRINTABLE_KEY_DOM_KEY],
    ["input", M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const keyBTextTrace = [
    ["beforeinput", M4_PRINTABLE_KEY_B_DOM_KEY],
    ["input", M4_PRINTABLE_KEY_B_DOM_KEY],
  ];
  const fullTextTrace = [...keyATextTrace, ...keyBTextTrace];
  const expectedModifiers = {
    alt: false,
    control: false,
    meta: false,
    shift: false,
  };
  const matchesOuterTrace = (keyboard, expected) => {
    const records = keyboard?.queuedRecords;
    return Array.isArray(records) && records.length === expected.length &&
      records.every((record, index) => {
        const [type, code, key] = expected[index];
        return record?.type === type && record?.code === code &&
          record?.key === key && record?.trusted === true &&
          record?.queued === true && record?.repeat === false &&
          record?.isComposing === false && record?.canvasFocused === true &&
          record?.pointerActivated === true &&
          record?.defaultPrevented === true &&
          JSON.stringify(record?.modifiers) === JSON.stringify(expectedModifiers) &&
          Number.isSafeInteger(record?.frameIdBefore) &&
          record.frameIdBefore >= 1;
      });
  };
  const matchesInnerKeyTrace = (trace, expected) =>
    Array.isArray(trace) && trace.length === expected.length &&
    trace.every((record, index) => {
      const [type, code, key] = expected[index];
      return record?.type === type && record?.trusted === true &&
        record?.code === code && record?.key === key &&
        record?.repeat === false && record?.isComposing === false &&
        record?.defaultPrevented === false &&
        record?.targetId === "editable-target";
    });
  const matchesTextTrace = (trace, expected) =>
    Array.isArray(trace) && trace.length === expected.length &&
    trace.every((record, index) => {
      const [type, data] = expected[index];
      return record?.type === type && record?.trusted === true &&
        record?.inputType === "insertText" && record?.data === data &&
        record?.isComposing === false &&
        record?.targetId === "editable-target";
    });
  const hasNoComposition = (pageProbe) =>
    pageProbe?.textInputEvents?.compositionstartCount === 0 &&
    pageProbe?.textInputEvents?.compositionupdateCount === 0 &&
    pageProbe?.textInputEvents?.compositionendCount === 0;
  const matchesTextCounts = (pageProbe, count) =>
    pageProbe?.textInputEvents?.beforeinputCount === count &&
    pageProbe?.textInputEvents?.inputCount === count;

  try {
    if (parameters.get("case") !== M4_PRINTABLE_KEY_CASE) {
      throw new Error("M4 printable-key case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 printable-key result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_PRINTABLE_KEY_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 printable-key base readiness timeout: " +
        JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 printable-key target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 printable-key target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4PrintableKeyState = {
      state: "awaiting-dom-printable-key-activation",
      targetX,
      targetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click and raw KeyA then KeyB input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "" &&
        pageProbe?.selectionStart === 0 &&
        pageProbe?.selectionEnd === 0 &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueuedPointer = pointer?.lastQueued;
    const pageAfterActivation = readiness?.pageProbe;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueuedPointer?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "editable-target" ||
      pageAfterActivation?.value !== "" ||
      pageAfterActivation?.selectionStart !== 0 ||
      pageAfterActivation?.selectionEnd !== 0 ||
      !(readiness.frame?.id > lastQueuedPointer.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone printable-key activation timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4PrintableKeyState = {
      state: "awaiting-dom-printable-key",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(readiness.keyboardInput),
    };
    statusElement.textContent =
      "M4 ready for trusted canvas raw KeyA input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      if (
        keyboard?.receivedCount === 2 &&
        keyboard?.trustedCount === 2 &&
        keyboard?.queuedCount === 2 &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesOuterTrace(keyboard, keyAQueue) &&
        pageProbe?.keyEvents?.keydownCount === 1 &&
        pageProbe?.keyEvents?.keyupCount === 1 &&
        matchesInnerKeyTrace(pageProbe?.keyEventTrace, keyATrace) &&
        matchesTextCounts(pageProbe, 1) &&
        matchesTextTrace(pageProbe?.textInputTrace, keyATextTrace) &&
        hasNoComposition(pageProbe) &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "a" &&
        pageProbe?.selectionStart === 1 &&
        pageProbe?.selectionEnd === 1 &&
        pageProbe?.resultText === "TEXT INPUT PARTIAL" &&
        readiness.frame?.id > keyboard.queuedRecords[0].frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboardAfterKeyA = readiness?.keyboardInput;
    const pageAfterKeyA = readiness?.pageProbe;
    if (
      !readiness ||
      keyboardAfterKeyA?.receivedCount !== 2 ||
      keyboardAfterKeyA?.trustedCount !== 2 ||
      keyboardAfterKeyA?.queuedCount !== 2 ||
      keyboardAfterKeyA?.pressedCodes?.length !== 0 ||
      !matchesOuterTrace(keyboardAfterKeyA, keyAQueue) ||
      pageAfterKeyA?.keyEvents?.keydownCount !== 1 ||
      pageAfterKeyA?.keyEvents?.keyupCount !== 1 ||
      !matchesInnerKeyTrace(pageAfterKeyA?.keyEventTrace, keyATrace) ||
      !matchesTextCounts(pageAfterKeyA, 1) ||
      !matchesTextTrace(pageAfterKeyA?.textInputTrace, keyATextTrace) ||
      !hasNoComposition(pageAfterKeyA) ||
      pageAfterKeyA?.activeElementId !== "editable-target" ||
      pageAfterKeyA?.value !== "a" ||
      pageAfterKeyA?.selectionStart !== 1 ||
      pageAfterKeyA?.selectionEnd !== 1 ||
      pageAfterKeyA?.resultText !== "TEXT INPUT PARTIAL" ||
      !(readiness.frame?.id > keyboardAfterKeyA?.queuedRecords?.[0]?.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone KeyA insert timeout before KeyB: " +
        JSON.stringify(readiness));
    }
    const keyAProof = {
      outerTraceExact: matchesOuterTrace(keyboardAfterKeyA, keyAQueue),
      innerTraceExact: matchesInnerKeyTrace(
          pageAfterKeyA?.keyEventTrace, keyATrace),
      textTraceExact: matchesTextTrace(
          pageAfterKeyA?.textInputTrace, keyATextTrace),
      noComposition: hasNoComposition(pageAfterKeyA),
      value: pageAfterKeyA?.value,
      selectionStart: pageAfterKeyA?.selectionStart,
      selectionEnd: pageAfterKeyA?.selectionEnd,
      frameAfterKeyADown:
        readiness.frame?.id > keyboardAfterKeyA?.queuedRecords?.[0]?.frameIdBefore,
    };
    window.__chromiumWasmM4PrintableKeyState = {
      state: "awaiting-dom-printable-key-b",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboardAfterKeyA),
      keyAProof,
    };
    statusElement.textContent = "M4 ready for trusted canvas raw KeyB input";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      if (
        keyboard?.receivedCount === 4 &&
        keyboard?.trustedCount === 4 &&
        keyboard?.queuedCount === 4 &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesOuterTrace(keyboard, fullKeyQueue) &&
        pageProbe?.keyEvents?.keydownCount === 2 &&
        pageProbe?.keyEvents?.keyupCount === 2 &&
        matchesInnerKeyTrace(pageProbe?.keyEventTrace, fullKeyTrace) &&
        matchesTextCounts(pageProbe, 2) &&
        matchesTextTrace(pageProbe?.textInputTrace, fullTextTrace) &&
        hasNoComposition(pageProbe) &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "ab" &&
        pageProbe?.selectionStart === 2 &&
        pageProbe?.selectionEnd === 2 &&
        pageProbe?.resultText === "TEXT INPUT RECEIVED" &&
        readiness.frame?.id > keyboard.queuedRecords[2].frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboard = readiness?.keyboardInput;
    const pageProbe = readiness?.pageProbe;
    if (
      !readiness ||
      keyboard?.receivedCount !== 4 ||
      keyboard?.trustedCount !== 4 ||
      keyboard?.queuedCount !== 4 ||
      keyboard?.pressedCodes?.length !== 0 ||
      !matchesOuterTrace(keyboard, fullKeyQueue) ||
      pageProbe?.keyEvents?.keydownCount !== 2 ||
      pageProbe?.keyEvents?.keyupCount !== 2 ||
      !matchesInnerKeyTrace(pageProbe?.keyEventTrace, fullKeyTrace) ||
      !matchesTextCounts(pageProbe, 2) ||
      !matchesTextTrace(pageProbe?.textInputTrace, fullTextTrace) ||
      !hasNoComposition(pageProbe) ||
      pageProbe?.activeElementId !== "editable-target" ||
      pageProbe?.value !== "ab" ||
      pageProbe?.selectionStart !== 2 ||
      pageProbe?.selectionEnd !== 2 ||
      pageProbe?.resultText !== "TEXT INPUT RECEIVED" ||
      !(readiness.frame?.id > keyboard?.queuedRecords?.[2]?.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone KeyA then KeyB timeout: " +
        JSON.stringify(readiness));
    }
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      pointerActivation:
        pointer.trustedCount >= 2 &&
        pointer.queuedCount >= 2 &&
        lastQueuedPointer.trusted === true &&
        lastQueuedPointer.queued === true,
      trustedDomInput:
        keyboard.receivedCount === 4 &&
        keyboard.trustedCount === 4 &&
        keyboard.queuedCount === 4 &&
        matchesOuterTrace(keyboard, fullKeyQueue),
      ozoneDelivered:
        pageProbe.activationCount === 1 &&
        pageProbe.clickTrusted === true &&
        pageProbe.focusCount >= 1 &&
        pageProbe.focusTrusted === true &&
        pageProbe.activeElementId === "editable-target" &&
        pageProbe.keyEvents.keydownCount === 2 &&
        pageProbe.keyEvents.keyupCount === 2 &&
        matchesInnerKeyTrace(pageProbe.keyEventTrace, fullKeyTrace) &&
        matchesTextCounts(pageProbe, 2) &&
        matchesTextTrace(pageProbe.textInputTrace, fullTextTrace) &&
        hasNoComposition(pageProbe) &&
        pageProbe.value === "ab" &&
        pageProbe.selectionStart === 2 &&
        pageProbe.selectionEnd === 2 &&
        pageProbe.resultText === "TEXT INPUT RECEIVED" &&
        readiness.frame.id > keyboard.queuedRecords[2].frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_PRINTABLE_KEY_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      keyAProof,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_PRINTABLE_KEY_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneBackspaceSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
      1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  const keyAQueue = [
    ["down", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
    ["up", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const keyABQueue = [
    ...keyAQueue,
    ["down", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
    ["up", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
  ];
  const backspaceDownQueue = [
    ...keyABQueue,
    ["down", M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, false],
  ];
  const backspaceRepeatQueue = [
    ...backspaceDownQueue,
    ["down", M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, true],
  ];
  const fullKeyQueue = [
    ...backspaceRepeatQueue,
    ["up", M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, false],
  ];
  const keyATextTrace = [
    ["beforeinput", "insertText", M4_PRINTABLE_KEY_DOM_KEY],
    ["input", "insertText", M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const keyABTextTrace = [
    ...keyATextTrace,
    ["beforeinput", "insertText", M4_PRINTABLE_KEY_B_DOM_KEY],
    ["input", "insertText", M4_PRINTABLE_KEY_B_DOM_KEY],
  ];
  const backspaceDownTextTrace = [
    ...keyABTextTrace,
    ["beforeinput", "deleteContentBackward", null],
    ["input", "deleteContentBackward", null],
  ];
  const fullTextTrace = [
    ...backspaceDownTextTrace,
    ["beforeinput", "deleteContentBackward", null],
    ["input", "deleteContentBackward", null],
  ];
  let host = null;
  let result;
  let keyAProof = null;
  let keyBProof = null;
  let backspaceRepeatProof = null;

  try {
    if (parameters.get("case") !== M4_BACKSPACE_CASE) {
      throw new Error("M4 backspace case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 backspace result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_BACKSPACE_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
          "M4 backspace base readiness timeout: " + JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 backspace target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 backspace target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4BackspaceState = {
      state: "awaiting-dom-backspace-activation",
      targetX,
      targetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click, raw KeyA, KeyB, then held Backspace";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "" &&
        pageProbe?.selectionStart === 0 &&
        pageProbe?.selectionEnd === 0 &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueuedPointer = pointer?.lastQueued;
    const pageAfterActivation = readiness?.pageProbe;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueuedPointer?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "editable-target" ||
      pageAfterActivation?.value !== "" ||
      pageAfterActivation?.selectionStart !== 0 ||
      pageAfterActivation?.selectionEnd !== 0 ||
      !(readiness.frame?.id > lastQueuedPointer.frameIdBefore)
    ) {
      throw new Error(
          "M4 trusted Ozone backspace activation timeout: " +
          JSON.stringify(readiness));
    }
    window.__chromiumWasmM4BackspaceState = {
      state: "awaiting-dom-backspace-key-a",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(readiness.keyboardInput),
    };
    statusElement.textContent = "M4 ready for trusted canvas raw KeyA input";

    // The runner must wait for this first normal Blink edit before it sends
    // KeyB, then freezes the resulting KeyA/KeyB proof before Backspace. That
    // makes the deletion proof depend on the physical Ozone/Aura route rather
    // than a pre-populated or DevTools-inserted field value.
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      const queuedRecords = keyboard?.queuedRecords;
      const keyTrace = pageProbe?.keyEventTrace;
      const textTrace = pageProbe?.textInputTrace;
      const compositionCounts = pageProbe?.compositionEventCounts;
      const keyADown = queuedRecords?.[0];
      if (
        keyboard?.receivedCount === 2 &&
        keyboard?.trustedCount === 2 &&
        keyboard?.queuedCount === 2 &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesM4BackspaceKeyPrefix(queuedRecords, keyAQueue) &&
        matchesM4BackspaceInnerKeyTrace(keyTrace, [
          ["keydown", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
          ["keyup", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
        ]) &&
        matchesM4BackspaceTextTrace(textTrace, keyATextTrace) &&
        compositionCounts?.compositionstart === 0 &&
        compositionCounts?.compositionupdate === 0 &&
        compositionCounts?.compositionend === 0 &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === M4_PRINTABLE_KEY_DOM_KEY &&
        pageProbe?.selectionStart === 1 &&
        pageProbe?.selectionEnd === 1 &&
        readiness.frame?.id > keyADown?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboardAfterKeyA = readiness?.keyboardInput;
    const pageAfterKeyA = readiness?.pageProbe;
    const keyAQueuedRecords = keyboardAfterKeyA?.queuedRecords;
    if (
      !readiness ||
      keyboardAfterKeyA?.receivedCount !== 2 ||
      keyboardAfterKeyA?.trustedCount !== 2 ||
      keyboardAfterKeyA?.queuedCount !== 2 ||
      keyboardAfterKeyA?.pressedCodes?.length !== 0 ||
      !matchesM4BackspaceKeyPrefix(keyAQueuedRecords, keyAQueue) ||
      !matchesM4BackspaceInnerKeyTrace(pageAfterKeyA?.keyEventTrace, [
        ["keydown", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
        ["keyup", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
      ]) ||
      !matchesM4BackspaceTextTrace(
          pageAfterKeyA?.textInputTrace, keyATextTrace) ||
      pageAfterKeyA?.compositionEventCounts?.compositionstart !== 0 ||
      pageAfterKeyA?.compositionEventCounts?.compositionupdate !== 0 ||
      pageAfterKeyA?.compositionEventCounts?.compositionend !== 0 ||
      pageAfterKeyA?.activeElementId !== "editable-target" ||
      pageAfterKeyA?.value !== M4_PRINTABLE_KEY_DOM_KEY ||
      pageAfterKeyA?.selectionStart !== 1 ||
      pageAfterKeyA?.selectionEnd !== 1 ||
      !(readiness.frame?.id > keyAQueuedRecords?.[0]?.frameIdBefore)
    ) {
      throw new Error(
          "M4 trusted Ozone KeyA insert timeout before KeyB: " +
          JSON.stringify(readiness));
    }
    keyAProof = {
      outerTraceExact: matchesM4BackspaceKeyPrefix(
          keyAQueuedRecords, keyAQueue),
      innerTraceExact: matchesM4BackspaceInnerKeyTrace(
          pageAfterKeyA?.keyEventTrace, [
            ["keydown", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
            ["keyup", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
          ]),
      textTraceExact: matchesM4BackspaceTextTrace(
          pageAfterKeyA?.textInputTrace, keyATextTrace),
      noComposition:
        pageAfterKeyA?.compositionEventCounts?.compositionstart === 0 &&
        pageAfterKeyA?.compositionEventCounts?.compositionupdate === 0 &&
        pageAfterKeyA?.compositionEventCounts?.compositionend === 0,
      value: pageAfterKeyA?.value,
      selectionStart: pageAfterKeyA?.selectionStart,
      selectionEnd: pageAfterKeyA?.selectionEnd,
      frameAfterKeyADown:
        readiness.frame?.id > keyAQueuedRecords?.[0]?.frameIdBefore,
    };
    window.__chromiumWasmM4BackspaceState = {
      state: "awaiting-dom-backspace-key-b",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboardAfterKeyA),
      keyAProof,
    };
    statusElement.textContent = "M4 ready for trusted canvas raw KeyB input";

    // Freeze the normal KeyA/KeyB editing path before deletion so neither
    // physical Backspace record can operate on a pre-populated field value.
    const keyABInnerTrace = [
      ["keydown", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
      ["keyup", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
      ["keydown", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
      ["keyup", M4_PRINTABLE_KEY_B_DOM_CODE, M4_PRINTABLE_KEY_B_DOM_KEY],
    ];
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      const queuedRecords = keyboard?.queuedRecords;
      const keyBDown = queuedRecords?.[2];
      if (
        keyboard?.receivedCount === 4 &&
        keyboard?.trustedCount === 4 &&
        keyboard?.queuedCount === 4 &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesM4BackspaceKeyPrefix(queuedRecords, keyABQueue) &&
        matchesM4BackspaceInnerKeyTrace(
            pageProbe?.keyEventTrace, keyABInnerTrace) &&
        matchesM4BackspaceTextTrace(
            pageProbe?.textInputTrace, keyABTextTrace) &&
        hasM4BackspaceNoComposition(pageProbe) &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "ab" &&
        pageProbe?.selectionStart === 2 &&
        pageProbe?.selectionEnd === 2 &&
        readiness.frame?.id > keyBDown?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboardAfterKeyB = readiness?.keyboardInput;
    const pageAfterKeyB = readiness?.pageProbe;
    const keyBQueuedRecords = keyboardAfterKeyB?.queuedRecords;
    if (
      !readiness ||
      keyboardAfterKeyB?.receivedCount !== 4 ||
      keyboardAfterKeyB?.trustedCount !== 4 ||
      keyboardAfterKeyB?.queuedCount !== 4 ||
      keyboardAfterKeyB?.pressedCodes?.length !== 0 ||
      !matchesM4BackspaceKeyPrefix(keyBQueuedRecords, keyABQueue) ||
      !matchesM4BackspaceInnerKeyTrace(
          pageAfterKeyB?.keyEventTrace, keyABInnerTrace) ||
      !matchesM4BackspaceTextTrace(
          pageAfterKeyB?.textInputTrace, keyABTextTrace) ||
      !hasM4BackspaceNoComposition(pageAfterKeyB) ||
      pageAfterKeyB?.activeElementId !== "editable-target" ||
      pageAfterKeyB?.value !== "ab" ||
      pageAfterKeyB?.selectionStart !== 2 ||
      pageAfterKeyB?.selectionEnd !== 2 ||
      !(readiness.frame?.id > keyBQueuedRecords?.[2]?.frameIdBefore)
    ) {
      throw new Error(
          "M4 trusted Ozone KeyB insert timeout before Backspace: " +
          JSON.stringify(readiness));
    }
    keyBProof = {
      outerTraceExact: matchesM4BackspaceKeyPrefix(
          keyBQueuedRecords, keyABQueue),
      innerTraceExact: matchesM4BackspaceInnerKeyTrace(
          pageAfterKeyB?.keyEventTrace, keyABInnerTrace),
      textTraceExact: matchesM4BackspaceTextTrace(
          pageAfterKeyB?.textInputTrace, keyABTextTrace),
      noComposition: hasM4BackspaceNoComposition(pageAfterKeyB),
      value: pageAfterKeyB?.value,
      selectionStart: pageAfterKeyB?.selectionStart,
      selectionEnd: pageAfterKeyB?.selectionEnd,
      frameAfterKeyBDown:
        readiness.frame?.id > keyBQueuedRecords?.[2]?.frameIdBefore,
    };
    window.__chromiumWasmM4BackspaceState = {
      state: "awaiting-dom-backspace-down",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboardAfterKeyB),
      keyAProof,
      keyBProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas raw Backspace down input";

    const backspaceDownInnerTrace = [
      ...keyABInnerTrace,
      ["keydown", M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, false],
    ];
    const backspaceRepeatInnerTrace = [
      ...backspaceDownInnerTrace,
      ["keydown", M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, true],
    ];
    const fullBackspaceInnerTrace = [
      ...backspaceRepeatInnerTrace,
      ["keyup", M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, false],
    ];
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      const queuedRecords = keyboard?.queuedRecords;
      const backspaceDown = queuedRecords?.[4];
      if (
        keyboard?.receivedCount === 5 &&
        keyboard?.trustedCount === 5 &&
        keyboard?.queuedCount === 5 &&
        hasM4BackspaceHeldCode(keyboard) &&
        matchesM4BackspaceKeyPrefix(queuedRecords, backspaceDownQueue) &&
        matchesM4BackspaceOuterKeyRecord(
            keyboard?.lastQueuedDown, "down", M4_BACKSPACE_DOM_CODE,
            M4_BACKSPACE_DOM_KEY, false) &&
        keyboard?.lastQueuedDown?.sequence === backspaceDown?.sequence &&
        matchesM4BackspaceInnerKeyTrace(
            pageProbe?.keyEventTrace, backspaceDownInnerTrace) &&
        matchesM4BackspaceTextTrace(
            pageProbe?.textInputTrace, backspaceDownTextTrace) &&
        hasM4BackspaceNoComposition(pageProbe) &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "a" &&
        pageProbe?.selectionStart === 1 &&
        pageProbe?.selectionEnd === 1 &&
        readiness.frame?.id > backspaceDown?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboardAfterBackspaceDown = readiness?.keyboardInput;
    const pageAfterBackspaceDown = readiness?.pageProbe;
    const backspaceDownQueuedRecords = keyboardAfterBackspaceDown?.queuedRecords;
    const initialBackspaceDownRecord = backspaceDownQueuedRecords?.[4];
    if (
      !readiness ||
      keyboardAfterBackspaceDown?.receivedCount !== 5 ||
      keyboardAfterBackspaceDown?.trustedCount !== 5 ||
      keyboardAfterBackspaceDown?.queuedCount !== 5 ||
      !hasM4BackspaceHeldCode(keyboardAfterBackspaceDown) ||
      !matchesM4BackspaceKeyPrefix(
          backspaceDownQueuedRecords, backspaceDownQueue) ||
      !matchesM4BackspaceOuterKeyRecord(
          keyboardAfterBackspaceDown?.lastQueuedDown, "down",
          M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, false) ||
      keyboardAfterBackspaceDown?.lastQueuedDown?.sequence !==
          initialBackspaceDownRecord?.sequence ||
      !matchesM4BackspaceInnerKeyTrace(
          pageAfterBackspaceDown?.keyEventTrace, backspaceDownInnerTrace) ||
      !matchesM4BackspaceTextTrace(
          pageAfterBackspaceDown?.textInputTrace, backspaceDownTextTrace) ||
      !hasM4BackspaceNoComposition(pageAfterBackspaceDown) ||
      pageAfterBackspaceDown?.activeElementId !== "editable-target" ||
      pageAfterBackspaceDown?.value !== "a" ||
      pageAfterBackspaceDown?.selectionStart !== 1 ||
      pageAfterBackspaceDown?.selectionEnd !== 1 ||
      !(readiness.frame?.id > initialBackspaceDownRecord?.frameIdBefore)
    ) {
      throw new Error(
          "M4 trusted Ozone Backspace initial delete timeout: " +
          JSON.stringify(readiness));
    }
    const backspaceDownProof = {
      outerTraceExact: matchesM4BackspaceKeyPrefix(
          backspaceDownQueuedRecords, backspaceDownQueue),
      innerTraceExact: matchesM4BackspaceInnerKeyTrace(
          pageAfterBackspaceDown?.keyEventTrace, backspaceDownInnerTrace),
      textTraceExact: matchesM4BackspaceTextTrace(
          pageAfterBackspaceDown?.textInputTrace, backspaceDownTextTrace),
      noComposition: hasM4BackspaceNoComposition(pageAfterBackspaceDown),
      initialDownRepeatFalse:
        initialBackspaceDownRecord?.repeat === false &&
        pageAfterBackspaceDown?.keyEventTrace?.[4]?.repeat === false,
      backspaceHeld: hasM4BackspaceHeldCode(keyboardAfterBackspaceDown),
      value: pageAfterBackspaceDown?.value,
      selectionStart: pageAfterBackspaceDown?.selectionStart,
      selectionEnd: pageAfterBackspaceDown?.selectionEnd,
      frameAfterBackspaceDown:
        readiness.frame?.id > initialBackspaceDownRecord?.frameIdBefore,
    };
    window.__chromiumWasmM4BackspaceState = {
      state: "awaiting-dom-backspace-repeat",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboardAfterBackspaceDown),
      keyAProof,
      keyBProof,
      backspaceDownProof,
    };
    statusElement.textContent =
      "M4 ready for one trusted canvas raw Backspace repeat";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      const queuedRecords = keyboard?.queuedRecords;
      const backspaceRepeatDown = queuedRecords?.[5];
      if (
        keyboard?.receivedCount === 6 &&
        keyboard?.trustedCount === 6 &&
        keyboard?.queuedCount === 6 &&
        hasM4BackspaceHeldCode(keyboard) &&
        matchesM4BackspaceKeyPrefix(queuedRecords, backspaceRepeatQueue) &&
        matchesM4BackspaceOuterKeyRecord(
            keyboard?.lastQueuedDown, "down", M4_BACKSPACE_DOM_CODE,
            M4_BACKSPACE_DOM_KEY, true) &&
        keyboard?.lastQueuedDown?.sequence === backspaceRepeatDown?.sequence &&
        matchesM4BackspaceInnerKeyTrace(
            pageProbe?.keyEventTrace, backspaceRepeatInnerTrace) &&
        matchesM4BackspaceTextTrace(
            pageProbe?.textInputTrace, fullTextTrace) &&
        hasM4BackspaceNoComposition(pageProbe) &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "" &&
        pageProbe?.selectionStart === 0 &&
        pageProbe?.selectionEnd === 0 &&
        pageProbe?.resultText === "TEXT INSERTED THEN REPEATEDLY DELETED" &&
        readiness.frame?.id > backspaceRepeatDown?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboardAfterBackspaceRepeat = readiness?.keyboardInput;
    const pageAfterBackspaceRepeat = readiness?.pageProbe;
    const backspaceRepeatQueuedRecords =
      keyboardAfterBackspaceRepeat?.queuedRecords;
    const repeatedBackspaceDownRecord = backspaceRepeatQueuedRecords?.[5];
    if (
      !readiness ||
      keyboardAfterBackspaceRepeat?.receivedCount !== 6 ||
      keyboardAfterBackspaceRepeat?.trustedCount !== 6 ||
      keyboardAfterBackspaceRepeat?.queuedCount !== 6 ||
      !hasM4BackspaceHeldCode(keyboardAfterBackspaceRepeat) ||
      !matchesM4BackspaceKeyPrefix(
          backspaceRepeatQueuedRecords, backspaceRepeatQueue) ||
      !matchesM4BackspaceOuterKeyRecord(
          keyboardAfterBackspaceRepeat?.lastQueuedDown, "down",
          M4_BACKSPACE_DOM_CODE, M4_BACKSPACE_DOM_KEY, true) ||
      keyboardAfterBackspaceRepeat?.lastQueuedDown?.sequence !==
          repeatedBackspaceDownRecord?.sequence ||
      !matchesM4BackspaceInnerKeyTrace(
          pageAfterBackspaceRepeat?.keyEventTrace, backspaceRepeatInnerTrace) ||
      !matchesM4BackspaceTextTrace(
          pageAfterBackspaceRepeat?.textInputTrace, fullTextTrace) ||
      !hasM4BackspaceNoComposition(pageAfterBackspaceRepeat) ||
      pageAfterBackspaceRepeat?.activeElementId !== "editable-target" ||
      pageAfterBackspaceRepeat?.value !== "" ||
      pageAfterBackspaceRepeat?.selectionStart !== 0 ||
      pageAfterBackspaceRepeat?.selectionEnd !== 0 ||
      pageAfterBackspaceRepeat?.resultText !==
          "TEXT INSERTED THEN REPEATEDLY DELETED" ||
      !(readiness.frame?.id > repeatedBackspaceDownRecord?.frameIdBefore)
    ) {
      throw new Error(
          "M4 trusted Ozone Backspace repeat delete timeout: " +
          JSON.stringify(readiness));
    }
    const backspaceRepeatPendingProof = {
      outerTraceExact: matchesM4BackspaceKeyPrefix(
          backspaceRepeatQueuedRecords, backspaceRepeatQueue),
      innerTraceExact: matchesM4BackspaceInnerKeyTrace(
          pageAfterBackspaceRepeat?.keyEventTrace, backspaceRepeatInnerTrace),
      textTraceExact: matchesM4BackspaceTextTrace(
          pageAfterBackspaceRepeat?.textInputTrace, fullTextTrace),
      noComposition: hasM4BackspaceNoComposition(pageAfterBackspaceRepeat),
      initialDownRepeatFalse:
        backspaceRepeatQueuedRecords?.[4]?.repeat === false &&
        pageAfterBackspaceRepeat?.keyEventTrace?.[4]?.repeat === false,
      repeatedDownRepeatTrue:
        repeatedBackspaceDownRecord?.repeat === true &&
        pageAfterBackspaceRepeat?.keyEventTrace?.[5]?.repeat === true,
      repeatExact:
        backspaceRepeatQueuedRecords?.[4]?.repeat === false &&
        repeatedBackspaceDownRecord?.repeat === true &&
        pageAfterBackspaceRepeat?.keyEventTrace?.[4]?.repeat === false &&
        pageAfterBackspaceRepeat?.keyEventTrace?.[5]?.repeat === true,
      backspaceHeld: hasM4BackspaceHeldCode(keyboardAfterBackspaceRepeat),
      value: pageAfterBackspaceRepeat?.value,
      selectionStart: pageAfterBackspaceRepeat?.selectionStart,
      selectionEnd: pageAfterBackspaceRepeat?.selectionEnd,
      frameAfterRepeatDown:
        readiness.frame?.id > repeatedBackspaceDownRecord?.frameIdBefore,
    };
    window.__chromiumWasmM4BackspaceState = {
      state: "awaiting-dom-backspace-up",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboardAfterBackspaceRepeat),
      keyAProof,
      keyBProof,
      backspaceDownProof,
      backspaceRepeatPendingProof,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas raw Backspace release";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      const queuedRecords = keyboard?.queuedRecords;
      const backspaceRepeatDown = queuedRecords?.[5];
      if (
        keyboard?.receivedCount === 7 &&
        keyboard?.trustedCount === 7 &&
        keyboard?.queuedCount === 7 &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesM4BackspaceKeyPrefix(queuedRecords, fullKeyQueue) &&
        matchesM4BackspaceOuterKeyRecord(
            keyboard?.lastQueuedDown, "down", M4_BACKSPACE_DOM_CODE,
            M4_BACKSPACE_DOM_KEY, true) &&
        keyboard?.lastQueuedDown?.sequence === backspaceRepeatDown?.sequence &&
        matchesM4BackspaceOuterKeyRecord(
            keyboard?.lastQueuedUp, "up", M4_BACKSPACE_DOM_CODE,
            M4_BACKSPACE_DOM_KEY) &&
        keyboard?.lastQueuedUp?.sequence === queuedRecords?.[6]?.sequence &&
        matchesM4BackspaceInnerKeyTrace(
            pageProbe?.keyEventTrace, fullBackspaceInnerTrace) &&
        matchesM4BackspaceTextTrace(
            pageProbe?.textInputTrace, fullTextTrace) &&
        hasM4BackspaceNoComposition(pageProbe) &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.value === "" &&
        pageProbe?.selectionStart === 0 &&
        pageProbe?.selectionEnd === 0 &&
        pageProbe?.resultText === "TEXT INSERTED THEN REPEATEDLY DELETED" &&
        readiness.frame?.id > backspaceRepeatDown?.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const keyboard = readiness?.keyboardInput;
    const queuedRecords = keyboard?.queuedRecords;
    const pageProbe = readiness?.pageProbe;
    const initialBackspaceDown = queuedRecords?.[4];
    const repeatedBackspaceDown = queuedRecords?.[5];
    const backspaceUp = queuedRecords?.[6];
    if (
      !readiness ||
      keyboard?.receivedCount !== 7 ||
      keyboard?.trustedCount !== 7 ||
      keyboard?.queuedCount !== 7 ||
      keyboard?.pressedCodes?.length !== 0 ||
      !matchesM4BackspaceKeyPrefix(queuedRecords, fullKeyQueue) ||
      !matchesM4BackspaceOuterKeyRecord(
          keyboard?.lastQueuedDown, "down", M4_BACKSPACE_DOM_CODE,
          M4_BACKSPACE_DOM_KEY, true) ||
      keyboard?.lastQueuedDown?.sequence !== repeatedBackspaceDown?.sequence ||
      !matchesM4BackspaceOuterKeyRecord(
          keyboard?.lastQueuedUp, "up", M4_BACKSPACE_DOM_CODE,
          M4_BACKSPACE_DOM_KEY) ||
      keyboard?.lastQueuedUp?.sequence !== backspaceUp?.sequence ||
      !matchesM4BackspaceInnerKeyTrace(
          pageProbe?.keyEventTrace, fullBackspaceInnerTrace) ||
      !matchesM4BackspaceTextTrace(pageProbe?.textInputTrace, fullTextTrace) ||
      !hasM4BackspaceNoComposition(pageProbe) ||
      pageProbe?.activeElementId !== "editable-target" ||
      pageProbe?.value !== "" ||
      pageProbe?.selectionStart !== 0 ||
      pageProbe?.selectionEnd !== 0 ||
      pageProbe?.resultText !== "TEXT INSERTED THEN REPEATEDLY DELETED" ||
      !(readiness.frame?.id > repeatedBackspaceDown?.frameIdBefore)
    ) {
      throw new Error(
          "M4 trusted Ozone Backspace timeout: " + JSON.stringify(readiness));
    }
    backspaceRepeatProof = {
      outerTraceExact: matchesM4BackspaceKeyPrefix(queuedRecords, fullKeyQueue),
      innerTraceExact: matchesM4BackspaceInnerKeyTrace(
          pageProbe?.keyEventTrace, fullBackspaceInnerTrace),
      textTraceExact: matchesM4BackspaceTextTrace(
          pageProbe?.textInputTrace, fullTextTrace),
      noComposition: hasM4BackspaceNoComposition(pageProbe),
      repeatExact:
        initialBackspaceDown?.repeat === false &&
        repeatedBackspaceDown?.repeat === true &&
        backspaceUp?.repeat === false &&
        pageProbe?.keyEventTrace?.[4]?.repeat === false &&
        pageProbe?.keyEventTrace?.[5]?.repeat === true &&
        pageProbe?.keyEventTrace?.[6]?.repeat === false,
      initialDownRepeatFalse:
        initialBackspaceDown?.repeat === false &&
        pageProbe?.keyEventTrace?.[4]?.repeat === false,
      repeatedDownRepeatTrue:
        repeatedBackspaceDown?.repeat === true &&
        pageProbe?.keyEventTrace?.[5]?.repeat === true,
      releaseRepeatFalse:
        backspaceUp?.repeat === false &&
        pageProbe?.keyEventTrace?.[6]?.repeat === false,
      backspaceHeld: backspaceRepeatPendingProof.backspaceHeld === true,
      releaseExact:
        matchesM4BackspaceOuterKeyRecord(
            keyboard?.lastQueuedUp, "up", M4_BACKSPACE_DOM_CODE,
            M4_BACKSPACE_DOM_KEY, false) &&
        keyboard?.lastQueuedUp?.sequence === backspaceUp?.sequence &&
        keyboard?.pressedCodes?.length === 0,
      value: pageProbe?.value,
      selectionStart: pageProbe?.selectionStart,
      selectionEnd: pageProbe?.selectionEnd,
      frameAfterRepeatDown:
        readiness.frame?.id > repeatedBackspaceDown?.frameIdBefore,
    };
    window.__chromiumWasmM4BackspaceState = {
      state: "input-delivered",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboard),
      keyAProof,
      keyBProof,
      backspaceRepeatProof,
    };
    const shutdownTimeoutMs = Math.max(
        1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      pointerActivation:
        pointer.trustedCount >= 2 &&
        pointer.queuedCount >= 2 &&
        lastQueuedPointer.trusted === true &&
        lastQueuedPointer.queued === true,
      trustedDomInput:
        keyboard.receivedCount === 7 &&
        keyboard.trustedCount === 7 &&
        keyboard.queuedCount === 7 &&
        matchesM4BackspaceKeyPrefix(queuedRecords, fullKeyQueue),
      ozoneDelivered:
        pageProbe.activationCount === 1 &&
        pageProbe.clickTrusted === true &&
        pageProbe.focusCount >= 1 &&
        pageProbe.focusTrusted === true &&
        pageProbe.activeElementId === "editable-target" &&
        matchesM4BackspaceInnerKeyTrace(
            pageProbe.keyEventTrace, fullBackspaceInnerTrace) &&
        matchesM4BackspaceTextTrace(pageProbe.textInputTrace, fullTextTrace) &&
        hasM4BackspaceNoComposition(pageProbe) &&
        pageProbe.value === "" &&
        pageProbe.selectionStart === 0 &&
        pageProbe.selectionEnd === 0 &&
        pageProbe.resultText === "TEXT INSERTED THEN REPEATEDLY DELETED" &&
        readiness.frame.id > repeatedBackspaceDown.frameIdBefore,
      backspaceRepeat:
        backspaceRepeatProof.outerTraceExact === true &&
        backspaceRepeatProof.innerTraceExact === true &&
        backspaceRepeatProof.textTraceExact === true &&
        backspaceRepeatProof.noComposition === true &&
        backspaceRepeatProof.repeatExact === true &&
        backspaceRepeatProof.initialDownRepeatFalse === true &&
        backspaceRepeatProof.repeatedDownRepeatTrue === true &&
        backspaceRepeatProof.releaseRepeatFalse === true &&
        backspaceRepeatProof.backspaceHeld === true &&
        backspaceRepeatProof.releaseExact === true &&
        backspaceRepeatProof.value === "" &&
        backspaceRepeatProof.selectionStart === 0 &&
        backspaceRepeatProof.selectionEnd === 0 &&
        backspaceRepeatProof.frameAfterRepeatDown === true,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_BACKSPACE_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointer,
      keyboardInput: keyboard,
      keyAProof,
      keyBProof,
      backspaceRepeatProof,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_BACKSPACE_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      keyAProof,
      keyBProof,
      backspaceRepeatProof,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneImeBridgeSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const imeProxy = document.querySelector("#m4-ime-proxy");
  const token = parameters.get("token") || "";
  const terminalMode = parameters.get("ime_terminal") || "commit";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;

  try {
    if (parameters.get("case") !== M4_IME_BRIDGE_CASE) {
      throw new Error("M4 IME bridge case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 IME bridge result token");
    }
    if (terminalMode !== "commit" && terminalMode !== "cancel") {
      throw new Error("M4 IME bridge terminal mode is invalid");
    }
    if (!(imeProxy instanceof HTMLTextAreaElement)) {
      throw new Error("M4 IME bridge proxy textarea is unavailable");
    }
    host = new ChromiumWasmM3Host(canvas, versions, {
      fixture: M4_IME_BRIDGE_FIXTURE,
      imeProxy,
    });
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 IME bridge base readiness timeout: " +
        JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 IME bridge target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 IME bridge target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const focusListeners = host.enableM4FocusInput();
    const imeProxyListeners = host.enableM4ImeProxyInput();
    window.__chromiumWasmM4ImeBridgeState = {
      state: "awaiting-dom-ime-bridge-activation",
      targetX,
      targetY,
      pointerListeners,
      focusListeners,
      imeProxyListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted Ozone click and IME proxy preedit";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const pageProbe = readiness.pageProbe;
      const proxy = readiness.imeProxyInput;
      const ozoneFocusState = readiness.ozoneFocusState;
      const ozoneTextInputState = readiness.ozoneTextInputState;
      if (
        pointer.queuedCount >= 2 &&
        pointer.lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "editable-target" &&
        isEmptyM4ImeTextSummary(pageProbe?.value) &&
        pageProbe?.valueMatchesExpected === false &&
        pageProbe?.selectionStart === 0 &&
        pageProbe?.selectionEnd === 0 &&
        proxy?.sessionId === 1 &&
        proxy?.focused === true &&
        proxy?.focusCount >= 1 &&
        proxy?.hostWindowActive === true &&
        proxy?.activationPending === false &&
        proxy?.nativeTextInputReady === true &&
        proxy?.failure === null &&
        ozoneFocusState?.keyboardTargetPresent === true &&
        ozoneFocusState?.active === true &&
        ozoneTextInputState?.focusedClientPresent === true &&
        ozoneTextInputState?.editable === true &&
        ozoneTextInputState?.canComposeInline === true
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const pageAfterActivation = readiness?.pageProbe;
    const proxyAfterActivation = readiness?.imeProxyInput;
    const ozoneFocusAfterActivation = readiness?.ozoneFocusState;
    const ozoneTextInputAfterActivation = readiness?.ozoneTextInputState;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      pointer?.lastQueued?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "editable-target" ||
      !isEmptyM4ImeTextSummary(pageAfterActivation?.value) ||
      pageAfterActivation?.valueMatchesExpected !== false ||
      pageAfterActivation?.selectionStart !== 0 ||
      pageAfterActivation?.selectionEnd !== 0 ||
      proxyAfterActivation?.sessionId !== 1 ||
      proxyAfterActivation?.focused !== true ||
      proxyAfterActivation?.focusCount < 1 ||
      proxyAfterActivation?.hostWindowActive !== true ||
      proxyAfterActivation?.activationPending !== false ||
      proxyAfterActivation?.nativeTextInputReady !== true ||
      ozoneFocusAfterActivation?.keyboardTargetPresent !== true ||
      ozoneFocusAfterActivation?.active !== true ||
      ozoneTextInputAfterActivation?.focusedClientPresent !== true ||
      ozoneTextInputAfterActivation?.editable !== true ||
      ozoneTextInputAfterActivation?.canComposeInline !== true ||
      proxyAfterActivation?.failure !== null
    ) {
      throw new Error(
        "M4 IME bridge activation timeout: " + JSON.stringify(readiness));
    }
    window.__chromiumWasmM4ImeBridgeState = {
      state: "awaiting-dom-ime-preedit",
      targetX,
      targetY,
      pointer: clone(pointer),
      imeProxy: clone(proxyAfterActivation),
    };
    statusElement.textContent =
      "M4 ready for trusted outer IME composition preedit";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const proxy = readiness.imeProxyInput;
      const pageProbe = readiness.pageProbe;
      const transaction = proxy?.lastConfirmedTransaction;
      const proxyText = proxy?.proxyText;
      const selection = proxyText?.selection;
      if (
        proxy?.receivedCount === 4 &&
        proxy?.trustedCount === 4 &&
        proxy?.acceptedCount === 4 &&
        proxy?.compositionStartCount === 1 &&
        proxy?.compositionUpdateCount === 1 &&
        proxy?.compositionEndCount === 0 &&
        proxy?.beforeinputCount === 1 &&
        proxy?.inputCount === 1 &&
        proxy?.compositionActive === true &&
        proxy?.pendingTransaction === false &&
        proxy?.failure === null &&
        proxy?.focused === true &&
        proxy?.activationPending === false &&
        proxy?.nativeTextInputReady === true &&
        proxy?.nativeQueuedCount === 1 &&
        proxy?.nativeSetDeliveryCount === 1 &&
        proxy?.nativeConfirmDeliveryCount === 0 &&
        proxy?.nativeClearDeliveryCount === 0 &&
        proxy?.nativePendingDelivery === false &&
        proxy?.nativeCompositionActive === true &&
        proxy?.nativeTerminalAction === null &&
        transaction?.sessionId === 1 &&
        transaction?.opcode === "set-composition" &&
        transaction?.rangeStart === 0 &&
        transaction?.rangeEnd === 2 &&
        transaction?.selection?.start === 2 &&
        transaction?.selection?.end === 2 &&
        isM4ImeSmokeTextSummary(transaction?.text) &&
        isM4ImeSmokeTextSummary(proxyText) &&
        selection?.start === 2 &&
        selection?.end === 2 &&
        pageProbe?.activeElementId === "editable-target" &&
        isM4ImeSmokeTextSummary(pageProbe?.value) &&
        pageProbe?.valueMatchesExpected === true &&
        pageProbe?.selectionStart === 2 &&
        pageProbe?.selectionEnd === 2 &&
        pageProbe?.textInputEvents?.beforeinputCount >= 1 &&
        pageProbe?.textInputEvents?.inputCount >= 1 &&
        pageProbe?.textInputEvents?.compositionstartCount === 1 &&
        pageProbe?.textInputEvents?.compositionupdateCount >= 1 &&
        pageProbe?.textInputEvents?.compositionendCount === 0 &&
        pageProbe?.textInputTrace?.[0]?.type === "compositionstart" &&
        pageProbe?.resultText === "INNER EDITOR COMPOSING"
      ) {
        break;
      }
      await delay(50);
    }
    const imeProxyInput = readiness?.imeProxyInput;
    const pageProbe = readiness?.pageProbe;
    const transaction = imeProxyInput?.lastConfirmedTransaction;
    const proxyText = imeProxyInput?.proxyText;
    if (
      !readiness ||
      imeProxyInput?.receivedCount !== 4 ||
      imeProxyInput?.trustedCount !== 4 ||
      imeProxyInput?.acceptedCount !== 4 ||
      imeProxyInput?.compositionStartCount !== 1 ||
      imeProxyInput?.compositionUpdateCount !== 1 ||
      imeProxyInput?.compositionEndCount !== 0 ||
      imeProxyInput?.beforeinputCount !== 1 ||
      imeProxyInput?.inputCount !== 1 ||
      imeProxyInput?.compositionActive !== true ||
      imeProxyInput?.pendingTransaction !== false ||
      imeProxyInput?.failure !== null ||
      imeProxyInput?.focused !== true ||
      imeProxyInput?.activationPending !== false ||
      imeProxyInput?.nativeTextInputReady !== true ||
      imeProxyInput?.nativeQueuedCount !== 1 ||
      imeProxyInput?.nativeSetDeliveryCount !== 1 ||
      imeProxyInput?.nativeConfirmDeliveryCount !== 0 ||
      imeProxyInput?.nativeClearDeliveryCount !== 0 ||
      imeProxyInput?.nativePendingDelivery !== false ||
      imeProxyInput?.nativeCompositionActive !== true ||
      imeProxyInput?.nativeTerminalAction !== null ||
      transaction?.sessionId !== 1 ||
      transaction?.opcode !== "set-composition" ||
      transaction?.rangeStart !== 0 ||
      transaction?.rangeEnd !== 2 ||
      transaction?.selection?.start !== 2 ||
      transaction?.selection?.end !== 2 ||
      !isM4ImeSmokeTextSummary(transaction?.text) ||
      !isM4ImeSmokeTextSummary(proxyText) ||
      proxyText?.selection?.start !== 2 ||
      proxyText?.selection?.end !== 2 ||
      pageProbe?.activeElementId !== "editable-target" ||
      !isM4ImeSmokeTextSummary(pageProbe?.value) ||
      pageProbe?.valueMatchesExpected !== true ||
      pageProbe?.selectionStart !== 2 ||
      pageProbe?.selectionEnd !== 2 ||
      pageProbe?.textInputEvents?.beforeinputCount < 1 ||
      pageProbe?.textInputEvents?.inputCount < 1 ||
      pageProbe?.textInputEvents?.compositionstartCount !== 1 ||
      pageProbe?.textInputEvents?.compositionupdateCount < 1 ||
      pageProbe?.textInputEvents?.compositionendCount !== 0 ||
      pageProbe?.textInputTrace?.[0]?.type !== "compositionstart" ||
      pageProbe?.resultText !== "INNER EDITOR COMPOSING"
    ) {
      throw new Error(
        "M4 IME bridge preedit timeout: " + JSON.stringify(readiness));
    }
    const isCancellation = terminalMode === "cancel";
    const terminalActionName = isCancellation
      ? "clear-composition"
      : "confirm-composition";
    const terminalResultText = isCancellation
      ? "INNER EDITOR COMPOSITION ENDED"
      : "INNER EDITOR COMMITTED";
    const terminalSelection = isCancellation ? 0 : 2;
    const terminalTextMatches = isCancellation
      ? isEmptyM4ImeTextSummary
      : isM4ImeSmokeTextSummary;
    // Both terminal modes produce a second update/beforeinput/input group in
    // the inner editor. For cancellation, Blink reports the final |input|
    // event's data as null rather than the empty string; the trace check below
    // binds that browser behavior before accepting the clear result.
    const terminalEventCount = 2;
    const terminalDerivedCount = isCancellation ? 0 : 1;
    const terminalObservedClearCount = isCancellation ? 1 : 0;
    const terminalAcceptedCount = isCancellation ? 7 : 8;
    const terminalNativeQueuedCount = isCancellation ? 2 : 3;
    const terminalSetDeliveryCount = isCancellation ? 1 : 2;
    const terminalConfirmDeliveryCount = isCancellation ? 0 : 1;
    const terminalClearDeliveryCount = isCancellation ? 1 : 0;
    const terminalNativeSequence = isCancellation ? 7 : 8;
    const terminalValueMatchesExpected = !isCancellation;
    const matchesConfirmedTransaction = (proxy) => {
      const candidate = proxy?.lastConfirmedTransaction;
      return candidate?.sessionId === 1 &&
          candidate?.opcode === "set-composition" &&
          candidate?.rangeStart === 0 && candidate?.rangeEnd === 2 &&
          candidate?.selection?.start === 2 && candidate?.selection?.end === 2 &&
          isM4ImeSmokeTextSummary(candidate?.text);
    };
    const matchesTerminalProxy = (proxy) => {
      const proxyCandidate = proxy?.proxyText;
      return proxy?.receivedCount === 8 && proxy?.trustedCount === 7 &&
          proxy?.acceptedCount === terminalAcceptedCount &&
          proxy?.derivedTerminalCount === terminalDerivedCount &&
          proxy?.observedClearTerminalCount === terminalObservedClearCount &&
          proxy?.compositionStartCount === 1 &&
          proxy?.compositionUpdateCount === 2 &&
          proxy?.compositionEndCount === 1 && proxy?.beforeinputCount === 2 &&
          proxy?.inputCount === 2 && proxy?.compositionActive === false &&
          proxy?.terminalCancellationPending === false &&
          proxy?.pendingTransaction === false && proxy?.failure === null &&
          proxy?.focused === true && proxy?.activationPending === false &&
          proxy?.nativeTextInputReady === true &&
          terminalTextMatches(proxyCandidate) &&
          proxyCandidate?.selection?.start === terminalSelection &&
          proxyCandidate?.selection?.end === terminalSelection &&
          matchesConfirmedTransaction(proxy);
    };
    const matchesTerminalDelivery = (proxy) =>
      proxy?.nativeQueuedCount === terminalNativeQueuedCount &&
      proxy?.nativeSetDeliveryCount === terminalSetDeliveryCount &&
      proxy?.nativeConfirmDeliveryCount === terminalConfirmDeliveryCount &&
      proxy?.nativeClearDeliveryCount === terminalClearDeliveryCount &&
      proxy?.nativePendingDelivery === false &&
      proxy?.nativeCompositionActive === false &&
      proxy?.nativeTerminalAction === null &&
      proxy?.lastNativeDelivery?.actionName === terminalActionName &&
      proxy?.lastNativeDelivery?.sequence === terminalNativeSequence &&
      proxy?.lastNativeDelivery?.deliveryAccepted === true;
    const matchesTerminalBlinkTrace = (page) => {
      const trace = page?.textInputTrace;
      const expectedTypes = [
        "compositionstart", "compositionupdate", "beforeinput", "input",
        "compositionupdate", "beforeinput", "input", "compositionend",
      ];
      if (!Array.isArray(trace) || trace.length !== expectedTypes.length ||
          !trace.every((record, index) =>
            record?.type === expectedTypes[index])) {
        return false;
      }
      // Chromium's direct composition-end dispatch deliberately preserves the
      // scoped queue's untrusted terminal. Every source event that carries
      // composition state must still be a native trusted Blink event.
      if (!trace.slice(0, -1).every((record) => record?.trusted === true) ||
          trace.at(-1)?.trusted !== false) {
        return false;
      }
      const start = trace[0];
      const candidateUpdate = trace[1];
      const candidateBeforeInput = trace[2];
      const candidateInput = trace[3];
      if (!isEmptyM4ImeTextSummary(start?.data) ||
          start?.dataMatchesExpected !== false ||
          !isM4ImeSmokeTextSummary(candidateUpdate?.data) ||
          candidateUpdate?.dataMatchesExpected !== true ||
          !isM4ImeSmokeTextSummary(candidateBeforeInput?.data) ||
          candidateBeforeInput?.inputType !== "insertCompositionText" ||
          candidateBeforeInput?.isComposing !== true ||
          candidateBeforeInput?.dataMatchesExpected !== true ||
          !isM4ImeSmokeTextSummary(candidateInput?.data) ||
          candidateInput?.inputType !== "insertCompositionText" ||
          candidateInput?.isComposing !== true ||
          candidateInput?.dataMatchesExpected !== true) {
        return false;
      }
      const terminalUpdate = trace[4];
      const terminalBeforeInput = trace[5];
      const terminalInput = trace[6];
      const terminalEnd = trace[7];
      if (!isCancellation) {
        return [terminalUpdate, terminalBeforeInput, terminalInput, terminalEnd]
            .every((record) => isM4ImeSmokeTextSummary(record?.data) &&
              record?.dataMatchesExpected === true) &&
            terminalBeforeInput?.inputType === "insertCompositionText" &&
            terminalBeforeInput?.isComposing === true &&
            terminalInput?.inputType === "insertCompositionText" &&
            terminalInput?.isComposing === true;
      }
      return isEmptyM4ImeTextSummary(terminalUpdate?.data) &&
          terminalUpdate?.dataMatchesExpected === false &&
          isEmptyM4ImeTextSummary(terminalBeforeInput?.data) &&
          terminalBeforeInput?.inputType === "insertCompositionText" &&
          terminalBeforeInput?.isComposing === true &&
          terminalBeforeInput?.dataMatchesExpected === false &&
          terminalInput?.data === null &&
          terminalInput?.inputType === "insertCompositionText" &&
          terminalInput?.isComposing === true &&
          terminalInput?.dataMatchesExpected === false &&
          isEmptyM4ImeTextSummary(terminalEnd?.data) &&
          terminalEnd?.dataMatchesExpected === false;
    };
    const matchesTerminalBlink = (page) =>
      page?.activeElementId === "editable-target" &&
      terminalTextMatches(page?.value) &&
      page?.valueMatchesExpected === terminalValueMatchesExpected &&
      page?.selectionStart === terminalSelection &&
      page?.selectionEnd === terminalSelection &&
      page?.textInputEvents?.beforeinputCount === terminalEventCount &&
      page?.textInputEvents?.inputCount === terminalEventCount &&
      page?.textInputEvents?.compositionstartCount === 1 &&
      page?.textInputEvents?.compositionupdateCount === terminalEventCount &&
      page?.textInputEvents?.compositionendCount === 1 &&
      matchesTerminalBlinkTrace(page) &&
      page?.resultText === terminalResultText;
    window.__chromiumWasmM4ImeBridgeState = {
      state: "awaiting-dom-ime-terminal",
      terminalMode,
      targetX,
      targetY,
      pointer: clone(pointer),
      imeProxy: clone(imeProxyInput),
    };
    statusElement.textContent =
      "M4 preedit reached Blink; ready for outer IME " + terminalMode;

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (
        matchesTerminalProxy(readiness.imeProxyInput) &&
        matchesTerminalDelivery(readiness.imeProxyInput) &&
        matchesTerminalBlink(readiness.pageProbe)
      ) {
        break;
      }
      await delay(50);
    }
    const terminalReadiness = readiness;
    const terminalImeProxyInput = terminalReadiness?.imeProxyInput;
    const terminalPageProbe = terminalReadiness?.pageProbe;
    if (
      !terminalReadiness || !matchesTerminalProxy(terminalImeProxyInput) ||
      !matchesTerminalDelivery(terminalImeProxyInput) ||
      !matchesTerminalBlink(terminalPageProbe)
    ) {
      throw new Error(
        "M4 IME bridge " + terminalMode + " timeout: " +
        JSON.stringify(terminalReadiness));
    }
    const focusSnapshot = {
      canvasFocused: document.activeElement === canvas,
      proxyFocused: document.activeElement === imeProxy,
    };
    window.__chromiumWasmM4ImeBridgeState = {
      state: isCancellation
        ? "native-composition-cancelled"
        : "native-composition-committed",
      terminalMode,
      targetX,
      targetY,
      pointer: clone(pointer),
      imeProxy: clone(terminalImeProxyInput),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      baseReady: terminalReadiness.baseReady === true,
      proxyFocus:
        focusSnapshot.canvasFocused === false &&
        focusSnapshot.proxyFocused === true &&
        terminalImeProxyInput.focused === true &&
        terminalImeProxyInput.hostWindowActive === true &&
        terminalImeProxyInput.activationPending === false &&
        terminalImeProxyInput.nativeTextInputReady === true &&
        ozoneFocusAfterActivation.keyboardTargetPresent === true &&
        ozoneFocusAfterActivation.active === true &&
        ozoneTextInputAfterActivation.focusedClientPresent === true &&
        ozoneTextInputAfterActivation.editable === true &&
        ozoneTextInputAfterActivation.canComposeInline === true,
      proxyComposition: matchesTerminalProxy(terminalImeProxyInput),
      nativeDelivery: matchesTerminalDelivery(terminalImeProxyInput),
      innerBlinkComposition: matchesTerminalBlink(terminalPageProbe),
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_IME_BRIDGE_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: focusSnapshot.canvasFocused,
      proxyFocused: focusSnapshot.proxyFocused,
      terminalMode,
      versions,
      readiness: terminalReadiness,
      pointerInput: pointer,
      focusInput: terminalReadiness.focusInput,
      imeProxyInput: terminalImeProxyInput,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_IME_BRIDGE_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      proxyFocused: document.activeElement === imeProxy,
      versions,
      readiness: null,
      pointerInput: null,
      focusInput: null,
      imeProxyInput: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.focusInput = result.readiness.focusInput;
        result.imeProxyInput = result.readiness.imeProxyInput;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneFocusSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const focusSink = document.querySelector("#m4-focus-sink");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let result;
  let focusSinkClick = null;
  let focusSinkListener = null;

  try {
    if (parameters.get("case") !== M4_FOCUS_CASE) {
      throw new Error("M4 focus case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 focus result token");
    }
    if (!(focusSink instanceof HTMLButtonElement)) {
      throw new Error("M4 focus host sink is missing");
    }
    focusSink.hidden = false;
    focusSinkListener = (event) => {
      focusSinkClick = {
        trusted: event.isTrusted === true,
        defaultPrevented: event.defaultPrevented === true,
      };
    };
    focusSink.addEventListener("click", focusSinkListener);
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_FOCUS_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    let readiness = null;
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 focus base readiness timeout: " + JSON.stringify(readiness));
    }
    const targetX = Number(readiness.pageProbe.targetCenterX);
    const targetY = Number(readiness.pageProbe.targetCenterY);
    checkInteger(targetX, "M4 focus target x", 0, DEFAULT_WIDTH - 1);
    checkInteger(targetY, "M4 focus target y", 0, DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4FocusState = {
      state: "awaiting-dom-focus-activation",
      targetX,
      targetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas click before host focus loss";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const lastQueued = pointer.lastQueued;
      const pageProbe = readiness.pageProbe;
      if (
        pointer.queuedCount >= 2 &&
        lastQueued?.type === "up" &&
        pageProbe?.activationCount === 1 &&
        pageProbe?.clickTrusted === true &&
        pageProbe?.focusCount >= 1 &&
        pageProbe?.focusTrusted === true &&
        pageProbe?.activeElementId === "focus-target" &&
        readiness.frame?.id > lastQueued.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const lastQueuedPointer = pointer?.lastQueued;
    const pageAfterActivation = readiness?.pageProbe;
    if (
      !readiness ||
      pointer?.queuedCount < 2 ||
      lastQueuedPointer?.type !== "up" ||
      pageAfterActivation?.activationCount !== 1 ||
      pageAfterActivation?.clickTrusted !== true ||
      pageAfterActivation?.focusCount < 1 ||
      pageAfterActivation?.focusTrusted !== true ||
      pageAfterActivation?.activeElementId !== "focus-target" ||
      !(readiness.frame?.id > lastQueuedPointer.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone focus activation timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4FocusState = {
      state: "awaiting-dom-focus-key-down",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(readiness.keyboardInput),
      focus: clone(readiness.focusInput),
    };
    statusElement.textContent =
      "M4 ready for a trusted raw ArrowDown keydown";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const keyDown = keyboard.lastQueuedDown;
      const pageProbe = readiness.pageProbe;
      const keyEvents = pageProbe?.keyEvents;
      if (
        keyboard.queuedCount >= 1 &&
        keyboard.pressedCodes?.length === 1 &&
        keyboard.pressedCodes[0] === M4_KEYBOARD_DOM_CODE &&
        keyDown?.type === "down" &&
        keyDown?.trusted === true &&
        keyDown?.queued === true &&
        keyDown?.defaultPrevented === true &&
        keyEvents?.keydownCount === 1 &&
        keyEvents?.keydownTrusted === true &&
        keyEvents?.keydownCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keydownKey === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keydownTargetId === "focus-target"
      ) {
        break;
      }
      await delay(50);
    }
    const keyboardBeforeFocusLoss = readiness?.keyboardInput;
    const keyDown = keyboardBeforeFocusLoss?.lastQueuedDown;
    const pageBeforeFocusLoss = readiness?.pageProbe;
    const keyEventsBeforeFocusLoss = pageBeforeFocusLoss?.keyEvents;
    if (
      !readiness ||
      keyboardBeforeFocusLoss?.queuedCount < 1 ||
      keyboardBeforeFocusLoss?.pressedCodes?.length !== 1 ||
      keyboardBeforeFocusLoss.pressedCodes[0] !== M4_KEYBOARD_DOM_CODE ||
      keyDown?.type !== "down" ||
      keyDown?.trusted !== true ||
      keyDown?.queued !== true ||
      keyDown?.defaultPrevented !== true ||
      keyEventsBeforeFocusLoss?.keydownCount !== 1 ||
      keyEventsBeforeFocusLoss?.keydownTrusted !== true ||
      keyEventsBeforeFocusLoss?.keydownCode !== M4_KEYBOARD_DOM_CODE ||
      keyEventsBeforeFocusLoss?.keydownKey !== M4_KEYBOARD_DOM_CODE ||
      keyEventsBeforeFocusLoss?.keydownTargetId !== "focus-target"
    ) {
      throw new Error(
        "M4 trusted Ozone focus keydown timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4FocusState = {
      state: "awaiting-dom-focus-loss",
      targetX,
      targetY,
      pointer: clone(pointer),
      keyboard: clone(keyboardBeforeFocusLoss),
      focus: clone(readiness.focusInput),
    };
    statusElement.textContent =
      "M4 ready for trusted host focus loss with a held ArrowDown key";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const focus = readiness.focusInput;
      const focusLoss = focus.lastQueuedFocusLoss;
      const ozoneFocusState = readiness.ozoneFocusState;
      const keyUp = keyboard.lastQueuedUp;
      const pageProbe = readiness.pageProbe;
      const keyEvents = pageProbe?.keyEvents;
      if (
        focus.hostWindowActive === false &&
        focusLoss?.type === "canvas-blur" &&
        focusLoss?.trusted === true &&
        focusLoss?.queued === true &&
        focusLoss?.canvasFocused === false &&
        focusLoss?.relatedTargetId === "m4-focus-sink" &&
        ozoneFocusState?.sequence >
          focusLoss?.ozoneFocusReportSequenceBefore &&
        ozoneFocusState?.keyboardTargetPresent === false &&
        ozoneFocusState?.active === false &&
        focusSinkClick?.trusted === true &&
        focusSinkClick?.defaultPrevented === false &&
        document.activeElement === focusSink &&
        keyboard.activated === false &&
        keyboard.pressedCodes?.length === 0 &&
        keyUp?.type === "up" &&
        keyUp?.generated === true &&
        keyUp?.trigger === "canvas-blur" &&
        keyUp?.triggerTrusted === true &&
        keyUp?.queued === true &&
        keyUp?.code === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keyupCount === 1 &&
        keyEvents?.keyupTrusted === true &&
        keyEvents?.keyupCode === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keyupKey === M4_KEYBOARD_DOM_CODE &&
        keyEvents?.keyupTargetId === "focus-target" &&
        pageProbe?.windowBlurCount >= 1 &&
        pageProbe?.windowBlurTrusted === true &&
        pageProbe?.documentHasFocus === false &&
        pageProbe?.activeElementId === "focus-target" &&
        pageProbe?.resultText === "WINDOW BLURRED" &&
        readiness.frame?.id > focusLoss.frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointerAfterFocusLoss = readiness?.pointerInput;
    const keyboard = readiness?.keyboardInput;
    const focus = readiness?.focusInput;
    const focusLoss = focus?.lastQueuedFocusLoss;
    const ozoneFocusState = readiness?.ozoneFocusState;
    const keyUp = keyboard?.lastQueuedUp;
    const pageProbe = readiness?.pageProbe;
    const keyEvents = pageProbe?.keyEvents;
    if (
      !readiness ||
      focus?.hostWindowActive !== false ||
      focusLoss?.type !== "canvas-blur" ||
      focusLoss?.trusted !== true ||
      focusLoss?.queued !== true ||
      focusLoss?.canvasFocused !== false ||
      focusLoss?.relatedTargetId !== "m4-focus-sink" ||
      !(ozoneFocusState?.sequence >
        focusLoss?.ozoneFocusReportSequenceBefore) ||
      ozoneFocusState?.keyboardTargetPresent !== false ||
      ozoneFocusState?.active !== false ||
      focusSinkClick?.trusted !== true ||
      focusSinkClick?.defaultPrevented !== false ||
      document.activeElement !== focusSink ||
      keyboard?.activated !== false ||
      keyboard?.pressedCodes?.length !== 0 ||
      keyUp?.type !== "up" ||
      keyUp?.generated !== true ||
      keyUp?.trigger !== "canvas-blur" ||
      keyUp?.triggerTrusted !== true ||
      keyUp?.queued !== true ||
      keyUp?.code !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keyupCount !== 1 ||
      keyEvents?.keyupTrusted !== true ||
      keyEvents?.keyupCode !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keyupKey !== M4_KEYBOARD_DOM_CODE ||
      keyEvents?.keyupTargetId !== "focus-target" ||
      pageProbe?.windowBlurCount < 1 ||
      pageProbe?.windowBlurTrusted !== true ||
      pageProbe?.documentHasFocus !== false ||
      pageProbe?.activeElementId !== "focus-target" ||
      pageProbe?.resultText !== "WINDOW BLURRED" ||
      !(readiness.frame?.id > focusLoss.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone focus loss timeout: " +
        JSON.stringify(readiness));
    }
    window.__chromiumWasmM4FocusState = {
      state: "focus-loss-delivered",
      targetX,
      targetY,
      pointer: clone(pointerAfterFocusLoss),
      keyboard: clone(keyboard),
      focus: clone(focus),
      ozoneFocusState: clone(ozoneFocusState),
      focusSinkClick: clone(focusSinkClick),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasUnfocused: document.activeElement === focusSink,
      baseReady: readiness.baseReady === true,
      pointerActivation:
        pointer.trustedCount >= 2 &&
        pointer.queuedCount >= 2 &&
        lastQueuedPointer.trusted === true &&
        lastQueuedPointer.queued === true,
      heldKeyDelivered:
        keyDown.trusted === true &&
        keyDown.queued === true &&
        keyEvents.keydownCount === 1 &&
        keyEvents.keydownTrusted === true,
      trustedHostFocusLoss:
        focusLoss.trusted === true &&
        focusLoss.queued === true &&
        focusLoss.relatedTargetId === "m4-focus-sink" &&
        focusSinkClick.trusted === true &&
        focusSinkClick.defaultPrevented === false,
      ozoneKeyboardTargetCleared:
        ozoneFocusState.sequence > focusLoss.ozoneFocusReportSequenceBefore &&
        ozoneFocusState.keyboardTargetPresent === false &&
        ozoneFocusState.active === false,
      auraAndBlinkDeactivated:
        keyboard.activated === false &&
        keyboard.pressedCodes.length === 0 &&
        keyUp.generated === true &&
        keyUp.queued === true &&
        keyEvents.keyupCount === 1 &&
        keyEvents.keyupTrusted === true &&
        pageProbe.windowBlurCount >= 1 &&
        pageProbe.windowBlurTrusted === true &&
        pageProbe.documentHasFocus === false &&
        pageProbe.activeElementId === "focus-target" &&
        pageProbe.resultText === "WINDOW BLURRED" &&
        readiness.frame.id > focusLoss.frameIdBefore,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_FOCUS_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      pointerInput: pointerAfterFocusLoss,
      keyboardInput: keyboard,
      focusInput: focus,
      ozoneFocusState,
      focusSinkClick,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_FOCUS_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      pointerInput: null,
      keyboardInput: null,
      focusInput: null,
      ozoneFocusState: null,
      focusSinkClick,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
        result.focusInput = result.readiness.focusInput;
        result.ozoneFocusState = result.readiness.ozoneFocusState;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  if (focusSink instanceof HTMLButtonElement && focusSinkListener) {
    focusSink.removeEventListener("click", focusSinkListener);
  }
  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM4OzoneFocusRetentionSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const timeoutMs = Math.max(
      1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  const expectedModifiers = {
    alt: false,
    control: false,
    meta: false,
    shift: false,
  };
  const keyQueue = [
    ["down", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
    ["up", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const keyTrace = [
    ["keydown", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
    ["keyup", M4_PRINTABLE_KEY_DOM_CODE, M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const textTrace = [
    ["beforeinput", M4_PRINTABLE_KEY_DOM_KEY],
    ["input", M4_PRINTABLE_KEY_DOM_KEY],
  ];
  const matchesPointerTrace = (pointer, expected) => {
    const records = pointer?.queuedRecords;
    return pointer?.receivedCount === expected.length &&
      pointer?.trustedCount === expected.length &&
      pointer?.queuedCount === expected.length &&
      Array.isArray(records) && records.length === expected.length &&
      expected.every(([type, x, y, button, buttons], index) => {
        const record = records[index];
        return record?.sequence === index + 1 && record?.type === type &&
          record?.trusted === true &&
          record?.queued === true && record?.canvasFocused === true &&
          record?.x === x && record?.y === y && record?.button === button &&
          record?.buttons === buttons &&
          Number.isSafeInteger(record?.frameIdBefore) &&
          record.frameIdBefore >= 1;
      });
  };
  const expectedPointerTrace = () => [
    ["move", editableTargetX, editableTargetY, -1, 0],
    ["down", editableTargetX, editableTargetY, 0, 1],
    ["up", editableTargetX, editableTargetY, 0, 0],
    ["move", retentionTargetX, retentionTargetY, -1, 0],
  ];
  const initialPointerTrace = () => expectedPointerTrace().slice(0, 3);
  const matchesOuterKeyTrace = (keyboard) => {
    const records = keyboard?.queuedRecords;
    return Array.isArray(records) && records.length === keyQueue.length &&
      keyQueue.every(([type, code, key], index) => {
        const record = records[index];
        return record?.type === type && record?.code === code &&
          record?.key === key && record?.trusted === true &&
          record?.queued === true && record?.repeat === false &&
          record?.isComposing === false && record?.canvasFocused === true &&
          record?.pointerActivated === true &&
          record?.defaultPrevented === true &&
          JSON.stringify(record?.modifiers) === JSON.stringify(expectedModifiers) &&
          Number.isSafeInteger(record?.frameIdBefore) &&
          record.frameIdBefore >= 1;
      });
  };
  const matchesInnerKeyTrace = (trace) =>
    Array.isArray(trace) && trace.length === keyTrace.length &&
    keyTrace.every(([type, code, key], index) => {
      const record = trace[index];
      return record?.type === type && record?.trusted === true &&
        record?.code === code && record?.key === key &&
        record?.repeat === false && record?.isComposing === false &&
        record?.defaultPrevented === false &&
        record?.targetId === "editable-target";
    });
  const matchesTextTrace = (trace) =>
    Array.isArray(trace) && trace.length === textTrace.length &&
    textTrace.every(([type, data], index) => {
      const record = trace[index];
      return record?.type === type && record?.trusted === true &&
        record?.inputType === "insertText" && record?.data === data &&
        record?.isComposing === false &&
        record?.targetId === "editable-target";
    });
  const hasNoComposition = (retention) => {
    const counts = retention?.compositionEventCounts;
    return counts?.compositionstart === 0 && counts?.compositionupdate === 0 &&
      counts?.compositionend === 0;
  };
  let host = null;
  let result;
  let readiness = null;
  let editableTargetX = null;
  let editableTargetY = null;
  let retentionTargetX = null;
  let retentionTargetY = null;
  let retentionFocusSequenceBefore = null;
  let retentionFocusSequenceAfter = null;
  let retentionOzoneFocusReports = null;

  try {
    if (parameters.get("case") !== M4_FOCUS_RETENTION_CASE) {
      throw new Error("M4 focus-retention case query mismatch");
    }
    if (!token) {
      throw new Error("missing M4 focus-retention result token");
    }
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M4_FOCUS_RETENTION_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;
    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    const fixtureURL = await buildFixtureDataURL(
      parameters.get("fixture"), parameters.get("font"));
    await host.loadURL(fixtureURL);

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady) {
        break;
      }
      await delay(50);
    }
    if (!readiness?.baseReady) {
      throw new Error(
        "M4 focus-retention base readiness timeout: " +
        JSON.stringify(readiness));
    }
    editableTargetX = Number(readiness.pageProbe.editableTargetX);
    editableTargetY = Number(readiness.pageProbe.editableTargetY);
    retentionTargetX = Number(readiness.pageProbe.retentionTargetX);
    retentionTargetY = Number(readiness.pageProbe.retentionTargetY);
    checkInteger(
        editableTargetX, "M4 focus-retention editable target x", 0,
        DEFAULT_WIDTH - 1);
    checkInteger(
        editableTargetY, "M4 focus-retention editable target y", 0,
        DEFAULT_HEIGHT - 1);
    checkInteger(
        retentionTargetX, "M4 focus-retention inert target x", 0,
        DEFAULT_WIDTH - 1);
    checkInteger(
        retentionTargetY, "M4 focus-retention inert target y", 0,
        DEFAULT_HEIGHT - 1);
    const pointerListeners = host.enableM4PointerInput();
    const keyboardListeners = host.enableM4KeyboardInput();
    const focusListeners = host.enableM4FocusInput();
    window.__chromiumWasmM4FocusRetentionState = {
      state: "awaiting-dom-focus-retention-activation",
      editableTargetX,
      editableTargetY,
      retentionTargetX,
      retentionTargetY,
      pointerListeners,
      keyboardListeners,
      focusListeners,
    };
    statusElement.textContent =
      "M4 ready for trusted canvas editable-focus activation";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const pageProbe = readiness.pageProbe;
      const retention = pageProbe?.focusRetention;
      const ozoneFocusState = readiness.ozoneFocusState;
      if (
        pointer?.queuedRecords?.length === 3 &&
        matchesPointerTrace(pointer, initialPointerTrace()) &&
        retention?.editableActivationCount === 1 &&
        retention?.editableClickTrusted === true &&
        retention?.editableFocusCount === 1 &&
        retention?.editableFocusTrusted === true &&
        retention?.editableBlurCount === 0 &&
        retention?.windowBlurCount === 0 &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.documentHasFocus === true &&
        ozoneFocusState?.keyboardTargetPresent === true &&
        ozoneFocusState?.active === true &&
        readiness.frame?.id > pointer.queuedRecords[1].frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const initialPointer = readiness?.pointerInput;
    const initialPageProbe = readiness?.pageProbe;
    const initialRetention = initialPageProbe?.focusRetention;
    const initialFocus = readiness?.focusInput;
    const initialOzoneFocusState = readiness?.ozoneFocusState;
    const initialOzoneFocusReports = readiness?.ozoneFocusReports;
    if (
      !readiness ||
      !matchesPointerTrace(initialPointer, initialPointerTrace()) ||
      initialRetention?.editableActivationCount !== 1 ||
      initialRetention?.editableClickTrusted !== true ||
      initialRetention?.editableFocusCount !== 1 ||
      initialRetention?.editableFocusTrusted !== true ||
      initialRetention?.editableBlurCount !== 0 ||
      initialRetention?.windowBlurCount !== 0 ||
      initialPageProbe?.activeElementId !== "editable-target" ||
      initialPageProbe?.documentHasFocus !== true ||
      initialFocus?.receivedCount !== 1 ||
      initialFocus?.trustedCount !== 1 ||
      initialFocus?.queuedCount !== 1 ||
      initialFocus?.hostWindowActive !== true ||
      initialFocus?.lastQueuedFocusLoss !== null ||
      initialOzoneFocusState?.keyboardTargetPresent !== true ||
      initialOzoneFocusState?.active !== true ||
      !Number.isSafeInteger(initialOzoneFocusState?.sequence) ||
      !Array.isArray(initialOzoneFocusReports) ||
      initialOzoneFocusReports.length === 0 ||
      initialOzoneFocusReports.at(-1)?.sequence !==
        initialOzoneFocusState.sequence ||
      !(readiness.frame?.id > initialPointer?.queuedRecords?.[1]?.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone focus-retention activation timeout: " +
        JSON.stringify(readiness));
    }
    retentionFocusSequenceBefore = initialOzoneFocusState.sequence;
    window.__chromiumWasmM4FocusRetentionState = {
      state: "awaiting-dom-focus-retention-pointer",
      editableTargetX,
      editableTargetY,
      retentionTargetX,
      retentionTargetY,
      retentionFocusSequenceBefore,
      pointer: clone(initialPointer),
      focus: clone(readiness.focusInput),
      ozoneFocusState: clone(initialOzoneFocusState),
    };
    statusElement.textContent =
      "M4 ready for trusted inert canvas pointer move retaining Blink focus";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const pointer = readiness.pointerInput;
      const focus = readiness.focusInput;
      const pageProbe = readiness.pageProbe;
      const retention = pageProbe?.focusRetention;
      const ozoneFocusState = readiness.ozoneFocusState;
      const reportsAfter = Array.isArray(readiness.ozoneFocusReports)
        ? readiness.ozoneFocusReports.filter(
            (report) => report?.sequence > retentionFocusSequenceBefore)
        : null;
      if (
        pointer?.queuedRecords?.length === 4 &&
        matchesPointerTrace(pointer, expectedPointerTrace()) &&
        retention?.retentionPointerMoveCount === 1 &&
        retention?.retentionPointerMoveTrusted === true &&
        retention?.editableBlurCount === 0 &&
        retention?.windowBlurCount === 0 &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.documentHasFocus === true &&
        focus?.hostWindowActive === true &&
        focus?.receivedCount === 1 &&
        focus?.trustedCount === 1 &&
        focus?.queuedCount === 1 &&
        focus?.lastQueuedFocusLoss === null &&
        ozoneFocusState?.sequence === retentionFocusSequenceBefore &&
        ozoneFocusState?.keyboardTargetPresent === true &&
        ozoneFocusState?.active === true &&
        reportsAfter?.length === 0
      ) {
        break;
      }
      await delay(50);
    }
    const pointerAfterRetention = readiness?.pointerInput;
    const focusAfterRetention = readiness?.focusInput;
    const pageAfterRetention = readiness?.pageProbe;
    const retentionAfterPointer = pageAfterRetention?.focusRetention;
    const ozoneAfterRetention = readiness?.ozoneFocusState;
    const reportsAfterRetention = Array.isArray(readiness?.ozoneFocusReports)
      ? readiness.ozoneFocusReports.filter(
          (report) => report?.sequence > retentionFocusSequenceBefore)
      : null;
    if (
      !readiness ||
      !matchesPointerTrace(pointerAfterRetention, expectedPointerTrace()) ||
      retentionAfterPointer?.retentionPointerMoveCount !== 1 ||
      retentionAfterPointer?.retentionPointerMoveTrusted !== true ||
      retentionAfterPointer?.editableBlurCount !== 0 ||
      retentionAfterPointer?.windowBlurCount !== 0 ||
      pageAfterRetention?.activeElementId !== "editable-target" ||
      pageAfterRetention?.documentHasFocus !== true ||
      focusAfterRetention?.hostWindowActive !== true ||
      focusAfterRetention?.receivedCount !== 1 ||
      focusAfterRetention?.trustedCount !== 1 ||
      focusAfterRetention?.queuedCount !== 1 ||
      focusAfterRetention?.lastQueuedFocusLoss !== null ||
      ozoneAfterRetention?.sequence !== retentionFocusSequenceBefore ||
      ozoneAfterRetention?.keyboardTargetPresent !== true ||
      ozoneAfterRetention?.active !== true ||
      !Array.isArray(reportsAfterRetention) ||
      reportsAfterRetention.length !== 0
    ) {
      throw new Error(
        "M4 trusted Ozone focus-retention pointer timeout: " +
        JSON.stringify(readiness));
    }
    retentionFocusSequenceAfter = ozoneAfterRetention.sequence;
    retentionOzoneFocusReports = clone(reportsAfterRetention);
    window.__chromiumWasmM4FocusRetentionState = {
      state: "awaiting-dom-focus-retention-key",
      editableTargetX,
      editableTargetY,
      retentionTargetX,
      retentionTargetY,
      retentionFocusSequenceBefore,
      retentionFocusSequenceAfter,
      pointer: clone(pointerAfterRetention),
      focus: clone(focusAfterRetention),
      ozoneFocusState: clone(ozoneAfterRetention),
    };
    statusElement.textContent =
      "M4 ready for trusted raw KeyA after retained focus";

    while (performance.now() < deadline) {
      readiness = await host.readiness();
      const keyboard = readiness.keyboardInput;
      const pageProbe = readiness.pageProbe;
      const retention = pageProbe?.focusRetention;
      if (
        keyboard?.receivedCount === 2 &&
        keyboard?.trustedCount === 2 &&
        keyboard?.queuedCount === 2 &&
        keyboard?.activated === true &&
        keyboard?.pressedCodes?.length === 0 &&
        matchesOuterKeyTrace(keyboard) &&
        matchesInnerKeyTrace(retention?.keyEventTrace) &&
        matchesTextTrace(retention?.textInputTrace) &&
        hasNoComposition(retention) &&
        retention?.value === M4_PRINTABLE_KEY_DOM_KEY &&
        retention?.selectionStart === 1 &&
        retention?.selectionEnd === 1 &&
        retention?.resultText === "FOCUS RETAINED" &&
        retention?.editableBlurCount === 0 &&
        retention?.windowBlurCount === 0 &&
        retention?.retentionPointerMoveCount === 1 &&
        retention?.retentionPointerMoveTrusted === true &&
        pageProbe?.activeElementId === "editable-target" &&
        pageProbe?.documentHasFocus === true &&
        readiness.focusInput?.receivedCount === 1 &&
        readiness.focusInput?.trustedCount === 1 &&
        readiness.focusInput?.queuedCount === 1 &&
        readiness.focusInput?.hostWindowActive === true &&
        readiness.focusInput?.lastQueuedFocusLoss === null &&
        readiness.ozoneFocusState?.sequence === retentionFocusSequenceBefore &&
        readiness.ozoneFocusState?.keyboardTargetPresent === true &&
        readiness.ozoneFocusState?.active === true &&
        Array.isArray(readiness.ozoneFocusReports) &&
        readiness.ozoneFocusReports.every(
            (report) => report?.sequence <= retentionFocusSequenceBefore) &&
        readiness.frame?.id > keyboard.queuedRecords[0].frameIdBefore
      ) {
        break;
      }
      await delay(50);
    }
    const pointer = readiness?.pointerInput;
    const keyboard = readiness?.keyboardInput;
    const focus = readiness?.focusInput;
    const pageProbe = readiness?.pageProbe;
    const retention = pageProbe?.focusRetention;
    const ozoneFocusState = readiness?.ozoneFocusState;
    const finalOzoneFocusReports = Array.isArray(readiness?.ozoneFocusReports)
      ? readiness.ozoneFocusReports.filter(
          (report) => report?.sequence > retentionFocusSequenceBefore)
      : null;
    if (
      !readiness ||
      !matchesPointerTrace(pointer, expectedPointerTrace()) ||
      keyboard?.receivedCount !== 2 ||
      keyboard?.trustedCount !== 2 ||
      keyboard?.queuedCount !== 2 ||
      keyboard?.activated !== true ||
      keyboard?.pressedCodes?.length !== 0 ||
      !matchesOuterKeyTrace(keyboard) ||
      !matchesInnerKeyTrace(retention?.keyEventTrace) ||
      !matchesTextTrace(retention?.textInputTrace) ||
      !hasNoComposition(retention) ||
      retention?.value !== M4_PRINTABLE_KEY_DOM_KEY ||
      retention?.selectionStart !== 1 ||
      retention?.selectionEnd !== 1 ||
      retention?.resultText !== "FOCUS RETAINED" ||
      retention?.editableBlurCount !== 0 ||
      retention?.windowBlurCount !== 0 ||
      retention?.retentionPointerMoveCount !== 1 ||
      retention?.retentionPointerMoveTrusted !== true ||
      pageProbe?.activeElementId !== "editable-target" ||
      pageProbe?.documentHasFocus !== true ||
      focus?.hostWindowActive !== true ||
      focus?.receivedCount !== 1 ||
      focus?.trustedCount !== 1 ||
      focus?.queuedCount !== 1 ||
      focus?.lastQueuedFocusLoss !== null ||
      ozoneFocusState?.sequence !== retentionFocusSequenceBefore ||
      ozoneFocusState?.keyboardTargetPresent !== true ||
      ozoneFocusState?.active !== true ||
      !Array.isArray(finalOzoneFocusReports) ||
      finalOzoneFocusReports.length !== 0 ||
      !(readiness.frame?.id > keyboard?.queuedRecords?.[0]?.frameIdBefore)
    ) {
      throw new Error(
        "M4 trusted Ozone focus-retention KeyA timeout: " +
        JSON.stringify(readiness));
    }
    retentionFocusSequenceAfter = ozoneFocusState.sequence;
    retentionOzoneFocusReports = clone(finalOzoneFocusReports);
    const focusRetentionProof = {
      pointerTraceExact: matchesPointerTrace(pointer, expectedPointerTrace()),
      nativeFocusStateStable:
        retentionFocusSequenceAfter === retentionFocusSequenceBefore &&
        Array.isArray(retentionOzoneFocusReports) &&
        retentionOzoneFocusReports.length === 0 &&
        ozoneFocusState.sequence === retentionFocusSequenceBefore &&
        ozoneFocusState.keyboardTargetPresent === true &&
        ozoneFocusState.active === true,
      blinkFocusRetained:
        retention.editableBlurCount === 0 &&
        retention.windowBlurCount === 0 &&
        pageProbe.activeElementId === "editable-target" &&
        pageProbe.documentHasFocus === true,
      keyOuterTraceExact: matchesOuterKeyTrace(keyboard),
      keyInnerTraceExact: matchesInnerKeyTrace(retention.keyEventTrace),
      textTraceExact: matchesTextTrace(retention.textInputTrace),
      noComposition: hasNoComposition(retention),
      frameAfterKeyDown:
        readiness.frame.id > keyboard.queuedRecords[0].frameIdBefore,
    };
    window.__chromiumWasmM4FocusRetentionState = {
      state: "input-delivered",
      editableTargetX,
      editableTargetY,
      retentionTargetX,
      retentionTargetY,
      retentionFocusSequenceBefore,
      retentionFocusSequenceAfter,
      focusRetentionProof: clone(focusRetentionProof),
    };
    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    const shutdown = await host.shutdown(shutdownTimeoutMs);
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      baseReady: readiness.baseReady === true,
      trustedPointerInput: focusRetentionProof.pointerTraceExact,
      retainedNativeFocus: focusRetentionProof.nativeFocusStateStable,
      retainedBlinkFocus: focusRetentionProof.blinkFocusRetained,
      trustedKeyEditing:
        focusRetentionProof.keyOuterTraceExact &&
        focusRetentionProof.keyInnerTraceExact &&
        focusRetentionProof.textTraceExact &&
        focusRetentionProof.noComposition &&
        focusRetentionProof.frameAfterKeyDown,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_FOCUS_RETENTION_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness,
      editableTargetX,
      editableTargetY,
      retentionTargetX,
      retentionTargetY,
      retentionFocusSequenceBefore,
      retentionFocusSequenceAfter,
      retentionOzoneFocusReports,
      pointerInput: pointer,
      keyboardInput: keyboard,
      focusInput: focus,
      ozoneFocusState,
      focusRetentionProof,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M4_FOCUS_RETENTION_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      readiness: null,
      editableTargetX,
      editableTargetY,
      retentionTargetX,
      retentionTargetY,
      retentionFocusSequenceBefore,
      retentionFocusSequenceAfter,
      retentionOzoneFocusReports,
      pointerInput: null,
      keyboardInput: null,
      focusInput: null,
      ozoneFocusState: null,
      focusRetentionProof: null,
      logs: null,
      shutdown: null,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.pointerInput = result.readiness.pointerInput;
        result.keyboardInput = result.readiness.keyboardInput;
        result.focusInput = result.readiness.focusInput;
        result.ozoneFocusState = result.readiness.ozoneFocusState;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

async function runM5WispNetworkSmokeFromQuery() {
  const parameters = new URLSearchParams(location.search);
  const versions = {
    chromium: normalizeVersion(parameters.get("chromium")),
    v8: normalizeVersion(parameters.get("v8")),
    emscripten: normalizeVersion(parameters.get("emscripten")),
    port: normalizeVersion(parameters.get("port")),
  };
  renderVersions(versions);
  const statusElement = document.querySelector("#smoke-status");
  const root = document.querySelector("#smoke-root");
  const canvas = document.querySelector("#browser-canvas");
  const token = parameters.get("token") || "";
  const relayEndpoint = parameters.get("wisp_endpoint");
  const m5URL = parameters.get("m5_url");
  const m5PlaintextHttpControlURL = parameters.get(
    "m5_plaintext_http_control_url");
  const m5TLSFailureURL = parameters.get("m5_tls_failure_url");
  const timeoutMs = Math.max(
    1000, Math.min(180000, Number(parameters.get("timeout_ms")) || 90000));
  let host = null;
  let readiness = null;
  let initialFrame = null;
  let plaintextHttpControlNavigationResult = null;
  let plaintextHttpControlReadiness = null;
  let navigationResult = null;
  let tlsFailureNavigationResult = null;
  let tlsFailureReadiness = null;
  let shutdown = null;
  let result;

  try {
    if (parameters.get("case") !== M5_NETWORK_CASE) {
      throw new Error("M5 WISP case query mismatch");
    }
    if (!token) {
      throw new Error("missing M5 WISP result token");
    }
    if (!relayEndpoint) {
      throw new Error("missing M5 WISP endpoint");
    }
    const testURL = normalizeM5NetworkTestURL(m5URL);
    const plaintextHttpControlURL = normalizeM5PlaintextHttpControlURL(
      m5PlaintextHttpControlURL);
    const tlsFailureURL = normalizeM5NetworkTestURL(m5TLSFailureURL);
    host = new ChromiumWasmM3Host(
        canvas, versions, {fixture: M5_NETWORK_FIXTURE});
    window.chromiumWasmHost = host;
    const deadline = performance.now() + timeoutMs;

    await host.initialize({
      modulePath: parameters.get("module"),
      readyTimeoutMs: Math.min(60000, Math.max(1000, timeoutMs - 1000)),
      wisp: {
        version: WISP_CONFIGURATION_VERSION,
        endpoint: relayEndpoint,
        subprotocol: "wisp",
      },
    });
    await host.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1);
    while (performance.now() < deadline) {
      const candidate = await host.readiness();
      if (candidate.frame?.width === DEFAULT_WIDTH &&
          candidate.frame?.height === DEFAULT_HEIGHT) {
        initialFrame = candidate.frame;
        break;
      }
      await delay(25);
    }
    if (!initialFrame) {
      throw new Error("M5 runtime did not present the initial shell frame");
    }

    plaintextHttpControlNavigationResult =
      await host.loadM5PlaintextHttpControlURL(plaintextHttpControlURL);
    while (performance.now() < deadline) {
      plaintextHttpControlReadiness = await host.readiness();
      if (
        plaintextHttpControlReadiness.navigation?.committed === true &&
        plaintextHttpControlReadiness.navigation?.scheme === "http" &&
        hasM5PlaintextHttpControlPageProbe(
          plaintextHttpControlReadiness.pageProbe)
      ) {
        break;
      }
      if (
        plaintextHttpControlReadiness.navigation?.committed === false &&
        plaintextHttpControlReadiness.navigation?.scheme === "http"
      ) {
        break;
      }
      await delay(50);
    }
    if (
      !plaintextHttpControlReadiness ||
      plaintextHttpControlReadiness.navigation?.committed !== true ||
      plaintextHttpControlReadiness.navigation?.scheme !== "http" ||
      !hasM5PlaintextHttpControlPageProbe(
        plaintextHttpControlReadiness.pageProbe) ||
      plaintextHttpControlReadiness.fatalErrors?.length !== 0
    ) {
      throw new Error(
        "M5 WISP plaintext HTTP control did not complete: " +
        JSON.stringify(plaintextHttpControlReadiness));
    }

    navigationResult = await host.loadM5NetworkURL(testURL);
    while (performance.now() < deadline) {
      readiness = await host.readiness();
      if (readiness.baseReady && hasM5NetworkPageProbe(readiness.pageProbe)) {
        break;
      }
      await delay(50);
    }
    if (!readiness || !readiness.baseReady ||
        !hasM5NetworkPageProbe(readiness.pageProbe)) {
      throw new Error(
          "M5 WISP HTTPS fixture did not complete: " +
          JSON.stringify(readiness));
    }

    tlsFailureNavigationResult = await host.loadM5NetworkURL(tlsFailureURL);
    while (performance.now() < deadline) {
      tlsFailureReadiness = await host.readiness();
      if (
        tlsFailureReadiness.navigation?.committed === false &&
        tlsFailureReadiness.navigation?.scheme === "https" &&
        tlsFailureReadiness.navigation?.netError ===
          M5_TLS_NAME_MISMATCH_NET_ERROR
      ) {
        break;
      }
      await delay(50);
    }
    if (
      !tlsFailureReadiness ||
      tlsFailureReadiness.navigation?.committed !== false ||
      tlsFailureReadiness.navigation?.scheme !== "https" ||
      tlsFailureReadiness.navigation?.netError !==
        M5_TLS_NAME_MISMATCH_NET_ERROR
    ) {
      throw new Error(
        "M5 WISP TLS-name-mismatch fixture did not fail natively: " +
        JSON.stringify(tlsFailureReadiness));
    }

    const shutdownTimeoutMs = Math.max(
      1000, Math.min(60000, deadline - performance.now()));
    shutdown = await host.shutdown(shutdownTimeoutMs);
    const pageProbe = readiness.pageProbe;
    const logs = await host.logs();
    const checks = {
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      initialFrame: initialFrame !== null,
      wispConfigured: logs.host.includes("initialize:wisp-configured"),
      plaintextHttpControl:
        plaintextHttpControlNavigationResult?.ok === true &&
        plaintextHttpControlReadiness.navigation?.committed === true &&
        plaintextHttpControlReadiness.navigation?.scheme === "http" &&
        hasM5PlaintextHttpControlPageProbe(
          plaintextHttpControlReadiness.pageProbe) &&
        plaintextHttpControlReadiness.fatalErrors?.length === 0,
      m5Navigation:
        navigationResult?.ok === true &&
        readiness.navigation?.committed === true &&
        readiness.navigation?.scheme === "https",
      tlsNameMismatch:
        tlsFailureNavigationResult?.ok === true &&
        tlsFailureReadiness.navigation?.committed === false &&
        tlsFailureReadiness.navigation?.scheme === "https" &&
        tlsFailureReadiness.navigation?.netError ===
          M5_TLS_NAME_MISMATCH_NET_ERROR &&
        tlsFailureReadiness.fatalErrors?.length === 0,
      fixture: hasM5NetworkPageProbe(pageProbe),
      redirect: pageProbe.redirected === true,
      cache:
        pageProbe.cacheStored === true && pageProbe.cacheRevalidated === true,
      csp: pageProbe.cspConnectSrcBlocked === true,
      activeMixedContent:
        pageProbe.activeMixedContentBlocked === true &&
        typeof pageProbe.activeMixedContentTargetUrl === "string" &&
        pageProbe.activeMixedContentTargetUrl.length > 0 &&
        pageProbe.activeMixedContentErrorName === "TypeError" &&
        pageProbe.activeMixedContentCspAllowed === true,
      http2: pageProbe.h2Fetch === true && pageProbe.h2Protocol === "h2",
      cors: pageProbe.corsFetch === true,
      webSocket: pageProbe.webSocketEcho === true,
      altSvcH3Advertised: pageProbe.altSvcH3Advertised === true,
      shutdown:
        shutdown.ok === true && shutdown.complete === true &&
        shutdown.exitCode === 0 && shutdown.runtimeExitCode === 0,
      versions: Object.values(versions).every((value) => value !== "missing"),
    };
    const failedChecks = Object.entries(checks)
      .filter(([, passed]) => !passed)
      .map(([name]) => name);
    result = {
      protocol: HOST_PROTOCOL,
      case: M5_NETWORK_CASE,
      status: failedChecks.length === 0 ? "pass" : "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      initialFrame,
      plaintextHttpControlNavigationResult,
      plaintextHttpControlReadiness,
      navigationResult,
      readiness,
      tlsFailureNavigationResult,
      tlsFailureReadiness,
      logs,
      shutdown,
      failedChecks,
      error: failedChecks.length === 0
        ? null : "failed checks: " + failedChecks.join(", "),
    };
  } catch (error) {
    result = {
      protocol: HOST_PROTOCOL,
      case: M5_NETWORK_CASE,
      status: "fail",
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocused: document.activeElement === canvas,
      versions,
      initialFrame,
      plaintextHttpControlNavigationResult,
      plaintextHttpControlReadiness,
      navigationResult,
      tlsFailureNavigationResult,
      readiness: null,
      tlsFailureReadiness: null,
      logs: null,
      shutdown,
      failedChecks: ["exception"],
      error: String(error),
    };
    if (host) {
      try {
        result.logs = await host.logs();
      } catch (diagnosticError) {
        result.error += "; diagnostics: " + String(diagnosticError);
      }
      try {
        result.readiness = await host.readiness();
        result.plaintextHttpControlReadiness = result.readiness;
        result.tlsFailureReadiness = result.readiness;
      } catch (diagnosticError) {
        result.error += "; readiness diagnostics: " + String(diagnosticError);
      }
    }
  }

  root.dataset.state = result.status;
  statusElement.textContent = JSON.stringify(result, null, 2);
  await postResult(token, result);
  return result;
}

export async function runContentShellSmokeFromQuery() {
  const selectedCase = new URLSearchParams(location.search).get("case");
  if (selectedCase === M3_CASE) {
    return runM3SmokeFromQuery();
  }
  if (selectedCase === M4_CASE) {
    return runM4OzonePointerSmokeFromQuery();
  }
  if (selectedCase === M4_SELECT_CASE) {
    return runM4OzoneSelectSmokeFromQuery();
  }
  if (selectedCase === M4_RESIZE_CASE) {
    return runM4OzoneResizeSmokeFromQuery();
  }
  if (selectedCase === M4_DPR_CASE) {
    return runM4OzoneDprSmokeFromQuery();
  }
  if (selectedCase === M4_CONTEXT_MENU_CASE) {
    return runM4OzoneContextMenuSmokeFromQuery();
  }
  if (selectedCase === M4_TOOLTIP_CASE) {
    return runM4OzoneTooltipSmokeFromQuery();
  }
  if (selectedCase === M4_SELECTION_CASE) {
    return runM4OzoneSelectionSmokeFromQuery();
  }
  if (selectedCase === M4_PRIMARY_PASTE_CASE) {
    return runM4OzonePrimaryPasteSmokeFromQuery();
  }
  if (selectedCase === M4_COPY_PASTE_CASE) {
    return runM4OzoneCopyPasteSmokeFromQuery();
  }
  if (selectedCase === M4_WHEEL_CASE) {
    return runM4OzoneWheelSmokeFromQuery();
  }
  if (selectedCase === M4_KEYBOARD_CASE) {
    return runM4OzoneKeyboardSmokeFromQuery();
  }
  if (selectedCase === M4_PRINTABLE_KEY_CASE) {
    return runM4OzonePrintableKeySmokeFromQuery();
  }
  if (selectedCase === M4_BACKSPACE_CASE) {
    return runM4OzoneBackspaceSmokeFromQuery();
  }
  if (selectedCase === M4_IME_BRIDGE_CASE) {
    return runM4OzoneImeBridgeSmokeFromQuery();
  }
  if (selectedCase === M4_FOCUS_CASE) {
    return runM4OzoneFocusSmokeFromQuery();
  }
  if (selectedCase === M4_FOCUS_RETENTION_CASE) {
    return runM4OzoneFocusRetentionSmokeFromQuery();
  }
  if (selectedCase === M5_NETWORK_CASE) {
    return runM5WispNetworkSmokeFromQuery();
  }
  throw new Error("unknown Content Shell Wasm smoke case");
}

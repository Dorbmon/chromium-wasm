# M3 Content Shell host contract

This loader is a diagnostic shell around Chromium-rendered pixels. It does not
recreate browser controls in HTML.

## JavaScript API

`window.chromiumWasmHost` is installed by the M3 page and exposes asynchronous
methods:

- `initialize({modulePath, readyTimeoutMs})`
- `resize(width, height, devicePixelRatio)`
- `loadURL(url)`
- `injectInput(event)`
- `requestScreenshot()`
- `readiness()`
- `logs()`
- `shutdown()`

Every method returns a Promise. M3 accepts only a deterministic `data:` URL.
The M3 input control supports exactly one primary-button click:

```json
{
  "ok": true,
  "accepted": true,
  "code": "CLICK_POSTED",
  "eventType": "click",
  "x": 570,
  "y": 468,
  "button": 0
}
```

The click is forwarded through Content's `RenderWidgetHost` input path. The
fixture proves delivery with a trusted DOM `click` and a later compositor
frame. After the trusted probe is observed, the runner forces a deterministic
799×600 resize and restores 800×600; both transitions must present newer
frames before capture. This avoids assuming that the periodic probe runs
before the CLICKED paint. Pointer movement, wheel, keyboard, IME, focus,
capture, and the general Ozone event source remain the M4 gate. Returning
success while dropping an event is a contract failure.

`initialize()` does not resolve merely because the Emscripten MODULARIZE
factory resolved. It waits for a `shellReady` bridge report, proving that
Chromium reached `PreMainMessageLoopRun` and registered the UI runner before
the first resize or navigation command.

## Runtime exports

The Emscripten module must expose these C ABI functions (directly or through
`Module.ccall`):

```c
int chromium_wasm_host_resize(int width, int height, double device_pixel_ratio);
int chromium_wasm_host_load_url(const char* data_url);
int chromium_wasm_host_click(int x, int y, int button);
int chromium_wasm_host_shutdown(void);
```

Each returns `1` only after accepting the operation. Any other value fails the
gate. For tests, equivalent functions may be supplied on
`Module.chromiumWasmHostCommands`, keyed by the full C function name.
`chromium_wasm_host_load_url` must copy the URL before returning. The host
releases its temporary UTF-8 allocation immediately after the call. Runtime
exports sequence-hop to Chromium's application thread and must not block the
browser JavaScript main thread.

M3 resize accepts dimensions in `[1, 16384]`, at most 128 MiB total for the
Skia raster backing plus its RGBA presentation copy, and device-pixel ratio 1.
The runner proves an actual 640×480 frame before restoring the 800×600
acceptance surface. `shutdown()` does not
resolve when the task is merely posted: it waits for `ContentMain` and the
shell delegate to finish, then requires Emscripten's `onExit` after it has
requested termination of every running and prewarmed pthread worker. Both
exit statuses must be zero and equal.

## Runtime-to-host bridge

The Content/Ozone integration reports state through the versioned global
`globalThis.__chromiumWasmHostBridgeV1`:

```js
bridge.reportFrame({
  protocol: 1,
  id: 1,
  width: 800,
  height: 600,
  timestampMs: 1234.5,
});

bridge.reportReadiness({
  protocol: 1,
  shellReady: true,
  surfaceReady: true,
  firstVisuallyNonEmptyPaint: true,
});

bridge.reportNavigation({
  protocol: 1,
  committed: true,
  scheme: "data",
});

bridge.reportPageProbe({
  protocol: 1,
  fixture: "chromium-wasm-m3-static-v1",
  ready: true,
  fontReady: true,
  imageReady: true,
  canvasReady: true,
  timerTicks: 30,
  scrollTop: 48,
  formValue: "M3 form",
  inputClicks: 1,
  inputTrusted: true,
  buttonText: "CLICKED",
  buttonCenterX: 570,
  buttonCenterY: 468,
});

bridge.reportProcessExit({
  protocol: 1,
  exitCode: 0,
});
```

Fatal runtime failures call `bridge.reportFatal(message)`. Wasm aborts,
uncaught outer-page exceptions, and unhandled Promise rejections are also
captured as fatal errors.

The page probe must be reported again as its timer count advances; readiness
requires a probe with at least three ticks rather than treating initial script
execution as sufficient evidence.

Frame IDs must increase monotonically across surface recreation. The
presentation bridge must copy pixel bytes before returning and must never
retain a `HEAPU8` view across possible `WebAssembly.Memory` growth.

## Passing gate

Readiness is computed by the host rather than accepted as a single runtime
boolean. It requires:

- initialized runtime, shell, and software surface;
- committed `data:` navigation and first visually nonempty paint;
- a passing inner-page probe and at least three inner timer ticks;
- one trusted primary-button click delivered to the fixture;
- a compositor frame matching the 800×600 canvas;
- a proved 799×600/800×600 redraw sequence after the interaction was first
  observed;
- at least 3 seconds of outer-page timer and animation-frame progress;
- no timer gap above 250 ms and no fatal error.

The runner then captures a PNG, waits for deterministic Content and Emscripten
runtime shutdown, checks the ordered lifecycle logs, and compares the PNG with
a reviewed baseline. The checked-in screenshot contract allows a per-channel
delta of 2 and at most 0.25% differing pixels.

`--capture-baseline PATH` writes a candidate only after every non-pixel runtime
check passes and exits with status 2. It never reports the M3 gate as passing.
Review the image, then run again with `--baseline PATH`.

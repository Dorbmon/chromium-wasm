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
Input is intentionally not forwarded yet and returns:

```json
{
  "ok": false,
  "code": "INPUT_UNSUPPORTED_UNTIL_M4",
  "milestone": "M4"
}
```

Returning success while dropping an event is a contract failure.
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
int chromium_wasm_host_shutdown(void);
```

Each returns `1` only after accepting the operation. Any other value fails the
gate. For tests, equivalent functions may be supplied on
`Module.chromiumWasmHostCommands`, keyed by the full C function name.
`chromium_wasm_host_load_url` must copy the URL before returning. The host
releases its temporary UTF-8 allocation immediately after the call. Runtime
exports sequence-hop to Chromium's application thread and must not block the
browser JavaScript main thread.

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
});
```

Fatal runtime failures call `bridge.reportFatal(message)`. Wasm aborts,
uncaught outer-page exceptions, and unhandled Promise rejections are also
captured as fatal errors.

The page probe must be reported again as its timer count advances; readiness
requires a probe with at least three ticks rather than treating initial script
execution as sufficient evidence.

Frame IDs must increase monotonically. The presentation bridge must copy pixel
bytes before returning and must never retain a `HEAPU8` view across possible
`WebAssembly.Memory` growth.

## Passing gate

Readiness is computed by the host rather than accepted as a single runtime
boolean. It requires:

- initialized runtime, shell, and software surface;
- committed `data:` navigation and first visually nonempty paint;
- a passing inner-page probe and at least three inner timer ticks;
- a compositor frame matching the 800×600 canvas;
- at least 3 seconds of outer-page timer and animation-frame progress;
- no timer gap above 250 ms and no fatal error.

The runner then captures a PNG, verifies the structured M4 input rejection,
requests deterministic shutdown, and compares the PNG with a reviewed
baseline. The checked-in screenshot contract allows a per-channel delta of 2
and at most 0.25% differing pixels.

`--capture-baseline PATH` writes a candidate only after every non-pixel runtime
check passes and exits with status 2. It never reports the M3 gate as passing.
Review the image, then run again with `--baseline PATH`.

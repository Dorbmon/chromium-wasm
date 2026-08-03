# M3 Content Shell host contract

This loader is a diagnostic shell around Chromium-rendered pixels. It does not
recreate browser controls in HTML.

## JavaScript API

`window.chromiumWasmHost` is installed by the M3/M4 page and exposes
asynchronous methods:

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
before the CLICKED paint. This legacy M3 click path remains an M3 regression
control; it is not the M4 input path.

M4 adds `enableM4PointerInput()`, `enableM4WheelInput()`, the narrowly scoped
`enableM4KeyboardInput()`, `enableM4FocusInput()`, and the bounded native
composition contract `enableM4ImeProxyInput()` after initialization. They
attach host-canvas or host-owned-proxy listeners, not a replacement HTML
browser UI. Primary mouse pointer input, pixel wheel input, the bounded raw-key
paths, host focus loss, and the limited composition route cross normal Ozone
boundaries. Generic text entry, arbitrary selection/replacement, deletion,
paste, modifiers, repeat, touch, pen, non-primary buttons, cursor control,
focus regain without a pointer press, and richer multi-window behavior remain
outside this first M4 input slice. Returning success while dropping an event is
a contract failure.

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
int chromium_wasm_host_pointer(int type, int x, int y, int button);
int chromium_wasm_host_wheel(int x, int y, int delta_x, int delta_y);
int chromium_wasm_host_key(const char* code, int down);
int chromium_wasm_host_text_input(int action, int session_id, int sequence,
                                  const uint8_t* text_utf8,
                                  int text_utf8_bytes, int selection_start,
                                  int selection_end);
int chromium_wasm_host_deactivate(void);
int chromium_wasm_host_shutdown(void);
```

Each returns `1` only after accepting and queueing the operation on Chromium's
UI task runner. Any other value fails the gate. In particular, `1` from an M4
input export means **queued**, not that Ozone, Aura, or Blink has delivered the
event. `chromium_wasm_host_text_input` additionally means that the UTF-8 bytes
were copied and validated before its UI-task hop; it is not a native
`TextInputClient` acknowledgement. End-to-end evidence must come from the
inner-page probe, a matching delivery acknowledgement for text input, and a
later compositor frame. For tests, equivalent functions may be supplied on
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

### M4 pointer, wheel, raw-key, focus-loss, and IME ABI

`chromium_wasm_host_pointer` accepts only primary mouse input: `type` is `0`
for move, `1` for down, or `2` for up, and `button` must be `0`. The host
accepts only trusted primary mouse `PointerEvent`s. It focuses and captures the
canvas for a press, and releases or cancels that capture on pointer up, pointer
cancel, blur, visibility loss, or teardown.

The `x` and `y` arguments of both M4 exports are physical canvas backing
pixels, never outer-page CSS pixels. The host subtracts the canvas border and
content origin from `clientX`/`clientY`, scales through
`canvas.width / canvas.clientWidth` and its Y equivalent, then floors the
result. Coordinates must be nonnegative; the UI-side task separately checks
that they still fall within the current Wasm viewport.

`chromium_wasm_host_wheel` receives a trusted, cancelable, unmodified DOM
`WheelEvent` with `deltaMode == DOM_DELTA_PIXEL` and no modifier keys. The host
does not emulate page scrolling in JavaScript. It converts the DOM CSS-pixel
deltas to physical backing-pixel deltas, retaining fractional residuals until
an integral physical-pixel wheel command can be queued. A zero integral delta
is deliberately buffered rather than reported as delivered. Non-pixel,
untrusted, noncancelable, modified, out-of-canvas, invalid, and out-of-range
wheel events are explicitly rejected.

DOM wheel deltas are positive for right and down. The host passes that physical
pixel convention unchanged to `chromium_wasm_host_wheel`; the C++ ABI boundary
converts the sign exactly once before `SystemInputInjector::InjectMouseWheel`,
whose Chromium convention is positive for left and up. This keeps Blink's
observed DOM wheel delta in the original right/down convention.

`chromium_wasm_host_key` accepts only the bounded DOM code strings
`"ArrowDown"` and `"KeyA"`, with `down == 0` or `1`. The `"KeyA"` slice
also requires the unmodified DOM key `"a"`; it is a fixed-US physical-layout
experiment, not a host text, composition, or IME API. The host accepts only a
trusted, cancelable canvas `keydown`/`keyup` pair after a queued
primary-pointer press has activated the Wasm window. It rejects modifier,
repeat, composition, dead-key, process-key, unsupported-code, mismatched key,
duplicate-down, and unmatched-up records explicitly. A successful export means
the record was queued on the UI task runner; it does not mean Blink has received
it. The host cancels its held key state on canvas or window blur, visibility
loss, teardown, and shutdown, queuing a matching release when Chromium is still
running. It prevents the outer canvas event's default action only after queue
acceptance.

`chromium_wasm_host_deactivate` accepts no arguments and is one-way: it is
queued only when the host canvas, host window, or document visibility loses
focus. The host cancels an active pointer and queues held raw-key releases
before it queues deactivation, preserving event order on Chromium's UI task
runner. The UI task clears the normal Aura `FocusClient` target and then calls
the generic `PlatformWindow::Deactivate()` API. This reaches Blink's ordinary
lost-focus handling while clearing ozone_wasm's keyboard target without
referencing a Wasm platform class from Content Shell. Focus regain remains the
existing trusted primary-pointer activation path; a wheel event focusing the
outer canvas must not activate the browser window.

The pointer, wheel, and raw-key exports create a `SystemInputInjector`
through public `OzonePlatform`, then route through the Wasm
`PlatformEventSource`, Aura's `PlatformWindowDelegate`, and Blink. A
primary pointer press activates the Ozone window; raw key records target that
keyboard-focused window rather than hover or wheel hit testing. The M4 pointer
smoke proves trusted inner mouse and pointer events, trusted link activation,
and a newer compositor frame after the queued release. The M4 wheel smoke
proves a trusted inner pixel-mode wheel event with the expected DOM delta,
inner scrolling while the outer page remains unscrolled, and a newer compositor
frame. The M4 raw-key smoke clicks a real focusable page element, drives one
trusted DevTools `rawKeyDown`/`keyUp` pair, proves trusted inner ArrowDown
events and normal document scrolling, verifies no text, beforeinput, input, or
composition side effects, and requires a newer compositor frame after the key
down. These checks, rather than an export return value, establish
Ozone/Aura/Blink delivery.

The M4 printable-key smoke clicks a real initially empty Blink text input and
drives one trusted DevTools `KeyA` `rawKeyDown`/`keyUp` pair without a DevTools
text payload. It requires trusted inner key events, exactly one trusted
`beforeinput` and `input` pair with `inputType == "insertText"` and data
`"a"`, a collapsed selection after the inserted character, no composition
events, and a newer compositor frame. This proves the bounded direct-layout
path through Ozone/Aura and Chromium text input; it does not provide generic
text entry or IME support.

#### Bounded IME composition route

A queued pointer event alone does not arm the proxy: its focus is delayed until
the Ozone-owned `WasmInputMethod` reports a fresh focused `TextInputClient`
that is editable and supports inline composition. The host also requires a
fresh active Ozone keyboard-target report. It then consumes a one-shot
canvas-to-exact-proxy focus-transfer token, preserving the existing Aura/Ozone
target only for that expected transition. A non-editable click therefore cannot
steal DOM focus.

The host accepts only trusted `compositionstart`, `compositionupdate`,
`beforeinput`, and matching `input` events for one bounded, well-formed UTF-16
`insertCompositionText` transaction. It creates the native record only after
the matching outer `beforeinput`. `compositionend` has no text authority.
Blink emits this terminal through its scoped event queue and may therefore
report it untrusted even when its source transaction was genuine. The host
accepts it only as a zero-authority lifecycle acknowledgement: it may confirm
the exact private candidate, but only after the same session has already
established that candidate through trusted source events. It cannot create,
replace, alter, or clear a candidate. Cancellation instead requires a trusted
empty `compositionupdate`/`beforeinput`/`input` transaction; its final terminal
is observation-only after ClearCompositionText was queued. The proxy text is
never copied into diagnostics: diagnostics retain only its UTF-16-unit,
UTF-8-byte, and code-point counts.

`action`, `session_id`, and `sequence` are positive signed 32-bit values.
`sequence` must strictly increase for the target Ozone widget; terminal actions
must name the active session and current focused client. Selection offsets are
UTF-16 code units. This initial route deliberately supports only a collapsed
candidate-end selection, because the underlying Aura renderer path does not yet
preserve an arbitrary composition selection range.

| Action | Text and selection contract | Ozone-owned operation |
| --- | --- | --- |
| `1` (`set-composition`) | Nonempty, well-formed UTF-8; at most 64 Ki UTF-16 units and 192 KiB; selection is `[N, N]`, where `N` is the decoded UTF-16 length. | `TextInputClient::SetCompositionText` |
| `2` (`confirm-composition`) | No text (`text_utf8_bytes == 0`) and selection `[0, 0]`; session must match the active composition. | `TextInputClient::ConfirmCompositionText(false)` |
| `3` (`clear-composition`) | No text (`text_utf8_bytes == 0`) and selection `[0, 0]`; session must match the active composition. | `TextInputClient::ClearCompositionText` |

The C ABI rejects malformed action, ID, range, pointer, size, or UTF-8 records
synchronously with `0`. For a nonempty payload, it verifies that the Wasm
memory range is live, copies the bytes before posting, validates UTF-8 while
allowing Unicode noncharacters, and converts to an owned UTF-16 record. A null
text pointer is valid only for a zero-byte terminal record. The host must not
retain a Wasm-memory view across this call or across possible memory growth.

On its UI task, Content Shell resolves the exact Aura/Ozone accelerated widget
and calls the opaque `DispatchWasmTextInput` boundary. `WasmInputMethod` then
requires that widget to be visible and keyboard focused, and that its current
client be editable and compose-inline capable. It invokes only the standard
`TextInputClient` composition methods above; it neither uses
`SystemInputInjector` nor injects a Blink/renderer event directly. Proxy blur,
teardown, and host deactivation clear an active native candidate before their
normal focus transitions. This is a bounded composition path, not generic text
or physical-OS-IME compatibility.

The host records the queue entry before calling the C export and waits for a
matching runtime-to-host delivery report. `accepted: true` in that report means
the Ozone `WasmInputMethod` accepted the record and issued the corresponding
`TextInputClient` call. It does not by itself prove that Blink emitted the
expected DOM events or painted; the smoke must still prove the inner
composition/preedit and final commit (or clear) plus a later frame. `accepted:
false` means no native text operation was issued for that record and invalidates
the host transaction. Unknown, duplicate, or mismatched acknowledgements are
fatal host-contract errors.

The M4 focus-loss smoke holds one trusted raw `ArrowDown` down event, uses a
trusted DevTools mouse click on a real host-page focus-sink button, and requires
the canvas blur record, generated matching key-up, cleared Ozone keyboard
state confirmed by a UI-thread Ozone focus report, trusted inner `keyup`, inner
`window.blur`, `document.hasFocus() == false`, a later compositor frame, and
clean shutdown. It never calls inner-page `focus()`, `blur()`, or
`dispatchEvent()`.

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

bridge.reportOzoneFocusState({
  protocol: 1,
  keyboardTargetPresent: false,
  active: false,
});

bridge.reportOzoneTextInputState({
  protocol: 1,
  focusedClientPresent: true,
  editable: true,
  canComposeInline: true,
});

bridge.reportOzoneTextInputDelivery({
  protocol: 1,
  action: 1,
  sessionId: 7,
  sequence: 11,
  accepted: true,
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

ozone_wasm sends `reportOzoneFocusState` after each activation transition.
Its values come from the UI-thread `WasmWindowManager` and platform activation
state, rather than host-page bookkeeping. The M4 focus-loss smoke requires a
fresh false/false report after the trusted focus-sink click.

`WasmInputMethod` sends `reportOzoneTextInputState` whenever Aura changes the
focused `TextInputClient` or its text-input type. The report contains only
booleans; it never exposes client identity, text, selection, or composition
data. The IME proxy gate uses a report newer than its trusted pointer press,
not a page-probe guess or a queued host command, before transferring DOM focus.

After every routed text-input record, Content Shell sends
`reportOzoneTextInputDelivery`. It contains only the protocol version, action,
session ID, sequence, and boolean native acceptance result; it never returns
the candidate text, selection, client identity, or renderer state. The host
matches it exactly once to its already queued request.

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

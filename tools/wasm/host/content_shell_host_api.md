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
browser UI. Primary, bounded middle, and bounded secondary mouse pointer input,
pixel wheel input, the bounded raw-key paths, one explicit trusted ArrowDown
repeat, host focus loss, and the limited composition route cross normal Ozone
boundaries. A primary-mouse drag can use the same pointer path to make a native
Blink selection; it is not a host selection command. Generic text entry,
programmatic or arbitrary selection/replacement, deletion, generic paste,
modifiers, generic repeat, touch, pen, non-primary buttons outside the bounded
middle-click primary-paste and secondary context-menu routes, cursor
warping/confinement, focus regain without a pointer press, and richer
multi-window behavior remain outside this first M4 input slice. Returning
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
int chromium_wasm_host_pointer(int type, int x, int y, int button);
int chromium_wasm_host_wheel(int x, int y, int delta_x, int delta_y);
int chromium_wasm_host_key(const char* code, int down);
int chromium_wasm_host_arrow_down_repeat(void);
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

The bounded resize API accepts dimensions in `[1, 16384]`, at most 128 MiB
total for the Skia raster backing plus its RGBA presentation copy, and only
device-pixel ratio 1. An M4 resize first updates ozone_wasm's single primary
display and work area at that same scale, notifying normal display observers,
then resizes Aura, Blink, and the software surface. The dedicated smoke drives
800×600 → 640×480 → 800×600 through this API alone and requires trusted native
`resize` events, matching `window`/`screen` geometry, a CSS two-column →
one-column → two-column reflow, and newer compositor frames. DPR changes,
multi-display topology, and popup coordinate scaling remain explicitly
unsupported. `shutdown()` does not
resolve when the task is merely posted: it waits for `ContentMain` and the
shell delegate to finish, then requires Emscripten's `onExit` after it has
requested termination of every running and prewarmed pthread worker. Both
exit statuses must be zero and equal.

### M4 pointer, wheel, raw-key, focus-loss, and IME ABI

`chromium_wasm_host_pointer` accepts the bounded mouse buttons `0` (primary),
`1` (middle), and `2` (secondary): `type` is `0` for move, `1` for down, or
`2` for up. The host accepts only trusted mouse `PointerEvent`s for those
buttons. It focuses and captures the canvas for a press, and releases or
cancels that capture with the same button on pointer up, pointer cancel, blur,
visibility loss, or teardown. Other mouse buttons, touch, and pen remain
explicitly unsupported. Middle input is presently limited to the native
primary-selection-paste proof below; it is not generic auxiliary-button input.
Secondary input is limited to the native context-menu proof below; it is not
generic auxiliary-button input. One unmodified pointer ID/button stream may be
active at a time; additional button chords, mismatched releases, and held moves
with the wrong button mask are rejected before reaching Ozone. A matching
active-button release remains a cleanup path once its own button bit has
cleared, even if an unsupported button is still held, so the native input state
cannot stick. Once a middle-button record is queued, the host prevents the
outer page default so the embedding page cannot start its own middle-click
behavior such as autoscroll. Once a matching secondary stream is queued, it
prevents only the trusted matching outer-page `contextmenu` default; Blink
still receives the native Ozone mouse stream and owns the in-Chromium menu.

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

`chromium_wasm_host_key` accepts exactly the bounded DOM code strings
`"ArrowDown"`, `"KeyA"`, `"Backspace"`, `"ControlLeft"`, `"KeyC"`, and
`"KeyV"`, with `down == 0` or `1`. This physical-key ABI has no text payload.
The `"KeyA"` and `"Backspace"` slices require the unmodified DOM keys `"a"`
and `"Backspace"`, respectively. `"KeyA"` is a fixed-US physical-layout
experiment and `"Backspace"` is one fixed backward-edit key. `"KeyC"` and
`"KeyV"` are admitted only as a paired `ControlLeft` chord; Alt, Meta, Shift,
other Control combinations, and generic modifier handling remain unsupported.
None of these keys is a host text, composition, IME, generic editing, or generic
keyboard API. The ABI rejects unpaired or duplicate Control, `KeyC`, and
`KeyV` transitions before queueing. The host accepts only a trusted,
cancelable canvas `keydown`/`keyup` pair after a queued primary-pointer press
has activated the Wasm window. It rejects modifier, composition, dead-key,
process-key, unsupported-code, mismatched key, duplicate-down, and unmatched-up
records explicitly. `chromium_wasm_host_arrow_down_repeat` is the only repeat
escape hatch: the host calls it only for a trusted, cancelable `ArrowDown`
`keydown` with `KeyboardEvent.repeat == true` while that same ArrowDown is
already held. It posts exactly one Ozone `kKeyPressed` record with
`EF_IS_REPEAT`; it neither starts nor requests a repeat timer. Repeat-before-
down, keyup repeats, and repeats of every other supported key remain rejected.
A successful export means the record was queued on the UI task runner; it does
not mean Blink has received it. The host cancels its held key state on canvas or
window blur, visibility loss, teardown, and shutdown, releasing chord keys
before `ControlLeft` when Chromium is still running. It prevents the outer
canvas event's default action only after queue acceptance.

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
and a newer compositor frame after the queued release. The same trusted hover
now reaches Aura's `CursorClient`, `WindowTreeHost`, and `WasmWindow`, whose
versioned host report applies the corresponding standard CSS cursor to the
outer canvas. It proves Blink's `cursor: pointer` becomes the native hand
cursor and then `canvas.style.cursor == "pointer"`; this CSS update does not
need a compositor redraw. Exact CSS-compatible standard cursor shapes are
scalar type mappings, and the native call succeeds only after the host accepts
the CSS value. Directional panning, DnD decoration, no-resize, and
custom bitmap/hotspot cursors expose a diagnostic fallback but explicitly
report unsupported rather than being silently treated as rendered; cursor
movement/confinement remain unsupported. The M4 wheel smoke
proves a trusted inner pixel-mode wheel event with the expected DOM delta,
inner scrolling while the outer page remains unscrolled, and a newer compositor
frame. The M4 raw-key smoke clicks a real focusable page element, drives
trusted DevTools `rawKeyDown`, `rawKeyDown(autoRepeat)`, and `keyUp` records,
proves the exact trusted inner ArrowDown repeat sequence and normal document
scrolling, verifies no text, beforeinput, input, or composition side effects,
and requires a newer compositor frame after the repeat record. These checks,
rather than an export return value, establish Ozone/Aura/Blink delivery.

The M4 native-select smoke makes two trusted primary-pointer clicks. The first
opens Blink's internal Aura popup for a real HTML `<select>`; the host finds
the fixture's option color only in actual compositor canvas pixels and uses the
scan-derived center for the second click. It requires native trusted `input`
then `change` delivery for option `two`, popup disappearance, and a newer
compositor frame. This proves one collapsed HTML select control, not
Chrome/Views menus, dialogs, tooltips, arbitrary transient surfaces, or a
general popup protocol.

The M4 printable-key smoke clicks a real initially empty Blink text input and
drives one trusted DevTools `KeyA` `rawKeyDown`/`keyUp` pair without a DevTools
text payload. It requires trusted inner key events, exactly one trusted
`beforeinput` and `input` pair with `inputType == "insertText"` and data
`"a"`, a collapsed selection after the inserted character, no composition
events, and a newer compositor frame. This proves the bounded direct-layout
path through Ozone/Aura and Chromium text input; it does not provide generic
text entry or IME support.

The separate M4 Backspace smoke clicks a real initially empty Blink text input,
then drives a trusted `KeyA` `rawKeyDown`/`keyUp` pair followed by a trusted
`Backspace` `rawKeyDown`/`keyUp` pair. It sends raw physical-key records only,
with no DevTools text payload. The proof requires the exact trusted inner
four-key trace, then exactly four trusted editing events: `beforeinput` and
`input` with `inputType == "insertText"` and data `"a"`, followed by
`beforeinput` and `input` with `inputType == "deleteContentBackward"` and
`data == null`. It also requires no composition events, an empty final value,
a collapsed final selection at `[0, 0]`, and a compositor frame newer than the
Backspace down record. This proves one bounded physical insert-then-delete
path through Ozone/Aura/Blink; it does not make the key ABI a text-injection or
generic-editing interface.

The separate M4 selection smoke begins with a static `value="WASM"` native
text input. An external driver clicks the input and then sends one trusted
primary-mouse drag through the host canvas, Ozone, Aura, and Blink. It proves
the exact queued outer pointer sequence, trusted inner mouse/pointer delivery,
a noncollapsed trusted selection event, unchanged input value, selection
`[0, 4]`, selected text `"WASM"`, and a `none` or `forward` native selection
direction (Chrome reports `none` for this mouse gesture), with no composition
or text-input events and a compositor frame newer than the drag release. It
also requires the initial activation click to leave Blink's native selection
collapsed. It does not expose a script-driven selection API or general
selection semantics.

The separate M4 primary-selection paste smoke starts with the same native
source selection and then sends a trusted middle-button click to a second,
initially empty Blink text input. Wasm selects Unix editing behavior explicitly
without declaring itself POSIX, because Blink's Mac fallback disables global
selection. The middle-button release therefore takes Blink's ordinary
`PasteGlobalSelection` command, which reads the process-local
`ClipboardBuffer::kSelection` data written by Aura after the source drag. The
test requires native trusted `paste`, `beforeinput`, and `input` events with
`insertFromPaste`, an unchanged source value, a target value of `"WASM"`, and
a post-paste compositor frame. It does not call `navigator.clipboard`, use a
host text command, or claim system-clipboard integration.

The separate M4 Ctrl copy/paste smoke uses one native source input containing
`"COPY"`, selects it through a trusted primary drag, and sends raw physical
`ControlLeft`+`KeyC` records. It then replaces the primary selection with a
trusted drag over a second native input containing `"DECOY"`. A trusted middle
click later pastes `"DECOY"` into a separate blank verification input through
Blink's normal `PasteGlobalSelection` route. Before that final verification,
the smoke focuses a third blank input through the canvas and sends raw
`ControlLeft`+`KeyV` records; it receives `"COPY"` after the primary selection
has already been overwritten. Those two native paste results prove that the
process-local standard `ClipboardBuffer::kCopyPaste` buffer is distinct from
the overwritten `ClipboardBuffer::kSelection` primary buffer. Before the
accepted chord, the smoke also sends an unmodified raw `KeyC` pair and requires
the host to reject it without Blink delivery. The proof requires exact outer
pointer and key traces, exact trusted inner key traces, no text payload,
clipboard API, or DOM command, no source/decoy mutation, and post-paste
compositor frames. It does not provide system-clipboard integration or the
asynchronous, permission-gated host clipboard bridge.

The separate M4 native context-menu smoke uses a real native Blink input
selection for `"MENU"`, then sends a trusted secondary click through the host
canvas, Ozone, Aura, and Content. Content Shell creates one `WINDOW_TYPE_MENU`
Aura child on the existing compositor root—never a second platform window—and
keeps the renderer focused so the bounded Copy command calls
`WebContents::Copy()` for that selection. The host locates the resulting opaque
Copy row only in compositor pixels and sends a scan-derived primary click to
the menu. It then activates a second real text input and sends raw
`ControlLeft`+`KeyV`; the proof requires trusted native `contextmenu`, `copy`,
`paste`, `beforeinput`, and `input` events, exact outer pointer/key traces,
menu disappearance, a pasted value of `"MENU"`, and newer compositor frames.
It does not call Clipboard APIs, DOM clipboard commands, programmatic
selection, or an outer-page menu replacement.

The separate M4 native title-tooltip smoke sends exactly four unpressed,
trusted mouse moves through the existing pointer ABI. It first sends a rapid
move to a real Blink element whose `title` is `"WASM TOOLTIP"` and then to a
distant title-less element within 250 ms; the native pixels must remain absent
for 750 ms, longer than the hover delay. It then moves to a distinct Blink
title and anchor to prove the normal show path, followed by a final title-less
move to prove removal. Content Shell's
root-owned `wm::TooltipClient` receives Blink's normal Aura tooltip property
and, after its native 500 ms hover timer, creates one non-hit-testable
`WINDOW_TYPE_TOOLTIP` child in the existing compositor root. It never creates
a second platform window, a Views bubble, or a host-page DOM overlay. The smoke
scans only compositor pixels and requires the exact 110×24 opaque native
overlay at the pointer-relative `(+12,+18)` anchor, including its background,
border, and fixed bitmap title mask. Keyboard tooltips, rich typography, custom
tooltip content, Chrome/Views bubbles, and generic transient-surface behavior
remain outside this bounded first route.

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

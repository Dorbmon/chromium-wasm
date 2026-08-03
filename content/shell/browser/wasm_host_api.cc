// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/shell/browser/wasm_host_api.h"

#include <stddef.h>
#include <stdint.h>

#include <cstring>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/logging.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "base/values.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/render_widget_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/common/isolated_world_ids.h"
#include "content/shell/browser/shell.h"
#include "emscripten/emscripten.h"
#include "emscripten/heap.h"
#include "third_party/blink/public/common/input/web_mouse_event.h"
#include "ui/aura/client/focus_client.h"
#include "ui/aura/window.h"
#include "ui/aura/window_tree_host.h"
#include "ui/aura/window_tree_host_platform.h"
#include "ui/events/event_constants.h"
#include "ui/events/event_utils.h"
#include "ui/events/keycodes/dom/keycode_converter.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"
#include "ui/gfx/geometry/vector2d.h"
#include "ui/ozone/public/ozone_platform.h"
#include "ui/ozone/public/system_input_injector.h"
#include "ui/ozone/platform/wasm/wasm_input_method.h"
#include "ui/ozone/platform/wasm/wasm_screen.h"
#include "ui/platform_window/platform_window.h"
#include "url/gurl.h"
#include "url/url_constants.h"

namespace content {

namespace {

constexpr int kMaximumCanvasDimension = 16384;
// Account for both the Skia raster backing and the unpremultiplied RGBA
// presentation copy. This leaves at least 1.875 GiB of the configured 2 GiB
// linear-memory ceiling to Content, V8, and browser services.
constexpr int64_t kMaximumCanvasStorageBytes = 128 * 1024 * 1024;
constexpr size_t kMaximumDataUrlBytes = 8 * 1024 * 1024;
constexpr size_t kMaximumM4TextInputUtf16Units = 64 * 1024;
constexpr size_t kMaximumM4TextInputUtf8Bytes =
    kMaximumM4TextInputUtf16Units * 3;
// This remains a bounded physical-key ABI. Backspace and the explicit
// Ctrl+C/Ctrl+V chord are editing experiments, not a generic keyboard or
// text-insertion path.
constexpr std::string_view kM4NavigationDomCode = "ArrowDown";
constexpr std::string_view kM4PrintableDomCode = "KeyA";
constexpr std::string_view kM4BackspaceDomCode = "Backspace";
constexpr std::string_view kM4ControlLeftDomCode = "ControlLeft";
constexpr std::string_view kM4CopyDomCode = "KeyC";
constexpr std::string_view kM4PasteDomCode = "KeyV";
constexpr size_t kMaximumM4DomCodeLength = kM4ControlLeftDomCode.size();

bool IsSupportedM4DomCode(ui::DomCode dom_code) {
  return dom_code == ui::DomCode::ARROW_DOWN ||
         dom_code == ui::DomCode::US_A ||
         dom_code == ui::DomCode::BACKSPACE ||
         dom_code == ui::DomCode::CONTROL_LEFT ||
         dom_code == ui::DomCode::US_C || dom_code == ui::DomCode::US_V;
}

enum class DomPointerEventType {
  kMove = 0,
  kDown = 1,
  kUp = 2,
};

extern "C" int chromium_wasm_report_readiness(
    int shell_ready,
    int surface_ready,
    int first_visually_nonempty_paint);
extern "C" int chromium_wasm_report_navigation();
extern "C" int chromium_wasm_report_page_probe(const char* probe);
extern "C" int chromium_wasm_report_fatal(const char* message);
extern "C" int chromium_wasm_report_ozone_text_input_delivery(
    int action,
    int session_id,
    int sequence,
    int accepted);

void ReportFatal(std::string_view message) {
  const std::string terminated_message(message);
  if (chromium_wasm_report_fatal(terminated_message.c_str()) != 1) {
    LOG(ERROR) << "Unable to deliver M3 host failure: " << message;
  }
}

void ReportTextInputDelivery(const ui::WasmTextInputRecord& record,
                             bool accepted) {
  if (chromium_wasm_report_ozone_text_input_delivery(
          static_cast<int>(record.action), record.session_id, record.sequence,
          accepted ? 1 : 0) != 1) {
    ReportFatal("host rejected M4 Ozone text-input delivery report");
  }
}

std::optional<ui::WasmTextInputAction> ParseWasmTextInputAction(int action) {
  switch (action) {
    case static_cast<int>(ui::WasmTextInputAction::kSetComposition):
      return ui::WasmTextInputAction::kSetComposition;
    case static_cast<int>(ui::WasmTextInputAction::kConfirmComposition):
      return ui::WasmTextInputAction::kConfirmComposition;
    case static_cast<int>(ui::WasmTextInputAction::kClearComposition):
      return ui::WasmTextInputAction::kClearComposition;
  }
  return std::nullopt;
}

bool CopyM4TextInputRecord(int action,
                           int session_id,
                           int sequence,
                           const uint8_t* text_utf8,
                           int text_utf8_bytes,
                           int selection_start,
                           int selection_end,
                           ui::WasmTextInputRecord* record) {
  CHECK(record);
  const std::optional<ui::WasmTextInputAction> parsed_action =
      ParseWasmTextInputAction(action);
  if (!parsed_action || session_id <= 0 || sequence <= 0 ||
      text_utf8_bytes < 0 || selection_start < 0 ||
      selection_end < selection_start) {
    return false;
  }

  const size_t text_bytes = static_cast<size_t>(text_utf8_bytes);
  if (text_bytes > kMaximumM4TextInputUtf8Bytes) {
    return false;
  }
  if (text_bytes != 0) {
    if (!text_utf8) {
      return false;
    }
    const uintptr_t start = reinterpret_cast<uintptr_t>(text_utf8);
    const size_t heap_size = emscripten_get_heap_size();
    if (start > heap_size || text_bytes > heap_size - start) {
      return false;
    }
  }

  std::string utf8;
  if (text_bytes != 0) {
    utf8.assign(reinterpret_cast<const char*>(text_utf8), text_bytes);
  }
  if (!base::IsStringUTF8AllowingNoncharacters(utf8)) {
    return false;
  }
  std::u16string text = base::UTF8ToUTF16(utf8);
  if (text.size() > kMaximumM4TextInputUtf16Units) {
    return false;
  }

  const size_t start = static_cast<size_t>(selection_start);
  const size_t end = static_cast<size_t>(selection_end);
  switch (*parsed_action) {
    case ui::WasmTextInputAction::kSetComposition:
      // RenderWidgetHostViewAura currently honors composition.selection.end()
      // but not selection.start(). Keep this first route intentionally
      // collapsed at the candidate end rather than silently losing a range.
      if (text.empty() || start != end || end != text.size()) {
        return false;
      }
      break;
    case ui::WasmTextInputAction::kConfirmComposition:
    case ui::WasmTextInputAction::kClearComposition:
      if (!text.empty() || start != 0 || end != 0) {
        return false;
      }
      break;
  }

  *record = {*parsed_action, static_cast<uint32_t>(session_id),
             static_cast<uint32_t>(sequence), std::move(text),
             gfx::Range(start, end)};
  return true;
}

class WasmHostObserver final : public WebContentsObserver {
 public:
  explicit WasmHostObserver(WebContents* web_contents)
      : WebContentsObserver(web_contents) {}

  WasmHostObserver(const WasmHostObserver&) = delete;
  WasmHostObserver& operator=(const WasmHostObserver&) = delete;

  ~WasmHostObserver() override = default;

  void DidStartNavigation(NavigationHandle* navigation_handle) override {
    if (!navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument()) {
      return;
    }

    probe_timer_.Stop();
    probe_in_flight_ = false;
    weak_ptr_factory_.InvalidateWeakPtrs();
    ++navigation_generation_;
  }

  void DidFinishNavigation(NavigationHandle* navigation_handle) override {
    if (!navigation_handle->IsInPrimaryMainFrame() ||
        !navigation_handle->HasCommitted() ||
        navigation_handle->IsSameDocument()) {
      return;
    }

    if (!navigation_handle->GetURL().SchemeIs(url::kDataScheme)) {
      return;
    }

    if (chromium_wasm_report_navigation() != 1) {
      ReportFatal("host rejected the committed data navigation report");
    }
  }

  void DocumentOnLoadCompletedInPrimaryMainFrame() override {
    if (!web_contents()->GetLastCommittedURL().SchemeIs(url::kDataScheme)) {
      return;
    }
    ProbePage();
    probe_timer_.Start(FROM_HERE, base::Milliseconds(100), this,
                       &WasmHostObserver::ProbePage);
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!web_contents()->GetLastCommittedURL().SchemeIs(url::kDataScheme)) {
      return;
    }
    if (chromium_wasm_report_readiness(
            /*shell_ready=*/-1, /*surface_ready=*/-1,
            /*first_visually_nonempty_paint=*/1) != 1) {
      ReportFatal("host rejected the first visually nonempty paint report");
    }
  }

  void WebContentsDestroyed() override {
    probe_timer_.Stop();
    probe_in_flight_ = false;
    weak_ptr_factory_.InvalidateWeakPtrs();
    Observe(nullptr);
  }

 private:
  void ProbePage() {
    if (probe_in_flight_ || !web_contents()) {
      return;
    }
    RenderFrameHost* frame = web_contents()->GetPrimaryMainFrame();
    if (!frame || !frame->IsRenderFrameLive()) {
      return;
    }

    probe_in_flight_ = true;
    frame->ExecuteJavaScriptForTests(
        u"window.__chromiumWasmM4Probe ? "
        u"window.__chromiumWasmM4Probe() : "
        u"(window.__chromiumWasmM3Probe ? "
        u"window.__chromiumWasmM3Probe() : '')",
        base::BindOnce(&WasmHostObserver::OnPageProbe,
                       weak_ptr_factory_.GetWeakPtr(),
                       navigation_generation_),
        ISOLATED_WORLD_ID_GLOBAL);
  }

  void OnPageProbe(uint64_t navigation_generation, base::Value result) {
    if (navigation_generation != navigation_generation_) {
      return;
    }
    probe_in_flight_ = false;
    if (!result.is_string() || result.GetString().empty()) {
      return;
    }
    if (chromium_wasm_report_page_probe(result.GetString().c_str()) != 1) {
      ReportFatal("host rejected the deterministic page probe");
      probe_timer_.Stop();
    }
  }

  bool probe_in_flight_ = false;
  uint64_t navigation_generation_ = 0;
  base::RepeatingTimer probe_timer_;
  base::WeakPtrFactory<WasmHostObserver> weak_ptr_factory_{this};
};

class WasmHostState {
 public:
  WasmHostState() = default;

  WasmHostState(const WasmHostState&) = delete;
  WasmHostState& operator=(const WasmHostState&) = delete;

  scoped_refptr<base::SingleThreadTaskRunner> GetTaskRunner() {
    base::AutoLock lock(lock_);
    return task_runner_;
  }

  void SetTaskRunner(
      scoped_refptr<base::SingleThreadTaskRunner> task_runner) {
    base::AutoLock lock(lock_);
    task_runner_ = std::move(task_runner);
    m4_control_left_down_ = false;
    m4_copy_down_ = false;
    m4_paste_down_ = false;
  }

  bool PostM4KeyCommand(ui::DomCode physical_key,
                        bool down,
                        base::OnceClosure command) {
    base::AutoLock lock(lock_);
    // Track successfully posted chord transitions at the ABI boundary. This
    // keeps a direct caller from receiving queue success for a KeyC/KeyV
    // record that the Ozone injector would otherwise drop as unpaired.
    if (!IsM4KeyTransitionAllowedLocked(physical_key, down) ||
        !task_runner_ ||
        !task_runner_->PostTask(FROM_HERE, std::move(command))) {
      return false;
    }
    RecordM4KeyTransitionLocked(physical_key, down);
    return true;
  }

  void SetViewportSizeOnUiThread(const gfx::Size& viewport_size) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    CHECK(!viewport_size.IsEmpty());
    viewport_size_ = viewport_size;
  }

  bool ContainsViewportPointOnUiThread(const gfx::Point& point) const {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    return gfx::Rect(viewport_size_).Contains(point);
  }

  void SetInputInjector(
      std::unique_ptr<ui::SystemInputInjector> input_injector) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    input_injector_ = std::move(input_injector);
  }

  ui::SystemInputInjector* GetInputInjectorOnUiThread() {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    return input_injector_.get();
  }

  std::unique_ptr<WasmHostObserver> observer;

 private:
  bool IsM4KeyTransitionAllowedLocked(ui::DomCode physical_key,
                                      bool down) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (physical_key == ui::DomCode::CONTROL_LEFT) {
      return m4_control_left_down_ != down;
    }
    if (physical_key != ui::DomCode::US_C &&
        physical_key != ui::DomCode::US_V) {
      return true;
    }
    const bool key_down = physical_key == ui::DomCode::US_C
                              ? m4_copy_down_
                              : m4_paste_down_;
    return key_down != down && (!down || m4_control_left_down_);
  }

  void RecordM4KeyTransitionLocked(ui::DomCode physical_key, bool down)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (physical_key == ui::DomCode::CONTROL_LEFT) {
      m4_control_left_down_ = down;
    } else if (physical_key == ui::DomCode::US_C) {
      m4_copy_down_ = down;
    } else if (physical_key == ui::DomCode::US_V) {
      m4_paste_down_ = down;
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_
      GUARDED_BY(lock_);
  bool m4_control_left_down_ GUARDED_BY(lock_) = false;
  bool m4_copy_down_ GUARDED_BY(lock_) = false;
  bool m4_paste_down_ GUARDED_BY(lock_) = false;
  std::unique_ptr<ui::SystemInputInjector> input_injector_;
  gfx::Size viewport_size_;
};

WasmHostState& GetWasmHostState() {
  static base::NoDestructor<WasmHostState> state;
  return *state;
}

bool PostHostCommand(base::OnceClosure command) {
  scoped_refptr<base::SingleThreadTaskRunner> task_runner =
      GetWasmHostState().GetTaskRunner();
  return task_runner && task_runner->PostTask(FROM_HERE, std::move(command));
}

Shell* GetSingleShell() {
  if (Shell::windows().size() != 1u) {
    ReportFatal("M3 host command requires exactly one Content Shell window");
    return nullptr;
  }
  return Shell::windows().front();
}

void ResizeOnUiThread(const gfx::Size& size) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (!shell) {
    return;
  }

  // Updating DisplayList notifies Aura synchronously. Do not retain the
  // Content Shell or Aura pointers across it.
  if (!ui::WasmScreen::UpdatePrimaryDisplayForHostResize(size)) {
    ReportFatal("M4 host resize has no live ozone_wasm screen");
    return;
  }

  shell = GetSingleShell();
  if (!shell) {
    return;
  }
  aura::Window* window = shell->window();
  if (!window || !window->GetHost()) {
    ReportFatal("M3 Content Shell has no Aura host window");
    return;
  }
  window->GetHost()->SetBoundsInPixels(gfx::Rect(size));

  // Bounds observers may synchronously destroy the Aura host or its Shell.
  // Reacquire the sole shell before continuing the resize transaction.
  shell = GetSingleShell();
  if (!shell) {
    return;
  }
  shell->ResizeWebContentForTests(size);
  GetWasmHostState().SetViewportSizeOnUiThread(size);
}

void ClickOnUiThread(const gfx::Point& location) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  if (!GetWasmHostState().ContainsViewportPointOnUiThread(location)) {
    ReportFatal("M3 host click is outside the accepted viewport");
    return;
  }

  Shell* shell = GetSingleShell();
  if (!shell) {
    return;
  }

  WebContents* web_contents = shell->web_contents();
  RenderFrameHost* frame = web_contents->GetPrimaryMainFrame();
  RenderWidgetHost* widget = frame ? frame->GetRenderWidgetHost() : nullptr;
  if (!widget || !frame->IsRenderFrameLive()) {
    ReportFatal("M3 Content Shell has no live renderer for host input");
    return;
  }

  web_contents->Focus();
  const gfx::PointF position(location);
  blink::WebMouseEvent mouse_down(
      blink::WebInputEvent::Type::kMouseDown, position, position,
      blink::WebMouseEvent::Button::kLeft, /*click_count=*/1,
      blink::WebInputEvent::kNoModifiers, ui::EventTimeForNow());
  mouse_down.UpdateEventModifiersToMatchButton();
  widget->ForwardMouseEvent(mouse_down);

  blink::WebMouseEvent mouse_up(
      blink::WebInputEvent::Type::kMouseUp, position, position,
      blink::WebMouseEvent::Button::kLeft, /*click_count=*/1,
      blink::WebInputEvent::kNoModifiers, ui::EventTimeForNow());
  mouse_up.UpdateEventModifiersToMatchButton();
  widget->ForwardMouseEvent(mouse_up);
}

void DispatchDomPointerOnUiThread(DomPointerEventType type,
                                  const gfx::Point& location,
                                  ui::EventFlags button) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  WasmHostState& state = GetWasmHostState();
  if (!state.ContainsViewportPointOnUiThread(location)) {
    ReportFatal("M4 host pointer event is outside the accepted viewport");
    return;
  }

  if (type == DomPointerEventType::kDown) {
    Shell* shell = GetSingleShell();
    if (!shell) {
      return;
    }
    // The host canvas owns DOM focus. Give the in-process WebContents its
    // normal browser focus before Aura dispatches the trusted pointer press.
    shell->web_contents()->Focus();
  }

  ui::SystemInputInjector* input_injector =
      state.GetInputInjectorOnUiThread();
  if (!input_injector) {
    ReportFatal("M4 host pointer event has no Ozone input injector");
    return;
  }

  input_injector->MoveCursorTo(gfx::PointF(location));
  switch (type) {
    case DomPointerEventType::kMove:
      return;
    case DomPointerEventType::kDown:
      input_injector->InjectMouseButton(button, /*down=*/true);
      return;
    case DomPointerEventType::kUp:
      input_injector->InjectMouseButton(button, /*down=*/false);
      return;
  }
  NOTREACHED();
}

void DispatchDomWheelOnUiThread(const gfx::Point& location,
                                const gfx::Vector2d& dom_delta) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  WasmHostState& state = GetWasmHostState();
  if (!state.ContainsViewportPointOnUiThread(location)) {
    ReportFatal("M4 host wheel event is outside the accepted viewport");
    return;
  }

  ui::SystemInputInjector* input_injector =
      state.GetInputInjectorOnUiThread();
  if (!input_injector) {
    ReportFatal("M4 host wheel event has no Ozone input injector");
    return;
  }

  input_injector->MoveCursorTo(gfx::PointF(location));
  // DOM WheelEvent deltas are positive for right/down. Chromium wheel offsets
  // are positive for left/up, so convert at the host ABI boundary exactly once.
  input_injector->InjectMouseWheel(-dom_delta.x(), -dom_delta.y());
}

void DispatchDomKeyOnUiThread(ui::DomCode physical_key, bool down) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  ui::SystemInputInjector* input_injector =
      GetWasmHostState().GetInputInjectorOnUiThread();
  if (!input_injector) {
    ReportFatal("M4 host raw key event has no Ozone input injector");
    return;
  }

  // The host accepts only an explicit trusted DOM keydown/keyup pair. The
  // Wasm injector does not synthesize repeats between those records.
  input_injector->InjectKeyEvent(physical_key, down,
                                 /*suppress_auto_repeat=*/true);
}

void DispatchM4TextInputOnUiThread(ui::WasmTextInputRecord record) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportTextInputDelivery(record, /*accepted=*/false);
    return;
  }

  aura::WindowTreeHostPlatform* host =
      aura::WindowTreeHostPlatform::GetHostForWindow(shell->window());
  if (!host) {
    ReportTextInputDelivery(record, /*accepted=*/false);
    return;
  }

  // The platform-specific registry resolves only this Aura/Ozone widget's
  // InputMethod. Generic SystemInputInjector is intentionally reserved for
  // native pointer, wheel, and physical-key events.
  const bool accepted = ui::DispatchWasmTextInput(host->GetAcceleratedWidget(),
                                                  record);
  ReportTextInputDelivery(record, accepted);
}

void LoadUrlOnUiThread(GURL url) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (shell) {
    shell->LoadURL(url);
  }
}

void DeactivateHostWindowOnUiThread() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportFatal("M4 host focus loss has no Content Shell window");
    return;
  }

  aura::Window* root_window = shell->window();
  aura::client::FocusClient* focus_client =
      aura::client::GetFocusClient(root_window);
  aura::WindowTreeHostPlatform* host =
      aura::WindowTreeHostPlatform::GetHostForWindow(root_window);
  if (!focus_client || !host || !host->platform_window()) {
    ReportFatal("M4 host focus loss has no Aura/Ozone window path");
    return;
  }

  // Clear any active Wasm composition before focus/activation callbacks can
  // detach its TextInputClient. The opaque Ozone boundary keeps Content Shell
  // independent of the concrete Wasm PlatformWindow implementation.
  ui::CancelWasmTextInputForWidget(host->GetAcceleratedWidget());

  // Composition cancellation can synchronously close the Content Shell
  // window. Do not retain Aura or PlatformWindow pointers across it.
  shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportFatal("M4 host composition cancellation closed Content Shell");
    return;
  }
  root_window = shell->window();
  focus_client = aura::client::GetFocusClient(root_window);
  host = aura::WindowTreeHostPlatform::GetHostForWindow(root_window);
  if (!focus_client || !host || !host->platform_window()) {
    ReportFatal("M4 host focus loss has no surviving Aura/Ozone window path");
    return;
  }

  // Dropping the Aura focus target reaches the regular renderer focus-loss
  // path. Deactivating the generic PlatformWindow separately clears
  // ozone_wasm's keyboard target without exposing a Wasm implementation type
  // to Content Shell.
  focus_client->FocusWindow(nullptr);

  // Focus notifications can synchronously close the Content Shell window.
  // Do not retain the old Aura or PlatformWindow pointers across them.
  shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportFatal("M4 host focus loss closed the Content Shell window");
    return;
  }
  root_window = shell->window();
  host = aura::WindowTreeHostPlatform::GetHostForWindow(root_window);
  if (!host || !host->platform_window()) {
    ReportFatal("M4 host focus loss has no surviving Aura/Ozone window path");
    return;
  }
  host->platform_window()->Deactivate();
}

void ShutdownOnUiThread() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell::Shutdown();
}

}  // namespace

void InitializeWasmHostApi() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  CHECK(shell);

  WasmHostState& state = GetWasmHostState();
  aura::Window* window = shell->window();
  CHECK(window);
  CHECK(window->GetHost());
  state.SetViewportSizeOnUiThread(
      window->GetHost()->GetBoundsInPixels().size());
  state.SetTaskRunner(base::SingleThreadTaskRunner::GetCurrentDefault());
  std::unique_ptr<ui::SystemInputInjector> input_injector =
      ui::OzonePlatform::GetInstance()->CreateSystemInputInjector();
  if (!input_injector) {
    ReportFatal("ozone_wasm did not create the M4 input injector");
    return;
  }
  state.SetInputInjector(std::move(input_injector));
  state.observer = std::make_unique<WasmHostObserver>(shell->web_contents());
  if (chromium_wasm_report_readiness(
          /*shell_ready=*/1, /*surface_ready=*/-1,
          /*first_visually_nonempty_paint=*/-1) != 1) {
    ReportFatal("host rejected the Content Shell readiness report");
  }
}

void ShutdownWasmHostApi() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  WasmHostState& state = GetWasmHostState();
  state.observer.reset();
  state.SetInputInjector(nullptr);
  state.SetTaskRunner(nullptr);
}

}  // namespace content

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_resize(
    int width,
    int height,
    double device_pixel_ratio) {
  if (width <= 0 || width > content::kMaximumCanvasDimension || height <= 0 ||
      height > content::kMaximumCanvasDimension ||
      device_pixel_ratio != 1.0) {
    return 0;
  }
  const int64_t canvas_bytes =
      static_cast<int64_t>(width) * static_cast<int64_t>(height) * 4;
  if (canvas_bytes * 2 > content::kMaximumCanvasStorageBytes) {
    return 0;
  }
  return content::PostHostCommand(base::BindOnce(
             &content::ResizeOnUiThread, gfx::Size(width, height)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_click(int x,
                                                  int y,
                                                  int button) {
  if (button != 0 || x < 0 || y < 0) {
    return 0;
  }
  return content::PostHostCommand(
             base::BindOnce(&content::ClickOnUiThread, gfx::Point(x, y)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_pointer(int type,
                                                    int x,
                                                    int y,
                                                    int button) {
  if (type < static_cast<int>(content::DomPointerEventType::kMove) ||
      type > static_cast<int>(content::DomPointerEventType::kUp) ||
      (button != 0 && button != 1) || x < 0 || y < 0) {
    return 0;
  }
  const ui::EventFlags mouse_button =
      button == 0 ? ui::EF_LEFT_MOUSE_BUTTON : ui::EF_MIDDLE_MOUSE_BUTTON;
  const auto event_type = static_cast<content::DomPointerEventType>(type);
  return content::PostHostCommand(base::BindOnce(
             &content::DispatchDomPointerOnUiThread, event_type,
             gfx::Point(x, y), mouse_button))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_wheel(int x,
                                                  int y,
                                                  int delta_x,
                                                  int delta_y) {
  if (x < 0 || y < 0 || (delta_x == 0 && delta_y == 0) ||
      delta_x == std::numeric_limits<int>::min() ||
      delta_y == std::numeric_limits<int>::min()) {
    return 0;
  }
  return content::PostHostCommand(base::BindOnce(
             &content::DispatchDomWheelOnUiThread, gfx::Point(x, y),
             gfx::Vector2d(delta_x, delta_y)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_key(const char* code, int down) {
  if (!code || (down != 0 && down != 1)) {
    return 0;
  }
  const size_t length =
      strnlen(code, content::kMaximumM4DomCodeLength + 1);
  const std::string_view code_string(code, length);
  if (code_string != content::kM4NavigationDomCode &&
      code_string != content::kM4PrintableDomCode &&
      code_string != content::kM4BackspaceDomCode &&
      code_string != content::kM4ControlLeftDomCode &&
      code_string != content::kM4CopyDomCode &&
      code_string != content::kM4PasteDomCode) {
    return 0;
  }
  const ui::DomCode physical_key =
      ui::KeycodeConverter::CodeStringToDomCode(code_string);
  if (!content::IsSupportedM4DomCode(physical_key)) {
    return 0;
  }
  return content::GetWasmHostState().PostM4KeyCommand(
             physical_key, down == 1,
             base::BindOnce(&content::DispatchDomKeyOnUiThread, physical_key,
                            down == 1))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url(const char* data_url) {
  if (!data_url) {
    return 0;
  }
  const size_t length = strnlen(data_url, content::kMaximumDataUrlBytes + 1);
  if (length == 0 || length > content::kMaximumDataUrlBytes) {
    return 0;
  }
  GURL url(std::string(data_url, length));
  if (!url.is_valid() || !url.SchemeIs(url::kDataScheme)) {
    return 0;
  }
  return content::PostHostCommand(
             base::BindOnce(&content::LoadUrlOnUiThread, std::move(url)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_text_input(
    int action,
    int session_id,
    int sequence,
    const uint8_t* text_utf8,
    int text_utf8_bytes,
    int selection_start,
    int selection_end) {
  ui::WasmTextInputRecord record;
  if (!content::CopyM4TextInputRecord(
          action, session_id, sequence, text_utf8, text_utf8_bytes,
          selection_start, selection_end, &record)) {
    return 0;
  }
  // |record| owns its UTF-16 copy before this task hops off the proxying host
  // call. It never retains a JavaScript heap view or a Wasm pointer.
  return content::PostHostCommand(base::BindOnce(
             &content::DispatchM4TextInputOnUiThread, std::move(record)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_deactivate() {
  return content::PostHostCommand(
             base::BindOnce(&content::DeactivateHostWindowOnUiThread))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_shutdown() {
  return content::PostHostCommand(
             base::BindOnce(&content::ShutdownOnUiThread))
             ? 1
             : 0;
}

}  // extern "C"

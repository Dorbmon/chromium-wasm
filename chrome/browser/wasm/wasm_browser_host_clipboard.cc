// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_clipboard.h"

#include <stddef.h>
#include <stdint.h>

#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "emscripten/emscripten.h"
#include "emscripten/heap.h"
#include "ui/base/clipboard/scoped_clipboard_writer.h"
#include "ui/events/keycodes/dom/dom_code.h"
#include "ui/ozone/platform/wasm/wasm_input_method.h"
#include "ui/ozone/public/ozone_platform.h"
#include "ui/ozone/public/system_input_injector.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_host_clipboard.cc must only be built for WebAssembly"
#endif

extern "C" int chromium_wasm_report_ozone_browser_clipboard_paste_delivery(
    int request_id,
    int accepted);

namespace chrome {

namespace {

// This capability deliberately accepts only one ordinary text/plain paste at
// a time. The host copies the data before this bridge queues work, so neither
// a JavaScript string nor a Wasm-memory view can outlive the synchronous ABI.
constexpr size_t kMaximumHostClipboardUtf8Bytes = 192 * 1024;
constexpr size_t kMaximumHostClipboardUtf16Units = 64 * 1024;

bool ValidateWasmBrowserHostClipboardPaste(const uint8_t* text_utf8,
                                           int text_utf8_bytes,
                                           int request_id,
                                           size_t* text_bytes) {
  CHECK(text_bytes);
  if (!text_utf8 || text_utf8_bytes <= 0 || request_id <= 0) {
    return false;
  }

  const size_t bytes = static_cast<size_t>(text_utf8_bytes);
  if (bytes > kMaximumHostClipboardUtf8Bytes) {
    return false;
  }
  const uintptr_t start = reinterpret_cast<uintptr_t>(text_utf8);
  const size_t heap_size = emscripten_get_heap_size();
  if (start > heap_size || bytes > heap_size - start) {
    return false;
  }
  *text_bytes = bytes;
  return true;
}

bool CopyWasmBrowserHostClipboardPaste(const uint8_t* text_utf8,
                                       int text_utf8_bytes,
                                       int request_id,
                                       std::u16string* text) {
  CHECK(text);
  size_t text_bytes = 0;
  if (!ValidateWasmBrowserHostClipboardPaste(
          text_utf8, text_utf8_bytes, request_id, &text_bytes)) {
    return false;
  }

  std::string utf8(reinterpret_cast<const char*>(text_utf8), text_bytes);
  if (!base::IsStringUTF8AllowingNoncharacters(utf8)) {
    return false;
  }
  std::u16string converted = base::UTF8ToUTF16(utf8);
  if (converted.empty() || converted.size() > kMaximumHostClipboardUtf16Units) {
    return false;
  }
  *text = std::move(converted);
  return true;
}

void ReportWasmBrowserHostClipboardPasteDelivery(int request_id,
                                                 bool accepted) {
  // The fixed opaque request ID is registered by the trusted-DOM adapter
  // before it enters the C ABI. Do not report text, a focus token, a widget,
  // or Clipboard contents back to JavaScript.
  const int reported = chromium_wasm_report_ozone_browser_clipboard_paste_delivery(
      request_id, accepted ? 1 : 0);
  if (reported != 1) {
    LOG(ERROR) << "host rejected browser clipboard-paste delivery report";
  }
}

class WasmBrowserHostClipboardState {
 public:
  struct PasteAdmission {
    gfx::AcceleratedWidget target_widget;
    ui::WasmTextInputFocusToken focus_token;
    uint64_t generation;
    uint64_t target_generation;
    size_t text_utf8_bytes;
    int request_id;
  };

  struct PendingPasteRecord {
    PasteAdmission admission;
    std::u16string text;
  };

  WasmBrowserHostClipboardState() = default;
  WasmBrowserHostClipboardState(const WasmBrowserHostClipboardState&) = delete;
  WasmBrowserHostClipboardState& operator=(
      const WasmBrowserHostClipboardState&) = delete;
  ~WasmBrowserHostClipboardState() = default;

  bool InitializeOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    std::unique_ptr<ui::SystemInputInjector> input_injector =
        ui::OzonePlatform::GetInstance()->CreateSystemInputInjector();
    if (!input_injector) {
      return false;
    }
    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    if (!task_runner) {
      return false;
    }

    {
      base::AutoLock lock(lock_);
      if (accepting_host_clipboard_ || task_runner_ || permanently_shutdown_) {
        return false;
      }
      ++generation_;
      ++target_generation_;
      ever_initialized_ = true;
      accepting_host_clipboard_ = true;
      task_runner_ = std::move(task_runner);
      target_widget_ = gfx::kNullAcceleratedWidget;
      outstanding_paste_ = false;
      active_request_id_ = 0;
      active_paste_cancelled_ = false;
      paste_import_started_ = false;
      last_request_id_ = 0;
      pending_paste_.reset();
      dispatch_task_posted_ = false;
    }
    input_injector_ = std::move(input_injector);
    return true;
  }

  void ShutdownOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    std::optional<PendingPasteRecord> terminal_paste;
    {
      base::AutoLock lock(lock_);
      if (!ever_initialized_ || !accepting_host_clipboard_) {
        return;
      }
      ++generation_;
      ++target_generation_;
      accepting_host_clipboard_ = false;
      task_runner_ = nullptr;
      target_widget_ = gfx::kNullAcceleratedWidget;
      terminal_paste = TakeQueuedPasteLocked();
      outstanding_paste_ = false;
      active_request_id_ = 0;
      active_paste_cancelled_ = false;
      paste_import_started_ = false;
      dispatch_task_posted_ = false;
      permanently_shutdown_ = true;
    }
    if (terminal_paste) {
      ReportWasmBrowserHostClipboardPasteDelivery(
          terminal_paste->admission.request_id, /*accepted=*/false);
    }
    input_injector_.reset();
  }

  bool SetTargetOnUiThread(gfx::AcceleratedWidget widget) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    if (widget == gfx::kNullAcceleratedWidget) {
      return false;
    }
    base::AutoLock lock(lock_);
    if (!accepting_host_clipboard_ || !task_runner_ || outstanding_paste_) {
      return false;
    }
    ++target_generation_;
    target_widget_ = widget;
    return true;
  }

  void ClearTargetOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    std::optional<PendingPasteRecord> terminal_paste;
    {
      base::AutoLock lock(lock_);
      ++target_generation_;
      target_widget_ = gfx::kNullAcceleratedWidget;
      terminal_paste = TakeQueuedPasteLocked();
      if (terminal_paste) {
        outstanding_paste_ = false;
        active_request_id_ = 0;
        active_paste_cancelled_ = false;
        paste_import_started_ = false;
        dispatch_task_posted_ = false;
      }
    }
    if (terminal_paste) {
      ReportWasmBrowserHostClipboardPasteDelivery(
          terminal_paste->admission.request_id, /*accepted=*/false);
    }
  }

  std::optional<PasteAdmission> ReservePasteAdmission(size_t text_utf8_bytes,
                                                       int request_id) {
    base::AutoLock lock(lock_);
    if (!accepting_host_clipboard_ || !task_runner_ ||
        target_widget_ == gfx::kNullAcceleratedWidget || outstanding_paste_ ||
        text_utf8_bytes == 0 ||
        text_utf8_bytes > kMaximumHostClipboardUtf8Bytes || request_id <= 0 ||
        request_id <= last_request_id_) {
      return std::nullopt;
    }
    // Capture the current Ozone editable-client epoch before copying host
    // memory. A focus transition during the copy makes the reserved token
    // stale; dispatch will reject it rather than select a new target.
    const std::optional<ui::WasmTextInputFocusToken> focus_token =
        ui::CaptureWasmTextInputFocusToken(target_widget_);
    if (!focus_token) {
      return std::nullopt;
    }
    outstanding_paste_ = true;
    active_request_id_ = request_id;
    active_paste_cancelled_ = false;
    paste_import_started_ = false;
    last_request_id_ = request_id;
    return PasteAdmission{target_widget_, *focus_token, generation_,
                          target_generation_, text_utf8_bytes, request_id};
  }

  void CancelPasteAdmission(const PasteAdmission& admission) {
    base::AutoLock lock(lock_);
    if (generation_ == admission.generation && !pending_paste_) {
      CancelPasteAdmissionLocked(admission);
    }
  }

  bool PostReservedPaste(std::u16string text, const PasteAdmission& admission) {
    if (text.empty()) {
      CancelPasteAdmission(admission);
      return false;
    }

    base::AutoLock lock(lock_);
    if (!accepting_host_clipboard_ || !task_runner_ || !outstanding_paste_ ||
        pending_paste_ || active_request_id_ != admission.request_id ||
        active_paste_cancelled_ || paste_import_started_ ||
        target_widget_ != admission.target_widget ||
        generation_ != admission.generation ||
        target_generation_ != admission.target_generation) {
      CancelPasteAdmissionLocked(admission);
      return false;
    }

    pending_paste_.emplace(
        PendingPasteRecord{admission, std::move(text)});
    dispatch_task_posted_ = true;
    if (task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostClipboardState::DispatchPasteOnUiThread,
                base::Unretained(this)))) {
      return true;
    }
    pending_paste_.reset();
    dispatch_task_posted_ = false;
    CancelPasteAdmissionLocked(admission);
    return false;
  }

  bool CancelPendingPaste(int request_id) {
    std::optional<PendingPasteRecord> terminal_paste;
    {
      base::AutoLock lock(lock_);
      if (!accepting_host_clipboard_ || request_id <= 0 ||
          !outstanding_paste_ || active_request_id_ != request_id ||
          active_paste_cancelled_) {
        return false;
      }
      // This is the linearization boundary with DispatchPasteOnUiThread(). A
      // cancellation that arrives after BeginPasteImportAndChord() loses
      // cleanly: it must return false and must not claim it suppressed the
      // volatile import or the native chord.
      if (paste_import_started_) {
        return false;
      }
      // A proxy blur, document hide, or adapter teardown must make the exact
      // outstanding host gesture inert before its UI task can inject Ctrl+V.
      // A task already running outside the lock observes this flag before
      // injection and owns the matching terminal false report.
      active_paste_cancelled_ = true;
      terminal_paste = TakeQueuedPasteLocked();
      if (terminal_paste) {
        outstanding_paste_ = false;
        active_request_id_ = 0;
        active_paste_cancelled_ = false;
        paste_import_started_ = false;
        dispatch_task_posted_ = false;
      }
    }
    if (terminal_paste) {
      ReportWasmBrowserHostClipboardPasteDelivery(
          terminal_paste->admission.request_id, /*accepted=*/false);
    }
    return true;
  }

 private:
  std::optional<PendingPasteRecord> TakeQueuedPasteLocked()
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (!pending_paste_) {
      return std::nullopt;
    }
    std::optional<PendingPasteRecord> result = std::move(pending_paste_);
    pending_paste_.reset();
    return result;
  }

  void CancelPasteAdmissionLocked(const PasteAdmission& admission)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (generation_ == admission.generation &&
        active_request_id_ == admission.request_id) {
      outstanding_paste_ = false;
      active_request_id_ = 0;
      active_paste_cancelled_ = false;
      paste_import_started_ = false;
    }
  }

  bool IsCurrentTarget(gfx::AcceleratedWidget target_widget,
                       uint64_t generation,
                       uint64_t target_generation) const {
    base::AutoLock lock(lock_);
    return accepting_host_clipboard_ && generation == generation_ &&
           target_generation == target_generation_ &&
           target_widget == target_widget_ &&
           target_widget != gfx::kNullAcceleratedWidget;
  }

  bool IsCurrentPasteAdmission(const PasteAdmission& admission) const {
    base::AutoLock lock(lock_);
    return accepting_host_clipboard_ &&
           admission.generation == generation_ &&
           admission.target_generation == target_generation_ &&
           admission.target_widget == target_widget_ &&
           admission.target_widget != gfx::kNullAcceleratedWidget &&
           outstanding_paste_ &&
           active_request_id_ == admission.request_id &&
           !active_paste_cancelled_;
  }

  bool BeginPasteImportAndChord(const PasteAdmission& admission) {
    base::AutoLock lock(lock_);
    if (!accepting_host_clipboard_ ||
        admission.generation != generation_ ||
        admission.target_generation != target_generation_ ||
        admission.target_widget != target_widget_ ||
        admission.target_widget == gfx::kNullAcceleratedWidget ||
        !outstanding_paste_ || active_request_id_ != admission.request_id ||
        active_paste_cancelled_ || paste_import_started_) {
      return false;
    }
    // The exact cancellation boundary is before the irreversible clipboard
    // commit and first injector call, rather than between individual key
    // events. A caller that loses this transition receives false from its
    // cancel ABI and must await the ordinary terminal delivery report instead
    // of claiming suppression.
    paste_import_started_ = true;
    return true;
  }

  void DispatchPasteOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    std::optional<PendingPasteRecord> pending;
    {
      base::AutoLock lock(lock_);
      if (!dispatch_task_posted_ || !pending_paste_) {
        return;
      }
      pending.emplace(std::move(*pending_paste_));
      pending_paste_.reset();
    }

    bool accepted = false;
    const PasteAdmission& admission = pending->admission;
    if (IsCurrentTarget(admission.target_widget, admission.generation,
                        admission.target_generation) &&
        IsCurrentPasteAdmission(admission) &&
        ui::IsWasmTextInputFocusTokenCurrent(admission.target_widget,
                                              admission.focus_token) &&
        BeginPasteImportAndChord(admission)) {
      // This writes only a volatile, process-local copy/paste payload. The
      // writer's destructor commits before the native chord is considered;
      // no ClipboardNonBacked cast or replacement platform implementation is
      // needed (or permitted) here.
      {
        ui::ScopedClipboardWriter writer(ui::ClipboardBuffer::kCopyPaste);
        writer.WriteText(pending->text);
      }

      // Clipboard observers may synchronously change focus while the writer
      // commits. Revalidate the same opaque target and focus epoch before
      // injecting anything, so that race cannot paste into a replacement
      // client. A post-commit rejection leaves only the volatile import.
      if (IsCurrentTarget(admission.target_widget, admission.generation,
                          admission.target_generation) &&
          IsCurrentPasteAdmission(admission) &&
          ui::IsWasmTextInputFocusTokenCurrent(admission.target_widget,
                                                admission.focus_token) &&
          input_injector_) {
        // The bridge owns a complete key chord on its private injector. It
        // never consumes or reuses state from the host physical-key ABI.
        input_injector_->InjectKeyEvent(ui::DomCode::CONTROL_LEFT,
                                        /*down=*/true,
                                        /*suppress_auto_repeat=*/true);
        input_injector_->InjectKeyEvent(ui::DomCode::US_V, /*down=*/true,
                                        /*suppress_auto_repeat=*/true);
        input_injector_->InjectKeyEvent(ui::DomCode::US_V, /*down=*/false,
                                        /*suppress_auto_repeat=*/true);
        input_injector_->InjectKeyEvent(ui::DomCode::CONTROL_LEFT,
                                        /*down=*/false,
                                        /*suppress_auto_repeat=*/true);
        accepted = true;
      }
    }

    // This terminal acknowledgement means only that the copied import and
    // native chord were accepted. The smoke independently proves the actual
    // Textfield value, frame, and normal navigation before accepting success.
    ReportWasmBrowserHostClipboardPasteDelivery(admission.request_id, accepted);
    {
      base::AutoLock lock(lock_);
      if (generation_ == admission.generation &&
          active_request_id_ == admission.request_id) {
        outstanding_paste_ = false;
        active_request_id_ = 0;
        active_paste_cancelled_ = false;
        paste_import_started_ = false;
        dispatch_task_posted_ = false;
      }
    }
  }

  mutable base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_
      GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  uint64_t target_generation_ GUARDED_BY(lock_) = 0;
  bool accepting_host_clipboard_ GUARDED_BY(lock_) = false;
  bool ever_initialized_ GUARDED_BY(lock_) = false;
  bool permanently_shutdown_ GUARDED_BY(lock_) = false;
  gfx::AcceleratedWidget target_widget_ GUARDED_BY(lock_) =
      gfx::kNullAcceleratedWidget;
  bool outstanding_paste_ GUARDED_BY(lock_) = false;
  int active_request_id_ GUARDED_BY(lock_) = 0;
  bool active_paste_cancelled_ GUARDED_BY(lock_) = false;
  // Once true, cancellation lost the transaction before its irreversible
  // process-local clipboard write. It must return false rather than claim it
  // can still suppress the normal Ozone Ctrl+V chord.
  bool paste_import_started_ GUARDED_BY(lock_) = false;
  int last_request_id_ GUARDED_BY(lock_) = 0;
  std::optional<PendingPasteRecord> pending_paste_ GUARDED_BY(lock_);
  bool dispatch_task_posted_ GUARDED_BY(lock_) = false;
  std::unique_ptr<ui::SystemInputInjector> input_injector_;
};

WasmBrowserHostClipboardState& GetWasmBrowserHostClipboardState() {
  static base::NoDestructor<WasmBrowserHostClipboardState> state;
  return *state;
}

}  // namespace

bool InitializeWasmBrowserHostClipboard() {
  return GetWasmBrowserHostClipboardState().InitializeOnUiThread();
}

void ShutdownWasmBrowserHostClipboard() {
  GetWasmBrowserHostClipboardState().ShutdownOnUiThread();
}

bool SetWasmBrowserHostClipboardTarget(gfx::AcceleratedWidget widget) {
  return GetWasmBrowserHostClipboardState().SetTargetOnUiThread(widget);
}

void ClearWasmBrowserHostClipboardTarget() {
  GetWasmBrowserHostClipboardState().ClearTargetOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_clipboard_paste(
    const uint8_t* text_utf8,
    int text_utf8_bytes,
    int request_id) {
  size_t text_bytes = 0;
  if (!ValidateWasmBrowserHostClipboardPaste(text_utf8, text_utf8_bytes,
                                             request_id, &text_bytes)) {
    return 0;
  }

  WasmBrowserHostClipboardState& state = GetWasmBrowserHostClipboardState();
  const std::optional<WasmBrowserHostClipboardState::PasteAdmission> admission =
      state.ReservePasteAdmission(text_bytes, request_id);
  if (!admission) {
    return 0;
  }

  std::u16string text;
  if (!CopyWasmBrowserHostClipboardPaste(text_utf8, text_utf8_bytes,
                                         request_id, &text)) {
    state.CancelPasteAdmission(*admission);
    return 0;
  }
  return state.PostReservedPaste(std::move(text), *admission) ? 1 : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_clipboard_cancel(
    int request_id) {
  return GetWasmBrowserHostClipboardState().CancelPendingPaste(request_id)
             ? 1
             : 0;
}

}  // extern "C"

}  // namespace chrome

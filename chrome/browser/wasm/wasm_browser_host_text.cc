// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_text.h"

#include <stddef.h>
#include <stdint.h>

#include <deque>
#include <limits>
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
#include "ui/gfx/range/range.h"
#include "ui/ozone/platform/wasm/wasm_input_method.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_host_text.cc must only be built for WebAssembly"
#endif

extern "C" int chromium_wasm_report_ozone_browser_text_input_delivery(
    int action,
    int session_id,
    int sequence,
    int accepted);

namespace chrome {

namespace {

// Keep this materially below Wasm's linear-memory limits. The bridge copies
// before hopping to the UI sequence, so a host-supplied pointer never escapes
// the synchronous C ABI invocation.
constexpr size_t kMaximumHostTextUtf8Bytes = 192 * 1024;
constexpr size_t kMaximumHostTextUtf16Units = 64 * 1024;
// Each C ABI admission captures an exact Ozone focus token. Keep a small FIFO
// of those copied records so ordinary rapid physical typing is preserved
// without letting an untrusted host retain unbounded text in the bridge.
constexpr size_t kMaximumPendingHostTextRecords = 16;
constexpr size_t kMaximumPendingHostTextUtf8Bytes = 192 * 1024;
constexpr uint32_t kMaximumHostTextSequence =
    static_cast<uint32_t>(std::numeric_limits<int>::max());

bool ValidateWasmBrowserHostTextInput(const uint8_t* text_utf8,
                                      int text_utf8_bytes,
                                      size_t* text_bytes) {
  CHECK(text_bytes);
  if (!text_utf8 || text_utf8_bytes <= 0) {
    return false;
  }

  const size_t bytes = static_cast<size_t>(text_utf8_bytes);
  if (bytes > kMaximumHostTextUtf8Bytes) {
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

bool CopyWasmBrowserHostText(const uint8_t* text_utf8,
                             int text_utf8_bytes,
                             std::u16string* text) {
  CHECK(text);
  size_t text_bytes = 0;
  // Revalidate after focus-token reservation: memory can grow while the UI
  // sequence advances, and the copied host pointer must remain in bounds.
  if (!ValidateWasmBrowserHostTextInput(text_utf8, text_utf8_bytes,
                                        &text_bytes)) {
    return false;
  }

  std::string utf8(reinterpret_cast<const char*>(text_utf8), text_bytes);
  if (!base::IsStringUTF8AllowingNoncharacters(utf8)) {
    return false;
  }
  std::u16string converted = base::UTF8ToUTF16(utf8);
  if (converted.empty() || converted.size() > kMaximumHostTextUtf16Units) {
    return false;
  }
  *text = std::move(converted);
  return true;
}

void ReportWasmBrowserHostTextDelivery(const ui::WasmTextInputRecord& record,
                                       bool accepted) {
  // This is a separate versioned Chrome-host report rather than an extension
  // of M4's composition delivery protocol. Its fixed action/session identify
  // the non-composing browser-address text transaction without exposing its
  // focus token, client, text, or selection to JavaScript.
  const int reported = chromium_wasm_report_ozone_browser_text_input_delivery(
      static_cast<int>(record.action), record.session_id, record.sequence,
      accepted ? 1 : 0);
  if (reported != 1) {
    LOG(ERROR) << "host rejected browser committed-text delivery report";
  }
}

class WasmBrowserHostTextState {
 public:
  struct TextAdmission {
    gfx::AcceleratedWidget target_widget;
    ui::WasmTextInputFocusToken focus_token;
    uint64_t generation;
    uint64_t target_generation;
    size_t text_utf8_bytes;
  };

  struct PendingTextRecord {
    TextAdmission admission;
    ui::WasmTextInputRecord record;
  };

  WasmBrowserHostTextState() = default;
  WasmBrowserHostTextState(const WasmBrowserHostTextState&) = delete;
  WasmBrowserHostTextState& operator=(const WasmBrowserHostTextState&) =
      delete;
  ~WasmBrowserHostTextState() = default;

  bool InitializeOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    if (!task_runner) {
      return false;
    }

    base::AutoLock lock(lock_);
    // The action-4 protocol has a fixed session zero and per-module sequence
    // space. It is deliberately one-shot: a fresh adapter requires a fresh
    // Wasm module, so late old-generation reports cannot collide with a
    // reinitialized JavaScript pending map.
    if (accepting_host_text_ || task_runner_ || permanently_shutdown_) {
      return false;
    }
    ++generation_;
    ++target_generation_;
    ever_initialized_ = true;
    accepting_host_text_ = true;
    task_runner_ = std::move(task_runner);
    target_widget_ = gfx::kNullAcceleratedWidget;
    pending_text_records_ = 0;
    pending_text_utf8_bytes_ = 0;
    return true;
  }

  void ShutdownOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    std::deque<PendingTextRecord> terminal_records;
    {
      base::AutoLock lock(lock_);
      // Teardown before a completed initialization is harmless. Once live,
      // however, this bridge cannot be reinitialized in the same module.
      if (!ever_initialized_ || !accepting_host_text_) {
        return;
      }
      ++generation_;
      ++target_generation_;
      accepting_host_text_ = false;
      task_runner_ = nullptr;
      target_widget_ = gfx::kNullAcceleratedWidget;
      // Every successfully admitted record must eventually receive a terminal
      // report. Drain records that have not yet entered the UI pump now; an
      // already-running task observes the new generation and reports false.
      terminal_records.swap(pending_text_queue_);
      dispatch_task_posted_ = false;
      minimum_committed_records_before_dispatch_ = 1;
      // A queued task from the old lifetime sees a different |generation_| and
      // therefore cannot release accounting that belongs to a later lifetime.
      // Keep |next_sequence_| monotonic: old false acknowledgements use the
      // fixed session zero and must never collide with a fresh host request.
      pending_text_records_ = 0;
      pending_text_utf8_bytes_ = 0;
      permanently_shutdown_ = true;
    }
    for (const PendingTextRecord& pending : terminal_records) {
      ReportWasmBrowserHostTextDelivery(pending.record, /*accepted=*/false);
    }
  }

  bool SetTargetOnUiThread(gfx::AcceleratedWidget widget) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    if (widget == gfx::kNullAcceleratedWidget) {
      return false;
    }
    base::AutoLock lock(lock_);
    if (!accepting_host_text_ || !task_runner_) {
      return false;
    }
    ++target_generation_;
    target_widget_ = widget;
    return true;
  }

  void ClearTargetOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    std::deque<PendingTextRecord> terminal_records;
    {
      base::AutoLock lock(lock_);
      ++target_generation_;
      target_widget_ = gfx::kNullAcceleratedWidget;
      // A target teardown must not leave a smoke-gated or otherwise queued
      // transaction waiting forever for a UI dispatch that can no longer be
      // valid for its captured focus token.
      terminal_records = DrainQueuedTextRecordsLocked();
      dispatch_task_posted_ = false;
      minimum_committed_records_before_dispatch_ = 1;
    }
    for (const PendingTextRecord& pending : terminal_records) {
      ReportWasmBrowserHostTextDelivery(pending.record, /*accepted=*/false);
    }
  }

  bool ArmSmokeTwoRecordBarrierOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    // The smoke arms this before READY, while no host request can yet exist.
    // Do not let a test-only gate alter a production/in-flight transaction.
    if (!accepting_host_text_ || !task_runner_ || dispatch_task_posted_ ||
        !pending_text_queue_.empty() || pending_text_records_ != 0) {
      return false;
    }
    minimum_committed_records_before_dispatch_ = 2;
    return true;
  }

  std::optional<TextAdmission> ReserveTextAdmission(size_t text_utf8_bytes) {
    base::AutoLock lock(lock_);
    if (!accepting_host_text_ || !task_runner_ ||
        target_widget_ == gfx::kNullAcceleratedWidget ||
        next_sequence_ >= kMaximumHostTextSequence || text_utf8_bytes == 0 ||
        text_utf8_bytes > kMaximumPendingHostTextUtf8Bytes ||
        pending_text_records_ >= kMaximumPendingHostTextRecords ||
        text_utf8_bytes >
            kMaximumPendingHostTextUtf8Bytes - pending_text_utf8_bytes_) {
      return std::nullopt;
    }
    // Capture the Ozone client epoch while the lifecycle target and native
    // capacity reservation are protected. The UTF-8 copy below can interleave
    // with UI focus work under PROXY_TO_PTHREAD, so it must never choose the
    // target/token after that potentially large copy.
    const std::optional<ui::WasmTextInputFocusToken> focus_token =
        ui::CaptureWasmTextInputFocusToken(target_widget_);
    if (!focus_token) {
      return std::nullopt;
    }
    ++pending_text_records_;
    pending_text_utf8_bytes_ += text_utf8_bytes;
    return TextAdmission{target_widget_, *focus_token, generation_,
                         target_generation_, text_utf8_bytes};
  }

  void CancelTextAdmission(const TextAdmission& admission) {
    ReleaseTextReservation(admission.generation, admission.text_utf8_bytes);
  }

  bool PostReservedText(std::u16string text, const TextAdmission& admission) {
    if (text.empty()) {
      CancelTextAdmission(admission);
      return false;
    }

    std::deque<PendingTextRecord> terminal_records;
    {
      base::AutoLock lock(lock_);
      if (!accepting_host_text_ || !task_runner_ ||
          target_widget_ != admission.target_widget ||
          generation_ != admission.generation ||
          target_generation_ != admission.target_generation ||
          next_sequence_ >= kMaximumHostTextSequence) {
        ReleaseTextReservationLocked(admission.generation,
                                     admission.text_utf8_bytes);
        return false;
      }

      const uint32_t sequence = next_sequence_ + 1;
      ui::WasmTextInputRecord record{
          ui::WasmTextInputAction::kInsertText,
          /*session_id=*/0,
          sequence,
          std::move(text),
          gfx::Range(/*start=*/0, /*end=*/0),
      };
      pending_text_queue_.push_back(PendingTextRecord{admission,
                                                      std::move(record)});
      next_sequence_ = sequence;
      if (!MaybeScheduleTextDispatchLocked()) {
        // This admission never became observable to JavaScript, so it may
        // return failure and let the caller discard its local pending record.
        // Earlier accepted FIFO records receive explicit terminal reports.
        const PendingTextRecord& failed = pending_text_queue_.back();
        ReleaseTextReservationLocked(failed.admission.generation,
                                     failed.admission.text_utf8_bytes);
        pending_text_queue_.pop_back();
        --next_sequence_;
        terminal_records = DrainQueuedTextRecordsLocked();
        minimum_committed_records_before_dispatch_ = 1;
      } else {
        // The UI runner processes accepted reservations FIFO. A reservation
        // stays occupied through its synchronous delivery import, then the
        // next task is posted only after that import has returned.
        return true;
      }
    }
    for (const PendingTextRecord& pending : terminal_records) {
      ReportWasmBrowserHostTextDelivery(pending.record, /*accepted=*/false);
    }
    return false;
  }

 private:
  bool IsCurrentTarget(gfx::AcceleratedWidget target_widget,
                       uint64_t generation,
                       uint64_t target_generation) const {
    base::AutoLock lock(lock_);
    return accepting_host_text_ && generation == generation_ &&
           target_generation == target_generation_ &&
           target_widget == target_widget_ &&
           target_widget != gfx::kNullAcceleratedWidget;
  }

  void ReleaseTextReservationLocked(uint64_t generation,
                                    size_t text_utf8_bytes) {
    lock_.AssertAcquired();
    if (generation != generation_) {
      // Shutdown reset the old lifetime's accounting. A queued task or a
      // failed pre-copy reservation must not touch a fresh bridge lifetime.
      return;
    }
    CHECK_GT(pending_text_records_, 0u);
    CHECK_LE(text_utf8_bytes, pending_text_utf8_bytes_);
    --pending_text_records_;
    pending_text_utf8_bytes_ -= text_utf8_bytes;
  }

  void ReleaseTextReservation(uint64_t generation, size_t text_utf8_bytes) {
    base::AutoLock lock(lock_);
    ReleaseTextReservationLocked(generation, text_utf8_bytes);
  }

  std::deque<PendingTextRecord> DrainQueuedTextRecordsLocked()
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    std::deque<PendingTextRecord> terminal_records;
    terminal_records.swap(pending_text_queue_);
    for (const PendingTextRecord& pending : terminal_records) {
      ReleaseTextReservationLocked(pending.admission.generation,
                                   pending.admission.text_utf8_bytes);
    }
    return terminal_records;
  }

  bool MaybeScheduleTextDispatchLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (!accepting_host_text_ || !task_runner_ || dispatch_task_posted_ ||
        pending_text_queue_.size() <
            minimum_committed_records_before_dispatch_) {
      return true;
    }
    dispatch_task_posted_ = true;
    if (task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(
                &WasmBrowserHostTextState::DispatchNextTextOnUiThread,
                base::Unretained(this)))) {
      return true;
    }
    dispatch_task_posted_ = false;
    return false;
  }

  void DispatchNextTextOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    std::optional<PendingTextRecord> pending;
    {
      base::AutoLock lock(lock_);
      if (!dispatch_task_posted_) {
        return;
      }
      if (!accepting_host_text_ || pending_text_queue_.empty() ||
          pending_text_queue_.size() <
              minimum_committed_records_before_dispatch_) {
        dispatch_task_posted_ = false;
        return;
      }
      pending.emplace(std::move(pending_text_queue_.front()));
      pending_text_queue_.pop_front();
      // The first smoke burst starts only after both records are committed.
      minimum_committed_records_before_dispatch_ = 1;
      // Keep |dispatch_task_posted_| true while the synchronous JS delivery
      // import runs. A reentrant host admission can queue behind this record
      // but cannot observe a released native reservation or start a second
      // pump before its acknowledgement returns.
    }

    bool accepted = false;
    if (IsCurrentTarget(pending->admission.target_widget,
                        pending->admission.generation,
                        pending->admission.target_generation)) {
      // Ozone verifies that |focus_token| still names the same editable
      // TextInputClient before it runs InsertText. The bridge reports either
      // native result to the host, including stale target/focus rejection.
      accepted = ui::DispatchWasmTextInputWithFocusToken(
          pending->admission.target_widget, pending->record,
          pending->admission.focus_token);
    }

    // Do not free the native reservation until this synchronous UI->JS import
    // returns. The adapter schedules any follow-on Wasm work out of the
    // import, and the FIFO pump posts its next UI task only below.
    ReportWasmBrowserHostTextDelivery(pending->record, accepted);
    std::deque<PendingTextRecord> terminal_records;
    {
      base::AutoLock lock(lock_);
      ReleaseTextReservationLocked(pending->admission.generation,
                                   pending->admission.text_utf8_bytes);
      dispatch_task_posted_ = false;
      if (!MaybeScheduleTextDispatchLocked()) {
        // PostTask failure must not strand records already accepted by the C
        // ABI. They are no longer deliverable asynchronously, so terminally
        // reject each one after dropping the lock.
        terminal_records = DrainQueuedTextRecordsLocked();
        minimum_committed_records_before_dispatch_ = 1;
      }
    }
    for (const PendingTextRecord& terminal : terminal_records) {
      ReportWasmBrowserHostTextDelivery(terminal.record, /*accepted=*/false);
    }
  }

  mutable base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_
      GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  uint64_t target_generation_ GUARDED_BY(lock_) = 0;
  bool accepting_host_text_ GUARDED_BY(lock_) = false;
  bool ever_initialized_ GUARDED_BY(lock_) = false;
  bool permanently_shutdown_ GUARDED_BY(lock_) = false;
  gfx::AcceleratedWidget target_widget_ GUARDED_BY(lock_) =
      gfx::kNullAcceleratedWidget;
  uint32_t next_sequence_ GUARDED_BY(lock_) = 0;
  size_t pending_text_records_ GUARDED_BY(lock_) = 0;
  size_t pending_text_utf8_bytes_ GUARDED_BY(lock_) = 0;
  std::deque<PendingTextRecord> pending_text_queue_ GUARDED_BY(lock_);
  bool dispatch_task_posted_ GUARDED_BY(lock_) = false;
  size_t minimum_committed_records_before_dispatch_ GUARDED_BY(lock_) = 1;
};

WasmBrowserHostTextState& GetWasmBrowserHostTextState() {
  static base::NoDestructor<WasmBrowserHostTextState> state;
  return *state;
}

}  // namespace

bool InitializeWasmBrowserHostText() {
  return GetWasmBrowserHostTextState().InitializeOnUiThread();
}

void ShutdownWasmBrowserHostText() {
  GetWasmBrowserHostTextState().ShutdownOnUiThread();
}

bool SetWasmBrowserHostTextTarget(gfx::AcceleratedWidget widget) {
  return GetWasmBrowserHostTextState().SetTargetOnUiThread(widget);
}

void ClearWasmBrowserHostTextTarget() {
  GetWasmBrowserHostTextState().ClearTargetOnUiThread();
}

bool ArmWasmBrowserHostTextSmokeTwoRecordBarrier() {
  return GetWasmBrowserHostTextState().ArmSmokeTwoRecordBarrierOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_text(
    const uint8_t* text_utf8,
    int text_utf8_bytes) {
  size_t text_bytes = 0;
  if (!ValidateWasmBrowserHostTextInput(text_utf8, text_utf8_bytes,
                                        &text_bytes)) {
    return 0;
  }
  WasmBrowserHostTextState& state = GetWasmBrowserHostTextState();
  const std::optional<WasmBrowserHostTextState::TextAdmission> admission =
      state.ReserveTextAdmission(text_bytes);
  if (!admission) {
    return 0;
  }

  std::u16string text;
  if (!CopyWasmBrowserHostText(text_utf8, text_utf8_bytes, &text)) {
    state.CancelTextAdmission(*admission);
    return 0;
  }
  return state.PostReservedText(std::move(text), *admission) ? 1 : 0;
}

}  // extern "C"

}  // namespace chrome

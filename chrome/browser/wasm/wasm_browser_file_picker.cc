// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_file_picker.h"

#include <stddef.h>
#include <stdint.h>

#include <algorithm>
#include <limits>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "base/check_op.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/file_select_listener.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "emscripten/emscripten.h"
#include "emscripten/heap.h"
#include "third_party/blink/public/mojom/choosers/file_chooser.mojom.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_file_picker.cc must only be built for WebAssembly"
#endif

// The import asks the trusted outer host to present a single ordinary file
// picker. It is an admission result only: selection data returns later through
// the bounded C ABI below, and the host owns neither an inner WebContents nor a
// Chromium file path.
extern "C" int chromium_wasm_request_ozone_browser_file_picker(int request_id);

// This terminal acknowledgement lets the host clear its temporary DOM input
// and copied byte chunks. It carries no filename, path, MIME type, contents,
// file handle, or result object.
extern "C" int chromium_wasm_report_ozone_browser_file_picker_delivery(
    int request_id,
    int accepted);

namespace chrome {

namespace {

constexpr char kVolatileFilePickerRoot[] = "/tmp/chromium-wasm-file-picker";
constexpr size_t kMaximumFilePickerBytes = 8 * 1024 * 1024;
constexpr size_t kMaximumVolatileFilePickerVaultBytes = 16 * 1024 * 1024;
constexpr size_t kMaximumFilePickerNameBytes = 255;
constexpr size_t kFilePickerChunkBytes = 64 * 1024;
constexpr int kMaximumFilePickerRequestId = std::numeric_limits<int>::max();

bool IsValidHeapRange(const uint8_t* bytes, size_t byte_count) {
  if (byte_count == 0) {
    return true;
  }
  if (!bytes) {
    return false;
  }
  const uintptr_t start = reinterpret_cast<uintptr_t>(bytes);
  const size_t heap_size = emscripten_get_heap_size();
  return start <= heap_size && byte_count <= heap_size - start;
}

bool IsSafeFileName(std::string_view file_name) {
  if (file_name.empty() || file_name.size() > kMaximumFilePickerNameBytes ||
      !base::IsStringUTF8AllowingNoncharacters(file_name) ||
      file_name == "." || file_name == "..") {
    return false;
  }
  return std::none_of(file_name.begin(), file_name.end(), [](char character) {
    return character == '\0' || character == '/' || character == '\\';
  });
}

void ReportTerminalFilePickerDelivery(int request_id, bool accepted) {
  const int reported = chromium_wasm_report_ozone_browser_file_picker_delivery(
      request_id, accepted ? 1 : 0);
  if (reported != 1) {
    LOG(ERROR) << "host rejected Wasm file-picker terminal delivery";
  }
}

void NotifyFileSelectionCanceled(
    scoped_refptr<content::FileSelectListener> listener) {
  if (listener) {
    listener->FileSelectionCanceled();
  }
}

}  // namespace

// This global owns only the asynchronous trusted-host transfer transaction. A
// Browser-owned WasmBrowserFilePicker retains the WebContents/listener/file
// lifetime. Splitting those roles prevents a host callback from choosing a
// WebContents, retaining a JS heap view, or writing into a profile directory.
class WasmBrowserFilePickerHostState {
 public:
  WasmBrowserFilePickerHostState() = default;
  WasmBrowserFilePickerHostState(const WasmBrowserFilePickerHostState&) =
      delete;
  WasmBrowserFilePickerHostState& operator=(
      const WasmBrowserFilePickerHostState&) = delete;
  ~WasmBrowserFilePickerHostState() = default;

  bool BindOnUiThread(base::WeakPtr<WasmBrowserFilePicker> owner) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    if (!owner) {
      return false;
    }
    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    if (!task_runner) {
      return false;
    }

    base::AutoLock lock(lock_);
    if (owner_ || task_runner_ || active_request_) {
      return false;
    }
    owner_ = std::move(owner);
    task_runner_ = std::move(task_runner);
    return true;
  }

  void UnbindOnUiThread(WasmBrowserFilePicker* owner) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    bool report_canceled = false;
    int request_id = 0;
    {
      base::AutoLock lock(lock_);
      if (!owner_ || owner_.get() != owner) {
        return;
      }
      if (active_request_) {
        request_id = active_request_->request_id;
        report_canceled = active_request_->host_admitted;
        active_request_.reset();
      }
      owner_.reset();
      task_runner_ = nullptr;
    }
    if (report_canceled) {
      ReportTerminalFilePickerDelivery(request_id, /*accepted=*/false);
    }
  }

  std::optional<int> ReserveRequest(
      base::WeakPtr<WasmBrowserFilePicker> owner) {
    base::AutoLock lock(lock_);
    if (!owner || !owner_ || owner_.get() != owner.get() || !task_runner_ ||
        active_request_ || next_request_id_ >= kMaximumFilePickerRequestId) {
      return std::nullopt;
    }
    ++next_request_id_;
    active_request_.emplace();
    active_request_->request_id = next_request_id_;
    active_request_->owner = std::move(owner);
    return active_request_->request_id;
  }

  bool MarkHostAdmitted(int request_id) {
    base::AutoLock lock(lock_);
    if (!active_request_ || active_request_->request_id != request_id ||
        active_request_->host_admitted) {
      return false;
    }
    active_request_->host_admitted = true;
    return true;
  }

  bool AbandonUnadmittedRequest(int request_id) {
    base::AutoLock lock(lock_);
    if (active_request_ && active_request_->request_id == request_id &&
        !active_request_->host_admitted) {
      active_request_.reset();
      return true;
    }
    return false;
  }

  bool BeginTransfer(const uint8_t* file_name,
                     int file_name_bytes,
                     int expected_file_bytes,
                     int request_id) {
    if (file_name_bytes <= 0 || expected_file_bytes < 0 || request_id <= 0) {
      return false;
    }
    const size_t name_bytes = static_cast<size_t>(file_name_bytes);
    const size_t expected_bytes = static_cast<size_t>(expected_file_bytes);
    if (name_bytes > kMaximumFilePickerNameBytes ||
        expected_bytes > kMaximumFilePickerBytes ||
        !IsValidHeapRange(file_name, name_bytes)) {
      return false;
    }

    std::string copied_name(reinterpret_cast<const char*>(file_name),
                            name_bytes);
    if (!IsSafeFileName(copied_name)) {
      return false;
    }

    base::AutoLock lock(lock_);
    if (!active_request_ || !active_request_->host_admitted ||
        active_request_->request_id != request_id ||
        active_request_->phase != Phase::kAwaitingBegin) {
      return false;
    }
    active_request_->file_name = std::move(copied_name);
    active_request_->expected_bytes = expected_bytes;
    active_request_->received_bytes = 0;
    active_request_->next_sequence = 0;
    active_request_->contents.clear();
    active_request_->contents.reserve(expected_bytes);
    active_request_->phase = Phase::kReceiving;
    return true;
  }

  bool AppendTransferChunk(const uint8_t* bytes,
                           int byte_count,
                           int sequence,
                           int request_id) {
    if (byte_count <= 0 || sequence < 0 || request_id <= 0) {
      return false;
    }
    const size_t chunk_bytes = static_cast<size_t>(byte_count);
    if (chunk_bytes > kFilePickerChunkBytes ||
        !IsValidHeapRange(bytes, chunk_bytes)) {
      return false;
    }

    base::AutoLock lock(lock_);
    if (!active_request_ || !active_request_->host_admitted ||
        active_request_->request_id != request_id ||
        active_request_->phase != Phase::kReceiving ||
        sequence != active_request_->next_sequence ||
        active_request_->received_bytes > active_request_->expected_bytes) {
      return false;
    }
    const size_t remaining =
        active_request_->expected_bytes - active_request_->received_bytes;
    const size_t expected_chunk_bytes = std::min(kFilePickerChunkBytes,
                                                 remaining);
    if (chunk_bytes != expected_chunk_bytes || remaining == 0) {
      return false;
    }
    active_request_->contents.insert(active_request_->contents.end(), bytes,
                                     bytes + chunk_bytes);
    active_request_->received_bytes += chunk_bytes;
    ++active_request_->next_sequence;
    return true;
  }

  bool CompleteTransfer(int request_id) {
    base::WeakPtr<WasmBrowserFilePicker> owner;
    std::string file_name;
    std::vector<uint8_t> contents;
    scoped_refptr<base::SingleThreadTaskRunner> task_runner;
    {
      base::AutoLock lock(lock_);
      if (!active_request_ || !active_request_->host_admitted ||
          active_request_->request_id != request_id ||
          active_request_->phase != Phase::kReceiving ||
          active_request_->received_bytes != active_request_->expected_bytes ||
          !active_request_->owner.MaybeValid() || !task_runner_) {
        return false;
      }
      owner = active_request_->owner;
      file_name = std::move(active_request_->file_name);
      contents = std::move(active_request_->contents);
      task_runner = task_runner_;
      active_request_->phase = Phase::kCompletionPosted;
    }

    if (task_runner->PostTask(
            FROM_HERE,
            base::BindOnce(&WasmBrowserFilePicker::OnHostFilePickerCompleted,
                           std::move(owner), request_id, std::move(file_name),
                           std::move(contents)))) {
      return true;
    }

    // The host will call the explicit cancel ABI after a false return. Leave
    // the request cancellable rather than inventing a terminal success while
    // the UI sequence is unavailable.
    base::AutoLock lock(lock_);
    if (active_request_ && active_request_->request_id == request_id) {
      active_request_->phase = Phase::kAwaitingCancel;
    }
    return false;
  }

  bool CancelTransfer(int request_id) {
    base::WeakPtr<WasmBrowserFilePicker> owner;
    scoped_refptr<base::SingleThreadTaskRunner> task_runner;
    bool report_canceled = false;
    Phase previous_phase;
    {
      base::AutoLock lock(lock_);
      // Completion has handed copied bytes to a UI task. It is deliberately
      // irreversible here: reporting cancellation after that task can still
      // select the materialized file would split host and page outcomes.
      if (!active_request_ || active_request_->request_id != request_id ||
          !active_request_->host_admitted ||
          !active_request_->owner.MaybeValid() ||
          !task_runner_ ||
          active_request_->phase == Phase::kCompletionPosted ||
          active_request_->phase == Phase::kCancellationPosted) {
        return false;
      }
      owner = active_request_->owner;
      task_runner = task_runner_;
      // Claim cancellation before posting across the thread boundary. This
      // makes CompleteTransfer() reject a concurrent completion rather than
      // allowing a canceled DOM picker to materialize a file afterward.
      previous_phase = active_request_->phase;
      active_request_->phase = Phase::kCancellationPosted;
    }
    if (!task_runner->PostTask(
            FROM_HERE,
            base::BindOnce(&WasmBrowserFilePicker::OnHostFilePickerCanceled,
                           std::move(owner), request_id))) {
      // Task-runner failure occurs during teardown. Restore the prior phase
      // so a still-live UI owner retains a coherent request rather than a
      // permanently claimed cancellation.
      base::AutoLock lock(lock_);
      if (active_request_ && active_request_->request_id == request_id &&
          active_request_->phase == Phase::kCancellationPosted) {
        active_request_->phase = previous_phase;
      }
      return false;
    }

    {
      base::AutoLock lock(lock_);
      if (active_request_ && active_request_->request_id == request_id &&
          active_request_->phase == Phase::kCancellationPosted) {
        report_canceled = active_request_->host_admitted;
        active_request_.reset();
      }
    }
    if (report_canceled) {
      ReportTerminalFilePickerDelivery(request_id, /*accepted=*/false);
    }
    return true;
  }

  void FinishRequest(int request_id, bool accepted) {
    bool report = false;
    {
      base::AutoLock lock(lock_);
      if (!active_request_ || active_request_->request_id != request_id) {
        return;
      }
      report = active_request_->host_admitted;
      active_request_.reset();
    }
    if (report) {
      ReportTerminalFilePickerDelivery(request_id, accepted);
    }
  }

 private:
  enum class Phase {
    kAwaitingBegin,
    kReceiving,
    kCompletionPosted,
    kAwaitingCancel,
    kCancellationPosted,
  };

  struct ActiveRequest {
    int request_id = 0;
    base::WeakPtr<WasmBrowserFilePicker> owner;
    bool host_admitted = false;
    Phase phase = Phase::kAwaitingBegin;
    std::string file_name;
    size_t expected_bytes = 0;
    size_t received_bytes = 0;
    int next_sequence = 0;
    std::vector<uint8_t> contents;
  };

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_ GUARDED_BY(lock_);
  base::WeakPtr<WasmBrowserFilePicker> owner_ GUARDED_BY(lock_);
  std::optional<ActiveRequest> active_request_ GUARDED_BY(lock_);
  int next_request_id_ GUARDED_BY(lock_) = 0;
};

namespace {

WasmBrowserFilePickerHostState& GetWasmBrowserFilePickerHostState() {
  static base::NoDestructor<WasmBrowserFilePickerHostState> state;
  return *state;
}

}  // namespace

WasmBrowserFilePicker::WasmBrowserFilePicker(TabStripModel* tab_strip_model)
    : tab_strip_model_(tab_strip_model) {
  CHECK(tab_strip_model_);
  CHECK(GetWasmBrowserFilePickerHostState().BindOnUiThread(
      weak_ptr_factory_.GetWeakPtr()));
}

WasmBrowserFilePicker::~WasmBrowserFilePicker() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (pending_request_) {
    scoped_refptr<content::FileSelectListener> listener =
        std::move(pending_request_->listener);
    const int request_id = pending_request_->request_id;
    pending_request_.reset();
    GetWasmBrowserFilePickerHostState().FinishRequest(
        request_id, /*accepted=*/false);
    NotifyFileSelectionCanceled(std::move(listener));
  }
  for (const auto& entry : volatile_files_) {
    for (const VolatileFile& file : entry.second) {
      if (!base::DeleteFile(file.path)) {
        LOG(ERROR) << "failed to remove volatile Wasm file-picker import";
      }
    }
  }
  volatile_files_.clear();
  volatile_file_bytes_ = 0;
  for (content::WebContents* web_contents : attached_contents_) {
    if (web_contents && web_contents->GetDelegate() == this) {
      web_contents->SetDelegate(nullptr);
    }
  }
  attached_contents_.clear();
  GetWasmBrowserFilePickerHostState().UnbindOnUiThread(this);
  weak_ptr_factory_.InvalidateWeakPtrs();
}

bool WasmBrowserFilePicker::AttachToWebContents(
    content::WebContents* web_contents) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!web_contents || web_contents->GetDelegate() ||
      IsAttached(web_contents)) {
    return false;
  }
  web_contents->SetDelegate(this);
  attached_contents_.push_back(web_contents);
  return true;
}

void WasmBrowserFilePicker::DetachFromWebContents(
    content::WebContents* web_contents) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!web_contents || !IsAttached(web_contents)) {
    return;
  }
  if (pending_request_ && pending_request_->web_contents == web_contents) {
    CancelPendingRequest(/*notify_host=*/true);
  }
  DeleteVolatileFilesFor(web_contents);
  if (web_contents->GetDelegate() == this) {
    web_contents->SetDelegate(nullptr);
  }
  std::erase(attached_contents_, web_contents);
}

void WasmBrowserFilePicker::OnActiveWebContentsChanged() {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (pending_request_ && !IsContentsActive(pending_request_->web_contents)) {
    CancelPendingRequest(/*notify_host=*/true);
  }
}

bool WasmBrowserFilePicker::IsContentsActive(content::WebContents* contents) {
  return IsAttached(contents) && tab_strip_model_ &&
         tab_strip_model_->GetActiveWebContents() == contents;
}

void WasmBrowserFilePicker::CanDownload(
    const GURL& /*url*/,
    const std::string& /*request_method*/,
    base::OnceCallback<void(bool)> callback) {
  std::move(callback).Run(false);
}

bool WasmBrowserFilePicker::CanDragEnter(
    content::WebContents* /*source*/,
    const content::DropData& /*data*/,
    blink::DragOperationsMask /*operations_allowed*/) {
  return false;
}

void WasmBrowserFilePicker::RunFileChooser(
    content::RenderFrameHost* render_frame_host,
    scoped_refptr<content::FileSelectListener> listener,
    const blink::mojom::FileChooserParams& params) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  content::WebContents* const web_contents =
      render_frame_host
          ? content::WebContents::FromRenderFrameHost(render_frame_host)
          : nullptr;

  // The first Web implementation intentionally does not provide a generic
  // filesystem facade. Do not turn host filters into authority: Chromium still
  // owns the input's accepted file, and all modes except one regular open-file
  // operation cancel through the ordinary FileSelectListener route.
  if (!listener || pending_request_ || !IsContentsActive(web_contents) ||
      params.mode != blink::mojom::FileChooserParams::Mode::kOpen ||
      params.open_writable || params.use_media_capture) {
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&NotifyFileSelectionCanceled, std::move(listener)));
    return;
  }

  const std::optional<int> request_id =
      GetWasmBrowserFilePickerHostState().ReserveRequest(
          weak_ptr_factory_.GetWeakPtr());
  if (!request_id) {
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&NotifyFileSelectionCanceled, std::move(listener)));
    return;
  }

  pending_request_.emplace();
  pending_request_->request_id = *request_id;
  pending_request_->web_contents = web_contents;
  pending_request_->listener = std::move(listener);

  // This is a synchronous Emscripten proxy from Chromium's application
  // pthread to the outer browser main thread. The host verifies a live trusted
  // DOM activation immediately before input.showPicker(), and returns zero if
  // that capability is unavailable or already consumed.
  const bool host_admitted =
      chromium_wasm_request_ozone_browser_file_picker(*request_id) == 1;
  if (!host_admitted ||
      !GetWasmBrowserFilePickerHostState().MarkHostAdmitted(*request_id)) {
    const bool abandoned =
        GetWasmBrowserFilePickerHostState().AbandonUnadmittedRequest(
            *request_id);
    // A host that admitted the DOM picker must always receive a terminal
    // outcome, even if native state disappeared before it could record that
    // admission. Otherwise its temporary input could remain live until a
    // timeout despite Chromium having canceled the listener.
    if (host_admitted && abandoned) {
      ReportTerminalFilePickerDelivery(*request_id, /*accepted=*/false);
    }
    CancelPendingRequest(/*notify_host=*/false);
  }
}

void WasmBrowserFilePicker::OnHostFilePickerCompleted(
    int request_id,
    std::string file_name,
    std::vector<uint8_t> contents) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!pending_request_ || pending_request_->request_id != request_id ||
      !IsContentsActive(pending_request_->web_contents) ||
      !IsSafeFileName(file_name) || contents.size() > kMaximumFilePickerBytes ||
      volatile_file_bytes_ > kMaximumVolatileFilePickerVaultBytes ||
      contents.size() >
          kMaximumVolatileFilePickerVaultBytes - volatile_file_bytes_) {
    if (pending_request_ && pending_request_->request_id == request_id) {
      CancelPendingRequest(/*notify_host=*/true);
    } else {
      GetWasmBrowserFilePickerHostState().FinishRequest(
          request_id, /*accepted=*/false);
    }
    return;
  }

  const base::FilePath vault_path =
      base::FilePath::FromUTF8Unsafe(kVolatileFilePickerRoot);
  const base::FilePath imported_path = vault_path.AppendASCII(
      base::NumberToString(request_id) + ".upload");
  const bool materialized = base::CreateDirectory(vault_path) &&
                            base::WriteFile(imported_path, base::span(contents));

  PendingRequest request = std::move(*pending_request_);
  pending_request_.reset();
  if (!materialized) {
    base::DeleteFile(imported_path);
    GetWasmBrowserFilePickerHostState().FinishRequest(
        request_id, /*accepted=*/false);
    NotifyFileSelectionCanceled(std::move(request.listener));
    return;
  }

  volatile_files_[request.web_contents].push_back(
      {imported_path, contents.size()});
  volatile_file_bytes_ += contents.size();
  std::vector<blink::mojom::FileChooserFileInfoPtr> files;
  files.push_back(blink::mojom::FileChooserFileInfo::NewNativeFile(
      blink::mojom::NativeFileInfo::New(
          imported_path, base::UTF8ToUTF16(file_name),
          std::vector<std::u16string>())));

  // The terminal acknowledgement follows materialization, not the host's DOM
  // change event. A host-side success therefore cannot credit an inaccessible
  // or partial file. The selected file remains in this Browser-owned volatile
  // vault until its owning tab is removed.
  GetWasmBrowserFilePickerHostState().FinishRequest(request_id,
                                                    /*accepted=*/true);
  request.listener->FileSelected(
      std::move(files), base::FilePath(),
      blink::mojom::FileChooserParams::Mode::kOpen);
}

void WasmBrowserFilePicker::OnHostFilePickerCanceled(int request_id) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!pending_request_ || pending_request_->request_id != request_id) {
    return;
  }
  scoped_refptr<content::FileSelectListener> listener =
      std::move(pending_request_->listener);
  pending_request_.reset();
  NotifyFileSelectionCanceled(std::move(listener));
}

void WasmBrowserFilePicker::CancelPendingRequest(bool notify_host) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!pending_request_) {
    return;
  }
  scoped_refptr<content::FileSelectListener> listener =
      std::move(pending_request_->listener);
  const int request_id = pending_request_->request_id;
  pending_request_.reset();
  if (notify_host) {
    GetWasmBrowserFilePickerHostState().FinishRequest(request_id,
                                                       /*accepted=*/false);
  }
  NotifyFileSelectionCanceled(std::move(listener));
}

bool WasmBrowserFilePicker::IsAttached(
    content::WebContents* web_contents) const {
  return std::find(attached_contents_.begin(), attached_contents_.end(),
                   web_contents) != attached_contents_.end();
}

void WasmBrowserFilePicker::DeleteVolatileFilesFor(
    content::WebContents* web_contents) {
  const auto files = volatile_files_.find(web_contents);
  if (files == volatile_files_.end()) {
    return;
  }
  for (const VolatileFile& file : files->second) {
    if (base::DeleteFile(file.path)) {
      CHECK_GE(volatile_file_bytes_, file.bytes);
      volatile_file_bytes_ -= file.bytes;
    } else {
      // Keep the quota charged if a volatile import cannot be removed. This
      // fails future selections closed instead of silently treating leaked
      // data as available storage.
      LOG(ERROR) << "failed to remove volatile Wasm file-picker import";
    }
  }
  volatile_files_.erase(files);
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_file_picker_begin(
    const uint8_t* file_name,
    int file_name_bytes,
    int expected_file_bytes,
    int request_id) {
  return GetWasmBrowserFilePickerHostState().BeginTransfer(
             file_name, file_name_bytes, expected_file_bytes, request_id)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_file_picker_chunk(
    const uint8_t* bytes,
    int byte_count,
    int sequence,
    int request_id) {
  return GetWasmBrowserFilePickerHostState().AppendTransferChunk(
             bytes, byte_count, sequence, request_id)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_file_picker_complete(
    int request_id) {
  return GetWasmBrowserFilePickerHostState().CompleteTransfer(request_id) ? 1
                                                                            : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_file_picker_cancel(
    int request_id) {
  return GetWasmBrowserFilePickerHostState().CancelTransfer(request_id) ? 1
                                                                          : 0;
}

}  // extern "C"

}  // namespace chrome

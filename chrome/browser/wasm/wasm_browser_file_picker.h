// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_FILE_PICKER_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_FILE_PICKER_H_

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "base/files/file_path.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "content/public/browser/web_contents_delegate.h"

class TabStripModel;

namespace blink::mojom {
class FileChooserParams;
}  // namespace blink::mojom

namespace content {
class FileSelectListener;
class RenderFrameHost;
class WebContents;
}  // namespace content

namespace chrome {

class WasmBrowserFilePickerHostState;

// Owns the first, deliberately narrow file-upload bridge for the source-
// selected Wasm Browser. It attaches only to the Browser's bounded tab model
// and accepts one user-selected regular file at a time. The file is copied to
// a process-local volatile vault; it never names an outer-host path, handle,
// URL, OPFS entry, or Chrome profile location.
//
// All folder, multiple-file, save, File System Access, download, drag/drop,
// and browser-external WebContents cases remain explicitly unsupported.
class WasmBrowserFilePicker final : public content::WebContentsDelegate {
 public:
  explicit WasmBrowserFilePicker(TabStripModel* tab_strip_model);
  WasmBrowserFilePicker(const WasmBrowserFilePicker&) = delete;
  WasmBrowserFilePicker& operator=(const WasmBrowserFilePicker&) = delete;
  ~WasmBrowserFilePicker() override;

  // Browser calls these while the tab model still owns |web_contents|. The
  // delegate is never installed over an existing embedder delegate.
  bool AttachToWebContents(content::WebContents* web_contents);
  void DetachFromWebContents(content::WebContents* web_contents);

  // The host picker is authorized only for the active tab. Browser calls this
  // after a tab-selection change to revoke any chooser opened by the tab that
  // just became inactive.
  void OnActiveWebContentsChanged();

  // content::WebContentsDelegate:
  bool IsContentsActive(content::WebContents* contents) override;
  void CanDownload(const GURL& url,
                   const std::string& request_method,
                   base::OnceCallback<void(bool)> callback) override;
  bool CanDragEnter(content::WebContents* source,
                    const content::DropData& data,
                    blink::DragOperationsMask operations_allowed) override;
  void RunFileChooser(
      content::RenderFrameHost* render_frame_host,
      scoped_refptr<content::FileSelectListener> listener,
      const blink::mojom::FileChooserParams& params) override;

 private:
  friend class WasmBrowserFilePickerHostState;

  struct PendingRequest {
    int request_id = 0;
    raw_ptr<content::WebContents> web_contents = nullptr;
    scoped_refptr<content::FileSelectListener> listener;
  };

  struct VolatileFile {
    base::FilePath path;
    size_t bytes = 0;
  };

  void OnHostFilePickerCompleted(int request_id,
                                 std::string file_name,
                                 std::vector<uint8_t> contents);
  void OnHostFilePickerCanceled(int request_id);
  void CancelPendingRequest(bool notify_host);
  bool IsAttached(content::WebContents* web_contents) const;
  void DeleteVolatileFilesFor(content::WebContents* web_contents);

  const raw_ptr<TabStripModel> tab_strip_model_;
  std::vector<raw_ptr<content::WebContents>> attached_contents_;
  std::map<content::WebContents*, std::vector<VolatileFile>> volatile_files_;
  size_t volatile_file_bytes_ = 0;
  std::optional<PendingRequest> pending_request_;

  base::WeakPtrFactory<WasmBrowserFilePicker> weak_ptr_factory_{this};
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_FILE_PICKER_H_

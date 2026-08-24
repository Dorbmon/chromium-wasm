// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_ACCESSIBILITY_SNAPSHOT_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_ACCESSIBILITY_SNAPSHOT_SMOKE_H_

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "url/gurl.h"

namespace content {
class WebContents;
}  // namespace content

namespace ui {
struct AXTreeUpdate;
}  // namespace ui

namespace chrome {

// Returns the one fixed, non-interactive document used by the test-only AX
// snapshot smoke. This is deliberately not a caller-controlled URL and must
// not be reused as a general host accessibility bridge.
GURL GetWasmBrowserAccessibilitySnapshotSmokeUrl();

// Takes exactly one AX snapshot from the lifecycle-owned WebContents after
// that fixed document has committed and painted. It validates the expected
// root/main/heading/static-text/toggle semantics and the toggle's fixed
// bounds before asking the host bridge to create a corresponding passive
// semantic-DOM witness. It is not a page-semantic replacement; it neither
// observes updates nor exposes focus, keyboard, or action routing.
class WasmBrowserAccessibilitySnapshotSmoke final {
 public:
  using CompletionCallback = base::OnceCallback<void(bool success)>;

  explicit WasmBrowserAccessibilitySnapshotSmoke(
      CompletionCallback completion_callback);
  WasmBrowserAccessibilitySnapshotSmoke(
      const WasmBrowserAccessibilitySnapshotSmoke&) = delete;
  WasmBrowserAccessibilitySnapshotSmoke& operator=(
      const WasmBrowserAccessibilitySnapshotSmoke&) = delete;
  ~WasmBrowserAccessibilitySnapshotSmoke();

  // Begins the single snapshot request. |web_contents| must still own the
  // fixed document returned by GetWasmBrowserAccessibilitySnapshotSmokeUrl().
  void Start(content::WebContents* web_contents);

 private:
  void OnSnapshot(ui::AXTreeUpdate& snapshot);
  void Complete(bool success);

  bool started_ = false;
  bool completed_ = false;
  CompletionCallback completion_callback_;
  // Must be last so outstanding renderer snapshot callbacks become inert
  // before the one-shot completion callback or any other smoke state tears
  // down with its owning Browser lifecycle.
  base::WeakPtrFactory<WasmBrowserAccessibilitySnapshotSmoke>
      weak_ptr_factory_{this};
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_ACCESSIBILITY_SNAPSHOT_SMOKE_H_

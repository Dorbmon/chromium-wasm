// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_accessibility_snapshot_smoke.h"

#include <cstdio>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "ui/accessibility/ax_mode.h"
#include "ui/accessibility/ax_node_data.h"
#include "ui/accessibility/ax_tree_update.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_accessibility_snapshot_smoke.cc must only be built for WebAssembly"
#endif

// This synchronous import is provided by ozone_wasm's versioned host bridge.
// It accepts only this test's fixed UTF-8 text and its fixed semantic-role
// mask; it is not an arbitrary page-text export or an accessibility action
// interface.
extern "C" int chromium_wasm_report_accessibility_snapshot(
    const char* heading,
    int heading_length,
    const char* text,
    int text_length,
    int role_mask);

namespace chrome {

namespace {

constexpr char kAccessibilitySnapshotSmokeUrl[] =
    "data:text/html;base64,"
    "PCFkb2N0eXBlIGh0bWw+PHRpdGxlPkNocm9taXVtIFdhc20gQVggc25hcHNob3Q8L3RpdGxlPjxtYWluIGFyaWEtbGFiZWw9IkNocm9taXVtIFdhc20gQVggc21va2UiPjxoMT5DaHJvbWl1bSBXYXNtIEFYIHNuYXBzaG90PC9oMT48cD5TdGF0aWMgc2VtYW50aWMgdGV4dC48L3A+PC9tYWluPg==";
constexpr char kExpectedMainName[] = "Chromium Wasm AX smoke";
constexpr char kExpectedHeading[] = "Chromium Wasm AX snapshot";
constexpr char kExpectedStaticText[] = "Static semantic text.";
constexpr int kSnapshotRoleMask = 0x7;
constexpr size_t kMaximumSnapshotNodes = 32;
constexpr base::TimeDelta kSnapshotTimeout = base::Seconds(5);
constexpr char kSnapshotDeliveredMarker[] =
    "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:DELIVERED";
constexpr char kSnapshotFailureMarker[] =
    "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:FAIL";

bool HasNamedRole(const ui::AXTreeUpdate& snapshot,
                  ax::mojom::Role role,
                  std::string_view expected_name) {
  for (const ui::AXNodeData& node : snapshot.nodes) {
    if (node.role == role &&
        node.GetStringAttribute(ax::mojom::StringAttribute::kName) ==
            expected_name) {
      return true;
    }
  }
  return false;
}

bool HasRootWebArea(const ui::AXTreeUpdate& snapshot) {
  if (snapshot.root_id == ui::kInvalidAXNodeID) {
    return false;
  }
  for (const ui::AXNodeData& node : snapshot.nodes) {
    if (node.id == snapshot.root_id) {
      return node.role == ax::mojom::Role::kRootWebArea;
    }
  }
  return false;
}

bool IsExpectedSnapshot(const ui::AXTreeUpdate& snapshot) {
  // The renderer supplies the snapshot, but retain a narrow upper bound so a
  // future accidental broadening cannot make this fixed smoke a page-data
  // transport. The document has one frame and only needs four semantic nodes.
  return snapshot.nodes.size() > 0 &&
         snapshot.nodes.size() <= kMaximumSnapshotNodes &&
         HasRootWebArea(snapshot) &&
         HasNamedRole(snapshot, ax::mojom::Role::kMain, kExpectedMainName) &&
         HasNamedRole(snapshot, ax::mojom::Role::kHeading, kExpectedHeading) &&
         HasNamedRole(snapshot, ax::mojom::Role::kStaticText,
                      kExpectedStaticText);
}

}  // namespace

GURL GetWasmBrowserAccessibilitySnapshotSmokeUrl() {
  return GURL(kAccessibilitySnapshotSmokeUrl);
}

WasmBrowserAccessibilitySnapshotSmoke::WasmBrowserAccessibilitySnapshotSmoke(
    CompletionCallback completion_callback)
    : completion_callback_(std::move(completion_callback)) {
  CHECK(completion_callback_);
}

WasmBrowserAccessibilitySnapshotSmoke::~WasmBrowserAccessibilitySnapshotSmoke() =
    default;

void WasmBrowserAccessibilitySnapshotSmoke::Start(
    content::WebContents* web_contents) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(web_contents);
  CHECK(!started_);
  started_ = true;

  content::RenderFrameHost* const primary_main_frame =
      web_contents->GetPrimaryMainFrame();
  if (web_contents->GetLastCommittedURL() !=
          GetWasmBrowserAccessibilitySnapshotSmokeUrl() ||
      !primary_main_frame || !primary_main_frame->IsRenderFrameLive()) {
    Complete(false);
    return;
  }

  // RequestAXTreeSnapshot is explicitly one-shot and does not turn on the
  // WebContents' persistent accessibility mode. Keep the policy in the one
  // same-origin fixed document even though it contains no child frame.
  web_contents->RequestAXTreeSnapshot(
      base::BindOnce(&WasmBrowserAccessibilitySnapshotSmoke::OnSnapshot,
                     weak_ptr_factory_.GetWeakPtr()),
      ui::kAXModeComplete, kMaximumSnapshotNodes, kSnapshotTimeout,
      content::WebContents::AXTreeSnapshotPolicy::kSameOriginDirectDescendants);
}

void WasmBrowserAccessibilitySnapshotSmoke::OnSnapshot(
    ui::AXTreeUpdate& snapshot) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(started_);
  if (completed_) {
    return;
  }

  if (!IsExpectedSnapshot(snapshot)) {
    Complete(false);
    return;
  }

  // Both strings have just been checked against exact constants. The host
  // bridge separately rejects any different byte sequence or role mask before
  // it can create semantic DOM, keeping this a fixed smoke rather than a
  // general text mirror.
  const int delivered = chromium_wasm_report_accessibility_snapshot(
      kExpectedHeading, static_cast<int>(sizeof(kExpectedHeading) - 1),
      kExpectedStaticText,
      static_cast<int>(sizeof(kExpectedStaticText) - 1),
      kSnapshotRoleMask);
  if (delivered != 1) {
    Complete(false);
    return;
  }

  std::fprintf(stderr, "%s\n", kSnapshotDeliveredMarker);
  std::fflush(stderr);
  Complete(true);
}

void WasmBrowserAccessibilitySnapshotSmoke::Complete(bool success) {
  if (completed_) {
    return;
  }
  completed_ = true;
  // A renderer reply is asynchronous. Invalidate any queued weak reply before
  // the lifecycle completion can begin Browser teardown or destroy |this|.
  weak_ptr_factory_.InvalidateWeakPtrs();
  CompletionCallback completion_callback = std::move(completion_callback_);
  CHECK(completion_callback);
  if (!success) {
    std::fprintf(stderr, "%s\n", kSnapshotFailureMarker);
    std::fflush(stderr);
  }
  std::move(completion_callback).Run(success);
}

}  // namespace chrome

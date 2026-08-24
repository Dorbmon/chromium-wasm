// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_accessibility_snapshot_smoke.h"

#include <cmath>
#include <cstdio>
#include <string>
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
// It accepts only this test's fixed UTF-8 semantic values, role mask, and
// bounds; it is not an arbitrary page-text export or an accessibility action
// interface.
extern "C" int chromium_wasm_report_accessibility_snapshot(
    const char* heading,
    int heading_length,
    const char* text,
    int text_length,
    const char* control_name,
    int control_name_length,
    int role_mask,
    int control_left,
    int control_top,
    int control_width,
    int control_height);

namespace chrome {

namespace {

constexpr char kAccessibilitySnapshotSmokeUrl[] =
    "data:text/html;base64,"
    "PCFkb2N0eXBlIGh0bWw+PHRpdGxlPkNocm9taXVtIFdhc20gQVggc25hcHNob3Q8L3RpdGxlPjxzdHlsZT5odG1sLGJvZHl7bWFyZ2luOjB9YnV0dG9ue3Bvc2l0aW9uOmFic29sdXRlO2xlZnQ6NjRweDt0b3A6MTI4cHg7d2lkdGg6MTkycHg7aGVpZ2h0OjQ4cHg7Ym94LXNpemluZzpib3JkZXItYm94O21hcmdpbjowO3BhZGRpbmc6MDtib3JkZXI6MH08L3N0eWxlPjxtYWluIGFyaWEtbGFiZWw9IkNocm9taXVtIFdhc20gQVggc21va2UiPjxoMT5DaHJvbWl1bSBXYXNtIEFYIHNuYXBzaG90PC9oMT48cD5TdGF0aWMgc2VtYW50aWMgdGV4dC48L3A+PGJ1dHRvbiBhcmlhLWxhYmVsPSJDaHJvbWl1bSBXYXNtIEFYIGNvbnRyb2wiIGFyaWEtcHJlc3NlZD0idHJ1ZSI+VG9nZ2xlIHNlbWFudGljIHN0YXRlPC9idXR0b24+PC9tYWluPg==";
constexpr char kExpectedMainName[] = "Chromium Wasm AX smoke";
constexpr char kExpectedHeading[] = "Chromium Wasm AX snapshot";
constexpr char kExpectedStaticText[] = "Static semantic text.";
constexpr char kExpectedControlName[] = "Chromium Wasm AX control";
constexpr int kExpectedControlLeft = 64;
constexpr int kExpectedControlTop = 128;
constexpr int kExpectedControlWidth = 192;
constexpr int kExpectedControlHeight = 48;
constexpr int kSnapshotRoleMask = 0xf;
constexpr size_t kMaximumSnapshotNodes = 32;
constexpr base::TimeDelta kSnapshotTimeout = base::Seconds(5);
constexpr char kSnapshotDeliveredMarker[] =
    "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:DELIVERED";
constexpr char kSnapshotFailureMarker[] =
    "CHROMIUM_WASM_M8_ACCESSIBILITY_SNAPSHOT:FAIL";

const ui::AXNodeData* FindNamedRole(const ui::AXTreeUpdate& snapshot,
                                    ax::mojom::Role role,
                                    std::string_view expected_name) {
  for (const ui::AXNodeData& node : snapshot.nodes) {
    if (node.role == role &&
        node.GetStringAttribute(ax::mojom::StringAttribute::kName) ==
            expected_name) {
      return &node;
    }
  }
  return nullptr;
}

bool HasNamedRole(const ui::AXTreeUpdate& snapshot,
                  ax::mojom::Role role,
                  std::string_view expected_name) {
  return FindNamedRole(snapshot, role, expected_name) != nullptr;
}

bool IsExpectedControlBounds(const ui::AXNodeData& control) {
  const gfx::RectF& bounds = control.relative_bounds.bounds;
  const auto has_expected_coordinate = [](float actual, int expected) {
    return std::abs(actual - static_cast<float>(expected)) < 0.01f;
  };
  return has_expected_coordinate(bounds.x(), kExpectedControlLeft) &&
         has_expected_coordinate(bounds.y(), kExpectedControlTop) &&
         has_expected_coordinate(bounds.width(), kExpectedControlWidth) &&
         has_expected_coordinate(bounds.height(), kExpectedControlHeight);
}

bool HasExpectedControl(const ui::AXTreeUpdate& snapshot) {
  const ui::AXNodeData* const control = FindNamedRole(
      snapshot, ax::mojom::Role::kToggleButton, kExpectedControlName);
  return control && control->IsButtonPressed() &&
         IsExpectedControlBounds(*control);
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
                      kExpectedStaticText) &&
         HasExpectedControl(snapshot);
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

  // Pass values from the validated native AX nodes, not a parallel host-side
  // description. The bridge separately rejects a different byte sequence,
  // role mask, or bounds before it can create semantic DOM, keeping this a
  // fixed smoke rather than a general text or geometry mirror.
  const ui::AXNodeData* const heading = FindNamedRole(
      snapshot, ax::mojom::Role::kHeading, kExpectedHeading);
  const ui::AXNodeData* const static_text = FindNamedRole(
      snapshot, ax::mojom::Role::kStaticText, kExpectedStaticText);
  const ui::AXNodeData* const control = FindNamedRole(
      snapshot, ax::mojom::Role::kToggleButton, kExpectedControlName);
  if (!heading || !static_text || !control) {
    Complete(false);
    return;
  }

  const std::string& heading_name =
      heading->GetStringAttribute(ax::mojom::StringAttribute::kName);
  const std::string& static_text_name =
      static_text->GetStringAttribute(ax::mojom::StringAttribute::kName);
  const std::string& control_name =
      control->GetStringAttribute(ax::mojom::StringAttribute::kName);
  const gfx::RectF& control_bounds = control->relative_bounds.bounds;
  const auto rounded_coordinate = [](float coordinate) {
    return static_cast<int>(std::lround(coordinate));
  };
  const int delivered = chromium_wasm_report_accessibility_snapshot(
      heading_name.data(), static_cast<int>(heading_name.size()),
      static_text_name.data(), static_cast<int>(static_text_name.size()),
      control_name.data(), static_cast<int>(control_name.size()),
      kSnapshotRoleMask, rounded_coordinate(control_bounds.x()),
      rounded_coordinate(control_bounds.y()),
      rounded_coordinate(control_bounds.width()),
      rounded_coordinate(control_bounds.height()));
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

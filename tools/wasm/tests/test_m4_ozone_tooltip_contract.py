#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Static contracts for the bounded M4 native Blink title-tooltip path."""

from __future__ import annotations

import re
import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class M4OzoneTooltipContractTest(unittest.TestCase):
    def test_wasm_content_shell_owns_a_root_tooltip_client(self) -> None:
        build = source("content/shell/BUILD.gn")
        platform_data_header = source(
            "content/shell/browser/shell_platform_data_aura.h"
        )
        platform_data = source(
            "content/shell/browser/shell_platform_data_aura.cc"
        )

        aura_delegate_selection = build.split(
            'sources += [ "browser/shell_platform_delegate_aura.cc" ]', 1
        )[1]
        wasm_branch = aura_delegate_selection.split("if (is_wasm) {", 1)[1].split(
            "      } else {", 1
        )[0]
        for marker in (
            '"browser/shell_tooltip_wasm.cc"',
            '"browser/shell_tooltip_wasm.h"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, wasm_branch)

        for marker in (
            '#include "content/shell/browser/shell_tooltip_wasm.h"',
            "WasmTooltipControllerPtr tooltip_controller_;",
            "tooltip_controller_ = CreateWasmTooltipController(host_->window());",
            "tooltip_controller_.reset();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, platform_data_header + platform_data)

    def test_controller_uses_a_normal_tooltip_client_and_compositor_child(
        self,
    ) -> None:
        controller = source("content/shell/browser/shell_tooltip_wasm.cc")

        for marker in (
            "class WasmTooltipController final : public wm::TooltipClient",
            "wm::SetTooltipClient(root_window_, this);",
            "root_window_->AddPreTargetHandler(this);",
            "root_window_->RemovePreTargetHandler(this);",
            "wm::GetTooltipText(target);",
            "base::Milliseconds(500)",
            "aura::client::WINDOW_TYPE_TOOLTIP",
            "tooltip_window_->set_owned_by_parent(false);",
            "tooltip_window_->Init(ui::LAYER_TEXTURED);",
            "aura::EventTargetingPolicy::kNone",
            "bool CanFocus() override { return false; }",
            "bool HasHitTestMask() const override { return false; }",
            "root_window_->AddChild(tooltip_window_.get());",
            "root_window_->StackChildAtTop(tooltip_window_.get());",
            "tooltip_window_->Show();",
            "kTooltipCursorOffsetX = 12",
            "kTooltipCursorOffsetY = 18",
            "gfx::Rect(0, 0, 1, tooltip_size_.height())",
            "aura::Env::GetInstance()->IsMouseButtonDown()",
            "wm::GetTooltipText(observed_window_) != tooltip_text_",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, controller)

        for forbidden in (
            "PlatformWindow",
            "CreatePlatformWindow",
            "WindowTreeHost",
            "SurfaceOzone",
            "chromium_wasm_host_",
            "FontList",
            "RenderText",
            "views::",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, controller)

        show = section(
            controller,
            "  void ShowTooltip() {",
            "  void EnsureTooltipWindow() {",
        )
        self.assertLess(
            show.index("EnsureTooltipWindow();"),
            show.index("tooltip_window_->SetBounds(gfx::Rect(tooltip_origin"),
        )
        self.assertIn("wm::GetTooltipText(observed_window_) != tooltip_text_", show)

        update = section(
            controller,
            "  void UpdateTooltip(aura::Window* target) override {",
            "  void UpdateTooltipFromKeyboard(",
        )
        self.assertIn("target != observed_window_", update)
        self.assertNotIn("UpdateObservedWindow(target);", update)

    def test_title_tooltip_uses_the_normal_aura_under_cursor_check(self) -> None:
        view = source(
            "content/browser/renderer_host/render_widget_host_view_aura.cc"
        )
        update = section(
            view,
            "void RenderWidgetHostViewAura::UpdateTooltipUnderCursor(",
            "void RenderWidgetHostViewAura::UpdateTooltip(",
        )

        self.assertIn("GetCursorManager()->IsViewUnderCursor(this)", update)
        self.assertIn("UpdateTooltip(tooltip_text);", update)
        self.assertNotIn("#if BUILDFLAG(IS_WASM)", update)

    def test_wasm_tooltips_reject_updates_from_stale_mouse_input(self) -> None:
        mojom = source(
            "third_party/blink/public/mojom/widget/platform_widget.mojom"
        )
        widget_base_header = source(
            "third_party/blink/renderer/platform/widget/widget_base.h"
        )
        widget_base = source(
            "third_party/blink/renderer/platform/widget/widget_base.cc"
        )
        frame_widget = source(
            "third_party/blink/renderer/core/frame/web_frame_widget_impl.cc"
        )
        popup_widget = source(
            "third_party/blink/renderer/core/exported/web_page_popup_impl.cc"
        )
        host = source(
            "content/browser/renderer_host/render_widget_host_impl.cc"
        )
        base_header = source(
            "content/browser/renderer_host/render_widget_host_view_base.h"
        )
        base = source(
            "content/browser/renderer_host/render_widget_host_view_base.cc"
        )
        aura = source(
            "content/browser/renderer_host/render_widget_host_view_aura.cc"
        )
        child_frame = source(
            "content/browser/renderer_host/render_widget_host_view_child_frame.h"
        )
        event_source_header = source(
            "ui/ozone/platform/wasm/wasm_event_source.h"
        )
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")

        mojo_update = section(
            mojom,
            "  UpdateTooltipUnderCursor(",
            "\n\n  // Sent by a widget to the browser to set the tooltip text",
        )
        self.assertIn("mojo_base.mojom.TimeTicks input_event_time", mojo_update)

        for marker in (
            "void SetTooltipInputEventTime(base::TimeTicks input_event_time)",
            "tooltip_input_event_time_ = input_event_time;",
            "base::TimeTicks tooltip_input_event_time_;",
        ):
            with self.subTest(widget_base_marker=marker):
                self.assertIn(marker, widget_base_header)

        widget_base_update = section(
            widget_base,
            "void WidgetBase::UpdateTooltipUnderCursor(",
            "void WidgetBase::UpdateTooltipFromKeyboard(",
        )
        self.assertIn("tooltip_input_event_time_", widget_base_update)

        # Capture occurs before the input-event trace and later dispatch.
        frame_input = frame_widget.split(
            "WebInputEventResult WebFrameWidgetImpl::HandleInputEvent(", 1
        )[1].split("  TRACE_EVENT1", 1)[0]
        self.assertIn("WebInputEvent::IsMouseEventType", frame_input)
        self.assertIn(
            "widget_base_->SetTooltipInputEventTime(input_event.TimeStamp());",
            frame_input,
        )

        popup_input = section(
            popup_widget,
            "WebInputEventResult WebPagePopupImpl::HandleInputEvent(",
            "void WebPagePopupImpl::FocusChanged(",
        )
        self.assertIn("WebInputEvent::IsMouseEventType", popup_input)
        self.assertIn(
            "widget_base_->SetTooltipInputEventTime(event.Event().TimeStamp());",
            popup_input,
        )

        host_update = section(
            host,
            "void RenderWidgetHostImpl::UpdateTooltipUnderCursor(",
            "void RenderWidgetHostImpl::UpdateTooltipFromKeyboard(",
        )
        self.assertIn("IsTooltipInputEventCurrent(input_event_time)", host_update)
        self.assertLess(
            host_update.index("IsTooltipInputEventCurrent(input_event_time)"),
            host_update.index("view_->UpdateTooltipUnderCursor("),
        )

        for marker in (
            "bool IsTooltipInputEventCurrent(",
            "void RecordTooltipInputEventTime(base::TimeTicks input_event_time,",
            "const gfx::PointF& screen_location);",
            "void InvalidateTooltipInputEventEpoch();",
            "base::TimeTicks tooltip_input_event_time_;",
            "base::TimeTicks tooltip_input_epoch_start_time_;",
            "gfx::PointF tooltip_input_screen_location_;",
            "bool has_tooltip_input_epoch_ = false;",
        ):
            with self.subTest(base_header_marker=marker):
                self.assertIn(marker, base_header)

        process_mouse = section(
            base,
            "void RenderWidgetHostViewBase::ProcessMouseEvent(",
            "bool RenderWidgetHostViewBase::IsTooltipInputEventCurrent(",
        )
        self.assertIn(
            "RecordTooltipInputEventTime(event.TimeStamp(), event.PositionInScreen());",
            process_mouse,
        )
        self.assertIn("InvalidateTooltipInputEventEpoch();", process_mouse)
        input_current = section(
            base,
            "bool RenderWidgetHostViewBase::IsTooltipInputEventCurrent(",
            "void RenderWidgetHostViewBase::RecordTooltipInputEventTime(",
        )
        for marker in (
            "#if BUILDFLAG(IS_WASM)",
            "has_tooltip_input_epoch_",
            "!input_event_time.is_null()",
            "input_event_time >= tooltip_input_epoch_start_time_",
            "input_event_time <= tooltip_input_event_time_",
        ):
            with self.subTest(input_current_marker=marker):
                self.assertIn(marker, input_current)

        aura_mouse = section(
            aura,
            "void RenderWidgetHostViewAura::OnMouseEvent(ui::MouseEvent* event) {",
            "bool RenderWidgetHostViewAura::HasFallbackSurface() const",
        )
        self.assertIn("ui::EventType::kMouseMoved", aura_mouse)
        self.assertIn("event->root_location_f()", aura_mouse)
        self.assertIn("InvalidateTooltipInputEventEpoch();", aura_mouse)
        self.assertLess(
            aura_mouse.index("RecordTooltipInputEventTime(event->time_stamp(),"),
            aura_mouse.index("event_handler_->OnMouseEvent(event);"),
        )

        for marker in (
            "void RenderWidgetHostViewBase::ProcessMouseWheelEvent(",
            "void RenderWidgetHostViewBase::ProcessTouchEvent(",
            "void RenderWidgetHostViewBase::ProcessGestureEvent(",
        ):
            with self.subTest(epoch_invalidation_marker=marker):
                self.assertIn(marker, base)
        self.assertGreaterEqual(base.count("InvalidateTooltipInputEventEpoch();"), 4)
        self.assertIn(
            "InvalidateTooltipInputEventEpoch();\n  last_pointer_type_",
            aura,
        )
        self.assertIn(
            "class CONTENT_EXPORT RenderWidgetHostViewChildFrame\n"
            "    : public RenderWidgetHostViewBase",
            child_frame,
        )

        for marker in (
            "base::TimeTicks NextMouseEventTime();",
            "base::TimeTicks last_mouse_event_time_;",
        ):
            with self.subTest(event_source_header_marker=marker):
                self.assertIn(marker, event_source_header)

        event_time = section(
            event_source,
            "base::TimeTicks WasmPlatformEventSource::NextMouseEventTime()",
            "bool WasmPlatformEventSource::DispatchMouseEvent(",
        )
        for marker in (
            "const base::TimeTicks now = EventTimeForNow();",
            "if (now <= last_mouse_event_time_)",
            "last_mouse_event_time_ + base::Microseconds(1)",
            "last_mouse_event_time_ = now;",
            "return last_mouse_event_time_;",
        ):
            with self.subTest(event_time_marker=marker):
                self.assertIn(marker, event_time)

        mouse_dispatch = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchMouseEvent(",
            "bool WasmPlatformEventSource::DispatchMouseWheelEvent(",
        )
        self.assertIn("NextMouseEventTime()", mouse_dispatch)

    def test_host_canvas_exit_uses_the_last_native_hover_target(self) -> None:
        api = source("content/shell/browser/wasm_host_api.cc")
        event_source_header = source(
            "ui/ozone/platform/wasm/wasm_event_source.h"
        )
        event_source = source("ui/ozone/platform/wasm/wasm_event_source.cc")
        manager_header = source(
            "ui/ozone/platform/wasm/wasm_window_manager.h"
        )
        manager = source("ui/ozone/platform/wasm/wasm_window_manager.cc")
        host = source("tools/wasm/host/content_shell_host.js")

        for marker in (
            "bool DispatchMouseExitEvent();",
            "gfx::Point last_mouse_root_location_;",
            "int last_mouse_source_device_id_ = ED_UNKNOWN_DEVICE;",
            "bool has_last_mouse_root_location_ = false;",
            "bool DispatchWasmMouseExit();",
            "WasmWindow* TakePointerFocusedWindow();",
            "void SetCursorOutsideDisplay();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, event_source_header + manager_header)

        dispatch_exit = section(
            event_source,
            "bool WasmPlatformEventSource::DispatchMouseExitEvent()",
            "bool WasmPlatformEventSource::DispatchMouseWheelEvent(",
        )
        for marker in (
            "has_last_mouse_root_location_",
            "window_manager_->TakePointerFocusedWindow()",
            "window_manager_->SetCursorOutsideDisplay()",
            "has_last_mouse_root_location_ = false;",
            "EventType::kMouseExited",
            "NextMouseEventTime()",
            "event.set_source_device_id(last_mouse_source_device_id_);",
            "PlatformEventSource::DispatchEvent(&event);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dispatch_exit)
        self.assertLess(
            dispatch_exit.index("window_manager_->TakePointerFocusedWindow()"),
            dispatch_exit.index("window_manager_->SetCursorOutsideDisplay()"),
        )
        self.assertLess(
            dispatch_exit.index("window_manager_->SetCursorOutsideDisplay()"),
            dispatch_exit.index("PlatformEventSource::DispatchEvent(&event)"),
        )
        self.assertIn("pointer_focused_window_ = nullptr;", manager)
        self.assertIn("cursor_screen_point_ = gfx::Point(-1, -1);", manager)

        exit_dispatch = section(
            api,
            "void DispatchDomPointerExitOnUiThread()",
            "void DispatchDomWheelOnUiThread(",
        )
        self.assertIn("ui::DispatchWasmMouseExit()", exit_dispatch)
        self.assertIn("out-of-viewport mouse move", exit_dispatch)
        exit_export = section(
            api,
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_pointer_exit()",
            "EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_wheel(",
        )
        self.assertIn("PostHostCommand", exit_export)
        self.assertIn("DispatchDomPointerExitOnUiThread", exit_export)

        exit_handler = section(
            host,
            "  #handleM4PointerExit(event) {",
            "  #handleM4PointerEvent(type, event) {",
        )
        for marker in (
            'type: "exit"',
            'event.pointerType !== "mouse"',
            "event.isPrimary !== true",
            "record.button !== -1",
            "record.buttons !== 0",
            "NO_UNPRESSED_HOVER",
            "chromium_wasm_host_pointer_exit",
            "this.#m4PointerHoverActive = false;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, exit_handler)
        listeners = section(host, "  enableM4PointerInput()", "  #handleM4WheelEvent")
        self.assertIn('"pointerleave"', listeners)

    def test_controller_cancels_on_input_and_does_not_reuse_stale_titles(
        self,
    ) -> None:
        controller = source("content/shell/browser/shell_tooltip_wasm.cc")
        mouse_handler = section(
            controller,
            "void OnMouseEvent(ui::MouseEvent* event) override",
            "void OnScrollEvent(ui::ScrollEvent*) override",
        )

        for marker in (
            "ui::EventType::kMouseMoved",
            "ui::EventType::kMouseDragged",
            "ui::EventType::kMouseCaptureChanged",
            "ui::EventType::kMouseExited",
            "ui::EventType::kMousePressed",
            "ui::EventType::kMouseReleased",
            "ui::EventType::kMousewheel",
            "HideAndCancelTooltip();",
            "UpdateObservedWindow(nullptr);",
            "aura::Env::GetInstance()->IsMouseButtonDown()",
            "event->root_location() == last_mouse_location_",
            "target == observed_window_",
            "Blink coalesces tooltip decisions",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, mouse_handler)

        for marker in (
            "void OnKeyEvent(ui::KeyEvent*) override { HideAndCancelTooltip(); }",
            "void OnScrollEvent(ui::ScrollEvent*) override",
            "void OnTouchEvent(ui::TouchEvent*) override { "
            "HideAndCancelTooltip(); }",
            "void OnGestureEvent(ui::GestureEvent*) override",
            "void OnCancelMode(ui::CancelModeEvent*) override",
            "target->GetRootWindow() != root_window_",
            "if (wm::GetTooltipClient(root_window_) == this)",
            "wm::SetTooltipClient(root_window_, nullptr);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, controller)

        self.assertNotIn("wm::GetTooltipText(", mouse_handler)
        self.assertLess(
            mouse_handler.index("Blink coalesces tooltip decisions"),
            mouse_handler.index("HideTooltipWindow();"),
        )

    def test_fixture_uses_a_real_title_and_observes_trusted_moves(self) -> None:
        fixture = source("tools/wasm/testdata/m4_ozone_tooltip_page.html")

        for marker in (
            'id="tooltip-target" title="WASM TOOLTIP"',
            'id="confirm-target" title="SWAM TOOLTIP"',
            'id="clear-target"',
            "HOVER_TARGET_X = 220",
            "HOVER_TARGET_Y = 116",
            "CONFIRM_TARGET_X = 220",
            "CONFIRM_TARGET_Y = 286",
            "CLEAR_TARGET_X = 580",
            "CLEAR_TARGET_Y = 376",
            "hoverTargetX",
            "hoverTargetY",
            "confirmTargetX",
            "confirmTargetY",
            "clearTargetX",
            "clearTargetY",
            "tooltipTitle: target.title",
            "confirmTitle: confirmTarget.title",
            'clearTitle: clearTarget.getAttribute("title")',
            "mouseTrace",
            "pointerTrace",
            "mouseLeaveTrace",
            'element.addEventListener("mousemove"',
            'element.addEventListener("pointermove"',
            'confirmTarget.addEventListener("mouseleave"',
            "trusted: event.isTrusted === true",
            "defaultPrevented: event.defaultPrevented === true",
            "observedAtMs: Math.floor(performance.now())",
            "geometryIsDeterministic",
            "__chromiumWasmM4Probe",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)

        self.assertEqual(fixture.count('addEventListener("mouseleave"'), 1)

        for forbidden in (
            "navigator.clipboard",
            "execCommand(",
            "dispatchEvent(",
            "event.preventDefault()",
            "Input.insertText",
            "new MouseEvent",
            "setPointerCapture(",
            "releasePointerCapture(",
            'setAttribute("title"',
            'removeAttribute("title"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fixture)

        self.assertIsNone(
            re.search(
                r"(?:\.title|\[['\"]title['\"]\])\s*=\s*(?!=)", fixture
            )
        )
        self.assertNotIn('id="clear-target" title=', fixture)
        self.assertNotIn("#202124", fixture)
        self.assertNotIn("#5f6368", fixture)

    def test_host_harness_scans_only_the_native_compositor_tooltip(self) -> None:
        host = source("tools/wasm/host/content_shell_host.js")
        server = source("tools/wasm/m3_content_server.py")
        runner = source("tools/wasm/run_m4_ozone_smoke.py")
        cdp = source("tools/wasm/m4_cdp.py")

        for marker in (
            'const M4_TOOLTIP_CASE = "ozone_tooltip_m4"',
            'const M4_TOOLTIP_FIXTURE = "chromium-wasm-m4-ozone-tooltip-v1"',
            "function scanM4TooltipOverlay(canvas, anchorX, anchorY, label)",
            "getImageData",
            "M4_TOOLTIP_BACKGROUND_RGBA",
            "M4_TOOLTIP_BORDER_RGBA",
            "M4_TOOLTIP_INK_RGBA",
            "M4_TOOLTIP_WIDTH = 110",
            "M4_TOOLTIP_HEIGHT = 24",
            "M4_TOOLTIP_INK_PIXELS = 424",
            "M4_TOOLTIP_CLEAR_QUIESCENCE_MS = 750",
            "M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS = 250",
            "minX !== expectedMinX + 1",
            "maxX !== expectedMaxX - 1",
            "function countM4TooltipBackgroundPixels(canvas)",
            "function m4TooltipInnerTraceGapMs(pageProbe, firstIndex, secondIndex)",
            "async function runM4OzoneTooltipSmokeFromQuery()",
            "window.__chromiumWasmM4TooltipState",
            'state: "awaiting-dom-tooltip-race"',
            'state: "awaiting-dom-tooltip-hover"',
            'state: "awaiting-dom-tooltip-exit"',
            "tooltipRapidClearProof",
            "tooltipShowProof",
            "tooltipExitProof",
            "matchesM4TooltipQueuedPointerExit",
            "hasM4TooltipInnerMouseExit",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, host)

        smoke = section(
            host,
            "async function runM4OzoneTooltipSmokeFromQuery()",
            "export async function runContentShellSmokeFromQuery",
        )
        for forbidden in (
            "chromium_wasm_host_click",
            "Input.insertText",
            "navigator.clipboard",
            "document.createElement",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, smoke)

        rapid_proof = smoke.split("    const raceTrace = [", 1)[1].split(
            "    const hoverTrace = [", 1
        )[0]
        for marker in (
            "raceClearRecord",
            "m4TooltipInnerTraceGapMs(readiness.pageProbe, 0, 1)",
            "M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS",
            "readiness.frame?.id > raceClearRecord?.frameIdBefore",
            "frameId: readiness.frame.id",
            "countM4TooltipBackgroundPixels(canvas)",
        ):
            with self.subTest(rapid_marker=marker):
                self.assertIn(marker, rapid_proof)

        show_proof = smoke.split("    const hoverTrace = [", 1)[1].split(
            "    const exitSequence =", 1
        )[0]
        for marker in (
            "[confirmX, confirmY]",
            '["confirm-target", confirmX, confirmY]',
            "m4TooltipInnerTraceGapMs(\n          readiness.pageProbe, 2, 3)",
            "duplicateMoveGapMs: duplicateHoverGapMs",
            "scanM4TooltipOverlay(\n        canvas, confirmX, confirmY, confirmTitle);",
        ):
            with self.subTest(show_marker=marker):
                self.assertIn(marker, show_proof)

        exit_proof = smoke.split("    const exitSequence =", 1)[1].split(
            "    const shutdownTimeoutMs", 1
        )[0]
        self.assertIn("matchesM4TooltipQueuedPointerExit", exit_proof)
        self.assertIn("hasM4TooltipInnerMouseExit", exit_proof)
        self.assertIn("countM4TooltipBackgroundPixels(canvas)", exit_proof)
        self.assertIn("tooltipAbsenceStartedAt", exit_proof)
        self.assertIn("quietForMs", exit_proof)
        self.assertNotIn(
            "scanM4TooltipOverlay(canvas, hoverX, hoverY) === null",
            exit_proof,
        )

        for marker in (
            'M4_TOOLTIP_CASE = "ozone_tooltip_m4"',
            'M4_TOOLTIP_FIXTURE = M3_TESTDATA_DIR / "m4_ozone_tooltip_page.html"',
            '"/__m3__/m4-tooltip-fixture.html": M4_TOOLTIP_FIXTURE',
            "M4_TOOLTIP_RAPID_MOVE_MAX_GAP_MS = 250",
            "def m4_tooltip_smoke_url(",
            "def validate_m4_tooltip_result(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)

        for marker in (
            '"tooltip",',
            "M4_TOOLTIP_CASE",
            "window.__chromiumWasmM4TooltipState || null",
            '"awaiting-dom-tooltip-race"',
            '"awaiting-dom-tooltip-hover"',
            '"awaiting-dom-tooltip-exit"',
            "client.dispatch_mouse_move(click_x, click_y)",
            "client.dispatch_mouse_move(rapid_clear_x, rapid_clear_y)",
            'x_field="confirmTargetX"',
            'y_field="confirmTargetY"',
            "canvas_pointer_exit_position(",
            "client.dispatch_mouse_move(exit_x, exit_y)",
            "validate_m4_tooltip_result(result, expected_versions=versions)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)

        mouse_move = section(
            cdp,
            "    def dispatch_mouse_move(",
            "\n    def dispatch_mouse_wheel(",
        )
        for marker in (
            '"Input.dispatchMouseEvent"',
            '"type": "mouseMoved"',
            '"pointerType": "mouse"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, mouse_move)


if __name__ == "__main__":
    unittest.main()

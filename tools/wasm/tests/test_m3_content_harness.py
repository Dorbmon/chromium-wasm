#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import base64
import json
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import m3_content_server


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def make_png(
    width: int,
    height: int,
    rgba: bytes,
    *,
    color_type: int = 6,
) -> bytes:
    channels = 4 if color_type == 6 else 3
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA fixture size mismatch")
    rows = bytearray()
    for row in range(height):
        rows.append(0)
        for column in range(width):
            offset = (row * width + column) * 4
            rows.extend(rgba[offset : offset + channels])
    header = struct.pack(
        ">IIBBBBB", width, height, 8, color_type, 0, 0, 0
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + png_chunk(b"IEND", b"")
    )


def passing_result(
    png_bytes: bytes,
) -> tuple[dict[str, object], dict[str, str]]:
    versions = {
        "chromium": "chromium-revision",
        "v8": "v8-revision",
        "emscripten": "emscripten-revision",
        "port": "port-revision",
    }
    heartbeat = {
        "anchor": "data-navigation-committed",
        "elapsedMs": 3200,
        "timerDelta": 125,
        "animationFrameDelta": 181,
        "maxTimerGapMs": 31,
    }
    result: dict[str, object] = {
        "protocol": 1,
        "case": "content_shell_m3",
        "status": "pass",
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocused": True,
        "versions": versions,
        "readiness": {
            "ready": True,
            "baseReady": True,
            "interactionReady": True,
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "pageReady": True,
            "fatalErrors": [],
            "frame": {
                "id": 9,
                "width": 800,
                "height": 600,
                "timestampMs": 3150.5,
            },
            "inputPostedAtFrameId": 8,
            "interactionObservedAtFrameId": 8,
            "pageProbe": {
                "protocol": 1,
                "fixture": "chromium-wasm-m3-static-v1",
                "ready": True,
                "fontReady": True,
                "imageReady": True,
                "canvasReady": True,
                "timerTicks": 31,
                "scrollTop": 48,
                "formValue": "M3 form",
                "inputClicks": 1,
                "inputTrusted": True,
                "buttonText": "CLICKED",
                "buttonCenterX": 570,
                "buttonCenterY": 468,
            },
            "heartbeat": heartbeat,
        },
        "heartbeat": heartbeat,
        "inputResult": {
            "ok": True,
            "accepted": True,
            "code": "CLICK_POSTED",
            "eventType": "click",
            "x": 570,
            "y": 468,
            "button": 0,
        },
        "screenshot": {
            "ok": True,
            "mimeType": "image/png",
            "width": 800,
            "height": 600,
            "dataBase64": base64.b64encode(png_bytes).decode("ascii"),
        },
        "logs": {
            "host": [
                "initialize:complete",
                "resize:640x480@1",
                "resize:800x600@1",
                "input:click:570,468",
                "resize:799x600@1",
                "resize:800x600@1",
                "shutdown:accepted",
                "process:exit:0",
                "runtime:exit:0",
                "shutdown:complete",
            ],
            "stdout": [],
            "stderr": [],
        },
        "shutdown": {
            "ok": True,
            "accepted": True,
            "complete": True,
            "exitCode": 0,
            "runtimeExitCode": 0,
            "linearMemory": {
                "initialBytes": 16 * 1024 * 1024,
                "peakBytes": 24 * 1024 * 1024,
            },
        },
        "failedChecks": [],
        "error": None,
    }
    return result, versions


class M3FixtureTest(unittest.TestCase):
    def test_fixture_builds_a_self_contained_data_url(self) -> None:
        data_url = m3_content_server.build_fixture_data_url(
            "<style>@font-face{src:url(data:font/woff2;base64,"
            "__M3_AHEM_WOFF2_BASE64__)}</style><p>M3</p>",
            b"deterministic-font",
        )
        self.assertTrue(
            data_url.startswith("data:text/html;charset=utf-8;base64,")
        )
        expanded = base64.b64decode(data_url.split(",", 1)[1]).decode()
        self.assertNotIn("__M3_AHEM_WOFF2_BASE64__", expanded)
        self.assertIn(
            base64.b64encode(b"deterministic-font").decode(), expanded
        )

    def test_fixture_contains_every_m3_rendering_feature(self) -> None:
        fixture = m3_content_server.fixture_html()
        required = (
            "@font-face",
            "<img",
            "scroll-region",
            "transform:",
            "<canvas",
            "<form",
            "<input",
            "setInterval",
            'button.addEventListener("click"',
            "event.isTrusted",
            'button.textContent = "CLICKED"',
            "__chromiumWasmM3Probe",
            "chromium-wasm-m3-static-v1",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, fixture)
        self.assertEqual(
            fixture.count(m3_content_server.M3_FONT_MARKER), 1
        )

    def test_repository_fixture_and_ahem_fit_the_navigation_limit(self) -> None:
        data_url = m3_content_server.build_fixture_data_url()
        self.assertLess(
            len(data_url.encode()),
            8 * 1024 * 1024,
        )
        expanded = base64.b64decode(data_url.split(",", 1)[1]).decode()
        self.assertNotIn(m3_content_server.M3_FONT_MARKER, expanded)
        self.assertIn("<canvas", expanded)

    def test_screenshot_contract_is_narrow_and_explicit(self) -> None:
        contract = m3_content_server.load_screenshot_contract()
        self.assertEqual(contract["width"], 800)
        self.assertEqual(contract["height"], 600)
        self.assertEqual(contract["channel_tolerance"], 2)
        self.assertLessEqual(
            contract["maximum_different_pixel_ratio"], 0.0025
        )
        self.assertIn("never reports", contract["baseline_policy"])


class M3ServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temporary.name)
        (self.out_dir / "content_shell_wasm.js").write_text(
            "export default async function createModule() {}\n",
            encoding="utf-8",
        )
        (self.out_dir / "content_shell_wasm.wasm").write_bytes(b"\0asm")
        self.results: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        self.state = m3_content_server.M3ServerState(
            token="test-token",
            out_dir=self.out_dir.resolve(),
            module_name="content_shell_wasm",
            result_queue=self.results,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_server_contract_has_isolation_headers_and_wasm_mime(self) -> None:
        self.assertEqual(
            m3_content_server.SECURITY_HEADERS[
                "Cross-Origin-Opener-Policy"
            ],
            "same-origin",
        )
        self.assertEqual(
            m3_content_server.SECURITY_HEADERS[
                "Cross-Origin-Embedder-Policy"
            ],
            "require-corp",
        )
        self.assertEqual(
            m3_content_server.CONTENT_TYPES[".wasm"], "application/wasm"
        )
        host_page = (
            TOOLS_DIR / "host" / "content_shell.html"
        ).read_text(encoding="utf-8")
        self.assertIn('tabindex="0"', host_page)
        artifact = m3_content_server._artifact_for_request(
            self.state,
            "/__m3__/artifacts/content_shell_wasm.wasm",
        )
        self.assertEqual(
            artifact, (self.out_dir / "content_shell_wasm.wasm").resolve()
        )

    def test_server_rejects_artifact_traversal(self) -> None:
        self.assertIsNone(
            m3_content_server._artifact_for_request(
                self.state, "/__m3__/artifacts/../LICENSE"
            )
        )
        self.assertIsNone(
            m3_content_server._artifact_for_request(
                self.state, "/__m3__/artifacts/other.wasm"
            )
        )

    def test_server_rejects_an_artifact_symlink_outside_output(self) -> None:
        outside = self.out_dir.parent / f"{self.out_dir.name}.secret"
        outside.write_bytes(b"secret")
        symlink = self.out_dir / "content_shell_wasm.data"
        try:
            symlink.symlink_to(outside)
            self.assertIsNone(
                m3_content_server._artifact_for_request(
                    self.state,
                    "/__m3__/artifacts/content_shell_wasm.data",
                )
            )
        finally:
            symlink.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

    def test_result_endpoint_is_tokened_and_one_shot(self) -> None:
        payload = {
            "protocol": 1,
            "case": "content_shell_m3",
            "status": "fail",
        }
        self.assertTrue(
            m3_content_server.accept_result(self.state, payload)
        )
        self.assertEqual(self.results.get_nowait()["case"], "content_shell_m3")
        self.assertFalse(
            m3_content_server.accept_result(self.state, payload)
        )

    def test_result_payload_rejects_duplicate_keys_and_bool_protocol(self) -> None:
        valid_payload = (
            b'{"protocol":1,"case":"wisp_public_https_m5","status":"pass"}'
        )
        self.assertEqual(
            m3_content_server._parse_result_payload(valid_payload),
            {
                "protocol": 1,
                "case": "wisp_public_https_m5",
                "status": "pass",
            },
        )
        for payload in (
            b'{"protocol":true,"case":"wisp_public_https_m5"}',
            (
                b'{"protocol":1,"case":"wisp_public_https_m5",'
                b'"readiness":{"publicDevtoolsNetwork":{'
                b'"responseStatus":201,"responseStatus":200}}}'
            ),
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(m3_content_server._parse_result_payload(payload))


class M3ResultValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pixel = bytes((20, 40, 60, 255))
        cls.png = make_png(800, 600, pixel * (800 * 600))

    def test_complete_runtime_contract_returns_png(self) -> None:
        result, versions = passing_result(self.png)
        self.assertEqual(
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            ),
            self.png,
        )

    def test_missing_real_input_delivery_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        result["inputResult"]["ok"] = False  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "input result ok mismatch"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_untrusted_fixture_click_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        page_probe = result["readiness"]["pageProbe"]  # type: ignore[index]
        page_probe["inputTrusted"] = False
        with self.assertRaisesRegex(M0Error, "inputTrusted mismatch"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_pre_input_frame_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        result["readiness"]["frame"]["id"] = 8  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "post-interaction frame"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_frame_ids_must_be_safe_integers(self) -> None:
        for value in (9.0, True, 1 << 53):
            with self.subTest(value=value):
                result, versions = passing_result(self.png)
                result["readiness"]["frame"]["id"] = value  # type: ignore[index]
                with self.assertRaisesRegex(M0Error, "safe integer"):
                    m3_content_server.validate_m3_result(
                        result, expected_versions=versions
                    )

    def test_interaction_observed_before_input_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        result["readiness"]["interactionObservedAtFrameId"] = 7  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "before input was posted"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_posted_but_incomplete_shutdown_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        result["shutdown"]["complete"] = False  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "shutdown complete mismatch"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_missing_runtime_exit_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        del result["shutdown"]["runtimeExitCode"]  # type: ignore[index]
        with self.assertRaisesRegex(
            M0Error, "shutdown runtimeExitCode must be a safe integer"
        ):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_exit_codes_must_be_safe_integers(self) -> None:
        for value in (False, 0.0, 1 << 53):
            with self.subTest(value=value):
                result, versions = passing_result(self.png)
                result["shutdown"]["exitCode"] = value  # type: ignore[index]
                with self.assertRaisesRegex(M0Error, "safe integer"):
                    m3_content_server.validate_m3_result(
                        result, expected_versions=versions
                    )

    def test_linear_memory_bytes_must_be_positive_safe_integers(self) -> None:
        cases = (
            ("initialBytes", 0),
            ("initialBytes", float(64 * 1024)),
            ("peakBytes", 1 << 53),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                result, versions = passing_result(self.png)
                linear_memory = result["shutdown"]["linearMemory"]  # type: ignore[index]
                linear_memory[field] = value
                with self.assertRaisesRegex(
                    M0Error, "positive safe integer"
                ):
                    m3_content_server.validate_m3_result(
                        result, expected_versions=versions
                    )

    def test_linear_memory_bytes_must_be_wasm_page_aligned(self) -> None:
        result, versions = passing_result(self.png)
        linear_memory = result["shutdown"]["linearMemory"]  # type: ignore[index]
        linear_memory["peakBytes"] += 1
        with self.assertRaisesRegex(M0Error, "aligned to a 64 KiB page"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_peak_linear_memory_cannot_be_smaller_than_initial(self) -> None:
        result, versions = passing_result(self.png)
        linear_memory = result["shutdown"]["linearMemory"]  # type: ignore[index]
        linear_memory["peakBytes"] = 8 * 1024 * 1024
        with self.assertRaisesRegex(M0Error, "at least the initial bytes"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_out_of_order_runtime_exit_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        host_logs = result["logs"]["host"]  # type: ignore[index]
        process_index = host_logs.index("process:exit:0")
        runtime_index = host_logs.index("runtime:exit:0")
        host_logs[process_index], host_logs[runtime_index] = (
            host_logs[runtime_index],
            host_logs[process_index],
        )
        with self.assertRaisesRegex(M0Error, "markers are out of order"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_inner_page_timer_is_required(self) -> None:
        result, versions = passing_result(self.png)
        page_probe = result["readiness"]["pageProbe"]  # type: ignore[index]
        page_probe["timerTicks"] = 2
        with self.assertRaisesRegex(M0Error, "inner page timer"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_outer_timer_gap_is_bounded(self) -> None:
        result, versions = passing_result(self.png)
        result["heartbeat"]["maxTimerGapMs"] = 251  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "timer gap exceeded"):
            m3_content_server.validate_m3_result(
                result, expected_versions=versions
            )

    def test_outer_heartbeat_requires_committed_navigation_anchor(
        self,
    ) -> None:
        for anchor in (None, "runtime-initialized"):
            with self.subTest(anchor=anchor):
                result, versions = passing_result(self.png)
                result["heartbeat"]["anchor"] = anchor  # type: ignore[index]
                readiness = result["readiness"]  # type: ignore[assignment]
                readiness["heartbeat"]["anchor"] = anchor  # type: ignore[index]
                with self.assertRaisesRegex(
                    M0Error, "anchored to the committed data: navigation"
                ):
                    m3_content_server.validate_m3_result(
                        result, expected_versions=versions
                    )


class M3ScreenshotTest(unittest.TestCase):
    def test_decoder_accepts_canvas_rgb_and_rgba_pngs(self) -> None:
        rgba = bytes(
            (
                10, 20, 30, 255,
                40, 50, 60, 128,
            )
        )
        decoded_rgba = m3_content_server.decode_png(
            make_png(2, 1, rgba, color_type=6)
        )
        self.assertEqual(decoded_rgba.rgba, rgba)
        decoded_rgb = m3_content_server.decode_png(
            make_png(2, 1, rgba, color_type=2)
        )
        self.assertEqual(
            decoded_rgb.rgba,
            bytes((10, 20, 30, 255, 40, 50, 60, 255)),
        )

    def test_comparison_applies_channel_and_pixel_tolerances(self) -> None:
        expected_rgba = bytes((10, 20, 30, 255)) * 4
        actual_rgba = bytearray(expected_rgba)
        actual_rgba[0] += 2
        actual_rgba[4] += 3
        comparison = m3_content_server.compare_screenshots(
            make_png(2, 2, bytes(actual_rgba)),
            make_png(2, 2, expected_rgba),
            channel_tolerance=2,
            maximum_different_pixel_ratio=0.25,
        )
        self.assertTrue(comparison.matches)
        self.assertEqual(comparison.different_pixels, 1)
        self.assertEqual(comparison.different_pixel_ratio, 0.25)
        rejected = m3_content_server.compare_screenshots(
            make_png(2, 2, bytes(actual_rgba)),
            make_png(2, 2, expected_rgba),
            channel_tolerance=2,
            maximum_different_pixel_ratio=0.24,
        )
        self.assertFalse(rejected.matches)

    def test_bad_png_crc_is_rejected(self) -> None:
        png = bytearray(make_png(1, 1, bytes((1, 2, 3, 255))))
        png[-5] ^= 1
        with self.assertRaisesRegex(M0Error, "bad CRC"):
            m3_content_server.decode_png(bytes(png))


class M3HostJavaScriptTest(unittest.TestCase):
    def test_host_exposes_the_promise_api_and_bridge_contract(self) -> None:
        source = (
            TOOLS_DIR / "host" / "content_shell_host.js"
        ).read_text(encoding="utf-8")
        for method in (
            "async initialize(",
            "async resize(",
            "async loadURL(",
            "async injectInput(",
            "async requestScreenshot(",
            "async readiness(",
            "async logs(",
            "async shutdown(",
        ):
            with self.subTest(method=method):
                self.assertIn(method, source)
        self.assertIn("__chromiumWasmHostBridgeV1", source)
        self.assertIn("chromium_wasm_host_click", source)
        self.assertIn("CLICK_POSTED", source)
        self.assertIn("inputPostedAtFrameId", source)
        self.assertIn("process:exit:", source)
        self.assertIn("runtime:exit:", source)
        self.assertIn("noExitRuntime: false", source)
        self.assertIn("mainScriptUrlOrBlob", source)
        self.assertIn("await import(resolvedModule.href)", source)
        self.assertNotIn("URL.createObjectURL(moduleScriptBlob)", source)
        self.assertIn('parsed.protocol !== "data:"', source)
        self.assertIn("memory growth invalidates old views", source)

    def test_host_module_parses_as_ecmascript_module(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        source = (
            TOOLS_DIR / "host" / "content_shell_host.js"
        ).read_text(encoding="utf-8")
        completed = subprocess.run(
            [node, "--input-type=module", "--check"],
            input=source,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_host_resize_uses_logical_dips_and_bounded_dpr_backing_pixels(
        self,
    ) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        host_url = (
            TOOLS_DIR / "host" / "content_shell_host.js"
        ).resolve().as_uri()
        with tempfile.TemporaryDirectory() as temporary:
            mock_module = Path(temporary) / "m3_dpr_resize_module.mjs"
            mock_module.write_text(
                """
export default async function createModule(options) {
  options.onRuntimeInitialized();
  globalThis.__chromiumWasmHostBridgeV1.reportReadiness({
    protocol: 1,
    shellReady: true,
    surfaceReady: false,
    firstVisuallyNonEmptyPaint: false,
  });
  return {
    HEAPU8: new Uint8Array(new ArrayBuffer(64 * 1024)),
    chromiumWasmHostCommands: {
      chromium_wasm_host_resize: (width, height, devicePixelRatio) => {
        globalThis.__m3DprResizeCalls.push({
          width,
          height,
          devicePixelRatio,
        });
        return 1;
      },
      chromium_wasm_host_shutdown: () => {
        queueMicrotask(() => {
          globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({
            protocol: 1,
            exitCode: 0,
          });
          options.onExit(0);
        });
        return 1;
      },
    },
  };
}
""",
                encoding="utf-8",
            )
            script = f"""
globalThis.window = globalThis;
globalThis.location = {{origin: "null"}};
globalThis.crossOriginIsolated = true;
globalThis.__m3DprResizeCalls = [];
globalThis.addEventListener = () => {{}};
globalThis.removeEventListener = () => {{}};
globalThis.requestAnimationFrame =
  (callback) => setTimeout(() => callback(performance.now()), 1);
globalThis.cancelAnimationFrame = (handle) => clearTimeout(handle);
class TestCanvas {{
  constructor() {{
    this.width = 800;
    this.height = 600;
    this.style = {{}};
  }}
  focus() {{
    document.activeElement = this;
  }}
  toDataURL() {{
    return "data:image/png;base64,iVBORw0KGgo=";
  }}
}}
globalThis.HTMLCanvasElement = TestCanvas;
globalThis.document = {{
  activeElement: null,
  baseURI: "file:///",
  querySelector: () => null,
}};

const {{ChromiumWasmM3Host}} = await import({json.dumps(host_url)});
const canvas = new TestCanvas();
const host = new ChromiumWasmM3Host(canvas, {{
  chromium: "c",
  v8: "v",
  emscripten: "e",
  port: "p",
}});
await host.initialize({{modulePath: {json.dumps(mock_module.as_uri())}}});

const oneX = await host.resize(800, 600, 1);
const twoX = await host.resize(800, 600, 2);
if (
  oneX.ok !== true || oneX.width !== 800 || oneX.height !== 600 ||
  oneX.devicePixelRatio !== 1 || oneX.physicalWidth !== 800 ||
  oneX.physicalHeight !== 600 || twoX.ok !== true || twoX.width !== 800 ||
  twoX.height !== 600 || twoX.devicePixelRatio !== 2 ||
  twoX.physicalWidth !== 1600 || twoX.physicalHeight !== 1200 ||
  canvas.width !== 1600 || canvas.height !== 1200 ||
  canvas.style.width !== "800px" || canvas.style.height !== "600px"
) {{
  throw new Error("DPR resize did not preserve CSS dimensions and scale backing pixels");
}}
let legacyInputRejected = false;
try {{
  await host.injectInput({{type: "click", x: 570, y: 468, button: 0}});
}} catch (error) {{
  legacyInputRejected = String(error).includes(
    "M3 input only supports devicePixelRatio 1");
}}
if (!legacyInputRejected) {{
  throw new Error("legacy M3 direct input was not rejected at DPR 2");
}}

globalThis.__chromiumWasmHostBridgeV1.reportFrame({{
  protocol: 1,
  id: 1,
  width: 1600,
  height: 1200,
  timestampMs: 1,
}});
const screenshot = await host.requestScreenshot();
if (
  screenshot.width !== 1600 || screenshot.height !== 1200 ||
  screenshot.frame.width !== 1600 || screenshot.frame.height !== 1200
) {{
  throw new Error("DPR screenshot dimensions were not physical backing pixels");
}}

const restored = await host.resize(800, 600, 1);
if (
  restored.physicalWidth !== 800 || restored.physicalHeight !== 600 ||
  canvas.width !== 800 || canvas.height !== 600 ||
  canvas.style.width !== "800px" || canvas.style.height !== "600px"
) {{
  throw new Error("DPR resize did not restore the one-times backing store");
}}

for (const [args, expectedMessage] of [
  [[800, 600, 1.5], "devicePixelRatio 1 or 2"],
  [[800, 600, 3], "devicePixelRatio 1 or 2"],
  [[8193, 1, 2], "physical canvas exceeds the host storage limit"],
  [[2049, 2048, 2], "physical canvas exceeds the host storage limit"],
]) {{
  let rejected = false;
  try {{
    await host.resize(...args);
  }} catch (error) {{
    rejected = String(error).includes(expectedMessage);
  }}
  if (!rejected) {{
    throw new Error("host accepted unsupported DPR resize " + JSON.stringify(args));
  }}
}}

const expectedCalls = JSON.stringify([
  {{width: 800, height: 600, devicePixelRatio: 1}},
  {{width: 800, height: 600, devicePixelRatio: 2}},
  {{width: 800, height: 600, devicePixelRatio: 1}},
]);
if (JSON.stringify(globalThis.__m3DprResizeCalls) !== expectedCalls) {{
  throw new Error("host did not forward logical dimensions and the exact DPR");
}}

const shutdown = await host.shutdown();
if (shutdown.complete !== true || shutdown.runtimeExitCode !== 0) {{
  throw new Error("DPR resize host did not shut down cleanly");
}}
console.log("M3_DPR_RESIZE_CONTRACT:PASS");
"""
            completed = subprocess.run(
                [node, "--input-type=module"],
                input=script,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("M3_DPR_RESIZE_CONTRACT:PASS", completed.stdout)

    def test_heartbeat_window_ignores_pre_navigation_time(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        host_url = (
            TOOLS_DIR / "host" / "content_shell_host.js"
        ).resolve().as_uri()
        with tempfile.TemporaryDirectory() as temporary:
            mock_module = Path(temporary) / "m3_heartbeat_module.mjs"
            mock_module.write_text(
                """
export default async function createModule(options) {
  options.onRuntimeInitialized();
  globalThis.__chromiumWasmHostBridgeV1.reportReadiness({
    protocol: 1,
    shellReady: true,
    surfaceReady: false,
    firstVisuallyNonEmptyPaint: false,
  });
  return {
    HEAPU8: new Uint8Array(new ArrayBuffer(64 * 1024)),
  };
}
""",
                encoding="utf-8",
            )
            script = f"""
let now = 0;
let timerCallback = null;
let animationFrameCallback = null;
let nextHandle = 1;
globalThis.performance = {{now: () => now}};
globalThis.setInterval = (callback) => {{
  timerCallback = callback;
  return nextHandle++;
}};
globalThis.clearInterval = () => {{}};
globalThis.requestAnimationFrame = (callback) => {{
  animationFrameCallback = callback;
  return nextHandle++;
}};
globalThis.cancelAnimationFrame = () => {{}};
globalThis.window = globalThis;
globalThis.location = {{origin: "null"}};
globalThis.crossOriginIsolated = true;
globalThis.addEventListener = () => {{}};
globalThis.removeEventListener = () => {{}};
class TestCanvas {{
  constructor() {{
    this.width = 800;
    this.height = 600;
    this.style = {{}};
  }}
  focus() {{
    document.activeElement = this;
  }}
}}
globalThis.HTMLCanvasElement = TestCanvas;
globalThis.document = {{
  activeElement: null,
  baseURI: "file:///",
  querySelector: () => null,
}};

function advanceHeartbeat(milliseconds, steps) {{
  const step = milliseconds / steps;
  for (let index = 0; index < steps; ++index) {{
    now += step;
    timerCallback();
    const callback = animationFrameCallback;
    callback(now);
  }}
}}

const {{ChromiumWasmM3Host}} = await import({json.dumps(host_url)});
const host = new ChromiumWasmM3Host(new TestCanvas(), {{
  chromium: "c",
  v8: "v",
  emscripten: "e",
  port: "p",
}});
await host.initialize({{modulePath: {json.dumps(mock_module.as_uri())}}});

advanceHeartbeat(5000, 250);
const beforeCommit = await host.readiness();
if (
  beforeCommit.heartbeat.anchor !== null ||
  beforeCommit.heartbeat.elapsedMs !== 0 ||
  beforeCommit.heartbeat.timerDelta !== 0 ||
  beforeCommit.heartbeat.animationFrameDelta !== 0
) {{
  throw new Error("pre-navigation time leaked into the M3 heartbeat gate");
}}

globalThis.__chromiumWasmHostBridgeV1.reportNavigation({{
  protocol: 1,
  committed: true,
  scheme: "data",
}});
const atCommit = await host.readiness();
if (
  atCommit.heartbeat.anchor !== "data-navigation-committed" ||
  atCommit.heartbeat.elapsedMs !== 0 ||
  atCommit.heartbeat.timerDelta !== 0 ||
  atCommit.heartbeat.animationFrameDelta !== 0
) {{
  throw new Error("M3 heartbeat did not reset at navigation commit");
}}

advanceHeartbeat(3200, 200);
const afterWindow = await host.readiness();
if (
  afterWindow.heartbeat.elapsedMs !== 3200 ||
  afterWindow.heartbeat.timerDelta !== 200 ||
  afterWindow.heartbeat.animationFrameDelta !== 200 ||
  afterWindow.heartbeat.maxTimerGapMs > 250
) {{
  throw new Error("M3 heartbeat did not measure the post-commit window");
}}
console.log("M3_HEARTBEAT_WINDOW:PASS");
"""
            completed = subprocess.run(
                [node, "--input-type=module"],
                input=script,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("M3_HEARTBEAT_WINDOW:PASS", completed.stdout)

    def test_host_promise_api_executes_against_a_contract_module(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        host_url = (
            TOOLS_DIR / "host" / "content_shell_host.js"
        ).resolve().as_uri()
        with tempfile.TemporaryDirectory() as temporary:
            mock_module = Path(temporary) / "m3_contract_module.mjs"
            mock_module.write_text(
                """
export default async function createModule(options) {
  options.onRuntimeInitialized();
  globalThis.__chromiumWasmHostBridgeV1.reportReadiness({
    protocol: 1,
    shellReady: true,
    surfaceReady: false,
    firstVisuallyNonEmptyPaint: false,
  });
  const module = {
    HEAPU8: new Uint8Array(new ArrayBuffer(64 * 1024)),
    chromiumWasmHostCommands: {
      chromium_wasm_host_resize: () => 1,
      chromium_wasm_host_load_url: () => 1,
      chromium_wasm_host_click: () => {
        globalThis.__m3MockClickCalls += 1;
        return 1;
      },
      chromium_wasm_host_shutdown: () => {
        module.HEAPU8 = new Uint8Array(new ArrayBuffer(2 * 64 * 1024));
        queueMicrotask(() => {
          const reportProcessExit = () => {
            globalThis.__chromiumWasmHostBridgeV1.reportProcessExit({
              protocol: 1,
              exitCode: 0,
            });
          };
          if (globalThis.__m3MockReverseExitOrder) {
            options.onExit(0);
            reportProcessExit();
          } else {
            reportProcessExit();
            options.onExit(0);
          }
        });
        return 1;
      },
    },
  };
  return module;
}
""",
                encoding="utf-8",
            )
            script = f"""
globalThis.window = globalThis;
globalThis.location = {{origin: "null"}};
globalThis.crossOriginIsolated = true;
globalThis.__m3MockClickCalls = 0;
globalThis.__m3MockReverseExitOrder = false;
globalThis.addEventListener = () => {{}};
globalThis.removeEventListener = () => {{}};
globalThis.requestAnimationFrame =
  (callback) => setTimeout(() => callback(performance.now()), 1);
globalThis.cancelAnimationFrame = (handle) => clearTimeout(handle);
class TestCanvas {{
  constructor() {{
    this.width = 800;
    this.height = 600;
    this.style = {{}};
  }}
  focus() {{
    document.activeElement = this;
  }}
  toDataURL() {{
    return "data:image/png;base64,iVBORw0KGgo=";
  }}
}}
globalThis.HTMLCanvasElement = TestCanvas;
globalThis.document = {{
  activeElement: null,
  baseURI: "file:///",
  querySelector: () => null,
}};

const {{ChromiumWasmM3Host}} = await import({json.dumps(host_url)});

async function exerciseInteraction(frameBeforeProbe) {{
  const canvas = new TestCanvas();
  const host = new ChromiumWasmM3Host(canvas, {{
    chromium: "c",
    v8: "v",
    emscripten: "e",
    port: "p",
  }});
  await host.initialize({{modulePath: {json.dumps(mock_module.as_uri())}}});
  await host.resize(800, 600, 1);
  await host.loadURL("data:text/html,%3Cp%3EM3%3C%2Fp%3E");
  globalThis.__chromiumWasmHostBridgeV1.reportFrame({{
    protocol: 1,
    id: 1,
    width: 800,
    height: 600,
    timestampMs: 1,
  }});
  globalThis.__chromiumWasmHostBridgeV1.reportReadiness({{
    protocol: 1,
    shellReady: true,
    surfaceReady: true,
    firstVisuallyNonEmptyPaint: true,
  }});
  globalThis.__chromiumWasmHostBridgeV1.reportNavigation({{
    protocol: 1,
    committed: true,
    scheme: "data",
  }});
  globalThis.__chromiumWasmHostBridgeV1.reportPageProbe({{
    protocol: 1,
    fixture: "chromium-wasm-m3-static-v1",
    ready: true,
    fontReady: true,
    imageReady: true,
    canvasReady: true,
    timerTicks: 3,
    scrollTop: 48,
    formValue: "M3 form",
    inputClicks: 0,
    inputTrusted: false,
    buttonText: "READY",
    buttonCenterX: 570,
    buttonCenterY: 468,
  }});
  const baseReadiness = await host.readiness();
  const input = await host.injectInput({{
    type: "click",
    x: 570,
    y: 468,
    button: 0,
  }});
  const reportClickedProbe = () => {{
    globalThis.__chromiumWasmHostBridgeV1.reportPageProbe({{
      protocol: 1,
      fixture: "chromium-wasm-m3-static-v1",
      ready: true,
      fontReady: true,
      imageReady: true,
      canvasReady: true,
      timerTicks: 3,
      scrollTop: 48,
      formValue: "M3 form",
      inputClicks: 1,
      inputTrusted: true,
      buttonText: "CLICKED",
      buttonCenterX: 570,
      buttonCenterY: 468,
    }});
  }};
  let nextFrameId = 2;
  const reportFrame = (width, height) => {{
    globalThis.__chromiumWasmHostBridgeV1.reportFrame({{
      protocol: 1,
      id: nextFrameId,
      width,
      height,
      timestampMs: nextFrameId,
    }});
    nextFrameId += 1;
  }};
  if (frameBeforeProbe) {{
    reportFrame(800, 600);
    reportClickedProbe();
    const staleReadiness = await host.readiness();
    if (
      staleReadiness.interactionReady !== false ||
      staleReadiness.interactionObservedAtFrameId !== 2
    ) {{
      throw new Error("M3 accepted a frame older than click observation");
    }}
  }} else {{
    reportClickedProbe();
  }}
  await host.resize(799, 600, 1);
  reportFrame(799, 600);
  await host.resize(800, 600, 1);
  reportFrame(800, 600);
  const readiness = await host.readiness();
  const screenshot = await host.requestScreenshot();
  const shutdown = await host.shutdown();
  if (
    baseReadiness.baseReady !== true ||
    readiness.shellReady !== true ||
    readiness.surfaceReady !== true ||
    readiness.interactionReady !== true ||
    readiness.inputPostedAtFrameId !== 1 ||
    readiness.interactionObservedAtFrameId !==
      (frameBeforeProbe ? 2 : 1) ||
    readiness.frame.id !== (frameBeforeProbe ? 4 : 3) ||
    screenshot.mimeType !== "image/png" ||
    input.code !== "CLICK_POSTED" ||
    shutdown.complete !== true ||
    shutdown.runtimeExitCode !== 0 ||
    shutdown.linearMemory.initialBytes !== 64 * 1024 ||
    shutdown.linearMemory.peakBytes !== 2 * 64 * 1024
  ) {{
    throw new Error(
      "M3 Promise API contract failed for frameBeforeProbe=" +
      String(frameBeforeProbe));
  }}
}}

async function exerciseStaleInputRejection() {{
  const host = new ChromiumWasmM3Host(new TestCanvas(), {{
    chromium: "c",
    v8: "v",
    emscripten: "e",
    port: "p",
  }});
  await host.initialize({{modulePath: {json.dumps(mock_module.as_uri())}}});
  globalThis.__chromiumWasmHostBridgeV1.reportPageProbe({{
    protocol: 1,
    fixture: "chromium-wasm-m3-static-v1",
    inputClicks: 1,
    inputTrusted: true,
    buttonText: "CLICKED",
  }});
  const clickCallsBefore = globalThis.__m3MockClickCalls;
  let rejected = false;
  try {{
    await host.injectInput({{
      type: "click",
      x: 570,
      y: 468,
      button: 0,
    }});
  }} catch (error) {{
    rejected = String(error).includes("pristine READY fixture probe");
  }}
  if (!rejected || globalThis.__m3MockClickCalls !== clickCallsBefore) {{
    throw new Error("M3 accepted stale trusted fixture state");
  }}
  await host.shutdown();
}}

async function exerciseReversedShutdownRejection() {{
  const host = new ChromiumWasmM3Host(new TestCanvas(), {{
    chromium: "c",
    v8: "v",
    emscripten: "e",
    port: "p",
  }});
  await host.initialize({{modulePath: {json.dumps(mock_module.as_uri())}}});
  globalThis.__m3MockReverseExitOrder = true;
  let rejected = false;
  try {{
    await host.shutdown();
  }} catch (error) {{
    rejected = String(error).includes(
      "runtime exited before Content Shell completed");
  }} finally {{
    globalThis.__m3MockReverseExitOrder = false;
  }}
  if (!rejected) {{
    throw new Error("M3 accepted reversed shutdown completion");
  }}
}}

await exerciseInteraction(false);
await exerciseInteraction(true);
await exerciseStaleInputRejection();
await exerciseReversedShutdownRejection();
console.log("M3_HOST_CONTRACT:PASS");
"""
            completed = subprocess.run(
                [node, "--input-type=module"],
                input=script,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("M3_HOST_CONTRACT:PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()

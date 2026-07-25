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
            "runtimeInitialized": True,
            "shellReady": True,
            "surfaceReady": True,
            "navigationCommitted": True,
            "firstVisuallyNonEmptyPaint": True,
            "pageReady": True,
            "fatalErrors": [],
            "frame": {
                "id": 7,
                "width": 800,
                "height": 600,
                "timestampMs": 3150.5,
            },
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
            },
            "heartbeat": heartbeat,
        },
        "heartbeat": heartbeat,
        "inputResult": {
            "ok": False,
            "code": "INPUT_UNSUPPORTED_UNTIL_M4",
            "milestone": "M4",
            "eventType": "pointerDown",
        },
        "screenshot": {
            "ok": True,
            "mimeType": "image/png",
            "width": 800,
            "height": 600,
            "dataBase64": base64.b64encode(png_bytes).decode("ascii"),
        },
        "logs": {
            "host": ["initialize:complete", "shutdown:accepted"],
            "stdout": [],
            "stderr": [],
        },
        "shutdown": {"ok": True, "accepted": True},
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

    def test_fake_input_success_is_rejected(self) -> None:
        result, versions = passing_result(self.png)
        result["inputResult"]["ok"] = True  # type: ignore[index]
        with self.assertRaisesRegex(M0Error, "input result ok mismatch"):
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
        self.assertIn("INPUT_UNSUPPORTED_UNTIL_M4", source)
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
  return {
    chromiumWasmHostCommands: {
      chromium_wasm_host_resize: () => 1,
      chromium_wasm_host_load_url: () => 1,
      chromium_wasm_host_shutdown: () => 1,
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
}});
const readiness = await host.readiness();
const screenshot = await host.requestScreenshot();
const input = await host.injectInput({{type: "pointerDown"}});
const shutdown = await host.shutdown();
if (
  readiness.shellReady !== true ||
  readiness.surfaceReady !== true ||
  screenshot.mimeType !== "image/png" ||
  input.code !== "INPUT_UNSUPPORTED_UNTIL_M4" ||
  shutdown.ok !== true
) {{
  throw new Error("M3 Promise API contract failed");
}}
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

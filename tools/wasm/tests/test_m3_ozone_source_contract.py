#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class M3OzoneSourceContractTest(unittest.TestCase):
    def test_wasm_is_the_only_m3_ozone_platform(self) -> None:
        config = source("build/config/ozone.gni")
        ozone = source("ui/ozone/BUILD.gn")

        self.assertIn("ozone_auto_platforms = use_ozone && !is_wasm", config)
        self.assertIn('ozone_platform = "wasm"', config)
        self.assertIn(
            "ozone_platform_wasm = is_wasm && enable_chromium_wasm_content",
            config,
        )
        self.assertIn("if (ozone_platform_wasm)", ozone)
        self.assertIn('ozone_platforms += [ "wasm" ]', ozone)
        self.assertIn('ozone_platform_deps += [ "platform/wasm" ]', ozone)

    def test_platform_requires_single_process_and_rejects_native_paths(
        self,
    ) -> None:
        platform = source("ui/ozone/platform/wasm/ozone_platform_wasm.cc")
        factory = source("ui/ozone/platform/wasm/wasm_surface_factory.cc")

        for marker in (
            "class OzonePlatformWasmImpl final",
            "if (!params.single_process)",
            "CHECK(params.single_process)",
            "runtime_properties_.supports_overlays = false",
            "runtime_properties_.supports_native_pixmaps = false",
            "CreateSystemInputInjector() override",
            "CreateNativeDisplayDelegate() override",
            "return new OzonePlatformWasmImpl();",
            "CreateStubClientNativePixmapFactory()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, platform)
        self.assertNotIn("CreateOzonePlatformHeadless", platform)

        self.assertIn("return {};", factory)
        self.assertIn("return nullptr;", factory)
        self.assertIn("Native pixmaps are unsupported", factory)
        self.assertIn("canvas_active_->exchange(true", factory)
        self.assertIn("one live compositor surface", factory)

    def test_wasm_ui_fallbacks_are_explicit_and_non_native(self) -> None:
        text_elider = source("ui/gfx/text_elider.cc")
        vector_icon = source("ui/gfx/paint_vector_icon.cc")
        pixmap = source("ui/gfx/native_pixmap_handle.cc")
        pixmap_traits = source(
            "ui/gfx/mojom/native_handle_types_mojom_traits.cc"
        )
        platform_handle_wasm = source(
            "mojo/public/cpp/platform/platform_handle_wasm.cc"
        )
        ui_base_build = source("ui/base/BUILD.gn")
        exchange_factory = source(
            "ui/base/dragdrop/os_exchange_data_provider_factory.cc"
        )

        filename_setup = text_elider.split(
            "std::u16string ElideFilename", 1
        )[1].split("const float full_width", 1)[0]
        self.assertIn("BUILDFLAG(IS_WASM)", filename_setup)
        self.assertIn("SysNativeMBToWide", filename_setup)

        self.assertEqual(
            vector_icon.count("value_or(SkPoint{0, 0})"),
            3,
        )
        self.assertNotIn("value_or({0, 0})", vector_icon)

        self.assertIn(
            "Native pixmap handle cloning is unsupported on Wasm",
            pixmap,
        )
        self.assertIn(
            "Mojo native pixmap transport is unsupported on Wasm",
            pixmap_traits,
        )
        self.assertIn(
            "Native pixmap plane deserialization is unsupported by",
            pixmap_traits,
        )
        self.assertIn("CHECK(handle.planes.empty())", pixmap)
        self.assertIn("CHECK(false)", pixmap_traits)
        self.assertIn("return false;", pixmap_traits)
        self.assertEqual(
            platform_handle_wasm.count(
                "Native platform handles are unsupported in WebAssembly"
            ),
            1,
        )
        self.assertIn(
            "handle->type != "
            "MOJO_PLATFORM_HANDLE_TYPE_WASM_SHARED_MEMORY",
            platform_handle_wasm,
        )
        self.assertIn(
            "Invalid or consumed Wasm shared-memory transport token",
            platform_handle_wasm,
        )

        self.assertIn(
            "is_fuchsia || is_wasm",
            ui_base_build,
        )
        self.assertIn(
            "WebAssembly has no host drag-and-drop integration",
            exchange_factory,
        )
        self.assertIn(
            "return std::make_unique<OSExchangeDataProviderNonBacked>();",
            exchange_factory,
        )

    def test_clipboard_stays_process_local_until_host_integration(self) -> None:
        build = source("ui/base/clipboard/BUILD.gn")
        factory = source(
            "ui/base/clipboard/clipboard_factory_ozone.cc"
        )

        wasm_sources = build.split(
            'sources += [ "clipboard_factory_ozone.cc" ]', 1
        )[1].split("deps +=", 1)[0]
        self.assertIn("if (!is_wasm)", wasm_sources)
        self.assertIn('"clipboard_ozone.cc"', wasm_sources)
        self.assertIn("BUILDFLAG(IS_WASM)", factory)
        self.assertIn(
            "return new ClipboardNonBacked;",
            factory,
        )
        self.assertIn(
            "Host clipboard integration is outside the M3 gate",
            factory,
        )

    def test_window_cursor_controls_and_host_decorations_are_explicitly_scoped(
        self,
    ) -> None:
        window = source("ui/ozone/platform/wasm/wasm_window.cc")
        screen = source("ui/ozone/platform/wasm/wasm_screen.cc")

        for message in (
            "Host cursor movement is unsupported by the M4 pointer slice",
            "Host cursor confinement is unsupported by the M4 pointer slice",
            "ozone_wasm M3 has no host-native title surface",
            "ozone_wasm M3 has no host-native window icon surface",
        ):
            with self.subTest(message=message):
                self.assertIn(message, window)
        self.assertIn("chromium_wasm_report_ozone_cursor", window)
        self.assertIn("BitmapCursor::FromPlatformCursor", window)
        self.assertIn("host cannot present raster custom cursors", window)
        self.assertNotIn(
            "Host cursor updates are unsupported by the M4 pointer slice", window
        )
        self.assertNotIn(
            "Host cursor position is unsupported by the M4 pointer slice",
            screen,
        )

    def test_software_surface_bounds_both_owned_frame_copies(self) -> None:
        canvas = source(
            "ui/ozone/platform/wasm/wasm_surface_ozone_canvas.cc"
        )
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")

        for marker in (
            "kMaximumCanvasDimension = 16384",
            "kMaximumCanvasStorageBytes = 128 * 1024 * 1024",
            "base::CheckedNumeric<size_t>",
            "storage_size *= 2",
            "storage_size.ValueOrDie<size_t>()",
            "surface_.reset()",
            "std::vector<uint8_t>().swap(rgba_pixels_)",
            "SkSurfaces::Raster(",
            "surface_->readPixels",
            "chromium_wasm_present_frame(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, canvas)
        storage_mib = int(
            re.search(
                r"kMaximumCanvasStorageBytes = (\d+) \* 1024 \* 1024",
                canvas,
            ).group(1)
        )
        frame_mib = int(
            re.search(
                r"maximumFrameBytes: (\d+) \* 1024 \* 1024",
                bridge,
            ).group(1)
        )
        self.assertEqual(storage_mib, 2 * frame_mib)

    def test_versioned_bridge_validates_before_host_allocation(self) -> None:
        bridge = source("ui/ozone/platform/wasm/wasm_host_bridge.js")

        validation = bridge.index("const byteLength = stride * height;")
        canvas_lookup = bridge.index("const canvas = Module['canvas'];")
        self.assertLess(validation, canvas_lookup)
        for marker in (
            "version: 1",
            "maximumCanvasDimension: 16384",
            "maximumFrameBytes: 64 * 1024 * 1024",
            "Number.isSafeInteger(pixels)",
            "Number.isSafeInteger(frameId)",
            "byteLength > ChromiumWasmHostBridge.maximumFrameBytes",
            "end > HEAPU8.length",
            "chromium_wasm_present_frame__proxy: 'sync'",
            "ChromiumWasmHostBridge.imageData.data.set(",
            "HEAPU8.subarray(pixels, end)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, bridge)
        self.assertNotIn("ChromiumWasmHostBridge.heapView", bridge)

    def test_bridge_copies_current_heap_after_memory_growth(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")

        bridge_source = source("ui/ozone/platform/wasm/wasm_host_bridge.js")
        script = f"""
const LibraryManager = {{library: {{}}}};
const mergeInto = (target, additions) => Object.assign(target, additions);
let ChromiumWasmHostBridge;
let HEAPU8 = new Uint8Array(64);
const frames = [];
const readiness = [];
const puts = [];
const context = {{
  createImageData(width, height) {{
    return {{
      width,
      height,
      data: new Uint8ClampedArray(width * height * 4),
    }};
  }},
  putImageData(imageData) {{
    puts.push(Array.from(imageData.data));
  }},
}};
class TestCanvas {{
  constructor() {{
    this.width = 0;
    this.height = 0;
  }}
  getContext(kind, options) {{
    if (kind !== '2d' || options.alpha !== false) {{
      throw new Error('unexpected canvas context request');
    }}
    return context;
  }}
}}
globalThis.HTMLCanvasElement = TestCanvas;
globalThis.CustomEvent = class {{
  constructor(type, options) {{
    this.type = type;
    this.detail = options.detail;
  }}
}};
globalThis.dispatchEvent = () => true;
const Module = {{canvas: new TestCanvas()}};
globalThis.__chromiumWasmHostBridgeV1 = {{
  protocol: 1,
  reportFrame(frame) {{
    frames.push(frame);
  }},
  reportReadiness(update) {{
    readiness.push(update);
  }},
}};

eval({json.dumps(bridge_source)});
ChromiumWasmHostBridge = LibraryManager.library.$ChromiumWasmHostBridge;
const present = LibraryManager.library.chromium_wasm_present_frame;

HEAPU8.set([1, 2, 3, 4, 5, 6, 7, 8,
            9, 10, 11, 12, 13, 14, 15, 16], 4);
if (present(1, 4, 2, 2, 8, 1, 1.5) !== 1) {{
  throw new Error('valid frame was rejected');
}}

HEAPU8 = new Uint8Array(128);
HEAPU8.set([16, 15, 14, 13, 12, 11, 10, 9,
           8, 7, 6, 5, 4, 3, 2, 1], 68);
if (present(1, 68, 2, 2, 8, 2, 2.5) !== 1) {{
  throw new Error('post-growth frame was rejected');
}}

const putsBeforeRejects = puts.length;
const widthBeforeRejects = Module.canvas.width;
if (present(1, 0, 16385, 1, 16385 * 4, 3, 3.5) !== 0 ||
    present(1, 120, 2, 2, 8, 3, 3.5) !== 0 ||
    present(2, 0, 2, 2, 8, 3, 3.5) !== 0) {{
  throw new Error('invalid frame was accepted');
}}
if (puts.length !== putsBeforeRejects ||
    Module.canvas.width !== widthBeforeRejects) {{
  throw new Error('invalid frame mutated the canvas');
}}
if (puts.length !== 2 || frames.length !== 2 || readiness.length !== 2 ||
    puts[0][0] !== 1 || puts[1][0] !== 16) {{
  throw new Error('frame copy contract failed');
}}
console.log('M3_OZONE_BRIDGE:PASS');
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
        self.assertIn("M3_OZONE_BRIDGE:PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()

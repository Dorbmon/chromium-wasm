#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3GpuImageTransportSourceContractTest(unittest.TestCase):
    def test_wasm_selects_an_explicit_software_only_boundary(self) -> None:
        build = source("gpu/ipc/service/BUILD.gn")
        implementation = source(
            "gpu/ipc/service/image_transport_surface_wasm.cc"
        )
        interface = source("gpu/ipc/service/image_transport_surface.h")

        self.assertIn(
            'if (is_wasm) {\n'
            '    sources += [ "image_transport_surface_wasm.cc" ]',
            build,
        )
        self.assertIn(
            'if (is_linux || is_chromeos) {\n'
            '    sources += [ "image_transport_surface_linux.cc" ]',
            build,
        )
        self.assertEqual(
            interface.count(
                "On failure, a null\n  // scoped_refptr should be returned."
            ),
            2,
        )
        self.assertIn(
            "ImageTransportSurface::CreatePresenter(", implementation
        )
        self.assertIn(
            "ImageTransportSurface::CreateNativeGLSurface(", implementation
        )
        self.assertEqual(implementation.count("return nullptr;"), 2)
        self.assertIn(
            "M3 presents software compositor frames through Ozone Wasm",
            implementation,
        )
        self.assertNotIn("gl::init::", implementation)
        self.assertNotIn("GLSurfaceStub", implementation)
        self.assertNotIn("MakeRefCounted", implementation)


if __name__ == "__main__":
    unittest.main()

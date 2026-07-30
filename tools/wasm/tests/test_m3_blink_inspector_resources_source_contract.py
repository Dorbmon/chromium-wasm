#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3BlinkInspectorResourcesSourceContractTest(unittest.TestCase):
    def test_public_buildflag_matches_the_resource_generator_gate(self) -> None:
        build = source("third_party/blink/public/BUILD.gn")

        self.assertIn(
            "_enable_blink_devtools_resources =\n"
            "    !is_wasm || enable_chromium_wasm_devtools_resources",
            build,
        )
        self.assertIn(
            '"ENABLE_BLINK_DEVTOOLS_INSPECTOR_RESOURCES='
            '$_enable_blink_devtools_resources",',
            build,
        )
        self.assertIn(
            "if (_enable_blink_devtools_resources) {\n"
            '  grit("devtools_inspector_resources")',
            build,
        )

    def test_inspect_tools_does_not_depend_on_an_unused_resource_map(
        self,
    ) -> None:
        inspect_tools = source(
            "third_party/blink/renderer/core/inspector/inspect_tools.cc"
        )

        self.assertNotIn(
            "inspector_overlay_resources_map.h",
            inspect_tools,
        )
        self.assertNotIn("IDR_INSPECT_TOOL_MAIN_JS", inspect_tools)

    def test_overlay_reports_omitted_resources_before_claiming_success(
        self,
    ) -> None:
        implementation = source(
            "third_party/blink/renderer/core/inspector/"
            "inspector_overlay_agent.cc"
        )
        header = source(
            "third_party/blink/renderer/core/inspector/"
            "inspector_overlay_agent.h"
        )

        self.assertIn(
            "#if BUILDFLAG(ENABLE_BLINK_DEVTOOLS_INSPECTOR_RESOURCES)\n"
            '#include "third_party/blink/public/resources/grit/'
            'inspector_overlay_resources_map.h"\n'
            "#endif",
            implementation,
        )
        self.assertIn(
            "protocol::Response InspectorOverlayAgent::"
            "LoadOverlayPageResource() {\n"
            "#if !BUILDFLAG("
            "ENABLE_BLINK_DEVTOOLS_INSPECTOR_RESOURCES)\n"
            "  return protocol::Response::ServerError(\n"
            '      "Inspector overlay resources are unavailable in this '
            'build.");',
            implementation,
        )
        self.assertIn(
            "protocol::Response LoadOverlayPageResource();",
            header,
        )
        self.assertEqual(
            implementation.count(
                "protocol::Response response = LoadOverlayPageResource();\n"
                "  if (!response.IsSuccess()) {"
            ),
            2,
        )
        self.assertIn(
            "hinge_ = nullptr;\n    return response;",
            implementation,
        )
        self.assertIn(
            "inspect_tool_ = nullptr;\n    return response;",
            implementation,
        )


if __name__ == "__main__":
    unittest.main()

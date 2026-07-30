#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


def braced_block(contents: str, marker: str) -> str:
    marker_index = contents.index(marker)
    open_brace = contents.index("{", marker_index + len(marker))
    depth = 0
    for index in range(open_brace, len(contents)):
        if contents[index] == "{":
            depth += 1
        elif contents[index] == "}":
            depth -= 1
            if depth == 0:
                return contents[open_brace + 1 : index]
    raise AssertionError(f"unterminated block after {marker}")


class M3PermissionBoundaryContractTest(unittest.TestCase):
    def test_shell_preserves_origin_resolution_without_permissions_component(
        self,
    ) -> None:
        manager = source(
            "content/shell/browser/shell_permission_manager.cc"
        )
        origin_helper = braced_block(
            manager,
            "GURL GetLastCommittedOriginAsURL(",
        )

        self.assertNotIn(
            "components/permissions/permission_util.h",
            manager,
        )
        self.assertNotIn("permissions::PermissionUtil", manager)
        self.assertIn("CHECK(render_frame_host);", origin_helper)
        self.assertIn(
            "WebContents::FromRenderFrameHost(render_frame_host)",
            origin_helper,
        )

        android_file_origin = origin_helper.split(
            "#if BUILDFLAG(IS_ANDROID)", 1
        )[1].split("#endif", 1)[0]
        self.assertIn(
            "allow_universal_access_from_file_urls",
            android_file_origin,
        )
        self.assertIn("SchemeIsFile()", android_file_origin)
        self.assertIn(
            "GetLastCommittedURL().DeprecatedGetOriginAsURL()",
            android_file_origin,
        )
        self.assertIn(
            "UmaHistogramBoolean(kIsFileURLHistogram, true)",
            android_file_origin,
        )
        self.assertIn(
            "UmaHistogramBoolean(kIsFileURLHistogram, false)",
            android_file_origin,
        )

        self.assertIn(
            "render_frame_host->GetLastCommittedOrigin().GetURL()",
            origin_helper,
        )
        self.assertIn(
            "origin.is_empty() && "
            "render_frame_host->IsInPrimaryMainFrame()",
            origin_helper,
        )
        self.assertIn(
            "origin = web_contents->GetVisibleURL();",
            origin_helper,
        )
        self.assertEqual(
            manager.count("GetLastCommittedOriginAsURL("),
            4,
        )

    def test_wasm_shell_drops_only_the_desktop_permissions_dependency(
        self,
    ) -> None:
        build = source("content/shell/BUILD.gn")
        browser_client = source(
            "content/shell/browser/shell_content_browser_client.cc"
        )
        shell = braced_block(build, 'static_library("content_shell_lib")')
        common_deps = shell.split("\n  deps = [", 1)[1].split(
            "\n  ]", 1
        )[0]
        wasm = braced_block(shell, "if (is_wasm)")
        wasm_deps = wasm.split("deps -= [", 1)[1].split("]", 1)[0]
        ios_bluetooth = browser_client.split(
            "#if BUILDFLAG(IS_IOS)", 1
        )[1].split("#endif", 1)[0]

        self.assertIn('"//components/permissions"', common_deps)
        self.assertIn('"//components/custom_handlers"', common_deps)
        self.assertIn(
            '"//components/custom_handlers:test_support"',
            common_deps,
        )
        self.assertIn('"//components/permissions"', wasm_deps)
        self.assertNotIn('"//components/custom_handlers"', wasm_deps)
        self.assertNotIn(
            '"//components/custom_handlers:test_support"',
            wasm_deps,
        )
        self.assertIn(
            '#include "components/permissions/bluetooth_delegate_impl.h"  '
            "// nogncheck",
            ios_bluetooth,
        )

    def test_custom_handlers_keeps_registry_without_desktop_permission_ui(
        self,
    ) -> None:
        build = source("components/custom_handlers/BUILD.gn")
        handlers = braced_block(
            build,
            'static_library("custom_handlers")',
        )
        desktop = braced_block(
            handlers,
            "if (!is_android && !is_ios && !is_wasm)",
        )
        registry = handlers.split(
            "if (!is_android && !is_ios && !is_wasm)",
            1,
        )[0]
        test_support = braced_block(
            build,
            'source_set("test_support")',
        )

        for source_name in (
            "protocol_handler.cc",
            "protocol_handler_registry.cc",
            "protocol_handler_throttle.cc",
        ):
            with self.subTest(source_name=source_name):
                self.assertIn(f'"{source_name}"', registry)

        for source_name in (
            "protocol_handler_navigation_throttle.cc",
            "register_protocol_handler_permission_request.cc",
        ):
            with self.subTest(source_name=source_name):
                self.assertIn(f'"{source_name}"', desktop)
                self.assertNotIn(f'"{source_name}"', registry)

        self.assertIn('"//components/permissions"', desktop)
        self.assertIn('"//ui/base"', desktop)
        self.assertNotIn('"//components/permissions"', registry)
        self.assertIn(
            '"simple_protocol_handler_registry_factory.cc"',
            test_support,
        )
        self.assertIn(
            '"test_protocol_handler_registry_delegate.cc"',
            test_support,
        )
        self.assertIn('":custom_handlers"', test_support)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the package runner's redacted WISP init seam."""

from __future__ import annotations

import json
import subprocess
import unittest

from tools.wasm import run_m9_package_browser_smoke as package_browser_smoke
from tools.wasm.m0_common import M0Error, REPO_ROOT


ENDPOINT = "wss://release-gateway.invalid/carrier/"


class FakeClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> object:
        self.calls.append((method, params))
        return self.response


class M9PackageWispPreNavigationTest(unittest.TestCase):
    def test_normalizer_rejects_secret_or_non_wss_command_line_values(self) -> None:
        self.assertEqual(
            ENDPOINT,
            package_browser_smoke._normalize_release_wisp_endpoint(ENDPOINT),
        )
        for value in (
            "ws://release-gateway.invalid/carrier/",
            "wss://operator:secret@release-gateway.invalid/carrier/",
            "wss://release-gateway.invalid/carrier/?token=secret",
            "wss://release-gateway.invalid/carrier/#secret",
            "wss://release-gateway.invalid/carrier",
            f" {ENDPOINT}",
            None,
        ):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(M0Error) as context:
                    package_browser_smoke._normalize_release_wisp_endpoint(value)
                self.assertNotIn("secret", str(context.exception))
                self.assertNotIn("operator", str(context.exception))

    def test_init_script_defines_one_immutable_idempotent_data_property(self) -> None:
        node = REPO_ROOT / "third_party/emsdk/node/22.16.0_64bit/bin/node"
        if not node.is_file():
            self.skipTest("the pinned Node executable is unavailable")
        source = package_browser_smoke._release_wisp_init_script(ENDPOINT)
        global_name = package_browser_smoke.RELEASE_WISP_CONFIGURATION_GLOBAL
        script = "\n".join(
            (
                f"const source = {json.dumps(source)};",
                "eval(source);",
                "eval(source);",
                f"const descriptor = Object.getOwnPropertyDescriptor(globalThis, {json.dumps(global_name)});",
                "process.stdout.write(JSON.stringify({",
                "  configurable: descriptor.configurable,",
                "  enumerable: descriptor.enumerable,",
                "  frozen: Object.isFrozen(descriptor.value),",
                "  hasOnlyVersionAndEndpoint: Object.keys(descriptor.value).sort().join(',') === 'endpoint,version',",
                "  version: descriptor.value.version,",
                "  writable: descriptor.writable,",
                "}));",
            )
        )
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            {
                "configurable": False,
                "enumerable": False,
                "frozen": True,
                "hasOnlyVersionAndEndpoint": True,
                "version": 1,
                "writable": False,
            },
            json.loads(completed.stdout),
        )
        self.assertNotIn(ENDPOINT, completed.stdout)
        self.assertNotIn(ENDPOINT, completed.stderr)

    def test_install_requires_a_devtools_identifier_without_exposing_endpoint(
        self,
    ) -> None:
        client = FakeClient({"identifier": "script-1"})
        package_browser_smoke._install_release_wisp_configuration(client, ENDPOINT)
        self.assertEqual(
            "Page.enable", client.calls[0][0]
        )
        self.assertEqual(
            "Page.addScriptToEvaluateOnNewDocument", client.calls[1][0]
        )
        self.assertEqual({"source"}, set(client.calls[1][1] or {}))
        self.assertIn(
            package_browser_smoke.RELEASE_WISP_CONFIGURATION_GLOBAL,
            str((client.calls[1][1] or {})["source"]),
        )

        with self.assertRaises(M0Error) as context:
            package_browser_smoke._install_release_wisp_configuration(
                FakeClient({}), ENDPOINT
            )
        self.assertNotIn(ENDPOINT, str(context.exception))

    def test_navigation_and_host_status_are_both_required(self) -> None:
        client = FakeClient({"frameId": "frame-1"})
        package_browser_smoke._navigate_to_package_document(
            client, "http://127.0.0.1:1234/"
        )
        self.assertEqual(
            [("Page.navigate", {"url": "http://127.0.0.1:1234/"})],
            client.calls,
        )
        package_browser_smoke._require_release_wisp_configuration(
            {"wispConfigured": True}, True
        )
        with self.assertRaisesRegex(
            M0Error, "package host WISP configuration state is invalid"
        ):
            package_browser_smoke._require_release_wisp_configuration(
                {"wispConfigured": False}, True
            )
        package_browser_smoke._require_release_wisp_configuration(
            {"wispConfigured": False}, False
        )
        with self.assertRaisesRegex(
            M0Error, "package host WISP configuration state is invalid"
        ):
            package_browser_smoke._require_release_wisp_configuration(
                {"wispConfigured": True}, False
            )


if __name__ == "__main__":
    unittest.main()

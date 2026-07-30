#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT_DIR / path).read_text(encoding="utf-8")


class M3UserAgentSourceContractTest(unittest.TestCase):
    def test_wasm_has_a_stable_platform_name(self) -> None:
        version_info = source("base/version_info/version_info.h")
        navigator_base = source(
            "third_party/blink/renderer/core/execution_context/"
            "navigator_base.cc"
        )
        navigator_id = source(
            "third_party/blink/renderer/core/frame/navigator_id.cc"
        )

        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n  return \"WebAssembly\";",
            version_info,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  // Report the application target without exposing or "
            "impersonating the\n"
            "  // browser host operating system.\n"
            "  return \"WebAssembly\";",
            navigator_base,
        )
        self.assertNotIn("<sys/utsname.h>", navigator_base)

        self.assertIn(
            "#if !BUILDFLAG(IS_MAC) && !BUILDFLAG(IS_WIN) && "
            "!BUILDFLAG(IS_WASM)",
            navigator_id,
        )
        wasm_platform = navigator_id.split(
            "#elif BUILDFLAG(IS_WASM)", 1
        )[1].split("#else  // Unix-like systems", 1)[0]
        self.assertIn('return "WebAssembly";', wasm_platform)
        self.assertNotIn("uname(", wasm_platform)

    def test_wasm_user_agent_does_not_spoof_the_host_os(self) -> None:
        user_agent = source(
            "components/embedder_support/user_agent_utils.cc"
        )

        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n  return \"\";\n#else\n"
            "#error Unsupported platform",
            user_agent,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n"
            "  return \"WebAssembly\";\n"
            "#else\n"
            "#error Unsupported platform",
            user_agent,
        )
        self.assertIn(
            "BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_FUCHSIA) || "
            "BUILDFLAG(IS_WASM)",
            user_agent,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n  return \"wasm\";",
            user_agent,
        )
        self.assertIn(
            "#elif BUILDFLAG(IS_WASM)\n  return \"32\";",
            user_agent,
        )
        self.assertIn(
            '#elif BUILDFLAG(IS_WASM)\n                      "WebAssembly"',
            user_agent,
        )
        self.assertNotIn("Emscripten", user_agent)

    def test_content_shell_metadata_uses_the_same_platform(self) -> None:
        browser_client = source(
            "content/shell/browser/shell_content_browser_client.cc"
        )
        metadata = browser_client.split(
            "blink::UserAgentMetadata GetShellUserAgentMetadata()", 1
        )[1].split("ShellContentBrowserClient* ", 1)[0]

        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  metadata.platform = \"WebAssembly\";\n"
            "#else\n"
            "  metadata.platform = \"Unknown\";\n"
            "#endif",
            metadata,
        )
        self.assertIn(
            "metadata.architecture = "
            "embedder_support::GetCpuArchitecture();",
            metadata,
        )
        self.assertIn(
            "metadata.bitness = embedder_support::GetCpuBitness();",
            metadata,
        )


if __name__ == "__main__":
    unittest.main()

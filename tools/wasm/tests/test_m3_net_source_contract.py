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


class M3NetSourceContractTest(unittest.TestCase):
    def test_wasm_uses_builtin_certificate_verification(self) -> None:
        features = source("net/features.gni")

        self.assertIn(
            "is_win || is_mac || is_linux || is_chromeos || is_wasm",
            features,
        )
        self.assertIn(
            'assert(!is_wasm || chrome_root_store_only,\n'
            '       "Wasm requires the builtin certificate verifier and '
            'Chrome Root Store")',
            features,
        )

    def test_wasm_disables_host_negotiate_authentication(self) -> None:
        features = source("net/features.gni")

        self.assertIn(
            "!is_ios && !is_fuchsia && !is_castos && !is_cast_android && "
            "!is_wasm",
            features,
        )
        self.assertIn(
            'assert(!is_wasm || !use_kerberos,\n'
            '       "HTTP Negotiate requires a host GSSAPI or SSPI provider")',
            features,
        )

    def test_wasm_file_stream_uses_memfs_on_its_task_runner(self) -> None:
        build = source("net/BUILD.gn")
        context = source("net/base/file_stream_context.cc")
        header = source("net/base/file_stream_context.h")
        wasm = source("net/base/file_stream_context_wasm.cc")

        self.assertIn(
            'if (is_wasm) {\n'
            "    sources += [\n"
            '      "base/file_stream_context_wasm.cc",\n'
            '      "base/net_errors_posix.cc",\n',
            build,
        )
        self.assertIn(
            "BUILDFLAG(IS_FUCHSIA) || BUILDFLAG(IS_WASM)", header
        )
        self.assertIn(
            "#if BUILDFLAG(IS_POSIX) || BUILDFLAG(IS_WASM)\n"
            "  // Always use blocking IO.",
            context,
        )
        self.assertIn(
            "task_runner_->PostTaskAndReplyWithResult(", wasm
        )
        self.assertIn("file_.ReadAtCurrentPosNoBestEffort(", wasm)
        self.assertIn("file_.WriteAtCurrentPosNoBestEffort(", wasm)
        self.assertIn("file_.Seek(base::File::FROM_BEGIN, offset)", wasm)
        self.assertIn(
            '#error "file_stream_context_wasm.cc must only be built for '
            'WebAssembly"',
            wasm,
        )

    def test_wasm_filename_paths_keep_the_utf8_file_path_contract(self) -> None:
        filename = source("net/base/filename_util.cc")
        internal = source("net/base/filename_util_internal.cc")

        self.assertGreaterEqual(
            filename.count(
                "BUILDFLAG(IS_FUCHSIA) || BUILDFLAG(IS_WASM)"
            ),
            2,
        )
        self.assertEqual(
            internal.count(
                "// Emscripten virtual filesystem paths use UTF-8."
            ),
            2,
        )
        self.assertIn(
            "base::UTF8ToUTF16(component8.c_str(), component8.size(), "
            "converted);",
            internal,
        )
        self.assertIn(
            "base::FilePath generated_name(base::UTF16ToUTF8(file_name));",
            internal,
        )


if __name__ == "__main__":
    unittest.main()

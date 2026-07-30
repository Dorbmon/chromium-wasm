#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3ShellDialogsSourceContractTest(unittest.TestCase):
    def test_wasm_selects_the_explicit_unsupported_dialog_factory(self) -> None:
        build = source("ui/shell_dialogs/BUILD.gn")
        stub = source("ui/shell_dialogs/shell_dialog_stub.cc")

        self.assertIn(
            "if (is_chromeos || is_castos || is_wasm) {\n"
            '    sources += [ "shell_dialog_stub.cc" ]',
            build,
        )
        self.assertIn("SelectFileDialog* CreateSelectFileDialog(", stub)
        self.assertIn("NOTIMPLEMENTED();", stub)
        self.assertIn("return nullptr;", stub)
        self.assertNotIn("FileSelected(", stub)
        self.assertNotIn("new SelectFileDialog", stub)

    def test_m3_content_callers_turn_null_into_cancellation(self) -> None:
        shell_chooser = source(
            "content/shell/browser/shell_file_select_helper.cc"
        )
        content_chooser = source(
            "content/browser/file_system_access/file_system_chooser.cc"
        )

        self.assertIn(
            "select_file_dialog_ = ui::SelectFileDialog::Create(this, "
            "nullptr);\n"
            "  if (!select_file_dialog_) {\n"
            "    listener->FileSelectionCanceled();",
            shell_chooser,
        )
        self.assertIn(
            "if (!listener->dialog_) {\n"
            "    listener->FileSelectionCanceled();",
            content_chooser,
        )


if __name__ == "__main__":
    unittest.main()

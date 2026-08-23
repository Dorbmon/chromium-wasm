#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the opt-in M7 native-abort PC diagnostic."""

from __future__ import annotations

import subprocess
import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


_NODE_SEMANTIC_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(0, "utf8");

function preprocess(assertions) {
  const preprocessed = source.replace(
      /^#if ASSERTIONS\r?\n([\s\S]*?)^#else\r?\n([\s\S]*?)^#endif\r?\n?/m,
      assertions ? "$1" : "$2");
  if (preprocessed === source) {
    throw new Error("missing ASSERTIONS branch");
  }
  return preprocessed;
}

function loadLibrary(assertions) {
  let library;
  const context = {
    addToLibrary: (entries) => { library = entries; },
  };
  vm.createContext(context);
  vm.runInContext(preprocess(assertions), context, {
    filename: "wasm_profile_database_abort_pc_diagnostic.js",
  });
  if (!library || typeof library._abort_js !== "function") {
    throw new Error("abort library did not load");
  }
  return {context, library};
}

function invoke(assertions, name, stack, expectedMarker) {
  const {context, library} = loadLibrary(assertions);
  const abortSignal = {};
  const markers = [];
  const abortArguments = [];
  context.Error = function ControlledError() { return {stack}; };
  context.err = (marker) => { markers.push(marker); };
  context.abort = (...arguments_) => {
    abortArguments.push(arguments_);
    throw abortSignal;
  };

  let observedAbort = false;
  try {
    library._abort_js();
  } catch (error) {
    if (error !== abortSignal) {
      throw error;
    }
    observedAbort = true;
  }

  if (!observedAbort) {
    throw new Error(name + ": abort was not observed");
  }
  if (markers.length !== 1 || markers[0] !== expectedMarker) {
    throw new Error(name + ": unexpected marker");
  }
  const expectedAbort = assertions ? "native code called abort()" : "";
  if (abortArguments.length !== 1 || abortArguments[0].length !== 1 ||
      abortArguments[0][0] !== expectedAbort) {
    throw new Error(name + ": unexpected abort");
  }
}

const unavailable = "CHROMIUM_WASM_M7_ABORT_PC:unavailable";
const cases = [
  [
    "caller-caller-frame",
    [
      "Error",
      "wasm-function[7]:0x000A",
      "wasm-function[8]:0x000B",
      "wasm-function[4294967295]:0x0000000f",
      "wasm-function[99]:0x3",
    ].join("\n"),
    "CHROMIUM_WASM_M7_ABORT_PC:frame=caller-caller;function=4294967295;offset=0xf",
  ],
  ["zero-frames", "Error", unavailable],
  ["one-frame", "Error\nwasm-function[7]:0x1", unavailable],
  [
    "two-frames",
    "Error\nwasm-function[7]:0x1\nwasm-function[8]:0x2",
    unavailable,
  ],
  [
    "malformed-first-frame",
    "Error\nwasm-function[01]:0x1\nwasm-function[7]:0x2\n" +
        "wasm-function[8]:0x3\nwasm-function[9]:0x4",
    unavailable,
  ],
  [
    "malformed-second-frame",
    "Error\nwasm-function[1]:0x1\nwasm-function[02]:0x2\n" +
        "wasm-function[3]:0x3\nwasm-function[4]:0x4",
    unavailable,
  ],
  [
    "malformed-third-frame",
    "Error\nwasm-function[1]:0x1\nwasm-function[2]:0x2\n" +
        "wasm-function[3]:0x100000000\nwasm-function[4]:0x4",
    unavailable,
  ],
  [
    "over-bound-first-frame",
    "Error\nwasm-function[4294967296]:0x1\nwasm-function[2]:0x2\n" +
        "wasm-function[3]:0x3\nwasm-function[4]:0x4",
    unavailable,
  ],
  [
    "over-bound-second-frame",
    "Error\nwasm-function[1]:0x1\nwasm-function[4294967296]:0x2\n" +
        "wasm-function[3]:0x3\nwasm-function[4]:0x4",
    unavailable,
  ],
  [
    "over-bound-third-frame",
    "Error\nwasm-function[1]:0x1\nwasm-function[2]:0x2\n" +
        "wasm-function[4294967296]:0x3\nwasm-function[4]:0x4",
    unavailable,
  ],
  ["non-string-stack", null, unavailable],
];

for (const assertions of [false, true]) {
  for (const [name, stack, expectedMarker] of cases) {
    invoke(assertions, name, stack, expectedMarker);
  }
}
"""


def _body_after_signature(text: str, signature: str) -> str:
    start = text.index(signature)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise AssertionError(f"missing closing brace for {signature}")


class M7ProfileDatabaseAbortPcDiagnosticContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gni = source("chrome/browser/wasm/wasm_profile_database_smoke.gni")
        self.chrome_build = source("chrome/BUILD.gn")
        self.library = source(
            "chrome/browser/wasm/wasm_profile_database_abort_pc_diagnostic.js"
        )

    def test_diagnostic_requires_database_smoke_and_a_distinct_output(self) -> None:
        flag = "enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic"
        for token in (
            f"{flag} = false",
            f"!{flag} ||",
            "enable_chromium_wasm_m7_profile_database_test",
            '"wasm-chrome-m7-profile-database"',
            '"wasm-chrome-m7-profile-database-abort-pc"',
            "M7 abort-PC diagnostic requires the M7 database smoke configuration",
            "M7 abort-PC diagnostic must use",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.gni)

    def test_linker_probe_is_confined_to_the_diagnostic_artifact(self) -> None:
        config = _body_after_signature(
            self.chrome_build,
            'config("chrome_wasm_m7_profile_database_abort_pc_diagnostic")',
        )
        for token in (
            '"--emit-symbol-map"',
            '"--js-library=" +',
            '"browser/wasm/wasm_profile_database_abort_pc_diagnostic.js"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, config)

        target = _body_after_signature(self.chrome_build, 'executable("chrome_wasm")')
        diagnostic = _body_after_signature(
            target,
            "if (enable_chromium_wasm_m7_profile_database_abort_pc_diagnostic)",
        )
        for token in (
            'output_name = "chrome_wasm_m7_profile_database_abort_pc_diagnostic"',
            'inputs += [ "browser/wasm/wasm_profile_database_abort_pc_diagnostic.js" ]',
            'configs += [ ":chrome_wasm_m7_profile_database_abort_pc_diagnostic" ]',
        ):
            with self.subTest(token=token):
                self.assertIn(token, diagnostic)

        self.assertEqual(self.chrome_build.count("--emit-symbol-map"), 1)
        self.assertEqual(
            target.count("chrome_wasm_m7_profile_database_abort_pc_diagnostic"),
            2,
        )

    def test_abort_override_has_no_new_abi_and_emits_only_fixed_data(self) -> None:
        self.assertIn("addToLibrary({", self.library)
        self.assertIn("_abort_js: () =>", self.library)
        self.assertNotIn("_abort_js__sig", self.library)
        self.assertIn("new Error().stack", self.library)
        self.assertIn(
            "/^wasm-function\\[(0|[1-9][0-9]{0,9})\\]:0x([0-9a-fA-F]{1,8})(?![0-9a-fA-F])/",
            self.library,
        )
        self.assertIn("const nextWasmFrame = (startIndex) =>", self.library)
        self.assertIn("const firstFrame = nextWasmFrame(0);", self.library)
        self.assertIn(
            "firstFrame && nextWasmFrame(firstFrame.nextIndex);", self.library
        )
        self.assertIn(
            "secondFrame && nextWasmFrame(secondFrame.nextIndex);", self.library
        )
        self.assertNotIn("stack.split(", self.library)
        self.assertNotIn("frameCount", self.library)
        self.assertNotIn("for (", self.library)
        self.assertNotIn("matchAll", self.library)
        self.assertIn("functionIndex > 0xffffffff", self.library)
        self.assertIn("callerCallerFrame.offset.toLowerCase()", self.library)
        self.assertIn(
            "'CHROMIUM_WASM_M7_ABORT_PC:unavailable'", self.library
        )
        self.assertIn(
            "'CHROMIUM_WASM_M7_ABORT_PC:frame=caller-caller;function=' +",
            self.library,
        )
        self.assertIn(
            "callerCallerFrame.functionIndex + ';offset=0x' + offset",
            self.library,
        )
        self.assertNotIn("CHROMIUM_WASM_M7_ABORT_PC:function=", self.library)
        self.assertNotIn(
            "CHROMIUM_WASM_M7_ABORT_PC:frame=caller;function=", self.library
        )
        self.assertIn("err(marker);", self.library)
        self.assertIn("#if ASSERTIONS", self.library)
        self.assertIn("abort('native code called abort()');", self.library)
        self.assertIn("abort('');", self.library)
        self.assertNotIn("console.", self.library)
        self.assertNotIn("err(stack", self.library)

    def test_abort_override_node_semantics_select_exact_caller_caller_frame(
        self,
    ) -> None:
        completed = subprocess.run(
            ["node", "--input-type=commonjs", "--eval", _NODE_SEMANTIC_HARNESS],
            capture_output=True,
            check=False,
            cwd=ROOT_DIR,
            input=self.library,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()

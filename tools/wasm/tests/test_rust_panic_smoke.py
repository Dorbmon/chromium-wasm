#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_rust_panic_smoke


def panic_stdout(observation: dict[str, object] | None) -> str:
    lines = [
        run_rust_panic_smoke.RUNTIME_START,
        run_rust_panic_smoke.PANIC_TRIGGER,
    ]
    if observation is not None:
        lines.append(
            run_rust_panic_smoke.OBSERVATION_PREFIX
            + json.dumps(observation, separators=(",", ":"))
        )
    return "\n".join(lines)


def panic_stderr() -> str:
    return (
        "thread '<unnamed>' panicked at "
        f"'{run_rust_panic_smoke.EXPECTED_PANIC_MARKER}'"
    )


class RustPanicRunnerTest(unittest.TestCase):
    def test_runner_observes_abort_nonzero_exit_and_timeout(self) -> None:
        source = run_rust_panic_smoke.runner_source(
            "file:///m1_rust_panic_negative.js", 1000
        )
        self.assertIn("onAbort(reason)", source)
        self.assertIn("onExit(code)", source)
        self.assertIn('recordTermination("abort"', source)
        self.assertIn('recordTermination("timeout")', source)
        self.assertIn(
            run_rust_panic_smoke.OBSERVATION_PREFIX,
            source,
        )

    def test_module_name_is_fixed(self) -> None:
        self.assertEqual(
            run_rust_panic_smoke.resolve_module(None),
            Path("out/wasm/m1_rust_panic_negative.js"),
        )
        self.assertEqual(
            run_rust_panic_smoke.resolve_module(
                Path("custom/m1_rust_panic_negative.js")
            ),
            Path("custom/m1_rust_panic_negative.js"),
        )
        with self.assertRaises(M0Error):
            run_rust_panic_smoke.resolve_module(
                Path("out/wasm/m1_rust_smoke.js")
            )

    def test_expected_abort_is_accepted(self) -> None:
        self.assertEqual(
            run_rust_panic_smoke.validate_panic_result(
                0,
                panic_stdout({"kind": "abort", "reason": "abort()"}),
                panic_stderr(),
            ),
            "abort",
        )

    def test_expected_nonzero_exit_is_accepted(self) -> None:
        self.assertEqual(
            run_rust_panic_smoke.validate_panic_result(
                0,
                panic_stdout({"kind": "nonzero_exit", "exitCode": 101}),
                panic_stderr(),
            ),
            "nonzero_exit",
        )
        self.assertEqual(
            run_rust_panic_smoke.validate_panic_result(
                1,
                panic_stdout(None),
                panic_stderr(),
            ),
            "process_nonzero",
        )

    def test_zero_exit_and_false_success_are_rejected(self) -> None:
        zero_exit = panic_stdout({"kind": "zero_exit", "exitCode": 0})
        with self.assertRaisesRegex(M0Error, "exited successfully"):
            run_rust_panic_smoke.validate_panic_result(
                0, zero_exit, panic_stderr()
            )
        for sentinel in (
            run_rust_panic_smoke.FALSE_SUCCESS,
            run_rust_panic_smoke.MODULE_PASS,
            run_rust_panic_smoke.MODULE_FAIL,
            run_rust_panic_smoke.POSITIVE_MODULE_PASS,
        ):
            with (
                self.subTest(sentinel=sentinel),
                self.assertRaisesRegex(M0Error, "falsely reported success"),
            ):
                run_rust_panic_smoke.validate_panic_result(
                    0,
                    panic_stdout({"kind": "abort"}) + f"\n{sentinel}",
                    panic_stderr(),
                )

    def test_unrelated_abort_is_rejected(self) -> None:
        unrelated_stderr = (
            f"{run_rust_panic_smoke.NODE_PREFIX}:ON_ABORT "
            + json.dumps(
                {
                    "reason": (
                        run_rust_panic_smoke.EXPECTED_PANIC_MARKER
                    )
                }
            )
        )
        with self.assertRaisesRegex(M0Error, "diagnostics"):
            run_rust_panic_smoke.validate_panic_result(
                0,
                panic_stdout({"kind": "abort"}),
                unrelated_stderr,
            )

    def test_missing_trigger_and_nontermination_are_rejected(self) -> None:
        with self.assertRaisesRegex(M0Error, "PANIC_TRIGGER"):
            run_rust_panic_smoke.validate_panic_result(
                1,
                run_rust_panic_smoke.RUNTIME_START,
                panic_stderr(),
            )
        for observation, message in (
            ({"kind": "timeout"}, "timed out"),
            ({"kind": "rejection"}, "without an abort"),
            ({"kind": "nonzero_exit", "exitCode": 0}, "invalid nonzero"),
        ):
            with (
                self.subTest(observation=observation),
                self.assertRaisesRegex(M0Error, message),
            ):
                run_rust_panic_smoke.validate_panic_result(
                    0,
                    panic_stdout(observation),
                    panic_stderr(),
                )


if __name__ == "__main__":
    unittest.main()

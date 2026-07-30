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
ROOT_DIR = TOOLS_DIR.parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m3_allocator_oom_smoke


MODULE_PREFIX = run_m3_allocator_oom_smoke.MODULE_PREFIX
NODE_PREFIX = run_m3_allocator_oom_smoke.NODE_PREFIX


def limit_line(mode: str) -> str:
    return (
        f"{MODULE_PREFIX}:LIMIT mode={mode} "
        "current_heap_bytes=67108864 max_heap_bytes=2147483648 "
        "request_bytes=2147483649"
    )


def observation(
    mode: str,
    kind: str,
    *,
    base_oom_after_trigger: bool = False,
    **details: object,
) -> str:
    payload = {
        "mode": mode,
        "kind": kind,
        **details,
        "baseOomAfterTrigger": base_oom_after_trigger,
    }
    return (
        f"{NODE_PREFIX}:OBSERVATION "
        + json.dumps(payload, separators=(",", ":"))
    )


def unchecked_stdout() -> str:
    return "\n".join(
        (
            f"{MODULE_PREFIX}:RUNTIME_START mode=unchecked",
            limit_line("unchecked"),
            (
                f"{MODULE_PREFIX}:POLICY mode=unchecked "
                "terminate_on_oom=enabled"
            ),
            f"{MODULE_PREFIX}:CONTROL mode=unchecked success=1",
            (
                f"{MODULE_PREFIX}:HEAP_AFTER mode=unchecked "
                "heap_bytes=67108864 unchanged=1"
            ),
            (
                f"{MODULE_PREFIX}:RESULT mode=unchecked "
                "success=0 pointer_null=1"
            ),
            f"{MODULE_PREFIX}:PASS mode=unchecked",
            observation("unchecked", "zero_exit", exitCode=0),
        )
    )


def ordinary_stdout(kind: str = "abort") -> str:
    return "\n".join(
        (
            f"{MODULE_PREFIX}:RUNTIME_START mode=ordinary",
            limit_line("ordinary"),
            (
                f"{MODULE_PREFIX}:POLICY mode=ordinary "
                "terminate_on_oom=enabled"
            ),
            f"{MODULE_PREFIX}:CONTROL mode=ordinary success=1",
            f"{MODULE_PREFIX}:TRIGGER mode=ordinary allocator=malloc",
            observation(
                "ordinary",
                kind,
                base_oom_after_trigger=True,
                reason="abort",
            ),
        )
    )


class AllocatorOomRunnerTest(unittest.TestCase):
    def test_runner_passes_exact_mode_to_the_module(self) -> None:
        source = run_m3_allocator_oom_smoke.runner_source(
            "file:///tmp/module.js", "unchecked", 1234
        )

        self.assertIn('from "file:///tmp/module.js"', source)
        self.assertIn('arguments: ["unchecked"]', source)
        self.assertIn('recordTermination("timeout"), 1234', source)
        self.assertIn("onAbort(reason)", source)
        self.assertIn("onExit(code)", source)
        self.assertIn("Number.isSafeInteger(code)", source)
        self.assertNotIn("Number(code)", source)
        self.assertIn(
            'triggerSeen && text.trimEnd() === "Out of memory"', source
        )
        self.assertIn("baseOomAfterTrigger", source)

    def test_runner_rejects_an_unknown_mode(self) -> None:
        with self.assertRaisesRegex(M0Error, "unsupported allocator mode"):
            run_m3_allocator_oom_smoke.runner_source(
                "file:///tmp/module.js", "invalid", 1234
            )

    def test_unchecked_mode_requires_false_and_null(self) -> None:
        outcome = run_m3_allocator_oom_smoke.validate_unchecked_result(
            0, unchecked_stdout(), ""
        )

        self.assertEqual(outcome, "returned_null")

    def test_unchecked_mode_rejects_false_success(self) -> None:
        stdout = unchecked_stdout().replace(
            "success=0 pointer_null=1", "success=1 pointer_null=0"
        )

        with self.assertRaisesRegex(M0Error, "missing .*success=0"):
            run_m3_allocator_oom_smoke.validate_unchecked_result(
                0, stdout, ""
            )

    def test_unchecked_mode_requires_zero_exit_observation(self) -> None:
        stdout = unchecked_stdout().replace(
            '"kind":"zero_exit","exitCode":0',
            '"kind":"abort","reason":"unexpected"',
        )

        with self.assertRaisesRegex(M0Error, "did not exit normally"):
            run_m3_allocator_oom_smoke.validate_unchecked_result(
                0, stdout, ""
            )

    def test_unchecked_mode_rejects_non_integer_exit_codes(self) -> None:
        for exit_code in (False, "0", 0.0, 1.5):
            with self.subTest(exit_code=exit_code):
                stdout = unchecked_stdout().replace(
                    observation("unchecked", "zero_exit", exitCode=0),
                    observation(
                        "unchecked", "zero_exit", exitCode=exit_code
                    ),
                )
                with self.assertRaisesRegex(M0Error, "invalid module exit"):
                    run_m3_allocator_oom_smoke.validate_unchecked_result(
                        0, stdout, ""
                    )

    def test_unchecked_mode_rejects_process_exit_inconsistency(self) -> None:
        with self.assertRaisesRegex(M0Error, "Node process exited"):
            run_m3_allocator_oom_smoke.validate_unchecked_result(
                1, unchecked_stdout(), ""
            )

    def test_unchecked_mode_requires_unchanged_heap(self) -> None:
        stdout = unchecked_stdout().replace("unchanged=1", "unchanged=0")

        with self.assertRaisesRegex(M0Error, "missing .*unchanged=1"):
            run_m3_allocator_oom_smoke.validate_unchecked_result(
                0, stdout, ""
            )

    def test_ordinary_mode_accepts_base_abort(self) -> None:
        outcome = run_m3_allocator_oom_smoke.validate_ordinary_result(
            1, ordinary_stdout(), "Out of memory"
        )

        self.assertEqual(outcome, "abort")

    def test_ordinary_mode_rejects_missing_observation(self) -> None:
        stdout = ordinary_stdout().rsplit("\n", 1)[0]

        for returncode in (1, 134, -9):
            with self.subTest(returncode=returncode):
                with self.assertRaisesRegex(
                    M0Error, "without termination evidence"
                ):
                    run_m3_allocator_oom_smoke.validate_ordinary_result(
                        returncode, stdout, "Out of memory"
                    )

    def test_ordinary_mode_rejects_a_zero_exit(self) -> None:
        stdout = ordinary_stdout().rsplit("\n", 1)[0] + "\n" + observation(
            "ordinary",
            "zero_exit",
            base_oom_after_trigger=True,
            exitCode=0,
        )

        with self.assertRaisesRegex(M0Error, "exited successfully"):
            run_m3_allocator_oom_smoke.validate_ordinary_result(
                1, stdout, "Out of memory"
            )

    def test_ordinary_mode_rejects_non_integer_exit_codes(self) -> None:
        for exit_code in (False, "1", 1.0, 1.5):
            with self.subTest(exit_code=exit_code):
                stdout = (
                    ordinary_stdout().rsplit("\n", 1)[0]
                    + "\n"
                    + observation(
                        "ordinary",
                        "nonzero_exit",
                        base_oom_after_trigger=True,
                        exitCode=exit_code,
                    )
                    )
                with self.assertRaisesRegex(M0Error, "invalid module exit"):
                    run_m3_allocator_oom_smoke.validate_ordinary_result(
                        1, stdout, "Out of memory"
                    )

    def test_ordinary_mode_requires_causal_base_oom_diagnostic(self) -> None:
        stdout = ordinary_stdout().replace(
            '"baseOomAfterTrigger":true',
            '"baseOomAfterTrigger":false',
        )

        with self.assertRaisesRegex(M0Error, "causal Base OOM"):
            run_m3_allocator_oom_smoke.validate_ordinary_result(
                1, stdout, "Out of memory\nabort"
            )

    def test_ordinary_mode_rejects_missing_base_oom_diagnostic(self) -> None:
        stdout = ordinary_stdout().replace(
            '"baseOomAfterTrigger":true',
            '"baseOomAfterTrigger":false',
        )

        with self.assertRaisesRegex(M0Error, "causal Base OOM"):
            run_m3_allocator_oom_smoke.validate_ordinary_result(
                1, stdout, "abort"
            )

    def test_ordinary_mode_rejects_process_exit_inconsistency(self) -> None:
        for returncode in (0, 134, -9):
            with self.subTest(returncode=returncode):
                with self.assertRaisesRegex(M0Error, "inconsistent abort"):
                    run_m3_allocator_oom_smoke.validate_ordinary_result(
                        returncode, ordinary_stdout(), "Out of memory"
                    )

    def test_both_modes_request_beyond_the_linked_maximum(self) -> None:
        for mode, stdout in (
            ("unchecked", unchecked_stdout()),
            ("ordinary", ordinary_stdout()),
        ):
            with self.subTest(mode=mode):
                current, maximum = (
                    run_m3_allocator_oom_smoke.validate_limit(stdout, mode)
                )
                self.assertEqual(current, 67108864)
                self.assertEqual(maximum, 2147483648)

    def test_limit_rejects_a_request_at_the_ceiling(self) -> None:
        stdout = unchecked_stdout().replace(
            "request_bytes=2147483649", "request_bytes=2147483648"
        )

        with self.assertRaisesRegex(M0Error, "beyond maximum"):
            run_m3_allocator_oom_smoke.validate_limit(stdout, "unchecked")

    def test_limit_requires_the_linked_memory_profile(self) -> None:
        replacements = (
            ("current_heap_bytes=67108864", "current_heap_bytes=33554432"),
            ("max_heap_bytes=2147483648", "max_heap_bytes=1073741824"),
        )
        for old, new in replacements:
            with self.subTest(field=old):
                with self.assertRaisesRegex(M0Error, "linked .* memory"):
                    run_m3_allocator_oom_smoke.validate_limit(
                        unchecked_stdout().replace(old, new),
                        "unchecked",
                    )

    def test_limit_rejects_wrong_mode_and_duplicate_evidence(self) -> None:
        with self.assertRaisesRegex(M0Error, "wrong mode"):
            run_m3_allocator_oom_smoke.validate_limit(
                unchecked_stdout().replace(
                    "LIMIT mode=unchecked", "LIMIT mode=ordinary"
                ),
                "unchecked",
            )

        with self.assertRaisesRegex(M0Error, "exactly one"):
            run_m3_allocator_oom_smoke.validate_limit(
                unchecked_stdout() + "\n" + limit_line("ordinary"),
                "unchecked",
            )

    def test_runtime_sentinels_must_not_repeat(self) -> None:
        stdout = (
            unchecked_stdout()
            + "\n"
            + f"{MODULE_PREFIX}:PASS mode=unchecked"
        )

        with self.assertRaisesRegex(M0Error, "repeated"):
            run_m3_allocator_oom_smoke.validate_unchecked_result(
                0, stdout, ""
            )

    def test_resolve_module_requires_the_linked_target_name(self) -> None:
        with self.assertRaisesRegex(M0Error, "requires"):
            run_m3_allocator_oom_smoke.resolve_module(
                Path("/tmp/not-the-target.js")
            )


class AllocatorOomSourceContractTest(unittest.TestCase):
    def test_target_links_the_actual_base_implementation(self) -> None:
        build = (TOOLS_DIR / "BUILD.gn").read_text(encoding="utf-8")
        source = (TOOLS_DIR / "m3_allocator_oom_smoke.cc").read_text(
            encoding="utf-8"
        )

        self.assertIn('executable("m3_allocator_oom_smoke")', build)
        self.assertIn("testonly = true", build)
        self.assertIn('deps = [ "//base" ]', build)
        self.assertIn("base::EnableTerminationOnOutOfMemory();", source)
        self.assertIn("base::UncheckedMalloc(request_bytes", source)
        self.assertIn("emscripten_get_heap_max()", source)
        self.assertIn("maximum_heap_bytes + 1", source)
        self.assertIn("unchanged=%d", source)
        self.assertIn("&malloc", source)

    def test_runner_uses_pinned_node_and_separate_processes(self) -> None:
        source = (
            TOOLS_DIR / "run_m3_allocator_oom_smoke.py"
        ).read_text(encoding="utf-8")

        self.assertIn("node_executable(manifest)", source)
        self.assertIn('("unchecked", validate_unchecked_result)', source)
        self.assertIn('("ordinary", validate_ordinary_result)', source)
        self.assertIn("completed = run_mode(", source)
        self.assertNotIn("em++", source)

    def test_full_base_raw_log_flushes_a_complete_line_before_abort(
        self,
    ) -> None:
        logging = (ROOT_DIR / "base/logging.cc").read_text(
            encoding="utf-8"
        )
        raw_log = logging.split("void RawLog(", 1)[1].split(
            "// This was defined at the beginning of this file.", 1
        )[0]

        self.assertIn("message[message_len - 1]) != '\\n'", raw_log)
        self.assertIn('write(STDERR_FILENO, "\\n", 1)', raw_log)
        self.assertLess(
            raw_log.index('write(STDERR_FILENO, "\\n", 1)'),
            raw_log.index("base::ImmediateCrash();"),
        )


if __name__ == "__main__":
    unittest.main()

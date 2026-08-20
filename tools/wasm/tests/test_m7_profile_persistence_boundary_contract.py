#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for Chrome's staged M7 OPFS profile-lifecycle integration.

The first M7 slice mounts the canonical /profile root on a leased OPFS WasmFS
backend and records a result-bearing scoped backend drain. It does not turn the
current in-memory PrefService into durable profile evidence; later migrations
must prove each Chrome-owned persistent store independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import unittest

from tools.wasm.tests.m3_source_contract_test_support import ROOT_DIR, source


_CONFIG_LIST_FIELDS = frozenset(
    {"all_dependent_configs", "configs", "public_configs"}
)
_WASM_TOOLS_DIRECTORY = Path("tools/wasm")


@dataclass(frozen=True)
class _GnToken:
    value: str
    start: int
    end: int
    is_string: bool = False


@dataclass(frozen=True)
class _GnScope:
    declaration: str
    target: str
    opening_brace: int
    closing_brace: int


@dataclass(frozen=True)
class _GnConfigAssignment:
    field: str
    opening_bracket: int
    closing_bracket: int


@dataclass(frozen=True)
class _GnConfigConsumer:
    path: Path
    scope: _GnScope
    field: str
    testonly: bool


def _is_gn_identifier(token: _GnToken) -> bool:
    return (
        not token.is_string
        and bool(token.value)
        and (token.value[0].isalpha() or token.value[0] == "_")
        and all(character.isalnum() or character == "_" for character in token.value)
    )


def _gn_tokens(text: str) -> list[_GnToken]:
    """Tokenizes the small GN subset needed for target and config lists.

    Comments and quoted strings are handled explicitly so brace matching does
    not mistake explanatory text or label contents for GN scope syntax.
    """

    tokens = []
    index = 0
    while index < len(text):
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if character == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if character == '"':
            start = index
            index += 1
            value_start = index
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == '"':
                    tokens.append(
                        _GnToken(
                            text[value_start:index], start, index + 1, is_string=True
                        )
                    )
                    index += 1
                    break
                index += 1
            else:
                raise AssertionError(f"unterminated GN string at offset {start}")
            continue
        if character.isalpha() or character == "_":
            start = index
            index += 1
            while index < len(text):
                next_character = text[index]
                if not (next_character.isalnum() or next_character == "_"):
                    break
                index += 1
            tokens.append(_GnToken(text[start:index], start, index))
            continue
        tokens.append(_GnToken(character, index, index + 1))
        index += 1
    return tokens


def _matching_delimiters(
    tokens: list[_GnToken], opening: str, closing: str
) -> dict[int, int]:
    """Returns both directions of each balanced delimiter pair."""

    stack = []
    pairs = {}
    for index, token in enumerate(tokens):
        if token.value == opening:
            stack.append(index)
        elif token.value == closing:
            if not stack:
                raise AssertionError(f"unmatched {closing!r} in GN source")
            opening_index = stack.pop()
            pairs[opening_index] = index
            pairs[index] = opening_index
    if stack:
        raise AssertionError(f"unmatched {opening!r} in GN source")
    return pairs


def _gn_scope_data(text: str) -> tuple[list[_GnToken], list[_GnScope]]:
    """Returns named GN scopes using lexical delimiter matching."""

    tokens = _gn_tokens(text)
    braces = _matching_delimiters(tokens, "{", "}")
    scopes = []
    for index in range(len(tokens) - 4):
        declaration, opening_paren, target, closing_paren, opening_brace = tokens[
            index : index + 5
        ]
        if (
            _is_gn_identifier(declaration)
            and opening_paren.value == "("
            and target.is_string
            and closing_paren.value == ")"
            and opening_brace.value == "{"
        ):
            scopes.append(
                _GnScope(
                    declaration.value,
                    target.value,
                    index + 4,
                    braces[index + 4],
                )
            )
    return tokens, scopes


def _scope_body(text: str, tokens: list[_GnToken], scope: _GnScope) -> str:
    return text[tokens[scope.opening_brace].end : tokens[scope.closing_brace].start]


def _balanced_body(text: str, opening_brace: int, description: str) -> str:
    """Returns the C++ body beginning at a known opening brace."""

    if opening_brace < 0:
        raise AssertionError(f"missing opening brace for {description}")

    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1 : index]
    raise AssertionError(f"missing closing brace for {description}")


def _gn_named_scopes(build_file: str) -> list[tuple[str, str, str]]:
    """Returns each named GN scope and its balanced body in source order."""

    tokens, scopes = _gn_scope_data(build_file)
    return [
        (scope.declaration, scope.target, _scope_body(build_file, tokens, scope))
        for scope in scopes
    ]


def _gn_target_body(build_file: str, declaration: str, target: str) -> str:
    """Returns one named GN target body without relying on line layout."""

    for actual_declaration, actual_target, body in _gn_named_scopes(build_file):
        if (actual_declaration, actual_target) == (declaration, target):
            return body
    raise AssertionError(f"missing {declaration} {target!r}")


def _gn_targets(build_file: str, declaration: str) -> list[tuple[str, str]]:
    """Returns every named declaration and its balanced body."""

    return [
        (target, body)
        for actual_declaration, target, body in _gn_named_scopes(build_file)
        if actual_declaration == declaration
    ]


def _gn_config_assignments(tokens: list[_GnToken]) -> list[_GnConfigAssignment]:
    """Finds literal config-list additions, including += and = forms."""

    brackets = _matching_delimiters(tokens, "[", "]")
    assignments = []
    for index, field in enumerate(tokens):
        if field.is_string or field.value not in _CONFIG_LIST_FIELDS:
            continue
        assignment = index + 1
        if assignment < len(tokens) and tokens[assignment].value == "+":
            assignment += 1
        if assignment + 1 >= len(tokens) or tokens[assignment].value != "=":
            continue
        opening_bracket = assignment + 1
        if tokens[opening_bracket].value != "[":
            continue
        closing_bracket = brackets.get(opening_bracket)
        if closing_bracket is None:
            raise AssertionError(f"unclosed {field.value!r} list in GN source")
        assignments.append(
            _GnConfigAssignment(
                field.value, opening_bracket, closing_bracket
            )
        )
    return assignments


def _innermost_scope(
    scopes: list[_GnScope], token_index: int
) -> _GnScope | None:
    containing_scopes = [
        scope
        for scope in scopes
        if scope.opening_brace < token_index < scope.closing_brace
    ]
    if not containing_scopes:
        return None
    return min(
        containing_scopes,
        key=lambda scope: scope.closing_brace - scope.opening_brace,
    )


def _set_testonly(tokens: list[_GnToken], scope: _GnScope) -> bool:
    """Returns whether the direct target body declares ``testonly = true``."""

    braces = _matching_delimiters(tokens, "{", "}")
    for index in range(scope.opening_brace + 1, scope.closing_brace - 2):
        # A nested conditional may contain an explanatory or conditional
        # assignment, but only the target body's own assignment establishes
        # that the entire target is test-only.
        if any(
            opening < index < closing
            for opening, closing in braces.items()
            if opening < closing
            and scope.opening_brace < opening < scope.closing_brace
        ):
            continue
        if (
            not tokens[index].is_string
            and tokens[index].value == "testonly"
            and tokens[index + 1].value == "="
            and not tokens[index + 2].is_string
            and tokens[index + 2].value == "true"
        ):
            return True
    return False


def _referenced_wasmfs_config(
    value: str, path: Path, configs: frozenset[str]
) -> str | None:
    """Identifies a local, full, or toolchain-qualified WasmFS config label."""

    if value.startswith(":"):
        if path.parent != _WASM_TOOLS_DIRECTORY:
            return None
        target_and_toolchain = value[1:]
    elif value.startswith("//tools/wasm:"):
        target_and_toolchain = value.removeprefix("//tools/wasm:")
    else:
        return None

    target, separator, toolchain = target_and_toolchain.partition("(")
    if not target.startswith("m7_wasmfs_"):
        return None
    if separator and not toolchain.endswith(")"):
        raise AssertionError(f"malformed WasmFS config label {value!r} in {path}")
    if target not in configs:
        raise AssertionError(f"unknown WasmFS config label {value!r} in {path}")
    return target


@lru_cache(maxsize=1)
def _tracked_gn_paths() -> tuple[Path, ...]:
    """Lists source-controlled GN and GNI files, excluding generated output."""

    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.gn", "*.gni"],
        check=True,
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
    )
    return tuple(
        Path(path.decode("utf-8"))
        for path in result.stdout.split(b"\0")
        if path
    )


def _tracked_direct_config_consumers(
    configs: frozenset[str],
) -> dict[str, list[_GnConfigConsumer]]:
    """Finds every tracked literal direct config consumer for ``configs``.

    A literal matching label outside a direct ``configs``/``public_configs``/
    ``all_dependent_configs`` list is rejected, so a known config cannot be
    silently repurposed or hidden behind a literal intermediate variable.
    """

    consumers = {config: [] for config in configs}
    for path in _tracked_gn_paths():
        text = (ROOT_DIR / path).read_text(encoding="utf-8")
        if not any(config in text for config in configs):
            continue

        tokens, scopes = _gn_scope_data(text)
        assignments = _gn_config_assignments(tokens)
        for token_index, token in enumerate(tokens):
            if not token.is_string:
                continue
            config = _referenced_wasmfs_config(token.value, path, configs)
            if config is None:
                continue

            matching_assignments = [
                assignment
                for assignment in assignments
                if assignment.opening_bracket < token_index < assignment.closing_bracket
            ]
            if not matching_assignments:
                raise AssertionError(
                    f"WasmFS config label {token.value!r} in {path} is not in "
                    "a direct config-list assignment"
                )
            scope = _innermost_scope(scopes, token_index)
            if scope is None:
                raise AssertionError(
                    f"WasmFS config label {token.value!r} in {path} has no "
                    "named target consumer"
                )
            consumers[config].append(
                _GnConfigConsumer(
                    path,
                    scope,
                    matching_assignments[-1].field,
                    _set_testonly(tokens, scope),
                )
            )
    return consumers


class M7ProfilePersistenceBoundaryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.wasm_browser_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_build = source("chrome/BUILD.gn")
        self.wasm_tools_build = source("tools/wasm/BUILD.gn")

    def test_profile_keeps_its_pref_store_explicitly_in_memory(self) -> None:
        """The mounted path alone must not be mistaken for durable prefs."""

        for phrase in (
            "leased OPFS WasmFS mount",
            "in-memory PersistentPrefStore",
            "does not claim durable\n// preferences, databases, sessions, or profile recovery",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.profile_header)

        self.assertIn(
            '#include "components/prefs/in_memory_pref_store.h"', self.profile
        )
        constructor = re.search(
            r"WasmProfile::WasmProfile\(base::FilePath profile_path\)",
            self.profile,
        )
        self.assertIsNotNone(constructor)
        constructor_opening = re.search(r"\)\s*\{", self.profile[constructor.end() :])
        self.assertIsNotNone(constructor_opening)
        constructor_body = _balanced_body(
            self.profile,
            constructor.end() + constructor_opening.end() - 1,
            "WasmProfile constructor",
        )
        self.assertRegex(
            constructor_body,
            r"pref_service_factory\.set_user_prefs\(\s*"
            r"base::MakeRefCounted<InMemoryPrefStore>\(\)\s*\);",
        )

    def test_gn_helpers_require_addition_and_unconditional_testonly(self) -> None:
        """Helper parsing must not confuse removal or conditional safety."""

        removal_tokens, removal_scopes = _gn_scope_data(
            '''
executable("m7_wasmfs_removal_only") {
  testonly = true
  configs -= [ ":m7_wasmfs_opfs_smoke_link" ]
}
'''
        )
        self.assertEqual([], _gn_config_assignments(removal_tokens))
        self.assertTrue(_set_testonly(removal_tokens, removal_scopes[0]))

        conditional_tokens, conditional_scopes = _gn_scope_data(
            '''
executable("m7_wasmfs_conditional_testonly") {
  if (is_wasm) {
    testonly = true
  }
  configs += [ ":m7_wasmfs_opfs_smoke_link" ]
}
'''
        )
        self.assertEqual(1, len(_gn_config_assignments(conditional_tokens)))
        self.assertFalse(_set_testonly(conditional_tokens, conditional_scopes[0]))

    def test_main_parts_requires_the_mount_and_constructs_default_profile(self) -> None:
        """DIR_USER_DATA must be resolved only after the storage mount."""

        pre_main = re.search(
            r"int WasmBrowserMainParts::PreMainMessageLoopRun\(\) "
            r"\{",
            self.main_parts,
        )
        self.assertIsNotNone(pre_main)
        body = _balanced_body(
            self.main_parts,
            self.main_parts.find("{", pre_main.start()),
            "WasmBrowserMainParts::PreMainMessageLoopRun",
        )
        for required in (
            "chrome::IsWasmProfileStorageMounted()",
            'LOG(ERROR) << "chrome_wasm profile storage is not mounted"',
            "base::PathService::Get(chrome::DIR_USER_DATA, &user_data_directory)",
            'LOG(ERROR) << "chrome_wasm could not resolve its mounted profile root"',
            'user_data_directory.AppendASCII("Default")',
            "base::CreateDirectory(profile_path)",
            'LOG(ERROR) << "chrome_wasm could not create its mounted profile path"',
            "profile_ = std::make_unique<WasmProfile>(profile_path);",
            "chrome::NotifyWasmProfileStorageProfileCreated()",
        ):
            with self.subTest(required=required):
                self.assertIn(required, body)

        self.assertLess(
            body.index("chrome::IsWasmProfileStorageMounted()"),
            body.index("base::PathService::Get(chrome::DIR_USER_DATA"),
        )
        self.assertLess(
            body.index("base::CreateDirectory(profile_path)"),
            body.index("profile_ = std::make_unique<WasmProfile>(profile_path);"),
        )
        self.assertLess(
            body.index("profile_ = std::make_unique<WasmProfile>(profile_path);"),
            body.index("chrome::NotifyWasmProfileStorageProfileCreated()"),
        )

    def test_chrome_wasm_owns_its_wasmfs_link_flag_and_storage_target(self) -> None:
        """Production Chrome must select its owned M7 lifecycle, not a smoke."""

        chrome_assets = _gn_target_body(
            self.chrome_build, "config", "chrome_wasm_assets"
        )
        chrome_storage = _gn_target_body(
            self.chrome_build, "config", "chrome_wasm_profile_storage"
        )
        chrome_wasm = _gn_target_body(
            self.chrome_build, "executable", "chrome_wasm"
        )
        chrome_https_test = _gn_target_body(
            self.chrome_build, "executable", "chrome_wasm_m6_https_test"
        )
        chrome_profile = _gn_target_body(
            self.wasm_browser_build, "source_set", "wasm_profile"
        )
        chrome_profile_storage = _gn_target_body(
            self.wasm_browser_build, "source_set", "wasm_profile_storage"
        )

        self.assertIn("-sWASMFS=1", chrome_storage)
        self.assertIn('":chrome_wasm_assets",', chrome_wasm)
        self.assertIn('":chrome_wasm_profile_storage",', chrome_wasm)
        self.assertIn('":chrome_wasm_profile_storage",', chrome_https_test)
        self.assertIn(
            '"//chrome/browser/wasm:wasm_profile_storage",', chrome_wasm
        )
        self.assertIn(
            '"//chrome/browser/wasm:wasm_profile_storage",', chrome_https_test
        )
        self.assertIn("wasm_profile_storage.cc", chrome_profile_storage)
        self.assertIn("wasm_profile_storage.h", chrome_profile_storage)
        for label, target in (
            ("chrome_wasm assets", chrome_assets),
            ("WasmProfile source set", chrome_profile),
            ("WasmProfile storage source set", chrome_profile_storage),
        ):
            with self.subTest(label=label):
                self.assertNotIn("m7_wasmfs_", target)

    def test_isolated_wasmfs_flags_remain_confined_to_testonly_m7_tools(self) -> None:
        """The old primitive smokes remain separate from Chrome's link config."""

        wasmfs_configs = frozenset(
            name
            for name, body in _gn_targets(self.wasm_tools_build, "config")
            if "-sWASMFS=1" in body
        )
        self.assertTrue(wasmfs_configs)
        all_consumers = _tracked_direct_config_consumers(wasmfs_configs)

        for config in sorted(wasmfs_configs):
            with self.subTest(config=config):
                self.assertTrue(config.startswith("m7_wasmfs_"))
                consumers = all_consumers[config]
                self.assertTrue(consumers)
                for consumer in consumers:
                    with self.subTest(
                        config=config,
                        target=consumer.scope.target,
                        path=consumer.path,
                        field=consumer.field,
                    ):
                        self.assertEqual(
                            _WASM_TOOLS_DIRECTORY / "BUILD.gn", consumer.path
                        )
                        self.assertEqual("executable", consumer.scope.declaration)
                        self.assertTrue(
                            consumer.scope.target.startswith("m7_wasmfs_")
                        )
                        self.assertTrue(consumer.testonly)

        # Chrome's executable target owns its distinct lifecycle config and
        # must not name an isolated feasibility package. This deliberately says
        # nothing about unrelated non-WasmFS tools/wasm utilities.
        chrome_wasm = _gn_target_body(
            self.chrome_build, "executable", "chrome_wasm"
        )
        self.assertNotIn("m7_wasmfs_", chrome_wasm)


if __name__ == "__main__":
    unittest.main()

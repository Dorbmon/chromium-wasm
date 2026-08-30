#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for normal volatile profile startup and experimental M7 storage.

Normal Chrome owns a file-backed Preferences store beneath /profile, but does
not claim durable OPFS persistence. The pinned V4 WasmFS/OPFS backend remains
available only to the dedicated M7 experiment configurations.
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


_M7_STORAGE_MACROS = (
    "CHROME_WASM_M7_PREFERENCES_SMOKE_TEST",
    "CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST",
)
_M7_STORAGE_GN_FLAGS = (
    "enable_chromium_wasm_m7_profile_preferences_test",
    "enable_chromium_wasm_m7_profile_database_test",
)


def _is_in_m7_storage_macro_block(text: str, position: int) -> bool:
    """Returns whether |position| is under either M7 storage capability."""

    active_stack: list[bool] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if offset <= position < offset + len(line):
            return any(active_stack)

        directive = line.lstrip()
        is_storage_directive = any(
            macro in directive for macro in _M7_STORAGE_MACROS
        )
        if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
            active_stack.append(is_storage_directive)
        elif re.match(r"#\s*elif\b", directive):
            if active_stack:
                active_stack[-1] = is_storage_directive
        elif re.match(r"#\s*else\b", directive):
            if active_stack:
                active_stack[-1] = False
        elif re.match(r"#\s*endif\b", directive):
            if active_stack:
                active_stack.pop()
        offset += len(line)
    return False


def _assert_only_in_m7_storage_blocks(
    testcase: unittest.TestCase, text: str, token: str
) -> None:
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(
                _is_in_m7_storage_macro_block(text, position),
                f"{token} is not M7-storage-config-gated",
            )


def _m7_storage_gn_blocks(text: str) -> list[tuple[int, int]]:
    """Returns GN ``if`` bodies that explicitly grant an M7 capability."""

    blocks = []
    for match in re.finditer(r"if\s*\((.*?)\)\s*\{", text, re.DOTALL):
        if not any(flag in match.group(1) for flag in _M7_STORAGE_GN_FLAGS):
            continue
        opening_brace = match.end() - 1
        body = _balanced_body(text, opening_brace, "M7 storage GN capability")
        blocks.append((opening_brace, opening_brace + len(body) + 1))
    return blocks


def _assert_only_in_m7_storage_gn_blocks(
    testcase: unittest.TestCase, text: str, token: str
) -> None:
    positions = [match.start() for match in re.finditer(re.escape(token), text)]
    testcase.assertTrue(positions, f"missing {token}")
    blocks = _m7_storage_gn_blocks(text)
    testcase.assertTrue(blocks, "missing M7 storage GN capability block")
    for position in positions:
        with testcase.subTest(token=token, position=position):
            testcase.assertTrue(
                any(start < position < end for start, end in blocks),
                f"{token} is not M7-storage-config-gated",
            )


class M7ProfilePersistenceBoundaryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_header = source("chrome/browser/wasm/wasm_profile.h")
        self.profile = source("chrome/browser/wasm/wasm_profile.cc")
        self.pref_service = source("components/prefs/pref_service.cc")
        self.pref_service_factory = source(
            "components/prefs/pref_service_factory.cc"
        )
        self.main_parts = source(
            "chrome/browser/wasm/wasm_browser_main_parts.cc"
        )
        self.wasm_browser_build = source("chrome/browser/wasm/BUILD.gn")
        self.chrome_build = source("chrome/BUILD.gn")
        self.chrome_paths = source("chrome/common/chrome_paths_wasm.cc")
        self.wasm_tools_build = source("tools/wasm/BUILD.gn")

    def test_profile_owns_file_backed_json_prefs_without_durability_claim(
        self,
    ) -> None:
        """Preferences remain file-backed without asserting OPFS persistence."""

        self.assertIn("JsonPrefStore", self.profile_header)
        self.assertNotIn("leased OPFS WasmFS mount", self.profile_header)

        self.assertIn(
            '#include "components/prefs/json_pref_store.h"', self.profile
        )
        self.assertNotIn("InMemoryPrefStore", self.profile)
        self.assertIn(
            "std::unique_ptr<WasmProfilePersistentPrefsLifetimeParticipant>",
            self.profile_header,
        )
        self.assertIn(
            ": WasmProfile(std::move(profile_path), nullptr) {}", self.profile
        )
        constructor = re.search(
            r"WasmProfile::WasmProfile\(\s*"
            r"base::FilePath profile_path,\s*"
            r"std::unique_ptr<WasmProfilePersistentPrefsLifetimeParticipant>\s*"
            r"prefs_lifetime_profile_io_participant\)\s*:",
            self.profile,
        )
        self.assertIsNotNone(constructor)
        constructor_opening_match = re.search(
            r"\)\s*\{", self.profile[constructor.end() :]
        )
        self.assertIsNotNone(constructor_opening_match)
        constructor_opening = (
            constructor.end() + constructor_opening_match.end() - 1
        )
        constructor_prefix = self.profile[constructor.start() : constructor_opening]
        constructor_body = _balanced_body(
            self.profile,
            constructor_opening,
            "WasmProfile constructor",
        )
        self.assertIn(
            "prefs_lifetime_profile_io_participant_(\n"
            "          std::move(prefs_lifetime_profile_io_participant))",
            constructor_prefix,
        )
        for required in (
            "CHECK(prefs_lifetime_profile_io_participant_)",
            "prefs_lifetime_profile_io_participant_->IsPending()",
            "json_pref_store_ = base::MakeRefCounted<JsonPrefStore>(",
            "profile_path_.Append(chrome::kPreferencesFilename)",
            "io_task_runner_",
            "pref_service_factory.set_user_prefs(json_pref_store_);",
            "pref_registry_->RegisterStringPref(kWasmPersistentPrefsFenceUuid,",
            "base::Uuid::GenerateRandomV4().AsLowercaseString()",
            "prefs_->SetString(kWasmPersistentPrefsFenceUuid,",
        ):
            with self.subTest(required=required):
                self.assertIn(required, constructor_body)

        self.assertLess(
            constructor_body.index(
                "CHECK(prefs_lifetime_profile_io_participant_)"
            ),
            constructor_body.index("json_pref_store_ ="),
        )
        self.assertLess(
            constructor_body.index(
                "prefs_lifetime_profile_io_participant_->IsPending()"
            ),
            constructor_body.index("prefs_ = pref_service_factory.Create("),
        )
        self.assertLess(
            constructor_body.index("json_pref_store_ ="),
            constructor_body.index("pref_service_factory.set_user_prefs("),
        )
        self.assertLess(
            constructor_body.index("pref_service_factory.set_user_prefs("),
            constructor_body.index("prefs_ = pref_service_factory.Create("),
        )
        self.assertLess(
            constructor_body.index("prefs_ = pref_service_factory.Create("),
            constructor_body.index("prefs_->SetString(kWasmPersistentPrefsFenceUuid,"),
        )
        self.assertNotIn("pref_service_factory.set_async(", constructor_body)

        factory_create = _balanced_body(
            self.pref_service_factory,
            self.pref_service_factory.index(
                "{", self.pref_service_factory.index("PrefServiceFactory::Create")
            ),
            "PrefServiceFactory::Create",
        )
        self.assertIn("std::make_unique<PrefService>(", factory_create)
        self.assertIn("async_", factory_create)
        self.assertIn(
            "PrefServiceFactory::PrefServiceFactory()\n"
            "    : read_error_callback_(base::DoNothing()), async_(false) {}",
            self.pref_service_factory,
        )

        pref_service_constructor = _balanced_body(
            self.pref_service,
            self.pref_service.index(
                "{", self.pref_service.index("PrefService::PrefService(")
            ),
            "PrefService::PrefService",
        )
        self.assertIn("InitFromStorage(async);", pref_service_constructor)
        init_from_storage = _balanced_body(
            self.pref_service,
            self.pref_service.index(
                "{", self.pref_service.index("void PrefService::InitFromStorage(")
            ),
            "PrefService::InitFromStorage",
        )
        self.assertIn("user_pref_store_->ReadPrefs()", init_from_storage)
        self.assertLess(
            init_from_storage.index("if (!async)"),
            init_from_storage.index("user_pref_store_->ReadPrefs()"),
        )

    def test_prefs_shutdown_fence_is_async_and_strict(self) -> None:
        """A completed write must round-trip on the JsonPrefStore file runner."""

        self.assertNotIn("wasm_profile_storage", self.profile_header)
        for text in (self.profile_header, self.profile):
            self.assertNotIn("wasmfs_", text)

        # The normal profile remains free of the OPFS adapter. M7 receives its
        # construction-start admission from BrowserMainParts rather than
        # letting WasmProfile select the storage owner itself.
        self.assertIn(
            "#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST)", self.profile
        )
        self.assertIn(
            "defined(CHROME_WASM_M7_PROFILE_DATABASE_SMOKE_TEST)", self.profile
        )
        self.assertNotIn("wasm_profile_storage.h", self.profile)
        self.assertIn(
            "WasmProfilePersistentPrefsLifetimeParticipant", self.profile
        )
        self.assertNotIn(
            "CompletePersistentPrefsWithProfileStorageHold", self.profile
        )

        fence = re.search(
            r"void WasmProfile::BeginPrefsShutdownFence\(\s*"
            r"base::OnceCallback<void\(bool success\)> completion\)\s*\{",
            self.profile,
        )
        self.assertIsNotNone(fence)
        fence_body = _balanced_body(
            self.profile,
            self.profile.find("{", fence.start()),
            "WasmProfile::BeginPrefsShutdownFence",
        )
        for required in (
            "CHECK(shutdown_)",
            "PrefsShutdownFenceState::kNotStarted",
            "PrefsShutdownFenceState::kPending",
            "WasmProfilePrefsFenceController",
            "prefs_shutdown_fence_controller_->Begin(",
            "WasmProfile::StartPrefsShutdownFence",
            "WasmProfile::OnPrefsShutdownFenceComplete",
            "base::Unretained(this)",
            "weak_ptr_factory_.GetWeakPtr()",
        ):
            with self.subTest(required=required):
                self.assertIn(required, fence_body)
        for forbidden in ("base::RunLoop", "WaitableEvent", ".Wait("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fence_body)

        starter = re.search(
            r"bool WasmProfile::StartPrefsShutdownFence\(\s*"
            r"base::OnceCallback<void\(bool success\)> completion\)\s*\{",
            self.profile,
        )
        self.assertIsNotNone(starter)
        starter_body = _balanced_body(
            self.profile,
            self.profile.find("{", starter.start()),
            "WasmProfile::StartPrefsShutdownFence",
        )
        for required in (
            "base::BindPostTask(",
            "base::SequencedTaskRunner::GetCurrentDefault()",
            "std::move(completion)",
            "prefs_->CommitPendingWrite(",
            "base::OnceClosure()",
            "json_pref_store_->GetValues()",
            "CHECK(prefs_lifetime_profile_io_participant_)",
            "prefs_lifetime_profile_io_participant_->IsPending()",
        ):
            with self.subTest(required=required):
                self.assertIn(required, starter_body)
        self.assertNotIn(
            "WasmProfile::OnPrefsShutdownFenceComplete", starter_body
        )
        self.assertNotIn(
            "TryAcquireWasmProfileStorageProfileIO", starter_body
        )
        for forbidden in ("base::RunLoop", "WaitableEvent", ".Wait("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, starter_body)

        self.assertLess(
            self.profile.index("void WasmProfile::BeginPrefsShutdownFence"),
            self.profile.index("bool WasmProfile::StartPrefsShutdownFence"),
        )

        self.assertNotIn("StartPrefsLifetimeProfileIOAdmission", self.profile)
        self.assertNotIn(
            "StartPrefsLifetimeProfileIOAdmission", self.profile_header
        )

        completion = re.search(
            r"void WasmProfile::OnPrefsShutdownFenceComplete\(\s*"
            r"base::OnceCallback<void\(bool success\)> completion,\s*"
            r"bool success\)\s*\{",
            self.profile,
        )
        self.assertIsNotNone(completion)
        completion_body = _balanced_body(
            self.profile,
            self.profile.find("{", completion.start()),
            "WasmProfile::OnPrefsShutdownFenceComplete",
        )
        for required in (
            "prefs_lifetime_profile_io_participant_",
            "CompleteAfterStrictFence(",
            "success = false;",
        ):
            with self.subTest(required=required):
                self.assertIn(required, completion_body)
        self.assertLess(
            completion_body.index("CompleteAfterStrictFence("),
            completion_body.index("prefs_shutdown_fence_state_ = success"),
        )

        destructor = re.search(r"WasmProfile::~WasmProfile\(\)\s*\{", self.profile)
        self.assertIsNotNone(destructor)
        destructor_body = _balanced_body(
            self.profile,
            self.profile.find("{", destructor.start()),
            "WasmProfile::~WasmProfile",
        )
        self.assertIn("prefs_lifetime_profile_io_participant_->Cancel();", destructor_body)
        self.assertLess(
            destructor_body.index("prefs_lifetime_profile_io_participant_->Cancel();"),
            destructor_body.index("prefs_shutdown_fence_controller_->Cancel();"),
        )

        verify = re.search(
            r"void VerifyPersistentPrefsAndReplyOnFileSequence\(", self.profile
        )
        self.assertIsNotNone(verify)
        verify_body = _balanced_body(
            self.profile,
            self.profile.find("{", verify.start()),
            "VerifyPersistentPrefsAndReplyOnFileSequence",
        )
        self.assertIn("VerifyPersistentPrefsOnFileSequence", verify_body)
        self.assertIn(
            "std::move(reply).Run(readback_succeeded);", verify_body
        )

        readback = re.search(
            r"bool VerifyPersistentPrefsOnFileSequence\(", self.profile
        )
        self.assertIsNotNone(readback)
        readback_body = _balanced_body(
            self.profile,
            self.profile.find("{", readback.start()),
            "VerifyPersistentPrefsOnFileSequence",
        )
        for required in (
            "base::ReadFileToStringWithMaxSize(",
            "kMaxPersistentPrefsFileSize",
            "base::JSONReader::ReadDict(",
            "base::JSON_PARSE_RFC",
            "*persisted_values == expected_values",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readback_body)

    def test_main_parts_waits_for_the_prefs_fence_before_profile_reset(self) -> None:
        """Normal teardown waits for the file-backed Preferences readback."""

        finish = re.search(
            r"void WasmBrowserMainParts::FinishShutdown\(\)\s*\{",
            self.main_parts,
        )
        self.assertIsNotNone(finish)
        finish_body = _balanced_body(
            self.main_parts,
            self.main_parts.find("{", finish.start()),
            "WasmBrowserMainParts::FinishShutdown",
        )
        for required in (
            "profile_->Shutdown();",
            "HasPrefsShutdownFenceCompleted()",
            "IsPrefsShutdownFencePending()",
            "BeginPrefsShutdownFence(",
            "weak_ptr_factory_.GetWeakPtr()",
            "main_parts->FinishShutdown();",
            "DidPrefsShutdownFenceSucceed()",
            "profile_.reset();",
            "main_message_loop_quit_closure_.Run();",
        ):
            with self.subTest(required=required):
                self.assertIn(required, finish_body)
        self.assertLess(
            finish_body.index("BeginPrefsShutdownFence("),
            finish_body.index("main_message_loop_quit_closure_.Run();"),
        )
        self.assertLess(
            finish_body.index("profile_.reset();"),
            finish_body.index("main_message_loop_quit_closure_.Run();"),
        )
        profile_reset_positions = [
            match.start()
            for match in re.finditer(re.escape("profile_.reset();"), finish_body)
        ]
        self.assertGreaterEqual(len(profile_reset_positions), 2)
        self.assertTrue(
            any(
                _is_in_m7_storage_macro_block(finish_body, position)
                for position in profile_reset_positions
            )
        )
        self.assertTrue(
            any(
                not _is_in_m7_storage_macro_block(finish_body, position)
                for position in profile_reset_positions
            )
        )

        _assert_only_in_m7_storage_blocks(
            self,
            self.main_parts,
            "chrome::NotifyWasmProfileStorageProfileShutdown()",
        )

        foundation = re.search(
            r"void WasmBrowserMainParts::ShutdownFoundation\(\)\s*\{",
            self.main_parts,
        )
        self.assertIsNotNone(foundation)
        foundation_body = _balanced_body(
            self.main_parts,
            self.main_parts.find("{", foundation.start()),
            "WasmBrowserMainParts::ShutdownFoundation",
        )
        self.assertIn("profile_->Shutdown();", foundation_body)
        foundation_reset_positions = [
            match.start()
            for match in re.finditer(
                re.escape("profile_.reset();"), foundation_body
            )
        ]
        self.assertTrue(foundation_reset_positions)
        for position in foundation_reset_positions:
            with self.subTest(position=position):
                self.assertFalse(
                    _is_in_m7_storage_macro_block(foundation_body, position)
                )
        _assert_only_in_m7_storage_blocks(
            self,
            foundation_body,
            "chrome_wasm retains its OPFS profile lease because",
        )
        self.assertIn(
            "chrome_wasm releases its incomplete volatile profile",
            foundation_body,
        )
        self.assertNotIn(
            "NotifyWasmProfileStorageProfileShutdown", foundation_body
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

    def test_main_parts_constructs_default_profile_beneath_profile_root(self) -> None:
        """Normal startup keeps its /profile/Default construction path."""

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
            "base::PathService::Get(chrome::DIR_USER_DATA, &user_data_directory)",
            'user_data_directory.AppendASCII("Default")',
            "base::CreateDirectory(profile_path)",
            "profile_ = std::make_unique<WasmProfile>(profile_path);",
        ):
            with self.subTest(required=required):
                self.assertIn(required, body)

        self.assertLess(
            body.index("base::CreateDirectory(profile_path)"),
            body.index("profile_ = std::make_unique<WasmProfile>(profile_path);"),
        )

        profile_root_start = self.chrome_paths.index(
            "bool GetDefaultUserDataDirectory("
        )
        profile_root = _balanced_body(
            self.chrome_paths,
            self.chrome_paths.index("{", profile_root_start),
            "GetDefaultUserDataDirectory",
        )
        self.assertIn('FILE_PATH_LITERAL("/profile")', self.chrome_paths)
        self.assertIn("base::FilePath(kProfileRoot)", profile_root)

        _assert_only_in_m7_storage_blocks(
            self,
            self.main_parts,
            "chrome::IsWasmProfileStorageMounted()",
        )
        _assert_only_in_m7_storage_blocks(
            self,
            self.main_parts,
            "chrome::NotifyWasmProfileStorageProfileCreated()",
        )
        _assert_only_in_m7_storage_blocks(
            self,
            self.main_parts,
            "chrome::BeginWasmProfileStorageProfileConstruction()",
        )
        _assert_only_in_m7_storage_blocks(
            self,
            self.main_parts,
            "chrome::AbortWasmProfileStorageProfileConstructionFailClosed()",
        )
        preconstruction_admission = body.index(
            "chrome::BeginWasmProfileStorageProfileConstruction()"
        )
        participant = body.index(
            "std::make_unique<WasmProfilePersistentPrefsLifetimeParticipant>("
        )
        m7_profile = body.index(
            "profile_ = std::make_unique<WasmProfile>(\n"
            "      profile_path, std::move(prefs_lifetime_profile_io_participant));"
        )
        profile_created = body.index(
            "chrome::NotifyWasmProfileStorageProfileCreated()"
        )
        self.assertLess(
            preconstruction_admission,
            participant,
        )
        self.assertLess(
            participant,
            m7_profile,
        )
        self.assertLess(m7_profile, profile_created)
        normal_profile = body.index(
            "profile_ = std::make_unique<WasmProfile>(profile_path);"
        )
        self.assertFalse(_is_in_m7_storage_macro_block(body, normal_profile))

    def test_preconstruction_admission_denial_selects_fail_closed_abort(
        self,
    ) -> None:
        """A denied construction admission cannot publish ProfileCreated()."""

        pre_main = re.search(
            r"int WasmBrowserMainParts::PreMainMessageLoopRun\(\) " r"\{",
            self.main_parts,
        )
        self.assertIsNotNone(pre_main)
        pre_main_body = _balanced_body(
            self.main_parts,
            self.main_parts.find("{", pre_main.start()),
            "WasmBrowserMainParts::PreMainMessageLoopRun",
        )
        admission_denial = re.search(
            r"if \(!preconstruction_profile_io_hold\)\s*\{",
            pre_main_body,
        )
        self.assertIsNotNone(admission_denial)
        admission_denial_body = _balanced_body(
            pre_main_body,
            pre_main_body.find("{", admission_denial.start()),
            "WasmProfile construction admission denial",
        )
        self.assertIn("FailCloseM7ProfileConstruction();", admission_denial_body)
        self.assertIn(
            "return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;", admission_denial_body
        )
        self.assertNotIn("profile_", admission_denial_body)
        self.assertNotIn(
            "NotifyWasmProfileStorageProfileCreated", admission_denial_body
        )

        construction_abort = re.search(
            r"void FailCloseM7ProfileConstruction\(\)\s*\{", self.main_parts
        )
        self.assertIsNotNone(construction_abort)
        construction_abort_body = _balanced_body(
            self.main_parts,
            self.main_parts.find("{", construction_abort.start()),
            "FailCloseM7ProfileConstruction",
        )
        self.assertIn(
            "chrome::AbortWasmProfileStorageProfileConstructionFailClosed()",
            construction_abort_body,
        )
        self.assertNotIn(
            "NotifyWasmProfileStorageProfileShutdown", construction_abort_body
        )
        self.assertNotIn(
            "NotifyWasmProfileStorageProfileCreated", construction_abort_body
        )

        construction_notify_failure = re.search(
            r"if \(!chrome::NotifyWasmProfileStorageProfileCreated\(\)\)\s*\{",
            pre_main_body,
        )
        self.assertIsNotNone(construction_notify_failure)
        construction_notify_failure_body = _balanced_body(
            pre_main_body,
            pre_main_body.find("{", construction_notify_failure.start()),
            "WasmProfile ProfileCreated failure",
        )
        self.assertLess(
            construction_notify_failure_body.index("profile_.reset();"),
            construction_notify_failure_body.index(
                "FailCloseM7ProfileConstruction();"
            ),
        )

    def test_normal_chrome_and_m6_do_not_select_experimental_wasmfs_storage(
        self,
    ) -> None:
        """Only dedicated M7 artifacts select the pinned V4 storage backend."""

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
        prefs_lifetime_participant = _gn_target_body(
            self.wasm_browser_build,
            "source_set",
            "wasm_profile_persistent_prefs_lifetime_participant",
        )
        prefs_lifetime_participant_unittests = _gn_target_body(
            self.wasm_browser_build,
            "test",
            "wasm_profile_persistent_prefs_lifetime_participant_unittests",
        )
        main_parts = _gn_target_body(
            self.wasm_browser_build, "source_set", "wasm_browser_main_parts"
        )

        self.assertIn("-sWASMFS=1", chrome_storage)
        self.assertIn('":chrome_wasm_assets"', chrome_wasm)
        _assert_only_in_m7_storage_gn_blocks(
            self, chrome_wasm, '":chrome_wasm_profile_storage"'
        )
        _assert_only_in_m7_storage_gn_blocks(
            self,
            chrome_wasm,
            '"//chrome/browser/wasm:wasm_profile_storage"',
        )
        _assert_only_in_m7_storage_gn_blocks(
            self, main_parts, '":wasm_profile_storage"'
        )
        self.assertIn(
            '":wasm_profile_persistent_prefs_lifetime_participant",',
            chrome_profile,
        )
        self.assertIn(
            'public_deps = [ ":wasm_profile_ordered_drain_lifecycle" ]',
            prefs_lifetime_participant,
        )
        for token in (
            "wasm_profile_persistent_prefs_lifetime_participant_unittest.cc",
            '":wasm_profile_persistent_prefs_lifetime_participant",',
            '"//base/test:run_all_unittests",',
        ):
            with self.subTest(token=token):
                self.assertIn(token, prefs_lifetime_participant_unittests)
        for forbidden in ("wasm_profile_storage", "wasmfs", "emscripten"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prefs_lifetime_participant)
        for token in (
            '":chrome_wasm_profile_storage"',
            '"//chrome/browser/wasm:wasm_profile_storage"',
            '":wasm_profile_storage"',
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, chrome_https_test)
        self.assertIn("wasm_profile_storage.cc", chrome_profile_storage)
        self.assertIn("wasm_profile_storage.h", chrome_profile_storage)
        self.assertIn('"//chrome/common:non_code_constants",', chrome_profile)
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

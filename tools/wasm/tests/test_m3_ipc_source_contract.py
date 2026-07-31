#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


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


def code_without_comments(contents: str) -> str:
    # Preserve newlines so match locations still map to source line numbers.
    contents = re.sub(
        r"/\*.*?\*/",
        lambda match: "\n" * match.group(0).count("\n"),
        contents,
        flags=re.DOTALL,
    )
    return re.sub(r"//[^\n]*", "", contents)


def preprocessor_conditions_by_line(
    contents: str,
) -> dict[int, tuple[str, ...]]:
    conditions: dict[int, tuple[str, ...]] = {}
    stack: list[str] = []
    lines = contents.splitlines()
    index = 0

    while index < len(lines):
        conditions[index + 1] = tuple(stack)
        logical_line = lines[index].lstrip()
        if not logical_line.startswith("#"):
            index += 1
            continue

        while logical_line.rstrip().endswith("\\"):
            logical_line = logical_line.rstrip()[:-1]
            index += 1
            if index >= len(lines):
                raise AssertionError(
                    "unterminated preprocessor continuation"
                )
            conditions[index + 1] = tuple(stack)
            logical_line += " " + lines[index].strip()

        directive = re.match(
            r"#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)",
            logical_line,
        )
        if directive:
            kind = directive.group(1)
            expression = directive.group(2).strip()
            if kind == "if":
                stack.append(expression)
            elif kind == "ifdef":
                stack.append(f"defined({expression})")
            elif kind == "ifndef":
                stack.append(f"!defined({expression})")
            elif kind == "elif":
                if not stack:
                    raise AssertionError("unmatched #elif")
                stack[-1] = expression
            elif kind == "else":
                if not stack:
                    raise AssertionError("unmatched #else")
                # Require an explicit guard in the active branch instead of
                # inferring the inverse of an arbitrary expression.
                stack[-1] = "<else>"
            else:
                if not stack:
                    raise AssertionError("unmatched #endif")
                stack.pop()

        index += 1

    if stack:
        raise AssertionError("unterminated preprocessor conditional")
    return conditions


def condition_excludes_wasm(condition: str) -> bool:
    compact = re.sub(r"\s+", "", condition)
    return (
        "||" not in compact
        and "!BUILDFLAG(IS_WASM)" in compact
    )


class M3IpcSourceContractTest(unittest.TestCase):
    def assert_code_occurrences_guarded(
        self,
        path: str,
        contents: str,
        pattern: str,
        predicate: Callable[[str], bool],
        *,
        require_match: bool = True,
    ) -> list[int]:
        code = code_without_comments(contents)
        matches = list(
            re.finditer(pattern, code, flags=re.MULTILINE | re.DOTALL)
        )
        if require_match:
            self.assertTrue(
                matches, f"{path}: no matches for {pattern!r}"
            )

        conditions = preprocessor_conditions_by_line(contents)
        lines: list[int] = []
        for match in matches:
            line = code.count("\n", 0, match.start()) + 1
            lines.append(line)
            active = conditions[line]
            with self.subTest(path=path, line=line, pattern=pattern):
                self.assertTrue(
                    any(predicate(condition) for condition in active),
                    f"{path}:{line}: {match.group(0)!r} has guards "
                    f"{active}, none of which enforce the required "
                    "Wasm exclusion",
                )
        return lines

    def test_shared_memory_ipc_fails_explicitly_without_platform_handles(
        self,
    ) -> None:
        source = (ROOT_DIR / "ipc/param_traits_utils.cc").read_text(
            encoding="utf-8"
        )
        write = source.split(
            "void ParamTraits<base::subtle::PlatformSharedMemoryRegion>::Write",
            1,
        )[1].split(
            "bool ParamTraits<base::subtle::PlatformSharedMemoryRegion>::Read",
            1,
        )[0]
        read = source.split(
            "bool ParamTraits<base::subtle::PlatformSharedMemoryRegion>::Read",
            1,
        )[1].split(
            "void ParamTraits<base::subtle::PlatformSharedMemoryRegion::Mode>",
            1,
        )[0]

        for body in (write, read):
            with self.subTest(body=body[:24]):
                self.assertIn("#if BUILDFLAG(IS_WASM)", body)
        self.assertIn(
            'CHECK(false) << "IPC shared memory transport is unsupported on '
            'Wasm";',
            write,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n  return false;\n#else",
            read,
        )

    def test_wasm_excludes_named_and_server_channel_apis(self) -> None:
        def read(path: str) -> str:
            return (ROOT_DIR / path).read_text(encoding="utf-8")

        platform_build = read("mojo/public/cpp/platform/BUILD.gn")
        invitation_header = read("mojo/public/cpp/system/invitation.h")
        invitation = read("mojo/public/cpp/system/invitation.cc")
        isolated_header = read(
            "mojo/public/cpp/system/isolated_connection.h"
        )
        isolated = read(
            "mojo/public/cpp/system/isolated_connection.cc"
        )
        ipcz = read("mojo/core/ipcz_driver/invitation.cc")

        platform_target = braced_block(
            platform_build,
            'component("platform")',
        )
        wasm_sources = braced_block(
            platform_target,
            "if (is_wasm && enable_chromium_wasm_port)",
        )
        self.assertIn("platform_channel_wasm.cc", wasm_sources)
        self.assertIn("platform_channel_endpoint_wasm.cc", wasm_sources)
        self.assertNotIn("NamedPlatformChannel", wasm_sources)
        self.assertNotIn("server", wasm_sources.lower())

        server_api_paths = {
            "mojo/public/cpp/system/invitation.h": invitation_header,
            "mojo/public/cpp/system/invitation.cc": invitation,
            "mojo/public/cpp/system/isolated_connection.h": isolated_header,
            "mojo/public/cpp/system/isolated_connection.cc": isolated,
        }
        server_api_count = 0
        server_include_count = 0
        for path, contents in server_api_paths.items():
            server_api_count += len(
                self.assert_code_occurrences_guarded(
                    path,
                    contents,
                    r"\bPlatformChannelServerEndpoint\b",
                    condition_excludes_wasm,
                )
            )
            server_include_count += len(
                self.assert_code_occurrences_guarded(
                    path,
                    contents,
                    r"platform_channel_server(?:_endpoint)?\.h",
                    condition_excludes_wasm,
                    require_match=False,
                )
            )
        self.assertGreater(server_api_count, 0)
        self.assertGreater(server_include_count, 0)

        ipcz_code = code_without_comments(ipcz)
        self.assertNotIn(
            "platform_channel_server_endpoint.h",
            ipcz_code,
        )
        self.assertNotIn("PlatformChannelServerEndpoint", ipcz_code)
        self.assertIn(
            "ScopedMessagePipeHandle IsolatedConnection::Connect(\n"
            "    PlatformChannelEndpoint endpoint)",
            isolated,
        )
        endpoint_send_marker = (
            "void OutgoingInvitation::Send(OutgoingInvitation invitation,\n"
            "                              base::ProcessHandle "
            "target_process,\n"
            "                              PlatformChannelEndpoint "
            "channel_endpoint,"
        )
        self.assertEqual(invitation.count(endpoint_send_marker), 1)
        endpoint_send_line = invitation.count(
            "\n", 0, invitation.index(endpoint_send_marker)
        ) + 1
        endpoint_send_conditions = preprocessor_conditions_by_line(
            invitation
        )[endpoint_send_line]
        self.assertFalse(
            any(
                "BUILDFLAG(IS_WASM)" in condition
                for condition in endpoint_send_conditions
            ),
            "the PlatformChannelEndpoint Send overload must remain "
            f"available on Wasm, but has guards {endpoint_send_conditions}",
        )
        endpoint_send = braced_block(invitation, endpoint_send_marker)
        self.assertIn(
            "channel_endpoint.TakePlatformHandle()",
            endpoint_send,
        )
        self.assertNotIn("server_endpoint", endpoint_send)

    def test_wasm_has_no_legacy_isolated_channel_fallback(self) -> None:
        path = "mojo/public/cpp/system/isolated_connection.cc"
        isolated = (ROOT_DIR / path).read_text(encoding="utf-8")

        for pattern in (
            r"mojo/public/cpp/platform/platform_channel\.h",
            r"\bPlatformChannel\s+\w+\s*;",
            r"!\s*mojo::core::IsMojoIpczEnabled\(\)",
            r"\bchannel\.TakeLocalEndpoint\(\)",
        ):
            self.assert_code_occurrences_guarded(
                path,
                isolated,
                pattern,
                condition_excludes_wasm,
            )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exercise three clean package lifetimes in one fresh real browser.

This deliberately starts from the immutable package server snapshot used by
the ordinary package browser smoke.  Each lifetime must bind to a new outer
document URL and time origin, report a real host frame, retain its bounded
document-scoped core host-bridge Resource Timing receipt, retain an exact
same-origin local-server successful-GET receipt under an opaque test-only
epoch path, and complete both the native and Emscripten exit channels with
zero.  It is a fixed, bounded reload observation, not evidence of long-run
reliability, leak freedom, general HTTP caching, persistence, or M9 release
completion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

if __package__:
    from . import package as package_tool
    from . import run_m9_package_browser_smoke as package_browser_smoke
    from .m0_common import M0Error, parse_timeout
else:
    import package as package_tool
    import run_m9_package_browser_smoke as package_browser_smoke

    from m0_common import M0Error, parse_timeout


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE_OUTER_DOCUMENT_RELOAD_STRESS"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
PASS_MARKER = f"{SENTINEL}:PASS"
FAIL_MARKER = f"{SENTINEL}:FAIL"
EPOCH_COUNT = package_browser_smoke.OUTER_DOCUMENT_RELOAD_STRESS_EPOCH_COUNT
RESTART_COUNT = package_browser_smoke.OUTER_DOCUMENT_RELOAD_STRESS_RESTART_COUNT
SCOPE = package_browser_smoke.OUTER_DOCUMENT_RELOAD_STRESS_SCOPE
LIMITATIONS = package_browser_smoke.OUTER_DOCUMENT_RELOAD_STRESS_LIMITATIONS

_EPOCH_FIELDS = frozenset(
    (
        "frames_presented",
        "post_exit_frame_quiescent",
        "process_exit_code",
        "runtime_core_resource_receipt",
        "runtime_core_server_receipt",
        "runtime_exit_code",
        "shutdown_disabled",
        "shutdown_requested",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "browser_version",
        "distinct_document_epoch_count",
        "distinct_document_time_origin_count",
        "epochs",
        "limitations",
        "m9_gate_complete",
        "outer_document_epoch_count",
        "outer_document_restarts",
        "performance_gate",
        "release_status",
        "scope",
        "served_version_json_sha256",
    )
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_nonempty_string(value: object, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise M0Error(f"package reload stress {description} is invalid")
    return value


def _require_nonnegative_integer(value: object, description: str) -> int:
    if type(value) is not int or value < 0:
        raise M0Error(f"package reload stress {description} is invalid")
    return value


def validate_reload_stress_result(value: object) -> dict[str, object]:
    """Reject any result that loses a fixed package-lifetime guarantee."""

    if not isinstance(value, dict) or set(value) != _RESULT_FIELDS:
        raise M0Error("package reload stress result fields are invalid")
    result: dict[str, object] = value
    _require_nonempty_string(result["browser_version"], "browser version")
    version_identity = _require_nonempty_string(
        result["served_version_json_sha256"], "served VERSION.json identity"
    )
    if not _SHA256_RE.fullmatch(version_identity):
        raise M0Error("package reload stress served VERSION.json identity is invalid")
    if result["release_status"] != package_tool.RELEASE_STATUS:
        raise M0Error("package reload stress release status is invalid")
    if result["scope"] != SCOPE:
        raise M0Error("package reload stress scope is invalid")
    if result["m9_gate_complete"] is not False:
        raise M0Error("package reload stress must not complete M9")
    if result["performance_gate"] is not False:
        raise M0Error("package reload stress must not set a performance gate")
    if result["limitations"] != list(LIMITATIONS):
        raise M0Error("package reload stress limitations are invalid")
    if (
        type(result["outer_document_epoch_count"]) is not int
        or result["outer_document_epoch_count"] != EPOCH_COUNT
    ):
        raise M0Error("package reload stress epoch count is invalid")
    if (
        type(result["outer_document_restarts"]) is not int
        or result["outer_document_restarts"] != RESTART_COUNT
    ):
        raise M0Error("package reload stress restart count is invalid")
    for field in (
        "distinct_document_epoch_count",
        "distinct_document_time_origin_count",
    ):
        if type(result[field]) is not int or result[field] != EPOCH_COUNT:
            raise M0Error(f"package reload stress {field} is invalid")

    epochs = result["epochs"]
    if not isinstance(epochs, list) or len(epochs) != EPOCH_COUNT:
        raise M0Error("package reload stress epoch results are invalid")
    for index, epoch in enumerate(epochs, start=1):
        if not isinstance(epoch, dict) or set(epoch) != _EPOCH_FIELDS:
            raise M0Error(f"package reload stress epoch {index} fields are invalid")
        if _require_nonnegative_integer(
            epoch["frames_presented"], f"epoch {index} frame count"
        ) < 1:
            raise M0Error(f"package reload stress epoch {index} lacks a frame")
        if epoch["post_exit_frame_quiescent"] is not True:
            raise M0Error(
                f"package reload stress epoch {index} lacks post-exit frame quiescence"
            )
        try:
            package_browser_smoke.validate_runtime_core_resource_receipt(
                epoch["runtime_core_resource_receipt"]
            )
        except M0Error as error:
            raise M0Error(
                "package reload stress epoch "
                f"{index} runtime resource receipt is invalid"
            ) from error
        try:
            package_browser_smoke.validate_runtime_core_server_receipt(
                epoch["runtime_core_server_receipt"]
            )
        except M0Error as error:
            raise M0Error(
                "package reload stress epoch "
                f"{index} runtime server receipt is invalid"
            ) from error
        if (
            type(epoch["runtime_exit_code"]) is not int
            or type(epoch["process_exit_code"]) is not int
            or epoch["runtime_exit_code"] != 0
            or epoch["process_exit_code"] != 0
        ):
            raise M0Error(f"package reload stress epoch {index} exit is unclean")
        if (
            epoch["shutdown_disabled"] is not True
            or epoch["shutdown_requested"] is not True
        ):
            raise M0Error(f"package reload stress epoch {index} shutdown is invalid")
    return result


def run_package_outer_document_reload_stress(
    *,
    dist_dir: Path,
    browser_argument: Path | None,
    no_sandbox: bool,
    timeout: float,
) -> dict[str, object]:
    """Run exactly three independently acknowledged outer package documents."""

    result = package_browser_smoke.run_package_browser_smoke(
        dist_dir=dist_dir,
        browser_argument=browser_argument,
        no_sandbox=no_sandbox,
        timeout=timeout,
        outer_document_restart=False,
        outer_document_restart_count=RESTART_COUNT,
        release_wisp_endpoint=None,
        emit_package_observation=False,
    )
    return validate_reload_stress_result(result)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run three bounded clean outer-document package lifetimes in one "
            "real browser."
        )
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 30:
        parser.error("--timeout must allow all three package lifetimes")
    try:
        result = run_package_outer_document_reload_stress(
            dist_dir=args.dist_dir,
            browser_argument=args.browser,
            no_sandbox=args.no_sandbox,
            timeout=args.timeout,
        )
        print(
            RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError) as error:
        print(f"{FAIL_MARKER} reason={error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

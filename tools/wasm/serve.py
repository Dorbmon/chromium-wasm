#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import secrets
import sys
import threading
from typing import Any
from urllib.parse import urlencode, urlsplit

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    fail,
    load_manifest,
    print_context,
)


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".map": "application/json",
    ".wasm": "application/wasm",
}


@dataclass(frozen=True)
class SmokeCase:
    module_name: str
    sentinel_prefix: str
    required_stdout: tuple[str, ...]
    required_stderr: tuple[str, ...] = ()
    require_separate_streams: bool = False
    minimum_runtime_ms: int = 200


TASK_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M1_TASK:RESULT",
    "immediate=ok",
    "delayed_not_early=ok",
    "delayed_deadline_order=ok",
    "worker_to_app_wake=ok",
    "app_to_worker=ok",
    "nested_quit_independent=ok",
    "outer_continues=ok",
    "sleeping_quit_wake=ok",
    "idle_wait_bounded=ok",
    "clean_shutdown=ok",
    "task_count=18",
    "delayed_wake_count=3",
    "max_nesting=2",
    "joinable_created=1",
    "joinable_joined=1",
    "wake_count_bounded_nonzero=ok",
    "wait_count_bounded_nonzero=ok",
    "browser_heartbeat=external",
)

RUST_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M1_RUST:RESULT",
    "cpp_to_rust=ok",
    "rust_to_cpp=ok",
    "cxx_bridge=ok",
    "structured_abi=ok",
    "integer_widths=ok",
    "pointer_width=32",
    "vec=ok",
    "string=ok",
    "allocation=ok",
    "free=ok",
    "atomics=ok",
    "arc=ok",
    "mutex=ok",
    "thread_spawn=ok",
    "thread_join=ok",
    "callback_count=1",
    "drop_count=1",
    "same_module=ok",
    "clean_shutdown=ok",
    "browser_heartbeat=external",
)

SHARED_MEMORY_RESULT_VALUES = {
    "capability_handle": "ok",
    "writable_create": "ok",
    "writable_map": "ok",
    "byte_round_trip": "ok",
    "handle_move": "ok",
    "serialization_round_trip": "ok",
    "mapping_outlives_handle": "ok",
    "writable_to_read_only": "ok",
    "read_only_create": "ok",
    "read_only_duplicate": "ok",
    "read_only_write_rejected": "ok",
    "mode_mismatch_rejected": "ok",
    "writable_duplicate_rejected": "ok",
    "invalid_capability_rejected": "ok",
    "stale_capability_rejected": "ok",
    "corrupt_metadata_rejected": "ok",
    "corrupt_rights_rejected": "ok",
    "unsafe_create": "ok",
    "unsafe_duplicate": "ok",
    "partial_map": "ok",
    "invalid_range_rejected": "ok",
    "zero_size_rejected": "ok",
    "minimum_alignment": "32",
    "vm_alignment": "65536",
    "guid_identity": "ok",
    "region_lifetime": "ok",
    "concurrent_threads": "ok",
    "concurrent_overlap": "ok",
    "worker_threads_created": "1",
    "worker_threads_joined": "1",
    "worker_creation_failures": "0",
    "max_concurrent_test_threads": "2",
    "clean_shutdown": "ok",
    "memory_metrics": "ok",
    "browser_heartbeat": "external",
}
SHARED_MEMORY_METRIC_NAMES = (
    "initial_heap_bytes",
    "peak_heap_bytes",
    "max_heap_bytes",
)
SHARED_MEMORY_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M1_SHARED_MEMORY:RESULT",
    "CHROMIUM_WASM_M1_SHARED_MEMORY:METRICS",
    *(f"{key}={value}" for key, value in SHARED_MEMORY_RESULT_VALUES.items()),
    "initial_heap_bytes=",
    "peak_heap_bytes=",
    "max_heap_bytes=2147483648",
)

MOJO_RESULT_VALUES = {
    "single_node": "ok",
    "message_pipe_create": "ok",
    "empty_pipe_should_wait": "ok",
    "shared_buffer_create": "ok",
    "sender_map": "ok",
    "deterministic_write": "ok",
    "shared_buffer_attach": "ok",
    "message_write": "ok",
    "message_read": "ok",
    "shared_buffer_extract": "ok",
    "receiver_map": "ok",
    "payload_verified": "ok",
    "unsafe_duplicate": "ok",
    "duplicate_map": "ok",
    "receiver_modify": "ok",
    "sender_observed_modify": "ok",
    "duplicate_unmap_accounting": "ok",
    "invalid_region_rejected": "ok",
    "use_after_final_close_rejected": "ok",
    "oversized_create_rejected": "ok",
    "oversized_map_rejected": "ok",
    "readonly_after_unsafe_rejected": "ok",
    "readonly_mode_mismatch_rejected": "ok",
    "corrupt_metadata_rejected": "ok",
    "remote_transport_rejected": "ok",
    "driver_failures_rejected": "ok",
    "mapping_outlives_handles": "ok",
    "all_handles_closed": "ok",
    "clean_shutdown": "ok",
    "memory_metrics": "ok",
    "browser_heartbeat": "external",
}
MOJO_METRIC_NAMES = (
    "initial_heap_bytes",
    "peak_heap_bytes",
    "max_heap_bytes",
)
MOJO_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M1_MOJO:RESULT",
    "CHROMIUM_WASM_M1_MOJO:METRICS",
    *(f"{key}={value}" for key, value in MOJO_RESULT_VALUES.items()),
    "initial_heap_bytes=",
    "peak_heap_bytes=",
    "max_heap_bytes=2147483648",
)


SMOKE_CASES = {
    "hello": SmokeCase(
        module_name="hello_wasm.js",
        sentinel_prefix="CHROMIUM_WASM_M0",
        required_stdout=(
            "CHROMIUM_WASM_M0:RUNTIME_START",
            "CHROMIUM_WASM_M0:RUNTIME_END",
            "CHROMIUM_WASM_M0:STDOUT",
            "CHROMIUM_WASM_M0:PASS",
        ),
        required_stderr=("CHROMIUM_WASM_M0:STDERR capture=ok",),
        require_separate_streams=True,
    ),
    "base": SmokeCase(
        module_name="m1_base_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M1_BASE",
        required_stdout=(
            "CHROMIUM_WASM_M1_BASE:RUNTIME_START",
            "CHROMIUM_WASM_M1_BASE:RUNTIME_END",
            "CHROMIUM_WASM_M1_BASE:RESULT",
            "CHROMIUM_WASM_M1_BASE:PASS",
        ),
    ),
    "tasks": SmokeCase(
        module_name="m1_task_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M1_TASK",
        required_stdout=(
            "CHROMIUM_WASM_M1_TASK:RUNTIME_START",
            "CHROMIUM_WASM_M1_TASK:RUNTIME_END",
            *TASK_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M1_TASK:PASS",
        ),
    ),
    "rust": SmokeCase(
        module_name="m1_rust_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M1_RUST",
        required_stdout=(
            "CHROMIUM_WASM_M1_RUST:RUNTIME_START",
            "CHROMIUM_WASM_M1_RUST:RUNTIME_END",
            *RUST_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M1_RUST:PASS",
        ),
    ),
    "shared_memory": SmokeCase(
        module_name="m1_shared_memory_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M1_SHARED_MEMORY",
        required_stdout=(
            "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_START",
            "CHROMIUM_WASM_M1_SHARED_MEMORY:RUNTIME_END",
            *SHARED_MEMORY_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M1_SHARED_MEMORY:PASS",
        ),
        minimum_runtime_ms=250,
    ),
    "mojo": SmokeCase(
        module_name="m1_mojo_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M1_MOJO",
        required_stdout=(
            "CHROMIUM_WASM_M1_MOJO:RUNTIME_START",
            "CHROMIUM_WASM_M1_MOJO:RUNTIME_END",
            *MOJO_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M1_MOJO:PASS",
        ),
        minimum_runtime_ms=250,
    ),
}


def smoke_case(name: str) -> SmokeCase:
    try:
        return SMOKE_CASES[name]
    except KeyError as exc:
        raise M0Error(f"unsupported smoke case: {name}") from exc


def _parse_contract_line(
    stdout: str, prefix: str
) -> dict[str, str]:
    matches = [
        line
        for line in stdout.splitlines()
        if line.startswith(f"{prefix} ")
    ]
    if len(matches) != 1:
        raise M0Error(f"expected exactly one {prefix} line")

    fields: dict[str, str] = {}
    for field in matches[0][len(prefix) + 1 :].split():
        key, separator, value = field.partition("=")
        if not separator or not key or not value:
            raise M0Error(f"malformed {prefix} field: {field}")
        if key in fields:
            raise M0Error(f"duplicate {prefix} field: {key}")
        fields[key] = value
    return fields


def validate_case_stdout(name: str, stdout: str) -> None:
    if name == "shared_memory":
        display_name = "shared-memory"
        sentinel_prefix = "CHROMIUM_WASM_M1_SHARED_MEMORY"
        result_values = SHARED_MEMORY_RESULT_VALUES
        metric_names = SHARED_MEMORY_METRIC_NAMES
    elif name == "mojo":
        display_name = "Mojo"
        sentinel_prefix = "CHROMIUM_WASM_M1_MOJO"
        result_values = MOJO_RESULT_VALUES
        metric_names = MOJO_METRIC_NAMES
    else:
        return

    lines = stdout.splitlines()
    runtime_start = f"{sentinel_prefix}:RUNTIME_START"
    runtime_end = f"{sentinel_prefix}:RUNTIME_END"
    pass_sentinel = f"{sentinel_prefix}:PASS"
    result_prefix = f"{sentinel_prefix}:RESULT"
    result = _parse_contract_line(stdout, result_prefix)
    if result != result_values:
        missing = sorted(result_values.keys() - result.keys())
        unexpected = sorted(result.keys() - result_values.keys())
        mismatched = sorted(
            key
            for key in result.keys() & result_values.keys()
            if result[key] != result_values[key]
        )
        raise M0Error(
            f"{result_prefix} mismatch: missing={missing}, "
            f"unexpected={unexpected}, mismatched={mismatched}"
        )

    metrics_prefix = f"{sentinel_prefix}:METRICS"
    metrics = _parse_contract_line(stdout, metrics_prefix)
    for marker in (runtime_start, runtime_end, pass_sentinel):
        if lines.count(marker) != 1:
            raise M0Error(f"expected exactly one {marker} line")
    try:
        runtime_start_index = lines.index(runtime_start)
        runtime_end_index = lines.index(runtime_end)
        metrics_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith(f"{metrics_prefix} ")
        )
        result_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith(f"{result_prefix} ")
        )
        pass_index = lines.index(pass_sentinel)
    except (StopIteration, ValueError) as exc:
        raise M0Error(f"{display_name} runtime markers are incomplete") from exc
    if not (
        runtime_start_index
        < runtime_end_index
        < metrics_index
        < result_index
        < pass_index
    ):
        raise M0Error(f"{display_name} runtime markers are out of order")

    if set(metrics) != set(metric_names):
        raise M0Error(f"{metrics_prefix} fields do not match the contract")
    if any(
        not metrics[name].isascii() or not metrics[name].isdecimal()
        for name in metric_names
    ):
        raise M0Error(f"{metrics_prefix} values must be decimal integers")

    initial = int(metrics["initial_heap_bytes"])
    peak = int(metrics["peak_heap_bytes"])
    maximum = int(metrics["max_heap_bytes"])
    if initial <= 0 or peak < initial or peak > maximum:
        raise M0Error(f"{metrics_prefix} values are out of range")
    if maximum != 2147483648:
        raise M0Error(f"{metrics_prefix} maximum memory changed")


def artifact_names(case: SmokeCase) -> tuple[str, ...]:
    module_path = Path(case.module_name)
    wasm_name = module_path.with_suffix(".wasm").name
    return case.module_name, wasm_name, f"{wasm_name}.map"


@dataclass
class ServerState:
    token: str
    out_dir: Path
    result_queue: queue.Queue[dict[str, Any]]
    smoke_case_name: str
    smoke_case: SmokeCase
    verbose: bool = False
    result_received: bool = False
    result_lock: threading.Lock = field(default_factory=threading.Lock)


def artifact_for_request(
    state: ServerState, request_path: str
) -> Path | None:
    allowed_artifacts = {
        f"/out/wasm/{name}": state.out_dir / name
        for name in artifact_names(state.smoke_case)
    }
    artifact = allowed_artifacts.get(request_path)
    if artifact is None or not artifact.is_file():
        return None
    return artifact


class M0RequestHandler(BaseHTTPRequestHandler):
    server_version = "ChromiumWasmM0/1"

    @property
    def state(self) -> ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, format_string: str, *args: object) -> None:
        if self.state.verbose:
            super().log_message(format_string, *args)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path in (
            "/",
            f"/__smoke__/{self.state.smoke_case_name}",
        ):
            host_page = Path(__file__).with_name("host") / "hello.html"
            self._send_bytes(
                host_page.read_bytes(), CONTENT_TYPES[host_page.suffix]
            )
            return

        artifact = artifact_for_request(self.state, request_path)
        if artifact is None:
            self.send_error(404)
            return
        self._send_bytes(
            artifact.read_bytes(),
            CONTENT_TYPES.get(artifact.suffix, "application/octet-stream"),
        )

    def do_POST(self) -> None:
        request_path = urlsplit(self.path).path
        expected_path = f"/__smoke__/result/{self.state.token}"
        if request_path != expected_path:
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length <= 0 or length > 1024 * 1024:
            self.send_error(413)
            return
        try:
            result = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return
        if not isinstance(result, dict) or result.get("protocol") != 1:
            self.send_error(400)
            return

        with self.state.result_lock:
            if self.state.result_received:
                self.send_error(409)
                return
            self.state.result_received = True
            self.state.result_queue.put_nowait(result)
        self._send_bytes(b'{"accepted":true}\n', "application/json")


class M0HTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        state: ServerState,
    ) -> None:
        self.state = state
        super().__init__(address, M0RequestHandler)


def create_server(
    bind: str,
    port: int,
    out_dir: Path,
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    smoke_case_name: str = "hello",
    verbose: bool = False,
) -> M0HTTPServer:
    resolved_out_dir = out_dir.resolve()
    selected_case = smoke_case(smoke_case_name)
    for artifact_name in artifact_names(selected_case)[:2]:
        if not (resolved_out_dir / artifact_name).is_file():
            raise M0Error(
                f"{artifact_name} is missing from the output directory"
            )
    state = ServerState(
        token=token,
        out_dir=resolved_out_dir,
        result_queue=result_queue,
        smoke_case_name=smoke_case_name,
        smoke_case=selected_case,
        verbose=verbose,
    )
    return M0HTTPServer((bind, port), state)


def smoke_url(
    server: M0HTTPServer,
    token: str,
    manifest: dict[str, Any],
    port_commit: str,
    timeout_seconds: float = 20.0,
    smoke_case_name: str = "hello",
) -> str:
    selected_case = smoke_case(smoke_case_name)
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": smoke_case_name,
            "chromium": manifest["chromium"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
            "module": f"/out/wasm/{selected_case.module_name}",
            "port": port_commit,
            "token": token,
            "timeout_ms": max(
                1000, min(120000, int(timeout_seconds * 1000))
            ),
            "v8": manifest["git_dependencies"]["v8"]["revision"],
        }
    )
    return f"http://{host}:{port}/__smoke__/{smoke_case_name}?{query}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve the M0 host page with cross-origin isolation headers."
    )
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm"))
    parser.add_argument(
        "--case", choices=tuple(SMOKE_CASES), default="hello"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        token = secrets.token_urlsafe(24)
        results: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        out_dir = args.out_dir
        if not out_dir.is_absolute():
            out_dir = REPO_ROOT / out_dir
        server = create_server(
            args.bind,
            args.port,
            out_dir,
            token,
            results,
            smoke_case_name=args.case,
            verbose=args.verbose,
        )
        port_commit = checked_output(["git", "rev-parse", "HEAD"])
        print_context(
            "serve.py",
            manifest,
            bind=args.bind,
            case=args.case,
            port=server.server_address[1],
        )
        selected_case = smoke_case(args.case)
        url = smoke_url(
            server,
            token,
            manifest,
            port_commit,
            smoke_case_name=args.case,
        )
        print(
            f"{selected_case.sentinel_prefix}:SERVE {url}",
            flush=True,
        )
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())

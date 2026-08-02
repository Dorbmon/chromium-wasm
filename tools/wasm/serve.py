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
    gn_args_key: str = "gn_args"


BASE_RESULT_VALUES = {
    "wall_time": "ok",
    "monotonic_time": "ok",
    "bounded_sleep": "ok",
    "secure_entropy": "ok",
    "worker_entropy": "ok",
    "platform_thread": "ok",
    "thread_ids": "ok",
    "thread_names": "diagnostic_ok",
    "yield_sleep": "ok",
    "atomic_handoff": "ok",
    "tls": "ok",
    "tls_destructors": "ok",
    "lock": "ok",
    "lock_try": "ok",
    "condition_signal": "ok",
    "condition_broadcast": "ok",
    "condition_timeout": "ok",
    "event_manual": "ok",
    "event_auto": "ok",
    "event_reset": "ok",
    "event_timeout": "ok",
    "event_wait_many": "ok",
    "bidirectional": "ok",
    "joins": "ok",
    "path_current": "ok",
    "path_temp": "ok",
    "path_home": "ok",
    "path_executable": "unsupported",
    "path_module": "unsupported",
    "temp_workspace": "ok",
    "file_empty": "ok",
    "filesystem": "memfs",
    "file_binary_nul": "ok",
    "file_seek": "ok",
    "file_middle_overwrite": "ok",
    "file_append": "ok",
    "file_truncate": "ok",
    "file_zero_fill": "ok",
    "file_flush": "memfs_only",
    "file_reopen": "ok",
    "file_rename_stat": "ok",
    "directories": "ok",
    "enumeration": "ok",
    "file_errors": "ok",
    "parent_traversal": "denied",
    "file_lock": "invalid_operation",
    "closed_fd": "ebadf",
    "cleanup": "ok",
    "process_identity": "ok",
    "process_handle": "ok",
    "unique_proc_id": "ok",
    "process_current": "ok",
    "process_duplicate": "ok",
    "process_release_close": "ok",
    "process_open_noncurrent": "invalid",
    "process_control": "unsupported",
    "process_launch": "unsupported",
    "process_output": "unsupported",
    "sysinfo_processors": "ok",
    "page_size": "65536",
    "allocation_granularity": "65536",
    "wasm_heap": "current_ok",
    "virtual_memory": "wasm_max",
    "physical_memory": "unavailable",
    "disk_space": "unavailable",
    "os_name": "emscripten",
    "os_arch": "wasm32",
    "cpu_arch": "wasm32",
    "cpu_model": "unavailable",
    "uptime": "runtime_clock",
    "browser_main_free": "ok",
}
BASE_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M1_BASE:RESULT",
    *(f"{key}={value}" for key, value in BASE_RESULT_VALUES.items()),
)

TASK_RESULT_VALUES = {
    "immediate": "ok",
    "delayed_not_early": "ok",
    "delayed_deadline_order": "ok",
    "worker_to_app_wake": "ok",
    "app_to_worker": "ok",
    "nested_quit_independent": "ok",
    "outer_continues": "ok",
    "sleeping_quit_wake": "ok",
    "idle_wait_bounded": "ok",
    "clean_shutdown": "ok",
    "task_count": "18",
    "delayed_wake_count": "3",
    "wake_count_bounded_nonzero": "ok",
    "wait_count_bounded_nonzero": "ok",
    "max_nesting": "2",
    "nested_begin_count": "1",
    "nested_exit_count": "1",
    "joinable_created": "1",
    "joinable_joined": "1",
    "wait_counter_source": "delegate_idle_cycles",
    "browser_heartbeat": "external",
}
TASK_RESULT_NUMERIC_NAMES = (
    "wake_count",
    "wait_count",
    "idle_wake_returns",
    "worker_to_app_latency_ms",
    "sleeping_quit_latency_ms",
    "idle_elapsed_ms",
    "idle_wake_latency_ms",
)
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

RUST_RESULT_VALUES = {
    "cpp_to_rust": "ok",
    "rust_to_cpp": "ok",
    "cxx_bridge": "ok",
    "structured_abi": "ok",
    "integer_widths": "ok",
    "pointer_width": "32",
    "vec": "ok",
    "string": "ok",
    "allocation": "ok",
    "free": "ok",
    "atomics": "ok",
    "arc": "ok",
    "mutex": "ok",
    "thread_spawn": "ok",
    "thread_join": "ok",
    "callback_count": "1",
    "drop_count": "1",
    "same_module": "ok",
    "clean_shutdown": "ok",
    "browser_heartbeat": "external",
}
RUST_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M1_RUST:RESULT",
    *(f"{key}={value}" for key, value in RUST_RESULT_VALUES.items()),
)

V8_BASE_RESULT_VALUES = {
    "host": "wasm32",
    "target": "arm",
    "simulator_config": "arm",
    "jitless_config": "on",
    "threads": "ok",
    "tls": "ok",
    "time": "ok",
    "entropy": "ok",
    "stack_bounds": "ok",
    "stack_trace": "unsupported_reported",
    "page_allocator": "logical_ok",
    "file_mapping": "buffered_ok",
}
V8_BASE_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M2_V8_BASE:RESULT",
    *(f"{key}={value}" for key, value in V8_BASE_RESULT_VALUES.items()),
)

V8_SNAPSHOTLESS_RESULT_VALUES = {
    "value": "100:42:42:0:1234567890123456800",
    "arrays": "ok",
    "closures": "ok",
    "regexp": "interpreter",
    "json": "ok",
    "bigint": "ok",
    "lookup_pair": "ok",
    "fp_calls": "ok",
    "classes": "ok",
    "exceptions": "js_and_native",
    "stacks": "js_callers",
    "promises": "explicit_checkpoint",
    "async": "ok",
    "proxy": "ok",
    "typed_arrays": "ok",
    "native_callback": "ok",
    "gc_stress": "ok",
    "gc_reclamation": "verified_after_isolate_disposal",
    "modules": "graph_tla",
    "timers": "delayed_foreground",
    "test262": "ok",
    "test262_revision": "7e115f46ac64340827d505fa928ad436cb7ba5a6",
    "test262_license_notice": "embedded",
    "test262_license_sha256": (
        "4dd9244dfe8197c75348c4b24ab53d29"
        "d3b1cfad143ac76b5a3d8942aa354ce0"
    ),
    "test262_pack_sha256": (
        "c290b8630ed71553ac1ceda6493fa4b5"
        "1614593163d84c3b7baa27779e09d53b"
    ),
    "startup_snapshot": "runtime_generated",
    "external_startup_data": "off",
    "snapshot_anchor": "retained_during_cycles",
    "isolate": "ordinary",
    "lifecycle_cycles": "3",
    "metrics_scope": "ordinary_isolates",
    "heap_sampling": "feature_gc_and_cycle",
    "i18n": "off",
    "host": "wasm32",
    "target": "arm",
    "simulator": "arm",
    "jitless": "on",
    "version": "15.0.245.21",
}
V8_SNAPSHOTLESS_RESULT_NUMERIC_NAMES = (
    "native_callback_calls",
    "feature_cycles",
    "gc_cycles",
    "module_cycles",
    "module_resolve_calls",
    "timer_delay_ms",
    "timer_elapsed_us",
    "timer_cycles",
    "test262_license_bytes",
    "test262_license_fnv1a",
    "test262_embedded_source_bytes",
    "test262_cases",
    "test262_executions",
    "test262_passed",
    "test262_failed",
    "test262_scripts",
    "test262_modules",
    "test262_strict",
    "test262_sloppy",
    "test262_async",
    "test262_negative_parse",
    "test262_negative_runtime",
    "test262_negative_resolution",
    "test262_detach_calls",
    "test262_resolver_calls",
    "test262_module_compile_attempts",
    "test262_runtime_ms",
    "snapshot_bytes",
    "snapshot_create_ms",
    "isolate_runs_ms",
    "runtime_ms",
    "v8_heap_total_max_sampled_bytes",
    "v8_heap_used_max_sampled_bytes",
    "v8_heap_physical_max_sampled_bytes",
    "v8_malloced_max_sampled_bytes",
    "v8_peak_malloced_bytes",
    "v8_external_max_sampled_bytes",
    "v8_heap_limit_bytes",
    "v8_total_allocated_max_per_isolate_bytes",
    "v8_shared_read_only_used_bytes",
    "array_buffer_peak_bytes",
    "wasm_linear_initial_bytes",
    "wasm_linear_after_cycle_1_bytes",
    "wasm_linear_after_cycle_2_bytes",
    "wasm_linear_after_cycle_3_bytes",
    "wasm_linear_peak_bytes",
    "wasm_linear_limit_bytes",
)
V8_SNAPSHOTLESS_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M2_V8_JS:RESULT",
    *(
        f"{key}={value}"
        for key, value in V8_SNAPSHOTLESS_RESULT_VALUES.items()
    ),
)
V8_SNAPSHOTLESS_STAGE_NAMES = (
    "platform_create_begin",
    "platform_create_end",
    "platform_initialize_end",
    "v8_initialize_end",
    "snapshot_creator_begin",
    "snapshot_create_begin",
    "snapshot_create_end",
    "ordinary_isolate_begin",
    "script_compile_end",
    "script_run_end",
    "microtask_checkpoint_end",
    "module_graph_end",
    "gc_stress_end",
    "delayed_task_end",
    "ordinary_isolate_dispose_end",
    "ordinary_isolate_begin",
    "script_compile_end",
    "script_run_end",
    "microtask_checkpoint_end",
    "module_graph_end",
    "ordinary_isolate_dispose_end",
    "ordinary_isolate_begin",
    "script_compile_end",
    "script_run_end",
    "microtask_checkpoint_end",
    "module_graph_end",
    "ordinary_isolate_dispose_end",
)
V8_SNAPSHOTLESS_TEST262_CASES = (
    (
        "test/built-ins/Object/fromEntries/evaluation-order.js",
        ("sloppy", "strict"),
    ),
    (
        "test/language/expressions/function/scope-name-var-close.js",
        ("sloppy", "strict"),
    ),
    (
        "test/language/statements/class/subclass/binding.js",
        ("sloppy", "strict"),
    ),
    (
        "test/language/statements/const/syntax/"
        "block-scope-syntax-const-declarations-without-initialiser.js",
        ("sloppy", "strict"),
    ),
    (
        "test/language/statements/const/"
        "global-use-before-initialization-in-prior-statement.js",
        ("sloppy", "strict"),
    ),
    (
        "test/built-ins/Promise/prototype/then/prfm-fulfilled.js",
        ("sloppy", "strict"),
    ),
    (
        "test/language/statements/async-function/"
        "evaluation-body-that-returns-after-await.js",
        ("sloppy", "strict"),
    ),
    (
        "test/built-ins/Proxy/ownKeys/"
        "not-extensible-missing-keys-throws.js",
        ("sloppy", "strict"),
    ),
    (
        "test/built-ins/BigInt/asIntN/arithmetic.js",
        ("sloppy", "strict"),
    ),
    (
        "test/built-ins/TypedArray/prototype/map/values-are-not-cached.js",
        ("sloppy", "strict"),
    ),
    (
        "test/built-ins/ArrayBuffer/prototype/byteLength/detached-buffer.js",
        ("sloppy", "strict"),
    ),
    (
        "test/language/module-code/instn-iee-bndng-const.js",
        ("module",),
    ),
    (
        "test/language/module-code/instn-resolve-order-depth.js",
        ("module",),
    ),
    (
        "test/language/module-code/eval-rqstd-once.js",
        ("module",),
    ),
)
V8_SNAPSHOTLESS_TEST262_CASE_LINES = tuple(
    f"CHROMIUM_WASM_M2_V8_JS:TEST262_CASE path={path} "
    f"mode={mode} status=ok"
    for path, modes in V8_SNAPSHOTLESS_TEST262_CASES
    for mode in modes
)
V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE = (
    "CHROMIUM_WASM_M2_V8_JS:TEST262_SUMMARY "
    "cases=14 executions=25 passed=25 failed=0 status=ok"
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
    "platform_region_wrap": "ok",
    "platform_region_unwrap": "ok",
    "platform_region_metadata": "ok",
    "transport_token_one_shot": "ok",
    "platform_region_aliasing": "ok",
    "platform_region_single_owner": "ok",
    "platform_region_unwrap_failure_closes": "ok",
    "platform_file_wrap": "ok",
    "platform_file_transfer": "ok",
    "platform_file_unwrap": "ok",
    "platform_file_read": "ok",
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

MOJO_FILE_RESULT_VALUES = {
    "file_serialize": "ok",
    "file_sender_invalidated": "ok",
    "file_message_transport": "ok",
    "file_deserialize": "ok",
    "file_content": "ok",
    "file_async_preserved": "ok",
    "file_receiver_ownership": "ok",
    "file_close_ebadf": "ok",
    "file_failed_unwrap_closes": "ok",
    "read_only_serialize": "ok",
    "read_only_sender_invalidated": "ok",
    "read_only_message_transport": "ok",
    "read_only_deserialize": "ok",
    "read_only_content": "ok",
    "read_only_async_preserved": "ok",
    "read_only_receiver_ownership": "ok",
    "read_only_close_ebadf": "ok",
    "clean_shutdown": "ok",
}
MOJO_FILE_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M3_MOJO_FILE:RESULT",
    *(f"{key}={value}" for key, value in MOJO_FILE_RESULT_VALUES.items()),
)

PA_PAGE_RESULT_VALUES = {
    "host": "wasm32",
    "production_pa": "off",
    "allocator_shim": "off",
    "pa_as_malloc": "off",
    "granularity_64k": "ok",
    "system_page_64k": "ok",
    "superpage_alignment": "ok",
    "superpage_nonoverlap": "ok",
    "superpage_fresh_zero": "ok",
    "offset_alignment": "ok",
    "bounded_reuse": "ok",
    "reused_zero": "ok",
    "free_accounting": "ok",
    "pthread_contention": "ok",
    "overflow_rejected": "ok",
    "linear_limit_rejected": "ok",
    "failure_isolation": "ok",
    "discard_contract": "ok",
    "decommit_recommit_zero": "ok",
    "require_update": "unsupported",
    "decommit_and_zero": "unsupported",
    "permissions": "logical_only",
    "unsupported_permissions": "reported",
    "memory_growth": "ok",
    "growth_reuse": "ok",
    "mapped_accounting": "ok",
    "threads": "4",
    "iterations_per_thread": "64",
    "contention_allocations": "256",
    "reuse_cycles": "128",
    "allocation_granularity_bytes": "65536",
    "system_page_bytes": "65536",
    "superpage_bytes": "2097152",
    "alignment_offset_bytes": "65536",
}
PA_PAGE_METRIC_NAMES = (
    "startup_heap_bytes",
    "pre_growth_heap_bytes",
    "grown_heap_bytes",
    "final_heap_bytes",
    "max_heap_bytes",
    "initial_mapped_bytes",
    "growth_request_bytes",
    "mapped_during_growth_bytes",
    "final_mapped_bytes",
)
PA_PAGE_PHASE_NAMES = (
    "constants",
    "aligned_superpages",
    "alignment_offset",
    "bounded_reuse",
    "pthread_contention",
    "allocation_failures",
    "page_lifecycle",
    "memory_growth",
)
PA_PAGE_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M3_PA_PAGE:RESULT",
    "CHROMIUM_WASM_M3_PA_PAGE:METRICS",
    *(f"{key}={value}" for key, value in PA_PAGE_RESULT_VALUES.items()),
)

PA_ROOT_RESULT_VALUES = {
    "host": "wasm32",
    "production_pa": "on",
    "allocator_shim": "off",
    "pa_as_malloc": "off",
    "explicit_roots": "ok",
    "root_isolation": "ok",
    "bucket_allocation": "ok",
    "zero_fill": "ok",
    "capacity": "ok",
    "realloc": "ok",
    "direct_map": "ok",
    "direct_map_stats": "ok",
    "alignment": "ok",
    "thread_cache": "ok",
    "pthread_contention": "ok",
    "purge": "ok",
    "stats": "ok",
    "reclaimer": "ok",
}
PA_ROOT_METRIC_NAMES = (
    "committed_before_reclaim",
    "committed_after_reclaim",
    "threads",
    "iterations_per_thread",
    "contention_allocations",
    "roots",
)
PA_ROOT_PHASE_NAMES = (
    "root_initialization",
    "root_isolation",
    "bucket_zero_capacity_realloc",
    "direct_map_realloc_stats",
    "array_buffer_alignment",
    "pthread_contention",
    "purge_stats_reclaimer",
)
PA_ROOT_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M3_PA_ROOT:RESULT",
    "CHROMIUM_WASM_M3_PA_ROOT:METRICS",
    *(f"{key}={value}" for key, value in PA_ROOT_RESULT_VALUES.items()),
)

DISK_CACHE_RESULT_VALUES = {
    "filesystem": "memfs",
    "move": "ok",
    "delete_open_reuse": "ok",
    "default_backend": "simple",
    "write_read": "ok",
    "reopen": "ok",
    "blockfile": "unsupported_async",
}
DISK_CACHE_RESULT_REQUIREMENTS = (
    "CHROMIUM_WASM_M3_DISK_CACHE:RESULT",
    *(
        f"{key}={value}"
        for key, value in DISK_CACHE_RESULT_VALUES.items()
    ),
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
            *BASE_RESULT_REQUIREMENTS,
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
    "v8_base": SmokeCase(
        module_name="wasm_v8_base_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M2_V8_BASE",
        required_stdout=(
            "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_START",
            "CHROMIUM_WASM_M2_V8_BASE:RUNTIME_END",
            *V8_BASE_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M2_V8_BASE:PASS",
        ),
        minimum_runtime_ms=200,
        gn_args_key="m2_v8_gn_args",
    ),
    "v8_snapshotless": SmokeCase(
        module_name="wasm_v8_snapshotless_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M2_V8_JS",
        required_stdout=(
            "CHROMIUM_WASM_M2_V8_JS:RUNTIME_START",
            "CHROMIUM_WASM_M2_V8_JS:RUNTIME_END",
            *V8_SNAPSHOTLESS_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M2_V8_JS:PASS",
        ),
        minimum_runtime_ms=1000,
        gn_args_key="m2_v8_gn_args",
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
    "mojo_file": SmokeCase(
        module_name="m3_mojo_file_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M3_MOJO_FILE",
        required_stdout=(
            "CHROMIUM_WASM_M3_MOJO_FILE:RUNTIME_START",
            "CHROMIUM_WASM_M3_MOJO_FILE:RUNTIME_END",
            *MOJO_FILE_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M3_MOJO_FILE:PASS",
        ),
        minimum_runtime_ms=0,
        gn_args_key="m3_content_gn_args",
    ),
    "pa_pages": SmokeCase(
        module_name="m3_partition_alloc_page_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M3_PA_PAGE",
        required_stdout=(
            "CHROMIUM_WASM_M3_PA_PAGE:RUNTIME_START",
            "CHROMIUM_WASM_M3_PA_PAGE:RUNTIME_END",
            *PA_PAGE_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M3_PA_PAGE:PASS",
        ),
        gn_args_key="m3_content_gn_args",
    ),
    "pa_roots": SmokeCase(
        module_name="m3_partition_alloc_root_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M3_PA_ROOT",
        required_stdout=(
            "CHROMIUM_WASM_M3_PA_ROOT:RUNTIME_START",
            "CHROMIUM_WASM_M3_PA_ROOT:RUNTIME_END",
            *PA_ROOT_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M3_PA_ROOT:PASS",
        ),
        gn_args_key="m3_content_gn_args",
    ),
    "disk_cache": SmokeCase(
        module_name="m3_disk_cache_smoke.js",
        sentinel_prefix="CHROMIUM_WASM_M3_DISK_CACHE",
        required_stdout=(
            "CHROMIUM_WASM_M3_DISK_CACHE:RUNTIME_START",
            "CHROMIUM_WASM_M3_DISK_CACHE:RUNTIME_END",
            *DISK_CACHE_RESULT_REQUIREMENTS,
            "CHROMIUM_WASM_M3_DISK_CACHE:PASS",
        ),
        gn_args_key="m3_content_gn_args",
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


def _validate_result_fields(
    prefix: str,
    result: dict[str, str],
    fixed_values: dict[str, str],
    numeric_names: tuple[str, ...] = (),
) -> dict[str, int]:
    expected_keys = set(fixed_values) | set(numeric_names)
    missing = sorted(expected_keys - result.keys())
    unexpected = sorted(result.keys() - expected_keys)
    mismatched = sorted(
        key
        for key in result.keys() & fixed_values.keys()
        if result[key] != fixed_values[key]
    )
    if missing or unexpected or mismatched:
        raise M0Error(
            f"{prefix} mismatch: missing={missing}, "
            f"unexpected={unexpected}, mismatched={mismatched}"
        )

    numeric_values: dict[str, int] = {}
    for name in numeric_names:
        value = result[name]
        if not value.isascii() or not value.isdecimal():
            raise M0Error(f"{prefix} {name} must be a decimal integer")
        numeric_values[name] = int(value)
    return numeric_values


def _validate_task_result(prefix: str, values: dict[str, int]) -> None:
    if not 3 <= values["wake_count"] <= 10:
        raise M0Error(f"{prefix} wake_count is out of range")
    if not 1 <= values["wait_count"] <= 8:
        raise M0Error(f"{prefix} wait_count is out of range")
    if values["idle_wake_returns"] != values["wait_count"]:
        raise M0Error(f"{prefix} idle wait/wake counts do not match")
    for name in (
        "worker_to_app_latency_ms",
        "sleeping_quit_latency_ms",
        "idle_wake_latency_ms",
    ):
        if values[name] >= 1000:
            raise M0Error(f"{prefix} {name} is out of range")
    if not 200 <= values["idle_elapsed_ms"] < 2000:
        raise M0Error(f"{prefix} idle_elapsed_ms is out of range")


def _validate_v8_snapshotless_result(
    prefix: str, values: dict[str, int]
) -> None:
    expected_cycles = int(
        V8_SNAPSHOTLESS_RESULT_VALUES["lifecycle_cycles"]
    )
    if values["feature_cycles"] != expected_cycles:
        raise M0Error(f"{prefix} feature cycle count is inconsistent")
    if values["native_callback_calls"] != 2 * values["feature_cycles"]:
        raise M0Error(f"{prefix} native callback count is inconsistent")
    if values["gc_cycles"] != 3:
        raise M0Error(f"{prefix} GC cycle count is inconsistent")
    if values["module_cycles"] != values["feature_cycles"]:
        raise M0Error(f"{prefix} module cycle count is inconsistent")
    if values["module_resolve_calls"] != values["module_cycles"]:
        raise M0Error(f"{prefix} module resolver count is inconsistent")
    if values["timer_cycles"] != 1:
        raise M0Error(f"{prefix} timer cycle count is inconsistent")
    if values["timer_delay_ms"] != 25:
        raise M0Error(f"{prefix} timer delay is inconsistent")
    if values["timer_elapsed_us"] < values["timer_delay_ms"] * 1000:
        raise M0Error(f"{prefix} delayed timer fired early")
    expected_test262_values = {
        "test262_license_bytes": 2213,
        "test262_license_fnv1a": 1790394517849644,
        "test262_embedded_source_bytes": 40217,
        "test262_cases": 14,
        "test262_executions": 25,
        "test262_passed": 25,
        "test262_failed": 0,
        "test262_scripts": 22,
        "test262_modules": 3,
        "test262_strict": 14,
        "test262_sloppy": 11,
        "test262_async": 4,
        "test262_negative_parse": 2,
        "test262_negative_runtime": 2,
        "test262_negative_resolution": 1,
        "test262_detach_calls": 2,
        "test262_resolver_calls": 5,
        "test262_module_compile_attempts": 7,
    }
    for name, expected in expected_test262_values.items():
        if values[name] != expected:
            raise M0Error(f"{prefix} {name} is inconsistent")
    if (
        values["test262_scripts"] + values["test262_modules"]
        != values["test262_executions"]
    ):
        raise M0Error(f"{prefix} Test262 execution kinds are inconsistent")
    if (
        values["test262_strict"] + values["test262_sloppy"]
        != values["test262_executions"]
    ):
        raise M0Error(f"{prefix} Test262 strictness counts are inconsistent")
    if values["test262_resolver_calls"] < values["test262_modules"]:
        raise M0Error(f"{prefix} Test262 resolver coverage is inconsistent")
    if values["test262_runtime_ms"] <= 0:
        raise M0Error(f"{prefix} Test262 runtime must be positive")
    if not (
        values["test262_runtime_ms"]
        <= values["isolate_runs_ms"]
        <= values["runtime_ms"]
    ):
        raise M0Error(f"{prefix} Test262 runtime timing is inconsistent")
    for name in (
        "snapshot_bytes",
        "snapshot_create_ms",
        "isolate_runs_ms",
        "runtime_ms",
        "v8_heap_total_max_sampled_bytes",
        "v8_heap_used_max_sampled_bytes",
        "v8_heap_physical_max_sampled_bytes",
        "v8_heap_limit_bytes",
        "v8_total_allocated_max_per_isolate_bytes",
        "wasm_linear_initial_bytes",
        "wasm_linear_after_cycle_1_bytes",
        "wasm_linear_after_cycle_2_bytes",
        "wasm_linear_after_cycle_3_bytes",
        "wasm_linear_peak_bytes",
        "wasm_linear_limit_bytes",
    ):
        if values[name] <= 0:
            raise M0Error(f"{prefix} {name} must be positive")
    if (
        values["snapshot_create_ms"] + values["isolate_runs_ms"]
        > values["runtime_ms"]
    ):
        raise M0Error(f"{prefix} runtime timings are inconsistent")
    if (
        values["v8_heap_used_max_sampled_bytes"]
        > values["v8_heap_total_max_sampled_bytes"]
    ):
        raise M0Error(f"{prefix} V8 used heap exceeds total heap")
    if (
        values["v8_heap_physical_max_sampled_bytes"]
        > values["v8_heap_total_max_sampled_bytes"]
    ):
        raise M0Error(f"{prefix} V8 physical heap exceeds total heap")
    if (
        values["v8_heap_total_max_sampled_bytes"]
        > values["v8_heap_limit_bytes"]
    ):
        raise M0Error(f"{prefix} V8 total heap exceeds its limit")
    if (
        values["v8_malloced_max_sampled_bytes"]
        > values["v8_peak_malloced_bytes"]
    ):
        raise M0Error(f"{prefix} V8 malloc accounting is inconsistent")
    if values["array_buffer_peak_bytes"] < 32 * 65536:
        raise M0Error(f"{prefix} ArrayBuffer stress allocation is missing")
    if (
        values["v8_external_max_sampled_bytes"]
        < values["array_buffer_peak_bytes"]
    ):
        raise M0Error(
            f"{prefix} V8 external-memory accounting is inconsistent"
        )
    linear_samples = (
        values["wasm_linear_initial_bytes"],
        values["wasm_linear_after_cycle_1_bytes"],
        values["wasm_linear_after_cycle_2_bytes"],
        values["wasm_linear_after_cycle_3_bytes"],
        values["wasm_linear_peak_bytes"],
        values["wasm_linear_limit_bytes"],
    )
    if tuple(sorted(linear_samples)) != linear_samples:
        raise M0Error(f"{prefix} Wasm linear-memory bounds are inconsistent")
    if (
        values["wasm_linear_after_cycle_2_bytes"]
        != values["wasm_linear_after_cycle_3_bytes"]
    ):
        raise M0Error(
            f"{prefix} Wasm linear memory did not stabilize after warmup"
        )


def _validate_v8_snapshotless_stages(
    prefix: str,
    lines: list[str],
    runtime_start_index: int,
    runtime_end_index: int,
) -> None:
    stage_prefix = f"{prefix}:STAGE"
    expected = [
        f"{stage_prefix} name={name}"
        for name in V8_SNAPSHOTLESS_STAGE_NAMES
    ]
    indexed_stages = [
        (index, line)
        for index, line in enumerate(lines)
        if line.startswith(stage_prefix)
    ]
    actual = [line for _, line in indexed_stages]
    if actual != expected:
        raise M0Error(f"{prefix} stage sequence is inconsistent")
    if any(
        not runtime_start_index < index < runtime_end_index
        for index, _ in indexed_stages
    ):
        raise M0Error(f"{prefix} stages escaped the runtime interval")


def _validate_v8_snapshotless_test262_cases(
    prefix: str,
    lines: list[str],
    runtime_start_index: int,
    runtime_end_index: int,
) -> None:
    case_prefix = f"{prefix}:TEST262_CASE"
    indexed_cases = [
        (index, line)
        for index, line in enumerate(lines)
        if line.startswith(case_prefix)
    ]
    actual = [line for _, line in indexed_cases]
    if actual != list(V8_SNAPSHOTLESS_TEST262_CASE_LINES):
        raise M0Error(f"{prefix} Test262 case sequence is inconsistent")
    if any(
        not runtime_start_index < index < runtime_end_index
        for index, _ in indexed_cases
    ):
        raise M0Error(f"{prefix} Test262 cases escaped the runtime interval")
    summary_indices = [
        index
        for index, line in enumerate(lines)
        if line.startswith(f"{prefix}:TEST262_SUMMARY")
    ]
    if len(summary_indices) != 1:
        raise M0Error(f"{prefix} Test262 summary count is inconsistent")
    summary_index = summary_indices[0]
    if lines[summary_index] != V8_SNAPSHOTLESS_TEST262_SUMMARY_LINE:
        raise M0Error(f"{prefix} Test262 summary is inconsistent")
    if not (
        runtime_start_index < summary_index < runtime_end_index
        and indexed_cases[-1][0] < summary_index
    ):
        raise M0Error(f"{prefix} Test262 summary ordering is inconsistent")


def validate_case_stdout(name: str, stdout: str) -> None:
    numeric_names: tuple[str, ...] = ()
    metric_names: tuple[str, ...] | None = None
    if name == "base":
        display_name = "Base"
        sentinel_prefix = "CHROMIUM_WASM_M1_BASE"
        result_values = BASE_RESULT_VALUES
    elif name == "tasks":
        display_name = "task"
        sentinel_prefix = "CHROMIUM_WASM_M1_TASK"
        result_values = TASK_RESULT_VALUES
        numeric_names = TASK_RESULT_NUMERIC_NAMES
    elif name == "rust":
        display_name = "Rust"
        sentinel_prefix = "CHROMIUM_WASM_M1_RUST"
        result_values = RUST_RESULT_VALUES
    elif name == "v8_base":
        display_name = "V8 Base"
        sentinel_prefix = "CHROMIUM_WASM_M2_V8_BASE"
        result_values = V8_BASE_RESULT_VALUES
    elif name == "v8_snapshotless":
        display_name = "V8 snapshotless"
        sentinel_prefix = "CHROMIUM_WASM_M2_V8_JS"
        result_values = V8_SNAPSHOTLESS_RESULT_VALUES
        numeric_names = V8_SNAPSHOTLESS_RESULT_NUMERIC_NAMES
    elif name == "shared_memory":
        display_name = "shared-memory"
        sentinel_prefix = "CHROMIUM_WASM_M1_SHARED_MEMORY"
        result_values = SHARED_MEMORY_RESULT_VALUES
        metric_names = SHARED_MEMORY_METRIC_NAMES
    elif name == "mojo":
        display_name = "Mojo"
        sentinel_prefix = "CHROMIUM_WASM_M1_MOJO"
        result_values = MOJO_RESULT_VALUES
        metric_names = MOJO_METRIC_NAMES
    elif name == "mojo_file":
        display_name = "Mojo file"
        sentinel_prefix = "CHROMIUM_WASM_M3_MOJO_FILE"
        result_values = MOJO_FILE_RESULT_VALUES
    elif name == "pa_pages":
        display_name = "PartitionAlloc page"
        sentinel_prefix = "CHROMIUM_WASM_M3_PA_PAGE"
        result_values = PA_PAGE_RESULT_VALUES
        metric_names = PA_PAGE_METRIC_NAMES
    elif name == "pa_roots":
        display_name = "PartitionAlloc root"
        sentinel_prefix = "CHROMIUM_WASM_M3_PA_ROOT"
        result_values = PA_ROOT_RESULT_VALUES
        metric_names = PA_ROOT_METRIC_NAMES
    elif name == "disk_cache":
        display_name = "disk-cache"
        sentinel_prefix = "CHROMIUM_WASM_M3_DISK_CACHE"
        result_values = DISK_CACHE_RESULT_VALUES
    else:
        return

    lines = stdout.splitlines()
    runtime_start = f"{sentinel_prefix}:RUNTIME_START"
    runtime_end = f"{sentinel_prefix}:RUNTIME_END"
    pass_sentinel = f"{sentinel_prefix}:PASS"
    result_prefix = f"{sentinel_prefix}:RESULT"
    result = _parse_contract_line(stdout, result_prefix)
    numeric_values = _validate_result_fields(
        result_prefix, result, result_values, numeric_names
    )
    if name == "tasks":
        _validate_task_result(result_prefix, numeric_values)
    elif name == "v8_snapshotless":
        _validate_v8_snapshotless_result(result_prefix, numeric_values)

    for marker in (runtime_start, runtime_end, pass_sentinel):
        if lines.count(marker) != 1:
            raise M0Error(f"expected exactly one {marker} line")
    try:
        runtime_start_index = lines.index(runtime_start)
        runtime_end_index = lines.index(runtime_end)
        result_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith(f"{result_prefix} ")
        )
        pass_index = lines.index(pass_sentinel)
    except (StopIteration, ValueError) as exc:
        raise M0Error(f"{display_name} runtime markers are incomplete") from exc

    if name == "v8_snapshotless":
        _validate_v8_snapshotless_stages(
            sentinel_prefix,
            lines,
            runtime_start_index,
            runtime_end_index,
        )
        _validate_v8_snapshotless_test262_cases(
            sentinel_prefix,
            lines,
            runtime_start_index,
            runtime_end_index,
        )
    elif name in ("pa_pages", "pa_roots"):
        phase_prefix = f"{sentinel_prefix}:PHASE"
        phase_names = (
            PA_PAGE_PHASE_NAMES
            if name == "pa_pages"
            else PA_ROOT_PHASE_NAMES
        )
        expected_phases = [
            f"{phase_prefix} name={phase_name} status=ok"
            for phase_name in phase_names
        ]
        indexed_phases = [
            (index, line)
            for index, line in enumerate(lines)
            if line.startswith(phase_prefix)
        ]
        if [line for _, line in indexed_phases] != expected_phases:
            raise M0Error(
                f"{sentinel_prefix} phase sequence is inconsistent"
            )
        if any(
            not runtime_start_index < index < runtime_end_index
            for index, _ in indexed_phases
        ):
            raise M0Error(
                f"{sentinel_prefix} phases escaped the runtime interval"
            )

    if metric_names is None:
        if not (
            runtime_start_index < runtime_end_index < result_index < pass_index
        ):
            raise M0Error(f"{display_name} runtime markers are out of order")
        return

    metrics_prefix = f"{sentinel_prefix}:METRICS"
    metrics = _parse_contract_line(stdout, metrics_prefix)
    try:
        metrics_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith(f"{metrics_prefix} ")
        )
    except StopIteration as exc:
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

    if name == "pa_pages":
        metric_values = {key: int(value) for key, value in metrics.items()}
        page_bytes = 65536
        heap_names = (
            "startup_heap_bytes",
            "pre_growth_heap_bytes",
            "grown_heap_bytes",
            "final_heap_bytes",
            "max_heap_bytes",
        )
        if any(metric_values[key] % page_bytes for key in heap_names):
            raise M0Error(f"{metrics_prefix} heap values are not page-aligned")
        startup = metric_values["startup_heap_bytes"]
        pre_growth = metric_values["pre_growth_heap_bytes"]
        grown = metric_values["grown_heap_bytes"]
        final = metric_values["final_heap_bytes"]
        maximum = metric_values["max_heap_bytes"]
        if not (0 < startup <= pre_growth < grown == final < maximum):
            raise M0Error(f"{metrics_prefix} heap growth is inconsistent")
        if maximum != 2147483648:
            raise M0Error(f"{metrics_prefix} maximum memory changed")
        growth_request = metric_values["growth_request_bytes"]
        if (
            growth_request <= pre_growth
            or growth_request % page_bytes
            or metric_values["initial_mapped_bytes"] != 0
            or metric_values["mapped_during_growth_bytes"] != growth_request
            or metric_values["final_mapped_bytes"] != 0
        ):
            raise M0Error(
                f"{metrics_prefix} mapped/growth accounting is inconsistent"
            )
    elif name == "pa_roots":
        metric_values = {key: int(value) for key, value in metrics.items()}
        committed_before = metric_values["committed_before_reclaim"]
        committed_after = metric_values["committed_after_reclaim"]
        if (
            committed_before <= 0
            or committed_before % 65536
            or committed_after % 65536
            or not 0 <= committed_after < committed_before
        ):
            raise M0Error(
                f"{metrics_prefix} reclaim accounting is inconsistent"
            )
        expected_counts = {
            "threads": 4,
            "iterations_per_thread": 128,
            "contention_allocations": 512,
            "roots": 3,
        }
        if any(
            metric_values[key] != value
            for key, value in expected_counts.items()
        ):
            raise M0Error(
                f"{metrics_prefix} execution counts are inconsistent"
            )
    else:
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
        selected_case = smoke_case(args.case)
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
            gn_args=manifest[selected_case.gn_args_key],
            port=server.server_address[1],
        )
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

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run the fixed in-process DevTools protocol smoke in a real browser host.

The real browser supplies the cross-origin-isolated worker environment needed
by the threaded Wasm Chrome host. This runner serves immutable snapshots of
one built loader and Wasm module, then requires the native fixed
Network.enable, Runtime.enable, DOM.getDocument, Runtime.evaluate, Console API
event, detach, and lifecycle-close markers. It is neither a DevTools frontend
nor a remote debugging/protocol transport, and it does not claim M8 completion.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

from check_m6_chrome_boundary import check_boundary
from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    gn_args_text,
    load_manifest,
    parse_timeout,
    print_context,
)
from m9_descriptor_snapshot import snapshot_regular_files
from run_browser_smoke import browser_command, drain_stream, find_browser, stop_browser
from run_content_shell_smoke import manifest_versions
import run_wasm_browser_view_smoke as browser_view_smoke


SENTINEL = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL_DOM"
CASE = "browser_devtools_protocol_m8"
SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-dom-get-document-runtime-evaluate-console-event-detach-close"
)
SWITCH = "--wasm-browser-devtools-protocol-smoke"
PAGE_WEBASSEMBLY_SENTINEL = "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_DOM"
PAGE_WEBASSEMBLY_MODE = "page-webassembly"
PAGE_WEBASSEMBLY_CASE = "browser_page_webassembly_m8"
PAGE_WEBASSEMBLY_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-validate-module-instance-"
    "add42-console-event-detach-close"
)
PAGE_WEBASSEMBLY_SWITCH = "--wasm-browser-m8-page-webassembly-smoke"
PAGE_WEBASSEMBLY_MEMORY_SENTINEL = "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_MEMORY_DOM"
PAGE_WEBASSEMBLY_MEMORY_MODE = "page-webassembly-memory"
PAGE_WEBASSEMBLY_MEMORY_CASE = "browser_page_webassembly_memory_m8"
PAGE_WEBASSEMBLY_MEMORY_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-memory-construct-import-"
    "js-write-wasm-read-wasm-write-js-read-console-event-detach-close"
)
PAGE_WEBASSEMBLY_MEMORY_SWITCH = (
    "--wasm-browser-m8-page-webassembly-memory-smoke"
)
PAGE_WEBASSEMBLY_TABLE_SENTINEL = "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_TABLE_DOM"
PAGE_WEBASSEMBLY_TABLE_MODE = "page-webassembly-table"
PAGE_WEBASSEMBLY_TABLE_CASE = "browser_page_webassembly_table_m8"
PAGE_WEBASSEMBLY_TABLE_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-table-construct-import-"
    "element-initialize-indirect-call-console-event-detach-close"
)
PAGE_WEBASSEMBLY_TABLE_SWITCH = "--wasm-browser-m8-page-webassembly-table-smoke"
PAGE_WEBASSEMBLY_TABLE_GROWTH_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_TABLE_GROWTH_DOM"
)
PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE = "page-webassembly-table-growth"
PAGE_WEBASSEMBLY_TABLE_GROWTH_CASE = "browser_page_webassembly_table_growth_m8"
PAGE_WEBASSEMBLY_TABLE_GROWTH_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-table-construct-import-"
    "grow-one-to-two-entries-initialize-grown-entry-indirect-call-console-event-"
    "detach-close"
)
PAGE_WEBASSEMBLY_TABLE_GROWTH_SWITCH = (
    "--wasm-browser-m8-page-webassembly-table-growth-smoke"
)
PAGE_WEBASSEMBLY_MEMORY_GROWTH_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_MEMORY_GROWTH_DOM"
)
PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE = "page-webassembly-memory-growth"
PAGE_WEBASSEMBLY_MEMORY_GROWTH_CASE = "browser_page_webassembly_memory_growth_m8"
PAGE_WEBASSEMBLY_MEMORY_GROWTH_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-memory-construct-import-"
    "grow-one-to-two-pages-post-growth-js-write-wasm-read-wasm-write-js-read-"
    "console-event-detach-close"
)
PAGE_WEBASSEMBLY_MEMORY_GROWTH_SWITCH = (
    "--wasm-browser-m8-page-webassembly-memory-growth-smoke"
)
PAGE_WEBASSEMBLY_EXCEPTIONS_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_EXCEPTIONS_DOM"
)
PAGE_WEBASSEMBLY_EXCEPTIONS_MODE = "page-webassembly-exceptions"
PAGE_WEBASSEMBLY_EXCEPTIONS_CASE = "browser_page_webassembly_exceptions_m8"
PAGE_WEBASSEMBLY_EXCEPTIONS_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-exception-construct-import-"
    "tag-js-throw-wasm-catch-console-event-detach-close"
)
PAGE_WEBASSEMBLY_EXCEPTIONS_SWITCH = (
    "--wasm-browser-m8-page-webassembly-exceptions-smoke"
)
PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_DOM"
)
PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE = (
    "page-webassembly-wasm-memory-grow-opcode"
)
PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_CASE = (
    "browser_page_webassembly_wasm_memory_grow_opcode_m8"
)
PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-memory-construct-import-"
    "wasm-memory-grow-opcode-one-to-two-pages-buffer-replaced-console-event-"
    "detach-close"
)
PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SWITCH = (
    "--wasm-browser-m8-page-webassembly-wasm-memory-grow-opcode-smoke"
)
PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_DOM"
)
PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE = (
    "page-webassembly-wasm-table-grow-opcode"
)
PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_CASE = (
    "browser_page_webassembly_wasm_table_grow_opcode_m8"
)
PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-table-construct-import-"
    "wasm-table-grow-opcode-one-to-two-entries-initialize-grown-entry-"
    "indirect-call-console-event-detach-close"
)
PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SWITCH = (
    "--wasm-browser-m8-page-webassembly-wasm-table-grow-opcode-smoke"
)
PAGE_WEBASSEMBLY_WASM_THROW_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_WASM_THROW_DOM"
)
PAGE_WEBASSEMBLY_WASM_THROW_MODE = "page-webassembly-wasm-throw"
PAGE_WEBASSEMBLY_WASM_THROW_CASE = "browser_page_webassembly_wasm_throw_m8"
PAGE_WEBASSEMBLY_WASM_THROW_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-exception-import-tag-"
    "wasm-throw-js-catch-console-event-detach-close"
)
PAGE_WEBASSEMBLY_WASM_THROW_SWITCH = (
    "--wasm-browser-m8-page-webassembly-wasm-throw-smoke"
)
PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_DOM"
)
PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE = "page-webassembly-wasm-throw-payload"
PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_CASE = (
    "browser_page_webassembly_wasm_throw_payload_m8"
)
PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-exception-import-i32-tag-"
    "wasm-throw-js-catch-payload-42-console-event-detach-close"
)
PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SWITCH = (
    "--wasm-browser-m8-page-webassembly-wasm-throw-payload-smoke"
)
PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_DOM"
)
PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE = "page-webassembly-js-throw-payload"
PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_CASE = (
    "browser_page_webassembly_js_throw_payload_m8"
)
PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-exception-import-i32-tag-"
    "js-throw-wasm-catch-payload-42-console-event-detach-close"
)
PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SWITCH = (
    "--wasm-browser-m8-page-webassembly-js-throw-payload-smoke"
)
PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SENTINEL = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_DOM"
)
PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE = "page-webassembly-instantiate-streaming"
PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_CASE = (
    "browser_page_webassembly_instantiate_streaming_m8"
)
PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SCOPE = (
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-"
    "runtime-enable-runtime-evaluate-page-webassembly-instantiate-streaming-"
    "fetch-data-application-wasm-module-instance-add42-console-event-detach-"
    "close"
)
PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SWITCH = (
    "--wasm-browser-m8-page-webassembly-instantiate-streaming-smoke"
)
NETWORK_ENABLE_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:NETWORK_ENABLE_OK"
RUNTIME_ENABLE_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_ENABLE_OK"
DOM_GET_DOCUMENT_MARKER = (
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DOM_GET_DOCUMENT_OK"
)
RUNTIME_EVALUATE_MARKER = (
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_EVALUATE_OK"
)
PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER = (
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:PAGE_WEBASSEMBLY_UNAVAILABLE"
)
PAGE_WEBASSEMBLY_ADD42_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "VALIDATED_MODULE_CONSTRUCTED_INSTANCE_ADD_42_OK"
)
PAGE_WEBASSEMBLY_MEMORY_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "MEMORY_CONSTRUCTED_IMPORTED_JS_WRITE_WASM_READ_WASM_WRITE_JS_READ_OK"
)
PAGE_WEBASSEMBLY_TABLE_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "TABLE_CONSTRUCTED_IMPORTED_ELEMENT_INITIALIZED_INDIRECT_CALL_42_OK"
)
PAGE_WEBASSEMBLY_TABLE_GROWTH_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "TABLE_CONSTRUCTED_IMPORTED_GROWN_1_TO_2_ENTRIES_INITIALIZED_"
    "INDIRECT_CALL_42_OK"
)
PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "MEMORY_CONSTRUCTED_IMPORTED_GROWN_1_TO_2_PAGES_POST_GROWTH_JS_WRITE_"
    "WASM_READ_WASM_WRITE_JS_READ_OK"
)
PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_CONSTRUCTED_IMPORTED_TAG_JS_THROW_WASM_CATCH_42_OK"
)
PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "MEMORY_CONSTRUCTED_IMPORTED_WASM_MEMORY_GROW_OPCODE_GROWN_1_TO_2_PAGES_"
    "BUFFER_REPLACED_OK"
)
PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "TABLE_CONSTRUCTED_IMPORTED_WASM_TABLE_GROW_OPCODE_GROWN_1_TO_2_ENTRIES_"
    "INITIALIZED_INDIRECT_CALL_42_OK"
)
PAGE_WEBASSEMBLY_WASM_THROW_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_IMPORTED_TAG_WASM_THROW_JS_CATCH_OK"
)
PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_IMPORTED_I32_TAG_WASM_THROW_JS_CATCH_PAYLOAD_42_OK"
)
PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_IMPORTED_I32_TAG_JS_THROW_WASM_CATCH_PAYLOAD_42_OK"
)
PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER = (
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "INSTANTIATE_STREAMING_DATA_URL_APPLICATION_WASM_MODULE_INSTANCE_ADD_42_OK"
)
RUNTIME_CONSOLE_API_CALLED_MARKER = (
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_CONSOLE_API_CALLED_OK"
)
DETACHED_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DETACHED"
FAILURE_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:FAIL"
LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS"
HOST_ROOT = "/__m8_browser_devtools_protocol__"
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
MAX_RESULT_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_GN_ARGS_BYTES = 1024 * 1024
ARTIFACT_DELIVERY = "immutable-in-memory-server-snapshot"
LIMITATIONS = (
    "does_not_enable_or_exercise_page_webassembly",
    "only_observes_the_disabled_page_webassembly_global_not_api_semantics",
    "only_observes_one_fixed_dom_document_root_not_elements_frontend_interaction",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_LIMITATIONS = (
    "only_validates_one_fixed_page_webassembly_module_instance_add42_path",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_MEMORY_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_memory_construct_import_read_write_path",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_TABLE_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_table_construct_import_element_initialize_indirect_call_path",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_table_mutation",
    "does_not_exercise_page_webassembly_table_growth",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_MEMORY_GROWTH_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_memory_import_js_grow_one_to_two_pages_post_growth_read_write_path",
    "does_not_exercise_the_wasm_memory_grow_opcode",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_table_growth",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_TABLE_GROWTH_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_table_construct_import_js_grow_one_to_two_entries_initialized_indirect_call_path",
    "does_not_exercise_the_wasm_table_grow_opcode",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_broader_page_webassembly_reference_types",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_EXCEPTIONS_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_exception_construct_imported_tag_js_throw_wasm_catch_path",
    "does_not_exercise_wasm_throw",
    "does_not_exercise_wasm_exception_payloads",
    "does_not_exercise_wasm_rethrow_or_catch_all",
    "does_not_exercise_wasm_to_javascript_exception_escape",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_imported_wasm_memory_grow_opcode_one_to_two_pages_path",
    "does_not_exercise_javascript_memory_grow",
    "does_not_exercise_failed_or_zero_page_memory_growth",
    "does_not_exercise_shared_or_multiple_memories",
    "does_not_exercise_memory64_or_post_growth_data_exchange",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_imported_wasm_table_grow_opcode_one_to_two_entries_indirect_call_path",
    "does_not_exercise_javascript_table_grow",
    "does_not_exercise_failed_growth_or_null_initialization",
    "does_not_exercise_table_copy_fill_or_init",
    "does_not_exercise_multiple_tables_or_broader_reference_types",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_WASM_THROW_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_imported_zero_payload_tag_wasm_throw_javascript_catch_path",
    "does_not_exercise_exception_payloads",
    "does_not_exercise_wasm_internal_catch_rethrow_or_catch_all",
    "does_not_exercise_throw_ref_or_exception_stack_semantics",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_imported_i32_tag_wasm_throw_javascript_catch_payload_42_path",
    "does_not_exercise_other_payload_types_or_coercions",
    "does_not_exercise_wasm_internal_catch_rethrow_or_catch_all",
    "does_not_exercise_throw_ref_or_exception_stack_semantics",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_imported_i32_tag_javascript_throw_wasm_catch_payload_42_path",
    "does_not_exercise_other_payload_types_or_coercions",
    "does_not_exercise_wasm_throw_rethrow_or_catch_all",
    "does_not_exercise_throw_ref_or_exception_stack_semantics",
    "does_not_exercise_page_webassembly_add42",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)
PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_LIMITATIONS = (
    "only_exercises_one_fixed_page_webassembly_instantiate_streaming_data_application_wasm_module_instance_add42_path",
    "does_not_exercise_http_wisp_or_chunked_streaming",
    "does_not_exercise_arbitrary_fetch_sources_cors_cache_or_service_workers",
    "does_not_exercise_imports_cancellation_or_streaming_errors",
    "does_not_exercise_page_webassembly_tables",
    "does_not_exercise_page_webassembly_memories",
    "does_not_exercise_page_webassembly_exceptions",
    "does_not_exercise_page_webassembly_memory_growth",
    "does_not_exercise_page_webassembly_threads",
    "does_not_provide_a_devtools_frontend_or_generic_protocol_bridge",
    "does_not_claim_m8_compatibility_completion",
)


@dataclass(frozen=True)
class DevToolsProtocolSmokeConfig:
    """One closed native DevTools smoke configuration.

    The runner never relays a caller-provided DevTools command, URL, or page
    expression.  The optional page-WebAssembly configuration is another fixed
    native smoke rather than a general WebAssembly test surface.
    """

    mode_id: str
    query_mode: str | None
    sentinel: str
    case: str
    scope: str
    runtime_arguments: tuple[str, ...]
    native_markers: tuple[str, ...]
    page_webassembly_expectations: tuple[tuple[str, object], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ChromeBuildProfile:
    """One exact Chrome build configuration accepted by this runner."""

    name: str
    manifest_key: str
    default_out_dir: Path
    experimental: bool
    allows_page_webassembly_attempt: bool


M6_CHROME_BUILD_PROFILE = "m6"
M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE = "m8-codegen-experiment"
CHROME_BUILD_PROFILES = {
    M6_CHROME_BUILD_PROFILE: ChromeBuildProfile(
        name=M6_CHROME_BUILD_PROFILE,
        manifest_key="m6_chrome_gn_args",
        default_out_dir=Path("out/wasm-chrome-m6"),
        experimental=False,
        allows_page_webassembly_attempt=False,
    ),
    M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE: ChromeBuildProfile(
        name=M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE,
        manifest_key="m8_chrome_codegen_experiment_gn_args",
        default_out_dir=Path("out/wasm-chrome-m8-codegen-experiment"),
        experimental=True,
        allows_page_webassembly_attempt=True,
    ),
}


def chrome_build_profile(name: str) -> ChromeBuildProfile:
    try:
        return CHROME_BUILD_PROFILES[name]
    except KeyError as exc:
        raise M0Error(f"unknown Chrome build profile: {name}") from exc


def resolve_build_out_dir(
    profile: ChromeBuildProfile, requested_out_dir: Path | None
) -> Path:
    out_dir = requested_out_dir or profile.default_out_dir
    return out_dir if out_dir.is_absolute() else REPO_ROOT / out_dir


def require_build_profile_for_smoke(
    profile: ChromeBuildProfile,
    smoke_config: DevToolsProtocolSmokeConfig,
) -> None:
    if (
        smoke_config.query_mode is not None
        and not profile.allows_page_webassembly_attempt
    ):
        raise M0Error(
            "page-WebAssembly modes require --build-profile "
            f"{M8_CHROME_CODEGEN_EXPERIMENT_BUILD_PROFILE}; that profile is "
            "experimental and does not complete M8"
        )


def verify_build_profile(
    out_dir: Path,
    manifest: dict[str, Any],
    profile: ChromeBuildProfile,
) -> dict[str, object]:
    """Bind the served Chrome artifacts to one exact manifest GN profile."""

    try:
        expected_args = gn_args_text(manifest, profile.manifest_key).encode(
            "utf-8"
        )
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise M0Error(
            f"{profile.name} manifest GN arguments are invalid"
        ) from exc
    if not expected_args or len(expected_args) > MAX_GN_ARGS_BYTES:
        raise M0Error(f"{profile.name} manifest GN arguments are invalid")

    actual_args = snapshot_regular_files(
        out_dir,
        ("args.gn",),
        maximum_bytes=MAX_GN_ARGS_BYTES,
        description="DevTools protocol selected build GN args",
    )["args.gn"]
    if actual_args != expected_args:
        raise M0Error(
            "selected build args do not exactly match the "
            f"{profile.manifest_key} manifest profile"
        )
    return {
        "name": profile.name,
        "manifest_key": profile.manifest_key,
        "experimental": profile.experimental,
        "allows_page_webassembly_attempt": (
            profile.allows_page_webassembly_attempt
        ),
        "m8_gate_complete": False,
        "args_gn": _byte_identity(actual_args),
    }


DEFAULT_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id="default",
    query_mode=None,
    sentinel=SENTINEL,
    case=CASE,
    scope=SCOPE,
    runtime_arguments=(SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        DOM_GET_DOCUMENT_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", True),
    ),
    limitations=LIMITATIONS,
)

PAGE_WEBASSEMBLY_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_MODE,
    query_mode=PAGE_WEBASSEMBLY_MODE,
    sentinel=PAGE_WEBASSEMBLY_SENTINEL,
    case=PAGE_WEBASSEMBLY_CASE,
    scope=PAGE_WEBASSEMBLY_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_ADD42_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", True),
        ("pageWebAssemblyTablesObserved", False),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyExceptionsObserved", False),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_LIMITATIONS,
)

PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_MEMORY_MODE,
    query_mode=PAGE_WEBASSEMBLY_MEMORY_MODE,
    sentinel=PAGE_WEBASSEMBLY_MEMORY_SENTINEL,
    case=PAGE_WEBASSEMBLY_MEMORY_CASE,
    scope=PAGE_WEBASSEMBLY_MEMORY_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_MEMORY_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_MEMORY_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", False),
        ("pageWebAssemblyMemoriesObserved", True),
        (
            "pageWebAssemblyMemoryConstructedImportedReadWriteObserved",
            True,
        ),
        ("pageWebAssemblyExceptionsObserved", False),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_MEMORY_LIMITATIONS,
)

PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_TABLE_MODE,
    query_mode=PAGE_WEBASSEMBLY_TABLE_MODE,
    sentinel=PAGE_WEBASSEMBLY_TABLE_SENTINEL,
    case=PAGE_WEBASSEMBLY_TABLE_CASE,
    scope=PAGE_WEBASSEMBLY_TABLE_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_TABLE_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_TABLE_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", True),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            True,
        ),
        ("pageWebAssemblyTableGrowthObserved", False),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyExceptionsObserved", False),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_TABLE_LIMITATIONS,
)

PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE,
    query_mode=PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE,
    sentinel=PAGE_WEBASSEMBLY_TABLE_GROWTH_SENTINEL,
    case=PAGE_WEBASSEMBLY_TABLE_GROWTH_CASE,
    scope=PAGE_WEBASSEMBLY_TABLE_GROWTH_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_TABLE_GROWTH_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_TABLE_GROWTH_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", True),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            True,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            True,
        ),
        ("pageWebAssemblyTableGrowthObserved", True),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyExceptionsObserved", False),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_TABLE_GROWTH_LIMITATIONS,
)

PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE,
    query_mode=PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE,
    sentinel=PAGE_WEBASSEMBLY_MEMORY_GROWTH_SENTINEL,
    case=PAGE_WEBASSEMBLY_MEMORY_GROWTH_CASE,
    scope=PAGE_WEBASSEMBLY_MEMORY_GROWTH_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_MEMORY_GROWTH_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", False),
        ("pageWebAssemblyTableGrowthObserved", False),
        ("pageWebAssemblyMemoriesObserved", True),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", True),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            True,
        ),
        ("pageWebAssemblyExceptionsObserved", False),
        ("pageWebAssemblyMemoryGrowthObserved", True),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_MEMORY_GROWTH_LIMITATIONS,
)

PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_EXCEPTIONS_MODE,
    query_mode=PAGE_WEBASSEMBLY_EXCEPTIONS_MODE,
    sentinel=PAGE_WEBASSEMBLY_EXCEPTIONS_SENTINEL,
    case=PAGE_WEBASSEMBLY_EXCEPTIONS_CASE,
    scope=PAGE_WEBASSEMBLY_EXCEPTIONS_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_EXCEPTIONS_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            False,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            False,
        ),
        ("pageWebAssemblyTableGrowthObserved", False),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            False,
        ),
        ("pageWebAssemblyExceptionsObserved", True),
        (
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
            True,
        ),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_EXCEPTIONS_LIMITATIONS,
)

PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE,
    query_mode=PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE,
    sentinel=PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SENTINEL,
    case=PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_CASE,
    scope=PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            False,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            False,
        ),
        ("pageWebAssemblyTableGrowthObserved", False),
        ("pageWebAssemblyMemoriesObserved", True),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            False,
        ),
        ("pageWebAssemblyExceptionsObserved", False),
        (
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
            False,
        ),
        ("pageWebAssemblyMemoryGrowthObserved", True),
        (
            "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
            True,
        ),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_LIMITATIONS,
)

PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE,
    query_mode=PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE,
    sentinel=PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SENTINEL,
    case=PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_CASE,
    scope=PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", True),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            False,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            False,
        ),
        ("pageWebAssemblyTableGrowthObserved", True),
        (
            "pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved",
            True,
        ),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            False,
        ),
        ("pageWebAssemblyExceptionsObserved", False),
        (
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
            False,
        ),
        ("pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved", False),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
            False,
        ),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_LIMITATIONS,
)

PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_WASM_THROW_MODE,
    query_mode=PAGE_WEBASSEMBLY_WASM_THROW_MODE,
    sentinel=PAGE_WEBASSEMBLY_WASM_THROW_SENTINEL,
    case=PAGE_WEBASSEMBLY_WASM_THROW_CASE,
    scope=PAGE_WEBASSEMBLY_WASM_THROW_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_WASM_THROW_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_WASM_THROW_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            False,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            False,
        ),
        ("pageWebAssemblyTableGrowthObserved", False),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            False,
        ),
        ("pageWebAssemblyExceptionsObserved", True),
        (
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
            False,
        ),
        ("pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved", True),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
            False,
        ),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_WASM_THROW_LIMITATIONS,
)

PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE,
    query_mode=PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE,
    sentinel=PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SENTINEL,
    case=PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_CASE,
    scope=PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            False,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            False,
        ),
        ("pageWebAssemblyTableGrowthObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved",
            False,
        ),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            False,
        ),
        ("pageWebAssemblyExceptionsObserved", True),
        (
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
            False,
        ),
        ("pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved", False),
        (
            "pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved",
            True,
        ),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
            False,
        ),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_LIMITATIONS,
)

PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE,
    query_mode=PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE,
    sentinel=PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SENTINEL,
    case=PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_CASE,
    scope=PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        ("pageWebAssemblyTablesObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            False,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            False,
        ),
        ("pageWebAssemblyTableGrowthObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved",
            False,
        ),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            False,
        ),
        ("pageWebAssemblyExceptionsObserved", True),
        (
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
            False,
        ),
        ("pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved", False),
        (
            "pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved",
            False,
        ),
        (
            "pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved",
            True,
        ),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
            False,
        ),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_LIMITATIONS,
)

PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG = DevToolsProtocolSmokeConfig(
    mode_id=PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE,
    query_mode=PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE,
    sentinel=PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SENTINEL,
    case=PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_CASE,
    scope=PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SCOPE,
    runtime_arguments=(PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SWITCH,),
    native_markers=(
        NETWORK_ENABLE_MARKER,
        RUNTIME_ENABLE_MARKER,
        RUNTIME_EVALUATE_MARKER,
        PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER,
        RUNTIME_CONSOLE_API_CALLED_MARKER,
        DETACHED_MARKER,
        LIFECYCLE_PASS_MARKER,
    ),
    page_webassembly_expectations=(
        ("pageWebAssemblyUnavailableObserved", False),
        ("pageWebAssemblyAdd42Observed", False),
        (
            "pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed",
            True,
        ),
        ("pageWebAssemblyTablesObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedIndirectCallObserved",
            False,
        ),
        (
            "pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved",
            False,
        ),
        ("pageWebAssemblyTableGrowthObserved", False),
        (
            "pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved",
            False,
        ),
        ("pageWebAssemblyMemoriesObserved", False),
        ("pageWebAssemblyMemoryConstructedImportedReadWriteObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved",
            False,
        ),
        ("pageWebAssemblyExceptionsObserved", False),
        (
            "pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved",
            False,
        ),
        ("pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved", False),
        (
            "pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved",
            False,
        ),
        (
            "pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved",
            False,
        ),
        ("pageWebAssemblyMemoryGrowthObserved", False),
        (
            "pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved",
            False,
        ),
        ("pageWebAssemblyThreadsObserved", False),
    ),
    limitations=PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_LIMITATIONS,
)


def smoke_config_for_page_webassembly(
    page_webassembly: bool,
    page_webassembly_memory: bool = False,
) -> DevToolsProtocolSmokeConfig:
    if page_webassembly_memory:
        return smoke_config_for_page_webassembly_memory(True)
    return (
        PAGE_WEBASSEMBLY_SMOKE_CONFIG
        if page_webassembly
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_memory(
    page_webassembly_memory: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG
        if page_webassembly_memory
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_table(
    page_webassembly_table: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG
        if page_webassembly_table
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_table_growth(
    page_webassembly_table_growth: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_CONFIG
        if page_webassembly_table_growth
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_memory_growth(
    page_webassembly_memory_growth: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG
        if page_webassembly_memory_growth
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_exceptions(
    page_webassembly_exceptions: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG
        if page_webassembly_exceptions
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_wasm_memory_grow_opcode(
    page_webassembly_wasm_memory_grow_opcode: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG
        if page_webassembly_wasm_memory_grow_opcode
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_wasm_table_grow_opcode(
    page_webassembly_wasm_table_grow_opcode: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_CONFIG
        if page_webassembly_wasm_table_grow_opcode
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_wasm_throw(
    page_webassembly_wasm_throw: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG
        if page_webassembly_wasm_throw
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_wasm_throw_payload(
    page_webassembly_wasm_throw_payload: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_CONFIG
        if page_webassembly_wasm_throw_payload
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_js_throw_payload(
    page_webassembly_js_throw_payload: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_CONFIG
        if page_webassembly_js_throw_payload
        else DEFAULT_SMOKE_CONFIG
    )


def smoke_config_for_page_webassembly_instantiate_streaming(
    page_webassembly_instantiate_streaming: bool,
) -> DevToolsProtocolSmokeConfig:
    return (
        PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG
        if page_webassembly_instantiate_streaming
        else DEFAULT_SMOKE_CONFIG
    )


def _require_known_smoke_config(smoke_config: DevToolsProtocolSmokeConfig) -> None:
    if smoke_config not in (
        DEFAULT_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_CONFIG,
        PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG,
    ):
        raise M0Error("DevTools protocol smoke configuration is not fixed")


class DevToolsProtocolSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    artifacts: dict[str, bytes]
    host_html: bytes
    host_js: bytes
    module_name: str
    result_token: str
    result_queue: queue.Queue[dict[str, Any]]
    result_lock: threading.Lock
    result_received: bool
    smoke_config: DevToolsProtocolSmokeConfig


class DevToolsProtocolSmokeRequestHandler(BaseHTTPRequestHandler):
    server: DevToolsProtocolSmokeServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_bytes(
        self, status: HTTPStatus, content_type: str, body: bytes
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_bytes(
            HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (HOST_ROOT, f"{HOST_ROOT}/"):
            self._send_bytes(
                HTTPStatus.OK, "text/html; charset=utf-8", self.server.host_html
            )
            return
        if path == (
            f"{HOST_ROOT}/chrome_wasm_browser_devtools_protocol_smoke_host.js"
        ):
            self._send_bytes(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                self.server.host_js,
            )
            return
        if path == f"{HOST_ROOT}/config/{self.server.result_token}":
            mode_payload = json.dumps(
                {
                    "protocol": 1,
                    "mode": self.server.smoke_config.mode_id,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_bytes(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                mode_payload,
            )
            return
        prefix = f"{HOST_ROOT}/artifacts/"
        if path.startswith(prefix):
            name = path[len(prefix) :]
            artifact = self.server.artifacts.get(name)
            if artifact is not None:
                self._send_bytes(
                    HTTPStatus.OK,
                    "application/wasm"
                    if name.endswith(".wasm")
                    else "text/javascript; charset=utf-8",
                    artifact,
                )
                return
        self._not_found()

    def do_POST(self) -> None:
        expected = f"{HOST_ROOT}/result/{self.server.result_token}"
        if urlsplit(self.path).path != expected:
            self._not_found()
            return
        content_length = self.headers.get("Content-Length")
        try:
            byte_count = int(content_length) if content_length is not None else -1
        except ValueError:
            byte_count = -1
        if byte_count < 0 or byte_count > MAX_RESULT_BYTES:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "text/plain; charset=utf-8",
                b"invalid result size\n",
            )
            return
        result = parse_result_payload(
            self.rfile.read(byte_count), smoke_config=self.server.smoke_config
        )
        if result is None:
            self._send_bytes(
                HTTPStatus.BAD_REQUEST,
                "text/plain; charset=utf-8",
                b"invalid DevTools protocol result\n",
            )
            return
        with self.server.result_lock:
            if self.server.result_received:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"DevTools protocol result already received\n",
                )
                return
            try:
                self.server.result_queue.put_nowait(result)
            except queue.Full:
                self._send_bytes(
                    HTTPStatus.CONFLICT,
                    "text/plain; charset=utf-8",
                    b"DevTools protocol result queue is full\n",
                )
                return
            self.server.result_received = True
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def parse_result_payload(
    payload: bytes,
    *,
    smoke_config: DevToolsProtocolSmokeConfig = DEFAULT_SMOKE_CONFIG,
) -> dict[str, Any] | None:
    _require_known_smoke_config(smoke_config)
    try:
        result = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=browser_view_smoke._reject_duplicate_result_object_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(result, dict)
        or type(result.get("protocol")) is not int
        or result.get("protocol") != 1
        or result.get("case") != smoke_config.case
        or result.get("scope") != smoke_config.scope
    ):
        return None
    return result


def create_server(
    host: str,
    port: int,
    out_dir: Path,
    result_token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    module_name: str,
    smoke_config: DevToolsProtocolSmokeConfig = DEFAULT_SMOKE_CONFIG,
) -> DevToolsProtocolSmokeServer:
    if not MODULE_NAME_RE.fullmatch(module_name):
        raise M0Error("module name must contain only ASCII letters, digits, or _")
    _require_known_smoke_config(smoke_config)
    out_dir = out_dir.resolve()
    host_dir = Path(__file__).with_name("host")
    artifacts = snapshot_regular_files(
        out_dir,
        (f"{module_name}.js", f"{module_name}.wasm"),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="DevTools protocol artifacts",
    )
    host_resources = snapshot_regular_files(
        host_dir,
        (
            "chrome_wasm_browser_devtools_protocol_smoke.html",
            "chrome_wasm_browser_devtools_protocol_smoke_host.js",
        ),
        maximum_bytes=MAX_SNAPSHOT_BYTES,
        description="DevTools protocol host resources",
    )
    server = DevToolsProtocolSmokeServer(
        (host, port), DevToolsProtocolSmokeRequestHandler
    )
    server.artifacts = artifacts
    server.host_html = host_resources[
        "chrome_wasm_browser_devtools_protocol_smoke.html"
    ]
    server.host_js = host_resources[
        "chrome_wasm_browser_devtools_protocol_smoke_host.js"
    ]
    server.module_name = module_name
    server.result_token = result_token
    server.result_queue = result_queue
    server.result_lock = threading.Lock()
    server.result_received = False
    server.smoke_config = smoke_config
    return server


def _byte_identity(contents: bytes) -> dict[str, object]:
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def artifact_identity(server: DevToolsProtocolSmokeServer) -> dict[str, object]:
    return {
        "delivery": ARTIFACT_DELIVERY,
        "module": server.module_name,
        "loader": _byte_identity(server.artifacts[f"{server.module_name}.js"]),
        "wasm": _byte_identity(server.artifacts[f"{server.module_name}.wasm"]),
    }


def smoke_url(
    server: DevToolsProtocolSmokeServer,
    token: str,
    versions: dict[str, str],
    *,
    module_name: str,
    timeout_seconds: float,
    smoke_config: DevToolsProtocolSmokeConfig = DEFAULT_SMOKE_CONFIG,
) -> str:
    _require_known_smoke_config(smoke_config)
    host, port = server.server_address[:2]
    query_values = {
        "token": token,
        "module": module_name,
        "timeoutMs": str(int(timeout_seconds * 1000)),
        "versions": json.dumps(versions, sort_keys=True, separators=(",", ":")),
    }
    if smoke_config.query_mode is not None:
        query_values["mode"] = smoke_config.query_mode
    query = urlencode(query_values)
    return f"http://{host}:{port}{HOST_ROOT}/?{query}"


def _require_equal(result: dict[str, Any], field: str, expected: object) -> None:
    if not browser_view_smoke._exact_json_value_equal(result.get(field), expected):
        raise M0Error(
            f"DevTools protocol result {field} mismatch: "
            f"expected {expected!r}, got {result.get(field)!r}"
        )


def _require_unique_ordered_markers(
    stderr: list[object],
    *,
    smoke_config: DevToolsProtocolSmokeConfig = DEFAULT_SMOKE_CONFIG,
) -> None:
    _require_known_smoke_config(smoke_config)
    output = "\n".join(str(value) for value in stderr)
    markers = smoke_config.native_markers
    positions: dict[str, int] = {}
    for marker in markers:
        count = output.count(marker)
        if count != 1:
            raise M0Error(
                f"DevTools protocol native marker count is {count}: {marker}"
            )
        positions[marker] = output.index(marker)
    if FAILURE_MARKER in output:
        raise M0Error("DevTools protocol native smoke emitted a failure marker")
    if smoke_config == PAGE_WEBASSEMBLY_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_ADD42_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_MEMORY_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_MEMORY_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_TABLE_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_TABLE_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_TABLE_GROWTH_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_WASM_THROW_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MARKER
    elif smoke_config == PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_CONFIG:
        page_webassembly_marker = PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER
    else:
        page_webassembly_marker = PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER
    dom_get_document_ordered = (
        smoke_config != DEFAULT_SMOKE_CONFIG
        or (
            positions[RUNTIME_ENABLE_MARKER]
            < positions[DOM_GET_DOCUMENT_MARKER]
            < positions[RUNTIME_EVALUATE_MARKER]
        )
    )
    if not (
        positions[NETWORK_ENABLE_MARKER]
        < positions[RUNTIME_ENABLE_MARKER]
        < positions[RUNTIME_EVALUATE_MARKER]
        < positions[page_webassembly_marker]
        < positions[DETACHED_MARKER]
        < positions[LIFECYCLE_PASS_MARKER]
        and positions[RUNTIME_ENABLE_MARKER]
        < positions[RUNTIME_CONSOLE_API_CALLED_MARKER]
        < positions[DETACHED_MARKER]
        and dom_get_document_ordered
    ):
        raise M0Error("DevTools protocol native markers are not ordered")


def validate_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    smoke_config: DevToolsProtocolSmokeConfig = DEFAULT_SMOKE_CONFIG,
) -> None:
    _require_known_smoke_config(smoke_config)
    expected_fields = {
        "protocol": 1,
        "case": smoke_config.case,
        "scope": smoke_config.scope,
        "status": "pass",
        "m8GateComplete": False,
        "runtimeExitCode": 0,
        "runtimeInitialized": True,
        "crossOriginIsolated": True,
        "sharedArrayBuffer": True,
        "canvasFocusAccepted": True,
        "networkEnableObserved": True,
        "runtimeEnableObserved": True,
        "runtimeEvaluateObserved": True,
        "runtimeConsoleApiCalledObserved": True,
        "detachedObserved": True,
        "lifecyclePassObserved": True,
        "abort": None,
        "failedChecks": [],
        "error": None,
    }
    expected_fields.update(smoke_config.page_webassembly_expectations)
    if smoke_config == DEFAULT_SMOKE_CONFIG:
        expected_fields["domGetDocumentObserved"] = True
    for field, expected in expected_fields.items():
        _require_equal(result, field, expected)
    process_exit_code = result.get("processExitCode")
    if process_exit_code is not None and (
        type(process_exit_code) is not int or process_exit_code != 0
    ):
        raise M0Error("DevTools protocol process exit disagrees with normal close")
    if result.get("versions") != expected_versions:
        raise M0Error("DevTools protocol versions do not match the manifest")
    for field in ("fatalErrors", "windowErrors", "unhandledRejections", "stdout"):
        if not isinstance(result.get(field), list) or result[field]:
            raise M0Error(f"DevTools protocol {field} is not empty")
    stderr = result.get("stderr")
    if not isinstance(stderr, list):
        raise M0Error("DevTools protocol stderr is not a list")
    _require_unique_ordered_markers(stderr, smoke_config=smoke_config)
    browser_view_smoke._validate_frame_reports(result.get("frameReports"))
    browser_view_smoke._validate_readiness(
        result.get("readiness"), result.get("readinessReports")
    )


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while True:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before DevTools protocol result: "
                + "\n".join(browser_stderr)
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M0Error(
                "DevTools protocol smoke timeout: " + "\n".join(browser_stderr)
            )
        try:
            return result_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    runtime_result: dict[str, Any] | None,
    smoke_config: DevToolsProtocolSmokeConfig,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "chrome-browser-devtools-protocol-m8-failure.json"
    payload = {
        "schema_version": 1,
        "runner": "run_m8_wasm_browser_devtools_protocol_dom_smoke.py",
        "case": smoke_config.case,
        "scope": smoke_config.scope,
        "stage": stage,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": list(browser_stderr),
        },
        "runtime_result": runtime_result,
    }
    if smoke_config.query_mode is not None:
        payload["mode"] = smoke_config.mode_id
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed in-process DevTools protocol smoke in a browser."
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--build-profile",
        choices=tuple(CHROME_BUILD_PROFILES),
        default=M6_CHROME_BUILD_PROFILE,
        help=(
            "select the exact manifest-backed Chrome build profile; "
            "m8-codegen-experiment is not an M8 completion gate"
        ),
    )
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--module-name", default="chrome_wasm")
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument(
        "--page-webassembly",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly validate/module/instance/add42 "
            "DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-memory",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly memory construct/import/"
            "read-write DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-table",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly table construct/import/"
            "element-initialize/indirect-call DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-memory-growth",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly memory construct/import/"
            "grow/post-growth-read-write DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-table-growth",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly table construct/import/"
            "grow/initialized-indirect-call DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-exceptions",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly exception construct/"
            "imported-tag/JS-throw/Wasm-catch DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-wasm-memory-grow-opcode",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly imported-memory Wasm "
            "memory.grow opcode DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-wasm-table-grow-opcode",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly imported-table Wasm "
            "table.grow opcode/indirect-call DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-wasm-throw",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly imported-tag Wasm throw/"
            "JavaScript-catch DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-wasm-throw-payload",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly imported-i32-tag Wasm "
            "throw/JavaScript-catch-payload DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-js-throw-payload",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly imported-i32-tag JavaScript "
            "throw/Wasm-catch-payload DevTools smoke"
        ),
    )
    parser.add_argument(
        "--page-webassembly-instantiate-streaming",
        action="store_true",
        help=(
            "run the fixed native page-WebAssembly instantiateStreaming "
            "data:application/wasm module/instance/add42 DevTools smoke"
        ),
    )
    parser.add_argument("--timeout", type=parse_timeout, default=60.0)
    args = parser.parse_args()
    if args.timeout < 2.0:
        parser.error("--timeout must be at least two seconds")
    if not MODULE_NAME_RE.fullmatch(args.module_name):
        parser.error("--module-name must contain only ASCII letters, digits, or _")
    if (
        int(args.page_webassembly)
        + int(args.page_webassembly_memory)
        + int(args.page_webassembly_table)
        + int(args.page_webassembly_memory_growth)
        + int(args.page_webassembly_table_growth)
        + int(args.page_webassembly_exceptions)
        + int(args.page_webassembly_wasm_memory_grow_opcode)
        + int(args.page_webassembly_wasm_table_grow_opcode)
        + int(args.page_webassembly_wasm_throw)
        + int(args.page_webassembly_wasm_throw_payload)
        + int(args.page_webassembly_js_throw_payload)
        + int(args.page_webassembly_instantiate_streaming)
        > 1
    ):
        parser.error(
            "--page-webassembly, --page-webassembly-memory, "
            "--page-webassembly-table, --page-webassembly-memory-growth, and "
            "--page-webassembly-table-growth, --page-webassembly-exceptions, "
            "--page-webassembly-wasm-memory-grow-opcode, and "
            "--page-webassembly-wasm-table-grow-opcode, --page-webassembly-"
            "wasm-throw, --page-webassembly-wasm-throw-payload, and "
            "--page-webassembly-js-throw-payload, and "
            "--page-webassembly-instantiate-streaming are mutually exclusive"
        )
    smoke_config = (
        smoke_config_for_page_webassembly_instantiate_streaming(True)
        if args.page_webassembly_instantiate_streaming
        else (
            smoke_config_for_page_webassembly_js_throw_payload(True)
            if args.page_webassembly_js_throw_payload
            else (
                smoke_config_for_page_webassembly_wasm_throw_payload(True)
                if args.page_webassembly_wasm_throw_payload
                else (
                    smoke_config_for_page_webassembly_wasm_throw(True)
                    if args.page_webassembly_wasm_throw
                    else (
                        smoke_config_for_page_webassembly_wasm_memory_grow_opcode(True)
                        if args.page_webassembly_wasm_memory_grow_opcode
                        else (
                            smoke_config_for_page_webassembly_wasm_table_grow_opcode(True)
                            if args.page_webassembly_wasm_table_grow_opcode
                            else (
                                smoke_config_for_page_webassembly_exceptions(True)
                                if args.page_webassembly_exceptions
                                else (
                                    smoke_config_for_page_webassembly_table_growth(True)
                                    if args.page_webassembly_table_growth
                                    else (
                                        smoke_config_for_page_webassembly_memory_growth(True)
                                        if args.page_webassembly_memory_growth
                                        else (
                                            smoke_config_for_page_webassembly_table(True)
                                            if args.page_webassembly_table
                                            else smoke_config_for_page_webassembly(
                                                args.page_webassembly,
                                                args.page_webassembly_memory,
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
    )

    build_profile = chrome_build_profile(args.build_profile)
    try:
        require_build_profile_for_smoke(build_profile, smoke_config)
    except M0Error as exc:
        parser.error(str(exc))

    out_dir = resolve_build_out_dir(build_profile, args.out_dir)
    diagnostics_dir = args.diagnostics_dir or out_dir / "diagnostics"
    if not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir
    server: DevToolsProtocolSmokeServer | None = None
    server_thread: threading.Thread | None = None
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] | None = None
    stage = "check_artifacts"

    try:
        stage = "load_manifest"
        manifest = load_manifest()
        stage = "verify_build_profile"
        build_profile_record = verify_build_profile(
            out_dir, manifest, build_profile
        )
        stage = "check_boundary"
        check_boundary(out_dir)
        versions = manifest_versions(
            manifest, checked_output(["git", "rev-parse", "HEAD"])
        )
        print_context(
            "run_m8_wasm_browser_devtools_protocol_dom_smoke.py",
            manifest,
            case=smoke_config.case,
            scope=smoke_config.scope,
            gn_args=manifest[build_profile.manifest_key],
            build_profile=build_profile_record,
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            artifact_delivery=ARTIFACT_DELIVERY,
            runtime_arguments=list(smoke_config.runtime_arguments),
            limitations=list(smoke_config.limitations),
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "snapshot_and_create_server"
        server = create_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
            smoke_config=smoke_config,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m8-devtools-protocol-server",
            daemon=True,
        )
        server_thread.start()
        url = smoke_url(
            server,
            token,
            versions,
            module_name=args.module_name,
            timeout_seconds=max(1.0, args.timeout - 1.0),
            smoke_config=smoke_config,
        )
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m8-devtools-protocol-"
        )
        stage = "launch_browser"
        command = browser_command(
            browser_path, profile.name, url, no_sandbox=args.no_sandbox
        )
        command[1:1] = ["--enable-logging=stderr"]
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m8-devtools-protocol-browser-stderr",
            daemon=True,
        )
        stderr_thread.start()
        stage = "wait_for_normal_close_result"
        result = wait_for_result(
            browser, browser_stderr, result_queue, time.monotonic() + args.timeout
        )
        stage = "validate_result"
        validate_result(
            result, expected_versions=versions, smoke_config=smoke_config
        )
        print(
            f"{smoke_config.sentinel}:ARTIFACT "
            + json.dumps(
                artifact_identity(server), sort_keys=True, separators=(",", ":")
            ),
            flush=True,
        )
        print(
            f"{smoke_config.sentinel}:BROWSER_RESULT "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{smoke_config.sentinel}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        try:
            diagnostic = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=exc,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                runtime_result=result,
                smoke_config=smoke_config,
            )
            print(
                f"{smoke_config.sentinel}:DIAGNOSTICS "
                + json.dumps({"path": str(diagnostic)}),
                file=sys.stderr,
            )
        except (OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{smoke_config.sentinel}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
            )
        print(
            f"{smoke_config.sentinel}:FAIL reason={exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=1)
        if profile is not None:
            profile.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

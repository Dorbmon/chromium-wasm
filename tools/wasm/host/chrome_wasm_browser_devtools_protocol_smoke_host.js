// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This host witnesses one fixed, in-process native DevToolsAgentHost exchange
// under a real browser profile. It neither implements a DevTools frontend nor
// forwards a protocol command, response, event, socket, or page script.
const HOST_PROTOCOL = 1;
const CASE = "browser_devtools_protocol_m8";
const SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-dom-get-document-runtime-evaluate-console-event-detach-close";
const SWITCH = "--wasm-browser-devtools-protocol-smoke";
const PAGE_JAVASCRIPT_SEMANTICS_MODE = "page-javascript-semantics";
const PAGE_JAVASCRIPT_SEMANTICS_CASE = "browser_page_javascript_semantics_m8";
const PAGE_JAVASCRIPT_SEMANTICS_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-javascript-closures-classes-promise-" +
    "microtasks-bigint-typed-arrays-console-event-detach-close";
const PAGE_JAVASCRIPT_SEMANTICS_SWITCH =
    "--wasm-browser-m8-page-javascript-semantics-smoke";
const PAGE_JAVASCRIPT_ASYNC_REJECTION_MODE = "page-javascript-async-rejection";
const PAGE_JAVASCRIPT_ASYNC_REJECTION_CASE =
    "browser_page_javascript_async_rejection_m8";
const PAGE_JAVASCRIPT_ASYNC_REJECTION_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-javascript-async-rejection-catch-" +
    "finally-order-console-event-detach-close";
const PAGE_JAVASCRIPT_ASYNC_REJECTION_SWITCH =
    "--wasm-browser-m8-page-javascript-async-rejection-smoke";
const PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MODE =
    "page-javascript-platform-semantics";
const PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_CASE =
    "browser_page_javascript_platform_semantics_m8";
const PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-javascript-data-module-live-binding-" +
    "structured-clone-transfer-message-channel-transfer-custom-element-" +
    "mutation-observer-console-event-detach-close";
const PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SWITCH =
    "--wasm-browser-m8-page-javascript-platform-semantics-smoke";
const PAGE_WEBASSEMBLY_MODE = "page-webassembly";
const PAGE_WEBASSEMBLY_CASE = "browser_page_webassembly_m8";
const PAGE_WEBASSEMBLY_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-validate-module-instance-" +
    "add42-console-event-detach-close";
const PAGE_WEBASSEMBLY_SWITCH = "--wasm-browser-m8-page-webassembly-smoke";
const PAGE_WEBASSEMBLY_MEMORY_MODE = "page-webassembly-memory";
const PAGE_WEBASSEMBLY_MEMORY_CASE = "browser_page_webassembly_memory_m8";
const PAGE_WEBASSEMBLY_MEMORY_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-memory-construct-import-" +
    "js-write-wasm-read-wasm-write-js-read-console-event-detach-close";
const PAGE_WEBASSEMBLY_MEMORY_SWITCH =
    "--wasm-browser-m8-page-webassembly-memory-smoke";
const PAGE_WEBASSEMBLY_TABLE_MODE = "page-webassembly-table";
const PAGE_WEBASSEMBLY_TABLE_CASE = "browser_page_webassembly_table_m8";
const PAGE_WEBASSEMBLY_TABLE_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-table-construct-import-" +
    "element-initialize-indirect-call-console-event-detach-close";
const PAGE_WEBASSEMBLY_TABLE_SWITCH =
    "--wasm-browser-m8-page-webassembly-table-smoke";
const PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE = "page-webassembly-table-growth";
const PAGE_WEBASSEMBLY_TABLE_GROWTH_CASE =
    "browser_page_webassembly_table_growth_m8";
const PAGE_WEBASSEMBLY_TABLE_GROWTH_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-table-construct-import-" +
    "grow-one-to-two-entries-initialize-grown-entry-indirect-call-console-event-" +
    "detach-close";
const PAGE_WEBASSEMBLY_TABLE_GROWTH_SWITCH =
    "--wasm-browser-m8-page-webassembly-table-growth-smoke";
const PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE = "page-webassembly-memory-growth";
const PAGE_WEBASSEMBLY_MEMORY_GROWTH_CASE =
    "browser_page_webassembly_memory_growth_m8";
const PAGE_WEBASSEMBLY_MEMORY_GROWTH_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-memory-construct-import-" +
    "grow-one-to-two-pages-post-growth-js-write-wasm-read-wasm-write-js-read-" +
    "console-event-detach-close";
const PAGE_WEBASSEMBLY_MEMORY_GROWTH_SWITCH =
    "--wasm-browser-m8-page-webassembly-memory-growth-smoke";
const PAGE_WEBASSEMBLY_EXCEPTIONS_MODE = "page-webassembly-exceptions";
const PAGE_WEBASSEMBLY_EXCEPTIONS_CASE =
    "browser_page_webassembly_exceptions_m8";
const PAGE_WEBASSEMBLY_EXCEPTIONS_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-exception-construct-import-" +
    "tag-js-throw-wasm-catch-console-event-detach-close";
const PAGE_WEBASSEMBLY_EXCEPTIONS_SWITCH =
    "--wasm-browser-m8-page-webassembly-exceptions-smoke";
const PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE =
    "page-webassembly-wasm-memory-grow-opcode";
const PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_CASE =
    "browser_page_webassembly_wasm_memory_grow_opcode_m8";
const PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-memory-construct-import-" +
    "wasm-memory-grow-opcode-one-to-two-pages-buffer-replaced-console-event-" +
    "detach-close";
const PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SWITCH =
    "--wasm-browser-m8-page-webassembly-wasm-memory-grow-opcode-smoke";
const PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE =
    "page-webassembly-wasm-table-grow-opcode";
const PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_CASE =
    "browser_page_webassembly_wasm_table_grow_opcode_m8";
const PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-table-construct-import-" +
    "wasm-table-grow-opcode-one-to-two-entries-initialize-grown-entry-" +
    "indirect-call-console-event-detach-close";
const PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SWITCH =
    "--wasm-browser-m8-page-webassembly-wasm-table-grow-opcode-smoke";
const PAGE_WEBASSEMBLY_WASM_THROW_MODE = "page-webassembly-wasm-throw";
const PAGE_WEBASSEMBLY_WASM_THROW_CASE =
    "browser_page_webassembly_wasm_throw_m8";
const PAGE_WEBASSEMBLY_WASM_THROW_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-exception-import-tag-" +
    "wasm-throw-js-catch-console-event-detach-close";
const PAGE_WEBASSEMBLY_WASM_THROW_SWITCH =
    "--wasm-browser-m8-page-webassembly-wasm-throw-smoke";
const PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE =
    "page-webassembly-wasm-throw-payload";
const PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_CASE =
    "browser_page_webassembly_wasm_throw_payload_m8";
const PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-exception-import-i32-tag-" +
    "wasm-throw-js-catch-payload-42-console-event-detach-close";
const PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SWITCH =
    "--wasm-browser-m8-page-webassembly-wasm-throw-payload-smoke";
const PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE =
    "page-webassembly-js-throw-payload";
const PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_CASE =
    "browser_page_webassembly_js_throw_payload_m8";
const PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-exception-import-i32-tag-" +
    "js-throw-wasm-catch-payload-42-console-event-detach-close";
const PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SWITCH =
    "--wasm-browser-m8-page-webassembly-js-throw-payload-smoke";
const PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE =
    "page-webassembly-instantiate-streaming";
const PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_CASE =
    "browser_page_webassembly_instantiate_streaming_m8";
const PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SCOPE =
    "fixed-data-url-primary-webcontents-native-devtools-client-network-enable-" +
    "runtime-enable-runtime-evaluate-page-webassembly-instantiate-streaming-" +
    "fetch-data-application-wasm-module-instance-add42-console-event-detach-" +
    "close";
const PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SWITCH =
    "--wasm-browser-m8-page-webassembly-instantiate-streaming-smoke";
const NETWORK_ENABLE_MARKER =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:NETWORK_ENABLE_OK";
const RUNTIME_ENABLE_MARKER =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_ENABLE_OK";
const DOM_GET_DOCUMENT_MARKER =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DOM_GET_DOCUMENT_OK";
const RUNTIME_EVALUATE_MARKER =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_EVALUATE_OK";
const PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:PAGE_WEBASSEMBLY_UNAVAILABLE";
const PAGE_JAVASCRIPT_SEMANTICS_MARKER =
    "CHROMIUM_WASM_M8_PAGE_JAVASCRIPT_SEMANTICS:" +
    "CLOSURES_CLASSES_PROMISE_MICROTASKS_BIGINT_TYPED_ARRAYS_OK";
const PAGE_JAVASCRIPT_ASYNC_REJECTION_MARKER =
    "CHROMIUM_WASM_M8_PAGE_JAVASCRIPT_ASYNC_REJECTION:" +
    "CATCH_FINALLY_ORDER_OK";
const PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MARKER =
    "CHROMIUM_WASM_M8_PAGE_JAVASCRIPT_PLATFORM_SEMANTICS:" +
    "DATA_MODULE_LIVE_BINDING_STRUCTURED_CLONE_TRANSFER_MESSAGE_CHANNEL_" +
    "TRANSFER_CUSTOM_ELEMENT_MUTATION_OBSERVER_OK";
const PAGE_WEBASSEMBLY_ADD42_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "VALIDATED_MODULE_CONSTRUCTED_INSTANCE_ADD_42_OK";
const PAGE_WEBASSEMBLY_MEMORY_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "MEMORY_CONSTRUCTED_IMPORTED_JS_WRITE_WASM_READ_WASM_WRITE_JS_READ_OK";
const PAGE_WEBASSEMBLY_TABLE_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "TABLE_CONSTRUCTED_IMPORTED_ELEMENT_INITIALIZED_INDIRECT_CALL_42_OK";
const PAGE_WEBASSEMBLY_TABLE_GROWTH_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "TABLE_CONSTRUCTED_IMPORTED_GROWN_1_TO_2_ENTRIES_INITIALIZED_" +
    "INDIRECT_CALL_42_OK";
const PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "MEMORY_CONSTRUCTED_IMPORTED_GROWN_1_TO_2_PAGES_POST_GROWTH_JS_WRITE_" +
    "WASM_READ_WASM_WRITE_JS_READ_OK";
const PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "EXCEPTION_CONSTRUCTED_IMPORTED_TAG_JS_THROW_WASM_CATCH_42_OK";
const PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "MEMORY_CONSTRUCTED_IMPORTED_WASM_MEMORY_GROW_OPCODE_GROWN_1_TO_2_PAGES_" +
    "BUFFER_REPLACED_OK";
const PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "TABLE_CONSTRUCTED_IMPORTED_WASM_TABLE_GROW_OPCODE_GROWN_1_TO_2_ENTRIES_" +
    "INITIALIZED_INDIRECT_CALL_42_OK";
const PAGE_WEBASSEMBLY_WASM_THROW_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "EXCEPTION_IMPORTED_TAG_WASM_THROW_JS_CATCH_OK";
const PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "EXCEPTION_IMPORTED_I32_TAG_WASM_THROW_JS_CATCH_PAYLOAD_42_OK";
const PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "EXCEPTION_IMPORTED_I32_TAG_JS_THROW_WASM_CATCH_PAYLOAD_42_OK";
const PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:" +
    "INSTANTIATE_STREAMING_DATA_URL_APPLICATION_WASM_MODULE_INSTANCE_ADD_42_OK";
const RUNTIME_CONSOLE_API_CALLED_MARKER =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_CONSOLE_API_CALLED_OK";
const DETACHED_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DETACHED";
const FAILURE_MARKER = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:FAIL";
const LIFECYCLE_PASS_MARKER = "CHROMIUM_WASM_M6_BROWSER_LIFECYCLE:PASS";
const MAX_TIMEOUT_MS = 120000;
const MAX_FRAME_DIMENSION = 16384;
const MAX_RECORD_HISTORY = 64;
const HOST_ROOT = "/__m8_browser_devtools_protocol__";

const DEFAULT_SMOKE_MODE = Object.freeze({
  id: "default",
  queryMode: null,
  case: CASE,
  scope: SCOPE,
  runtimeArguments: Object.freeze([SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: true,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    DOM_GET_DOCUMENT_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_JAVASCRIPT_SEMANTICS_SMOKE_MODE = Object.freeze({
  id: PAGE_JAVASCRIPT_SEMANTICS_MODE,
  queryMode: PAGE_JAVASCRIPT_SEMANTICS_MODE,
  case: PAGE_JAVASCRIPT_SEMANTICS_CASE,
  scope: PAGE_JAVASCRIPT_SEMANTICS_SCOPE,
  runtimeArguments: Object.freeze([PAGE_JAVASCRIPT_SEMANTICS_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({}),
  ordinaryJavaScriptExpectations: Object.freeze({
    v8ProvenanceEstablished: false,
    pageJavaScriptSemanticsClosuresClassesPromiseMicrotasksBigIntTypedArraysObserved:
        true,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_JAVASCRIPT_SEMANTICS_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_MODE = Object.freeze({
  id: PAGE_JAVASCRIPT_ASYNC_REJECTION_MODE,
  queryMode: PAGE_JAVASCRIPT_ASYNC_REJECTION_MODE,
  case: PAGE_JAVASCRIPT_ASYNC_REJECTION_CASE,
  scope: PAGE_JAVASCRIPT_ASYNC_REJECTION_SCOPE,
  runtimeArguments: Object.freeze([PAGE_JAVASCRIPT_ASYNC_REJECTION_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({}),
  ordinaryJavaScriptExpectations: Object.freeze({
    v8ProvenanceEstablished: false,
    pageJavaScriptAsyncRejectionCatchFinallyOrderObserved: true,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_JAVASCRIPT_ASYNC_REJECTION_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SMOKE_MODE = Object.freeze({
  id: PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MODE,
  queryMode: PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MODE,
  case: PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_CASE,
  scope: PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SCOPE,
  runtimeArguments: Object.freeze([PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({}),
  ordinaryJavaScriptExpectations: Object.freeze({
    v8ProvenanceEstablished: false,
    pageJavaScriptPlatformSemanticsDataModuleStructuredCloneMessageChannelCustomElementMutationObserverObserved:
        true,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_MODE,
  queryMode: PAGE_WEBASSEMBLY_MODE,
  case: PAGE_WEBASSEMBLY_CASE,
  scope: PAGE_WEBASSEMBLY_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: true,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_ADD42_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_MEMORY_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_MEMORY_MODE,
  queryMode: PAGE_WEBASSEMBLY_MEMORY_MODE,
  case: PAGE_WEBASSEMBLY_MEMORY_CASE,
  scope: PAGE_WEBASSEMBLY_MEMORY_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_MEMORY_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyMemoriesObserved: true,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: true,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_MEMORY_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_TABLE_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_TABLE_MODE,
  queryMode: PAGE_WEBASSEMBLY_TABLE_MODE,
  case: PAGE_WEBASSEMBLY_TABLE_CASE,
  scope: PAGE_WEBASSEMBLY_TABLE_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_TABLE_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: true,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: true,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_TABLE_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE,
  queryMode: PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE,
  case: PAGE_WEBASSEMBLY_TABLE_GROWTH_CASE,
  scope: PAGE_WEBASSEMBLY_TABLE_GROWTH_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_TABLE_GROWTH_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: true,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: true,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: true,
    pageWebAssemblyTableGrowthObserved: true,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_TABLE_GROWTH_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE,
  queryMode: PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE,
  case: PAGE_WEBASSEMBLY_MEMORY_GROWTH_CASE,
  scope: PAGE_WEBASSEMBLY_MEMORY_GROWTH_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_MEMORY_GROWTH_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyMemoriesObserved: true,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: true,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: true,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyMemoryGrowthObserved: true,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_EXCEPTIONS_MODE,
  queryMode: PAGE_WEBASSEMBLY_EXCEPTIONS_MODE,
  case: PAGE_WEBASSEMBLY_EXCEPTIONS_CASE,
  scope: PAGE_WEBASSEMBLY_EXCEPTIONS_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_EXCEPTIONS_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false,
    pageWebAssemblyExceptionsObserved: true,
    pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: true,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE,
  queryMode: PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE,
  case: PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_CASE,
  scope: PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SCOPE,
  runtimeArguments: Object.freeze([
    PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SWITCH,
  ]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyMemoriesObserved: true,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: false,
    pageWebAssemblyMemoryGrowthObserved: true,
    pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:
        true,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE,
  queryMode: PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE,
  case: PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_CASE,
  scope: PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SCOPE,
  runtimeArguments: Object.freeze([
    PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SWITCH,
  ]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: true,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: true,
    pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved:
        true,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: false,
    pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved: false,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:
        false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_WASM_THROW_MODE,
  queryMode: PAGE_WEBASSEMBLY_WASM_THROW_MODE,
  case: PAGE_WEBASSEMBLY_WASM_THROW_CASE,
  scope: PAGE_WEBASSEMBLY_WASM_THROW_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_WASM_THROW_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false,
    pageWebAssemblyExceptionsObserved: true,
    pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: false,
    pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved: true,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:
        false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_WASM_THROW_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE,
  queryMode: PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE,
  case: PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_CASE,
  scope: PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved:
        false,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false,
    pageWebAssemblyExceptionsObserved: true,
    pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: false,
    pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved: false,
    pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved:
        true,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:
        false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE,
  queryMode: PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE,
  case: PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_CASE,
  scope: PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SCOPE,
  runtimeArguments: Object.freeze([PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SWITCH]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved:
        false,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false,
    pageWebAssemblyExceptionsObserved: true,
    pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: false,
    pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved: false,
    pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved:
        false,
    pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved:
        true,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:
        false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

const PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_MODE = Object.freeze({
  id: PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE,
  queryMode: PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE,
  case: PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_CASE,
  scope: PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SCOPE,
  runtimeArguments: Object.freeze([
    PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SWITCH,
  ]),
  pageWebAssemblyExpectations: Object.freeze({
    pageWebAssemblyUnavailableObserved: false,
    pageWebAssemblyAdd42Observed: false,
    pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed:
        true,
    pageWebAssemblyTablesObserved: false,
    pageWebAssemblyTableConstructedImportedIndirectCallObserved: false,
    pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved: false,
    pageWebAssemblyTableGrowthObserved: false,
    pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved:
        false,
    pageWebAssemblyMemoriesObserved: false,
    pageWebAssemblyMemoryConstructedImportedReadWriteObserved: false,
    pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved: false,
    pageWebAssemblyExceptionsObserved: false,
    pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved: false,
    pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved: false,
    pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved:
        false,
    pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved:
        false,
    pageWebAssemblyMemoryGrowthObserved: false,
    pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:
        false,
    pageWebAssemblyThreadsObserved: false,
  }),
  nativeMarkers: Object.freeze([
    NETWORK_ENABLE_MARKER,
    RUNTIME_ENABLE_MARKER,
    RUNTIME_EVALUATE_MARKER,
    PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER,
    RUNTIME_CONSOLE_API_CALLED_MARKER,
    DETACHED_MARKER,
    LIFECYCLE_PASS_MARKER,
  ]),
});

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_RECORD_HISTORY) {
    records.shift();
  }
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(description + " must be a nonempty string");
  }
  return value;
}

function asReport(value, description) {
  let report = value;
  if (typeof report === "string") {
    try {
      report = JSON.parse(report);
    } catch (error) {
      throw new Error(description + " is not valid JSON: " + String(error));
    }
  }
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    throw new Error(description + " must be an object");
  }
  return report;
}

function parseVersions(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    throw new Error("invalid DevTools protocol versions: " + String(error));
  }
  const versions = {};
  for (const field of ["chromium", "v8", "emscripten", "port"]) {
    versions[field] = asNonemptyString(parsed?.[field], "version " + field);
  }
  return Object.freeze(versions);
}

function renderVersions(element, versions) {
  element.replaceChildren();
  for (const [name, value] of Object.entries(versions)) {
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = name;
    definition.textContent = value;
    element.append(term, definition);
  }
}

function isFrameReport(value) {
  return value && typeof value === "object" &&
      Number.isSafeInteger(value.id) && value.id >= 1 &&
      Number.isSafeInteger(value.width) && value.width >= 1 &&
      value.width <= MAX_FRAME_DIMENSION &&
      Number.isSafeInteger(value.height) && value.height >= 1 &&
      value.height <= MAX_FRAME_DIMENSION &&
      Number.isFinite(value.timestampMs) && value.timestampMs >= 0;
}

function isReadinessReport(value) {
  return value && typeof value === "object" &&
      typeof value.shellReady === "boolean" &&
      typeof value.surfaceReady === "boolean" &&
      typeof value.firstVisuallyNonEmptyPaint === "boolean";
}

function countMarker(records, marker) {
  return records.filter((record) => record.includes(marker)).length;
}

function markerIndex(records, marker) {
  return records.findIndex((record) => record.includes(marker));
}

function isKnownSmokeMode(smokeMode) {
  return smokeMode === DEFAULT_SMOKE_MODE ||
      smokeMode === PAGE_JAVASCRIPT_SEMANTICS_SMOKE_MODE ||
      smokeMode === PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_MODE ||
      smokeMode === PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_MEMORY_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_TABLE_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_MODE ||
      smokeMode === PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_MODE;
}

function validateResult(result, smokeMode) {
  if (!isKnownSmokeMode(smokeMode)) {
    throw new Error("DevTools protocol smoke mode is not fixed");
  }
  const failures = [];
  const require = (condition, message) => {
    if (!condition) {
      failures.push(message);
    }
  };
  require(result.status === "pass", "runtime status is not pass");
  require(result.m8GateComplete === false, "smoke claims M8 complete");
  require(result.runtimeExitCode === 0, "runtime did not close normally");
  require(result.processExitCode === null || result.processExitCode === 0,
      "process exit disagrees with normal close");
  require(result.runtimeInitialized === true, "runtime did not initialize");
  require(result.crossOriginIsolated === true, "host is not isolated");
  require(result.sharedArrayBuffer === true, "SharedArrayBuffer is unavailable");
  require(result.canvasFocusAccepted === true, "canvas did not accept focus");
  require(result.networkEnableObserved === true,
      "Network.enable marker was not observed");
  require(result.runtimeEnableObserved === true,
      "Runtime.enable marker was not observed");
  if (smokeMode === DEFAULT_SMOKE_MODE) {
    require(result.domGetDocumentObserved === true,
        "DOM.getDocument marker was not observed");
  }
  require(result.runtimeEvaluateObserved === true,
      "Runtime.evaluate marker was not observed");
  for (const [field, expected] of Object.entries(
      smokeMode.pageWebAssemblyExpectations)) {
    require(result[field] === expected,
        "page WebAssembly expectation mismatch: " + field);
  }
  for (const [field, expected] of Object.entries(
      smokeMode.ordinaryJavaScriptExpectations || {})) {
    require(result[field] === expected,
        "ordinary JavaScript expectation mismatch: " + field);
  }
  require(result.runtimeConsoleApiCalledObserved === true,
      "Runtime.consoleAPICalled marker was not observed");
  require(result.detachedObserved === true, "detach marker was not observed");
  require(result.lifecyclePassObserved === true,
      "Browser lifecycle pass marker was not observed");
  require(result.abort === null, "runtime aborted");
  require(result.fatalErrors.length === 0, "host recorded a fatal error");
  require(result.windowErrors.length === 0, "host recorded a window error");
  require(result.unhandledRejections.length === 0,
      "host recorded an unhandled rejection");
  require(Array.isArray(result.frameReports) && result.frameReports.length >= 1,
      "host did not record a compositor frame");
  require(result.readiness?.surfaceReady === true,
      "host did not observe a ready canvas surface");

  const stderr = result.stderr;
  const markers = smokeMode.nativeMarkers;
  const positions = {};
  if (Array.isArray(stderr)) {
    for (const marker of markers) {
      require(countMarker(stderr, marker) === 1,
          "native marker is not unique: " + marker);
      positions[marker] = markerIndex(stderr, marker);
    }
    require(countMarker(stderr, FAILURE_MARKER) === 0,
        "native DevTools smoke emitted a failure marker");
  } else {
    require(false, "native stderr is not a list");
  }
  const runtimeMarker = smokeMode === PAGE_JAVASCRIPT_SEMANTICS_SMOKE_MODE ?
      PAGE_JAVASCRIPT_SEMANTICS_MARKER :
      smokeMode === PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_MODE ?
      PAGE_JAVASCRIPT_ASYNC_REJECTION_MARKER :
      smokeMode === PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SMOKE_MODE ?
      PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_ADD42_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_MEMORY_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_MEMORY_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_TABLE_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_TABLE_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_TABLE_GROWTH_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_WASM_THROW_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MARKER :
      smokeMode === PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_MODE ?
      PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER :
      PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER;
  const domGetDocumentOrdered = smokeMode !== DEFAULT_SMOKE_MODE ||
      (positions[RUNTIME_ENABLE_MARKER] < positions[DOM_GET_DOCUMENT_MARKER] &&
       positions[DOM_GET_DOCUMENT_MARKER] < positions[RUNTIME_EVALUATE_MARKER]);
  require(positions[NETWORK_ENABLE_MARKER] >= 0 &&
              positions[RUNTIME_ENABLE_MARKER] >= 0 &&
              positions[RUNTIME_EVALUATE_MARKER] >= 0 &&
              positions[runtimeMarker] >= 0 &&
              positions[RUNTIME_CONSOLE_API_CALLED_MARKER] >= 0 &&
              positions[DETACHED_MARKER] >= 0 &&
              positions[LIFECYCLE_PASS_MARKER] >= 0 &&
              positions[NETWORK_ENABLE_MARKER] <
                  positions[RUNTIME_ENABLE_MARKER] &&
              positions[RUNTIME_ENABLE_MARKER] <
                  positions[RUNTIME_EVALUATE_MARKER] &&
              positions[RUNTIME_ENABLE_MARKER] <
                  positions[RUNTIME_CONSOLE_API_CALLED_MARKER] &&
              positions[RUNTIME_EVALUATE_MARKER] <
                  positions[runtimeMarker] &&
              positions[runtimeMarker] <
                  positions[DETACHED_MARKER] &&
              positions[RUNTIME_CONSOLE_API_CALLED_MARKER] <
                  positions[DETACHED_MARKER] &&
              positions[DETACHED_MARKER] < positions[LIFECYCLE_PASS_MARKER] &&
              domGetDocumentOrdered,
          "native DevTools protocol markers are not ordered");

  if (failures.length !== 0) {
    result.status = "fail";
    result.failedChecks = failures;
  }
  return result;
}

class ChromiumWasmBrowserDevToolsProtocolSmokeHost {
  #canvas;
  #versions;
  #smokeMode;
  #module = null;
  #stdout = [];
  #stderr = [];
  #fatalErrors = [];
  #windowErrors = [];
  #unhandledRejections = [];
  #runtimeInitialized = false;
  #runtimeExitCode = null;
  #processExitCode = null;
  #abort = null;
  #runtimeExitResolver;
  #runtimeExitPromise;
  #frameReports = [];
  #readiness = null;
  #readinessReports = [];
  #canvasFocusAccepted = false;
  #networkEnableObserved = false;
  #runtimeEnableObserved = false;
  #domGetDocumentObserved = false;
  #runtimeEvaluateObserved = false;
  #pageJavaScriptSemanticsClosuresClassesPromiseMicrotasksBigIntTypedArraysObserved =
      false;
  #pageJavaScriptAsyncRejectionCatchFinallyOrderObserved = false;
  #pageJavaScriptPlatformSemanticsDataModuleStructuredCloneMessageChannelCustomElementMutationObserverObserved =
      false;
  #pageWebAssemblyUnavailableObserved = false;
  #pageWebAssemblyAdd42Observed = false;
  #pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed =
      false;
  #pageWebAssemblyTablesObserved = false;
  #pageWebAssemblyTableConstructedImportedIndirectCallObserved = false;
  #pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved = false;
  #pageWebAssemblyTableGrowthObserved = false;
  #pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved =
      false;
  #pageWebAssemblyMemoriesObserved = false;
  #pageWebAssemblyMemoryConstructedImportedReadWriteObserved = false;
  #pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved =
      false;
  #pageWebAssemblyMemoryGrowthObserved = false;
  #pageWebAssemblyExceptionsObserved = false;
  #pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved =
      false;
  #pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved =
      false;
  #pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved = false;
  #pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved =
      false;
  #pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved =
      false;
  #runtimeConsoleApiCalledObserved = false;
  #detachedObserved = false;
  #lifecyclePassObserved = false;
  #errorHandler;
  #rejectionHandler;

  constructor(canvas, versions, smokeMode) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new Error("DevTools protocol smoke requires a canvas");
    }
    if (!isKnownSmokeMode(smokeMode)) {
      throw new Error("DevTools protocol smoke mode is not fixed");
    }
    this.#canvas = canvas;
    this.#versions = versions;
    this.#smokeMode = smokeMode;
    this.#runtimeExitPromise = new Promise((resolve) => {
      this.#runtimeExitResolver = resolve;
    });
  }

  #recordFatal(message) {
    appendBounded(this.#fatalErrors, String(message));
  }

  #captureWindowErrors() {
    this.#errorHandler = (event) => {
      const message = String(event.error || event.message || "window error");
      appendBounded(this.#windowErrors, message);
      this.#recordFatal("window error: " + message);
    };
    this.#rejectionHandler = (event) => {
      appendBounded(this.#unhandledRejections, String(event.reason));
    };
    window.addEventListener("error", this.#errorHandler);
    window.addEventListener("unhandledrejection", this.#rejectionHandler);
  }

  #releaseWindowErrors() {
    if (this.#errorHandler) {
      window.removeEventListener("error", this.#errorHandler);
      this.#errorHandler = undefined;
    }
    if (this.#rejectionHandler) {
      window.removeEventListener("unhandledrejection", this.#rejectionHandler);
      this.#rejectionHandler = undefined;
    }
  }

  #recordOutput(text) {
    if (text.includes(NETWORK_ENABLE_MARKER)) this.#networkEnableObserved = true;
    if (text.includes(RUNTIME_ENABLE_MARKER)) this.#runtimeEnableObserved = true;
    if (text.includes(DOM_GET_DOCUMENT_MARKER)) {
      this.#domGetDocumentObserved = true;
    }
    if (text.includes(RUNTIME_EVALUATE_MARKER)) {
      this.#runtimeEvaluateObserved = true;
    }
    if (text.includes(PAGE_JAVASCRIPT_SEMANTICS_MARKER)) {
      this.#pageJavaScriptSemanticsClosuresClassesPromiseMicrotasksBigIntTypedArraysObserved =
          true;
    }
    if (text.includes(PAGE_JAVASCRIPT_ASYNC_REJECTION_MARKER)) {
      this.#pageJavaScriptAsyncRejectionCatchFinallyOrderObserved = true;
    }
    if (text.includes(PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MARKER)) {
      this.#pageJavaScriptPlatformSemanticsDataModuleStructuredCloneMessageChannelCustomElementMutationObserverObserved =
          true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_UNAVAILABLE_MARKER)) {
      this.#pageWebAssemblyUnavailableObserved = true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_ADD42_MARKER)) {
      this.#pageWebAssemblyAdd42Observed = true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MARKER)) {
      this.#pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed =
          true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_TABLE_MARKER)) {
      this.#pageWebAssemblyTablesObserved = true;
      this.#pageWebAssemblyTableConstructedImportedIndirectCallObserved = true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_TABLE_GROWTH_MARKER)) {
      this.#pageWebAssemblyTablesObserved = true;
      this.#pageWebAssemblyTableConstructedImportedIndirectCallObserved = true;
      this.#pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved =
          true;
      this.#pageWebAssemblyTableGrowthObserved = true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_MEMORY_MARKER)) {
      this.#pageWebAssemblyMemoriesObserved = true;
      this.#pageWebAssemblyMemoryConstructedImportedReadWriteObserved = true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_MEMORY_GROWTH_MARKER)) {
      this.#pageWebAssemblyMemoriesObserved = true;
      this.#pageWebAssemblyMemoryConstructedImportedReadWriteObserved = true;
      this.#pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved =
          true;
      this.#pageWebAssemblyMemoryGrowthObserved = true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_EXCEPTIONS_MARKER)) {
      this.#pageWebAssemblyExceptionsObserved = true;
      this.#pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved =
          true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MARKER)) {
      this.#pageWebAssemblyMemoriesObserved = true;
      this.#pageWebAssemblyMemoryGrowthObserved = true;
      this.#pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved =
          true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MARKER)) {
      this.#pageWebAssemblyTablesObserved = true;
      this.#pageWebAssemblyTableGrowthObserved = true;
      this.#pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved =
          true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_WASM_THROW_MARKER)) {
      this.#pageWebAssemblyExceptionsObserved = true;
      this.#pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved = true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MARKER)) {
      this.#pageWebAssemblyExceptionsObserved = true;
      this.#pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved =
          true;
    }
    if (text.includes(PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MARKER)) {
      this.#pageWebAssemblyExceptionsObserved = true;
      this.#pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved =
          true;
    }
    if (text.includes(RUNTIME_CONSOLE_API_CALLED_MARKER)) {
      this.#runtimeConsoleApiCalledObserved = true;
    }
    if (text.includes(DETACHED_MARKER)) this.#detachedObserved = true;
    if (text.includes(LIFECYCLE_PASS_MARKER)) {
      this.#lifecyclePassObserved = true;
    }
  }

  #reportRuntimeExit(code) {
    if (!Number.isSafeInteger(code) || this.#runtimeExitCode !== null) {
      this.#recordFatal("invalid runtime exit: " + String(code));
      return;
    }
    this.#runtimeExitCode = code;
    this.#runtimeExitResolver(code);
  }

  #reportProcessExit(value) {
    try {
      const report = asReport(value, "process-exit report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.exitCode) ||
          this.#processExitCode !== null) {
        throw new Error("process exit report is invalid or duplicated");
      }
      this.#processExitCode = report.exitCode;
    } catch (error) {
      this.#recordFatal("invalid process-exit report: " + String(error));
    }
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL || !isFrameReport(report)) {
        throw new Error("frame metadata is invalid");
      }
      const previous = this.#frameReports.at(-1);
      if ((previous && report.id <= previous.id) ||
          this.#canvas.width !== report.width ||
          this.#canvas.height !== report.height) {
        throw new Error("frame sequence or canvas dimensions are invalid");
      }
      appendBounded(this.#frameReports, {
        id: report.id,
        width: report.width,
        height: report.height,
        timestampMs: report.timestampMs,
      });
    } catch (error) {
      this.#recordFatal("invalid frame report: " + String(error));
    }
  }

  #reportReadiness(value) {
    try {
      const report = asReport(value, "readiness report");
      if (report.protocol !== HOST_PROTOCOL || !isReadinessReport(report)) {
        throw new Error("readiness metadata is invalid");
      }
      this.#readiness = {
        shellReady: report.shellReady,
        surfaceReady: report.surfaceReady,
        firstVisuallyNonEmptyPaint: report.firstVisuallyNonEmptyPaint,
      };
      appendBounded(this.#readinessReports, this.#readiness);
    } catch (error) {
      this.#recordFatal("invalid readiness report: " + String(error));
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("DevTools protocol host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(message) { host.#recordFatal(message); },
      reportProcessExit(report) { host.#reportProcessExit(report); },
      reportFrame(report) { host.#reportFrame(report); },
      reportReadiness(report) { host.#reportReadiness(report); },
      reportOzoneFocusState(_report) {},
      reportOzoneCursor(_report) { return true; },
      reportOzoneTextInputState(_report) {},
      reportOzoneTextInputDelivery(_report) {},
      reportOzoneBrowserTextInputDelivery(_report) {},
      reportOzoneBrowserClipboardPasteDelivery(_report) {},
      requestOuterOriginStorageEstimate(_report) { return false; },
    });
  }

  #setModule(module) {
    if (!module || typeof module !== "object" || this.#module !== null) {
      this.#recordFatal("onRuntimeInitialized supplied an invalid Module object");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
  }

  #result(status, error) {
    let pageRuntimeResult;
    if (this.#smokeMode === DEFAULT_SMOKE_MODE) {
      pageRuntimeResult = {
        pageWebAssemblyUnavailableObserved:
            this.#pageWebAssemblyUnavailableObserved,
      };
    } else if (this.#smokeMode === PAGE_JAVASCRIPT_SEMANTICS_SMOKE_MODE) {
      pageRuntimeResult = {
        v8ProvenanceEstablished: false,
        pageJavaScriptSemanticsClosuresClassesPromiseMicrotasksBigIntTypedArraysObserved:
            this.#pageJavaScriptSemanticsClosuresClassesPromiseMicrotasksBigIntTypedArraysObserved,
      };
    } else if (this.#smokeMode ===
               PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_MODE) {
      pageRuntimeResult = {
        v8ProvenanceEstablished: false,
        pageJavaScriptAsyncRejectionCatchFinallyOrderObserved:
            this.#pageJavaScriptAsyncRejectionCatchFinallyOrderObserved,
      };
    } else if (this.#smokeMode ===
               PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SMOKE_MODE) {
      pageRuntimeResult = {
        v8ProvenanceEstablished: false,
        pageJavaScriptPlatformSemanticsDataModuleStructuredCloneMessageChannelCustomElementMutationObserverObserved:
            this.#pageJavaScriptPlatformSemanticsDataModuleStructuredCloneMessageChannelCustomElementMutationObserverObserved,
      };
    } else {
      pageRuntimeResult = {
        pageWebAssemblyUnavailableObserved:
            this.#pageWebAssemblyUnavailableObserved,
        pageWebAssemblyAdd42Observed: this.#pageWebAssemblyAdd42Observed,
        pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed:
            this.#pageWebAssemblyInstantiateStreamingDataUrlModuleInstanceAdd42Observed,
        pageWebAssemblyTablesObserved: this.#pageWebAssemblyTablesObserved,
        pageWebAssemblyTableConstructedImportedIndirectCallObserved:
            this.#pageWebAssemblyTableConstructedImportedIndirectCallObserved,
        pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved:
            this.#pageWebAssemblyTableConstructedImportedGrownIndirectCallObserved,
        pageWebAssemblyTableGrowthObserved:
            this.#pageWebAssemblyTableGrowthObserved,
        pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved:
            this.#pageWebAssemblyTableConstructedImportedWasmGrowOpcodeOneToTwoEntriesObserved,
        pageWebAssemblyMemoriesObserved: this.#pageWebAssemblyMemoriesObserved,
        pageWebAssemblyMemoryConstructedImportedReadWriteObserved:
            this.#pageWebAssemblyMemoryConstructedImportedReadWriteObserved,
        pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved:
            this.#pageWebAssemblyMemoryConstructedImportedGrownPostGrowthReadWriteObserved,
        pageWebAssemblyExceptionsObserved:
            this.#pageWebAssemblyExceptionsObserved,
        pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved:
            this.#pageWebAssemblyExceptionConstructedImportedTagJsThrowWasmCatchObserved,
        pageWebAssemblyMemoryGrowthObserved:
            this.#pageWebAssemblyMemoryGrowthObserved,
        pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved:
            this.#pageWebAssemblyMemoryConstructedImportedWasmGrowOpcodeOneToTwoPagesObserved,
        pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved:
            this.#pageWebAssemblyExceptionImportedTagWasmThrowJsCatchObserved,
        pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved:
            this.#pageWebAssemblyExceptionImportedI32TagWasmThrowJsCatchPayloadObserved,
        pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved:
            this.#pageWebAssemblyExceptionImportedI32TagJsThrowWasmCatchPayloadObserved,
        pageWebAssemblyThreadsObserved: false,
      };
    }
    return {
      protocol: HOST_PROTOCOL,
      case: this.#smokeMode.case,
      scope: this.#smokeMode.scope,
      status,
      m8GateComplete: false,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      runtimeInitialized: this.#runtimeInitialized,
      crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      canvasFocusAccepted: this.#canvasFocusAccepted,
      networkEnableObserved: this.#networkEnableObserved,
      runtimeEnableObserved: this.#runtimeEnableObserved,
      domGetDocumentObserved: this.#domGetDocumentObserved,
      runtimeEvaluateObserved: this.#runtimeEvaluateObserved,
      ...pageRuntimeResult,
      runtimeConsoleApiCalledObserved: this.#runtimeConsoleApiCalledObserved,
      detachedObserved: this.#detachedObserved,
      lifecyclePassObserved: this.#lifecyclePassObserved,
      abort: this.#abort,
      fatalErrors: this.#fatalErrors,
      windowErrors: this.#windowErrors,
      unhandledRejections: this.#unhandledRejections,
      versions: this.#versions,
      frameReports: this.#frameReports,
      readiness: this.#readiness,
      readinessReports: this.#readinessReports,
      stdout: this.#stdout,
      stderr: this.#stderr,
      failedChecks: [],
      error,
    };
  }

  async run(modulePath, timeoutMs) {
    const startedAt = performance.now();
    try {
      if (!crossOriginIsolated || typeof SharedArrayBuffer !== "function") {
        throw new Error("DevTools protocol smoke requires cross-origin isolation");
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 ||
          timeoutMs > MAX_TIMEOUT_MS) {
        throw new Error("DevTools protocol timeout is out of range");
      }
      const moduleUrl = new URL(modulePath, document.baseURI);
      if (moduleUrl.origin !== location.origin) {
        throw new Error("DevTools protocol module must use the host origin");
      }
      this.#canvas.focus({preventScroll: true});
      this.#canvasFocusAccepted = document.activeElement === this.#canvas;
      if (!this.#canvasFocusAccepted) {
        throw new Error("DevTools protocol canvas did not accept focus");
      }
      this.#installBridge();
      this.#captureWindowErrors();
      const response = await fetch(moduleUrl.href, {cache: "no-store"});
      if (!response.ok) {
        throw new Error("module request returned HTTP " + response.status);
      }
      const mainScriptUrlOrBlob = await response.blob();
      if (mainScriptUrlOrBlob.size === 0) {
        throw new Error("DevTools protocol module loader is empty");
      }
      const namespace = await import(moduleUrl.href);
      if (typeof namespace.default !== "function") {
        throw new Error("DevTools protocol loader has no default factory export");
      }
      const host = this;
      namespace.default({
        // Emscripten owns and may extend its argv array, so copy the one
        // immutable mode tuple rather than passing the frozen configuration
        // array itself.
        arguments: [...this.#smokeMode.runtimeArguments],
        canvas: this.#canvas,
        noExitRuntime: false,
        mainScriptUrlOrBlob,
        locateFile: (path) => new URL(path, moduleUrl).href,
        print(line) {
          const text = String(line);
          appendBounded(host.#stdout, text);
          host.#recordOutput(text);
        },
        printErr(line) {
          const text = String(line);
          appendBounded(host.#stderr, text);
          host.#recordOutput(text);
        },
        onRuntimeInitialized() { host.#setModule(this); },
        onAbort(reason) {
          host.#abort = String(reason);
          host.#recordFatal("abort: " + host.#abort);
        },
        onExit(code) { host.#reportRuntimeExit(Number(code)); },
      }).catch((_error) => {
        host.#recordFatal("DevTools protocol module factory rejected");
      });

      const deadline = startedAt + timeoutMs;
      while (this.#runtimeExitCode === null && performance.now() < deadline) {
        await Promise.race([this.#runtimeExitPromise, delay(25)]);
      }
      if (this.#runtimeExitCode === null) {
        throw new Error("DevTools protocol smoke did not exit before timeout");
      }
      await delay(25);
      return this.#result("pass", null);
    } catch (error) {
      return this.#result("fail", String(error));
    } finally {
      this.#releaseWindowErrors();
    }
  }
}

function requireSingleQueryValue(query, key, description) {
  const values = query.getAll(key);
  if (values.length !== 1) {
    throw new Error(description + " must occur exactly once");
  }
  return asNonemptyString(values[0], description);
}

export function parseDevToolsProtocolSmokeQuery(query) {
  if (!(query instanceof URLSearchParams)) {
    throw new Error("DevTools protocol query must be URLSearchParams");
  }
  const acceptedKeys =
      new Set(["token", "module", "timeoutMs", "versions", "mode"]);
  for (const key of query.keys()) {
    if (!acceptedKeys.has(key)) {
      throw new Error(
          "DevTools protocol query has an unsupported field: " + key);
    }
  }
  const token = requireSingleQueryValue(query, "token", "result token");
  const moduleName = requireSingleQueryValue(query, "module", "module name");
  if (!/^[A-Za-z0-9_]+$/.test(moduleName)) {
    throw new Error("module name contains unsupported characters");
  }
  const timeoutMs = Number(requireSingleQueryValue(
      query, "timeoutMs", "DevTools protocol timeout"));
  const versions = parseVersions(requireSingleQueryValue(
      query, "versions", "DevTools protocol versions"));
  const modes = query.getAll("mode");
  let smokeMode;
  if (modes.length === 0) {
    smokeMode = DEFAULT_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_JAVASCRIPT_SEMANTICS_MODE) {
    smokeMode = PAGE_JAVASCRIPT_SEMANTICS_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_JAVASCRIPT_ASYNC_REJECTION_MODE) {
    smokeMode = PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_MODE) {
    smokeMode = PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SMOKE_MODE;
  } else if (modes.length === 1 && modes[0] === PAGE_WEBASSEMBLY_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_SMOKE_MODE;
  } else if (modes.length === 1 && modes[0] === PAGE_WEBASSEMBLY_MEMORY_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_MEMORY_SMOKE_MODE;
  } else if (modes.length === 1 && modes[0] === PAGE_WEBASSEMBLY_TABLE_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_TABLE_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_TABLE_GROWTH_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_MEMORY_GROWTH_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_EXCEPTIONS_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_WASM_THROW_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_MODE;
  } else if (modes.length === 1 &&
             modes[0] === PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_MODE) {
    smokeMode = PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_MODE;
  } else {
    throw new Error("DevTools protocol query has an invalid mode");
  }
  return Object.freeze({token, moduleName, timeoutMs, versions, smokeMode});
}

async function fetchExpectedSmokeMode(token) {
  const response = await fetch(
      HOST_ROOT + "/config/" + encodeURIComponent(token), {cache: "no-store"});
  if (!response.ok) {
    throw new Error("DevTools protocol mode binding returned HTTP " +
        response.status);
  }
  let binding;
  try {
    binding = JSON.parse(await response.text());
  } catch (error) {
    throw new Error("DevTools protocol mode binding is not JSON: " +
        String(error));
  }
  if (!binding || typeof binding !== "object" || Array.isArray(binding) ||
      binding.protocol !== HOST_PROTOCOL ||
      !Object.hasOwn(binding, "mode") || Object.keys(binding).length !== 2 ||
      (binding.mode !== DEFAULT_SMOKE_MODE.id &&
       binding.mode !== PAGE_JAVASCRIPT_SEMANTICS_SMOKE_MODE.id &&
       binding.mode !== PAGE_JAVASCRIPT_ASYNC_REJECTION_SMOKE_MODE.id &&
       binding.mode !== PAGE_JAVASCRIPT_PLATFORM_SEMANTICS_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_MEMORY_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_TABLE_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_TABLE_GROWTH_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_MEMORY_GROWTH_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_EXCEPTIONS_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_WASM_MEMORY_GROW_OPCODE_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_WASM_TABLE_GROW_OPCODE_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_WASM_THROW_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_WASM_THROW_PAYLOAD_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_JS_THROW_PAYLOAD_SMOKE_MODE.id &&
       binding.mode !== PAGE_WEBASSEMBLY_INSTANTIATE_STREAMING_SMOKE_MODE.id)) {
    throw new Error("DevTools protocol mode binding is invalid");
  }
  return binding.mode;
}

export async function runChromeWasmBrowserDevToolsProtocolSmokeFromQuery() {
  const parameters = parseDevToolsProtocolSmokeQuery(
      new URLSearchParams(location.search));
  const expectedSmokeMode = await fetchExpectedSmokeMode(parameters.token);
  if (expectedSmokeMode !== parameters.smokeMode.id) {
    throw new Error("DevTools protocol query mode does not match its binding");
  }
  const root = document.querySelector("#browser-devtools-protocol-root");
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#browser-devtools-protocol-status");
  const versionElement = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) ||
      !(status instanceof HTMLElement) || !(versionElement instanceof HTMLElement)) {
    throw new Error("DevTools protocol page is missing required elements");
  }
  renderVersions(versionElement, parameters.versions);
  const host = new ChromiumWasmBrowserDevToolsProtocolSmokeHost(
      canvas, parameters.versions, parameters.smokeMode);
  const result = validateResult(await host.run(
      HOST_ROOT + "/artifacts/" + parameters.moduleName + ".js",
      parameters.timeoutMs), parameters.smokeMode);
  root.dataset.state = result.status;
  status.textContent = JSON.stringify(result, null, 2);
  const response = await fetch(
      HOST_ROOT + "/result/" + encodeURIComponent(parameters.token), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(result),
      });
  if (!response.ok) {
    throw new Error(
        "DevTools protocol result POST returned HTTP " + response.status);
  }
  return result;
}

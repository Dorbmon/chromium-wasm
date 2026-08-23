// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef BASE_LOGGING_WASM_H_
#define BASE_LOGGING_WASM_H_

#include "base/logging.h"

#if !BUILDFLAG(IS_WASM)
#error "logging_wasm.h must only be included by WebAssembly targets"
#endif

namespace logging {

// Atomically claims the empty handler slot on a pthread-capable Wasm build.
// Returns false without modifying the installed handler when another owner
// already holds it. |handler| must be non-null.
BASE_EXPORT bool TrySetLogMessageHandlerIfNone(LogMessageHandlerFunction handler);

// Atomically clears the handler slot only when it still equals |handler|.
// Returns false without modifying a handler installed by another owner.
// |handler| must be non-null.
BASE_EXPORT bool ClearLogMessageHandlerIfEqual(LogMessageHandlerFunction handler);

}  // namespace logging

#endif  // BASE_LOGGING_WASM_H_

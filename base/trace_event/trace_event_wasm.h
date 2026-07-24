// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef BASE_TRACE_EVENT_TRACE_EVENT_WASM_H_
#define BASE_TRACE_EVENT_TRACE_EVENT_WASM_H_

// Perfetto tracing is not part of the M1 task-runtime gate. Keep the public
// trace argument types available to scheduler interfaces, but make every trace
// category explicitly disabled so this narrow Wasm build does not require a
// partially initialized tracing service.
#include "base/trace_event/common/trace_event_common.h"
#include "base/trace_event/trace_arguments.h"

#undef TRACE_COUNTER1
#undef TRACE_EVENT
#undef TRACE_EVENT0
#undef TRACE_EVENT1
#undef TRACE_EVENT_API_GET_CATEGORY_GROUP_ENABLED
#undef TRACE_EVENT_BEGIN
#undef TRACE_EVENT_BEGIN0
#undef TRACE_EVENT_CATEGORY_ENABLED
#undef TRACE_EVENT_CATEGORY_GROUP_ENABLED
#undef TRACE_EVENT_END
#undef TRACE_EVENT_END0
#undef TRACE_EVENT_INSTANT

namespace base::trace_event::internal {

inline constexpr unsigned char kWasmTracingDisabled = 0;

}  // namespace base::trace_event::internal

#define TRACE_EVENT(...) ((void)0)
#define TRACE_EVENT0(...) ((void)0)
#define TRACE_EVENT1(...) ((void)0)
#define TRACE_EVENT_BEGIN(...) ((void)0)
#define TRACE_EVENT_BEGIN0(...) ((void)0)
#define TRACE_EVENT_END(...) ((void)0)
#define TRACE_EVENT_END0(...) ((void)0)
#define TRACE_EVENT_INSTANT(...) ((void)0)
#define TRACE_COUNTER1(category, name, value) ((void)(value))

#define TRACE_EVENT_CATEGORY_ENABLED(category) false
#define TRACE_EVENT_CATEGORY_GROUP_ENABLED(category, result) \
  do {                                                       \
    *(result) = false;                                       \
  } while (false)
#define TRACE_EVENT_API_GET_CATEGORY_GROUP_ENABLED(category) \
  (&::base::trace_event::internal::kWasmTracingDisabled)

#endif  // BASE_TRACE_EVENT_TRACE_EVENT_WASM_H_

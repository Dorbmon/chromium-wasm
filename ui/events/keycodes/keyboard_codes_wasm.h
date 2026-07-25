// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// IWYU pragma: private, include "ui/events/keycodes/keyboard_codes.h"

#ifndef UI_EVENTS_KEYCODES_KEYBOARD_CODES_WASM_H_
#define UI_EVENTS_KEYCODES_KEYBOARD_CODES_WASM_H_

// Wasm has no native keyboard-code ABI. Aura and ui/events still require
// Chromium's VKEY value type before host input exists, so reuse the value-only
// enum also used by Fuchsia. This does not classify Wasm as POSIX or select any
// POSIX input implementation.
#include "ui/events/keycodes/keyboard_codes_posix.h"  // IWYU pragma: export

#endif  // UI_EVENTS_KEYCODES_KEYBOARD_CODES_WASM_H_

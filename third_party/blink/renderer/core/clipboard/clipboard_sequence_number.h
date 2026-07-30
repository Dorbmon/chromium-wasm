// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_CLIPBOARD_CLIPBOARD_SEQUENCE_NUMBER_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_CLIPBOARD_CLIPBOARD_SEQUENCE_NUMBER_H_

#include <cstdint>

namespace blink {

// A renderer-side snapshot of the 128-bit clipboard sequence number.
//
// ClipboardSequenceNumber is stored in garbage-collected objects. Keep its
// alignment at most 8 bytes because cppgc supports at most double-word-aligned
// allocations on 32-bit targets.
class ClipboardSequenceNumber {
 public:
  constexpr ClipboardSequenceNumber() = default;
  constexpr ClipboardSequenceNumber(uint64_t high, uint64_t low)
      : high_(high), low_(low) {}

  friend constexpr bool operator==(const ClipboardSequenceNumber&,
                                   const ClipboardSequenceNumber&) = default;

 private:
  uint64_t high_ = 0;
  uint64_t low_ = 0;
};

static_assert(sizeof(ClipboardSequenceNumber) == 2 * sizeof(uint64_t));
static_assert(alignof(ClipboardSequenceNumber) <= 8);

}  // namespace blink

#endif  // THIRD_PARTY_BLINK_RENDERER_CORE_CLIPBOARD_CLIPBOARD_SEQUENCE_NUMBER_H_

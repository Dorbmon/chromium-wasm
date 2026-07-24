// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/unguessable_token.h"

#include <stddef.h>
#include <stdint.h>

#include <ostream>
#include <string_view>

#include "base/check.h"
#include "base/token.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "unguessable_token_wasm.cc is only for WebAssembly"
#endif

namespace base {

UnguessableToken::UnguessableToken(const base::Token& token) : token_(token) {}

// static
UnguessableToken UnguessableToken::Create() {
  Token token = Token::CreateRandom();
  DCHECK(!token.is_zero());
  return UnguessableToken(token);
}

// static
const UnguessableToken& UnguessableToken::Null() {
  static const UnguessableToken null_token{};
  return null_token;
}

// static
std::optional<UnguessableToken> UnguessableToken::Deserialize(uint64_t high,
                                                              uint64_t low) {
  if (high == 0 && low == 0) {
    return std::nullopt;
  }
  return UnguessableToken(Token{high, low});
}

// static
std::optional<UnguessableToken> UnguessableToken::DeserializeFromString(
    std::string_view string_representation) {
  auto token = Token::FromString(string_representation);
  if (!token.has_value() || token->is_zero()) {
    return std::nullopt;
  }
  return UnguessableToken(*token);
}

bool operator==(const UnguessableToken& lhs, const UnguessableToken& rhs) {
  const auto lhs_bytes = lhs.token_.AsBytes();
  const auto rhs_bytes = rhs.token_.AsBytes();
  // The focused Wasm graph does not hydrate BoringSSL. Preserve the bearer
  // token comparison contract by examining every byte without an early exit.
  uint8_t difference = 0;
  for (size_t i = 0; i < 16; ++i) {
    difference |= lhs_bytes[i] ^ rhs_bytes[i];
  }
  return difference == 0;
}

std::ostream& operator<<(std::ostream& out, const UnguessableToken& token) {
  return out << "(" << token.ToString() << ")";
}

}  // namespace base

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/location.h"

#include <sstream>
#include <utility>

#include "base/compiler_specific.h"

namespace base {

Location::Location() = default;
Location::Location(const Location& other) = default;
Location::Location(Location&& other) noexcept = default;
Location& Location::operator=(const Location& other) = default;

Location::Location(const char* file_name, const void* program_counter)
    : file_name_(file_name), program_counter_(program_counter) {}

Location::Location(const char* function_name,
                   const char* file_name,
                   int line_number,
                   const void* program_counter)
    : function_name_(function_name),
      file_name_(file_name),
      line_number_(line_number),
      program_counter_(program_counter) {}

std::string Location::ToString() const {
  std::ostringstream output;
  if (has_source_info()) {
    output << function_name_ << '@' << file_name_ << ':' << line_number_;
  } else {
    output << "pc:" << program_counter_;
  }
  return std::move(output).str();
}

#if defined(COMPILER_GCC)
#define RETURN_ADDRESS() \
  __builtin_extract_return_addr(__builtin_return_address(0))
#else
#define RETURN_ADDRESS() nullptr
#endif

NOINLINE Location Location::Current(const char* function_name,
                                    const char* file_name,
                                    int line_number) {
  return Location(function_name, file_name, line_number, RETURN_ADDRESS());
}

NOINLINE Location Location::CurrentWithoutFunctionName(const char* file_name,
                                                       int line_number) {
  return Location(nullptr, file_name, line_number, RETURN_ADDRESS());
}

NOINLINE const void* GetProgramCounter() {
  return RETURN_ADDRESS();
}

#undef RETURN_ADDRESS

}  // namespace base

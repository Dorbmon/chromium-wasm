// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_INPUT_METHOD_H_
#define UI_OZONE_PLATFORM_WASM_WASM_INPUT_METHOD_H_

#include "ui/base/ime/input_method_minimal.h"

namespace ui {

// Keeps M4's existing direct-key behavior while reporting the authoritative
// TextInputClient state to the host. The host uses that acknowledgement before
// moving DOM focus from the presentation canvas to its IME proxy textarea.
class WasmInputMethod final : public InputMethodMinimal {
 public:
  explicit WasmInputMethod(ImeKeyEventDispatcher* ime_key_event_dispatcher);

  WasmInputMethod(const WasmInputMethod&) = delete;
  WasmInputMethod& operator=(const WasmInputMethod&) = delete;

  ~WasmInputMethod() override;

  // InputMethod:
  void OnTextInputTypeChanged(TextInputClient* client) override;

 protected:
  // InputMethodBase:
  void OnDidChangeFocusedClient(TextInputClient* focused_before,
                                TextInputClient* focused) override;

 private:
  void ReportTextInputState();
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_INPUT_METHOD_H_

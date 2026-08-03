// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_OZONE_PLATFORM_WASM_WASM_INPUT_METHOD_H_
#define UI_OZONE_PLATFORM_WASM_WASM_INPUT_METHOD_H_

#include <stdint.h>

#include <optional>
#include <string>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "ui/base/ime/input_method_minimal.h"
#include "ui/gfx/native_ui_types.h"
#include "ui/gfx/range/range.h"

namespace ui {

class WasmWindowManager;

// The versioned host-to-Ozone text record. Text is UTF-16 and all offsets are
// UTF-16 code units. It is constructed only after the C ABI has copied and
// validated the host-provided UTF-8 payload.
enum class WasmTextInputAction : int {
  kSetComposition = 1,
  kConfirmComposition = 2,
  kClearComposition = 3,
};

struct WasmTextInputRecord {
  WasmTextInputAction action;
  uint32_t session_id;
  uint32_t sequence;
  std::u16string text;
  gfx::Range selection;
};

// Keeps M4's existing direct-key behavior while reporting the authoritative
// TextInputClient state to the host. The host uses that acknowledgement before
// moving DOM focus from the presentation canvas to its IME proxy textarea.
class WasmInputMethod final : public InputMethodMinimal {
 public:
  WasmInputMethod(ImeKeyEventDispatcher* ime_key_event_dispatcher,
                  gfx::AcceleratedWidget widget,
                  WasmWindowManager* window_manager);

  WasmInputMethod(const WasmInputMethod&) = delete;
  WasmInputMethod& operator=(const WasmInputMethod&) = delete;

  ~WasmInputMethod() override;

  // InputMethod:
  void OnTextInputTypeChanged(TextInputClient* client) override;
  void CancelComposition(const TextInputClient* client) override;

  // Delivers a copied host composition record through the current focused
  // TextInputClient. The caller must have resolved this exact widget through
  // the Ozone-owned registry below.
  bool DispatchTextInput(const WasmTextInputRecord& record);
  void CancelHostComposition();

 protected:
  // InputMethodBase:
  void OnWillChangeFocusedClient(TextInputClient* focused_before,
                                 TextInputClient* focused) override;
  void OnDidChangeFocusedClient(TextInputClient* focused_before,
                                TextInputClient* focused) override;

 private:
  struct ActiveComposition {
    uint32_t session_id;
    base::WeakPtr<TextInputClient> client;
  };

  bool CanDispatchTextInput(TextInputClient* client) const;
  void ClearActiveComposition(TextInputClient* client);
  void ReportTextInputState();

  const gfx::AcceleratedWidget widget_;
  const raw_ptr<WasmWindowManager> window_manager_;
  uint32_t last_sequence_ = 0;
  std::optional<ActiveComposition> active_composition_;
};

// Opaque Ozone-Wasm routing boundary for Content Shell. This intentionally
// avoids extending SystemInputInjector or fabricating a generic ui::Event for
// IME operations.
bool DispatchWasmTextInput(gfx::AcceleratedWidget widget,
                           const WasmTextInputRecord& record);
void CancelWasmTextInputForWidget(gfx::AcceleratedWidget widget);

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_WASM_WASM_INPUT_METHOD_H_

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_input_method.h"

#include "base/logging.h"
#include "ui/base/ime/text_input_client.h"
#include "ui/base/ime/text_input_type.h"

extern "C" int chromium_wasm_report_ozone_text_input_state(
    int focused_client_present,
    int editable,
    int can_compose_inline);

namespace ui {

WasmInputMethod::WasmInputMethod(
    ImeKeyEventDispatcher* ime_key_event_dispatcher)
    : InputMethodMinimal(ime_key_event_dispatcher) {
  // Establish an explicit initial state. The host bridge queues this report
  // until its one owning host instance has finished initialization.
  ReportTextInputState();
}

WasmInputMethod::~WasmInputMethod() = default;

void WasmInputMethod::OnTextInputTypeChanged(TextInputClient* client) {
  InputMethodMinimal::OnTextInputTypeChanged(client);
  ReportTextInputState();
}

void WasmInputMethod::OnDidChangeFocusedClient(
    TextInputClient* /*focused_before*/,
    TextInputClient* /*focused*/) {
  // InputMethodBase has already installed |focused| when this hook runs. Do
  // not use the callback arguments as authoritative state: focus callbacks can
  // synchronously reenter and alter the client again.
  ReportTextInputState();
}

void WasmInputMethod::ReportTextInputState() {
  TextInputClient* client = GetTextInputClient();
  const bool focused_client_present = client != nullptr;
  const bool editable =
      focused_client_present && GetTextInputType() != TEXT_INPUT_TYPE_NONE;
  const bool can_compose_inline = editable && client->CanComposeInline();
  const int result = chromium_wasm_report_ozone_text_input_state(
      focused_client_present ? 1 : 0, editable ? 1 : 0,
      can_compose_inline ? 1 : 0);
  if (result != 1) {
    LOG(ERROR) << "host rejected ozone_wasm text-input state report";
  }
}

}  // namespace ui

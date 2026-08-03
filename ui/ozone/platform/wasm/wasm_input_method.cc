// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/wasm_input_method.h"

#include "base/check.h"
#include "base/containers/flat_map.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/threading/thread_checker.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/base/ime/composition_text.h"
#include "ui/base/ime/ime_text_span.h"
#include "ui/base/ime/text_input_client.h"
#include "ui/base/ime/text_input_type.h"
#include "ui/ozone/platform/wasm/wasm_window_manager.h"

extern "C" int chromium_wasm_report_ozone_text_input_state(
    int focused_client_present,
    int editable,
    int can_compose_inline);

namespace ui {

namespace {

using InputMethodMap =
    base::flat_map<gfx::AcceleratedWidget, raw_ptr<WasmInputMethod>>;

InputMethodMap& GetInputMethods() {
  static base::NoDestructor<InputMethodMap> input_methods;
  return *input_methods;
}

base::ThreadChecker& GetInputMethodThreadChecker() {
  static base::NoDestructor<base::ThreadChecker> thread_checker;
  return *thread_checker;
}

}  // namespace

WasmInputMethod::WasmInputMethod(
    ImeKeyEventDispatcher* ime_key_event_dispatcher,
    gfx::AcceleratedWidget widget,
    WasmWindowManager* window_manager)
    : InputMethodMinimal(ime_key_event_dispatcher),
      widget_(widget),
      window_manager_(window_manager) {
  DCHECK(GetInputMethodThreadChecker().CalledOnValidThread());
  CHECK_NE(widget_, gfx::kNullAcceleratedWidget);
  CHECK(window_manager_);
  const bool inserted = GetInputMethods().emplace(widget_, this).second;
  CHECK(inserted);
  // Establish an explicit initial state. The host bridge queues this report
  // until its one owning host instance has finished initialization.
  ReportTextInputState();
}

WasmInputMethod::~WasmInputMethod() {
  DCHECK(GetInputMethodThreadChecker().CalledOnValidThread());
  CancelHostComposition();
  auto input_method = GetInputMethods().find(widget_);
  CHECK(input_method != GetInputMethods().end());
  CHECK_EQ(input_method->second, this);
  GetInputMethods().erase(input_method);
}

void WasmInputMethod::OnTextInputTypeChanged(TextInputClient* client) {
  InputMethodMinimal::OnTextInputTypeChanged(client);
  TextInputClient* focused_client = GetTextInputClient();
  if (active_composition_ && !CanDispatchTextInput(focused_client)) {
    ClearActiveComposition(focused_client);
  }
  ReportTextInputState();
}

void WasmInputMethod::CancelComposition(const TextInputClient* client) {
  if (client != GetTextInputClient()) {
    return;
  }
  ClearActiveComposition(GetTextInputClient());
}

bool WasmInputMethod::DispatchTextInput(const WasmTextInputRecord& record) {
  DCHECK(GetInputMethodThreadChecker().CalledOnValidThread());
  if (record.sequence == 0 || record.sequence <= last_sequence_ ||
      !window_manager_->IsKeyboardFocusedWidget(widget_)) {
    return false;
  }

  TextInputClient* client = GetTextInputClient();
  if (!CanDispatchTextInput(client)) {
    return false;
  }

  switch (record.action) {
    case WasmTextInputAction::kSetComposition: {
      // A new host session cannot replace an unconfirmed composition owned by
      // another session or focused client.
      if (record.text.empty() || !record.selection.IsValid() ||
          record.selection.start() != record.selection.end() ||
          record.selection.end() != record.text.size() ||
          (active_composition_ &&
           (active_composition_->session_id != record.session_id ||
            active_composition_->client.get() != client))) {
        return false;
      }
      CompositionText composition;
      composition.text = record.text;
      composition.selection = record.selection;
      composition.ime_text_spans.emplace_back(
          ImeTextSpan::Type::kComposition, /*start_offset=*/0,
          record.text.size(), ImeTextSpan::Thickness::kThin,
          ImeTextSpan::UnderlineStyle::kSolid, SK_ColorTRANSPARENT);
      last_sequence_ = record.sequence;
      active_composition_ =
          ActiveComposition{record.session_id, client->AsWeakPtr()};
      // SetCompositionText can synchronously change focus. Never use |client|
      // after this call; active_composition_ carries only a weak reference.
      client->SetCompositionText(composition);
      return true;
    }
    case WasmTextInputAction::kConfirmComposition:
      if (!record.text.empty() || !record.selection.IsValid() ||
          !record.selection.is_empty() || !active_composition_ ||
          active_composition_->session_id != record.session_id ||
          active_composition_->client.get() != client) {
        return false;
      }
      last_sequence_ = record.sequence;
      active_composition_.reset();
      // ConfirmCompositionText finalizes the existing renderer composition;
      // it must not be replaced with InsertText, which would duplicate text.
      client->ConfirmCompositionText(/*keep_selection=*/false);
      return true;
    case WasmTextInputAction::kClearComposition:
      if (!record.text.empty() || !record.selection.IsValid() ||
          !record.selection.is_empty() || !active_composition_ ||
          active_composition_->session_id != record.session_id ||
          active_composition_->client.get() != client) {
        return false;
      }
      last_sequence_ = record.sequence;
      active_composition_.reset();
      client->ClearCompositionText();
      return true;
  }
  NOTREACHED();
}

void WasmInputMethod::CancelHostComposition() {
  DCHECK(GetInputMethodThreadChecker().CalledOnValidThread());
  TextInputClient* client = GetTextInputClient();
  ClearActiveComposition(client);
}

void WasmInputMethod::OnWillChangeFocusedClient(
    TextInputClient* focused_before,
    TextInputClient* /*focused*/) {
  ClearActiveComposition(focused_before);
}

void WasmInputMethod::OnDidChangeFocusedClient(
    TextInputClient* /*focused_before*/,
    TextInputClient* /*focused*/) {
  // InputMethodBase has already installed |focused| when this hook runs. Do
  // not use the callback arguments as authoritative state: focus callbacks can
  // synchronously reenter and alter the client again.
  ReportTextInputState();
}

bool WasmInputMethod::CanDispatchTextInput(TextInputClient* client) const {
  return client && GetTextInputType() != TEXT_INPUT_TYPE_NONE &&
         client->CanComposeInline();
}

void WasmInputMethod::ClearActiveComposition(TextInputClient* client) {
  if (!active_composition_) {
    return;
  }
  base::WeakPtr<TextInputClient> active_client = active_composition_->client;
  active_composition_.reset();
  if (client && active_client.get() == client) {
    // Clear the bookkeeping before this reentrant client call. The weak
    // pointer prevents retaining a stale client across a focus transition.
    active_client->ClearCompositionText();
  }
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

bool DispatchWasmTextInput(gfx::AcceleratedWidget widget,
                           const WasmTextInputRecord& record) {
  DCHECK(GetInputMethodThreadChecker().CalledOnValidThread());
  auto input_method = GetInputMethods().find(widget);
  return input_method != GetInputMethods().end() &&
         input_method->second->DispatchTextInput(record);
}

void CancelWasmTextInputForWidget(gfx::AcceleratedWidget widget) {
  DCHECK(GetInputMethodThreadChecker().CalledOnValidThread());
  auto input_method = GetInputMethods().find(widget);
  if (input_method != GetInputMethods().end()) {
    input_method->second->CancelHostComposition();
  }
}

}  // namespace ui

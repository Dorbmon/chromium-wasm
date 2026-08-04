// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_SHELL_BROWSER_SHELL_TOOLTIP_WASM_H_
#define CONTENT_SHELL_BROWSER_SHELL_TOOLTIP_WASM_H_

#include <memory>

namespace aura {
class Window;
}

namespace content {

class WasmTooltipController;

struct WasmTooltipControllerDeleter {
  void operator()(WasmTooltipController* controller) const;
};

using WasmTooltipControllerPtr =
    std::unique_ptr<WasmTooltipController, WasmTooltipControllerDeleter>;

// Creates the bounded first Wasm implementation of the root TooltipClient.
// It renders a non-interactive Aura child in the existing compositor root;
// it never creates a second PlatformWindow or a host-page overlay.
WasmTooltipControllerPtr CreateWasmTooltipController(
    aura::Window* root_window);

}  // namespace content

#endif  // CONTENT_SHELL_BROWSER_SHELL_TOOLTIP_WASM_H_

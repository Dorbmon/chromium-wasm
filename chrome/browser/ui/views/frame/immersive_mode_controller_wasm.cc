// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/views/frame/immersive_mode_controller.h"

#include <memory>

#include "base/check.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "immersive_mode_controller_wasm.cc must only be built for WebAssembly"
#endif

namespace {

class WasmImmersiveRevealedLock final : public ImmersiveRevealedLock {};

class WasmImmersiveModeController final : public ImmersiveModeController {
 public:
  explicit WasmImmersiveModeController(ui::UnownedUserDataHost& host)
      : ImmersiveModeController(host) {}
  ~WasmImmersiveModeController() override = default;

  void Init(BrowserView*) override {}

  void SetEnabled(bool enabled) override {
    // A true request would need a host-backed immersive fullscreen policy.
    CHECK(!enabled);
  }

  bool IsEnabled() const override { return false; }

  bool IsRevealed() const override { return false; }

  int GetTopContainerVerticalOffset(const gfx::Size&) const override {
    return 0;
  }

  std::unique_ptr<ImmersiveRevealedLock> GetRevealedLock(
      AnimateReveal) override {
    // The generic API requires a valid lock even when immersive mode is off.
    return std::make_unique<WasmImmersiveRevealedLock>();
  }

  void OnFindBarVisibleBoundsChanged(const gfx::Rect&) override {}

  bool ShouldStayImmersiveAfterExitingFullscreen() override { return false; }

  int GetMinimumContentOffset() const override { return 0; }

  int GetExtraInfobarOffset() const override { return 0; }

  void OnContentFullscreenChanged(bool) override {}
};

}  // namespace

namespace chrome {

std::unique_ptr<ImmersiveModeController> CreateImmersiveModeController(
    WindowFeatureController*,
    ui::UnownedUserDataHost& host) {
  return std::make_unique<WasmImmersiveModeController>(host);
}

}  // namespace chrome

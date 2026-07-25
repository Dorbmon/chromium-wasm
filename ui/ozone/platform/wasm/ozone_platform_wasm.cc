// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/ozone/platform/wasm/ozone_platform_wasm.h"

#include <memory>

#include "base/check.h"
#include "base/logging.h"
#include "ui/base/cursor/cursor_factory.h"
#include "ui/base/ime/input_method_minimal.h"
#include "ui/display/types/native_display_delegate.h"
#include "ui/events/ozone/layout/keyboard_layout_engine_manager.h"
#include "ui/events/ozone/layout/stub/stub_keyboard_layout_engine.h"
#include "ui/events/platform/platform_event_source.h"
#include "ui/ozone/common/bitmap_cursor_factory.h"
#include "ui/ozone/common/stub_client_native_pixmap_factory.h"
#include "ui/ozone/common/stub_overlay_manager.h"
#include "ui/ozone/platform/wasm/wasm_screen.h"
#include "ui/ozone/platform/wasm/wasm_surface_factory.h"
#include "ui/ozone/platform/wasm/wasm_window.h"
#include "ui/ozone/platform/wasm/wasm_window_manager.h"
#include "ui/ozone/public/gpu_platform_support_host.h"
#include "ui/ozone/public/input_controller.h"
#include "ui/ozone/public/ozone_platform.h"
#include "ui/ozone/public/stub_input_controller.h"
#include "ui/ozone/public/system_input_injector.h"
#include "ui/platform_window/platform_window_init_properties.h"

namespace ui {

namespace {

// M3 has no host input path yet, but Aura requires a platform event source
// while bootstrapping. Input becomes an actual event source at the M4 gate.
class WasmBootstrapPlatformEventSource final : public PlatformEventSource {
 public:
  WasmBootstrapPlatformEventSource() = default;

  WasmBootstrapPlatformEventSource(
      const WasmBootstrapPlatformEventSource&) = delete;
  WasmBootstrapPlatformEventSource& operator=(
      const WasmBootstrapPlatformEventSource&) = delete;

  ~WasmBootstrapPlatformEventSource() override = default;
};

class OzonePlatformWasmImpl final : public OzonePlatform {
 public:
  OzonePlatformWasmImpl() {
    platform_properties_.platform_shows_drag_image = false;
    runtime_properties_.supports_overlays = false;
    runtime_properties_.supports_server_side_window_decorations = false;
    runtime_properties_.supports_native_pixmaps = false;
  }

  OzonePlatformWasmImpl(const OzonePlatformWasmImpl&) = delete;
  OzonePlatformWasmImpl& operator=(const OzonePlatformWasmImpl&) = delete;

  ~OzonePlatformWasmImpl() override = default;

  SurfaceFactoryOzone* GetSurfaceFactoryOzone() override {
    return surface_factory_.get();
  }

  OverlayManagerOzone* GetOverlayManager() override {
    return overlay_manager_.get();
  }

  CursorFactory* GetCursorFactory() override {
    return cursor_factory_.get();
  }

  InputController* GetInputController() override {
    return input_controller_.get();
  }

  GpuPlatformSupportHost* GetGpuPlatformSupportHost() override {
    return gpu_platform_support_host_.get();
  }

  std::unique_ptr<SystemInputInjector> CreateSystemInputInjector() override {
    return nullptr;
  }

  std::unique_ptr<PlatformWindow> CreatePlatformWindow(
      PlatformWindowDelegate* delegate,
      PlatformWindowInitProperties properties) override {
    CHECK(window_manager_);
    // Reuse only Chromium's bootstrap window bookkeeping. Presentation is
    // supplied by WasmSurfaceFactory, and M4 replaces this with interactive
    // host-event handling.
    return std::make_unique<WasmWindow>(
        delegate, window_manager_.get(), properties.bounds);
  }

  std::unique_ptr<display::NativeDisplayDelegate>
  CreateNativeDisplayDelegate() override {
    return nullptr;
  }

  std::unique_ptr<PlatformScreen> CreateScreen() override {
    CHECK(window_manager_);
    return std::make_unique<WasmScreen>(window_manager_.get());
  }

  void InitScreen(PlatformScreen* screen) override {
    CHECK(screen);
  }

  std::unique_ptr<InputMethod> CreateInputMethod(
      ImeKeyEventDispatcher* ime_key_event_dispatcher,
      gfx::AcceleratedWidget widget) override {
    return std::make_unique<InputMethodMinimal>(ime_key_event_dispatcher);
  }

  bool IsWindowCompositingSupported() const override {
    return true;
  }

  const PlatformProperties& GetPlatformProperties() override {
    return platform_properties_;
  }

  const PlatformRuntimeProperties& GetPlatformRuntimeProperties() override {
    return runtime_properties_;
  }

 private:
  bool InitializeUI(const InitParams& params) override {
    if (!params.single_process) {
      LOG(ERROR) << "ozone_wasm M3 requires in-process browser and GPU "
                    "services";
      return false;
    }

    if (!window_manager_) {
      window_manager_ = std::make_unique<WasmWindowManager>();
    }
    if (!surface_factory_) {
      surface_factory_ = std::make_unique<WasmSurfaceFactory>();
    }
    if (!PlatformEventSource::GetInstance()) {
      platform_event_source_ =
          std::make_unique<WasmBootstrapPlatformEventSource>();
    }

    keyboard_layout_engine_ = std::make_unique<StubKeyboardLayoutEngine>();
    KeyboardLayoutEngineManager::SetKeyboardLayoutEngine(
        keyboard_layout_engine_.get());
    overlay_manager_ = std::make_unique<StubOverlayManager>();
    input_controller_ = std::make_unique<StubInputController>();
    cursor_factory_ = std::make_unique<BitmapCursorFactory>();
    gpu_platform_support_host_.reset(CreateStubGpuPlatformSupportHost());
    return true;
  }

  void InitializeGPU(const InitParams& params) override {
    CHECK(params.single_process)
        << "ozone_wasm has no cross-process GPU transport";
    if (!surface_factory_) {
      surface_factory_ = std::make_unique<WasmSurfaceFactory>();
    }
  }

  PlatformProperties platform_properties_;
  PlatformRuntimeProperties runtime_properties_;
  std::unique_ptr<KeyboardLayoutEngine> keyboard_layout_engine_;
  std::unique_ptr<WasmWindowManager> window_manager_;
  std::unique_ptr<WasmSurfaceFactory> surface_factory_;
  std::unique_ptr<PlatformEventSource> platform_event_source_;
  std::unique_ptr<CursorFactory> cursor_factory_;
  std::unique_ptr<InputController> input_controller_;
  std::unique_ptr<GpuPlatformSupportHost> gpu_platform_support_host_;
  std::unique_ptr<OverlayManagerOzone> overlay_manager_;
};

}  // namespace

OzonePlatform* CreateOzonePlatformWasm() {
  return new OzonePlatformWasmImpl();
}

gfx::ClientNativePixmapFactory* CreateClientNativePixmapFactoryWasm() {
  return CreateStubClientNativePixmapFactory();
}

}  // namespace ui

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_chrome_main_delegate.h"

#include <iterator>
#include <memory>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/command_line.h"
#include "base/logging.h"
#include "base/logging/logging_settings.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_chrome_content_client.h"
#include "chrome/browser/wasm/wasm_content_browser_client.h"
#include "chrome/common/chrome_paths.h"
#include "chrome/common/chrome_result_codes.h"
#include "components/content_settings/core/common/content_settings_pattern.h"
#include "components/memory_system/initializer.h"
#include "components/memory_system/memory_system.h"
#include "components/memory_system/parameters.h"
#include "components/network_session_configurator/common/network_switches.h"
#include "content/public/common/content_switches.h"
#include "content/public/common/url_constants.h"
#include "ui/base/ui_base_switches.h"
#include "ui/gl/gl_switches.h"
#include "ui/ozone/public/ozone_platform.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_chrome_main_delegate.cc must only be built for WebAssembly"
#endif

class WasmChromeMainDelegate::State {
 public:
  State() = default;
  State(const State&) = delete;
  State& operator=(const State&) = delete;
  ~State() = default;

  WasmChromeContentClient content_client;
  std::unique_ptr<WasmContentBrowserClient> browser_client;
  memory_system::MemorySystem memory_system;
};

WasmChromeMainDelegate::WasmChromeMainDelegate()
    : state_(std::make_unique<State>()) {}

WasmChromeMainDelegate::~WasmChromeMainDelegate() = default;

std::optional<int> WasmChromeMainDelegate::BasicStartupComplete() {
  base::CommandLine& command_line = *base::CommandLine::ForCurrentProcess();
  if (command_line.HasSwitch(switches::kProcessType)) {
    LOG(ERROR) << "chrome_wasm only supports the browser process; --type="
               << command_line.GetSwitchValueASCII(switches::kProcessType)
               << " is unsupported";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }

  // No process boundary exists inside a Wasm module. Keep renderer execution
  // in-process and disable transport/graphics paths without a Wasm backend.
  if (!command_line.HasSwitch(switches::kSingleProcess)) {
    command_line.AppendSwitch(switches::kSingleProcess);
  }
  command_line.RemoveSwitch(switches::kDisableGpu);
  if (!command_line.HasSwitch(switches::kDisableGpuCompositing)) {
    command_line.AppendSwitch(switches::kDisableGpuCompositing);
  }
  if (!command_line.HasSwitch(switches::kUseGL)) {
    command_line.AppendSwitchASCII(switches::kUseGL,
                                   gl::kGLImplementationDisabledName);
  }
  if (!command_line.HasSwitch(switches::kDisableQuic)) {
    command_line.AppendSwitch(switches::kDisableQuic);
  }
  if (!command_line.HasSwitch(switches::kEnableLogging)) {
    command_line.AppendSwitchASCII(switches::kEnableLogging, "stderr");
  }
  if (!command_line.HasSwitch(switches::kLang)) {
    command_line.AppendSwitchASCII(switches::kLang, "en-US");
  }

  chrome::RegisterPathProvider();
  constexpr const char* kContentSettingsSchemes[] = {
      content::kChromeDevToolsScheme,
      content::kChromeUIScheme,
      content::kChromeUIUntrustedScheme,
  };
  ContentSettingsPattern::SetNonWildcardDomainNonPortSchemes(
      kContentSettingsSchemes, std::size(kContentSettingsSchemes));
  return std::nullopt;
}

void WasmChromeMainDelegate::PreSandboxStartup() {
  logging::LoggingSettings settings{.logging_dest =
                                        logging::LOG_TO_STDERR |
                                        logging::LOG_TO_SYSTEM_DEBUG_LOG};
  CHECK(logging::InitLogging(settings));
  logging::SetLogItems(/*enable_process_id=*/true, /*enable_thread_id=*/true,
                       /*enable_timestamp=*/true, /*enable_tickcount=*/false);

  // Ozone is the platform boundary. Its Wasm implementation owns host canvas
  // setup and does not let Views/Aura call DOM APIs directly.
  ui::OzonePlatform::PreSandboxStartup();
}

std::optional<int> WasmChromeMainDelegate::PostEarlyInitialization(
    InvokedIn invoked_in) {
  if (std::optional<int> exit_code =
          content::ContentMainDelegate::PostEarlyInitialization(invoked_in);
      exit_code.has_value()) {
    return exit_code;
  }

  const std::string process_type =
      base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII(
          switches::kProcessType);
  memory_system::Initializer()
      .SetDispatcherParameters(memory_system::DispatcherParameters::
                                   PoissonAllocationSamplerInclusion::kEnforce,
                               memory_system::DispatcherParameters::
                                   AllocationTraceRecorderInclusion::kIgnore,
                               process_type)
      .Initialize(state_->memory_system);
  return std::nullopt;
}

content::ContentClient* WasmChromeMainDelegate::CreateContentClient() {
  return &state_->content_client;
}

content::ContentBrowserClient*
WasmChromeMainDelegate::CreateContentBrowserClient() {
  CHECK(!state_->browser_client);
  state_->browser_client = std::make_unique<WasmContentBrowserClient>();
  return state_->browser_client.get();
}

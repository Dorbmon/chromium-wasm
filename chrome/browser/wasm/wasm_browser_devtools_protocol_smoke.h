// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_BROWSER_DEVTOOLS_PROTOCOL_SMOKE_H_
#define CHROME_BROWSER_WASM_WASM_BROWSER_DEVTOOLS_PROTOCOL_SMOKE_H_

#include <string_view>

#include "base/containers/span.h"
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/scoped_refptr.h"
#include "base/values.h"
#include "content/public/browser/devtools_agent_host_client.h"
#include "url/gurl.h"

namespace content {
class DevToolsAgentHost;
class RenderFrameHost;
class WebContents;
}  // namespace content

namespace chrome {

// A switch-gated, direct DevToolsAgentHost client used only to prove that the
// active Wasm Browser tab can accept three fixed protocol requests:
// Network.enable, Runtime.enable, and one literal Runtime.evaluate expression.
// It also accepts one exact console event produced by that expression. This is
// deliberately not a DevTools frontend or a protocol transport: it accepts
// only those fixed successful responses and the one event and forwards no
// protocol traffic to JavaScript or another process. The expression exercises
// ordinary page JavaScript and verifies that |typeof WebAssembly| is
// "undefined" in this disabled configuration; it does not construct, compile,
// or otherwise exercise page WebAssembly.
class WasmBrowserDevToolsProtocolSmoke final
    : public content::DevToolsAgentHostClient {
 public:
  explicit WasmBrowserDevToolsProtocolSmoke(base::OnceClosure success_callback);
  WasmBrowserDevToolsProtocolSmoke(const WasmBrowserDevToolsProtocolSmoke&) =
      delete;
  WasmBrowserDevToolsProtocolSmoke& operator=(
      const WasmBrowserDevToolsProtocolSmoke&) = delete;
  ~WasmBrowserDevToolsProtocolSmoke() override;

  // Attaches only when |web_contents|' current primary main frame has committed
  // the fixed DevTools smoke data URL, sends the literal Network.enable,
  // Runtime.enable, and Runtime.evaluate commands, and runs |success_callback|
  // only after receiving the matching console event and detaching from the
  // agent host.
  void Start(content::WebContents* web_contents);

  bool IsDetached() const;

 private:
  enum class State {
    kCreated,
    kEnablingNetwork,
    kEnablingRuntime,
    kEvaluatingRuntime,
    kDetached,
    kFailed,
  };

  // content::DevToolsAgentHostClient:
  void DispatchProtocolMessage(content::DevToolsAgentHost* agent_host,
                               base::span<const uint8_t> message) override;
  void AgentHostClosed(content::DevToolsAgentHost* agent_host) override;
  bool MayAttachToURL(const GURL& url, bool is_webui) override;
  bool MayAttachToRenderFrameHost(
      content::RenderFrameHost* render_frame_host) override;
  bool IsTrusted() override;
  bool MayAccessAllCookies() override;
  bool MayReadLocalFiles() override;
  bool MayWriteLocalFiles() override;
  bool AllowUnsafeOperations() override;

  void CompleteNetworkEnable();
  void CompleteRuntimeEnable();
  void CompleteRuntimeConsoleApiCalled(const base::DictValue& notification);
  void CompleteRuntimeEvaluate();
  [[noreturn]] void Fail(std::string_view reason);
  void Detach();

  State state_ = State::kCreated;
  scoped_refptr<content::DevToolsAgentHost> agent_host_;
  raw_ptr<content::RenderFrameHost> primary_main_frame_ = nullptr;
  GURL permitted_url_;
  bool runtime_evaluate_response_received_ = false;
  bool runtime_console_api_called_received_ = false;
  base::OnceClosure success_callback_;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_DEVTOOLS_PROTOCOL_SMOKE_H_

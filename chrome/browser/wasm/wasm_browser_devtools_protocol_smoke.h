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
#include "content/public/browser/devtools_agent_host_client.h"
#include "url/gurl.h"

namespace content {
class DevToolsAgentHost;
class RenderFrameHost;
class WebContents;
}  // namespace content

namespace chrome {

// A switch-gated, direct DevToolsAgentHost client used only to prove that the
// active Wasm Browser tab can accept one fixed Network.enable request. It is
// deliberately not a DevTools frontend or a protocol transport: it emits one
// literal request, accepts only its fixed successful response, and forwards no
// protocol traffic to JavaScript or another process.
class WasmBrowserDevToolsProtocolSmoke final
    : public content::DevToolsAgentHostClient {
 public:
  explicit WasmBrowserDevToolsProtocolSmoke(base::OnceClosure success_callback);
  WasmBrowserDevToolsProtocolSmoke(const WasmBrowserDevToolsProtocolSmoke&) =
      delete;
  WasmBrowserDevToolsProtocolSmoke& operator=(
      const WasmBrowserDevToolsProtocolSmoke&) = delete;
  ~WasmBrowserDevToolsProtocolSmoke() override;

  // Attaches only to |web_contents|' current primary main frame, sends the
  // literal Network.enable command, and runs |success_callback| only after
  // detaching from the agent host.
  void Start(content::WebContents* web_contents);

  bool IsDetached() const;

 private:
  enum class State {
    kCreated,
    kEnabling,
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
  [[noreturn]] void Fail(std::string_view reason);
  void Detach();

  State state_ = State::kCreated;
  scoped_refptr<content::DevToolsAgentHost> agent_host_;
  raw_ptr<content::RenderFrameHost> primary_main_frame_ = nullptr;
  GURL permitted_url_;
  base::OnceClosure success_callback_;
};

}  // namespace chrome

#endif  // CHROME_BROWSER_WASM_WASM_BROWSER_DEVTOOLS_PROTOCOL_SMOKE_H_

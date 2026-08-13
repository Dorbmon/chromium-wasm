// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"

#include <cstdio>
#include <optional>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/json/json_reader.h"
#include "base/values.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/devtools_agent_host.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_devtools_protocol_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kNetworkEnableCommand[] =
    R"({"id":1,"method":"Network.enable"})";
constexpr char kRuntimeEvaluateCommand[] =
    R"json({"id":2,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("String(6 * 7)","returnByValue":true,"silent":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kFixedDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20DevTools%20smoke";
constexpr char kNetworkEnableSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:NETWORK_ENABLE_OK";
constexpr char kRuntimeEvaluateSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_EVALUATE_OK";
constexpr char kDetachedMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DETACHED";
constexpr char kFailureMarker[] = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:FAIL";
constexpr int kNetworkEnableCommandId = 1;
constexpr int kRuntimeEvaluateCommandId = 2;
constexpr size_t kMaximumProtocolResponseBytes = 1024;
constexpr char kRuntimeEvaluateExpectedType[] = "string";
constexpr char kRuntimeEvaluateExpectedValue[] = "42";

}  // namespace

WasmBrowserDevToolsProtocolSmoke::WasmBrowserDevToolsProtocolSmoke(
    base::OnceClosure success_callback)
    : success_callback_(std::move(success_callback)) {
  CHECK(success_callback_);
}

WasmBrowserDevToolsProtocolSmoke::~WasmBrowserDevToolsProtocolSmoke() {
  Detach();
}

void WasmBrowserDevToolsProtocolSmoke::Start(
    content::WebContents* web_contents) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(web_contents);
  CHECK_EQ(state_, State::kCreated);
  CHECK(!agent_host_);
  CHECK(!primary_main_frame_);
  CHECK(!permitted_url_.is_valid());

  const GURL expected_url(kFixedDevToolsProtocolSmokeUrl);
  CHECK(expected_url.is_valid());
  CHECK_EQ(web_contents->GetLastCommittedURL(), expected_url);

  primary_main_frame_ = web_contents->GetPrimaryMainFrame();
  CHECK(primary_main_frame_);
  CHECK_EQ(primary_main_frame_->GetLastCommittedURL(), expected_url);
  permitted_url_ = expected_url;

  agent_host_ = content::DevToolsAgentHost::GetOrCreateFor(web_contents);
  if (!agent_host_) {
    Fail("could not create the active tab's DevTools agent host");
  }
  if (!agent_host_->AttachClient(this)) {
    agent_host_ = nullptr;
    Fail("could not attach the fixed protocol client");
  }

  state_ = State::kEnablingNetwork;
  // These two literal commands are the only protocol messages this client can
  // emit. There is no frontend, pipe, socket, host ABI, or caller-provided
  // command surface. Runtime.evaluate runs one ordinary JavaScript expression
  // only; it is not a page WebAssembly probe or enablement path.
  agent_host_->DispatchProtocolMessage(
      this, base::byte_span_from_cstring(kNetworkEnableCommand));
}

bool WasmBrowserDevToolsProtocolSmoke::IsDetached() const {
  return state_ == State::kDetached && !agent_host_;
}

void WasmBrowserDevToolsProtocolSmoke::DispatchProtocolMessage(
    content::DevToolsAgentHost* agent_host,
    base::span<const uint8_t> message) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if ((state_ != State::kEnablingNetwork &&
       state_ != State::kEvaluatingRuntime) ||
      agent_host != agent_host_.get()) {
    return;
  }
  if (message.size() > kMaximumProtocolResponseBytes) {
    Fail("fixed DevTools protocol response exceeded its bound");
  }

  const std::string_view message_text(
      reinterpret_cast<const char*>(message.data()), message.size());
  std::optional<base::Value> value =
      base::JSONReader::Read(message_text, base::JSON_PARSE_RFC);
  if (!value || !value->is_dict()) {
    // Network events are not part of this smoke. Ignore any frame that cannot
    // be the one fixed command response rather than becoming a generic
    // protocol consumer.
    return;
  }

  const base::DictValue& response = value->GetDict();
  const std::optional<int> id = response.FindInt("id");
  if (!id) {
    return;
  }

  if (state_ == State::kEnablingNetwork) {
    if (*id != kNetworkEnableCommandId) {
      return;
    }
    const base::DictValue* result = response.FindDict("result");
    if (response.Find("error") || !result || !result->empty()) {
      Fail("Network.enable did not return its fixed empty result");
    }
    CompleteNetworkEnable();
    return;
  }

  CHECK_EQ(state_, State::kEvaluatingRuntime);
  if (*id != kRuntimeEvaluateCommandId) {
    return;
  }
  const base::DictValue* result = response.FindDict("result");
  if (response.Find("error") || !result || result->Find("exceptionDetails")) {
    Fail("Runtime.evaluate did not return a fixed ordinary-JavaScript result");
  }
  const base::DictValue* remote_result = result->FindDict("result");
  const std::string* result_type =
      remote_result ? remote_result->FindString("type") : nullptr;
  const std::string* result_value =
      remote_result ? remote_result->FindString("value") : nullptr;
  if (!result_type || *result_type != kRuntimeEvaluateExpectedType ||
      !result_value || *result_value != kRuntimeEvaluateExpectedValue) {
    Fail("Runtime.evaluate did not return the fixed string result");
  }
  CompleteRuntimeEvaluate();
}

void WasmBrowserDevToolsProtocolSmoke::AgentHostClosed(
    content::DevToolsAgentHost* agent_host) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (agent_host != agent_host_.get()) {
    return;
  }
  agent_host_ = nullptr;
  if (state_ != State::kDetached) {
    Fail("active tab DevTools agent host closed before detaching");
  }
}

bool WasmBrowserDevToolsProtocolSmoke::MayAttachToURL(const GURL& url,
                                                      bool is_webui) {
  // This client is authorized only for the fixed, lifecycle-owned primary
  // document selected at Start(). Attachment is separately constrained to
  // |primary_main_frame_|. Any navigation request therefore forces a detach
  // rather than widening this test-only authority.
  return !is_webui && permitted_url_.is_valid() && url == permitted_url_;
}

bool WasmBrowserDevToolsProtocolSmoke::MayAttachToRenderFrameHost(
    content::RenderFrameHost* render_frame_host) {
  return render_frame_host == primary_main_frame_;
}

bool WasmBrowserDevToolsProtocolSmoke::IsTrusted() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::MayAccessAllCookies() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::MayReadLocalFiles() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::MayWriteLocalFiles() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::AllowUnsafeOperations() {
  return false;
}

void WasmBrowserDevToolsProtocolSmoke::CompleteNetworkEnable() {
  CHECK_EQ(state_, State::kEnablingNetwork);
  CHECK(agent_host_);

  // Advance before dispatch because a DevTools agent may synchronously deliver
  // the fixed Runtime.evaluate response while handling this call.
  state_ = State::kEvaluatingRuntime;
  std::fprintf(stderr, "%s\n", kNetworkEnableSuccessMarker);
  std::fflush(stderr);
  agent_host_->DispatchProtocolMessage(
      this, base::byte_span_from_cstring(kRuntimeEvaluateCommand));
}

void WasmBrowserDevToolsProtocolSmoke::CompleteRuntimeEvaluate() {
  CHECK_EQ(state_, State::kEvaluatingRuntime);
  CHECK(success_callback_);

  // Keep both fixed response witnesses before detachment, then make
  // detachment an independently observable barrier before the lifecycle is
  // allowed to close its Browser and destroy the sole WebContents.
  std::fprintf(stderr, "%s\n", kRuntimeEvaluateSuccessMarker);
  std::fflush(stderr);
  Detach();
  state_ = State::kDetached;
  CHECK(IsDetached());
  std::fprintf(stderr, "%s\n", kDetachedMarker);
  std::fflush(stderr);

  // The lifecycle owns this object until its Browser close observer clears
  // it, so running this callback cannot destroy |this| while this method is
  // still active.
  std::move(success_callback_).Run();
}

[[noreturn]] void WasmBrowserDevToolsProtocolSmoke::Fail(
    std::string_view reason) {
  state_ = State::kFailed;
  Detach();
  std::fprintf(stderr, "%s reason=%.*s\n", kFailureMarker,
               static_cast<int>(reason.size()), reason.data());
  std::fflush(stderr);
  CHECK(false) << "Wasm DevTools protocol smoke failed: " << reason;
}

void WasmBrowserDevToolsProtocolSmoke::Detach() {
  if (!agent_host_) {
    return;
  }
  scoped_refptr<content::DevToolsAgentHost> agent_host =
      std::move(agent_host_);
  CHECK(agent_host->DetachClient(this));
}

}  // namespace chrome

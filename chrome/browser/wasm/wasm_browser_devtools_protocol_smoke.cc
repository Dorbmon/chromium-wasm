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
constexpr char kRuntimeEnableCommand[] =
    R"({"id":2,"method":"Runtime.enable"})";
constexpr char kRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(console.log('chromium-wasm-m8-devtools-console'),)json"
    R"json( typeof WebAssembly)","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,7,1,96,2,127,127,1,127,3,2,1,0,7,7,1,3,97,)json"
    R"json(100,100,0,0,10,9,1,7,0,32,0,32,1,106,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm validation failed');)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m);)json"
    R"json(const r=i.exports.add(20,22);if(r!==42)throw new Error('wasm add result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-add-42');)json"
    R"json(return 'wasm-add-42';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyMemoryRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,11,2,96,1,127,1,127,96,2,127,127,0,2,16,1,3,101,110,118,6,109,101,109,111,114,121,2,1,1,1,)json"
    R"json(3,3,2,0,1,7,16,2,4,114,101,97,100,0,0,5,119,114,105,116,101,0,1,10,19,2,7,0,32,0,40,2,0,11,9,0,32,0,32,1,54,2,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm memory validation failed');)json"
    R"json(const memory=new WebAssembly.Memory({initial:1,maximum:1});)json"
    R"json(if(memory.buffer.byteLength!==65536)throw new Error('wasm memory initial size was not 65536');)json"
    R"json(const view=new DataView(memory.buffer);view.setUint32(0,0x12345678,true);)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{memory}});)json"
    R"json(if(i.exports.read(0)!==0x12345678)throw new Error('wasm memory did not read JS write');)json"
    R"json(i.exports.write(4,0x0badf00d);)json"
    R"json(if(view.getUint32(4,true)!==0x0badf00d)throw new Error('JS did not read wasm memory write');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-memory-import-read-write');)json"
    R"json(return 'wasm-memory-import-read-write';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kFixedDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20DevTools%20smoke";
constexpr char kFixedPageWebAssemblyDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20smoke";
constexpr char kFixedPageWebAssemblyMemoryDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20memory%20smoke";
constexpr char kNetworkEnableSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:NETWORK_ENABLE_OK";
constexpr char kRuntimeEnableSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_ENABLE_OK";
constexpr char kRuntimeEvaluateSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_EVALUATE_OK";
constexpr char kPageWebAssemblyUnavailableSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:PAGE_WEBASSEMBLY_UNAVAILABLE";
constexpr char kPageWebAssemblySuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:VALIDATED_MODULE_CONSTRUCTED_INSTANCE_ADD_42_OK";
constexpr char kPageWebAssemblyMemorySuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "MEMORY_CONSTRUCTED_IMPORTED_JS_WRITE_WASM_READ_WASM_WRITE_JS_READ_OK";
constexpr char kRuntimeConsoleApiCalledSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_CONSOLE_API_CALLED_OK";
constexpr char kDetachedMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DETACHED";
constexpr char kFailureMarker[] = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:FAIL";
constexpr int kNetworkEnableCommandId = 1;
constexpr int kRuntimeEnableCommandId = 2;
constexpr int kRuntimeEvaluateCommandId = 3;
constexpr size_t kMaximumProtocolResponseBytes = 4 * 1024;
constexpr char kRuntimeEvaluateExpectedType[] = "string";
constexpr char kRuntimeEvaluateExpectedValue[] = "undefined";
constexpr char kPageWebAssemblyRuntimeEvaluateExpectedValue[] =
    "wasm-add-42";
constexpr char kPageWebAssemblyMemoryRuntimeEvaluateExpectedValue[] =
    "wasm-memory-import-read-write";
constexpr char kRuntimeConsoleApiCalledMethod[] = "Runtime.consoleAPICalled";
constexpr char kRuntimeConsoleApiCalledExpectedType[] = "log";
constexpr char kRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-devtools-console";
constexpr char kPageWebAssemblyRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-page-webassembly-add-42";
constexpr char kPageWebAssemblyMemoryRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-page-webassembly-memory-import-read-write";

}  // namespace

GURL GetWasmBrowserDevToolsProtocolSmokeUrl(
    WasmBrowserDevToolsProtocolSmokeMode mode) {
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    return GURL(kFixedDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kValidateModuleInstanceAdd42) {
    return GURL(kFixedPageWebAssemblyDevToolsProtocolSmokeUrl);
  }
  CHECK_EQ(mode, WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite);
  return GURL(kFixedPageWebAssemblyMemoryDevToolsProtocolSmokeUrl);
}

WasmBrowserDevToolsProtocolSmoke::WasmBrowserDevToolsProtocolSmoke(
    base::OnceClosure success_callback)
    : WasmBrowserDevToolsProtocolSmoke(
          WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable,
          std::move(success_callback)) {}

WasmBrowserDevToolsProtocolSmoke::WasmBrowserDevToolsProtocolSmoke(
    WasmBrowserDevToolsProtocolSmokeMode mode,
    base::OnceClosure success_callback)
    : mode_(mode), success_callback_(std::move(success_callback)) {
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

  const GURL expected_url(GetWasmBrowserDevToolsProtocolSmokeUrl(mode_));
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
  // These three literal commands are the only protocol messages this client
  // can emit. There is no frontend, pipe, socket, host ABI, or caller-provided
  // command surface. The default Runtime.evaluate expression reads only
  // |typeof WebAssembly| to make the current disabled page-WebAssembly
  // boundary observable; it neither constructs nor compiles a page module and
  // does not enable page WebAssembly. The closed alternate expressions use
  // only literal module bytes and fixed add or memory import/read-write
  // witnesses.
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
       state_ != State::kEnablingRuntime &&
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
    // Ignore malformed or unrelated protocol frames; this smoke is not a
    // generic protocol consumer.
    return;
  }

  const base::DictValue& response = value->GetDict();
  const std::string* method = response.FindString("method");
  if (method) {
    if (*method == kRuntimeConsoleApiCalledMethod &&
        state_ == State::kEvaluatingRuntime) {
      CompleteRuntimeConsoleApiCalled(response);
    }
    return;
  }
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

  if (state_ == State::kEnablingRuntime) {
    if (*id != kRuntimeEnableCommandId) {
      return;
    }
    const base::DictValue* result = response.FindDict("result");
    if (response.Find("error") || !result || !result->empty()) {
      Fail("Runtime.enable did not return its fixed empty result");
    }
    CompleteRuntimeEnable();
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
  const char* expected_value = nullptr;
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    expected_value = kRuntimeEvaluateExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::
                 kValidateModuleInstanceAdd42) {
    expected_value = kPageWebAssemblyRuntimeEvaluateExpectedValue;
  } else {
    CHECK_EQ(mode_,
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite);
    expected_value = kPageWebAssemblyMemoryRuntimeEvaluateExpectedValue;
  }
  if (!result_type || *result_type != kRuntimeEvaluateExpectedType ||
      !result_value || *result_value != expected_value) {
    if (mode_ ==
        WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
      Fail("Runtime.evaluate did not return the fixed "
           "page-WebAssembly-unavailable result");
    }
    if (mode_ ==
        WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "memory import/read-write result");
    }
    Fail("Runtime.evaluate did not return the fixed "
         "page-WebAssembly add(20, 22) result");
  }
  if (runtime_evaluate_response_received_) {
    Fail("Runtime.evaluate returned more than one fixed response");
  }
  runtime_evaluate_response_received_ = true;
  std::fprintf(stderr, "%s\n", kRuntimeEvaluateSuccessMarker);
  std::fflush(stderr);
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyUnavailableSuccessMarker);
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::
                 kValidateModuleInstanceAdd42) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblySuccessMarker);
  } else {
    CHECK_EQ(mode_,
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite);
    std::fprintf(stderr, "%s\n", kPageWebAssemblyMemorySuccessMarker);
  }
  std::fflush(stderr);
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
  // the fixed Runtime.enable response while handling this call.
  state_ = State::kEnablingRuntime;
  std::fprintf(stderr, "%s\n", kNetworkEnableSuccessMarker);
  std::fflush(stderr);
  agent_host_->DispatchProtocolMessage(
      this, base::byte_span_from_cstring(kRuntimeEnableCommand));
}

void WasmBrowserDevToolsProtocolSmoke::CompleteRuntimeEnable() {
  CHECK_EQ(state_, State::kEnablingRuntime);
  CHECK(agent_host_);

  // Runtime.enable must complete before the one expression can generate the
  // exact console event. Set the state before dispatch because either the
  // notification or the response can be delivered synchronously, in either
  // order, while this call is active.
  state_ = State::kEvaluatingRuntime;
  std::fprintf(stderr, "%s\n", kRuntimeEnableSuccessMarker);
  std::fflush(stderr);
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    agent_host_->DispatchProtocolMessage(
        this, base::byte_span_from_cstring(kRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kValidateModuleInstanceAdd42) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(kPageWebAssemblyRuntimeEvaluateCommand));
    return;
  }
  CHECK_EQ(mode_, WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite);
  agent_host_->DispatchProtocolMessage(
      this,
      base::byte_span_from_cstring(kPageWebAssemblyMemoryRuntimeEvaluateCommand));
}

void WasmBrowserDevToolsProtocolSmoke::CompleteRuntimeConsoleApiCalled(
    const base::DictValue& notification) {
  CHECK_EQ(state_, State::kEvaluatingRuntime);
  const base::DictValue* params = notification.FindDict("params");
  const std::string* type = params ? params->FindString("type") : nullptr;
  const base::ListValue* arguments =
      params ? params->FindList("args") : nullptr;
  const base::DictValue* argument =
      arguments && arguments->size() == 1 ? (*arguments)[0].GetIfDict()
                                          : nullptr;
  const std::string* argument_type =
      argument ? argument->FindString("type") : nullptr;
  const std::string* argument_value =
      argument ? argument->FindString("value") : nullptr;
  const char* expected_value = nullptr;
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    expected_value = kRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::
                 kValidateModuleInstanceAdd42) {
    expected_value = kPageWebAssemblyRuntimeConsoleApiCalledExpectedValue;
  } else {
    CHECK_EQ(mode_,
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite);
    expected_value =
        kPageWebAssemblyMemoryRuntimeConsoleApiCalledExpectedValue;
  }
  if (!type || *type != kRuntimeConsoleApiCalledExpectedType ||
      !argument_type ||
      *argument_type != kRuntimeEvaluateExpectedType || !argument_value ||
      *argument_value != expected_value) {
    Fail("Runtime.consoleAPICalled did not contain the fixed log argument");
  }
  if (runtime_console_api_called_received_) {
    Fail("Runtime.consoleAPICalled was delivered more than once");
  }
  runtime_console_api_called_received_ = true;
  std::fprintf(stderr, "%s\n", kRuntimeConsoleApiCalledSuccessMarker);
  std::fflush(stderr);
  CompleteRuntimeEvaluate();
}

void WasmBrowserDevToolsProtocolSmoke::CompleteRuntimeEvaluate() {
  CHECK_EQ(state_, State::kEvaluatingRuntime);
  if (!runtime_evaluate_response_received_ ||
      !runtime_console_api_called_received_) {
    return;
  }
  CHECK(success_callback_);

  // Keep both the fixed result and exact console-event witnesses before
  // detachment, then make detachment an independently observable barrier
  // before the lifecycle is allowed to close its Browser and destroy the sole
  // WebContents.
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

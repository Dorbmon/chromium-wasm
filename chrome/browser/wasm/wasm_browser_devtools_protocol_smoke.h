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

// Closed modes for the fixed, lifecycle-owned DevTools protocol proof. These
// are deliberately not derived from a command line, host bridge, URL, or
// protocol input. Each mode has one literal document URL and one literal
// Runtime.evaluate command defined in the implementation.
enum class WasmBrowserDevToolsProtocolSmokeMode {
  kPageWebAssemblyUnavailable,
  kValidateModuleInstanceAdd42,
  kMemoryImportReadWrite,
  kTableImportIndirectCall,
  kMemoryGrowImportReadWrite,
  kTableGrowImportIndirectCall,
  kExceptionImportedTagJsThrowWasmCatch,
  kWasmMemoryGrowOpcodeImport,
  kWasmTableGrowOpcodeImportIndirectCall,
  kWasmThrowImportedTagJsCatch,
  kWasmThrowImportedI32TagJsCatchPayload,
  kExceptionImportedI32TagJsThrowWasmCatchPayload,
};

// Returns the one literal data: URL associated with |mode|. This is used by
// the lifecycle to navigate its sole active tab before the direct client
// attaches; callers cannot supply an arbitrary page URL.
GURL GetWasmBrowserDevToolsProtocolSmokeUrl(
    WasmBrowserDevToolsProtocolSmokeMode mode);

// A switch-gated, direct DevToolsAgentHost client used only to prove that the
// active Wasm Browser tab can accept three fixed protocol requests:
// Network.enable, Runtime.enable, and one literal Runtime.evaluate expression.
// It also accepts one exact console event produced by that expression. This is
// deliberately not a DevTools frontend or a protocol transport: it accepts
// only those fixed successful responses and the one event and forwards no
// protocol traffic to JavaScript or another process. Its default expression
// exercises ordinary page JavaScript and verifies that |typeof WebAssembly| is
// "undefined" in this disabled configuration; it does not construct, compile,
// or otherwise exercise page WebAssembly. The separate closed page-WebAssembly
// mode is limited to one literal 41-byte module and its fixed add(20, 22)
// result. A second closed page-WebAssembly mode imports one fixed one-page
// memory and witnesses JavaScript-to-Wasm and Wasm-to-JavaScript reads and
// writes without exercising growth, tables, exceptions, or threads. A third
// closed page-WebAssembly mode imports one fixed, non-growable table,
// initializes its sole entry through an active element segment, and calls it
// indirectly. It does not exercise table mutation/growth, reference types
// beyond funcref, memories, exceptions, or threads. A fourth closed
// page-WebAssembly mode grows a fixed imported memory from one page to two,
// verifies the non-shared buffer replacement, and witnesses Wasm/JavaScript
// reads and writes in the newly added page. It does not exercise Wasm's
// memory.grow opcode, tables, exceptions, or threads. A fifth closed
// page-WebAssembly mode grows a fixed imported table from one entry to two
// through JavaScript, initializes the new entry, and calls it indirectly from
// Wasm. It does not exercise Wasm's table.grow opcode, broader reference
// types, exceptions, or threads. A sixth closed page-WebAssembly mode creates
// a JavaScript exception with a fixed imported Wasm tag, throws it from an
// imported JavaScript function, and catches it in Wasm. It does not exercise
// Wasm throw, payload, rethrow, catch-all, Wasm-to-JavaScript escape, or
// thread semantics. A seventh closed page-WebAssembly mode invokes the Wasm
// memory.grow opcode for a fixed imported memory and verifies its returned old
// page count, non-shared buffer replacement, and final size. It does not
// exercise shared or multiple memories, post-growth data exchange, tables,
// exceptions, or threads. An eighth closed page-WebAssembly mode imports one
// bounded table, invokes Wasm's table.grow opcode to grow it from one entry to
// two, and makes a fixed indirect call through the grown entry. It does not
// exercise failed growth, table copy/fill/init, multiple tables, typed
// function references, GC references, exceptions, memories, or threads. A
// ninth closed page-WebAssembly mode imports one zero-payload tag, executes
// the Wasm throw opcode, and validates in JavaScript that the escaping
// WebAssembly.Exception matches that tag. It does not exercise payloads,
// Wasm-internal catches, rethrow, catch-all, throw_ref, tables, memories, or
// threads. A tenth closed page-WebAssembly mode imports one i32-payload tag,
// executes Wasm throw with payload 42, and validates in JavaScript both tag
// identity and the payload. It does not exercise other payload types,
// coercions, Wasm-internal catches, rethrow, catch-all, throw_ref, exception
// stacks, tables, memories, or threads. An eleventh closed page-WebAssembly
// mode imports one i32-payload tag and one JavaScript function that throws a
// fixed WebAssembly.Exception(tag, [42]); Wasm catches that tag and returns
// its payload. It does not exercise other payload types, coercions, Wasm
// throw, rethrow, catch-all, throw_ref, exception stacks, tables, memories,
// or threads.
class WasmBrowserDevToolsProtocolSmoke final
    : public content::DevToolsAgentHostClient {
 public:
  // Retains the original unavailable-boundary behavior for existing callers.
  explicit WasmBrowserDevToolsProtocolSmoke(base::OnceClosure success_callback);
  WasmBrowserDevToolsProtocolSmoke(
      WasmBrowserDevToolsProtocolSmokeMode mode,
      base::OnceClosure success_callback);
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

  const WasmBrowserDevToolsProtocolSmokeMode mode_;
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

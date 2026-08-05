// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/shell/browser/wasm_host_api.h"

#include <stddef.h>
#include <stdint.h>

#include <atomic>
#include <cstring>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "base/containers/span.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/location.h"
#include "base/logging.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "base/values.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/devtools_agent_host.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/render_widget_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/common/isolated_world_ids.h"
#include "content/shell/browser/shell.h"
#include "emscripten/emscripten.h"
#include "emscripten/heap.h"
#include "net/base/net_errors.h"
#include "net/http/http_connection_info.h"
#include "net/http/http_response_headers.h"
#include "net/socket/wisp_transport_wasm.h"
#include "third_party/blink/public/common/input/web_mouse_event.h"
#include "ui/aura/client/focus_client.h"
#include "ui/aura/window.h"
#include "ui/aura/window_tree_host.h"
#include "ui/aura/window_tree_host_platform.h"
#include "ui/events/event_constants.h"
#include "ui/events/event_utils.h"
#include "ui/events/keycodes/dom/keycode_converter.h"
#include "ui/gfx/geometry/point.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"
#include "ui/gfx/geometry/vector2d.h"
#include "ui/ozone/platform/wasm/wasm_event_source.h"
#include "ui/ozone/platform/wasm/wasm_input_method.h"
#include "ui/ozone/public/ozone_platform.h"
#include "ui/ozone/public/system_input_injector.h"
#include "ui/ozone/platform/wasm/wasm_screen.h"
#include "ui/platform_window/platform_window.h"
#include "url/gurl.h"
#include "url/url_constants.h"

namespace content {

namespace {

constexpr int kMaximumCanvasDimension = 16384;
// Account for both the Skia raster backing and the unpremultiplied RGBA
// presentation copy. This leaves at least 1.875 GiB of the configured 2 GiB
// linear-memory ceiling to Content, V8, and browser services.
constexpr int64_t kMaximumCanvasStorageBytes = 128 * 1024 * 1024;
constexpr size_t kMaximumDataUrlBytes = 8 * 1024 * 1024;
constexpr size_t kMaximumM5PublicUrlBytes = 2048;
constexpr size_t kMaximumM5DevToolsProtocolMessageBytes = 64 * 1024;
constexpr size_t kMaximumM5DevToolsReportBytes = 4096;
constexpr std::string_view kM5NetworkTestHostname = "a.test";
constexpr std::string_view kM5NetworkTestPathPrefix = "/m5/";
constexpr std::string_view kM5NetworkRedirectPath = "/m5/redirect-cookie";
constexpr std::string_view kM5NetworkDocumentPath = "/m5/";
constexpr std::string_view kM5PublicSpecialUseHostnameSuffixes[] = {
    ".localhost",
    ".local",
    ".test",
    ".example",
    ".invalid",
    ".onion",
    ".home.arpa",
};
// The plaintext control is deliberately one exact test URL. It establishes
// Chromium-to-WISP HTTP transport before the HTTPS fixture proves that an
// active mixed-content fetch to the same listener is blocked.
constexpr std::string_view kM5PlaintextHttpControlPath =
    "/m5/plaintext-control";
constexpr size_t kMaximumM4TextInputUtf16Units = 64 * 1024;
constexpr size_t kMaximumM4TextInputUtf8Bytes =
    kMaximumM4TextInputUtf16Units * 3;
// This remains a bounded physical-key ABI. Fixed-US KeyA/KeyB, Backspace, and
// the explicit Ctrl+C/Ctrl+V chord are editing experiments, not a generic
// keyboard or text-insertion path.
constexpr std::string_view kM4NavigationDomCode = "ArrowDown";
constexpr std::string_view kM4PrintableKeyADomCode = "KeyA";
constexpr std::string_view kM4PrintableKeyBDomCode = "KeyB";
constexpr std::string_view kM4BackspaceDomCode = "Backspace";
constexpr std::string_view kM4ControlLeftDomCode = "ControlLeft";
constexpr std::string_view kM4CopyDomCode = "KeyC";
constexpr std::string_view kM4PasteDomCode = "KeyV";
constexpr size_t kMaximumM4DomCodeLength = kM4ControlLeftDomCode.size();

bool IsSupportedM4DomCode(ui::DomCode dom_code) {
  return dom_code == ui::DomCode::ARROW_DOWN ||
         dom_code == ui::DomCode::US_A || dom_code == ui::DomCode::US_B ||
         dom_code == ui::DomCode::BACKSPACE ||
         dom_code == ui::DomCode::CONTROL_LEFT ||
         dom_code == ui::DomCode::US_C || dom_code == ui::DomCode::US_V;
}

bool IsM4RepeatableDomCode(ui::DomCode dom_code) {
  return dom_code == ui::DomCode::ARROW_DOWN ||
         dom_code == ui::DomCode::BACKSPACE;
}

enum class DomPointerEventType {
  kMove = 0,
  kDown = 1,
  kUp = 2,
};

std::atomic_bool& GetWasmM5NetworkTestMode() {
  static std::atomic_bool enabled(false);
  return enabled;
}

std::atomic_bool& GetWasmM5PublicNetworkTestMode() {
  static std::atomic_bool enabled(false);
  return enabled;
}

bool IsWasmM5NetworkTestModeEnabled() {
  return GetWasmM5NetworkTestMode().load(std::memory_order_relaxed);
}

bool IsWasmM5PublicNetworkTestModeEnabled() {
  return GetWasmM5PublicNetworkTestMode().load(std::memory_order_relaxed);
}

bool IsM5NetworkTestUrl(const GURL& candidate_url) {
  return IsWasmM5NetworkTestModeEnabled() && candidate_url.is_valid() &&
         candidate_url.SchemeIs(url::kHttpsScheme) &&
         candidate_url.host() == kM5NetworkTestHostname &&
         candidate_url.has_port() &&
         !candidate_url.has_username() && !candidate_url.has_password() &&
         !candidate_url.has_query() && !candidate_url.has_ref() &&
         candidate_url.path().starts_with(kM5NetworkTestPathPrefix);
}

bool IsM5PlaintextHttpControlUrl(const GURL& candidate_url) {
  return IsWasmM5NetworkTestModeEnabled() && candidate_url.is_valid() &&
         candidate_url.SchemeIs(url::kHttpScheme) &&
         candidate_url.host() == kM5NetworkTestHostname &&
         candidate_url.has_port() &&
         !candidate_url.has_username() && !candidate_url.has_password() &&
         !candidate_url.has_query() && !candidate_url.has_ref() &&
         candidate_url.path() == kM5PlaintextHttpControlPath;
}

bool IsM5PublicDnsHostname(std::string_view host) {
  if (host.find('.') == std::string_view::npos || host.ends_with('.')) {
    return false;
  }
  for (const std::string_view suffix : kM5PublicSpecialUseHostnameSuffixes) {
    const std::string_view exact_name = suffix.substr(1);
    if (base::EqualsCaseInsensitiveASCII(host, exact_name) ||
        base::EndsWith(host, suffix, base::CompareCase::INSENSITIVE_ASCII)) {
      return false;
    }
  }
  return true;
}

// This test-only lane intentionally accepts a single canonical public HTTPS
// URL from the external smoke runner. It is unavailable from the regular and
// controlled-fixture binaries. The runner and host bind the exact URL before
// navigation, while the separately provisioned WISP gateway owns the
// destination allowlist. Do not treat this syntax check as a gateway policy.
bool IsM5PublicHttpsUrl(const GURL& candidate_url) {
  const std::string_view host = candidate_url.host();
  return IsWasmM5PublicNetworkTestModeEnabled() &&
         candidate_url.is_valid() &&
         candidate_url.SchemeIs(url::kHttpsScheme) &&
         candidate_url.EffectiveIntPort() == 443 &&
         !candidate_url.has_username() && !candidate_url.has_password() &&
         !candidate_url.has_query() && !candidate_url.has_ref() &&
         !candidate_url.HostIsIPAddress() &&
         IsM5PublicDnsHostname(host);
}

bool IsObservedWasmHostUrl(const GURL& candidate_url) {
  return candidate_url.SchemeIs(url::kDataScheme) ||
         IsM5NetworkTestUrl(candidate_url) ||
         IsM5PlaintextHttpControlUrl(candidate_url) ||
         IsM5PublicHttpsUrl(candidate_url);
}

extern "C" int chromium_wasm_report_readiness(
    int shell_ready,
    int surface_ready,
    int first_visually_nonempty_paint);
extern "C" int chromium_wasm_report_navigation();
extern "C" int chromium_wasm_report_page_probe(const char* probe);
extern "C" int chromium_wasm_report_m5_navigation();
extern "C" int chromium_wasm_report_m5_navigation_error(int net_error);
extern "C" int chromium_wasm_report_m5_devtools_network(const char* report);
extern "C" int chromium_wasm_report_m5_public_devtools_network(
    const char* report);
extern "C" int chromium_wasm_report_m5_page_probe(const char* probe);
extern "C" int chromium_wasm_report_m5_plaintext_http_control_navigation();
extern "C" int chromium_wasm_report_m5_plaintext_http_control_navigation_error(
    int net_error);
extern "C" int chromium_wasm_report_m5_plaintext_http_control_page_probe(
    const char* probe);
extern "C" int chromium_wasm_report_m5_public_navigation(
    const char* url,
    int response_code,
    const char* protocol,
    int protocol_length);
extern "C" int chromium_wasm_report_m5_public_navigation_error(
    const char* url,
    int net_error);
extern "C" int chromium_wasm_report_fatal(const char* message);
extern "C" int chromium_wasm_report_ozone_text_input_delivery(
    int action,
    int session_id,
    int sequence,
    int accepted);

void ReportFatal(std::string_view message) {
  const std::string terminated_message(message);
  if (chromium_wasm_report_fatal(terminated_message.c_str()) != 1) {
    LOG(ERROR) << "Unable to deliver M3 host failure: " << message;
  }
}

// The browser-facing DevTools sockets and pipe are intentionally unsupported
// on Wasm: a browser page cannot safely expose a listening TCP endpoint, and
// Emscripten has no inherited debugging file descriptors. This recorder uses
// the same in-process DevToolsAgentHost protocol client that Chromium's
// browser tests use. It is instantiated only by the dedicated controlled M5
// executable and forwards a fixed, redacted event summary rather than raw CDP
// frames, request IDs, URLs, headers, or cookies.
class M5DevToolsNetworkRecorder final : public DevToolsAgentHostClient {
 public:
  M5DevToolsNetworkRecorder() = default;

  M5DevToolsNetworkRecorder(const M5DevToolsNetworkRecorder&) = delete;
  M5DevToolsNetworkRecorder& operator=(
      const M5DevToolsNetworkRecorder&) = delete;

  ~M5DevToolsNetworkRecorder() override { Detach(); }

  bool Start(WebContents* web_contents) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (!web_contents || agent_host_ || state_ != State::kCreated) {
      return false;
    }

    agent_host_ = DevToolsAgentHost::GetOrCreateFor(web_contents);
    if (!agent_host_ || !agent_host_->AttachClient(this)) {
      agent_host_ = nullptr;
      return false;
    }

    state_ = State::kEnabling;
    static constexpr char kEnableNetworkCommand[] =
        R"({"id":1,"method":"Network.enable"})";
    agent_host_->DispatchProtocolMessage(
        this, base::byte_span_from_cstring(kEnableNetworkCommand));
    return state_ != State::kFailed;
  }

 private:
  enum class State {
    kCreated,
    kEnabling,
    kEnabled,
    kComplete,
    kFailed,
  };

  void DispatchProtocolMessage(DevToolsAgentHost* agent_host,
                               base::span<const uint8_t> message) override {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (agent_host != agent_host_.get() || state_ == State::kFailed ||
        state_ == State::kComplete) {
      return;
    }
    if (message.size() > kMaximumM5DevToolsProtocolMessageBytes) {
      Fail("received an oversized protocol message");
      return;
    }

    const std::string_view message_text(
        reinterpret_cast<const char*>(message.data()), message.size());
    std::optional<base::Value> value = base::JSONReader::Read(
        message_text, base::JSON_PARSE_CHROMIUM_EXTENSIONS);
    if (!value || !value->is_dict()) {
      Fail("received a malformed protocol message");
      return;
    }
    const base::DictValue& parsed = value->GetDict();
    if (const std::optional<int> id = parsed.FindInt("id")) {
      HandleCommandResponse(*id, parsed);
      return;
    }

    const std::string* method = parsed.FindString("method");
    const base::DictValue* params = parsed.FindDict("params");
    if (!method || !params || state_ != State::kEnabled) {
      return;
    }
    if (*method == "Network.requestWillBeSent") {
      RecordRequest(*params);
    } else if (*method == "Network.responseReceived") {
      RecordResponse(*params);
    } else if (*method == "Network.loadingFinished") {
      RecordFinished(*params);
    }
  }

  void AgentHostClosed(DevToolsAgentHost* agent_host) override {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (agent_host != agent_host_.get()) {
      return;
    }
    agent_host_ = nullptr;
    if (state_ != State::kComplete && state_ != State::kFailed) {
      Fail("closed before the controlled network trace completed");
    }
  }

  void HandleCommandResponse(int id, const base::DictValue& response) {
    if (id != 1) {
      return;
    }
    if (state_ != State::kEnabling || response.FindDict("error") ||
        !response.FindDict("result")) {
      Fail("Network.enable was rejected");
      return;
    }

    state_ = State::kEnabled;
    base::DictValue report;
    report.Set("protocol", 1);
    report.Set("state", "enabled");
    report.Set("networkEnabled", true);
    report.Set("events", base::ListValue());
    if (!Report(std::move(report))) {
      Fail("could not report Network.enable");
    }
  }

  bool IsTargetDocumentRequest(const base::DictValue& params,
                               std::string_view expected_path,
                               std::string* request_id) {
    const std::string* url = params.FindStringByDottedPath("request.url");
    const std::string* resource_type = params.FindString("type");
    const std::string* id = params.FindString("requestId");
    if (!url || !resource_type || !id) {
      return false;
    }
    const GURL request_url(*url);
    if (!IsM5NetworkTestUrl(request_url) ||
        request_url.path() != expected_path) {
      return false;
    }
    if (*resource_type != "Document" || id->empty() ||
        id->size() > 256) {
      Fail("received an invalid controlled document request event");
      return false;
    }
    *request_id = *id;
    return true;
  }

  void RecordRequest(const base::DictValue& params) {
    std::string request_id;
    if (IsTargetDocumentRequest(params, kM5NetworkRedirectPath, &request_id)) {
      if (redirect_request_seen_ || !request_id_.empty()) {
        Fail("received a duplicate redirect request event");
        return;
      }
      redirect_request_seen_ = true;
      request_id_ = std::move(request_id);
      AppendEvent("Network.requestWillBeSent:redirect");
      return;
    }

    if (!IsTargetDocumentRequest(params, kM5NetworkDocumentPath, &request_id)) {
      return;
    }
    if (!redirect_request_seen_ || final_request_seen_ ||
        request_id != request_id_) {
      Fail("final document request did not preserve the redirect request ID");
      return;
    }
    final_request_seen_ = true;
    AppendEvent("Network.requestWillBeSent:final");
  }

  void RecordResponse(const base::DictValue& params) {
    if (!final_request_seen_) {
      return;
    }
    const std::string* request_id = params.FindString("requestId");
    if (!request_id || *request_id != request_id_) {
      return;
    }
    const std::optional<int> status =
        params.FindIntByDottedPath("response.status");
    const std::string* protocol =
        params.FindStringByDottedPath("response.protocol");
    if (response_received_ || !status || !protocol || protocol->empty() ||
        protocol->size() > 32) {
      Fail("received an invalid final document response event");
      return;
    }
    response_received_ = true;
    response_status_ = *status;
    response_protocol_ = *protocol;
    AppendEvent("Network.responseReceived:final");
  }

  void RecordFinished(const base::DictValue& params) {
    if (!response_received_) {
      return;
    }
    const std::string* request_id = params.FindString("requestId");
    if (!request_id || *request_id != request_id_) {
      return;
    }
    if (loading_finished_) {
      Fail("received a duplicate final document completion event");
      return;
    }
    loading_finished_ = true;
    AppendEvent("Network.loadingFinished:final");
    MaybeReportComplete();
  }

  void AppendEvent(std::string_view event) {
    if (events_.size() >= 4) {
      Fail("recorded too many controlled document events");
      return;
    }
    events_.Append(event);
  }

  void MaybeReportComplete() {
    if (state_ != State::kEnabled || !redirect_request_seen_ ||
        !final_request_seen_ || !response_received_ || !loading_finished_ ||
        events_.size() != 4) {
      return;
    }

    state_ = State::kComplete;
    base::DictValue report;
    report.Set("protocol", 1);
    report.Set("state", "complete");
    report.Set("networkEnabled", true);
    report.Set("redirectRequest", redirect_request_seen_);
    report.Set("finalRequest", final_request_seen_);
    report.Set("responseReceived", response_received_);
    report.Set("loadingFinished", loading_finished_);
    report.Set("requestIdCorrelated", true);
    report.Set("responseStatus", response_status_);
    report.Set("responseProtocol", response_protocol_);
    report.Set("events", std::move(events_));
    if (!Report(std::move(report))) {
      Fail("could not report the completed controlled network trace");
    }
  }

  bool Report(base::DictValue report) {
    const std::optional<std::string> serialized = base::WriteJson(report);
    if (!serialized || serialized->empty() ||
        serialized->size() > kMaximumM5DevToolsReportBytes) {
      return false;
    }
    return chromium_wasm_report_m5_devtools_network(serialized->c_str()) == 1;
  }

  void Fail(std::string_view reason) {
    if (state_ == State::kFailed) {
      return;
    }
    state_ = State::kFailed;
    ReportFatal("M5 DevTools Network recorder: " + std::string(reason));
  }

  void Detach() {
    if (!agent_host_) {
      return;
    }
    scoped_refptr<DevToolsAgentHost> agent_host = std::move(agent_host_);
    agent_host->DetachClient(this);
  }

  State state_ = State::kCreated;
  scoped_refptr<DevToolsAgentHost> agent_host_;
  bool redirect_request_seen_ = false;
  bool final_request_seen_ = false;
  bool response_received_ = false;
  bool loading_finished_ = false;
  std::string request_id_;
  int response_status_ = 0;
  std::string response_protocol_;
  base::ListValue events_;
};

// The public M5 executable uses a separate, deliberately narrower recorder.
// Its single externally supplied document must produce genuine Chromium CDP
// Network events, but no runtime-provided URL, request ID, header, cookie, or
// payload may leave this process. The final report additionally proves that
// the WISP bridge completed a WebSocket/WISP handshake and one TCP stream
// after the public navigation's diagnostic boundary.
class M5PublicDevToolsNetworkRecorder final : public DevToolsAgentHostClient {
 public:
  M5PublicDevToolsNetworkRecorder() = default;

  M5PublicDevToolsNetworkRecorder(const M5PublicDevToolsNetworkRecorder&) =
      delete;
  M5PublicDevToolsNetworkRecorder& operator=(
      const M5PublicDevToolsNetworkRecorder&) = delete;

  ~M5PublicDevToolsNetworkRecorder() override { Detach(); }

  bool Start(WebContents* web_contents) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (!web_contents || agent_host_ || state_ != State::kCreated) {
      return false;
    }

    agent_host_ = DevToolsAgentHost::GetOrCreateFor(web_contents);
    if (!agent_host_ || !agent_host_->AttachClient(this)) {
      agent_host_ = nullptr;
      return false;
    }

    state_ = State::kEnabling;
    static constexpr char kEnableNetworkCommand[] =
        R"({"id":1,"method":"Network.enable"})";
    agent_host_->DispatchProtocolMessage(
        this, base::byte_span_from_cstring(kEnableNetworkCommand));
    return state_ != State::kFailed;
  }

  bool BeginWispEvidenceWindow() {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (state_ != State::kEnabled || wisp_evidence_window_started_ ||
        !net::BeginWasmWispTransportDiagnostics()) {
      return false;
    }
    wisp_evidence_window_started_ = true;
    return true;
  }

 private:
  enum class State {
    kCreated,
    kEnabling,
    kEnabled,
    kComplete,
    kFailed,
  };

  void DispatchProtocolMessage(DevToolsAgentHost* agent_host,
                               base::span<const uint8_t> message) override {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (agent_host != agent_host_.get() || state_ == State::kFailed ||
        state_ == State::kComplete) {
      return;
    }
    if (message.size() > kMaximumM5DevToolsProtocolMessageBytes) {
      Fail("received an oversized protocol message");
      return;
    }

    const std::string_view message_text(
        reinterpret_cast<const char*>(message.data()), message.size());
    std::optional<base::Value> value = base::JSONReader::Read(
        message_text, base::JSON_PARSE_CHROMIUM_EXTENSIONS);
    if (!value || !value->is_dict()) {
      Fail("received a malformed protocol message");
      return;
    }
    const base::DictValue& parsed = value->GetDict();
    if (const std::optional<int> id = parsed.FindInt("id")) {
      HandleCommandResponse(*id, parsed);
      return;
    }

    const std::string* method = parsed.FindString("method");
    const base::DictValue* params = parsed.FindDict("params");
    if (!method || !params || state_ != State::kEnabled) {
      return;
    }
    if (*method == "Network.requestWillBeSent") {
      RecordRequest(*params);
    } else if (*method == "Network.responseReceived") {
      RecordResponse(*params);
    } else if (*method == "Network.loadingFinished") {
      RecordFinished(*params);
    }
  }

  void AgentHostClosed(DevToolsAgentHost* agent_host) override {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    if (agent_host != agent_host_.get()) {
      return;
    }
    agent_host_ = nullptr;
    if (state_ != State::kComplete && state_ != State::kFailed) {
      Fail("closed before the public network trace completed");
    }
  }

  void HandleCommandResponse(int id, const base::DictValue& response) {
    if (id != 1) {
      return;
    }
    if (state_ != State::kEnabling || response.FindDict("error") ||
        !response.FindDict("result")) {
      Fail("Network.enable was rejected");
      return;
    }

    state_ = State::kEnabled;
    base::DictValue report;
    report.Set("protocol", 1);
    report.Set("state", "enabled");
    report.Set("networkEnabled", true);
    report.Set("events", base::ListValue());
    if (!Report(std::move(report))) {
      Fail("could not report Network.enable");
    }
  }

  bool IsPublicDocumentRequest(const base::DictValue& params,
                               std::string* request_id) {
    const std::string* url = params.FindStringByDottedPath("request.url");
    if (!url) {
      return false;
    }
    const GURL request_url(*url);
    if (!IsM5PublicHttpsUrl(request_url)) {
      return false;
    }
    const std::string* resource_type = params.FindString("type");
    const std::string* id = params.FindString("requestId");
    if (!resource_type || !id || *resource_type != "Document" ||
        id->empty() || id->size() > 256) {
      Fail("received an invalid public document request event");
      return false;
    }
    *request_id = *id;
    return true;
  }

  void RecordRequest(const base::DictValue& params) {
    std::string request_id;
    if (!IsPublicDocumentRequest(params, &request_id)) {
      return;
    }
    if (document_request_seen_ || !request_id_.empty()) {
      Fail("received a duplicate public document request event");
      return;
    }
    document_request_seen_ = true;
    request_id_ = std::move(request_id);
    AppendEvent("Network.requestWillBeSent:document");
  }

  void RecordResponse(const base::DictValue& params) {
    if (!document_request_seen_) {
      return;
    }
    const std::string* request_id = params.FindString("requestId");
    if (!request_id || *request_id != request_id_) {
      return;
    }
    const std::string* resource_type = params.FindString("type");
    const std::optional<int> status =
        params.FindIntByDottedPath("response.status");
    const std::string* protocol =
        params.FindStringByDottedPath("response.protocol");
    if (response_received_ || !resource_type || *resource_type != "Document" ||
        !status || !protocol || protocol->empty() || protocol->size() > 32) {
      Fail("received an invalid public document response event");
      return;
    }
    response_received_ = true;
    response_status_ = *status;
    response_protocol_ = *protocol;
    AppendEvent("Network.responseReceived:document");
  }

  void RecordFinished(const base::DictValue& params) {
    if (!response_received_) {
      return;
    }
    const std::string* request_id = params.FindString("requestId");
    if (!request_id || *request_id != request_id_) {
      return;
    }
    if (loading_finished_) {
      Fail("received a duplicate public document completion event");
      return;
    }
    loading_finished_ = true;
    AppendEvent("Network.loadingFinished:document");
    MaybeReportComplete();
  }

  void AppendEvent(std::string_view event) {
    if (events_.size() >= 3) {
      Fail("recorded too many public document events");
      return;
    }
    events_.Append(event);
  }

  void MaybeReportComplete() {
    if (state_ != State::kEnabled || !document_request_seen_ ||
        !response_received_ || !loading_finished_ || events_.size() != 3) {
      return;
    }
    if (!wisp_evidence_window_started_) {
      Fail("public document completed before its WISP evidence window started");
      return;
    }
    const std::optional<net::WasmWispTransportDiagnostics> diagnostics =
        net::GetWasmWispTransportDiagnostics();
    if (!diagnostics ||
        diagnostics->completion_flags != net::kWasmWispDiagnosticAllRequired) {
      Fail("public document did not complete a WISP WebSocket and TCP stream");
      return;
    }

    state_ = State::kComplete;
    base::DictValue report;
    report.Set("protocol", 1);
    report.Set("state", "complete");
    report.Set("networkEnabled", true);
    report.Set("documentRequest", document_request_seen_);
    report.Set("responseReceived", response_received_);
    report.Set("loadingFinished", loading_finished_);
    report.Set("requestIdCorrelated", true);
    report.Set("responseStatus", response_status_);
    report.Set("responseProtocol", response_protocol_);
    report.Set("wispWebSocketOpened", true);
    report.Set("wispHandshakeReady", true);
    report.Set("wispConfirmedStream", true);
    report.Set("events", std::move(events_));
    if (!Report(std::move(report))) {
      Fail("could not report the completed public network trace");
    }
  }

  bool Report(base::DictValue report) {
    const std::optional<std::string> serialized = base::WriteJson(report);
    if (!serialized || serialized->empty() ||
        serialized->size() > kMaximumM5DevToolsReportBytes) {
      return false;
    }
    return chromium_wasm_report_m5_public_devtools_network(
               serialized->c_str()) == 1;
  }

  void Fail(std::string_view reason) {
    if (state_ == State::kFailed) {
      return;
    }
    state_ = State::kFailed;
    ReportFatal("M5 public DevTools Network recorder: " +
                std::string(reason));
  }

  void Detach() {
    if (!agent_host_) {
      return;
    }
    scoped_refptr<DevToolsAgentHost> agent_host = std::move(agent_host_);
    agent_host->DetachClient(this);
  }

  State state_ = State::kCreated;
  scoped_refptr<DevToolsAgentHost> agent_host_;
  bool document_request_seen_ = false;
  bool response_received_ = false;
  bool loading_finished_ = false;
  bool wisp_evidence_window_started_ = false;
  std::string request_id_;
  int response_status_ = 0;
  std::string response_protocol_;
  base::ListValue events_;
};

void ReportTextInputDelivery(const ui::WasmTextInputRecord& record,
                             bool accepted) {
  if (chromium_wasm_report_ozone_text_input_delivery(
          static_cast<int>(record.action), record.session_id, record.sequence,
          accepted ? 1 : 0) != 1) {
    ReportFatal("host rejected M4 Ozone text-input delivery report");
  }
}

std::optional<ui::WasmTextInputAction> ParseWasmTextInputAction(int action) {
  switch (action) {
    case static_cast<int>(ui::WasmTextInputAction::kSetComposition):
      return ui::WasmTextInputAction::kSetComposition;
    case static_cast<int>(ui::WasmTextInputAction::kConfirmComposition):
      return ui::WasmTextInputAction::kConfirmComposition;
    case static_cast<int>(ui::WasmTextInputAction::kClearComposition):
      return ui::WasmTextInputAction::kClearComposition;
  }
  return std::nullopt;
}

bool CopyM4TextInputRecord(int action,
                           int session_id,
                           int sequence,
                           const uint8_t* text_utf8,
                           int text_utf8_bytes,
                           int selection_start,
                           int selection_end,
                           ui::WasmTextInputRecord* record) {
  CHECK(record);
  const std::optional<ui::WasmTextInputAction> parsed_action =
      ParseWasmTextInputAction(action);
  if (!parsed_action || session_id <= 0 || sequence <= 0 ||
      text_utf8_bytes < 0 || selection_start < 0 ||
      selection_end < selection_start) {
    return false;
  }

  const size_t text_bytes = static_cast<size_t>(text_utf8_bytes);
  if (text_bytes > kMaximumM4TextInputUtf8Bytes) {
    return false;
  }
  if (text_bytes != 0) {
    if (!text_utf8) {
      return false;
    }
    const uintptr_t start = reinterpret_cast<uintptr_t>(text_utf8);
    const size_t heap_size = emscripten_get_heap_size();
    if (start > heap_size || text_bytes > heap_size - start) {
      return false;
    }
  }

  std::string utf8;
  if (text_bytes != 0) {
    utf8.assign(reinterpret_cast<const char*>(text_utf8), text_bytes);
  }
  if (!base::IsStringUTF8AllowingNoncharacters(utf8)) {
    return false;
  }
  std::u16string text = base::UTF8ToUTF16(utf8);
  if (text.size() > kMaximumM4TextInputUtf16Units) {
    return false;
  }

  const size_t start = static_cast<size_t>(selection_start);
  const size_t end = static_cast<size_t>(selection_end);
  switch (*parsed_action) {
    case ui::WasmTextInputAction::kSetComposition:
      // RenderWidgetHostViewAura currently honors composition.selection.end()
      // but not selection.start(). Keep this first route intentionally
      // collapsed at the candidate end rather than silently losing a range.
      if (text.empty() || start != end || end != text.size()) {
        return false;
      }
      break;
    case ui::WasmTextInputAction::kConfirmComposition:
    case ui::WasmTextInputAction::kClearComposition:
      if (!text.empty() || start != 0 || end != 0) {
        return false;
      }
      break;
  }

  *record = {*parsed_action, static_cast<uint32_t>(session_id),
             static_cast<uint32_t>(sequence), std::move(text),
             gfx::Range(start, end)};
  return true;
}

class WasmHostObserver final : public WebContentsObserver {
 public:
  explicit WasmHostObserver(WebContents* web_contents)
      : WebContentsObserver(web_contents) {}

  WasmHostObserver(const WasmHostObserver&) = delete;
  WasmHostObserver& operator=(const WasmHostObserver&) = delete;

  ~WasmHostObserver() override = default;

  void DidStartNavigation(NavigationHandle* navigation_handle) override {
    if (!navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument()) {
      return;
    }

    probe_timer_.Stop();
    probe_in_flight_ = false;
    weak_ptr_factory_.InvalidateWeakPtrs();
    ++navigation_generation_;
    if (IsM5PublicHttpsUrl(navigation_handle->GetURL())) {
      if (m5_public_navigation_finished_ || m5_public_navigation_handle_) {
        ReportFatal("unexpected additional M5 public HTTPS navigation");
        return;
      }
      // NavigationHandle is stable from DidStartNavigation through
      // DidFinishNavigation. Retaining its identity, rather than one global
      // boolean, keeps an overlapping main-frame navigation from being
      // misclassified as the one allowed public probe.
      m5_public_navigation_handle_ = navigation_handle;
    }
  }

  void DidFinishNavigation(NavigationHandle* navigation_handle) override {
    if (!navigation_handle->IsInPrimaryMainFrame() ||
        navigation_handle->IsSameDocument()) {
      return;
    }

    const GURL& navigation_url = navigation_handle->GetURL();
    const net::Error net_error = navigation_handle->GetNetErrorCode();
    const bool is_m5_public_navigation =
        m5_public_navigation_handle_ == navigation_handle;
    if (is_m5_public_navigation) {
      m5_public_navigation_handle_ = nullptr;
      m5_public_navigation_finished_ = true;
      if (navigation_url.spec().size() > kMaximumM5PublicUrlBytes) {
        ReportFatal("M5 public HTTPS navigation URL exceeded its bound");
        return;
      }
    }
    if (is_m5_public_navigation &&
        (net_error != net::OK || !navigation_handle->HasCommitted() ||
         navigation_handle->IsErrorPage())) {
      const std::string url_spec(navigation_url.spec());
      const int report_error =
          net_error == net::OK ? net::ERR_FAILED : static_cast<int>(net_error);
      if (chromium_wasm_report_m5_public_navigation_error(
              url_spec.c_str(), report_error) != 1) {
        ReportFatal("host rejected the failed M5 public HTTPS navigation "
                    "report");
      }
      return;
    }
    if (IsM5PlaintextHttpControlUrl(navigation_url) &&
        net_error != net::OK) {
      if (chromium_wasm_report_m5_plaintext_http_control_navigation_error(
              static_cast<int>(net_error)) != 1) {
        ReportFatal(
            "host rejected the failed M5 plaintext HTTP control navigation "
            "report");
      }
      return;
    }
    if (IsM5NetworkTestUrl(navigation_url) && net_error != net::OK) {
      if (chromium_wasm_report_m5_navigation_error(
              static_cast<int>(net_error)) != 1) {
        ReportFatal("host rejected the failed M5 HTTPS navigation report");
      }
      return;
    }

    if (!navigation_handle->HasCommitted()) {
      return;
    }
    if (navigation_url.SchemeIs(url::kDataScheme)) {
      if (chromium_wasm_report_navigation() != 1) {
        ReportFatal("host rejected the committed data navigation report");
      }
      return;
    }
    if (is_m5_public_navigation) {
      const std::string url_spec(navigation_url.spec());
      const net::HttpResponseHeaders* headers =
          navigation_handle->GetResponseHeaders();
      const int response_code = headers ? headers->response_code() : 0;
      const std::string_view protocol = net::HttpConnectionInfoToString(
          navigation_handle->GetConnectionInfo());
      if (chromium_wasm_report_m5_public_navigation(
              url_spec.c_str(), response_code, protocol.data(),
              static_cast<int>(protocol.size())) != 1) {
        ReportFatal("host rejected the committed M5 public HTTPS navigation "
                    "report");
      }
      return;
    }
    if (IsM5PlaintextHttpControlUrl(navigation_url) &&
        chromium_wasm_report_m5_plaintext_http_control_navigation() != 1) {
      ReportFatal(
          "host rejected the committed M5 plaintext HTTP control navigation "
          "report");
      return;
    }
    if (IsM5NetworkTestUrl(navigation_url) &&
        chromium_wasm_report_m5_navigation() != 1) {
      ReportFatal("host rejected the committed M5 HTTPS navigation report");
    }
  }

  void DocumentOnLoadCompletedInPrimaryMainFrame() override {
    const GURL& committed_url = web_contents()->GetLastCommittedURL();
    if (!IsObservedWasmHostUrl(committed_url)) {
      return;
    }
    // A public page is not a deterministic fixture and therefore exposes no
    // privileged page probe. Its navigation metadata is reported above.
    if (m5_public_navigation_finished_) {
      return;
    }
    ProbePage();
    probe_timer_.Start(FROM_HERE, base::Milliseconds(100), this,
                       &WasmHostObserver::ProbePage);
  }

  void DidFirstVisuallyNonEmptyPaint() override {
    if (!IsObservedWasmHostUrl(web_contents()->GetLastCommittedURL())) {
      return;
    }
    if (chromium_wasm_report_readiness(
            /*shell_ready=*/-1, /*surface_ready=*/-1,
            /*first_visually_nonempty_paint=*/1) != 1) {
      ReportFatal("host rejected the first visually nonempty paint report");
    }
  }

  void WebContentsDestroyed() override {
    probe_timer_.Stop();
    probe_in_flight_ = false;
    m5_public_navigation_handle_ = nullptr;
    weak_ptr_factory_.InvalidateWeakPtrs();
    Observe(nullptr);
  }

 private:
  void ProbePage() {
    if (probe_in_flight_ || !web_contents()) {
      return;
    }
    RenderFrameHost* frame = web_contents()->GetPrimaryMainFrame();
    if (!frame || !frame->IsRenderFrameLive()) {
      return;
    }

    const GURL& committed_url = web_contents()->GetLastCommittedURL();
    const bool is_m5_network_test = IsM5NetworkTestUrl(committed_url);
    const bool is_m5_plaintext_http_control =
        IsM5PlaintextHttpControlUrl(committed_url);
    probe_in_flight_ = true;
    frame->ExecuteJavaScriptForTests(
        is_m5_plaintext_http_control
            ? u"window.__chromiumWasmM5PlaintextHttpControlProbe ? "
              u"window.__chromiumWasmM5PlaintextHttpControlProbe() : ''"
            : is_m5_network_test
            ? u"window.__chromiumWasmM5Probe ? "
              u"window.__chromiumWasmM5Probe() : ''"
            : u"window.__chromiumWasmM4Probe ? "
              u"window.__chromiumWasmM4Probe() : "
              u"(window.__chromiumWasmM3Probe ? "
              u"window.__chromiumWasmM3Probe() : '')",
        base::BindOnce(&WasmHostObserver::OnPageProbe,
                       weak_ptr_factory_.GetWeakPtr(),
                       navigation_generation_, is_m5_network_test,
                       is_m5_plaintext_http_control),
        ISOLATED_WORLD_ID_GLOBAL);
  }

  void OnPageProbe(uint64_t navigation_generation,
                   bool is_m5_network_test,
                   bool is_m5_plaintext_http_control,
                   base::Value result) {
    if (navigation_generation != navigation_generation_) {
      return;
    }
    probe_in_flight_ = false;
    if (!result.is_string() || result.GetString().empty()) {
      return;
    }
    const int accepted = is_m5_plaintext_http_control
                             ? chromium_wasm_report_m5_plaintext_http_control_page_probe(
                                   result.GetString().c_str())
                             : is_m5_network_test
                                   ? chromium_wasm_report_m5_page_probe(
                                         result.GetString().c_str())
                                   : chromium_wasm_report_page_probe(
                                         result.GetString().c_str());
    if (accepted != 1) {
      ReportFatal("host rejected the deterministic page probe");
      probe_timer_.Stop();
    }
  }

  bool probe_in_flight_ = false;
  raw_ptr<NavigationHandle> m5_public_navigation_handle_ = nullptr;
  bool m5_public_navigation_finished_ = false;
  uint64_t navigation_generation_ = 0;
  base::RepeatingTimer probe_timer_;
  base::WeakPtrFactory<WasmHostObserver> weak_ptr_factory_{this};
};

class WasmHostState {
 public:
  WasmHostState() = default;

  WasmHostState(const WasmHostState&) = delete;
  WasmHostState& operator=(const WasmHostState&) = delete;

  scoped_refptr<base::SingleThreadTaskRunner> GetTaskRunner() {
    base::AutoLock lock(lock_);
    return task_runner_;
  }

  void SetTaskRunner(
      scoped_refptr<base::SingleThreadTaskRunner> task_runner) {
    base::AutoLock lock(lock_);
    task_runner_ = std::move(task_runner);
    m4_arrow_down_ = false;
    m4_key_a_ = false;
    m4_key_b_ = false;
    m4_backspace_ = false;
    m4_control_left_down_ = false;
    m4_copy_down_ = false;
    m4_paste_down_ = false;
  }

  bool PostM4KeyCommand(ui::DomCode physical_key,
                        bool down,
                        bool auto_repeat,
                        base::OnceClosure command) {
    base::AutoLock lock(lock_);
    // Track successfully posted physical-key transitions at the ABI boundary.
    // This keeps a direct caller from receiving queue success for a duplicate
    // record that the Ozone injector would otherwise drop. Repeat records are
    // limited to trusted held ArrowDown and Backspace keydowns.
    if (!IsM4KeyTransitionAllowedLocked(physical_key, down, auto_repeat) ||
        !task_runner_ ||
        !task_runner_->PostTask(FROM_HERE, std::move(command))) {
      return false;
    }
    RecordM4KeyTransitionLocked(physical_key, down, auto_repeat);
    return true;
  }

  void SetViewportSizeOnUiThread(const gfx::Size& viewport_size) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    CHECK(!viewport_size.IsEmpty());
    viewport_size_ = viewport_size;
  }

  bool ContainsViewportPointOnUiThread(const gfx::Point& point) const {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    return gfx::Rect(viewport_size_).Contains(point);
  }

  void SetInputInjector(
      std::unique_ptr<ui::SystemInputInjector> input_injector) {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    input_injector_ = std::move(input_injector);
  }

  ui::SystemInputInjector* GetInputInjectorOnUiThread() {
    DCHECK_CURRENTLY_ON(BrowserThread::UI);
    return input_injector_.get();
  }

  std::unique_ptr<WasmHostObserver> observer;
  std::unique_ptr<M5DevToolsNetworkRecorder> m5_devtools_network_recorder;
  std::unique_ptr<M5PublicDevToolsNetworkRecorder>
      m5_public_devtools_network_recorder;

 private:
  bool IsM4KeyTransitionAllowedLocked(ui::DomCode physical_key,
                                      bool down,
                                      bool auto_repeat) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (auto_repeat) {
      if (!down || !IsM4RepeatableDomCode(physical_key)) {
        return false;
      }
      return physical_key == ui::DomCode::ARROW_DOWN ? m4_arrow_down_
                                                       : m4_backspace_;
    }
    bool key_down = false;
    if (physical_key == ui::DomCode::ARROW_DOWN) {
      key_down = m4_arrow_down_;
    } else if (physical_key == ui::DomCode::US_A) {
      key_down = m4_key_a_;
    } else if (physical_key == ui::DomCode::US_B) {
      key_down = m4_key_b_;
    } else if (physical_key == ui::DomCode::BACKSPACE) {
      key_down = m4_backspace_;
    } else if (physical_key == ui::DomCode::CONTROL_LEFT) {
      key_down = m4_control_left_down_;
    } else if (physical_key == ui::DomCode::US_C) {
      key_down = m4_copy_down_;
    } else {
      DCHECK_EQ(physical_key, ui::DomCode::US_V);
      key_down = m4_paste_down_;
    }
    if (key_down == down) {
      return false;
    }
    if (physical_key == ui::DomCode::CONTROL_LEFT) {
      return true;
    }
    if (physical_key != ui::DomCode::US_C &&
        physical_key != ui::DomCode::US_V) {
      return true;
    }
    return !down || m4_control_left_down_;
  }

  void RecordM4KeyTransitionLocked(ui::DomCode physical_key,
                                   bool down,
                                   bool auto_repeat)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    if (auto_repeat) {
      DCHECK(IsM4RepeatableDomCode(physical_key));
      DCHECK(down);
      return;
    }
    if (physical_key == ui::DomCode::ARROW_DOWN) {
      m4_arrow_down_ = down;
    } else if (physical_key == ui::DomCode::US_A) {
      m4_key_a_ = down;
    } else if (physical_key == ui::DomCode::US_B) {
      m4_key_b_ = down;
    } else if (physical_key == ui::DomCode::BACKSPACE) {
      m4_backspace_ = down;
    } else if (physical_key == ui::DomCode::CONTROL_LEFT) {
      m4_control_left_down_ = down;
    } else if (physical_key == ui::DomCode::US_C) {
      m4_copy_down_ = down;
    } else if (physical_key == ui::DomCode::US_V) {
      m4_paste_down_ = down;
    }
  }

  base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_
      GUARDED_BY(lock_);
  bool m4_arrow_down_ GUARDED_BY(lock_) = false;
  bool m4_key_a_ GUARDED_BY(lock_) = false;
  bool m4_key_b_ GUARDED_BY(lock_) = false;
  bool m4_backspace_ GUARDED_BY(lock_) = false;
  bool m4_control_left_down_ GUARDED_BY(lock_) = false;
  bool m4_copy_down_ GUARDED_BY(lock_) = false;
  bool m4_paste_down_ GUARDED_BY(lock_) = false;
  std::unique_ptr<ui::SystemInputInjector> input_injector_;
  gfx::Size viewport_size_;
};

WasmHostState& GetWasmHostState() {
  static base::NoDestructor<WasmHostState> state;
  return *state;
}

bool PostHostCommand(base::OnceClosure command) {
  scoped_refptr<base::SingleThreadTaskRunner> task_runner =
      GetWasmHostState().GetTaskRunner();
  return task_runner && task_runner->PostTask(FROM_HERE, std::move(command));
}

Shell* GetSingleShell() {
  if (Shell::windows().size() != 1u) {
    ReportFatal("M3 host command requires exactly one Content Shell window");
    return nullptr;
  }
  return Shell::windows().front();
}

void ResizeOnUiThread(const gfx::Size& logical_size,
                      const gfx::Size& physical_size,
                      float device_scale_factor) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (!shell) {
    return;
  }

  // Updating DisplayList notifies Aura synchronously. Do not retain the
  // Content Shell or Aura pointers across it.
  if (!ui::WasmScreen::UpdatePrimaryDisplayForHostResize(
          physical_size, device_scale_factor)) {
    ReportFatal("M4 host resize has no live ozone_wasm screen");
    return;
  }

  shell = GetSingleShell();
  if (!shell) {
    return;
  }
  aura::Window* window = shell->window();
  if (!window || !window->GetHost()) {
    ReportFatal("M3 Content Shell has no Aura host window");
    return;
  }
  window->GetHost()->SetBoundsInPixels(gfx::Rect(physical_size));

  // Bounds observers may synchronously destroy the Aura host or its Shell.
  // Reacquire the sole shell before continuing the resize transaction.
  shell = GetSingleShell();
  if (!shell) {
    return;
  }
  // Aura and the compositor use physical pixels above, while Blink's
  // viewport stays in the host canvas's CSS-DIP coordinate space.
  shell->ResizeWebContentForTests(logical_size);
  GetWasmHostState().SetViewportSizeOnUiThread(physical_size);
}

void ClickOnUiThread(const gfx::Point& location) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  if (!GetWasmHostState().ContainsViewportPointOnUiThread(location)) {
    ReportFatal("M3 host click is outside the accepted viewport");
    return;
  }

  Shell* shell = GetSingleShell();
  if (!shell) {
    return;
  }

  WebContents* web_contents = shell->web_contents();
  RenderFrameHost* frame = web_contents->GetPrimaryMainFrame();
  RenderWidgetHost* widget = frame ? frame->GetRenderWidgetHost() : nullptr;
  if (!widget || !frame->IsRenderFrameLive()) {
    ReportFatal("M3 Content Shell has no live renderer for host input");
    return;
  }

  web_contents->Focus();
  const gfx::PointF position(location);
  blink::WebMouseEvent mouse_down(
      blink::WebInputEvent::Type::kMouseDown, position, position,
      blink::WebMouseEvent::Button::kLeft, /*click_count=*/1,
      blink::WebInputEvent::kNoModifiers, ui::EventTimeForNow());
  mouse_down.UpdateEventModifiersToMatchButton();
  widget->ForwardMouseEvent(mouse_down);

  blink::WebMouseEvent mouse_up(
      blink::WebInputEvent::Type::kMouseUp, position, position,
      blink::WebMouseEvent::Button::kLeft, /*click_count=*/1,
      blink::WebInputEvent::kNoModifiers, ui::EventTimeForNow());
  mouse_up.UpdateEventModifiersToMatchButton();
  widget->ForwardMouseEvent(mouse_up);
}

void DispatchDomPointerOnUiThread(DomPointerEventType type,
                                  const gfx::Point& location,
                                  ui::EventFlags button) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  WasmHostState& state = GetWasmHostState();
  if (!state.ContainsViewportPointOnUiThread(location)) {
    ReportFatal("M4 host pointer event is outside the accepted viewport");
    return;
  }

  if (type == DomPointerEventType::kDown) {
    Shell* shell = GetSingleShell();
    if (!shell) {
      return;
    }
    // The host canvas owns DOM focus. Give the in-process WebContents its
    // normal browser focus before Aura dispatches the trusted pointer press.
    shell->web_contents()->Focus();
  }

  ui::SystemInputInjector* input_injector =
      state.GetInputInjectorOnUiThread();
  if (!input_injector) {
    ReportFatal("M4 host pointer event has no Ozone input injector");
    return;
  }

  input_injector->MoveCursorTo(gfx::PointF(location));
  switch (type) {
    case DomPointerEventType::kMove:
      return;
    case DomPointerEventType::kDown:
      input_injector->InjectMouseButton(button, /*down=*/true);
      return;
    case DomPointerEventType::kUp:
      input_injector->InjectMouseButton(button, /*down=*/false);
      return;
  }
  NOTREACHED();
}

void DispatchDomPointerExitOnUiThread() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  // The Ozone source retains the former valid in-canvas point and platform
  // target. A host pointerleave has no coordinate within the Wasm display, so
  // it must not be modeled as an out-of-viewport mouse move.
  if (!ui::DispatchWasmMouseExit()) {
    LOG(WARNING) << "M4 host pointer exit had no active Wasm hover target";
  }
}

void DispatchDomWheelOnUiThread(const gfx::Point& location,
                                const gfx::Vector2d& dom_delta) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  WasmHostState& state = GetWasmHostState();
  if (!state.ContainsViewportPointOnUiThread(location)) {
    ReportFatal("M4 host wheel event is outside the accepted viewport");
    return;
  }

  ui::SystemInputInjector* input_injector =
      state.GetInputInjectorOnUiThread();
  if (!input_injector) {
    ReportFatal("M4 host wheel event has no Ozone input injector");
    return;
  }

  input_injector->MoveCursorTo(gfx::PointF(location));
  // DOM WheelEvent deltas are positive for right/down. Chromium wheel offsets
  // are positive for left/up, so convert at the host ABI boundary exactly once.
  input_injector->InjectMouseWheel(-dom_delta.x(), -dom_delta.y());
}

void DispatchDomKeyOnUiThread(ui::DomCode physical_key,
                              bool down,
                              bool auto_repeat) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  ui::SystemInputInjector* input_injector =
      GetWasmHostState().GetInputInjectorOnUiThread();
  if (!input_injector) {
    ReportFatal("M4 host raw key event has no Ozone input injector");
    return;
  }

  // The host submits explicit trusted DOM records. SystemInputInjector has no
  // separate repeat field: an accepted ArrowDown or Backspace repeat is
  // represented by a supplied duplicate keydown with auto-repeat suppression
  // disabled. The Wasm injector dispatches that one record with EF_IS_REPEAT;
  // it never owns or schedules an independent repeat timer.
  input_injector->InjectKeyEvent(physical_key, down,
                                 /*suppress_auto_repeat=*/!auto_repeat);
}

void DispatchM4TextInputOnUiThread(ui::WasmTextInputRecord record) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportTextInputDelivery(record, /*accepted=*/false);
    return;
  }

  aura::WindowTreeHostPlatform* host =
      aura::WindowTreeHostPlatform::GetHostForWindow(shell->window());
  if (!host) {
    ReportTextInputDelivery(record, /*accepted=*/false);
    return;
  }

  // The platform-specific registry resolves only this Aura/Ozone widget's
  // InputMethod. Generic SystemInputInjector is intentionally reserved for
  // native pointer, wheel, and physical-key events.
  const bool accepted = ui::DispatchWasmTextInput(host->GetAcceleratedWidget(),
                                                  record);
  ReportTextInputDelivery(record, accepted);
}

void LoadUrlOnUiThread(GURL url) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (shell) {
    shell->LoadURL(url);
  }
}

void LoadM5PublicUrlOnUiThread(GURL url) {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  WasmHostState& state = GetWasmHostState();
  if (!state.m5_public_devtools_network_recorder ||
      !state.m5_public_devtools_network_recorder->BeginWispEvidenceWindow()) {
    ReportFatal("could not start the M5 public WISP evidence window");
    return;
  }
  LoadUrlOnUiThread(std::move(url));
}

void DeactivateHostWindowOnUiThread() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportFatal("M4 host focus loss has no Content Shell window");
    return;
  }

  aura::Window* root_window = shell->window();
  aura::client::FocusClient* focus_client =
      aura::client::GetFocusClient(root_window);
  aura::WindowTreeHostPlatform* host =
      aura::WindowTreeHostPlatform::GetHostForWindow(root_window);
  if (!focus_client || !host || !host->platform_window()) {
    ReportFatal("M4 host focus loss has no Aura/Ozone window path");
    return;
  }

  // Clear any active Wasm composition before focus/activation callbacks can
  // detach its TextInputClient. The opaque Ozone boundary keeps Content Shell
  // independent of the concrete Wasm PlatformWindow implementation.
  ui::CancelWasmTextInputForWidget(host->GetAcceleratedWidget());

  // Composition cancellation can synchronously close the Content Shell
  // window. Do not retain Aura or PlatformWindow pointers across it.
  shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportFatal("M4 host composition cancellation closed Content Shell");
    return;
  }
  root_window = shell->window();
  focus_client = aura::client::GetFocusClient(root_window);
  host = aura::WindowTreeHostPlatform::GetHostForWindow(root_window);
  if (!focus_client || !host || !host->platform_window()) {
    ReportFatal("M4 host focus loss has no surviving Aura/Ozone window path");
    return;
  }

  // Dropping the Aura focus target reaches the regular renderer focus-loss
  // path. Deactivating the generic PlatformWindow separately clears
  // ozone_wasm's keyboard target without exposing a Wasm implementation type
  // to Content Shell.
  focus_client->FocusWindow(nullptr);

  // Focus notifications can synchronously close the Content Shell window.
  // Do not retain the old Aura or PlatformWindow pointers across them.
  shell = GetSingleShell();
  if (!shell || !shell->window()) {
    ReportFatal("M4 host focus loss closed the Content Shell window");
    return;
  }
  root_window = shell->window();
  host = aura::WindowTreeHostPlatform::GetHostForWindow(root_window);
  if (!host || !host->platform_window()) {
    ReportFatal("M4 host focus loss has no surviving Aura/Ozone window path");
    return;
  }
  host->platform_window()->Deactivate();
}

void ShutdownOnUiThread() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell::Shutdown();
}

}  // namespace

void InitializeWasmHostApi() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  Shell* shell = GetSingleShell();
  CHECK(shell);

  WasmHostState& state = GetWasmHostState();
  aura::Window* window = shell->window();
  CHECK(window);
  CHECK(window->GetHost());
  state.SetViewportSizeOnUiThread(
      window->GetHost()->GetBoundsInPixels().size());
  state.SetTaskRunner(base::SingleThreadTaskRunner::GetCurrentDefault());
  std::unique_ptr<ui::SystemInputInjector> input_injector =
      ui::OzonePlatform::GetInstance()->CreateSystemInputInjector();
  if (!input_injector) {
    ReportFatal("ozone_wasm did not create the M4 input injector");
    return;
  }
  state.SetInputInjector(std::move(input_injector));
  state.observer = std::make_unique<WasmHostObserver>(shell->web_contents());
  if (IsWasmM5NetworkTestModeEnabled()) {
    state.m5_devtools_network_recorder =
        std::make_unique<M5DevToolsNetworkRecorder>();
    if (!state.m5_devtools_network_recorder->Start(shell->web_contents())) {
      state.m5_devtools_network_recorder.reset();
      ReportFatal("could not start the M5 DevTools Network recorder");
      return;
    }
  }
  if (IsWasmM5PublicNetworkTestModeEnabled()) {
    state.m5_public_devtools_network_recorder =
        std::make_unique<M5PublicDevToolsNetworkRecorder>();
    if (!state.m5_public_devtools_network_recorder->Start(
            shell->web_contents())) {
      state.m5_public_devtools_network_recorder.reset();
      ReportFatal("could not start the M5 public DevTools Network recorder");
      return;
    }
  }
  if (chromium_wasm_report_readiness(
          /*shell_ready=*/1, /*surface_ready=*/-1,
          /*first_visually_nonempty_paint=*/-1) != 1) {
    ReportFatal("host rejected the Content Shell readiness report");
  }
}

void EnableWasmM5NetworkTestModeForTesting() {
  GetWasmM5NetworkTestMode().store(true, std::memory_order_relaxed);
}

void EnableWasmM5PublicNetworkTestModeForTesting() {
  GetWasmM5PublicNetworkTestMode().store(true, std::memory_order_relaxed);
}

void ShutdownWasmHostApi() {
  DCHECK_CURRENTLY_ON(BrowserThread::UI);
  WasmHostState& state = GetWasmHostState();
  state.m5_public_devtools_network_recorder.reset();
  state.m5_devtools_network_recorder.reset();
  state.observer.reset();
  state.SetInputInjector(nullptr);
  state.SetTaskRunner(nullptr);
}

}  // namespace content

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_resize(
    int width,
    int height,
    double device_pixel_ratio) {
  if (width <= 0 || width > content::kMaximumCanvasDimension || height <= 0 ||
      height > content::kMaximumCanvasDimension ||
      (device_pixel_ratio != 1.0 && device_pixel_ratio != 2.0)) {
    return 0;
  }
  const int device_scale_factor = static_cast<int>(device_pixel_ratio);
  const int64_t physical_width =
      static_cast<int64_t>(width) * device_scale_factor;
  const int64_t physical_height =
      static_cast<int64_t>(height) * device_scale_factor;
  if (physical_width > content::kMaximumCanvasDimension ||
      physical_height > content::kMaximumCanvasDimension) {
    return 0;
  }
  const int64_t canvas_bytes =
      physical_width * physical_height * 4;
  if (canvas_bytes * 2 > content::kMaximumCanvasStorageBytes) {
    return 0;
  }
  return content::PostHostCommand(base::BindOnce(
             &content::ResizeOnUiThread, gfx::Size(width, height),
             gfx::Size(static_cast<int>(physical_width),
                       static_cast<int>(physical_height)),
             static_cast<float>(device_scale_factor)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_click(int x,
                                                  int y,
                                                  int button) {
  if (button != 0 || x < 0 || y < 0) {
    return 0;
  }
  return content::PostHostCommand(
             base::BindOnce(&content::ClickOnUiThread, gfx::Point(x, y)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_pointer(int type,
                                                    int x,
                                                    int y,
                                                    int button) {
  if (type < static_cast<int>(content::DomPointerEventType::kMove) ||
      type > static_cast<int>(content::DomPointerEventType::kUp) ||
      (button != 0 && button != 1 && button != 2) || x < 0 || y < 0) {
    return 0;
  }
  const ui::EventFlags mouse_button =
      button == 0 ? ui::EF_LEFT_MOUSE_BUTTON
                  : button == 1 ? ui::EF_MIDDLE_MOUSE_BUTTON
                                : ui::EF_RIGHT_MOUSE_BUTTON;
  const auto event_type = static_cast<content::DomPointerEventType>(type);
  return content::PostHostCommand(base::BindOnce(
             &content::DispatchDomPointerOnUiThread, event_type,
             gfx::Point(x, y), mouse_button))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_pointer_exit() {
  return content::PostHostCommand(
             base::BindOnce(&content::DispatchDomPointerExitOnUiThread))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_wheel(int x,
                                                  int y,
                                                  int delta_x,
                                                  int delta_y) {
  if (x < 0 || y < 0 || (delta_x == 0 && delta_y == 0) ||
      delta_x == std::numeric_limits<int>::min() ||
      delta_y == std::numeric_limits<int>::min()) {
    return 0;
  }
  return content::PostHostCommand(base::BindOnce(
             &content::DispatchDomWheelOnUiThread, gfx::Point(x, y),
             gfx::Vector2d(delta_x, delta_y)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_key(const char* code, int down) {
  if (!code || (down != 0 && down != 1)) {
    return 0;
  }
  const size_t length =
      strnlen(code, content::kMaximumM4DomCodeLength + 1);
  const std::string_view code_string(code, length);
  if (code_string != content::kM4NavigationDomCode &&
      code_string != content::kM4PrintableKeyADomCode &&
      code_string != content::kM4PrintableKeyBDomCode &&
      code_string != content::kM4BackspaceDomCode &&
      code_string != content::kM4ControlLeftDomCode &&
      code_string != content::kM4CopyDomCode &&
      code_string != content::kM4PasteDomCode) {
    return 0;
  }
  const ui::DomCode physical_key =
      ui::KeycodeConverter::CodeStringToDomCode(code_string);
  if (!content::IsSupportedM4DomCode(physical_key)) {
    return 0;
  }
  return content::GetWasmHostState().PostM4KeyCommand(
             physical_key, down == 1, /*auto_repeat=*/false,
             base::BindOnce(&content::DispatchDomKeyOnUiThread, physical_key,
                            down == 1, /*auto_repeat=*/false))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_arrow_down_repeat() {
  return content::GetWasmHostState().PostM4KeyCommand(
             ui::DomCode::ARROW_DOWN, /*down=*/true, /*auto_repeat=*/true,
             base::BindOnce(&content::DispatchDomKeyOnUiThread,
                            ui::DomCode::ARROW_DOWN, /*down=*/true,
                            /*auto_repeat=*/true))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_backspace_repeat() {
  return content::GetWasmHostState().PostM4KeyCommand(
             ui::DomCode::BACKSPACE, /*down=*/true, /*auto_repeat=*/true,
             base::BindOnce(&content::DispatchDomKeyOnUiThread,
                            ui::DomCode::BACKSPACE, /*down=*/true,
                            /*auto_repeat=*/true))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_url(const char* data_url) {
  if (!data_url) {
    return 0;
  }
  const size_t length = strnlen(data_url, content::kMaximumDataUrlBytes + 1);
  if (length == 0 || length > content::kMaximumDataUrlBytes) {
    return 0;
  }
  GURL url(std::string(data_url, length));
  if (!url.is_valid() || !url.SchemeIs(url::kDataScheme)) {
    return 0;
  }
  return content::PostHostCommand(
             base::BindOnce(&content::LoadUrlOnUiThread, std::move(url)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_url(const char* test_url) {
  if (!test_url || !content::IsWasmM5NetworkTestModeEnabled()) {
    return 0;
  }
  const size_t length = strnlen(test_url, content::kMaximumDataUrlBytes + 1);
  if (length == 0 || length > content::kMaximumDataUrlBytes) {
    return 0;
  }
  GURL url(std::string(test_url, length));
  if (!content::IsM5NetworkTestUrl(url)) {
    return 0;
  }
  return content::PostHostCommand(
             base::BindOnce(&content::LoadUrlOnUiThread, std::move(url)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_plaintext_http_control_url(
    const char* test_url) {
  if (!test_url || !content::IsWasmM5NetworkTestModeEnabled()) {
    return 0;
  }
  const size_t length = strnlen(test_url, content::kMaximumDataUrlBytes + 1);
  if (length == 0 || length > content::kMaximumDataUrlBytes) {
    return 0;
  }
  GURL url(std::string(test_url, length));
  if (!content::IsM5PlaintextHttpControlUrl(url)) {
    return 0;
  }
  return content::PostHostCommand(
             base::BindOnce(&content::LoadUrlOnUiThread, std::move(url)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_load_m5_public_url(
    const char* public_url) {
  if (!public_url || !content::IsWasmM5PublicNetworkTestModeEnabled()) {
    return 0;
  }
  const size_t length =
      strnlen(public_url, content::kMaximumM5PublicUrlBytes + 1);
  if (length == 0 || length > content::kMaximumM5PublicUrlBytes) {
    return 0;
  }
  GURL url(std::string(public_url, length));
  if (!content::IsM5PublicHttpsUrl(url)) {
    return 0;
  }
  return content::PostHostCommand(
             base::BindOnce(&content::LoadM5PublicUrlOnUiThread, std::move(url)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_text_input(
    int action,
    int session_id,
    int sequence,
    const uint8_t* text_utf8,
    int text_utf8_bytes,
    int selection_start,
    int selection_end) {
  ui::WasmTextInputRecord record;
  if (!content::CopyM4TextInputRecord(
          action, session_id, sequence, text_utf8, text_utf8_bytes,
          selection_start, selection_end, &record)) {
    return 0;
  }
  // |record| owns its UTF-16 copy before this task hops off the proxying host
  // call. It never retains a JavaScript heap view or a Wasm pointer.
  return content::PostHostCommand(base::BindOnce(
             &content::DispatchM4TextInputOnUiThread, std::move(record)))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_deactivate() {
  return content::PostHostCommand(
             base::BindOnce(&content::DeactivateHostWindowOnUiThread))
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_host_shutdown() {
  return content::PostHostCommand(
             base::BindOnce(&content::ShutdownOnUiThread))
             ? 1
             : 0;
}

}  // extern "C"

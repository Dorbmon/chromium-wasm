// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_cookie_smoke.h"

#include <cstdio>
#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/no_destructor.h"
#include "base/strings/strcat.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/browser/wasm/wasm_profile.h"
#include "content/public/browser/storage_partition.h"
#include "net/cookies/canonical_cookie.h"
#include "net/cookies/cookie_access_result.h"
#include "net/cookies/cookie_inclusion_status.h"
#include "net/cookies/cookie_options.h"
#include "net/cookies/cookie_partition_key_collection.h"
#include "services/network/public/mojom/cookie_manager.mojom.h"
#include "url/gurl.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_cookie_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kMarkerPrefix[] = "CHROMIUM_WASM_M7_PREFS:";
constexpr char kCookieName[] = "wasm_m7_profile_cookie";
constexpr char kCookieUrl[] = "https://wasm-profile-cookie.test/";

void EmitDigestMarker(const char* marker, const std::string& digest) {
  std::fprintf(stderr, "%s%s sha256=%s\n", kMarkerPrefix, marker,
               digest.c_str());
  std::fflush(stderr);
}

bool HasExpectedCookie(const net::CookieAccessResultList& cookies,
                       const std::string& expected_value) {
  for (const auto& result : cookies) {
    const net::CanonicalCookie& cookie = result.cookie;
    if (result.access_result.status.IsInclude() &&
        cookie.Name() == kCookieName && cookie.Value() == expected_value &&
        cookie.Path() == "/" && cookie.SecureAttribute() &&
        cookie.IsHttpOnly() && cookie.IsPersistent()) {
      return true;
    }
  }
  return false;
}

const net::CanonicalCookie* FindExpectedCookie(
    const net::CookieAccessResultList& cookies,
    const std::string& expected_value) {
  for (const auto& result : cookies) {
    const net::CanonicalCookie& cookie = result.cookie;
    if (result.access_result.status.IsInclude() &&
        cookie.Name() == kCookieName && cookie.Value() == expected_value &&
        cookie.Path() == "/" && cookie.SecureAttribute() &&
        cookie.IsHttpOnly() && cookie.IsPersistent()) {
      return &cookie;
    }
  }
  return nullptr;
}

bool HasAnyTestCookie(const net::CookieAccessResultList& cookies) {
  for (const auto& result : cookies) {
    if (result.cookie.Name() == kCookieName) {
      return true;
    }
  }
  return false;
}

class WasmProfileCookieSmokeState {
 public:
  WasmProfileCookieSmokeState() = default;
  WasmProfileCookieSmokeState(const WasmProfileCookieSmokeState&) = delete;
  WasmProfileCookieSmokeState& operator=(const WasmProfileCookieSmokeState&) =
      delete;
  ~WasmProfileCookieSmokeState() = default;

  bool Start(WasmProfile* profile,
             WasmProfilePreferencesCookieSmokeInput input,
             base::OnceCallback<void(bool success)> completion) {
    if (!IsWasmProfilePreferencesCookieSmokeEnabled() || !profile ||
        !completion || started_) {
      return false;
    }

    started_ = true;
    profile_ = profile;
    input_ = std::move(input);
    completion_ = std::move(completion);
    if (!HasValidInput()) {
      Finish(false);
      return true;
    }

    switch (input_.mode) {
      case WasmProfilePreferencesCookieSmokeInput::Mode::kWrite:
        ReadInitial(std::nullopt);
        break;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyAndWrite:
        ReadInitial(input_.token_a);
        break;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyB:
        ReadInitial(input_.token_b);
        break;
    }
    return true;
  }

  bool DidSucceed() const { return started_ && completed_ && succeeded_; }

 private:
  network::mojom::CookieManager* GetCookieManager() const {
    if (!profile_) {
      return nullptr;
    }
    content::StoragePartition* storage_partition =
        profile_->GetDefaultStoragePartition();
    return storage_partition
               ? storage_partition->GetCookieManagerForBrowserProcess()
               : nullptr;
  }

  bool HasValidInput() const {
    switch (input_.mode) {
      case WasmProfilePreferencesCookieSmokeInput::Mode::kWrite:
        return !input_.token_a.empty() && !input_.token_a_digest.empty() &&
               input_.token_b.empty() && input_.token_b_digest.empty();
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyAndWrite:
        return !input_.token_a.empty() && !input_.token_a_digest.empty() &&
               !input_.token_b.empty() && !input_.token_b_digest.empty() &&
               input_.token_a != input_.token_b;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyB:
        return input_.token_a.empty() && input_.token_a_digest.empty() &&
               !input_.token_b.empty() && !input_.token_b_digest.empty();
    }
    return false;
  }

  void ReadInitial(std::optional<std::string> expected_value) {
    network::mojom::CookieManager* cookie_manager = GetCookieManager();
    if (!cookie_manager) {
      Finish(false);
      return;
    }
    cookie_manager->GetCookieList(
        GURL(kCookieUrl), net::CookieOptions::MakeAllInclusive(),
        net::CookiePartitionKeyCollection(),
        base::BindOnce(&WasmProfileCookieSmokeState::OnInitialRead,
                       base::Unretained(this), std::move(expected_value)));
  }

  void OnInitialRead(std::optional<std::string> expected_value,
                     const net::CookieAccessResultList& included,
                     const net::CookieAccessResultList& excluded) {
    if (completed_) {
      return;
    }
    const net::CanonicalCookie* expected_cookie =
        expected_value ? FindExpectedCookie(included, *expected_value)
                       : nullptr;
    const bool has_expected = expected_cookie != nullptr;
    const bool has_any = HasAnyTestCookie(included) || HasAnyTestCookie(excluded);
    if ((expected_value && !has_expected) || (!expected_value && has_any)) {
      Finish(false);
      return;
    }

    switch (input_.mode) {
      case WasmProfilePreferencesCookieSmokeInput::Mode::kWrite:
        WriteAndValidate(input_.token_a, input_.token_a_digest,
                         "COOKIE_A_WRITE_FLUSHED");
        return;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyAndWrite:
        EmitDigestMarker("COOKIE_A_READ_OK", input_.token_a_digest);
        WriteAndValidate(input_.token_b, input_.token_b_digest,
                         "COOKIE_B_WRITE_FLUSHED");
        return;
      case WasmProfilePreferencesCookieSmokeInput::Mode::kVerifyB:
        EmitDigestMarker("COOKIE_B_READ_OK", input_.token_b_digest);
        DeleteAndFlush(*expected_cookie);
        return;
    }
  }

  void WriteAndValidate(std::string expected_value,
                        std::string expected_digest,
                        const char* flushed_marker) {
    net::CookieInclusionStatus syntax_status;
    pending_cookie_ = net::CanonicalCookie::Create(
        GURL(kCookieUrl),
        base::StrCat({kCookieName, "=", expected_value,
                      "; Max-Age=31536000; Path=/; Secure; HttpOnly; "
                      "SameSite=Lax"}),
        base::Time::Now(), /*server_time=*/std::nullopt,
        /*cookie_partition_key=*/std::nullopt, net::CookieSourceType::kOther,
        &syntax_status);
    network::mojom::CookieManager* cookie_manager = GetCookieManager();
    if (!pending_cookie_ || !syntax_status.IsInclude() ||
        !pending_cookie_->IsPersistent() || !cookie_manager) {
      Finish(false);
      return;
    }

    cookie_manager->SetCanonicalCookie(
        *pending_cookie_, GURL(kCookieUrl),
        net::CookieOptions::MakeAllInclusive(),
        base::BindOnce(&WasmProfileCookieSmokeState::OnSetCookie,
                       base::Unretained(this), std::move(expected_value),
                       std::move(expected_digest), flushed_marker));
  }

  void OnSetCookie(std::string expected_value,
                   std::string expected_digest,
                   const char* flushed_marker,
                   net::CookieAccessResult access_result) {
    pending_cookie_.reset();
    if (completed_ || !access_result.status.IsInclude()) {
      Finish(false);
      return;
    }

    network::mojom::CookieManager* cookie_manager = GetCookieManager();
    if (!cookie_manager) {
      Finish(false);
      return;
    }
    cookie_manager->GetCookieList(
        GURL(kCookieUrl), net::CookieOptions::MakeAllInclusive(),
        net::CookiePartitionKeyCollection(),
        base::BindOnce(&WasmProfileCookieSmokeState::OnWriteReadback,
                       base::Unretained(this), std::move(expected_value),
                       std::move(expected_digest), flushed_marker));
  }

  void OnWriteReadback(std::string expected_value,
                       std::string expected_digest,
                       const char* flushed_marker,
                       const net::CookieAccessResultList& included,
                       const net::CookieAccessResultList& excluded) {
    if (completed_ || !HasExpectedCookie(included, expected_value) ||
        HasAnyTestCookie(excluded)) {
      Finish(false);
      return;
    }
    FlushAndEmit(flushed_marker, std::move(expected_digest));
  }

  void DeleteAndFlush(const net::CanonicalCookie& cookie) {
    network::mojom::CookieManager* cookie_manager = GetCookieManager();
    if (!cookie_manager) {
      Finish(false);
      return;
    }
    // Delete the fixed test cookie only after the third fresh process has
    // observed it. A clean terminal state makes a subsequent independent
    // outer-reload run reject neither leaked state nor a false write success.
    cookie_manager->DeleteCanonicalCookie(
        cookie, base::BindOnce(&WasmProfileCookieSmokeState::OnDeleted,
                               base::Unretained(this)));
  }

  void OnDeleted(bool success) {
    if (completed_ || !success) {
      Finish(false);
      return;
    }
    FlushAndClose();
  }

  void FlushAndClose() {
    network::mojom::CookieManager* cookie_manager = GetCookieManager();
    if (!cookie_manager) {
      Finish(false);
      return;
    }
    cookie_manager->FlushCookieStore(base::BindOnce(
        &WasmProfileCookieSmokeState::OnFlushed, base::Unretained(this),
        /*marker=*/nullptr, std::string()));
  }

  void FlushAndEmit(const char* marker, std::string digest) {
    network::mojom::CookieManager* cookie_manager = GetCookieManager();
    if (!cookie_manager || !marker || digest.empty()) {
      Finish(false);
      return;
    }
    cookie_manager->FlushCookieStore(base::BindOnce(
        &WasmProfileCookieSmokeState::OnFlushed, base::Unretained(this),
        marker, std::move(digest)));
  }

  void OnFlushed(const char* marker, std::string digest) {
    if (completed_) {
      return;
    }
    if (marker) {
      EmitDigestMarker(marker, digest);
    }
    CloseAndFinish();
  }

  void CloseAndFinish() {
    network::mojom::CookieManager* cookie_manager = GetCookieManager();
    if (!cookie_manager) {
      Finish(false);
      return;
    }
    // This test-only Mojo method is a true close fence: it calls the real
    // SQLitePersistentCookieStore backend close and returns only from its
    // background-sequence completion. No profile storage lease may be handed
    // off before this callback.
    cookie_manager->CloseCookieStoreForTesting(base::BindOnce(
        &WasmProfileCookieSmokeState::OnBackendClosed,
        base::Unretained(this)));
  }

  void OnBackendClosed(bool success) {
    if (completed_ || !success) {
      Finish(false);
      return;
    }
    std::fprintf(stderr, "%sCOOKIE_BACKEND_CLOSED\n", kMarkerPrefix);
    std::fflush(stderr);
    Finish(true);
  }

  void Finish(bool success) {
    if (completed_) {
      return;
    }
    completed_ = true;
    succeeded_ = success;
    pending_cookie_.reset();
    input_.token_a.clear();
    input_.token_b.clear();
    if (completion_) {
      std::move(completion_).Run(success);
    }
  }

  bool started_ = false;
  bool completed_ = false;
  bool succeeded_ = false;
  raw_ptr<WasmProfile> profile_ = nullptr;
  WasmProfilePreferencesCookieSmokeInput input_;
  std::unique_ptr<net::CanonicalCookie> pending_cookie_;
  base::OnceCallback<void(bool success)> completion_;
};

WasmProfileCookieSmokeState& GetWasmProfileCookieSmokeState() {
  static base::NoDestructor<WasmProfileCookieSmokeState> state;
  return *state;
}

}  // namespace

bool StartWasmProfileCookieSmoke(
    WasmProfile* profile,
    WasmProfilePreferencesCookieSmokeInput input,
    base::OnceCallback<void(bool success)> completion) {
  return GetWasmProfileCookieSmokeState().Start(
      profile, std::move(input), std::move(completion));
}

bool DidWasmProfileCookieSmokeSucceed() {
  return GetWasmProfileCookieSmokeState().DidSucceed();
}

}  // namespace chrome

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <algorithm>
#include <optional>
#include <utility>

#include "base/check.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_window/public/browser_collection_observer.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_manager_service.cc must only be built for Wasm"
#endif

BrowserManagerService::BrowserManagerService(Profile* profile)
    : ProfileBrowserCollection(profile) {
  AddObserver(GlobalBrowserCollection::GetInstance()->GetPlatformDelegate());
}

BrowserManagerService::~BrowserManagerService() = default;

void BrowserManagerService::Shutdown() {
  CHECK(browsers_and_subscriptions_for_testing_.empty());

  while (!browsers_and_subscriptions_.empty()) {
    BrowserAndSubscriptions entry =
        std::move(browsers_and_subscriptions_.back());
    browsers_and_subscriptions_.pop_back();
    std::erase(browsers_activation_order_, entry.browser.get());

    // `entry` is destroyed here. Member destruction order ensures browser is
    // released before subscriptions are destroyed.
  }

  browsers_activation_order_.clear();
}

bool BrowserManagerService::IsEmpty() const {
  return GetSize() == 0;
}

size_t BrowserManagerService::GetSize() const {
  // TODO(crbug.com/512607471): Remove this once the pending-delete state has
  // been removed.
  CHECK(browsers_and_subscriptions_.empty() ||
        browsers_and_subscriptions_for_testing_.empty());
  size_t size = 0;
  for (const auto& entry : browsers_and_subscriptions_) {
    if (!entry.browser->IsDeleteScheduled()) {
      size++;
    }
  }
  for (const auto& entry : browsers_and_subscriptions_for_testing_) {
    if (!entry.browser->IsDeleteScheduled()) {
      size++;
    }
  }
  return size;
}

void BrowserManagerService::AddBrowser(
    std::unique_ptr<BrowserWindowInterface> browser) {
  CHECK(browsers_and_subscriptions_for_testing_.empty());
  BrowserWindowInterface* const browser_ptr = browser.get();
  // Prefer push_back, see totw/112.
  // NOLINTNEXTLINE(modernize-use-emplace)
  browsers_and_subscriptions_.push_back(BrowserAndSubscriptions(
      std::move(browser),
      browser_ptr->RegisterDidBecomeActive(base::BindRepeating(
          &BrowserManagerService::OnBrowserActivated, base::Unretained(this))),
      browser_ptr->RegisterDidBecomeInactive(
          base::BindRepeating(&BrowserManagerService::OnBrowserDeactivated,
                              base::Unretained(this))),
      browser_ptr->RegisterBrowserDidClose(base::BindRepeating(
          &BrowserManagerService::OnBrowserClosed, base::Unretained(this)))));

  // Push the browser to the back of the activation order list. It is moved to
  // the front when activation eventually occurs.
  browsers_activation_order_.push_back(browser_ptr);

  base::WeakPtr<BrowserWindowInterface> browser_weak_ptr =
      browser_ptr->GetWeakPtr();
  for (BrowserCollectionObserver& observer : observers()) {
    if (browser_weak_ptr) {
      observer.OnBrowserCreated(browser_weak_ptr.get());
    }
  }
}

void BrowserManagerService::DeleteBrowser(
    BrowserWindowInterface* removed_browser) {
  // Extract the browser before deleting it to avoid a use-after-free if its
  // teardown sends a synchronous close notification.
  std::optional<BrowserAndSubscriptions> target_browser_and_subscriptions;
  auto it = std::ranges::find_if(
      browsers_and_subscriptions_,
      [&removed_browser](
          const BrowserAndSubscriptions& browser_and_subscriptions) {
        return browser_and_subscriptions.browser.get() == removed_browser;
      });
  if (it == browsers_and_subscriptions_.end()) {
    return;
  }

  std::erase(browsers_activation_order_, it->browser.get());
  target_browser_and_subscriptions = std::move(*it);
  browsers_and_subscriptions_.erase(it);

  // WasmProfile currently supports only a regular profile. Incognito profile
  // destruction and desktop application-termination notifications have no
  // supported M6 lifecycle yet; main-parts owns process shutdown instead.
  CHECK(!profile_->IsOffTheRecord());
  target_browser_and_subscriptions->browser.reset();
}

void BrowserManagerService::AddBrowserForTesting(
    BrowserWindowInterface* browser) {
  // Tests manually creating owned browsers must create all their instances
  // via `Browser::DeprecatedCreateOwnedForTesting()`, which calls into this
  // method.
  CHECK(browsers_and_subscriptions_.empty());
  // Prefer push_back, see totw/112.
  // NOLINTNEXTLINE(modernize-use-emplace)
  browsers_and_subscriptions_for_testing_.push_back(
      UnownedBrowserAndSubscriptions(
          browser,
          browser->RegisterDidBecomeActive(
              base::BindRepeating(&BrowserManagerService::OnBrowserActivated,
                                  base::Unretained(this))),
          browser->RegisterDidBecomeInactive(
              base::BindRepeating(&BrowserManagerService::OnBrowserDeactivated,
                                  base::Unretained(this))),
          browser->RegisterBrowserDidClose(base::BindRepeating(
              &BrowserManagerService::OnBrowserClosedForTesting,
              base::Unretained(this)))));

  browsers_activation_order_.push_back(browser);
  observers().Notify(&BrowserCollectionObserver::OnBrowserCreated, browser);
}

BrowserCollection::BrowserVector BrowserManagerService::GetBrowsers(
    Order order) {
  CHECK(order == Order::kCreation || order == Order::kActivation);
  BrowserCollection::BrowserVector browsers;
  // TODO(crbug.com/512607471): Remove this once the pending-delete state has
  // been removed.
  if (order == Order::kActivation) {
    browsers.reserve(browsers_activation_order_.size());
    for (raw_ptr<BrowserWindowInterface>& browser :
         browsers_activation_order_) {
      if (!browser->IsDeleteScheduled()) {
        browsers.push_back(browser);
      }
    }
    return browsers;
  }

  CHECK(browsers_and_subscriptions_.empty() ||
        browsers_and_subscriptions_for_testing_.empty());
  if (!browsers_and_subscriptions_for_testing_.empty()) {
    CHECK(browsers_and_subscriptions_.empty());
    browsers.reserve(browsers_and_subscriptions_for_testing_.size());
    for (auto& browser_and_subscriptions :
         browsers_and_subscriptions_for_testing_) {
      if (!browser_and_subscriptions.browser->IsDeleteScheduled()) {
        browsers.push_back(browser_and_subscriptions.browser);
      }
    }
  } else {
    browsers.reserve(browsers_and_subscriptions_.size());
    for (auto& browser_and_subscriptions : browsers_and_subscriptions_) {
      if (!browser_and_subscriptions.browser->IsDeleteScheduled()) {
        browsers.push_back(browser_and_subscriptions.browser.get());
      }
    }
  }

  return browsers;
}

void BrowserManagerService::OnBrowserActivated(
    BrowserWindowInterface* browser) {
  auto it = std::ranges::find(browsers_activation_order_, browser);
  CHECK(it != browsers_activation_order_.end());
  std::rotate(browsers_activation_order_.begin(), it, it + 1);

  for (BrowserCollectionObserver& observer : observers()) {
    observer.OnBrowserActivated(browser);
  }
}

void BrowserManagerService::OnBrowserDeactivated(
    BrowserWindowInterface* browser) {
  for (BrowserCollectionObserver& observer : observers()) {
    observer.OnBrowserDeactivated(browser);
  }
}

void BrowserManagerService::OnBrowserClosed(BrowserWindowInterface* browser) {
  for (BrowserCollectionObserver& observer : observers()) {
    observer.OnBrowserClosed(browser);
  }
}

void BrowserManagerService::OnBrowserClosedForTesting(
    BrowserWindowInterface* browser) {
  CHECK(browsers_and_subscriptions_.empty());
  auto it = std::ranges::find_if(
      browsers_and_subscriptions_for_testing_,
      [browser](
          const UnownedBrowserAndSubscriptions& browser_and_subscriptions) {
        return browser_and_subscriptions.browser == browser;
      });
  if (it != browsers_and_subscriptions_for_testing_.end()) {
    std::erase(browsers_activation_order_, browser);
    browsers_and_subscriptions_for_testing_.erase(it);
    observers().Notify(&BrowserCollectionObserver::OnBrowserClosed, browser);
  }
}

BrowserManagerService::BrowserAndSubscriptions::BrowserAndSubscriptions(
    std::unique_ptr<BrowserWindowInterface> browser,
    base::CallbackListSubscription activated_subscription,
    base::CallbackListSubscription deactivated_subscription,
    base::CallbackListSubscription closed_subscription)
    : activated_subscription(std::move(activated_subscription)),
      deactivated_subscription(std::move(deactivated_subscription)),
      closed_subscription(std::move(closed_subscription)),
      browser(std::move(browser)) {}

BrowserManagerService::BrowserAndSubscriptions::BrowserAndSubscriptions(
    BrowserAndSubscriptions&&) = default;

BrowserManagerService::BrowserAndSubscriptions::~BrowserAndSubscriptions() =
    default;

BrowserManagerService::UnownedBrowserAndSubscriptions::
    UnownedBrowserAndSubscriptions(
        BrowserWindowInterface* browser,
        base::CallbackListSubscription activated_subscription,
        base::CallbackListSubscription deactivated_subscription,
        base::CallbackListSubscription closed_subscription)
    : browser(browser),
      activated_subscription(std::move(activated_subscription)),
      deactivated_subscription(std::move(deactivated_subscription)),
      closed_subscription(std::move(closed_subscription)) {}

BrowserManagerService::UnownedBrowserAndSubscriptions::
    UnownedBrowserAndSubscriptions(UnownedBrowserAndSubscriptions&&) = default;

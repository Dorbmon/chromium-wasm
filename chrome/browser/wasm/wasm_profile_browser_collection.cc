// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/check_deref.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/browser_window/public/profile_browser_collection.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_browser_collection.cc must only be built for Wasm"
#endif

ProfileBrowserCollection::ProfileBrowserCollection(Profile* profile)
    : profile_(CHECK_DEREF(profile)) {}

ProfileBrowserCollection::~ProfileBrowserCollection() = default;

BrowserWindowInterface* ProfileBrowserCollection::FindTabbedBrowser(
    bool match_original_profiles) {
  Profile* original =
      match_original_profiles ? profile_->GetOriginalProfile() : nullptr;
  BrowserWindowInterface* match = nullptr;

  auto find = [&match, original](BrowserWindowInterface* browser) {
    if (browser->GetType() != BrowserWindowInterface::TYPE_NORMAL ||
        browser->IsDeleteScheduled()) {
      return true;
    }
    if (original && browser->GetProfile()->GetOriginalProfile() != original) {
      return true;
    }

    // A Wasm embedding has one Ozone surface rather than a set of native
    // workspaces, so every live browser belongs to the current workspace.
    match = browser;
    return false;
  };

  if (match_original_profiles) {
    GlobalBrowserCollection::GetInstance()->ForEach(find, Order::kActivation);
  } else {
    ForEach(find, Order::kActivation);
  }
  return match;
}

size_t ProfileBrowserCollection::GetOffTheRecordBrowserCount() {
  size_t count = 0;
  auto count_browsers = [&count](BrowserWindowInterface* browser) {
    if (browser->GetType() == BrowserWindowInterface::Type::TYPE_DEVTOOLS) {
      return true;
    }
    ++count;
    return true;
  };
  for (Profile* otr : profile_->GetAllOffTheRecordProfiles()) {
    if (ProfileBrowserCollection* otr_collection = GetForProfile(otr)) {
      otr_collection->ForEach(count_browsers);
    }
  }
  return count;
}

// static
ProfileBrowserCollection* ProfileBrowserCollection::GetForProfile(
    Profile* profile) {
  return BrowserManagerServiceFactory::GetForProfile(profile);
}

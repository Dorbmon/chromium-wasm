// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <memory>

#include "base/no_destructor.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_manager_service.h"
#include "chrome/browser/ui/browser_manager_service_factory.h"
#include "chrome/browser/wasm/wasm_browser_manager.h"
#include "components/keyed_service/content/browser_context_dependency_manager.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_manager_service_factory.cc must only be built for Wasm"
#endif

void EnsureWasmBrowserKeyedServiceFactoriesBuilt() {
  // This must precede WasmProfile's base-class construction. See the
  // BrowserContextDependencyManager context-liveness contract.
  BrowserManagerServiceFactory::GetInstance();
}

// static
BrowserManagerService* BrowserManagerServiceFactory::GetForProfile(
    Profile* profile) {
  return static_cast<BrowserManagerService*>(
      GetInstance()->GetServiceForBrowserContext(profile, /*create=*/true));
}

// static
BrowserManagerServiceFactory* BrowserManagerServiceFactory::GetInstance() {
  static base::NoDestructor<BrowserManagerServiceFactory> factory;
  return factory.get();
}

BrowserManagerServiceFactory::BrowserManagerServiceFactory()
    : BrowserContextKeyedServiceFactory(
          "BrowserManagerService",
          BrowserContextDependencyManager::GetInstance()) {
  // The desktop factory depends on HistoryServiceFactory. History needs its
  // own durable database/bookmark source slice, which is not part of this
  // blank-window lifecycle boundary. Browser navigation/history helpers stay
  // out of the Wasm closure until that real service is available.
}

std::unique_ptr<KeyedService>
BrowserManagerServiceFactory::BuildServiceInstanceForBrowserContext(
    content::BrowserContext* context) const {
  return std::make_unique<BrowserManagerService>(
      Profile::FromBrowserContext(context));
}

content::BrowserContext* BrowserManagerServiceFactory::GetBrowserContextToUse(
    content::BrowserContext* context) const {
  // Create an empty BrowserManagerService even for contexts that do not
  // support browser windows. Browser construction checks its own eligibility.
  return context;
}

BrowserManagerServiceFactory::~BrowserManagerServiceFactory() = default;

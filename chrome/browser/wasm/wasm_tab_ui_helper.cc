// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ui/tab_ui_helper.h"

#include <optional>

#include "base/check_op.h"
#include "base/feature_list.h"
#include "base/functional/bind.h"
#include "base/process/kill.h"
#include "build/build_config.h"
#include "chrome/browser/ui/tabs/features.h"
#include "components/tabs/public/tab_interface.h"
#include "components/tabs/public/tab_network_state.h"
#include "content/public/browser/favicon_status.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_entry.h"
#include "content/public/browser/visibility.h"
#include "content/public/browser/web_contents.h"
#include "content/public/common/url_constants.h"
#include "ui/base/models/image_model.h"
#include "url/gurl.h"
#include "url/url_constants.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_tab_ui_helper.cc must only be built for WebAssembly"
#endif

// The reduced Wasm TabUIHelper still uses the canonical unowned-user-data
// identity so the real TabFeatures lifetime can retrieve it from TabModel.
DEFINE_USER_DATA(TabUIHelper);

TabUIHelper::TabUIHelper(tabs::TabInterface& tab_interface)
    : ContentsObservingTabFeature(tab_interface),
      scoped_unowned_user_data_(tab_interface.GetUnownedUserDataHost(), *this) {
  pin_tab_subscription_ = tab().RegisterPinnedStateChanged(base::BindRepeating(
      &TabUIHelper::OnTabPinnedStatusChange, base::Unretained(this)));
}

TabUIHelper::~TabUIHelper() = default;

// static
const TabUIHelper* TabUIHelper::From(const tabs::TabInterface* tab) {
  return Get(tab->GetUnownedUserDataHost());
}

// static
TabUIHelper* TabUIHelper::From(tabs::TabInterface* tab) {
  return Get(tab->GetUnownedUserDataHost());
}

base::CallbackListSubscription TabUIHelper::AddTabUIChangeCallback(
    base::RepeatingClosure callback) {
  return tab_ui_change_callbacks_.Add(std::move(callback));
}

std::u16string TabUIHelper::GetTitle() const {
  return web_contents()->GetTitle();
}

bool TabUIHelper::ShouldRenderLoadingTitle() {
  return GetTitle().empty() &&
         !GetVisibleURL().SchemeIs(content::kChromeUIUntrustedScheme);
}

ui::ImageModel TabUIHelper::GetFavicon() {
  content::NavigationEntry* const entry =
      web_contents()->GetController().GetLastCommittedEntry();
  return entry ? ui::ImageModel::FromImage(entry->GetFavicon().image)
               : ui::ImageModel();
}

bool TabUIHelper::ShouldHideThrobber() const {
  return created_by_session_restore_ && !was_active_at_least_once_;
}

void TabUIHelper::SetWasActiveAtLeastOnce() {
  const bool was_hiding_throbber = ShouldHideThrobber();
  was_active_at_least_once_ = true;
  if (was_hiding_throbber != ShouldHideThrobber()) {
    tab_ui_change_callbacks_.Notify();
  }
}

bool TabUIHelper::IsCrashed() {
  const base::TerminationStatus crashed_status =
      web_contents()->GetCrashedStatus();
  return crashed_status == base::TERMINATION_STATUS_PROCESS_WAS_KILLED ||
         crashed_status == base::TERMINATION_STATUS_PROCESS_CRASHED ||
         crashed_status == base::TERMINATION_STATUS_ABNORMAL_TERMINATION ||
         crashed_status == base::TERMINATION_STATUS_LAUNCH_FAILED;
}

GURL TabUIHelper::GetVisibleURL() {
  content::WebContents* const contents = web_contents();
  content::NavigationEntry* const entry =
      contents->GetController().GetLastCommittedEntry();
  const bool missing_navigation_entry = !entry || entry->IsInitialEntry();
  return missing_navigation_entry ? GURL(url::kAboutBlankURL)
                                  : contents->GetVisibleURL();
}

GURL TabUIHelper::GetLastCommittedURL() {
  return web_contents()->GetLastCommittedURL();
}

void TabUIHelper::TitleWasSet(content::NavigationEntry* /*entry*/) {
  tab_ui_change_callbacks_.Notify();
}

void TabUIHelper::DidStopLoading() {
  // A later source-selected session-restore owner may set this state. Reset it
  // after the first regular load exactly as the canonical helper does.
  created_by_session_restore_ = false;
}

void TabUIHelper::OnVisibilityChanged(content::Visibility visibility) {
  if (base::FeatureList::IsEnabled(
          tabs::kSessionRestoreShowThrobberOnVisible) &&
      visibility == content::Visibility::VISIBLE) {
    SetWasActiveAtLeastOnce();
  }
}

void TabUIHelper::WasDiscarded() {
  // A discard replaces the observed WebContents state. There is no Wasm
  // memory-saver badge policy yet, but live UI observers still need a real
  // state-change notification rather than a successful no-op.
  tab_ui_change_callbacks_.Notify();
}

void TabUIHelper::DidFinishNavigation(
    content::NavigationHandle* /*navigation_handle*/) {
  tab_ui_change_callbacks_.Notify();
}

void TabUIHelper::PrimaryMainFrameRenderProcessGone(
    base::TerminationStatus /*status*/) {
  if (IsCrashed()) {
    tab_ui_change_callbacks_.Notify();
  }
}

void TabUIHelper::PrimaryPageChanged(content::Page& /*page*/) {
  // Page replacement can alter the title/favicon source even without a
  // desktop split-tab metrics owner.
  tab_ui_change_callbacks_.Notify();
}

void TabUIHelper::SetCreatedBySessionRestore(bool created_by_session_restore) {
  const bool was_hiding_throbber = ShouldHideThrobber();
  created_by_session_restore_ = created_by_session_restore;
  if (was_hiding_throbber != ShouldHideThrobber()) {
    tab_ui_change_callbacks_.Notify();
  }
}

void TabUIHelper::SetNeedsAttention(bool needs_attention) {
  if (needs_attention == needs_attention_) {
    return;
  }

  needs_attention_ = needs_attention;
  tab_ui_change_callbacks_.Notify();
}

bool TabUIHelper::IsDiscarded() {
  return web_contents()->WasDiscarded();
}

tabs::TabNetworkState TabUIHelper::GetTabNetworkState() {
  return tabs::TabNetworkStateForWebContents(web_contents());
}

void TabUIHelper::NotifyTabUIChanged(base::PassKey<Browser> /*pass_key*/) {
  tab_ui_change_callbacks_.Notify();
}

void TabUIHelper::OnTabPinnedStatusChange(tabs::TabInterface* tab_interface,
                                          bool /*new_pinned_state*/) {
  CHECK_EQ(&tab(), tab_interface);
  tab_ui_change_callbacks_.Notify();
}

// These APIs intentionally have no Wasm definitions: their desktop behavior
// needs a full web-app/security-interstitial/memory-saver feature owner.
// Linking them is an explicit feature-boundary failure until that owner exists.
// - ShouldThemifyFavicon()
// - ShouldDisplayFavicon()
// - IsMonochromeFavicon()
// - ShouldDisplayURL()
// - ShouldShowDiscardStatus()
// - GetDiscardedMemorySavings()

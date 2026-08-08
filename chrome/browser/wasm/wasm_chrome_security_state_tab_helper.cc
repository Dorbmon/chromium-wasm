// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/ssl/chrome_security_state_tab_helper.h"

#include "base/check.h"
#include "base/memory/ptr_util.h"
#include "build/build_config.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_chrome_security_state_tab_helper.cc must only be built for WebAssembly"
#endif

namespace {

using UsesEmbedderInformation = SecurityStateTabHelper::UsesEmbedderInformation;

}  // namespace

// static
void ChromeSecurityStateTabHelper::CreateForWebContents(
    content::WebContents* contents) {
  DCHECK(contents);
  SecurityStateTabHelper* helper = FromWebContents(contents);
  if (!helper) {
    helper = new ChromeSecurityStateTabHelper(contents);
    contents->SetUserData(UserDataKey(), base::WrapUnique(helper));
  }

  // Chrome callers require the elevated helper. A pre-existing generic helper
  // is a lifecycle error, not a fallback to silently accept on Wasm.
  CHECK(helper->uses_embedder_information())
      << "Do not create a SecurityStateTabHelper in chrome/!";
}

ChromeSecurityStateTabHelper::ChromeSecurityStateTabHelper(
    content::WebContents* web_contents)
    : SecurityStateTabHelper(web_contents, UsesEmbedderInformation(true)) {}

ChromeSecurityStateTabHelper::~ChromeSecurityStateTabHelper() = default;

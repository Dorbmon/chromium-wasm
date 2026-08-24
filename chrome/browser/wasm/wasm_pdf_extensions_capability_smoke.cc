// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// A narrow M8.7 feature-boundary smoke for the Wasm Chrome configuration. It
// verifies that the explicitly unsupported extensions and PDF/PDFium source
// closures remain disabled. It does not construct a Browser or WebContents,
// load an extension, create a service worker, inject a content script, access
// extension storage, parse a PDF, initialize PDFium, or provide a host-page
// substitute for any of those features.

#include <cstdio>

#include "base/at_exit.h"
#include "base/command_line.h"
#include "build/build_config.h"
#include "extensions/buildflags/buildflags.h"
#include "pdf/buildflags.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_pdf_extensions_capability_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M8_PDF_EXTENSIONS";

void Emit(const char* marker) {
  std::fprintf(stdout, "%s:%s\n", kPrefix, marker);
  std::fflush(stdout);
}

int Fail(const char* stage) {
  std::fprintf(stderr, "%s:FAIL stage=%s\n", kPrefix, stage);
  std::fflush(stderr);
  return 1;
}

}  // namespace

int main(int argc, char** argv) {
  base::AtExitManager at_exit;
  base::CommandLine::Init(argc, argv);

  Emit("RUNTIME_START");

  // ENABLE_EXTENSIONS_CORE is the source-selection gate for the extension
  // service, its background/service-worker lifecycle, content scripts, and
  // extension storage. Full ENABLE_EXTENSIONS additionally selects the
  // production desktop extension implementation. A later enabling profile
  // must replace this witness with integration coverage; it must not continue
  // to report an unsupported surface as disabled.
  const volatile bool extensions_disabled =
      !BUILDFLAG(ENABLE_EXTENSIONS) && !BUILDFLAG(ENABLE_EXTENSIONS_CORE);
  if (!extensions_disabled) {
    return Fail("extensions_unexpectedly_enabled");
  }
  Emit("PHASE name=extensions_buildflags status=disabled");

  // ENABLE_PDF controls the bundled PDF extension/PDFium closure. The two
  // subordinate flags must remain disabled with it. This is source-selection
  // evidence only; it does not attempt to turn an embedded host PDF viewer
  // into Chromium PDF support.
  const volatile bool pdf_disabled =
      !BUILDFLAG(ENABLE_PDF) && !BUILDFLAG(ENABLE_PDF_INK2) &&
      !BUILDFLAG(ENABLE_PDF_SAVE_TO_DRIVE);
  if (!pdf_disabled) {
    return Fail("pdf_unexpectedly_enabled");
  }
  Emit("PHASE name=pdf_buildflags status=disabled");

  std::fprintf(
      stdout,
      "%s:RESULT extensions=disabled extensions_core=disabled "
      "extension_service=not_selected "
      "extension_background_lifecycle=not_selected "
      "extension_content_scripts=not_selected extension_storage=not_selected "
      "extension_native_messaging=not_selected pdf=disabled "
      "pdf_ink2=disabled pdf_save_to_drive=disabled "
      "bundled_pdf_extension=not_selected pdfium=not_selected "
      "pdf_viewer=not_selected\n",
      kPrefix);
  std::fflush(stdout);
  Emit("RUNTIME_END");
  Emit("PASS");
  return 0;
}

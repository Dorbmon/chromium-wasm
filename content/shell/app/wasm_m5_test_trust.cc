// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/shell/app/wasm_m5_test_trust.h"

#include <stdint.h>

#include <utility>

#include "base/check.h"
#include "base/no_destructor.h"
#include "net/cert/test_root_certs.h"
#include "net/cert/x509_certificate.h"

namespace content {

namespace {

// Generated from the CERTIFICATE block only by
// generate-fuzzer-cert-include.py. The source PEM, which contains the test
// private key too, is never linked or embedded into this executable.
constexpr uint8_t kM5TestRootCertificateDer[] = {
#include "content/shell/app/wasm_m5_test_root_cert.inc"
};

net::ScopedTestRoot MakeM5TestRoot() {
  scoped_refptr<net::X509Certificate> certificate =
      net::X509Certificate::CreateFromBytes(kM5TestRootCertificateDer);
  CHECK(certificate);
  return net::ScopedTestRoot(std::move(certificate));
}

}  // namespace

void InstallWasmM5TestTrustRoot() {
  static const base::NoDestructor<net::ScopedTestRoot> test_root(
      MakeM5TestRoot());
  CHECK(!test_root->IsEmpty());
}

}  // namespace content

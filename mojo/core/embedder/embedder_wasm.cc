// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "mojo/core/embedder/embedder.h"

#include "base/check.h"
#include "build/build_config.h"
#include "mojo/core/configuration.h"
#include "mojo/core/core_ipcz.h"
#include "mojo/core/ipcz_api.h"
#include "mojo/core/ipcz_driver/driver.h"
#include "mojo/public/c/system/thunks.h"

#if !BUILDFLAG(IS_WASM)
#error "embedder_wasm.cc is only for WebAssembly"
#endif

namespace mojo::core {
namespace {

bool g_initialized = false;

}  // namespace

void Init(const Configuration& configuration) {
  CHECK(!g_initialized);
  CHECK(!configuration.disable_ipcz);
  internal::g_configuration = configuration;
  CHECK(InitializeIpczNodeForProcess({
      .is_broker = configuration.is_broker_process,
      .use_local_shared_memory_allocation =
          configuration.is_broker_process ||
          configuration.force_direct_shared_memory_allocation,
      .enable_memv2 = false,
  }));
  MojoEmbedderSetSystemThunks(GetMojoIpczImpl());
  g_initialized = true;
}

void Init() {
  Init(Configuration());
}

void ShutDown() {
  CHECK(g_initialized);
  DestroyIpczNodeForProcess();
  g_initialized = false;
}

scoped_refptr<base::SingleThreadTaskRunner> GetIOTaskRunner() {
  return nullptr;
}

void InitFeatures() {
  CHECK(false) << "FeatureList-driven Mojo initialization is unsupported on "
                  "WebAssembly";
}

void EnableMojoIpcz() {}

bool IsMojoIpczEnabled() {
  return true;
}

void InstallMojoIpczBaseSharedMemoryHooks() {
  // Wasm Base shared memory is already backed by the process-local capability
  // registry, so no broker allocation hook is required.
}

const IpczAPI& GetIpczAPIForMojo() {
  return GetIpczAPI();
}

const IpczDriver& GetIpczDriverForMojo() {
  return ipcz_driver::kDriver;
}

}  // namespace mojo::core

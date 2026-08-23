// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_storage.h"

#include <emscripten/threading.h>
#include <emscripten/wasmfs.h>
#include <emscripten/wasmfs_opfs_profile_drain.h>

#include <cerrno>

#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_storage.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kProfileMountPath[] = "/profile";
constexpr char kProfileLeaseName[] = "chromium-wasm-profile-v1";

int NegativeErrnoOrEio() {
  return errno == 0 ? -EIO : -errno;
}

class WasmProfileStorageState {
 public:
  WasmProfileStorageState() = default;
  WasmProfileStorageState(const WasmProfileStorageState&) = delete;
  WasmProfileStorageState& operator=(const WasmProfileStorageState&) = delete;
  ~WasmProfileStorageState() = default;

  bool Initialize() {
    base::AutoLock lock(lock_);
    if (state_ != State::kUninitialized) {
      return state_ == State::kMounted;
    }

    // Leased OPFS backend construction cannot run on the browser main thread,
    // and the scoped backend drain cannot run on Emscripten's runtime main
    // thread. The Chrome application pthread avoids both restrictions; fail
    // rather than reaching either blocking API from an unsupported thread.
    if (emscripten_is_main_browser_thread() ||
        emscripten_is_main_runtime_thread()) {
      initialization_error_ = -EAGAIN;
      state_ = State::kMountFailed;
      return false;
    }

    errno = 0;
    backend_t backend =
        wasmfs_create_opfs_backend_with_profile_lease(kProfileLeaseName);
    if (!backend) {
      initialization_error_ = NegativeErrnoOrEio();
      state_ = State::kMountFailed;
      return false;
    }

    // Keep the exact factory result even if a later mount or identity check
    // fails. Creating this backend acquired the lease, but draining it in this
    // startup frame could race destruction of ChromeMain's delegate and
    // ContentMainParams. ChromeMain releases it after that scope is gone.
    backend_ = backend;

    const int mount_result =
        wasmfs_create_directory(kProfileMountPath, /*mode=*/0700, backend);
    if (mount_result != 0) {
      initialization_error_ = mount_result < 0 ? mount_result : -EIO;
      state_ = State::kMountFailed;
      return false;
    }

    if (wasmfs_get_backend_by_path(kProfileMountPath) != backend) {
      initialization_error_ = -EIO;
      state_ = State::kMountFailed;
      return false;
    }

    state_ = State::kMounted;
    return true;
  }

  bool IsMounted() {
    base::AutoLock lock(lock_);
    return state_ == State::kMounted && !backend_drain_attempted_;
  }

  bool NeedsBackendDrain() {
    base::AutoLock lock(lock_);
    return backend_ != nullptr && !backend_drain_attempted_;
  }

  bool NotifyProfileCreated() {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_ ||
        profile_created_ || profile_shutdown_) {
      return false;
    }
    profile_created_ = true;
    return true;
  }

  bool NotifyProfileShutdown() {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_) {
      return false;
    }
    // A Content startup failure can reach BrowserMainParts teardown without
    // constructing a profile. In that case there is no live profile service
    // to wait for, and this records that fact before ChromeMain later drains.
    profile_shutdown_ = true;
    return true;
  }

  WasmProfileStorageDrainResult DrainAndReleaseBackend() {
    backend_t backend = nullptr;
    {
      base::AutoLock lock(lock_);
      if (backend_drain_attempted_) {
        if (state_ == State::kDraining) {
          WasmProfileStorageDrainResult result;
          result.error = -EBUSY;
          return result;
        }
        return backend_drain_result_;
      }
      if (!backend_) {
        WasmProfileStorageDrainResult result;
        result.error =
            initialization_error_ != 0 ? initialization_error_ : -EINVAL;
        return result;
      }
      if (state_ == State::kMounted && profile_created_ && !profile_shutdown_) {
        WasmProfileStorageDrainResult result;
        result.error = -EBUSY;
        return result;
      }
      // Preserve the mounted state after an invalid-thread call so an
      // embedding can retry from Chromium's application pthread. The scoped
      // WasmFS API does not seal the backend when it returns EAGAIN.
      if (emscripten_is_main_browser_thread() ||
          emscripten_is_main_runtime_thread()) {
        WasmProfileStorageDrainResult result;
        result.error = -EAGAIN;
        return result;
      }

      backend_drain_attempted_ = true;
      state_ = State::kDraining;
      backend = backend_;
    }

    // Do not hold Chrome's lifecycle lock while this waits for the OPFS
    // worker. The primitive seals and drains only |backend|; global WasmFS,
    // stdout/stderr, and the ordinary Emscripten exit tail stay live.
    WasmProfileStorageDrainResult result = DrainBackend(backend);

    base::AutoLock lock(lock_);
    backend_drain_result_ = result;
    state_ = backend_drain_result_.Succeeded() ? State::kDrained
                                               : State::kDrainFailed;
    return backend_drain_result_;
  }

 private:
  enum class State {
    kUninitialized,
    kMounted,
    kMountFailed,
    kDraining,
    kDrained,
    kDrainFailed,
  };

  static int NormalizeError(int error) { return error < 0 ? error : -EIO; }

  static WasmProfileStorageDrainResult DrainBackend(backend_t backend) {
    wasmfs_opfs_profile_drain_result wasmfs_result{};
    const int drain_result =
        wasmfs_drain_opfs_profile_backend(backend, &wasmfs_result);

    WasmProfileStorageDrainResult result;
    result.error = drain_result != 0 ? NormalizeError(drain_result)
                   : wasmfs_result.error == 0
                       ? 0
                       : NormalizeError(wasmfs_result.error);
    result.detached_descriptors = wasmfs_result.detached_descriptors;
    result.data_file_states = wasmfs_result.data_file_states;
    result.libc_flush_failed = wasmfs_result.libc_flush_failed;
    result.data_flush_failures = wasmfs_result.data_flush_failures;
    result.data_close_failures = wasmfs_result.data_close_failures;
    result.prior_close_failures = wasmfs_result.prior_close_failures;
    result.lease_release_failures = wasmfs_result.lease_release_failures;
    result.backend_retire_failures = wasmfs_result.backend_retire_failures;
    result.backend_sealed = wasmfs_result.backend_sealed != 0;
    result.lease_released = wasmfs_result.lease_released != 0;
    result.backend_retired = wasmfs_result.backend_retired != 0;
    if (result.error == 0 &&
        (result.libc_flush_failed != 0 || result.data_flush_failures != 0 ||
         result.data_close_failures != 0 || result.prior_close_failures != 0 ||
         result.lease_release_failures != 0 ||
         result.backend_retire_failures != 0 || !result.backend_sealed ||
         !result.lease_released || !result.backend_retired)) {
      // The pinned API promises a first negative errno whenever a failure
      // counter is nonzero. Treat a contradictory success, an unsealed
      // backend, an unacknowledged release, or an unretired worker as EIO
      // rather than reporting a clean profile handoff.
      result.error = -EIO;
    }
    return result;
  }

  base::Lock lock_;
  State state_ GUARDED_BY(lock_) = State::kUninitialized;
  int initialization_error_ GUARDED_BY(lock_) = 0;
  backend_t backend_ GUARDED_BY(lock_) = nullptr;
  bool profile_created_ GUARDED_BY(lock_) = false;
  bool profile_shutdown_ GUARDED_BY(lock_) = false;
  bool backend_drain_attempted_ GUARDED_BY(lock_) = false;
  WasmProfileStorageDrainResult backend_drain_result_ GUARDED_BY(lock_);
};

WasmProfileStorageState& GetWasmProfileStorageState() {
  static base::NoDestructor<WasmProfileStorageState> state;
  return *state;
}

}  // namespace

bool InitializeWasmProfileStorage() {
  return GetWasmProfileStorageState().Initialize();
}

bool IsWasmProfileStorageMounted() {
  return GetWasmProfileStorageState().IsMounted();
}

bool NeedsWasmProfileStorageBackendDrain() {
  return GetWasmProfileStorageState().NeedsBackendDrain();
}

bool NotifyWasmProfileStorageProfileCreated() {
  return GetWasmProfileStorageState().NotifyProfileCreated();
}

bool NotifyWasmProfileStorageProfileShutdown() {
  return GetWasmProfileStorageState().NotifyProfileShutdown();
}

WasmProfileStorageDrainResult DrainAndReleaseWasmProfileStorageBackend() {
  return GetWasmProfileStorageState().DrainAndReleaseBackend();
}

}  // namespace chrome

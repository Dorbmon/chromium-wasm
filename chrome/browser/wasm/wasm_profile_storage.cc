// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_profile_storage.h"

#include <emscripten/threading.h>
#include <emscripten/wasmfs.h>
#include <emscripten/wasmfs_opfs_profile_drain.h>

#include <cerrno>
#include <memory>
#include <optional>
#include <utility>

#include "base/check.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_profile_storage.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kProfileRootPath[] = "/profile";
constexpr char kProfileLeaseName[] = "chromium-wasm-profile-v1";

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
constexpr char kWasmFsRootPath[] = "/";
constexpr char kProfileDefaultPath[] = "/profile/Default";
#endif

int NegativeErrnoOrEio() {
  return errno == 0 ? -EIO : -errno;
}

enum class ProfileStorageMount {
  kProfileRoot,
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  kDefaultProfile,
#endif
};

enum class ProfileShutdownDisposition {
  kCleanHandoff,
  kFailClosed,
};

class WasmProfileStorageState {
 public:
  WasmProfileStorageState() = default;
  WasmProfileStorageState(const WasmProfileStorageState&) = delete;
  WasmProfileStorageState& operator=(const WasmProfileStorageState&) = delete;
  ~WasmProfileStorageState() = default;

  bool Initialize(ProfileStorageMount mount) {
    base::AutoLock lock(lock_);
    if (state_ != State::kUninitialized) {
      return state_ == State::kMounted && mount_ == mount;
    }

    // V4 leased-OPFS filesystem construction cannot run on the browser main
    // thread, and its scoped backend drain cannot run on Emscripten's runtime
    // main thread. The Chrome application pthread avoids both restrictions;
    // fail rather than reaching either blocking API from an unsupported thread.
    if (emscripten_is_main_browser_thread() ||
        emscripten_is_main_runtime_thread()) {
      initialization_error_ = -EAGAIN;
      state_ = State::kMountFailed;
      return false;
    }

    const char* mount_path = kProfileRootPath;
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    backend_t profile_root_backend = nullptr;
    if (mount == ProfileStorageMount::kDefaultProfile) {
      const int profile_root_result =
          PrepareVolatileProfileRoot(&profile_root_backend);
      if (profile_root_result != 0) {
        initialization_error_ = profile_root_result;
        state_ = State::kMountFailed;
        return false;
      }
      mount_path = kProfileDefaultPath;
    }
#endif

    errno = 0;
    backend_t backend =
        wasmfs_create_opfs_profile_log_v4_filesystem_backend(kProfileLeaseName);
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
        wasmfs_create_directory(mount_path, /*mode=*/0700, backend);
    if (mount_result != 0) {
      initialization_error_ = mount_result < 0 ? mount_result : -EIO;
      state_ = State::kMountFailed;
      return false;
    }

    bool has_expected_mount_identity =
        HasExpectedProfileRootMountIdentity(backend);
#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
    if (mount == ProfileStorageMount::kDefaultProfile) {
      has_expected_mount_identity =
          HasExpectedDefaultProfileMountIdentity(profile_root_backend, backend);
    }
#endif
    if (!has_expected_mount_identity) {
      initialization_error_ = -EIO;
      state_ = State::kMountFailed;
      return false;
    }

    mount_ = mount;
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

  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
  BeginProfileConstruction() {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_ ||
        profile_construction_started_ || profile_created_ ||
        profile_shutdown_ || profile_io_lifecycle_ ||
        profile_io_observation_) {
      return std::nullopt;
    }
    profile_io_lifecycle_ =
        std::make_unique<WasmProfileOrderedDrainLifecycle>();
    profile_construction_started_ = true;
    return profile_io_lifecycle_->TryAcquireProfileIO();
  }

  bool AbortProfileConstructionFailClosed() {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_ ||
        profile_created_ || profile_shutdown_) {
      return false;
    }

    // Construction never reached ProfileCreated(), so it cannot yield a
    // clean profile handoff. If admission started, retain its terminal
    // observation for ChromeMain's later failure retirement.
    force_fail_closed_ = true;
    if (profile_construction_started_) {
      if (!profile_io_lifecycle_ || profile_io_observation_) {
        return false;
      }
      profile_io_observation_ = profile_io_lifecycle_->BeginQuiesce();
      if (!profile_io_observation_) {
        return false;
      }
    }
    profile_shutdown_ = true;
    return true;
  }

  bool NotifyProfileCreated() {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_ ||
        !profile_construction_started_ || profile_created_ ||
        profile_shutdown_ || !profile_io_lifecycle_ ||
        profile_io_observation_) {
      return false;
    }
    profile_created_ = true;
    return true;
  }

  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
  TryAcquireProfileIO() {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_ ||
        !profile_created_ || profile_shutdown_ || !profile_io_lifecycle_) {
      return std::nullopt;
    }
    return profile_io_lifecycle_->TryAcquireProfileIO();
  }

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
  bool RetainOutstandingIOForRefusalTest(
      WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold) {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_ ||
        !profile_created_ || profile_shutdown_ || !profile_io_lifecycle_ ||
        outstanding_profile_io_hold_for_refusal_test_ ||
        outstanding_profile_io_refusal_observed_) {
      return false;
    }
    outstanding_profile_io_hold_for_refusal_test_.emplace(
        std::move(profile_io_hold));
    return true;
  }

  bool CompleteOutstandingIORefusalAsFailedForTest() {
    std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
        profile_io_hold;
    {
      base::AutoLock lock(lock_);
      if (state_ != State::kMounted || backend_drain_attempted_ ||
          !profile_shutdown_ || !outstanding_profile_io_hold_for_refusal_test_ ||
          !outstanding_profile_io_refusal_observed_) {
        return false;
      }
      profile_io_hold =
          std::move(outstanding_profile_io_hold_for_refusal_test_);
      outstanding_profile_io_hold_for_refusal_test_.reset();
    }
    return profile_io_hold->Complete(
        WasmProfileOrderedDrainLifecycle::ProfileIOCompletion::kFailed);
  }
#endif

  bool NotifyProfileShutdown(ProfileShutdownDisposition disposition) {
    base::AutoLock lock(lock_);
    if (state_ != State::kMounted || backend_drain_attempted_ ||
        profile_shutdown_) {
      return false;
    }
    // A normal profile handoff is valid only after construction completed and
    // BrowserMainParts recorded that fact. The precreation path has its own
    // explicit fail-closed retirement API.
    if (disposition == ProfileShutdownDisposition::kCleanHandoff &&
        !profile_created_) {
      return false;
    }
    // An owner-loss fallback has destroyed the Profile without a complete
    // Preferences/smoke lifecycle receipt. Keep that terminal disposition
    // sticky before closing admission so no later retry can mistake a clean
    // registered-I/O result for authority to release the profile lease.
    if (disposition == ProfileShutdownDisposition::kFailClosed) {
      force_fail_closed_ = true;
    }
    // A construction-start admission exists before ProfileCreated(). Whether
    // the profile reached that post-construction state or lost its owner
    // afterward, close this exact lifecycle before ChromeMain later drains.
    if (profile_construction_started_) {
      if (!profile_io_lifecycle_ || profile_io_observation_) {
        return false;
      }
      profile_io_observation_ = profile_io_lifecycle_->BeginQuiesce();
      if (!profile_io_observation_) {
        return false;
      }
    }
    profile_shutdown_ = true;
    return true;
  }

  WasmProfileStorageDrainResult DrainAndReleaseBackend() {
    backend_t backend = nullptr;
    bool force_fail_closed = false;
    std::optional<WasmProfileOrderedDrainLifecycle::PostContentDrainPermit>
        profile_io_drain_permit;
    std::optional<
        WasmProfileOrderedDrainLifecycle::PostContentFailureRetirementPermit>
        profile_io_failure_retirement_permit;
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
      // Preserve the mounted state after an invalid-thread call so an
      // embedding can retry from Chromium's application pthread. Check this
      // before claiming the one-shot profile-I/O permit: an unsupported
      // caller must not consume a clean handoff that the supported caller
      // still needs to perform the actual scoped drain.
      if (emscripten_is_main_browser_thread() ||
          emscripten_is_main_runtime_thread()) {
        WasmProfileStorageDrainResult result;
        result.error = -EAGAIN;
        return result;
      }
      // A mounted profile backend that never reached the post-construction
      // notification has no evidence that Chrome handed its profile services
      // off cleanly. This includes startup failures before construction can
      // begin, so do not let a later generic teardown release its lease.
      if (state_ == State::kMounted && !profile_created_) {
        force_fail_closed_ = true;
      }
      if (state_ == State::kMounted && profile_construction_started_) {
        if (!profile_shutdown_) {
          WasmProfileStorageDrainResult result;
          result.error = -EBUSY;
          return result;
        }
        if (!profile_io_observation_) {
          WasmProfileStorageDrainResult result;
          result.error = -EIO;
          return result;
        }

        const WasmProfileOrderedDrainLifecycle::Result profile_io_result =
            profile_io_observation_->GetResult();
        std::optional<
            WasmProfileOrderedDrainLifecycle::ProfileIOQuiesceResult>
            profile_io_quiesce_result;
        switch (profile_io_result.status) {
          case WasmProfileOrderedDrainLifecycle::Status::
              kReadyForPostContentDrain:
            profile_io_drain_permit =
                profile_io_observation_->ClaimPostContentDrain();
            if (profile_io_drain_permit) {
              profile_io_quiesce_result =
                  profile_io_drain_permit->GetProfileIOQuiesceResult();
            }
            break;
          case WasmProfileOrderedDrainLifecycle::Status::
              kRegisteredProfileIONotClean:
            profile_io_failure_retirement_permit =
                profile_io_observation_->ClaimPostContentFailureRetirement();
            if (profile_io_failure_retirement_permit) {
              profile_io_quiesce_result =
                  profile_io_failure_retirement_permit
                      ->GetProfileIOQuiesceResult();
            }
            break;
          case WasmProfileOrderedDrainLifecycle::Status::
              kWaitingForRegisteredProfileIO: {
            WasmProfileStorageDrainResult result;
            result.error = -EBUSY;
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
            // This fixture must complete its retained admission only after
            // the storage seam has observed this exact refusal. The latch
            // prevents test code from silently completing it early and
            // turning the required pre-transaction proof into a clean drain.
            if (outstanding_profile_io_hold_for_refusal_test_) {
              outstanding_profile_io_refusal_observed_ = true;
            }
#endif
            result.refused_for_outstanding_profile_io = true;
            return result;
          }
          case WasmProfileOrderedDrainLifecycle::Status::
              kAcceptingRegisteredProfileIO:
          case WasmProfileOrderedDrainLifecycle::Status::
              kAbortedBeforePostContentDrain:
          case WasmProfileOrderedDrainLifecycle::Status::
              kPostContentDrainPermitClaimed:
          case WasmProfileOrderedDrainLifecycle::Status::
              kPostContentDrainPermitRetired:
          case WasmProfileOrderedDrainLifecycle::Status::
              kPostContentFailureRetirementPermitClaimed:
          case WasmProfileOrderedDrainLifecycle::Status::
              kPostContentFailureRetirementPermitRetired: {
            WasmProfileStorageDrainResult result;
            result.error = -EIO;
            return result;
          }
        }

        const bool clean_profile_io = profile_io_drain_permit.has_value();
        if (!profile_io_quiesce_result ||
            profile_io_quiesce_result->Succeeded() != clean_profile_io) {
          WasmProfileStorageDrainResult result;
          result.error = -EIO;
          return result;
        }
        // An ordinary handoff still needs a positive registered-I/O witness.
        // The foundation fallback deliberately has no complete profile
        // lifecycle receipt, so it may use a zero-operation observation only
        // to prove quiescence for explicit fail-closed retirement.
        if (!force_fail_closed_ &&
            profile_io_quiesce_result->admitted_operations == 0) {
          WasmProfileStorageDrainResult result;
          result.error = -EIO;
          return result;
        }
      }
      force_fail_closed = force_fail_closed_;
      backend_drain_attempted_ = true;
      state_ = State::kDraining;
      backend = backend_;
    }

    // Do not hold Chrome's lifecycle lock while this waits for the OPFS
    // worker. The primitive seals and drains only |backend|; global WasmFS,
    // stdout/stderr, and the ordinary Emscripten exit tail stay live.
    const bool fail_closed_retirement =
        force_fail_closed || profile_io_failure_retirement_permit.has_value();
    WasmProfileStorageDrainResult result =
        fail_closed_retirement
            ? FailClosedRetireBackend(backend)
            : DrainBackend(backend);

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

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  static int PrepareVolatileProfileRoot(backend_t* profile_root_backend) {
    CHECK(profile_root_backend);

    errno = 0;
    const backend_t wasmfs_root_backend =
        wasmfs_get_backend_by_path(kWasmFsRootPath);
    if (!wasmfs_root_backend) {
      return NegativeErrnoOrEio();
    }

    // The dedicated Preferences probe stores only Default/Preferences. Keep
    // its containing user-data directory on WasmFS's default memory backend
    // rather than creating /profile from the leased V4 OPFS backend. EEXIST is
    // acceptable only after the identity check below; it is never a fallback
    // to an unknown existing mount.
    const int create_profile_root_result = wasmfs_create_directory(
        kProfileRootPath, /*mode=*/0700, wasmfs_root_backend);
    if (create_profile_root_result != 0 &&
        create_profile_root_result != -EEXIST) {
      return create_profile_root_result < 0 ? create_profile_root_result
                                            : -EIO;
    }

    const backend_t parent_backend =
        wasmfs_get_backend_by_path(kProfileRootPath);
    if (!parent_backend || parent_backend != wasmfs_root_backend) {
      return -EIO;
    }

    *profile_root_backend = parent_backend;
    return 0;
  }
#endif

  static bool HasExpectedProfileRootMountIdentity(backend_t leased_backend) {
    return wasmfs_get_backend_by_path(kProfileRootPath) == leased_backend;
  }

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
  static bool HasExpectedDefaultProfileMountIdentity(
      backend_t profile_root_backend,
      backend_t leased_backend) {
    // Verify the parent again after mounting Default: the parent must remain
    // on the WasmFS memory root and must never be the leased V4 OPFS backend,
    // while Default must resolve to the exact backend whose lease we drain.
    const backend_t parent_backend =
        wasmfs_get_backend_by_path(kProfileRootPath);
    const backend_t default_backend =
        wasmfs_get_backend_by_path(kProfileDefaultPath);
    return parent_backend == profile_root_backend &&
           parent_backend != leased_backend &&
           default_backend == leased_backend;
  }
#endif

  static int NormalizeError(int error) { return error < 0 ? error : -EIO; }

  static WasmProfileStorageDrainResult BuildDrainResult(
      int drain_result,
      const wasmfs_opfs_profile_drain_result& wasmfs_result) {
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

  static WasmProfileStorageDrainResult DrainBackend(backend_t backend) {
    wasmfs_opfs_profile_drain_result wasmfs_result{};
    return BuildDrainResult(
        wasmfs_drain_opfs_profile_backend(backend, &wasmfs_result),
        wasmfs_result);
  }

  static WasmProfileStorageDrainResult FailClosedRetireBackend(
      backend_t backend) {
    wasmfs_opfs_profile_drain_result wasmfs_result{};
    return BuildDrainResult(
        wasmfs_fail_closed_opfs_profile_backend(backend, &wasmfs_result),
        wasmfs_result);
  }

  base::Lock lock_;
  State state_ GUARDED_BY(lock_) = State::kUninitialized;
  ProfileStorageMount mount_ GUARDED_BY(lock_) =
      ProfileStorageMount::kProfileRoot;
  int initialization_error_ GUARDED_BY(lock_) = 0;
  backend_t backend_ GUARDED_BY(lock_) = nullptr;
  bool profile_construction_started_ GUARDED_BY(lock_) = false;
  bool profile_created_ GUARDED_BY(lock_) = false;
  bool profile_shutdown_ GUARDED_BY(lock_) = false;
  bool force_fail_closed_ GUARDED_BY(lock_) = false;
  std::unique_ptr<WasmProfileOrderedDrainLifecycle> profile_io_lifecycle_
      GUARDED_BY(lock_);
  scoped_refptr<WasmProfileOrderedDrainLifecycle::Observation>
      profile_io_observation_ GUARDED_BY(lock_);
#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
  // This is an admission-only test fixture. The database task has already
  // destroyed its SQLite/LevelDB resources before it arrives here. ChromeMain
  // completes it as failed only after observing the first refusal, so it can
  // make one explicit, separate fail-closed cleanup before runtime teardown.
  std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
      outstanding_profile_io_hold_for_refusal_test_ GUARDED_BY(lock_);
  bool outstanding_profile_io_refusal_observed_ GUARDED_BY(lock_) = false;
#endif
  bool backend_drain_attempted_ GUARDED_BY(lock_) = false;
  WasmProfileStorageDrainResult backend_drain_result_ GUARDED_BY(lock_);
};

WasmProfileStorageState& GetWasmProfileStorageState() {
  static base::NoDestructor<WasmProfileStorageState> state;
  return *state;
}

}  // namespace

bool InitializeWasmProfileStorage() {
  return GetWasmProfileStorageState().Initialize(
      ProfileStorageMount::kProfileRoot);
}

#if defined(CHROME_WASM_M7_PREFERENCES_SMOKE_TEST) || \
    defined(CHROME_WASM_M7_DEFAULT_PARTITION_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_LOCAL_STORAGE_TEST) || \
    defined(CHROME_WASM_M7_PROFILE_BOOKMARK_COOKIE_HISTORY_DATABASE_LOCAL_STORAGE_TEST)
bool InitializeWasmProfilePreferencesStorage() {
  return GetWasmProfileStorageState().Initialize(
      ProfileStorageMount::kDefaultProfile);
}
#endif

bool IsWasmProfileStorageMounted() {
  return GetWasmProfileStorageState().IsMounted();
}

bool NeedsWasmProfileStorageBackendDrain() {
  return GetWasmProfileStorageState().NeedsBackendDrain();
}

std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
BeginWasmProfileStorageProfileConstruction() {
  return GetWasmProfileStorageState().BeginProfileConstruction();
}

bool AbortWasmProfileStorageProfileConstructionFailClosed() {
  return GetWasmProfileStorageState().AbortProfileConstructionFailClosed();
}

bool NotifyWasmProfileStorageProfileCreated() {
  return GetWasmProfileStorageState().NotifyProfileCreated();
}

bool NotifyWasmProfileStorageProfileShutdown() {
  return GetWasmProfileStorageState().NotifyProfileShutdown(
      ProfileShutdownDisposition::kCleanHandoff);
}

bool NotifyWasmProfileStorageProfileShutdownFailClosed() {
  return GetWasmProfileStorageState().NotifyProfileShutdown(
      ProfileShutdownDisposition::kFailClosed);
}

std::optional<WasmProfileOrderedDrainLifecycle::ProfileIOHold>
TryAcquireWasmProfileStorageProfileIO() {
  return GetWasmProfileStorageState().TryAcquireProfileIO();
}

#if defined(CHROME_WASM_M7_PROFILE_DATABASE_OUTSTANDING_IO_REFUSAL_TEST)
bool RetainWasmProfileStorageOutstandingIOForRefusalTest(
    WasmProfileOrderedDrainLifecycle::ProfileIOHold profile_io_hold) {
  return GetWasmProfileStorageState().RetainOutstandingIOForRefusalTest(
      std::move(profile_io_hold));
}

bool CompleteWasmProfileStorageOutstandingIORefusalAsFailedForTest() {
  return GetWasmProfileStorageState()
      .CompleteOutstandingIORefusalAsFailedForTest();
}
#endif

WasmProfileStorageDrainResult DrainAndReleaseWasmProfileStorageBackend() {
  return GetWasmProfileStorageState().DrainAndReleaseBackend();
}

}  // namespace chrome

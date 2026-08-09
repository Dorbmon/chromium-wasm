// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_host_input.h"

#include <stddef.h>
#include <stdint.h>

#include <cstring>
#include <memory>
#include <string_view>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/task/single_thread_task_runner.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "emscripten/emscripten.h"
#include "ui/events/keycodes/dom/dom_code.h"
#include "ui/ozone/public/ozone_platform.h"
#include "ui/ozone/public/system_input_injector.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_host_input.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr size_t kMaximumHostDomCodeLength = 16;

bool ParseWasmBrowserHostDomCode(std::string_view code,
                                 ui::DomCode* physical_key) {
  CHECK(physical_key);
  if (code == "ControlLeft") {
    *physical_key = ui::DomCode::CONTROL_LEFT;
  } else if (code == "ShiftLeft") {
    *physical_key = ui::DomCode::SHIFT_LEFT;
  } else if (code == "AltLeft") {
    *physical_key = ui::DomCode::ALT_LEFT;
  } else if (code == "KeyL") {
    *physical_key = ui::DomCode::US_L;
  } else if (code == "KeyR") {
    *physical_key = ui::DomCode::US_R;
  } else if (code == "ArrowLeft") {
    *physical_key = ui::DomCode::ARROW_LEFT;
  } else if (code == "ArrowRight") {
    *physical_key = ui::DomCode::ARROW_RIGHT;
  } else if (code == "Tab") {
    *physical_key = ui::DomCode::TAB;
  } else {
    return false;
  }
  return true;
}

class WasmBrowserHostInputState {
 public:
  WasmBrowserHostInputState() = default;
  WasmBrowserHostInputState(const WasmBrowserHostInputState&) = delete;
  WasmBrowserHostInputState& operator=(const WasmBrowserHostInputState&) =
      delete;
  ~WasmBrowserHostInputState() = default;

  bool InitializeOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    CHECK(!input_injector_);

    std::unique_ptr<ui::SystemInputInjector> input_injector =
        ui::OzonePlatform::GetInstance()->CreateSystemInputInjector();
    if (!input_injector) {
      return false;
    }

    scoped_refptr<base::SingleThreadTaskRunner> task_runner =
        base::SingleThreadTaskRunner::GetCurrentDefault();
    if (!task_runner) {
      return false;
    }

    {
      base::AutoLock lock(lock_);
      CHECK(!accepting_host_input_);
      CHECK(!task_runner_);
      ++generation_;
      accepting_host_input_ = true;
      task_runner_ = std::move(task_runner);
      ResetKeyStateLocked();
    }
    input_injector_ = std::move(input_injector);
    return true;
  }

  void ShutdownOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    {
      base::AutoLock lock(lock_);
      ++generation_;
      accepting_host_input_ = false;
      task_runner_ = nullptr;
      ResetKeyStateLocked();
      verifier_.Reset();
      verified_callback_.Reset();
    }
    input_injector_.reset();
  }

  bool PostKey(ui::DomCode physical_key, bool down) {
    base::AutoLock lock(lock_);
    if (!accepting_host_input_ || !task_runner_ ||
        !IsKeyTransitionAllowedLocked(physical_key, down)) {
      return false;
    }

    const uint64_t generation = generation_;
    if (!task_runner_->PostTask(
            FROM_HERE,
            base::BindOnce(&WasmBrowserHostInputState::DispatchKeyOnUiThread,
                           base::Unretained(this), physical_key, down,
                           generation))) {
      return false;
    }
    *GetKeyStateLocked(physical_key) = down;
    return true;
  }

  bool PostVerificationCheck() {
    base::AutoLock lock(lock_);
    if (!accepting_host_input_ || !task_runner_ || !verifier_ ||
        !verified_callback_) {
      return false;
    }

    const uint64_t generation = generation_;
    return task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            &WasmBrowserHostInputState::RunVerificationOnUiThread,
            base::Unretained(this), generation));
  }

  void SetVerificationOnUiThread(base::RepeatingCallback<bool()> verifier,
                                 base::OnceClosure verified_callback) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    CHECK(verifier);
    CHECK(verified_callback);

    base::AutoLock lock(lock_);
    CHECK(accepting_host_input_);
    CHECK(!verifier_);
    CHECK(!verified_callback_);
    verifier_ = std::move(verifier);
    verified_callback_ = std::move(verified_callback);
  }

  void ClearVerificationOnUiThread() {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::AutoLock lock(lock_);
    verifier_.Reset();
    verified_callback_.Reset();
  }

 private:
  bool IsKeyTransitionAllowedLocked(ui::DomCode physical_key, bool down) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    const bool* const key_down = GetKeyStateLocked(physical_key);
    if (*key_down == down) {
      return false;
    }
    // A held action key must always be releasable after its modifier was
    // released first, but every new action key press must have the same narrow
    // modifier policy that ozone_wasm enforces at injection time.
    return !down || IsAcceleratorChordSatisfiedLocked(physical_key);
  }

  bool IsAcceleratorChordSatisfiedLocked(ui::DomCode physical_key) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (physical_key) {
      case ui::DomCode::US_L:
        return control_left_down_ && !shift_left_down_ && !alt_left_down_;
      case ui::DomCode::US_R:
        return control_left_down_ && !alt_left_down_;
      case ui::DomCode::ARROW_LEFT:
      case ui::DomCode::ARROW_RIGHT:
        return alt_left_down_ && !control_left_down_ && !shift_left_down_;
      case ui::DomCode::TAB:
        return control_left_down_ && !alt_left_down_;
      case ui::DomCode::CONTROL_LEFT:
      case ui::DomCode::SHIFT_LEFT:
      case ui::DomCode::ALT_LEFT:
        return true;
      default:
        NOTREACHED();
    }
  }

  bool* GetKeyStateLocked(ui::DomCode physical_key)
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    switch (physical_key) {
      case ui::DomCode::CONTROL_LEFT:
        return &control_left_down_;
      case ui::DomCode::SHIFT_LEFT:
        return &shift_left_down_;
      case ui::DomCode::ALT_LEFT:
        return &alt_left_down_;
      case ui::DomCode::US_L:
        return &key_l_down_;
      case ui::DomCode::US_R:
        return &key_r_down_;
      case ui::DomCode::ARROW_LEFT:
        return &arrow_left_down_;
      case ui::DomCode::ARROW_RIGHT:
        return &arrow_right_down_;
      case ui::DomCode::TAB:
        return &tab_down_;
      default:
        NOTREACHED();
    }
  }

  const bool* GetKeyStateLocked(ui::DomCode physical_key) const
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    return const_cast<WasmBrowserHostInputState*>(this)->GetKeyStateLocked(
        physical_key);
  }

  void ResetKeyStateLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    control_left_down_ = false;
    shift_left_down_ = false;
    alt_left_down_ = false;
    key_l_down_ = false;
    key_r_down_ = false;
    arrow_left_down_ = false;
    arrow_right_down_ = false;
    tab_down_ = false;
  }

  bool IsCurrentGeneration(uint64_t generation) const {
    base::AutoLock lock(lock_);
    return accepting_host_input_ && generation == generation_;
  }

  void DispatchKeyOnUiThread(ui::DomCode physical_key,
                             bool down,
                             uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    if (!IsCurrentGeneration(generation) || !input_injector_) {
      return;
    }
    input_injector_->InjectKeyEvent(physical_key, down,
                                    /*suppress_auto_repeat=*/true);
  }

  void RunVerificationOnUiThread(uint64_t generation) {
    DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
    base::RepeatingCallback<bool()> verifier;
    {
      base::AutoLock lock(lock_);
      if (!accepting_host_input_ || generation != generation_ || !verifier_ ||
          !verified_callback_) {
        return;
      }
      verifier = verifier_;
    }

    if (!verifier.Run()) {
      return;
    }

    base::OnceClosure verified_callback;
    {
      base::AutoLock lock(lock_);
      if (!accepting_host_input_ || generation != generation_ || !verifier_ ||
          !verified_callback_) {
        return;
      }
      verifier_.Reset();
      verified_callback = std::move(verified_callback_);
    }
    std::move(verified_callback).Run();
  }

  mutable base::Lock lock_;
  scoped_refptr<base::SingleThreadTaskRunner> task_runner_
      GUARDED_BY(lock_);
  uint64_t generation_ GUARDED_BY(lock_) = 0;
  bool accepting_host_input_ GUARDED_BY(lock_) = false;
  bool control_left_down_ GUARDED_BY(lock_) = false;
  bool shift_left_down_ GUARDED_BY(lock_) = false;
  bool alt_left_down_ GUARDED_BY(lock_) = false;
  bool key_l_down_ GUARDED_BY(lock_) = false;
  bool key_r_down_ GUARDED_BY(lock_) = false;
  bool arrow_left_down_ GUARDED_BY(lock_) = false;
  bool arrow_right_down_ GUARDED_BY(lock_) = false;
  bool tab_down_ GUARDED_BY(lock_) = false;
  base::RepeatingCallback<bool()> verifier_ GUARDED_BY(lock_);
  base::OnceClosure verified_callback_ GUARDED_BY(lock_);
  std::unique_ptr<ui::SystemInputInjector> input_injector_;
};

WasmBrowserHostInputState& GetWasmBrowserHostInputState() {
  static base::NoDestructor<WasmBrowserHostInputState> state;
  return *state;
}

}  // namespace

bool InitializeWasmBrowserHostInput() {
  return GetWasmBrowserHostInputState().InitializeOnUiThread();
}

void ShutdownWasmBrowserHostInput() {
  GetWasmBrowserHostInputState().ShutdownOnUiThread();
}

void SetWasmBrowserHostAcceleratorVerificationForTesting(
    base::RepeatingCallback<bool()> verifier,
    base::OnceClosure verified_callback) {
  GetWasmBrowserHostInputState().SetVerificationOnUiThread(
      std::move(verifier), std::move(verified_callback));
}

void ClearWasmBrowserHostAcceleratorVerificationForTesting() {
  GetWasmBrowserHostInputState().ClearVerificationOnUiThread();
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_key(const char* code,
                                                        int down) {
  if (!code || (down != 0 && down != 1)) {
    return 0;
  }

  const size_t length = strnlen(code, kMaximumHostDomCodeLength + 1);
  if (length == 0 || length > kMaximumHostDomCodeLength) {
    return 0;
  }

  ui::DomCode physical_key;
  if (!ParseWasmBrowserHostDomCode(std::string_view(code, length),
                                   &physical_key)) {
    return 0;
  }
  return GetWasmBrowserHostInputState().PostKey(physical_key, down == 1)
             ? 1
             : 0;
}

EMSCRIPTEN_KEEPALIVE int chromium_wasm_browser_host_accelerator_check() {
  return GetWasmBrowserHostInputState().PostVerificationCheck() ? 1 : 0;
}

}  // extern "C"

}  // namespace chrome
